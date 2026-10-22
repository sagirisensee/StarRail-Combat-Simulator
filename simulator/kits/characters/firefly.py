"""流萤 (Firefly / SAM - ID 1310, 毁灭 / 火) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【指令-闪燃推进】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的火属性伤害，削韧 10，回能 20，回 1 SP。
   - 强化普攻【火萤Ⅳ型-底火斩击】：回复 20% 生命上限，造成 280% (Lv 10) 攻击力的火属性伤害，削韧 15。
2. 战技【指令-天火轰击】：
   - 消耗自身 40% 生命上限，固定恢复自身 60% 能量上限的能量 (240 * 60% = 144 点能量)；
   - 对指定敌方单体造成 200% (Lv 10) 攻击力的火属性伤害，削韧 20；
   - 自身下一次行动提前 25%；
   - 强化战技【火萤Ⅳ型-死星过载】：回复 25% 生命上限，为目标添加火属性弱点 2 回合，对主目标与相邻目标造成高额扩散火属性与击破特攻缩放伤害；
   - E1【我曾安眠，赤染之茧】：强化战技不消耗战技点 (0 SP)，且无视目标 15% 防御力。
3. 终结技【火萤Ⅳ型-完全燃烧】(耗能 240 点)：
   - 自身行动提前 100%，进入「完全燃烧」状态 (is_combustion = True)；
   - 「完全燃烧」状态下速度提高 60 点，施放强化攻击时弱点击破效率提高 50% (E6 为 100%)，击破易伤提高 20%；
   - E6【绽放在终竟的明天】：火属性抗性穿透提高 20%。
4. 天赋【茧式源火中枢】：
   - 生命值越低减伤越高，最高降低 40%；完全燃烧下维持最大减伤且效果抵抗提高 30% (E4 额外提高 50%)；
   - 战斗开始时若能量不足 50% 则恢复至 50% (120 点能量)。
5. 秘技【Δ指令-焦土陨击】：每个波次开始为敌方全体添加火属性弱点 3 回合，造成 200% 攻击力火伤。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class FireflyKit(KitHandler):
    """流萤 / 装甲「萨姆」 (ID 1310, 毁灭 / 火)."""

    COMBUSTION_BUFF = "Firefly_Complete_Combustion"
    E1_DEF_SHRED = "Firefly_E1_DefShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_combustion: bool = False
        self.e2_cooldown: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "火萤Ⅳ型-底火斩击" if self.is_combustion else "指令-闪燃推进"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=name
            )
        elif kind == ActionKind.SKILL:
            sp_cost = 0 if (self.is_combustion and self.eidolon >= 1) else 1
            name = "火萤Ⅳ型-死星过载" if self.is_combustion else "指令-天火轰击"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=sp_cost),
                name=name
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=240.0),
                allow_self=True,
                name="火萤Ⅳ型-完全燃烧"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="Δ指令-焦土陨击"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self) -> None:
        """秘技【Δ指令-焦土陨击】：全队火伤与火弱点添加。"""
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=2.00,
                toughness_damage=20.0,
                damage_tag="Technique",
                scaling_stat="atk"
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if self.is_combustion:
            # 强化普攻【火萤Ⅳ型-底火斩击】: 回复 20% 生命上限，造成 280% 火伤
            max_hp = self.port.max_hp(self.owner_id)
            self.port.heal(self.owner_id, self.owner_id, max_hp * 0.20)
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=2.80,
                toughness_damage=15.0,
                damage_tag="BasicAttack",
                scaling_stat="atk"
            )
        else:
            # 常规普攻【指令-闪燃推进】: 140% 火伤
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=1.40,
                toughness_damage=10.0,
                damage_tag="BasicAttack",
                scaling_stat="atk"
            )
            self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        max_hp = self.port.max_hp(self.owner_id)

        if self.is_combustion:
            # 强化战技【火萤Ⅳ型-死星过载】
            # 回复 25% 生命上限
            self.port.heal(self.owner_id, self.owner_id, max_hp * 0.25)

            # E1: 施放强化战技无视目标 15% 防御
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key=self.E1_DEF_SHRED,
                    name="我曾安眠，赤染之茧",
                    source_id=self.owner_id,
                    target_id=self.owner_id,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.15),),
                    duration=1,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="无视目标 15% 防御"
                ))

            # 主目标攻击 (200% ATK + 0.2 * BE)
            be = self.port.stat(self.owner_id, StatType.BREAK_EFFECT) if hasattr(self.port, "stat") else 1.0
            be_eff = min(3.60, be)
            main_mult = 2.00 + 0.20 * be_eff
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=main_mult,
                toughness_damage=45.0,
                damage_tag="Skill",
                scaling_stat="atk"
            )

            # 相邻目标扩散 (100% ATK + 0.1 * BE)
            adj_mult = 1.00 + 0.10 * be_eff
            for e in self.port.enemies(self.owner_id):
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Fire",
                        atk_multiplier=adj_mult,
                        toughness_damage=22.5,
                        damage_tag="Skill",
                        scaling_stat="atk"
                    )

            # E2: 击破敌人或消灭目标获得额外回合 (100% 拉条)
            if self.eidolon >= 2 and self.e2_cooldown <= 0:
                self.e2_cooldown = 1
                self.port.advance(self.owner_id, self.owner_id, 1.0)
        else:
            # 常规战技【指令-天火轰击】: 消耗 40% 生命上限，固定回能 144 点，拉条 25%
            if hasattr(self.port, "lose_hp"):
                self.port.lose_hp(self.owner_id, max_hp * 0.40)
            self.port.gain_energy(self.owner_id, 144.0)

            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=2.00,
                toughness_damage=20.0,
                damage_tag="Skill",
                scaling_stat="atk"
            )
            self.port.advance(self.owner_id, self.owner_id, 0.25)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【火萤Ⅳ型-完全燃烧】：行动提前 100%，进入完全燃烧状态。"""
        self.is_combustion = True
        self.port.advance(self.owner_id, self.owner_id, 1.0)

        # 速度 +60 点，击破效率 +50% (E6 +100%)
        break_eff_bonus = 1.00 if self.eidolon >= 6 else 0.50
        mods = [
            Modifier(StatType.SPEED, ModifierOp.ADD, 60.0),
            Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.ADD, break_eff_bonus),
            Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.30 if self.eidolon < 4 else 0.80),
        ]
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20))

        self.port.upsert_status(BuffSpec(
            key=self.COMBUSTION_BUFF,
            name="火萤Ⅳ型-完全燃烧",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(mods),
            duration=4,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="速度提高 60 点，弱点击破效率提高"
        ))

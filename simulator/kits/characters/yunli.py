"""云璃 (Yunli - ID 1221, 毁灭 / 物理) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【翻风转日】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的单体物理伤害，削韧 10，回能 20，回 1 SP。
2. 战技【飞铗震赫】：
   - 消耗 1 点 SP，回复等同于自身 30% (Lv 10) 攻击力 + 200 的生命值；
   - 对指定敌方单体造成 120% (Lv 10) 攻击力的物理伤害，对其相邻目标造成 60% (Lv 10) 攻击力的物理伤害；削韧 20/10，回能 30 点。
3. 终结技【剑为地纪，刃惊天宗】(耗能 120 点，能量上限储蓄 240 点)：
   - 获得【格挡】架势 (is_parrying = True)，使敌方全体陷入嘲讽；
   - 下一次反击暴击伤害提高 100% (Lv 10)；
   - 受击触发强化反击【勘破•灭】：造成 220% 主目标 / 110% 相邻伤害，随后造成 6 次 (E1 为 9 次) 随机单体 72% 伤害；
   - 未受击结束时发动【勘破•斩】：造成 220% 主目标 / 110% 相邻伤害；
   - 反击造成的伤害均视为终结技伤害。
4. 天赋【闪铄】：受到攻击后额外恢复 15 点能量，并向攻击者发起普通反击，造成 120% 主目标 / 60% 相邻伤害。
5. 秘技【后发先至】：进战立即对随机敌方单体施放【勘破•灭】。
6. 星魂：
   - E1【沉锋离垢】：【勘破•斩】与【勘破•灭】伤害提高 20%，【勘破•灭】额外伤害次数增加 3 次；
   - E2【初芒破生】：发动反击造成伤害时无视目标 20% 防御力；
   - E4【大匠击橐】：发动反击后效果抵抗提高 50%，持续 1 回合；
   - E6【剑胆琴心】：暴击率提高 15%，物理属性抗性穿透提高 20%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType, FollowUpPhase,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class YunliKit(KitHandler):
    """云璃 (ID 1221, 毁灭 / 物理)."""
    follow_up_phase = FollowUpPhase.COUNTER

    PARRY_BUFF = "Yunli_Parry_Stance"
    E4_RES_BUFF = "Yunli_E4_EffectRes"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_parrying: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="翻风转日"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="飞铗震赫"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=120.0),
                allow_self=True,
                name="剑为地纪，刃惊天宗"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="后发先至"
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
        """秘技【后发先至】：进战施放【勘破•灭】。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.trigger_counter(enemies[0])

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【翻风转日】：单体物理伤害，140% (Lv 10) 攻击力。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【飞铗震赫】：自愈并扩散物理伤害 (120% / 60%)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        atk_val = self.port.stat(self.owner_id, StatType.ATK_BASE) if hasattr(self.port, "stat") else 1000.0
        heal_val = atk_val * 0.30 + 200.0
        self.port.heal(self.owner_id, self.owner_id, heal_val)

        mult_main = self.skill_param("skill", 0, default=1.20)
        mult_adj = self.skill_param("skill", 1, default=0.60)

        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=mult_main,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL,
            scaling_stat="atk"
        )

        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Physical",
                    atk_multiplier=mult_adj,
                    toughness_damage=10.0,
                    damage_type=DamageType.SKILL,
                    scaling_stat="atk"
                )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【剑为地纪，刃惊天宗】：进入格挡架势，暴伤提高 100%。"""
        self.is_parrying = True

        mods = [Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 1.00)]
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15))
            mods.append(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20))

        self.port.upsert_status(BuffSpec(
            key=self.PARRY_BUFF,
            name="剑为地纪，刃惊天宗 (格挡)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(mods),
            duration=1,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="暴击伤害提高 +100.0%"
        ))

    def trigger_counter(self, attacker_id: str) -> None:
        """受到攻击或格挡结算时触发反击。"""
        enemies = self.port.enemies(self.owner_id)
        target_id = attacker_id if attacker_id in enemies else (enemies[0] if enemies else "")
        if not target_id:
            return

        is_cull = self.is_parrying
        self.is_parrying = False

        # E2: 发动反击造成伤害时无视目标 20% 防御力
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key="Yunli_E2_DefShred",
                name="初芒破生",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="无视目标 20% 防御力"
            ))

        if is_cull:
            # 强化反击【勘破•灭】
            dmg_boost = 1.20 if self.eidolon >= 1 else 1.00
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=2.20 * dmg_boost,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="atk"
            )
            for e in enemies:
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Physical",
                        atk_multiplier=1.10 * dmg_boost,
                        toughness_damage=10.0,
                        damage_type=DamageType.ULTIMATE,
                        scaling_stat="atk"
                    )

            # 额外伤害段数：基础 6 次 (E1 为 9 次)
            extra_hits = 9 if self.eidolon >= 1 else 6
            for _ in range(extra_hits):
                self.port.attack(
                    self.owner_id,
                    target_id,
                    element="Physical",
                    atk_multiplier=0.72 * dmg_boost,
                    toughness_damage=5.0,
                    damage_type=DamageType.ULTIMATE,
                    scaling_stat="atk"
                )
        else:
            # 普通反击【闪铄】: 120% 主目标 / 60% 扩散，恢复 15 点能量
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=1.20,
                toughness_damage=10.0,
                damage_type=DamageType.FOLLOW_UP,
                scaling_stat="atk"
            )
            for e in enemies:
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Physical",
                        atk_multiplier=0.60,
                        toughness_damage=5.0,
                        damage_type=DamageType.FOLLOW_UP,
                        scaling_stat="atk"
                    )
            self.port.gain_energy(self.owner_id, 15.0)

        # E4: 效果抵抗提高 50%
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=self.E4_RES_BUFF,
                name="大匠击橐",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.50),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="效果抵抗提高 +50.0%"
            ))

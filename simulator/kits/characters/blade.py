"""刃 (Blade - ID 1205, 毁灭 / 风) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【支离剑】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的风属性伤害，削韧 10，回能 20，回 1 SP。
   - 强化普攻【无间剑树】：消耗自身 10% 生命上限，对指定单体造成 56% 攻击力 + 140% (Lv 10) 生命上限的风伤，对其相邻目标造成 22.4% 攻击力 + 56% (Lv 10) 生命上限的风伤；削韧 20/10，回能 30 点，不消耗也不恢复 SP。
2. 战技【地狱变】：
   - 消耗自身 30% 生命上限，进入【地狱变】状态 (Blade_Hellscape)，造成的伤害提高 40% (Lv 10)；
   - 普攻强化为【无间剑树】，持续 3 回合；施放后本回合不结束 (100% 自拉条)；消耗 1 点 SP，不恢复能量。
3. 终结技【大辟万死】(耗能 130 点)：
   - 当前生命值转化为生命上限 50%；
   - 对单体造成 40% 攻击力 + 100% (Lv 10) 生命上限 + 100% (Lv 10) 累计已损失生命值的风伤；
   - 对相邻目标造成 16% 攻击力 + 40% (Lv 10) 生命上限 + 40% (Lv 10) 累计已损失生命值的风伤；
   - 累计已损失生命值上限为 90% 生命上限，施放后重置；回能 5 点。
4. 天赋【倏忽恩赐】：
   - 受到伤害或消耗生命时获得 1 层充能 (上限 5 层，E6 降低至 4 层)；
   - 叠满时对全体施放追加攻击，造成 44% 攻击力 + 110% (Lv 10) 生命上限的风伤，并回复自身 25% 生命上限；削韧 10，回能 10 点；
   - E1【剑录大限，地狱变相】：终结技对单体伤害额外提高累计已损失生命值的 150%；
   - E2【支离旧梦，万端遗恨】：【地狱变】期间暴击率提高 15%；
   - E4【泉台歧路，百骸回春】：生命从 >50% 降至 <=50% 时生命上限提高 20%，可叠 2 层 (40%)；
   - E6【命留魂销，复返此身】：充能上限降至 4 层，追加攻击额外附加 50% 生命上限伤害。
5. 秘技【业途风】：消耗 20% 生命上限，对全体造成 40% 生命上限的风伤。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class BladeKit(KitHandler):
    """刃 (ID 1205, 毁灭 / 风)."""

    HELLSCAPE_BUFF = "Blade_Hellscape"
    E2_CRIT_BUFF = "Blade_E2_Crit"
    E4_HP_BUFF = "Blade_E4_MaxHp"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_enhanced_basic: bool = False
        self.charge: int = 0
        self.max_charge: int = 4 if eidolon >= 6 else 5
        self.accumulated_hp_loss: float = 0.0

    @property
    def is_enhanced(self) -> bool:
        return self.is_enhanced_basic

    def add_charge(self, amount: int = 1) -> None:
        """增加充能层数并在达到上限时触发追加攻击。"""
        self.charge = min(self.max_charge, self.charge + amount)
        if self.charge >= self.max_charge:
            self._trigger_follow_up()

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "无间剑树" if self.is_enhanced_basic else "支离剑"
            sp_cost = 0 if self.is_enhanced_basic else -1
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=sp_cost),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="地狱变"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=130.0),
                name="大辟万死"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="业途风"
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
        """秘技【业途风】：进战全体风伤。"""
        max_hp = self.port.max_hp(self.owner_id)
        if hasattr(self.port, "lose_hp"):
            self.port.lose_hp(self.owner_id, max_hp * 0.20)
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Wind",
                atk_multiplier=0.40,
                toughness_damage=20.0,
                damage_tag="Technique",
                scaling_stat="hp"
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        max_hp = self.port.max_hp(self.owner_id)

        if self.is_enhanced_basic:
            # 强化普攻【无间剑树】：消耗 10% 生命上限
            hp_cost = max_hp * 0.10
            if hasattr(self.port, "lose_hp"):
                self.port.lose_hp(self.owner_id, hp_cost)
            self._add_charge()
            self.accumulated_hp_loss += hp_cost

            # 主目标攻击 (56% ATK + 140% HP)
            self.port.attack(
                self.owner_id,
                target_id,
                element="Wind",
                atk_multiplier=1.40,
                toughness_damage=20.0,
                damage_tag="BasicAttack",
                scaling_stat="hp"
            )

            # 相邻目标扩散 (22.4% ATK + 56% HP)
            for e in self.port.enemies(self.owner_id):
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Wind",
                        atk_multiplier=0.56,
                        toughness_damage=10.0,
                        damage_tag="BasicAttack",
                        scaling_stat="hp"
                    )

            self.port.gain_energy(self.owner_id, 30.0)
        else:
            # 常规普攻【支离剑】：140% 攻击力
            self.port.attack(
                self.owner_id,
                target_id,
                element="Wind",
                atk_multiplier=1.40,
                toughness_damage=10.0,
                damage_tag="BasicAttack",
                scaling_stat="atk"
            )
            self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【地狱变】：消耗 30% 生命上限，增伤 40%，强化普攻 3 回合，不结束回合。"""
        max_hp = self.port.max_hp(self.owner_id)
        hp_cost = max_hp * 0.30
        if hasattr(self.port, "lose_hp"):
            self.port.lose_hp(self.owner_id, hp_cost)
        self._add_charge()
        self.accumulated_hp_loss += hp_cost

        self.is_enhanced_basic = True

        mods = [Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.40)]
        if self.eidolon >= 2:
            mods.append(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15))

        self.port.upsert_status(BuffSpec(
            key=self.HELLSCAPE_BUFF,
            name="地狱变",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(mods),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="造成的伤害提高 +40.0%"
        ))

        # 施放该战技后，本回合不会结束 (100% 自拉条)
        self.port.advance(self.owner_id, self.owner_id, 1.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【大辟万死】：生命重置为 50%，扩散风伤。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        max_hp = self.port.max_hp(self.owner_id)

        # 累计已损失生命值 (上限 90% 生命上限)
        loss_val = min(max_hp * 0.90, self.accumulated_hp_loss)
        self.accumulated_hp_loss = 0.0

        # 主目标基础倍率 100% HP (E1 额外提高 150% 累计损失)
        e1_mult = (loss_val / max_hp) * 1.50 if self.eidolon >= 1 else 0.0
        main_mult = 1.00 + (loss_val / max_hp) * 1.00 + e1_mult

        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=main_mult,
            toughness_damage=20.0,
            damage_tag="Ultimate",
            scaling_stat="hp"
        )

        # 相邻目标扩散 40% HP + 40% 损失
        adj_mult = 0.40 + (loss_val / max_hp) * 0.40
        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Wind",
                    atk_multiplier=adj_mult,
                    toughness_damage=10.0,
                    damage_tag="Ultimate",
                    scaling_stat="hp"
                )

        self.port.gain_energy(self.owner_id, 5.0)

    def _add_charge(self) -> None:
        """受到伤害或消耗生命时累积充能。"""
        self.charge += 1
        if self.charge >= self.max_charge:
            self._trigger_follow_up()

    def _trigger_follow_up(self) -> None:
        """天赋追加攻击【倏忽恩赐】：全体 110% 生命上限风伤并回复 25% 生命。"""
        self.charge = 0
        max_hp = self.port.max_hp(self.owner_id)
        self.port.heal(self.owner_id, self.owner_id, max_hp * 0.25)

        base_mult = 1.10
        if self.eidolon >= 6:
            base_mult += 0.50

        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Wind",
                atk_multiplier=base_mult,
                toughness_damage=10.0,
                damage_tag="FollowUpAttack",
                scaling_stat="hp"
            )

        self.port.gain_energy(self.owner_id, 10.0)

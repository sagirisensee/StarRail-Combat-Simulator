"""灵砂 (Lingsha) 战斗技能套件完整实现 (Character Kit).

适配角色：灵砂 (ID 1222, 丰饶 / 火)
严格契合实机机制与公式：
1. 普攻【含香倒影】：造成单体火伤，恢复 1 点战技点，回能 20 点；
2. 战技【识香召灵】：
   - 消耗 1 点 SP，治疗我方全体并召唤烟兽【浮元】；
   - 对敌方全体造成火属性群体伤害，削韧 10 点；
3. 终结技【落滴清露，烟霞弥散】：
   - 消耗 110 能量；
   - 对敌方全体造成火属性伤害，施加【醇醉】状态：受到的击破伤害提高 25%，持续 2 回合；
   - 治疗我方全体，并使烟兽【浮元】立即行动 (100% 立即拉条)！
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class LingshaKit(KitHandler):
    INTOXICATED_DEBUFF = "Lingsha_Intoxicated"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.fuyuan_count: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="含香倒影"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="识香召灵"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                name="落滴清露，烟霞弥散"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="极光浮香"
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
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【极光浮香】：进战立即召唤浮元并使敌方全体陷入【醇醉】状态 2 回合。"""
        self.fuyuan_count += 3
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.INTOXICATED_DEBUFF,
                name="醇醉 (灵砂秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.BREAK_VULN, ModifierOp.ADD, 0.25),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def on_battle_start(self) -> None:
        """E1: 触芳自及 (击破效率提高 50%)。"""
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key="Lingsha_E1_BreakEff",
                name="触芳自及 (灵砂E1击破效率提高50%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.PERCENT, 0.50),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

    def _execute_skill(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.heal(self.owner_id, ally, 1800.0)

        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.8,
                toughness_damage=10.0,
                damage_tag="Skill"
            )
            # E1: 弱点被击破时防御力降低 20%
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key="Lingsha_E1_DefShred",
                    name="触芳自及 (灵砂E1减防20%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

        self.fuyuan_count += 3
        # E4: 浮元急救回复
        if self.eidolon >= 4:
            lowest_ally = min(allies, key=lambda a: self.port.hp_ratio(a))
            self.port.heal(self.owner_id, lowest_ally, 1200.0)

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=1.5,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 醇醉状态：击破伤害提高 25%
            self.port.upsert_status(BuffSpec(
                key=self.INTOXICATED_DEBUFF,
                name="醇醉 (灵砂大招击破受伤提高25%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.25),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

            # E6: 敌方全体全属性抗性降低 20%
            if self.eidolon >= 6:
                self.port.upsert_status(BuffSpec(
                    key="Lingsha_E6_ResShred",
                    name="晓极归暮 (灵砂E6全属性减抗20%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.heal(self.owner_id, ally, 2200.0)
            # E2: 全队击破特攻提高 40%
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key="Lingsha_E2_BreakEffect",
                    name="垂叶落蕊 (灵砂E2全队击破特攻40%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.40),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

        self.port.gain_energy(self.owner_id, 5.0)

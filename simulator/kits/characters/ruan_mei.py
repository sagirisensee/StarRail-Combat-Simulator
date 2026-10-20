"""阮•梅 (Ruan Mei) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 天赋【分襟聚袂】：战斗开局为除自身外的全队提供 10% 速度加成 (常驻)；
2. 战技【慢捻抹复挑】：消耗 1 点 SP，展开结界 3 回合，我方全体造成的伤害提高 32%，弱点击破效率提高 50%；
3. 终结技【摇落绫罗】：展开结界 2 回合，我方全体全属性抗性穿透提高 25%；
4. 【星魂 1 联动】：终结技结界生效期间，我方全体造成伤害时无视目标 20% 防御。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class RuanMeiKit(KitHandler):
    TALENT_SPEED_BUFF = "RuanMei_Talent_Speed"
    SKILL_BUFF = "RuanMei_Skill_Field"
    ULT_RES_PEN_BUFF = "RuanMei_Ult_ResPen"
    E1_DEF_SHRED_BUFF = "RuanMei_E1_DefShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 1,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="一针幽兰"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="慢捻抹复挑"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=130.0),
                allow_self=True,
                name="摇落绫罗"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """开局激活天赋：除自身外的队友全员提速 10% (常驻无衰减)。"""
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            if ally != self.owner_id:
                self.port.upsert_status(BuffSpec(
                    key=self.TALENT_SPEED_BUFF,
                    name="分襟聚袂 (阮•梅天赋全队提速)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                    duration=None,  # 常驻光环
                    timing=DurationTiming.TARGET_TURN_END
                ))

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        # 结界持续 3 回合 (以阮梅自身回合为时钟)
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.upsert_status(BuffSpec(
                key=self.SKILL_BUFF,
                name="弦歌 (阮•梅战技增伤与击破效率)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(
                    Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.32),
                    Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.PERCENT, 0.50),
                ),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            # 全属性抗性穿透提高 25%
            self.port.upsert_status(BuffSpec(
                key=self.ULT_RES_PEN_BUFF,
                name="清馨生韵 (阮•梅大招全属性抗穿)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.25),),
                duration=2,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

            # E1: 结界期间造成伤害无视 20% 防御
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key=self.E1_DEF_SHRED_BUFF,
                    name="重叠的弦管 (阮•梅E1无视20%防御)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                    duration=2,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True
                ))
        self.port.gain_energy(self.owner_id, 5.0)

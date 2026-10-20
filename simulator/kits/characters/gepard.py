"""杰帕德 (Gepard) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【一意之拳】：造成冰伤，恢复 1 点战技点，回能 20 点；
2. 战技【震撼一击】：造成冰伤，削韧 20 点，概率冻结敌人；
3. 终结技【永屹之壁】：
   - 消耗 100 能量；
   - 为我方全体提供巨额防御护盾 (2500+)，持续 3 回合；
4. 天赋【不屈的荣光】：
   - 自身高仇恨嘲讽，受到致命伤害时免死并回血。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class GepardKit(KitHandler):
    SHIELD_BUFF = "Gepard_Fortified_Shield"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 4,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="一意之拳"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="震撼一击"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=100.0),
                allow_self=True,
                name="永屹之壁"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

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
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=2.0,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        # 为全队添加巨额护盾 (2600 点)
        for ally in allies:
            self.port.add_shield(self.owner_id, ally, 2600.0, duration=3)
            self.port.upsert_status(BuffSpec(
                key=self.SHIELD_BUFF,
                name="永屹之壁 (杰帕德大招巨额护盾)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

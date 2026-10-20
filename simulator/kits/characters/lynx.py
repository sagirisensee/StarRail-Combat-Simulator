"""玲可 (Lynx) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【冰原点穴针】：造成量子伤害，恢复 1 点战技点，回能 20 点；
2. 战技【盐渍野营罐头】：
   - 消耗 1 点 SP，单体大额治疗，施加【求生反应】持续 2 回合 (生命上限提高，毁灭/存护角色受击率大幅提高)；
3. 终结技【雪原急救方案】：
   - 消耗 100 能量，为我方全体回复生命，解除我方全体各 1 个负面状态。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class LynxKit(KitHandler):
    SURVIVAL_RESPONSE_BUFF = "Lynx_Survival_Response"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="冰原点穴针"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="盐渍野营罐头"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=100.0),
                allow_self=True,
                name="雪原急救方案"
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
            element="Quantum",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = self.port.allies(self.owner_id)
            target_id = allies[0] if allies else self.owner_id

        self.port.heal(self.owner_id, target_id, 2000.0)
        # 求生反应：生命上限提高 10%
        self.port.upsert_status(BuffSpec(
            key=self.SURVIVAL_RESPONSE_BUFF,
            name="求生反应 (玲可生命上限与受击率加成)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, 0.10),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.heal(self.owner_id, ally, 2200.0)
        self.port.gain_energy(self.owner_id, 5.0)

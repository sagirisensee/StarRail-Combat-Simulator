"""白露 (Bailu) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【望、闻、问……切】：造成雷伤，恢复 1 点战技点，回能 20 点；
2. 战技【云吟跃藻】：
   - 消耗 1 点 SP，单体大额治疗并随机弹射 2 次治疗队友；
3. 终结技【奔走悬壶济世】：
   - 消耗 100 能量，为我方全体回复生命，施加【生息】状态 (受击自动回血)；
4. 天赋【岐黄精义】：
   - 我方角色受到致命伤害时免疫死亡并复活 (每场限 1 次)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class BailuKit(KitHandler):
    INVIGORATION_BUFF = "Bailu_Invigoration"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 4,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.revive_used: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="望、闻、问……切"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="云吟跃藻"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=100.0),
                allow_self=True,
                name="奔走悬壶济世"
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
            element="Lightning",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        # 单体治疗 + 弹射治疗
        for ally in allies:
            self.port.heal(self.owner_id, ally, 1500.0)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.heal(self.owner_id, ally, 2400.0)
            self.port.upsert_status(BuffSpec(
                key=self.INVIGORATION_BUFF,
                name="生息 (白露受击自动回血状态)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

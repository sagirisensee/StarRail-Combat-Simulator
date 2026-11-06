from dataclasses import dataclass


@dataclass(frozen=True)
class EnemyActionCompleted:
    """一次敌方自然行动的效果已经完整结算。"""

    action_id: str
    actor_id: str


@dataclass(frozen=True)
class FriendlyHitResolved:
    """我方对某目标的一次有效命中已完成伤害结算。"""

    action_id: str
    hit_id: str
    source_id: str
    target_id: str

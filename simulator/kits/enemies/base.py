from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .port import EnemyCombatPort


STANDARD_ACTION_DISTANCE = 10000.0


@dataclass(frozen=True)
class EnemyActionContext:
    """一次已获准执行的敌方自然行动。"""

    action_id: str
    actor_id: str


@dataclass(frozen=True)
class EnemyActionResult:
    """仅描述本次行动的收尾结果，不直接修改实体跑道。"""

    reset_distance: float = STANDARD_ACTION_DISTANCE

    def __post_init__(self) -> None:
        if not math.isfinite(self.reset_distance) or self.reset_distance < 0.0:
            raise ValueError("reset_distance must be finite and non-negative")


class EnemyKit(ABC):
    """敌方专属 Kit 基类，独立于角色 KitHandler。"""

    def __init__(
        self,
        owner_id: str,
        port: EnemyCombatPort,
    ) -> None:
        self.owner_id = owner_id
        self.port = port

    def on_battle_start(self) -> Optional[EnemyActionResult]:
        """战前开场机制。返回 None 不修改初始跑道，返回 EnemyActionResult 则应用指定跑道。"""
        return None

    @abstractmethod
    def execute_turn(
        self,
        ctx: EnemyActionContext,
    ) -> EnemyActionResult:
        """实际执行自然行动时调用。"""
        raise NotImplementedError

    def on_event(self, event: Any) -> None:
        pass

    def intercept_incoming_damage(
        self,
        target_id: str,
        raw_damage: float,
    ) -> float:
        return raw_damage

    def on_battle_end(self) -> None:
        pass

    def get_kit_state(self) -> dict[str, Any]:
        return {}

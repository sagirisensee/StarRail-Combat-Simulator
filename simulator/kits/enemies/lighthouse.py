from __future__ import annotations

from typing import Any, Optional, Tuple

from .base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from .events import EnemyActionCompleted, FriendlyHitResolved
from .port import EnemyCombatPort


class LighthouseBossKit(EnemyKit):
    """灯塔首领机制 Kit。

    机制状态全部由 Kit 独立持有：
    - 当前召唤代数 (generation)
    - 当前一组戍卫 ID (guard_ids)
    - 众愿层数 (wish_stacks, 上限 12 层，每层 5% 免伤)
    - 除恶状态 (in_chue)
    - 跑道动态控制 (开场/召唤 20000.0，常规 10000.0)
    """

    GUARD_COUNT = 3
    MAX_WISH_STACKS = 12
    REDUCTION_PER_STACK = 0.05

    SUMMON_ACTION_DISTANCE = 20000.0
    NORMAL_ACTION_DISTANCE = STANDARD_ACTION_DISTANCE

    def __init__(
        self,
        owner_id: str,
        port: EnemyCombatPort,
        ally_ids: Tuple[str, ...] = (),
    ) -> None:
        super().__init__(owner_id, port)
        self._started = False
        self._active = False
        self._generation = 0
        self._guard_ids: Tuple[str, ...] = ()
        self._ally_ids: Tuple[str, ...] = tuple(ally_ids)
        self._wish_stacks = 0
        self._in_chue = False
        self._toughness_locked = False
        self._last_action_was_summon = False

    @property
    def wish_stacks(self) -> int:
        return self._wish_stacks

    @property
    def guard_ids(self) -> Tuple[str, ...]:
        return self._guard_ids

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def in_chue(self) -> bool:
        return self._in_chue

    @property
    def toughness_locked(self) -> bool:
        return self._toughness_locked and self._wish_stacks > 0

    @property
    def damage_reduction(self) -> float:
        return self._wish_stacks * self.REDUCTION_PER_STACK

    def on_battle_start(self) -> Optional[EnemyActionResult]:
        if self._started:
            return None
        if not self.port.is_alive(self.owner_id):
            raise RuntimeError("Lighthouse owner must be registered and alive before on_battle_start")

        self._toughness_locked = True
        self._summon_guards()
        self._started = True
        self._active = True
        self._last_action_was_summon = True

        return EnemyActionResult(reset_distance=self.SUMMON_ACTION_DISTANCE)

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        if ctx.actor_id != self.owner_id:
            raise ValueError(f"Actor mismatch: {ctx.actor_id!r} != {self.owner_id!r}")
        if not self._started:
            self.on_battle_start()
            return EnemyActionResult(reset_distance=self.SUMMON_ACTION_DISTANCE)
        if not self.port.is_alive(self.owner_id):
            raise RuntimeError("Dead Lighthouse cannot act")

        # 官方首领机制: 召唤与常规攻击严格交替进行
        # 召唤/除恶状态后下一次为常规行动 (距离 10000.0 / 耗时 52.61 AV)
        # 常规行动后下一次为重召/复活戍卫并重置众愿 (距离 20000.0 / 耗时 105.22 AV)
        if not self._last_action_was_summon:
            self._toughness_locked = True
            self._summon_guards()
            self._last_action_was_summon = True
            return EnemyActionResult(reset_distance=self.SUMMON_ACTION_DISTANCE)

        self.port.execute_lighthouse_regular_action(
            owner_id=self.owner_id,
            action_id=ctx.action_id,
        )
        self._in_chue = False
        self._toughness_locked = False
        self._set_wish_stacks(0)
        self._last_action_was_summon = False
        return EnemyActionResult(reset_distance=self.NORMAL_ACTION_DISTANCE)

    def on_event(self, event: Any) -> None:
        if not self._active or not self._in_chue or not self.port.is_alive(self.owner_id):
            return

        if isinstance(event, EnemyActionCompleted):
            if event.actor_id in self._guard_ids or event.actor_id in self._ally_ids:
                self._set_wish_stacks(self._wish_stacks + 1)
            return

        if isinstance(event, FriendlyHitResolved):
            if event.target_id == self.owner_id:
                self._set_wish_stacks(self._wish_stacks - 1)

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
        if target_id != self.owner_id or not self._active:
            return raw_damage
        if getattr(self.port, "handles_damage_reduction", False):
            return raw_damage
        return raw_damage * (1.0 - self.damage_reduction)

    def on_battle_end(self) -> None:
        self._active = False
        self._in_chue = False
        self._wish_stacks = 0

    def get_kit_state(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "active": self._active,
            "generation": self._generation,
            "guard_ids": list(self._guard_ids),
            "living_guard_ids": [eid for eid in self._guard_ids if self.port.is_alive(eid)],
            "wish_stacks": self._wish_stacks,
            "damage_reduction": self.damage_reduction,
            "in_chue": self._in_chue,
        }

    def _has_living_guard(self) -> bool:
        return any(self.port.is_alive(eid) for eid in self._guard_ids)

    def _set_wish_stacks(self, value: int) -> None:
        self._wish_stacks = max(0, min(self.MAX_WISH_STACKS, value))
        if hasattr(self.port, "on_wish_stacks_changed"):
            self.port.on_wish_stacks_changed(self._wish_stacks, self._in_chue)

    def _summon_guards(self) -> None:
        next_generation = self._generation + 1
        new_ids = tuple(
            self.port.summon_lighthouse_guards(
                owner_id=self.owner_id,
                generation=next_generation,
                count=self.GUARD_COUNT,
            )
        )
        if len(new_ids) != self.GUARD_COUNT:
            raise RuntimeError("Expected exactly three Lighthouse guards")
        if len(set(new_ids)) != self.GUARD_COUNT:
            raise RuntimeError("Guard IDs must be unique")
        if self.owner_id in new_ids:
            raise RuntimeError("Lighthouse cannot be its own guard")
        if not all(self.port.is_alive(eid) for eid in new_ids):
            raise RuntimeError("All summoned guards must be alive")

        self._generation = next_generation
        self._guard_ids = new_ids
        self._in_chue = True
        self._set_wish_stacks(self.MAX_WISH_STACKS)

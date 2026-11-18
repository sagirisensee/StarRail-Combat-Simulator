from __future__ import annotations

from typing import Any

from .base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from .port import EagleCombatPort


class MeteorEagleKit(EnemyKit):
    """流星铁鹰 (4022010) 专属机制 Kit。

    核心机制 (对齐实机日志 battle_20261114_155925.jsonl 69.44 / 92.17 / 114.90 x2 AV):
    - 常规行动对指定我方目标发动风属性攻击；
    - 【如流星闪耀 / 风行】：当 `windwalk_ready=True` 时，本次行动结束后跑道归零 (`reset_distance=0.0`)，
      立即获得一次额外再动并消耗该状态（对应日志 100021 在 114.90 AV 的双连动）。
    """

    ENEMY_ID = 4022010

    def __init__(
        self,
        owner_id: str,
        port: EagleCombatPort,
        *,
        windwalk_ready: bool = False,
        windwalk_target: str | None = None,
    ) -> None:
        super().__init__(owner_id, port)
        self._windwalk_ready = windwalk_ready
        self._windwalk_target = windwalk_target
        self._turn_count = 0

    @property
    def windwalk_ready(self) -> bool:
        return self._windwalk_ready

    @windwalk_ready.setter
    def windwalk_ready(self, value: bool) -> None:
        self._windwalk_ready = bool(value)

    @property
    def turn_count(self) -> int:
        return self._turn_count

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        if ctx.actor_id != self.owner_id:
            raise ValueError(f"Actor mismatch: {ctx.actor_id!r} != {self.owner_id!r}")
        if not self.port.is_alive(self.owner_id):
            raise RuntimeError("Dead MeteorEagle cannot act")

        self._turn_count += 1
        if self._windwalk_target:
            target_name = self._windwalk_target
            self._windwalk_target = None
            sim = getattr(self.port, "sim", None)
            target_ent = sim.get_entity(target_name) if sim is not None else None
            target_kit = getattr(target_ent, "kit", None) if target_ent is not None else None
            if target_kit is not None and hasattr(target_kit, "windwalk_ready"):
                target_kit.windwalk_ready = True
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

        allies = self.port.get_living_allies()
        if allies:
            target = allies[0]
            self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=(target,),
                multiplier=2.0,
                element="Wind",
                hit_energy=5.0,
                hits=1,
            )

        if self._windwalk_ready:
            self._windwalk_ready = False
            return EnemyActionResult(reset_distance=0.0)

        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def get_kit_state(self) -> dict[str, Any]:
        return {
            "turn_count": self._turn_count,
            "windwalk_ready": self._windwalk_ready,
        }

from __future__ import annotations

from typing import Any, Optional, Tuple

from .base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from .port import PegasusCombatPort


ORONYX_MARK_KEY = "Enemy_Oronyx_Mark"
ORONYX_MARK_NAME = "欧洛尼斯印记"


class MoonlitPegasusKit(EnemyKit):
    """月夜天马 (4023020) 专属机制 Kit。

    核心机制 (对齐实机日志 battle_20261114_155925.jsonl 75.76 / 151.52 / 227.27 AV 节拍):
    - 3 回合行动循环:
      - Turn 1: 单体攻击
      - Turn 2: 3 段扩散攻击并附加【欧洛尼斯印记】
      - Turn 3: 先单体再全体攻击，引爆仍持有【欧洛尼斯印记】的目标造成额外高额量子伤害后清除印记，并对未持有印记的目标附加印记
    - 我方目标施放终结技时，可主动消耗并清除自身的【欧洛尼斯印记】。
    """

    ENEMY_ID = 4023020

    def __init__(
        self,
        owner_id: str,
        port: PegasusCombatPort,
        *,
        windwalk_ready: bool = False,
    ) -> None:
        super().__init__(owner_id, port)
        self._turn_count = 0
        self._windwalk_ready = windwalk_ready

    @property
    def windwalk_ready(self) -> bool:
        return self._windwalk_ready

    @windwalk_ready.setter
    def windwalk_ready(self, value: bool) -> None:
        self._windwalk_ready = bool(value)

    @property
    def turn_count(self) -> int:
        return self._turn_count

    def _select_primary_target(self, allies: Tuple[str, ...]) -> str:
        return allies[0]

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        if ctx.actor_id != self.owner_id:
            raise ValueError(f"Actor mismatch: {ctx.actor_id!r} != {self.owner_id!r}")
        if not self.port.is_alive(self.owner_id):
            raise RuntimeError("Dead MoonlitPegasus cannot act")

        self._turn_count += 1
        allies = self.port.get_living_allies()
        if not allies:
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

        phase = (self._turn_count - 1) % 3
        if phase == 0:
            # Turn 1: 单体攻击 (Skill01 = 3.0)
            target = self._select_primary_target(allies)
            self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=(target,),
                multiplier=3.0,
                element="Quantum",
                hit_energy=5.0,
                hits=1,
            )
        elif phase == 1:
            # Turn 2: 3 段扩散攻击 (Skill04 = 4.5 -> 1.5 x 3) 并附加【欧洛尼斯印记】
            target = self._select_primary_target(allies)
            self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=(target,),
                multiplier=1.5,
                element="Quantum",
                hit_energy=20.0 / 3.0,
                hits=3,
                blast=True,
            )
            idx = allies.index(target)
            mark_targets = [target]
            if idx - 1 >= 0:
                mark_targets.append(allies[idx - 1])
            if idx + 1 < len(allies):
                mark_targets.append(allies[idx + 1])
            for mt in mark_targets:
                self.port.apply_mark_status(
                    owner_id=self.owner_id,
                    target_id=mt,
                    mark_key=ORONYX_MARK_KEY,
                    mark_name=ORONYX_MARK_NAME,
                    description="月夜天马附加的【欧洛尼斯印记】，施放终结技可解除，否则将在后续爆发结算额外伤害。",
                )
        else:
            # Turn 3: 先单体攻击 (Skill01 = 3.0, +5 回能)，再全体攻击 (Skill02 = 2.6, +10 回能) + 引爆【欧洛尼斯印记】
            target = self._select_primary_target(allies)
            self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=(target,),
                multiplier=3.0,
                element="Quantum",
                hit_energy=5.0,
                hits=1,
            )
            self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=allies,
                multiplier=2.6,
                element="Quantum",
                hit_energy=10.0,
                hits=1,
            )
            for target_id in allies:
                if self.port.has_mark_status(target_id=target_id, mark_key=ORONYX_MARK_KEY):
                    self.port.trigger_oronyx_detonation(
                        owner_id=self.owner_id,
                        target_id=target_id,
                        multiplier=6.27,
                        element="Quantum",
                    )
                    self.port.remove_mark_status(target_id=target_id, mark_key=ORONYX_MARK_KEY)
                else:
                    self.port.apply_mark_status(
                        owner_id=self.owner_id,
                        target_id=target_id,
                        mark_key=ORONYX_MARK_KEY,
                        mark_name=ORONYX_MARK_NAME,
                        description="月夜天马附加的【欧洛尼斯印记】，施放终结技可解除，否则将在后续爆发结算额外伤害。",
                    )

        if self._windwalk_ready:
            self._windwalk_ready = False
            return EnemyActionResult(reset_distance=0.0)

        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def on_event(self, event: Any) -> None:
        if not self.port.is_alive(self.owner_id):
            return
        # 我方施放终结技时清除自身【欧洛尼斯印记】
        action_kind = getattr(event, "action_kind", None)
        action_type = getattr(event, "action_type", "")
        actor_id = getattr(event, "actor_id", None)
        if not actor_id:
            return
        is_ult = (
            str(action_kind) == "ActionKind.ULTIMATE"
            or getattr(action_kind, "value", None) == "ULTIMATE"
            or "终结技" in str(action_type)
        )
        if is_ult:
            self.port.remove_mark_status(target_id=actor_id, mark_key=ORONYX_MARK_KEY)

    def get_kit_state(self) -> dict[str, Any]:
        return {"turn_count": self._turn_count}

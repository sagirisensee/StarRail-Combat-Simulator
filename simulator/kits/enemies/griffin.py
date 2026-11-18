from __future__ import annotations

from typing import Any, Optional, Tuple

from .base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from .port import GriffinCombatPort


AQUILA_MARK_KEY = "Enemy_Aquila_Mark"
AQUILA_MARK_NAME = "艾格勒印记"


class SunlitGriffinKit(EnemyKit):
    """正阳狮鹫专属机制 Kit。

    核心机制 (对齐实机日志 battle_20261114_155925.jsonl 31.57 / 94.70 / 157.83 / 220.96 AV 节拍):
    - 开场 50% 拉条 (`initial_distance = 5000.0`, Speed 158.4 下首动为 31.57 AV)；
    - 若当前场上无存活的【流星铁鹰】召唤物，则施放召唤技能生成 3 只流星铁鹰
      (初始距离分别为 5000.0 / 8000.0 / 11000.0) 并附带攻击与【艾格勒印记】；
    - 否则按节奏执行全体横扫或 4 段单体扑击，并为受击目标附加【艾格勒印记】；
    - 场上任意【流星铁鹰】被击杀时，解除我方全体的【艾格勒印记】。
    """

    SUMMON_COUNT = 3
    INITIAL_DISTANCE = 5000.0
    SUMMON_INITIAL_DISTANCES: Tuple[float, ...] = (5000.0, 8000.0, 11000.0)

    def __init__(
        self,
        owner_id: str,
        port: GriffinCombatPort,
        *,
        windwalk_ready: bool = False,
    ) -> None:
        super().__init__(owner_id, port)
        self._generation = 0
        self._turn_count = 0
        self._turns_since_summon = 0
        self._summon_ids: Tuple[str, ...] = ()
        self._windwalk_ready = windwalk_ready

    @property
    def windwalk_ready(self) -> bool:
        return self._windwalk_ready

    @windwalk_ready.setter
    def windwalk_ready(self, value: bool) -> None:
        self._windwalk_ready = bool(value)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def summon_ids(self) -> Tuple[str, ...]:
        return self._summon_ids

    @property
    def turn_count(self) -> int:
        return self._turn_count

    def on_battle_start(self) -> Optional[EnemyActionResult]:
        return EnemyActionResult(reset_distance=self.INITIAL_DISTANCE)

    def _has_living_summons(self) -> bool:
        return any(self.port.is_alive(eid) for eid in self._summon_ids)

    def _apply_aquila_marks(self, target_ids: Tuple[str, ...]) -> None:
        for tid in target_ids:
            self.port.apply_mark_status(
                owner_id=self.owner_id,
                target_id=tid,
                mark_key=AQUILA_MARK_KEY,
                mark_name=AQUILA_MARK_NAME,
                description="正阳狮鹫附加的【艾格勒印记】，击杀场上的流星铁鹰可解除该印记。",
            )

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        if ctx.actor_id != self.owner_id:
            raise ValueError(f"Actor mismatch: {ctx.actor_id!r} != {self.owner_id!r}")
        if not self.port.is_alive(self.owner_id):
            raise RuntimeError("Dead SunlitGriffin cannot act")

        self._turn_count += 1
        allies = self.port.get_living_allies()

        # 官方节拍: 召唤后需经历 2 次常规攻击 (全体横扫 -> 4段单体) 后，第 3 动强制回收残留铁鹰并重召下一代
        should_summon = self._generation == 0 or self._turns_since_summon >= 2
        if should_summon:
            # 召唤 3 只流星铁鹰: 实机日志 31.57 AV 实测为先制单体攻击 -> 召唤 3 鹰 -> 全体横扫并施加【艾格勒印记】
            if allies:
                self.port.apply_enemy_attack(
                    owner_id=self.owner_id,
                    target_ids=(allies[0],),
                    multiplier=3.0,
                    element="Fire",
                    hit_energy=5.0,
                    hits=1,
                )
            self._generation += 1
            self._turns_since_summon = 0
            self._summon_ids = self.port.summon_meteor_eagles(
                owner_id=self.owner_id,
                generation=self._generation,
                count=self.SUMMON_COUNT,
                initial_distances=self.SUMMON_INITIAL_DISTANCES,
            )
            if allies:
                self.port.apply_enemy_attack(
                    owner_id=self.owner_id,
                    target_ids=allies,
                    multiplier=2.6,
                    element="Fire",
                    hit_energy=5.0,
                    hits=1,
                )
                self._apply_aquila_marks(allies)
            if self._windwalk_ready:
                self._windwalk_ready = False
                return EnemyActionResult(reset_distance=0.0)
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

        self._turns_since_summon += 1
        if allies:
            # 常规攻击节奏: 召唤后第 1 动单体攻击 (Skill01 = 3.0) / 第 2 动 4 段扩散扑击 (Skill04 = 4.0)
            if self._turns_since_summon % 2 == 1:
                target = allies[0]
                resolved = self.port.apply_enemy_attack(
                    owner_id=self.owner_id,
                    target_ids=(target,),
                    multiplier=3.0,
                    element="Fire",
                    hit_energy=5.0,
                    hits=1,
                )
                if resolved:
                    self._apply_aquila_marks(resolved)
            else:
                target = allies[0]
                resolved = self.port.apply_enemy_attack(
                    owner_id=self.owner_id,
                    target_ids=(target,),
                    multiplier=1.0,
                    element="Fire",
                    hit_energy=5.0,
                    hits=4,
                    blast=True,
                    adjacent_multiplier_ratio=0.75,
                )
                if resolved:
                    self._apply_aquila_marks(resolved)

        if self._windwalk_ready:
            self._windwalk_ready = False
            return EnemyActionResult(reset_distance=0.0)

        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def clear_aquila_marks(self) -> None:
        """击杀流星铁鹰后清除我方全体的【艾格勒印记】。"""
        for tid in self.port.get_living_allies():
            self.port.remove_mark_status(target_id=tid, mark_key=AQUILA_MARK_KEY)

    def on_event(self, event: Any) -> None:
        if not self.port.is_alive(self.owner_id):
            return
        from ...events import EnemyDefeatedEvent
        if not isinstance(event, EnemyDefeatedEvent):
            return
        # 监听实体阵亡事件: 若阵亡者为己方召唤的流星铁鹰，解除【艾格勒印记】
        defeated_id = (
            getattr(event, "enemy_name", None)
            or getattr(event, "target_id", None)
            or getattr(event, "entity_id", None)
            or getattr(event, "target_name", None)
        )
        if defeated_id and defeated_id in self._summon_ids:
            self.clear_aquila_marks()

    def get_kit_state(self) -> dict[str, Any]:
        return {
            "generation": self._generation,
            "turn_count": self._turn_count,
            "summon_ids": list(self._summon_ids),
        }

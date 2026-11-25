# coding: utf-8
"""关卡波次模式组件 (WaveMode: MoCWaveMode / AnomalyWaveMode)。

从根目录 simulator/stage_director.py 迁入 simulator/vm/ 统一管理。
"""

from __future__ import annotations

from typing import Any, Optional, Protocol


class WaveMode(Protocol):
    """关卡波次切换模式契约。"""

    wave: int
    max_waves: int
    wave_start_av: float
    wave2_av: Optional[float]

    def current_wave_cycle(self, sim: Any) -> int: ...
    def should_advance_wave(self, sim: Any) -> bool: ...
    def advance_wave(self, sim: Any) -> bool: ...


class MoCWaveMode:
    """混沌回忆式波次切换模式（换波刷新 AV 计时基准与我方行动条）。"""

    def __init__(self, *, max_waves: int = 2) -> None:
        self.wave: int = 1
        self.max_waves: int = max_waves
        self.wave_start_av: float = 0.0
        self.wave2_av: Optional[float] = None

    def current_wave_cycle(self, sim: Any) -> int:
        elapsed = max(0.0, float(getattr(sim, "current_av", 0.0)) - self.wave_start_av)
        if elapsed < 150.0 - 1e-9:
            return 0
        return 1 + int((elapsed - 150.0 + 1e-9) // 100.0)

    def should_advance_wave(self, sim: Any) -> bool:
        if self.wave >= self.max_waves:
            return False
        living_enemies = [
            e for e in sim.entities
            if getattr(e, "is_enemy", False) and getattr(e, "current_hp", 0.0) > 0.0
        ]
        return len(living_enemies) == 0

    def advance_wave(self, sim: Any) -> bool:
        if not self.should_advance_wave(sim):
            return False
        self.wave += 1
        self.wave_start_av = float(getattr(sim, "current_av", 0.0))
        if self.wave == 2 and self.wave2_av is None:
            self.wave2_av = self.wave_start_av
        for ent in sim.entities:
            if (
                not getattr(ent, "is_enemy", False)
                and getattr(ent, "current_hp", 0.0) > 0.0
                and getattr(ent, "speed", 0.0) > 0.0
                and getattr(ent, "distance_remaining", 1e12) < 1e5
            ):
                ent.distance_remaining = 10000.0
        if hasattr(sim, "_ready_queue"):
            sim._ready_queue.clear()
        return True


class AnomalyWaveMode:
    """异象仲裁式波次切换模式（换波不刷新 AV，不重置我方行动条与就绪队列）。"""

    def __init__(self, *, max_waves: int = 2, ignore_infinite_hp: bool = True) -> None:
        self.wave: int = 1
        self.max_waves: int = max_waves
        self.wave_start_av: float = 0.0
        self.wave2_av: Optional[float] = None
        self.ignore_infinite_hp: bool = ignore_infinite_hp

    def current_wave_cycle(self, sim: Any) -> int:
        return int(getattr(sim, "current_cycle", 0))

    def should_advance_wave(self, sim: Any) -> bool:
        if self.wave >= self.max_waves:
            return False
        living_enemies = [
            e for e in sim.entities
            if getattr(e, "is_enemy", False)
            and (not self.ignore_infinite_hp or not getattr(e, "is_infinite_hp", False))
            and getattr(e, "current_hp", 0.0) > 0.0
        ]
        return len(living_enemies) == 0

    def advance_wave(self, sim: Any) -> bool:
        if not self.should_advance_wave(sim):
            return False
        self.wave += 1
        if self.wave == 2 and self.wave2_av is None:
            self.wave2_av = float(getattr(sim, "current_av", 0.0))
        return True

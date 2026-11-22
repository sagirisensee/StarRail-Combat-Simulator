# coding: utf-8
"""关卡波次模式与弱点击破异常状态辅助组件 (WaveMode & BreakStatusHelper)。

从根目录 simulator/stage_director.py 迁入 simulator/vm/ 统一管理。
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from simulator.damage import DamageRequest, DamageType
from simulator.effects import ApplyDamageEffect
from simulator.events import DamageAppliedEvent, TurnBeginEvent, WeaknessBreakEvent
from simulator.status import StatType


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


class BreakStatusHelper:
    """通用弱点击破异常状态结算器（量子纠缠 / 风化）。"""

    def __init__(self, sim: Any) -> None:
        self.sim = sim
        self.quantum_entanglements: dict[str, tuple[str, int]] = {}
        self.wind_shears: dict[str, tuple[str, int]] = {}

    def on_weakness_break(self, event: WeaknessBreakEvent) -> None:
        tgt = self.sim.get_entity(event.target_name)
        if tgt is None or not getattr(tgt, "is_enemy", False):
            return
        if event.element == "Quantum":
            self.quantum_entanglements[event.target_name] = (event.breaker_name, 1)
        elif event.element == "Wind":
            self.wind_shears[event.target_name] = (event.breaker_name, 2)

    def on_damage_applied(self, event: DamageAppliedEvent) -> None:
        target_name = str(getattr(event, "target_name", ""))
        if target_name in self.quantum_entanglements and getattr(event, "damage", 0.0) > 0.0:
            dtype = getattr(event, "damage_type", None)
            if dtype not in (DamageType.ADDITIONAL, DamageType.DOT, DamageType.TRUE):
                self.add_quantum_stack(target_name)

    def add_quantum_stack(self, target_name: str) -> None:
        if target_name in self.quantum_entanglements:
            atk_name, stacks = self.quantum_entanglements[target_name]
            if stacks < 5:
                self.quantum_entanglements[target_name] = (atk_name, stacks + 1)

    def on_turn_begin(self, event: TurnBeginEvent) -> None:
        if event.actor_name in self.quantum_entanglements:
            atk_name, stacks = self.quantum_entanglements.pop(event.actor_name)
            tgt = self.sim.get_entity(event.actor_name)
            atk = self.sim.get_entity(atk_name)
            if tgt is not None and atk is not None and getattr(tgt, "current_hp", 0.0) > 0.0:
                sm = self.sim.status_mgr
                be = sm.calculate_stat(atk.name, getattr(atk, "base_break_effect", 0.0), StatType.BREAK_EFFECT)
                dmg_boost = sm.calculate_stat(atk.name, getattr(atk, "base_dmg_boost", 0.0), StatType.DMG_BOOST)
                elem_boost = (
                    getattr(atk, "element_dmg_boost", {}).get("Quantum", 0.0)
                    if isinstance(getattr(atk, "element_dmg_boost", None), dict)
                    else 0.0
                )
                tough_mult = 0.5 + (getattr(tgt, "max_toughness", 0.0) / 120.0)
                base_ent = 0.6 * stacks * 3767.5533 * tough_mult * (1.0 + be) / max(1.0, 1.0 + dmg_boost + elem_boost)
                req = DamageRequest(
                    attacker=atk,
                    target=tgt,
                    skill_multiplier=0.0,
                    flat_damage=base_ent,
                    target_base_res=(
                        tgt.damage_res.get("Quantum", 0.0)
                        if isinstance(getattr(tgt, "damage_res", None), dict)
                        else 0.0
                    ),
                    target_is_broken=True,
                    force_crit=False,
                    damage_type=DamageType.ADDITIONAL,
                )
                self.sim.resolver.enqueue(
                    ApplyDamageEffect(
                        request=req,
                        element="Quantum",
                        damage_tag="Additional",
                        damage_type=DamageType.ADDITIONAL,
                    )
                )
        if event.actor_name in self.wind_shears:
            atk_name, turns_left = self.wind_shears[event.actor_name]
            tgt = self.sim.get_entity(event.actor_name)
            atk = self.sim.get_entity(atk_name)
            if tgt is not None and atk is not None and getattr(tgt, "current_hp", 0.0) > 0.0:
                sm = self.sim.status_mgr
                be = sm.calculate_stat(atk.name, getattr(atk, "base_break_effect", 0.0), StatType.BREAK_EFFECT)
                if getattr(atk, "is_memosprite", False) and hasattr(atk, "master_name"):
                    m_ent = self.sim.get_entity(atk.master_name)
                    if m_ent is not None:
                        be = max(be, sm.calculate_stat(m_ent.name, getattr(m_ent, "base_break_effect", 0.0), StatType.BREAK_EFFECT))
                dmg_boost = sm.calculate_stat(atk.name, 0.0, StatType.DMG_BOOST)
                stacks = 3 if getattr(tgt, "is_boss", False) else 1
                base_dot = 3767.5533 * stacks * (1.0 + be) / max(1.0, 1.0 + dmg_boost)
                req = DamageRequest(
                    attacker=atk,
                    target=tgt,
                    skill_multiplier=0.0,
                    flat_damage=base_dot,
                    target_base_res=0.0,
                    target_is_broken=True,
                    force_crit=False,
                    damage_type=DamageType.DOT,
                )
                self.sim.resolver.enqueue(
                    ApplyDamageEffect(
                        request=req,
                        element="Wind",
                        damage_tag="DoT",
                        damage_type=DamageType.DOT,
                    )
                )
            if turns_left <= 1:
                self.wind_shears.pop(event.actor_name, None)
            else:
                self.wind_shears[event.actor_name] = (atk_name, turns_left - 1)

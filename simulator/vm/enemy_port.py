# coding: utf-8
"""VM 敌方战斗协议与极简端口实现（合并原 simulator/kits/enemies/）。"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from simulator.damage import DamageRequest
from simulator.effects import ApplyDamageEffect
from simulator.status import StatType

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


@dataclass(frozen=True)
class EnemySubActionOutcome:
    """单次敌方子动作的执行结果，由内核 TurnFrame 统一协调间隙钩子与多动循环。"""

    executed: bool = True
    has_next_sub_action: bool = False


class EnemyKit(ABC):
    """敌方专属 Kit 基类，由 DataDrivenEnemyKit 实现。"""

    supports_staged_sub_actions: bool = False

    def __init__(self, owner_id: str, port: Any) -> None:
        self.owner_id = owner_id
        self.port = port

    def on_battle_start(self) -> Optional[EnemyActionResult]:
        return None

    def begin_turn_session(self, ctx: EnemyActionContext) -> Any:
        return None

    def execute_next_sub_action(
        self,
        session: Any,
        sub_action_index: int,
    ) -> Optional[EnemySubActionOutcome]:
        return None

    def finish_turn_session(self, session: Any) -> EnemyActionResult:
        return EnemyActionResult()

    @abstractmethod
    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        raise NotImplementedError

    def on_event(self, event: Any) -> None:
        pass

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
        return raw_damage

    def on_battle_end(self) -> None:
        pass

    def get_kit_state(self) -> dict[str, Any]:
        return {}


class BaseEnemyCombatPortImpl:
    """VM 敌方 Kit 战斗端口实现，连接 DataDrivenEnemyKit 与 TurnSimulator。"""

    def __init__(self, sim: Any) -> None:
        self.sim = sim

    def is_alive(self, entity_id: str) -> bool:
        ent = self.sim.get_entity(entity_id)
        return ent is not None and getattr(ent, "current_hp", 0.0) > 0

    def is_broken(self, entity_id: str) -> bool:
        ent = self.sim.get_entity(entity_id)
        return bool(ent is not None and getattr(ent, "is_broken", False))

    def apply_enemy_attack(
        self,
        *,
        owner_id: str,
        target_ids: Tuple[str, ...],
        multiplier: float,
        element: str = "Physical",
        hit_energy: float = 5.0,
        hits: int = 1,
        blast: bool = False,
        adjacent_multiplier_ratio: float = 1.0,
        increment_action_seq: bool = True,
    ) -> Tuple[str, ...]:
        attacker = self.sim.get_entity(owner_id)
        if attacker is None or attacker.current_hp <= 0:
            return ()
        skip_provider = getattr(self.sim, "enemy_attack_skip_provider", None)
        if skip_provider is not None and skip_provider(attacker, float(getattr(self.sim, "current_av", 0.0))):
            return ()
        attacker.hit_energy = hit_energy
        if increment_action_seq:
            self.sim._action_seq += 1

        resolved_targets: List[Any] = []
        for tid in target_ids:
            tgt = self.sim.get_entity(tid)
            if tgt is not None and tgt.current_hp > 0:
                resolved_targets.append(tgt)
        if not resolved_targets:
            return ()

        target_provider = getattr(self.sim, "target_provider", None)
        if target_provider is not None and len(resolved_targets) == 1:
            living = [
                e
                for e in self.sim.entities
                if not e.is_enemy
                and e.current_hp > 0
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
            ]
            if living:
                chosen = target_provider(attacker, living, 0)
                if chosen is not None:
                    resolved_targets = [chosen]

        primary_target: Optional[Any] = resolved_targets[0] if (blast and len(resolved_targets) == 1) else None
        if primary_target is not None:
            primary = primary_target
            living_allies = [
                e
                for e in self.sim.entities
                if not e.is_enemy
                and e.current_hp > 0
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
            ]
            blast_provider = getattr(self.sim, "blast_target_provider", None)
            if blast_provider is not None:
                extra = blast_provider(attacker, primary, living_allies)
                for adj in extra or ():
                    if adj is not None and adj.current_hp > 0 and adj not in resolved_targets:
                        resolved_targets.append(adj)
            else:
                port = getattr(self.sim, "port", None)
                paired = [
                    e
                    for e in living_allies
                    if e is not primary
                    and port is not None
                    and (
                        port.is_own_memosprite(primary.name, e.name)
                        or port.is_own_memosprite(e.name, primary.name)
                    )
                ]
                if paired:
                    resolved_targets.extend(paired)
                elif primary in living_allies:
                    idx = living_allies.index(primary)
                    for adj_idx in (idx - 1, idx + 1):
                        if 0 <= adj_idx < len(living_allies):
                            resolved_targets.append(living_allies[adj_idx])

        vm_rt = getattr(self.sim, "vm_runtime", None)
        if vm_rt is not None and increment_action_seq:
            vm_rt.begin_being_attacked(attacker.name, [t.name for t in resolved_targets])

        for _ in range(max(1, hits)):
            for tgt in resolved_targets:
                if tgt.current_hp <= 0:
                    continue
                tgt_mult = (
                    multiplier * adjacent_multiplier_ratio
                    if (primary_target is not None and tgt is not primary_target)
                    else multiplier
                )
                req = DamageRequest(
                    attacker=attacker,
                    target=tgt,
                    skill_multiplier=tgt_mult,
                )
                self.sim.resolver.enqueue(
                    ApplyDamageEffect(
                        request=req,
                        toughness_reduction=0.0,
                        element=element,
                    )
                )
            self.sim.resolver.resolve_all()
        return tuple(t.name for t in resolved_targets)

    def break_entity_toughness_and_deduct_hp(
        self,
        entity_id: str,
        *,
        hp_deduct: float,
        break_delay: float = 12500.0,
    ) -> None:
        ent = self.sim.get_entity(entity_id)
        if ent is None or ent.current_hp <= 0.0:
            return
        ent.current_toughness = 0.0
        ent.is_broken = True
        break_dmg = 0.0
        max_t = float(getattr(ent, "max_toughness", 0.0) or 0.0)
        if max_t > 0.0 and hasattr(self.sim, "status_mgr"):
            sm = self.sim.status_mgr
            tgt_lvl = int(getattr(ent, "level", 95) or 95)
            atk_lvl = float(tgt_lvl)
            base_break = 3767.5535
            vm_rt = getattr(self.sim, "vm_runtime", None)
            if vm_rt is not None and hasattr(vm_rt, "loader"):
                try:
                    for row in vm_rt.loader._read_excel("AvatarBreakDamage.json"):
                        if int(row.get("Level", 0) or 0) == tgt_lvl:
                            bv = row.get("BreakBaseDamage", {})
                            base_break = float(bv.get("Value", base_break) if isinstance(bv, dict) else bv)
                            break
                except Exception:
                    pass
            def_shred = sm.calculate_stat(ent.name, 0.0, StatType.DEF_SHRED)
            def_mult = (atk_lvl + 20.0) / ((float(tgt_lvl) + 20.0) * max(0.0, 1.0 - def_shred) + (atk_lvl + 20.0))
            base_res = ent.damage_res.get("Quantum", 0.0) if isinstance(getattr(ent, "damage_res", None), dict) else 0.0
            res_mult = max(0.0, 1.0 - base_res)
            vuln_mult = 1.0 + sm.calculate_stat(ent.name, 0.0, StatType.VULNERABILITY)
            break_dmg = base_break * 0.5 * (0.5 + max_t / 120.0) * def_mult * res_mult * vuln_mult * 0.9
        ent.current_hp = max(0.0, float(ent.current_hp) - hp_deduct - break_dmg)
        if ent.distance_remaining < 1e9:
            ent.distance_remaining += float(break_delay)

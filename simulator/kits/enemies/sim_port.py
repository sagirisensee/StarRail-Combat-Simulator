# coding: utf-8
"""通用敌方战斗端口实现 (BaseEnemyCombatPortImpl)。

将敌方 Kit 与 TurnSimulator 之间的通用桥接逻辑（存活查询、敌方攻击与扩散解析、
锁血/减速/印记互斥引爆、多阶段面板切换、通道脉冲、护盾反噬等）从具体关卡
文件抽离出来，供各关卡 StageCombatPort 直接继承复用。
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ...combat_port import BuffSpec
from ...damage import DamageRequest
from ...effects import ApplyDamageEffect
from ...status import DurationTiming, Modifier, ModifierOp, StatType
from .griffin import AQUILA_MARK_KEY
from .pegasus import ORONYX_MARK_KEY


class BaseEnemyCombatPortImpl:
    """通用敌方 Kit 战斗端口适配器基类，连接敌方 Kit 与 TurnSimulator。"""

    def __init__(self, sim: Any) -> None:
        self.sim = sim

    def is_alive(self, entity_id: str) -> bool:
        ent = self.sim.get_entity(entity_id)
        return ent is not None and getattr(ent, "current_hp", 0.0) > 0

    def get_living_allies(self, include_memosprites: bool = False) -> Tuple[str, ...]:
        allies = [
            e.name
            for e in self.sim.entities
            if not e.is_enemy
            and getattr(e, "current_hp", 0.0) > 0
            and not getattr(e, "is_countdown", False)
            and (include_memosprites or not getattr(e, "is_memosprite", False))
        ]
        return tuple(allies)

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

        # 若外部挂载了 target_provider 且本次为单体点名，则优先遵循对账引导
        target_provider = getattr(self.sim, "target_provider", None)
        if target_provider is not None and len(resolved_targets) == 1:
            living = [
                e
                for e in self.sim.entities
                if not e.is_enemy
                and e.current_hp > 0
                and not getattr(e, "is_countdown", False)
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
            ]
            blast_provider = getattr(self.sim, "blast_target_provider", None)
            if blast_provider is not None:
                extra = blast_provider(attacker, primary, living_allies)
                for adj in extra or ():
                    if adj is not None and adj.current_hp > 0 and adj not in resolved_targets:
                        resolved_targets.append(adj)
            else:
                # 通用扩散邻位: 优先匹配存在绑定关系的忆灵/召唤者, 否则按站位邻格扩散
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

    def apply_hp_lock(
        self,
        *,
        target_id: str,
        delta_ratio: float = 0.10,
        max_ratio: float = 0.50,
    ) -> None:
        tgt = self.sim.get_entity(target_id)
        if tgt is None or tgt.is_enemy or tgt.current_hp <= 0.0:
            return
        cur = float(getattr(tgt, "hp_lock_ratio", 0.0))
        tgt.hp_lock_ratio = min(max_ratio, cur + delta_ratio)
        tgt.clamp_hp()

    def apply_speed_debuff(
        self,
        *,
        owner_id: str,
        target_id: str,
        key: str,
        name: str,
        pct_per_stack: float = -0.10,
        max_stacks: int = 5,
        duration: int = 3,
        base_chance: float = 1.0,
    ) -> bool:
        attacker = self.sim.get_entity(owner_id)
        target = self.sim.get_entity(target_id)
        if attacker is None or target is None or target.current_hp <= 0:
            return False
        provider = getattr(self.sim, "debuff_hit_provider", None)
        if provider is not None:
            landed = bool(provider(attacker, target, key, float(getattr(self.sim, "current_av", 0.0))))
        else:
            eff_hit = float(getattr(attacker, "effect_hit_rate", getattr(attacker, "base_effect_hit_rate", 0.36)))
            eff_res = float(self.sim.port.stat(target_id, StatType.EFFECT_RES))
            chance = base_chance * (1.0 + eff_hit) * max(0.0, 1.0 - eff_res)
            rng = getattr(self.sim, "rng", None)
            roll = rng.random() if rng is not None else 0.0
            landed = roll < chance
        if not landed:
            return False

        full_key = f"{key}_{target_id}"
        existing = next(
            (s for s in self.sim.status_mgr.get_statuses(target_id) if s.id == full_key),
            None,
        )
        prev_stacks = int(getattr(existing, "stacks", 0)) if existing is not None else 0
        stacks = min(max_stacks, prev_stacks + 1)
        if existing is not None:
            self.sim.port.remove_status(target_id, full_key)
        self.sim.port.upsert_status(
            BuffSpec(
                key=full_key,
                name=name,
                source_id=owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, pct_per_stack),),
                duration=duration,
                timing=DurationTiming.TARGET_TURN_END,
                category="debuff",
                stacks=stacks,
                max_stacks=max_stacks,
                description=f"速度降低 {abs(pct_per_stack) * stacks * 100:.0f}% ({stacks}层)",
            )
        )
        return True

    def apply_mark_status(
        self,
        *,
        owner_id: str,
        target_id: str,
        mark_key: str,
        mark_name: str,
        description: str = "",
    ) -> None:
        opposite_key = (
            AQUILA_MARK_KEY if mark_key == ORONYX_MARK_KEY
            else (ORONYX_MARK_KEY if mark_key == AQUILA_MARK_KEY else None)
        )
        if opposite_key and self.has_mark_status(target_id=target_id, mark_key=opposite_key):
            self.remove_mark_status(target_id=target_id, mark_key=opposite_key)
            max_hp = self.sim.port.max_hp(target_id)
            if max_hp > 0.0:
                self.sim.port.lose_hp(target_id, max_hp * 0.25, cause="attack_damage")
            return
        self.sim.port.upsert_status(
            BuffSpec(
                key=mark_key,
                name=mark_name,
                source_id=owner_id,
                target_id=target_id,
                modifiers=(),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="mark",
                description=description,
            )
        )

    def remove_mark_status(
        self,
        *,
        target_id: str,
        mark_key: str,
    ) -> bool:
        if not self.has_mark_status(target_id=target_id, mark_key=mark_key):
            return False
        self.sim.status_mgr.remove_status(target_id, mark_key)
        return True

    def has_mark_status(
        self,
        *,
        target_id: str,
        mark_key: str,
    ) -> bool:
        return any(
            st.id == mark_key for st in self.sim.status_mgr.get_statuses(target_id)
        )

    def trigger_oronyx_detonation(
        self,
        *,
        owner_id: str,
        target_id: str,
        multiplier: float,
        element: str = "Quantum",
    ) -> None:
        self.apply_enemy_attack(
            owner_id=owner_id,
            target_ids=(target_id,),
            multiplier=multiplier,
            element=element,
            hit_energy=0.0,
            hits=1,
        )

    def get_current_av(self) -> float:
        return float(getattr(self.sim, "current_av", 0.0))

    def get_entity_hp_and_max(self, entity_id: str) -> Tuple[float, float]:
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            return (0.0, 0.0)
        return (float(ent.current_hp), float(ent.max_hp))

    def set_entity_phase_stats(
        self,
        entity_id: str,
        *,
        max_hp: float,
        current_hp: float,
        speed: float,
        toughness: float,
        reset_distance: Optional[float] = None,
        toughness_dmg_reduction: Optional[float] = None,
    ) -> None:
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            return
        ent.max_hp = max_hp
        ent.current_hp = current_hp
        ent.base_speed = speed
        ent.max_toughness = toughness
        ent.current_toughness = toughness
        ent.is_broken = False
        if reset_distance is not None:
            ent.distance_remaining = reset_distance
        if toughness_dmg_reduction is not None:
            ent.toughness_dmg_reduction = float(toughness_dmg_reduction)

    def set_entity_speed(self, entity_id: str, speed: float) -> None:
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            return
        ent.base_speed = speed

    def set_barrier_state(
        self,
        entity_id: str,
        *,
        active: bool,
        damage_reduction: float = 0.75,
        toughness_dmg_reduction: Optional[float] = None,
    ) -> None:
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            return
        def _apply() -> None:
            ent.barrier_guarded = bool(active)
            ent.toughness_locked = bool(active)
            ent.damage_reduction = float(damage_reduction) if active else 0.0
            if toughness_dmg_reduction is not None:
                ent.toughness_dmg_reduction = float(toughness_dmg_reduction)
        resolver = getattr(self.sim, "resolver", None)
        if active and resolver is not None and getattr(resolver, "_resolving", False):
            resolver.defer_post_resolve(_apply)
            return
        _apply()

    def break_entity_toughness_and_deduct_hp(
        self,
        entity_id: str,
        *,
        hp_deduct: float,
    ) -> None:
        ent = self.sim.get_entity(entity_id)
        if ent is None or ent.current_hp <= 0.0:
            return
        ent.current_toughness = 0.0
        ent.is_broken = True
        ent.current_hp = max(0.0, float(ent.current_hp) - hp_deduct)
        if ent.distance_remaining < 1e9:
            ent.distance_remaining += 2500.0

    def is_broken(self, entity_id: str) -> bool:
        ent = self.sim.get_entity(entity_id)
        return bool(ent is not None and getattr(ent, "is_broken", False))

    def set_continuous_action_hold(self, hold: bool) -> None:
        if hasattr(self.sim, "scheduler"):
            self.sim.scheduler.continuous_action_hold = hold

    def execute_channel_pulse(
        self,
        *,
        owner_id: str,
        allies: Tuple[str, ...],
        multipliers: Optional[Tuple[float, ...]] = None,
        tick_hit_energy: float = 1.0,
        final_hit_energy: float = 12.0,
    ) -> None:
        attacker = self.sim.get_entity(owner_id)
        if attacker is None or attacker.current_hp <= 0.0:
            return
        seq_mults = multipliers if multipliers is not None else ((0.12,) * 8 + (1.44,))
        if not seq_mults:
            return
        setattr(self.sim, "_in_channel_pulse", True)
        try:
            for idx, mult in enumerate(seq_mults):
                self.apply_enemy_attack(
                    owner_id=owner_id,
                    target_ids=allies,
                    multiplier=float(mult),
                    element="Physical",
                    hit_energy=float(final_hit_energy),
                    hits=1,
                    blast=False,
                    increment_action_seq=(idx == 0),
                )
        finally:
            setattr(self.sim, "_in_channel_pulse", False)

    def heal_boss_by_ratio(self, *, boss_id: str, ratio: float) -> float:
        boss = self.sim.get_entity(boss_id)
        if boss is None or boss.current_hp <= 0.0:
            return 0.0
        heal_amt = float(boss.max_hp) * ratio
        before = float(boss.current_hp)
        boss.current_hp = min(float(boss.max_hp), before + heal_amt)
        return boss.current_hp - before

    def is_boss_barrier_active(self, boss_id: str) -> bool:
        boss = self.sim.get_entity(boss_id)
        kit = getattr(boss, "kit", None) if boss is not None else None
        return bool(getattr(kit, "barrier_active", False))

    def apply_boss_backlash(self, *, boss_id: str, damage: float) -> None:
        resolver = getattr(self.sim, "resolver", None)
        if resolver is not None and (getattr(resolver, "_resolving", False) or getattr(resolver, "_aoe_depth", 0) > 0):
            resolver.defer_post_resolve(
                lambda: self._apply_boss_backlash_now(boss_id=boss_id, damage=damage)
            )
            return
        self._apply_boss_backlash_now(boss_id=boss_id, damage=damage)

    def _apply_boss_backlash_now(self, *, boss_id: str, damage: float) -> None:
        boss = self.sim.get_entity(boss_id)
        if boss is None or boss.current_hp <= 0.0:
            return
        kit = getattr(boss, "kit", None)
        if kit is not None and getattr(kit, "barrier_active", False):
            if hasattr(kit, "notify_sprout_killed_on_barrier"):
                kit.notify_sprout_killed_on_barrier(float(boss.max_hp) * 0.02)
            return
        boss.current_hp = max(0.0, float(boss.current_hp) - float(boss.max_hp) * 0.02)

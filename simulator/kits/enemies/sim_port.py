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
        allies: List[str] = []
        for e in self.sim.entities:
            if e.is_enemy or getattr(e, "current_hp", 0.0) <= 0 or getattr(e, "is_countdown", False):
                continue
            if not include_memosprites and getattr(e, "is_memosprite", False):
                continue
            if hasattr(self.sim, "port") and hasattr(self.sim.port, "is_action_suppressed") and self.sim.port.is_action_suppressed(e.name):
                proxy_id = self.sim.port.get_active_proxy(e.name)
                if proxy_id:
                    if proxy_id not in allies:
                        allies.append(proxy_id)
                continue
            allies.append(e.name)
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
        if hasattr(self.sim, "port") and hasattr(self.sim.port, "is_action_suppressed") and self.sim.port.is_action_suppressed(target_id):
            return
        cur = float(getattr(tgt, "hp_lock_ratio", 0.0))
        tgt.hp_lock_ratio = min(max_ratio, cur + delta_ratio)
        old_hp = float(tgt.current_hp)
        tgt.clamp_hp()
        actual_loss = old_hp - float(tgt.current_hp)
        if actual_loss > 0.0:
            from ...events import HPLostEvent
            self.sim.event_bus.publish(HPLostEvent(
                av=round(float(getattr(self.sim, "current_av", 0.0)), 2),
                cycle=int(getattr(self.sim, "current_cycle", 0)),
                entity_name=tgt.name,
                amount=actual_loss,
                hp_left=float(tgt.current_hp),
                cause="hp_lock",
            ))
            for e in list(getattr(self.sim, "entities", ())):
                kit = getattr(e, "kit", None)
                if kit is not None and hasattr(kit, "on_hp_lost"):
                    kit.on_hp_lost(tgt.name, actual_loss, cause="hp_lock")

    def apply_corruption(
        self,
        *,
        owner_id: str,
        target_id: str,
        delta_stacks: int = 1,
    ) -> bool:
        attacker = self.sim.get_entity(owner_id)
        target = self.sim.get_entity(target_id)
        if attacker is None or target is None:
            return False
        hit_provider = getattr(self.sim, "debuff_hit_provider", None)
        av = float(getattr(self.sim, "current_av", 0.0))
        if hit_provider is not None:
            hit = hit_provider(attacker, target, "corruption", av)
            if not hit:
                return False
        corruption_dict = getattr(self.sim, "_apoli_corruption_stacks", None)
        if corruption_dict is None:
            corruption_dict = {}
            self.sim._apoli_corruption_stacks = corruption_dict
        cur_stacks = corruption_dict.get(target_id, 0) + delta_stacks
        corruption_dict[target_id] = cur_stacks
        if cur_stacks >= 3:
            self.set_phantom_state(target_id, active=True)
        return True

    def set_phantom_state(
        self,
        target_id: str,
        *,
        active: bool,
        proxy_name: str = "狂躁的铃音",
        proxy_uid: int = 6025,
        proxy_hp: float = 9002.091353935655,
        tb_hp_add: Optional[float] = None,
    ) -> None:
        target = self.sim.get_entity(target_id)
        if target is None:
            return
        if active:
            if hasattr(self.sim, "port") and hasattr(self.sim.port, "register_proxy"):
                self.sim.port.register_proxy(target_id, proxy_name)
            proxy = self.sim.get_entity(proxy_name)
            if proxy is None:
                from ...core import Entity
                proxy = Entity(
                    name=proxy_name,
                    base_speed=float(getattr(target, "speed", 92.92)),
                    max_hp=proxy_hp,
                    is_enemy=False,
                )
                setattr(proxy, "uid", proxy_uid)
                setattr(proxy, "avatar_id", proxy_uid)
                setattr(proxy, "is_proxy", True)
                proxy.current_hp = proxy_hp
                proxy.distance_remaining = float(getattr(target, "distance_remaining", 36.82))
                self.sim.entities.append(proxy)
            else:
                setattr(proxy, "is_proxy", True)
                proxy.max_hp = proxy_hp
                proxy.current_hp = proxy_hp
                proxy.speed = float(getattr(target, "speed", 92.92))
                proxy.distance_remaining = float(getattr(target, "distance_remaining", 36.82))
            from ...combat_port import BuffSpec
            from ...status import StatusTag
            spec = BuffSpec(
                key="Apoli_Phantom_Transformation",
                name="幻身",
                source_id=self.sim.get_entity("堕神之血•亚婆离").name if self.sim.get_entity("堕神之血•亚婆离") else target_id,
                target_id=target_id,
                modifiers=(),
                duration=None,
                tags=(StatusTag.TARGET_DEBUFF,),
            )
            if hasattr(self.sim, "port") and hasattr(self.sim.port, "upsert_status"):
                self.sim.port.upsert_status(spec)
            elif getattr(target, "kit", None) is not None:
                target.kit.port.upsert_status(spec)
            if tb_hp_add is not None and getattr(target, "kit", None) is not None:
                from ...combat_port import BuffSpec
                from ...status import Modifier, ModifierOp, StatType
                target.kit.port.upsert_status(BuffSpec(
                    key="bell_6025_tb_hp",
                    name="铃音城墙外羊羔",
                    source_id=target_id,
                    target_id=target_id,
                    modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, tb_hp_add / target.base_white_hp),),
                    duration=None,
                ))
        else:
            if hasattr(self.sim, "port") and hasattr(self.sim.port, "remove_proxy"):
                self.sim.port.remove_proxy(target_id)
            proxy = self.sim.get_entity(proxy_name)
            if proxy is not None:
                proxy.current_hp = 0.0
            if hasattr(self.sim, "port") and hasattr(self.sim.port, "remove_status"):
                self.sim.port.remove_status(target_id, "Apoli_Phantom_Transformation")
            elif getattr(target, "kit", None) is not None:
                target.kit.port.remove_status(target_id, "Apoli_Phantom_Transformation")

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
        if hasattr(self.sim, "status_mgr"):
            from ...status import StatusTag
            for st in list(self.sim.status_mgr.get_statuses(entity_id)):
                tags = getattr(st, "tags", ())
                is_debuff = getattr(st, "category", "") == "debuff" or StatusTag.TARGET_DEBUFF in tags
                if is_debuff and getattr(st, "duration", None) is not None and StatusTag.FIELD_AURA not in tags:
                    self.sim.status_mgr.remove_status(entity_id, st.id)

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
        break_dmg = 0.0
        max_t = float(getattr(ent, "max_toughness", 0.0) or 0.0)
        if max_t > 0.0 and hasattr(self.sim, "status_mgr"):
            sm = self.sim.status_mgr
            tgt_lvl = float(getattr(ent, "level", 95) or 95)
            atk_lvl = 80.0
            def_shred = sm.calculate_stat(ent.name, 0.0, StatType.DEF_SHRED)
            def_mult = (atk_lvl + 20.0) / ((tgt_lvl + 20.0) * max(0.0, 1.0 - def_shred) + (atk_lvl + 20.0))
            base_res = ent.damage_res.get("Quantum", 0.0) if isinstance(getattr(ent, "damage_res", None), dict) else 0.0
            res_mult = max(0.0, 1.0 - base_res)
            vuln_mult = 1.0 + sm.calculate_stat(ent.name, 0.0, StatType.VULNERABILITY)
            break_dmg = 3767.5533 * 0.5 * (0.5 + max_t / 120.0) * def_mult * res_mult * vuln_mult * 1.15
        ent.current_hp = max(0.0, float(ent.current_hp) - hp_deduct - break_dmg)
        if ent.distance_remaining < 1e9:
            ent.distance_remaining += 12500.0

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

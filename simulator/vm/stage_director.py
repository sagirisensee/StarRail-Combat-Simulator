# coding: utf-8
"""纯数据驱动关卡导演（DataDrivenStageDirector）与构建入口（从 stage_sim_adapter.py 拆分）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.core import Entity, TurnSimulator
from simulator.events import (
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    HPLostEvent,
    TurnBeginEvent,
    WeaknessBreakEvent,
)
from simulator.kits.enemies.sim_port import BaseEnemyCombatPortImpl
from simulator.stage_director import AnomalyWaveMode, BreakStatusHelper, MoCWaveMode
from simulator.status import StatType
from simulator.vm.enemy_kit import DataDrivenEnemyKit
from simulator.vm.stage_ai import CompiledMonsterAISpec, StageAILoader
from simulator.vm.stage_runner import StageRunner


class DataDrivenStageDirector:
    """Pure data-driven ``StageDirector`` bridging ``StageRunner`` & ``StageAILoader`` to ``TurnSimulator``."""

    def __init__(
        self,
        sim: TurnSimulator,
        runner: StageRunner,
        ai_loader: StageAILoader,
        *,
        ai_by_monster_id: Optional[Mapping[int, CompiledMonsterAISpec]] = None,
    ) -> None:
        self.sim = sim
        self.runner = runner
        self.ai_loader = ai_loader
        self.port = BaseEnemyCombatPortImpl(sim)
        self.stage_id = runner.built_stage.stage_id
        self.max_waves = runner.built_stage.num_waves
        self._is_moc = (
            runner.built_stage.source_spec.stage_infinite_group_id is None
            and runner.built_stage.stage_type == "Challenge"
        )
        self._wave_mode = (
            MoCWaveMode(max_waves=self.max_waves)
            if self._is_moc
            else AnomalyWaveMode(max_waves=self.max_waves)
        )
        self._break_helper = BreakStatusHelper(sim)
        self._ai_cache: Dict[int, CompiledMonsterAISpec] = dict(ai_by_monster_id or {})
        self._last_cycle: int = sim.current_cycle
        self.aha_special_damage: float = 0.0
        self._pending_aha_turn: bool = False
        self._published_aha_turn_avs: set[float] = set()
        self._wave_start_av: float = 0.0
        self._triggered_aha_cycles: set[tuple[int, int]] = set()
        self.aha_extra_turns: list[dict[str, Any]] = []
        self.laugh_points: int = 0
        self._fired_aha_interrupts: set[int] = set()
        self._battle_event_timers: Dict[str, Tuple[str, str]] = {}
        self._triggered_aha_137: bool = False
        self._triggered_aha_150: bool = False

        self.sim.event_bus.subscribe(WeaknessBreakEvent, self._break_helper.on_weakness_break)
        self.sim.event_bus.subscribe(DamageAppliedEvent, self._break_helper.on_damage_applied)
        self.sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        setattr(self.sim, "_stage_director", self)

    def _current_wave_cycle(self) -> int:
        return self._wave_mode.current_wave_cycle(self.sim)

    def _check_cycle_aha_extra_turn(self) -> None:
        cur_cycle = self._current_wave_cycle()
        key = (self.wave, cur_cycle)
        if key not in self._triggered_aha_cycles:
            self._triggered_aha_cycles.add(key)
            record = {
                "cycle": cur_cycle,
                "av": round(self.sim.current_av, 2),
                "fixed_laugh_points": 20,
                "consumed_laugh_points": 0,
                "remaining_laugh_points": getattr(self, "laugh_points", 0),
            }
            self.aha_extra_turns.append(record)
            if cur_cycle >= 1:
                self.sim._turn_seq = getattr(self.sim, "_turn_seq", 0) + 1
                self._published_aha_turn_avs.add(round(float(self.sim.current_av), 2))
                self.sim.event_bus.publish(
                    TurnBeginEvent(
                        av=round(self.sim.current_av, 2),
                        cycle=cur_cycle,
                        actor_id="阿哈",
                        actor_name="阿哈",
                        speed=0.0,
                        turn_id=self.sim._turn_seq,
                    )
                )
            from simulator.events import AhaExtraTurnEvent

            self.sim.event_bus.publish(
                AhaExtraTurnEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=cur_cycle,
                    fixed_laugh_points=20,
                    consumed_laugh_points=0,
                    remaining_laugh_points=getattr(self, "laugh_points", 0),
                    description=f"[AhaExtraTurn] 第 {cur_cycle} 轮开始：阿哈获得 1 个固定计入 20 笑点的额外回合（不消耗笑点）",
                )
            )

    def peek_next_interrupt_av(self, now0: float, landing_av: float) -> Optional[float]:
        """返回 (now0, landing_av) 区间内最早的关卡轮次边界或待触发阿哈事件 AV。"""
        best: Optional[float] = None
        c = 1
        wave_start = getattr(self, "_wave_start_av", 0.0)
        while True:
            if (self.wave, c) not in self._triggered_aha_cycles:
                cyc_av = wave_start + 150.0 + 100.0 * (c - 1)
                if now0 + 1e-6 < cyc_av < landing_av - 1e-6:
                    best = cyc_av
                break
            c += 1
        for idx, cand in enumerate(getattr(self.sim, "aha_interrupt_avs", ())):
            if idx in self._fired_aha_interrupts:
                continue
            cand_f = float(cand)
            if now0 + 1e-6 < cand_f < landing_av - 1e-6:
                if best is None or cand_f < best:
                    best = cand_f
        return best

    def mark_interrupt_av_checked(self, av: float) -> None:
        for idx, cand in enumerate(getattr(self.sim, "aha_interrupt_avs", ())):
            if abs(float(cand) - av) <= 1e-5:
                self._fired_aha_interrupts.add(idx)

    def flush_ally_talent_heals(self) -> None:
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is not None:
            hit_enemies = list(getattr(self, "_aha_hit_enemies", ()))
            if hit_enemies:
                self._aha_hit_enemies.clear()
                for ename in hit_enemies:
                    e_obj = self.sim.get_entity(ename)
                    if e_obj is not None and e_obj.current_hp > 0.0:
                        rt.modifier_engine.dispatch_event(
                            "OnAfterBeingAttacked",
                            owner_id=ename,
                            param_entity_id="阿哈",
                        )
            rt.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id="__LEVEL__")
            rt.end_being_attacked("阿哈")
            if getattr(self, "_pending_aha_turn", False):
                self._pending_aha_turn = False
                if not getattr(self, "_suppress_aha_turn_reset", False):
                    rt.modifier_engine.dispatch_event("OnListenTurnEnd", param_entity_id="阿哈")
                    cur_ent = getattr(self.sim, "_current_turn_entity", None)
                    if cur_ent is not None:
                        rt.modifier_engine.dispatch_event("OnListenTurnBegin", param_entity_id=cur_ent.name)
            return
        for ent in self.sim.entities:
            if not ent.is_enemy and ent.current_hp > 0:
                kit = getattr(ent, "kit", None)
                if kit is not None and hasattr(kit, "_resolve_talent_heal"):
                    kit._resolve_talent_heal()

    def _check_aha_special_damage_events(self) -> None:
        handler = getattr(self.sim, "aha_special_handler", None)
        if handler is not None:
            handler(self)

    def _init_wave_monster_battle_events(self, entities: Sequence[Entity], wave_index: int) -> None:
        """通用初始化当前波次怪物的 DynamicValues、触发 *PassiveSkillInitiate，并结算入场立即就绪的 BattleEvent（如 20041 进场召唤胚芽）。"""
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is None:
            return
        for ent in entities:
            kit = getattr(ent, "kit", None)
            if kit is not None and hasattr(kit, "_ensure_monster_dynamic_values"):
                kit._ensure_monster_dynamic_values(rt)
            try:
                mrs = self.runner.get_enemy_state(ent.name)
            except KeyError:
                continue
            for ab_name in getattr(mrs.blueprint, "ability_list", ()):
                if "PassiveSkillInitiate" in str(ab_name):
                    rt.trigger_ability(
                        caster_id=ent.name,
                        ability_name=str(ab_name),
                        target_ids=(ent.name,),
                    )

        # 若怪物 PassiveSkillInitiate 创建了 OnAdd 立即置零跑道 (distance_remaining == 0) 的 BattleEvent (如 20041)，
        # 按官方波次进场时序立即触发其 OnPhase1 + drain 并将距离重置为 10000.0
        for be_name in list(rt.named_targets.get("BattleEventEntityList", ())):
            be_ent = self.sim.get_entity(be_name)
            if (
                be_ent is not None
                and getattr(be_ent, "is_countdown", False)
                and be_ent.distance_remaining <= 1e-6
            ):
                if hasattr(self.sim, "_ready_queue") and be_name in self.sim._ready_queue:
                    self.sim._ready_queue.remove(be_name)
                if hasattr(self.sim, "_natural_due_names"):
                    self.sim._natural_due_names.discard(be_name)
                rt.modifier_engine.dispatch_event("OnPhase1", owner_id=be_name)
                sched = getattr(self.sim, "scheduler", None)
                if sched is not None and sched.has_pending():
                    prev_d = getattr(sched, "_action_frame_depth", 0)
                    sched._action_frame_depth = 0
                    try:
                        sched.drain()
                    finally:
                        sched._action_frame_depth = prev_d
                be_ent.distance_remaining = 10000.0
        self.sync_spawned_entities()

    def _on_turn_begin(self, event: TurnBeginEvent) -> None:
        self._check_aha_special_damage_events()
        self._break_helper.on_turn_begin(event)
        actor_ent = self.sim.get_entity(event.actor_name)
        if actor_ent is not None and getattr(actor_ent, "is_countdown", False):
            sched = getattr(self.sim, "scheduler", None)
            if sched is not None and sched.has_pending():
                prev_d = getattr(sched, "_action_frame_depth", 0)
                sched._action_frame_depth = 0
                try:
                    sched.drain()
                finally:
                    sched._action_frame_depth = prev_d
                self.sync_spawned_entities()

    @property
    def wave(self) -> int:
        return self.runner.state.wave_index + 1

    def _get_ai_spec(self, monster_id: int, wave_index: int) -> CompiledMonsterAISpec:
        if monster_id in self._ai_cache:
            return self._ai_cache[monster_id]
        src_wave = self.runner.built_stage.source_spec.waves[wave_index]
        for m in src_wave.monsters:
            if m.monster_id == monster_id:
                spec = self.ai_loader.compile_monster_ai(m)
                self._ai_cache[monster_id] = spec
                return spec
        if monster_id in src_wave.summon_monsters:
            spec = self.ai_loader.compile_monster_ai(src_wave.summon_monsters[monster_id])
            self._ai_cache[monster_id] = spec
            return spec
        try:
            m_spec = self.runner.factory.stage_loader.compile_monster(
                monster_id, level=src_wave.monster_level
            )
            spec = self.ai_loader.compile_monster_ai(m_spec)
            self._ai_cache[monster_id] = spec
            return spec
        except Exception:
            pass
        raise KeyError(f"Monster {monster_id} not found in wave {wave_index} of stage {self.stage_id}")

    def _sync_enemy_order(self) -> None:
        living_runner_enemies = [m.entity for m in self.runner.state.enemies if m.entity.current_hp > 0.0]
        runner_enemy_names = {e.name for e in living_runner_enemies}
        allies = [e for e in self.sim.entities if not getattr(e, "is_enemy", False)]
        other_enemies = [e for e in self.sim.entities if getattr(e, "is_enemy", False) and e.name not in runner_enemy_names]
        self.sim.entities[:] = allies + living_runner_enemies + other_enemies
        if hasattr(self.sim, "_rebuild_entity_cache"):
            self.sim._rebuild_entity_cache()

    def sync_spawned_entities(self) -> List[Entity]:
        sim_names = {e.name for e in self.sim.entities}
        new_entities = [
            mrs.entity
            for mrs in self.runner.state.enemies
            if mrs.entity.name not in sim_names and mrs.entity.current_hp > 0.0
        ]
        if new_entities:
            new_entities.sort(key=lambda e: getattr(e, "_runner_spawn_order", 0))
            self.attach_kits_to_entities(new_entities, self.runner.state.wave_index)
            rt = getattr(self.sim, "vm_runtime", None)
            for ent in new_entities:
                self.sim.add_entity(ent, trigger_battle_start=True)
                if getattr(ent, "kit", None) is not None:
                    ent.kit.port = self.port
                    if rt is not None and hasattr(ent.kit, "_ensure_monster_dynamic_values"):
                        ent.kit._ensure_monster_dynamic_values(rt)
                if rt is not None:
                    try:
                        mrs = self.runner.get_enemy_state(ent.name)
                    except KeyError:
                        mrs = None
                    if mrs is not None:
                        for ab_name in getattr(mrs.blueprint, "ability_list", ()):
                            if "PassiveSkillInitiate" in str(ab_name):
                                rt.trigger_ability(
                                    caster_id=ent.name,
                                    ability_name=str(ab_name),
                                    target_ids=(ent.name,),
                                )
            self._sync_enemy_order()
        return new_entities

    def attach_kits_to_entities(self, entities: Sequence[Entity], wave_index: int) -> None:
        for ent in entities:
            mid = int(getattr(ent, "monster_id", 0))
            if mid <= 0:
                continue
            ai_spec = self._get_ai_spec(mid, wave_index)
            ent.kit = DataDrivenEnemyKit(
                owner_id=ent.name,
                port=self.port,
                ai_spec=ai_spec,
                runner=self.runner,
            )

    def summon_enemy(
        self,
        caster_name: str,
        summon_task: Mapping[str, Any],
        *,
        dynamic_resolver: Optional[Any] = None,
    ) -> List[Entity]:
        spawned = self.runner.execute_summon_monster(
            caster_name,
            summon_task,
            dynamic_resolver=dynamic_resolver,
        )
        widx = self.runner.state.wave_index
        self.attach_kits_to_entities(spawned, widx)
        rt = getattr(self.sim, "vm_runtime", None)
        for ent in spawned:
            self.sim.add_entity(ent, trigger_battle_start=True)
            if rt is not None and getattr(ent, "kit", None) is not None and hasattr(ent.kit, "_ensure_monster_dynamic_values"):
                ent.kit._ensure_monster_dynamic_values(rt)
            if rt is not None:
                try:
                    mrs = self.runner.get_enemy_state(ent.name)
                except KeyError:
                    mrs = None
                if mrs is not None:
                    for ab_name in getattr(mrs.blueprint, "ability_list", ()):
                        if "PassiveSkillInitiate" in str(ab_name):
                            rt.trigger_ability(
                                caster_id=ent.name,
                                ability_name=str(ab_name),
                                target_ids=(ent.name,),
                            )
        self._sync_enemy_order()
        return spawned

    def _resolve_enemy_target(self, target_name: str) -> Optional[Entity]:
        ent = self.sim.get_entity(target_name)
        if ent is not None and ent.current_hp > 0:
            return ent
        if "_g1_" in target_name:
            alt = target_name.replace("_g1_", "_")
            ent = self.sim.get_entity(alt)
            if ent is not None and ent.current_hp > 0:
                return ent
        elif "_g2_" in target_name:
            alt = target_name.replace("_g2_", "_")
            ent = self.sim.get_entity(alt)
            if ent is not None and ent.current_hp > 0:
                return ent
        for e in self.sim.entities:
            if e.is_enemy and e.current_hp > 0 and e.name == target_name:
                return e
        return None

    def apply_aha_hp_damage(self, target_name: str, dmg: float) -> float:
        self._pending_aha_turn = True
        av_key = round(float(self.sim.current_av), 2)
        if av_key not in self._published_aha_turn_avs:
            self._published_aha_turn_avs.add(av_key)
            self.sim._turn_seq = getattr(self.sim, "_turn_seq", 0) + 1
            self.sim.event_bus.publish(
                TurnBeginEvent(
                    av=av_key,
                    cycle=int(self.sim.current_cycle),
                    actor_id="阿哈",
                    actor_name="阿哈",
                    speed=0.0,
                    turn_id=self.sim._turn_seq,
                )
            )
        ent = self._resolve_enemy_target(target_name)
        if ent is None or ent.current_hp <= 0:
            return 0.0
        if not hasattr(self, "_aha_hit_enemies"):
            self._aha_hit_enemies: set[str] = set()
        self._aha_hit_enemies.add(ent.name)
        if dmg <= 0.0:
            return 0.0
        kit = getattr(ent, "kit", None)
        effective_dmg = dmg
        if kit is not None and hasattr(kit, "intercept_incoming_damage"):
            effective_dmg = kit.intercept_incoming_damage(ent.name, dmg)
        actual = min(ent.current_hp, effective_dmg)
        ent.current_hp = max(0.0, ent.current_hp - effective_dmg)
        self.aha_special_damage += dmg
        if actual > 0.0:
            self._break_helper.add_quantum_stack(ent.name)
            vm_rt = getattr(self.sim, "vm_runtime", None)
            if vm_rt is not None:
                vm_rt.modifier_engine.dispatch_event("OnHPChange", owner_id=ent.name, param_entity_id="阿哈")
                try:
                    mrs = self.runner.get_enemy_state(ent.name)
                    if getattr(mrs, "_limbo_pending", False):
                        setattr(mrs, "_limbo_pending", False)
                        vm_rt.modifier_engine.dispatch_event("OnLimboWaitHeal", owner_id=ent.name, param_entity_id="阿哈")
                except KeyError:
                    pass
        if ent.current_hp <= 0.0:
            vm_rt = getattr(self.sim, "vm_runtime", None)
            if vm_rt is not None:
                vm_rt.modifier_engine.dispatch_event("OnBeforeDying", owner_id=ent.name, param_entity_id="阿哈")
                vm_rt.modifier_engine.destroy_all_for_entity(ent.name)
            self.sim.event_bus.publish(
                EnemyDefeatedEvent(
                    av=float(self.sim.current_av),
                    cycle=int(self.sim.current_cycle),
                    attacker_name="阿哈",
                    target_name=ent.name,
                )
            )
            self.runner.state.enemies = [
                m for m in self.runner.state.enemies if m.entity.name != ent.name
            ]
            self.sim.entities[:] = [
                e for e in self.sim.entities if e is not ent
            ]
        return actual

    def apply_aha_ally_chip_hit(self, target_name: str) -> None:
        """阿哈回合伴生 1.0 基础伤害 (Lv.95 DEF 减免) 与 +2.0 基础受击回能。"""
        self._pending_aha_turn = True
        ent = self.sim.get_entity(target_name)
        if ent is None or ent.current_hp <= 0:
            return
        sm = getattr(self.sim, "status_mgr", None)
        def_val = (
            sm.calculate_stat(ent.name, getattr(ent, "base_def", 1000.0), StatType.DEF)
            if sm is not None
            else getattr(ent, "base_def", 1000.0)
        )
        atk_lvl_coeff = 95 * 10 + 200
        dmg = 1.0 * atk_lvl_coeff / (atk_lvl_coeff + max(0.0, def_val))
        actual = min(max(0.0, ent.current_hp - 1.0), dmg) if ent.current_hp > 1.0 else 0.0
        ent.current_hp = max(1.0, ent.current_hp - dmg) if ent.current_hp > 0.0 else 0.0
        if actual > 0.0:
            vm_rt = getattr(self.sim, "vm_runtime", None)
            if vm_rt is not None:
                vm_rt._open_enemy_attack = "阿哈"
                vm_rt.modifier_engine.dispatch_event("OnBeforeBeingHitAll", owner_id=ent.name, param_entity_id="阿哈")
                self.sim.event_bus.publish(HPLostEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=self.sim.current_cycle,
                    entity_name=ent.name,
                    amount=actual,
                    hp_left=ent.current_hp,
                    cause="attack_damage",
                ))
                vm_rt.modifier_engine.dispatch_event("OnAfterBeingHitAll", owner_id=ent.name, param_entity_id="阿哈")
            else:
                for ally in self.sim.entities:
                    kit = getattr(ally, "kit", None)
                    if kit is not None and hasattr(kit, "on_hp_lost"):
                        kit.on_hp_lost(ent.name, actual, cause="attack_damage")
        energy_target = ent
        if getattr(ent, "is_memosprite", False) and getattr(ent, "max_energy", 0.0) <= 0.0:
            master_name = getattr(ent, "master_name", None)
            if master_name:
                m_ent = self.sim.get_entity(master_name)
                if m_ent is not None:
                    energy_target = m_ent
        if hasattr(energy_target, "gain_sp"):
            energy_target.gain_sp(2.0)
        elif hasattr(energy_target, "energy") and hasattr(energy_target, "max_energy"):
            err = (
                sm.calculate_stat(energy_target.name, getattr(energy_target, "base_err", 1.0), StatType.ERR)
                if sm is not None
                else getattr(energy_target, "base_err", 1.0)
            )
            energy_target.energy = min(energy_target.max_energy, energy_target.energy + 2.0 * err)

    def trigger_monster_phase_transition(
        self,
        monster_name: str,
        *,
        mode: str = "Inc",
        value: Optional[int] = None,
    ) -> int:
        new_phase = self.runner.set_monster_phase(monster_name, mode=mode, value=value)
        ent = self.sim.get_entity(monster_name)
        if ent is not None and isinstance(getattr(ent, "kit", None), DataDrivenEnemyKit):
            ent.kit.sync_phase(new_phase)
        return new_phase

    def after_step(self) -> None:
        # 0. Aha cycle check & special damage check
        self._check_cycle_aha_extra_turn()
        self._check_aha_special_damage_events()

        # 1. Cycle boundary check
        cur_cycle = self.sim.current_cycle
        if cur_cycle > self._last_cycle:
            self._last_cycle = cur_cycle
            self.runner.on_cycle_boundary(cur_cycle, current_av=self.sim.current_av)

        # 2. Enforce LockHP on active enemies
        for mrs in list(self.runner.state.enemies):
            if mrs.lock_hp_ratio is not None and mrs.entity.current_hp > 0.0:
                self.runner.enforce_lock_hp(mrs.entity.name)

        # 3. Infinite wave slot refill if wave not yet cleared
        src_wave = self.runner.built_stage.source_spec.waves[self.runner.state.wave_index]
        if (
            self.runner.built_stage.source_spec.stage_infinite_group_id is not None
            and src_wave.max_monster_count > 0
            and 0 < len(self.runner.living_enemies()) < src_wave.max_monster_count
        ):
            refilled = self.runner.refill_infinite_wave_slot()
            self.attach_kits_to_entities(refilled, self.runner.state.wave_index)
            for ent in refilled:
                self.sim.add_entity(ent, trigger_battle_start=True)

        # 4. Wave clearance & transition
        if not self.runner.living_enemies():
            # Remove defeated enemies from TurnSimulator's active entities before spawning next wave
            next_wave_entities = self.runner.advance_wave_if_cleared(current_av=self.sim.current_av)
            if next_wave_entities is not None:
                self._wave_start_av = float(self.sim.current_av)
                self.sim.entities[:] = [
                    e for e in self.sim.entities if not e.is_enemy or e.current_hp > 0.0
                ]
                if self._is_moc:
                    for ent in self.sim.entities:
                        if (
                            not ent.is_enemy
                            and ent.current_hp > 0.0
                            and ent.speed > 0.0
                            and ent.distance_remaining < 1e5
                        ):
                            ent.distance_remaining = 10000.0
                    if hasattr(self.sim, "_ready_queue"):
                        self.sim._ready_queue.clear()
                self.attach_kits_to_entities(next_wave_entities, self.runner.state.wave_index)
                for ent in next_wave_entities:
                    self.sim.add_entity(ent, trigger_battle_start=True)
                    if getattr(ent, "kit", None) is not None:
                        ent.kit.port = self.port
                rt = getattr(self.sim, "vm_runtime", None)
                if rt is not None:
                    # 官方 AST 规范（如 Tribbie OnWaveMonster 监听）：波次怪物入场时派发 OnWaveMonster，
                    # 激活跨波次挂起的追击/插入行动（如 OnInsertAbort_Flg 追击），并在召唤辅助实体前优先结算
                    rt.modifier_engine.dispatch_event("OnWaveMonster")
                    sched = getattr(self.sim, "scheduler", None)
                    if sched is not None and sched.can_auto_drain():
                        sched.drain()
                self._init_wave_monster_battle_events(next_wave_entities, self.runner.state.wave_index)
                if rt is not None:
                    # 官方日志实证（220255 L1336、221208 L1461）：新波次入场会触发一次 turn_owner=null 的 OnTurnBegin，
                    # 用于重置各角色每回合限制标记（如知更鸟 MAvatar_RobinS_00_Passive_HyperCharge_TurnFlag）。
                    rt.modifier_engine.dispatch_event("OnListenTurnBegin", param_entity_id="__LEVEL__")


def build_data_driven_stage(
    stage_id: int,
    team: List[Entity],
    *,
    technique_users: Optional[Sequence[str]] = None,
    auto_ult: bool = True,
) -> Tuple[TurnSimulator, DataDrivenStageDirector]:
    """Build a ``(TurnSimulator, DataDrivenStageDirector)`` purely from official stage tables."""
    for member in team:
        if (
            not getattr(member, "is_enemy", False)
            and getattr(member, "max_energy", 0.0) > 0
            and getattr(member, "energy", 0.0) == 0.0
        ):
            member.energy = member.max_energy * 0.5

    runner = StageRunner(stage_id)
    ai_loader = StageAILoader(stage_loader=runner.factory.stage_loader)
    wave0_enemies = runner.start_stage()

    if team:
        raw_elem = getattr(team[0], "element", None)
        entry_elem = str(raw_elem).capitalize() if raw_elem else None
        if entry_elem:
            for e in wave0_enemies:
                if entry_elem in getattr(e, "weaknesses", ()):
                    e.current_toughness = max(0.0, e.current_toughness - 10.0)

    sim = TurnSimulator(
        entities=list(team) + list(wave0_enemies),
        use_techniques=bool(technique_users),
        technique_users=list(technique_users) if technique_users is not None else None,
        auto_ult=auto_ult,
    )
    director = DataDrivenStageDirector(sim, runner, ai_loader)
    director.attach_kits_to_entities(wave0_enemies, wave_index=0)
    return sim, director

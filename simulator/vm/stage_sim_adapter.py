"""Read-only adapter bridging StageFactory / StageRunner / StageAILoader to TurnSimulator.

Provides a pure data-driven ``EnemyKit`` (``DataDrivenEnemyKit``) and
``StageDirector`` (``DataDrivenStageDirector``) + ``build_data_driven_stage()``
without modifying ``core.py``, ``stage_30126122.py``, or ``kits/enemies/*``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.core import Entity, TurnSimulator
from simulator.damage import DamageRequest
from simulator.effects import ApplyDamageEffect
from simulator.events import EnemyDefeatedEvent, HPLostEvent, TurnBeginEvent, WeaknessBreakEvent
from simulator.kits.enemies.base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from simulator.kits.enemies.sim_port import BaseEnemyCombatPortImpl
from simulator.stage_director import AnomalyWaveMode, BreakStatusHelper, MoCWaveMode
from simulator.status import StatType
from simulator.vm.stage_ai import (
    AISkillActionSpec,
    CompiledMonsterAISpec,
    MonsterAIExecutor,
    StageAILoader,
)
from simulator.vm.stage_runner import StageRunner


class DataDrivenEnemyKit(EnemyKit):
    """Pure data-driven ``EnemyKit`` backed by ``CompiledMonsterAISpec`` & ``StageRunner``."""

    def __init__(
        self,
        owner_id: str,
        port: BaseEnemyCombatPortImpl,
        ai_spec: CompiledMonsterAISpec,
        runner: StageRunner,
    ) -> None:
        super().__init__(owner_id=owner_id, port=port)
        self.enemy_port = port
        self.ai_spec = ai_spec
        self.ai_executor = MonsterAIExecutor(ai_spec)
        self.runner = runner
        self.executed_skills: List[str] = []

    def sync_phase(self, phase: int) -> None:
        if self.ai_executor.phase != phase:
            self.ai_executor.set_phase(phase, reset_ai_flag=1)

    def _select_targets(self, sim: TurnSimulator, selector: str) -> List[Entity]:
        allies = [
            e
            for e in sim.entities
            if not e.is_enemy
            and not getattr(e, "is_countdown", False)
            and e.current_hp > 0.0
        ]
        if not allies:
            return []
        if "All" in selector or "Team" in selector:
            return allies
        return [allies[0]]

    def _get_entry_ability_name(self, skill_key: str) -> Optional[str]:
        mrs = self.runner.get_enemy_state(self.owner_id)
        tpl_id = mrs.blueprint.monster_template_id
        trow = self.runner.factory.stage_loader.monster_templates.get(tpl_id, {})
        json_path = trow.get("JsonConfig", "")
        if not json_path:
            return None
        char_cfg = self.runner.factory.stage_loader._load_char_config(json_path)
        for sk_entry in char_cfg.get("SkillList", []):
            if sk_entry.get("Name") == skill_key:
                return sk_entry.get("EntryAbility")
        return None

    def _execute_ability_tasks(
        self, ability_name: str, visited: Optional[set[str]] = None
    ) -> None:
        if visited is None:
            visited = set()
        if ability_name in visited:
            return
        visited.add(ability_name)

        game_loader = getattr(self.runner.factory, "game_loader", None)
        if game_loader is None:
            from simulator.vm.loader import GameDataLoader

            game_loader = GameDataLoader()
            setattr(self.runner.factory, "game_loader", game_loader)
        ab = game_loader.get_ability(ability_name)
        if not ab:
            return
        for t in ab.get("OnStart", []):
            tt = t.get("$type", "")
            if tt == "RPG.GameCore.TriggerAbility":
                child_name = t.get("AbilityName", {}).get("Value")
                if child_name and "Camera" not in child_name:
                    self._execute_ability_tasks(child_name, visited=visited)
            elif tt == "RPG.GameCore.PredicateTaskList":
                for st in t.get("SuccessTaskList", []):
                    self.runner.execute_stage_task(st, caster_name=self.owner_id)
            else:
                self.runner.execute_stage_task(t, caster_name=self.owner_id)

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        sim: TurnSimulator = self.port.sim
        self.runner.on_turn_begin(self.owner_id, current_av=sim.current_av)

        # Keep AI phase synchronized with StageRunner's MonsterRuntimeState
        mrs = self.runner.get_enemy_state(self.owner_id)
        if self.ai_executor.phase != mrs.phase:
            self.ai_executor.set_phase(mrs.phase, reset_ai_flag=1)

        rank = getattr(mrs.blueprint, "rank", "")
        num_actions = 2 if rank in ("Elite", "Boss", "BigBoss") else 1

        attacker = sim.get_entity(self.owner_id)
        for _ in range(num_actions):
            actions: Tuple[AISkillActionSpec, ...] = self.ai_executor.select_next_actions()
            if not actions:
                break
            for sk in actions:
                self.executed_skills.append(sk.skill_trigger_key)

                # 1. Execute official ConfigAbility AST tasks (e.g. SummonMonster)
                entry_ab = self._get_entry_ability_name(sk.skill_trigger_key)
                if entry_ab:
                    self._execute_ability_tasks(entry_ab)

                # 2. Sync any newly spawned monsters to TurnSimulator
                director = getattr(sim, "_stage_director", None)
                if director and hasattr(director, "sync_spawned_entities"):
                    director.sync_spawned_entities()

                # 3. Apply skill damage
                mult = sk.param(0, default=0.0)
                if sk.is_passive or mult <= 0.0 or attacker is None:
                    continue
                targets = self._select_targets(sim, sk.target_selector)
                elem = sk.element or "Physical"
                hit_energy = getattr(attacker, "hit_energy", 5.0) or 5.0
                target_ids = tuple(t.name for t in targets)
                resolved = self.enemy_port.apply_enemy_attack(
                    owner_id=self.owner_id,
                    target_ids=target_ids,
                    multiplier=mult,
                    element=elem,
                    hit_energy=hit_energy,
                    hits=1,
                    blast=(sk.target_selector == "adjacent"),
                    increment_action_seq=True,
                )
                self.enemy_port.finish_enemy_being_hit(
                    owner_id=self.owner_id,
                    target_ids=resolved,
                )

        self.runner.on_turn_end(self.owner_id, current_av=sim.current_av)
        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def get_kit_state(self) -> Dict[str, Any]:
        return {
            "monster_id": self.ai_spec.monster_id,
            "phase": self.ai_executor.phase,
            "ai_flag": self.ai_executor.ai_flag,
            "executed_skills": list(self.executed_skills),
        }


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

        self.sim.event_bus.subscribe(WeaknessBreakEvent, self._break_helper.on_weakness_break)
        setattr(self.sim, "_stage_director", self)

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

    def sync_spawned_entities(self) -> List[Entity]:
        sim_names = {e.name for e in self.sim.entities}
        new_entities = [
            mrs.entity
            for mrs in self.runner.state.enemies
            if mrs.entity.name not in sim_names and mrs.entity.current_hp > 0.0
        ]
        if new_entities:
            self.attach_kits_to_entities(new_entities, self.runner.state.wave_index)
            for ent in new_entities:
                self.sim.add_entity(ent, trigger_battle_start=True)
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
    ) -> List[Entity]:
        spawned = self.runner.execute_summon_monster(caster_name, summon_task)
        widx = self.runner.state.wave_index
        self.attach_kits_to_entities(spawned, widx)
        for ent in spawned:
            self.sim.add_entity(ent, trigger_battle_start=True)
        return spawned

    def _resolve_enemy_target(self, target_name: str) -> Optional[Entity]:
        ent = self.sim.get_entity(target_name)
        if ent is not None and ent.current_hp > 0:
            return ent
        # Check alias (e.g. 流星铁鹰_g1_2 -> 流星铁鹰_2)
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
        kit = getattr(ent, "kit", None)
        effective_dmg = dmg
        if kit is not None and hasattr(kit, "intercept_incoming_damage"):
            effective_dmg = kit.intercept_incoming_damage(ent.name, dmg)
        actual = min(ent.current_hp, effective_dmg)
        ent.current_hp = max(0.0, ent.current_hp - effective_dmg)
        self.aha_special_damage += dmg
        if actual > 0.0:
            self._break_helper.add_quantum_stack(ent.name)
        if ent.current_hp <= 0.0:
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
            energy_target.energy = min(energy_target.max_energy, energy_target.energy + 2.0)

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
    sim.enemy_uid_map = {100009: "月夜天马", 100011: "正阳狮鹫"}
    director = DataDrivenStageDirector(sim, runner, ai_loader)
    director.attach_kits_to_entities(wave0_enemies, wave_index=0)
    return sim, director

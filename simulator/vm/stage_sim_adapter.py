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
from simulator.events import WeaknessBreakEvent
from simulator.kits.enemies.base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from simulator.kits.enemies.sim_port import BaseEnemyCombatPortImpl
from simulator.stage_director import AnomalyWaveMode, BreakStatusHelper, MoCWaveMode
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

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        sim: TurnSimulator = self.port.sim
        self.runner.on_turn_begin(self.owner_id, current_av=sim.current_av)

        # Keep AI phase synchronized with StageRunner's MonsterRuntimeState
        mrs = self.runner.get_enemy_state(self.owner_id)
        if self.ai_executor.phase != mrs.phase:
            self.ai_executor.set_phase(mrs.phase, reset_ai_flag=1)

        actions: Tuple[AISkillActionSpec, ...] = self.ai_executor.select_next_actions()
        attacker = sim.get_entity(self.owner_id)
        if attacker is not None:
            for sk in actions:
                self.executed_skills.append(sk.skill_trigger_key)
                mult = sk.param(0, default=0.0)
                if sk.is_passive or mult <= 0.0:
                    continue
                targets = self._select_targets(sim, sk.target_selector)
                elem = sk.element or "Physical"
                for tgt in targets:
                    req = DamageRequest(
                        attacker=attacker,
                        target=tgt,
                        skill_multiplier=mult,
                    )
                    sim.resolver.enqueue(
                        ApplyDamageEffect(
                            request=req,
                            toughness_reduction=0.0,
                            element=elem,
                        )
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
        raise KeyError(f"Monster {monster_id} not found in wave {wave_index} of stage {self.stage_id}")

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
    auto_ult: bool = False,
) -> Tuple[TurnSimulator, DataDrivenStageDirector]:
    """Build a ``(TurnSimulator, DataDrivenStageDirector)`` purely from official stage tables."""
    runner = StageRunner(stage_id)
    ai_loader = StageAILoader(stage_loader=runner.factory.stage_loader)
    wave0_enemies = runner.start_stage()

    sim = TurnSimulator(
        entities=list(team) + list(wave0_enemies),
        use_techniques=bool(technique_users),
        technique_users=list(technique_users) if technique_users is not None else None,
        auto_ult=auto_ult,
    )
    director = DataDrivenStageDirector(sim, runner, ai_loader)
    director.attach_kits_to_entities(wave0_enemies, wave_index=0)
    return sim, director

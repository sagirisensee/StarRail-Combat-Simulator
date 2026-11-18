"""Data-driven Stage Runtime & Boss State-Machine Bridge (Phase 3).

Bridges ``StageFactory`` / ``BuiltStageSpec`` into executable simulator state
without modifying ``core.py``, ``executor.py``, ``stage_30126122.py``, or
existing enemy kits.

Supports:
- Wave progression & multi-subgroup / InfiniteEliteGroup wave scheduling (30126122 & 30510021)
- Monster multi-phase transitions (``LockHP``, ``SetMonsterPhase``, ``ByCompareMonsterPhase``)
- In-combat monster summoning (``SummonMonster`` with slot limit & ``KeepOnEdge`` placement)
- Break exit / toughness reset & temporary weakness stacking (``ExitBreakState``, ``ResetStance``, ``StackWeakness``)
- Custom event bus & cycle/wave boundary hooks (``TriggerCustomString``, ``on_cycle_boundary``, ``on_turn_begin``)
- UniqueName entity registry (``SetTargetUniqueName``, ``TargetFetchUniqueNameEntity``)
- Stage/monster predicates (``ByCheckCustomValueBool``, ``ByCompareBattleEventID``,
  ``ByCompareStageID``, ``ByCompareStageType``, ``ByCompareMonsterUniqueID``,
  ``ByCompareMonsterTemplateID``, ``ByInfiniteMonsterWaveLeft``, ``ByIsInElationTime``,
  ``ByCurrentSkillName``, ``ByIsDamageType``, ``ByCompareHP``, ``ByIsTargetAbleToAction``,
  ``ByIsTurnActionEntity``)
- BattleEvent initialization & turn countdown (30149 Elation, 30503 Infinite/CountDown, 20041)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.entity import Entity
from simulator.vm.expr import dotnet_hash, eval_dynamic_float
from simulator.vm.stage_factory import (
    BuiltStageSpec,
    CompiledBattleEventAbility,
    EnemyEntityBlueprint,
    StageFactory,
    normalize_element,
)
from simulator.vm.stage_prunable_types import is_safe_prunable_type

MAX_ENEMY_SLOTS = 5


def _compare_values(lhs: float, rhs: float, cmp_type: str) -> bool:
    eps = 1e-6
    if cmp_type == "Equal":
        return abs(lhs - rhs) <= eps
    if cmp_type == "NotEqual":
        return abs(lhs - rhs) > eps
    if cmp_type == "Greater":
        return lhs > rhs + eps
    if cmp_type == "GreaterEqual":
        return lhs >= rhs - eps
    if cmp_type == "Less":
        return lhs < rhs - eps
    if cmp_type == "LessEqual":
        return lhs <= rhs + eps
    raise ValueError(f"Unsupported CompareType: {cmp_type!r}")


def _unwrap_str(v: Any) -> str:
    if isinstance(v, Mapping):
        return str(v.get("Value", ""))
    return str(v or "")


@dataclass
class MonsterRuntimeState:
    """Mutable runtime state for a spawned enemy entity."""

    entity: Entity
    blueprint: EnemyEntityBlueprint
    phase: int = 1
    lock_hp_ratio: Optional[float] = None
    custom_bools: Dict[int, bool] = field(default_factory=dict)
    custom_values: Dict[int, Any] = field(default_factory=dict)
    abilities: List[str] = field(default_factory=list)
    summon_seq: int = 0
    stacked_weaknesses: List[str] = field(default_factory=list)
    base_damage_res: Dict[str, float] = field(default_factory=dict)

    @property
    def max_phase(self) -> int:
        return len(self.blueprint.phase_max_hps)


@dataclass
class BattleEventRuntimeState:
    """Mutable runtime state for an active BattleEvent (stage turbulence / countdown / summon)."""

    spec: CompiledBattleEventAbility
    dynamic_values: Dict[int, float] = field(default_factory=dict)
    turns_elapsed: int = 0
    active: bool = True


@dataclass
class StageRuntimeState:
    """Complete runtime state for a data-driven stage execution."""

    built_stage: BuiltStageSpec
    wave_index: int = 0
    enemies: List[MonsterRuntimeState] = field(default_factory=list)
    battle_events: Dict[int, BattleEventRuntimeState] = field(default_factory=dict)
    stage_custom_bools: Dict[int, bool] = field(default_factory=dict)
    stage_abilities: List[str] = field(default_factory=list)
    elation_points: float = 0.0
    in_elation_time: bool = False
    challenge_turns_elapsed: int = 0
    custom_events_triggered: List[str] = field(default_factory=list)
    current_av: float = 0.0
    current_cycle: int = 0
    wave_start_av: float = 0.0
    current_turn_actor: Optional[str] = None
    unique_name_map: Dict[str, List[str]] = field(default_factory=dict)
    special_outcome: Optional[str] = None


class StageRunner:
    """Pure data-driven stage runtime & Boss state-machine bridge."""

    def __init__(
        self,
        stage_id: int,
        *,
        factory: Optional[StageFactory] = None,
    ) -> None:
        self.factory = factory or StageFactory()
        self.built_stage = self.factory.build_stage(stage_id)
        self.state = StageRuntimeState(built_stage=self.built_stage)
        self._enemy_by_name: Dict[str, MonsterRuntimeState] = {}
        self._custom_event_handlers: Dict[str, List[Callable[[str, StageRuntimeState], None]]] = {}
        self._cycle_boundary_handlers: List[Callable[[int, float, StageRuntimeState], None]] = []
        self._wave_transition_handlers: List[Callable[[int, StageRuntimeState], None]] = []

    def _register_enemy(
        self,
        entity: Entity,
        blueprint: EnemyEntityBlueprint,
    ) -> MonsterRuntimeState:
        raw_cv: Mapping[str, Any] = {}
        for m in self.built_stage.source_spec.waves[self.state.wave_index].monsters:
            if m.monster_id == blueprint.monster_id:
                raw_cv = m.custom_values
                break
        if not raw_cv:
            wave_summons = self.built_stage.source_spec.waves[self.state.wave_index].summon_monsters
            if blueprint.monster_id in wave_summons:
                raw_cv = wave_summons[blueprint.monster_id].custom_values

        hashed_cv: Dict[int, Any] = {}
        for k, v in raw_cv.items():
            hashed_cv[dotnet_hash(k)] = v
        for idx, sid in enumerate(blueprint.summon_ids, start=1):
            hashed_cv.setdefault(dotnet_hash(f"SummonID{idx:02d}"), sid)

        mrs = MonsterRuntimeState(
            entity=entity,
            blueprint=blueprint,
            phase=1,
            custom_values=hashed_cv,
            abilities=list(blueprint.ability_list),
            base_damage_res=dict(getattr(entity, "damage_res", {})),
        )
        self.state.enemies.append(mrs)
        self._enemy_by_name[entity.name] = mrs
        return mrs

    def start_stage(self) -> List[Entity]:
        """Initialize wave 0 enemies and stage-level BattleEvents."""
        self.state.wave_index = 0
        self.state.enemies.clear()
        self._enemy_by_name.clear()
        self.state.battle_events.clear()
        self.state.current_av = 0.0
        self.state.current_cycle = 0
        self.state.wave_start_av = 0.0
        self.state.current_turn_actor = None
        self.state.unique_name_map.clear()
        self.state.special_outcome = None

        for be in self.built_stage.battle_events:
            dyn: Dict[int, float] = {}
            for idx, val in enumerate(be.param_list):
                dyn[idx] = val
            if be.battle_event_id == 30503 and len(be.param_list) >= 2:
                dyn[dotnet_hash("BattleEventTurnLeftParam")] = be.param_list[1]
            self.state.battle_events[be.battle_event_id] = BattleEventRuntimeState(
                spec=be,
                dynamic_values=dyn,
                active=True,
            )

        return self._spawn_wave(0)

    def _spawn_wave(self, wave_index: int) -> List[Entity]:
        self.state.wave_index = wave_index
        self.state.enemies.clear()
        self._enemy_by_name.clear()

        wave = self.built_stage.waves[wave_index]
        entities = wave.spawn_entities()
        for ent, bp in zip(entities, wave.enemies):
            self._register_enemy(ent, bp)
        return entities

    def get_enemy_state(self, name: str) -> MonsterRuntimeState:
        if name not in self._enemy_by_name:
            raise KeyError(f"Active enemy {name!r} not found in wave {self.state.wave_index}")
        return self._enemy_by_name[name]

    def living_enemies(self) -> List[Entity]:
        return [
            mrs.entity
            for mrs in self.state.enemies
            if mrs.entity.current_hp > 0.0
        ]

    # ------------------------------------------------------------------
    # 自定义事件总线、UniqueName 与波次/回合/周期边界触发器
    # ------------------------------------------------------------------
    def subscribe_custom_event(
        self,
        event_name: str,
        callback: Callable[[str, StageRuntimeState], None],
    ) -> None:
        self._custom_event_handlers.setdefault(event_name, []).append(callback)

    def emit_custom_event(self, event_name: str) -> None:
        if not event_name:
            return
        self.state.custom_events_triggered.append(event_name)
        if event_name == "Level_SpecialWin":
            self.state.special_outcome = "win"
        elif event_name == "Level_ManualLose":
            self.state.special_outcome = "lose"
        for cb in self._custom_event_handlers.get(event_name, ()):
            cb(event_name, self.state)
        for cb in self._custom_event_handlers.get("*", ()):
            cb(event_name, self.state)

    def subscribe_cycle_boundary(
        self,
        callback: Callable[[int, float, StageRuntimeState], None],
    ) -> None:
        self._cycle_boundary_handlers.append(callback)

    def subscribe_wave_transition(
        self,
        callback: Callable[[int, StageRuntimeState], None],
    ) -> None:
        self._wave_transition_handlers.append(callback)

    def register_unique_name(self, unique_name: str, entity_name: str) -> None:
        if not unique_name:
            return
        bucket = self.state.unique_name_map.setdefault(unique_name, [])
        if entity_name not in bucket:
            bucket.append(entity_name)

    def resolve_unique_name_entities(self, unique_name: str) -> List[Entity]:
        names = self.state.unique_name_map.get(unique_name, ())
        return [self._enemy_by_name[n].entity for n in names if n in self._enemy_by_name]

    def on_turn_begin(self, actor_name: str, current_av: float = 0.0) -> None:
        self.state.current_av = float(current_av)
        self.state.current_turn_actor = actor_name

    def on_turn_end(self, actor_name: str, current_av: float = 0.0) -> None:
        self.state.current_av = float(current_av)
        if self.state.current_turn_actor == actor_name:
            self.state.current_turn_actor = None

    def on_cycle_boundary(self, cycle_index: int, current_av: float = 0.0) -> None:
        self.state.current_av = float(current_av)
        self.state.current_cycle = int(cycle_index)
        for be_state in self.state.battle_events.values():
            if not be_state.active:
                continue
            be_state.turns_elapsed += 1
            turn_left_h = dotnet_hash("BattleEventTurnLeftParam")
            if turn_left_h in be_state.dynamic_values:
                be_state.dynamic_values[turn_left_h] = max(
                    0.0, be_state.dynamic_values[turn_left_h] - 1.0
                )
        for cb in self._cycle_boundary_handlers:
            cb(cycle_index, current_av, self.state)

    def execute_stack_weakness(
        self,
        target_name: str,
        weak_list: Sequence[str],
        *,
        op_type: str = "Add",
    ) -> Tuple[str, ...]:
        mrs = self.get_enemy_state(target_name)
        ent = mrs.entity
        norm_list = [normalize_element(w) for w in weak_list if w]
        if op_type in ("Add", "Protected"):
            for elem in norm_list:
                if elem not in ent.weaknesses:
                    ent.weaknesses.append(elem)
                    if elem not in mrs.stacked_weaknesses:
                        mrs.stacked_weaknesses.append(elem)
                if hasattr(ent, "damage_res") and isinstance(ent.damage_res, dict):
                    ent.damage_res[elem] = 0.0
        elif op_type == "Remove":
            for elem in norm_list:
                if elem in mrs.stacked_weaknesses:
                    mrs.stacked_weaknesses.remove(elem)
                if elem in ent.weaknesses and elem not in mrs.blueprint.weaknesses:
                    ent.weaknesses.remove(elem)
                    if hasattr(ent, "damage_res") and isinstance(ent.damage_res, dict):
                        ent.damage_res[elem] = mrs.base_damage_res.get(elem, 0.2)
        return tuple(ent.weaknesses)

    # ------------------------------------------------------------------
    # 波次切换与无尽波次补怪
    # ------------------------------------------------------------------
    def advance_wave_if_cleared(self, *, current_av: Optional[float] = None) -> Optional[List[Entity]]:
        """Advance to the next wave when all living enemies are defeated."""
        if any(mrs.entity.current_hp > 0.0 for mrs in self.state.enemies):
            return None
        next_idx = self.state.wave_index + 1
        if next_idx >= self.built_stage.num_waves:
            return None
        if current_av is not None:
            self.state.current_av = float(current_av)
            if self.built_stage.source_spec.stage_infinite_group_id is None:
                self.state.wave_start_av = float(current_av)
        entities = self._spawn_wave(next_idx)
        for cb in self._wave_transition_handlers:
            cb(next_idx, self.state)
        return entities

    def refill_infinite_wave_slot(self, max_slots: Optional[int] = None) -> List[Entity]:
        """Spawn replacement enemies in infinite waves using the current wave's EliteGroup."""
        src_wave = self.built_stage.source_spec.waves[self.state.wave_index]
        limit = max_slots or src_wave.max_monster_count or MAX_ENEMY_SLOTS
        living_count = len(self.living_enemies())
        if living_count >= limit:
            return []

        wave_bp = self.built_stage.waves[self.state.wave_index]
        spawned: List[Entity] = []
        idx = 0
        while living_count + len(spawned) < limit and wave_bp.enemies:
            bp = wave_bp.enemies[idx % len(wave_bp.enemies)]
            idx += 1
            suffix = len(self.state.enemies) + 1
            ent = bp.to_entity(name=f"{bp.name}_inf_{suffix}")
            self._register_enemy(ent, bp)
            spawned.append(ent)
        return spawned

    # ------------------------------------------------------------------
    # Boss 多阶段转换与锁血 (LockHP / SetMonsterPhase)
    # ------------------------------------------------------------------
    def apply_lock_hp(self, monster_name: str, threshold_ratio: float) -> None:
        mrs = self.get_enemy_state(monster_name)
        mrs.lock_hp_ratio = max(0.0, min(1.0, float(threshold_ratio)))

    def clear_lock_hp(self, monster_name: str) -> None:
        mrs = self.get_enemy_state(monster_name)
        mrs.lock_hp_ratio = None

    def enforce_lock_hp(self, monster_name: str) -> float:
        """Clamp entity HP to ``max_hp * lock_hp_ratio`` if LockHP is active."""
        mrs = self.get_enemy_state(monster_name)
        if mrs.lock_hp_ratio is not None and mrs.entity.current_hp > 0.0:
            floor_hp = mrs.entity.max_hp * mrs.lock_hp_ratio
            if mrs.entity.current_hp < floor_hp:
                mrs.entity.current_hp = floor_hp
        return mrs.entity.current_hp

    def set_monster_phase(
        self,
        monster_name: str,
        *,
        mode: str = "Inc",
        value: Optional[int] = None,
    ) -> int:
        """Execute ``RPG.GameCore.SetMonsterPhase``: advance phase & switch phase MaxHP."""
        mrs = self.get_enemy_state(monster_name)
        if mode == "Inc":
            new_phase = mrs.phase + 1
        elif mode == "Set" and value is not None:
            new_phase = int(value)
        else:
            new_phase = mrs.phase + 1

        new_phase = max(1, min(mrs.max_phase, new_phase))
        mrs.phase = new_phase
        mrs.lock_hp_ratio = None

        new_hp = mrs.blueprint.phase_max_hps[new_phase - 1]
        mrs.entity.max_hp = new_hp
        mrs.entity.current_hp = new_hp
        self.execute_reset_stance(monster_name, forbid_when_empty=False)
        return new_phase

    # ------------------------------------------------------------------
    # 破韧退出与韧性重置 (ExitBreakState / ResetStance)
    # ------------------------------------------------------------------
    def execute_exit_break_state(self, target_name: str) -> None:
        mrs = self.get_enemy_state(target_name)
        mrs.entity.is_broken = False

    def execute_reset_stance(
        self,
        target_name: str,
        *,
        forbid_when_empty: bool = False,
    ) -> None:
        mrs = self.get_enemy_state(target_name)
        if forbid_when_empty and mrs.entity.current_toughness <= 0.0:
            return
        mrs.entity.current_toughness = mrs.entity.max_toughness
        mrs.entity.is_broken = False

    # ------------------------------------------------------------------
    # 战斗中召唤 (SummonMonster)
    # ------------------------------------------------------------------
    def _resolve_monster_num(
        self,
        spec: Any,
        caster_mrs: Optional[MonsterRuntimeState],
        dynamic_resolver: Optional[Callable[[int], float]],
        default: float = 0.0,
    ) -> float:
        def _resolver(h: int) -> float:
            if caster_mrs is not None and h in caster_mrs.custom_values:
                val = caster_mrs.custom_values[h]
                if isinstance(val, (int, float)):
                    return float(val)
            if dynamic_resolver is not None:
                return float(dynamic_resolver(h))
            return 0.0

        return eval_dynamic_float(spec, _resolver, default)

    def execute_summon_monster(
        self,
        caster_name: str,
        task: Mapping[str, Any],
        *,
        dynamic_resolver: Optional[Callable[[int], float]] = None,
        max_slots: int = MAX_ENEMY_SLOTS,
    ) -> List[Entity]:
        """Execute ``RPG.GameCore.SummonMonster`` from official ConfigAbility AST."""
        caster_mrs = self.get_enemy_state(caster_name)
        data_list = task.get("SummonMonsterDataList", [])
        delay_ratio_override = task.get("DelayRatio")

        spawned: List[Entity] = []
        for entry in data_list:
            if len(self.living_enemies()) >= max_slots:
                break
            mid = int(
                round(
                    self._resolve_monster_num(
                        entry.get("MonsterID"),
                        caster_mrs,
                        dynamic_resolver,
                        default=0.0,
                    )
                )
            )
            if mid <= 0 and caster_mrs.blueprint.summon_ids:
                mid = caster_mrs.blueprint.summon_ids[0]
            if mid <= 0:
                continue

            bp = self.built_stage.get_summon_blueprint(mid, wave_index=self.state.wave_index)
            caster_mrs.summon_seq += 1
            summon_name = f"{bp.name}_{caster_mrs.summon_seq}"

            if delay_ratio_override is not None:
                dr = self._resolve_monster_num(
                    delay_ratio_override, caster_mrs, dynamic_resolver, default=bp.initial_delay_ratio
                )
                init_dist = 10000.0 * dr
            else:
                init_dist = bp.initial_distance

            ent = bp.to_entity(name=summon_name, initial_distance=init_dist)
            loc_type = str(entry.get("LocationType", ""))

            if loc_type == "KeepOnEdge":
                caster_idx = next(
                    (i for i, m in enumerate(self.state.enemies) if m.entity.name == caster_name),
                    len(self.state.enemies),
                )
                insert_left = (caster_mrs.summon_seq % 2 == 1)
                mrs = self._register_enemy(ent, bp)
                self.state.enemies.pop()
                insert_idx = max(0, caster_idx) if insert_left else min(len(self.state.enemies), caster_idx + 1)
                self.state.enemies.insert(insert_idx, mrs)
            else:
                self._register_enemy(ent, bp)

            spawned.append(ent)

        return spawned

    # ------------------------------------------------------------------
    # 官方 Stage/Monster Predicate & Task 桥接求值
    # ------------------------------------------------------------------
    def eval_stage_predicate(
        self,
        pred: Optional[Mapping[str, Any]],
        *,
        caster_name: Optional[str] = None,
        param_entity_name: Optional[str] = None,
        battle_event_id: Optional[int] = None,
        skill_name: Optional[str] = None,
        damage_type: Optional[str] = None,
        dynamic_resolver: Optional[Callable[[int], float]] = None,
    ) -> bool:
        if not pred:
            return True
        res = self._eval_stage_predicate_raw(
            pred,
            caster_name=caster_name,
            param_entity_name=param_entity_name,
            battle_event_id=battle_event_id,
            skill_name=skill_name,
            damage_type=damage_type,
            dynamic_resolver=dynamic_resolver,
        )
        if pred.get("Inverse"):
            return not res
        return res

    def _eval_stage_predicate_raw(
        self,
        pred: Mapping[str, Any],
        *,
        caster_name: Optional[str],
        param_entity_name: Optional[str],
        battle_event_id: Optional[int],
        skill_name: Optional[str],
        damage_type: Optional[str],
        dynamic_resolver: Optional[Callable[[int], float]],
    ) -> bool:
        t = pred.get("$type", "")

        if t == "RPG.GameCore.ByAnd":
            return all(
                self.eval_stage_predicate(
                    p,
                    caster_name=caster_name,
                    param_entity_name=param_entity_name,
                    battle_event_id=battle_event_id,
                    skill_name=skill_name,
                    damage_type=damage_type,
                    dynamic_resolver=dynamic_resolver,
                )
                for p in pred.get("PredicateList", [])
            )

        if t == "RPG.GameCore.ByAny":
            return any(
                self.eval_stage_predicate(
                    p,
                    caster_name=caster_name,
                    param_entity_name=param_entity_name,
                    battle_event_id=battle_event_id,
                    skill_name=skill_name,
                    damage_type=damage_type,
                    dynamic_resolver=dynamic_resolver,
                )
                for p in pred.get("PredicateList", [])
            )

        if t == "RPG.GameCore.ByNot":
            return not self.eval_stage_predicate(
                pred.get("Predicate"),
                caster_name=caster_name,
                param_entity_name=param_entity_name,
                battle_event_id=battle_event_id,
                skill_name=skill_name,
                damage_type=damage_type,
                dynamic_resolver=dynamic_resolver,
            )

        target_name = caster_name
        tgt_spec = pred.get("TargetType")
        if isinstance(tgt_spec, Mapping):
            alias = str(tgt_spec.get("Alias", ""))
            if alias == "ParamEntity" and param_entity_name:
                target_name = param_entity_name
            elif alias in ("Caster", "ModifierOwnerEntity") and caster_name:
                target_name = caster_name

        mrs = self._enemy_by_name.get(target_name) if target_name else None

        if t == "RPG.GameCore.ByCompareMonsterPhase":
            lhs = float(mrs.phase) if mrs is not None else 1.0
            rhs = eval_dynamic_float(pred.get("CompareValue"), dynamic_resolver or (lambda _: 0.0), 1.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareStageID":
            rhs = eval_dynamic_float(pred.get("StageID"), dynamic_resolver or (lambda _: 0.0), 0.0)
            return _compare_values(float(self.built_stage.stage_id), rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareStageType":
            return self.built_stage.stage_type == str(pred.get("CurrentStageType", ""))

        if t == "RPG.GameCore.ByCompareBattleEventID":
            rhs = int(round(eval_dynamic_float(pred.get("TargetBattleEventID"), dynamic_resolver or (lambda _: 0.0), 0.0)))
            if battle_event_id is not None:
                return battle_event_id == rhs
            return rhs in self.state.battle_events

        if t == "RPG.GameCore.ByCompareMonsterTemplateID":
            rhs = int(round(eval_dynamic_float(pred.get("TargetMonsterTemplateID"), dynamic_resolver or (lambda _: 0.0), 0.0)))
            return bool(mrs is not None and mrs.blueprint.monster_template_id == rhs)

        if t == "RPG.GameCore.ByCompareMonsterUniqueID":
            rhs = int(round(eval_dynamic_float(pred.get("TargetMonsterUniqueID"), dynamic_resolver or (lambda _: 0.0), 0.0)))
            return bool(mrs is not None and mrs.blueprint.monster_id == rhs)

        if t == "RPG.GameCore.ByCheckCustomValueBool":
            key_obj = pred.get("Key", {})
            key_hash = int(key_obj.get("Hash", 0)) if isinstance(key_obj, Mapping) else dotnet_hash(str(key_obj))
            if mrs is not None and key_hash in mrs.custom_bools:
                return mrs.custom_bools[key_hash]
            return self.state.stage_custom_bools.get(key_hash, False)

        if t == "RPG.GameCore.ByInfiniteMonsterWaveLeft":
            waves_left = max(0, self.built_stage.num_waves - 1 - self.state.wave_index)
            rhs = eval_dynamic_float(pred.get("CompareValue"), dynamic_resolver or (lambda _: 0.0), 0.0)
            return _compare_values(float(waves_left), rhs, str(pred.get("CompareType", "Greater")))

        if t == "RPG.GameCore.ByIsInElationTime":
            return self.state.in_elation_time

        if t == "RPG.GameCore.ByCurrentSkillName":
            return bool(skill_name and skill_name == _unwrap_str(pred.get("SkillName")))

        if t == "RPG.GameCore.ByIsDamageType":
            if not damage_type:
                return False
            norm_dt = normalize_element(damage_type)
            allowed = {normalize_element(str(d)) for d in pred.get("DamageTypeList", [])}
            if not allowed and "DamageType" in pred:
                dt_val = pred["DamageType"]
                if isinstance(dt_val, Mapping):
                    allowed.add(normalize_element(str(dt_val.get("DamageType", ""))))
                else:
                    allowed.add(normalize_element(str(dt_val)))
            return norm_dt in allowed

        if t == "RPG.GameCore.ByCompareHP":
            lhs = float(mrs.entity.current_hp) if mrs is not None else 0.0
            rhs = eval_dynamic_float(pred.get("CompareValue"), dynamic_resolver or (lambda _: 0.0), 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByIsTargetAbleToAction":
            if mrs is None:
                return False
            ent = mrs.entity
            return bool(
                ent.current_hp > 0.0
                and not ent.is_broken
                and ent.distance_remaining < 1e11
            )

        if t == "RPG.GameCore.ByIsTurnActionEntity":
            return bool(target_name and self.state.current_turn_actor == target_name)

        raise NotImplementedError(f"Unsupported stage predicate type: {t!r}")

    def execute_stage_task(
        self,
        task: Mapping[str, Any],
        *,
        caster_name: Optional[str] = None,
        dynamic_resolver: Optional[Callable[[int], float]] = None,
    ) -> bool:
        """Execute a stage/monster Task if handled by StageRunner (returns True if handled/pruned)."""
        t = str(task.get("$type", ""))
        if is_safe_prunable_type(t):
            return True

        if t == "RPG.GameCore.SummonMonster":
            if caster_name is None:
                raise ValueError("SummonMonster requires caster_name")
            self.execute_summon_monster(caster_name, task, dynamic_resolver=dynamic_resolver)
            return True

        if t == "RPG.GameCore.LockHP":
            if caster_name is None:
                raise ValueError("LockHP requires caster_name")
            mrs = self.get_enemy_state(caster_name)
            thr = self._resolve_monster_num(task.get("Threshold"), mrs, dynamic_resolver, default=0.0)
            self.apply_lock_hp(caster_name, thr)
            return True

        if t == "RPG.GameCore.SetMonsterPhase":
            if caster_name is None:
                raise ValueError("SetMonsterPhase requires caster_name")
            mode = str(task.get("SetMode", "Inc"))
            val_spec = task.get("PhaseValue") or task.get("Value")
            val = int(round(eval_dynamic_float(val_spec, dynamic_resolver or (lambda _: 0.0), 1.0))) if val_spec else None
            self.set_monster_phase(caster_name, mode=mode, value=val)
            return True

        if t == "RPG.GameCore.ExitBreakState":
            target = caster_name
            if target:
                self.execute_exit_break_state(target)
            return True

        if t == "RPG.GameCore.ResetStance":
            target = caster_name
            if target:
                self.execute_reset_stance(
                    target, forbid_when_empty=bool(task.get("ForbidWhenEmpty", False))
                )
            return True

        if t == "RPG.GameCore.StackWeakness":
            target = caster_name
            if target and target in self._enemy_by_name:
                self.execute_stack_weakness(
                    target,
                    task.get("WeakList", []),
                    op_type=str(task.get("OPType", "Add")),
                )
            return True

        if t == "RPG.GameCore.SetTargetUniqueName":
            un_obj = task.get("UniqueName")
            uname = str(un_obj.get("RawString", "")) if isinstance(un_obj, Mapping) else _unwrap_str(un_obj)
            if uname and caster_name:
                self.register_unique_name(uname, caster_name)
            return True

        if t == "RPG.GameCore.TargetFetchUniqueNameEntity":
            # Target-resolution node when evaluated as standalone step
            return True

        if t == "RPG.GameCore.OwnerEntityAddAbility":
            ab_name = _unwrap_str(task.get("AbilityName"))
            if ab_name:
                if caster_name and caster_name in self._enemy_by_name:
                    self._enemy_by_name[caster_name].abilities.append(ab_name)
                else:
                    self.state.stage_abilities.append(ab_name)
            return True

        if t == "RPG.GameCore.AddStageAbilityByName":
            ab_name = _unwrap_str(task.get("AbilityName"))
            if ab_name:
                self.state.stage_abilities.append(ab_name)
            return True

        if t == "RPG.GameCore.LevelChallengeTurnAcc":
            self.state.challenge_turns_elapsed += 1
            return True

        if t == "RPG.GameCore.TriggerCustomString":
            cs = _unwrap_str(task.get("CustomString"))
            if cs:
                self.emit_custom_event(cs)
            return True

        return False

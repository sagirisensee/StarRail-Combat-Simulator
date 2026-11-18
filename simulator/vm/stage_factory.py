"""Read-only data-driven stage, enemy, and BattleEvent factory (Phase 2/3 bridge).

Builds simulator-ready enemy ``Entity`` blueprints (including multi-phase HP,
initial action distance, weaknesses normalized to simulator element names,
all-element damage resistances, effect resistance, and wave-scoped summon
registries) and parses official ``BattleEventAbility_*`` ``ConfigAbility`` ASTs
from ``StageDataLoader`` and ``GameDataLoader`` without modifying any existing
VM core or stage files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from simulator.entity import Entity
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_data_loader import (
    ALL_DAMAGE_TYPES,
    CompiledBattleEventSpec,
    CompiledMonsterSkillSpec,
    CompiledMonsterSpec,
    CompiledStageSpec,
    DEFAULT_TBGD_ROOT,
    StageDataLoader,
)

# Official TurnBasedGameData uses "Thunder" whereas simulator Entity/DamageType uses "Lightning"
OFFICIAL_TO_SIM_ELEMENT: Dict[str, str] = {
    "Thunder": "Lightning",
}

SIM_ELEMENTS: Tuple[str, ...] = tuple(
    OFFICIAL_TO_SIM_ELEMENT.get(e, e) for e in ALL_DAMAGE_TYPES
)

BOSS_RANKS: Set[str] = {"LittleBoss", "Boss", "BigBoss"}


def normalize_element(element: Optional[str]) -> str:
    """Normalize an official DamageType string to simulator element naming."""
    if not element:
        return ""
    return OFFICIAL_TO_SIM_ELEMENT.get(element, element)


def _collect_ast_node_types(
    obj: Any,
    task_types: Set[str],
    predicate_types: Set[str],
    in_predicate: bool = False,
) -> None:
    """Recursively collect ``$type`` names for tasks and predicates in a ConfigAbility AST."""
    if isinstance(obj, list):
        for item in obj:
            _collect_ast_node_types(item, task_types, predicate_types, in_predicate=in_predicate)
        return
    if not isinstance(obj, Mapping):
        return

    node_type = obj.get("$type")
    if isinstance(node_type, str) and node_type:
        if in_predicate or node_type.startswith("RPG.GameCore.By"):
            predicate_types.add(node_type)
        else:
            task_types.add(node_type)

    for key, val in obj.items():
        if key == "$type":
            continue
        if key == "Predicate":
            _collect_ast_node_types(val, task_types, predicate_types, in_predicate=True)
        elif key == "PredicateList":
            _collect_ast_node_types(val, task_types, predicate_types, in_predicate=True)
        else:
            _collect_ast_node_types(val, task_types, predicate_types, in_predicate=False)


@dataclass(frozen=True)
class EnemyEntityBlueprint:
    """Pure-data enemy blueprint derived from ``CompiledMonsterSpec``."""

    monster_id: int
    monster_template_id: int
    name: str
    rank: str
    level: int
    elite_group: int
    base_hp: float
    phase_max_hps: Tuple[float, ...]
    base_atk: float
    base_def: float
    base_speed: float
    max_toughness: float
    ui_toughness: float
    initial_distance: float
    initial_delay_ratio: float
    is_boss: bool
    weaknesses: Tuple[str, ...]
    damage_res: Mapping[str, float]
    effect_res: float
    status_probability: float
    debuff_resist: Mapping[str, float]
    summon_ids: Tuple[int, ...]
    skills_by_key: Mapping[str, CompiledMonsterSkillSpec]
    ability_list: Tuple[str, ...] = ()

    @classmethod
    def from_compiled_monster(cls, spec: CompiledMonsterSpec) -> "EnemyEntityBlueprint":
        norm_weaknesses = tuple(normalize_element(w) for w in spec.weaknesses)
        norm_res: Dict[str, float] = {
            normalize_element(elem): float(val) for elem, val in spec.damage_res.items()
        }
        for el in SIM_ELEMENTS:
            norm_res.setdefault(el, 0.0)

        phase_hps = tuple(p.max_hp for p in spec.phases) if spec.phases else (spec.hp,)
        return cls(
            monster_id=spec.monster_id,
            monster_template_id=spec.monster_template_id,
            name=spec.name or f"Monster_{spec.monster_id}",
            rank=spec.rank,
            level=spec.level,
            elite_group=spec.elite_group,
            base_hp=spec.hp,
            phase_max_hps=phase_hps,
            base_atk=spec.atk,
            base_def=spec.def_,
            base_speed=spec.speed,
            max_toughness=spec.toughness,
            ui_toughness=spec.ui_toughness,
            initial_distance=spec.initial_distance,
            initial_delay_ratio=spec.initial_delay_ratio,
            is_boss=(spec.rank in BOSS_RANKS),
            weaknesses=norm_weaknesses,
            damage_res=norm_res,
            effect_res=spec.status_resistance,
            status_probability=spec.status_probability,
            debuff_resist=dict(spec.debuff_resist),
            summon_ids=spec.summon_ids,
            skills_by_key=dict(spec.skills_by_key),
            ability_list=spec.ability_list,
        )

    def to_entity(
        self,
        *,
        name: Optional[str] = None,
        initial_distance: Optional[float] = None,
        phase: int = 1,
    ) -> Entity:
        """Instantiate a simulator ``Entity`` populated with this blueprint's stats."""
        idx = max(0, min(len(self.phase_max_hps) - 1, phase - 1))
        hp = self.phase_max_hps[idx]
        dist = self.initial_distance if initial_distance is None else float(initial_distance)

        ent = Entity(
            name=name or self.name,
            base_speed=self.base_speed,
            base_atk=self.base_atk,
            max_hp=hp,
            current_hp=hp,
            base_def=self.base_def,
            base_effect_res=self.effect_res,
            level=self.level,
            max_toughness=self.max_toughness,
            current_toughness=self.max_toughness,
            weaknesses=list(self.weaknesses),
            is_enemy=True,
            is_boss=self.is_boss,
        )
        ent.distance_remaining = dist
        ent.damage_res = dict(self.damage_res)
        ent.hit_energy = 5.0
        # Attach read-only metadata attributes for downstream VM / stage directors
        ent.monster_id = self.monster_id  # type: ignore[attr-defined]
        ent.monster_template_id = self.monster_template_id  # type: ignore[attr-defined]
        ent.phase_max_hps = self.phase_max_hps  # type: ignore[attr-defined]
        ent.debuff_resist = dict(self.debuff_resist)  # type: ignore[attr-defined]
        ent.status_probability = self.status_probability  # type: ignore[attr-defined]
        return ent


@dataclass(frozen=True)
class CompiledBattleEventAbility:
    """Compiled BattleEvent metadata paired with its official ConfigAbility ASTs."""

    battle_event_id: int
    name: str
    team: str
    event_sub_type: str
    base_speed: float
    effective_speed: float
    action_value: Optional[float]
    param_list: Tuple[float, ...]
    override_properties: Mapping[str, float]
    ability_names: Tuple[str, ...]
    abilities: Mapping[str, Mapping[str, Any]]
    unresolved_abilities: Tuple[str, ...]
    referenced_task_types: Tuple[str, ...]
    referenced_predicate_types: Tuple[str, ...]


@dataclass(frozen=True)
class BuiltWaveSpec:
    """Wave-level enemy blueprints and wave-scoped summon blueprint registry."""

    wave_index: int
    elite_group: int
    enemies: Tuple[EnemyEntityBlueprint, ...]
    summon_blueprints: Mapping[int, EnemyEntityBlueprint] = field(default_factory=dict)

    def spawn_entities(self) -> List[Entity]:
        """Instantiate simulator ``Entity`` objects for all primary enemies in this wave."""
        seen_names: Dict[str, int] = {}
        entities: List[Entity] = []
        for bp in self.enemies:
            count = seen_names.get(bp.name, 0) + 1
            seen_names[bp.name] = count
            ent_name = bp.name if count == 1 else f"{bp.name}_{count}"
            entities.append(bp.to_entity(name=ent_name))
        return entities


@dataclass(frozen=True)
class BuiltStageSpec:
    """Complete data-driven stage build specification ready for simulator wiring."""

    stage_id: int
    stage_name: str
    stage_type: str
    level: int
    hard_level_group: int
    default_elite_group: int
    is_elite_battle: bool
    waves: Tuple[BuiltWaveSpec, ...]
    battle_events: Tuple[CompiledBattleEventAbility, ...]
    source_spec: CompiledStageSpec

    @property
    def num_waves(self) -> int:
        return len(self.waves)

    def build_wave_entities(self, wave_index: int = 0) -> List[Entity]:
        """Instantiate simulator ``Entity`` objects for ``wave_index``."""
        return self.waves[wave_index].spawn_entities()

    def get_summon_blueprint(self, monster_id: int, wave_index: int = 0) -> EnemyEntityBlueprint:
        """Retrieve a wave-scoped summon blueprint by ``MonsterID`` or ``MonsterTemplateID``."""
        wave = self.waves[wave_index]
        if monster_id in wave.summon_blueprints:
            return wave.summon_blueprints[monster_id]
        for bp in wave.summon_blueprints.values():
            if bp.monster_template_id == monster_id:
                return bp
        raise KeyError(
            f"Summon blueprint {monster_id} not found in wave {wave_index} of stage {self.stage_id}"
        )

    def spawn_summon_entity(
        self,
        monster_id: int,
        *,
        wave_index: int = 0,
        name: Optional[str] = None,
        initial_distance: Optional[float] = None,
    ) -> Entity:
        """Instantiate a wave-scoped summoned enemy ``Entity``."""
        bp = self.get_summon_blueprint(monster_id, wave_index=wave_index)
        return bp.to_entity(name=name, initial_distance=initial_distance)

    def get_battle_event(self, battle_event_id: int) -> CompiledBattleEventAbility:
        """Lookup a compiled BattleEvent ability spec by ``BattleEventID``."""
        for be in self.battle_events:
            if be.battle_event_id == battle_event_id:
                return be
        raise KeyError(f"BattleEvent {battle_event_id} not found in stage {self.stage_id}")


class StageFactory:
    """Pure data-driven factory converting official stage tables into simulator blueprints."""

    def __init__(
        self,
        stage_loader: Optional[StageDataLoader] = None,
        game_loader: Optional[GameDataLoader] = None,
        tbgd_root: str | Any = DEFAULT_TBGD_ROOT,
    ) -> None:
        self.stage_loader = stage_loader or StageDataLoader(tbgd_root=tbgd_root)
        self.game_loader = game_loader or GameDataLoader(data_root=str(self.stage_loader.tbgd_root))

    def build_battle_event(self, be_spec: CompiledBattleEventSpec) -> CompiledBattleEventAbility:
        """Resolve official ``ConfigAbility`` ASTs for a ``CompiledBattleEventSpec``."""
        self.game_loader.ensure_ability_index()
        abilities: Dict[str, Mapping[str, Any]] = {}
        unresolved: List[str] = []
        task_types: Set[str] = set()
        predicate_types: Set[str] = set()

        for ab_name in be_spec.ability_list:
            ab_ast = self.game_loader.get_ability(ab_name)
            if ab_ast is None:
                unresolved.append(ab_name)
                continue
            abilities[ab_name] = ab_ast
            _collect_ast_node_types(ab_ast.get("OnAdd", []), task_types, predicate_types)
            _collect_ast_node_types(ab_ast.get("OnStart", []), task_types, predicate_types)
            for mod in ab_ast.get("Modifiers", {}).values():
                if isinstance(mod, Mapping):
                    for cb in mod.get("_CallbackList", []):
                        if isinstance(cb, Mapping):
                            _collect_ast_node_types(
                                cb.get("CallbackConfig", []), task_types, predicate_types
                            )

        return CompiledBattleEventAbility(
            battle_event_id=be_spec.battle_event_id,
            name=be_spec.name,
            team=be_spec.team,
            event_sub_type=be_spec.event_sub_type,
            base_speed=be_spec.base_speed,
            effective_speed=be_spec.effective_speed,
            action_value=be_spec.action_value,
            param_list=be_spec.param_list,
            override_properties=dict(be_spec.override_properties),
            ability_names=be_spec.ability_list,
            abilities=abilities,
            unresolved_abilities=tuple(unresolved),
            referenced_task_types=tuple(sorted(task_types)),
            referenced_predicate_types=tuple(sorted(predicate_types)),
        )

    def build_stage(self, stage_id: int) -> BuiltStageSpec:
        """Build a complete ``BuiltStageSpec`` for ``stage_id``."""
        compiled_stage = self.stage_loader.load_stage(stage_id)
        built_waves: List[BuiltWaveSpec] = []

        for wave in compiled_stage.waves:
            enemies = tuple(EnemyEntityBlueprint.from_compiled_monster(m) for m in wave.monsters)
            summons = {
                mid: EnemyEntityBlueprint.from_compiled_monster(sm)
                for mid, sm in wave.summon_monsters.items()
            }
            built_waves.append(
                BuiltWaveSpec(
                    wave_index=wave.wave_index,
                    elite_group=wave.elite_group,
                    enemies=enemies,
                    summon_blueprints=summons,
                )
            )

        built_bes = tuple(self.build_battle_event(be) for be in compiled_stage.battle_events)
        return BuiltStageSpec(
            stage_id=compiled_stage.stage_id,
            stage_name=compiled_stage.stage_name,
            stage_type=compiled_stage.stage_type,
            level=compiled_stage.level,
            hard_level_group=compiled_stage.hard_level_group,
            default_elite_group=compiled_stage.default_elite_group,
            is_elite_battle=compiled_stage.is_elite_battle,
            waves=tuple(built_waves),
            battle_events=built_bes,
            source_spec=compiled_stage,
        )

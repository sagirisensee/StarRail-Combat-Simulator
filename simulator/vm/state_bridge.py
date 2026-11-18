"""Read-only unified StateBridge for TurnSimulator, VMRuntime, ModifierEngine, and StageRunner.

Provides a standard, narrow query interface for memosprite states, healing/pool
records, Elation/Aha stage beats, Modifier stacks, and de-obfuscated DynamicValues
without ever accessing private character kit attributes.

Strictly read-only: never modifies ``core.py``, ``runtime.py``, ``modifier_engine.py``,
or any existing character/enemy kits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from simulator.vm.expr import dotnet_hash
from simulator.vm.ir_compiler import DynamicHashRegistry


@dataclass(frozen=True)
class MemospriteSnapshot:
    """Read-only snapshot of an active memosprite (servant) entity."""

    name: str
    master_name: Optional[str]
    servant_id: int
    current_hp: float
    max_hp: float
    speed: float
    distance_remaining: float
    active: bool


@dataclass(frozen=True)
class ModifierSnapshot:
    """Read-only snapshot of an active ``VMModifierInstance``."""

    uid: int
    name: str
    caster_id: str
    owner_id: str
    ability_name: str
    layer: int
    max_layer: int
    life_time: Optional[float]
    properties: Mapping[str, float]
    convert_properties: Mapping[str, float]
    dynamic_values: Mapping[str, float]


@dataclass(frozen=True)
class StageStateSnapshot:
    """Read-only snapshot of stage/BattleEvent runtime state."""

    stage_id: int
    wave_index: int
    current_av: float
    current_cycle: int
    elation_points: float
    in_elation_time: bool
    battle_event_turns_left: Mapping[int, float]
    living_enemies: Tuple[str, ...]


@dataclass(frozen=True)
class EntityResourceSnapshot:
    """Aggregated read-only resource & modifier snapshot for a single entity."""

    entity_name: str
    current_hp: float
    max_hp: float
    energy: float
    max_energy: float
    speed: float
    sp: int
    memosprites: Tuple[MemospriteSnapshot, ...]
    modifiers: Tuple[ModifierSnapshot, ...]
    dynamic_values: Mapping[str, float] = field(default_factory=dict)


class StateBridge:
    """Unified read-only bridge over ``TurnSimulator``, ``VMRuntime``, and ``StageRunner``."""

    def __init__(
        self,
        sim: Any,
        *,
        registry: Optional[DynamicHashRegistry] = None,
        runner: Optional[Any] = None,
    ) -> None:
        self.sim = sim
        self.registry = registry
        self._explicit_runner = runner

    @property
    def vm_runtime(self) -> Optional[Any]:
        return getattr(self.sim, "vm_runtime", None)

    @property
    def stage_runner(self) -> Optional[Any]:
        if self._explicit_runner is not None:
            return self._explicit_runner
        director = getattr(self.sim, "_stage_director", None)
        if director is not None and hasattr(director, "runner"):
            return director.runner
        return None

    def _resolve_symbol(self, key_hash: int) -> str:
        if self.registry is not None:
            sym = self.registry.resolve(key_hash)
            if sym is not None:
                return sym
        return f"hash:{key_hash}"

    def _to_hash(self, key_or_hash: Union[str, int]) -> int:
        if isinstance(key_or_hash, int):
            return key_or_hash
        return dotnet_hash(str(key_or_hash))

    def get_dynamic_value(
        self,
        entity_id: str,
        key_or_hash: Union[str, int],
        *,
        ability_name: str = "",
    ) -> float:
        """Read a ``DynamicValue`` for ``entity_id`` from ``VMRuntime`` or ``ModifierEngine``."""
        key_hash = self._to_hash(key_or_hash)
        rt = self.vm_runtime
        if rt is not None:
            val = float(rt.resolve_hash(entity_id, key_hash, ability_name=ability_name))
            if abs(val) > 0.0:
                return val
            for mod in rt.modifier_engine.get_modifiers(entity_id):
                if key_hash in mod.dynamic_values:
                    return float(mod.dynamic_values[key_hash])
        runner = self.stage_runner
        if runner is not None:
            for mrs in getattr(runner.state, "enemies", ()):
                if mrs.entity.name == entity_id and key_hash in mrs.custom_values:
                    cv = mrs.custom_values[key_hash]
                    if isinstance(cv, (int, float)):
                        return float(cv)
        return 0.0

    def get_all_dynamic_values(
        self,
        entity_id: str,
        *,
        include_modifiers: bool = True,
    ) -> Dict[int, float]:
        """Collect all raw ``{hash_int: float}`` dynamic values for ``entity_id``."""
        out: Dict[int, float] = {}
        rt = self.vm_runtime
        if rt is not None:
            ent_dyn = rt.entity_dynamics.get(entity_id)
            if isinstance(ent_dyn, Mapping):
                for h, v in ent_dyn.items():
                    out[int(h)] = float(v)
            for (oid, _ab), eq_map in getattr(rt, "equip_dynamics", {}).items():
                if oid == entity_id and isinstance(eq_map, Mapping):
                    for h, v in eq_map.items():
                        out.setdefault(int(h), float(v))
            if include_modifiers:
                for mod in rt.modifier_engine.get_modifiers(entity_id):
                    for h, v in mod.dynamic_values.items():
                        out.setdefault(int(h), float(v))
        return out

    def get_scoped_dynamic_values(self, entity_id: str) -> Dict[Tuple[str, int], float]:
        """Collect ``{(scope, hash_int): float}`` across entity, equipment, and each Modifier."""
        out: Dict[Tuple[str, int], float] = {}
        rt = self.vm_runtime
        if rt is None:
            return out
        ent_dyn = rt.entity_dynamics.get(entity_id)
        if isinstance(ent_dyn, Mapping):
            for h, v in ent_dyn.items():
                out[("entity", int(h))] = float(v)
        for (oid, ab), eq_map in getattr(rt, "equip_dynamics", {}).items():
            if oid == entity_id and isinstance(eq_map, Mapping):
                for h, v in eq_map.items():
                    out[(f"equip:{ab}", int(h))] = float(v)
        for mod in rt.modifier_engine.get_modifiers(entity_id):
            for h, v in mod.dynamic_values.items():
                out[(f"mod:{mod.name}#{mod.uid}", int(h))] = float(v)
        return out

    def get_modifiers(
        self,
        owner_id: str,
        name: Optional[str] = None,
    ) -> Tuple[ModifierSnapshot, ...]:
        """Read active ``VMModifierInstance`` snapshots for ``owner_id``."""
        rt = self.vm_runtime
        if rt is None:
            return ()
        snaps: List[ModifierSnapshot] = []
        for mod in rt.modifier_engine.get_modifiers(owner_id, name):
            named_dyn = {
                self._resolve_symbol(h): float(v)
                for h, v in mod.dynamic_values.items()
            }
            snaps.append(
                ModifierSnapshot(
                    uid=mod.uid,
                    name=mod.name,
                    caster_id=mod.caster_id,
                    owner_id=mod.owner_id,
                    ability_name=mod.ability_name,
                    layer=mod.layer,
                    max_layer=mod.max_layer,
                    life_time=mod.life_time,
                    properties=dict(mod.properties),
                    convert_properties=dict(mod.convert_properties),
                    dynamic_values=named_dyn,
                )
            )
        return tuple(snaps)

    def get_memosprites(
        self,
        master_id: Optional[str] = None,
    ) -> Tuple[MemospriteSnapshot, ...]:
        """Read active/summoned memosprite snapshots from ``TurnSimulator.entities``."""
        out: List[MemospriteSnapshot] = []
        for ent in getattr(self.sim, "entities", ()):
            if not getattr(ent, "is_memosprite", False):
                continue
            m_name = getattr(ent, "master_name", None)
            if master_id is not None and m_name != master_id:
                continue
            max_hp = float(self.sim.port.max_hp(ent.name)) if hasattr(self.sim, "port") else float(ent.max_hp)
            out.append(
                MemospriteSnapshot(
                    name=ent.name,
                    master_name=m_name,
                    servant_id=int(getattr(ent, "avatar_id", 0) or 0),
                    current_hp=float(ent.current_hp),
                    max_hp=max_hp,
                    speed=float(ent.speed),
                    distance_remaining=float(ent.distance_remaining),
                    active=bool(ent.current_hp > 0.0),
                )
            )
        return tuple(out)

    def get_stage_snapshot(self) -> Optional[StageStateSnapshot]:
        """Read current stage/BattleEvent snapshot from ``StageRunner`` or director."""
        runner = self.stage_runner
        if runner is not None:
            st = runner.state
            turn_left_h = dotnet_hash("BattleEventTurnLeftParam")
            turns_left: Dict[int, float] = {}
            for be_id, be_st in st.battle_events.items():
                if turn_left_h in be_st.dynamic_values:
                    turns_left[int(be_id)] = float(be_st.dynamic_values[turn_left_h])
            return StageStateSnapshot(
                stage_id=int(runner.built_stage.stage_id),
                wave_index=int(st.wave_index),
                current_av=float(getattr(self.sim, "current_av", st.current_av)),
                current_cycle=int(getattr(self.sim, "current_cycle", st.current_cycle)),
                elation_points=float(st.elation_points),
                in_elation_time=bool(st.in_elation_time),
                battle_event_turns_left=turns_left,
                living_enemies=tuple(e.name for e in runner.living_enemies()),
            )
        director = getattr(self.sim, "_stage_director", None)
        if director is not None:
            living = tuple(
                e.name
                for e in getattr(self.sim, "entities", ())
                if getattr(e, "is_enemy", False) and float(getattr(e, "current_hp", 0.0)) > 0.0
            )
            be_turns: Dict[int, float] = {}
            if hasattr(director, "aha_extra_turns"):
                be_turns[int(getattr(director, "stage_id", 0))] = float(len(director.aha_extra_turns))
            return StageStateSnapshot(
                stage_id=int(getattr(director, "stage_id", 0)),
                wave_index=max(0, int(getattr(director, "wave", 1)) - 1),
                current_av=float(getattr(self.sim, "current_av", 0.0)),
                current_cycle=int(getattr(self.sim, "current_cycle", 0)),
                elation_points=float(getattr(director, "laugh_points", 0.0)),
                in_elation_time=bool(getattr(director, "in_elation_time", False)),
                battle_event_turns_left=be_turns,
                living_enemies=living,
            )
        return None

    def get_resource(self, entity_id: str, resource_name: str) -> float:
        """Unified resource reader across entity stats, stage state, modifiers, and VM dynamics."""
        low = resource_name.lower()
        if low in ("sp", "skill_points"):
            sp_mgr = getattr(self.sim, "sp", None)
            return float(getattr(sp_mgr, "current_sp", 0))
        if low in ("elation_points", "laugh_points"):
            snap = self.get_stage_snapshot()
            return snap.elation_points if snap is not None else 0.0

        ent = self.sim.get_entity(entity_id) if hasattr(self.sim, "get_entity") else None
        if ent is not None:
            if low == "hp":
                return float(ent.current_hp)
            if low == "max_hp":
                return float(self.sim.port.max_hp(ent.name)) if hasattr(self.sim, "port") else float(ent.max_hp)
            if low == "energy":
                return float(ent.energy)
            if low == "max_energy":
                return float(ent.max_energy)
            if low == "speed":
                return float(ent.speed)
            if low == "toughness":
                return float(ent.current_toughness)

        # Modifier layer query (if resource_name matches an active modifier)
        mods = self.get_modifiers(entity_id, name=resource_name)
        if mods:
            return float(sum(m.layer for m in mods))

        # VM DynamicValue query (by exact symbol name)
        return self.get_dynamic_value(entity_id, resource_name)

    def snapshot_entity(self, entity_id: str) -> EntityResourceSnapshot:
        """Build a full read-only ``EntityResourceSnapshot`` for ``entity_id``."""
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            raise KeyError(f"Entity {entity_id!r} not found in TurnSimulator")
        max_hp = float(self.sim.port.max_hp(ent.name)) if hasattr(self.sim, "port") else float(ent.max_hp)
        sp_mgr = getattr(self.sim, "sp", None)
        named_dyn = {
            self._resolve_symbol(h): v
            for h, v in self.get_all_dynamic_values(ent.name).items()
        }
        return EntityResourceSnapshot(
            entity_name=ent.name,
            current_hp=float(ent.current_hp),
            max_hp=max_hp,
            energy=float(ent.energy),
            max_energy=float(ent.max_energy),
            speed=float(ent.speed),
            sp=int(getattr(sp_mgr, "current_sp", 0)),
            memosprites=self.get_memosprites(master_id=ent.name),
            modifiers=self.get_modifiers(ent.name),
            dynamic_values=named_dyn,
        )

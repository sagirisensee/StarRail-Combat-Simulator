"""Read-only VM Causal Tracer subscribing to EventBus and diffing StateBridge snapshots.

Captures per-action, per-hit, and out-of-action (TurnBegin / TurnEnd / Aha) causal
snapshots of entity/equip/Modifier-scoped ``DynamicValue`` transitions,
``VMModifierInstance`` layer changes, healing/HP-loss records, and damage hits
with full ``DamageBreakdown`` without touching any core VM or simulator files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from simulator.events import (
    ActionEndEvent,
    ActionExecuteEvent,
    DamageAppliedEvent,
    HPLostEvent,
    HealAppliedEvent,
    TurnBeginEvent,
    TurnEndEvent,
)
from simulator.vm.expr import dotnet_hash
from simulator.vm.ir_compiler import DynamicHashRegistry
from simulator.vm.state_bridge import StageStateSnapshot, StateBridge


@dataclass(frozen=True)
class DynamicValueTransition:
    """Single ``DynamicValue`` change observed across entity, equip, or Modifier scope."""

    entity_id: str
    key_hash: int
    symbol_name: str
    old_val: float
    new_val: float
    delta: float
    scope: str = "entity"


@dataclass(frozen=True)
class ModifierTransition:
    """Single ``VMModifierInstance`` lifecycle or layer change observed during an action."""

    owner_id: str
    mod_name: str
    uid: int
    change_type: str  # "added" | "stacked" | "removed"
    old_layer: int
    new_layer: int
    caster_id: str


@dataclass(frozen=True)
class HitCausalRecord:
    """Per-hit causal snapshot capturing active modifiers & DamageBreakdown."""

    hit_seq: int
    av: float
    cycle: int
    attacker_name: str
    target_name: str
    damage: float
    element: str
    damage_type: str
    is_crit: bool
    attacker_modifiers: Tuple[Tuple[str, int], ...]
    target_modifiers: Tuple[Tuple[str, int], ...]
    breakdown: Any = None


@dataclass(frozen=True)
class HealCausalRecord:
    """Per-heal causal record captured during an action or turn boundary."""

    av: float
    healer_name: str
    target_name: str
    amount: float
    overheal: float


@dataclass(frozen=True)
class ActionCausalSnapshot:
    """Complete causal audit snapshot for a single executed action or turn-boundary phase."""

    action_seq: int
    av: float
    cycle: int
    actor_name: str
    action_type: str
    skill_config_id: int
    dynamic_transitions: Tuple[DynamicValueTransition, ...] = ()
    modifier_transitions: Tuple[ModifierTransition, ...] = ()
    hits: Tuple[HitCausalRecord, ...] = ()
    heals: Tuple[HealCausalRecord, ...] = ()
    hp_lost: Tuple[Tuple[str, float, str], ...] = ()
    stage_snapshot_after: Optional[StageStateSnapshot] = None


class VMCausalTracer:
    """Read-only EventBus subscriber & StateBridge differ for VM causal auditing."""

    def __init__(
        self,
        sim: Any,
        *,
        bridge: Optional[StateBridge] = None,
        registry: Optional[DynamicHashRegistry] = None,
    ) -> None:
        self.sim = sim
        self.registry = registry
        self.bridge = bridge or StateBridge(sim, registry=registry)
        self.history: List[ActionCausalSnapshot] = []
        self._hit_seq: int = 0
        self._active_action: Optional[Dict[str, Any]] = None
        self._baseline_dyn: Dict[str, Dict[Tuple[str, int], float]] = self._capture_all_dynamics()
        self._baseline_mod: Dict[Tuple[str, int], Tuple[str, int, str]] = self._capture_all_modifiers()
        self._ooa_hits: List[HitCausalRecord] = []
        self._ooa_heals: List[HealCausalRecord] = []
        self._ooa_hp_lost: List[Tuple[str, float, str]] = []

        eb = sim.event_bus
        eb.subscribe(TurnBeginEvent, self._on_turn_begin)
        eb.subscribe(TurnEndEvent, self._on_turn_end)
        eb.subscribe(ActionExecuteEvent, self._on_action_execute)
        eb.subscribe(DamageAppliedEvent, self._on_damage_applied)
        eb.subscribe(HealAppliedEvent, self._on_heal)
        eb.subscribe(HPLostEvent, self._on_hp_lost)
        eb.subscribe(ActionEndEvent, self._on_action_end)

    def _resolve_symbol(self, h: int) -> str:
        if self.registry is not None:
            sym = self.registry.resolve(h)
            if sym is not None:
                return sym
        return f"hash:{h}"

    def _capture_all_dynamics(self) -> Dict[str, Dict[Tuple[str, int], float]]:
        out: Dict[str, Dict[Tuple[str, int], float]] = {}
        for ent in getattr(self.sim, "entities", ()):
            dyn = self.bridge.get_scoped_dynamic_values(ent.name)
            if dyn:
                out[ent.name] = dyn
        return out

    def _capture_all_modifiers(self) -> Dict[Tuple[str, int], Tuple[str, int, str]]:
        out: Dict[Tuple[str, int], Tuple[str, int, str]] = {}
        rt = self.bridge.vm_runtime
        if rt is None:
            return out
        for mod in rt.modifier_engine.all_modifiers():
            if not mod._destroyed:
                out[(mod.owner_id, mod.uid)] = (mod.name, int(mod.layer), mod.caster_id)
        return out

    def _diff_dynamics(
        self,
        dyn_before: Dict[str, Dict[Tuple[str, int], float]],
        dyn_after: Dict[str, Dict[Tuple[str, int], float]],
    ) -> Tuple[DynamicValueTransition, ...]:
        transitions: List[DynamicValueTransition] = []
        all_entities = sorted(set(dyn_before.keys()) | set(dyn_after.keys()))
        for eid in all_entities:
            bmap = dyn_before.get(eid, {})
            amap = dyn_after.get(eid, {})
            for scope, h in sorted(set(bmap.keys()) | set(amap.keys())):
                ov = bmap.get((scope, h), 0.0)
                nv = amap.get((scope, h), 0.0)
                if abs(nv - ov) > 1e-9:
                    transitions.append(
                        DynamicValueTransition(
                            entity_id=eid,
                            key_hash=h,
                            symbol_name=self._resolve_symbol(h),
                            old_val=ov,
                            new_val=nv,
                            delta=nv - ov,
                            scope=scope,
                        )
                    )
        return tuple(transitions)

    def _diff_modifiers(
        self,
        mod_before: Dict[Tuple[str, int], Tuple[str, int, str]],
        mod_after: Dict[Tuple[str, int], Tuple[str, int, str]],
    ) -> Tuple[ModifierTransition, ...]:
        transitions: List[ModifierTransition] = []
        for key, (mname, layer_a, caster) in mod_after.items():
            owner_id, uid = key
            if key not in mod_before:
                transitions.append(
                    ModifierTransition(
                        owner_id=owner_id,
                        mod_name=mname,
                        uid=uid,
                        change_type="added",
                        old_layer=0,
                        new_layer=layer_a,
                        caster_id=caster,
                    )
                )
            else:
                _, layer_b, _ = mod_before[key]
                if layer_a != layer_b:
                    transitions.append(
                        ModifierTransition(
                            owner_id=owner_id,
                            mod_name=mname,
                            uid=uid,
                            change_type="stacked",
                            old_layer=layer_b,
                            new_layer=layer_a,
                            caster_id=caster,
                        )
                    )
        for key, (mname, layer_b, caster) in mod_before.items():
            if key not in mod_after:
                owner_id, uid = key
                transitions.append(
                    ModifierTransition(
                        owner_id=owner_id,
                        mod_name=mname,
                        uid=uid,
                        change_type="removed",
                        old_layer=layer_b,
                        new_layer=0,
                        caster_id=caster,
                    )
                )
        return tuple(transitions)

    def _flush_out_of_action(
        self,
        *,
        av: float,
        cycle: int,
        actor_name: str,
        label: str,
    ) -> None:
        dyn_after = self._capture_all_dynamics()
        mod_after = self._capture_all_modifiers()
        dyn_tr = self._diff_dynamics(self._baseline_dyn, dyn_after)
        mod_tr = self._diff_modifiers(self._baseline_mod, mod_after)

        if dyn_tr or mod_tr or self._ooa_hits or self._ooa_heals or self._ooa_hp_lost:
            self.history.append(
                ActionCausalSnapshot(
                    action_seq=len(self.history) + 1,
                    av=av,
                    cycle=cycle,
                    actor_name=actor_name,
                    action_type=label,
                    skill_config_id=0,
                    dynamic_transitions=dyn_tr,
                    modifier_transitions=mod_tr,
                    hits=tuple(self._ooa_hits),
                    heals=tuple(self._ooa_heals),
                    hp_lost=tuple(self._ooa_hp_lost),
                    stage_snapshot_after=self.bridge.get_stage_snapshot(),
                )
            )
            self._ooa_hits.clear()
            self._ooa_heals.clear()
            self._ooa_hp_lost.clear()
        self._baseline_dyn = dyn_after
        self._baseline_mod = mod_after

    def _on_turn_begin(self, evt: TurnBeginEvent) -> None:
        if self._active_action is None:
            self._flush_out_of_action(
                av=float(evt.av),
                cycle=int(evt.cycle),
                actor_name=evt.actor_name,
                label="TurnBegin",
            )

    def _on_turn_end(self, evt: TurnEndEvent) -> None:
        if self._active_action is None:
            self._flush_out_of_action(
                av=float(evt.av),
                cycle=int(evt.cycle),
                actor_name=evt.actor_name,
                label="TurnEnd",
            )

    def _on_action_execute(self, evt: ActionExecuteEvent) -> None:
        # Flush any TurnBegin / out-of-action changes before starting this action's clean baseline
        self._flush_out_of_action(
            av=float(evt.av),
            cycle=int(evt.cycle),
            actor_name=evt.actor_name,
            label="OutOfAction",
        )
        self._active_action = {
            "action_seq": int(getattr(evt, "action_id", 0) or (len(self.history) + 1)),
            "av": float(evt.av),
            "cycle": int(evt.cycle),
            "actor_name": evt.actor_name,
            "action_type": str(evt.action_type),
            "skill_config_id": int(getattr(evt, "skill_config_id", 0) or 0),
            "dyn_before": self._baseline_dyn,
            "mod_before": self._baseline_mod,
            "hits": [],
            "heals": [],
            "hp_lost": [],
        }

    def _on_damage_applied(self, evt: DamageAppliedEvent) -> None:
        self._hit_seq += 1
        atk_mods = tuple(
            (m.name, m.layer)
            for m in self.bridge.get_modifiers(evt.attacker_name)
        )
        tgt_mods = tuple(
            (m.name, m.layer)
            for m in self.bridge.get_modifiers(evt.target_name)
        )
        rec = HitCausalRecord(
            hit_seq=self._hit_seq,
            av=float(evt.av),
            cycle=int(evt.cycle),
            attacker_name=evt.attacker_name,
            target_name=evt.target_name,
            damage=float(evt.damage),
            element=str(getattr(evt, "element", "")),
            damage_type=str(getattr(evt, "damage_type", "")),
            is_crit=bool(getattr(evt, "is_crit", False)),
            attacker_modifiers=atk_mods,
            target_modifiers=tgt_mods,
            breakdown=getattr(evt, "breakdown", None),
        )
        if self._active_action is not None:
            self._active_action["hits"].append(rec)
        else:
            self._ooa_hits.append(rec)

    def _on_heal(self, evt: HealAppliedEvent) -> None:
        rec = HealCausalRecord(
            av=float(evt.av),
            healer_name=evt.source_name,
            target_name=evt.target_name,
            amount=float(evt.amount),
            overheal=0.0,
        )
        if self._active_action is not None:
            self._active_action["heals"].append(rec)
        else:
            self._ooa_heals.append(rec)

    def _on_hp_lost(self, evt: HPLostEvent) -> None:
        item = (evt.entity_name, float(evt.amount), str(getattr(evt, "cause", "")))
        if self._active_action is not None:
            self._active_action["hp_lost"].append(item)
        else:
            self._ooa_hp_lost.append(item)

    def _on_action_end(self, evt: ActionEndEvent) -> None:
        if self._active_action is None:
            return
        act = self._active_action
        self._active_action = None

        dyn_after = self._capture_all_dynamics()
        mod_after = self._capture_all_modifiers()
        dyn_transitions = self._diff_dynamics(act["dyn_before"], dyn_after)
        mod_transitions = self._diff_modifiers(act["mod_before"], mod_after)

        snap = ActionCausalSnapshot(
            action_seq=act["action_seq"],
            av=float(evt.av),
            cycle=int(evt.cycle),
            actor_name=act["actor_name"],
            action_type=act["action_type"],
            skill_config_id=act["skill_config_id"],
            dynamic_transitions=dyn_transitions,
            modifier_transitions=mod_transitions,
            hits=tuple(act["hits"]),
            heals=tuple(act["heals"]),
            hp_lost=tuple(act["hp_lost"]),
            stage_snapshot_after=self.bridge.get_stage_snapshot(),
        )
        self.history.append(snap)
        self._baseline_dyn = dyn_after
        self._baseline_mod = mod_after

    def trace_deviation(
        self,
        entity_id: str,
        symbol_or_hash: Union[str, int],
    ) -> List[Tuple[int, float, DynamicValueTransition]]:
        """Root-cause query: list all actions where ``symbol_or_hash`` changed on ``entity_id``."""
        target_h = (
            symbol_or_hash
            if isinstance(symbol_or_hash, int)
            else dotnet_hash(str(symbol_or_hash))
        )
        out: List[Tuple[int, float, DynamicValueTransition]] = []
        for snap in self.history:
            for tr in snap.dynamic_transitions:
                if tr.entity_id == entity_id and tr.key_hash == target_h:
                    out.append((snap.action_seq, snap.av, tr))
        return out

    def trace_modifier_history(
        self,
        owner_id: str,
        mod_name: str,
    ) -> List[Tuple[int, float, ModifierTransition]]:
        """Root-cause query: list all lifecycle/layer transitions for ``mod_name`` on ``owner_id``."""
        out: List[Tuple[int, float, ModifierTransition]] = []
        for snap in self.history:
            for mt in snap.modifier_transitions:
                if mt.owner_id == owner_id and mt.mod_name == mod_name:
                    out.append((snap.action_seq, snap.av, mt))
        return out

    def format_report(self, *, last_n: Optional[int] = None) -> str:
        """Render a concise causal audit report."""
        items = self.history[-last_n:] if last_n is not None else self.history
        lines: List[str] = [f"# VM Causal Audit Report ({len(items)} actions)"]
        for snap in items:
            lines.append(
                f"## Action #{snap.action_seq} [{snap.av:.2f} AV | C{snap.cycle}] "
                f"{snap.actor_name} -> {snap.action_type}"
            )
            for dt in snap.dynamic_transitions:
                lines.append(
                    f"  - Dyn[{dt.entity_id}.{dt.symbol_name} ({dt.scope})]: "
                    f"{dt.old_val:.4g} -> {dt.new_val:.4g} ({dt.delta:+.4g})"
                )
            for mt in snap.modifier_transitions:
                lines.append(
                    f"  - Mod[{mt.owner_id}.{mt.mod_name}]: "
                    f"{mt.change_type} ({mt.old_layer} -> {mt.new_layer})"
                )
            for h in snap.hits:
                lines.append(
                    f"  - Hit#{h.hit_seq}: {h.attacker_name} -> {h.target_name} "
                    f"{h.damage:.2f} ({h.element}, crit={h.is_crit})"
                )
        return "\n".join(lines)

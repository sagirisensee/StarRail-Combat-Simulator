"""Read-only official Monster AI & skill-sequence compiler (Phase 3).

Compiles official ``ConfigAI/*.json``, ``MonsterConfig.json``,
``MonsterTemplateConfig.json``, ``MonsterSkillConfig.json``, and
``ConfigAbility/Monster/*.json`` into pure-data, multi-phase / multi-turn
monster action state machines without depending on any hand-written
``simulator/kits/enemies/*.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.vm.stage_data_loader import (
    CompiledMonsterSkillSpec,
    CompiledMonsterSpec,
    DEFAULT_TBGD_ROOT,
    StageDataLoader,
)
from simulator.vm.stage_factory import normalize_element


def _extract_use_skills_and_flag(
    node: Any,
    use_skills: List[str],
    next_flags: List[int],
    selectors: List[str],
) -> None:
    if isinstance(node, list):
        for item in node:
            _extract_use_skills_and_flag(item, use_skills, next_flags, selectors)
        return
    if not isinstance(node, Mapping):
        return
    t = node.get("$type", "")
    if t == "RPG.GameCore.UseSkill" and node.get("SkillName"):
        use_skills.append(str(node["SkillName"]))
        return
    elif t in ("RPG.GameCore.DefineDynamicValue", "RPG.GameCore.SetDynamicValue"):
        dk = node.get("DynamicKey")
        dk_name = dk.get("Value") if isinstance(dk, Mapping) else str(dk or "")
        if dk_name == "AIFlag" or dk_name.endswith("_AIFlag"):
            val_spec = node.get("ResetValue") if "ResetValue" in node else node.get("Value")
            if isinstance(val_spec, Mapping) and not val_spec.get("IsDynamic", False):
                fv = val_spec.get("FixedValue", {})
                if isinstance(fv, Mapping) and isinstance(fv.get("Value"), (int, float)):
                    next_flags.append(int(fv["Value"]))
    elif t == "RPG.GameCore.SelectAISkillTarget":
        sel = node.get("Selector", {})
        if isinstance(sel, Mapping) and sel.get("$type"):
            selectors.append(str(sel["$type"]).split(".")[-1])
    for k, v in node.items():
        if k != "$type":
            _extract_use_skills_and_flag(v, use_skills, next_flags, selectors)


def _extract_axis_conditions(
    pred: Any,
    phase_conds: List[Tuple[str, int]],
    flag_conds: List[int],
) -> None:
    if isinstance(pred, list):
        for item in pred:
            _extract_axis_conditions(item, phase_conds, flag_conds)
        return
    if not isinstance(pred, Mapping):
        return
    t = pred.get("$type", "")
    if t == "RPG.GameCore.ByCompareMonsterPhase":
        cv = pred.get("CompareValue", {})
        if isinstance(cv, Mapping) and not cv.get("IsDynamic", False):
            fv = cv.get("FixedValue", {})
            if isinstance(fv, Mapping) and isinstance(fv.get("Value"), (int, float)):
                cmp_t = str(pred.get("CompareType", "Equal"))
                if cmp_t in ("Equal", "GreaterEqual", "Greater", "LessEqual", "Less"):
                    phase_conds.append((cmp_t, int(fv["Value"])))
    elif t == "RPG.GameCore.ByCompareDynamicValue":
        dk = pred.get("DynamicKey", {})
        dk_name = dk.get("Value") if isinstance(dk, Mapping) else str(dk or "")
        if (dk_name == "AIFlag" or dk_name.endswith("_AIFlag")) and pred.get("CompareType", "Equal") == "Equal":
            cv = pred.get("CompareValue", {})
            if isinstance(cv, Mapping) and not cv.get("IsDynamic", False):
                fv = cv.get("FixedValue", {})
                if isinstance(fv, Mapping) and isinstance(fv.get("Value"), (int, float)):
                    flag_conds.append(int(fv["Value"]))
    for k, v in pred.items():
        if k != "$type":
            _extract_axis_conditions(v, phase_conds, flag_conds)


@dataclass(frozen=True)
class AISkillActionSpec:
    """Resolved monster skill action including effective multipliers & element."""

    skill_trigger_key: str
    skill_id: int
    skill_name: str
    damage_type: Optional[str]
    element: str
    sp_hit_base: float
    base_params: Tuple[float, ...]
    effective_params: Tuple[float, ...]
    is_passive: bool
    target_selector: str = "Default"
    is_blast: bool = False
    is_aoe: bool = False
    hit_count: int = 1
    has_mark_target: bool = False

    @classmethod
    def from_compiled_skill(
        cls,
        sk: CompiledMonsterSkillSpec,
        target_selector: str = "Default",
    ) -> "AISkillActionSpec":
        return cls(
            skill_trigger_key=sk.trigger_key,
            skill_id=sk.skill_id,
            skill_name=sk.name,
            damage_type=sk.damage_type,
            element=normalize_element(sk.damage_type),
            sp_hit_base=sk.sp_hit_base,
            base_params=sk.base_params,
            effective_params=sk.effective_params,
            is_passive=sk.is_passive,
            target_selector=target_selector,
            is_blast=sk.is_blast,
            is_aoe=sk.is_aoe,
            hit_count=sk.hit_count,
            has_mark_target=sk.has_mark_target,
        )

    def param(self, index: int, default: float = 0.0) -> float:
        if 0 <= index < len(self.effective_params):
            return self.effective_params[index]
        return default


@dataclass(frozen=True)
class AIDecisionRule:
    """Single compiled decision entry from ``ConfigAI.DecisionList``."""

    decision_name: str
    group_name: str
    phase_condition: Optional[int]
    ai_flag_condition: Optional[int]
    next_ai_flag: Optional[int]
    use_skills: Tuple[str, ...]
    candidate_skills: Tuple[AISkillActionSpec, ...]
    condition_predicates: Tuple[Mapping[str, Any], ...]
    root_task: Mapping[str, Any]
    phase_compare_type: str = "Equal"
    success_score: float = 1.0

    def matches_phase(self, phase: int) -> bool:
        if self.phase_condition is None:
            return True
        if self.phase_compare_type == "Equal":
            return phase == self.phase_condition
        if self.phase_compare_type == "GreaterEqual":
            return phase >= self.phase_condition
        if self.phase_compare_type == "Greater":
            return phase > self.phase_condition
        if self.phase_compare_type == "LessEqual":
            return phase <= self.phase_condition
        if self.phase_compare_type == "Less":
            return phase < self.phase_condition
        return phase == self.phase_condition


@dataclass(frozen=True)
class ReactiveAbilityHook:
    """Reactive hook extracted from monster ConfigAbility (TurnInsert / StanceBreak / PhaseTransition)."""

    hook_type: str  # "TurnInsert" | "StanceBreak" | "PhaseTransition"
    ability_name: str
    trigger_event: str
    insert_priority: Optional[str] = None
    target_ability: Optional[str] = None


@dataclass(frozen=True)
class CompiledMonsterAISpec:
    """Complete compiled monster AI & skill-sequence state machine."""

    monster_id: int
    monster_template_id: int
    name: str
    ai_path: str
    ai_name: str
    initial_variables: Mapping[str, Any]
    initial_ai_flag: int
    override_ai_skill_sequence: Tuple[int, ...]
    decisions: Tuple[AIDecisionRule, ...]
    phase_sequences: Mapping[int, Tuple[Tuple[str, ...], ...]]
    reactive_hooks: Tuple[ReactiveAbilityHook, ...]
    skills_by_key: Mapping[str, AISkillActionSpec]

    def skill(self, trigger_key: str) -> AISkillActionSpec:
        return self.skills_by_key[trigger_key]

    def trace_ai_flag_cycle(
        self,
        *,
        phase: int = 1,
        max_steps: int = 12,
    ) -> Tuple[Tuple[str, ...], ...]:
        """Trace the deterministic skill-sequence cycle driven by ``AIFlag`` for ``phase``."""
        flag = self.initial_ai_flag
        visited: set[int] = set()
        turns: List[Tuple[str, ...]] = []
        for _ in range(max_steps):
            if flag in visited:
                break
            visited.add(flag)
            matched: Optional[AIDecisionRule] = None
            for dec in self.decisions:
                if not dec.matches_phase(phase):
                    continue
                if dec.ai_flag_condition == flag:
                    matched = dec
                    break
            if matched is None:
                break
            turns.append(matched.use_skills)
            if matched.next_ai_flag is None or matched.next_ai_flag == flag:
                break
            flag = matched.next_ai_flag
        return tuple(turns)


class MonsterAIExecutor:
    """Lightweight runtime state machine stepping through ``CompiledMonsterAISpec``."""

    def __init__(self, spec: CompiledMonsterAISpec) -> None:
        self.spec = spec
        self.phase: int = 1
        self.ai_flag: int = spec.initial_ai_flag
        self.turn_count: int = 0
        self.last_matched_decision: Optional[AIDecisionRule] = None

    def set_phase(self, phase: int, reset_ai_flag: int = 1) -> None:
        self.phase = phase
        self.ai_flag = reset_ai_flag

    def select_next_actions(
        self,
        *,
        predicate_evaluator: Optional[Any] = None,
    ) -> Tuple[AISkillActionSpec, ...]:
        """Select the next turn's skill action(s) based on current ``phase`` & ``ai_flag``."""
        self.turn_count += 1
        matched: Optional[AIDecisionRule] = None

        if callable(predicate_evaluator) and self.spec.decisions:
            best_score = -1.0
            for dec in self.spec.decisions:
                if not dec.matches_phase(self.phase):
                    continue
                if dec.ai_flag_condition is not None and dec.ai_flag_condition != self.ai_flag:
                    continue
                if dec.condition_predicates:
                    ok = True
                    for pred in dec.condition_predicates:
                        try:
                            if not predicate_evaluator(pred):
                                ok = False
                                break
                        except NotImplementedError:
                            ok = False
                            break
                    if not ok:
                        continue
                elif dec.ai_flag_condition is None:
                    continue
                if dec.success_score > best_score:
                    best_score = dec.success_score
                    matched = dec

        if matched is None:
            for dec in self.spec.decisions:
                if not dec.matches_phase(self.phase):
                    continue
                if dec.ai_flag_condition is not None and dec.ai_flag_condition == self.ai_flag:
                    matched = dec
                    break

        if matched is None and self.spec.decisions:
            # Fallback to first decision matching current phase (e.g. modifier-driven AI)
            for dec in self.spec.decisions:
                if dec.matches_phase(self.phase):
                    matched = dec
                    break

        if matched is None:
            self.last_matched_decision = None
            return ()

        self.last_matched_decision = matched
        if matched.next_ai_flag is not None:
            self.ai_flag = matched.next_ai_flag
        if matched.candidate_skills:
            return matched.candidate_skills
        if self.spec.override_ai_skill_sequence:
            seq = self.spec.override_ai_skill_sequence
            sid = seq[(self.turn_count - 1) % len(seq)]
            for sk in self.spec.skills_by_key.values():
                if sk.skill_id == sid:
                    return (sk,)
        return ()


class StageAILoader:
    """Read-only compiler converting official ConfigAI & MonsterAbility into ``CompiledMonsterAISpec``."""

    def __init__(
        self,
        stage_loader: Optional[StageDataLoader] = None,
        tbgd_root: Path | str = DEFAULT_TBGD_ROOT,
    ) -> None:
        self.stage_loader = stage_loader or StageDataLoader(tbgd_root=tbgd_root)
        self.tbgd_root = self.stage_loader.tbgd_root
        self._ai_cache: Dict[str, Dict[str, Any]] = {}

    def _load_ai_json(self, ai_path: str) -> Dict[str, Any]:
        if not ai_path:
            return {}
        if ai_path not in self._ai_cache:
            full = self.tbgd_root / ai_path
            if not full.exists():
                self._ai_cache[ai_path] = {}
            else:
                try:
                    self._ai_cache[ai_path] = json.loads(full.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"Failed to parse ConfigAI '{full}': {exc}") from exc
        return self._ai_cache[ai_path]

    def _extract_reactive_hooks(self, monster: CompiledMonsterSpec) -> Tuple[ReactiveAbilityHook, ...]:
        hooks: List[ReactiveAbilityHook] = []
        if not monster.json_config_path:
            return ()
        stem = Path(monster.json_config_path).stem
        if not stem.endswith("_Config"):
            return ()
        ab_file = self.tbgd_root / "Config" / "ConfigAbility" / "Monster" / f"{stem[:-len('_Config')]}_Ability.json"
        if not ab_file.exists():
            return ()
        try:
            ab_doc = json.loads(ab_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to parse MonsterAbility '{ab_file}': {exc}") from exc

        def _scan_tasks(tasks: Any, ab_name: str, trigger_evt: str) -> None:
            if isinstance(tasks, list):
                for t in tasks:
                    _scan_tasks(t, ab_name, trigger_evt)
            elif isinstance(tasks, Mapping):
                tt = tasks.get("$type", "")
                if tt == "RPG.GameCore.TurnInsertAbility":
                    target_ab = tasks.get("AbilityName", {})
                    target_ab_str = (
                        target_ab.get("Value") if isinstance(target_ab, Mapping) else str(target_ab or "")
                    )
                    prio = str(tasks.get("InsertAbilityPriority", ""))
                    htype = "PhaseTransition" if prio == "MonsterChangePhase" else "TurnInsert"
                    hooks.append(
                        ReactiveAbilityHook(
                            hook_type=htype,
                            ability_name=ab_name,
                            trigger_event=trigger_evt,
                            insert_priority=prio or None,
                            target_ability=target_ab_str or None,
                        )
                    )
                elif tt == "RPG.GameCore.SetMonsterPhase":
                    hooks.append(
                        ReactiveAbilityHook(
                            hook_type="PhaseTransition",
                            ability_name=ab_name,
                            trigger_event=trigger_evt,
                        )
                    )
                for k, v in tasks.items():
                    if k != "$type":
                        _scan_tasks(v, ab_name, trigger_evt)

        for ab in ab_doc.get("AbilityList", []):
            ab_name = str(ab.get("Name", ""))
            _scan_tasks(ab.get("OnStart", []), ab_name, "OnStart")
            _scan_tasks(ab.get("OnAdd", []), ab_name, "OnAdd")
            for mod_name, mod in ab.get("Modifiers", {}).items():
                if isinstance(mod, Mapping):
                    for cb in mod.get("_CallbackList", []):
                        if isinstance(cb, Mapping):
                            evt = str(cb.get("Event", ""))
                            if evt in ("OnBeingBreak", "OnBeforeBeingBreak"):
                                hooks.append(
                                    ReactiveAbilityHook(
                                        hook_type="StanceBreak",
                                        ability_name=ab_name or str(mod_name),
                                        trigger_event=evt,
                                    )
                                )
                            _scan_tasks(cb.get("CallbackConfig", []), ab_name or str(mod_name), evt)
        for mod_name, mod in ab_doc.get("GlobalModifiers", {}).items():
            if isinstance(mod, Mapping):
                for cb in mod.get("_CallbackList", []):
                    if isinstance(cb, Mapping):
                        evt = str(cb.get("Event", ""))
                        if evt in ("OnBeingBreak", "OnBeforeBeingBreak"):
                            hooks.append(
                                ReactiveAbilityHook(
                                    hook_type="StanceBreak",
                                    ability_name=str(mod_name),
                                    trigger_event=evt,
                                )
                            )
                        _scan_tasks(cb.get("CallbackConfig", []), str(mod_name), evt)
        return tuple(hooks)

    def compile_monster_ai(self, monster: CompiledMonsterSpec) -> CompiledMonsterAISpec:
        """Compile a ``CompiledMonsterAISpec`` from ``CompiledMonsterSpec``."""
        ai_doc = self._load_ai_json(monster.ai_path)
        char_cfg = self.stage_loader._load_char_config(monster.json_config_path)
        mrow = self.stage_loader.monsters.get(monster.monster_id, {})
        trow = self.stage_loader.monster_templates.get(monster.monster_template_id, {})

        init_vars: Dict[str, Any] = {}
        for var in ai_doc.get("VariableList", []):
            if isinstance(var, Mapping) and var.get("Name"):
                init_vars[str(var["Name"])] = var.get("Value")

        initial_ai_flag = int(
            char_cfg.get("CustomValues", {}).get("AIFlag", 1)
            if isinstance(char_cfg.get("CustomValues"), Mapping)
            else 1
        )
        seq_raw = mrow.get("OverrideAISkillSequence") or trow.get("AISkillSequence") or []
        override_seq_list: List[int] = []
        for x in seq_raw:
            if isinstance(x, Mapping):
                for v in x.values():
                    if isinstance(v, (int, float, str)):
                        override_seq_list.append(int(v))
                        break
            else:
                override_seq_list.append(int(x))
        override_seq = tuple(override_seq_list)

        skills_by_key: Dict[str, AISkillActionSpec] = {
            k: AISkillActionSpec.from_compiled_skill(sk)
            for k, sk in monster.skills_by_key.items()
        }

        decisions: List[AIDecisionRule] = []

        def _ingest_decision(dec: Mapping[str, Any], group_name: str) -> None:
            root_task = dec.get("RootTask", {})
            use_skills: List[str] = []
            next_flags: List[int] = []
            selectors: List[str] = []
            _extract_use_skills_and_flag(root_task, use_skills, next_flags, selectors)

            phase_conds: List[Tuple[str, int]] = []
            flag_conds: List[int] = []
            cond_preds: List[Mapping[str, Any]] = []
            axis_scores: List[float] = []
            for ax in dec.get("ConsiderAxisList", []):
                if isinstance(ax, Mapping) and isinstance(ax.get("Predicate"), Mapping):
                    cond_preds.append(ax["Predicate"])
                    _extract_axis_conditions(ax["Predicate"], phase_conds, flag_conds)
                if isinstance(ax, Mapping) and isinstance(ax.get("SuccessScore"), Mapping):
                    try:
                        axis_scores.append(float(ax["SuccessScore"].get("Value", 1.0)))
                    except (TypeError, ValueError):
                        pass

            sel_str = selectors[0] if selectors else "Default"
            cand_skills = tuple(
                AISkillActionSpec.from_compiled_skill(
                    monster.skills_by_key[sk_key], target_selector=sel_str
                )
                for sk_key in use_skills
                if sk_key in monster.skills_by_key
            )

            decisions.append(
                AIDecisionRule(
                    decision_name=str(dec.get("DecisionName", "")),
                    group_name=group_name,
                    phase_condition=phase_conds[0][1] if phase_conds else None,
                    phase_compare_type=phase_conds[0][0] if phase_conds else "Equal",
                    ai_flag_condition=flag_conds[0] if flag_conds else None,
                    next_ai_flag=next_flags[-1] if next_flags else None,
                    use_skills=tuple(use_skills),
                    candidate_skills=cand_skills,
                    condition_predicates=tuple(cond_preds),
                    root_task=root_task,
                    success_score=max(axis_scores) if axis_scores else 1.0,
                )
            )

        for dec in ai_doc.get("DecisionList", []):
            if not isinstance(dec, Mapping):
                continue
            dt = dec.get("$type", "")
            if "Stepper" in dt:
                gname = str(dec.get("DecisionGroupName", "Stepper"))
                for sub in dec.get("DecisionList", []):
                    if isinstance(sub, Mapping):
                        _ingest_decision(sub, gname)
            else:
                _ingest_decision(dec, "Default")

        # Build phase_sequences for phases 1..monster.max_phase
        phase_sequences: Dict[int, Tuple[Tuple[str, ...], ...]] = {}
        temp_spec = CompiledMonsterAISpec(
            monster_id=monster.monster_id,
            monster_template_id=monster.monster_template_id,
            name=monster.name,
            ai_path=monster.ai_path,
            ai_name=str(ai_doc.get("AIName", "")),
            initial_variables=init_vars,
            initial_ai_flag=initial_ai_flag,
            override_ai_skill_sequence=override_seq,
            decisions=tuple(decisions),
            phase_sequences={},
            reactive_hooks=(),
            skills_by_key=skills_by_key,
        )
        for p in range(1, max(1, monster.max_phase) + 1):
            cycle = temp_spec.trace_ai_flag_cycle(phase=p)
            if not cycle and decisions:
                cycle = tuple(
                    d.use_skills
                    for d in decisions
                    if d.phase_condition is None or d.phase_condition == p
                )
            phase_sequences[p] = cycle

        hooks = self._extract_reactive_hooks(monster)
        return CompiledMonsterAISpec(
            monster_id=monster.monster_id,
            monster_template_id=monster.monster_template_id,
            name=monster.name,
            ai_path=monster.ai_path,
            ai_name=str(ai_doc.get("AIName", "")),
            initial_variables=init_vars,
            initial_ai_flag=initial_ai_flag,
            override_ai_skill_sequence=override_seq,
            decisions=tuple(decisions),
            phase_sequences=phase_sequences,
            reactive_hooks=hooks,
            skills_by_key=skills_by_key,
        )

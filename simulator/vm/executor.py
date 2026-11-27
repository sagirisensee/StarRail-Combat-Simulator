"""官方 ConfigAbility AST Task & Predicate 解释器 + 战斗结算桥接 (Phase 3)。

将官方 `Task` 与 `Predicate` 指令集桥接到现有 `TurnSimulator` 微内核：
- Predicate 求值：`ops/predicates.py` (`PredicateOpsMixin`)；
- 伤害/治疗/能量/扣血：`ops/combat_ops.py` (`CombatOpsMixin`)；
- 回合插队/召唤/关卡事件/变身：`ops/turn_ops.py` (`TurnOpsMixin`)；
- 动态变量与属性重置：`ops/dynamic_ops.py` (`DynamicOpsMixin`)；
- Modifier/护盾/驱散/延迟：`ops/modifier_ops.py` (`ModifierOpsMixin`)；
- 关卡/怪物机制/弱点/波次：`ops/stage_ops.py` (`StageOpsMixin`)；
- 未知逻辑 `$type` 严禁静默跳过，默认抛出 `NotImplementedError`。
"""
from __future__ import annotations

import heapq
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set

from ..events import DamageAppliedEvent, WeaknessBreakEvent
from .expr import dotnet_hash, eval_dynamic_float
from .loader import PRUNABLE_PRESENTATION_TYPES
from .ops import (
    CombatOpsMixin,
    DynamicOpsMixin,
    ModifierOpsMixin,
    PredicateOpsMixin,
    StageOpsMixin,
    TurnOpsMixin,
)
from .ops.predicates import _compare_values, _str_val
from .stage_prunable_types import is_safe_prunable_type
from .target_alias import ExecutionContext, resolve_target_type


# 未实现 / 暂忽略的机械层运行时占位符：仅在 TaskExecutor 执行阶段按需跳过，
# 绝不可合入 loader.PRUNABLE_PRESENTATION_TYPES 以免加载期静默丢弃 AST 语义。
IGNORED_MECHANICAL_TASK_STUBS: Set[str] = {
    "RPG.GameCore.AttachEntityDeparted",
    "RPG.GameCore.SetMonsterEnergyBarState",
    "RPG.GameCore.TriggerCustomString",
    "RPG.GameCore.ChangeCharacterRowData",
    "RPG.GameCore.StackStatusResistance",
    "RPG.GameCore.SetResilience",
    "RPG.GameCore.CharacterChangePhase",
    "RPG.GameCore.LockTargetActionDelay",
    "RPG.GameCore.SummonPartner",
    "RPG.GameCore.SetStanceCount",
    "RPG.GameCore.PerformDelayExecute",
    "RPG.GameCore.RemoveEntityFromRelationGroup",
    "RPG.GameCore.SetEntityRelationGroup",
    "RPG.GameCore.SwitchCaseByAttackDamageType",
    "RPG.GameCore.TargetFetchUniqueNameEntity",
    "RPG.GameCore.TargetFilterAliveState",
    "RPG.GameCore.TriggerBreak",
    "RPG.GameCore.SwitchByCommandType",
    "RPG.GameCore.ToggleSpecialSkillMark",
    "RPG.GameCore.StackCrazyAIBehavior",
}

# 已确认在当前对账口径下无独立战斗副作用的混淆 $type 占位符
IGNORED_OBFUSCATED_TASK_STUBS: Set[str] = {
    "LMKKFPJBAFD",
    "BIEFKHPDHPI",
    "MJHAGGNNBIK",
    "FOIBLOANLCJ",
    "CKCOFEAAJII",
    "KADCLBEPFPL",
    "NDFKINKPKHF",
    "EOPFECKEAIK",
    "GFODFDCBFJF",
    "IKAHOOLKHDN",
    "HGHNFLIFOGP",
    "PGFAJJBCMDK",
    "MBFDBNPKBBM",
    "NKLOMENKLHK",
    "NIDNKHHNCDD",
    "CANBAEOKAJD",
    "AFGOLNPFJIF",
    "AOMNGKKKCOI",
    "BALFAPGPFGA",
    "BCNMIFBIGIE",
    "BFKKNBNIBFB",
    "CAJDCGPFPBA",
    "CPFPIKGBLFK",
    "EGKMFINAFHB",
    "HCBPOFFBEOH",
    "LBMLBLLLMGG",
    "MMBPCMGMMIH",
    "NGLKHNKNBDC",
    "OLCFDLCNOHH",
    "CGHBOOLNOOJ",
    "MFHGBPDJJPE",
    "LLFEHBKEFDM",
    "MJAPKPPJNLF",
    "PCKCEGKJFAO",
    "FCCIDFIMONC",
    "PHJFJAOILHD",
}


class TaskExecutor(
    PredicateOpsMixin,
    CombatOpsMixin,
    TurnOpsMixin,
    DynamicOpsMixin,
    ModifierOpsMixin,
    StageOpsMixin,
):
    """官方 ConfigAbility Task 与 Predicate 解释执行器。"""

    def __init__(self, runtime: Any, strict: bool = True) -> None:
        self.rt = runtime
        self.strict = strict
        self._damage_capture_stack: List[List[float]] = []

    def on_damage_applied(self, evt: DamageAppliedEvent) -> None:
        if self._damage_capture_stack:
            tgt = self.rt.sim.get_entity(evt.target_name)
            bg = bool(tgt is not None and getattr(tgt, "barrier_guarded", False))
            overflow = getattr(tgt, "_single_block_break_overflow", None) if tgt is not None else None
            if overflow is not None:
                delattr(tgt, "_single_block_break_overflow")
                self._damage_capture_stack[-1][0] += float(overflow)
                return
            if bg:
                return
            self._damage_capture_stack[-1][0] += max(0.0, float(evt.damage) - float(getattr(evt, "shield_absorbed", 0.0)))

    def on_weakness_break(self, evt: WeaknessBreakEvent) -> None:
        if self._damage_capture_stack:
            self._damage_capture_stack[-1][0] += float(evt.break_damage)
        t_ent = self.rt.sim.get_entity(evt.target_name)
        if t_ent is not None and getattr(t_ent, "is_broken", False):
            self.rt.modifier_engine.dispatch_event(
                "OnBeingBreak",
                owner_id=evt.target_name,
                param_entity_id=evt.breaker_name,
            )
            self.rt.modifier_engine.dispatch_event(
                "OnListenBreak",
                param_entity_id=evt.target_name,
            )
            if evt.action_delay_pct > 0.0 and evt.element:
                elem_map = {
                    "Physical": "MCommon_Element_Bleed",
                    "Fire": "MCommon_Element_Burn",
                    "Ice": "MCommon_Element_Frozen",
                    "Lightning": "MCommon_Element_Electric",
                    "Thunder": "MCommon_Element_Electric",
                    "Wind": "MCommon_Element_Poison",
                    "Quantum": "MCommon_Element_Entangle",
                    "Imaginary": "MCommon_Element_Confine",
                }
                mod_name = elem_map.get(evt.element)
                if mod_name and (evt.element != "Quantum" or getattr(evt, "entangle_applied", True)):
                    dyn: Dict[int, float] = {}
                    init_count: int | None = None
                    init_life: float = 2.0
                    if evt.element == "Quantum":
                        init_life = 1.0
                        dyn = {
                            dotnet_hash("MDF_DamagePercentage"): 0.6,
                            dotnet_hash("MDF_BeingHitDamageValue"): 0.0,
                            dotnet_hash("MDF_ActionDelayRatio"): 0.20,
                            560166466: 1.0,
                            808921108: 5.0,
                            dotnet_hash("Max_Count"): 5.0,
                        }
                    elif evt.element == "Wind":
                        init_life = 2.0
                        init_count = 3 if getattr(t_ent, "is_boss", False) else 1
                        dyn = {
                            dotnet_hash("MDF_DamagePercentage"): 1.0,
                            dotnet_hash("DOT_TriggerRatio"): 1.0,
                        }
                    elif evt.element == "Fire":
                        init_life = 2.0
                        dyn = {
                            dotnet_hash("MDF_DamagePercentage"): 1.0,
                            dotnet_hash("DOT_TriggerRatio"): 1.0,
                        }
                    elif evt.element in ("Lightning", "Thunder"):
                        init_life = 2.0
                        dyn = {
                            dotnet_hash("MDF_DamagePercentage"): 2.0,
                            dotnet_hash("DOT_TriggerRatio"): 1.0,
                        }
                    elif evt.element == "Ice":
                        init_life = 1.0
                        dyn = {dotnet_hash("MDF_DamagePercentage"): 1.0}
                    elif evt.element == "Physical":
                        init_life = 2.0
                        dyn = {
                            dotnet_hash("MDF_DamagePercentage"): 2.0,
                            dotnet_hash("DOT_TriggerRatio"): 1.0,
                        }
                    elif evt.element == "Imaginary":
                        init_life = 1.0
                        dyn = {
                            dotnet_hash("MDF_ActionDelayRatio"): 0.30,
                            -811945046: 0.10,
                        }
                    self.rt.modifier_engine.add_modifier(
                        owner_id=evt.target_name,
                        caster_id=evt.breaker_name,
                        mod_name=mod_name,
                        ability_name="",
                        life_time=init_life,
                        count=init_count,
                        resolved_dynamics=dyn,
                    )

    def _resolve_targets(self, target_spec: Any, ctx: ExecutionContext) -> List[str]:
        """解析 TargetType（支持 GlobalTargetAlias 查表与 TargetSequence.Sequence 管道）。"""
        if target_spec is None:
            return [ctx.caster_id] if ctx.caster_id else []
        if isinstance(target_spec, str):
            g_spec = self.rt.resolve_global_target_alias(target_spec)
            if g_spec is not None:
                return self._resolve_targets(g_spec, ctx)
            return resolve_target_type(target_spec, ctx)
        if not isinstance(target_spec, dict) and not isinstance(target_spec, Mapping):
            return []

        t = target_spec.get("$type", "")
        if t == "RPG.GameCore.TargetAlias" or ("Alias" in target_spec and not t):
            alias_str = str(target_spec.get("Alias", "")).strip()
            g_spec = self.rt.resolve_global_target_alias(alias_str)
            if g_spec is not None:
                return self._resolve_targets(g_spec, ctx)
            return resolve_target_type(target_spec, ctx)

        if t == "RPG.GameCore.TargetSequence" and "Sequence" in target_spec:
            steps = target_spec.get("Sequence") or []
            if not steps:
                return []

            def _run_sequence() -> List[str]:
                cur = self._resolve_targets(steps[0], ctx)
                me = self.rt.modifier_engine
                sim = self.rt.sim
                for step in steps[1:]:
                    if not isinstance(step, dict) and not isinstance(step, Mapping):
                        continue
                    st = step.get("$type", "")
                    if st == "RPG.GameCore.TargetFilter":
                        pred = step.get("Predicate")
                        cur = [tid for tid in cur if self.eval_predicate(pred, ctx.clone(param_entity_id=tid))]
                    elif st == "RPG.GameCore.TargetShuffle":
                        r_prov = getattr(sim, "enemy_retarget_provider", None)
                        caster_ent = sim.get_entity(ctx.caster_id)
                        dark_cands = [sim.get_entity(cid) for cid in cur]
                        dark_cands = [e for e in dark_cands if e is not None and getattr(e, "is_enemy", False)]
                        if caster_ent is not None and dark_cands and callable(r_prov):
                            picked = r_prov(caster_ent, dark_cands)
                            pname = getattr(picked, "name", picked) if picked is not None else None
                            if isinstance(pname, str) and pname in cur:
                                cur = [pname] + [cid for cid in cur if cid != pname]
                    elif st == "RPG.GameCore.TargetSortByFormation":
                        if bool(step.get("HighestFirst", False)):
                            cur = list(reversed(cur))
                    elif st == "RPG.GameCore.TargetSortMonsterRank":
                        highest = bool(step.get("HighestFirst", True))
                        cur = sorted(
                            cur,
                            key=lambda tid: getattr(sim.get_entity(tid), "max_hp", 0.0),
                            reverse=highest,
                        )
                    elif st == "RPG.GameCore.TargetReverse":
                        cur = list(reversed(cur))
                    elif st in ("RPG.GameCore.TargetSortByProperty", "RPG.GameCore.TargetSortByPropertyRatio"):
                        if st == "RPG.GameCore.TargetSortByPropertyRatio":
                            prop = str(step.get("PropertyRatioType", "HPRatio"))
                            highest = bool(step.get("HighestFirst", False))
                        else:
                            prop = str(step.get("PropertyType", "CurrentHP"))
                            highest = bool(step.get("HighestFirst", True))
                        if step.get("AliveOnly", True):
                            cur = [
                                tid for tid in cur
                                if (e_al := sim.get_entity(tid)) is not None
                                and (getattr(e_al, "current_hp", 0.0) > 0.0 or getattr(e_al, "is_infinite_hp", False))
                            ]
                        cur = sorted(cur, key=lambda tid: me.get_entity_property(tid, prop), reverse=highest)
                    elif st == "RPG.GameCore.TargetTake":
                        cnt = max(0, int(round(self._eval_num(step.get("Count"), ctx, 1.0))))
                        cur = cur[:cnt]
                    elif st == "RPG.GameCore.TargetIndex":
                        idx_spec = step.get("IndexValue") if step.get("IndexValue") is not None else step.get("Index")
                        idx = int(round(self._eval_num(idx_spec, ctx, 0.0)))
                        cur = [cur[idx]] if 0 <= idx < len(cur) else []
                    elif st == "RPG.GameCore.TargetFetchActualOwner":
                        nxt: List[str] = []
                        seen_ao: set[str] = set()
                        for tid in cur:
                            e_ao = sim.get_entity(tid)
                            if (
                                e_ao is not None
                                and not getattr(e_ao, "is_memosprite", False)
                                and getattr(e_ao, "master_name", None)
                                and sim.get_entity(e_ao.master_name) is not None
                            ):
                                resolved_id = e_ao.master_name
                            else:
                                resolved_id = tid
                            if resolved_id and resolved_id not in seen_ao:
                                seen_ao.add(resolved_id)
                                nxt.append(resolved_id)
                        cur = nxt
                    else:
                        cur = self._resolve_targets(step, ctx)
                return cur

            cur = _run_sequence()
            if not cur and not getattr(self.rt, "_include_limbo", False):
                has_added_or_alive = any(
                    isinstance(st, Mapping)
                    and st.get("$type") == "RPG.GameCore.TargetFilter"
                    and isinstance(st.get("Predicate"), Mapping)
                    and st["Predicate"].get("AddedOrAlive")
                    for st in steps[1:]
                )
                if has_added_or_alive:
                    self.rt._include_limbo = True
                    try:
                        cur = _run_sequence()
                    finally:
                        self.rt._include_limbo = False
            return cur

        if t == "RPG.GameCore.TargetConcat":
            acc: List[str] = []
            seen: set[str] = set()
            for sub in target_spec.get("Targets", []):
                for tid in self._resolve_targets(sub, ctx):
                    if tid and tid not in seen:
                        seen.add(tid)
                        acc.append(tid)
            return acc

        return resolve_target_type(target_spec, ctx)

    def _eval_num(self, spec: Any, ctx: ExecutionContext, default: float = 0.0) -> float:
        return eval_dynamic_float(
            spec,
            lambda h: self.rt.resolve_hash(ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx),
            default,
        )

    # ------------------------------------------------------------------
    # 控制流算子
    # ------------------------------------------------------------------
    def _op_predicate_task_list(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        cond = self.eval_predicate(task.get("Predicate"), ctx)
        taken = task.get("SuccessTaskList", []) if cond else task.get("FailedTaskList", [])
        skipped = task.get("FailedTaskList", []) if cond else task.get("SuccessTaskList", [])
        skip_cb = getattr(self.rt.sim, "random_config_pity_skip_cb", None)
        if callable(skip_cb) and taken and skipped:
            taken_list = list(taken)
            for sk in skipped:
                if not ((isinstance(sk, dict) or isinstance(sk, Mapping)) and sk.get("$type") == "RPG.GameCore.RandomConfig"):
                    continue
                rc_tlist = sk.get("TaskList") or ()
                matched_idx: Optional[int] = None
                for idx, rc_item in enumerate(rc_tlist):
                    if (len(taken_list) == 1 and rc_item == taken_list[0]) or rc_item == taken_list:
                        matched_idx = idx
                        break
                if matched_idx is not None:
                    skip_cb(ctx.caster_id, ctx.ability_name, matched_idx)
                    diag_cb = getattr(self.rt.sim, "timeline_diag_cb", None)
                    if callable(diag_cb):
                        diag_cb("RAND", f"{ctx.caster_id} pity_skip={matched_idx}/{len(rc_tlist)}")
                    break
        self.execute_tasks(taken, ctx)

    def _op_switch_case(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        branches = task.get("TaskList") or task.get("CaseTaskList") or ()
        for branch in branches:
            if not isinstance(branch, Mapping):
                continue
            pred = branch.get("Predicate")
            if pred is None or self.eval_predicate(pred, ctx):
                tasks = branch.get("SuccessTaskList") if "SuccessTaskList" in branch else branch.get("TaskList", [])
                self.execute_tasks(tasks or (), ctx)
                return
        self.execute_tasks(task.get("DefaultTaskList", []), ctx)

    def _op_switch_case_by_dynamic_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        if "Switch" in task:
            val = self._eval_num(task.get("Switch"), ctx, 0.0)
        else:
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            val = self.rt.get_dynamic_value(ctx.caster_id, key_h, ability_name=ctx.ability_name, local_ctx=ctx)
        cmp_mode = str(task.get("CompareType", "Equal"))
        cases = task.get("CaseTaskList") if "CaseTaskList" in task else task.get("CaseList", [])
        for c in cases:
            c_spec = c.get("Case") if "Case" in c else c.get("Value")
            c_val = self._eval_num(c_spec, ctx, 0.0)
            if _compare_values(val, c_val, cmp_mode):
                self.execute_tasks(c.get("TaskList", []), ctx)
                return
        self.execute_tasks(task.get("DefaultTaskList", []), ctx)

    def _op_condition_loop_execute_task_list(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        max_loop = (
            max(0, min(64, int(round(self._eval_num(task.get("MaxLoopCount"), ctx, 0.0)))))
            if "MaxLoopCount" in task
            else None
        )
        guard = 0
        while self.eval_predicate(task.get("Predicate"), ctx):
            if max_loop is not None and guard >= max_loop:
                break
            guard += 1
            if guard > 64:
                raise RuntimeError("ConditionLoopExecuteTaskList 超过安全循环次数上限")
            self.execute_tasks(task.get("TaskList", []), ctx)

    def _op_loop_execute_task_list(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        cnt = max(0, min(64, int(round(self._eval_num(task.get("MaxLoopCount"), ctx, 0.0)))))
        for _ in range(cnt):
            self.execute_tasks(task.get("TaskList", []), ctx)

    def _build_template_sub_ctx(self, task: Mapping[str, Any], ctx: ExecutionContext) -> ExecutionContext:
        sub_dyn = dict(ctx.local_dynamics)
        for k, v in (task.get("DynamicValues") or {}).items():
            sub_dyn[dotnet_hash(k)] = self._eval_num(v, ctx, 0.0)
        tpl_dyn = dict(sub_dyn)
        sub_strs = dict(ctx.custom_strings)
        for k, v in (task.get("DynamicStrings") or {}).items():
            if isinstance(v, Mapping) and v.get("Custom"):
                sub_strs[str(k)] = ctx.custom_strings.get(str(v.get("Key") or ""), "")
            else:
                sub_strs[str(k)] = _str_val(v)
        sub_seqs = dict(ctx.template_param_sequences)
        param_seqs = task.get("TemplateParamSequences")
        if isinstance(param_seqs, Mapping):
            sub_seqs.update(param_seqs)
        param_tgts = self._resolve_targets(task.get("ParamTarget"), ctx) if "ParamTarget" in task else []
        return ctx.clone(
            local_dynamics=sub_dyn,
            template_dynamics=tpl_dyn,
            custom_strings=sub_strs,
            param_entity_id=param_tgts[0] if param_tgts else ctx.param_entity_id,
            template_param_targets=tuple(param_tgts) if param_tgts else ctx.template_param_targets,
            template_param_sequences=sub_seqs,
        )

    def _op_include_task_list_template(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        tpl_name = _str_val(task.get("Name") or task.get("TemplateName"))
        if tpl_name in ("PursuedDamage_PerformanceDelay", "PursuedDamage_PerformanceDelay_ForSnapshotEntity"):
            return
        tpl_tasks = rt.find_template(tpl_name, ctx.ability_name)
        if tpl_tasks is None and ctx.modifier_instance is not None:
            mod_cfg = getattr(ctx.modifier_instance, "config", None) or {}
            for t_item in mod_cfg.get("TaskListTemplate") or ():
                if isinstance(t_item, Mapping) and str(t_item.get("Name") or "") == tpl_name:
                    tpl_tasks = t_item.get("TaskList") or []
                    break
        if tpl_tasks is None:
            if self.strict:
                raise KeyError(f"找不到 TaskListTemplate: {tpl_name}")
            return
        self.execute_tasks(tpl_tasks, self._build_template_sub_ctx(task, ctx))

    def _op_trigger_parallel_task_list_template(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        tpl_entries = list(task.get("Templates") or [])
        if not tpl_entries and (task.get("Name") or task.get("TemplateName")):
            tpl_entries = [{"Name": task.get("Name") or task.get("TemplateName")}]
        sub_ctx = self._build_template_sub_ctx(task, ctx)
        for entry in tpl_entries:
            tname = _str_val(entry.get("Name") if isinstance(entry, Mapping) else entry)
            if not tname:
                continue
            tpl_tasks = rt.find_template(tname, ctx.ability_name)
            if tpl_tasks is None:
                if self.strict:
                    raise KeyError(f"找不到 Parallel TaskListTemplate: {tname}")
                continue
            self.execute_tasks(tpl_tasks, sub_ctx)

    def _op_task_template_fetch_param_sequence(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        pname = str(task.get("ParamName") or "")
        entry = ctx.template_param_sequences.get(pname) if pname else None
        seq_tasks = entry.get("TaskList") if isinstance(entry, Mapping) else (entry if isinstance(entry, list) else ())
        if seq_tasks:
            self.execute_tasks(seq_tasks, ctx)

    def _op_include_global_task_list_template(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        tpl_name = _str_val(task.get("Name"))
        if tpl_name:
            rt.loader.ensure_ability_index()
            tpl_tasks = rt.loader._global_tpl_by_name.get(tpl_name)
            if isinstance(tpl_tasks, list):
                self.execute_tasks(tpl_tasks, ctx)

    def _op_trigger_ability(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        ab_name = _str_val(task.get("AbilityName"))
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        if not targets or not ab_name:
            return
        if ab_name.endswith("_Camera") or "_Camera_" in ab_name:
            return
        inherent_targets = (
            tuple(self._resolve_targets(task.get("AbilityInherentTargetType"), ctx))
            if task.get("AbilityInherentTargetType") is not None
            else ()
        )
        caster_ent = sim.get_entity(ctx.caster_id)
        caster_is_enemy = bool(getattr(caster_ent, "is_enemy", False))
        if all(not getattr(sim.get_entity(tid), "is_enemy", False) for tid in targets):
            for tid in targets:
                rt.trigger_ability(
                    caster_id=tid,
                    ability_name=ab_name,
                    target_ids=inherent_targets or (tid,),
                    skill_target_ids=ctx.skill_target_ids,
                    current_skill_type=ctx.current_skill_type,
                    current_attack_type=ctx.current_attack_type,
                )
        elif caster_is_enemy and all(getattr(sim.get_entity(tid), "is_enemy", False) for tid in targets):
            for tid in targets:
                child_targets = (
                    inherent_targets
                    if inherent_targets
                    else (
                        ctx.ability_target_ids
                        if tid == ctx.caster_id and bool(task.get("IsSkillPerform")) and ctx.ability_target_ids
                        else (tid,)
                    )
                )
                rt.trigger_ability(
                    caster_id=tid,
                    ability_name=ab_name,
                    target_ids=child_targets,
                    skill_target_ids=ctx.skill_target_ids,
                    current_skill_type=ctx.current_skill_type,
                    current_attack_type=ctx.current_attack_type,
                )
        else:
            child_targets = (
                inherent_targets
                if inherent_targets
                else (
                    ctx.ability_target_ids
                    if bool(task.get("IsSkillPerform")) and ctx.ability_target_ids
                    else tuple(targets)
                )
            )
            rt.trigger_ability(
                caster_id=ctx.caster_id,
                ability_name=ab_name,
                target_ids=child_targets,
                skill_target_ids=ctx.skill_target_ids,
                current_skill_type=ctx.current_skill_type,
                current_attack_type=ctx.current_attack_type,
            )

    def _task_has_wait_timestamp(self, task: Any) -> bool:
        if isinstance(task, list):
            return any(self._task_has_wait_timestamp(x) for x in task)
        if not isinstance(task, Mapping):
            return False
        if task.get("$type") == "RPG.GameCore.WaitParallelTimeStamp":
            return True
        for k in ("TaskList", "SuccessTaskList", "FailedTaskList", "FailTaskList"):
            sub = task.get(k)
            if isinstance(sub, list) and any(self._task_has_wait_timestamp(x) for x in sub):
                return True
        return False

    def _op_trigger_parallel_ability(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        entries = list(task.get("ParallelAbilityList") or [])
        if not entries and task.get("AbilityName"):
            entries = [{
                "TargetType": task.get("TargetType"),
                "AbilityInherentTargetType": task.get("AbilityInherentTargetType"),
                "AbilityName": task.get("AbilityName"),
            }]
        resolved_calls: List[tuple[str, str, tuple[str, ...], float]] = []
        for item in entries:
            if not isinstance(item, Mapping):
                continue
            ab_name = _str_val(item.get("AbilityName"))
            if not ab_name or ab_name.endswith("_Camera") or "_Camera_" in ab_name:
                continue
            targets = self._resolve_targets(item.get("TargetType"), ctx)
            if not targets:
                continue
            inherent = (
                tuple(self._resolve_targets(item.get("AbilityInherentTargetType"), ctx))
                if item.get("AbilityInherentTargetType") is not None
                else ()
            )
            delay = self._eval_num(item.get("Delay"), ctx, 0.0) if "Delay" in item else 0.0
            for tid in targets:
                child_targets = inherent if inherent else (tid,)
                resolved_calls.append((ab_name, tid, child_targets, float(delay)))

        if not resolved_calls:
            return

        need_timeline = any(delay > 0.0 for _, _, _, delay in resolved_calls)
        if not need_timeline:
            for ab_name, _, _, _ in resolved_calls:
                ab = rt.loader.get_ability(ab_name)
                if ab is not None and self._task_has_wait_timestamp(ab.get("OnStart", [])):
                    need_timeline = True
                    break

        if not need_timeline:
            for ab_name, tid, child_targets, _ in resolved_calls:
                rt.trigger_ability(
                    caster_id=tid,
                    ability_name=ab_name,
                    target_ids=child_targets,
                    skill_target_ids=ctx.skill_target_ids,
                    current_skill_type=ctx.current_skill_type,
                    current_attack_type=ctx.current_attack_type,
                )
            return

        class _ParallelBranch:
            __slots__ = ("order", "base_time", "cur_time", "frames", "ab_name", "tid", "ab", "branch_ctx", "started")

            def __init__(self, order: int, base_time: float, ab_name: str, tid: str, ab: Mapping[str, Any], branch_ctx: ExecutionContext) -> None:
                self.order = order
                self.base_time = base_time
                self.cur_time = base_time
                self.frames: List[List[Any]] = []
                self.ab_name = ab_name
                self.tid = tid
                self.ab = ab
                self.branch_ctx = branch_ctx
                self.started = False

        heap: List[tuple[float, int, _ParallelBranch]] = []
        for idx_call, (ab_name, tid, child_targets, delay) in enumerate(resolved_calls):
            ab = rt.loader.get_ability(ab_name)
            if ab is None:
                continue
            tgt_info = (ab.get("TargetInfo") or {}).get("TargetType", "")
            eff_targets = ctx.skill_target_ids if (tgt_info == "SkillTargetEntityList" and ctx.skill_target_ids) else child_targets
            b_ctx = ExecutionContext(
                runtime=rt,
                caster_id=tid,
                ability_name=ab_name,
                ability_target_ids=eff_targets,
                skill_target_ids=ctx.skill_target_ids or eff_targets,
                current_skill_type=ctx.current_skill_type,
                current_attack_type=ctx.current_attack_type,
            )
            br = _ParallelBranch(idx_call, delay, ab_name, tid, ab, b_ctx)
            heapq.heappush(heap, (delay, idx_call, br))

        while heap:
            wake_t, _, br = heapq.heappop(heap)
            br.cur_time = wake_t
            if not br.started:
                br.started = True
                if br.ab.get("OnAdd"):
                    add_key = (br.tid, br.ab_name)
                    if add_key not in rt._added_abilities:
                        rt._added_abilities.add(add_key)
                        self.execute_tasks(br.ab.get("OnAdd", []), br.branch_ctx)
                if "OnStart" in br.ab:
                    br.frames.append([list(br.ab.get("OnStart") or []), 0, br.branch_ctx])
            while br.frames:
                frame = br.frames[-1]
                tasks_seq, pos, f_ctx = frame
                if pos >= len(tasks_seq):
                    br.frames.pop()
                    continue
                t_item = tasks_seq[pos]
                frame[1] = pos + 1
                if not isinstance(t_item, Mapping):
                    continue
                tt = t_item.get("$type", "")
                if tt == "RPG.GameCore.WaitParallelTimeStamp":
                    target_t = br.base_time + self._eval_num(t_item.get("WaitTime"), f_ctx, 0.0)
                    if target_t > br.cur_time + 1e-9:
                        br.cur_time = target_t
                        heapq.heappush(heap, (target_t, br.order, br))
                        break
                    continue
                if tt == "RPG.GameCore.PredicateTaskList" and self._task_has_wait_timestamp(t_item):
                    sub = t_item.get("SuccessTaskList", []) if self.eval_predicate(t_item.get("Predicate"), f_ctx) else t_item.get("FailedTaskList", [])
                    if isinstance(sub, list) and sub:
                        br.frames.append([sub, 0, f_ctx])
                    continue
                if tt == "RPG.GameCore.IncludeTaskListTemplate":
                    tpl_name = _str_val(t_item.get("Name") or t_item.get("TemplateName"))
                    tpl_tasks = rt.find_template(tpl_name, f_ctx.ability_name) if tpl_name else None
                    if isinstance(tpl_tasks, list) and self._task_has_wait_timestamp(tpl_tasks):
                        br.frames.append([tpl_tasks, 0, self._build_template_sub_ctx(t_item, f_ctx)])
                        continue
                self.execute_task(t_item, f_ctx)

    def _op_retarget(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim

        def _targets_dying_state(tspec: Any) -> bool:
            if not isinstance(tspec, Mapping):
                return False
            if tspec.get("$type") == "RPG.GameCore.TargetQuery" and any(
                tok in str(tspec.get("AliveStateMask") or "")
                for tok in ("Bit_Dying", "Bit_Deathrattle", "Dead")
            ):
                return True
            return "DyingCharacter" in str(tspec.get("Alias") or "")

        def _match_retarget() -> List[str]:
            candidates = self._resolve_targets(task.get("TargetType"), ctx)
            if not getattr(rt, "_include_limbo", False) and not _targets_dying_state(task.get("TargetType")):
                candidates = [
                    cid for cid in candidates
                    if not (
                        (c_ent := sim.get_entity(cid)) is not None
                        and float(getattr(c_ent, "current_hp", 0.0)) <= 0.0
                        and not getattr(c_ent, "is_infinite_hp", False)
                        and getattr(c_ent, "_in_deathrattle_limbo", False)
                    )
                ]
            pred = task.get("Predicate")
            out: List[str] = []
            for cid in candidates:
                p_ctx = ctx.clone(param_entity_id=cid)
                if self.eval_predicate(pred, p_ctx):
                    out.append(cid)
            if "MaxNumber" in task:
                cap = max(0, int(round(self._eval_num(task.get("MaxNumber"), ctx, len(out)))))
                if task.get("ByRandom") and out and cap > 0:
                    caster_ent = sim.get_entity(ctx.caster_id)
                    if caster_ent is not None and getattr(caster_ent, "is_enemy", False):
                        t_prov = getattr(sim, "target_provider", None)
                        b_prov = getattr(sim, "blast_target_provider", None)
                        cand_ents = [sim.get_entity(cid) for cid in out]
                        cand_ents = [e for e in cand_ents if e is not None and not getattr(e, "is_enemy", False)]
                        if cand_ents:
                            picked_order: List[str] = []
                            if getattr(sim, "current_turn_entity", None) is caster_ent and callable(t_prov):
                                if not getattr(rt, "_current_enemy_skill_has_damage", True):
                                    return []
                                p0 = t_prov(caster_ent, cand_ents, 0)
                                if p0 is not None and p0.name in out:
                                    picked_order.append(p0.name)
                                    if cap > 1 and callable(b_prov):
                                        for ex in (b_prov(caster_ent, p0, cand_ents) or ()):
                                            if ex is not None and ex.name in out and ex.name not in picked_order:
                                                picked_order.append(ex.name)
                            if not picked_order and len(cand_ents) > cap:
                                a_prov = getattr(sim, "ally_retarget_provider", None)
                                if callable(a_prov):
                                    picked = a_prov(caster_ent, cand_ents)
                                    pname = getattr(picked, "name", picked) if picked is not None else None
                                    if isinstance(pname, str) and pname in out:
                                        picked_order.append(pname)
                            if picked_order:
                                out = picked_order + [cid for cid in out if cid not in picked_order]
                        elif not cand_ents:
                            r_prov = getattr(sim, "enemy_retarget_provider", None)
                            dark_cands = [sim.get_entity(cid) for cid in out]
                            dark_cands = [e for e in dark_cands if e is not None and getattr(e, "is_enemy", False)]
                            if dark_cands and callable(r_prov):
                                picked = r_prov(caster_ent, dark_cands)
                                pname = getattr(picked, "name", picked) if picked is not None else None
                                if isinstance(pname, str) and pname in out:
                                    out = [pname] + [cid for cid in out if cid != pname]
                    elif caster_ent is not None and len(out) > cap:
                        r_prov = getattr(sim, "enemy_retarget_provider", None)
                        dark_cands = [sim.get_entity(cid) for cid in out]
                        dark_cands = [e for e in dark_cands if e is not None and getattr(e, "is_enemy", False)]
                        if len(dark_cands) > cap and callable(r_prov):
                            pick_caster = sim.get_entity(ctx.modifier_owner_id) if ctx.modifier_owner_id else caster_ent
                            picked = r_prov(pick_caster or caster_ent, dark_cands)
                            pname = getattr(picked, "name", picked) if picked is not None else None
                            diag_cb = getattr(sim, "timeline_diag_cb", None)
                            if callable(diag_cb):
                                diag_cb(
                                    "RETARG",
                                    f"caster={getattr(pick_caster or caster_ent, 'name', '')} cands={[e.name for e in dark_cands]} picked={pname} ab={ctx.ability_name}",
                                )
                            if isinstance(pname, str) and pname in out:
                                out = [pname] + [cid for cid in out if cid != pname]
                        else:
                            light_cands = [sim.get_entity(cid) for cid in out]
                            light_cands = [e for e in light_cands if e is not None and not getattr(e, "is_enemy", False)]
                            a_prov = getattr(sim, "ally_retarget_provider", None)
                            if len(light_cands) > cap and callable(a_prov):
                                pick_caster = sim.get_entity(ctx.modifier_owner_id) if ctx.modifier_owner_id else caster_ent
                                picked = a_prov(pick_caster or caster_ent, light_cands)
                                pname = getattr(picked, "name", picked) if picked is not None else None
                                diag_cb = getattr(sim, "timeline_diag_cb", None)
                                if callable(diag_cb):
                                    diag_cb(
                                        "RETARG",
                                        f"caster={getattr(pick_caster or caster_ent, 'name', '')} cands={[e.name for e in light_cands]} picked={pname} ab={ctx.ability_name}",
                                    )
                                if isinstance(pname, str) and pname in out:
                                    out = [pname] + [cid for cid in out if cid != pname]
                out = out[:cap]
            return out

        matched = _match_retarget()
        if not matched and task.get("IncludeLimbo") and not getattr(rt, "_include_limbo", False):
            rt._include_limbo = True
            try:
                matched = _match_retarget()
            finally:
                rt._include_limbo = False
        if not matched:
            self.execute_tasks(task.get("FailedTaskList", []), ctx)
            return
        if len(matched) > 1 and sim is not None and hasattr(sim, "notify_entity_ready") and not getattr(sim, "_in_retarget_ready_batch", False):
            orig_notify = sim.notify_entity_ready
            deferred_ready: List[str] = []

            def _batch_notify(entity_name: str, *, allow_jump_natural: bool = False) -> None:
                if allow_jump_natural:
                    orig_notify(entity_name, allow_jump_natural=True)
                elif entity_name not in deferred_ready:
                    deferred_ready.append(entity_name)

            batch_ids = getattr(ctx, "_set_delay_zero_batch", None)
            if batch_ids is None:
                batch_ids = []
                setattr(ctx, "_set_delay_zero_batch", batch_ids)
            batch_prev_av = getattr(ctx, "_set_delay_zero_prev_av", None)
            if batch_prev_av is None:
                batch_prev_av = {}
                setattr(ctx, "_set_delay_zero_prev_av", batch_prev_av)
            sim._in_retarget_ready_batch = True
            sim.notify_entity_ready = _batch_notify
            try:
                for tid in matched:
                    t_ctx = ctx.clone(param_entity_id=tid, ability_target_ids=(tid,))
                    setattr(t_ctx, "_set_delay_zero_batch", batch_ids)
                    setattr(t_ctx, "_set_delay_zero_prev_av", batch_prev_av)
                    self.execute_tasks(task.get("TaskList", []), t_ctx)
            finally:
                sim.notify_entity_ready = orig_notify
                sim._in_retarget_ready_batch = False
            natural_due = getattr(sim, "_natural_due_names", ())
            ready_q = getattr(sim, "_ready_queue", None)
            for ename in reversed(deferred_ready):
                if isinstance(ready_q, list) and ename in ready_q and ename not in natural_due:
                    ready_q.remove(ename)
                orig_notify(ename, allow_jump_natural=False)
        else:
            batch_ids = getattr(ctx, "_set_delay_zero_batch", None)
            batch_prev_av = getattr(ctx, "_set_delay_zero_prev_av", None)
            if len(matched) > 1:
                if batch_ids is None:
                    batch_ids = []
                    setattr(ctx, "_set_delay_zero_batch", batch_ids)
                if batch_prev_av is None:
                    batch_prev_av = {}
                    setattr(ctx, "_set_delay_zero_prev_av", batch_prev_av)
            for tid in matched:
                t_ctx = ctx.clone(param_entity_id=tid, ability_target_ids=(tid,))
                if batch_ids is not None:
                    setattr(t_ctx, "_set_delay_zero_batch", batch_ids)
                if batch_prev_av is not None:
                    setattr(t_ctx, "_set_delay_zero_prev_av", batch_prev_av)
                self.execute_tasks(task.get("TaskList", []), t_ctx)

    def _op_retarget_list(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        prev_limbo = getattr(rt, "_include_limbo", False)
        if task.get("IncludeLimbo"):
            rt._include_limbo = True
        try:
            candidates = self._resolve_targets(task.get("TargetType"), ctx)
        finally:
            rt._include_limbo = prev_limbo
        pred = task.get("Predicate")
        matched_list: List[str] = []
        for cid in candidates:
            p_ctx = ctx.clone(param_entity_id=cid)
            if self.eval_predicate(pred, p_ctx):
                matched_list.append(cid)
        if not matched_list:
            self.execute_tasks(task.get("FailedTaskList", []), ctx)
            return
        t_ctx = ctx.clone(
            param_entity_id=matched_list[0] if matched_list else ctx.param_entity_id,
            template_param_targets=tuple(matched_list),
        )
        self.execute_tasks(task.get("TaskList", []), t_ctx)

    def _op_fire_projectile(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        self.execute_tasks(task.get("OnProjectileHit", []), ctx)
        self.execute_tasks(task.get("OnHit", []), ctx)

    def _op_random_config(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        tlist = task.get("TaskList") or []
        odds_list = task.get("OddsList") or []
        if tlist:
            weights = [self._eval_num(o, ctx, 0.0) for o in odds_list[:len(tlist)]] if odds_list else []
            target_id = ctx.param_entity_id or ctx.modifier_owner_id or ""
            best_idx = 0
            prov = getattr(self.rt.sim, "random_config_provider", None)
            picked = prov(ctx.caster_id, ctx.ability_name, tlist, weights) if callable(prov) else None
            if picked is None:
                t_prov = getattr(self.rt.sim, "random_config_target_provider", None)
                if callable(t_prov):
                    picked = t_prov(ctx.caster_id, target_id, ctx.ability_name, len(tlist), weights)
            src = "default"
            if picked is not None and 0 <= int(picked) < len(tlist):
                best_idx = int(picked)
                src = "oracle"
            elif weights and any(w > 0.0 for w in weights):
                best_idx = max(range(len(weights)), key=lambda i: weights[i])
                src = "weight"
            trace_rec = getattr(self.rt.sim, "rng_trace_recorder", None)
            if callable(trace_rec):
                trace_rec(
                    "RANDCFG",
                    round(float(getattr(self.rt.sim, "current_av", 0.0)), 2),
                    ctx.caster_id,
                    target_id,
                    ctx.ability_name,
                    list(weights),
                    len(tlist),
                    best_idx,
                )
            diag_cb = getattr(self.rt.sim, "timeline_diag_cb", None)
            if callable(diag_cb):
                diag_cb("RAND", f"{ctx.caster_id} pick={best_idx}/{len(tlist)} src={src}")
            chosen = tlist[best_idx]
            if isinstance(chosen, Mapping):
                self.execute_task(chosen, ctx)
            elif isinstance(chosen, list):
                self.execute_tasks(chosen, ctx)

    def _op_remodifier(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        me = rt.modifier_engine
        prev_limbo = getattr(rt, "_include_limbo", False)
        if task.get("IncludeLimbo"):
            rt._include_limbo = True
        try:
            targets = self._resolve_targets(task.get("TargetType"), ctx)
        finally:
            rt._include_limbo = prev_limbo
        bf_filter = {str(f) for f in (task.get("BehaviorFlagFilter") or ()) if f}
        pred_filter = task.get("PredicateFilter")
        task_list = task.get("TaskList") or ()
        for tid in targets:
            for m in list(me.get_modifiers(tid)):
                if m._destroyed:
                    continue
                if bf_filter and not (m.behavior_flags & bf_filter):
                    continue
                f_ctx = ctx.clone(
                    modifier_owner_id=tid,
                    modifier_instance=m,
                    param_entity_id=tid,
                    callback_modifier_name=m.name,
                    callback_behavior_flags=tuple(m.behavior_flags),
                    callback_status_type=me.get_modifier_status_type(m),
                    callback_modifier_instance=m,
                )
                if pred_filter and not self.eval_predicate(pred_filter, f_ctx):
                    continue
                self.execute_tasks(task_list, f_ctx)

    def _op_noop(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        return

    def _op_sequence_config(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        self.execute_tasks(task.get("TaskList") or (), ctx)

    # ------------------------------------------------------------------
    # Task 静态分发表（105 个官方 Task $type）与执行入口
    # ------------------------------------------------------------------
    _TASK_DISPATCH: Dict[str, Callable[..., None]] = {
        # 1. 控制流
        "RPG.GameCore.SequenceConfig": _op_sequence_config,
        "RPG.GameCore.PredicateTaskList": _op_predicate_task_list,
        "RPG.GameCore.SwitchCase": _op_switch_case,
        "RPG.GameCore.SwitchCaseByDynamicValue": _op_switch_case_by_dynamic_value,
        "RPG.GameCore.ConditionLoopExecuteTaskList": _op_condition_loop_execute_task_list,
        "RPG.GameCore.ConditionLoopExecuteTaskListWithInterval": _op_condition_loop_execute_task_list,
        "RPG.GameCore.LoopExecuteTaskList": _op_loop_execute_task_list,
        "RPG.GameCore.LoopExecuteTaskListWithInterval": _op_loop_execute_task_list,
        "RPG.GameCore.IncludeTaskListTemplate": _op_include_task_list_template,
        "RPG.GameCore.TriggerParallelTaskListTemplate": _op_trigger_parallel_task_list_template,
        "RPG.GameCore.IncludeGlobalTaskListTemplate": _op_include_global_task_list_template,
        "RPG.GameCore.TaskTemplateFetchParamSequence": _op_task_template_fetch_param_sequence,
        "RPG.GameCore.TriggerAbility": _op_trigger_ability,
        "RPG.GameCore.TriggerParallelAbility": _op_trigger_parallel_ability,
        "RPG.GameCore.WaitParallelTimeStamp": _op_noop,
        "RPG.GameCore.TriggerModifierCustomEvent": ModifierOpsMixin._op_trigger_modifier_custom_event,
        "RPG.GameCore.Retarget": _op_retarget,
        "GLOABNLLLEL": _op_retarget,
        "RPG.GameCore.RetargetList": _op_retarget_list,
        "RPG.GameCore.FireProjectile": _op_fire_projectile,
        "RPG.GameCore.NewFireProjectile": _op_fire_projectile,
        "RPG.GameCore.RandomConfig": _op_random_config,
        "RPG.GameCore.Remodifier": _op_remodifier,
        # 2. DynamicValues 与实体参数（DynamicOpsMixin）
        "RPG.GameCore.DefineDynamicValue": DynamicOpsMixin._op_define_dynamic_value,
        "RPG.GameCore.SetDynamicValue": DynamicOpsMixin._op_set_dynamic_value,
        "RPG.GameCore.SetDynamicValueInRange": DynamicOpsMixin._op_set_dynamic_value_in_range,
        "RPG.GameCore.SetDynamicValueByChangeValue": DynamicOpsMixin._op_set_dynamic_value_by_change_value,
        "RPG.GameCore.SetDynamicValueByAddValue": DynamicOpsMixin._op_set_dynamic_value_by_add_value,
        "RPG.GameCore.SetDynamicValueByProperty": DynamicOpsMixin._op_set_dynamic_value_by_property,
        "RPG.GameCore.SetDynamicValueByHPRatio": DynamicOpsMixin._op_set_dynamic_value_by_property,
        "RPG.GameCore.SetDynamicValueByCopying": DynamicOpsMixin._op_set_dynamic_value_by_copying,
        "RPG.GameCore.SetDynamicValueByModifierValue": DynamicOpsMixin._op_set_dynamic_value_by_modifier_value,
        "RPG.GameCore.SetDynamicValueByCharacterCount": DynamicOpsMixin._op_set_dynamic_value_by_character_count,
        "RPG.GameCore.SetDynamicValueByHealDataProperty": DynamicOpsMixin._op_set_dynamic_value_by_heal_data_property,
        "RPG.GameCore.SetDynamicValueByDamageDataProperty": DynamicOpsMixin._op_set_dynamic_value_by_damage_data_property,
        "RPG.GameCore.SetDynamicValueByAttackTargetCount": DynamicOpsMixin._op_set_dynamic_value_by_attack_target_count,
        "RPG.GameCore.SetDynamicValueByVariateType": DynamicOpsMixin._op_set_dynamic_value_by_variate_type,
        "RPG.GameCore.SetDynamicValueByRandom": DynamicOpsMixin._op_set_dynamic_value_by_random,
        "RPG.GameCore.SetDynamicValueByMazeBuffConfig": DynamicOpsMixin._op_set_dynamic_value_by_maze_buff_config,
        "RPG.GameCore.SetDynamicValueByHardLevelProperty": DynamicOpsMixin._op_set_dynamic_value_by_hard_level_property,
        "RPG.GameCore.SetDynamicValueByStatusCount": DynamicOpsMixin._op_set_dynamic_value_by_status_count,
        "RPG.GameCore.SetDynamicValueByBehaviorFlagCount": DynamicOpsMixin._op_set_dynamic_value_by_behavior_flag_count,
        "RPG.GameCore.SetDynamicValueByCountOfBaseType": DynamicOpsMixin._op_set_dynamic_value_by_count_of_base_type,
        "RPG.GameCore.SetDynamicEntityParam": DynamicOpsMixin._op_set_dynamic_entity_param,
        "IJJGPIPMNAE": DynamicOpsMixin._op_read_invasion_param,
        "RPG.GameCore.ReinitProperty": DynamicOpsMixin._op_reinit_property,
        "NMBCOGABNMC": DynamicOpsMixin._op_calc_elation_echo_add_value,
        "IDNEFFCGFFL": DynamicOpsMixin._op_read_modifier_config_value,
        "DIHCJLDIMNA": DynamicOpsMixin._op_set_dynamic_value_by_elation_point,
        # 3. Modifier、护盾、驱散与属性修正（ModifierOpsMixin）
        "RPG.GameCore.SetModifierDynamicValue": ModifierOpsMixin._op_set_modifier_dynamic_value,
        "RPG.GameCore.SetModifierValue": ModifierOpsMixin._op_set_modifier_value,
        "RPG.GameCore.AddModifier": ModifierOpsMixin._op_add_modifier,
        "RPG.GameCore.RemoveModifier": ModifierOpsMixin._op_remove_modifier,
        "RPG.GameCore.RemoveSelfModifier": ModifierOpsMixin._op_remove_self_modifier,
        "RPG.GameCore.RemoveModifierByBehaviorFlag": ModifierOpsMixin._op_remove_modifier_by_behavior_flag,
        "RPG.GameCore.AddBehaviorFlagForModifier": ModifierOpsMixin._op_add_behavior_flag_for_modifier,
        "RPG.GameCore.RemoveBehaviorFlagForModifier": ModifierOpsMixin._op_remove_behavior_flag_for_modifier,
        "RPG.GameCore.StackProperty": ModifierOpsMixin._op_stack_property,
        "RPG.GameCore.DispelStatus": ModifierOpsMixin._op_dispel_status,
        "RPG.GameCore.InitShield": ModifierOpsMixin._op_init_shield,
        "RPG.GameCore.RemoveShield": ModifierOpsMixin._op_remove_shield,
        "RPG.GameCore.ModifyShieldMax": ModifierOpsMixin._op_modify_shield,
        "RPG.GameCore.ModifyShield": ModifierOpsMixin._op_modify_shield,
        "RPG.GameCore.DefineHPSharedGroup": ModifierOpsMixin._op_define_hp_shared_group,
        "RPG.GameCore.SetHP": ModifierOpsMixin._op_set_hp,
        "RPG.GameCore.ModifyHealData": ModifierOpsMixin._op_modify_heal_data,
        "RPG.GameCore.ModifyDamageData": ModifierOpsMixin._op_modify_damage_data,
        "RPG.GameCore.ModifyTeamBoostPoint": ModifierOpsMixin._op_modify_team_boost_point,
        "RPG.GameCore.ModifyTeamBoostPointMax": ModifierOpsMixin._op_modify_team_boost_point_max,
        "RPG.GameCore.ModifySpecialSP": ModifierOpsMixin._op_modify_special_sp,
        "RPG.GameCore.ModifyProperty": ModifierOpsMixin._op_modify_property,
        "RPG.GameCore.ModifySkillPropertyByName": ModifierOpsMixin._op_modify_skill_property_by_name,
        "RPG.GameCore.AttachSkillTypeDisable": ModifierOpsMixin._op_attach_skill_type_disable,
        "RPG.GameCore.AttachEntityUnselectable": ModifierOpsMixin._op_attach_entity_unselectable,
        "BDDPLIAEAIN": ModifierOpsMixin._op_modify_current_modifier_dynamic_value,
        "EGAIKBNEPOG": ModifierOpsMixin._op_set_skill_tag,
        "BCOAEFIKBAO": ModifierOpsMixin._op_init_team_block,
        "PEMEHFIAHKI": ModifierOpsMixin._op_modify_team_block,
        "GDBOEBBNHLP": ModifierOpsMixin._op_consume_elation_echo_point,
        "DKHNKLPFEJN": ModifierOpsMixin._op_modify_elation_echo_add_data,
        "RPG.GameCore.ModifyActionDelay": ModifierOpsMixin._op_modify_action_delay,
        "RPG.GameCore.ResetActionDelay": ModifierOpsMixin._op_reset_action_delay,
        "RPG.GameCore.SetActionDelay": ModifierOpsMixin._op_set_action_delay,
        "RPG.GameCore.LockActionDelayChange": ModifierOpsMixin._op_lock_action_delay_change,
        "RPG.GameCore.ModifyCurrentSkillDelayCost": ModifierOpsMixin._op_modify_current_skill_delay_cost,
        "JDOLDFECMPL": ModifierOpsMixin._op_modify_elation_points,
        "RPG.GameCore.SetTargetUniqueName": ModifierOpsMixin._op_set_target_unique_name,
        "RPG.GameCore.ReleaseTargetUniqueName": ModifierOpsMixin._op_release_target_unique_name,
        "RPG.GameCore.SetEntityActionState": ModifierOpsMixin._op_set_entity_action_state,
        "RPG.GameCore.SetControlSkillMapping": ModifierOpsMixin._op_set_control_skill_mapping,
        "EOCFKGFAPHJ": ModifierOpsMixin._op_add_common_skill_pool,
        "MOPOKJECALI": ModifierOpsMixin._op_remap_control_skill_mapping,
        "DGAOCHGKJKJ": ModifierOpsMixin._op_reset_control_skill_mapping,
        "GIFBHKAGPEG": _op_noop,
        "MHJOIIOMENF": _op_noop,
        "RPG.GameCore.AttackData": ModifierOpsMixin._op_attack_data,
        "DANFCLODJNK": ModifierOpsMixin._op_remove_skill_tag,
        # 4. 战斗结算与回合插队/召唤（CombatOpsMixin / TurnOpsMixin）
        "RPG.GameCore.HealHP": CombatOpsMixin._execute_heal,
        "RPG.GameCore.DamageByAttackProperty": CombatOpsMixin._execute_damage,
        "RPG.GameCore.LoseHPByRatio": CombatOpsMixin._execute_lose_hp,
        "RPG.GameCore.LoseHP": CombatOpsMixin._execute_lose_hp,
        "RPG.GameCore.ModifySP": CombatOpsMixin._execute_modify_sp,
        "RPG.GameCore.ModifySPNew": CombatOpsMixin._execute_modify_sp_new,
        "RPG.GameCore.TurnInsertAbility": TurnOpsMixin._execute_turn_insert,
        "RPG.GameCore.TurnInsertAbilityCondition": TurnOpsMixin._execute_turn_insert,
        "RPG.GameCore.TurnInsertAction": TurnOpsMixin._execute_turn_insert,
        "RPG.GameCore.UseSkillOneMore": TurnOpsMixin._execute_use_skill_one_more,
        "KJNHIELIFEK": TurnOpsMixin._op_merged_attack_scope,
        "RPG.GameCore.CreateServant": TurnOpsMixin._execute_create_servant,
        "RPG.GameCore.CreateBattleEvent": TurnOpsMixin._execute_create_battle_event,
        "RPG.GameCore.AttachAvatarChange": TurnOpsMixin._execute_attach_avatar_change,
        "RPG.GameCore.DetachAvatarChange": TurnOpsMixin._execute_detach_avatar_change,
        "RPG.GameCore.AutoUseUltraSkill": TurnOpsMixin._execute_auto_use_ultra_skill,
        # 5. 关卡与怪物机制（StageOpsMixin）
        "RPG.GameCore.RemoveEntityFromTeamFormation": StageOpsMixin._op_toggle_team_formation,
        "RPG.GameCore.AddEntityToTeamFormation": StageOpsMixin._op_toggle_team_formation,
        "RPG.GameCore.SetCharacterFormation": StageOpsMixin._op_set_character_formation,
        "RPG.GameCore.ForceKill": StageOpsMixin._op_force_kill,
        "RPG.GameCore.DamagePerformFinish": StageOpsMixin._op_damage_perform_finish,
        "RPG.GameCore.SummonMonster": StageOpsMixin._op_summon_monster,
        "RPG.GameCore.SetMonsterPhase": StageOpsMixin._op_set_monster_phase,
        "RPG.GameCore.LockHP": StageOpsMixin._op_stage_runner_task,
        "RPG.GameCore.ResetStance": StageOpsMixin._op_stage_runner_task,
        "RPG.GameCore.ExitBreakState": StageOpsMixin._op_stage_runner_task,
        "RPG.GameCore.StackWeakness": StageOpsMixin._op_stack_weakness,
        "RPG.GameCore.ClearWeakness": StageOpsMixin._op_clear_weakness,
        "RPG.GameCore.StackWeakResistance": StageOpsMixin._op_stack_weak_resistance,
        "RPG.GameCore.TriggerStanceCountDown": StageOpsMixin._op_trigger_stance_count_down,
        "OOCOGGMJLBN": StageOpsMixin._op_init_single_block,
        "RPG.GameCore.AddStageAbilityByName": StageOpsMixin._op_add_stage_ability_by_name,
        "RPG.GameCore.DamageStance": StageOpsMixin._op_damage_stance,
        "RPG.GameCore.DestroyBattleCharacter": StageOpsMixin._op_destroy_battle_character,
        "RPG.GameCore.LockTargetHP": StageOpsMixin._op_lock_target_hp,
        "RPG.GameCore.UnlockTargetHP": StageOpsMixin._op_unlock_target_hp,
        "FBCGHKLKHJN": StageOpsMixin._op_disable_locked_hp,
        "RPG.GameCore.SetDieImmediately": StageOpsMixin._op_set_die_immediately,
        "RPG.GameCore.OwnerEntityAddAbility": StageOpsMixin._op_owner_entity_add_ability,
        "RPG.GameCore.InfiniteWaveAddCurWaveMaxCount": StageOpsMixin._op_infinite_wave_add_max_count,
        "RPG.GameCore.RecordEntityFormationIndex": StageOpsMixin._op_record_entity_formation_index,
        "RPG.GameCore.InfiniteWaveNextMonsterId": StageOpsMixin._op_infinite_wave_next_monster_id,
        "RPG.GameCore.ClearRecordEntityFormation": StageOpsMixin._op_clear_record_entity_formation,
        "RPG.GameCore.SetLevelChallengeTurnLimit": StageOpsMixin._op_set_level_challenge_turn_limit,
        "RPG.GameCore.LevelChallengeTurnAcc": StageOpsMixin._op_level_challenge_turn_acc,
        "RPG.GameCore.EnableNegativeHP": StageOpsMixin._op_enable_negative_hp,
        "RPG.GameCore.AbortInsertAbility": StageOpsMixin._op_abort_insert_ability,
        "RPG.GameCore.ShowBattleCardBuffSelection": StageOpsMixin._op_show_battle_card_buff_selection,
        "RPG.GameCore.SetDynamicValueByBPChange": DynamicOpsMixin._op_set_dynamic_value_by_bp_change,
        "RPG.GameCore.SetDynamicValueByCurrentBP": DynamicOpsMixin._op_set_dynamic_value_by_current_bp,
        "RPG.GameCore.SetDynamicValueByMaxBP": DynamicOpsMixin._op_set_dynamic_value_by_max_bp,
        "RPG.GameCore.SetDynamicValueByElationTimeSkillCount": DynamicOpsMixin._op_set_dynamic_value_by_elation_time_skill_count,
        "RPG.GameCore.SetDynamicString": DynamicOpsMixin._op_set_dynamic_string,
        "RPG.GameCore.SetDynamicValueBySkillProperty": DynamicOpsMixin._op_set_dynamic_value_by_skill_property,
        "RPG.GameCore.GlobalModifyInsertAbilityPriority": _op_noop,
        "ELLFLJKDCAE": TurnOpsMixin._execute_start_elation_time,
        "LAJIKDENEOO": DynamicOpsMixin._op_modify_dynamic_value_clamped,
        "RPG.GameCore.ModifyEntityBoostPoint": ModifierOpsMixin._op_modify_entity_boost_point,
        "RPG.GameCore.TriggerSkipDeadHandler": _op_noop,
    }

    def execute_tasks(self, tasks: Sequence[Mapping[str, Any]], ctx: ExecutionContext) -> None:
        for task in tasks:
            if isinstance(task, dict) or isinstance(task, Mapping):
                self.execute_task(task, ctx)

    def execute_task(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        t = task.get("$type", "")
        if not t or t in PRUNABLE_PRESENTATION_TYPES or t.endswith("ClientOnly"):
            return

        handler = self._TASK_DISPATCH.get(t)
        if handler is not None:
            handler(self, task, ctx)
            return

        if t in IGNORED_MECHANICAL_TASK_STUBS or t in IGNORED_OBFUSCATED_TASK_STUBS:
            return

        if is_safe_prunable_type(t):
            return

        if self.strict:
            raise NotImplementedError(f"未实现的 Task 节点类型: {t}")

"""官方 ConfigAbility AST Task & Predicate 解释器 + 战斗结算桥接 (Phase 3)。

将官方 `Task` 与 `Predicate` 指令集桥接到现有 `TurnSimulator` 微内核：
- Predicate 求值：`ops/predicates.py` (`PredicateOpsMixin`)；
- 伤害/治疗/能量/扣血：`ops/combat_ops.py` (`CombatOpsMixin`)；
- 回合插队/召唤/关卡事件/变身：`ops/turn_ops.py` (`TurnOpsMixin`)；
- 未知逻辑 `$type` 严禁静默跳过，默认抛出 `NotImplementedError`。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from ..events import DamageAppliedEvent, HPLostEvent, WeaknessBreakEvent
from ..status import StatType
from .expr import dotnet_hash, eval_dynamic_float
from .loader import PRUNABLE_PRESENTATION_TYPES
from .ops import CombatOpsMixin, PredicateOpsMixin, TurnOpsMixin
from .ops.predicates import _compare_values, _is_alive, _str_val
from .stage_prunable_types import is_safe_prunable_type
from .target_alias import ExecutionContext, resolve_target_type


# 未实现 / 暂忽略的机械层运行时占位符：仅在 TaskExecutor 执行阶段按需跳过，
# 绝不可合入 loader.PRUNABLE_PRESENTATION_TYPES 以免加载期静默丢弃 AST 语义。
IGNORED_MECHANICAL_TASK_STUBS: Set[str] = {
    "RPG.GameCore.AttachEntityUnselectable",
    "RPG.GameCore.AttachEntityDeparted",
    "RPG.GameCore.SetMonsterEnergyBarState",
    "RPG.GameCore.TriggerCustomString",
    "RPG.GameCore.ChangeCharacterRowData",
    "RPG.GameCore.StackStatusResistance",
    "RPG.GameCore.SetResilience",
    "RPG.GameCore.CharacterChangePhase",
    "RPG.GameCore.LockActionDelayChange",
    "RPG.GameCore.LockTargetActionDelay",
    "RPG.GameCore.AttachSkillTypeDisable",
    "RPG.GameCore.SummonPartner",
    "RPG.GameCore.Remodifier",
    "RPG.GameCore.TriggerModifierCustomEvent",
    "RPG.GameCore.SetStanceCount",
    "RPG.GameCore.PerformDelayExecute",
    "RPG.GameCore.RemoveEntityFromRelationGroup",
    "RPG.GameCore.SetEntityRelationGroup",
    "RPG.GameCore.SwitchCaseByAttackDamageType",
    "RPG.GameCore.TargetFetchUniqueNameEntity",
    "RPG.GameCore.TargetFilterAliveState",
    "RPG.GameCore.TriggerBreak",
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
}


class TaskExecutor(PredicateOpsMixin, CombatOpsMixin, TurnOpsMixin):
    """官方 ConfigAbility Task 与 Predicate 解释执行器。"""

    def __init__(self, runtime: Any, strict: bool = True) -> None:
        self.rt = runtime
        self.strict = strict
        self._damage_capture_stack: List[List[float]] = []
        if getattr(runtime, "sim", None) is not None and getattr(runtime.sim, "event_bus", None) is not None:
            runtime.sim.event_bus.subscribe(DamageAppliedEvent, self._on_damage_applied)
            runtime.sim.event_bus.subscribe(WeaknessBreakEvent, self._on_weakness_break)

    def _on_damage_applied(self, evt: DamageAppliedEvent) -> None:
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

    def _on_weakness_break(self, evt: WeaknessBreakEvent) -> None:
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
            if (
                evt.action_delay_pct > 0.0
                and evt.element
                and (evt.element != "Quantum" or getattr(evt, "entangle_applied", True))
            ):
                self.rt.modifier_engine.add_modifier(
                    owner_id=evt.target_name,
                    caster_id=evt.breaker_name,
                    mod_name=f"MCommon_BreakDebuff_{evt.element}",
                    ability_name="BreakDebuff",
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
        if not isinstance(target_spec, Mapping):
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
                    if not isinstance(step, Mapping):
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
                    elif st == "RPG.GameCore.TargetSortByProperty":
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

    def _dyn_scope_entity(self, task: Mapping[str, Any], ctx: ExecutionContext) -> str:
        scope = task.get("ContextScope", "")
        if scope == "SummonerEntity":
            t = self._resolve_targets(task.get("TargetType") or {"Alias": "CasterSummoner"}, ctx)
            return t[0] if t else ctx.caster_id
        if "TargetType" in task:
            t = self._resolve_targets(task["TargetType"], ctx)
            if t:
                return t[0]
        if scope == "Modifier":
            return ctx.modifier_owner_id or ctx.caster_id
        return ctx.caster_id

    def _write_dyn(
        self,
        task: Mapping[str, Any],
        ctx: ExecutionContext,
        key_h: int,
        value: float,
    ) -> None:
        mod_target = None
        scope = task.get("ContextScope", "")
        target_id = self._dyn_scope_entity(task, ctx)
        if ctx.modifier_instance is not None:
            if scope in ("Modifier", "ContextModifier"):
                mod_target = ctx.modifier_instance
            elif scope not in ("ContextCaster", "SummonerEntity", "TargetEntity"):
                mod_floats = ctx.modifier_instance.config.get("DynamicValues", {}).get("Floats", {})
                if str(key_h) in mod_floats or key_h in ctx.modifier_instance.dynamic_values:
                    if "TargetType" not in task or target_id == ctx.modifier_instance.owner_id:
                        mod_target = ctx.modifier_instance
        eff_ab = "" if (target_id == "__LEVEL__" and scope != "ContextAbility") else ctx.ability_name
        self.rt.set_dynamic_value(
            target_id,
            key_h,
            value,
            modifier=mod_target,
            ability_name=eff_ab,
        )

    # ------------------------------------------------------------------
    # Task 列表执行
    # ------------------------------------------------------------------
    def execute_tasks(self, tasks: Sequence[Mapping[str, Any]], ctx: ExecutionContext) -> None:
        for task in tasks:
            if isinstance(task, Mapping):
                self.execute_task(task, ctx)

    def execute_task(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        t = task.get("$type", "")
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        if not t or t in PRUNABLE_PRESENTATION_TYPES or t.endswith("ClientOnly"):
            return

        # 1. 控制流
        if t == "RPG.GameCore.PredicateTaskList":
            if self.eval_predicate(task.get("Predicate"), ctx):
                self.execute_tasks(task.get("SuccessTaskList", []), ctx)
            else:
                self.execute_tasks(task.get("FailedTaskList", []), ctx)
            return

        if t == "RPG.GameCore.SwitchCaseByDynamicValue":
            if "Switch" in task:
                val = self._eval_num(task.get("Switch"), ctx, 0.0)
            else:
                key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
                val = rt.get_dynamic_value(ctx.caster_id, key_h, ability_name=ctx.ability_name, local_ctx=ctx)
            cmp_mode = str(task.get("CompareType", "Equal"))
            cases = task.get("CaseTaskList") if "CaseTaskList" in task else task.get("CaseList", [])
            for c in cases:
                c_spec = c.get("Case") if "Case" in c else c.get("Value")
                c_val = self._eval_num(c_spec, ctx, 0.0)
                if _compare_values(val, c_val, cmp_mode):
                    self.execute_tasks(c.get("TaskList", []), ctx)
                    return
            self.execute_tasks(task.get("DefaultTaskList", []), ctx)
            return

        if t == "RPG.GameCore.ConditionLoopExecuteTaskList":
            guard = 0
            while self.eval_predicate(task.get("Predicate"), ctx):
                guard += 1
                if guard > 64:
                    raise RuntimeError("ConditionLoopExecuteTaskList 超过安全循环次数上限")
                self.execute_tasks(task.get("TaskList", []), ctx)
            return

        if t in ("RPG.GameCore.LoopExecuteTaskList", "RPG.GameCore.LoopExecuteTaskListWithInterval"):
            cnt = max(0, min(64, int(round(self._eval_num(task.get("MaxLoopCount"), ctx, 0.0)))))
            for _ in range(cnt):
                self.execute_tasks(task.get("TaskList", []), ctx)
            return

        if t == "RPG.GameCore.IncludeTaskListTemplate":
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
            sub_dyn = dict(ctx.local_dynamics)
            for k, v in (task.get("DynamicValues") or {}).items():
                sub_dyn[dotnet_hash(k)] = self._eval_num(v, ctx, 0.0)
            param_tgts = self._resolve_targets(task.get("ParamTarget"), ctx) if "ParamTarget" in task else []
            sub_ctx = ctx.clone(
                local_dynamics=sub_dyn,
                param_entity_id=param_tgts[0] if param_tgts else ctx.param_entity_id,
                template_param_targets=tuple(param_tgts) if param_tgts else ctx.template_param_targets,
            )
            self.execute_tasks(tpl_tasks, sub_ctx)
            return

        if t == "RPG.GameCore.TriggerParallelTaskListTemplate":
            tpl_entries = list(task.get("Templates") or [])
            if not tpl_entries and (task.get("Name") or task.get("TemplateName")):
                tpl_entries = [{"Name": task.get("Name") or task.get("TemplateName")}]
            sub_dyn = dict(ctx.local_dynamics)
            for k, v in (task.get("DynamicValues") or {}).items():
                sub_dyn[dotnet_hash(k)] = self._eval_num(v, ctx, 0.0)
            param_tgts = self._resolve_targets(task.get("ParamTarget"), ctx) if "ParamTarget" in task else []
            sub_ctx = ctx.clone(
                local_dynamics=sub_dyn,
                param_entity_id=param_tgts[0] if param_tgts else ctx.param_entity_id,
                template_param_targets=tuple(param_tgts) if param_tgts else ctx.template_param_targets,
            )
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
            return

        if t == "RPG.GameCore.TriggerAbility":
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
            return

        if t == "RPG.GameCore.TriggerParallelAbility":
            entries = list(task.get("ParallelAbilityList") or [])
            if not entries and task.get("AbilityName"):
                entries = [{"TargetType": task.get("TargetType"), "AbilityName": task.get("AbilityName")}]
            resolved_calls: List[tuple[str, List[str]]] = []
            for item in entries:
                if not isinstance(item, Mapping):
                    continue
                ab_name = _str_val(item.get("AbilityName"))
                if not ab_name or ab_name.endswith("_Camera") or "_Camera_" in ab_name:
                    continue
                targets = self._resolve_targets(item.get("TargetType"), ctx)
                if targets:
                    resolved_calls.append((ab_name, list(targets)))
            for ab_name, targets in resolved_calls:
                for tid in targets:
                    rt.trigger_ability(
                        caster_id=tid,
                        ability_name=ab_name,
                        target_ids=(tid,),
                        skill_target_ids=ctx.skill_target_ids,
                        current_skill_type=ctx.current_skill_type,
                        current_attack_type=ctx.current_attack_type,
                    )
            return

        if t == "RPG.GameCore.Retarget":
            def _match_retarget() -> List[str]:
                candidates = self._resolve_targets(task.get("TargetType"), ctx)
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
                            if cand_ents and callable(t_prov):
                                if not getattr(rt, "_current_enemy_skill_has_damage", True):
                                    return []
                                picked_order: List[str] = []
                                p0 = t_prov(caster_ent, cand_ents, 0)
                                if p0 is not None and p0.name in out:
                                    picked_order.append(p0.name)
                                    if cap > 1 and callable(b_prov):
                                        for ex in (b_prov(caster_ent, p0, cand_ents) or ()):
                                            if ex is not None and ex.name in out and ex.name not in picked_order:
                                                picked_order.append(ex.name)
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
                    out = out[:cap]
                return out

            matched = _match_retarget()
            if not matched and task.get("IncludeLimbo") and not getattr(self.rt, "_include_limbo", False):
                self.rt._include_limbo = True
                try:
                    matched = _match_retarget()
                finally:
                    self.rt._include_limbo = False
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

                sim._in_retarget_ready_batch = True
                sim.notify_entity_ready = _batch_notify
                try:
                    for tid in matched:
                        t_ctx = ctx.clone(param_entity_id=tid, ability_target_ids=(tid,))
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
                for tid in matched:
                    t_ctx = ctx.clone(param_entity_id=tid, ability_target_ids=(tid,))
                    self.execute_tasks(task.get("TaskList", []), t_ctx)
            return

        if t == "RPG.GameCore.RetargetList":
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
            return

        if t in ("RPG.GameCore.FireProjectile", "RPG.GameCore.NewFireProjectile"):
            self.execute_tasks(task.get("OnProjectileHit", []), ctx)
            self.execute_tasks(task.get("OnHit", []), ctx)
            return

        # 2. DynamicValues 操作
        if t == "RPG.GameCore.DefineDynamicValue":
            val_spec = task.get("Value") if "Value" in task else task.get("ResetValue")
            if val_spec is not None:
                key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
                val = self._eval_num(val_spec, ctx, 0.0)
                self._write_dyn(task, ctx, key_h, val)
            else:
                target_id = self._dyn_scope_entity(task, ctx)
                t_ent = sim.get_entity(target_id)
                if target_id == "__LEVEL__" or (t_ent is not None and getattr(t_ent, "is_enemy", False)):
                    key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
                    scope = task.get("ContextScope", "")
                    if scope == "TargetEntity" or key_h not in rt.entity_dynamics.get(target_id, {}):
                        self._write_dyn(task, ctx, key_h, 0.0)
            return

        if t == "RPG.GameCore.SetDynamicValue":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
            val = self._eval_num(task.get("Value"), ctx, 0.0)
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByChangeValue":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
            val = float(getattr(ctx, "change_value", 0.0) or 0.0)
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByAddValue":
            key_str = _str_val(task.get("DynamicKey") or task.get("Key"))
            key_h = dotnet_hash(key_str)
            delta = self._eval_num(task.get("AddValue") or task.get("Value"), ctx, 0.0)
            target_id = self._dyn_scope_entity(task, ctx)
            cur = rt.get_dynamic_value(target_id, key_h, ability_name=ctx.ability_name, local_ctx=ctx)
            nxt = cur + delta
            if "Min" in task:
                nxt = max(self._eval_num(task["Min"], ctx, nxt), nxt)
            if "Max" in task:
                nxt = min(self._eval_num(task["Max"], ctx, nxt), nxt)
            self._write_dyn(task, ctx, key_h, nxt)
            return

        if t in ("RPG.GameCore.SetDynamicValueByProperty", "RPG.GameCore.SetDynamicValueByHPRatio"):
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            read_spec = task.get("ReadTargetType") or {"Alias": "ModifierOwnerEntity"}
            prop_name = "HPRatio" if t == "RPG.GameCore.SetDynamicValueByHPRatio" else str(task.get("Value", ""))
            is_snap = isinstance(read_spec, Mapping) and read_spec.get("Alias") == "SnapshotPropertyEntity"
            val: Optional[float] = None
            if is_snap and ctx.modifier_instance is not None:
                snap_props = getattr(ctx.modifier_instance, "caster_snapshot_props", None)
                if isinstance(snap_props, Mapping) and prop_name in snap_props:
                    val = float(snap_props[prop_name])
                elif getattr(ctx.modifier_instance, "caster_snapshot_entity", None) is not None:
                    val = me.get_entity_property(
                        ctx.modifier_instance.caster_id,
                        prop_name,
                        entity_override=ctx.modifier_instance.caster_snapshot_entity,
                    )
            if val is None:
                read_targets = self._resolve_targets(read_spec, ctx)
                val = me.get_entity_property(read_targets[0], prop_name) if read_targets else 0.0
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByCopying":
            from_t = self._resolve_targets(task.get("FromTargetType"), ctx)
            to_t = self._resolve_targets(task.get("ToTargetType") or {"Alias": "ModifierOwnerEntity"}, ctx)
            fk = dotnet_hash(_str_val(task.get("FromDynamicKey")))
            tk = dotnet_hash(_str_val(task.get("ToDynamicKey")))
            from_mod = _str_val(task.get("FromModifierName"))
            if from_t and to_t:
                val = None
                if from_mod:
                    mods = me.get_modifiers(from_t[0], from_mod)
                    if mods and fk in mods[0].dynamic_values:
                        val = mods[0].dynamic_values[fk]
                if val is None:
                    val = rt.get_dynamic_value(from_t[0], fk, ability_name=ctx.ability_name, local_ctx=ctx)
                mod_target = ctx.modifier_instance if ("ToTargetType" not in task and ctx.modifier_instance is not None) else None
                rt.set_dynamic_value(to_t[0], tk, val, modifier=mod_target)
            return

        if t == "RPG.GameCore.SetDynamicValueByModifierValue":
            mname = _str_val(task.get("ModifierName"))
            targets = self._resolve_targets(task.get("TargetType"), ctx) if "TargetType" in task else [ctx.modifier_owner_id or ctx.caster_id]
            mod = None
            if ctx.modifier_instance is not None and (not mname or ctx.modifier_instance.name == mname):
                mod = ctx.modifier_instance
            elif targets and mname:
                found = me.get_modifiers(targets[0], mname)
                if found:
                    mod = found[0]
            val = 0.0
            if mod is not None:
                vtype = str(task.get("ValueType", "Layer"))
                if vtype == "Layer":
                    val = float(mod.layer)
                elif vtype == "LifeTime":
                    val = float(mod.life_time or 0.0)
            mult = self._eval_num(task.get("Multiplier"), ctx, 1.0)
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            self._write_dyn(task, ctx, key_h, val * mult)
            return

        if t == "RPG.GameCore.SetDynamicValueByCharacterCount":
            targets = self._resolve_targets(task.get("ReadTargetType") or task.get("TargetType"), ctx)
            if bool(task.get("AliveOnly", False)):
                alive_targets = []
                for tid in targets:
                    e_cnt = sim.get_entity(tid)
                    if e_cnt is None:
                        continue
                    if getattr(e_cnt, "_in_deathrattle_limbo", False):
                        continue
                    if getattr(e_cnt, "_vm_limbo_pending", False) and self.rt.modifier_engine.has_behavior_flag(tid, "Deathrattle"):
                        continue
                    if getattr(e_cnt, "current_hp", 0.0) > 0 or getattr(e_cnt, "is_infinite_hp", False):
                        alive_targets.append(tid)
                targets = alive_targets
            sub_pred = task.get("Predicate")
            if sub_pred:
                targets = [tid for tid in targets if self.eval_predicate(sub_pred, ctx.clone(param_entity_id=tid, caster_id=tid))]
            cnt = float(len(targets))
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            self._write_dyn(task, ctx, key_h, cnt)
            return

        if t == "RPG.GameCore.SetDynamicValueByHealDataProperty":
            hd = ctx.heal_data or {}
            prop = str(task.get("Property", "HealValue"))
            val = float(hd.get(prop, hd.get("HealValue", 0.0)))
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByDamageDataProperty":
            dd = ctx.damage_data or {}
            prop = str(task.get("Property", "FinalDamage"))
            val = float(dd.get(prop, 0.0))
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByAttackTargetCount":
            cnt = float(len(ctx.attack_target_ids or ctx.ability_target_ids))
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            self._write_dyn(task, ctx, key_h, cnt)
            return

        if t == "RPG.GameCore.SetDynamicValueByVariateType":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            vtype = str(task.get("VariateType", "ParamValue"))
            if vtype == "ParamValue":
                val = float(ctx.change_value)
            elif vtype == "MaxMonsterPhase":
                owner_tid = ctx.modifier_owner_id or ctx.caster_id
                director = getattr(sim, "_stage_director", None)
                runner = getattr(director, "runner", None) if director is not None else None
                val = 1.0
                if runner is not None:
                    try:
                        val = float(runner.get_enemy_state(owner_tid).max_phase)
                    except KeyError:
                        val = 1.0
            else:
                val = 0.0
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByRandom":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            lo = self._eval_num(task.get("Min"), ctx, 0.0)
            hi = self._eval_num(task.get("Max"), ctx, lo)
            val = float(int(lo)) if task.get("IsInt") else (lo + hi) * 0.5
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetModifierDynamicValue":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            mname = _str_val(task.get("ModifierName"))
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            val_spec = task.get("NewValue") if "NewValue" in task else task.get("Value")
            val = self._eval_num(val_spec, ctx, 0.0)
            for tid in targets:
                for m in me.get_modifiers(tid, mname):
                    old_val = m.dynamic_values.get(key_h, 0.0)
                    m.dynamic_values[key_h] = val
                    me.check_dynamic_value_changes(m.owner_id, key_h, old_val, val)
            return

        if t == "RPG.GameCore.SetModifierValue":
            targets = self._resolve_targets(task.get("TargetType"), ctx) if "TargetType" in task else [ctx.modifier_owner_id or ctx.caster_id]
            mname = _str_val(task.get("ModifierName"))
            mfunc = str(task.get("ModifyFunction", "Set"))
            vtype = str(task.get("ValueType") or "Layer")
            val = self._eval_num(task.get("Value"), ctx, -1.0 if mfunc == "Add" else 0.0)
            for tid in targets:
                mods = [ctx.modifier_instance] if (not mname and ctx.modifier_instance is not None) else me.get_modifiers(tid, mname)
                for m in mods:
                    if vtype == "LifeTime":
                        if mfunc == "Add":
                            m.life_time = (m.life_time or 0.0) + val
                        elif mfunc in ("Sub", "Minus"):
                            m.life_time = max(0.0, (m.life_time or 0.0) - val)
                        else:
                            m.life_time = val
                    elif vtype == "Layer":
                        if mfunc == "Add":
                            m.layer = max(0, int(round(m.layer + val)))
                        elif mfunc in ("Sub", "Minus"):
                            m.layer = max(0, int(round(m.layer - val)))
                        else:
                            m.layer = max(0, int(round(val)))
                    if vtype == "Layer" and m.layer <= 0 and "RetainCountZero" not in m.behavior_flags:
                        me.destroy_modifier(m)
            return

        # 3. Modifier 与属性操作
        if t == "RPG.GameCore.AddModifier":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            mname = _str_val(task.get("ModifierName"))
            chance_spec = task.get("Chance")
            chance_val: Optional[float] = None
            if chance_spec is not None:
                chance_val = self._eval_num(chance_spec, ctx, 1.0)
                if chance_val <= 0.0:
                    return
            life = self._eval_num(task["LifeTime"], ctx) if "LifeTime" in task else None
            cnt_spec = task.get("LayerAddWhenStack") if "LayerAddWhenStack" in task else task.get("Count")
            cnt = int(round(self._eval_num(cnt_spec, ctx, 1.0))) if cnt_spec is not None else None
            max_l = int(round(self._eval_num(task["MaxLayer"], ctx, 1.0))) if "MaxLayer" in task else None
            inherit = str(task.get("InheritCaster", ""))
            alive_only = bool(task.get("AliveOnly", True))
            for tid in targets:
                if alive_only and tid != "__LEVEL__":
                    t_chk = sim.get_entity(tid)
                    if (
                        t_chk is None
                        or (
                            float(getattr(t_chk, "current_hp", 0.0)) <= 0.0
                            and not getattr(t_chk, "is_infinite_hp", False)
                        )
                        or getattr(t_chk, "_vm_limbo_pending", False)
                    ):
                        continue
                if inherit == "TargetSelf":
                    eff_caster = tid
                elif inherit == "CasterSelf":
                    eff_caster = ctx.modifier_owner_id or ctx.caster_id
                else:
                    eff_caster = ctx.caster_id
                if chance_val is not None:
                    caster_ent = sim.get_entity(eff_caster)
                    tgt_ent = sim.get_entity(tid)
                    if (
                        caster_ent is not None
                        and tgt_ent is not None
                        and getattr(caster_ent, "is_enemy", False)
                        and not getattr(tgt_ent, "is_enemy", False)
                    ):
                        hit_provider = getattr(sim, "enemy_debuff_hit_provider", None)
                        if callable(hit_provider):
                            if not hit_provider(caster_ent, tgt_ent, mname, chance_val):
                                continue
                        else:
                            sm = getattr(sim, "status_mgr", None)
                            eff_res = (
                                sm.calculate_stat(tid, getattr(tgt_ent, "base_effect_res", 0.0), StatType.EFFECT_RES)
                                if sm is not None
                                else float(getattr(tgt_ent, "base_effect_res", 0.0))
                            )
                            atk_ehr = float(getattr(caster_ent, "base_effect_hit_rate", 0.0))
                            if chance_val * (1.0 + atk_ehr) * max(0.0, 1.0 - eff_res) < 0.5:
                                continue
                me.add_modifier(
                    owner_id=tid,
                    caster_id=eff_caster,
                    mod_name=mname,
                    ability_name=ctx.ability_name,
                    dynamic_values=task.get("DynamicValues"),
                    life_time=life,
                    count=cnt,
                    max_layer=max_l,
                    ctx=ctx,
                )
            return

        if t == "RPG.GameCore.RemoveModifier":
            rt = getattr(sim, "vm_runtime", None)
            prev_limbo = getattr(rt, "_include_limbo", False) if rt is not None else False
            prev_phase_limbo = getattr(rt, "_include_phase_limbo", False) if rt is not None else False
            if rt is not None:
                rt._include_limbo = True
                rt._include_phase_limbo = True
            try:
                targets = self._resolve_targets(task.get("TargetType"), ctx)
            finally:
                if rt is not None:
                    rt._include_limbo = prev_limbo
                    rt._include_phase_limbo = prev_phase_limbo
            mname = _str_val(task.get("ModifierName"))
            only_caster = bool(task.get("OnlyRemoveCasterAdded", False))
            for tid in targets:
                me.remove_modifier(tid, mname, caster_id=ctx.caster_id, only_remove_caster_added=only_caster)
            return

        if t == "RPG.GameCore.RemoveSelfModifier":
            if ctx.modifier_instance is not None:
                me.destroy_modifier(ctx.modifier_instance)
            return

        if t == "RPG.GameCore.RemoveModifierByBehaviorFlag":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            flags: Set[str] = set()
            raw_flags = task.get("ModifierBehaviorFlags")
            if isinstance(raw_flags, list):
                flags.update(str(f) for f in raw_flags if f)
            single_flag = str(task.get("BehaviorFlag", "") or "")
            if single_flag:
                flags.add(single_flag)
            director = getattr(sim, "_stage_director", None)
            break_helper = getattr(director, "_break_helper", None) if director is not None else None
            for tid in targets:
                if flags:
                    for m in list(me.get_modifiers(tid)):
                        if m.behavior_flags & flags:
                            me.destroy_modifier(m)
                if "STAT_CTRL" in flags and break_helper is not None:
                    break_helper.quantum_entanglements.pop(tid, None)
            return

        if t == "RPG.GameCore.StackProperty":
            prop_name = str(task.get("Property", ""))
            val = self._eval_num(task.get("PropertyValue"), ctx, 0.0)
            is_conv = bool(task.get("IsConvert", False))
            is_refresh = bool(task.get("IsRefresh", False))
            if ctx.modifier_instance is not None:
                me.stack_property(ctx.modifier_instance, prop_name, val, is_convert=is_conv, is_refresh=is_refresh)
            return

        if t == "RPG.GameCore.DispelStatus":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            count = max(1, int(round(self._eval_num(task.get("Numbers"), ctx, 1.0)))) if "Numbers" in task else 99
            req_flags = set(task.get("BehaviorFlags") or [])
            order = str(task.get("Order", "LastAdded"))
            director = getattr(sim, "_stage_director", None)
            break_helper = getattr(director, "_break_helper", None) if director is not None else None
            for tid in targets:
                sim.port.dispel(tid, is_debuff=True)
                mods = list(me.get_modifiers(tid))
                if req_flags:
                    cands = [m for m in mods if (m.behavior_flags & req_flags) and m.halo_parent_uid is None]
                else:
                    cands = [
                        m for m in mods
                        if (
                            (
                                me.get_modifier_status_type(m) == "Debuff"
                                or ("STAT_CTRL" in m.behavior_flags)
                                or ("DisableAction" in m.behavior_flags)
                                or (float(m.properties.get("AllDamageTypeTakenRatio", 0.0)) > 0.0)
                            )
                            and me.can_dispel_modifier(m)
                            and m.halo_parent_uid is None
                        )
                    ]
                if order == "LastAdded":
                    cands.sort(key=lambda m: getattr(m, "_spawn_order", 0), reverse=True)
                else:
                    cands.sort(key=lambda m: getattr(m, "_spawn_order", 0))
                for m in cands[:count]:
                    if break_helper is not None:
                        if m.name == "MCommon_BreakDebuff_Quantum":
                            break_helper.quantum_entanglements.pop(tid, None)
                        elif m.name == "MCommon_BreakDebuff_Wind":
                            break_helper.wind_shears.pop(tid, None)
                    me.destroy_modifier(m)
                if break_helper is not None and not req_flags and "Numbers" not in task:
                    break_helper.quantum_entanglements.pop(tid, None)
                    break_helper.wind_shears.pop(tid, None)
                for m in list(me.get_modifiers(tid)):
                    me._sync_modifier_to_status_mgr(m)
            return

        # 4. 战斗结算：治疗 / 伤害 / 自扣血 / 战技点 / 拉推条 / 插队 / 召唤
        if t == "RPG.GameCore.SetHP":
            from ..effects import sync_hp_shared_subtargets

            targets = self._resolve_targets(task.get("TargetType"), ctx)
            if "ModifyRatio" in task:
                ratio = self._eval_num(task.get("ModifyRatio"), ctx, -1.0)
                if ratio >= 0.0:
                    for tid in targets:
                        ent = sim.get_entity(tid)
                        if ent is not None and (
                            getattr(ent, "current_hp", 0.0) > 0.0
                            or getattr(ent, "_vm_limbo_pending", False)
                            or getattr(ent, "_in_deathrattle_limbo", False)
                        ):
                            old_hp = float(ent.current_hp)
                            max_hp = sim.port.max_hp(tid) or getattr(ent, "max_hp", 0.0)
                            ent.current_hp = max(0.0, min(float(max_hp), float(max_hp) * float(ratio)))
                            delta = float(ent.current_hp) - old_hp
                            if abs(delta) > 1e-6:
                                sync_hp_shared_subtargets(sim, ent)
                                me.dispatch_event("OnHPChange", owner_id=tid, param_entity_id=ctx.caster_id, change_value=delta)
                                me.dispatch_event("OnListenHPChange", param_entity_id=tid, change_value=delta)
                return
            val = self._eval_num(task.get("ModifyValue") or task.get("Value"), ctx, -1.0)
            if val >= 0.0:
                for tid in targets:
                    ent = sim.get_entity(tid)
                    if ent is not None and getattr(ent, "current_hp", 0.0) > 0.0:
                        old_hp = float(ent.current_hp)
                        max_hp = sim.port.max_hp(tid) or getattr(ent, "max_hp", val)
                        ent.current_hp = max(0.0, min(float(max_hp), float(val)))
                        delta = float(ent.current_hp) - old_hp
                        if abs(delta) > 1e-6:
                            sync_hp_shared_subtargets(sim, ent)
                            me.dispatch_event("OnHPChange", owner_id=tid, param_entity_id=ctx.caster_id, change_value=delta)
                            me.dispatch_event("OnListenHPChange", param_entity_id=tid, change_value=delta)
            return

        if t == "RPG.GameCore.HealHP":
            self._execute_heal(task, ctx)
            return

        if t == "RPG.GameCore.ModifyHealData":
            if ctx.heal_data is not None:
                for k in ("HealRatioAdded", "HealPercentage", "ModifyValue"):
                    if k in task:
                        ctx.heal_data[k] = ctx.heal_data.get(k, 0.0) + self._eval_num(task[k], ctx, 0.0)
                if "Healer_HealRatio" in task:
                    ctx.heal_data["HealRatioAdded"] = ctx.heal_data.get("HealRatioAdded", 0.0) + self._eval_num(
                        task["Healer_HealRatio"], ctx, 0.0
                    )
            return

        if t == "RPG.GameCore.DamageByAttackProperty":
            self._execute_damage(task, ctx)
            return

        if t == "RPG.GameCore.ModifyDamageData":
            if ctx.damage_data is not None:
                for k, v in task.items():
                    if k in ("$type", "TargetType"):
                        continue
                    if isinstance(v, (dict, int, float)):
                        if k == "AttackData_ConstFinalDamage":
                            ctx.damage_data[k] = self._eval_num(v, ctx, 0.0)
                        else:
                            ctx.damage_data[k] = ctx.damage_data.get(k, 0.0) + self._eval_num(v, ctx, 0.0)
            return

        if t in ("RPG.GameCore.LoseHPByRatio", "RPG.GameCore.LoseHP"):
            self._execute_lose_hp(task, ctx)
            return

        if t == "RPG.GameCore.ModifySPNew":
            self._execute_modify_sp_new(task, ctx)
            return

        if t == "RPG.GameCore.ModifyTeamBoostPoint":
            mfunc = str(task.get("ModifyFunction", "Add"))
            mval = int(round(self._eval_num(task.get("ModifyValue"), ctx, 0.0)))
            delta = mval if mfunc == "Add" else (-mval if mfunc in ("Sub", "Minus") else 0)
            if delta != 0:
                sim.port.change_sp(ctx.caster_id, delta, reason=ctx.ability_name or "VM_Skill")
                me.dispatch_event("OnSPChange", owner_id=ctx.caster_id, change_value=float(delta))
            return

        if t == "RPG.GameCore.ModifyActionDelay":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            cur_turn = getattr(sim, "_current_turn_entity", None)
            if task.get("AddNormalizedValue") is not None:
                val = self._eval_num(task.get("AddNormalizedValue"), ctx, 0.0)
                for tid in targets:
                    if val <= -1.0 + 1e-6 and not getattr(sim, "_in_retarget_ready_batch", False):
                        if cur_turn is not None and cur_turn.name == tid:
                            setattr(cur_turn, "_vm_immediate_jump", True)
                        sim.port.set_distance(tid, 0.0)
                    elif val < 0:
                        sim.port.advance(ctx.caster_id, tid, abs(val))
                    elif val > 0:
                        sim.port.delay(ctx.caster_id, tid, val)
            elif task.get("AddValue") is not None:
                raw_val = self._eval_num(task.get("AddValue"), ctx, 0.0)
                for tid in targets:
                    ent = sim.get_entity(tid)
                    if ent is None:
                        continue
                    spd = float(getattr(ent, "speed", 0.0) or 0.0)
                    if spd <= 0.0:
                        continue
                    new_dist = float(getattr(ent, "distance_remaining", 0.0)) + raw_val * 10.0 * spd
                    if new_dist <= 1e-6:
                        if (
                            not getattr(sim, "_in_retarget_ready_batch", False)
                            and cur_turn is not None
                            and cur_turn.name == tid
                        ):
                            setattr(cur_turn, "_vm_immediate_jump", True)
                        sim.port.set_distance(tid, 0.0)
                    else:
                        sim.port.set_distance(tid, new_dist)
            else:
                val = self._eval_num(task.get("DelayValue") or task.get("Value"), ctx, 0.0)
                for tid in targets:
                    if val <= -1.0 + 1e-6 and not getattr(sim, "_in_retarget_ready_batch", False):
                        if cur_turn is not None and cur_turn.name == tid:
                            setattr(cur_turn, "_vm_immediate_jump", True)
                        sim.port.set_distance(tid, 0.0)
                    elif val < 0:
                        sim.port.advance(ctx.caster_id, tid, abs(val))
                    elif val > 0:
                        sim.port.delay(ctx.caster_id, tid, val)
            return

        if t == "RPG.GameCore.ResetActionDelay":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            for tid in targets:
                sim.port.set_distance(tid, 10000.0)
            return

        if t == "RPG.GameCore.SetActionDelay":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            has_norm = task.get("NormalizedValue") is not None
            val_spec = task.get("NormalizedValue")
            if val_spec is None:
                val_spec = task.get("DelayValue") if "DelayValue" in task else task.get("Value")
            val = self._eval_num(val_spec, ctx, 1.0)
            cur_turn = getattr(sim, "_current_turn_entity", None)
            for tid in targets:
                if val <= 1e-6:
                    if cur_turn is not None and cur_turn.name == tid:
                        setattr(cur_turn, "_vm_immediate_jump", True)
                    ent = sim.get_entity(tid)
                    rq = getattr(sim, "_ready_queue", None)
                    if ent is not None and isinstance(rq, list):
                        ent.distance_remaining = 0.0
                        if tid not in rq and (ent.current_hp > 0 or getattr(ent, "is_infinite_hp", False)):
                            nat = getattr(sim, "_natural_due_names", None)
                            if isinstance(nat, set):
                                nat.discard(tid)
                            batch_ids = getattr(ctx, "_set_delay_zero_batch", None)
                            if batch_ids is None:
                                batch_ids = []
                                setattr(ctx, "_set_delay_zero_batch", batch_ids)
                            batch_ids.append(tid)
                            batch_set = set(batch_ids)
                            rest = [name for name in rq if name not in batch_set]
                            batch_in_rq = [name for name in rq if name in batch_set] + [tid]
                            batch_in_rq.sort(
                                key=lambda name: (
                                    -float(getattr(sim.get_entity(name), "speed", 0.0) or 0.0),
                                    int(getattr(sim.get_entity(name), "_spawn_seq", 0) or 0),
                                )
                            )
                            rq[:] = batch_in_rq + rest
                    else:
                        sim.port.set_distance(tid, 0.0)
                else:
                    if has_norm:
                        sim.port.set_distance(tid, max(0.0, val * 10000.0))
                    else:
                        ent = sim.get_entity(tid)
                        spd = float(getattr(ent, "speed", 0.0) or 0.0) if ent is not None else 0.0
                        dist = val * 10.0 * spd if spd > 0.0 else val * 10000.0
                        sim.port.set_distance(tid, max(0.0, dist))
            return

        if t in ("RPG.GameCore.TurnInsertAbility", "RPG.GameCore.TurnInsertAbilityCondition", "RPG.GameCore.TurnInsertAction"):
            self._execute_turn_insert(task, ctx)
            return

        if t == "RPG.GameCore.CreateServant":
            self._execute_create_servant(task, ctx)
            return

        if t == "RPG.GameCore.CreateBattleEvent":
            self._execute_create_battle_event(task, ctx)
            return

        if t == "JDOLDFECMPL":
            val = self._eval_num(task.get("AJHHCOHFIFA"), ctx, 0.0)
            mode = "set" if str(task.get("FKCKKFALPBK", "")) == "DADCFBHGLOH" else "add"
            rt.modify_elation_points(val, mode=mode)
            return

        if t == "RPG.GameCore.SetTargetUniqueName":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            un_obj = task.get("UniqueName")
            uname = str(un_obj.get("RawString", "")) if isinstance(un_obj, Mapping) else _str_val(un_obj)
            if uname and targets:
                rt.named_targets[uname] = list(targets)
            return

        if t == "RPG.GameCore.SetEntityActionState":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            active = bool(task.get("ActionState", True))
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                if not active:
                    ent.distance_remaining = 1e12
                elif ent.distance_remaining >= 1e11:
                    ent.distance_remaining = 10000.0
            return

        if t in (
            "RPG.GameCore.RemoveEntityFromTeamFormation",
            "RPG.GameCore.AddEntityToTeamFormation",
        ):
            tgt_spec = task.get("TargetType") or {
                "Alias": ("ModifierOwnerEntity" if ctx.modifier_owner_id else "Caster")
            }
            targets = self._resolve_targets(tgt_spec, ctx)
            unselectable = t == "RPG.GameCore.RemoveEntityFromTeamFormation"
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None:
                    ent.is_unselectable = unselectable
            return

        if t == "RPG.GameCore.ForceKill":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            mute_death = bool(task.get("MuteAllTriggerDeath", False))
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                if getattr(ent, "is_enemy", False):
                    rt.record_entity_team(ent)
                    # 已进入亡语悬停且仍保有 Deathrattle 动作（如已被去除 Initiate 但仍有 Power 遗赠）的敌方，等待其亡语队列完成后再清场
                    if (
                        getattr(ent, "_in_deathrattle_limbo", False)
                        and int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) > 0
                        and me.has_behavior_flag(tid, "Deathrattle")
                    ):
                        setattr(ent, "_die_immediately_after_deathrattle", True)
                        continue
                if getattr(ent, "is_memosprite", False):
                    me.dispatch_event("OnDeathrattle", owner_id=tid, param_entity_id=tid)
                    master_id = getattr(ent, "master_name", None)
                    me.dispatch_event(
                        "OnTriggerDeathrattle",
                        owner_id=master_id,
                        param_entity_id=tid,
                    )
                prev_hp = float(getattr(ent, "current_hp", 0.0))
                was_limbo = bool(getattr(ent, "_in_deathrattle_limbo", False))
                was_deferred_die = bool(getattr(ent, "_deferred_listen_die", False))
                if was_limbo:
                    setattr(ent, "_in_deathrattle_limbo", False)
                if was_deferred_die:
                    setattr(ent, "_deferred_listen_die", False)
                setattr(ent, "_die_immediately_after_deathrattle", False)
                setattr(ent, "_pending_deathrattle_actions", 0)
                ent.current_hp = 0.0
                if not getattr(ent, "is_enemy", False) and prev_hp > 0.0:
                    sim.event_bus.publish(
                        HPLostEvent(
                            av=round(float(sim.current_av), 2),
                            cycle=int(sim.current_cycle),
                            entity_name=tid,
                            amount=prev_hp,
                            hp_left=0.0,
                            cause="ForceKill",
                        )
                    )
                me.destroy_all_for_entity(tid)
                if getattr(ent, "is_enemy", False):
                    eff_attacker = ctx.caster_id or ""
                    c_ent = sim.get_entity(eff_attacker) if eff_attacker and eff_attacker != "__LEVEL__" else None
                    if eff_attacker in ("", "__LEVEL__") or (c_ent is not None and getattr(c_ent, "monster_id", 0) == 8003060):
                        eff_attacker = getattr(rt, "_last_enemy_killer_id", "") or getattr(rt, "_current_attacker_id", "") or eff_attacker
                    director = getattr(sim, "_stage_director", None)
                    runner = getattr(director, "runner", None) if director is not None else None
                    is_inf_stage = bool(
                        runner is not None
                        and getattr(getattr(runner.built_stage, "source_spec", None), "stage_infinite_group_id", None) is not None
                    )
                    if runner is not None and not is_inf_stage:
                        runner.state.enemies[:] = [m for m in runner.state.enemies if m.entity.name != tid]
                    sim.entities[:] = [e for e in sim.entities if e.name != tid]
                    pending_dead = getattr(rt, "_pending_dead_enemies", None)
                    if pending_dead and tid in pending_dead:
                        pending_dead[:] = [x for x in pending_dead if x != tid]
                    if prev_hp > 0.0:
                        from simulator.events import EnemyDefeatedEvent
                        sim.event_bus.publish(
                            EnemyDefeatedEvent(
                                av=float(sim.current_av),
                                cycle=int(sim.current_cycle),
                                attacker_name=eff_attacker,
                                target_name=tid,
                            )
                        )
                    elif not mute_death and (was_deferred_die or was_limbo):
                        if (
                            getattr(rt, "_attack_scope_depth", 0) > 0
                            and not getattr(rt, "_in_after_attack", False)
                            and not getattr(rt, "_flushing_listen_die", False)
                        ):
                            q = getattr(rt, "_pending_listen_die", None)
                            if q is None:
                                q = []
                                rt._pending_listen_die = q
                            if tid not in q:
                                q.append(tid)
                        else:
                            me.dispatch_event("OnListenCharacterDie", param_entity_id=tid)
                elif not mute_death and (prev_hp > 0.0 or getattr(ent, "is_memosprite", False)):
                    me.dispatch_event("OnListenCharacterDie", param_entity_id=tid)
                if getattr(ent, "is_memosprite", False) or getattr(ent, "is_countdown", False):
                    sim.port.despawn_spirit(tid, reason="ForceKill")
                be_list = rt.named_targets.get("BattleEventEntityList")
                if be_list and tid in be_list:
                    rt.named_targets["BattleEventEntityList"] = [x for x in be_list if x != tid]
            return

        if t == "RPG.GameCore.DamagePerformFinish":
            rt.flush_pending_after_attack()
            return

        if t == "RPG.GameCore.ModifyCurrentSkillDelayCost":
            val = self._eval_num(task.get("NormalizedValue") or task.get("Value"), ctx, 0.0)
            mfunc = str(task.get("ModifyFunction", "Add") or "Add")
            cur_turn = getattr(sim, "_current_turn_entity", None)
            if cur_turn is not None:
                cur_d = getattr(sim, "_pending_turn_reset_distance", None)
                base_d = 10000.0 if cur_d is None else float(cur_d)
                if mfunc == "Set":
                    new_d = max(0.0, val * 10000.0)
                elif mfunc == "Mul":
                    new_d = max(0.0, base_d * val)
                else:
                    new_d = max(0.0, base_d + val * 10000.0)
                sim._pending_turn_reset_distance = new_d
                if new_d <= 0.0:
                    setattr(cur_turn, "_vm_immediate_jump", True)
            return

        if t == "RPG.GameCore.SummonMonster":
            if getattr(rt, "_skip_vm_summon_monster", False):
                return
            director = getattr(sim, "_stage_director", None)
            if director is not None and hasattr(director, "flush_ally_talent_heals"):
                director.flush_ally_talent_heals()
            data_list = task.get("SummonMonsterDataList") or []
            if data_list and isinstance(data_list[0], Mapping) and data_list[0].get("LocationType") == "FormationRecord":
                runner = getattr(director, "runner", None) if director is not None else None
                if runner is not None and hasattr(runner, "refill_next_infinite_monster"):
                    slot_spec = data_list[0].get("MonsterSlot")
                    slot_val = int(round(self._eval_num(slot_spec, ctx, -1.0))) if slot_spec is not None else -1
                    dr_spec = task.get("DelayRatio")
                    dr_val = self._eval_num(dr_spec, ctx, 0.3) if dr_spec is not None else None
                    ent = runner.refill_next_infinite_monster(
                        formation_slot=(slot_val if slot_val >= 0 else None),
                        delay_ratio=dr_val,
                    )
                    if ent is not None:
                        rt.named_targets["LastSummonMonsters"] = [ent.name]
                        if director is not None:
                            director.sync_spawned_entities()
                return
            if director is not None and hasattr(director, "summon_enemy"):
                spawned = director.summon_enemy(
                    ctx.caster_id,
                    task,
                    dynamic_resolver=lambda h: self.rt.resolve_hash(
                        ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx
                    ),
                )
                rt.named_targets["LastSummonMonsters"] = [e.name for e in (spawned or ()) if e is not None]
            return

        if t == "RPG.GameCore.SetMonsterPhase":
            director = getattr(sim, "_stage_director", None)
            if director is not None and hasattr(director, "trigger_monster_phase_transition"):
                mode = str(task.get("SetMode") or task.get("Mode") or "Set")
                val_spec = task.get("PhaseValue") if "PhaseValue" in task else task.get("Value")
                val = (
                    int(round(self._eval_num(val_spec, ctx, 1.0)))
                    if val_spec is not None
                    else (1 if mode == "Set" else None)
                )
                targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.caster_id]
                for tid in targets:
                    director.trigger_monster_phase_transition(tid, mode=mode, value=val)
            return

        if t in (
            "RPG.GameCore.LockHP",
            "RPG.GameCore.ResetStance",
            "RPG.GameCore.ExitBreakState",
        ):
            if t == "RPG.GameCore.LockHP" and ctx.modifier_instance is not None:
                setattr(ctx.modifier_instance, "_applied_lock_hp", True)
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None and hasattr(runner, "execute_stage_task"):
                targets = (
                    self._resolve_targets(task.get("TargetType"), ctx)
                    if task.get("TargetType") is not None
                    else [ctx.modifier_owner_id or ctx.caster_id]
                )
                for tid in targets or [ctx.modifier_owner_id or ctx.caster_id]:
                    tgt_eb = sim.get_entity(tid)
                    was_broken_eb = bool(tgt_eb is not None and getattr(tgt_eb, "is_broken", False))
                    runner.execute_stage_task(
                        task,
                        caster_name=tid,
                        dynamic_resolver=lambda h: self.rt.resolve_hash(
                            ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx
                        ),
                    )
                    if (
                        t in ("RPG.GameCore.ExitBreakState", "RPG.GameCore.ResetStance")
                        and was_broken_eb
                        and tgt_eb is not None
                        and not getattr(tgt_eb, "is_broken", False)
                    ):
                        me.dispatch_event("OnEndBreak", owner_id=tid, param_entity_id=tid)
                        me.dispatch_event("OnListenEndBreak", param_entity_id=tid)
            return

        if t == "RPG.GameCore.StackWeakness":
            from .stage_factory import normalize_element

            targets = (
                self._resolve_targets(task.get("TargetType"), ctx)
                if task.get("TargetType") is not None
                else [ctx.modifier_owner_id or ctx.caster_id]
            )
            targets = targets or [ctx.modifier_owner_id or ctx.caster_id]
            raw_op = task.get("OPType")
            op_type = "Override" if not raw_op else str(raw_op)
            raw_list = task.get("WeakList") or ()
            norm_list = tuple(normalize_element(w) for w in raw_list if w)
            if ctx.modifier_instance is not None:
                for tid in targets:
                    ctx.modifier_instance.stacked_weaknesses.setdefault(tid, []).append((op_type, norm_list))
                    me.recompute_entity_weaknesses(tid)
            else:
                director = getattr(sim, "_stage_director", None)
                runner = getattr(director, "runner", None) if director is not None else None
                if runner is not None:
                    for tid in targets:
                        if tid in getattr(runner, "_enemy_by_name", ()):
                            runner.execute_stack_weakness(tid, raw_list, op_type=op_type)
            return

        if t == "RPG.GameCore.ClearWeakness":
            from .stage_factory import normalize_element

            targets = (
                self._resolve_targets(task.get("TargetType"), ctx)
                if task.get("TargetType") is not None
                else [ctx.modifier_owner_id or ctx.caster_id]
            )
            targets = targets or [ctx.modifier_owner_id or ctx.caster_id]
            raw_op = str(task.get("OPType") or "")
            clear_op = (
                "ClearProtected"
                if raw_op == "Protected"
                else ("ClearAttach" if raw_op == "Attach" else ("ClearSecret" if raw_op == "Secret" else "Clear"))
            )
            if clear_op == "ClearSecret":
                return
            norm_list = tuple(normalize_element(w) for w in (task.get("WeakList") or ()) if w)
            if ctx.modifier_instance is not None:
                for tid in targets:
                    ctx.modifier_instance.stacked_weaknesses.setdefault(tid, []).append((clear_op, norm_list))
                    me.recompute_entity_weaknesses(tid)
            else:
                for tid in targets:
                    ent = sim.get_entity(tid)
                    if ent is None:
                        continue
                    if clear_op == "ClearProtected":
                        ent.toughness_locked = False
                    else:
                        ent.weaknesses[:] = [w for w in getattr(ent, "weaknesses", []) if w not in norm_list]
            return

        if t == "RPG.GameCore.StackWeakResistance":
            from .stage_factory import normalize_element

            targets = (
                self._resolve_targets(task.get("TargetType"), ctx)
                if task.get("TargetType") is not None
                else [ctx.modifier_owner_id or ctx.caster_id]
            )
            targets = targets or [ctx.modifier_owner_id or ctx.caster_id]
            stype = str(task.get("StackType") or "Delta")
            entries = []
            for item in task.get("StackResistanceList") or ():
                if not isinstance(item, Mapping):
                    continue
                elem = normalize_element(str(item.get("DamageType") or ""))
                val = self._eval_num(item.get("Value"), ctx, 0.0)
                if elem:
                    entries.append((stype, elem, val))
            if not entries:
                return
            if ctx.modifier_instance is not None:
                for tid in targets:
                    ctx.modifier_instance.weak_resistance_deltas.setdefault(tid, []).extend(entries)
                    me.recompute_entity_damage_res(tid)
            else:
                for tid in targets:
                    ent = sim.get_entity(tid)
                    if ent is None:
                        continue
                    res = dict(getattr(ent, "damage_res", {}) or {})
                    for st, elem, val in entries:
                        res[elem] = float(res.get(elem, 0.0)) + val if st == "Delta" else float(val)
                    ent.damage_res = res
            return

        if t == "RPG.GameCore.TriggerStanceCountDown":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            director = getattr(sim, "_stage_director", None)
            port = getattr(director, "port", None) if director is not None else None
            for tid in targets:
                if port is not None and hasattr(port, "break_entity_toughness_and_deduct_hp"):
                    port.break_entity_toughness_and_deduct_hp(tid, hp_deduct=0.0, break_delay=2500.0)
            return

        if t == "OOCOGGMJLBN":
            val = max(0.0, self._eval_num(task.get("MCNPMDPMCKM"), ctx, 0.0))
            mod = ctx.modifier_instance
            if mod is not None and val > 0.0:
                setattr(mod, "single_block_max", val)
                setattr(mod, "single_block_cur", val)
                mod.dynamic_values[2124040366] = val
                mod.dynamic_values[-276442507] = val
                owner_ent = sim.get_entity(mod.owner_id)
                if owner_ent is not None:
                    owner_ent.barrier_guarded = True
                    owner_ent.toughness_locked = True
                    director = getattr(sim, "_stage_director", None)
                    runner = getattr(director, "runner", None) if director is not None else None
                    if runner is not None:
                        try:
                            if runner.get_enemy_state(mod.owner_id).phase >= 2:
                                saved_tdr = getattr(owner_ent, "_phase_saved_toughness_dmg_reduction", getattr(owner_ent, "toughness_dmg_reduction", 0.10))
                                setattr(mod, "_saved_toughness_dmg_reduction", saved_tdr)
                                owner_ent.toughness_dmg_reduction = 0.0
                        except KeyError:
                            pass
            return

        if t == "RPG.GameCore.SetControlSkillMapping":
            sk_key = str(task.get("SkillTriggerKey") or "")
            ctrl_type = str(task.get("ControlSkillType") or "ControlSkill01")
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            for tid in targets:
                if tid:
                    if sk_key:
                        self.rt.control_skill_mapping[(tid, ctrl_type)] = sk_key
                    else:
                        self.rt.control_skill_mapping.pop((tid, ctrl_type), None)
            return

        if t == "RPG.GameCore.SetDynamicEntityParam":
            key = _str_val(task.get("DynamicKey"))
            owners = self._resolve_targets(task.get("ReadTargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            param_spec = task.get("ParamTargetType")
            alias = param_spec.get("Alias") if isinstance(param_spec, Mapping) else None
            if alias == "None" or param_spec is None:
                vals: List[str] = []
            else:
                vals = self._resolve_targets(param_spec, ctx)
            for oid in owners:
                if oid and key:
                    if vals:
                        self.rt.dynamic_entity_params[(oid, key)] = list(vals)
                    else:
                        self.rt.dynamic_entity_params.pop((oid, key), None)
            return

        if t == "RPG.GameCore.AddStageAbilityByName":
            ab_name = _str_val(task.get("StageAbilityName"))
            if ab_name:
                owner = "__LEVEL__"
                can_replace = bool(task.get("CanReplace", True))
                eq_key = (owner, ab_name)
                if can_replace or eq_key not in rt.equip_dynamics:
                    dyn_map: Dict[int, float] = {}
                    for dk, dv in (task.get("DynamicValues") or {}).items():
                        val = self._eval_num(dv, ctx, 0.0)
                        kh = dotnet_hash(str(dk))
                        dyn_map[kh] = val
                        rt.set_dynamic_value(owner, kh, val, ability_name=ab_name)
                    rt.equip_dynamics[eq_key] = dyn_map
                ab = rt.loader.get_ability(ab_name)
                if ab is not None and ab.get("OnAdd"):
                    add_key = (owner, ab_name)
                    if can_replace or add_key not in rt._added_abilities:
                        rt._added_abilities.add(add_key)
                        add_ctx = ExecutionContext(
                            runtime=rt,
                            caster_id=owner,
                            ability_name=ab_name,
                            ability_target_ids=(owner,),
                        )
                        self.execute_tasks(ab["OnAdd"], add_ctx)
            return

        if t == "RPG.GameCore.DamageStance":
            tgt_spec = task.get("DefenderTargetType") or task.get("TargetType")
            targets = self._resolve_targets(tgt_spec, ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            atk_targets = (
                self._resolve_targets(task.get("AttackerTargetType"), ctx)
                if task.get("AttackerTargetType") is not None
                else []
            )
            atk_id = atk_targets[0] if atk_targets else ctx.caster_id
            atk_ent = sim.get_entity(atk_id) if atk_id else None
            force_stance = bool(task.get("ForceStanceDamage", False) or task.get("IgnoreMuteBreak", False))
            sdt = task.get("StanceDamageType")
            explicit_elem = (
                str(sdt.get("DamageType"))
                if isinstance(sdt, Mapping) and sdt.get("DamageType")
                else (str(sdt) if sdt else "")
            )
            break_table = getattr(rt.loader, "_break_base_by_level", None)
            if break_table is None:
                break_table = {}
                try:
                    for row in rt.loader._read_excel("AvatarBreakDamage.json"):
                        lv = int(row.get("Level", 0) or 0)
                        bv = row.get("BreakBaseDamage", {})
                        if lv > 0:
                            break_table[lv] = float(
                                bv.get("Value", 0.0) if isinstance(bv, Mapping) else (bv or 0.0)
                            )
                except Exception:
                    break_table = {}
                setattr(rt.loader, "_break_base_by_level", break_table)

            def _calc_stance_break_dmg(ent_obj: Any, eid: str, st_el: str) -> float:
                atk_lvl = int(getattr(atk_ent, "level", None) or getattr(ent_obj, "level", 95) or 95)
                tgt_lvl = int(getattr(ent_obj, "level", 95) or 95)
                base_break = float(break_table.get(atk_lvl, 7494.3716 if atk_lvl >= 95 else 3767.5535))
                elem_mult = (
                    2.0
                    if st_el in ("Physical", "Fire")
                    else (1.5 if st_el == "Wind" else (0.5 if st_el in ("Quantum", "Imaginary") else 1.0))
                )
                tough_mult = 0.5 + (float(getattr(ent_obj, "max_toughness", 0.0)) / 120.0)
                sm = getattr(sim, "status_mgr", None)
                be = float(getattr(atk_ent, "base_break_effect", 0.0) or 0.0) if atk_ent is not None else 0.0
                if sm is not None and atk_id:
                    be = sm.calculate_stat(atk_id, be, StatType.BREAK_EFFECT)
                def_shred = sm.calculate_stat(eid, 0.0, StatType.DEF_SHRED) if sm else 0.0
                def_ignore = (
                    sm.calculate_stat(atk_id, 0.0, StatType.DEF_SHRED)
                    if (sm is not None and atk_id and atk_id != eid)
                    else 0.0
                )
                def_mult = (atk_lvl + 20.0) / (
                    (tgt_lvl + 20.0) * max(0.0, 1.0 - def_shred - def_ignore) + (atk_lvl + 20.0)
                )
                base_res = float((getattr(ent_obj, "damage_res", {}) or {}).get(st_el, 0.0))
                tgt_res_mod = 0.0
                red_mult = 1.0 - max(0.0, min(1.0, float(getattr(ent_obj, "damage_reduction", 0.0))))
                for m_def in me.get_modifiers(eid):
                    m_red = float(m_def.properties.get("AllDamageReduce", 0.0))
                    if m_red > 0.0:
                        red_mult *= max(0.0, 1.0 - m_red)
                    tgt_res_mod += float(m_def.properties.get("AllDamageTypeResistance", 0.0))
                res_mult = max(0.0, 1.0 - (base_res + tgt_res_mod))
                vuln = sm.calculate_stat(eid, 0.0, StatType.VULNERABILITY) if sm else 0.0
                vuln_mult = 1.0 + vuln
                tough_red = max(0.0, 1.0 - float(getattr(ent_obj, "toughness_dmg_reduction", 0.10)))
                return (
                    base_break
                    * elem_mult
                    * tough_mult
                    * (1.0 + be)
                    * def_mult
                    * res_mult
                    * vuln_mult
                    * tough_red
                    * red_mult
                )

            sval = self._eval_num(task.get("StanceValue"), ctx, 0.0)
            if sval > 0.0:
                for tid in targets:
                    ent = sim.get_entity(tid)
                    rem_s = float(sval)
                    while (
                        rem_s > 0.0
                        and ent is not None
                        and getattr(ent, "current_toughness", 0.0) > 0.0
                        and not getattr(ent, "is_broken", False)
                        and (force_stance or not getattr(ent, "toughness_locked", False))
                    ):
                        cur_t = float(ent.current_toughness)
                        if rem_s < cur_t:
                            ent.current_toughness = cur_t - rem_s
                            rem_s = 0.0
                            break
                        rem_s -= cur_t
                        ent.current_toughness = 0.0
                        st_elem = explicit_elem or str(getattr(ent, "stance_type", None) or "Imaginary")
                        cur_sc = int(getattr(ent, "current_stance_count", 1) or 1)
                        if cur_sc > 1:
                            ent.current_stance_count = cur_sc - 1
                            if task.get("TriggerCountDown", False):
                                cd_dmg = _calc_stance_break_dmg(ent, tid, st_elem)
                                kit = getattr(ent, "kit", None)
                                actual_loss = (
                                    kit.intercept_incoming_damage(tid, cd_dmg)
                                    if kit is not None and hasattr(kit, "intercept_incoming_damage")
                                    else cd_dmg
                                )
                                ent.current_hp = max(0.0, float(ent.current_hp) - actual_loss)
                            ent.current_toughness = float(ent.max_toughness)
                        else:
                            brk_dmg = _calc_stance_break_dmg(ent, tid, st_elem)
                            ent.current_stance_count = 0
                            ent.is_broken = True
                            from ..effects import sync_hp_shared_subtargets

                            shared_map = getattr(rt, "hp_shared_groups", None)
                            main_id = shared_map.get(tid) if shared_map else None
                            main_ent = sim.get_entity(main_id) if main_id else None
                            if main_ent is not None and main_ent is not ent and float(getattr(main_ent, "current_hp", 0.0)) > 0.0:
                                m_kit = getattr(main_ent, "kit", None)
                                actual_loss = (
                                    m_kit.intercept_incoming_damage(main_id, brk_dmg)
                                    if m_kit is not None and hasattr(m_kit, "intercept_incoming_damage")
                                    else brk_dmg
                                )
                                main_ent.current_hp = max(0.0, float(main_ent.current_hp) - actual_loss)
                                sync_hp_shared_subtargets(sim, main_ent)
                            else:
                                kit = getattr(ent, "kit", None)
                                actual_loss = (
                                    kit.intercept_incoming_damage(tid, brk_dmg)
                                    if kit is not None and hasattr(kit, "intercept_incoming_damage")
                                    else brk_dmg
                                )
                                ent.current_hp = max(0.0, float(ent.current_hp) - actual_loss)
                                sync_hp_shared_subtargets(sim, ent)
                            ent.delay_action(0.25)
                            sm_be = getattr(sim, "status_mgr", None)
                            atk_be = float(getattr(atk_ent, "base_break_effect", 0.0) or 0.0) if atk_ent is not None else 0.0
                            if sm_be is not None and atk_id:
                                atk_be = sm_be.calculate_stat(atk_id, atk_be, StatType.BREAK_EFFECT)
                            entangle_applied = True
                            if st_elem == "Quantum":
                                ctrl_immune = False
                                if me.has_behavior_flag(tid, "Endurance") or me.has_behavior_flag(tid, "EnduranceLogicOnly"):
                                    ctrl_immune = True
                                if not ctrl_immune:
                                    debuff_res = getattr(ent, "debuff_resist", None)
                                    if isinstance(debuff_res, dict) and float(debuff_res.get("STAT_CTRL", 0.0)) >= 1.0 - 1e-6:
                                        ctrl_immune = True
                                if ctrl_immune:
                                    entangle_applied = False
                                else:
                                    debuff_prov = getattr(sim, "debuff_hit_provider", None)
                                    if callable(debuff_prov):
                                        entangle_applied = bool(
                                            debuff_prov(
                                                atk_ent,
                                                ent,
                                                "Quantum_Entanglement",
                                                round(float(getattr(sim, "current_av", 0.0)), 2),
                                            )
                                        )
                                if entangle_applied:
                                    ent.delay_action(0.20 * (1.0 + atk_be))
                            bus = getattr(sim, "event_bus", None)
                            if bus is not None:
                                bus.publish(
                                    WeaknessBreakEvent(
                                        av=round(float(getattr(sim, "current_av", 0.0)), 2),
                                        cycle=int(getattr(sim, "current_cycle", 0)),
                                        breaker_name=atk_id,
                                        target_name=tid,
                                        element=st_elem,
                                        break_damage=brk_dmg,
                                        action_delay_pct=0.25,
                                        entangle_applied=entangle_applied,
                                    )
                                )
                            else:
                                me.dispatch_event("OnBeingBreak", owner_id=tid, param_entity_id=atk_id)
                                me.dispatch_event("OnListenBreak", param_entity_id=tid)
                            break
            return

        if t == "RPG.GameCore.DestroyBattleCharacter":
            uniq = str(task.get("CharacterUniqueName") or "")
            if uniq:
                targets = list(rt.named_targets.get(uniq, ()))
                if not targets and sim.get_entity(uniq) is not None:
                    targets = [uniq]
            elif "TargetType" in task:
                targets = self._resolve_targets(task.get("TargetType"), ctx)
            else:
                targets = []
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None:
                    ent.current_hp = 0.0
                    me.destroy_all_for_entity(tid)
                    if hasattr(sim, "remove_entity"):
                        sim.remove_entity(tid)
            return

        if t == "RPG.GameCore.RandomConfig":
            tlist = task.get("TaskList") or []
            odds_list = task.get("OddsList") or []
            if tlist:
                best_idx = 0
                if odds_list:
                    weights = [self._eval_num(o, ctx, 0.0) for o in odds_list[:len(tlist)]]
                    if any(w > 0.0 for w in weights):
                        best_idx = max(range(len(weights)), key=lambda i: weights[i])
                chosen = tlist[best_idx]
                if isinstance(chosen, Mapping):
                    self.execute_task(chosen, ctx)
                elif isinstance(chosen, list):
                    self.execute_tasks(chosen, ctx)
            return

        if t == "RPG.GameCore.LockTargetHP":
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            lock_key = str(task.get("LockKey") or "default")
            thresh = self._eval_num(task.get("Threshold"), ctx, 1.0)
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None:
                    locks = getattr(ent, "_locked_hp_thresholds", None)
                    if locks is None:
                        locks = {}
                        setattr(ent, "_locked_hp_thresholds", locks)
                    locks[lock_key] = max(1.0, float(thresh))
            return

        if t == "RPG.GameCore.UnlockTargetHP":
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            lock_key = str(task.get("LockKey") or "default")
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None:
                    locks = getattr(ent, "_locked_hp_thresholds", None)
                    if isinstance(locks, dict):
                        locks.pop(lock_key, None)
            return

        if t == "FBCGHKLKHJN":
            if str(task.get("MEPFOEEGBEA", "")) == "Disable":
                targets = self._resolve_targets(task.get("HILNFHCPEAD"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
                for tid in targets:
                    ent = sim.get_entity(tid)
                    if ent is not None:
                        locks = getattr(ent, "_locked_hp_thresholds", None)
                        if isinstance(locks, dict):
                            locks.clear()
            return

        if t == "IJJGPIPMNAE":
            # 官方贪饕参数读取: 优先从 StageMonsterInvasionParam[InvasionID].ParamList[idx] 读取，回退至 MazeBuff ParamList
            key_str = str(task.get("FHLJGDGMMHK") or "")
            idx = int(round(self._eval_num(task.get("DKJFDABPLCO"), ctx, 0.0)))
            val = 0.0
            inv_params = None
            director = getattr(sim, "_stage_director", None)
            if director is not None:
                inv_info = getattr(director, "_stage_invasion_info", None)
                if isinstance(inv_info, Mapping):
                    inv_params = inv_info.get("monster_params")
            if inv_params and 0 <= idx < len(inv_params):
                val = float(inv_params[idx])
            else:
                maze_hashes = (462955996, 59671469, 1625755410, 866240523, -1862642832)
                if 0 <= idx < len(maze_hashes) and ctx.modifier_instance is not None:
                    val = float(ctx.modifier_instance.dynamic_values.get(maze_hashes[idx], 0.0))
            if key_str:
                h_key = dotnet_hash(key_str)
                if ctx.modifier_instance is not None:
                    ctx.modifier_instance.dynamic_values[h_key] = val
                targets = self._resolve_targets(task.get("OLPAJJAEEHH"), ctx)
                for tid in targets:
                    rt.set_dynamic_value(tid, h_key, val)
            return

        if t == "RPG.GameCore.ReinitProperty":
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            prop = str(task.get("Property") or "")
            val = self._eval_num(task.get("InitValue"), ctx, 0.0)
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None and prop == "BaseHP" and val > 0.0:
                    ent.base_max_hp = val
                    ent.max_hp = val
                    if ent.current_hp > ent.max_hp:
                        ent.current_hp = ent.max_hp
            return

        if t == "RPG.GameCore.AttachAvatarChange":
            self._execute_attach_avatar_change(task, ctx)
            return

        if t == "RPG.GameCore.DetachAvatarChange":
            self._execute_detach_avatar_change(task, ctx)
            return

        if t == "RPG.GameCore.SetDieImmediately":
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            active_dr = getattr(rt, "_active_deathrattle_entities", ())
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None and getattr(ent, "_in_deathrattle_limbo", False):
                    if tid in active_dr or int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) > 0:
                        setattr(ent, "_die_immediately_after_deathrattle", True)
                    else:
                        setattr(ent, "_die_immediately_after_deathrattle", False)
                        setattr(ent, "_in_deathrattle_limbo", False)
                        ent.current_hp = 0.0
                        me.destroy_all_for_entity(tid)
            return

        if t == "RPG.GameCore.OwnerEntityAddAbility":
            ab_name = _str_val(task.get("AbilityName"))
            if ab_name:
                targets = (
                    self._resolve_targets(task.get("TargetType"), ctx)
                    if "TargetType" in task
                    else [ctx.modifier_owner_id or ctx.caster_id]
                )
                init_dyn: Dict[int, float] = {}
                for dk, dv in (task.get("DynamicValues") or {}).items():
                    init_dyn[dotnet_hash(str(dk))] = self._eval_num(dv, ctx, 0.0)
                rt.loader.ensure_ability_index()
                ab_doc = rt.loader.get_ability(ab_name)
                for tid in targets:
                    for kh, val in init_dyn.items():
                        rt.set_dynamic_value(tid, kh, val, ability_name=ab_name)
                    if ab_doc:
                        sub_ctx = ctx.clone(
                            caster_id=tid,
                            ability_name=ab_name,
                            ability_target_ids=(tid,),
                            modifier_owner_id=tid,
                            local_dynamics=dict(init_dyn),
                        )
                        on_add = ab_doc.get("OnAdd")
                        if on_add:
                            self.execute_tasks(on_add, sub_ctx)
            return

        if t == "RPG.GameCore.SetDynamicValueByMazeBuffConfig":
            qlist = task.get("QueryList") or {}
            if isinstance(qlist, Mapping):
                mb_map = getattr(rt.loader, "_maze_buff_by_id", None)
                if mb_map is None:
                    mb_map = {}
                    try:
                        for row in rt.loader._read_excel("MazeBuff.json"):
                            mid = int(row.get("ID", 0) or 0)
                            if mid and mid not in mb_map:
                                mb_map[mid] = row
                    except Exception:
                        pass
                    rt.loader._maze_buff_by_id = mb_map
                for dk, qspec in qlist.items():
                    if not isinstance(qspec, Mapping):
                        continue
                    mb_id = int(qspec.get("MazeBuffID", 0) or 0)
                    idx = int(qspec.get("Index", 1) or 1)
                    row = mb_map.get(mb_id)
                    val = 0.0
                    if row is not None:
                        plist = row.get("ParamList") or []
                        if 1 <= idx <= len(plist):
                            p = plist[idx - 1]
                            val = float(p.get("Value", 0.0) if isinstance(p, Mapping) else (p or 0.0))
                    kh = dotnet_hash(str(dk))
                    if ctx.modifier_instance is not None:
                        ctx.modifier_instance.dynamic_values[kh] = val
                    self._write_dyn(task, ctx, kh, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByHardLevelProperty":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            prop = str(task.get("Property") or "HPRatio")
            val = 1.0
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                hlc = getattr(getattr(runner.built_stage, "source_spec", None), "hard_level_curve", None)
                if hlc is not None:
                    prop_map = {
                        "HPRatio": "hp_ratio",
                        "AttackRatio": "attack_ratio",
                        "DefenceRatio": "defence_ratio",
                        "SpeedRatio": "speed_ratio",
                        "StanceRatio": "stance_ratio",
                    }
                    attr = prop_map.get(prop)
                    if attr and hasattr(hlc, attr):
                        val = float(getattr(hlc, attr))
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByStatusCount":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            read_targets = self._resolve_targets(task.get("ReadTargetType") or task.get("TargetType"), ctx)
            want_st = str(task.get("StatusType") or "Debuff")
            cnt = 0.0
            if read_targets:
                tid = read_targets[0]
                cnt = float(
                    sum(
                        1
                        for m in me.get_modifiers(tid)
                        if not m._destroyed and me.get_modifier_status_type(m) == want_st
                    )
                )
            self._write_dyn(task, ctx, key_h, cnt)
            return

        if t == "RPG.GameCore.IncludeGlobalTaskListTemplate":
            tpl_name = _str_val(task.get("Name"))
            if tpl_name:
                rt.loader.ensure_ability_index()
                tpl_tasks = rt.loader._global_tpl_by_name.get(tpl_name)
                if isinstance(tpl_tasks, list):
                    self.execute_tasks(tpl_tasks, ctx)
            return

        if t == "RPG.GameCore.InfiniteWaveAddCurWaveMaxCount":
            delta = int(round(self._eval_num(task.get("AddDelta"), ctx, 0.0)))
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                runner.state.infinite_wave_max_count = max(
                    0, runner.state.infinite_wave_max_count + delta
                )
            return

        if t == "RPG.GameCore.RecordEntityFormationIndex":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                for tid in targets:
                    for idx, mrs in enumerate(runner.state.enemies):
                        if mrs.entity.name == tid:
                            if idx not in runner.state.recorded_formation_slots:
                                runner.state.recorded_formation_slots.append(idx)
                            break
            return

        if t == "RPG.GameCore.InfiniteWaveNextMonsterId":
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                wave_bp = runner.built_stage.waves[runner.state.wave_index]
                cur = runner.state.infinite_wave_cursor
                limit = min(len(wave_bp.enemies), runner.state.infinite_wave_max_count)
                next_mid = float(wave_bp.enemies[cur].monster_id) if cur < limit else 0.0
                next_eg = float(wave_bp.enemies[cur].elite_group) if cur < limit else 0.0
                slot = (
                    float(runner.state.recorded_formation_slots.pop())
                    if runner.state.recorded_formation_slots
                    else -1.0
                )
                for key_field, val in (
                    ("MonsterIDKey", next_mid),
                    ("EliteGroupKey", next_eg),
                    ("MonsterSlotKey", slot),
                ):
                    kname = _str_val(task.get(key_field))
                    if kname:
                        kh = dotnet_hash(kname)
                        ctx.local_dynamics[kh] = val
                        rt.set_dynamic_value(ctx.caster_id, kh, val, ability_name=ctx.ability_name)
            return

        if t == "RPG.GameCore.ClearRecordEntityFormation":
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                runner.state.recorded_formation_slots.clear()
            return

        if t == "RPG.GameCore.SetLevelChallengeTurnLimit":
            val = self._eval_num(task.get("LimitCount"), ctx, 0.0)
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                runner.state.challenge_turn_limit = max(0, int(round(val)))
            return

        if t == "RPG.GameCore.LevelChallengeTurnAcc":
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                runner.state.challenge_turns_elapsed += 1
            return

        if t == "RPG.GameCore.InitShield":
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            val = max(0.0, self._eval_num(task.get("ShieldValue"), ctx, 0.0))
            if ctx.modifier_instance is not None:
                ctx.modifier_instance.shield_value = val
                ctx.modifier_instance.shield_max = max(ctx.modifier_instance.shield_max, val)
            for tid in targets:
                if ctx.modifier_instance is not None:
                    me.sync_entity_shield(tid)
                else:
                    ent = sim.get_entity(tid)
                    if ent is not None:
                        ent.shield = max(float(getattr(ent, "shield", 0.0)), val)
                if val > 0.0:
                    me.dispatch_event(
                        "OnListenInitShield",
                        param_entity_id=ctx.caster_id or tid,
                        param_entity2_id=tid,
                    )
            return

        if t == "RPG.GameCore.RemoveShield":
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            if ctx.modifier_instance is not None:
                ctx.modifier_instance.shield_value = 0.0
                ctx.modifier_instance.shield_max = 0.0
            for tid in targets:
                me.sync_entity_shield(tid)
            return

        if t in ("RPG.GameCore.ModifyShieldMax", "RPG.GameCore.ModifyShield"):
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            mod_names = [str(m) for m in (task.get("ShieldModifiers") or []) if m]
            delta = self._eval_num(task.get("FormulaValue"), ctx, 0.0)
            for tid in targets:
                if mod_names:
                    matched_mods = [
                        m for m in me.get_modifiers(tid) if m.name in mod_names
                    ]
                elif ctx.modifier_instance is not None and ctx.modifier_instance.owner_id == tid:
                    matched_mods = [ctx.modifier_instance]
                else:
                    matched_mods = []
                for m in matched_mods:
                    if t == "RPG.GameCore.ModifyShieldMax":
                        m.shield_max = max(0.0, m.shield_max + delta)
                    else:
                        new_v = max(0.0, m.shield_value + delta)
                        if m.shield_max > 0.0:
                            new_v = min(m.shield_max, new_v)
                        m.shield_value = new_v
                if t == "RPG.GameCore.ModifyShield":
                    me.sync_entity_shield(tid)
            return

        if t == "RPG.GameCore.DefineHPSharedGroup":
            mains = self._resolve_targets(task.get("MainTarget"), ctx)
            subs = self._resolve_targets(task.get("SubTargets"), ctx)
            if mains:
                main_id = mains[0]
                for sid in subs:
                    if sid and sid != main_id:
                        rt.hp_shared_groups[sid] = main_id
            return

        if t == "RPG.GameCore.ModifySpecialSP":
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            for tid in targets:
                if not tid or tid == "__LEVEL__":
                    continue
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                ep_tid = tid
                if getattr(ent, "is_memosprite", False) and getattr(ent, "max_energy", 0.0) <= 0.0 and getattr(ent, "master_name", None):
                    ep_tid = ent.master_name
                    ent = sim.get_entity(ep_tid)
                    if ent is None:
                        continue
                max_ep = float(sim.port.max_energy(ep_tid) or getattr(ent, "max_energy", 0.0) or 0.0)
                if "SetValue" in task:
                    val = self._eval_num(task.get("SetValue"), ctx, float(ent.energy))
                    ent.energy = max(0.0, min(max_ep, val)) if max_ep > 0.0 else max(0.0, val)
                else:
                    delta = self._eval_num(task.get("FixedAddValue") or task.get("AddValue"), ctx, 0.0)
                    if "AddMaxSPRatio" in task:
                        delta += max_ep * self._eval_num(task.get("AddMaxSPRatio"), ctx, 0.0)
                    new_ep = float(ent.energy) + delta
                    ent.energy = max(0.0, min(max_ep, new_ep)) if max_ep > 0.0 else max(0.0, new_ep)
            return

        if t == "RPG.GameCore.EnableNegativeHP":
            targets = (
                self._resolve_targets(task.get("TargetType"), ctx)
                if task.get("TargetType") is not None
                else [ctx.modifier_owner_id or ctx.caster_id]
            )
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None:
                    setattr(ent, "_negative_hp_enabled", True)
                    if ctx.modifier_instance is not None:
                        setattr(ctx.modifier_instance, "_enabled_negative_hp", True)
            return

        if t == "RPG.GameCore.AbortInsertAbility":
            ab_name = _str_val(task.get("AbilityName"))
            tgt_spec = task.get("TargetFilter") or task.get("TargetType")
            targets = self._resolve_targets(tgt_spec, ctx) if tgt_spec is not None else None
            sched = getattr(sim, "scheduler", None)
            if ab_name and sched is not None and hasattr(sched, "abort_pending_actions"):
                sched.abort_pending_actions(targets, ab_name)
            return

        if t == "RPG.GameCore.SetDynamicValueByCountOfBaseType":
            targets = self._resolve_targets(task.get("TargetType") or task.get("ReadTargetType"), ctx)
            want = {str(b) for b in (task.get("BaseTypeList") or ())}
            path_aliases = {
                "Warrior": "Destruction", "Destruction": "Destruction", "毁灭": "Destruction",
                "Rogue": "Hunt", "Hunt": "Hunt", "巡猎": "Hunt",
                "Mage": "Erudition", "Erudition": "Erudition", "智识": "Erudition",
                "Shaman": "Harmony", "Harmony": "Harmony", "同谐": "Harmony",
                "Warlock": "Nihility", "Nihility": "Nihility", "虚无": "Nihility",
                "Knight": "Preservation", "Preservation": "Preservation", "存护": "Preservation",
                "Priest": "Abundance", "Abundance": "Abundance", "丰饶": "Abundance",
                "Memory": "Remembrance", "Remembrance": "Remembrance", "记忆": "Remembrance",
                "Elation": "Elation", "欢愉": "Elation",
            }
            want_norm = {path_aliases.get(b, b) for b in want}
            cnt = 0
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                raw_path = str(getattr(ent, "path", "") or "")
                norm_path = path_aliases.get(raw_path, raw_path)
                if raw_path in want or norm_path in want_norm:
                    cnt += 1
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            self._write_dyn(task, ctx, key_h, float(cnt))
            return

        if t == "RPG.GameCore.AttackData":
            tgt_spec = task.get("TargetType") or {"Alias": "AbilityTargetEntity"}
            self._execute_damage({"TargetType": tgt_spec, "AttackProperty": task}, ctx)
            return

        if t in IGNORED_MECHANICAL_TASK_STUBS or t in IGNORED_OBFUSCATED_TASK_STUBS:
            return

        if is_safe_prunable_type(t):
            return

        if self.strict:
            raise NotImplementedError(f"未实现的 Task 节点类型: {t}")

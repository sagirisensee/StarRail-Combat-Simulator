"""官方 ConfigAbility AST Task & Predicate 解释器 + 战斗结算桥接 (Phase 3)。

将官方 `Task` 与 `Predicate` 指令集桥接到现有 `TurnSimulator` 微内核：
- Predicate 求值：`ops/predicates.py` (`PredicateOpsMixin`)；
- 伤害/治疗/能量/扣血：`ops/combat_ops.py` (`CombatOpsMixin`)；
- 回合插队/召唤/关卡事件/变身：`ops/turn_ops.py` (`TurnOpsMixin`)；
- 未知逻辑 `$type` 严禁静默跳过，默认抛出 `NotImplementedError`。
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

from ..events import DamageAppliedEvent, WeaknessBreakEvent
from ..status import StatType
from .expr import dotnet_hash, eval_dynamic_float
from .loader import PRUNABLE_PRESENTATION_TYPES
from .ops import CombatOpsMixin, PredicateOpsMixin, TurnOpsMixin
from .ops.predicates import _compare_values, _is_alive, _str_val
from .target_alias import ExecutionContext, resolve_target_type


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
            self._damage_capture_stack[-1][0] += float(evt.damage)

    def _on_weakness_break(self, evt: WeaknessBreakEvent) -> None:
        if self._damage_capture_stack:
            self._damage_capture_stack[-1][0] += float(evt.break_damage)

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
                            cur = [tid for tid in cur if _is_alive(sim, tid)]
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
            elif scope not in ("ContextCaster", "SummonerEntity"):
                mod_floats = ctx.modifier_instance.config.get("DynamicValues", {}).get("Floats", {})
                if str(key_h) in mod_floats or key_h in ctx.modifier_instance.dynamic_values:
                    if "TargetType" not in task or target_id == ctx.modifier_instance.owner_id:
                        mod_target = ctx.modifier_instance
        self.rt.set_dynamic_value(
            target_id,
            key_h,
            value,
            modifier=mod_target,
            ability_name=ctx.ability_name,
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

        if t == "RPG.GameCore.LoopExecuteTaskList":
            cnt = max(0, min(64, int(round(self._eval_num(task.get("MaxLoopCount"), ctx, 0.0)))))
            for _ in range(cnt):
                self.execute_tasks(task.get("TaskList", []), ctx)
            return

        if t == "RPG.GameCore.IncludeTaskListTemplate":
            tpl_name = _str_val(task.get("Name") or task.get("TemplateName"))
            if tpl_name in ("PursuedDamage_PerformanceDelay", "PursuedDamage_PerformanceDelay_ForSnapshotEntity"):
                return
            tpl_tasks = rt.find_template(tpl_name, ctx.ability_name)
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
            if all(not getattr(sim.get_entity(tid), "is_enemy", False) for tid in targets):
                for tid in targets:
                    rt.trigger_ability(
                        caster_id=tid,
                        ability_name=ab_name,
                        target_ids=(tid,),
                        skill_target_ids=ctx.skill_target_ids,
                        current_skill_type=ctx.current_skill_type,
                        current_attack_type=ctx.current_attack_type,
                    )
            else:
                child_targets = (
                    ctx.ability_target_ids
                    if bool(task.get("IsSkillPerform")) and ctx.ability_target_ids
                    else tuple(targets)
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
            for item in entries:
                if not isinstance(item, Mapping):
                    continue
                ab_name = _str_val(item.get("AbilityName"))
                if not ab_name or ab_name.endswith("_Camera") or "_Camera_" in ab_name:
                    continue
                targets = self._resolve_targets(item.get("TargetType"), ctx)
                if not targets:
                    continue
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
            return

        if t == "RPG.GameCore.SetDynamicValue":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
            val = self._eval_num(task.get("Value"), ctx, 0.0)
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

        if t == "RPG.GameCore.SetDynamicValueByProperty":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
            read_targets = self._resolve_targets(task.get("ReadTargetType") or {"Alias": "ModifierOwnerEntity"}, ctx)
            prop_name = str(task.get("Value", ""))
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
            if task.get("AliveOnly", True):
                targets = [tid for tid in targets if _is_alive(sim, tid)]
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
            val = float(ctx.change_value) if vtype == "ParamValue" else 0.0
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
            cnt = int(round(self._eval_num(cnt_spec, ctx, 1.0))) if cnt_spec is not None else 1
            max_l = int(round(self._eval_num(task["MaxLayer"], ctx, 1.0))) if "MaxLayer" in task else None
            inherit = str(task.get("InheritCaster", ""))
            for tid in targets:
                eff_caster = tid if inherit == "TargetSelf" else ctx.caster_id
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
            targets = self._resolve_targets(task.get("TargetType"), ctx)
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
            flag = str(task.get("BehaviorFlag", ""))
            for tid in targets:
                for m in list(me.get_modifiers(tid)):
                    if flag in m.behavior_flags:
                        me.destroy_modifier(m)
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
                                m.config.get("StatusType") == "Debuff"
                                or ("STAT_CTRL" in m.behavior_flags)
                                or ("DisableAction" in m.behavior_flags)
                                or (float(m.properties.get("AllDamageTypeTakenRatio", 0.0)) > 0.0)
                            )
                            and "UnDispellable" not in m.behavior_flags
                            and m.halo_parent_uid is None
                        )
                    ]
                if order == "LastAdded":
                    cands.sort(key=lambda m: getattr(m, "_spawn_order", 0), reverse=True)
                else:
                    cands.sort(key=lambda m: getattr(m, "_spawn_order", 0))
                for m in cands[:count]:
                    me.destroy_modifier(m)
                for m in list(me.get_modifiers(tid)):
                    me._sync_modifier_to_status_mgr(m)
            return

        # 4. 战斗结算：治疗 / 伤害 / 自扣血 / 战技点 / 拉推条 / 插队 / 召唤
        if t == "RPG.GameCore.SetHP":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            val = self._eval_num(task.get("ModifyValue") or task.get("Value"), ctx, -1.0)
            if val >= 0.0:
                for tid in targets:
                    ent = sim.get_entity(tid)
                    if ent is not None and getattr(ent, "current_hp", 0.0) > 0.0:
                        max_hp = sim.port.max_hp(tid) or getattr(ent, "max_hp", val)
                        ent.current_hp = max(0.0, min(float(max_hp), float(val)))
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
            val = self._eval_num(
                task.get("AddNormalizedValue") or task.get("AddValue") or task.get("DelayValue") or task.get("Value"),
                ctx,
                0.0,
            )
            cur_turn = getattr(sim, "_current_turn_entity", None)
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
                            insert_at = 0
                            while insert_at < len(rq) and rq[insert_at] in batch_ids:
                                insert_at += 1
                            rq.insert(insert_at, tid)
                            batch_ids.append(tid)
                    else:
                        sim.port.set_distance(tid, 0.0)
                else:
                    sim.port.set_distance(tid, max(0.0, val * 10000.0))
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

        if t == "RPG.GameCore.ForceKill":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
            mute_death = bool(task.get("MuteAllTriggerDeath", False))
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                if getattr(ent, "is_memosprite", False):
                    me.dispatch_event("OnDeathrattle", owner_id=tid, param_entity_id=tid)
                    master_id = getattr(ent, "master_name", None)
                    me.dispatch_event(
                        "OnTriggerDeathrattle",
                        owner_id=master_id,
                        param_entity_id=tid,
                    )
                prev_hp = getattr(ent, "current_hp", 0.0)
                ent.current_hp = 0.0
                if getattr(ent, "is_enemy", False) and prev_hp > 0.0:
                    from simulator.events import EnemyDefeatedEvent
                    sim.event_bus.publish(
                        EnemyDefeatedEvent(
                            av=float(sim.current_av),
                            cycle=int(sim.current_cycle),
                            attacker_name=ctx.caster_id or "",
                            target_name=tid,
                        )
                    )
                    director = getattr(sim, "_stage_director", None)
                    runner = getattr(director, "runner", None) if director is not None else None
                    if runner is not None:
                        runner.state.enemies[:] = [m for m in runner.state.enemies if m.entity.name != tid]
                    sim.entities[:] = [e for e in sim.entities if e.name != tid]
                elif not mute_death:
                    me.dispatch_event("OnListenCharacterDie", param_entity_id=tid)
                me.destroy_all_for_entity(tid)
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
            cur_turn = getattr(sim, "_current_turn_entity", None)
            if cur_turn is not None:
                cur_d = getattr(sim, "_pending_turn_reset_distance", None)
                base_d = 10000.0 if cur_d is None else float(cur_d)
                new_d = max(0.0, base_d + val * 10000.0)
                sim._pending_turn_reset_distance = new_d
                if new_d <= 0.0:
                    setattr(cur_turn, "_vm_immediate_jump", True)
            return

        if t == "RPG.GameCore.SummonMonster":
            director = getattr(sim, "_stage_director", None)
            if director is not None and hasattr(director, "flush_ally_talent_heals"):
                director.flush_ally_talent_heals()
            if director is not None and hasattr(director, "summon_enemy"):
                director.summon_enemy(
                    ctx.caster_id,
                    task,
                    dynamic_resolver=lambda h: self.rt.resolve_hash(
                        ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx
                    ),
                )
            return

        if t == "RPG.GameCore.SetMonsterPhase":
            director = getattr(sim, "_stage_director", None)
            if director is not None and hasattr(director, "trigger_monster_phase_transition"):
                mode = str(task.get("SetMode") or task.get("Mode") or "Inc")
                val_spec = task.get("PhaseValue") if "PhaseValue" in task else task.get("Value")
                val = int(round(self._eval_num(val_spec, ctx, 1.0))) if val_spec is not None else None
                targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.caster_id]
                for tid in targets:
                    director.trigger_monster_phase_transition(tid, mode=mode, value=val)
            return

        if t in (
            "RPG.GameCore.LockHP",
            "RPG.GameCore.ResetStance",
            "RPG.GameCore.ExitBreakState",
            "RPG.GameCore.StackWeakness",
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
                    runner.execute_stage_task(
                        task,
                        caster_name=tid,
                        dynamic_resolver=lambda h: self.rt.resolve_hash(
                            ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx
                        ),
                    )
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

        if t == "PGFAJJBCMDK":
            owner_id = ctx.modifier_owner_id or ctx.caster_id
            owner_ent = sim.get_entity(owner_id) if owner_id else None
            if owner_ent is not None:
                owner_ent.barrier_guarded = True
                owner_ent.toughness_locked = True
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

        if t == "RPG.GameCore.AttachAvatarChange":
            self._execute_attach_avatar_change(task, ctx)
            return

        if t == "RPG.GameCore.DetachAvatarChange":
            self._execute_detach_avatar_change(task, ctx)
            return

        if t in (
            "RPG.GameCore.AttachEntityUnselectable",
            "RPG.GameCore.SetMonsterEnergyBarState",
            "RPG.GameCore.TriggerCustomString",
            "RPG.GameCore.AttachEntityDeparted",
            "RPG.GameCore.ChangeCharacterRowData",
            "RPG.GameCore.RemoveEntityFromTeamFormation",
            "RPG.GameCore.SetTeamFormation",
            "RPG.GameCore.SetEntityForbidCameraDither",
            "RPG.GameCore.SetEntityVisible",
            "RPG.GameCore.SetDieImmediately",
            "RPG.GameCore.OwnerEntityAddAbility",
            "OOCOGGMJLBN",
            "RPG.GameCore.StackStatusResistance",
            "RPG.GameCore.SetResilience",
            "RPG.GameCore.CharacterChangePhase",
            "RPG.GameCore.LockActionDelayChange",
            "RPG.GameCore.AttachSkillTypeDisable",
            "RPG.GameCore.SummonPartner",
            "RPG.GameCore.Remodifier",
            "RPG.GameCore.TriggerModifierCustomEvent",
            "RPG.GameCore.SetStanceCount",
            "FOIBLOANLCJ",
            "CKCOFEAAJII",
            "KADCLBEPFPL",
            "NDFKINKPKHF",
            "EOPFECKEAIK",
            "GFODFDCBFJF",
        ):
            return

        from .stage_prunable_types import is_safe_prunable_type

        if is_safe_prunable_type(t):
            return

        if self.strict:
            raise NotImplementedError(f"未实现的 Task 节点类型: {t}")

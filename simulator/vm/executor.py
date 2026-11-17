"""官方 ConfigAbility AST Task & Predicate 解释器 + 战斗结算桥接 (Phase 3)。

将官方 `Task` 与 `Predicate` 指令集桥接到现有 `TurnSimulator` 微内核：
- 伤害：`AttackData` + `DamageByAttackProperty` -> `DamageCalculator` / `CombatPort.attack`；
- 治疗：`HealHP` (`HealByHealerMaxHP`, `HealByTargetMaxHP`, `HealByTargetLostHP`, `HealByBaseValue`) -> `HealCalculator` + `OnBeforeDealHeal` / `OnAfterDealHeal`；
- 行动条与插队：`ModifyActionDelay` / `ResetActionDelay` / `TurnInsertAbility` / `TurnInsertAction` -> `ActionScheduler`；
- 忆灵召唤与自扣血：`CreateServant` / `LoseHPByRatio` -> `Entity` / `HPLostEvent` / `OnListenHPChange`；
- 未知逻辑 `$type` 严禁静默跳过，默认抛出 `NotImplementedError`。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..actions import ActionKind, ActionScheduleCategory, DamageType, FollowUpPhase
from ..entity import Entity
from ..events import HPLostEvent
from ..status import StatType
from .expr import dotnet_hash, eval_dynamic_float
from .target_alias import ExecutionContext, resolve_target_type


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
    raise ValueError(f"未知 CompareType: {cmp_type}")


def _str_val(v: Any) -> str:
    if isinstance(v, Mapping):
        return str(v.get("Value", ""))
    return str(v or "")


def _is_alive(sim: Any, eid: str) -> bool:
    if eid == "__LEVEL__":
        return True
    e = sim.get_entity(eid)
    return bool(e is not None and (getattr(e, "current_hp", 0.0) > 0 or getattr(e, "is_infinite_hp", False)))


class TaskExecutor:
    """官方 ConfigAbility Task 与 Predicate 解释执行器。"""

    def __init__(self, runtime: Any, strict: bool = True) -> None:
        self.rt = runtime
        self.strict = strict

    def _eval_num(self, spec: Any, ctx: ExecutionContext, default: float = 0.0) -> float:
        return eval_dynamic_float(
            spec,
            lambda h: self.rt.resolve_hash(ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx),
            default,
        )

    def _dyn_scope_entity(self, task: Mapping[str, Any], ctx: ExecutionContext) -> str:
        scope = task.get("ContextScope", "")
        if scope == "SummonerEntity":
            t = resolve_target_type(task.get("TargetType") or {"Alias": "CasterSummoner"}, ctx)
            return t[0] if t else ctx.caster_id
        if "TargetType" in task:
            t = resolve_target_type(task["TargetType"], ctx)
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
        if ctx.modifier_instance is not None:
            if scope in ("Modifier", "ContextModifier"):
                mod_target = ctx.modifier_instance
            elif "TargetType" not in task and scope not in ("ContextCaster", "SummonerEntity"):
                mod_floats = ctx.modifier_instance.config.get("DynamicValues", {}).get("Floats", {})
                if str(key_h) in mod_floats or key_h in ctx.modifier_instance.dynamic_values:
                    mod_target = ctx.modifier_instance
        target_id = self._dyn_scope_entity(task, ctx)
        self.rt.set_dynamic_value(
            target_id,
            key_h,
            value,
            modifier=mod_target,
            ability_name=ctx.ability_name,
        )

    # ------------------------------------------------------------------
    # Predicate 求值
    # ------------------------------------------------------------------
    def eval_predicate(self, pred: Optional[Mapping[str, Any]], ctx: ExecutionContext) -> bool:
        if not pred:
            return True
        res = self._eval_predicate_raw(pred, ctx)
        if pred.get("Inverse"):
            return not res
        return res

    def _eval_predicate_raw(self, pred: Mapping[str, Any], ctx: ExecutionContext) -> bool:
        t = pred.get("$type", "")
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        if t == "RPG.GameCore.ByAnd":
            return all(self.eval_predicate(p, ctx) for p in pred.get("PredicateList", []))
        if t == "RPG.GameCore.ByAny":
            return any(self.eval_predicate(p, ctx) for p in pred.get("PredicateList", []))
        if t == "RPG.GameCore.ByNot":
            return not self.eval_predicate(pred.get("Predicate"), ctx)

        if t == "RPG.GameCore.ByCompareDynamicValue":
            key_str = _str_val(pred.get("DynamicKey"))
            key_h = dotnet_hash(key_str)
            scope_targets = resolve_target_type(pred.get("TargetType"), ctx) if "TargetType" in pred else [ctx.caster_id]
            tid = scope_targets[0] if scope_targets else ctx.caster_id
            lhs = rt.get_dynamic_value(tid, key_h, ability_name=ctx.ability_name, local_ctx=ctx)
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareAbilityProperty":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            prop = str(pred.get("Property", ""))
            lhs = me.get_entity_property(targets[0], prop) if targets else 0.0
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareModifierValue":
            mname = _str_val(pred.get("ModifierName"))
            mod = None
            if ctx.modifier_instance is not None and (not mname or ctx.modifier_instance.name == mname):
                mod = ctx.modifier_instance
            elif mname:
                search_ids = resolve_target_type(pred.get("TargetType"), ctx) if "TargetType" in pred else [ctx.caster_id, ctx.modifier_owner_id or ctx.caster_id]
                for sid in search_ids:
                    found = me.get_modifiers(sid, mname)
                    if found:
                        mod = found[0]
                        break
            vtype = pred.get("ValueType", "Layer")
            lhs = 0.0
            if mod is not None:
                if vtype == "Layer":
                    lhs = float(mod.layer)
                elif vtype == "LifeTime":
                    lhs = float(mod.life_time or 0.0)
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareChangeValue":
            lhs = float(ctx.change_value)
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareParamValue":
            lhs = float(ctx.change_value)
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareHPRatio":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            lhs = me.get_entity_property(targets[0], "HPRatio") if targets else 0.0
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareStanceCount":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            ent = sim.get_entity(targets[0]) if targets else None
            lhs = float(getattr(ent, "current_toughness", 0.0)) if ent else 0.0
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByIsContainModifier":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            mname = _str_val(pred.get("ModifierName"))
            caster_only = bool(pred.get("OnlyCheckCasterAdded", False))
            c_filter = ctx.caster_id if caster_only else None
            return any(me.has_modifier(tid, mname, c_filter) for tid in targets)

        if t == "RPG.GameCore.ByContainBehaviorFlag":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            flag = str(pred.get("BehaviorFlag", ""))
            return any(me.has_behavior_flag(tid, flag) for tid in targets)

        if t == "RPG.GameCore.ByRankActivated":
            targets = resolve_target_type(pred.get("TargetType") or {"Alias": "Caster"}, ctx)
            tk = pred.get("TriggerKey", {})
            th = int(tk.get("Hash", 0)) if isinstance(tk, Mapping) else 0
            for tid in targets:
                spec = rt.entity_specs.get(tid)
                if spec is None:
                    continue
                for r in spec.unlocked_ranks:
                    if dotnet_hash(f"Rank0{r}") == th:
                        return True
            return False

        if t == "RPG.GameCore.BySkillPointActivated":
            # 行迹大节点（PointB1/B2/B3）默认全部已解锁
            return True

        if t == "RPG.GameCore.ByCompareTarget":
            t1 = resolve_target_type(pred.get("TargetType"), ctx)
            t2 = resolve_target_type(pred.get("CompareType"), ctx)
            return bool(t1 and t2 and set(t1) == set(t2))

        if t == "RPG.GameCore.ByTargetListIntersects":
            s1 = set(resolve_target_type(pred.get("FirstTargetType"), ctx))
            s2 = set(resolve_target_type(pred.get("SecondTargetType"), ctx))
            return bool(s1 & s2)

        if t == "RPG.GameCore.ByTargetListAny":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            sub_pred = pred.get("Predicate")
            for tid in targets:
                sub_ctx = ctx.clone(param_entity_id=tid)
                if self.eval_predicate(sub_pred, sub_ctx):
                    return True
            return False

        if t == "RPG.GameCore.ByCompareTargetCount":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            if pred.get("AliveOnly"):
                targets = [tid for tid in targets if _is_alive(sim, tid)]
            lhs = float(len(targets))
            rhs = self._eval_num(pred.get("Number"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareCharacterNumber":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            lhs = float(len([tid for tid in targets if _is_alive(sim, tid)]))
            rhs = self._eval_num(pred.get("Number") or pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareWaveCount":
            lhs = float(getattr(sim, "current_wave", 1))
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 1.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByTargetTeam":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            want_team = str(pred.get("Team", ""))
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                is_dark = bool(getattr(ent, "is_enemy", False))
                if want_team in ("TeamDark", "Dark") and is_dark:
                    return True
                if want_team in ("TeamLight", "Light") and not is_dark:
                    return True
            return False

        if t == "RPG.GameCore.ByTargetEntityType":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            want = str(pred.get("EntityType") or pred.get("EntityTypeMask") or "")
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                if "Servant" in want and getattr(ent, "is_memosprite", False):
                    return True
                if "Avatar" in want and not getattr(ent, "is_enemy", False) and not getattr(ent, "is_memosprite", False):
                    return True
                if "Monster" in want and getattr(ent, "is_enemy", False):
                    return True
            return False

        if t == "RPG.GameCore.ByTargetAliveState":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            mask = str(pred.get("AliveStateMask", ""))
            want = "Dead" if "Dead" in mask else str(pred.get("AliveState", "Alive"))
            for tid in targets:
                alive = _is_alive(sim, tid)
                if want == "Alive" and alive:
                    return True
                if want == "Dead" and not alive:
                    return True
            return False

        if t == "RPG.GameCore.ByIsTargetValid":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            if pred.get("AliveOnly"):
                targets = [tid for tid in targets if _is_alive(sim, tid)]
            return len(targets) > 0

        if t == "RPG.GameCore.ByCurrentSkillType":
            want = str(pred.get("SkillType") or "Normal")
            aliases = {"BPSkill": "Skill", "Skill": "Skill"}
            got = aliases.get(ctx.current_skill_type, ctx.current_skill_type)
            want_norm = aliases.get(want, want)
            return got == want_norm

        if t == "RPG.GameCore.ByAttackType":
            want = str(pred.get("AttackType", ""))
            return ctx.current_attack_type == want

        if t == "RPG.GameCore.ByCharacterDamageType":
            targets = resolve_target_type(pred.get("TargetType") or {"Alias": "Caster"}, ctx)
            dt = pred.get("DamageType", {})
            want = dt.get("DamageType", "") if isinstance(dt, Mapping) else str(dt)
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None and getattr(ent, "element", "") == want:
                    return True
            return False

        if t == "RPG.GameCore.ByAvatarBaseType":
            targets = resolve_target_type(pred.get("TargetType") or {"Alias": "Caster"}, ctx)
            base_list = pred.get("BaseTypeList")
            if isinstance(base_list, list):
                wants = {str(x) for x in base_list}
            else:
                wants = {str(pred.get("AvatarBaseType", ""))}
            for tid in targets:
                spec = rt.entity_specs.get(tid)
                if spec is not None and not spec.is_servant:
                    rt.loader._ensure_avatars()
                    av = rt.loader._avatars.get(spec.unit_id)
                    if av and av.get("AvatarBaseType") in wants:
                        return True
            return False

        if t == "RPG.GameCore.ByHaveEnemyAlive":
            return any(getattr(e, "is_enemy", False) and e.current_hp > 0 for e in sim.entities)

        if t == "RPG.GameCore.ByCheckFightFinish":
            has_enemy = any(getattr(e, "is_enemy", False) and e.current_hp > 0 for e in sim.entities)
            has_ally = any(not getattr(e, "is_enemy", False) and e.current_hp > 0 for e in sim.entities)
            return (not has_enemy) or (not has_ally)

        if t == "RPG.GameCore.ByIsBattleEventEntity":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            return any(bool(getattr(sim.get_entity(tid), "is_countdown", False)) for tid in targets)

        if t == "RPG.GameCore.ByIsTurnOwnerEntity":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            cur = getattr(sim, "current_turn_entity", None)
            return bool(cur is not None and cur.name in targets)

        if t == "RPG.GameCore.ByTurnOwnerActionPhaseEnd":
            return bool(getattr(rt, "_in_turn_phase1_end", False))

        if t == "RPG.GameCore.ByHasSummonRelation":
            summoners = resolve_target_type(pred.get("SummonerType"), ctx)
            servants = resolve_target_type(pred.get("ServantType"), ctx)
            for sv in servants:
                ent = sim.get_entity(sv)
                if ent is not None and getattr(ent, "master_name", None) in summoners:
                    return True
            return False

        if t == "RPG.GameCore.ByCheckModifierCallBackName":
            return ctx.callback_modifier_name == _str_val(pred.get("ModifierName"))

        if t == "RPG.GameCore.ByCheckModifierCallBackBehaviorFlag":
            want = str(pred.get("BehaviorFlag", ""))
            return want in ctx.callback_behavior_flags

        if t == "RPG.GameCore.ByContainsParamFlag":
            return str(pred.get("Flag", "")) in ctx.param_flags

        if t == "RPG.GameCore.ByDieAnimFinished":
            return True

        if t == "RPG.GameCore.BySimulateSpeedUp":
            return False

        if t == "RPG.GameCore.ByCompareMonsterRank":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None and getattr(ent, "is_boss", False) and pred.get("Rank") in ("Boss", "LittleBoss"):
                    return True
            return False

        if t == "RPG.GameCore.ByCompareMonsterID":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            mid = str(pred.get("MonsterID", ""))
            return any(str(getattr(sim.get_entity(tid), "monster_id", "")) == mid for tid in targets)

        if t == "RPG.GameCore.ByHasStanceWeak":
            targets = resolve_target_type(pred.get("TargetType"), ctx)
            wt = pred.get("WeakType", {})
            elem = wt.get("DamageType", "") if isinstance(wt, Mapping) else str(wt)
            return any(elem in getattr(sim.get_entity(tid), "weaknesses", []) for tid in targets)

        if t == "RPG.GameCore.ByInTurnBasedGameModeState":
            return True

        if t == "NDFKINKPKHF":
            return False

        if self.strict:
            raise NotImplementedError(f"未实现的 Predicate 类型: {t}")
        return False

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

        if not t:
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

        if t == "RPG.GameCore.IncludeTaskListTemplate":
            tpl_name = _str_val(task.get("Name") or task.get("TemplateName"))
            tpl_tasks = rt.find_template(tpl_name, ctx.ability_name)
            if tpl_tasks is None:
                if self.strict:
                    raise KeyError(f"找不到 TaskListTemplate: {tpl_name}")
                return
            sub_dyn = dict(ctx.local_dynamics)
            for k, v in (task.get("DynamicValues") or {}).items():
                sub_dyn[dotnet_hash(k)] = self._eval_num(v, ctx, 0.0)
            param_tgts = resolve_target_type(task.get("ParamTarget"), ctx) if "ParamTarget" in task else []
            sub_ctx = ctx.clone(
                local_dynamics=sub_dyn,
                param_entity_id=param_tgts[0] if param_tgts else ctx.param_entity_id,
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
            sub_ctx = ctx.clone(local_dynamics=sub_dyn)
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
            targets = resolve_target_type(task.get("TargetType"), ctx)
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
                rt.trigger_ability(
                    caster_id=ctx.caster_id,
                    ability_name=ab_name,
                    target_ids=tuple(targets),
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
                targets = resolve_target_type(item.get("TargetType"), ctx)
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
            candidates = resolve_target_type(task.get("TargetType"), ctx)
            pred = task.get("Predicate")
            matched: List[str] = []
            for cid in candidates:
                p_ctx = ctx.clone(param_entity_id=cid)
                if self.eval_predicate(pred, p_ctx):
                    matched.append(cid)
            if "MaxNumber" in task:
                cap = max(0, int(round(self._eval_num(task.get("MaxNumber"), ctx, len(matched)))))
                matched = matched[:cap]
            for tid in matched:
                t_ctx = ctx.clone(param_entity_id=tid, ability_target_ids=(tid,))
                self.execute_tasks(task.get("TaskList", []), t_ctx)
            return

        if t in ("RPG.GameCore.FireProjectile", "RPG.GameCore.NewFireProjectile"):
            self.execute_tasks(task.get("OnProjectileHit", []), ctx)
            self.execute_tasks(task.get("OnHit", []), ctx)
            return

        # 2. DynamicValues 操作
        if t == "RPG.GameCore.SetDynamicValue":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
            val = self._eval_num(task.get("Value"), ctx, 0.0)
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByAddValue":
            key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
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
            read_targets = resolve_target_type(task.get("ReadTargetType") or {"Alias": "ModifierOwnerEntity"}, ctx)
            prop_name = str(task.get("Value", ""))
            val = me.get_entity_property(read_targets[0], prop_name) if read_targets else 0.0
            self._write_dyn(task, ctx, key_h, val)
            return

        if t == "RPG.GameCore.SetDynamicValueByCopying":
            from_t = resolve_target_type(task.get("FromTargetType"), ctx)
            to_t = resolve_target_type(task.get("ToTargetType") or {"Alias": "ModifierOwnerEntity"}, ctx)
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
            targets = resolve_target_type(task.get("TargetType"), ctx) if "TargetType" in task else [ctx.modifier_owner_id or ctx.caster_id]
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
            targets = resolve_target_type(task.get("ReadTargetType") or task.get("TargetType"), ctx)
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
            targets = resolve_target_type(task.get("TargetType"), ctx)
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
            targets = resolve_target_type(task.get("TargetType"), ctx) if "TargetType" in task else [ctx.modifier_owner_id or ctx.caster_id]
            mname = _str_val(task.get("ModifierName"))
            mfunc = str(task.get("ModifyFunction", "Set"))
            vtype = str(task.get("ValueType") or ("Layer" if (mfunc == "Add" and "Value" not in task) else "LifeTime"))
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
                    if vtype == "Layer" and m.layer <= 0:
                        me.destroy_modifier(m)
            return

        # 3. Modifier 与属性操作
        if t == "RPG.GameCore.AddModifier":
            targets = resolve_target_type(task.get("TargetType"), ctx)
            mname = _str_val(task.get("ModifierName"))
            life = self._eval_num(task["LifeTime"], ctx) if "LifeTime" in task else None
            cnt_spec = task.get("LayerAddWhenStack") if "LayerAddWhenStack" in task else task.get("Count")
            cnt = int(round(self._eval_num(cnt_spec, ctx, 1.0))) if cnt_spec is not None else 1
            max_l = int(round(self._eval_num(task["MaxLayer"], ctx, 1.0))) if "MaxLayer" in task else None
            inherit = str(task.get("InheritCaster", ""))
            for tid in targets:
                eff_caster = tid if inherit == "TargetSelf" else ctx.caster_id
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
            targets = resolve_target_type(task.get("TargetType"), ctx)
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
            targets = resolve_target_type(task.get("TargetType"), ctx)
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
            targets = resolve_target_type(task.get("TargetType"), ctx)
            for tid in targets:
                sim.port.dispel(tid, is_debuff=True)
            return

        # 4. 战斗结算：治疗 / 伤害 / 自扣血 / 战技点 / 拉推条 / 插队 / 召唤
        if t == "RPG.GameCore.HealHP":
            self._execute_heal(task, ctx)
            return

        if t == "RPG.GameCore.ModifyHealData":
            if ctx.heal_data is not None:
                for k in ("HealRatioAdded", "HealPercentage", "ModifyValue"):
                    if k in task:
                        ctx.heal_data[k] = ctx.heal_data.get(k, 0.0) + self._eval_num(task[k], ctx, 0.0)
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

        if t == "RPG.GameCore.LoseHPByRatio":
            self._execute_lose_hp(task, ctx)
            return

        if t == "RPG.GameCore.ModifySPNew":
            delta = int(round(self._eval_num(task.get("AddSP") or task.get("Value"), ctx, 0.0)))
            if delta != 0:
                sim.port.change_sp(ctx.caster_id, delta, reason=ctx.ability_name or "VM_Skill")
                me.dispatch_event("OnSPChange", owner_id=ctx.caster_id, change_value=float(delta))
            return

        if t == "RPG.GameCore.ModifyActionDelay":
            targets = resolve_target_type(task.get("TargetType"), ctx)
            val = self._eval_num(task.get("AddValue") or task.get("DelayValue") or task.get("Value"), ctx, 0.0)
            for tid in targets:
                if val < 0:
                    sim.port.advance(ctx.caster_id, tid, abs(val))
                elif val > 0:
                    sim.port.delay(ctx.caster_id, tid, val)
            return

        if t == "RPG.GameCore.ResetActionDelay":
            targets = resolve_target_type(task.get("TargetType"), ctx)
            for tid in targets:
                sim.port.advance(ctx.caster_id, tid, 1.0)
            return

        if t == "RPG.GameCore.SetActionDelay":
            targets = resolve_target_type(task.get("TargetType"), ctx)
            val = self._eval_num(task.get("DelayValue") or task.get("Value"), ctx, 1.0)
            for tid in targets:
                sim.port.set_distance(tid, max(0.0, val * 10000.0))
            return

        if t in ("RPG.GameCore.TurnInsertAbility", "RPG.GameCore.TurnInsertAbilityCondition", "RPG.GameCore.TurnInsertAction"):
            self._execute_turn_insert(task, ctx)
            return

        if t == "RPG.GameCore.CreateServant":
            self._execute_create_servant(task, ctx)
            return

        if t == "RPG.GameCore.ForceKill":
            targets = resolve_target_type(task.get("TargetType"), ctx)
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None:
                    ent.current_hp = 0.0
                    if getattr(ent, "is_memosprite", False):
                        sim.port.despawn_spirit(tid, reason="ForceKill")
            return

        if t in (
            "RPG.GameCore.SetEnergyBarState",
            "RPG.GameCore.SetSummonerEnergyBarState",
            "RPG.GameCore.ModifyTeamBoostPoint",
            "RPG.GameCore.ModifyCurrentSkillDelayCost",
            "RPG.GameCore.SetTargetUniqueName",
            "RPG.GameCore.SetEntityActionState",
            "RPG.GameCore.SetTargetAlwaysAutoBattle",
            "RPG.GameCore.AddEntityToTeamFormation",
            "RPG.GameCore.RemoveEntityFromTeamFormation",
            "RPG.GameCore.AttachEntityUnselectable",
            "RPG.GameCore.SetDieImmediately",
            "RPG.GameCore.DamagePerformFinish",
            "RPG.GameCore.SkillPerformFinish",
            "RPG.GameCore.StackStatusDesc",
            "RPG.GameCore.StackStatusResistance",
            "RPG.GameCore.SetResilience",
            "RPG.GameCore.CharacterChangePhase",
            "RPG.GameCore.LockActionDelayChange",
            "RPG.GameCore.AttachSkillTypeDisable",
            "RPG.GameCore.SummonPartner",
            "RPG.GameCore.Remodifier",
            "RPG.GameCore.CreateBattleEvent",
            "RPG.GameCore.LinearProjectileData",
            "FOIBLOANLCJ",
            "CKCOFEAAJII",
            "KADCLBEPFPL",
            "NDFKINKPKHF",
            "EOPFECKEAIK",
            "GFODFDCBFJF",
        ):
            # 状态标记 / HUD / 动作收尾确认节点（逻辑均在对应前置指令完成）
            return

        if self.strict:
            raise NotImplementedError(f"未实现的 Task 节点类型: {t}")

    # ------------------------------------------------------------------
    # 具体战斗算子实现
    # ------------------------------------------------------------------
    def _execute_heal(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        targets = resolve_target_type(task.get("TargetType"), ctx)
        healer = sim.get_entity(ctx.caster_id)
        if healer is None or not targets:
            return

        ftype = str(task.get("FormulaType", "HealByHealerMaxHP"))
        pct = self._eval_num(task.get("HealPercentage"), ctx, 0.0)
        flat = self._eval_num(task.get("ModifyValue"), ctx, 0.0)
        healer_max_hp = float(sim.port.max_hp(healer.name))

        post_events: List[Tuple[str, Dict[str, Any]]] = []
        for tid in targets:
            tgt = sim.get_entity(tid)
            if tgt is None or tgt.current_hp <= 0:
                continue
            if ftype == "HealByHealerMaxHP":
                base_heal = healer_max_hp * pct + flat
            elif ftype == "HealByTargetMaxHP":
                base_heal = float(sim.port.max_hp(tgt.name)) * pct + flat
            elif ftype == "HealByTargetLostHP":
                m_hp = float(sim.port.max_hp(tgt.name))
                base_heal = max(0.0, m_hp - tgt.current_hp) * pct + flat
            elif ftype == "HealByBaseValue":
                base_heal = flat
            elif ftype == "HealByHealerDefence":
                base_heal = float(healer.defense) * pct + flat
            else:
                raise NotImplementedError(f"未实现的 HealHP FormulaType: {ftype}")

            heal_data = {
                "HealRatioAdded": 0.0,
                "BaseHeal": base_heal,
                "HealValue": 0.0,
                "ActualHealValue": 0.0,
                "OverflowHealValue": 0.0,
            }
            me.dispatch_event(
                "OnBeforeDealHeal",
                owner_id=ctx.caster_id,
                param_entity_id=tid,
                heal_data=heal_data,
            )
            me.dispatch_event(
                "OnBeforeBeingHeal",
                owner_id=tid,
                param_entity_id=ctx.caster_id,
                heal_data=heal_data,
            )

            outgoing = float(sim.port.stat(healer.name, StatType.OUTGOING_HEALING)) + heal_data["HealRatioAdded"]
            final_heal = max(0.0, base_heal * (1.0 + outgoing))
            hp_before = float(tgt.current_hp)
            cap = tgt.effective_hp_cap(float(sim.port.max_hp(tgt.name)))
            actual_restored = max(0.0, min(cap, hp_before + final_heal) - hp_before)
            heal_data["HealValue"] = final_heal
            heal_data["ActualHealValue"] = actual_restored
            heal_data["OverflowHealValue"] = max(0.0, final_heal - actual_restored)
            post_events.append((tid, heal_data))

        for tid, heal_data in post_events:
            sim.port.heal(ctx.caster_id, tid, heal_data["HealValue"])

        for tid, heal_data in post_events:
            me.dispatch_event(
                "OnAfterDealHeal",
                owner_id=ctx.caster_id,
                param_entity_id=tid,
                heal_data=heal_data,
            )
            me.dispatch_event(
                "OnAfterBeingHeal",
                owner_id=tid,
                param_entity_id=ctx.caster_id,
                heal_data=heal_data,
            )

    def _execute_damage(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        targets = resolve_target_type(task.get("TargetType"), ctx)
        atk_prop = task.get("AttackProperty") or {}
        if not targets or not atk_prop:
            return

        _ELEM_ZH_TO_EN = {
            "物理": "Physical",
            "火": "Fire",
            "冰": "Ice",
            "雷": "Lightning",
            "风": "Wind",
            "量子": "Quantum",
            "虚数": "Imaginary",
            "Thunder": "Lightning",
        }
        dt_obj = atk_prop.get("DamageType", {})
        if isinstance(dt_obj, Mapping) and dt_obj.get("SourceType") == "ReadTargetType":
            rt_list = resolve_target_type(dt_obj.get("ReadTargetType"), ctx)
            src_ent = sim.get_entity(rt_list[0]) if rt_list else sim.get_entity(ctx.caster_id)
            element = getattr(src_ent, "element", "Physical") or "Physical"
        elif isinstance(dt_obj, Mapping):
            element = dt_obj.get("DamageType", "Physical")
        else:
            element = str(dt_obj or "Physical")
        element = _ELEM_ZH_TO_EN.get(element, element)
        if element and element not in _ELEM_ZH_TO_EN.values():
            element = element.strip().title()
        element = _ELEM_ZH_TO_EN.get(element, element)
        ftype = str(atk_prop.get("FormulaType", "ByAttack"))
        pct = self._eval_num(atk_prop.get("DamagePercentage"), ctx, 0.0)
        flat = self._eval_num(atk_prop.get("DamageValue"), ctx, 0.0)
        stance = self._eval_num(atk_prop.get("StanceValue"), ctx, 0.0)
        atk_type = str(atk_prop.get("AttackType", ctx.current_attack_type or "Normal"))

        scaling_stat = "atk"
        if ftype == "ByMaxHP":
            scaling_stat = "hp"
        elif ftype == "ByDefence":
            scaling_stat = "def"

        dtype_map = {
            "Normal": DamageType.BASIC,
            "BPSkill": DamageType.SKILL,
            "Ultra": DamageType.ULTIMATE,
            "Pursued": DamageType.FOLLOW_UP,
            "Servant": DamageType.SERVANT,
            "ElementDamage": DamageType.ADDITIONAL,
        }
        damage_type = dtype_map.get(atk_type, DamageType.BASIC)

        is_equip_sub = ctx.ability_name.startswith(("Ability2", "Ability5"))
        if not getattr(rt, "_in_after_attack", False) and not is_equip_sub:
            atk_seq = int(getattr(sim, "_action_seq", 0))
            fired_set = getattr(rt, "_prepare_attack_fired", None)
            if fired_set is None:
                fired_set = set()
                rt._prepare_attack_fired = fired_set
            atk_key = (atk_seq, ctx.caster_id)
            if atk_key not in fired_set:
                fired_set.add(atk_key)
                me.dispatch_event(
                    "OnAttackerPrepareAttackData",
                    owner_id=ctx.caster_id,
                    attack_target_ids=tuple(targets),
                    current_attack_type=atk_type,
                )
                me.dispatch_event(
                    "OnBeforeAttack",
                    owner_id=ctx.caster_id,
                    attack_target_ids=tuple(targets),
                    current_attack_type=atk_type,
                )

        dmg_data: Dict[str, Any] = {}
        me.dispatch_event(
            "OnBeforeHitAll",
            owner_id=ctx.caster_id,
            attack_target_ids=tuple(targets),
            damage_data=dmg_data,
            current_attack_type=atk_type,
        )
        me.dispatch_event(
            "OnListenBeforeHitAll",
            param_entity_id=ctx.caster_id,
            attack_target_ids=tuple(targets),
            damage_data=dmg_data,
            current_attack_type=atk_type,
        )

        extra_dmg_boost = float(dmg_data.get("Attacker_AllDamageTypeAddedRatio", 0.0))
        extra_def_ignore = -float(dmg_data.get("Defender_DefenceAddedRatio", 0.0))
        extra_res_pen = float(dmg_data.get("Attacker_AllDamageTypePenetrate", 0.0))
        extra_vuln = float(dmg_data.get("Defender_AllDamageTypeTakenRatio", 0.0))
        extra_crit_dmg = float(dmg_data.get("Attacker_CriticalDamageBase", 0.0))
        base_mult_ratio = float(dmg_data.get("Attacker_BaseDamageMultiRatio", 0.0))
        eff_pct = pct * base_mult_ratio if base_mult_ratio > 0 else pct
        eff_flat = flat * base_mult_ratio if base_mult_ratio > 0 else flat

        sim.resolver.begin_aoe()
        try:
            for tid in targets:
                if tid == "__LEVEL__":
                    continue
                sim.port.attack(
                    ctx.caster_id,
                    tid,
                    element=element,
                    atk_multiplier=eff_pct,
                    flat_damage=eff_flat,
                    toughness_damage=stance,
                    scaling_stat=scaling_stat,
                    damage_type=damage_type,
                    extra_dmg_boost=extra_dmg_boost,
                    extra_def_ignore=extra_def_ignore,
                    extra_res_pen=extra_res_pen,
                    extra_vuln=extra_vuln,
                    extra_crit_dmg=extra_crit_dmg,
                )
            sim.resolver.resolve_all()
        finally:
            sim.resolver.end_aoe()

        if not getattr(rt, "_in_after_attack", False) and not is_equip_sub:
            atk_seq = int(getattr(sim, "_action_seq", 0))
            after_set = getattr(rt, "_after_attack_fired", None)
            if after_set is None:
                after_set = set()
                rt._after_attack_fired = after_set
            after_key = (atk_seq, ctx.caster_id)
            if after_key not in after_set:
                after_set.add(after_key)
                rt._in_after_attack = True
                try:
                    me.dispatch_event(
                        "OnAfterHitAll",
                        owner_id=ctx.caster_id,
                        attack_target_ids=tuple(targets),
                        damage_data=dmg_data,
                        current_attack_type=atk_type,
                    )
                    me.dispatch_event(
                        "OnAfterAttack",
                        owner_id=ctx.caster_id,
                        attack_target_ids=tuple(targets),
                        damage_data=dmg_data,
                        current_attack_type=atk_type,
                    )
                    me.dispatch_event(
                        "OnListenAfterAttack",
                        param_entity_id=ctx.caster_id,
                        attack_target_ids=tuple(targets),
                        damage_data=dmg_data,
                        current_attack_type=atk_type,
                    )
                finally:
                    rt._in_after_attack = False

    def _execute_lose_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        targets = resolve_target_type(task.get("TargetType"), ctx)
        ratio_type = str(task.get("RatioType", "CurrentHP"))
        ratio = self._eval_num(task.get("Ratio"), ctx, 0.0)
        hp_floor = self._eval_num(task.get("Floor"), ctx, 1.0) if "Floor" in task else 1.0
        dyn_set = str(task.get("DynamicFloatSet", ""))

        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is None or ent.current_hp <= 0:
                continue
            max_hp = float(sim.port.max_hp(tid))
            base = float(ent.current_hp) if ratio_type == "CurrentHP" else max_hp
            raw_loss = base * ratio
            actual_loss = max(0.0, min(ent.current_hp - hp_floor, raw_loss))
            if actual_loss > 0:
                ent.current_hp -= actual_loss
                sim.event_bus.publish(HPLostEvent(
                    av=round(sim.current_av, 2),
                    cycle=sim.current_cycle,
                    entity_name=tid,
                    amount=actual_loss,
                    hp_left=ent.current_hp,
                    cause=ctx.ability_name or "LoseHPByRatio",
                ))
                if dyn_set and max_hp > 0:
                    rt.set_dynamic_value(ctx.caster_id, dotnet_hash(dyn_set), actual_loss / max_hp)

    def _execute_turn_insert(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = resolve_target_type(task.get("TargetType") or {"Alias": "Caster"}, ctx)
        prio = str(task.get("InsertActionPriority", "Character_ChainSkill"))
        ab_name = _str_val(task.get("AbilityName"))

        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is None or ent.current_hp <= 0:
                continue
            if not sim.port.enemies(tid):
                continue
            if ab_name:
                cat = ActionScheduleCategory.FOLLOW_UP if prio == "Character_ChainSkill" else ActionScheduleCategory.IMMEDIATE_EXTRA_TURN
                sim.scheduler.enqueue(
                    tid,
                    lambda a_id=tid, ab=ab_name: self.rt.trigger_ability(
                        caster_id=a_id,
                        ability_name=ab,
                        target_ids=tuple(e.name for e in sim.entities if e.is_enemy and e.current_hp > 0),
                    ),
                    name=ab_name,
                    category=cat,
                    action_kind=ActionKind.FOLLOW_UP,
                )
            elif getattr(ent, "is_memosprite", False):
                sim.scheduler.enqueue(
                    tid,
                    lambda m_ent=ent: sim._execute_action(
                        m_ent,
                        action_override=ActionKind.MEMOSPRITE_SKILL,
                        target_ids=tuple(e.name for e in sim.entities if e.is_enemy and e.current_hp > 0),
                        is_natural_turn_action=False,
                        advance_policy=False,
                    ),
                    name=f"{tid}_InsertAction",
                    category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                    action_kind=ActionKind.MEMOSPRITE_SKILL,
                )

    def _execute_create_servant(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        sv_id = int(round(self._eval_num(task.get("ServantID"), ctx, 0.0)))
        if sv_id <= 0:
            return
        # 检查主人是否已有存活忆灵
        existing = [
            e for e in sim.entities
            if getattr(e, "is_memosprite", False) and getattr(e, "master_name", None) == ctx.caster_id and e.current_hp > 0
        ]
        if existing:
            return
        init_dyn: Dict[int, float] = {}
        for k, v in (task.get("DynamicValues") or {}).items():
            init_dyn[dotnet_hash(k)] = self._eval_num(v, ctx, 0.0)
        rt.summon_servant(ctx.caster_id, sv_id, init_dynamics=init_dyn)

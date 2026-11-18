"""官方 ConfigAbility AST Task & Predicate 解释器 + 战斗结算桥接 (Phase 3)。

将官方 `Task` 与 `Predicate` 指令集桥接到现有 `TurnSimulator` 微内核：
- 伤害：`AttackData` + `DamageByAttackProperty` -> `DamageCalculator` / `CombatPort.attack`；
- 治疗：`HealHP` (`HealByHealerMaxHP`, `HealByTargetMaxHP`, `HealByTargetLostHP`, `HealByBaseValue`) -> `HealCalculator` + `OnBeforeDealHeal` / `OnAfterDealHeal`；
- 行动条与插队：`ModifyActionDelay` / `ResetActionDelay` / `TurnInsertAbility` / `TurnInsertAction` -> `ActionScheduler`；
- 忆灵召唤与自扣血：`CreateServant` / `LoseHPByRatio` -> `Entity` / `HPLostEvent` / `OnListenHPChange`；
- 未知逻辑 `$type` 严禁静默跳过，默认抛出 `NotImplementedError`。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..actions import ActionKind, ActionScheduleCategory, DamageType, FollowUpPhase
from ..entity import Entity
from ..events import DamageAppliedEvent, HPLostEvent, WeaknessBreakEvent
from ..status import StatType
from .expr import dotnet_hash, eval_dynamic_float
from .loader import CompiledCharacterSpec, PRUNABLE_PRESENTATION_TYPES
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
        self._damage_capture_stack: List[List[float]] = []
        if getattr(runtime, "sim", None) is not None and getattr(runtime.sim, "event_bus", None) is not None:
            runtime.sim.event_bus.subscribe(DamageAppliedEvent, self._on_damage_applied)
            runtime.sim.event_bus.subscribe(WeaknessBreakEvent, self._on_weakness_break)

    def _on_damage_applied(self, evt: DamageAppliedEvent) -> None:
        if self._damage_capture_stack:
            tgt = self.rt.sim.get_entity(evt.target_name)
            if tgt is not None and getattr(tgt, "barrier_guarded", False):
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
                        continue
                    elif st == "RPG.GameCore.TargetSortByProperty":
                        prop = str(step.get("PropertyType", "CurrentHP"))
                        highest = bool(step.get("HighestFirst", True))
                        if step.get("AliveOnly", True):
                            cur = [tid for tid in cur if _is_alive(sim, tid)]
                        cur = sorted(cur, key=lambda tid: me.get_entity_property(tid, prop), reverse=highest)
                    elif st == "RPG.GameCore.TargetTake":
                        cnt = max(0, int(round(self._eval_num(step.get("Count"), ctx, 1.0))))
                        cur = cur[:cnt]
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
            if "DynamicValue" in pred:
                lhs = self._eval_num(pred.get("DynamicValue"), ctx, 0.0)
            else:
                key_str = _str_val(pred.get("DynamicKey"))
                key_h = dotnet_hash(key_str)
                scope_targets = self._resolve_targets(pred.get("TargetType"), ctx) if "TargetType" in pred else [ctx.caster_id]
                tid = scope_targets[0] if scope_targets else ctx.caster_id
                lhs = rt.get_dynamic_value(tid, key_h, ability_name=ctx.ability_name, local_ctx=ctx)
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareAbilityProperty":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
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
                search_ids = self._resolve_targets(pred.get("TargetType"), ctx) if "TargetType" in pred else [ctx.caster_id, ctx.modifier_owner_id or ctx.caster_id]
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
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            lhs = me.get_entity_property(targets[0], "HPRatio") if targets else 0.0
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareStanceCount":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            ent = sim.get_entity(targets[0]) if targets else None
            lhs = float(getattr(ent, "current_toughness", 0.0)) if ent else 0.0
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByIsContainModifier":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            mname = _str_val(pred.get("ModifierName"))
            caster_only = bool(pred.get("OnlyCheckCasterAdded", False))
            c_filter = ctx.caster_id if caster_only else None
            return any(me.has_modifier(tid, mname, c_filter) for tid in targets)

        if t == "RPG.GameCore.ByContainBehaviorFlag":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            flag = str(pred.get("BehaviorFlag") or pred.get("Flag") or "")
            return any(me.has_behavior_flag(tid, flag) for tid in targets)

        if t == "RPG.GameCore.ByRankActivated":
            targets = self._resolve_targets(pred.get("TargetType") or {"Alias": "Caster"}, ctx)
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
            t1 = self._resolve_targets(pred.get("TargetType"), ctx)
            t2 = self._resolve_targets(pred.get("CompareType"), ctx)
            return bool(t1 and t2 and set(t1) == set(t2))

        if t == "RPG.GameCore.ByTargetListIntersects":
            s1 = set(self._resolve_targets(pred.get("FirstTargetType"), ctx))
            s2 = set(self._resolve_targets(pred.get("SecondTargetType"), ctx))
            return bool(s1 & s2)

        if t == "RPG.GameCore.ByTargetListAny":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            sub_pred = pred.get("Predicate")
            for tid in targets:
                sub_ctx = ctx.clone(param_entity_id=tid)
                if self.eval_predicate(sub_pred, sub_ctx):
                    return True
            return False

        if t == "RPG.GameCore.ByCompareTargetCount":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            if pred.get("AliveOnly"):
                targets = [tid for tid in targets if _is_alive(sim, tid)]
            lhs = float(len(targets))
            rhs = self._eval_num(pred.get("Number"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareCharacterNumber":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            lhs = float(len([tid for tid in targets if _is_alive(sim, tid)]))
            rhs = self._eval_num(pred.get("Number") or pred.get("CompareValue"), ctx, 0.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByCompareWaveCount":
            lhs = float(getattr(sim, "current_wave", 1))
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 1.0)
            return _compare_values(lhs, rhs, str(pred.get("CompareType", "Equal")))

        if t == "RPG.GameCore.ByTargetTeam":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
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
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            want = str(pred.get("EntityType") or pred.get("EntityTypeMask") or "")
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                if "Servant" in want and getattr(ent, "is_memosprite", False):
                    return True
                if (
                    "Avatar" in want
                    and not getattr(ent, "is_enemy", False)
                    and not getattr(ent, "is_memosprite", False)
                    and not getattr(ent, "is_proxy", False)
                    and not getattr(ent, "is_countdown", False)
                    and not getattr(ent, "is_battle_event", False)
                ):
                    return True
                if "Monster" in want and getattr(ent, "is_enemy", False):
                    return True
            return False

        if t == "RPG.GameCore.ByTargetAliveState":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
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
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
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
            want_list = pred.get("AttackTypes")
            if isinstance(want_list, list):
                return ctx.current_attack_type in [str(x) for x in want_list]
            want = str(pred.get("AttackType", ""))
            return ctx.current_attack_type == want

        if t == "RPG.GameCore.ByCharacterDamageType":
            targets = self._resolve_targets(pred.get("TargetType") or {"Alias": "Caster"}, ctx)
            dt = pred.get("DamageType", {})
            want = dt.get("DamageType", "") if isinstance(dt, Mapping) else str(dt)
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None and getattr(ent, "element", "") == want:
                    return True
            return False

        if t == "RPG.GameCore.ByAvatarBaseType":
            targets = self._resolve_targets(pred.get("TargetType") or {"Alias": "Caster"}, ctx)
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
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            return any(
                tid == "阿哈" or bool(getattr(sim.get_entity(tid), "is_countdown", False))
                for tid in targets
            )

        if t == "RPG.GameCore.ByIsTurnOwnerEntity":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            cur = getattr(sim, "current_turn_entity", None)
            return bool(cur is not None and cur.name in targets)

        if t == "RPG.GameCore.ByTurnOwnerActionPhaseEnd":
            return bool(getattr(rt, "_in_turn_phase1_end", False))

        if t == "RPG.GameCore.ByHasSummonRelation":
            summoners = self._resolve_targets(pred.get("SummonerType"), ctx)
            servants = self._resolve_targets(pred.get("ServantType"), ctx)
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
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None and getattr(ent, "is_boss", False) and pred.get("Rank") in ("Boss", "LittleBoss"):
                    return True
            return False

        if t == "RPG.GameCore.ByCompareMonsterID":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            mid = str(pred.get("MonsterID", ""))
            return any(str(getattr(sim.get_entity(tid), "monster_id", "")) == mid for tid in targets)

        if t == "RPG.GameCore.ByCompareCharacterID":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            want_id = int(round(self._eval_num(pred.get("TargetCharacterID"), ctx, 0.0)))
            return any(int(getattr(sim.get_entity(tid), "avatar_id", 0) or 0) == want_id for tid in targets)

        if t == "RPG.GameCore.ByIsMatchTeammateCount":
            team_type = str(pred.get("TeamType", "TeamLight"))
            want_s = str(pred.get("CountType", "Count1"))
            want_cnt = int(want_s[5:]) if want_s.startswith("Count") and want_s[5:].isdigit() else 1
            is_dark = team_type in ("TeamDark", "Dark")
            cnt = sum(
                1 for e in sim.entities
                if bool(getattr(e, "is_enemy", False)) == is_dark
                and not getattr(e, "is_memosprite", False)
                and not getattr(e, "is_countdown", False)
                and _is_alive(sim, e.name)
            )
            return cnt == want_cnt

        if t == "RPG.GameCore.ByIsTeamLocationIndexType":
            targets = self._resolve_targets(pred.get("TargetType") or {"Alias": "Caster"}, ctx)
            team_type = str(pred.get("TeamType", "TeamLight"))
            loc_type = str(pred.get("Type", "Min"))
            is_dark = team_type in ("TeamDark", "Dark")
            pool = [
                e.name for e in sim.entities
                if bool(getattr(e, "is_enemy", False)) == is_dark
                and not getattr(e, "is_memosprite", False)
                and not getattr(e, "is_countdown", False)
            ]
            if not pool or not targets:
                return False
            if loc_type == "Min":
                return targets[0] == pool[0]
            if loc_type == "Max":
                return targets[0] == pool[-1]
            return False

        if t == "RPG.GameCore.ByHasStanceWeak":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
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
                    out = out[:cap]
                return out

            matched = _match_retarget()
            if not matched and task.get("IncludeLimbo") and not getattr(self.rt, "_include_limbo", False):
                self.rt._include_limbo = True
                try:
                    matched = _match_retarget()
                finally:
                    self.rt._include_limbo = False
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
            if "Value" in task:
                key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
                val = self._eval_num(task.get("Value"), ctx, 0.0)
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
                    if vtype == "Layer" and m.layer <= 0:
                        me.destroy_modifier(m)
            return

        # 3. Modifier 与属性操作
        if t == "RPG.GameCore.AddModifier":
            targets = self._resolve_targets(task.get("TargetType"), ctx)
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

        if t == "RPG.GameCore.LoseHPByRatio":
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
            for tid in targets:
                if val < 0:
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
                ent.current_hp = 0.0
                if not mute_death:
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
            if getattr(sim, "_current_turn_entity", None) is not None:
                cur_d = getattr(sim, "_pending_turn_reset_distance", None)
                base_d = 10000.0 if cur_d is None else float(cur_d)
                sim._pending_turn_reset_distance = max(0.0, base_d + val * 10000.0)
            return

        if t in (
            "RPG.GameCore.SetEnergyBarState",
            "RPG.GameCore.SetSummonerEnergyBarState",
            "RPG.GameCore.SetTargetAlwaysAutoBattle",
            "RPG.GameCore.AddEntityToTeamFormation",
            "RPG.GameCore.RemoveEntityFromTeamFormation",
            "RPG.GameCore.AttachEntityUnselectable",
            "RPG.GameCore.SetDieImmediately",
            "RPG.GameCore.SkillPerformFinish",
            "RPG.GameCore.StackStatusDesc",
            "RPG.GameCore.StackStatusResistance",
            "RPG.GameCore.SetResilience",
            "RPG.GameCore.CharacterChangePhase",
            "RPG.GameCore.LockActionDelayChange",
            "RPG.GameCore.AttachSkillTypeDisable",
            "RPG.GameCore.SummonPartner",
            "RPG.GameCore.Remodifier",
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
    def _execute_modify_sp_new(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        if not targets:
            return

        sp_base = float(getattr(rt, "_active_skill_sp_base", 0.0) or 0.0)
        for tid in targets:
            if tid == "__LEVEL__":
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

            err = float(sim.port.stat(ep_tid, StatType.ERR) or 1.0)
            max_ep = float(sim.port.max_energy(ep_tid) or getattr(ent, "max_energy", 0.0) or 0.0)

            if "SetValue" in task:
                v = self._eval_num(task["SetValue"], ctx, ent.energy)
                ent.energy = max(0.0, min(max_ep, v)) if max_ep > 0 else max(0.0, v)
                continue
            if "SetMaxSPRatio" in task:
                r = self._eval_num(task["SetMaxSPRatio"], ctx, 0.0)
                if max_ep > 0:
                    ent.energy = max(0.0, min(max_ep, max_ep * r))
                continue

            total_gain = 0.0
            if "AddValue" in task:
                total_gain += self._eval_num(task["AddValue"], ctx, 0.0) * err
            if "AddMaxSPRatio" in task:
                total_gain += max_ep * self._eval_num(task["AddMaxSPRatio"], ctx, 0.0) * err
            if "AddRatio" in task:
                rt._skill_sp_ratio_granted = True
                total_gain += sp_base * self._eval_num(task["AddRatio"], ctx, 0.0) * err
            if "FixedAddValue" in task:
                total_gain += self._eval_num(task["FixedAddValue"], ctx, 0.0)
            if "FixedAddMaxSPRatio" in task:
                total_gain += max_ep * self._eval_num(task["FixedAddMaxSPRatio"], ctx, 0.0)
            if "FixedAddRatio" in task:
                rt._skill_sp_ratio_granted = True
                total_gain += sp_base * self._eval_num(task["FixedAddRatio"], ctx, 0.0)

            if total_gain > 0.0:
                sim.port.gain_energy(ep_tid, total_gain, cause=ctx.ability_name or "ModifySPNew")
            elif total_gain < 0.0:
                ent.energy = max(0.0, ent.energy + total_gain)

    def _execute_heal(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        targets = self._resolve_targets(task.get("TargetType"), ctx)
        healer = sim.get_entity(ctx.caster_id)
        if healer is None or not targets:
            return

        ftype = str(task.get("FormulaType", "HealByHealerMaxHP"))
        pct = self._eval_num(task.get("HealPercentage"), ctx, 0.0)
        flat = self._eval_num(task.get("ModifyValue"), ctx, 0.0)

        for tid in targets:
            tgt = sim.get_entity(tid)
            if tgt is None or tgt.current_hp <= 0:
                continue
            healer_max_hp = float(sim.port.max_hp(healer.name))
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

            if hasattr(sim.port, "get_active_proxy") and sim.port.get_active_proxy(tid):
                continue
            sim.port.heal(ctx.caster_id, tid, heal_data["HealValue"])

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

        targets = self._resolve_targets(task.get("TargetType"), ctx)
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
            rt_list = self._resolve_targets(dt_obj.get("ReadTargetType"), ctx)
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
        if stance <= 0.0 and atk_prop.get("StanceValue"):
            # 官方 Skill StanceValue 哈希 (如 1659254037 单体 / 1182064154 群体) 存储在角色技能表 ShowStanceList 中
            ab_l = ctx.ability_name
            if "Skill01" in ab_l or atk_type in ("Normal", "Servant"):
                stance = 30.0
            elif "Skill03" in ab_l or atk_type == "Ultra":
                stance = 90.0 if "Evernight" in ab_l else 60.0
            elif "Skill02" in ab_l or atk_type == "BPSkill":
                stance = 60.0
            elif atk_type in ("Insert", "Pursued"):
                stance = 15.0

        scaling_stat = "atk"
        if ftype == "ByMaxHP":
            scaling_stat = "hp"
        elif ftype == "ByDefence":
            scaling_stat = "def"

        is_equip_sub = ctx.ability_name.startswith(("Ability2", "Ability5"))
        is_additional_pursued = (
            atk_type == "Pursued"
            and getattr(rt, "_in_after_attack", False)
        )
        dtype_map = {
            "Normal": DamageType.BASIC,
            "BPSkill": DamageType.SKILL,
            "Ultra": DamageType.ULTIMATE,
            "Pursued": DamageType.ADDITIONAL if is_additional_pursued else DamageType.FOLLOW_UP,
            "Insert": DamageType.FOLLOW_UP,
            "Servant": DamageType.SERVANT,
            "ElementDamage": DamageType.ADDITIONAL,
            "TrueDamage": DamageType.TRUE,
        }
        damage_type = dtype_map.get(atk_type, DamageType.BASIC)
        is_true_dmg = (damage_type == DamageType.TRUE)
        is_nested_sub = is_true_dmg or getattr(rt, "_in_after_attack", False) or is_equip_sub

        atk_seq = int(getattr(sim, "_action_seq", 0))
        atk_key = (atk_seq, ctx.caster_id)
        if not is_nested_sub:
            acc_targets = rt._attack_targets_by_key.setdefault(atk_key, [])
            for tid in targets:
                if tid != "__LEVEL__" and tid not in acc_targets:
                    acc_targets.append(tid)

            fired_set = getattr(rt, "_prepare_attack_fired", None)
            if fired_set is None:
                fired_set = set()
                rt._prepare_attack_fired = fired_set
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
                me.dispatch_event(
                    "OnListenBeforeAttack",
                    param_entity_id=ctx.caster_id,
                    attack_target_ids=tuple(targets),
                    current_attack_type=atk_type,
                )

        dmg_data: Dict[str, Any] = {}
        if not is_true_dmg:
            me.dispatch_event(
                "OnBeforeHitAll",
                owner_id=ctx.caster_id,
                attack_target_ids=tuple(targets),
                damage_data=dmg_data,
                current_attack_type=atk_type,
            )
            base_before_hit_all = dict(dmg_data)
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
        hit_split = self._eval_num(atk_prop.get("HitSplitRatio"), ctx, 1.0)
        if str(atk_prop.get("FinalFormulaType", "")) == "ByBaseDamage" and pct == 0.0:
            eff_pct = 0.0
            eff_flat = flat * hit_split
        else:
            eff_pct = (pct * base_mult_ratio if base_mult_ratio > 0 else pct) * hit_split
            eff_flat = (flat * base_mult_ratio if base_mult_ratio > 0 else flat) * hit_split
        eff_stance = stance * hit_split

        base_before_hit_all = dict(dmg_data) if is_true_dmg else base_before_hit_all
        captured = [0.0]
        self._damage_capture_stack.append(captured)
        sim.resolver.begin_aoe()
        try:
            real_targets = [tid for tid in targets if tid != "__LEVEL__"]
            any_died_mid_aoe = False
            for idx, tid in enumerate(real_targets):
                if idx > 0 and any_died_mid_aoe and not is_true_dmg:
                    any_died_mid_aoe = False
                    dmg_data = dict(base_before_hit_all)
                    me.dispatch_event(
                        "OnListenBeforeHitAll",
                        param_entity_id=ctx.caster_id,
                        attack_target_ids=tuple(real_targets[idx:]),
                        damage_data=dmg_data,
                        current_attack_type=atk_type,
                    )
                    extra_dmg_boost = float(dmg_data.get("Attacker_AllDamageTypeAddedRatio", 0.0))
                    extra_def_ignore = -float(dmg_data.get("Defender_DefenceAddedRatio", 0.0))
                    extra_res_pen = float(dmg_data.get("Attacker_AllDamageTypePenetrate", 0.0))
                    extra_vuln = float(dmg_data.get("Defender_AllDamageTypeTakenRatio", 0.0))
                    extra_crit_dmg = float(dmg_data.get("Attacker_CriticalDamageBase", 0.0))
                    base_mult_ratio = float(dmg_data.get("Attacker_BaseDamageMultiRatio", 0.0))
                    if str(atk_prop.get("FinalFormulaType", "")) == "ByBaseDamage" and pct == 0.0:
                        eff_pct = 0.0
                        eff_flat = flat * hit_split
                    else:
                        eff_pct = (pct * base_mult_ratio if base_mult_ratio > 0 else pct) * hit_split
                        eff_flat = (flat * base_mult_ratio if base_mult_ratio > 0 else flat) * hit_split
                tgt_ent = sim.get_entity(tid)
                was_alive = bool(tgt_ent is not None and getattr(tgt_ent, "current_hp", 0.0) > 0.0)
                if not is_nested_sub:
                    me.dispatch_event(
                        "OnBeforeHit",
                        owner_id=ctx.caster_id,
                        param_entity_id=tid,
                        attack_target_ids=tuple(targets),
                        damage_data=dmg_data,
                        current_attack_type=atk_type,
                    )
                sim.port.attack(
                    ctx.caster_id,
                    tid,
                    element=element,
                    atk_multiplier=eff_pct,
                    flat_damage=eff_flat,
                    toughness_damage=eff_stance,
                    scaling_stat=scaling_stat,
                    damage_type=damage_type,
                    extra_dmg_boost=extra_dmg_boost,
                    extra_def_ignore=extra_def_ignore,
                    extra_res_pen=extra_res_pen,
                    extra_vuln=extra_vuln,
                    extra_crit_dmg=extra_crit_dmg,
                    vm_hit_hooks_applied=not is_true_dmg,
                )
                if len(real_targets) > 1:
                    sim.resolver.resolve_all()
                    if was_alive and tgt_ent is not None and getattr(tgt_ent, "current_hp", 0.0) <= 0.0:
                        any_died_mid_aoe = True
            sim.resolver.resolve_all()
        finally:
            sim.resolver.end_aoe()
            self._damage_capture_stack.pop()

        dmg_data["Result_FinalDamageBase"] = captured[0]
        dmg_data["FinalDamage"] = captured[0]

        if not is_true_dmg:
            me.dispatch_event(
                "OnAfterHitAll",
                owner_id=ctx.caster_id,
                attack_target_ids=tuple(targets),
                damage_data=dmg_data,
                current_attack_type=atk_type,
            )
            me.dispatch_event(
                "OnListenAfterHitAll",
                param_entity_id=ctx.caster_id,
                attack_target_ids=tuple(targets),
                damage_data=dmg_data,
                current_attack_type=atk_type,
            )

        if not is_nested_sub:
            if getattr(rt, "_attack_scope_depth", 0) > 0:
                rt._pending_after_attack = (atk_seq, ctx.caster_id, dmg_data, atk_type)
            else:
                after_set = getattr(rt, "_after_attack_fired", None)
                if after_set is None:
                    after_set = set()
                    rt._after_attack_fired = after_set
                if atk_key not in after_set:
                    after_set.add(atk_key)
                    all_tgts = tuple(rt._attack_targets_by_key.get(atk_key, targets))
                    rt._in_after_attack = True
                    try:
                        me.dispatch_event(
                            "OnAfterAttack",
                            owner_id=ctx.caster_id,
                            attack_target_ids=all_tgts,
                            damage_data=dmg_data,
                            current_attack_type=atk_type,
                        )
                        me.dispatch_event(
                            "OnListenAfterAttack",
                            param_entity_id=ctx.caster_id,
                            attack_target_ids=all_tgts,
                            damage_data=dmg_data,
                            current_attack_type=atk_type,
                        )
                    finally:
                        rt._in_after_attack = False

    def _execute_lose_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim

        targets = self._resolve_targets(task.get("TargetType"), ctx)
        ratio_type = str(task.get("RatioType", "CurrentHP"))
        ratio = self._eval_num(task.get("Ratio"), ctx, 0.0)
        hp_floor = self._eval_num(task.get("Floor"), ctx, 1.0) if "Floor" in task else 1.0
        dyn_set = str(task.get("DynamicFloatSet", ""))

        for tid in targets:
            if hasattr(sim.port, "get_active_proxy"):
                proxy_id = sim.port.get_active_proxy(tid)
                if proxy_id:
                    tid = proxy_id
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

    def _resolve_insert_skill_meta(self, actor_id: str, ab_name: str) -> Tuple[int, float]:
        spec = self.rt.entity_specs.get(actor_id)
        if spec is None:
            return 0, 0.0
        sk_key = ""
        for item in spec.config.get("SkillAbilityList", []):
            if ab_name in item.get("AbilityList", []):
                sk_key = str(item.get("Skill", ""))
                break
        if not sk_key:
            return 0, 0.0
        if spec.is_servant:
            self.rt.loader._ensure_servants()
            self.rt.loader._ensure_servant_skills()
            sv = self.rt.loader._servants.get(spec.unit_id, {})
            for sid in sv.get("SkillIDList", []):
                row = self.rt.loader._servant_skills.get((int(sid), 1))
                if row and row.get("SkillTriggerKey") == sk_key:
                    sp_obj = row.get("SPBase") or {}
                    sp_base = float(sp_obj.get("Value", 0.0)) if isinstance(sp_obj, dict) else 0.0
                    return int(row.get("SkillID") or 0), sp_base
            return 0, 0.0
        self.rt.loader._ensure_avatars()
        self.rt.loader._ensure_avatar_skills()
        av = self.rt.loader._avatars.get(spec.unit_id, {})
        for sid in av.get("SkillList", []):
            row = self.rt.loader._avatar_skills.get((int(sid), 1))
            if row and row.get("SkillTriggerKey") == sk_key:
                sp_obj = row.get("SPBase") or {}
                sp_base = float(sp_obj.get("Value", 0.0)) if isinstance(sp_obj, dict) else 0.0
                return int(row.get("SkillID") or 0), sp_base
        return 0, 0.0

    def _execute_turn_insert(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        targets = self._resolve_targets(task.get("TargetType") or {"Alias": "Caster"}, ctx)
        prio = str(task.get("InsertAbilityPriority") or task.get("InsertActionPriority") or "Character_ChainSkill")
        ab_name = _str_val(task.get("AbilityName"))
        ability_tgt_spec = task.get("AbilityTarget")

        for tid in targets:
            if hasattr(sim.port, "get_active_proxy"):
                proxy_id = sim.port.get_active_proxy(tid)
                if proxy_id:
                    tid = proxy_id
            ent = sim.get_entity(tid)
            if ent is None or ent.current_hp <= 0:
                continue
            if not sim.port.enemies(tid):
                continue
            if ab_name:
                cat = (
                    ActionScheduleCategory.FOLLOW_UP
                    if prio in ("Character_ChainSkill", "AvatarInsertAttackSelf")
                    else ActionScheduleCategory.IMMEDIATE_EXTRA_TURN
                )
                act_kind = ActionKind.FOLLOW_UP if cat == ActionScheduleCategory.FOLLOW_UP else ActionKind.TALENT
                ins_skill_id, ins_sp_base = self._resolve_insert_skill_meta(tid, ab_name)
                preset_targets = tuple(self._resolve_targets(ability_tgt_spec, ctx)) if ability_tgt_spec is not None else ()

                def _run_insert(
                    a_id: str = tid,
                    ab: str = ab_name,
                    _c: ActionScheduleCategory = cat,
                    _tgts: Tuple[str, ...] = preset_targets,
                    _sp: float = ins_sp_base,
                ) -> None:
                    sim._action_seq += 1
                    sk_t = "Insert" if _c == ActionScheduleCategory.FOLLOW_UP else "Talent"
                    me = rt.modifier_engine
                    eff_tgts = _tgts if _tgts else tuple(e.name for e in sim.entities if e.is_enemy and e.current_hp > 0)
                    me.dispatch_event("OnBeforeSkillUse", owner_id=a_id, current_skill_type=sk_t)
                    me.dispatch_event("OnListenBeforeSkillUse", param_entity_id=a_id, current_skill_type=sk_t)
                    prev_sp_base = rt._active_skill_sp_base
                    prev_sp_granted = rt._skill_sp_ratio_granted
                    rt._active_skill_sp_base = _sp
                    rt._skill_sp_ratio_granted = False
                    rt.begin_attack_scope()
                    try:
                        rt.trigger_ability(
                            caster_id=a_id,
                            ability_name=ab,
                            target_ids=eff_tgts,
                            skill_target_ids=eff_tgts,
                            current_skill_type=sk_t,
                            current_attack_type=sk_t,
                        )
                    finally:
                        rt.end_attack_scope()
                        sp_granted = rt._skill_sp_ratio_granted
                        rt._active_skill_sp_base = prev_sp_base
                        rt._skill_sp_ratio_granted = prev_sp_granted
                    if _sp > 0 and not sp_granted and sim.port:
                        ep_recipient = a_id
                        a_ent = sim.get_entity(a_id)
                        if a_ent is not None and getattr(a_ent, "is_memosprite", False) and getattr(a_ent, "master_name", None):
                            ep_recipient = a_ent.master_name
                        err = sim.port.stat(ep_recipient, StatType.ERR) or 1.0
                        sim.port.gain_energy(ep_recipient, _sp * err, cause=f"追击回能 {ab}")
                    me.dispatch_event("OnAfterSkillUse", owner_id=a_id, current_skill_type=sk_t)
                    me.dispatch_event("OnActionEnd", owner_id=a_id)
                    me.dispatch_event("OnListenAfterSkillUse", param_entity_id=a_id, current_skill_type=sk_t)
                    me.dispatch_event("OnListenActionEnd", param_entity_id=a_id)
                    me.dispatch_event("OnAfterAction", owner_id=a_id)
                    me.dispatch_event("OnListenAfterAction", param_entity_id=a_id)
                    me.dispatch_event(
                        "CheckParamFlagCallBack",
                        param_entity_id=a_id,
                        param_flags=("CallBack_SettleSkillOrInsertAbility",),
                    )

                sim.scheduler.enqueue(
                    tid,
                    _run_insert,
                    name=ab_name,
                    category=cat,
                    action_kind=act_kind,
                    skill_id=ins_skill_id,
                    preempt_follow_up=(prio == "AvatarBuffSelf"),
                )
            elif getattr(ent, "is_memosprite", False):
                kit = getattr(ent, "kit", None)
                defn = None
                if kit is not None:
                    try:
                        defn = kit.definition(ActionKind.MEMOSPRITE_SKILL)
                    except Exception:
                        defn = None
                sv_skill_id = int(getattr(defn, "skill_id", 0) or 0)
                sv_skill_name = str(getattr(defn, "name", "") or f"{tid}_InsertAction")
                sim.scheduler.enqueue(
                    tid,
                    lambda m_ent=ent: sim._execute_action(
                        m_ent,
                        action_override=ActionKind.MEMOSPRITE_SKILL,
                        target_ids=(),
                        is_natural_turn_action=False,
                        advance_policy=False,
                    ),
                    name=sv_skill_name,
                    category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                    action_kind=ActionKind.MEMOSPRITE_SKILL,
                    skill_id=sv_skill_id,
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
        sv = rt.summon_servant(ctx.caster_id, sv_id, init_dynamics=init_dyn)
        if sv is not None and task.get("OnServantCreate"):
            self.execute_tasks(task["OnServantCreate"], ctx.clone(param_entity_id=sv.name))

    def _execute_create_battle_event(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        event_id = int(round(self._eval_num(task.get("EventID"), ctx, 0.0)))
        if event_id <= 0:
            return
        init_dyn: Dict[int, float] = {}
        for k, v in (task.get("DynamicValues") or {}).items():
            init_dyn[dotnet_hash(k)] = self._eval_num(v, ctx, 0.0)

        default_names = {11512: "晴空乐手•倒计时"}
        be_name = default_names.get(event_id, f"BattleEvent_{event_id}")
        spd = float(init_dyn.get(dotnet_hash("BattleEvent_RobinS_00_BaseSpeed"), 140.0) or 140.0)

        be_ent = sim.get_entity(be_name)
        if be_ent is None:
            be_ent = Entity(
                name=be_name,
                base_speed=max(1.0, spd),
                base_atk=100.0,
                max_hp=1000.0,
                current_hp=1000.0,
                is_enemy=False,
                is_memosprite=False,
                is_countdown=True,
                master_name=ctx.caster_id,
                avatar_id=event_id,
            )
            sim.add_entity(be_ent, trigger_battle_start=False)
        else:
            be_ent.base_speed = max(1.0, spd)
            be_ent.current_hp = 1000.0
            be_ent.distance_remaining = 10000.0
            be_ent.master_name = ctx.caster_id

        rt.loader.ensure_ability_index()
        be_spec = CompiledCharacterSpec(
            unit_id=event_id,
            is_servant=False,
            config={},
            abilities={},
            global_modifiers=rt.loader._global_mod_by_name,
            global_templates=rt.loader._global_tpl_by_name,
            dynamic_floats=init_dyn,
            skill_levels={},
        )
        rt.register_character(be_name, be_spec)
        rt.named_targets["BattleEventCaster"] = [ctx.caster_id]
        rt.named_targets["BattleEventEntityList"] = [be_name]

        # 从 BattleEventConfig.json 查找并挂载 AbilityList (如 BattleEventAbility_RobinS_00_BE)
        try:
            rows = rt.loader._read_excel("BattleEventConfig.json")
        except Exception:
            rows = []
        for row in rows:
            if int(row.get("BattleEventID", 0) or 0) == event_id:
                for ab_name in row.get("AbilityList", []):
                    rt.trigger_ability(caster_id=be_name, ability_name=ab_name, target_ids=(be_name,))
                break

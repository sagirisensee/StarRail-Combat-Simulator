# coding: utf-8
"""ConfigAbility VM Predicate 求值算子 Mixin（从 executor.py 拆分）。"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..expr import dotnet_hash
from ..target_alias import ExecutionContext


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
    if e is None or getattr(e, "_vm_limbo_pending", False):
        return False
    return bool(getattr(e, "current_hp", 0.0) > 0 or getattr(e, "is_infinite_hp", False))


class PredicateOpsMixin:
    """官方 ConfigAbility Predicate 求值器 Mixin。"""

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
            if pred.get("AliveOnly", True):
                targets = [tid for tid in targets if _is_alive(sim, tid)]
            sub_pred = pred.get("Predicate")
            if sub_pred:
                targets = [tid for tid in targets if self.eval_predicate(sub_pred, ctx.clone(param_entity_id=tid))]
            lhs = float(len(targets))
            rhs_spec = pred.get("CompareNumber")
            if rhs_spec is None:
                rhs_spec = pred.get("Number") if "Number" in pred else pred.get("CompareValue")
            rhs = self._eval_num(rhs_spec, ctx, 0.0)
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
                bool(getattr(sim.get_entity(tid), "is_countdown", False))
                or bool(getattr(sim.get_entity(tid), "is_battle_event", False))
                or tid == "阿哈"
                for tid in targets
            )

        if t == "RPG.GameCore.ByIsTurnOwnerEntity":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            cur = getattr(sim, "current_turn_entity", None)
            return bool(cur is not None and cur.name in targets)

        if t == "RPG.GameCore.ByTurnOwnerActionPhaseEnd":
            return bool(getattr(rt, "_in_turn_phase1_end", False))

        if t == "RPG.GameCore.ByHasSummonRelation":
            summoners = set(self._resolve_targets(pred.get("SummonerType"), ctx))
            servants = self._resolve_targets(pred.get("ServantType"), ctx)
            for sv in servants:
                ent = sim.get_entity(sv)
                if ent is not None:
                    owner = getattr(ent, "summoner_name", None) or getattr(ent, "master_name", None)
                    if owner in summoners:
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
            rank_to_num = {
                "Minion": 1,
                "MinionLv2": 2,
                "Elite": 3,
                "LittleBoss": 4,
                "BigBoss": 5,
                "Boss": 5,
            }
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            cmp_val = pred.get("CompareValue")
            cmp_type = str(pred.get("CompareType", "Equal"))
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                if cmp_val is not None:
                    ent_rank_str = ""
                    if runner is not None:
                        try:
                            ent_rank_str = str(runner.get_enemy_state(tid).blueprint.rank)
                        except KeyError:
                            pass
                    if not ent_rank_str:
                        ent_rank_str = "LittleBoss" if getattr(ent, "is_boss", False) else "MinionLv2"
                    lhs = float(rank_to_num.get(ent_rank_str, 0))
                    rhs = float(cmp_val) if isinstance(cmp_val, (int, float)) else self._eval_num(cmp_val, ctx, 0.0)
                    if _compare_values(lhs, rhs, cmp_type):
                        return True
                elif getattr(ent, "is_boss", False) and pred.get("Rank") in ("Boss", "LittleBoss"):
                    return True
            return False

        if t == "RPG.GameCore.ByCompareMonsterPhase":
            targets = self._resolve_targets(pred.get("TargetType"), ctx) or ([ctx.caster_id] if ctx.caster_id else [])
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            rhs = self._eval_num(pred.get("CompareValue"), ctx, 1.0)
            cmp_type = str(pred.get("CompareType", "Equal"))
            for tid in targets:
                phase = 1.0
                if runner is not None:
                    try:
                        phase = float(runner.get_enemy_state(tid).phase)
                    except KeyError:
                        pass
                if _compare_values(phase, rhs, cmp_type):
                    return True
            return False

        if t == "RPG.GameCore.ByCompareStageType":
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            cur_st = str(getattr(getattr(runner, "built_stage", None), "stage_type", "")) if runner is not None else ""
            want_st = str(pred.get("StageType", ""))
            return bool(cur_st and want_st and cur_st == want_st)

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

        if t == "RPG.GameCore.ByCheckCustomValueBool":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            key_raw = pred.get("Key", "")
            key_str = str(key_raw.get("Value", "") if isinstance(key_raw, Mapping) else key_raw)
            expected = bool(pred.get("ExpectedValue", True))
            if not targets:
                return False
            h = dotnet_hash(key_str)
            val = bool(self.rt.get_dynamic_value(targets[0], h))
            return val == expected

        if t == "NDFKINKPKHF":
            return False

        if t == "RPG.GameCore.ByCompareMonsterTemplateID":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            want = int(round(self._eval_num(pred.get("TemplateID") or pred.get("MonsterTemplateID"), ctx, 0.0)))
            return any(int(getattr(sim.get_entity(tid), "monster_template_id", 0)) == want for tid in targets)

        if t == "RPG.GameCore.ByIsCharacterChangeTarget":
            targets = self._resolve_targets(pred.get("TargetType"), ctx)
            return any(bool(getattr(sim.get_entity(tid), "_is_avatar_change_target", False)) for tid in targets)

        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None and hasattr(runner, "eval_stage_predicate"):
            try:
                return bool(
                    runner.eval_stage_predicate(
                        pred,
                        caster_name=ctx.caster_id,
                        param_entity_name=ctx.param_entity_id,
                        dynamic_resolver=lambda h: self.rt.resolve_hash(
                            ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx
                        ),
                    )
                )
            except NotImplementedError:
                pass

        if self.strict:
            raise NotImplementedError(f"未实现的 Predicate 类型: {t}")
        return False

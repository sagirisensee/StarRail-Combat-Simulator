# coding: utf-8
"""ConfigAbility VM 回合插队、召唤、关卡事件与角色变身算子 Mixin。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...actions import AbilityDefinition, ActionKind, ActionScheduleCategory, ResourceCost, TargetMode
from ...entity import Entity
from ...events import ActionExecuteEvent
from ...lifecycle import AbilityFrameSpec, emit_sim_event, increment_deathrattle_actions
from ...status import StatType
from ..expr import dotnet_hash
from ..loader import CompiledCharacterSpec
from ..target_alias import ExecutionContext
from .predicates import _str_val


class TurnOpsMixin:
    """TurnInsertAbility / CreateServant / CreateBattleEvent / AttachAvatarChange 算子实现。"""

    def _resolve_dynamic_strings(self, raw_strs: Any, ctx: ExecutionContext) -> Dict[str, str]:
        out: Dict[str, str] = {}
        if not isinstance(raw_strs, Mapping):
            return out
        ent_strs = getattr(self.rt, "entity_dynamic_strings", {}).get(ctx.caster_id, {})
        for k, v in raw_strs.items():
            if isinstance(v, Mapping) and v.get("Custom"):
                ck = str(v.get("Key") or "")
                out[str(k)] = str(ctx.custom_strings.get(ck, ent_strs.get(ck, "")))
            elif isinstance(v, Mapping):
                raw_v = v.get("Value") if "Value" in v else v.get("RawString", "")
                raw_s = str(raw_v or "")
                out[str(k)] = str(ctx.custom_strings.get(raw_s, ent_strs.get(raw_s, raw_s)))
            elif v is not None:
                out[str(k)] = str(v)
        return out

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
        cond_prio = task.get("InsertConditionPriority")
        override_prio = cond_prio.get("OverridePriority") if isinstance(cond_prio, Mapping) else None
        prio = str(
            task.get("InsertAbilityPriority")
            or task.get("InsertActionPriority")
            or "Character_ChainSkill"
        )
        if override_prio:
            cond_pred = cond_prio.get("Predicate")
            if cond_pred is None or self.eval_predicate(cond_pred, ctx):
                prio = str(override_prio)
        ab_name = _str_val(task.get("AbilityName"))
        if task.get("TargetType") is not None:
            targets = self._resolve_targets(task.get("TargetType"), ctx)
        elif ctx.modifier_owner_id and (
            prio.startswith("Monster")
            or "Limbo" in str(task.get("OwnerAliveState", ""))
            or (
                ctx.caster_id
                and (sim.get_entity(ctx.caster_id) is None or getattr(sim.get_entity(ctx.caster_id), "current_hp", 0.0) <= 0.0)
            )
        ):
            targets = [ctx.modifier_owner_id]
        else:
            targets = self._resolve_targets({"Alias": "Caster"}, ctx)
        ability_tgt_spec = task.get("AbilityTarget")

        for tid in targets:
            is_level_caster = (tid == "__LEVEL__")
            if not is_level_caster and hasattr(sim.port, "get_active_proxy"):
                proxy_id = sim.port.get_active_proxy(tid)
                if proxy_id:
                    tid = proxy_id
            ent = None if is_level_caster else sim.get_entity(tid)
            allow_limbo = "Limbo" in str(task.get("OwnerAliveState", "")) or str(task.get("OwnerAliveState", "")) == "Anyone"
            if not is_level_caster and (ent is None or (ent.current_hp <= 0 and not allow_limbo)):
                continue
            if ent is not None and getattr(ent, "_avatar_change_target_id", None) is not None and not getattr(ent, "is_enemy", False):
                continue
            is_enemy_caster = bool(ent is not None and getattr(ent, "is_enemy", False))
            can_run_unselectable = bool(task.get("CanRunOnUnselectableTarget", False))
            if not is_level_caster and not is_enemy_caster and not can_run_unselectable and not sim.port.enemies(tid):
                continue
            if ab_name:
                pre_check = task.get("PreCheck")
                if isinstance(pre_check, Mapping) and pre_check.get("Type") == "AbilityOwnerInsertUnusedCount":
                    max_unused = int(round(self._eval_num(pre_check.get("Count"), ctx, 1.0)))
                    if sim.scheduler.count_pending_actions(tid, ab_name) >= max_unused:
                        continue
                cat = (
                    ActionScheduleCategory.FOLLOW_UP
                    if prio in ("Character_ChainSkill", "AvatarInsertAttackSelf", "MonsterBuffOthers")
                    else ActionScheduleCategory.IMMEDIATE_EXTRA_TURN
                )
                act_kind = ActionKind.FOLLOW_UP if cat == ActionScheduleCategory.FOLLOW_UP else ActionKind.TALENT
                ins_skill_id, ins_sp_base = (0, 0.0) if is_level_caster else self._resolve_insert_skill_meta(tid, ab_name)
                preset_targets = tuple(self._resolve_targets(ability_tgt_spec, ctx)) if ability_tgt_spec is not None else ()
                raw_dyn = task.get("DynamicValues")
                insert_dyn: Dict[int, float] = (
                    {dotnet_hash(str(k)): self._eval_num(v, ctx, 0.0) for k, v in raw_dyn.items()}
                    if isinstance(raw_dyn, Mapping)
                    else {}
                )
                active_pred = task.get("ActivePredicate")
                pred_ctx = ctx.clone()

                _is_limbo_insert = ent is not None and (
                    prio in ("MonsterDeathRattle", "MonsterForceKill")
                    or (
                        getattr(ent, "_in_deathrattle_limbo", False)
                        and (prio.startswith("MonsterBuffOthers") or "Limbo" in str(task.get("OwnerAliveState", "")))
                    )
                )
                if _is_limbo_insert:
                    increment_deathrattle_actions(ent)

                def _run_insert(
                    a_id: str = tid,
                    ab: str = ab_name,
                    _c: ActionScheduleCategory = cat,
                    _tgts: Tuple[str, ...] = preset_targets,
                    _sp: float = ins_sp_base,
                    _is_en: bool = is_enemy_caster,
                    _prio: str = prio,
                    _dyn: Dict[int, float] = insert_dyn,
                    _active_pred: Any = active_pred,
                    _pred_ctx: ExecutionContext = pred_ctx,
                ) -> None:
                    try:
                        if isinstance(_active_pred, Mapping) and not self.eval_predicate(_active_pred, _pred_ctx):
                            ab_doc = rt.loader.get_ability(ab)
                            if ab_doc and ab_doc.get("OnInsertAbort"):
                                self.execute_tasks(
                                    ab_doc["OnInsertAbort"],
                                    _pred_ctx.clone(caster_id=a_id, ability_name=ab),
                                )
                            return
                        sim._action_seq += 1
                        sk_t = "Insert" if _c == ActionScheduleCategory.FOLLOW_UP else "Talent"
                        if _tgts:
                            eff_tgts = _tgts
                        elif _is_en:
                            eff_tgts = tuple(
                                e.name for e in sim.entities
                                if not e.is_enemy and not getattr(e, "is_countdown", False) and e.current_hp > 0
                            )
                        else:
                            eff_tgts = tuple(
                                e.name
                                for e in sim.entities
                                if e.is_enemy and (e.current_hp > 0 or getattr(e, "_in_deathrattle_limbo", False))
                            )
                        rt.lifecycle.run_ability_frame(
                            AbilityFrameSpec(
                                caster_id=a_id,
                                ability_name=ab,
                                target_ids=eff_tgts,
                                skill_target_ids=eff_tgts,
                                skill_type=sk_t,
                                attack_type=sk_t,
                                sp_base=_sp,
                                energy_cause=f"追击回能 {ab}",
                                local_dynamics=_dyn,
                                emit_insert_start=True,
                                emit_before_skill=(sk_t == "Insert"),
                                emit_listen_before_skill=(sk_t == "Insert"),
                                emit_after_skill=True,
                                emit_action_end_hooks=True,
                                emit_insert_finish=True,
                                emit_settle_callback=True,
                            )
                        )
                    finally:
                        rt.lifecycle.complete_deathrattle_action(
                            a_id,
                            force_limbo_prio=_prio in ("MonsterDeathRattle", "MonsterForceKill"),
                        )

                imm_prio = (
                    2 if prio.startswith("MonsterBuffOthers")
                    else (
                        3 if prio == "MonsterDeathRattle"
                        else (
                            4 if prio == "MonsterForceKill"
                            else (
                                5 if prio == "MonsterSummon"
                                else (
                                    6 if prio == "MonsterChangePhase"
                                    else (7 if prio == "MonsterBattleCry" else 10)
                                )
                            )
                        )
                    )
                )
                sim.scheduler.enqueue(
                    tid,
                    _run_insert,
                    name=ab_name,
                    category=cat,
                    action_kind=act_kind,
                    skill_id=ins_skill_id,
                    preempt_follow_up=(
                        prio in (
                            "AvatarBuffSelf",
                            "MonsterBattleCry",
                            "MonsterChangeState",
                            "MonsterChangePhase",
                            "MonsterForceKill",
                            "MonsterBuffOthers_Elation",
                        )
                    ),
                    immediate_priority=imm_prio,
                    allow_limbo=allow_limbo,
                )
            elif "SkillIndex" in task and not is_level_caster:
                sk_idx = int(round(self._eval_num(task.get("SkillIndex"), ctx, 0.0)))
                spec = rt.entity_specs.get(tid)
                skill_list = (spec.config.get("SkillList") or []) if spec is not None else []
                sk_entry = skill_list[sk_idx] if 0 <= sk_idx < len(skill_list) else None
                entry_ab = str(sk_entry.get("EntryAbility") or "") if isinstance(sk_entry, Mapping) else ""
                if not entry_ab:
                    continue
                sk_type = str(sk_entry.get("SkillType") or "Elation")
                preset_targets = tuple(self._resolve_targets(ability_tgt_spec, ctx)) if ability_tgt_spec is not None else ()
                raw_dyn = task.get("DynamicValues")
                insert_dyn: Dict[int, float] = (
                    {dotnet_hash(str(k)): self._eval_num(v, ctx, 0.0) for k, v in raw_dyn.items()}
                    if isinstance(raw_dyn, Mapping)
                    else {}
                )
                insert_strs = self._resolve_dynamic_strings(task.get("DynamicStrings"), ctx)
                active_pred = task.get("ActivePredicate")
                pred_ctx = ctx.clone()
                imm_prio = 1 if prio in ("StartElationTime", "RestartElationTime") else 2

                def _run_insert_skill_index(
                    a_id: str = tid,
                    ab: str = entry_ab,
                    _sk_t: str = sk_type,
                    _tgts: Tuple[str, ...] = preset_targets,
                    _is_en: bool = is_enemy_caster,
                    _dyn: Dict[int, float] = insert_dyn,
                    _strs: Dict[str, str] = insert_strs,
                    _active_pred: Any = active_pred,
                    _pred_ctx: ExecutionContext = pred_ctx,
                ) -> None:
                    if isinstance(_active_pred, Mapping) and not self.eval_predicate(_active_pred, _pred_ctx):
                        return
                    a_ent = sim.get_entity(a_id)
                    if a_ent is None or (float(getattr(a_ent, "current_hp", 0.0)) <= 0.0 and not getattr(a_ent, "is_infinite_hp", False)):
                        return
                    if _tgts:
                        eff_tgts = _tgts
                    elif _is_en:
                        eff_tgts = tuple(
                            e.name for e in sim.entities
                            if not e.is_enemy and not getattr(e, "is_countdown", False) and e.current_hp > 0
                        )
                    else:
                        eff_tgts = tuple(
                            e.name for e in sim.entities
                            if e.is_enemy and (e.current_hp > 0 or getattr(e, "_in_deathrattle_limbo", False))
                        )
                    rt.lifecycle.run_ability_frame(
                        AbilityFrameSpec(
                            caster_id=a_id,
                            ability_name=ab,
                            target_ids=eff_tgts,
                            skill_target_ids=eff_tgts,
                            skill_type=_sk_t,
                            attack_type=_sk_t,
                            local_dynamics=_dyn,
                            custom_strings=_strs,
                        )
                    )

                sim.scheduler.enqueue(
                    tid,
                    _run_insert_skill_index,
                    name=entry_ab,
                    category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                    action_kind=ActionKind.TALENT,
                    skill_id=0,
                    publish_execute_event=False,
                    preempt_follow_up=True,
                    immediate_priority=imm_prio,
                    allow_limbo=allow_limbo,
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
            elif getattr(ent, "is_dummy", False):
                kit = getattr(ent, "kit", None)
                defn = None
                if kit is not None:
                    try:
                        defn = kit.definition(ActionKind.BASIC)
                    except Exception:
                        defn = None
                d_skill_id = int(getattr(defn, "skill_id", 0) or 0)
                d_skill_name = str(getattr(defn, "name", "") or f"{tid}_InsertAction")

                def _run_dummy_insert(d_ent: Entity = ent) -> None:
                    if d_ent.current_hp <= 0.0:
                        return
                    sim._execute_action(
                        d_ent,
                        target_ids=(),
                        is_natural_turn_action=False,
                        advance_policy=False,
                    )
                    rt.modifier_engine.dispatch_event(
                        "OnInsertActionFinish",
                        owner_id=d_ent.name,
                        param_entity_id=d_ent.name,
                    )

                sim.scheduler.enqueue(
                    tid,
                    _run_dummy_insert,
                    name=d_skill_name,
                    category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                    action_kind=(getattr(defn, "kind", ActionKind.BASIC) if defn is not None else ActionKind.BASIC),
                    skill_id=d_skill_id,
                )
            elif task.get("SkillType") in ("ControlSkill01", "ControlSkill02", "ControlSkill03"):
                ctrl_map = {
                    "ControlSkill01": ActionKind.BASIC,
                    "ControlSkill02": ActionKind.SKILL,
                    "ControlSkill03": ActionKind.ULTIMATE,
                }
                act_kind = ctrl_map[str(task["SkillType"])]
                kit = getattr(ent, "kit", None)
                defn = None
                if kit is not None:
                    try:
                        defn = kit.definition(act_kind)
                    except Exception:
                        defn = None
                ins_skill_id = int(getattr(defn, "skill_id", 0) or 0)
                ins_skill_name = str(getattr(defn, "name", "") or f"{tid}_{task['SkillType']}")
                preset_targets = tuple(self._resolve_targets(ability_tgt_spec, ctx)) if ability_tgt_spec is not None else ()

                def _run_avatar_insert_action(
                    a_ent: Entity = ent,
                    _kind: ActionKind = act_kind,
                    _tgts: Tuple[str, ...] = preset_targets,
                ) -> None:
                    if a_ent.current_hp <= 0.0 and not getattr(a_ent, "is_infinite_hp", False):
                        return
                    sim._execute_action(
                        a_ent,
                        action_override=_kind,
                        target_ids=_tgts,
                        is_natural_turn_action=False,
                        advance_policy=False,
                    )

                sim.scheduler.enqueue(
                    tid,
                    _run_avatar_insert_action,
                    name=ins_skill_name,
                    category=(
                        ActionScheduleCategory.AUTO_SKILL
                        if task.get("AutoCast")
                        else ActionScheduleCategory.IMMEDIATE_EXTRA_TURN
                    ),
                    action_kind=act_kind,
                    skill_id=ins_skill_id,
                )
            elif not is_level_caster:
                custom_tags = tuple(_str_val(ct) for ct in (task.get("CustomTags") or ()) if _str_val(ct))
                ins_name = custom_tags[0] if custom_tags else f"{tid}_InsertAction"
                pre_check = task.get("PreCheck")
                if isinstance(pre_check, Mapping) and (
                    pre_check.get("Type") == "AbilityOwnerInsertUnusedCount"
                    or pre_check.get("$type") in ("AbilityOwnerInsertUnusedCount", "IKDAKCBKFAB")
                ):
                    cnt_spec = pre_check.get("HOCMHABKLGJ") if "HOCMHABKLGJ" in pre_check else pre_check.get("Count")
                    max_unused = int(round(self._eval_num(cnt_spec, ctx, 1.0)))
                    if sim.scheduler.count_pending_actions(tid, ins_name) >= max_unused:
                        continue
                kit = getattr(ent, "kit", None)
                defn = None
                if kit is not None:
                    try:
                        defn = kit.definition(ActionKind.BASIC)
                    except Exception:
                        defn = None
                ins_skill_id = int(getattr(defn, "skill_id", 0) or 0)
                preset_targets = tuple(self._resolve_targets(ability_tgt_spec, ctx)) if ability_tgt_spec is not None else ()
                active_pred = task.get("ActivePredicate")
                pred_ctx = ctx.clone()

                def _run_avatar_tag_insert_action(
                    a_id: str = tid,
                    a_ent: Entity = ent,
                    _tgts: Tuple[str, ...] = preset_targets,
                    _tags: Tuple[str, ...] = custom_tags,
                    _active_pred: Any = active_pred,
                    _pred_ctx: ExecutionContext = pred_ctx,
                ) -> None:
                    if isinstance(_active_pred, Mapping) and not self.eval_predicate(_active_pred, _pred_ctx):
                        return
                    if a_ent.current_hp <= 0.0 and not getattr(a_ent, "is_infinite_hp", False):
                        return
                    me = rt.modifier_engine
                    me.dispatch_event("OnBeforeInsertActionPrepare", owner_id=a_id, param_entity_id=a_id, param_strings=_tags)
                    me.dispatch_event("OnInsertActionStart", owner_id=a_id, param_entity_id=a_id, param_strings=_tags)
                    me.dispatch_event("OnListenInsertActionStart", param_entity_id=a_id, param_strings=_tags)
                    prev_ins = getattr(rt, "_in_insert_action", False)
                    rt._in_insert_action = True
                    try:
                        decide_fn = getattr(sim, "decide_insert_action", None)
                        if not callable(decide_fn):
                            decide_fn = getattr(sim, "insert_action_decision_provider", None)
                        dec = decide_fn(a_id) if callable(decide_fn) else None
                        first_kind = dec[0] if (dec is not None and dec[0] is not None) else ActionKind.BASIC
                        first_tgts = dec[1] if (dec is not None and dec[1] is not None) else _tgts
                        sim._execute_action(
                            a_ent,
                            action_override=first_kind,
                            target_ids=first_tgts,
                            is_natural_turn_action=False,
                            advance_policy=False,
                        )
                        hold_guard = 0
                        while getattr(sim.scheduler, "continuous_action_hold", False):
                            hold_guard += 1
                            if hold_guard >= 32:
                                sim.scheduler.continuous_action_hold = False
                                break
                            if a_ent.current_hp <= 0.0 and not getattr(a_ent, "is_infinite_hp", False):
                                sim.scheduler.continuous_action_hold = False
                                break
                            nxt_dec = decide_fn(a_id) if callable(decide_fn) else None
                            if nxt_dec is None or nxt_dec[0] is None:
                                sim.scheduler.continuous_action_hold = False
                                break
                            sim._execute_action(
                                a_ent,
                                action_override=nxt_dec[0],
                                target_ids=nxt_dec[1] if nxt_dec[1] is not None else (),
                                is_natural_turn_action=False,
                                advance_policy=False,
                            )
                    finally:
                        rt._in_insert_action = prev_ins
                    me.dispatch_event("OnInsertActionFinish", owner_id=a_id, param_entity_id=a_id, param_strings=_tags)
                    me.dispatch_event("OnListenInsertActionFinish", param_entity_id=a_id, param_strings=_tags)
                    me.dispatch_event("OnListenAllowAction", param_entity_id=a_id)

                sim.scheduler.enqueue(
                    tid,
                    _run_avatar_tag_insert_action,
                    name=ins_name,
                    category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                    action_kind=ActionKind.BASIC,
                    skill_id=ins_skill_id,
                )

    def _execute_use_skill_one_more(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if "TargetType" in task
            else ([ctx.caster_id] if ctx.caster_id else [])
        )
        ctrl_type = str(task.get("SkillType") or "ControlSkill01")
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            self.rt._pending_use_skill_one_more.setdefault(tid, []).append(ctrl_type)

    def _execute_start_elation_time(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        """执行官方 ELLFLJKDCAE（开启阿哈时刻 ElationTime 并按 ElationSkill.PriorityValue 依次施放欢愉技）。"""
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        raw_targets = self._resolve_targets(task.get("HILNFHCPEAD"), ctx)
        excl_flags = {str(f) for f in (task.get("HMOBDKGBECE") or ()) if f}

        candidates: List[Dict[str, Any]] = []
        for idx, tid in enumerate(raw_targets):
            if not tid or tid == "__LEVEL__":
                continue
            ent = sim.get_entity(tid)
            if ent is None or (float(getattr(ent, "current_hp", 0.0)) <= 0.0 and not getattr(ent, "is_infinite_hp", False)):
                continue
            if excl_flags and any(me.has_behavior_flag(tid, flg) for flg in excl_flags):
                continue
            spec = rt.entity_specs.get(tid)
            if spec is None:
                continue
            dyn_tags = rt.entity_skill_tags.get(tid, {})
            rem_tags = rt.entity_removed_skill_tags.get(tid, {})
            chosen_sk = None
            first_elation_sk = None
            for sk in (spec.config.get("SkillList") or ()):
                if not isinstance(sk, Mapping) or str(sk.get("SkillType") or "") != "Elation":
                    continue
                sk_name = str(sk.get("Name") or "")
                if (8, 1) in rem_tags.get(sk_name, ()):
                    continue
                if first_elation_sk is None:
                    first_elation_sk = sk
                has_dyn = (8, 1) in dyn_tags.get(sk_name, ())
                has_stat = any(
                    isinstance(tg, Mapping)
                    and int(tg.get("EnumIndex", 0) or 0) == 8
                    and int(tg.get("Value", 0) or 0) == 1
                    for tg in (sk.get("Tags") or ())
                )
                if has_dyn or has_stat:
                    chosen_sk = sk
                    break
            if chosen_sk is None:
                chosen_sk = first_elation_sk
            if chosen_sk is None:
                continue
            sk_name = str(chosen_sk.get("Name") or "")
            entry_ab = str(chosen_sk.get("EntryAbility") or "")
            if not entry_ab:
                continue
            sk_id, sp_base = self._resolve_insert_skill_meta(tid, entry_ab)
            prio_val = rt.loader.get_elation_skill_priority(sk_id) if sk_id > 0 else 500
            t_info = (chosen_sk.get("TargetInfo") or {}).get("TargetType", "")
            candidates.append(
                {
                    "tid": tid,
                    "sk_name": sk_name,
                    "entry_ab": entry_ab,
                    "skill_id": sk_id,
                    "sp_base": sp_base,
                    "prio": prio_val,
                    "orig_idx": idx,
                    "target_type": str(t_info or ""),
                }
            )

        candidates.sort(key=lambda u: (u["prio"], u["orig_idx"]))
        ov_pt = self._eval_num(task.get("CKLLHFKPACB"), ctx, -1.0)
        tag_spec = task.get("GEIGNKLEOBD")
        if isinstance(tag_spec, Mapping) and tag_spec.get("Custom"):
            custom_tag = str(ctx.custom_strings.get(str(tag_spec.get("Key") or ""), ""))
        else:
            custom_tag = _str_val(tag_spec)

        rt.in_elation_time = True
        rt.elation_time_override_points = float(ov_pt) if ov_pt > 0.0 else 0.0
        rt.elation_time_custom_tag = custom_tag
        rt.elation_time_units = [u["tid"] for u in candidates]
        p_strs = (custom_tag,) if custom_tag and custom_tag != "-1" else ()
        me.dispatch_event("OnListenElationTimeStart", param_entity_id=ctx.caster_id, param_strings=p_strs)

        for u in candidates:
            def _run_elation_unit(_u: Dict[str, Any] = u) -> None:
                a_id = _u["tid"]
                a_ent = sim.get_entity(a_id)
                if a_ent is None or (float(getattr(a_ent, "current_hp", 0.0)) <= 0.0 and not getattr(a_ent, "is_infinite_hp", False)):
                    return
                t_type = _u["target_type"]
                if t_type in ("Caster", "Self"):
                    eff_tgts = (a_id,)
                elif t_type in ("AllTeamMember", "AllLightTeam", "AllLightMember"):
                    eff_tgts = tuple(
                        e.name
                        for e in sim.entities
                        if not getattr(e, "is_enemy", False)
                        and not getattr(e, "is_countdown", False)
                        and not getattr(e, "is_battle_event", False)
                        and not getattr(e, "is_unselectable", False)
                        and float(getattr(e, "current_hp", 0.0)) > 0.0
                    )
                else:
                    eff_tgts = tuple(
                        e.name
                        for e in sorted(
                            (
                                e for e in sim.entities
                                if getattr(e, "is_enemy", False)
                                and not getattr(e, "is_countdown", False)
                                and not getattr(e, "is_unselectable", False)
                                and float(getattr(e, "current_hp", 0.0)) > 0.0
                            ),
                            key=lambda x: getattr(x, "_spawn_seq", 0),
                        )
                    )
                    if not eff_tgts:
                        return
                sim._action_seq += 1
                sim._av_batch_seq += 1
                emit_sim_event(sim, ActionExecuteEvent(
                    av=round(sim.current_av, 2),
                    cycle=sim.current_cycle,
                    actor_id=a_id,
                    actor_name=a_id,
                    action_type=_u["entry_ab"],
                    description=f"施放欢愉技【{_u['entry_ab']}】",
                    action_kind=ActionKind.TALENT,
                    skill_config_id=_u["skill_id"],
                    action_id=sim._action_seq,
                ))
                rt.lifecycle.run_ability_frame(
                    AbilityFrameSpec(
                        caster_id=a_id,
                        ability_name=_u["entry_ab"],
                        target_ids=eff_tgts,
                        skill_target_ids=eff_tgts,
                        skill_type="Elation",
                        attack_type="ElationDamage",
                        skill_name=_u["sk_name"],
                        sp_base=_u["sp_base"],
                        energy_cause=f"欢愉技回能 {_u['entry_ab']}",
                        emit_before_skill=True,
                        emit_listen_before_skill=True,
                        pass_skill_targets_to_before_hooks=True,
                        emit_after_skill=True,
                        emit_action_end_hooks=True,
                        emit_settle_callback=True,
                    )
                )

            sim.scheduler.enqueue(
                u["tid"],
                _run_elation_unit,
                name=u["entry_ab"],
                category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                action_kind=ActionKind.TALENT,
                skill_id=u["skill_id"],
                publish_execute_event=False,
                preempt_follow_up=True,
                immediate_priority=8,
            )

        be_id = ctx.caster_id
        def _finish_elation_time(_be_id: str = be_id, _p_strs: Tuple[str, ...] = p_strs) -> None:
            me.dispatch_event("OnListenElationTimeWaitEnd", param_entity_id=_be_id, param_strings=_p_strs)
            me.dispatch_event("OnListenElationTimeEnd", param_entity_id=_be_id, param_strings=_p_strs)
            rt.in_elation_time = False
            rt.elation_time_override_points = 0.0
            rt.elation_time_custom_tag = ""
            rt.elation_time_units = []

        sim.scheduler.enqueue(
            be_id,
            _finish_elation_time,
            name="EndElationTime",
            category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
            action_kind=ActionKind.TALENT,
            skill_id=0,
            publish_execute_event=False,
            preempt_follow_up=True,
            immediate_priority=9,
            allow_limbo=True,
        )

    def _execute_create_servant(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        sv_id = int(round(self._eval_num(task.get("ServantID"), ctx, 0.0)))
        if sv_id <= 0:
            return
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

        be_name = f"BattleEvent_{event_id}"

        compiled_be = None
        src_spec = None
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            src_spec = getattr(getattr(runner, "built_stage", None), "source_spec", None)
            if src_spec is not None:
                for be in getattr(src_spec, "battle_events", ()):
                    if int(getattr(be, "battle_event_id", 0)) == event_id:
                        compiled_be = be
                        break
                if compiled_be is None:
                    widx = int(getattr(runner.state, "wave_index", 0))
                    waves = getattr(src_spec, "waves", ())
                    if 0 <= widx < len(waves):
                        for m in getattr(waves[widx], "monsters", ()):
                            for be in getattr(m, "battle_events", ()):
                                if int(getattr(be, "battle_event_id", 0)) == event_id:
                                    compiled_be = be
                                    break
                            if compiled_be is not None:
                                break

        rt.loader.ensure_ability_index()
        bec_row: Dict[str, Any] = {}
        try:
            for row in rt.loader._read_excel("BattleEventConfig.json"):
                if int(row.get("BattleEventID", 0) or 0) == event_id:
                    bec_row = row
                    break
        except Exception:
            bec_row = {}

        event_sub_type = str(
            (getattr(compiled_be, "event_sub_type", "") if compiled_be is not None else "")
            or bec_row.get("EventSubType", "")
        )
        ab_names: List[str] = []
        param_list: List[float] = []
        if compiled_be is not None:
            ab_names = list(getattr(compiled_be, "ability_list", ()))
            param_list = [float(p) for p in getattr(compiled_be, "param_list", ())]
        if not ab_names and bec_row:
            ab_names = [str(a) for a in bec_row.get("AbilityList", [])]
        if not param_list and bec_row:
            for p in bec_row.get("ParamList", []):
                val = p.get("Value", 0.0) if isinstance(p, Mapping) else p
                param_list.append(float(val or 0.0))

        robin_spd = float(init_dyn.get(dotnet_hash("BattleEvent_RobinS_00_BaseSpeed"), 0.0) or 0.0)
        dv_be_spd = float(init_dyn.get(dotnet_hash("DV_BE_BaseSpeed"), 0.0) or 0.0)
        bec_fixed_spd = 0.0
        raw_spd = bec_row.get("Speed")
        if isinstance(raw_spd, Mapping):
            bec_fixed_spd = float(raw_spd.get("Value", 0.0) or 0.0)
        elif isinstance(raw_spd, (int, float)):
            bec_fixed_spd = float(raw_spd)
        bec_override_spd = 0.0
        for ov in bec_row.get("OverrideProperty") or ():
            if isinstance(ov, Mapping) and ov.get("PropertyType") == "BaseSpeed":
                ov_v = ov.get("Value", 0.0)
                bec_override_spd = float(ov_v.get("Value", 0.0) if isinstance(ov_v, Mapping) else (ov_v or 0.0))
                break
        if robin_spd > 0.0:
            spd = robin_spd
        elif dv_be_spd > 0.0:
            spd = dv_be_spd
        elif compiled_be is not None and float(getattr(compiled_be, "effective_speed", 0.0) or 0.0) > 0.0:
            spd = float(compiled_be.effective_speed)
        elif bec_fixed_spd > 0.0:
            spd = bec_fixed_spd
        elif bec_override_spd > 0.0:
            spd = bec_override_spd
        else:
            spd = 140.0

        if event_sub_type in ("DummyCharacter", "Elation"):
            self._create_dummy_character_battle_event(
                event_id=event_id,
                be_name=be_name,
                bec_row=bec_row,
                src_spec=src_spec,
                init_dyn=init_dyn,
                ab_names=ab_names,
                param_list=param_list,
                task=task,
                ctx=ctx,
                event_sub_type=event_sub_type,
            )
            return

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

        be_abilities: Dict[str, Dict[str, Any]] = {}
        for ab_name in ab_names:
            ab_doc = rt.loader.get_ability(ab_name)
            if ab_doc is not None:
                be_abilities[ab_name] = ab_doc
                floats = (ab_doc.get("DynamicValues") or {}).get("Floats") or {}
                if isinstance(floats, Mapping):
                    for h_str, entry in floats.items():
                        if not isinstance(entry, Mapping):
                            continue
                        ri = entry.get("ReadInfo") or {}
                        if ri.get("Type") == "BattleEvent":
                            idx = int(ri.get("Index", 0) or 0)
                            if 0 <= idx < len(param_list):
                                init_dyn[int(h_str)] = float(param_list[idx])

        be_spec = CompiledCharacterSpec(
            unit_id=event_id,
            is_servant=False,
            config={},
            abilities=be_abilities,
            global_modifiers=rt.loader._global_mod_by_name,
            global_templates=rt.loader._global_tpl_by_name,
            dynamic_floats=init_dyn,
            skill_levels={},
        )
        rt.register_character(be_name, be_spec)
        rt.named_targets["BattleEventCaster"] = [ctx.caster_id]
        be_list = rt.named_targets.setdefault("BattleEventEntityList", [])
        if be_name not in be_list:
            be_list.append(be_name)

        for ab_name in ab_names:
            rt.trigger_ability(caster_id=be_name, ability_name=ab_name, target_ids=(be_name,))
        on_create = task.get("OnBattleEventCreate")
        if isinstance(on_create, list) and on_create:
            self.execute_tasks(on_create, ctx.clone(param_entity_id=be_name))

    def _create_dummy_character_battle_event(
        self,
        *,
        event_id: int,
        be_name: str,
        bec_row: Mapping[str, Any],
        src_spec: Any,
        init_dyn: Dict[int, float],
        ab_names: List[str],
        param_list: List[float],
        task: Mapping[str, Any],
        ctx: ExecutionContext,
        event_sub_type: str = "DummyCharacter",
    ) -> None:
        rt = self.rt
        sim = rt.sim

        bed_row: Dict[str, Any] = {}
        try:
            for row in rt.loader._read_excel("BattleEventData.json"):
                if int(row.get("BattleEventID", 0) or 0) == event_id:
                    bed_row = row
                    break
        except Exception:
            bed_row = {}

        char_cfg: Dict[str, Any] = {}
        cfg_path = str(bed_row.get("Config", ""))
        if cfg_path:
            try:
                char_cfg = rt.loader._read_json(cfg_path)
            except Exception:
                char_cfg = {}

        skill_id_list = [int(s) for s in bed_row.get("SkillIDList", []) if isinstance(s, int)]
        skill_params: Dict[str, List[float]] = {}
        skill_meta_by_key: Dict[str, Dict[str, Any]] = {}
        try:
            for row in rt.loader._read_excel("BattleEventSkillConfig.json"):
                sid = int(row.get("SkillID", 0) or 0)
                if (skill_id_list and sid in skill_id_list) or (not skill_id_list and sid // 100 == event_id):
                    tkey = str(row.get("SkillTriggerKey", ""))
                    if not tkey:
                        continue
                    plist = [
                        float(p.get("Value", 0.0) if isinstance(p, Mapping) else (p or 0.0))
                        for p in row.get("ParamList", [])
                    ]
                    skill_params.setdefault(tkey, plist)
                    if tkey not in skill_meta_by_key:
                        skill_meta_by_key[tkey] = {
                            "skill_id": sid,
                            "attack_type": str(row.get("AttackType") or "Normal"),
                        }
        except Exception:
            pass

        for h_str, entry in (char_cfg.get("DynamicValues") or {}).get("Floats", {}).items():
            if not isinstance(entry, Mapping):
                continue
            ri = entry.get("ReadInfo") or {}
            rtype = ri.get("Type")
            idx = int(ri.get("Index", 0) or 0)
            if rtype == "SkillParam":
                tkey = str(ri.get("TriggerKey", ""))
                plist = skill_params.get(tkey, [])
                if 0 <= idx < len(plist):
                    init_dyn[int(h_str)] = float(plist[idx])
            elif rtype == "BattleEvent":
                if 0 <= idx < len(param_list):
                    init_dyn[int(h_str)] = float(param_list[idx])

        stage_level = int(getattr(src_spec, "level", 80) or 80) if src_spec is not None else 80
        curve = getattr(src_spec, "hard_level_curve", None) if src_spec is not None else None
        overrides: Dict[str, float] = {}
        for item in bec_row.get("OverrideProperty", []):
            if not isinstance(item, Mapping):
                continue
            pt = item.get("PropertyType")
            if pt:
                ov = item.get("Value")
                overrides[str(pt)] = float(ov.get("Value", 0.0) if isinstance(ov, Mapping) else (ov or 0.0))

        base_hp = overrides.get("BaseHP", 1000.0)
        base_atk = overrides.get("BaseAttack", 100.0)
        base_spd = overrides.get("BaseSpeed", 140.0)
        if bool(bec_row.get("HardLevel", False)) and curve is not None:
            eff_hp = base_hp * float(curve.hp_ratio)
            eff_atk = base_atk * float(curve.atk_ratio)
            eff_spd = base_spd * float(curve.speed_ratio)
        else:
            eff_hp, eff_atk, eff_spd = base_hp, base_atk, base_spd

        from ..stage_factory import normalize_element

        elem = normalize_element(str(char_cfg.get("DamageType", ""))) or "Quantum"
        is_enemy_team = str(task.get("Team", bec_row.get("Team", ""))) == "TeamDark"

        be_ent = sim.get_entity(be_name)
        if be_ent is None:
            be_ent = Entity(
                name=be_name,
                level=stage_level,
                base_speed=max(1.0, eff_spd),
                base_atk=eff_atk,
                base_crit_rate=0.0,
                base_crit_dmg=0.5,
                max_hp=eff_hp,
                current_hp=eff_hp,
                element=elem,
                is_enemy=is_enemy_team,
                is_memosprite=False,
                is_countdown=True,
                master_name=ctx.caster_id,
                avatar_id=event_id,
            )
            be_ent.is_battle_event = True  # type: ignore[attr-defined]
            be_ent.is_dummy = (event_sub_type == "DummyCharacter")  # type: ignore[attr-defined]
            sim.add_entity(be_ent, trigger_battle_start=False)
        else:
            be_ent.level = stage_level
            be_ent.base_speed = max(1.0, eff_spd)
            be_ent.base_atk = eff_atk
            be_ent.max_hp = eff_hp
            be_ent.current_hp = eff_hp
            be_ent.element = elem
            be_ent.distance_remaining = 10000.0
            be_ent.master_name = ctx.caster_id
            be_ent.is_battle_event = True  # type: ignore[attr-defined]
            be_ent.is_dummy = (event_sub_type == "DummyCharacter")  # type: ignore[attr-defined]

        passive_entries: List[str] = []
        collect_ab_names: List[str] = list(ab_names) + [
            str(a) for a in char_cfg.get("AbilityList", []) if isinstance(a, str) and a
        ]
        for sa in char_cfg.get("SkillAbilityList", []):
            if isinstance(sa, Mapping):
                for a in sa.get("AbilityList", []):
                    if isinstance(a, str) and a:
                        collect_ab_names.append(a)
        default_skill_key = "Skill01"
        for sk_entry in char_cfg.get("SkillList", []):
            if not isinstance(sk_entry, Mapping):
                continue
            sk_name = str(sk_entry.get("Name", ""))
            entry_ab = str(sk_entry.get("EntryAbility", ""))
            sk_type = str(sk_entry.get("SkillType", "Skill"))
            if entry_ab:
                collect_ab_names.append(entry_ab)
                if entry_ab.endswith("_Phase01"):
                    collect_ab_names.append(entry_ab.replace("_Phase01", "_Phase02"))
                if sk_type == "Passive" or sk_name.startswith(("SkillP", "Passive")):
                    if entry_ab not in passive_entries:
                        passive_entries.append(entry_ab)
                else:
                    meta = skill_meta_by_key.setdefault(
                        sk_name,
                        {"skill_id": event_id * 100 + 1, "attack_type": "Normal"},
                    )
                    meta["entry_ab"] = entry_ab
                    meta["skill_type"] = sk_type
                    meta["always_auto_lock"] = bool(sk_entry.get("AlwaysDoAutoLock", False))

        if default_skill_key not in skill_meta_by_key and skill_meta_by_key:
            default_skill_key = next(iter(skill_meta_by_key))

        be_abilities: Dict[str, Dict[str, Any]] = {}
        seen_ab: set[str] = set()
        queue_ab = list(collect_ab_names)
        while queue_ab:
            ab_n = queue_ab.pop(0)
            if not ab_n or ab_n in seen_ab or ab_n.endswith("_Camera"):
                continue
            seen_ab.add(ab_n)
            ab_doc = rt.loader.get_ability(ab_n)
            if ab_doc is None:
                continue
            be_abilities[ab_n] = ab_doc
            floats = (ab_doc.get("DynamicValues") or {}).get("Floats") or {}
            if isinstance(floats, Mapping):
                for h_str, entry in floats.items():
                    if not isinstance(entry, Mapping):
                        continue
                    ri = entry.get("ReadInfo") or {}
                    if ri.get("Type") == "BattleEvent":
                        idx = int(ri.get("Index", 0) or 0)
                        if 0 <= idx < len(param_list):
                            init_dyn[int(h_str)] = float(param_list[idx])
            for t_item in ab_doc.get("OnStart", []) + ab_doc.get("OnAdd", []):
                if isinstance(t_item, Mapping):
                    sub_ab = _str_val(t_item.get("AbilityName"))
                    if sub_ab and sub_ab not in seen_ab:
                        queue_ab.append(sub_ab)

        class _DummyCharacterBattleEventKit:
            def __init__(self, owner_id: str) -> None:
                self.owner_id = owner_id
                self.port = sim.port

            def _active_key(self) -> str:
                mapped = rt.control_skill_mapping.get((self.owner_id, "ControlSkill01"))
                if mapped and mapped in skill_meta_by_key:
                    return mapped
                return default_skill_key

            def definition(self, kind: Any) -> Any:
                key = self._active_key()
                meta = skill_meta_by_key.get(key) or {}
                atk_type = str(meta.get("attack_type", "Normal"))
                act_kind = ActionKind.SKILL if atk_type == "BPSkill" else ActionKind.BASIC
                return AbilityDefinition(
                    kind=act_kind,
                    target_mode=TargetMode.SINGLE_ENEMY,
                    name=f"BattleEvent_{event_id}_{key}",
                    cost=ResourceCost(sp=0),
                    skill_id=int(meta.get("skill_id", event_id * 100 + 1)),
                )

            def decide_action(self, act_ctx: Any) -> Any:
                return self.definition(ActionKind.BASIC).kind

            def choose_action(self, act_ctx: Any) -> Any:
                return self.definition(ActionKind.BASIC).kind

            def execute(self, act_ctx: Any) -> None:
                key = self._active_key()
                meta = skill_meta_by_key.get(key) or {}
                entry_ab = str(meta.get("entry_ab", ""))
                if not entry_ab:
                    return
                tgt_ids = getattr(act_ctx, "target_ids", None)
                chosen: Optional[str] = None
                if tgt_ids:
                    for tid in tgt_ids:
                        te = sim.get_entity(tid)
                        if te is not None and te.is_enemy and te.current_hp > 0:
                            chosen = te.name
                            break
                if chosen is None:
                    living_enemies = [
                        e for e in sim.entities
                        if e.is_enemy
                        and e.current_hp > 0
                        and not getattr(e, "is_countdown", False)
                        and not getattr(e, "is_unselectable", False)
                    ]
                    tprov = getattr(sim, "target_provider", None)
                    owner_ent = sim.get_entity(self.owner_id)
                    if callable(tprov) and owner_ent is not None and living_enemies:
                        picked = tprov(owner_ent, living_enemies, 0)
                        if picked is not None and getattr(picked, "current_hp", 0.0) > 0.0:
                            chosen = picked.name
                    if chosen is None and living_enemies:
                        if meta.get("always_auto_lock") or meta.get("attack_type") == "BPSkill":
                            chosen_ent = max(
                                living_enemies,
                                key=lambda e: (
                                    bool(getattr(e, "is_boss", False)),
                                    float(getattr(e, "max_hp", 0.0)),
                                    float(getattr(e, "current_hp", 0.0)),
                                ),
                            )
                            chosen = chosen_ent.name
                        else:
                            minions = [e for e in living_enemies if not getattr(e, "is_boss", False)]
                            chosen = (minions[0] if minions else living_enemies[0]).name
                if chosen is not None:
                    rt.lifecycle.run_ability_frame(
                        AbilityFrameSpec(
                            caster_id=self.owner_id,
                            ability_name=entry_ab,
                            target_ids=(chosen,),
                            skill_target_ids=(chosen,),
                            skill_type=str(meta.get("skill_type", "Skill")),
                            attack_type=str(meta.get("attack_type", "Normal")),
                        )
                    )

        class _ElationBattleEventKit:
            def __init__(self, owner_id: str) -> None:
                self.owner_id = owner_id
                self.port = sim.port

            def definition(self, kind: Any) -> Any:
                return AbilityDefinition(
                    kind=ActionKind.BASIC,
                    target_mode=TargetMode.SELF,
                    name=f"BattleEvent_{event_id}_Turn",
                    cost=ResourceCost(sp=0),
                    skill_id=0,
                )

            def decide_action(self, act_ctx: Any) -> Any:
                return ActionKind.BASIC

            def choose_action(self, act_ctx: Any) -> Any:
                return ActionKind.BASIC

            def execute(self, act_ctx: Any) -> None:
                return

        be_ent.kit = _ElationBattleEventKit(be_name) if event_sub_type == "Elation" else _DummyCharacterBattleEventKit(be_name)

        be_spec = CompiledCharacterSpec(
            unit_id=event_id,
            is_servant=False,
            config=char_cfg,
            abilities=be_abilities,
            global_modifiers=rt.loader._global_mod_by_name,
            global_templates=rt.loader._global_tpl_by_name,
            dynamic_floats=init_dyn,
            skill_levels={},
        )
        rt.register_character(be_name, be_spec)
        rt.named_targets["BattleEventCaster"] = [ctx.caster_id]
        be_list = rt.named_targets.setdefault("BattleEventEntityList", [])
        if be_name not in be_list:
            be_list.append(be_name)

        for ab_name in passive_entries + ab_names:
            if ab_name in be_abilities:
                rt.trigger_ability(caster_id=be_name, ability_name=ab_name, target_ids=(be_name,))
        on_create = task.get("OnBattleEventCreate")
        if isinstance(on_create, list) and on_create:
            self.execute_tasks(on_create, ctx.clone(param_entity_id=be_name))

    def _execute_attach_avatar_change(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        src_id = ctx.modifier_owner_id or ctx.caster_id
        source = sim.get_entity(src_id)
        if source is None:
            return
        if getattr(source, "_avatar_change_target_id", None) is not None:
            return

        new_avatar_id = int(round(self._eval_num(task.get("NewAvatarID"), ctx, 0.0)))
        if new_avatar_id <= 0:
            return
        new_name = f"UID_{new_avatar_id}"
        existing = sim.get_entity(new_name)
        if existing is not None:
            try:
                sim.entities.remove(existing)
            except ValueError:
                pass

        new_ent = Entity(
            name=new_name,
            avatar_id=new_avatar_id,
            level=source.level,
            base_max_hp=source.base_max_hp,
            base_white_hp=source.base_white_hp,
            base_atk=source.base_atk,
            base_white_atk=source.base_white_atk,
            base_def=source.base_def,
            base_white_def=source.base_white_def,
            base_speed=source.base_speed,
            base_white_speed=source.base_white_speed,
            base_crit_rate=source.base_crit_rate,
            base_crit_dmg=source.base_crit_dmg,
            base_err=source.base_err,
            max_energy=source.max_energy,
            is_enemy=False,
        )
        new_ent._is_avatar_change_target = True
        new_ent._avatar_change_source_id = source.name
        new_ent._avatar_change_group = str(task.get("ConfigGroupName", ""))
        source._avatar_change_target_id = new_name
        source._saved_unselectable = getattr(source, "is_unselectable", False)
        source._saved_distance_remaining = float(source.distance_remaining)
        source.is_unselectable = True
        source.distance_remaining = 1e12

        if hasattr(rt.loader, "ensure_ability_index"):
            rt.loader.ensure_ability_index()
        ac_char_cfg: Dict[str, Any] = {}
        ac_skill_ids: List[int] = []
        try:
            for row in rt.loader._read_excel("ActivityAvatarConfig.json"):
                if int(row.get("AvatarID", 0) or 0) == new_avatar_id:
                    jp = str(row.get("JsonPath", ""))
                    if jp:
                        ac_char_cfg = rt.loader._read_json(jp)
                    ac_skill_ids = [int(s) for s in row.get("SkillList", []) if isinstance(s, int)]
                    break
        except Exception:
            pass

        ac_skill_params: Dict[str, List[float]] = {}
        try:
            for row in rt.loader._read_excel("ActivityAvatarSkillConfig.json"):
                sid = int(row.get("SkillID", 0) or 0)
                if (ac_skill_ids and sid in ac_skill_ids) or (not ac_skill_ids and sid // 100 == new_avatar_id):
                    tkey = str(row.get("SkillTriggerKey", ""))
                    if tkey and tkey not in ac_skill_params:
                        ac_skill_params[tkey] = [
                            float(p.get("Value", 0.0) if isinstance(p, Mapping) else (p or 0.0))
                            for p in row.get("ParamList", [])
                        ]
        except Exception:
            pass

        ac_dyn_floats: Dict[int, float] = {}
        for h_str, entry in (ac_char_cfg.get("DynamicValues") or {}).get("Floats", {}).items():
            if not isinstance(entry, Mapping):
                continue
            ri = entry.get("ReadInfo") or {}
            if ri.get("Type") == "SkillParam":
                tkey = str(ri.get("TriggerKey", ""))
                idx = int(ri.get("Index", 0) or 0)
                plist = ac_skill_params.get(tkey, [])
                if 0 <= idx < len(plist):
                    ac_dyn_floats[int(h_str)] = float(plist[idx])

        skill01_ab = ""
        passive_ab = ""
        ac_ab_names: List[str] = []
        for sk_entry in ac_char_cfg.get("SkillList", []):
            if not isinstance(sk_entry, Mapping):
                continue
            sn = str(sk_entry.get("Name", ""))
            ea = str(sk_entry.get("EntryAbility", ""))
            if ea:
                ac_ab_names.append(ea)
                if sn == "Skill01" and not skill01_ab:
                    skill01_ab = ea
                elif sn in ("SkillP01", "PassiveSkill01") and not passive_ab:
                    passive_ab = ea
        for extra_ab in (
            skill01_ab,
            skill01_ab.replace("_Phase01", "_Phase02") if skill01_ab else "",
            passive_ab,
        ):
            if extra_ab and extra_ab not in ac_ab_names:
                ac_ab_names.append(extra_ab)

        class _AvatarChangeKit:
            def __init__(self, owner_id: str, ab_skill: str) -> None:
                self.owner_id = owner_id
                self.ab_skill = ab_skill
                self.port = sim.port

            def definition(self, kind: Any) -> Any:
                from ...actions import AbilityDefinition, TargetMode
                return AbilityDefinition(
                    kind=ActionKind.BASIC,
                    target_mode=TargetMode.SINGLE_ENEMY,
                    name=f"AvatarChange_{new_avatar_id}_Basic",
                    skill_id=new_avatar_id * 100 + 1,
                )

            def decide_action(self, act_ctx: Any) -> Any:
                return ActionKind.BASIC

            def choose_action(self, act_ctx: Any) -> Any:
                return ActionKind.BASIC

            def execute(self, act_ctx: Any) -> None:
                tgt_ids = getattr(act_ctx, "target_ids", None)
                chosen: Optional[str] = None
                if tgt_ids:
                    for tid in tgt_ids:
                        te = sim.get_entity(tid)
                        if te is not None and te.is_enemy and te.current_hp > 0:
                            chosen = te.name
                            break
                if chosen is None:
                    living_enemies = [
                        e for e in sim.entities
                        if e.is_enemy and e.current_hp > 0 and not getattr(e, "is_countdown", False)
                    ]
                    tprov = getattr(sim, "target_provider", None)
                    owner_ent = sim.get_entity(self.owner_id)
                    if callable(tprov) and owner_ent is not None and living_enemies:
                        picked = tprov(owner_ent, living_enemies, 0)
                        if picked is not None and getattr(picked, "current_hp", 0.0) > 0.0:
                            chosen = picked.name
                    if chosen is None:
                        minions = [e for e in living_enemies if not getattr(e, "is_boss", False)]
                        if minions:
                            chosen = minions[0].name
                        elif living_enemies:
                            chosen = living_enemies[0].name
                if chosen is not None:
                    rt.trigger_ability(
                        caster_id=self.owner_id,
                        ability_name=self.ab_skill,
                        target_ids=(chosen,),
                        current_attack_type="Normal",
                    )

        new_ent.kit = _AvatarChangeKit(new_name, skill01_ab)

        sim.add_entity(new_ent, trigger_battle_start=False)
        if hasattr(sim, "_rebuild_entity_cache"):
            sim._rebuild_entity_cache()

        for m in list(me.get_modifiers(source.name)):
            if (
                m.properties
                and m.caster_id != source.name
                and m.config.get("StatusType") != "Debuff"
                and m.halo_parent_uid is None
                and ("HPAddedRatio" in m.properties or "HPDelta" in m.properties)
                and all(
                    isinstance(cb, dict) and cb.get("Event") in ("OnCreate", "OnStack", "OnDestroy")
                    for cb in (m.config.get("_CallbackList") or [])
                )
            ):
                new_m = me.add_modifier(
                    owner_id=new_name,
                    mod_name=m.name,
                    caster_id=m.caster_id,
                    ability_name=m.ability_name,
                    life_time=m.life_time,
                    halo_parent_uid=m.halo_parent_uid,
                )
                if new_m is not None and m.dynamic_values:
                    new_m.dynamic_values.update(m.dynamic_values)
        new_ent.current_hp = float(sim.port.max_hp(new_name))

        ac_abilities: Dict[str, Dict[str, Any]] = {}
        for ab_n in ac_ab_names:
            ab_doc = rt.loader.get_ability(ab_n)
            if ab_doc is not None:
                ac_abilities[ab_n] = ab_doc

        ac_spec = CompiledCharacterSpec(
            unit_id=new_avatar_id,
            is_servant=False,
            config=ac_char_cfg,
            abilities=ac_abilities,
            global_modifiers=rt.loader._global_mod_by_name,
            global_templates=rt.loader._global_tpl_by_name,
            dynamic_floats=ac_dyn_floats,
            skill_levels={},
        )
        rt.register_character(new_name, ac_spec)

        on_create = task.get("OnNewAvatarCreate", [])
        if on_create:
            self.execute_tasks(on_create, ctx.clone(param_entity_id=new_name))

        if passive_ab in ac_abilities:
            rt.trigger_ability(caster_id=new_name, ability_name=passive_ab, target_ids=(new_name,))

    def _execute_detach_avatar_change(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        targets = self._resolve_targets(task.get("NewAvatar"), ctx)
        for tid in targets:
            new_ent = sim.get_entity(tid)
            if new_ent is None or getattr(new_ent, "_detaching_avatar_change", False):
                continue
            new_ent._detaching_avatar_change = True
            src_id = getattr(new_ent, "_avatar_change_source_id", None)
            source = sim.get_entity(src_id) if src_id else None
            if source is not None:
                source._avatar_change_target_id = None
                source.is_unselectable = bool(getattr(source, "_saved_unselectable", False))
                saved_dist = getattr(source, "_saved_distance_remaining", None)
                if saved_dist is not None:
                    source.distance_remaining = float(saved_dist)
                for m in list(me.get_modifiers(source.name)):
                    if "SheepStatus" in m.name:
                        me.remove_modifier(source.name, m.name)
            new_ent.current_hp = 0.0
            new_ent.distance_remaining = 1e12
            if new_ent in sim.entities:
                sim.entities.remove(new_ent)
            if hasattr(sim, "_rebuild_entity_cache"):
                sim._rebuild_entity_cache()
            me.destroy_all_for_entity(new_ent.name)
            me.dispatch_event("OnListenCharacterDie", param_entity_id=new_ent.name)

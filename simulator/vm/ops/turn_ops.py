# coding: utf-8
"""ConfigAbility VM 回合插队、召唤、关卡事件与角色变身算子 Mixin。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...actions import ActionKind, ActionScheduleCategory
from ...entity import Entity
from ...status import StatType
from ..expr import dotnet_hash
from ..loader import CompiledCharacterSpec
from ..target_alias import ExecutionContext
from .predicates import _str_val


class TurnOpsMixin:
    """TurnInsertAbility / CreateServant / CreateBattleEvent / AttachAvatarChange 算子实现。"""

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
        prio = str(task.get("InsertAbilityPriority") or task.get("InsertActionPriority") or "Character_ChainSkill")
        ab_name = _str_val(task.get("AbilityName"))
        if task.get("TargetType") is not None:
            targets = self._resolve_targets(task.get("TargetType"), ctx)
        elif ctx.modifier_owner_id and (
            prio == "MonsterForceKill"
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
            if hasattr(sim.port, "get_active_proxy"):
                proxy_id = sim.port.get_active_proxy(tid)
                if proxy_id:
                    tid = proxy_id
            ent = sim.get_entity(tid)
            allow_limbo = "Limbo" in str(task.get("OwnerAliveState", ""))
            if ent is None or (ent.current_hp <= 0 and not allow_limbo):
                continue
            if getattr(ent, "_avatar_change_target_id", None) is not None and not getattr(ent, "is_enemy", False):
                continue
            is_enemy_caster = bool(getattr(ent, "is_enemy", False))
            if not is_enemy_caster and not sim.port.enemies(tid):
                continue
            if ab_name:
                cat = (
                    ActionScheduleCategory.FOLLOW_UP
                    if prio in ("Character_ChainSkill", "AvatarInsertAttackSelf", "MonsterBuffOthers")
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
                    _is_en: bool = is_enemy_caster,
                ) -> None:
                    sim._action_seq += 1
                    sk_t = "Insert" if _c == ActionScheduleCategory.FOLLOW_UP else "Talent"
                    me = rt.modifier_engine
                    if _tgts:
                        eff_tgts = _tgts
                    elif _is_en:
                        eff_tgts = tuple(
                            e.name for e in sim.entities
                            if not e.is_enemy and not getattr(e, "is_countdown", False) and e.current_hp > 0
                        )
                    else:
                        eff_tgts = tuple(e.name for e in sim.entities if e.is_enemy and e.current_hp > 0)
                    if sk_t == "Insert":
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
                    preempt_follow_up=(prio in ("AvatarBuffSelf", "MonsterChangeState", "MonsterChangePhase")),
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

        robin_spd = float(init_dyn.get(dotnet_hash("BattleEvent_RobinS_00_BaseSpeed"), 0.0) or 0.0)
        if robin_spd > 0.0:
            spd = robin_spd
        elif compiled_be is not None and float(getattr(compiled_be, "effective_speed", 0.0) or 0.0) > 0.0:
            spd = float(compiled_be.effective_speed)
        else:
            spd = 140.0

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
        ab_names: List[str] = []
        param_list: List[float] = []
        if compiled_be is not None:
            ab_names = list(getattr(compiled_be, "ability_list", ()))
            param_list = [float(p) for p in getattr(compiled_be, "param_list", ())]
        if not ab_names:
            try:
                rows = rt.loader._read_excel("BattleEventConfig.json")
            except Exception:
                rows = []
            for row in rows:
                if int(row.get("BattleEventID", 0) or 0) == event_id:
                    ab_names = [str(a) for a in row.get("AbilityList", [])]
                    for p in row.get("ParamList", []):
                        val = p.get("Value", 0.0) if isinstance(p, Mapping) else p
                        param_list.append(float(val or 0.0))
                    break

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

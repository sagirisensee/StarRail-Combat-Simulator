# coding: utf-8
"""ConfigAbility VM Modifier、护盾、驱散、行动延迟与战斗属性修正算子 Mixin。"""

from __future__ import annotations

import math
from typing import Any, List, Mapping, Optional, Set

from ...status import StatType
from ..expr import dotnet_hash
from ..target_alias import ExecutionContext
from .predicates import _str_val


class ModifierOpsMixin:
    """Modifier / Shield / Dispel / ActionDelay / SP / DamageData 相关算子。"""

    def _op_set_modifier_dynamic_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
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

    def _op_set_modifier_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx) if "TargetType" in task else [ctx.modifier_owner_id or ctx.caster_id]
        mname_spec = task.get("ModifierName")
        mname = _str_val(mname_spec)
        mfunc = str(task.get("ModifyFunction", "Set"))
        vtype = str(task.get("ValueType") or "Layer")
        val = self._eval_num(task.get("Value"), ctx, -1.0 if mfunc == "Add" else 0.0)
        if mname == "ParamModifier" and ctx.callback_modifier_instance is not None:
            m_cb = ctx.callback_modifier_instance
            if vtype == "LifeTime":
                if mfunc == "Add":
                    m_cb.life_time = (m_cb.life_time or 0.0) + val
                elif mfunc in ("Sub", "Minus"):
                    m_cb.life_time = max(0.0, (m_cb.life_time or 0.0) - val)
                else:
                    m_cb.life_time = None if val < 0.0 else val
            elif vtype == "Layer":
                if mfunc == "Add":
                    m_cb.layer = max(0, int(round(m_cb.layer + val)))
                elif mfunc in ("Sub", "Minus"):
                    m_cb.layer = max(0, int(round(m_cb.layer - val)))
                else:
                    m_cb.layer = max(0, int(round(val)))
            if vtype == "Layer" and mfunc != "Set" and m_cb.layer <= 0 and "RetainCountZero" not in m_cb.behavior_flags:
                me.destroy_modifier(m_cb)
            return
        for tid in targets:
            mods = [ctx.modifier_instance] if (not mname and ctx.modifier_instance is not None) else me.get_modifiers(tid, mname)
            for m in mods:
                if vtype == "LifeTime":
                    if mfunc == "Add":
                        m.life_time = (m.life_time or 0.0) + val
                    elif mfunc in ("Sub", "Minus"):
                        m.life_time = max(0.0, (m.life_time or 0.0) - val)
                    else:
                        m.life_time = None if val < 0.0 else val
                elif vtype == "Layer":
                    if mfunc == "Add":
                        m.layer = max(0, int(round(m.layer + val)))
                    elif mfunc in ("Sub", "Minus"):
                        m.layer = max(0, int(round(m.layer - val)))
                    else:
                        m.layer = max(0, int(round(val)))
                if vtype == "Layer" and mfunc != "Set" and m.layer <= 0 and "RetainCountZero" not in m.behavior_flags:
                    me.destroy_modifier(m)

    def _op_add_modifier(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        mname_spec = task.get("ModifierName")
        ref_mname = _str_val(task.get("ReferenceModifierName"))
        if isinstance(mname_spec, Mapping) and mname_spec.get("Custom"):
            custom_key = str(mname_spec.get("Key") or "")
            mname = ctx.custom_strings.get(custom_key) or ref_mname
        else:
            mname = _str_val(mname_spec) or ref_mname
        success_tasks = task.get("SuccessTaskList") or ()
        fail_tasks = task.get("FailTaskList") or task.get("FailedTaskList") or ()
        chance_spec = task.get("Chance")
        chance_val: Optional[float] = None
        if chance_spec is not None:
            chance_val = self._eval_num(chance_spec, ctx, 1.0)
            if chance_val <= 0.0 and not fail_tasks:
                return
        life = self._eval_num(task["LifeTime"], ctx) if "LifeTime" in task else None
        cnt_spec = task.get("LayerAddWhenStack") if "LayerAddWhenStack" in task else task.get("Count")
        cnt = int(round(self._eval_num(cnt_spec, ctx, 1.0))) if cnt_spec is not None else None
        max_l = int(round(self._eval_num(task["MaxLayer"], ctx, 1.0))) if "MaxLayer" in task else None
        inherit = str(task.get("InheritCaster", ""))
        alive_only = bool(task.get("AliveOnly", True))
        for tid in targets:
            if alive_only and tid not in ("__LEVEL__", "__LIGHT_TEAM__"):
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
            hit_ok = True
            if chance_val is not None:
                if chance_val <= 0.0:
                    hit_ok = False
                else:
                    caster_ent = sim.get_entity(eff_caster)
                    tgt_ent = sim.get_entity(tid)
                    if (
                        caster_ent is not None
                        and tgt_ent is not None
                        and getattr(caster_ent, "is_enemy", False)
                        and not getattr(tgt_ent, "is_enemy", False)
                    ):
                        hit_provider = getattr(sim, "enemy_debuff_hit_provider", None)
                        hit_res = hit_provider(caster_ent, tgt_ent, mname, chance_val) if callable(hit_provider) else None
                        if hit_res is False:
                            hit_ok = False
                        elif hit_res is None:
                            sm = getattr(sim, "status_mgr", None)
                            eff_res = (
                                sm.calculate_stat(tid, getattr(tgt_ent, "base_effect_res", 0.0), StatType.EFFECT_RES)
                                if sm is not None
                                else float(getattr(tgt_ent, "base_effect_res", 0.0))
                            )
                            atk_ehr = float(getattr(caster_ent, "base_effect_hit_rate", 0.0))
                            if chance_val * (1.0 + atk_ehr) * max(0.0, 1.0 - eff_res) < 0.5:
                                hit_ok = False
                    elif (
                        (success_tasks or fail_tasks)
                        and caster_ent is not None
                        and tgt_ent is not None
                        and not getattr(caster_ent, "is_enemy", False)
                        and getattr(tgt_ent, "is_enemy", False)
                    ):
                        sm = getattr(sim, "status_mgr", None)
                        atk_ehr = (
                            sm.calculate_stat(eff_caster, getattr(caster_ent, "base_effect_hit_rate", 0.0), StatType.EHR)
                            if sm is not None
                            else float(getattr(caster_ent, "base_effect_hit_rate", 0.0))
                        )
                        eff_res = (
                            sm.calculate_stat(tid, getattr(tgt_ent, "base_effect_res", 0.0), StatType.EFFECT_RES)
                            if sm is not None
                            else float(getattr(tgt_ent, "base_effect_res", 0.0))
                        )
                        eff_prob = chance_val * (1.0 + atk_ehr) * max(0.0, 1.0 - eff_res)
                        if eff_prob <= 1e-9:
                            hit_ok = False
                        elif eff_prob < 1.0 - 1e-9:
                            t_prov = getattr(sim, "random_chance_target_provider", None)
                            t_res = t_prov(eff_caster, tid, ctx.ability_name, eff_prob) if callable(t_prov) else None
                            hit_ok = bool(t_res) if t_res is not None else bool(eff_prob >= 0.5)
            succeeded = False
            if hit_ok:
                mod_res = me.add_modifier(
                    owner_id=tid,
                    caster_id=eff_caster,
                    mod_name=mname,
                    ability_name=ctx.ability_name,
                    dynamic_values=task.get("DynamicValues"),
                    life_time=life,
                    count=cnt,
                    max_layer=max_l,
                    ctx=ctx,
                    reference_mod_name=ref_mname,
                    dynamic_strings=task.get("DynamicStrings"),
                )
                succeeded = mod_res is not None
            if succeeded and success_tasks:
                self.execute_tasks(success_tasks, ctx.clone(param_entity_id=tid))
            elif not succeeded and fail_tasks:
                self.execute_tasks(fail_tasks, ctx.clone(param_entity_id=tid))

    def _op_remove_modifier(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
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

    def _op_remove_self_modifier(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        if ctx.modifier_instance is not None:
            self.rt.modifier_engine.destroy_modifier(ctx.modifier_instance)

    def _op_remove_modifier_by_behavior_flag(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        flags: Set[str] = set()
        raw_flags = task.get("ModifierBehaviorFlags")
        if isinstance(raw_flags, list):
            flags.update(str(f) for f in raw_flags if f)
        single_flag = str(task.get("BehaviorFlag", "") or "")
        if single_flag:
            flags.add(single_flag)
        pred = task.get("Predicate")
        for tid in targets:
            if flags:
                for m in list(me.get_modifiers(tid)):
                    if m.behavior_flags & flags:
                        if pred is not None:
                            p_ctx = ctx.clone(
                                param_entity_id=tid,
                                callback_modifier_instance=m,
                                callback_modifier_name=m.name,
                                callback_behavior_flags=frozenset(m.behavior_flags),
                            )
                            if not self.eval_predicate(pred, p_ctx):
                                continue
                        me.destroy_modifier(m)

    def _update_modifier_behavior_flags(self, task: Mapping[str, Any], ctx: ExecutionContext, *, add: bool) -> None:
        """为目标身上指定 Modifier 动态增删 BehaviorFlags（可选按 CasterFilter 过滤）。"""
        me = self.rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        mname = _str_val(task.get("ModifierName"))
        raw_key = "AddBehaviorFlags" if add else "RemoveBehaviorFlags"
        flags = [str(f) for f in (task.get(raw_key) or ()) if f]
        if not flags:
            return
        caster_filter_ids: Optional[Set[str]] = None
        if "CasterFilter" in task:
            caster_filter_ids = set(self._resolve_targets(task.get("CasterFilter"), ctx))
        for tid in targets:
            for m in me.get_modifiers(tid, mname):
                if caster_filter_ids is not None and m.caster_id not in caster_filter_ids:
                    continue
                if add:
                    m.behavior_flags.update(flags)
                else:
                    m.behavior_flags.difference_update(flags)

    def _op_add_behavior_flag_for_modifier(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        self._update_modifier_behavior_flags(task, ctx, add=True)

    def _op_remove_behavior_flag_for_modifier(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        self._update_modifier_behavior_flags(task, ctx, add=False)

    def _op_stack_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        prop_name = str(task.get("Property", ""))
        val = self._eval_num(task.get("PropertyValue"), ctx, 0.0)
        is_conv = bool(task.get("IsConvert", False))
        is_refresh = bool(task.get("IsRefresh", False))
        if ctx.modifier_instance is not None:
            self.rt.modifier_engine.stack_property(ctx.modifier_instance, prop_name, val, is_convert=is_conv, is_refresh=is_refresh)

    def _op_dispel_status(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
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
                me.destroy_modifier(m)

    def _op_init_shield(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
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

    def _op_remove_shield(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        if ctx.modifier_instance is not None:
            ctx.modifier_instance.shield_value = 0.0
            ctx.modifier_instance.shield_max = 0.0
        for tid in targets:
            me.sync_entity_shield(tid)

    def _op_modify_shield(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        t = task.get("$type", "")
        targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        mod_names = [str(m) for m in (task.get("ShieldModifiers") or []) if m]
        modify_op = str(task.get("ModifyOp") or "Add")
        delta = self._eval_num(task.get("FormulaValue"), ctx, 0.0)
        for tid in targets:
            if mod_names:
                matched_mods = [m for m in me.get_modifiers(tid) if m.name in mod_names]
            elif ctx.modifier_instance is not None and ctx.modifier_instance.owner_id == tid:
                matched_mods = [ctx.modifier_instance]
            else:
                matched_mods = []
            changed_delta = 0.0
            for m in matched_mods:
                if t == "RPG.GameCore.ModifyShieldMax":
                    if modify_op == "Set":
                        m.shield_max = max(0.0, delta)
                    else:
                        m.shield_max = max(0.0, m.shield_max + delta)
                else:
                    old_v = m.shield_value
                    if modify_op == "Set":
                        new_v = max(0.0, delta)
                    else:
                        new_v = max(0.0, m.shield_value + delta)
                    if m.shield_max > 0.0:
                        new_v = min(m.shield_max, new_v)
                    m.shield_value = new_v
                    changed_delta += new_v - old_v
            if t == "RPG.GameCore.ModifyShield":
                me.sync_entity_shield(tid)
                if abs(changed_delta) > 1e-12:
                    me.dispatch_event(
                        "OnListenShieldChange",
                        param_entity_id=tid,
                        change_value=changed_delta,
                    )

    def _op_define_hp_shared_group(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        mains = self._resolve_targets(task.get("MainTarget"), ctx)
        subs = self._resolve_targets(task.get("SubTargets"), ctx)
        if mains:
            main_id = mains[0]
            for sid in subs:
                if sid and sid != main_id:
                    self.rt.hp_shared_groups[sid] = main_id

    def _op_set_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        from ...effects import sync_hp_shared_subtargets

        sim = self.rt.sim
        me = self.rt.modifier_engine
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
                        if ent.current_hp > 0.0:
                            setattr(ent, "_vm_limbo_pending", False)
                            setattr(ent, "_vm_phase_change_pending", False)
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

    def _op_modify_heal_data(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        if ctx.heal_data is not None:
            for k in ("HealRatioAdded", "HealPercentage", "ModifyValue"):
                if k in task:
                    ctx.heal_data[k] = ctx.heal_data.get(k, 0.0) + self._eval_num(task[k], ctx, 0.0)
            if "Healer_HealRatio" in task:
                ctx.heal_data["HealRatioAdded"] = ctx.heal_data.get("HealRatioAdded", 0.0) + self._eval_num(
                    task["Healer_HealRatio"], ctx, 0.0
                )

    def _op_modify_damage_data(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        if ctx.damage_data is not None:
            for k, v in task.items():
                if k in ("$type", "TargetType"):
                    continue
                if isinstance(v, (dict, int, float)):
                    if k in (
                        "AttackData_ConstFinalDamage",
                        "AttackData_ElationPointNum",
                        "AttackData_EnableElationPointMultiplier",
                    ):
                        ctx.damage_data[k] = self._eval_num(v, ctx, 0.0)
                    else:
                        ctx.damage_data[k] = ctx.damage_data.get(k, 0.0) + self._eval_num(v, ctx, 0.0)

    def _op_modify_team_boost_point(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
        mfunc = str(task.get("ModifyFunction", "Add"))
        mval = int(round(self._eval_num(task.get("ModifyValue"), ctx, 0.0)))
        delta = mval if mfunc == "Add" else (-mval if mfunc in ("Sub", "Minus") else 0)
        if delta != 0:
            sim.port.change_sp(ctx.caster_id, delta, reason=ctx.ability_name or "VM_Skill")
            me.dispatch_event("OnSPChange", owner_id=ctx.caster_id, change_value=float(delta))

    def _op_modify_special_sp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
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
            old_ep = float(ent.energy)
            if "SetValue" in task:
                val = self._eval_num(task.get("SetValue"), ctx, float(ent.energy))
                ent.energy = max(0.0, min(max_ep, val)) if max_ep > 0.0 else max(0.0, val)
            else:
                delta = self._eval_num(task.get("FixedAddValue") or task.get("AddValue"), ctx, 0.0)
                if "AddMaxSPRatio" in task:
                    delta += max_ep * self._eval_num(task.get("AddMaxSPRatio"), ctx, 0.0)
                new_ep = float(ent.energy) + delta
                ent.energy = max(0.0, min(max_ep, new_ep)) if max_ep > 0.0 else max(0.0, new_ep)
            diag_cb = getattr(sim, "timeline_diag_cb", None)
            if callable(diag_cb):
                diag_cb("SSP", f"{ep_tid} {old_ep:g}->{float(ent.energy):g} (ab={ctx.ability_name})")
            if me._apc_defer_depth > 0:
                me._dirty_apc_entities.add(ep_tid)
            else:
                me.check_property_changes(ep_tid)

    def _filter_action_delay_unlocked(self, targets: List[str], ctx: ExecutionContext) -> List[str]:
        sim = self.rt.sim
        unlocked: List[str] = []
        for tid in targets:
            ent = sim.get_entity(tid)
            if (
                ent is not None
                and getattr(ent, "_action_delay_locked", False)
                and ctx.caster_id not in getattr(ent, "_action_delay_lock_whitelist", ())
            ):
                continue
            unlocked.append(tid)
        return unlocked

    def _op_modify_action_delay(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._filter_action_delay_unlocked(self._resolve_targets(task.get("TargetType"), ctx), ctx)
        if not targets:
            return
        cur_turn = getattr(sim, "_current_turn_entity", None)
        def _requeue_ready_if_zero(tid: str) -> None:
            ent = sim.get_entity(tid)
            rq = getattr(sim, "_ready_queue", None)
            nat = getattr(sim, "_natural_due_names", None)
            if (
                ent is not None
                and float(getattr(ent, "distance_remaining", 0.0) or 0.0) <= 1e-6
                and isinstance(rq, list)
                and tid in rq
                and (not isinstance(nat, set) or tid not in nat)
                and not getattr(sim, "_in_retarget_ready_batch", False)
            ):
                rq.remove(tid)
                sim.notify_entity_ready(tid, allow_jump_natural=False)

        if task.get("AddNormalizedValue") is not None:
            val = self._eval_num(task.get("AddNormalizedValue"), ctx, 0.0)
            for tid in targets:
                if val <= -1.0 + 1e-6 and not getattr(sim, "_in_retarget_ready_batch", False):
                    if cur_turn is not None and cur_turn.name == tid:
                        setattr(cur_turn, "_vm_immediate_jump", True)
                    sim.port.set_distance(tid, 0.0)
                elif abs(val) <= 1e-9:
                    _requeue_ready_if_zero(tid)
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
                elif abs(val) <= 1e-9:
                    _requeue_ready_if_zero(tid)
                elif val < 0:
                    sim.port.advance(ctx.caster_id, tid, abs(val))
                elif val > 0:
                    sim.port.delay(ctx.caster_id, tid, val)

    def _op_reset_action_delay(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._filter_action_delay_unlocked(self._resolve_targets(task.get("TargetType"), ctx), ctx)
        skip_turn = bool(task.get("SkipTargetTurn", False))
        cur_turn = getattr(sim, "_current_turn_entity", None)
        for tid in targets:
            sim.port.set_distance(tid, 10000.0)
            if skip_turn and cur_turn is not None and cur_turn.name == tid:
                setattr(cur_turn, "_vm_skip_current_turn", True)
                setattr(cur_turn, "_vm_skip_reset_dist_on_turn_end", True)

    def _op_set_action_delay(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._filter_action_delay_unlocked(self._resolve_targets(task.get("TargetType"), ctx), ctx)
        if not targets:
            return
        has_norm = task.get("NormalizedValue") is not None
        val_spec = task.get("NormalizedValue")
        if val_spec is None:
            val_spec = task.get("DelayValue") if "DelayValue" in task else task.get("Value")
        val = self._eval_num(val_spec, ctx, 1.0)
        cur_turn = getattr(sim, "_current_turn_entity", None)
        multi_target = len(targets) > 1
        multi_batch: List[str] = []
        multi_prev_av: dict[str, float] = {}
        for tid in targets:
            if val <= 1e-6:
                if cur_turn is not None and cur_turn.name == tid:
                    setattr(cur_turn, "_vm_immediate_jump", True)
                ent = sim.get_entity(tid)
                rq = getattr(sim, "_ready_queue", None)
                if ent is not None and isinstance(rq, list):
                    prev_dist = float(getattr(ent, "distance_remaining", 0.0) or 0.0)
                    prev_spd = float(getattr(ent, "speed", 0.0) or 0.0)
                    prev_av = (prev_dist / prev_spd) if prev_spd > 0.0 else float("inf")
                    ent.distance_remaining = 0.0
                    if tid not in rq and (ent.current_hp > 0 or getattr(ent, "is_infinite_hp", False)):
                        nat = getattr(sim, "_natural_due_names", None)
                        if isinstance(nat, set):
                            nat.discard(tid)
                        if multi_target:
                            multi_prev_av.setdefault(tid, prev_av)
                            multi_batch.append(tid)
                            batch_set = set(multi_batch)
                            rest = [name for name in rq if name not in batch_set]
                            batch_in_rq = [name for name in rq if name in batch_set] + [tid]
                            batch_in_rq.sort(
                                key=lambda name: (
                                    round(float(multi_prev_av.get(name, 0.0)), 4),
                                    -float(getattr(sim.get_entity(name), "speed", 0.0) or 0.0),
                                    int(getattr(sim.get_entity(name), "_spawn_seq", 0) or 0),
                                )
                            )
                            rq[:] = batch_in_rq + rest
                        else:
                            batch_ids = getattr(ctx, "_set_delay_zero_batch", None)
                            if batch_ids is None:
                                batch_ids = []
                                setattr(ctx, "_set_delay_zero_batch", batch_ids)
                            batch_prev_av = getattr(ctx, "_set_delay_zero_prev_av", None)
                            if batch_prev_av is None:
                                batch_prev_av = {}
                                setattr(ctx, "_set_delay_zero_prev_av", batch_prev_av)
                            batch_prev_av.setdefault(tid, prev_av)
                            batch_ids.append(tid)
                            batch_set = set(batch_ids)
                            rest = [name for name in rq if name not in batch_set]
                            batch_in_rq = [name for name in rq if name in batch_set] + [tid]
                            batch_in_rq.sort(
                                key=lambda name: (
                                    round(float(batch_prev_av.get(name, 0.0)), 4),
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

    def _op_modify_current_skill_delay_cost(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
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

    def _op_modify_elation_points(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        val = self._eval_num(task.get("AJHHCOHFIFA"), ctx, 0.0)
        op = str(task.get("FKCKKFALPBK", ""))
        src = str(ctx.ability_name or ctx.caster_id or "")
        if op == "DADCFBHGLOH":
            self.rt.modify_elation_points(val, mode="set", source=src)
        elif op == "NOKLNMBGACJ":
            self.rt.modify_elation_points(-val, mode="add", source=src)
        else:
            self.rt.modify_elation_points(val, mode="add", source=src)

    def _op_set_target_unique_name(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        un_obj = task.get("UniqueName")
        uname = str(un_obj.get("RawString", "")) if isinstance(un_obj, Mapping) else _str_val(un_obj)
        if uname and targets:
            self.rt.named_targets[uname] = list(targets)

    def _op_release_target_unique_name(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        un_obj = task.get("UniqueName")
        uname = str(un_obj.get("RawString", "")) if isinstance(un_obj, Mapping) else _str_val(un_obj)
        if uname:
            self.rt.named_targets.pop(uname, None)

    def _op_set_entity_action_state(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        active = bool(task.get("ActionState", True))
        uname = str(task.get("UniqueName") or "__default__")
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is None:
                continue
            keys = getattr(ent, "_action_state_false_keys", None)
            if keys is None:
                keys = set()
                setattr(ent, "_action_state_false_keys", keys)
            if not active:
                keys.add(uname)
                ent.distance_remaining = 1e12
            else:
                keys.discard(uname)
                if not keys and ent.distance_remaining >= 1e11:
                    ent.distance_remaining = 10000.0

    def _op_set_control_skill_mapping(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sk_key = str(task.get("SkillTriggerKey") or "")
        ctrl_type = str(task.get("ControlSkillType") or "ControlSkill01")
        targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        for tid in targets:
            if tid:
                if sk_key:
                    self.rt.control_skill_mapping[(tid, ctrl_type)] = sk_key
                else:
                    self.rt.control_skill_mapping.pop((tid, ctrl_type), None)

    def _op_add_common_skill_pool(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        """执行官方 EOCFKGFAPHJ：从 ConfigCommonSkillPool 注册通用技能槽（SkillID / EntryAbility / UsableConditions）。"""
        pool_name = str(task.get("MBDAKKKPKCG") or "")
        if not pool_name:
            return
        pool = self.rt.loader.get_common_skill_pool(pool_name)
        if not pool:
            return
        tgt_spec = task.get("TargetType") or task.get("HILNFHCPEAD")
        targets = self._resolve_targets(tgt_spec, ctx) if tgt_spec is not None else [ctx.modifier_owner_id or ctx.caster_id]
        sim = self.rt.sim
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            ent = sim.get_entity(tid)
            kit = getattr(ent, "kit", None) if ent is not None else None
            for sk_entry in pool.get("SkillList") or ():
                if not isinstance(sk_entry, Mapping):
                    continue
                cfg = sk_entry.get("Config") or {}
                sk_ab = sk_entry.get("SkillAbility") or {}
                sk_name = str(cfg.get("Name") or sk_ab.get("Skill") or "")
                if not sk_name:
                    continue
                entry_ab = str(cfg.get("EntryAbility") or "")
                ab_list = list(sk_ab.get("AbilityList") or ())
                if not entry_ab and ab_list:
                    entry_ab = str(ab_list[0])
                t_info = dict(cfg.get("TargetInfo") or {})
                sk_id = int(sk_entry.get("SkillID") or 0)
                usable_conds = list(cfg.get("UsableConditions") or ())
                self.rt.common_skills[(tid, sk_name)] = {
                    "pool_name": pool_name,
                    "skill_id": sk_id,
                    "skill_name": sk_name,
                    "skill_type": str(cfg.get("SkillType") or "Ultra"),
                    "entry_ability": entry_ab,
                    "ability_list": ab_list,
                    "target_info": t_info,
                    "usable_conditions": usable_conds,
                }
                if kit is not None and hasattr(kit, "_skill_abilities"):
                    kit._skill_abilities[sk_name] = ab_list or ([entry_ab] if entry_ab else [])
                    if entry_ab and hasattr(kit, "_skill_entries"):
                        kit._skill_entries[sk_name] = entry_ab
                    if hasattr(kit, "_skill_target_infos"):
                        kit._skill_target_infos[sk_name] = t_info

    def _op_remap_control_skill_mapping(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        """执行官方 MOPOKJECALI：将控制技能槽位映射为指定技能或通用技能键。"""
        ctrl_type = str(task.get("GFNJJEFJKPD") or "ControlSkill03")
        sk_key = str(task.get("IPOJMHGKIEH") or "")
        tgt_spec = task.get("TargetType") or task.get("HILNFHCPEAD")
        targets = self._resolve_targets(tgt_spec, ctx) if tgt_spec is not None else [ctx.modifier_owner_id or ctx.caster_id]
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            if sk_key:
                self.rt.control_skill_mapping[(tid, ctrl_type)] = sk_key
            else:
                self.rt.control_skill_mapping.pop((tid, ctrl_type), None)

    def _op_reset_control_skill_mapping(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        """执行官方 DGAOCHGKJKJ：重置控制技能槽位重映射。"""
        if not task.get("JHLNDMMBMJP", False):
            return
        tgt_spec = task.get("TargetType") or task.get("HILNFHCPEAD")
        targets = self._resolve_targets(tgt_spec, ctx) if tgt_spec is not None else [ctx.modifier_owner_id or ctx.caster_id]
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            to_del = [
                k for k, v in self.rt.control_skill_mapping.items()
                if k[0] == tid and (tid, v) in self.rt.common_skills
            ]
            for k in to_del:
                self.rt.control_skill_mapping.pop(k, None)

    def _op_attack_data(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        tgt_spec = task.get("TargetType") or {"Alias": "AbilityTargetEntity"}
        self._execute_damage({"TargetType": tgt_spec, "AttackProperty": task}, ctx)

    def _op_modify_current_modifier_dynamic_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        mod = ctx.modifier_instance or ctx.callback_modifier_instance
        if mod is None:
            return
        key_h = dotnet_hash(_str_val(task.get("FHLJGDGMMHK")))
        val = self._eval_num(task.get("KHBBNDBJAFK"), ctx, 0.0)
        mfunc = str(task.get("FKCKKFALPBK") or "Set")
        old_val = float(mod.dynamic_values.get(key_h, 0.0))
        if mfunc == "Add":
            new_val = old_val + val
        elif mfunc in ("Sub", "Minus"):
            new_val = old_val - val
        else:
            new_val = val
        mod.dynamic_values[key_h] = float(new_val)
        me.check_dynamic_value_changes(mod.owner_id, key_h, old_val, float(new_val), modifier=mod)

    def _op_modify_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if "TargetType" in task
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        prop = str(task.get("Property") or "")
        mfunc = str(task.get("ModifyFunction") or "Add")
        val = self._eval_num(task.get("ModifyValue") if "ModifyValue" in task else task.get("Value"), ctx, 0.0)
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            ent = sim.get_entity(tid)
            if ent is None:
                continue
            if prop == "CurExtraSpecialSP":
                cur_val = float(getattr(ent, "extra_special_sp", 0.0) or 0.0)
                if mfunc == "Set":
                    nxt = val
                elif mfunc in ("Sub", "Minus"):
                    nxt = cur_val - val
                else:
                    nxt = cur_val + val
                max_extra = me.get_entity_property(tid, "MaxExtraSpecialSP")
                nxt = max(0.0, min(max_extra, nxt)) if max_extra > 0.0 else max(0.0, nxt)
                setattr(ent, "extra_special_sp", float(nxt))
            elif ctx.modifier_instance is not None and ctx.modifier_instance.owner_id == tid:
                cur_val = float(ctx.modifier_instance.properties.get(prop, 0.0))
                if mfunc == "Set":
                    delta = val - cur_val
                elif mfunc in ("Sub", "Minus"):
                    delta = -val
                else:
                    delta = val
                me.stack_property(ctx.modifier_instance, prop, delta)
                continue
            if me._apc_defer_depth > 0:
                me._dirty_apc_entities.add(tid)
            else:
                me.check_property_changes(tid)

    def _op_modify_skill_property_by_name(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if "TargetType" in task
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        sk_name = _str_val(task.get("SkillName"))
        props = task.get("Properties") or ()
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            ov_list = self.rt.skill_property_overrides.setdefault(tid, [])
            for p in props:
                if not isinstance(p, Mapping):
                    continue
                prop_type = str(p.get("PropertyType") or "")
                op = str(p.get("OperatorType") or "Set")
                if op == "Unset":
                    ov_list[:] = [
                        ov
                        for ov in ov_list
                        if not (
                            ov.get("PropertyType") == prop_type
                            and (not sk_name or ov.get("SkillName") == sk_name)
                        )
                    ]
                    continue
                ov_list.append(
                    {
                        "SkillName": sk_name,
                        "PropertyType": prop_type,
                        "OperatorType": op,
                        "Value": self._eval_num(p.get("Value"), ctx, 0.0) if "Value" in p else 0.0,
                    }
                )
            if not ov_list:
                self.rt.skill_property_overrides.pop(tid, None)

    def _op_set_skill_tag(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = (
            self._resolve_targets(task.get("TargetType") or task.get("HILNFHCPEAD"), ctx)
            if ("TargetType" in task or "HILNFHCPEAD" in task)
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        sk_key = str(task.get("CIDCEJCGOGB") or "")
        tag_items = task.get("DCLGGMAEMAO") or ()
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            tag_map = self.rt.entity_skill_tags.setdefault(tid, {})
            tag_set = tag_map.setdefault(sk_key, set())
            rem_set = self.rt.entity_removed_skill_tags.get(tid, {}).get(sk_key)
            for tg in tag_items:
                if isinstance(tg, Mapping):
                    pair = (int(tg.get("EnumIndex", 0) or 0), int(tg.get("Value", 0) or 0))
                    tag_set.add(pair)
                    if rem_set is not None:
                        rem_set.discard(pair)

    def _op_remove_skill_tag(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = (
            self._resolve_targets(task.get("TargetType") or task.get("HILNFHCPEAD"), ctx)
            if ("TargetType" in task or "HILNFHCPEAD" in task)
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        sk_key = str(task.get("CIDCEJCGOGB") or "")
        tag_items = task.get("DCLGGMAEMAO") or ()
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            tag_set = self.rt.entity_skill_tags.get(tid, {}).get(sk_key)
            rem_map = self.rt.entity_removed_skill_tags.setdefault(tid, {})
            rem_set = rem_map.setdefault(sk_key, set())
            for tg in tag_items:
                if isinstance(tg, Mapping):
                    pair = (int(tg.get("EnumIndex", 0) or 0), int(tg.get("Value", 0) or 0))
                    if tag_set is not None:
                        tag_set.discard(pair)
                    rem_set.add(pair)

    def _op_modify_team_boost_point_max(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        mfunc = str(task.get("ModifyFunction", "Add"))
        mval = int(round(self._eval_num(task.get("ModifyValue"), ctx, 0.0)))
        cur_max = int(sim.sp.max_sp)
        if mfunc == "Set":
            new_max = mval
        elif mfunc == "Add":
            new_max = cur_max + mval
        elif mfunc in ("Sub", "Minus"):
            new_max = cur_max - mval
        else:
            raise NotImplementedError(f"Unsupported ModifyTeamBoostPointMax ModifyFunction: {mfunc!r}")
        sim.port.set_sp_cap(max(1, new_max))

    def _op_init_team_block(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rate = max(0.0, min(1.0, self._eval_num(task.get("OJGEEODEMMO"), ctx, 1.0)))
        val = max(0.0, self._eval_num(task.get("MCNPMDPMCKM"), ctx, 0.0))
        mod = ctx.modifier_instance
        if mod is not None:
            setattr(mod, "team_block_rate", rate)
            setattr(mod, "team_block_max", val)
            setattr(mod, "team_block_cur", val)
            setattr(mod, "team_block_predicate", task.get("GODIODIIBNC"))
            mod.dynamic_values[dotnet_hash("MDF_TeamBlockValue")] = val

    def _op_modify_team_block(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        mfunc = str(task.get("HJOALLKGNGP", "Set"))
        val = self._eval_num(task.get("MIOOGEBNBGL"), ctx, 0.0)
        mod = ctx.modifier_instance
        if mod is not None:
            cur = float(getattr(mod, "team_block_cur", 0.0))
            if mfunc == "Add":
                new_val = max(0.0, cur + val)
            elif mfunc in ("Sub", "Minus"):
                new_val = max(0.0, cur - val)
            else:
                new_val = max(0.0, val)
            setattr(mod, "team_block_cur", new_val)
            setattr(mod, "team_block_max", max(float(getattr(mod, "team_block_max", 0.0)), new_val))
            diag_cb = getattr(self.rt.sim, "timeline_diag_cb", None)
            if callable(diag_cb):
                diag_cb("TBLK", f"mod {mfunc} val={val:.2f} {cur:.2f}->{new_val:.2f} mod={mod.name}")
            self.rt.set_dynamic_value(mod.owner_id, dotnet_hash("MDF_TeamBlockValue"), new_val, modifier=mod)

    def _op_consume_elation_echo_point(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        raw_amt = self._eval_num(task.get("AHCBJENOJHJ"), ctx, 0.0)
        amt = max(0.0, raw_amt)
        if task.get("NLIAEJNBEKP") is False and amt > 0.0:
            # 珍珠 EchoBlock 传 NLIAEJNBEKP=false：按四舍五入消耗整点意气
            amt = float(math.floor(amt + 0.5))
        if amt <= 0.0:
            return
        targets = self._resolve_targets(task.get("HILNFHCPEAD"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        target_mname = str(task.get("EMFAHIBNJMP") or "")
        echo_hash = dotnet_hash("ElationEchoPoint")
        me = self.rt.modifier_engine
        diag_cb = getattr(self.rt.sim, "timeline_diag_cb", None)
        for tid in targets:
            remaining = amt
            for m in list(me.get_modifiers(tid)):
                if m._destroyed:
                    continue
                if target_mname:
                    if m.name != target_mname:
                        continue
                elif "ElationEchoPoint" not in m.behavior_flags:
                    continue
                cur_m = float(m.dynamic_values.get(echo_hash, m.properties.get("ElationEchoPoint", 0.0)))
                if cur_m <= 0.0:
                    continue
                take = min(cur_m, remaining)
                new_m = max(0.0, cur_m - take)
                remaining -= take
                if callable(diag_cb):
                    src_m = ctx.modifier_instance
                    dyn_info = ""
                    if src_m is not None:
                        dv = src_m.dynamic_values
                        echo_d = dv.get(dotnet_hash("MDF_Echo"))
                        blk_d = dv.get(dotnet_hash("MDF_TeamBlockValue"))
                        per_d = dv.get(dotnet_hash("MDF_BlockPerEcho"))
                        if echo_d is not None or blk_d is not None or per_d is not None:
                            dyn_info = f" echo={echo_d} blk={blk_d} per={per_d}"
                    diag_cb(
                        "ECHO_C",
                        f"target={tid} raw={raw_amt:.4f} amt={amt:.4f} flag={task.get('NLIAEJNBEKP')} mod={m.name} {cur_m:g}->{new_m:g}{dyn_info}",
                    )
                self.rt.set_dynamic_value(tid, echo_hash, new_m, modifier=m)
                if "ElationEchoPoint" in m.properties and abs(float(m.properties.get("ElationEchoPoint", 0.0)) - new_m) > 1e-9:
                    m.properties["ElationEchoPoint"] = new_m
                    me.check_property_changes(tid)
                if new_m <= 1e-9 and not m._destroyed:
                    me.destroy_modifier(m)
                if remaining <= 1e-9:
                    break

    def _op_modify_elation_echo_add_data(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        pending = getattr(self.rt, "_pending_elation_echo_add", None)
        if not isinstance(pending, dict):
            return
        if "MFIBFJPLCOG" in task:
            pending["flag"] = bool(task.get("MFIBFJPLCOG"))
        if "EIMIIHEDKFM" in task:
            pending["mult"] = float(pending.get("mult", 1.0)) * self._eval_num(task.get("EIMIIHEDKFM"), ctx, 1.0)
        if "PPBNKKKIIIN" in task:
            pending["bonus"] = float(pending.get("bonus", 0.0)) + self._eval_num(task.get("PPBNKKKIIIN"), ctx, 0.0)

    def _op_modify_entity_boost_point(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = (
            self._resolve_targets(task["TargetType"], ctx)
            if "TargetType" in task
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        mfunc = str(task.get("ModifyFunction") or "Set")
        val = self._eval_num(task.get("ModifyValue"), ctx, 0.0)
        for tid in targets:
            if not tid or tid == "__LEVEL__":
                continue
            cur = float(self.rt.entity_boost_points.get(tid, 0.0))
            if mfunc == "Set":
                new_val = max(0.0, val)
            elif mfunc == "Add":
                new_val = max(0.0, cur + val)
            elif mfunc == "Sub":
                new_val = max(0.0, cur - val)
            else:
                raise NotImplementedError(f"Unsupported ModifyEntityBoostPoint ModifyFunction: {mfunc!r}")
            self.rt.entity_boost_points[tid] = new_val
            diag_cb = getattr(self.rt.sim, "timeline_diag_cb", None)
            if callable(diag_cb):
                diag_cb("SP", f"EBP {tid} {mfunc} {val:g} -> {new_val:g}")
            self.rt.modifier_engine.check_property_changes(tid)

    _DOT_CUSTOM_EVENT_FLAGS = {
        1: None,
        2: "STAT_DOT_Burn",
        3: "STAT_DOT_Electric",
        4: "STAT_DOT_Poison",
        5: "STAT_DOT_Bleed",
        8: "CustomEvent_MonsterChangePhaseTrigger",
    }

    def _op_trigger_modifier_custom_event(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        if not targets:
            return
        ev_spec = task.get("EventType") or {}
        enum_idx = int(ev_spec.get("EnumIndex", 4) or 4) if isinstance(ev_spec, Mapping) else 4
        ev_val = int(ev_spec.get("Value", 1) or 1) if isinstance(ev_spec, Mapping) else 1
        dyn_key = str(task.get("DynamicKey") or "")
        key_hash = dotnet_hash(dyn_key) if dyn_key else 0
        dyn_val = self._eval_num(task.get("Value"), ctx, 1.0) if "Value" in task else None
        req_flag = self._DOT_CUSTOM_EVENT_FLAGS.get(ev_val) if enum_idx == 4 else None

        sim = self.rt.sim
        for tid in targets:
            tgt_ent = sim.get_entity(tid)
            if (
                tgt_ent is not None
                and float(getattr(tgt_ent, "current_hp", 0.0)) <= 0.0
                and not getattr(tgt_ent, "is_infinite_hp", False)
                and not getattr(tgt_ent, "_in_deathrattle_limbo", False)
            ):
                continue
            mods = list(me.get_modifiers(tid))
            if enum_idx == 4:
                mods.sort(
                    key=lambda m: 1
                    if ((m.config.get("UIConfig") or {}).get("ModifierUIPriority") == "DealDamageBlackSwan")
                    else 0
                )
            for mod in mods:
                if mod._destroyed:
                    continue
                if enum_idx == 4:
                    if ev_val == 1:
                        if not any(f == "STAT_DOT" or f.startswith("STAT_DOT_") for f in mod.behavior_flags):
                            continue
                    else:
                        if not req_flag or req_flag not in mod.behavior_flags:
                            continue
                has_cb = any(
                    isinstance(cb, Mapping) and cb.get("Event") == "OnCustomEvent"
                    for cb in mod.config.get("_CallbackList", ())
                )
                if not has_cb:
                    continue
                prev_had = False
                prev_val = 0.0
                if key_hash and dyn_val is not None:
                    prev_had = key_hash in mod.dynamic_values
                    prev_val = mod.dynamic_values.get(key_hash, 0.0)
                    mod.dynamic_values[key_hash] = dyn_val
                cb_ctx = ExecutionContext(
                    runtime=self.rt,
                    caster_id=mod.caster_id,
                    ability_name=mod.ability_name,
                    modifier_owner_id=mod.owner_id,
                    modifier_instance=mod,
                    param_entity_id=tid,
                    param_entity2_id=ctx.caster_id,
                    custom_strings=dict(mod.custom_strings),
                )
                try:
                    me.dispatch_modifier_callbacks(mod, "OnCustomEvent", cb_ctx)
                finally:
                    if key_hash and dyn_val is not None and not mod._destroyed:
                        if prev_had:
                            mod.dynamic_values[key_hash] = prev_val
                        else:
                            mod.dynamic_values.pop(key_hash, None)

    def _op_attach_skill_type_disable(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        types = [str(x) for x in (task.get("Types") or ()) if x]
        if not types:
            return
        if ctx.modifier_instance is not None:
            ctx.modifier_instance._disabled_skill_types.update(types)
        else:
            targets = (
                self._resolve_targets(task.get("TargetType"), ctx)
                if task.get("TargetType") is not None
                else [ctx.modifier_owner_id or ctx.caster_id]
            )
            disabled_map = getattr(self.rt, "_direct_skill_type_disables", None)
            if disabled_map is None:
                disabled_map = {}
                setattr(self.rt, "_direct_skill_type_disables", disabled_map)
            for tid in targets:
                if tid:
                    disabled_map.setdefault(tid, set()).update(types)

    def _op_attach_entity_unselectable(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        if ctx.modifier_instance is not None:
            ctx.modifier_instance._attached_unselectable = True
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if task.get("TargetType") is not None
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        for tid in targets:
            ent = sim.get_entity(tid) if tid and tid != "__LEVEL__" else None
            if ent is not None:
                ent.is_unselectable = True
                if ctx.modifier_instance is None:
                    setattr(ent, "_static_unselectable", True)

    def _op_lock_action_delay_change(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        tgt_spec = task.get("LockTargetType") or task.get("TargetType")
        targets = (
            self._resolve_targets(tgt_spec, ctx)
            if tgt_spec is not None
            else ([ctx.modifier_owner_id] if ctx.modifier_owner_id else [])
        )
        is_lock = bool(task.get("IsLock", True))
        wl_spec = task.get("WhitelistSourceEntity")
        wl_ids = set(self._resolve_targets(wl_spec, ctx)) if wl_spec is not None else set()
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is None:
                continue
            if is_lock:
                ent._action_delay_locked = True
                ent._action_delay_lock_whitelist = set(wl_ids)
                if ctx.modifier_instance is not None:
                    setattr(ctx.modifier_instance, "_applied_lock_action_delay", True)
            else:
                has_other_lock = any(
                    not m._destroyed
                    and (ctx.modifier_instance is None or m.uid != ctx.modifier_instance.uid)
                    and getattr(m, "_applied_lock_action_delay", False)
                    for m in self.rt.modifier_engine.get_modifiers(tid)
                )
                if not has_other_lock:
                    ent._action_delay_locked = False
                    ent._action_delay_lock_whitelist = set()

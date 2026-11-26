# coding: utf-8
"""ConfigAbility VM 动态变量、实体参数与属性重置算子 Mixin。"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from ..expr import dotnet_hash
from ..target_alias import ExecutionContext
from .predicates import _str_val


class DynamicOpsMixin:
    """DefineDynamicValue / SetDynamicValue* / SetDynamicEntityParam / IJJGPIPMNAE / ReinitProperty 算子。"""

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
        if scope == "ContextTaskTemplate":
            store = ctx.template_dynamics if ctx.template_dynamics is not None else ctx.local_dynamics
            store[key_h] = float(value)
            return
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

    def _op_define_dynamic_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
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

    def _op_set_dynamic_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        val = self._eval_num(task.get("Value"), ctx, 0.0)
        self._write_dyn(task, ctx, key_h, val)

    def _op_set_dynamic_value_in_range(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        lo = self._eval_num(task.get("Min"), ctx, 0.0)
        hi = self._eval_num(task.get("Max"), ctx, lo)
        if lo > hi:
            lo, hi = hi, lo
        if "Value" in task:
            val = max(lo, min(hi, self._eval_num(task.get("Value"), ctx, lo)))
        else:
            val = 0.5 * (lo + hi)
        self._write_dyn(task, ctx, key_h, val)

    def _op_set_dynamic_value_by_change_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        val = float(getattr(ctx, "change_value", 0.0) or 0.0)
        self._write_dyn(task, ctx, key_h, val)

    def _op_set_dynamic_value_by_add_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_str = _str_val(task.get("DynamicKey") or task.get("Key"))
        key_h = dotnet_hash(key_str)
        delta = self._eval_num(task.get("AddValue") or task.get("Value"), ctx, 0.0)
        target_id = self._dyn_scope_entity(task, ctx)
        cur = self.rt.get_dynamic_value(target_id, key_h, ability_name=ctx.ability_name, local_ctx=ctx)
        nxt = cur + delta
        if "Min" in task:
            nxt = max(self._eval_num(task["Min"], ctx, nxt), nxt)
        if "Max" in task:
            nxt = min(self._eval_num(task["Max"], ctx, nxt), nxt)
        self._write_dyn(task, ctx, key_h, nxt)

    def _op_set_dynamic_value_by_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        t = task.get("$type", "")
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        read_spec = task.get("ReadTargetType") or {"Alias": "ModifierOwnerEntity"}
        prop_name = "HPRatio" if t == "RPG.GameCore.SetDynamicValueByHPRatio" else str(task.get("Value", ""))
        is_snap = isinstance(read_spec, Mapping) and read_spec.get("Alias") == "SnapshotPropertyEntity"
        val: Optional[float] = None
        if is_snap and ctx.modifier_instance is not None:
            live_caster = self.rt.sim.get_entity(ctx.modifier_instance.caster_id)
            if live_caster is not None and getattr(live_caster, "current_hp", 0.0) > 0.0:
                val = me.get_entity_property(ctx.modifier_instance.caster_id, prop_name)
            else:
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

    def _op_set_dynamic_value_by_copying(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        me = rt.modifier_engine
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
            mod_target = None
            if ctx.modifier_instance is not None:
                scope = task.get("ContextScope", "")
                if scope in ("Modifier", "ContextModifier"):
                    mod_target = ctx.modifier_instance
                elif "ToTargetType" not in task and scope not in ("ContextCaster", "SummonerEntity", "TargetEntity"):
                    mod_floats = ctx.modifier_instance.config.get("DynamicValues", {}).get("Floats", {})
                    if str(tk) in mod_floats or tk in ctx.modifier_instance.dynamic_values:
                        mod_target = ctx.modifier_instance
            rt.set_dynamic_value(to_t[0], tk, val, modifier=mod_target)

    def _op_set_dynamic_value_by_modifier_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
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
            elif vtype == "CurrentShield":
                val = float(getattr(mod, "shield_value", 0.0) or 0.0)
            elif vtype == "MaxShield":
                val = float(getattr(mod, "shield_max", 0.0) or 0.0)
        mult = self._eval_num(task.get("Multiplier"), ctx, 1.0)
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        self._write_dyn(task, ctx, key_h, val * mult)

    def _op_set_dynamic_value_by_character_count(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
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

    def _op_set_dynamic_value_by_heal_data_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        hd = ctx.heal_data or {}
        prop = str(task.get("Property", "HealValue"))
        val = float(hd.get(prop, hd.get("HealValue", 0.0)))
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        self._write_dyn(task, ctx, key_h, val)

    def _op_set_dynamic_value_by_damage_data_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        dd = ctx.damage_data or {}
        prop = str(task.get("Property", "FinalDamage"))
        val = float(dd.get(prop, 0.0))
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        self._write_dyn(task, ctx, key_h, val)

    def _op_set_dynamic_value_by_attack_target_count(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        cnt = float(len(ctx.attack_target_ids or ctx.ability_target_ids))
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        self._write_dyn(task, ctx, key_h, cnt)

    def _op_set_dynamic_value_by_variate_type(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        vtype = str(task.get("VariateType", "ParamValue"))
        if vtype == "ParamValue":
            val = float(ctx.change_value)
        elif vtype == "ParamValue2":
            val = float(getattr(ctx, "change_value2", 0.0))
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

    def _op_set_dynamic_value_by_random(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        lo = self._eval_num(task.get("Min"), ctx, 0.0)
        hi = self._eval_num(task.get("Max"), ctx, lo)
        val = float(int(lo)) if task.get("IsInt") else (lo + hi) * 0.5
        self._write_dyn(task, ctx, key_h, val)

    def _op_set_dynamic_value_by_maze_buff_config(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
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

    def _op_set_dynamic_value_by_hard_level_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
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

    def _op_set_dynamic_value_by_status_count(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        read_targets = self._resolve_targets(task.get("ReadTargetType") or task.get("TargetType"), ctx)
        want_st = str(task.get("StatusType") or "Debuff")
        caster_filter = (
            set(self._resolve_targets(task["CasterFilter"], ctx))
            if "CasterFilter" in task
            else None
        )
        cnt = 0.0
        if read_targets:
            tid = read_targets[0]
            cnt = float(
                sum(
                    1
                    for m in me.get_modifiers(tid)
                    if not m._destroyed
                    and me.get_modifier_status_type(m) == want_st
                    and (caster_filter is None or m.caster_id in caster_filter)
                )
            )
        self._write_dyn(task, ctx, key_h, cnt)

    def _op_set_dynamic_value_by_behavior_flag_count(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        """统计目标身上含指定 BehaviorFlag 的未销毁 Modifier 数量写入动态变量。"""
        me = self.rt.modifier_engine
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        read_targets = self._resolve_targets(task.get("ReadTargetType") or task.get("TargetType"), ctx)
        flag = str(task.get("BehaviorFlag") or task.get("Flag") or "")
        cnt = 0.0
        if read_targets and flag:
            tid = read_targets[0]
            cnt = float(
                sum(
                    1
                    for m in me.get_modifiers(tid)
                    if not m._destroyed and flag in m.behavior_flags
                )
            )
        self._write_dyn(task, ctx, key_h, cnt)

    def _op_set_dynamic_value_by_count_of_base_type(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        target_spec = task.get("TargetType") or task.get("ReadTargetType") or {"Alias": "AllLightTeamIgnoreServant"}
        targets = self._resolve_targets(target_spec, ctx)
        want_low = {str(b).strip().lower() for b in (task.get("BaseTypeList") or ())}
        path_aliases = {
            "warrior": "destruction", "destruction": "destruction", "毁灭": "destruction",
            "rogue": "hunt", "hunt": "hunt", "巡猎": "hunt",
            "mage": "erudition", "erudition": "erudition", "智识": "erudition",
            "shaman": "harmony", "harmony": "harmony", "同谐": "harmony",
            "warlock": "nihility", "nihility": "nihility", "虚无": "nihility",
            "knight": "preservation", "preservation": "preservation", "存护": "preservation",
            "priest": "abundance", "abundance": "abundance", "丰饶": "abundance",
            "memory": "remembrance", "remembrance": "remembrance", "记忆": "remembrance",
            "elation": "elation", "欢愉": "elation",
        }
        want_norm = {path_aliases.get(b, b) for b in want_low}
        cnt = 0
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is None:
                continue
            raw_low = str(getattr(ent, "path", "") or "").strip().lower()
            norm_path = path_aliases.get(raw_low, raw_low)
            if raw_low in want_low or norm_path in want_norm:
                cnt += 1
        key_h = dotnet_hash(_str_val(task.get("DynamicKey")))
        self._write_dyn(task, ctx, key_h, float(cnt))

    def _op_set_dynamic_entity_param(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key = _str_val(task.get("DynamicKey"))
        owners = self._resolve_targets(task.get("ReadTargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        param_spec = task.get("ParamTargetType")
        alias = param_spec.get("Alias") if isinstance(param_spec, Mapping) else None
        if alias == "None" or param_spec is None:
            vals = []
        else:
            vals = self._resolve_targets(param_spec, ctx)
        for oid in owners:
            if oid and key:
                if vals:
                    self.rt.dynamic_entity_params[(oid, key)] = list(vals)
                else:
                    self.rt.dynamic_entity_params.pop((oid, key), None)

    def _op_read_invasion_param(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        # 官方贪饕参数读取: 优先从 StageMonsterInvasionParam[InvasionID].ParamList[idx] 读取，回退至 MazeBuff ParamList
        rt = self.rt
        sim = rt.sim
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

    def _op_reinit_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
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
            elif ent is not None and prop == "ElationEchoPoint" and "MaxValue" in task:
                setattr(ent, "_elation_echo_point_max", max(0.0, self._eval_num(task.get("MaxValue"), ctx, 0.0)))

    def _op_calc_elation_echo_add_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = self._resolve_targets(task.get("HILNFHCPEAD"), ctx)
        tid = targets[0] if targets else (ctx.param_entity_id or ctx.modifier_owner_id or ctx.caster_id)
        base_val = max(0.0, self._eval_num(task.get("IHOPFAFJPHF"), ctx, 0.0))
        prev_pending = getattr(self.rt, "_pending_elation_echo_add", None)
        pending: Dict[str, Any] = {"base": base_val, "mult": 1.0, "bonus": 0.0, "flag": False}
        self.rt._pending_elation_echo_add = pending
        try:
            if tid:
                self.rt.modifier_engine.dispatch_event(
                    "OnBeforeElationEchoPointBuffAdd",
                    owner_id=tid,
                    param_entity_id=tid,
                    change_value=base_val,
                )
        finally:
            self.rt._pending_elation_echo_add = prev_pending
        final_val = max(0.0, float(pending["base"]) * float(pending["mult"]) + float(pending["bonus"]))
        if tid:
            ent = self.rt.sim.get_entity(tid)
            if ent is not None:
                max_cap = getattr(ent, "_elation_echo_point_max", None)
                if max_cap is not None:
                    cur_echo = self.rt.modifier_engine.get_entity_property(tid, "ElationEchoPoint")
                    final_val = max(0.0, min(final_val, float(max_cap) - cur_echo))
        key_h = dotnet_hash(_str_val(task.get("FHLJGDGMMHK") or "_FinalAddValue"))
        store = ctx.template_dynamics if ctx.template_dynamics is not None else ctx.local_dynamics
        store[key_h] = float(final_val)

    def _op_read_modifier_config_value(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        me = self.rt.modifier_engine
        mname = _str_val(task.get("IFNAGLOMHBK"))
        cfg = me._lookup_modifier_config(mname, ctx.ability_name) if mname else {}
        vtype = str(task.get("ACBKMOPHPLE") or "LifeTime")
        val = 0.0
        if vtype == "LifeTime":
            if "LifeTime" in cfg:
                val = self._eval_num(cfg["LifeTime"], ctx, 0.0)
        elif vtype == "Layer":
            val = float(self._eval_num(cfg.get("Count"), ctx, 1.0))
        key_h = dotnet_hash(_str_val(task.get("FHLJGDGMMHK")))
        scope = str(task.get("AMEKHLANFKP") or "ContextTaskTemplate")
        self._write_dyn({"ContextScope": scope}, ctx, key_h, val)

    def _op_set_dynamic_value_by_elation_point(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("FHLJGDGMMHK")))
        val = self.rt.get_elation_points_for_query(
            ctx.modifier_owner_id or ctx.caster_id,
            task.get("PICEOEEKCIN"),
        )
        write_spec: Dict[str, Any] = {}
        if "AMEKHLANFKP" in task:
            write_spec["ContextScope"] = task.get("AMEKHLANFKP", "")
        if "HILNFHCPEAD" in task:
            write_spec["TargetType"] = task.get("HILNFHCPEAD")
        self._write_dyn(write_spec, ctx, key_h, val)

    def _op_set_dynamic_value_by_bp_change(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        raw = float(getattr(ctx, "change_value", 0.0) or 0.0)
        val = abs(raw) if str(task.get("ValueType") or "") == "AbsDelta" else raw
        self._write_dyn(task, ctx, key_h, val)

    def _op_set_dynamic_value_by_current_bp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        self._write_dyn(task, ctx, key_h, float(self.rt.sim.sp.current_sp))

    def _op_set_dynamic_value_by_max_bp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        self._write_dyn(task, ctx, key_h, float(self.rt.sim.sp.max_sp))

    def _op_set_dynamic_value_by_skill_property(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        read_targets = (
            self._resolve_targets(task["ReadTargetType"], ctx)
            if "ReadTargetType" in task
            else [ctx.caster_id]
        )
        read_tid = read_targets[0] if read_targets else ctx.caster_id
        sk_key = _str_val(task.get("SkillTriggerKey") or task.get("SkillName"))
        prop_type = str(task.get("PropertyType") or "")
        val = 0.0
        spec = self.rt.entity_specs.get(read_tid)
        if spec is not None:
            loader = self.rt.loader
            if spec.is_servant:
                loader._ensure_servants()
                loader._ensure_servant_skills()
                sv = loader._servants.get(spec.unit_id, {})
                skill_ids = sv.get("SkillIDList", ())
                skill_map = loader._servant_skills
            else:
                loader._ensure_avatar_skills()
                av = loader.get_avatar_config(spec.unit_id, enhanced=getattr(spec, "enhanced", False))
                skill_ids = av.get("SkillList", ())
                skill_map = loader._avatar_skills
            for sid in skill_ids:
                row = skill_map.get((int(sid), 1)) or skill_map.get((int(sid), 0))
                if row is not None and row.get("SkillTriggerKey") == sk_key:
                    raw = row.get(prop_type)
                    if isinstance(raw, Mapping):
                        val = float(raw.get("Value", 0.0))
                    elif raw is not None:
                        val = float(raw)
                    if prop_type in ("BPNeed", "BPAdd", "SPBase") and val < 0.0:
                        val = 0.0
                    break
            for ov in self.rt.skill_property_overrides.get(read_tid, ()):
                if ov.get("PropertyType") == prop_type and (
                    not ov.get("SkillName") or ov.get("SkillName") == sk_key
                ):
                    op = str(ov.get("OperatorType", "Set"))
                    ov_val = float(ov.get("Value", 0.0))
                    if op == "Mul":
                        val *= ov_val
                    elif op == "Add":
                        val += ov_val
                    else:
                        val = ov_val
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        self._write_dyn(task, ctx, key_h, val)

    def _op_modify_dynamic_value_clamped(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        targets = (
            self._resolve_targets(task["HILNFHCPEAD"], ctx)
            if "HILNFHCPEAD" in task
            else [ctx.caster_id]
        )
        key_h = dotnet_hash(_str_val(task.get("FHLJGDGMMHK")))
        delta = self._eval_num(task.get("AJHHCOHFIFA"), ctx, 0.0)
        for tid in targets:
            if not tid:
                continue
            cur = float(self.rt.entity_dynamics.get(tid, {}).get(key_h, 0.0))
            new_val = max(0.0, cur + delta)
            if abs(new_val - cur) <= 1e-12:
                continue
            self.rt.set_dynamic_value(tid, key_h, new_val, ability_name=ctx.ability_name)

    def _op_set_dynamic_string(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key = str(task.get("DynamicKey") or task.get("Key") or "")
        if not key:
            return
        v_spec = task.get("Value")
        if isinstance(v_spec, Mapping) and v_spec.get("Custom"):
            val = ctx.custom_strings.get(str(v_spec.get("Key") or ""), "")
        else:
            val = _str_val(v_spec)
        ctx.custom_strings[key] = val
        if ctx.modifier_instance is not None:
            ctx.modifier_instance.custom_strings[key] = val
        scope = str(task.get("ContextScope") or "")
        if scope in ("ContextCaster", "TargetEntity"):
            tid = self._dyn_scope_entity(task, ctx)
            if tid:
                self.rt.entity_dynamic_strings.setdefault(tid, {})[key] = val

    def _op_set_dynamic_value_by_elation_time_skill_count(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        key_h = dotnet_hash(_str_val(task.get("DynamicKey") or task.get("Key")))
        cnt = float(len(getattr(self.rt, "elation_time_units", ())))
        self._write_dyn(task, ctx, key_h, cnt)

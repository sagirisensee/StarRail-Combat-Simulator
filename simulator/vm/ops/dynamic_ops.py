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
            mod_target = ctx.modifier_instance if ("ToTargetType" not in task and ctx.modifier_instance is not None) else None
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

    def _op_set_dynamic_value_by_count_of_base_type(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
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

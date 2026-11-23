# coding: utf-8
"""ConfigAbility VM 战斗结算算子 Mixin（能量、治疗、伤害、自扣血）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...actions import DamageType
from ...events import HPLostEvent
from ...status import StatType
from ..expr import dotnet_hash
from ..target_alias import ExecutionContext


class CombatOpsMixin:
    """ModifySPNew / HealHP / DamageByAttackProperty / LoseHPByRatio 算子实现。"""

    def _clamp_enemy_direct_hp_loss(
        self,
        tid: str,
        tgt_ent: Any,
        raw_loss: float,
        *,
        max_hp: float,
        caster_id: str,
        param_flags: Tuple[str, ...] = (),
    ) -> Tuple[float, Optional[Any]]:
        """对敌方直接扣血（ByBaseDamage / LoseHP）执行锁血阈值与转阶段保护，返回裁剪后的扣血量与 mrs。"""
        rt = self.rt
        me = rt.modifier_engine
        cur_hp = float(tgt_ent.current_hp)
        mrs = None
        kit = getattr(tgt_ent, "kit", None)
        runner = getattr(kit, "runner", None) if kit is not None else None
        if runner is not None:
            try:
                mrs = runner.get_enemy_state(tid)
            except KeyError:
                mrs = None

        if mrs is not None:
            if mrs.lock_hp_ratio is not None and mrs.lock_hp_ratio > 0.0:
                fl = max_hp * float(mrs.lock_hp_ratio)
                if cur_hp >= fl - 1e-6 and cur_hp - raw_loss < fl:
                    raw_loss = max(0.0, cur_hp - fl)
            if mrs.phase < mrs.max_phase and cur_hp - raw_loss <= 0.0:
                setattr(mrs, "_limbo_pending", True)
                setattr(mrs.entity, "_vm_limbo_pending", True)
                raw_loss = max(0.0, cur_hp - 1.0)
            elif cur_hp - raw_loss <= 0.0:
                me.dispatch_event(
                    "OnBeforeMortallyWonded",
                    owner_id=tid,
                    param_entity_id=caster_id,
                    change_value=-float(raw_loss),
                    param_flags=param_flags,
                )
        elif cur_hp - raw_loss <= 0.0:
            me.dispatch_event(
                "OnBeforeMortallyWonded",
                owner_id=tid,
                param_entity_id=caster_id,
                change_value=-float(raw_loss),
                param_flags=param_flags,
            )

        locks = getattr(tgt_ent, "_locked_hp_thresholds", None)
        if isinstance(locks, dict) and locks:
            floor_hp = max(float(v) for v in locks.values())
            if cur_hp >= floor_hp - 1e-6 and cur_hp - raw_loss < floor_hp:
                raw_loss = max(0.0, cur_hp - floor_hp)
                me.dispatch_event(
                    "OnLockHPThresholdReached",
                    owner_id=tid,
                    param_entity_id=tid,
                )
        return raw_loss, mrs

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
        ftype = str(task.get("FormulaType", "HealByHealerMaxHP"))
        if not targets:
            return
        if healer is None and ftype not in ("HealByTargetMaxHP", "HealByTargetLostHP", "HealByBaseValue"):
            return

        pct = self._eval_num(task.get("HealPercentage"), ctx, 0.0)
        flat = self._eval_num(task.get("ModifyValue"), ctx, 0.0)

        snap_healer_max_hp = float(sim.port.max_hp(healer.name)) if healer is not None else 0.0
        snap_healer_def = float(healer.defense) if healer is not None else 0.0

        for tid in targets:
            tgt = sim.get_entity(tid)
            if tgt is None or tgt.current_hp <= 0:
                continue
            if any("DisableHealHP" in m.behavior_flags for m in me.get_modifiers(tid)):
                continue
            if ftype == "HealByHealerMaxHP":
                base_heal = snap_healer_max_hp * pct + flat
            elif ftype == "HealByTargetMaxHP":
                base_heal = float(sim.port.max_hp(tgt.name)) * pct + flat
            elif ftype == "HealByTargetLostHP":
                m_hp = float(sim.port.max_hp(tgt.name))
                base_heal = max(0.0, m_hp - tgt.current_hp) * pct + flat
            elif ftype == "HealByBaseValue":
                base_heal = flat
            elif ftype == "HealByHealerDefence":
                base_heal = snap_healer_def * pct + flat
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

            cur_outgoing = float(sim.port.stat(healer.name, StatType.OUTGOING_HEALING)) if healer is not None else 0.0
            outgoing = cur_outgoing + heal_data["HealRatioAdded"]
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
            ab_l = ctx.ability_name
            caster_ent_st = sim.get_entity(ctx.caster_id)
            caster_aid = getattr(caster_ent_st, "avatar_id", None) if caster_ent_st is not None else None
            if (
                (not caster_aid)
                and caster_ent_st is not None
                and getattr(caster_ent_st, "is_memosprite", False)
                and ab_l.startswith("Avatar_")
            ):
                owner_nm = getattr(caster_ent_st, "owner_name", None)
                owner_e = sim.get_entity(owner_nm) if owner_nm else None
                if owner_e is not None:
                    caster_aid = getattr(owner_e, "avatar_id", None)
            if caster_aid is not None:
                sk_idx = 0
                if "Skill01" in ab_l or atk_type == "Normal":
                    sk_idx = 1
                elif "Skill02" in ab_l or atk_type == "BPSkill":
                    sk_idx = 2
                elif "Skill03" in ab_l or atk_type == "Ultra":
                    sk_idx = 3
                if sk_idx > 0:
                    rt.loader._ensure_avatar_skills()
                    sk_row = (rt.loader._avatar_skills or {}).get((int(caster_aid) * 100 + sk_idx, 1))
                    if isinstance(sk_row, dict):
                        ssl = sk_row.get("ShowStanceList") or []
                        for sv in ssl:
                            v_raw = sv.get("Value", 0.0) if isinstance(sv, dict) else sv
                            if float(v_raw) > 0.0:
                                stance = float(v_raw)
                                break
            if stance <= 0.0 and caster_ent_st is not None and getattr(caster_ent_st, "is_memosprite", False):
                import re as _re_st

                m_sk = _re_st.search(r"(Skill\d+)", ab_l)
                tkey_st = m_sk.group(1) if m_sk else ""
                sv_aid = getattr(caster_ent_st, "avatar_id", None)
                if not sv_aid:
                    owner_nm = getattr(caster_ent_st, "owner_name", None)
                    owner_e = sim.get_entity(owner_nm) if owner_nm else None
                    if owner_e is not None and getattr(owner_e, "avatar_id", None):
                        sv_aid = int(owner_e.avatar_id) + 10000
                if sv_aid and tkey_st:
                    rt.loader._ensure_servant_skills()
                    prefix = str(int(sv_aid))
                    tgt_alias_st = str((task.get("TargetType") or {}).get("Alias", "")) if isinstance(task.get("TargetType"), Mapping) else ""
                    is_sub_target_st = ("-" in tgt_alias_st) or ("Adjoin" in tgt_alias_st)

                    def _pick_ssl(srow_in: Mapping[str, Any]) -> float:
                        ssl_in = srow_in.get("ShowStanceList") or []
                        vals_in = [float(sv.get("Value", 0.0) if isinstance(sv, dict) else sv) for sv in ssl_in]
                        if is_sub_target_st and len(vals_in) > 1 and vals_in[1] > 0.0:
                            return vals_in[1]
                        for v_in in vals_in:
                            if v_in > 0.0:
                                return v_in
                        return 0.0

                    cand_rows = [
                        srow
                        for (sid_k, lv_k), srow in (rt.loader._servant_skills or {}).items()
                        if lv_k == 1 and str(sid_k).startswith(prefix)
                    ]
                    for srow in cand_rows:
                        if srow.get("SkillTriggerKey") == tkey_st:
                            stance = _pick_ssl(srow)
                            if stance > 0.0:
                                break
                    if stance <= 0.0 and tkey_st not in ("Skill01",):
                        for srow in cand_rows:
                            if srow.get("SkillTriggerKey") not in ("Skill01",):
                                stance = _pick_ssl(srow)
                                if stance > 0.0:
                                    break
            if stance <= 0.0:
                if "Skill01" in ab_l or atk_type in ("Normal", "Servant"):
                    stance = 30.0
                elif "Skill03" in ab_l or atk_type == "Ultra":
                    stance = 60.0
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
        is_self_break_pursued = (
            atk_type == "Pursued"
            and ctx.modifier_instance is not None
            and ctx.caster_id == ctx.modifier_owner_id
            and bool(getattr(sim.get_entity(ctx.caster_id), "is_enemy", False))
        )
        is_additional_pursued = (
            atk_type == "Pursued"
            and (getattr(rt, "_in_after_attack", False) or is_self_break_pursued)
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
            "DOT": DamageType.DOT,
        }
        damage_type = dtype_map.get(atk_type, DamageType.BASIC)
        is_true_dmg = (damage_type == DamageType.TRUE)
        is_dot_dmg = (damage_type == DamageType.DOT)
        is_nested_sub = is_true_dmg or is_dot_dmg or getattr(rt, "_in_after_attack", False) or is_equip_sub

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

        final_formula = str(atk_prop.get("FinalFormulaType", ""))
        formula_type = str(atk_prop.get("FormulaType", ""))
        real_targets = [tid for tid in targets if tid != "__LEVEL__"]
        caster_ent_bd = sim.get_entity(ctx.caster_id) if ctx.caster_id != "__LEVEL__" else None
        is_level_base_dmg = ctx.caster_id == "__LEVEL__" and is_true_dmg and final_formula == "ByBaseDamage"
        is_enemy_self_base_dmg = (
            final_formula == "ByBaseDamage"
            and ctx.caster_id != "__LEVEL__"
            and caster_ent_bd is not None
            and bool(getattr(caster_ent_bd, "is_enemy", False))
            and bool(real_targets)
            and all(tid == ctx.caster_id for tid in real_targets)
        )
        if is_level_base_dmg or is_enemy_self_base_dmg:
            can_last_kill = bool(atk_prop.get("CanTriggerLastKill", False))
            last_killer = (
                getattr(rt, "_last_enemy_killer_id", "")
                or getattr(rt, "_current_attacker_id", "")
                or ctx.caster_id
            )
            hp_change_param = "__LEVEL__" if is_level_base_dmg else ctx.caster_id
            hp_change_atk_type = "TrueDamage" if is_level_base_dmg else (atk_type or "TrueDamage")
            for tid in real_targets:
                tgt_ent = sim.get_entity(tid)
                if tgt_ent is None or tgt_ent.current_hp <= 0.0:
                    continue
                max_hp = float(sim.port.max_hp(tid))
                if formula_type == "ByMaxHP":
                    raw_dmg = max_hp * float(eff_pct) + float(eff_flat)
                else:
                    raw_dmg = float(eff_flat)
                mrs_direct = None
                if getattr(tgt_ent, "is_enemy", False):
                    raw_dmg, mrs_direct = self._clamp_enemy_direct_hp_loss(
                        tid,
                        tgt_ent,
                        raw_dmg,
                        max_hp=max_hp,
                        caster_id=hp_change_param,
                        param_flags=("IsHPChangeByDamage",),
                    )
                actual = min(float(tgt_ent.current_hp), max(0.0, raw_dmg))
                if actual <= 0.0:
                    continue
                tgt_ent.current_hp = max(0.0, float(tgt_ent.current_hp) - actual)
                me.dispatch_event(
                    "OnHPChange",
                    owner_id=tid,
                    param_entity_id=hp_change_param,
                    change_value=-float(actual),
                    current_attack_type=hp_change_atk_type,
                    param_flags=("IsHPChangeByDamage",),
                )
                me.dispatch_event(
                    "OnListenHPChange",
                    param_entity_id=tid,
                    change_value=-float(actual),
                )
                if mrs_direct is not None and getattr(mrs_direct, "_limbo_pending", False):
                    if not rt.trigger_or_defer_limbo(tid, eff_killer_limbo := (last_killer if can_last_kill else hp_change_param)):
                        setattr(mrs_direct, "_limbo_pending", False)
                        me.dispatch_event("OnLimboWaitHeal", owner_id=tid, param_entity_id=eff_killer_limbo)
                if tgt_ent.current_hp <= 0.0:
                    if can_last_kill:
                        if is_level_base_dmg:
                            eff_killer = last_killer
                        else:
                            eff_killer = (ctx.param_entity_id if (ctx.param_entity_id and ctx.param_entity_id != tid) else "") or last_killer
                    else:
                        eff_killer = "__LEVEL__" if is_level_base_dmg else ctx.caster_id
                    if is_level_base_dmg and getattr(rt, "_attack_scope_depth", 0) > 0:
                        pending_lvl = getattr(rt, "_pending_level_kills", None)
                        if pending_lvl is None:
                            pending_lvl = []
                            rt._pending_level_kills = pending_lvl
                        if all(item[0] != tid for item in pending_lvl):
                            pending_lvl.append((tid, eff_killer))
                    else:
                        me.dispatch_event("OnBeforeDying", owner_id=tid, param_entity_id=eff_killer)
                        from simulator.events import EnemyDefeatedEvent
                        sim.event_bus.publish(
                            EnemyDefeatedEvent(
                                av=float(sim.current_av),
                                cycle=int(sim.current_cycle),
                                attacker_name=eff_killer,
                                target_name=tid,
                            )
                        )
                        me.destroy_all_for_entity(tid)
                        sim.entities[:] = [e for e in sim.entities if e.name != tid]
            return

        base_before_hit_all = dict(dmg_data) if is_true_dmg else base_before_hit_all
        captured = [0.0]
        self._damage_capture_stack.append(captured)
        sim.resolver.begin_aoe()
        try:
            caster_ent_pre = sim.get_entity(ctx.caster_id)
            if (
                not is_nested_sub
                and caster_ent_pre is not None
                and getattr(caster_ent_pre, "is_enemy", False)
                and real_targets
                and getattr(rt, "_open_enemy_attack", None) is None
            ):
                rt.begin_being_attacked(ctx.caster_id, real_targets)
            any_died_mid_aoe = False
            pending_limbo: List[str] = []
            pending_dying: List[str] = []
            for idx, tid in enumerate(real_targets):
                if idx > 0 and any_died_mid_aoe and not is_true_dmg and atk_type in ("Servant", "Pursued", "Ultra"):
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
                was_alive = bool(
                    tgt_ent is not None
                    and (getattr(tgt_ent, "current_hp", 0.0) > 0.0 or getattr(tgt_ent, "_in_deathrattle_limbo", False))
                )
                was_strictly_alive = bool(tgt_ent is not None and getattr(tgt_ent, "current_hp", 0.0) > 0.0)
                prev_tgt_hp = float(getattr(tgt_ent, "current_hp", 0.0)) if tgt_ent is not None else 0.0
                prev_dmg_red = getattr(tgt_ent, "damage_reduction", 0.0) if tgt_ent is not None else 0.0
                applied_def_red = False
                tgt_extra_vuln = 0.0
                tgt_extra_def_ignore = 0.0
                tgt_extra_res_pen = 0.0
                if tgt_ent is not None and getattr(tgt_ent, "is_enemy", False) and not is_true_dmg:
                    tgt_hit_data: Dict[str, Any] = {}
                    me.dispatch_event(
                        "OnBeforeBeingHitAll",
                        owner_id=tid,
                        param_entity_id=ctx.caster_id,
                        damage_data=tgt_hit_data,
                        current_attack_type=atk_type,
                    )
                    tgt_extra_vuln = float(tgt_hit_data.get("Defender_AllDamageTypeTakenRatio", 0.0))
                    tgt_extra_def_ignore = -float(tgt_hit_data.get("Defender_DefenceAddedRatio", 0.0))
                    tgt_res_mod = float(tgt_hit_data.get("Defender_AllDamageTypeResistance", 0.0))
                    def_red = float(tgt_hit_data.get("Defender_AllDamageReduce", 0.0))
                    red_mult = 1.0 - prev_dmg_red
                    if def_red > 0.0:
                        red_mult *= max(0.0, 1.0 - def_red)
                    for m_def in me.get_modifiers(tid):
                        m_red = float(m_def.properties.get("AllDamageReduce", 0.0))
                        if m_red > 0.0:
                            red_mult *= max(0.0, 1.0 - m_red)
                        tgt_res_mod += float(m_def.properties.get("AllDamageTypeResistance", 0.0))
                    tgt_extra_res_pen = -tgt_res_mod
                    combined_red = max(0.0, 1.0 - red_mult)
                    if abs(combined_red - prev_dmg_red) > 1e-9:
                        tgt_ent.damage_reduction = combined_red
                        applied_def_red = True
                    setattr(tgt_ent, "_vm_damage_reduction_active", True)
                    setattr(tgt_ent, "_vm_last_def_red", def_red)
                    setattr(tgt_ent, "_vm_last_tgt_vuln", tgt_extra_vuln)
                    setattr(tgt_ent, "_vm_last_tgt_def_ignore", tgt_extra_def_ignore)
                    setattr(tgt_ent, "_vm_last_tgt_res_pen", tgt_extra_res_pen)
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
                    force_crit=(False if is_dot_dmg else None),
                    extra_dmg_boost=extra_dmg_boost,
                    extra_def_ignore=extra_def_ignore + tgt_extra_def_ignore,
                    extra_res_pen=extra_res_pen + tgt_extra_res_pen,
                    extra_vuln=extra_vuln + tgt_extra_vuln,
                    extra_crit_dmg=extra_crit_dmg,
                    vm_hit_hooks_applied=not is_true_dmg,
                    source_entity=(
                        getattr(ctx.modifier_instance, "caster_snapshot_entity", None)
                        if ctx.modifier_instance is not None
                        else None
                    ),
                )
                if not is_true_dmg and not is_dot_dmg and was_alive and tgt_ent is not None and not getattr(tgt_ent, "is_enemy", False):
                    caster_ent = sim.get_entity(ctx.caster_id)
                    if caster_ent is not None and getattr(caster_ent, "is_enemy", False):
                        sp_base = float(getattr(rt, "_current_enemy_sp_hit_base", 0.0))
                        if sp_base <= 0.0 and ctx.ability_name:
                            mspec = getattr(getattr(caster_ent, "kit", None), "ai_spec", None)
                            if mspec is not None:
                                for sk_key, sk_spec in getattr(mspec, "skills_by_key", {}).items():
                                    if sk_key and (f"_{sk_key}_" in ctx.ability_name or ctx.ability_name.endswith(f"_{sk_key}")):
                                        sp_base = float(getattr(sk_spec, "sp_hit_base", 0.0) or 0.0)
                                        break
                        sp_ratio = self._eval_num(atk_prop.get("SPHitRatio"), ctx, 0.0)
                        sp_hit = sp_base * sp_ratio * hit_split
                        if sp_hit > 0.0:
                            energy_tid = (getattr(tgt_ent, "master_name", None) or tid) if getattr(tgt_ent, "is_memosprite", False) else tid
                            sim.port.gain_hit_energy(energy_tid, base_amount=sp_hit)
                try:
                    sim.resolver.resolve_all()
                finally:
                    if tgt_ent is not None:
                        if applied_def_red:
                            tgt_ent.damage_reduction = prev_dmg_red
                        setattr(tgt_ent, "_vm_damage_reduction_active", False)
                        setattr(tgt_ent, "_vm_last_def_red", 0.0)
                        setattr(tgt_ent, "_vm_last_tgt_vuln", 0.0)
                        setattr(tgt_ent, "_vm_last_tgt_def_ignore", 0.0)
                        setattr(tgt_ent, "_vm_last_tgt_res_pen", 0.0)
                if len(real_targets) > 1 or applied_def_red:
                    if was_strictly_alive and tgt_ent is not None and getattr(tgt_ent, "current_hp", 0.0) <= 0.0:
                        any_died_mid_aoe = True
                if tgt_ent is not None and getattr(tgt_ent, "is_enemy", False) and (
                    float(getattr(tgt_ent, "current_hp", 0.0)) < prev_tgt_hp
                    or getattr(tgt_ent, "_in_deathrattle_limbo", False)
                ):
                    director = getattr(sim, "_stage_director", None)
                    runner = getattr(director, "runner", None) if director is not None else None
                    if runner is not None:
                        try:
                            mrs = runner.get_enemy_state(tid)
                            if getattr(mrs, "_limbo_pending", False):
                                setattr(mrs, "_limbo_pending", False)
                                if atk_type in ("Servant", "Pursued"):
                                    any_died_mid_aoe = True
                                if tid not in pending_limbo:
                                    pending_limbo.append(tid)
                        except KeyError:
                            pass
                    if was_strictly_alive and float(getattr(tgt_ent, "current_hp", 0.0)) <= 0.0:
                        if me.has_behavior_flag(tid, "Deathrattle"):
                            summoner_id = getattr(tgt_ent, "summoner_name", None)
                            if not summoner_id or not me.has_behavior_flag(summoner_id, "Break"):
                                setattr(tgt_ent, "_in_deathrattle_limbo", True)
                        if tid not in pending_dying:
                            pending_dying.append(tid)
                        pending_dead = getattr(rt, "_pending_dead_enemies", None)
                        if pending_dead is None:
                            pending_dead = []
                            rt._pending_dead_enemies = pending_dead
                        if tid not in pending_dead:
                            pending_dead.append(tid)
            sim.resolver.resolve_all()
            if pending_dying:
                if ctx.caster_id and ctx.caster_id != "__LEVEL__":
                    rt._last_enemy_killer_id = ctx.caster_id
                if getattr(rt, "_attack_scope_depth", 0) > 0:
                    q = getattr(rt, "_pending_dying_enemies", None)
                    if q is None:
                        q = []
                        rt._pending_dying_enemies = q
                    for d_tid in pending_dying:
                        if not any(x[0] == d_tid for x in q):
                            q.append((d_tid, ctx.caster_id))
                else:
                    for d_tid in pending_dying:
                        me.dispatch_event("OnBeforeDying", owner_id=d_tid, param_entity_id=ctx.caster_id)
                        d_ent = sim.get_entity(d_tid)
                        if d_ent is not None and getattr(d_ent, "_in_deathrattle_limbo", False):
                            me.strip_for_deathrattle(d_tid)
                        me.dispatch_event("OnDeathrattle", owner_id=d_tid, param_entity_id=ctx.caster_id)
            for l_tid in pending_limbo:
                if not rt.trigger_or_defer_limbo(l_tid, ctx.caster_id):
                    me.dispatch_event("OnLimboWaitHeal", owner_id=l_tid, param_entity_id=ctx.caster_id)
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
            eff_sk_type = ctx.current_skill_type or atk_type
            if getattr(rt, "_attack_scope_depth", 0) > 0:
                rt._pending_after_attack = (atk_seq, ctx.caster_id, dmg_data, atk_type, eff_sk_type)
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
                            current_skill_type=eff_sk_type,
                            current_attack_type=atk_type,
                        )
                        me.dispatch_event(
                            "OnListenAfterAttack",
                            param_entity_id=ctx.caster_id,
                            attack_target_ids=all_tgts,
                            damage_data=dmg_data,
                            current_skill_type=eff_sk_type,
                            current_attack_type=atk_type,
                        )
                        for tid in all_tgts:
                            me.dispatch_event(
                                "OnAfterBeingAttacked",
                                owner_id=tid,
                                param_entity_id=ctx.caster_id,
                                damage_data=dmg_data,
                                current_attack_type=atk_type,
                            )
                            me.dispatch_event(
                                "OnAfterBeingAttackedEnd",
                                owner_id=tid,
                                param_entity_id=ctx.caster_id,
                                damage_data=dmg_data,
                                current_attack_type=atk_type,
                            )
                    finally:
                        rt._in_after_attack = False
                    pending_dead = getattr(rt, "_pending_dead_enemies", None)
                    if pending_dead:
                        remaining_dead = []
                        for dead_tid in list(pending_dead):
                            dead_ent = sim.get_entity(dead_tid)
                            if dead_ent is not None and getattr(dead_ent, "_in_deathrattle_limbo", False):
                                remaining_dead.append(dead_tid)
                            else:
                                me.destroy_all_for_entity(dead_tid)
                        pending_dead[:] = remaining_dead

    def _execute_lose_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        targets = self._resolve_targets(task.get("TargetType"), ctx)
        ratio_type = str(task.get("RatioType", "CurrentHP"))
        ratio = self._eval_num(task.get("Ratio"), ctx, 0.0) if "Ratio" in task else 0.0
        dmg_val = self._eval_num(task.get("DamageValue"), ctx, 0.0) if "DamageValue" in task else 0.0
        consume_shield = bool(task.get("ConsumeShield", False))
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
            if "DamageValue" in task and "Ratio" not in task:
                raw_loss = dmg_val
            else:
                base = float(ent.current_hp) if ratio_type == "CurrentHP" else max_hp
                raw_loss = base * ratio

            if getattr(ent, "is_enemy", False):
                kit = getattr(ent, "kit", None)
                if consume_shield and kit is not None and hasattr(kit, "intercept_incoming_damage"):
                    raw_loss = kit.intercept_incoming_damage(tid, raw_loss, allow_overflow=False)
                elif not consume_shield:
                    raw_loss, _ = self._clamp_enemy_direct_hp_loss(
                        tid,
                        ent,
                        raw_loss,
                        max_hp=max_hp,
                        caster_id=ctx.caster_id,
                    )
                eff_floor = self._eval_num(task.get("Floor"), ctx, 0.0) if "Floor" in task else 0.0
            else:
                eff_floor = hp_floor

            actual_loss = max(0.0, min(ent.current_hp - eff_floor, raw_loss))
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
                if getattr(ent, "is_enemy", False):
                    director = getattr(sim, "_stage_director", None)
                    runner = getattr(director, "runner", None) if director is not None else None
                    if runner is not None:
                        try:
                            mrs = runner.get_enemy_state(tid)
                            if getattr(mrs, "_limbo_pending", False):
                                if not rt.trigger_or_defer_limbo(tid, ctx.caster_id):
                                    setattr(mrs, "_limbo_pending", False)
                                    me.dispatch_event("OnLimboWaitHeal", owner_id=tid, param_entity_id=ctx.caster_id)
                        except KeyError:
                            pass
                    if ent.current_hp <= 0.0:
                        has_dr = False
                        if me.has_behavior_flag(tid, "Deathrattle"):
                            summoner_id = getattr(ent, "summoner_name", None)
                            if not summoner_id or not me.has_behavior_flag(summoner_id, "Break"):
                                has_dr = True
                                setattr(ent, "_in_deathrattle_limbo", True)
                        from simulator.events import EnemyDefeatedEvent
                        sim.event_bus.publish(
                            EnemyDefeatedEvent(
                                av=float(sim.current_av),
                                cycle=int(sim.current_cycle),
                                attacker_name=ctx.caster_id or "",
                                target_name=tid,
                            )
                        )
                        if getattr(rt, "_attack_scope_depth", 0) > 0:
                            q = getattr(rt, "_pending_dying_enemies", None)
                            if q is None:
                                q = []
                                rt._pending_dying_enemies = q
                            if not any(x[0] == tid for x in q):
                                q.append((tid, ctx.caster_id))
                            pending_dead = getattr(rt, "_pending_dead_enemies", None)
                            if pending_dead is None:
                                pending_dead = []
                                rt._pending_dead_enemies = pending_dead
                            if tid not in pending_dead:
                                pending_dead.append(tid)
                        else:
                            me.dispatch_event("OnBeforeDying", owner_id=tid, param_entity_id=ctx.caster_id)
                            if has_dr:
                                me.strip_for_deathrattle(tid)
                            me.dispatch_event("OnDeathrattle", owner_id=tid, param_entity_id=ctx.caster_id)
                            if not has_dr:
                                me.destroy_all_for_entity(tid)
                                if runner is not None:
                                    runner.state.enemies[:] = [m for m in runner.state.enemies if m.entity.name != tid]
                                sim.entities[:] = [e for e in sim.entities if e.name != tid]

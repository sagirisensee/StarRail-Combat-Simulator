# coding: utf-8
"""ConfigAbility VM 战斗结算算子 Mixin（能量、治疗、伤害、自扣血）。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...actions import DamageType
from ...damage import DamageBreakdown, DamageRequest
from ...events import DamageAppliedEvent, HPLostEvent
from ...lifecycle import emit_sim_event, enter_deathrattle_limbo
from ...status import StatType
from ..expr import dotnet_hash
from ..target_alias import ExecutionContext
from .predicates import _str_val


_ELEM_ZH_TO_EN: Dict[str, str] = {
    "物理": "Physical",
    "火": "Fire",
    "冰": "Ice",
    "雷": "Lightning",
    "风": "Wind",
    "量子": "Quantum",
    "虚数": "Imaginary",
    "Thunder": "Lightning",
}


@dataclass
class _DamageSpec:
    targets: List[str]
    real_targets: List[str]
    atk_prop: Mapping[str, Any]
    eff_attacker_id: str
    element: str
    formula_type: str
    final_formula: str
    pct: float
    flat: float
    stance: float
    atk_type: str
    scaling_stat: str
    damage_type: DamageType
    is_true_dmg: bool
    is_dot_dmg: bool
    is_additional_dmg: bool
    is_nested_sub: bool
    custom_name: str = ""
    is_elation_dmg: bool = False
    is_indirect: bool = False
    prop_source_id: str = ""
    equal_split: bool = False


@dataclass
class _PreparedAttackData:
    atk_seq: int
    atk_key: Tuple[int, str]
    dmg_data: Dict[str, Any]
    base_before_hit_all: Dict[str, Any]
    hit_split: float
    extra_dmg_boost: float
    extra_def_ignore: float
    extra_res_pen: float
    extra_vuln: float
    extra_crit_dmg: float
    base_mult_ratio: float
    eff_pct: float
    eff_flat: float
    eff_stance: float


def _extract_damage_modifiers(
    spec: _DamageSpec,
    dmg_data: Mapping[str, Any],
    hit_split: float,
) -> Tuple[float, float, float, float, float, float, float, float]:
    """从 dmg_data 提取额外乘区修正并折算单段倍率/固定伤害。"""
    extra_dmg_boost = float(dmg_data.get("Attacker_AllDamageTypeAddedRatio", 0.0))
    extra_def_ignore = -float(dmg_data.get("Defender_DefenceAddedRatio", 0.0))
    extra_res_pen = float(dmg_data.get("Attacker_AllDamageTypePenetrate", 0.0))
    extra_vuln = float(dmg_data.get("Defender_AllDamageTypeTakenRatio", 0.0))
    extra_crit_dmg = float(dmg_data.get("Attacker_CriticalDamageBase", 0.0))
    base_mult_ratio = float(dmg_data.get("Attacker_BaseDamageMultiRatio", 0.0))
    added_pct = float(dmg_data.get("AttackData_DamagePercentage", 0.0) or 0.0)
    added_flat = float(dmg_data.get("AttackData_DamageValue", 0.0) or 0.0)
    if spec.final_formula == "ByBaseDamage" and spec.pct == 0.0:
        eff_pct = 0.0
        eff_flat = (spec.flat + added_flat) * hit_split
    else:
        eff_pct = ((spec.pct + added_pct) * base_mult_ratio if base_mult_ratio > 0 else (spec.pct + added_pct)) * hit_split
        eff_flat = ((spec.flat + added_flat) * base_mult_ratio if base_mult_ratio > 0 else (spec.flat + added_flat)) * hit_split
    return (
        extra_dmg_boost,
        extra_def_ignore,
        extra_res_pen,
        extra_vuln,
        extra_crit_dmg,
        base_mult_ratio,
        eff_pct,
        eff_flat,
    )


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
                    change_value=float(raw_loss),
                    param_flags=param_flags,
                )
        elif cur_hp - raw_loss <= 0.0:
            me.dispatch_event(
                "OnBeforeMortallyWonded",
                owner_id=tid,
                param_entity_id=caster_id,
                change_value=float(raw_loss),
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

    def _execute_modify_sp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if "TargetType" in task
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        mfunc = str(task.get("ModifyFunction") or "Add")
        val = self._eval_num(task.get("ModifyValue") if "ModifyValue" in task else task.get("Value"), ctx, 0.0)
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
            if getattr(ent, "uses_special_sp", False) and not (mfunc == "Set" and ep_tid == ctx.caster_id):
                continue
            max_ep = float(sim.port.max_energy(ep_tid) or getattr(ent, "max_energy", 0.0) or 0.0)
            if mfunc == "Set":
                ent.energy = max(0.0, min(max_ep, val)) if max_ep > 0.0 else max(0.0, val)
            elif mfunc in ("Sub", "Minus"):
                ent.energy = max(0.0, float(ent.energy) - val)
            else:
                if val > 0.0:
                    sim.port.gain_energy(ep_tid, val, cause=ctx.ability_name or "ModifySP")
                elif val < 0.0:
                    ent.energy = max(0.0, float(ent.energy) + val)
            if me._apc_defer_depth > 0:
                me._dirty_apc_entities.add(ep_tid)
            else:
                me.check_property_changes(ep_tid)

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
            if getattr(ent, "uses_special_sp", False):
                continue

            err = float(sim.port.stat(ep_tid, StatType.ERR) or 1.0)
            max_ep = float(sim.port.max_energy(ep_tid) or getattr(ent, "max_energy", 0.0) or 0.0)

            if "SetValue" in task:
                old_e = float(ent.energy)
                v = self._eval_num(task["SetValue"], ctx, ent.energy)
                ent.energy = max(0.0, min(max_ep, v)) if max_ep > 0 else max(0.0, v)
                if getattr(sim, "_timeline_diag_energy", False) and callable(getattr(sim, "timeline_diag_cb", None)):
                    sim.timeline_diag_cb(
                        "EN",
                        f"{ent.name} {old_e:.2f} -> {ent.energy:.2f} (op=SetValue) cause={ctx.ability_name or 'ModifySPNew'}",
                    )
                continue
            if "SetMaxSPRatio" in task:
                old_e = float(ent.energy)
                r = self._eval_num(task["SetMaxSPRatio"], ctx, 0.0)
                if max_ep > 0:
                    ent.energy = max(0.0, min(max_ep, max_ep * r))
                if getattr(sim, "_timeline_diag_energy", False) and callable(getattr(sim, "timeline_diag_cb", None)):
                    sim.timeline_diag_cb(
                        "EN",
                        f"{ent.name} {old_e:.2f} -> {ent.energy:.2f} (op=SetMaxSPRatio) cause={ctx.ability_name or 'ModifySPNew'}",
                    )
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
                old_e = float(ent.energy)
                ent.energy = max(0.0, ent.energy + total_gain)
                if getattr(sim, "_timeline_diag_energy", False) and callable(getattr(sim, "timeline_diag_cb", None)):
                    sim.timeline_diag_cb(
                        "EN",
                        f"{ent.name} {old_e:.2f} -> {ent.energy:.2f} (op=Sub) cause={ctx.ability_name or 'ModifySPNew'}",
                    )

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
            neg_hp = float(getattr(tgt, "_negative_hp", 0.0) or 0.0)
            neg_cleared = min(neg_hp, final_heal)
            rem_heal = max(0.0, final_heal - neg_cleared)
            actual_restored = neg_cleared + max(0.0, min(cap, hp_before + rem_heal) - hp_before)
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

    def _resolve_fallback_stance(
        self,
        task: Mapping[str, Any],
        ctx: ExecutionContext,
        atk_type: str,
    ) -> float:
        """当 StanceValue 动态表达式求值为 0 时，从技能表或攻击类型回退削韧值。"""
        rt = self.rt
        sim = rt.sim
        ab_l = ctx.ability_name
        stance = 0.0
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
            m_sk = re.search(r"(Skill\d+)", ab_l)
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
        return stance

    def _parse_damage_spec(self, task: Mapping[str, Any], ctx: ExecutionContext) -> Optional[_DamageSpec]:
        """解析攻击目标、元素、基础倍率/削韧（含兜底）及 DamageType 分类。"""
        rt = self.rt
        sim = rt.sim

        targets = self._resolve_targets(task.get("TargetType"), ctx)
        atk_prop = task.get("AttackProperty") or {}
        if not targets or not atk_prop:
            return None
        override_atk_spec = task.get("OverrideAttacker")
        eff_attacker_id = ctx.caster_id
        if isinstance(override_atk_spec, Mapping):
            ov_targets = self._resolve_targets(override_atk_spec, ctx)
            if ov_targets:
                eff_attacker_id = ov_targets[0]
        prop_source_id = eff_attacker_id
        override_prop_spec = task.get("OverrideDamagePropertySource")
        if isinstance(override_prop_spec, Mapping):
            prop_targets = self._resolve_targets(override_prop_spec, ctx)
            if prop_targets:
                prop_source_id = prop_targets[0]

        dt_obj = atk_prop.get("DamageType", {})
        if isinstance(dt_obj, Mapping) and dt_obj.get("SourceType") == "ReadTargetType":
            rt_list = self._resolve_targets(dt_obj.get("ReadTargetType"), ctx)
            src_ent = sim.get_entity(rt_list[0]) if rt_list else sim.get_entity(eff_attacker_id)
            element = getattr(src_ent, "element", "Physical") or "Physical"
        elif isinstance(dt_obj, Mapping):
            element = dt_obj.get("DamageType", "Physical")
        else:
            element = str(dt_obj or "Physical")
        element = _ELEM_ZH_TO_EN.get(element, element)
        if element and element not in _ELEM_ZH_TO_EN.values():
            element = element.strip().title()
        element = _ELEM_ZH_TO_EN.get(element, element)

        formula_type = str(atk_prop.get("FormulaType", ""))
        final_formula = str(atk_prop.get("FinalFormulaType", ""))
        custom_name = _str_val(atk_prop.get("CustomName"))
        atk_type = str(atk_prop.get("AttackType", ctx.current_attack_type or "Normal"))
        is_break_dmg_formula = formula_type == "ByBreakDamage"
        is_elation_dmg = (formula_type == "ByElationDamage") or (atk_type == "ElationDamage")
        if is_break_dmg_formula and "BreakDamagePercentage" in atk_prop:
            pct = self._eval_num(atk_prop.get("BreakDamagePercentage"), ctx, 0.0)
        elif formula_type == "ByElationDamage" and "ElationDamagePercentage" in atk_prop:
            pct = self._eval_num(atk_prop.get("ElationDamagePercentage"), ctx, 0.0)
        else:
            pct = self._eval_num(atk_prop.get("DamagePercentage"), ctx, 0.0)
        flat = self._eval_num(atk_prop.get("DamageValue"), ctx, 0.0)
        stance = self._eval_num(atk_prop.get("StanceValue"), ctx, 0.0)
        if stance <= 0.0 and atk_prop.get("StanceValue"):
            stance = self._resolve_fallback_stance(task, ctx, atk_type)

        scaling_stat = "atk"
        if formula_type == "ByMaxHP":
            scaling_stat = "hp"
        elif formula_type == "ByDefence":
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
            "ElationDamage": DamageType.ELATION,
        }
        if is_break_dmg_formula:
            damage_type = DamageType.DOT if atk_type == "DOT" else DamageType.ADDITIONAL
        elif is_elation_dmg:
            damage_type = DamageType.ELATION
        else:
            damage_type = dtype_map.get(atk_type, DamageType.BASIC)
        is_true_dmg = damage_type == DamageType.TRUE
        is_dot_dmg = damage_type == DamageType.DOT
        is_additional_dmg = damage_type == DamageType.ADDITIONAL
        is_nested_sub = (
            is_true_dmg
            or is_dot_dmg
            or is_break_dmg_formula
            or getattr(rt, "_in_after_attack", False)
            or is_equip_sub
        )
        real_targets = [tid for tid in targets if tid != "__LEVEL__"]
        return _DamageSpec(
            targets=targets,
            real_targets=real_targets,
            atk_prop=atk_prop,
            eff_attacker_id=eff_attacker_id,
            element=element,
            formula_type=formula_type,
            final_formula=final_formula,
            pct=pct,
            flat=flat,
            stance=stance,
            atk_type=atk_type,
            scaling_stat=scaling_stat,
            damage_type=damage_type,
            is_true_dmg=is_true_dmg,
            is_dot_dmg=is_dot_dmg,
            is_additional_dmg=is_additional_dmg,
            is_nested_sub=is_nested_sub,
            custom_name=custom_name,
            is_elation_dmg=is_elation_dmg,
            is_indirect=bool(atk_prop.get("IsIndirect", False)),
            prop_source_id=prop_source_id,
            equal_split=bool(task.get("EqualSplitInTargets", False)),
        )

    def _prepare_attack_hooks(self, spec: _DamageSpec, ctx: ExecutionContext) -> _PreparedAttackData:
        """派发攻击前与 HitAll 钩子，随后求值 HitSplitRatio 并组装初始乘区。"""
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        merged_seq = getattr(getattr(rt, "lifecycle", None), "merged_atk_seq", None)
        atk_seq = int(merged_seq) if merged_seq is not None else int(getattr(sim, "_action_seq", 0))
        atk_key = (atk_seq, spec.eff_attacker_id)
        if not spec.is_nested_sub and not spec.is_additional_dmg:
            acc_targets = rt._attack_targets_by_key.setdefault(atk_key, [])
            for tid in spec.targets:
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
                    owner_id=spec.eff_attacker_id,
                    attack_target_ids=tuple(spec.targets),
                    current_attack_type=spec.atk_type,
                )
                me.dispatch_event(
                    "OnBeforeAttack",
                    owner_id=spec.eff_attacker_id,
                    attack_target_ids=tuple(spec.targets),
                    current_attack_type=spec.atk_type,
                )
                me.dispatch_event(
                    "OnListenBeforeAttack",
                    param_entity_id=spec.eff_attacker_id,
                    attack_target_ids=tuple(spec.targets),
                    current_attack_type=spec.atk_type,
                )

        dmg_data: Dict[str, Any] = {
            "Element": spec.element,
            "CustomName": spec.custom_name,
            "AttackData_RawDamagePercentage": spec.pct,
            "AttackData_RawDamageValue": spec.flat,
            "IsConvertDamage": bool(spec.is_true_dmg),
        }
        base_before_hit_all = dict(dmg_data)

        # 必须在 OnBeforeAttack 之后再求值 HitSplitRatio，以免读到旧动态值
        hit_split = self._eval_num(spec.atk_prop.get("HitSplitRatio"), ctx, 1.0)
        if spec.equal_split and len(spec.real_targets) > 1:
            hit_split /= float(len(spec.real_targets))
        (
            extra_dmg_boost,
            extra_def_ignore,
            extra_res_pen,
            extra_vuln,
            extra_crit_dmg,
            base_mult_ratio,
            eff_pct,
            eff_flat,
        ) = _extract_damage_modifiers(spec, dmg_data, hit_split)
        eff_stance = spec.stance * hit_split
        return _PreparedAttackData(
            atk_seq=atk_seq,
            atk_key=atk_key,
            dmg_data=dmg_data,
            base_before_hit_all=base_before_hit_all,
            hit_split=hit_split,
            extra_dmg_boost=extra_dmg_boost,
            extra_def_ignore=extra_def_ignore,
            extra_res_pen=extra_res_pen,
            extra_vuln=extra_vuln,
            extra_crit_dmg=extra_crit_dmg,
            base_mult_ratio=base_mult_ratio,
            eff_pct=eff_pct,
            eff_flat=eff_flat,
            eff_stance=eff_stance,
        )

    def _resolve_enemy_sp_hit_base(self, caster_ent: Any, ability_name: str) -> float:
        sp_base = float(getattr(self.rt, "_current_enemy_sp_hit_base", 0.0))
        if sp_base <= 0.0 and ability_name:
            mspec = getattr(getattr(caster_ent, "kit", None), "ai_spec", None)
            if mspec is not None:
                for sk_key, sk_spec in getattr(mspec, "skills_by_key", {}).items():
                    if sk_key and (f"_{sk_key}_" in ability_name or ability_name.endswith(f"_{sk_key}")):
                        sp_base = float(getattr(sk_spec, "sp_hit_base", 0.0) or 0.0)
                        break
        return sp_base

    def _try_execute_break_damage(self, spec: _DamageSpec, ctx: ExecutionContext) -> bool:
        """执行官方 `FormulaType == 'ByBreakDamage'` 击破持续伤害/纠缠/冻结结算。"""
        if spec.formula_type != "ByBreakDamage":
            return False
        rt = self.rt
        sim = rt.sim
        atk_ent = sim.get_entity(spec.eff_attacker_id)
        if atk_ent is None and ctx.modifier_instance is not None:
            atk_ent = getattr(ctx.modifier_instance, "caster_snapshot_entity", None)
        if atk_ent is None:
            return True

        atk_lvl = int(getattr(atk_ent, "level", 80) or 80)
        cache = getattr(rt, "_break_base_cache", None)
        if cache is None:
            cache = {}
            try:
                for row in rt.loader._read_excel("AvatarBreakDamage.json"):
                    lv = int(row.get("Level", 0) or 0)
                    bv = row.get("BreakBaseDamage", {})
                    if lv > 0:
                        cache[lv] = float(bv.get("Value", 3767.5535) if isinstance(bv, Mapping) else bv)
            except Exception:
                pass
            setattr(rt, "_break_base_cache", cache)
        base_break = float(cache.get(atk_lvl, 3767.5535))

        mod_inst = ctx.modifier_instance
        snap_props = getattr(mod_inst, "caster_snapshot_props", None) if mod_inst is not None else None
        if isinstance(snap_props, Mapping) and "BreakDamageAddedRatio" in snap_props:
            be = float(snap_props["BreakDamageAddedRatio"])
        elif isinstance(snap_props, Mapping) and "BreakDamageAddedRatioBase" in snap_props:
            be = float(snap_props["BreakDamageAddedRatioBase"])
        else:
            be = float(getattr(atk_ent, "base_break_effect", 0.0) or 0.0)
            sm = getattr(sim, "status_mgr", None)
            if sm is not None:
                be = sm.calculate_stat(atk_ent.name, be, StatType.BREAK_EFFECT)
                if getattr(atk_ent, "is_memosprite", False) and getattr(atk_ent, "master_name", None):
                    be = max(be, sm.calculate_stat(atk_ent.master_name, be, StatType.BREAK_EFFECT))

        from ...effects import ApplyDamageEffect

        for tid in spec.real_targets:
            tgt_ent = sim.get_entity(tid)
            if tgt_ent is None or float(getattr(tgt_ent, "current_hp", 0.0)) <= 0.0:
                continue
            if spec.element == "Quantum" and spec.atk_type == "Pursued":
                tough_mult = 0.5 + (float(getattr(tgt_ent, "max_toughness", 0.0) or 0.0) / 120.0)
                base_val = base_break * spec.pct * tough_mult * (1.0 + be)
            elif spec.element == "Physical" and spec.atk_type == "DOT":
                tough_mult = 0.5 + (float(getattr(tgt_ent, "max_toughness", 0.0) or 0.0) / 120.0)
                hp_ratio = 0.07 if getattr(tgt_ent, "is_boss", False) else 0.16
                base_val = min(float(tgt_ent.max_hp) * hp_ratio, 2.0 * base_break * tough_mult) * (1.0 + be)
            else:
                base_val = base_break * spec.pct * (1.0 + be)
            tgt_res = (
                float(tgt_ent.damage_res.get(spec.element, 0.0))
                if isinstance(getattr(tgt_ent, "damage_res", None), dict)
                else 0.0
            )
            req = DamageRequest(
                attacker=atk_ent,
                target=tgt_ent,
                skill_multiplier=0.0,
                flat_damage=base_val,
                target_base_res=tgt_res,
                target_is_broken=True,
                force_crit=False,
                ignore_dmg_boost=True,
                damage_type=spec.damage_type,
            )
            sim.resolver.enqueue(
                ApplyDamageEffect(
                    request=req,
                    element=spec.element,
                    damage_tag=spec.damage_type.value,
                    damage_type=spec.damage_type,
                )
            )
        sim.resolver.resolve_all()
        return True

    def _try_execute_base_damage_fastpath(
        self,
        spec: _DamageSpec,
        prep: _PreparedAttackData,
        ctx: ExecutionContext,
    ) -> bool:
        """处理绕过常规 attack 管道的 ByBaseDamage 直伤路径；命中则返回 True。"""
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        real_targets = spec.real_targets
        caster_ent_bd = sim.get_entity(spec.eff_attacker_id) if spec.eff_attacker_id != "__LEVEL__" else None
        is_level_base_dmg = spec.eff_attacker_id == "__LEVEL__" and spec.is_true_dmg and spec.final_formula == "ByBaseDamage"
        is_enemy_self_base_dmg = (
            spec.final_formula == "ByBaseDamage"
            and spec.eff_attacker_id != "__LEVEL__"
            and caster_ent_bd is not None
            and bool(getattr(caster_ent_bd, "is_enemy", False))
            and bool(real_targets)
            and all(tid == spec.eff_attacker_id for tid in real_targets)
        )
        is_enemy_to_player_base_dmg = (
            spec.final_formula == "ByBaseDamage"
            and spec.pct == 0.0
            and spec.eff_attacker_id != "__LEVEL__"
            and caster_ent_bd is not None
            and bool(getattr(caster_ent_bd, "is_enemy", False))
            and bool(real_targets)
            and all(
                (t_ent := sim.get_entity(tid)) is not None
                and not bool(getattr(t_ent, "is_enemy", False))
                for tid in real_targets
            )
        )
        if is_enemy_to_player_base_dmg:
            sp_base = 0.0
            sp_ratio = self._eval_num(spec.atk_prop.get("SPHitRatio"), ctx, 0.0)
            if sp_ratio > 0.0 and not spec.is_true_dmg and not spec.is_dot_dmg:
                sp_base = self._resolve_enemy_sp_hit_base(caster_ent_bd, ctx.ability_name)
            for tid in real_targets:
                tgt_ent = sim.get_entity(tid)
                if tgt_ent is None or float(getattr(tgt_ent, "current_hp", 0.0)) <= 0.0:
                    continue
                old_hp = float(tgt_ent.current_hp)
                raw_dmg = max(0.0, float(prep.eff_flat))
                if bool(getattr(tgt_ent, "_negative_hp_enabled", False)) and raw_dmg > 0.0 and old_hp - raw_dmg < min(old_hp, 1.0):
                    tgt_ent.current_hp = min(old_hp, 1.0)
                    actual = max(0.0, old_hp - float(tgt_ent.current_hp))
                    overflow = max(0.0, raw_dmg - actual)
                    if overflow > 0.0:
                        tgt_ent._negative_hp = float(getattr(tgt_ent, "_negative_hp", 0.0) or 0.0) + overflow
                else:
                    actual = min(old_hp, raw_dmg)
                    tgt_ent.current_hp = max(0.0, old_hp - actual)
                if actual > 0.0:
                    emit_sim_event(
                        sim,
                        HPLostEvent(
                            av=round(float(sim.current_av), 2),
                            cycle=int(sim.current_cycle),
                            entity_name=tid,
                            amount=float(actual),
                            hp_left=float(tgt_ent.current_hp),
                            cause=ctx.ability_name or "ByBaseDamage",
                        ),
                    )
                elif raw_dmg > 0.0 and bool(getattr(tgt_ent, "_negative_hp_enabled", False)):
                    me.dispatch_event(
                        "OnHPChange",
                        owner_id=tid,
                        param_entity_id=spec.eff_attacker_id,
                        change_value=-float(raw_dmg),
                        current_attack_type=spec.atk_type,
                        param_flags=("IsHPChangeByDamage",),
                    )
                    me.dispatch_event(
                        "OnListenHPChange",
                        param_entity_id=tid,
                        change_value=-float(raw_dmg),
                    )
                if raw_dmg > 0.0:
                    emit_sim_event(
                        sim,
                        DamageAppliedEvent(
                            av=round(float(sim.current_av), 2),
                            cycle=int(sim.current_cycle),
                            attacker_name=spec.eff_attacker_id,
                            target_name=tid,
                            damage=float(raw_dmg),
                            is_crit=False,
                            breakdown=DamageBreakdown(
                                attacker_name=spec.eff_attacker_id,
                                target_name=tid,
                                base_dmg=float(raw_dmg),
                                crit_mult=1.0,
                                is_crit=False,
                                dmg_boost_mult=1.0,
                                def_mult=1.0,
                                res_mult=1.0,
                                vuln_mult=1.0,
                                reduction_mult=1.0,
                                final_damage=float(raw_dmg),
                            ),
                            target_hp_left=float(tgt_ent.current_hp),
                            damage_tag=spec.damage_type.value,
                            damage_type=spec.damage_type,
                            target_killed=bool(
                                old_hp > 0.0
                                and float(tgt_ent.current_hp) <= 0.0
                                and not getattr(tgt_ent, "is_infinite_hp", False)
                            ),
                        )
                    )
                sp_hit = sp_base * sp_ratio * prep.hit_split
                if sp_hit > 0.0:
                    energy_tid = (getattr(tgt_ent, "master_name", None) or tid) if getattr(tgt_ent, "is_memosprite", False) else tid
                    sim.port.gain_hit_energy(energy_tid, base_amount=sp_hit)
                me.dispatch_event(
                    "OnAfterBeingHitAll",
                    owner_id=tid,
                    param_entity_id=spec.eff_attacker_id,
                    current_attack_type=spec.atk_type,
                )
                me.dispatch_event(
                    "OnListenAfterBeingHitAll",
                    param_entity_id=tid,
                    param_entity2_id=spec.eff_attacker_id,
                    damage_data={
                        "FinalDamage": float(raw_dmg),
                        "Result_FinalDamageBase": float(raw_dmg),
                    },
                    current_attack_type=spec.atk_type,
                )
            return True
        if is_level_base_dmg or is_enemy_self_base_dmg:
            can_last_kill = bool(spec.atk_prop.get("CanTriggerLastKill", False))
            last_killer = (
                getattr(rt, "_last_enemy_killer_id", "")
                or getattr(rt, "_current_attacker_id", "")
                or spec.eff_attacker_id
            )
            hp_change_param = "__LEVEL__" if is_level_base_dmg else spec.eff_attacker_id
            hp_change_atk_type = "TrueDamage" if is_level_base_dmg else (spec.atk_type or "TrueDamage")
            for tid in real_targets:
                tgt_ent = sim.get_entity(tid)
                if tgt_ent is None or tgt_ent.current_hp <= 0.0:
                    continue
                max_hp = float(sim.port.max_hp(tid))
                if spec.formula_type == "ByMaxHP":
                    raw_dmg = max_hp * float(prep.eff_pct) + float(prep.eff_flat)
                else:
                    raw_dmg = float(prep.eff_flat)
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
                from ...effects import sync_hp_shared_subtargets
                sync_hp_shared_subtargets(sim, tgt_ent)
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
                        eff_killer = "__LEVEL__" if is_level_base_dmg else spec.eff_attacker_id
                    if is_level_base_dmg and rt.lifecycle.in_attack_scope:
                        rt.lifecycle.enqueue_level_kill(tid, eff_killer)
                    else:
                        me.dispatch_event("OnBeforeDying", owner_id=tid, param_entity_id=eff_killer)
                        from simulator.events import EnemyDefeatedEvent
                        emit_sim_event(
                            sim,
                            EnemyDefeatedEvent(
                                av=float(sim.current_av),
                                cycle=int(sim.current_cycle),
                                attacker_name=eff_killer,
                                target_name=tid,
                            ),
                        )
                        me.destroy_all_for_entity(tid)
                        sim.entities[:] = [e for e in sim.entities if e.name != tid]
            return True
        return False

    def _resolve_standard_target_hits(
        self,
        spec: _DamageSpec,
        prep: _PreparedAttackData,
        ctx: ExecutionContext,
    ) -> Tuple[float, Dict[str, Any]]:
        """执行逐目标常规伤害命中循环、受击回能及段内亡语/limbo 状态采集。"""
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        real_targets = spec.real_targets
        dmg_data = prep.dmg_data
        extra_dmg_boost = prep.extra_dmg_boost
        extra_def_ignore = prep.extra_def_ignore
        extra_res_pen = prep.extra_res_pen
        extra_vuln = prep.extra_vuln
        extra_crit_dmg = prep.extra_crit_dmg
        base_mult_ratio = prep.base_mult_ratio
        eff_pct = prep.eff_pct
        eff_flat = prep.eff_flat

        captured = [0.0]
        self._damage_capture_stack.append(captured)
        sim.resolver.begin_aoe()
        try:
            caster_ent_pre = sim.get_entity(spec.eff_attacker_id)
            if (
                not spec.is_nested_sub
                and caster_ent_pre is not None
                and getattr(caster_ent_pre, "is_enemy", False)
                and real_targets
                and getattr(rt, "_open_enemy_attack", None) is None
            ):
                rt.begin_being_attacked(spec.eff_attacker_id, real_targets)
            any_died_mid_aoe = False
            pending_limbo: List[str] = []
            pending_dying: List[str] = []
            prop_src_id = spec.prop_source_id or spec.eff_attacker_id
            for idx, tid in enumerate(real_targets):
                live_attack_targets = (
                    tuple(real_targets[idx:])
                    if (idx > 0 and any_died_mid_aoe and not spec.is_true_dmg and spec.atk_type in ("Servant", "Pursued", "Ultra"))
                    else tuple(spec.targets)
                )
                if idx > 0 and any_died_mid_aoe and not spec.is_true_dmg and spec.atk_type in ("Servant", "Pursued", "Ultra"):
                    any_died_mid_aoe = False
                hit_dmg_data = dict(prep.base_before_hit_all)
                if (
                    caster_ent_pre is not None
                    and not getattr(caster_ent_pre, "is_enemy", False)
                    and not spec.is_nested_sub
                    and not spec.is_additional_dmg
                    and not spec.is_true_dmg
                    and not spec.is_dot_dmg
                ):
                    me.dispatch_event(
                        "OnBeforeBeingAttacked",
                        owner_id=tid,
                        param_entity_id=spec.eff_attacker_id,
                        attack_target_ids=tuple(spec.targets),
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                if not spec.is_true_dmg:
                    me.dispatch_event(
                        "OnBeforeHitAll",
                        owner_id=spec.eff_attacker_id,
                        param_entity_id=tid,
                        attack_target_ids=live_attack_targets,
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                    me.dispatch_event(
                        "OnListenBeforeHitAll",
                        param_entity_id=spec.eff_attacker_id,
                        param_entity2_id=tid,
                        attack_target_ids=live_attack_targets,
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                tgt_ent = sim.get_entity(tid)
                was_alive = bool(
                    tgt_ent is not None
                    and (getattr(tgt_ent, "current_hp", 0.0) > 0.0 or getattr(tgt_ent, "_in_deathrattle_limbo", False))
                )
                was_strictly_alive = bool(tgt_ent is not None and getattr(tgt_ent, "current_hp", 0.0) > 0.0)
                prev_tgt_hp = float(getattr(tgt_ent, "current_hp", 0.0)) if tgt_ent is not None else 0.0
                shared_main_id_pre = (getattr(rt, "hp_shared_groups", None) or {}).get(tid)
                shared_main_ent_pre = (
                    sim.get_entity(shared_main_id_pre)
                    if shared_main_id_pre and shared_main_id_pre != tid
                    else None
                )
                prev_shared_main_hp = (
                    float(getattr(shared_main_ent_pre, "current_hp", 0.0))
                    if shared_main_ent_pre is not None
                    else 0.0
                )
                prev_dmg_red = getattr(tgt_ent, "damage_reduction", 0.0) if tgt_ent is not None else 0.0
                applied_def_red = False
                tgt_extra_vuln = 0.0
                tgt_extra_def_ignore = 0.0
                tgt_extra_res_pen = 0.0
                tgt_hit_data: Dict[str, Any] = {"Element": spec.element, "CustomName": spec.custom_name}
                if tgt_ent is not None and not spec.is_true_dmg:
                    tgt_res_mod = 0.0
                    red_mult = 1.0 - prev_dmg_red
                    if getattr(tgt_ent, "is_enemy", False):
                        me.dispatch_event(
                            "OnBeforeBeingHitAll",
                            owner_id=tid,
                            param_entity_id=spec.eff_attacker_id,
                            damage_data=tgt_hit_data,
                            current_attack_type=spec.atk_type,
                        )
                        tgt_extra_vuln = float(tgt_hit_data.get("Defender_AllDamageTypeTakenRatio", 0.0))
                        tgt_extra_def_ignore = -float(tgt_hit_data.get("Defender_DefenceAddedRatio", 0.0))
                        tgt_res_mod = float(tgt_hit_data.get("Defender_AllDamageTypeResistance", 0.0))
                        def_red = float(tgt_hit_data.get("Defender_AllDamageReduce", 0.0))
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
                    setattr(tgt_ent, "_vm_base_damage_reduction", prev_dmg_red)
                if not spec.is_nested_sub:
                    me.dispatch_event(
                        "OnBeforeHit",
                        owner_id=spec.eff_attacker_id,
                        param_entity_id=tid,
                        attack_target_ids=tuple(spec.targets),
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                if not spec.is_nested_sub and not spec.is_additional_dmg:
                    me.dispatch_event(
                        "OnBeforeBeingHit",
                        owner_id=tid,
                        param_entity_id=spec.eff_attacker_id,
                        attack_target_ids=tuple(spec.targets),
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                    me.dispatch_event(
                        "OnListenBeforeBeingHit",
                        param_entity_id=tid,
                        param_entity2_id=spec.eff_attacker_id,
                        attack_target_ids=tuple(spec.targets),
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                    me.notify_entangle_being_attacked(tid, spec.eff_attacker_id, attack_type=spec.atk_type)
                if not spec.is_true_dmg:
                    (
                        hit_extra_dmg_boost,
                        hit_extra_def_ignore,
                        hit_extra_res_pen,
                        hit_extra_vuln,
                        hit_extra_crit_dmg,
                        hit_base_mult_ratio,
                        hit_eff_pct,
                        hit_eff_flat,
                    ) = _extract_damage_modifiers(spec, hit_dmg_data, prep.hit_split)
                    hit_res_delta = float(hit_dmg_data.get("Defender_AllDamageTypeResistance", 0.0)) - float(
                        dmg_data.get("Defender_AllDamageTypeResistance", 0.0)
                    )
                    if abs(hit_res_delta) > 1e-12:
                        tgt_extra_res_pen -= hit_res_delta
                    hit_def_red_delta = float(hit_dmg_data.get("Defender_AllDamageReduce", 0.0)) - float(
                        dmg_data.get("Defender_AllDamageReduce", 0.0)
                    )
                    if abs(hit_def_red_delta) > 1e-12 and tgt_ent is not None:
                        cur_red_mult = max(0.0, 1.0 - float(getattr(tgt_ent, "damage_reduction", 0.0)))
                        cur_red_mult *= max(0.0, 1.0 - hit_def_red_delta)
                        new_combined_red = max(0.0, 1.0 - cur_red_mult)
                        if abs(new_combined_red - prev_dmg_red) > 1e-9:
                            tgt_ent.damage_reduction = new_combined_red
                            applied_def_red = True
                    const_final_dmg: Optional[float] = None
                    if "AttackData_ConstFinalDamage" in hit_dmg_data:
                        const_final_dmg = float(hit_dmg_data["AttackData_ConstFinalDamage"])
                    elif (
                        tgt_ent is not None
                        and getattr(tgt_ent, "is_enemy", False)
                        and "AttackData_ConstFinalDamage" in tgt_hit_data
                    ):
                        const_final_dmg = float(tgt_hit_data["AttackData_ConstFinalDamage"])
                    if const_final_dmg is not None and const_final_dmg <= 0.0 and tgt_ent is not None:
                        tgt_ent.damage_reduction = 1.0
                        applied_def_red = True
                else:
                    hit_extra_dmg_boost = extra_dmg_boost
                    hit_extra_def_ignore = extra_def_ignore
                    hit_extra_res_pen = extra_res_pen
                    hit_extra_vuln = extra_vuln
                    hit_extra_crit_dmg = extra_crit_dmg
                    hit_eff_pct = eff_pct
                    hit_eff_flat = eff_flat
                hit_eff_stance = prep.eff_stance
                if hit_eff_stance > 0.0 and spec.eff_attacker_id and spec.eff_attacker_id != "__LEVEL__":
                    brk_eff = float(sim.port.stat(spec.eff_attacker_id, StatType.BREAK_EFFICIENCY)) + float(
                        hit_dmg_data.get("Attacker_StanceBreakAddedRatio", 0.0)
                    )
                    if abs(brk_eff) > 1e-12:
                        hit_eff_stance *= max(0.0, 1.0 + brk_eff)
                prev_active_atk = getattr(rt, "_active_damage_attacker_id", None)
                rt._active_damage_attacker_id = spec.eff_attacker_id
                try:
                    elation_level_base = 0.0
                    elation_point_num = 0.0
                    extra_elation = 0.0
                    extra_elation_extra = 0.0
                    if spec.is_elation_dmg:
                        atk_ent = sim.get_entity(prop_src_id)
                        raw_lvl = getattr(atk_ent, "level", 80) if atk_ent is not None else 80
                        atk_lvl = int(raw_lvl) if raw_lvl is not None else 80
                        elation_level_base = rt.loader.get_elation_basic_level_damage(atk_lvl)
                        if atk_lvl <= 0:
                            hit_eff_pct = 0.0
                            hit_eff_flat = 0.0
                        if "AttackData_ElationPointNum" in hit_dmg_data:
                            base_elation_pt = float(hit_dmg_data["AttackData_ElationPointNum"])
                        elif getattr(rt, "in_elation_time", False) and not spec.is_indirect:
                            ov_pt = float(getattr(rt, "elation_time_override_points", 0.0) or 0.0)
                            base_elation_pt = ov_pt if ov_pt > 0.0 else float(getattr(rt, "elation_points", 0.0) or 0.0)
                        else:
                            echo_pt = float(me.get_entity_property(spec.eff_attacker_id, "ElationEchoPoint") or 0.0)
                            if echo_pt <= 0.0 and prop_src_id != spec.eff_attacker_id:
                                echo_pt = float(me.get_entity_property(prop_src_id, "ElationEchoPoint") or 0.0)
                            base_elation_pt = echo_pt if echo_pt > 0.0 else float(getattr(rt, "elation_points", 0.0) or 0.0)
                        elation_point_num = base_elation_pt + float(
                            hit_dmg_data.get("AttackData_ElationPointNumDelta", 0.0) or 0.0
                        )
                        extra_elation = float(hit_dmg_data.get("Attacker_ElationDamageAddedRatio", 0.0) or 0.0)
                        extra_elation_extra = float(
                            hit_dmg_data.get("Attacker_ElationDamageExtraAddedRatio", 0.0) or 0.0
                        )
                    sim.port.attack(
                        spec.eff_attacker_id,
                        tid,
                        element=spec.element,
                        atk_multiplier=hit_eff_pct,
                        flat_damage=hit_eff_flat,
                        toughness_damage=hit_eff_stance,
                        scaling_stat=spec.scaling_stat,
                        damage_type=spec.damage_type,
                        force_crit=(False if spec.is_dot_dmg else None),
                        extra_dmg_boost=hit_extra_dmg_boost,
                        extra_def_ignore=hit_extra_def_ignore + tgt_extra_def_ignore,
                        extra_res_pen=hit_extra_res_pen + tgt_extra_res_pen,
                        extra_vuln=hit_extra_vuln + tgt_extra_vuln,
                        extra_crit_dmg=hit_extra_crit_dmg,
                        vm_hit_hooks_applied=not spec.is_true_dmg,
                        source_entity=(
                            getattr(ctx.modifier_instance, "caster_snapshot_entity", None)
                            if ctx.modifier_instance is not None
                            else None
                        ),
                        property_source_id=(prop_src_id if prop_src_id != spec.eff_attacker_id else None),
                        is_elation_dmg=spec.is_elation_dmg,
                        elation_level_base=elation_level_base,
                        elation_point_num=elation_point_num,
                        extra_elation=extra_elation,
                        extra_elation_extra=extra_elation_extra,
                    )
                    if not spec.is_true_dmg and not spec.is_dot_dmg and was_alive and tgt_ent is not None and not getattr(tgt_ent, "is_enemy", False):
                        caster_ent = sim.get_entity(spec.eff_attacker_id)
                        if caster_ent is not None and getattr(caster_ent, "is_enemy", False):
                            sp_base = self._resolve_enemy_sp_hit_base(caster_ent, ctx.ability_name)
                            sp_ratio = self._eval_num(spec.atk_prop.get("SPHitRatio"), ctx, 0.0)
                            sp_hit = sp_base * sp_ratio * prep.hit_split
                            if sp_hit > 0.0:
                                energy_tid = (getattr(tgt_ent, "master_name", None) or tid) if getattr(tgt_ent, "is_memosprite", False) else tid
                                sim.port.gain_hit_energy(energy_tid, base_amount=sp_hit)
                    sim.resolver.resolve_all()
                finally:
                    rt._active_damage_attacker_id = prev_active_atk
                    if tgt_ent is not None:
                        if applied_def_red:
                            tgt_ent.damage_reduction = prev_dmg_red
                        setattr(tgt_ent, "_vm_damage_reduction_active", False)
                        setattr(tgt_ent, "_vm_base_damage_reduction", 0.0)
                if not spec.is_true_dmg and not spec.is_nested_sub:
                    me.dispatch_event(
                        "OnAfterHit",
                        owner_id=spec.eff_attacker_id,
                        param_entity_id=tid,
                        attack_target_ids=tuple(spec.targets),
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                    me.dispatch_event(
                        "OnListenAfterHit",
                        param_entity_id=spec.eff_attacker_id,
                        param_entity2_id=tid,
                        attack_target_ids=tuple(spec.targets),
                        damage_data=hit_dmg_data,
                        current_attack_type=spec.atk_type,
                    )
                    if not spec.is_additional_dmg:
                        me.dispatch_event(
                            "OnAfterBeingHit",
                            owner_id=tid,
                            param_entity_id=spec.eff_attacker_id,
                            attack_target_ids=tuple(spec.targets),
                            damage_data=hit_dmg_data,
                            current_attack_type=spec.atk_type,
                        )
                        me.dispatch_event(
                            "OnListenAfterBeingHit",
                            param_entity_id=tid,
                            param_entity2_id=spec.eff_attacker_id,
                            attack_target_ids=tuple(spec.targets),
                            damage_data=hit_dmg_data,
                            current_attack_type=spec.atk_type,
                        )
                if len(real_targets) > 1 or applied_def_red:
                    if was_strictly_alive and tgt_ent is not None and getattr(tgt_ent, "current_hp", 0.0) <= 0.0:
                        any_died_mid_aoe = True
                shared_main_id = (getattr(rt, "hp_shared_groups", None) or {}).get(tid)
                if tgt_ent is not None and getattr(tgt_ent, "is_enemy", False) and (
                    float(getattr(tgt_ent, "current_hp", 0.0)) < prev_tgt_hp
                    or getattr(tgt_ent, "_in_deathrattle_limbo", False)
                    or shared_main_id is not None
                ):
                    director = getattr(sim, "_stage_director", None)
                    runner = getattr(director, "runner", None) if director is not None else None
                    if runner is not None:
                        limbo_check_ids = (tid, shared_main_id) if (shared_main_id and shared_main_id != tid) else (tid,)
                        for lcid in limbo_check_ids:
                            try:
                                mrs = runner.get_enemy_state(lcid)
                                if getattr(mrs, "_limbo_pending", False):
                                    setattr(mrs, "_limbo_pending", False)
                                    if spec.atk_type in ("Servant", "Pursued"):
                                        any_died_mid_aoe = True
                                    if lcid not in pending_limbo:
                                        pending_limbo.append(lcid)
                            except KeyError:
                                pass
                    died_candidates: List[str] = []
                    if was_strictly_alive and float(getattr(tgt_ent, "current_hp", 0.0)) <= 0.0:
                        died_candidates.append(tid)
                    if (
                        shared_main_ent_pre is not None
                        and prev_shared_main_hp > 0.0
                        and float(getattr(shared_main_ent_pre, "current_hp", 0.0)) <= 0.0
                    ):
                        died_candidates.append(shared_main_id_pre)
                    for dead_id_cand in died_candidates:
                        dead_cand_ent = sim.get_entity(dead_id_cand)
                        if dead_cand_ent is not None and me.has_behavior_flag(dead_id_cand, "Deathrattle"):
                            summoner_id = getattr(dead_cand_ent, "summoner_name", None)
                            if not summoner_id or not me.has_behavior_flag(summoner_id, "Break"):
                                enter_deathrattle_limbo(dead_cand_ent)
                        if dead_id_cand not in pending_dying:
                            pending_dying.append(dead_id_cand)
                        rt.lifecycle.enqueue_pending_dead(dead_id_cand)
                elif tgt_ent is not None and getattr(tgt_ent, "is_memosprite", False):
                    if was_strictly_alive and float(getattr(tgt_ent, "current_hp", 0.0)) <= 0.0:
                        if me.has_behavior_flag(tid, "Deathrattle"):
                            enter_deathrattle_limbo(tgt_ent)
                        if tid not in pending_dying:
                            pending_dying.append(tid)
                        rt.lifecycle.enqueue_pending_dead(tid)
            sim.resolver.resolve_all()
            if pending_dying:
                if spec.eff_attacker_id and spec.eff_attacker_id != "__LEVEL__":
                    rt._last_enemy_killer_id = spec.eff_attacker_id
                for d_tid in pending_dying:
                    rt.lifecycle.enqueue_or_process_dying(
                        d_tid,
                        spec.eff_attacker_id,
                        defer_in_after_attack=True,
                    )
            for l_tid in pending_limbo:
                if not rt.trigger_or_defer_limbo(l_tid, spec.eff_attacker_id):
                    me.dispatch_event("OnLimboWaitHeal", owner_id=l_tid, param_entity_id=spec.eff_attacker_id)
        finally:
            sim.resolver.end_aoe()
            self._damage_capture_stack.pop()
        return captured[0], dmg_data

    def _finalize_attack_lifecycle(
        self,
        spec: _DamageSpec,
        prep: _PreparedAttackData,
        dmg_data: Dict[str, Any],
        total_captured: float,
        ctx: ExecutionContext,
    ) -> None:
        """回填最终总伤，派发 AfterHitAll / AfterAttack 钩子并收口延迟死亡队列。"""
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        dmg_data["Result_FinalDamageBase"] = total_captured
        dmg_data["FinalDamage"] = total_captured

        if not spec.is_true_dmg:
            me.dispatch_event(
                "OnAfterHitAll",
                owner_id=spec.eff_attacker_id,
                attack_target_ids=tuple(spec.targets),
                damage_data=dmg_data,
                current_attack_type=spec.atk_type,
            )
            me.dispatch_event(
                "OnListenAfterHitAll",
                param_entity_id=spec.eff_attacker_id,
                attack_target_ids=tuple(spec.targets),
                damage_data=dmg_data,
                current_attack_type=spec.atk_type,
            )

        if not spec.is_nested_sub and not spec.is_additional_dmg:
            eff_sk_type = ctx.current_skill_type or spec.atk_type
            rt.lifecycle.schedule_after_attack(
                prep.atk_seq,
                spec.eff_attacker_id,
                dmg_data,
                spec.atk_type,
                eff_sk_type,
                fallback_targets=tuple(spec.targets),
            )

    def _execute_damage(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        spec = self._parse_damage_spec(task, ctx)
        if spec is None:
            return
        if self._try_execute_break_damage(spec, ctx):
            return
        prep = self._prepare_attack_hooks(spec, ctx)
        if self._try_execute_base_damage_fastpath(spec, prep, ctx):
            return
        total_captured, final_dmg_data = self._resolve_standard_target_hits(spec, prep, ctx)
        self._finalize_attack_lifecycle(spec, prep, final_dmg_data, total_captured, ctx)

    def _execute_lose_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        targets = self._resolve_targets(task.get("TargetType"), ctx)
        ratio_type = str(task.get("RatioType", "CurrentHP"))
        ratio = self._eval_num(task.get("Ratio"), ctx, 0.0) if "Ratio" in task else 0.0
        dmg_val = self._eval_num(task.get("DamageValue"), ctx, 0.0) if "DamageValue" in task else 0.0
        consume_shield = bool(task.get("ConsumeShield", False))
        has_explicit_floor = "Floor" in task
        hp_floor = self._eval_num(task.get("Floor"), ctx, 0.0) if has_explicit_floor else 1.0
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
                if has_explicit_floor:
                    eff_floor = hp_floor
                elif bool(getattr(ent, "_negative_hp_enabled", False)):
                    eff_floor = 1.0
                elif ratio_type == "CurrentHP" and ratio >= 1.0 - 1e-6:
                    eff_floor = 0.0
                else:
                    eff_floor = 1.0
                if consume_shield and raw_loss > 0.0:
                    raw_loss = me.intercept_team_block_damage(tid, raw_loss)
                    if raw_loss > 0.0 and hasattr(ent, "shield") and ent.shield > 0.0:
                        absorbed = min(float(ent.shield), raw_loss)
                        ent.shield -= absorbed
                        raw_loss -= absorbed
                        for m_shd in me.get_modifiers(tid):
                            if m_shd.shield_value > 0.0:
                                m_shd.shield_value = max(0.0, m_shd.shield_value - absorbed)

            actual_loss = max(0.0, min(ent.current_hp - eff_floor, raw_loss))
            diag_cb = getattr(sim, "timeline_diag_cb", None)
            if callable(diag_cb):
                diag_cb(
                    "LOSEHP",
                    f"target={tid} raw={raw_loss:.2f} actual={actual_loss:.2f} ab={ctx.ability_name}",
                )
            if actual_loss > 0:
                ent.current_hp -= actual_loss
                from ...effects import sync_hp_shared_subtargets
                sync_hp_shared_subtargets(sim, ent)
                emit_sim_event(sim, HPLostEvent(
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
                    eff_killer = ctx.caster_id or ""
                    if not eff_killer or eff_killer in ("__LEVEL__", tid):
                        cand = ctx.param_entity_id
                        if cand and cand not in ("__LEVEL__", tid) and sim.get_entity(cand) is not None:
                            eff_killer = cand
                        else:
                            act_atk = getattr(rt, "_active_damage_attacker_id", None)
                            if act_atk and act_atk not in ("__LEVEL__", tid):
                                eff_killer = act_atk
                    director = getattr(sim, "_stage_director", None)
                    runner = getattr(director, "runner", None) if director is not None else None
                    if runner is not None:
                        try:
                            mrs = runner.get_enemy_state(tid)
                            if getattr(mrs, "_limbo_pending", False):
                                if not rt.trigger_or_defer_limbo(tid, eff_killer):
                                    setattr(mrs, "_limbo_pending", False)
                                    me.dispatch_event("OnLimboWaitHeal", owner_id=tid, param_entity_id=eff_killer)
                        except KeyError:
                            pass
                    if ent.current_hp <= 0.0:
                        if me.has_behavior_flag(tid, "Deathrattle"):
                            summoner_id = getattr(ent, "summoner_name", None)
                            if not summoner_id or not me.has_behavior_flag(summoner_id, "Break"):
                                enter_deathrattle_limbo(ent)
                        from simulator.events import EnemyDefeatedEvent
                        emit_sim_event(
                            sim,
                            EnemyDefeatedEvent(
                                av=float(sim.current_av),
                                cycle=int(sim.current_cycle),
                                attacker_name=eff_killer or "",
                                target_name=tid,
                            ),
                        )
                        if rt.lifecycle.enqueue_or_process_dying(tid, eff_killer, defer_in_after_attack=False):
                            rt.lifecycle.enqueue_pending_dead(tid)
                        else:
                            if not getattr(ent, "_in_deathrattle_limbo", False) and float(getattr(ent, "current_hp", 0.0)) <= 0.0:
                                me.destroy_all_for_entity(tid)
                                if runner is not None:
                                    runner.state.enemies[:] = [m for m in runner.state.enemies if m.entity.name != tid]
                                sim.entities[:] = [e for e in sim.entities if e.name != tid]

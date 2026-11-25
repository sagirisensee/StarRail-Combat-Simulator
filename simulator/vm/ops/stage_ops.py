# coding: utf-8
"""ConfigAbility VM 关卡、怪物机制、弱点/削韧与无限波次算子 Mixin。"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from ...events import EnemyDefeatedEvent, HPLostEvent, WeaknessBreakEvent
from ...lifecycle import clear_deathrattle_limbo, emit_sim_event
from ...status import StatType
from ..expr import dotnet_hash
from ..target_alias import ExecutionContext
from .predicates import _str_val


class StageOpsMixin:
    """SummonMonster / SetMonsterPhase / LockHP / Weakness / DamageStance / InfiniteWave / ForceKill 算子。"""

    def _op_toggle_team_formation(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        t = task.get("$type", "")
        tgt_spec = task.get("TargetType") or {
            "Alias": ("ModifierOwnerEntity" if ctx.modifier_owner_id else "Caster")
        }
        targets = self._resolve_targets(tgt_spec, ctx)
        unselectable = t == "RPG.GameCore.RemoveEntityFromTeamFormation"
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is not None:
                ent.is_unselectable = unselectable

    def _op_force_kill(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        mute_death = bool(task.get("MuteAllTriggerDeath", False))
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is None:
                continue
            if getattr(ent, "is_enemy", False):
                rt.record_entity_team(ent)
                # 已进入亡语悬停且仍保有 Deathrattle 动作（如已被去除 Initiate 但仍有 Power 遗赠）的敌方，等待其亡语队列完成后再清场
                if (
                    getattr(ent, "_in_deathrattle_limbo", False)
                    and int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) > 0
                    and me.has_behavior_flag(tid, "Deathrattle")
                ):
                    setattr(ent, "_die_immediately_after_deathrattle", True)
                    continue
            if getattr(ent, "is_memosprite", False):
                me.dispatch_event("OnDeathrattle", owner_id=tid, param_entity_id=tid)
                master_id = getattr(ent, "master_name", None)
                me.dispatch_event(
                    "OnTriggerDeathrattle",
                    owner_id=master_id,
                    param_entity_id=tid,
                )
                if not mute_death:
                    me.dispatch_event("OnTriggerDeath", owner_id=tid, param_entity_id=tid)
                    done_set = getattr(rt, "_pre_despawn_trigger_death_done", None)
                    if done_set is None:
                        done_set = set()
                        setattr(rt, "_pre_despawn_trigger_death_done", done_set)
                    done_set.add(tid)
            prev_hp = float(getattr(ent, "current_hp", 0.0))
            was_limbo, was_deferred_die = clear_deathrattle_limbo(ent)
            ent.current_hp = 0.0
            if not getattr(ent, "is_enemy", False) and prev_hp > 0.0:
                emit_sim_event(
                    sim,
                    HPLostEvent(
                        av=round(float(sim.current_av), 2),
                        cycle=int(sim.current_cycle),
                        entity_name=tid,
                        amount=prev_hp,
                        hp_left=0.0,
                        cause="ForceKill",
                    ),
                )
            me.destroy_all_for_entity(tid)
            if getattr(ent, "is_enemy", False):
                eff_attacker = ctx.caster_id or ""
                c_ent = sim.get_entity(eff_attacker) if eff_attacker and eff_attacker != "__LEVEL__" else None
                if eff_attacker in ("", "__LEVEL__") or (c_ent is not None and getattr(c_ent, "monster_id", 0) == 8003060):
                    eff_attacker = getattr(rt, "_last_enemy_killer_id", "") or getattr(rt, "_current_attacker_id", "") or eff_attacker
                director = getattr(sim, "_stage_director", None)
                runner = getattr(director, "runner", None) if director is not None else None
                is_inf_stage = bool(
                    runner is not None
                    and getattr(getattr(runner.built_stage, "source_spec", None), "stage_infinite_group_id", None) is not None
                )
                if runner is not None and not is_inf_stage:
                    runner.state.enemies[:] = [m for m in runner.state.enemies if m.entity.name != tid]
                sim.entities[:] = [e for e in sim.entities if e.name != tid]
                rt.lifecycle.discard_pending_dead(tid)
                if prev_hp > 0.0:
                    emit_sim_event(
                        sim,
                        EnemyDefeatedEvent(
                            av=float(sim.current_av),
                            cycle=int(sim.current_cycle),
                            attacker_name=eff_attacker,
                            target_name=tid,
                        ),
                    )
                elif not mute_death and (was_deferred_die or was_limbo):
                    rt.lifecycle.defer_or_dispatch_listen_die(tid, defer_in_after_attack=False)
            elif not mute_death and (prev_hp > 0.0 or getattr(ent, "is_memosprite", False)):
                me.dispatch_event("OnListenCharacterDie", param_entity_id=tid)
            if getattr(ent, "is_memosprite", False) or getattr(ent, "is_countdown", False):
                sim.port.despawn_spirit(tid, reason="ForceKill")
            be_list = rt.named_targets.get("BattleEventEntityList")
            if be_list and tid in be_list:
                rt.named_targets["BattleEventEntityList"] = [x for x in be_list if x != tid]

    def _op_damage_perform_finish(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        self.rt.lifecycle.settle_attack_boundary()

    def _op_summon_monster(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        if getattr(rt, "_skip_vm_summon_monster", False):
            return
        director = getattr(sim, "_stage_director", None)
        if director is not None and hasattr(director, "flush_ally_talent_heals"):
            director.flush_ally_talent_heals()
        data_list = task.get("SummonMonsterDataList") or []
        if data_list and isinstance(data_list[0], Mapping) and data_list[0].get("LocationType") == "FormationRecord":
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None and hasattr(runner, "refill_next_infinite_monster"):
                slot_spec = data_list[0].get("MonsterSlot")
                slot_val = int(round(self._eval_num(slot_spec, ctx, -1.0))) if slot_spec is not None else -1
                dr_spec = task.get("DelayRatio")
                dr_val = self._eval_num(dr_spec, ctx, 0.3) if dr_spec is not None else None
                ent = runner.refill_next_infinite_monster(
                    formation_slot=(slot_val if slot_val >= 0 else None),
                    delay_ratio=dr_val,
                )
                if ent is not None:
                    rt.named_targets["LastSummonMonsters"] = [ent.name]
                    if director is not None:
                        director.sync_spawned_entities()
            return
        if director is not None and hasattr(director, "summon_enemy"):
            spawned = director.summon_enemy(
                ctx.caster_id,
                task,
                dynamic_resolver=lambda h: self.rt.resolve_hash(
                    ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx
                ),
            )
            rt.named_targets["LastSummonMonsters"] = [e.name for e in (spawned or ()) if e is not None]

    def _op_set_monster_phase(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        director = getattr(sim, "_stage_director", None)
        if director is not None and hasattr(director, "trigger_monster_phase_transition"):
            mode = str(task.get("SetMode") or task.get("Mode") or "Set")
            val_spec = task.get("PhaseValue") if "PhaseValue" in task else task.get("Value")
            val = (
                int(round(self._eval_num(val_spec, ctx, 1.0)))
                if val_spec is not None
                else (1 if mode == "Set" else None)
            )
            targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.caster_id]
            for tid in targets:
                director.trigger_monster_phase_transition(tid, mode=mode, value=val)

    def _op_stage_runner_task(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        me = self.rt.modifier_engine
        t = task.get("$type", "")
        if t == "RPG.GameCore.LockHP" and ctx.modifier_instance is not None:
            setattr(ctx.modifier_instance, "_applied_lock_hp", True)
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None and hasattr(runner, "execute_stage_task"):
            targets = (
                self._resolve_targets(task.get("TargetType"), ctx)
                if task.get("TargetType") is not None
                else [ctx.modifier_owner_id or ctx.caster_id]
            )
            for tid in targets or [ctx.modifier_owner_id or ctx.caster_id]:
                tgt_eb = sim.get_entity(tid)
                was_broken_eb = bool(tgt_eb is not None and getattr(tgt_eb, "is_broken", False))
                runner.execute_stage_task(
                    task,
                    caster_name=tid,
                    dynamic_resolver=lambda h: self.rt.resolve_hash(
                        ctx.caster_id, h, ability_name=ctx.ability_name, local_ctx=ctx
                    ),
                )
                if (
                    t in ("RPG.GameCore.ExitBreakState", "RPG.GameCore.ResetStance")
                    and was_broken_eb
                    and tgt_eb is not None
                    and not getattr(tgt_eb, "is_broken", False)
                ):
                    me.dispatch_event("OnEndBreak", owner_id=tid, param_entity_id=tid)
                    me.dispatch_event("OnListenEndBreak", param_entity_id=tid)

    def _op_stack_weakness(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        from ..stage_factory import normalize_element

        sim = self.rt.sim
        me = self.rt.modifier_engine
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if task.get("TargetType") is not None
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        targets = targets or [ctx.modifier_owner_id or ctx.caster_id]
        raw_op = task.get("OPType")
        op_type = "Override" if not raw_op else str(raw_op)
        raw_list = task.get("WeakList") or ()
        norm_list = tuple(normalize_element(w) for w in raw_list if w)
        if ctx.modifier_instance is not None:
            for tid in targets:
                ctx.modifier_instance.stacked_weaknesses.setdefault(tid, []).append((op_type, norm_list))
                me.recompute_entity_weaknesses(tid)
        else:
            director = getattr(sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                for tid in targets:
                    if tid in getattr(runner, "_enemy_by_name", ()):
                        runner.execute_stack_weakness(tid, raw_list, op_type=op_type)

    def _op_clear_weakness(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        from ..stage_factory import normalize_element

        sim = self.rt.sim
        me = self.rt.modifier_engine
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if task.get("TargetType") is not None
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        targets = targets or [ctx.modifier_owner_id or ctx.caster_id]
        raw_op = str(task.get("OPType") or "")
        clear_op = (
            "ClearProtected"
            if raw_op == "Protected"
            else ("ClearAttach" if raw_op == "Attach" else ("ClearSecret" if raw_op == "Secret" else "Clear"))
        )
        if clear_op == "ClearSecret":
            return
        norm_list = tuple(normalize_element(w) for w in (task.get("WeakList") or ()) if w)
        if ctx.modifier_instance is not None:
            for tid in targets:
                ctx.modifier_instance.stacked_weaknesses.setdefault(tid, []).append((clear_op, norm_list))
                me.recompute_entity_weaknesses(tid)
        else:
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                if clear_op == "ClearProtected":
                    ent.toughness_locked = False
                else:
                    ent.weaknesses[:] = [w for w in getattr(ent, "weaknesses", []) if w not in norm_list]

    def _op_stack_weak_resistance(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        from ..stage_factory import normalize_element

        sim = self.rt.sim
        me = self.rt.modifier_engine
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if task.get("TargetType") is not None
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        targets = targets or [ctx.modifier_owner_id or ctx.caster_id]
        stype = str(task.get("StackType") or "Delta")
        entries = []
        for item in task.get("StackResistanceList") or ():
            if not isinstance(item, Mapping):
                continue
            elem = normalize_element(str(item.get("DamageType") or ""))
            val = self._eval_num(item.get("Value"), ctx, 0.0)
            if elem:
                entries.append((stype, elem, val))
        if not entries:
            return
        if ctx.modifier_instance is not None:
            for tid in targets:
                ctx.modifier_instance.weak_resistance_deltas.setdefault(tid, []).extend(entries)
                me.recompute_entity_damage_res(tid)
        else:
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is None:
                    continue
                res = dict(getattr(ent, "damage_res", {}) or {})
                for st, elem, val in entries:
                    res[elem] = float(res.get(elem, 0.0)) + val if st == "Delta" else float(val)
                ent.damage_res = res

    def _op_trigger_stance_count_down(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        director = getattr(sim, "_stage_director", None)
        port = getattr(director, "port", None) if director is not None else None
        for tid in targets:
            if port is not None and hasattr(port, "break_entity_toughness_and_deduct_hp"):
                port.break_entity_toughness_and_deduct_hp(tid, hp_deduct=0.0, break_delay=2500.0)

    def _op_init_single_block(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        val = max(0.0, self._eval_num(task.get("MCNPMDPMCKM"), ctx, 0.0))
        mod = ctx.modifier_instance
        if mod is not None and val > 0.0:
            setattr(mod, "single_block_max", val)
            setattr(mod, "single_block_cur", val)
            mod.dynamic_values[2124040366] = val
            mod.dynamic_values[-276442507] = val
            owner_ent = sim.get_entity(mod.owner_id)
            if owner_ent is not None:
                owner_ent.barrier_guarded = True
                owner_ent.toughness_locked = True
                director = getattr(sim, "_stage_director", None)
                runner = getattr(director, "runner", None) if director is not None else None
                if runner is not None:
                    try:
                        if runner.get_enemy_state(mod.owner_id).phase >= 2:
                            saved_tdr = getattr(owner_ent, "_phase_saved_toughness_dmg_reduction", getattr(owner_ent, "toughness_dmg_reduction", 0.10))
                            setattr(mod, "_saved_toughness_dmg_reduction", saved_tdr)
                            owner_ent.toughness_dmg_reduction = 0.0
                    except KeyError:
                        pass

    def _op_add_stage_ability_by_name(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        ab_name = _str_val(task.get("StageAbilityName"))
        if ab_name:
            owner = "__LEVEL__"
            can_replace = bool(task.get("CanReplace", True))
            eq_key = (owner, ab_name)
            if can_replace or eq_key not in rt.equip_dynamics:
                dyn_map: Dict[int, float] = {}
                for dk, dv in (task.get("DynamicValues") or {}).items():
                    val = self._eval_num(dv, ctx, 0.0)
                    kh = dotnet_hash(str(dk))
                    dyn_map[kh] = val
                    rt.set_dynamic_value(owner, kh, val, ability_name=ab_name)
                rt.equip_dynamics[eq_key] = dyn_map
            ab = rt.loader.get_ability(ab_name)
            if ab is not None and ab.get("OnAdd"):
                add_key = (owner, ab_name)
                if can_replace or add_key not in rt._added_abilities:
                    rt._added_abilities.add(add_key)
                    add_ctx = ExecutionContext(
                        runtime=rt,
                        caster_id=owner,
                        ability_name=ab_name,
                        ability_target_ids=(owner,),
                    )
                    self.execute_tasks(ab["OnAdd"], add_ctx)

    def _op_damage_stance(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        tgt_spec = task.get("DefenderTargetType") or task.get("TargetType")
        targets = self._resolve_targets(tgt_spec, ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        atk_targets = (
            self._resolve_targets(task.get("AttackerTargetType"), ctx)
            if task.get("AttackerTargetType") is not None
            else []
        )
        atk_id = atk_targets[0] if atk_targets else ctx.caster_id
        atk_ent = sim.get_entity(atk_id) if atk_id else None
        force_stance = bool(task.get("ForceStanceDamage", False) or task.get("IgnoreMuteBreak", False))
        sdt = task.get("StanceDamageType")
        explicit_elem = (
            str(sdt.get("DamageType"))
            if isinstance(sdt, Mapping) and sdt.get("DamageType")
            else (str(sdt) if sdt else "")
        )
        break_table = getattr(rt.loader, "_break_base_by_level", None)
        if break_table is None:
            break_table = {}
            try:
                for row in rt.loader._read_excel("AvatarBreakDamage.json"):
                    lv = int(row.get("Level", 0) or 0)
                    bv = row.get("BreakBaseDamage", {})
                    if lv > 0:
                        break_table[lv] = float(
                            bv.get("Value", 0.0) if isinstance(bv, Mapping) else (bv or 0.0)
                        )
            except Exception:
                break_table = {}
            setattr(rt.loader, "_break_base_by_level", break_table)

        def _calc_stance_break_dmg(ent_obj: Any, eid: str, st_el: str) -> float:
            atk_lvl = int(getattr(atk_ent, "level", None) or getattr(ent_obj, "level", 95) or 95)
            tgt_lvl = int(getattr(ent_obj, "level", 95) or 95)
            base_break = float(break_table.get(atk_lvl, 7494.3716 if atk_lvl >= 95 else 3767.5535))
            elem_mult = (
                2.0
                if st_el in ("Physical", "Fire")
                else (1.5 if st_el == "Wind" else (0.5 if st_el in ("Quantum", "Imaginary") else 1.0))
            )
            tough_mult = 0.5 + (float(getattr(ent_obj, "max_toughness", 0.0)) / 120.0)
            sm = getattr(sim, "status_mgr", None)
            be = float(getattr(atk_ent, "base_break_effect", 0.0) or 0.0) if atk_ent is not None else 0.0
            if sm is not None and atk_id:
                be = sm.calculate_stat(atk_id, be, StatType.BREAK_EFFECT)
            def_shred = sm.calculate_stat(eid, 0.0, StatType.DEF_SHRED) if sm else 0.0
            def_ignore = (
                sm.calculate_stat(atk_id, 0.0, StatType.DEF_SHRED)
                if (sm is not None and atk_id and atk_id != eid)
                else 0.0
            )
            def_mult = (atk_lvl + 20.0) / (
                (tgt_lvl + 20.0) * max(0.0, 1.0 - def_shred - def_ignore) + (atk_lvl + 20.0)
            )
            base_res = float((getattr(ent_obj, "damage_res", {}) or {}).get(st_el, 0.0))
            tgt_res_mod = 0.0
            red_mult = 1.0 - max(0.0, min(1.0, float(getattr(ent_obj, "damage_reduction", 0.0))))
            for m_def in me.get_modifiers(eid):
                m_red = float(m_def.properties.get("AllDamageReduce", 0.0))
                if m_red > 0.0:
                    red_mult *= max(0.0, 1.0 - m_red)
                tgt_res_mod += float(m_def.properties.get("AllDamageTypeResistance", 0.0))
            res_mult = max(0.0, 1.0 - (base_res + tgt_res_mod))
            vuln = sm.calculate_stat(eid, 0.0, StatType.VULNERABILITY) if sm else 0.0
            vuln_mult = 1.0 + vuln
            tough_red = max(0.0, 1.0 - float(getattr(ent_obj, "toughness_dmg_reduction", 0.10)))
            return (
                base_break
                * elem_mult
                * tough_mult
                * (1.0 + be)
                * def_mult
                * res_mult
                * vuln_mult
                * tough_red
                * red_mult
            )

        sval = self._eval_num(task.get("StanceValue"), ctx, 0.0)
        if sval > 0.0:
            for tid in targets:
                ent = sim.get_entity(tid)
                rem_s = float(sval)
                while (
                    rem_s > 0.0
                    and ent is not None
                    and getattr(ent, "current_toughness", 0.0) > 0.0
                    and not getattr(ent, "is_broken", False)
                    and (force_stance or not getattr(ent, "toughness_locked", False))
                ):
                    cur_t = float(ent.current_toughness)
                    if rem_s < cur_t:
                        ent.current_toughness = cur_t - rem_s
                        rem_s = 0.0
                        break
                    rem_s -= cur_t
                    ent.current_toughness = 0.0
                    st_elem = explicit_elem or str(getattr(ent, "stance_type", None) or "Imaginary")
                    cur_sc = int(getattr(ent, "current_stance_count", 1) or 1)
                    if cur_sc > 1:
                        ent.current_stance_count = cur_sc - 1
                        if task.get("TriggerCountDown", False):
                            cd_dmg = _calc_stance_break_dmg(ent, tid, st_elem)
                            kit = getattr(ent, "kit", None)
                            actual_loss = (
                                kit.intercept_incoming_damage(tid, cd_dmg)
                                if kit is not None and hasattr(kit, "intercept_incoming_damage")
                                else cd_dmg
                            )
                            ent.current_hp = max(0.0, float(ent.current_hp) - actual_loss)
                        ent.current_toughness = float(ent.max_toughness)
                    else:
                        brk_dmg = _calc_stance_break_dmg(ent, tid, st_elem)
                        ent.current_stance_count = 0
                        ent.is_broken = True
                        from ...effects import sync_hp_shared_subtargets

                        shared_map = getattr(rt, "hp_shared_groups", None)
                        main_id = shared_map.get(tid) if shared_map else None
                        main_ent = sim.get_entity(main_id) if main_id else None
                        if main_ent is not None and main_ent is not ent and float(getattr(main_ent, "current_hp", 0.0)) > 0.0:
                            m_kit = getattr(main_ent, "kit", None)
                            actual_loss = (
                                m_kit.intercept_incoming_damage(main_id, brk_dmg)
                                if m_kit is not None and hasattr(m_kit, "intercept_incoming_damage")
                                else brk_dmg
                            )
                            main_ent.current_hp = max(0.0, float(main_ent.current_hp) - actual_loss)
                            sync_hp_shared_subtargets(sim, main_ent)
                        else:
                            kit = getattr(ent, "kit", None)
                            actual_loss = (
                                kit.intercept_incoming_damage(tid, brk_dmg)
                                if kit is not None and hasattr(kit, "intercept_incoming_damage")
                                else brk_dmg
                            )
                            ent.current_hp = max(0.0, float(ent.current_hp) - actual_loss)
                            sync_hp_shared_subtargets(sim, ent)
                        ent.delay_action(0.25)
                        sm_be = getattr(sim, "status_mgr", None)
                        atk_be = float(getattr(atk_ent, "base_break_effect", 0.0) or 0.0) if atk_ent is not None else 0.0
                        if sm_be is not None and atk_id:
                            atk_be = sm_be.calculate_stat(atk_id, atk_be, StatType.BREAK_EFFECT)
                        entangle_applied = True
                        if st_elem == "Quantum":
                            ctrl_immune = False
                            if me.has_behavior_flag(tid, "Endurance") or me.has_behavior_flag(tid, "EnduranceLogicOnly"):
                                ctrl_immune = True
                            if not ctrl_immune:
                                debuff_res = getattr(ent, "debuff_resist", None)
                                if isinstance(debuff_res, dict) and float(debuff_res.get("STAT_CTRL", 0.0)) >= 1.0 - 1e-6:
                                    ctrl_immune = True
                            if ctrl_immune:
                                entangle_applied = False
                            else:
                                debuff_prov = getattr(sim, "debuff_hit_provider", None)
                                if callable(debuff_prov):
                                    entangle_applied = bool(
                                        debuff_prov(
                                            atk_ent,
                                            ent,
                                            "Quantum_Entanglement",
                                            round(float(getattr(sim, "current_av", 0.0)), 2),
                                        )
                                    )
                        emit_sim_event(
                            sim,
                            WeaknessBreakEvent(
                                av=round(float(getattr(sim, "current_av", 0.0)), 2),
                                cycle=int(getattr(sim, "current_cycle", 0)),
                                breaker_name=atk_id,
                                target_name=tid,
                                element=st_elem,
                                break_damage=brk_dmg,
                                action_delay_pct=0.25,
                                entangle_applied=entangle_applied,
                            ),
                        )
                        break

    def _op_destroy_battle_character(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        uniq = str(task.get("CharacterUniqueName") or "")
        if uniq:
            targets = list(rt.named_targets.get(uniq, ()))
            if not targets and sim.get_entity(uniq) is not None:
                targets = [uniq]
        elif "TargetType" in task:
            targets = self._resolve_targets(task.get("TargetType"), ctx)
        else:
            targets = []
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is not None:
                ent.current_hp = 0.0
                me.destroy_all_for_entity(tid)
                if hasattr(sim, "remove_entity"):
                    sim.remove_entity(tid)

    def _op_lock_target_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        lock_key = str(task.get("LockKey") or "default")
        thresh = self._eval_num(task.get("Threshold"), ctx, 1.0)
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is not None:
                locks = getattr(ent, "_locked_hp_thresholds", None)
                if locks is None:
                    locks = {}
                    setattr(ent, "_locked_hp_thresholds", locks)
                locks[lock_key] = max(1.0, float(thresh))

    def _op_unlock_target_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        lock_key = str(task.get("LockKey") or "default")
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is not None:
                locks = getattr(ent, "_locked_hp_thresholds", None)
                if isinstance(locks, dict):
                    locks.pop(lock_key, None)

    def _op_disable_locked_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        if str(task.get("MEPFOEEGBEA", "")) == "Disable":
            targets = self._resolve_targets(task.get("HILNFHCPEAD"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
            for tid in targets:
                ent = sim.get_entity(tid)
                if ent is not None:
                    locks = getattr(ent, "_locked_hp_thresholds", None)
                    if isinstance(locks, dict):
                        locks.clear()

    def _op_set_die_immediately(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        targets = self._resolve_targets(task.get("TargetType"), ctx) or [ctx.modifier_owner_id or ctx.caster_id]
        active_dr = getattr(rt, "_active_deathrattle_entities", ())
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is not None and getattr(ent, "_in_deathrattle_limbo", False):
                if tid in active_dr or int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) > 0:
                    setattr(ent, "_die_immediately_after_deathrattle", True)
                else:
                    setattr(ent, "_die_immediately_after_deathrattle", False)
                    setattr(ent, "_in_deathrattle_limbo", False)
                    ent.current_hp = 0.0
                    me.destroy_all_for_entity(tid)

    def _op_owner_entity_add_ability(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        ab_name = _str_val(task.get("AbilityName"))
        if ab_name:
            targets = (
                self._resolve_targets(task.get("TargetType"), ctx)
                if "TargetType" in task
                else [ctx.modifier_owner_id or ctx.caster_id]
            )
            init_dyn: Dict[int, float] = {}
            for dk, dv in (task.get("DynamicValues") or {}).items():
                init_dyn[dotnet_hash(str(dk))] = self._eval_num(dv, ctx, 0.0)
            rt.loader.ensure_ability_index()
            ab_doc = rt.loader.get_ability(ab_name)
            for tid in targets:
                for kh, val in init_dyn.items():
                    rt.set_dynamic_value(tid, kh, val, ability_name=ab_name)
                if ab_doc:
                    sub_ctx = ctx.clone(
                        caster_id=tid,
                        ability_name=ab_name,
                        ability_target_ids=(tid,),
                        modifier_owner_id=tid,
                        local_dynamics=dict(init_dyn),
                    )
                    on_add = ab_doc.get("OnAdd")
                    if on_add:
                        self.execute_tasks(on_add, sub_ctx)

    def _op_infinite_wave_add_max_count(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        delta = int(round(self._eval_num(task.get("AddDelta"), ctx, 0.0)))
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            runner.state.infinite_wave_max_count = max(
                0, runner.state.infinite_wave_max_count + delta
            )

    def _op_record_entity_formation_index(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = self._resolve_targets(task.get("TargetType"), ctx)
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            for tid in targets:
                for idx, mrs in enumerate(runner.state.enemies):
                    if mrs.entity.name == tid:
                        if idx not in runner.state.recorded_formation_slots:
                            runner.state.recorded_formation_slots.append(idx)
                        break

    def _op_infinite_wave_next_monster_id(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        rt = self.rt
        sim = rt.sim
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            wave_bp = runner.built_stage.waves[runner.state.wave_index]
            cur = runner.state.infinite_wave_cursor
            limit = min(len(wave_bp.enemies), runner.state.infinite_wave_max_count)
            next_mid = float(wave_bp.enemies[cur].monster_id) if cur < limit else 0.0
            next_eg = float(wave_bp.enemies[cur].elite_group) if cur < limit else 0.0
            slot = (
                float(runner.state.recorded_formation_slots.pop())
                if runner.state.recorded_formation_slots
                else -1.0
            )
            for key_field, val in (
                ("MonsterIDKey", next_mid),
                ("EliteGroupKey", next_eg),
                ("MonsterSlotKey", slot),
            ):
                kname = _str_val(task.get(key_field))
                if kname:
                    kh = dotnet_hash(kname)
                    ctx.local_dynamics[kh] = val
                    rt.set_dynamic_value(ctx.caster_id, kh, val, ability_name=ctx.ability_name)

    def _op_clear_record_entity_formation(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            runner.state.recorded_formation_slots.clear()

    def _op_set_level_challenge_turn_limit(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        val = self._eval_num(task.get("LimitCount"), ctx, 0.0)
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            runner.state.challenge_turn_limit = max(0, int(round(val)))

    def _op_level_challenge_turn_acc(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            runner.state.challenge_turns_elapsed += 1

    def _op_enable_negative_hp(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        targets = (
            self._resolve_targets(task.get("TargetType"), ctx)
            if task.get("TargetType") is not None
            else [ctx.modifier_owner_id or ctx.caster_id]
        )
        for tid in targets:
            ent = sim.get_entity(tid)
            if ent is not None:
                setattr(ent, "_negative_hp_enabled", True)
                if ctx.modifier_instance is not None:
                    setattr(ctx.modifier_instance, "_enabled_negative_hp", True)

    def _op_abort_insert_ability(self, task: Mapping[str, Any], ctx: ExecutionContext) -> None:
        sim = self.rt.sim
        ab_name = _str_val(task.get("AbilityName"))
        tgt_spec = task.get("TargetFilter") or task.get("TargetType")
        targets = self._resolve_targets(tgt_spec, ctx) if tgt_spec is not None else None
        sched = getattr(sim, "scheduler", None)
        if ab_name and sched is not None and hasattr(sched, "abort_pending_actions"):
            sched.abort_pending_actions(targets, ab_name)

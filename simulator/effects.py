"""星穹铁道效果请求与事务结算模块 (Effect Request & Resolver)。

核心理念（遵从架构师规范）：
1. 角色技能和被动不直接篡改游戏状态，而是向结算上下文投递 `EffectRequest`；
2. 由统一的 `EffectResolver` 执行状态变更，产生对应的 `BattleEvent`；
3. 伤害、削韧、弱点击破与推条解耦结算，伤害分摊通过 `KitHandler.intercept_incoming_damage` 协议多态分发，绝不硬编码特定角色名；
4. 严格限制最大结算步数 (MAX_EFFECT_STEPS)，彻底防止追击/触发产生无限死循环递归。
"""
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional
from .events import (
    ActionAdvanceEvent, ActionDelayEvent, SPChangeEvent, StatusApplyEvent, 
    ActionExecuteEvent, DamageAppliedEvent, EnemyDefeatedEvent,
    ToughnessReduceEvent, WeaknessBreakEvent, HPLostEvent
)
from .damage import DamageCalculator, DamageRequest, DamageBreakdown
from .actions import DamageType
from .lifecycle import emit_sim_event


MAX_EFFECT_STEPS = 100


class EffectRequest:
    """所有战斗效果请求的基类。"""
    pass


@dataclass
class AdvanceActionEffect(EffectRequest):
    source_name: str
    target: Any                 # 目标实体
    percent: float              # 拉条百分比，如 0.5


@dataclass
class DelayActionEffect(EffectRequest):
    source_name: str
    target: Any
    percent: float              # 推条百分比，如 0.25


@dataclass
class ModifySPEffect(EffectRequest):
    actor_name: str
    delta: int                  # +1 或 -1 或 +4
    reason: str


@dataclass
class InterruptActionEffect(EffectRequest):
    actor: Any
    description: str
    sp_change: int = 0


@dataclass
class ApplyStatusEffect(EffectRequest):
    status: Any                 # StatusInstance


@dataclass
class ReduceToughnessEffect(EffectRequest):
    attacker: Any
    target: Any
    amount: float               # 削韧数值 (如 20)
    element: str = "Physical"   # 攻击属性
    break_effect: float = 0.0   # 击破特攻
    ignore_weakness: bool = False # 是否无视弱点削韧 (如黄泉终结技)


@dataclass
class ApplyDamageEffect(EffectRequest):
    request: DamageRequest
    toughness_reduction: float = 0.0
    element: str = "Physical"
    break_effect: float = 0.0
    ignore_weakness: bool = False
    damage_tag: str = "direct"
    damage_type: Optional[DamageType] = None  # 权威伤害分类；为 None 时由 damage_tag 经 DamageType.from_tag 收编
    action_id: int = 0


def sync_hp_shared_subtargets(simulator: Any, main_ent: Any) -> None:
    """按 DefineHPSharedGroup 主目标当前血量比例同步全部子目标 HP。"""
    if simulator is None or main_ent is None:
        return
    vm_rt = getattr(simulator, "vm_runtime", None)
    shared_map = getattr(vm_rt, "hp_shared_groups", None) if vm_rt is not None else None
    if not shared_map:
        return
    main_id = getattr(main_ent, "name", "")
    if not main_id:
        return
    sub_ids = [sid for sid, mid in shared_map.items() if mid == main_id]
    if not sub_ids:
        return
    port = getattr(simulator, "port", None)
    main_max = float(port.max_hp(main_id)) if port is not None else float(getattr(main_ent, "max_hp", 0.0) or 0.0)
    if main_max <= 0.0:
        return
    hp_ratio = max(0.0, float(main_ent.current_hp) / main_max)
    for sid in sub_ids:
        sub_ent = simulator.get_entity(sid)
        if sub_ent is None or sub_ent is main_ent:
            continue
        sub_max = float(port.max_hp(sid)) if port is not None else float(getattr(sub_ent, "max_hp", 0.0) or 0.0)
        if sub_max <= 0.0:
            continue
        new_sub_hp = max(0.0, sub_max * hp_ratio)
        kit = getattr(sub_ent, "kit", None)
        if kit is not None:
            runner = getattr(kit, "runner", None)
            if runner is not None:
                try:
                    mrs = runner.get_enemy_state(sid)
                    if getattr(mrs, "lock_hp_ratio", None) is not None and mrs.lock_hp_ratio > 0.0:
                        new_sub_hp = max(new_sub_hp, sub_max * float(mrs.lock_hp_ratio))
                except KeyError:
                    pass
        sub_ent.current_hp = new_sub_hp


class EffectResolver:
    """效果结算器：唯一的状态写入入口。"""
    def __init__(self, simulator: Any):
        self.simulator = simulator
        self.queue: List[EffectRequest] = []
        self._step_count = 0
        self._resolving = False
        self._aoe_depth = 0
        self._hit_energy_action_recipients = set()
        self._post_resolve_callbacks: List[Any] = []

    def begin_aoe(self) -> None:
        self._aoe_depth += 1

    def end_aoe(self) -> None:
        self._aoe_depth = max(0, self._aoe_depth - 1)
        if self._aoe_depth == 0 and not self._resolving:
            self._drain_post_resolve()

    def _drain_post_resolve(self) -> None:
        while self._post_resolve_callbacks:
            cb = self._post_resolve_callbacks.pop(0)
            cb()

    def defer_post_resolve(self, fn: Any) -> None:
        """在当前效果队列排空后执行的回调（如群攻全部命中后的亡语反噬）。"""
        self._post_resolve_callbacks.append(fn)

    def enqueue(self, effect: EffectRequest):
        """将效果放入待结算队列。"""
        self.queue.append(effect)

    def resolve_all(self):
        """排空并执行队列中的所有效果。"""
        self._step_count = 0
        self._resolving = True
        try:
            while self.queue:
                self._step_count += 1
                if self._step_count > MAX_EFFECT_STEPS:
                    raise RuntimeError(f"效果结算步数超过上限 ({MAX_EFFECT_STEPS})，检测到潜在的无限递归触发！")

                effect = self.queue.pop(0)
                self._resolve_one(effect)
        finally:
            self._resolving = False

        if self._aoe_depth == 0:
            self._drain_post_resolve()

        scheduler = getattr(self.simulator, "scheduler", None)
        if scheduler is not None and scheduler.can_auto_drain() and scheduler.has_pending():
            scheduler.drain()

    def _handle_enemy_defeated(self, attacker: Any, target: Any, av: float, cycle: int) -> None:
        """击败敌方时结算击杀回能并发布 EnemyDefeatedEvent。"""
        if not getattr(target, "is_enemy", False) or getattr(attacker, "is_enemy", False):
            return
        killer_name = attacker.name
        if getattr(attacker, "is_memosprite", False) and getattr(attacker, "master_name", None):
            killer_name = attacker.master_name
        vm_rt = getattr(self.simulator, "vm_runtime", None)
        vm_handles_kill_sp = bool(
            vm_rt is not None
            and vm_rt.modifier_engine.has_modifier(killer_name, "Local_SPAdd")
        )
        if not vm_handles_kill_sp and hasattr(self.simulator, "port") and hasattr(self.simulator.port, "gain_hit_energy"):
            self.simulator.port.gain_hit_energy(
                killer_name,
                10.0,
                cause=f"击败【{target.name}】击杀回能 (基础 10.0, 受 ERR 放大)",
            )
        emit_sim_event(
            self.simulator,
            EnemyDefeatedEvent(
                av=round(av, 2),
                cycle=cycle,
                attacker_name=killer_name,
                target_name=target.name,
            ),
        )
        scheduler = getattr(self.simulator, "scheduler", None)
        if scheduler is not None:
            scheduler.commit_reserved_wave()

    def _propagate_hp_shared_group(
        self,
        target: Any,
        loss: float,
        attacker: Any,
        av: float,
        cycle: int,
    ) -> None:
        """同步子目标扣血至 DefineHPSharedGroup 主目标（如冥龙双臂分摊扣减本体 HP）。"""
        if loss <= 0.0:
            return
        vm_rt = getattr(self.simulator, "vm_runtime", None)
        shared_map = getattr(vm_rt, "hp_shared_groups", None) if vm_rt is not None else None
        if not shared_map or target.name not in shared_map:
            return
        main_id = shared_map[target.name]
        main_ent = self.simulator.get_entity(main_id)
        if main_ent is None or main_ent is target or main_ent.current_hp <= 0.0:
            return
        shared_loss = float(loss)
        main_kit = getattr(main_ent, "kit", None)
        if main_kit is not None and hasattr(main_kit, "intercept_incoming_damage"):
            shared_loss = main_kit.intercept_incoming_damage(main_id, shared_loss)
        was_alive = float(getattr(main_ent, "current_hp", 0.0)) > 0.0
        old_hp = float(main_ent.current_hp)
        main_ent.current_hp = max(0.0, old_hp - shared_loss)
        actual_shared = old_hp - main_ent.current_hp
        if actual_shared > 0.0:
            emit_sim_event(
                self.simulator,
                HPLostEvent(
                    av=round(av, 2),
                    cycle=cycle,
                    entity_name=main_id,
                    amount=actual_shared,
                    hp_left=main_ent.current_hp,
                    cause="hp_shared_group",
                ),
            )
        sync_hp_shared_subtargets(self.simulator, main_ent)
        if was_alive and main_ent.current_hp <= 0.0 and not getattr(main_ent, "is_infinite_hp", False):
            self._handle_enemy_defeated(attacker, main_ent, av, cycle)

    def _resolve_one(self, effect: EffectRequest):
        av = self.simulator.current_av
        cycle = self.simulator.current_cycle

        if isinstance(effect, AdvanceActionEffect):
            before = effect.target.distance_remaining
            if self.simulator.current_turn_entity == effect.target and effect.percent >= 1.0:
                effect.target.extra_immediate_action = True
            effect.target.advance_action(effect.percent)
            after = effect.target.distance_remaining
            if after <= 0.0 and self.simulator.current_turn_entity != effect.target:
                if hasattr(self.simulator, "notify_entity_ready"):
                    self.simulator.notify_entity_ready(effect.target.name)
            emit_sim_event(self.simulator, ActionAdvanceEvent(
                av=round(av, 2),
                cycle=cycle,
                source_name=effect.source_name,
                target_name=effect.target.name,
                percent=effect.percent,
                distance_before=before,
                distance_after=after
            ))

        elif isinstance(effect, DelayActionEffect):
            before = effect.target.distance_remaining
            effect.target.delay_action(effect.percent)
            after = effect.target.distance_remaining
            if after > 1e-6:
                rq = getattr(self.simulator, "_ready_queue", None)
                if isinstance(rq, list) and effect.target.name in rq:
                    rq.remove(effect.target.name)
                nd = getattr(self.simulator, "_natural_due_names", None)
                if isinstance(nd, set):
                    nd.discard(effect.target.name)
            emit_sim_event(self.simulator, ActionDelayEvent(
                av=round(av, 2),
                cycle=cycle,
                source_name=effect.source_name,
                target_name=effect.target.name,
                percent=effect.percent,
                distance_before=before,
                distance_after=after
            ))

        elif isinstance(effect, ModifySPEffect):
            if effect.delta > 0:
                self.simulator.sp.generate(effect.delta, effect.actor_name, effect.reason, av)
            elif effect.delta < 0:
                need = abs(effect.delta)
                vm_rt = getattr(self.simulator, "vm_runtime", None)
                if vm_rt is not None and effect.actor_name in vm_rt.entity_boost_points:
                    avail_extra = int(vm_rt.entity_boost_points.get(effect.actor_name, 0.0))
                    used_extra = min(need, max(0, avail_extra))
                    if used_extra > 0:
                        vm_rt.entity_boost_points[effect.actor_name] = float(max(0, avail_extra - used_extra))
                        need -= used_extra
                if need > 0:
                    self.simulator.sp.consume(need, effect.actor_name, effect.reason, av)
            diag_cb = getattr(self.simulator, "timeline_diag_cb", None)
            if callable(diag_cb):
                vm_rt = getattr(self.simulator, "vm_runtime", None)
                extra_bp = int(vm_rt.entity_boost_points.get(effect.actor_name, 0.0)) if vm_rt is not None else 0
                diag_cb(
                    "SP",
                    f"{effect.actor_name} delta={effect.delta:+d} "
                    f"team_sp={self.simulator.sp.current_sp}/{self.simulator.sp.max_sp} "
                    f"extra_bp={extra_bp} cause={effect.reason}",
                )
            emit_sim_event(self.simulator, SPChangeEvent(
                av=round(av, 2),
                cycle=cycle,
                actor_name=effect.actor_name,
                delta=effect.delta,
                current_sp=self.simulator.sp.current_sp,
                max_sp=self.simulator.sp.max_sp,
                reason=effect.reason
            ))

        elif isinstance(effect, InterruptActionEffect):
            if effect.sp_change != 0:
                self.enqueue(ModifySPEffect(
                    actor_name=effect.actor.name,
                    delta=effect.sp_change,
                    reason="终结技效果"
                ))
            emit_sim_event(self.simulator, ActionExecuteEvent(
                av=round(av, 2),
                cycle=cycle,
                actor_id=effect.actor.name,
                actor_name=effect.actor.name,
                action_type="Ultimate",
                description=effect.description
            ))

        elif isinstance(effect, ApplyStatusEffect):
            st = effect.status
            self.simulator.status_mgr.add_status(st)
            # 派生同步类状态 (带 SUPPRESS_STATUS_APPLY_EVENT 标签) 不广播应用事件，防事件自循环
            from .status import StatusTag
            if StatusTag.SUPPRESS_STATUS_APPLY_EVENT not in (getattr(st, "tags", None) or ()):
                emit_sim_event(self.simulator, StatusApplyEvent(
                    av=round(av, 2),
                    cycle=cycle,
                    source_name=st.source.name,
                    target_name=st.target.name,
                    status_id=st.id,
                    status_name=st.name,
                    duration=st.duration
                ))

        elif isinstance(effect, ReduceToughnessEffect):
            target = effect.target
            if (
                hasattr(target, "max_toughness")
                and target.max_toughness > 0
                and not getattr(target, "is_broken", False)
                and not getattr(target, "toughness_locked", False)
            ):
                weaknesses = getattr(target, "weaknesses", [])
                if effect.ignore_weakness or (effect.element in weaknesses):
                    cut = min(target.current_toughness, effect.amount)
                    overflow = max(0.0, float(effect.amount) - float(cut))
                    target.current_toughness -= cut
                    emit_sim_event(self.simulator, ToughnessReduceEvent(
                        av=round(av, 2),
                        cycle=cycle,
                        attacker_name=effect.attacker.name,
                        target_name=target.name,
                        amount=cut,
                        toughness_left=target.current_toughness,
                        max_toughness=target.max_toughness
                    ))

                    # 检查是否触发弱点击破 (Weakness Break) 或多层韧性扣减 (StanceCountDown)
                    if target.current_toughness <= 0.0:
                        cur_sc = int(getattr(target, "current_stance_count", 1) or 1)
                        is_sub_stance = cur_sc > 1
                        if is_sub_stance:
                            target.current_stance_count = cur_sc - 1
                            target.current_toughness = max(0.0, float(target.max_toughness) - overflow)
                        else:
                            target.current_stance_count = 0
                            target.is_broken = True
                            self.enqueue(DelayActionEffect(
                                source_name="弱点击破",
                                target=target,
                                percent=0.25
                            ))

                        base_break = 3767.5533
                        elem_mult = 1.0  # 雷/冰为 1.0, 物理/火为 2.0
                        if effect.element in ["Physical", "Fire"]:
                            elem_mult = 2.0
                        elif effect.element in ["Wind"]:
                            elem_mult = 1.5
                        elif effect.element in ["Quantum", "Imaginary"]:
                            elem_mult = 0.5

                        from .status import StatType
                        be = getattr(effect.attacker, "base_break_effect", 0.0)
                        if getattr(effect.attacker, "is_memosprite", False) and hasattr(effect.attacker, "master_name"):
                            m_ent = self.simulator.get_entity(effect.attacker.master_name) if hasattr(self, "simulator") else None
                            if m_ent is not None:
                                be = max(be, getattr(m_ent, "base_break_effect", 0.0))
                        sm = getattr(self.simulator, "status_mgr", None)
                        if sm:
                            be = sm.calculate_stat(effect.attacker.name, be, StatType.BREAK_EFFECT)
                            if getattr(effect.attacker, "is_memosprite", False) and hasattr(effect.attacker, "master_name"):
                                be = max(be, sm.calculate_stat(effect.attacker.master_name, be, StatType.BREAK_EFFECT))
                        if effect.break_effect > 0.0:
                            be = max(be, effect.break_effect)

                        tough_mult = 0.5 + (getattr(target, "max_toughness", 0.0) / 120.0)
                        atk_lvl = getattr(effect.attacker, "level", 80)
                        tgt_lvl = getattr(target, "level", 100)
                        def_shred = sm.calculate_stat(target.name, 0.0, StatType.DEF_SHRED) if sm else 0.0
                        def_ignore = sm.calculate_stat(effect.attacker.name, 0.0, StatType.DEF_SHRED) if sm else 0.0
                        base_res = getattr(target, "damage_res", {}).get(effect.element, 0.0) if isinstance(getattr(target, "damage_res", None), dict) else 0.0
                        res_pen = sm.calculate_stat(effect.attacker.name, 0.0, StatType.RES_PEN) if sm else 0.0
                        vuln = sm.calculate_stat(target.name, 0.0, StatType.VULNERABILITY) if sm else 0.0
                        dr = max(0.0, min(1.0, float(getattr(target, "damage_reduction", 0.0))))
                        vm_rt = getattr(self.simulator, "vm_runtime", None)
                        vm_base_multi = 1.0
                        if vm_rt is not None:
                            if effect.attacker.name in vm_rt.entity_specs:
                                dmg_data = vm_rt.collect_hit_modifiers(effect.attacker.name, (target.name,), attack_type="Break")
                                def_ignore += -float(dmg_data.get("Defender_DefenceAddedRatio", 0.0))
                                res_pen += float(dmg_data.get("Attacker_AllDamageTypePenetrate", 0.0))
                                vuln += float(dmg_data.get("Defender_AllDamageTypeTakenRatio", 0.0))
                                vm_base_multi = float(dmg_data.get("Attacker_BaseDamageMultiRatio", 1.0))
                            if getattr(target, "is_enemy", False):
                                me = vm_rt.modifier_engine
                                dr_already_active = getattr(target, "_vm_damage_reduction_active", False)
                                vuln += float(getattr(target, "_vm_last_tgt_vuln", 0.0))
                                def_ignore += float(getattr(target, "_vm_last_tgt_def_ignore", 0.0))
                                res_pen += float(getattr(target, "_vm_last_tgt_res_pen", 0.0))
                                red_mult = 1.0 - dr
                                if not dr_already_active:
                                    def_red = float(getattr(target, "_vm_last_def_red", 0.0))
                                    if def_red > 0.0:
                                        red_mult *= max(0.0, 1.0 - def_red)
                                tgt_res_mod = 0.0
                                for m_def in me.get_modifiers(target.name):
                                    if not dr_already_active:
                                        m_red = float(m_def.properties.get("AllDamageReduce", 0.0))
                                        if m_red > 0.0:
                                            red_mult *= max(0.0, 1.0 - m_red)
                                        tgt_res_mod += float(m_def.properties.get("AllDamageTypeResistance", 0.0))
                                res_pen += -tgt_res_mod
                                dr = max(0.0, min(1.0, 1.0 - red_mult))
                        def_mult = (atk_lvl + 20.0) / ((tgt_lvl + 20.0) * max(0.0, 1.0 - def_shred - def_ignore) + (atk_lvl + 20.0))
                        res_mult = 1.0 - (base_res - res_pen)
                        vuln_mult = 1.0 + vuln

                        break_dmg = base_break * elem_mult * tough_mult * (1.0 + be) * def_mult * res_mult * vuln_mult * 0.9 * (1.0 - dr) * vm_base_multi
                        break_killed = False
                        if hasattr(target, "current_hp"):
                            was_strictly_alive = float(getattr(target, "current_hp", 0.0)) > 0.0
                            shared_map = getattr(vm_rt, "hp_shared_groups", None) if vm_rt is not None else None
                            main_id = shared_map.get(target.name) if shared_map else None
                            main_ent = self.simulator.get_entity(main_id) if main_id else None
                            if main_ent is not None and main_ent is not target and main_ent.current_hp > 0.0:
                                self._propagate_hp_shared_group(target, break_dmg, effect.attacker, av, cycle)
                            else:
                                actual_break_loss = break_dmg
                                kit = getattr(target, "kit", None)
                                if kit is not None and hasattr(kit, "intercept_incoming_damage"):
                                    actual_break_loss = kit.intercept_incoming_damage(target.name, break_dmg)
                                target.current_hp = max(0.0, target.current_hp - actual_break_loss)
                                sync_hp_shared_subtargets(self.simulator, target)
                                break_killed = bool(
                                    was_strictly_alive
                                    and target.current_hp == 0.0
                                    and not getattr(target, "is_infinite_hp", False)
                                )

                        entangle_applied = True
                        if not is_sub_stance and effect.element == "Quantum":
                            ctrl_immune = False
                            if vm_rt is not None:
                                me_q = vm_rt.modifier_engine
                                if me_q.has_behavior_flag(target.name, "Endurance") or me_q.has_behavior_flag(target.name, "EnduranceLogicOnly"):
                                    ctrl_immune = True
                            if not ctrl_immune:
                                debuff_res = getattr(target, "debuff_resist", None)
                                if isinstance(debuff_res, dict) and float(debuff_res.get("STAT_CTRL", 0.0)) >= 1.0 - 1e-6:
                                    ctrl_immune = True
                            if ctrl_immune:
                                entangle_applied = False
                            else:
                                debuff_prov = getattr(self.simulator, "debuff_hit_provider", None)
                                if callable(debuff_prov):
                                    entangle_applied = bool(
                                        debuff_prov(effect.attacker, target, "Quantum_Entanglement", round(float(av), 2))
                                    )
                            if entangle_applied:
                                self.enqueue(DelayActionEffect(
                                    source_name="量子纠缠推条",
                                    target=target,
                                    percent=0.20 * (1.0 + be)
                                ))
                        emit_sim_event(self.simulator, WeaknessBreakEvent(
                            av=round(av, 2),
                            cycle=cycle,
                            breaker_name=effect.attacker.name,
                            target_name=target.name,
                            element=effect.element,
                            break_damage=break_dmg,
                            action_delay_pct=0.0 if is_sub_stance else 0.25,
                            entangle_applied=entangle_applied,
                        ))
                        if break_killed:
                            self._handle_enemy_defeated(effect.attacker, target, av, cycle)
                        scheduler = getattr(self.simulator, "scheduler", None)
                        if scheduler is not None:
                            scheduler.commit_reserved_wave()

        elif isinstance(effect, ApplyDamageEffect):
            scheduler = getattr(self.simulator, "scheduler", None)
            if scheduler is not None:
                # 介入点 1 (before_hit): 命中前先提交攻击开始阶段预约的动作波次
                scheduler.commit_reserved_wave()
            target = effect.request.target
            if getattr(effect.request, "target_is_broken", None) is None:
                effect.request.target_is_broken = getattr(target, "is_broken", False)

            req_attacker = effect.request.attacker
            vm_rt = getattr(self.simulator, "vm_runtime", None)
            if (
                vm_rt is not None
                and req_attacker.name in vm_rt.entity_specs
                and not getattr(effect.request, "vm_hit_hooks_applied", False)
                and not getattr(effect.request, "is_true_damage", False)
            ):
                is_dot = effect.request.damage_type == DamageType.DOT
                atk_type = "Dot" if is_dot else "ElementDamage"
                dmg_data = vm_rt.collect_hit_modifiers(req_attacker.name, (target.name,), attack_type=atk_type)
                if not is_dot:
                    effect.request.extra_dmg_boost += float(dmg_data.get("Attacker_AllDamageTypeAddedRatio", 0.0))
                    effect.request.extra_crit_dmg += float(dmg_data.get("Attacker_CriticalDamageBase", 0.0))
                effect.request.extra_def_ignore += -float(dmg_data.get("Defender_DefenceAddedRatio", 0.0))
                effect.request.extra_res_pen += float(dmg_data.get("Attacker_AllDamageTypePenetrate", 0.0))
                effect.request.extra_vuln += float(dmg_data.get("Defender_AllDamageTypeTakenRatio", 0.0))
                effect.request.vm_hit_hooks_applied = True

            # 1. 伤害纯计算
            breakdown = DamageCalculator.calculate(effect.request)
            raw_dmg = breakdown.final_damage

            resolved_damage_type = getattr(effect, "damage_type", None) or DamageType.from_tag(getattr(effect, "damage_tag", "direct"))
            is_dot_dmg = (resolved_damage_type == DamageType.DOT)
            is_true_dmg = bool(getattr(effect.request, "is_true_damage", False) or resolved_damage_type == DamageType.TRUE)
            vm_blocked = False
            if vm_rt is not None and not is_true_dmg:
                me_blk = vm_rt.modifier_engine
                if me_blk.has_behavior_flag(target.name, "BlockDamage") or (
                    not is_dot_dmg and me_blk.has_behavior_flag(target.name, "BlockDamageExcludeDot")
                ):
                    vm_blocked = True

            shield_absorbed = 0.0
            if vm_blocked:
                raw_dmg = 0.0
                breakdown = replace(breakdown, final_damage=0.0)
                setattr(target, "_vm_hit_blocked", True)
                vm_rt._attack_blocked_targets.add(target.name)
            else:
                # 2. 多态伤害分摊/减免拦截协议钩子 (如符玄穷观阵分摊，零角色名硬编码)
                for ent in list(getattr(self.simulator, "entities", [])):
                    kit = getattr(ent, "kit", None)
                    if kit is not None and hasattr(kit, "intercept_incoming_damage"):
                        raw_dmg = kit.intercept_incoming_damage(target.name, raw_dmg)

                if vm_rt is not None and not is_true_dmg and raw_dmg > 0.0:
                    raw_dmg = vm_rt.modifier_engine.intercept_team_block_damage(target.name, raw_dmg)

                # 3. 护盾优先吸收 (砂金、杰帕德等)
                if hasattr(target, "shield") and target.shield > 0:
                    absorbed = min(target.shield, raw_dmg)
                    shield_absorbed = absorbed
                    target.shield -= absorbed
                    raw_dmg -= absorbed
                    if absorbed > 0 and vm_rt is not None:
                        for m_shd in vm_rt.modifier_engine.get_modifiers(target.name):
                            if m_shd.shield_value > 0.0:
                                m_shd.shield_value = max(0.0, m_shd.shield_value - absorbed)

            vm_atk_type = "DOT" if resolved_damage_type == DamageType.DOT else ""
            was_alive = getattr(target, "current_hp", 0.0) > 0 or getattr(target, "_in_deathrattle_limbo", False)
            was_strictly_alive = getattr(target, "current_hp", 0.0) > 0
            notify_vm_being_hit = bool(
                vm_rt is not None
                and getattr(req_attacker, "is_enemy", False)
                and not getattr(target, "is_enemy", False)
            )
            if notify_vm_being_hit:
                vm_rt.modifier_engine.dispatch_event(
                    "OnBeforeBeingHitAll",
                    owner_id=target.name,
                    param_entity_id=req_attacker.name,
                    current_attack_type=vm_atk_type,
                )
            if hasattr(target, "current_hp"):
                shared_map = getattr(vm_rt, "hp_shared_groups", None) if vm_rt is not None else None
                shared_main_id = shared_map.get(target.name) if shared_map else None
                shared_main_ent = self.simulator.get_entity(shared_main_id) if shared_main_id else None
                if shared_main_ent is not None and shared_main_ent is not target and shared_main_ent.current_hp > 0.0:
                    self._propagate_hp_shared_group(target, raw_dmg, req_attacker, av, cycle)
                    hp_left = float(target.current_hp)
                else:
                    old_hp = float(target.current_hp)
                    neg_enabled = (
                        not getattr(target, "is_enemy", False)
                        and bool(getattr(target, "_negative_hp_enabled", False))
                    )
                    if neg_enabled and old_hp > 0.0 and raw_dmg > 0.0 and old_hp - raw_dmg < min(old_hp, 1.0):
                        floor_hp = min(old_hp, 1.0)
                        target.current_hp = floor_hp
                        actual_loss = max(0.0, old_hp - floor_hp)
                        overflow = max(0.0, raw_dmg - actual_loss)
                        if overflow > 0.0:
                            target._negative_hp = float(getattr(target, "_negative_hp", 0.0) or 0.0) + overflow
                    else:
                        target.current_hp = max(0.0, old_hp - raw_dmg)
                        actual_loss = old_hp - target.current_hp
                    hp_left = target.current_hp
                    if actual_loss > 0:
                        emit_sim_event(self.simulator, HPLostEvent(
                            av=round(av, 2),
                            cycle=cycle,
                            entity_name=target.name,
                            amount=actual_loss,
                            hp_left=hp_left,
                            cause="attack_damage"
                        ))
                        sync_hp_shared_subtargets(self.simulator, target)
                    elif raw_dmg > 0.0 and neg_enabled and vm_rt is not None:
                        vm_rt.modifier_engine.dispatch_event(
                            "OnHPChange",
                            owner_id=target.name,
                            param_entity_id=req_attacker.name,
                            change_value=-float(raw_dmg),
                            current_attack_type=vm_atk_type,
                            param_flags=("IsHPChangeByDamage",),
                        )
                        vm_rt.modifier_engine.dispatch_event(
                            "OnListenHPChange",
                            param_entity_id=target.name,
                            change_value=-float(raw_dmg),
                        )
            else:
                hp_left = 0.0
            if notify_vm_being_hit:
                vm_rt.modifier_engine.dispatch_event(
                    "OnAfterBeingHitAll",
                    owner_id=target.name,
                    param_entity_id=req_attacker.name,
                    current_attack_type=vm_atk_type,
                )
            if vm_rt is not None:
                vm_rt.modifier_engine.dispatch_event(
                    "OnListenAfterBeingHitAll",
                    param_entity_id=target.name,
                    param_entity2_id=req_attacker.name,
                    damage_data={
                        "FinalDamage": float(breakdown.final_damage),
                        "Result_FinalDamageBase": float(breakdown.final_damage),
                    },
                    current_attack_type=vm_atk_type,
                )
                try:
                    vm_rt.modifier_engine.dispatch_event(
                        "OnAfterBeingHit",
                        owner_id=target.name,
                        param_entity_id=req_attacker.name,
                        current_attack_type=vm_atk_type,
                    )
                finally:
                    if vm_blocked:
                        setattr(target, "_vm_hit_blocked", False)

            target_killed = bool(
                was_strictly_alive
                and hp_left == 0.0
                and not getattr(target, "is_infinite_hp", False)
            )
            eff_action_id = getattr(effect, "action_id", 0) or getattr(self.simulator, "current_action_id", 0)
            if hasattr(self.simulator, "effect_counter"):
                self.simulator.effect_counter += 1
            else:
                self.simulator.effect_counter = 1
            eff_id = self.simulator.effect_counter
            emit_sim_event(self.simulator, DamageAppliedEvent(
                av=round(av, 2),
                cycle=cycle,
                attacker_name=breakdown.attacker_name,
                target_name=breakdown.target_name,
                damage=breakdown.final_damage,
                is_crit=breakdown.is_crit,
                breakdown=breakdown,
                target_hp_left=hp_left,
                damage_tag=resolved_damage_type.value,
                damage_type=resolved_damage_type,
                target_killed=target_killed,
                action_id=eff_action_id,
                effect_id=eff_id,
                shield_absorbed=shield_absorbed,
            ))
            if scheduler is not None:
                # 介入点 2 (after_hit): 命中后提交命中触发的动作波次 (如银狼 E2 追加回合、千刃等)
                scheduler.commit_reserved_wave()

            # 4. 敌方直接攻击命中我方角色或忆灵时触发标准受击回能 (忆灵受击回能归其主人, 严格受目标 ERR 放大)
            # 官方规范: 单动作多段攻击 (同一 action_seq 内多段 Hit) 仅算 1 次受击回能; 多动 (不同 action_seq) 各自算 1 次受击回能
            if (
                getattr(effect.request.attacker, "is_enemy", False)
                and not getattr(target, "is_enemy", False)
                and not getattr(target, "is_countdown", False)
                and resolved_damage_type == DamageType.DIRECT
            ):
                action_seq = getattr(self.simulator, "_action_seq", 0)
                energy_recipient = getattr(target, "master_name", None) if getattr(target, "is_memosprite", False) else target.name
                hit_key = (action_seq, target.name)
                if energy_recipient and (action_seq == 0 or hit_key not in self._hit_energy_action_recipients):
                    if action_seq > 0:
                        self._hit_energy_action_recipients.add(hit_key)
                    hit_base = getattr(effect.request.attacker, "hit_energy", 0.0) or getattr(effect.request, "hit_energy", 0.0) or 5.0
                    if hasattr(self.simulator, "port") and hasattr(self.simulator.port, "gain_hit_energy"):
                        self.simulator.port.gain_hit_energy(energy_recipient, hit_base)

            # 4.5 击杀回能与击败事件: 击败敌方目标时, 击杀者恢复 10 点能量 (受 ERR 放大); 忆灵击杀归其主人
            if target_killed:
                self._handle_enemy_defeated(effect.request.attacker, target, av, cycle)

            # 5. 如果携带削韧属性，入队削韧请求
            if effect.toughness_reduction > 0:
                self.enqueue(ReduceToughnessEffect(
                    attacker=effect.request.attacker,
                    target=target,
                    amount=effect.toughness_reduction,
                    element=effect.element,
                    break_effect=effect.break_effect,
                    ignore_weakness=effect.ignore_weakness
                ))

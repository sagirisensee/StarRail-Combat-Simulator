# coding: utf-8
"""统一战斗执行生命周期与结算栅栏 (Unified Execution Lifecycle & Settlement Barrier)。

将原本散落在 `VMRuntime` / `CombatOpsMixin` / `StageOpsMixin` / `TurnOpsMixin` 中的
16 个隐式状态标志、延后队列与亡语悬停态 (Limbo / Deathrattle) 收编至单一显式状态机，
确保无论是自然回合、追加回合、敌方回合、嵌套攻击帧还是非嵌套攻击，均经过同一条
8 阶段 `SettlementBarrier`（`settle_attack_boundary`）完成确定性收口。

微内核边界铁律：本模块严禁出现任何具体角色名、怪物模板 ID 或关卡硬编码。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from .events import (
    ActionEndEvent,
    ActionExecuteEvent,
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    HealAppliedEvent,
    HPLostEvent,
    SPChangeEvent,
    SpiritDespawnEvent,
    TurnBeginEvent,
    TurnEndEvent,
    WeaknessBreakEvent,
)
from .status import StatType


class ExecutionPhase(str, Enum):
    """当前执行生命周期所处的显式阶段。"""

    IDLE = "idle"
    TURN_PHASE1_END = "turn_phase1_end"
    ATTACK_SCOPE = "attack_scope"
    AFTER_ATTACK = "after_attack"
    AFTER_ATTACK_END = "after_attack_end"
    DYING_BATCH = "dying_batch"
    FLUSH_LISTEN_DIE = "flush_listen_die"


@dataclass(frozen=True)
class AfterAttackPayload:
    """挂起的攻击后收口载荷，用于在攻击帧最外层边界统一派发 AfterAttack 系列钩子。"""

    atk_seq: int
    caster_id: str
    dmg_data: Dict[str, Any]
    atk_type: str
    skill_type: str
    fallback_targets: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AbilityFrameSpec:
    """统一能力/技能执行帧规范（覆盖我方技能、忆灵技、敌方技能、追击、欢愉技与关卡事件）。"""

    caster_id: str
    ability_name: str
    target_ids: Tuple[str, ...] = ()
    skill_target_ids: Tuple[str, ...] = ()
    skill_type: str = ""
    attack_type: str = ""
    skill_name: Optional[str] = None
    sp_base: Optional[float] = None
    energy_cause: str = ""
    local_dynamics: Optional[Dict[int, float]] = None
    custom_strings: Optional[Dict[str, str]] = None
    emit_ultra_prepare: bool = False
    emit_insert_start: bool = False
    emit_before_skill: bool = False
    emit_listen_before_skill: bool = False
    pass_skill_targets_to_before_hooks: bool = False
    before_skill_targets_as_attack: bool = False
    end_being_attacked_on_exit: bool = False
    emit_after_skill: bool = False
    emit_action_end_hooks: bool = False
    emit_insert_finish: bool = False
    emit_settle_callback: bool = False


@dataclass(frozen=True)
class DamageHitSnapshot:
    """同步采集的受击目标快照，避免忆灵退场后延迟读取失效。"""

    target_name: str
    is_enemy: bool
    is_countdown: bool
    is_memosprite: bool
    master_name: Optional[str] = None


class InterventionHook:
    """微内核调度外部干预契约，替代散落在 TurnSimulator 上的动态猴子补丁属性。"""

    def on_sub_action_end(
        self,
        actor: Any,
        *,
        sub_action_index: int,
        has_next_sub_action: bool,
    ) -> None:
        pass

    def on_pre_turn_end(self, actor: Any) -> None:
        pass

    def on_turn_action_completed(self, actor: Any) -> None:
        pass

    def on_auto_chained_skill(self, actor_name: str, skill_id: int) -> None:
        pass

    def decide_insert_action(
        self,
        actor_name: str,
    ) -> Optional[Tuple[Optional[Any], Optional[Tuple[str, ...]]]]:
        return None


class CallbackInterventionHook(InterventionHook):
    """基于可选回调函数的轻量 InterventionHook 实现。"""

    def __init__(
        self,
        *,
        on_sub_action_end: Optional[Callable[..., None]] = None,
        on_pre_turn_end: Optional[Callable[[Any], None]] = None,
        on_turn_action_completed: Optional[Callable[[Any], None]] = None,
        on_auto_chained_skill: Optional[Callable[[str, int], None]] = None,
        decide_insert_action: Optional[
            Callable[[str], Optional[Tuple[Optional[Any], Optional[Tuple[str, ...]]]]]
        ] = None,
    ) -> None:
        self._on_sub_action_end = on_sub_action_end
        self._on_pre_turn_end = on_pre_turn_end
        self._on_turn_action_completed = on_turn_action_completed
        self._on_auto_chained_skill = on_auto_chained_skill
        self._decide_insert_action = decide_insert_action

    @property
    def has_pre_turn_end(self) -> bool:
        return self._on_pre_turn_end is not None

    @property
    def has_turn_action_completed(self) -> bool:
        return self._on_turn_action_completed is not None

    def on_sub_action_end(
        self,
        actor: Any,
        *,
        sub_action_index: int,
        has_next_sub_action: bool,
    ) -> None:
        if self._on_sub_action_end is not None:
            self._on_sub_action_end(
                actor,
                sub_action_index=sub_action_index,
                has_next_sub_action=has_next_sub_action,
            )

    def on_pre_turn_end(self, actor: Any) -> None:
        if self._on_pre_turn_end is not None:
            self._on_pre_turn_end(actor)

    def on_turn_action_completed(self, actor: Any) -> None:
        if self._on_turn_action_completed is not None:
            self._on_turn_action_completed(actor)

    def on_auto_chained_skill(self, actor_name: str, skill_id: int) -> None:
        if self._on_auto_chained_skill is not None:
            self._on_auto_chained_skill(actor_name, skill_id)

    def decide_insert_action(
        self,
        actor_name: str,
    ) -> Optional[Tuple[Optional[Any], Optional[Tuple[str, ...]]]]:
        if self._decide_insert_action is not None:
            return self._decide_insert_action(actor_name)
        return None


def is_entity_alive_or_limbo(ent: Any) -> bool:
    """判断实体是否仍处于存活、无限生命或亡语悬停态 (`_in_deathrattle_limbo`)。"""
    return bool(
        ent is not None
        and (
            float(getattr(ent, "current_hp", 0.0)) > 0.0
            or bool(getattr(ent, "is_infinite_hp", False))
            or bool(getattr(ent, "_in_deathrattle_limbo", False))
        )
    )


def enter_deathrattle_limbo(ent: Any) -> None:
    """将实体置入亡语悬停态，等待其临终反噬/亡语插队动作完成再正式退场。"""
    if ent is not None:
        setattr(ent, "_in_deathrattle_limbo", True)


def clear_deathrattle_limbo(ent: Any, *, clear_deferred_die: bool = True) -> Tuple[bool, bool]:
    """清理实体的亡语悬停态及计数标志，返回 `(was_limbo, was_deferred_die)`。"""
    if ent is None:
        return False, False
    was_limbo = bool(getattr(ent, "_in_deathrattle_limbo", False))
    was_deferred_die = bool(getattr(ent, "_deferred_listen_die", False))
    if was_limbo:
        setattr(ent, "_in_deathrattle_limbo", False)
    if clear_deferred_die and was_deferred_die:
        setattr(ent, "_deferred_listen_die", False)
    setattr(ent, "_die_immediately_after_deathrattle", False)
    setattr(ent, "_pending_deathrattle_actions", 0)
    return was_limbo, was_deferred_die


def increment_deathrattle_actions(ent: Any) -> int:
    """递增实体待完成的异步亡语插队动作计数。"""
    if ent is None:
        return 0
    cnt = int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) + 1
    setattr(ent, "_pending_deathrattle_actions", cnt)
    return cnt


def decrement_deathrattle_actions(ent: Any) -> int:
    """递减实体待完成的异步亡语插队动作计数（钳位至 >= 0）。"""
    if ent is None:
        return 0
    cnt = max(0, int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) - 1)
    setattr(ent, "_pending_deathrattle_actions", cnt)
    return cnt


class ExecutionLifecycle:
    """管理攻击作用域、延后死亡/亡语队列与 8 阶段统一结算栅栏的单一真值状态机。"""

    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.attack_scope_depth: int = 0
        self.in_turn_phase1_end: bool = False
        self.in_after_attack: bool = False
        self.in_after_attack_end: bool = False
        self.in_dying_batch: bool = False
        self.flushing_listen_die: bool = False

        self.pending_after_attack: Optional[AfterAttackPayload] = None
        self.after_attack_fired: Set[Tuple[int, str]] = set()
        self.attack_targets_by_key: Dict[Tuple[int, str], List[str]] = {}
        self.attack_blocked_targets: Set[str] = set()
        self.open_enemy_attack: Optional[str] = None

        self.pending_dying_enemies: List[Tuple[str, str]] = []
        self.pending_limbo_after_dying: List[Tuple[str, Optional[str]]] = []
        self.pending_level_kills: List[Tuple[str, str]] = []
        self.pending_dead_enemies: List[str] = []
        self.pending_listen_die: List[str] = []
        self.active_deathrattle_entities: Set[str] = set()
        self._damage_hit_recorders: List[Tuple[str, List[DamageHitSnapshot]]] = []

    @property
    def in_attack_scope(self) -> bool:
        return self.attack_scope_depth > 0

    @property
    def current_phase(self) -> ExecutionPhase:
        if self.flushing_listen_die:
            return ExecutionPhase.FLUSH_LISTEN_DIE
        if self.in_dying_batch:
            return ExecutionPhase.DYING_BATCH
        if self.in_after_attack_end:
            return ExecutionPhase.AFTER_ATTACK_END
        if self.in_after_attack:
            return ExecutionPhase.AFTER_ATTACK
        if self.attack_scope_depth > 0:
            return ExecutionPhase.ATTACK_SCOPE
        if self.in_turn_phase1_end:
            return ExecutionPhase.TURN_PHASE1_END
        return ExecutionPhase.IDLE

    def _dirty_reasons(self) -> List[str]:
        reasons: List[str] = []
        if self.attack_scope_depth != 0:
            reasons.append(f"attack_scope_depth={self.attack_scope_depth}")
        if self.in_turn_phase1_end:
            reasons.append("in_turn_phase1_end=True")
        if self.in_after_attack:
            reasons.append("in_after_attack=True")
        if self.in_after_attack_end:
            reasons.append("in_after_attack_end=True")
        if self.in_dying_batch:
            reasons.append("in_dying_batch=True")
        if self.flushing_listen_die:
            reasons.append("flushing_listen_die=True")
        if self.pending_after_attack is not None:
            reasons.append(f"pending_after_attack={self.pending_after_attack.caster_id}")
        if self.open_enemy_attack is not None:
            reasons.append(f"open_enemy_attack={self.open_enemy_attack}")
        if self.attack_blocked_targets:
            reasons.append(f"attack_blocked_targets={sorted(self.attack_blocked_targets)}")
        if self.pending_dying_enemies:
            reasons.append(f"pending_dying_enemies={self.pending_dying_enemies}")
        if self.pending_limbo_after_dying:
            reasons.append(f"pending_limbo_after_dying={self.pending_limbo_after_dying}")
        if self.pending_level_kills:
            reasons.append(f"pending_level_kills={self.pending_level_kills}")
        if self.pending_dead_enemies:
            reasons.append(f"pending_dead_enemies={self.pending_dead_enemies}")
        if self.pending_listen_die:
            reasons.append(f"pending_listen_die={self.pending_listen_die}")
        if self.active_deathrattle_entities:
            reasons.append(f"active_deathrattle_entities={sorted(self.active_deathrattle_entities)}")
        if self._damage_hit_recorders:
            reasons.append(f"damage_hit_recorders={len(self._damage_hit_recorders)}")
        return reasons

    @property
    def is_clean(self) -> bool:
        return not self._dirty_reasons()

    def assert_clean(self) -> None:
        """断言当前生命周期无悬空标志或未排空队列；否则抛出诊断信息清晰的 AssertionError。"""
        dirty = self._dirty_reasons()
        if dirty:
            raise AssertionError(f"ExecutionLifecycle 状态未清理干净: {', '.join(dirty)}")

    def begin_attack_scope(self) -> None:
        self.attack_scope_depth += 1

    def end_attack_scope(self) -> None:
        self.attack_scope_depth = max(0, self.attack_scope_depth - 1)
        if self.attack_scope_depth == 0:
            self.settle_attack_boundary()

    @contextmanager
    def attack_scope(self) -> Iterator[None]:
        """异常安全的攻击作用域上下文管理器；退出最外层时自动触发 8 阶段结算栅栏。"""
        self.begin_attack_scope()
        try:
            yield
        finally:
            self.end_attack_scope()

    @contextmanager
    def turn_phase1_end_scope(self) -> Iterator[None]:
        """异常安全的 TurnPhase1End 作用域上下文管理器（兼容嵌套重入）。"""
        prev = self.in_turn_phase1_end
        self.in_turn_phase1_end = True
        try:
            yield
        finally:
            self.in_turn_phase1_end = prev

    def schedule_after_attack(
        self,
        atk_seq: int,
        caster_id: str,
        dmg_data: Dict[str, Any],
        atk_type: str,
        skill_type: str,
        *,
        fallback_targets: Tuple[str, ...] = (),
    ) -> None:
        """登记本次主攻击的 AfterAttack 收口载荷；若已在顶层则立即走同一套 8 阶段结算栅栏。"""
        self.pending_after_attack = AfterAttackPayload(
            atk_seq=atk_seq,
            caster_id=caster_id,
            dmg_data=dmg_data,
            atk_type=atk_type,
            skill_type=skill_type,
            fallback_targets=fallback_targets,
        )
        if not self.in_attack_scope:
            self.settle_attack_boundary()

    def enqueue_pending_dead(self, dead_tid: str) -> None:
        if dead_tid and dead_tid not in self.pending_dead_enemies:
            self.pending_dead_enemies.append(dead_tid)

    def discard_pending_dead(self, dead_tid: str) -> None:
        if dead_tid in self.pending_dead_enemies:
            self.pending_dead_enemies[:] = [x for x in self.pending_dead_enemies if x != dead_tid]

    def enqueue_level_kill(self, dead_tid: str, killer_id: str) -> None:
        if dead_tid and all(item[0] != dead_tid for item in self.pending_level_kills):
            self.pending_level_kills.append((dead_tid, killer_id))

    def enqueue_or_process_dying(
        self,
        dead_tid: str,
        killer_id: str,
        *,
        defer_in_after_attack: bool = True,
    ) -> bool:
        """若处于攻击帧（或允许延后的 AfterAttack 帧），将濒死实体入队延后；否则立即执行单实体亡语管线。"""
        should_defer = self.in_attack_scope or (defer_in_after_attack and self.in_after_attack)
        if should_defer:
            if not any(x[0] == dead_tid for x in self.pending_dying_enemies):
                self.pending_dying_enemies.append((dead_tid, killer_id))
            return True
        self.process_single_dying_entity(dead_tid, killer_id)
        return False

    def process_single_dying_entity(self, dead_tid: str, killer_id: str) -> None:
        """执行单个濒死实体的标准亡语收口管线（OnBeforeDying -> OnBeingLimbo -> strip -> OnDeathrattle -> inline finalize）。"""
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        dead_ent = sim.get_entity(dead_tid)
        if dead_ent is not None:
            rt.record_entity_team(dead_ent)
        me.dispatch_event("OnBeforeDying", owner_id=dead_tid, param_entity_id=killer_id)
        me.dispatch_event("OnBeingLimbo", owner_id=dead_tid, param_entity_id=killer_id)
        dead_ent = sim.get_entity(dead_tid)
        if dead_ent is not None and getattr(dead_ent, "_in_deathrattle_limbo", False):
            me.strip_for_deathrattle(dead_tid)
        self.active_deathrattle_entities.add(dead_tid)
        try:
            me.dispatch_event("OnDeathrattle", owner_id=dead_tid, param_entity_id=killer_id)
        finally:
            self.active_deathrattle_entities.discard(dead_tid)
        self.finalize_inline_deathrattle(dead_tid)

    def trigger_or_defer_limbo(self, owner_id: str, param_entity_id: Optional[str]) -> bool:
        """若当前处于攻击作用域或死亡批处理中，将转阶段回血延后至结算完成后触发，防止附加/真伤或自伤误扣新阶段 HP。"""
        if self.in_dying_batch or self.in_attack_scope:
            if not any(tid == owner_id for tid, _ in self.pending_limbo_after_dying):
                self.pending_limbo_after_dying.append((owner_id, param_entity_id))
            return True
        return False

    def defer_or_dispatch_listen_die(
        self,
        dead_id: str,
        *,
        defer_in_after_attack: bool = True,
    ) -> None:
        """统一调度 `OnListenCharacterDie`：若处于受保护帧内则入队延后，否则检查亡语悬停态后派发。"""
        if defer_in_after_attack:
            should_defer = (self.in_attack_scope or self.in_after_attack) and not self.flushing_listen_die
        else:
            should_defer = self.in_attack_scope and not self.in_after_attack and not self.flushing_listen_die

        if should_defer:
            if dead_id and dead_id not in self.pending_listen_die:
                self.pending_listen_die.append(dead_id)
            return

        dead_ent = self.rt.sim.get_entity(dead_id) if dead_id else None
        if dead_ent is not None and getattr(dead_ent, "_in_deathrattle_limbo", False):
            setattr(dead_ent, "_deferred_listen_die", True)
        else:
            self.rt.modifier_engine.dispatch_event("OnListenCharacterDie", param_entity_id=dead_id)

    def drain_dying_batch(self) -> None:
        """排空当前一批延后濒死实体 (`OnBeforeDying` / `OnBeingLimbo` / `OnDeathrattle`)。"""
        if not self.pending_dying_enemies:
            return
        dying_batch = list(self.pending_dying_enemies)
        self.pending_dying_enemies.clear()
        prev_in_dying = self.in_dying_batch
        self.in_dying_batch = True
        try:
            for dead_tid, killer_id in dying_batch:
                self.process_single_dying_entity(dead_tid, killer_id)
        finally:
            self.in_dying_batch = prev_in_dying

    def flush_listen_die(self) -> None:
        """排空延后登记的 `OnListenCharacterDie` 监听回调。"""
        if not self.pending_listen_die:
            return
        self.flushing_listen_die = True
        try:
            while self.pending_listen_die:
                listen_batch = list(self.pending_listen_die)
                self.pending_listen_die.clear()
                for dead_id in listen_batch:
                    dead_ent = self.rt.sim.get_entity(dead_id)
                    if dead_ent is not None and getattr(dead_ent, "_in_deathrattle_limbo", False):
                        setattr(dead_ent, "_deferred_listen_die", True)
                        continue
                    self.rt.modifier_engine.dispatch_event("OnListenCharacterDie", param_entity_id=dead_id)
        finally:
            self.flushing_listen_die = False

    def settle_attack_boundary(self) -> None:
        """统一 8 阶段攻击后结算栅栏 (Settlement Barrier)。

        严格顺序：
        1. `OnAfterAttack` -> `OnListenAfterAttack` -> 逐目标 `OnAfterBeingAttacked`
        2. 排空本波濒死队列 (`drain_dying_batch`)
        3. 排空 `OnListenCharacterDie` (`flush_listen_die`)
        4. 派发延后的 Boss 转阶段 `OnLimboWaitHeal`
        5. 结算 `__LEVEL__` 延后击杀 (`OnBeforeDying` -> `EnemyDefeatedEvent` -> 清理)
        6. 逐目标 `OnAfterBeingAttackedEnd` -> `OnListenAfterAttackEnd` 并二次排空新产生的濒死/监听死亡
        7. 清空本轮免疫/挡伤目标集合 (`attack_blocked_targets`)
        8. 对已离开 `_in_deathrattle_limbo` 的阵亡敌方执行 `finalize_dead_enemy`
        """
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine
        after_end_payload: Optional[Tuple[Tuple[str, ...], str, Dict[str, Any], str]] = None

        # Stage 1
        if self.pending_after_attack is not None:
            payload = self.pending_after_attack
            self.pending_after_attack = None
            after_key = (payload.atk_seq, payload.caster_id)
            if after_key in self.attack_targets_by_key:
                all_targets = tuple(self.attack_targets_by_key[after_key])
            else:
                all_targets = tuple(payload.fallback_targets)
            if after_key not in self.after_attack_fired:
                self.after_attack_fired.add(after_key)
                if self.open_enemy_attack == payload.caster_id:
                    self.open_enemy_attack = None
                after_end_payload = (all_targets, payload.caster_id, payload.dmg_data, payload.atk_type)
                self.in_after_attack = True
                try:
                    me.dispatch_event(
                        "OnAfterAttack",
                        owner_id=payload.caster_id,
                        attack_target_ids=all_targets,
                        damage_data=payload.dmg_data,
                        current_skill_type=payload.skill_type,
                        current_attack_type=payload.atk_type,
                    )
                    me.dispatch_event(
                        "OnListenAfterAttack",
                        param_entity_id=payload.caster_id,
                        attack_target_ids=all_targets,
                        damage_data=payload.dmg_data,
                        current_skill_type=payload.skill_type,
                        current_attack_type=payload.atk_type,
                    )
                    for tid in all_targets:
                        me.dispatch_event(
                            "OnAfterBeingAttacked",
                            owner_id=tid,
                            param_entity_id=payload.caster_id,
                            damage_data=payload.dmg_data,
                            current_attack_type=payload.atk_type,
                        )
                finally:
                    self.in_after_attack = False

        # Stage 2
        self.drain_dying_batch()

        # Stage 3
        self.flush_listen_die()

        # Stage 4
        if not self.in_dying_batch and self.pending_limbo_after_dying:
            limbo_batch = list(self.pending_limbo_after_dying)
            self.pending_limbo_after_dying.clear()
            for limbo_tid, limbo_killer in limbo_batch:
                ent = sim.get_entity(limbo_tid)
                kit = getattr(ent, "kit", None) if ent is not None else None
                runner = getattr(kit, "runner", None) if kit is not None else None
                if runner is not None:
                    try:
                        mrs = runner.get_enemy_state(limbo_tid)
                        setattr(mrs, "_limbo_pending", False)
                    except KeyError:
                        pass
                me.dispatch_event(
                    "OnLimboWaitHeal",
                    owner_id=limbo_tid,
                    param_entity_id=limbo_killer,
                )

        # Stage 5
        while self.pending_level_kills:
            lvl_batch = list(self.pending_level_kills)
            self.pending_level_kills.clear()
            for dead_tid, eff_killer in lvl_batch:
                ent = sim.get_entity(dead_tid)
                if ent is None:
                    continue
                me.dispatch_event("OnBeforeDying", owner_id=dead_tid, param_entity_id=eff_killer)
                emit_sim_event(
                    sim,
                    EnemyDefeatedEvent(
                        av=float(sim.current_av),
                        cycle=int(sim.current_cycle),
                        attacker_name=eff_killer,
                        target_name=dead_tid,
                    ),
                )
                me.destroy_all_for_entity(dead_tid)
                sim.entities[:] = [e for e in sim.entities if e.name != dead_tid]

        # Stage 6
        if after_end_payload is not None:
            end_targets, end_caster, end_dmg_data, end_atk_type = after_end_payload
            self.in_after_attack = True
            self.in_after_attack_end = True
            try:
                for tid in end_targets:
                    me.dispatch_event(
                        "OnAfterBeingAttackedEnd",
                        owner_id=tid,
                        param_entity_id=end_caster,
                        damage_data=end_dmg_data,
                        current_attack_type=end_atk_type,
                    )
                me.dispatch_event(
                    "OnListenAfterAttackEnd",
                    param_entity_id=end_caster,
                    attack_target_ids=end_targets,
                    damage_data=end_dmg_data,
                    current_attack_type=end_atk_type,
                )
            finally:
                self.in_after_attack_end = False
                self.in_after_attack = False
            self.drain_dying_batch()
            self.flush_listen_die()

        # Stage 7
        if self.attack_blocked_targets:
            self.attack_blocked_targets.clear()

        # Stage 8
        if self.pending_dead_enemies:
            remaining_dead: List[str] = []
            for dead_tid in list(self.pending_dead_enemies):
                dead_ent = sim.get_entity(dead_tid)
                if dead_ent is not None and getattr(dead_ent, "_in_deathrattle_limbo", False):
                    remaining_dead.append(dead_tid)
                else:
                    self.finalize_dead_enemy(dead_tid)
            self.pending_dead_enemies[:] = remaining_dead

    def finalize_inline_deathrattle(self, entity_id: str) -> None:
        """若实体无异步亡语插入动作且 HP<=0，则立即结束亡语悬停态并销毁 Modifier。"""
        sim = self.rt.sim
        ent = sim.get_entity(entity_id)
        if (
            ent is not None
            and getattr(ent, "_in_deathrattle_limbo", False)
            and int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) == 0
            and float(getattr(ent, "current_hp", 0.0)) <= 0.0
        ):
            _, was_deferred_die = clear_deathrattle_limbo(ent)
            ent.current_hp = 0.0
            if getattr(ent, "is_memosprite", False) and hasattr(sim, "port"):
                sim.port.despawn_spirit(entity_id, reason="death")
            self.rt.modifier_engine.destroy_all_for_entity(entity_id)
            if was_deferred_die:
                self.rt.modifier_engine.dispatch_event("OnListenCharacterDie", param_entity_id=entity_id)

    def complete_deathrattle_action(self, entity_id: str, *, force_limbo_prio: bool = False) -> None:
        """在异步亡语插队动作完成时递减计数，并在归零且标记即死时正式完成退场清理。"""
        sim = self.rt.sim
        dr_ent = sim.get_entity(entity_id)
        if dr_ent is None:
            return
        if not (
            force_limbo_prio
            or (
                getattr(dr_ent, "_in_deathrattle_limbo", False)
                and int(getattr(dr_ent, "_pending_deathrattle_actions", 0) or 0) > 0
            )
        ):
            return
        rem_dr = decrement_deathrattle_actions(dr_ent)
        if rem_dr == 0 and getattr(dr_ent, "_die_immediately_after_deathrattle", False):
            setattr(dr_ent, "_die_immediately_after_deathrattle", False)
            if getattr(dr_ent, "_in_deathrattle_limbo", False):
                _, was_deferred_die = clear_deathrattle_limbo(dr_ent)
                dr_ent.current_hp = 0.0
                self.rt.modifier_engine.destroy_all_for_entity(entity_id)
                self.discard_pending_dead(entity_id)
                if was_deferred_die:
                    self.rt.modifier_engine.dispatch_event("OnListenCharacterDie", param_entity_id=entity_id)

    def finalize_dead_enemy(self, dead_tid: str) -> None:
        """完成阵亡敌方收尾并级联清理共享血量（HPSharedGroup）子目标。"""
        sim = self.rt.sim
        me = self.rt.modifier_engine
        dead_ent = sim.get_entity(dead_tid)
        if dead_ent is not None and float(getattr(dead_ent, "current_hp", 0.0)) > 0.0:
            return
        me.destroy_all_for_entity(dead_tid)
        shared_map = getattr(self.rt, "hp_shared_groups", None)
        if not shared_map:
            return
        director = getattr(sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        for sub_tid, mid in list(shared_map.items()):
            if mid != dead_tid:
                continue
            shared_map.pop(sub_tid, None)
            sub_ent = sim.get_entity(sub_tid)
            if sub_ent is not None:
                if runner is not None:
                    try:
                        mrs = runner.get_enemy_state(sub_tid)
                        mrs.lock_hp_ratio = None
                    except KeyError:
                        pass
                sub_ent.current_hp = 0.0
                me.destroy_all_for_entity(sub_tid)

    def begin_being_attacked(self, attacker_name: str, target_ids: Sequence[str]) -> None:
        """标记敌方攻击受击窗口开始并派发 `OnBeforeBeingAttacked`。"""
        if self.open_enemy_attack is not None:
            self.end_being_attacked(self.open_enemy_attack)
        self.open_enemy_attack = attacker_name
        for tid in target_ids:
            self.rt.modifier_engine.dispatch_event(
                "OnBeforeBeingAttacked",
                owner_id=tid,
                param_entity_id=attacker_name,
            )

    def end_being_attacked(self, attacker_name: Optional[str] = None) -> None:
        """结束当前敌方受击窗口并派发 `OnListenAfterAttack`。"""
        atk = attacker_name or self.open_enemy_attack
        if atk is None:
            return
        if self.open_enemy_attack == atk or attacker_name is None:
            self.open_enemy_attack = None
        self.rt.modifier_engine.dispatch_event("OnListenAfterAttack", param_entity_id=atk)

    @contextmanager
    def capture_damage_targets(self, attacker_id: str) -> Iterator[List[DamageHitSnapshot]]:
        """在作用域内按内核伤害事实同步收集指定攻击者命中的受击目标快照。"""
        recorded: List[DamageHitSnapshot] = []
        entry = (attacker_id, recorded)
        self._damage_hit_recorders.append(entry)
        try:
            yield recorded
        finally:
            try:
                self._damage_hit_recorders.remove(entry)
            except ValueError:
                pass

    def record_damage_applied(self, event: DamageAppliedEvent) -> None:
        """在 DamageAppliedEvent 发生瞬间采集目标快照，避免后续退场导致状态丢失。"""
        if not self._damage_hit_recorders:
            return
        atk = getattr(event, "attacker_name", None)
        tnm = str(getattr(event, "target_name", "") or "")
        sim = getattr(self.rt, "sim", None)
        if not tnm or sim is None:
            return
        tent = sim.get_entity(tnm)
        if tent is None:
            return
        snap = DamageHitSnapshot(
            target_name=tnm,
            is_enemy=bool(getattr(tent, "is_enemy", False)),
            is_countdown=bool(getattr(tent, "is_countdown", False)),
            is_memosprite=bool(getattr(tent, "is_memosprite", False)),
            master_name=getattr(tent, "master_name", None),
        )
        for rec_atk, snaps in self._damage_hit_recorders:
            if atk == rec_atk and all(s.target_name != tnm for s in snaps):
                snaps.append(snap)

    def run_ability_frame(self, spec: AbilityFrameSpec) -> None:
        """统一执行任意 ConfigAbility 帧：前置钩子 -> 攻击作用域 -> 技能基础回能 -> 后置收口钩子。"""
        rt = self.rt
        sim = rt.sim
        me = rt.modifier_engine

        prev_sk_name = getattr(rt, "_current_skill_name", "")
        prev_sp_base = getattr(rt, "_active_skill_sp_base", 0.0)
        prev_sp_granted = getattr(rt, "_skill_sp_ratio_granted", False)
        if spec.skill_name is not None:
            rt._current_skill_name = spec.skill_name
        if spec.sp_base is not None:
            rt._active_skill_sp_base = float(spec.sp_base)
            rt._skill_sp_ratio_granted = False

        sp_granted = False
        try:
            if spec.emit_ultra_prepare:
                me.dispatch_event("OnListenUltraSkillPrepare", param_entity_id=spec.caster_id)
            if spec.emit_insert_start:
                me.dispatch_event("OnListenInsertAbilityStart", param_entity_id=spec.caster_id)
            if spec.emit_before_skill:
                if spec.before_skill_targets_as_attack:
                    me.dispatch_event(
                        "OnBeforeSkillUse",
                        owner_id=spec.caster_id,
                        param_entity_id=spec.caster_id,
                        attack_target_ids=spec.target_ids,
                    )
                else:
                    before_kwargs: Dict[str, Any] = {
                        "owner_id": spec.caster_id,
                        "current_skill_type": spec.skill_type,
                    }
                    if spec.pass_skill_targets_to_before_hooks:
                        before_kwargs["skill_target_ids"] = spec.skill_target_ids
                        before_kwargs["param_skill_targets"] = spec.skill_target_ids
                    me.dispatch_event("OnBeforeSkillUse", **before_kwargs)
            if spec.emit_listen_before_skill:
                listen_before_kwargs: Dict[str, Any] = {
                    "param_entity_id": spec.caster_id,
                    "current_skill_type": spec.skill_type,
                }
                if spec.pass_skill_targets_to_before_hooks:
                    listen_before_kwargs["skill_target_ids"] = spec.skill_target_ids
                    listen_before_kwargs["param_skill_targets"] = spec.skill_target_ids
                me.dispatch_event("OnListenBeforeSkillUse", **listen_before_kwargs)

            try:
                with self.attack_scope():
                    if spec.ability_name:
                        rt.trigger_ability(
                            caster_id=spec.caster_id,
                            ability_name=spec.ability_name,
                            target_ids=spec.target_ids,
                            skill_target_ids=spec.skill_target_ids or spec.target_ids,
                            current_skill_type=spec.skill_type,
                            current_attack_type=spec.attack_type or spec.skill_type,
                            local_dynamics=spec.local_dynamics,
                            custom_strings=spec.custom_strings,
                        )
            finally:
                if spec.end_being_attacked_on_exit:
                    self.end_being_attacked()
        finally:
            if spec.sp_base is not None:
                sp_granted = bool(getattr(rt, "_skill_sp_ratio_granted", False))
                rt._active_skill_sp_base = prev_sp_base
                rt._skill_sp_ratio_granted = prev_sp_granted
            if spec.skill_name is not None:
                rt._current_skill_name = prev_sk_name

        if (
            spec.sp_base is not None
            and spec.sp_base > 0.0
            and not sp_granted
            and getattr(sim, "port", None) is not None
            and spec.caster_id
            and spec.caster_id != "__LEVEL__"
        ):
            ep_recipient: Optional[str] = spec.caster_id
            ent = sim.get_entity(spec.caster_id)
            if ent is not None and getattr(ent, "is_memosprite", False):
                ep_recipient = getattr(ent, "master_name", None)
            if ep_recipient:
                err = sim.port.stat(ep_recipient, StatType.ERR) or 1.0
                sim.port.gain_energy(
                    ep_recipient,
                    float(spec.sp_base) * err,
                    cause=spec.energy_cause or f"技能回能 {spec.skill_name or spec.ability_name}",
                )

        if spec.emit_after_skill:
            if spec.before_skill_targets_as_attack:
                me.dispatch_event(
                    "OnAfterSkillUse",
                    owner_id=spec.caster_id,
                    param_entity_id=spec.caster_id,
                    attack_target_ids=spec.target_ids,
                )
                me.dispatch_event(
                    "OnListenAfterSkillUse",
                    param_entity_id=spec.caster_id,
                    attack_target_ids=spec.target_ids,
                )
            else:
                me.dispatch_event(
                    "OnAfterSkillUse",
                    owner_id=spec.caster_id,
                    current_skill_type=spec.skill_type,
                )
                if spec.emit_action_end_hooks:
                    me.dispatch_event("OnActionEnd", owner_id=spec.caster_id)
                me.dispatch_event(
                    "OnListenAfterSkillUse",
                    param_entity_id=spec.caster_id,
                    current_skill_type=spec.skill_type,
                )
                if spec.emit_action_end_hooks:
                    me.dispatch_event("OnListenActionEnd", param_entity_id=spec.caster_id)
                    me.dispatch_event("OnAfterAction", owner_id=spec.caster_id)
                    me.dispatch_event("OnListenAfterAction", param_entity_id=spec.caster_id)

        if spec.emit_insert_finish:
            me.dispatch_event("OnListenInsertAbilityFinish", param_entity_id=spec.caster_id)
            me.dispatch_event("OnListenInsertActionFinish", param_entity_id=spec.caster_id)

        if spec.emit_settle_callback:
            me.dispatch_event(
                "CheckParamFlagCallBack",
                param_entity_id=spec.caster_id,
                param_flags=("CallBack_SettleSkillOrInsertAbility",),
            )


def dispatch_combat_fact(sim: Any, event: Any) -> None:
    """微内核确定性事实路由：按固定顺序显式驱动 VMRuntime / TaskExecutor 与 StageDirector。"""
    if sim is None or event is None:
        return
    vm_rt = getattr(sim, "vm_runtime", None)
    director = getattr(sim, "_stage_director", None)

    if isinstance(event, TurnBeginEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_turn_begin"):
            vm_rt.on_turn_begin(event)
        if director is not None and hasattr(director, "on_turn_begin"):
            director.on_turn_begin(event)
    elif isinstance(event, TurnEndEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_turn_end"):
            vm_rt.on_turn_end(event)
    elif isinstance(event, ActionExecuteEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_action_execute"):
            vm_rt.on_action_execute(event)
    elif isinstance(event, ActionEndEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_action_end"):
            vm_rt.on_action_end(event)
    elif isinstance(event, HPLostEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_hp_lost"):
            vm_rt.on_hp_lost(event)
    elif isinstance(event, HealAppliedEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_heal_applied"):
            vm_rt.on_heal_applied(event)
    elif isinstance(event, SPChangeEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_sp_change"):
            vm_rt.on_sp_change(event)
    elif isinstance(event, SpiritDespawnEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_spirit_despawn"):
            vm_rt.on_spirit_despawn(event)
    elif isinstance(event, EnemyDefeatedEvent):
        if vm_rt is not None and hasattr(vm_rt, "on_enemy_defeated"):
            vm_rt.on_enemy_defeated(event)
    elif isinstance(event, DamageAppliedEvent):
        if vm_rt is not None and getattr(vm_rt, "lifecycle", None) is not None:
            vm_rt.lifecycle.record_damage_applied(event)
        executor = getattr(vm_rt, "executor", None) if vm_rt is not None else None
        if executor is not None and hasattr(executor, "on_damage_applied"):
            executor.on_damage_applied(event)
    elif isinstance(event, WeaknessBreakEvent):
        executor = getattr(vm_rt, "executor", None) if vm_rt is not None else None
        if executor is not None and hasattr(executor, "on_weakness_break"):
            executor.on_weakness_break(event)


def emit_sim_event(sim: Any, event: Any) -> None:
    """统一发送战斗事实事件：优先走 `sim.emit_event`，否则执行确定性路由后广播至只读 EventBus。"""
    if sim is None:
        return
    emit_fn = getattr(sim, "emit_event", None)
    if callable(emit_fn):
        emit_fn(event)
        return
    dispatch_combat_fact(sim, event)
    bus = getattr(sim, "event_bus", None)
    if bus is not None:
        bus.publish(event)

# coding: utf-8
"""微内核统一执行生命周期与结算栅栏不变量测试 (`ExecutionLifecycle` / `drain_window` / 覆盖审计)。"""

from pathlib import Path
from typing import Any, List, Tuple
import unittest

from simulator.actions import (
    AbilityDefinition,
    ActionKind,
    ActionScheduleCategory,
    ResourceCost,
    TargetMode,
)
from simulator.core import TurnSimulator
from simulator.entity import Entity
from simulator.events import (
    ActionEndEvent,
    ActionExecuteEvent,
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    PrimaryDamageCompleteEvent,
    TurnBeginEvent,
    TurnEndEvent,
)
from simulator.lifecycle import (
    AbilityFrameSpec,
    CallbackInterventionHook,
    ExecutionPhase,
    enter_deathrattle_limbo,
    increment_deathrattle_actions,
)
from simulator.protocols import KitHandler
from simulator.vm.audit_vm_coverage import VMCoverageAuditor, extract_executor_supported_types
from simulator.vm.enemy_port import (
    BaseEnemyCombatPortImpl,
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    EnemySubActionOutcome,
    STANDARD_ACTION_DISTANCE,
)
from simulator.vm.executor import TaskExecutor
from simulator.vm.runtime import VMRuntime
from simulator.vm.stage_sim_adapter import DataDrivenStageDirector, build_data_driven_stage


def _build_synthetic_vm_env() -> Tuple[TurnSimulator, VMRuntime, Entity, Entity, Entity]:
    ally = Entity(
        name="测试角色",
        base_speed=110.0,
        base_atk=1200.0,
        max_hp=4000.0,
        current_hp=4000.0,
        max_energy=100.0,
        energy=0.0,
    )
    enemy_a = Entity(
        name="目标A",
        base_speed=100.0,
        base_atk=500.0,
        max_hp=5000.0,
        current_hp=0.0,
        is_enemy=True,
    )
    enemy_b = Entity(
        name="目标B",
        base_speed=95.0,
        base_atk=500.0,
        max_hp=5000.0,
        current_hp=5000.0,
        is_enemy=True,
    )
    lvl_enemy = Entity(
        name="机关小怪",
        base_speed=90.0,
        base_atk=500.0,
        max_hp=1000.0,
        current_hp=0.0,
        is_enemy=True,
    )
    sim = TurnSimulator(
        entities=[ally, enemy_a, enemy_b, lvl_enemy],
        use_techniques=False,
        auto_ult=True,
    )
    rt = VMRuntime(sim)
    sim.vm_runtime = rt
    return sim, rt, ally, enemy_a, lvl_enemy


class TestKernelLifecycle(unittest.TestCase):
    def test_attack_scope_canonical_8_stage_settlement_order(self) -> None:
        """嵌套 attack_scope 内全部死亡/转阶段/AfterAttack 延后至最外层退出时按 8 阶段严格顺序收口并归零。"""
        sim, rt, _, _, _ = _build_synthetic_vm_env()
        events: List[Tuple[str, str, str, ExecutionPhase]] = []

        orig_dispatch = rt.modifier_engine.dispatch_event

        def _spy_dispatch(event_name: str, **kwargs: Any) -> Any:
            events.append(
                (
                    event_name,
                    str(kwargs.get("owner_id") or ""),
                    str(kwargs.get("param_entity_id") or ""),
                    rt.lifecycle.current_phase,
                )
            )
            return orig_dispatch(event_name, **kwargs)

        rt.modifier_engine.dispatch_event = _spy_dispatch  # type: ignore[method-assign]
        sim.event_bus.subscribe(
            EnemyDefeatedEvent,
            lambda evt: events.append(
                ("EnemyDefeatedEvent", str(evt.attacker_name), str(evt.target_name), rt.lifecycle.current_phase)
            ),
        )

        with rt.lifecycle.attack_scope():
            self.assertEqual(rt.lifecycle.current_phase, ExecutionPhase.ATTACK_SCOPE)
            with rt.lifecycle.attack_scope():
                rt.lifecycle.attack_targets_by_key[(1, "测试角色")] = ["目标A"]
                rt.lifecycle.schedule_after_attack(
                    1,
                    "测试角色",
                    {"FinalDamage": 100.0},
                    "Normal",
                    "Normal",
                )
                self.assertTrue(rt.lifecycle.enqueue_or_process_dying("目标A", "测试角色"))
                rt.lifecycle.enqueue_pending_dead("目标A")
                rt.lifecycle.defer_or_dispatch_listen_die("目标A")
                self.assertTrue(rt.lifecycle.trigger_or_defer_limbo("目标B", "测试角色"))
                rt.lifecycle.enqueue_level_kill("机关小怪", "测试角色")
            # 退出内层 scope 时绝不可提前触发结算栅栏
            self.assertEqual(events, [])
            self.assertEqual(rt.lifecycle.attack_scope_depth, 1)

        # 退出最外层 scope 后按 8 阶段严格顺序触发，且生命周期回到 CLEAN
        rt.lifecycle.assert_clean()
        self.assertEqual(rt.lifecycle.current_phase, ExecutionPhase.IDLE)
        self.assertIsNone(sim.get_entity("机关小怪"))

        names = [(e[0], e[1] or e[2]) for e in events]
        expected_prefix = [
            ("OnAfterAttack", "测试角色"),
            ("OnListenAfterAttack", "测试角色"),
            ("OnAfterBeingAttacked", "目标A"),
            ("OnBeforeDying", "目标A"),
            ("OnBeingLimbo", "目标A"),
            ("OnDeathrattle", "目标A"),
            ("OnListenCharacterDie", "目标A"),
            ("OnLimboWaitHeal", "目标B"),
            ("OnBeforeDying", "机关小怪"),
            ("OnTriggerDeath", "测试角色"),
            ("OnListenCharacterDie", "机关小怪"),
            ("EnemyDefeatedEvent", "测试角色"),
            ("OnAfterBeingAttackedEnd", "目标A"),
            ("OnListenAfterAttackEnd", "测试角色"),
        ]
        self.assertEqual(names, expected_prefix)

        # 验证 Stage 1 与 Stage 6 的显式阶段状态
        self.assertEqual(events[0][3], ExecutionPhase.AFTER_ATTACK)
        self.assertEqual(events[3][3], ExecutionPhase.DYING_BATCH)
        self.assertEqual(events[6][3], ExecutionPhase.FLUSH_LISTEN_DIE)
        self.assertEqual(events[12][3], ExecutionPhase.AFTER_ATTACK_END)

    def test_non_nested_after_attack_uses_unified_settlement_pipeline(self) -> None:
        """非嵌套攻击 (scope_depth == 0) 也经由同一 8 阶段结算栅栏，确保阶段顺序完全一致。"""
        sim, rt, _, _, _ = _build_synthetic_vm_env()
        dispatched: List[Tuple[str, ExecutionPhase]] = []
        orig_dispatch = rt.modifier_engine.dispatch_event

        def _spy(event_name: str, **kwargs: Any) -> Any:
            dispatched.append((event_name, rt.lifecycle.current_phase))
            return orig_dispatch(event_name, **kwargs)

        rt.modifier_engine.dispatch_event = _spy  # type: ignore[method-assign]
        rt.lifecycle.attack_targets_by_key[(2, "测试角色")] = ["目标A"]
        rt.lifecycle.pending_dying_enemies.append(("目标A", "测试角色"))
        rt.lifecycle.pending_listen_die.append("目标A")
        rt.lifecycle.schedule_after_attack(
            2,
            "测试角色",
            {"FinalDamage": 50.0},
            "Skill",
            "BPSkill",
        )

        rt.lifecycle.assert_clean()
        self.assertEqual(
            [name for name, _ in dispatched],
            [
                "OnAfterAttack",
                "OnListenAfterAttack",
                "OnAfterBeingAttacked",
                "OnBeforeDying",
                "OnBeingLimbo",
                "OnDeathrattle",
                "OnListenCharacterDie",
                "OnAfterBeingAttackedEnd",
                "OnListenAfterAttackEnd",
            ],
        )

    def test_deathrattle_limbo_defers_listen_die_until_actions_complete(self) -> None:
        """亡语悬停态期间挂起 OnListenCharacterDie，待全部异步亡语动作完成后再统一释放并清理。"""
        sim, rt, _, enemy_a, _ = _build_synthetic_vm_env()
        listen_die_targets: List[str] = []
        orig_dispatch = rt.modifier_engine.dispatch_event

        def _spy(event_name: str, **kwargs: Any) -> Any:
            if event_name == "OnListenCharacterDie":
                listen_die_targets.append(str(kwargs.get("param_entity_id") or ""))
            return orig_dispatch(event_name, **kwargs)

        rt.modifier_engine.dispatch_event = _spy  # type: ignore[method-assign]

        enter_deathrattle_limbo(enemy_a)
        setattr(enemy_a, "_die_immediately_after_deathrattle", True)
        increment_deathrattle_actions(enemy_a)
        increment_deathrattle_actions(enemy_a)
        rt.lifecycle.enqueue_pending_dead(enemy_a.name)

        rt.lifecycle.defer_or_dispatch_listen_die(enemy_a.name)
        self.assertEqual(listen_die_targets, [])
        self.assertTrue(getattr(enemy_a, "_deferred_listen_die", False))

        # 第 1 个亡语动作完成：仍剩 1 个，绝不可提前退场
        rt.lifecycle.complete_deathrattle_action(enemy_a.name)
        self.assertTrue(getattr(enemy_a, "_in_deathrattle_limbo", False))
        self.assertEqual(listen_die_targets, [])

        # 第 2 个亡语动作完成：计数归零 -> 解除悬停、清理 pending_dead 并补发 OnListenCharacterDie
        rt.lifecycle.complete_deathrattle_action(enemy_a.name)
        self.assertFalse(getattr(enemy_a, "_in_deathrattle_limbo", False))
        self.assertFalse(getattr(enemy_a, "_deferred_listen_die", False))
        self.assertEqual(listen_die_targets, ["目标A"])
        rt.lifecycle.assert_clean()

    def test_inline_deathrattle_finalizes_immediately_when_no_async_actions(self) -> None:
        """无异步亡语动作的悬停实体在 finalize_inline_deathrattle 后立即退出悬停并补发死亡监听。"""
        _, rt, _, enemy_a, _ = _build_synthetic_vm_env()
        listen_die_targets: List[str] = []
        orig_dispatch = rt.modifier_engine.dispatch_event

        def _spy(event_name: str, **kwargs: Any) -> Any:
            if event_name == "OnListenCharacterDie":
                listen_die_targets.append(str(kwargs.get("param_entity_id") or ""))
            return orig_dispatch(event_name, **kwargs)

        rt.modifier_engine.dispatch_event = _spy  # type: ignore[method-assign]

        enter_deathrattle_limbo(enemy_a)
        setattr(enemy_a, "_deferred_listen_die", True)
        rt.lifecycle.finalize_inline_deathrattle(enemy_a.name)

        self.assertFalse(getattr(enemy_a, "_in_deathrattle_limbo", False))
        self.assertEqual(listen_die_targets, ["目标A"])
        rt.lifecycle.assert_clean()

    def test_scheduler_drain_window_and_boundary_restore_depth_on_exception(self) -> None:
        """drain_window 与 drain_at_boundary 能在原子帧内排空且在异常时严格恢复帧深度与 auto_ult。"""
        sim, _, _, _, _ = _build_synthetic_vm_env()
        fired: List[str] = []
        sim.scheduler.enqueue(
            "测试角色",
            lambda: fired.append("ok"),
            category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
            publish_execute_event=False,
        )

        with sim.scheduler.action_frame():
            self.assertEqual(sim.scheduler._action_frame_depth, 1)
            cnt = sim.scheduler.drain_at_boundary(auto_ult=False)
            self.assertEqual(cnt, 1)
            self.assertEqual(fired, ["ok"])
            self.assertEqual(sim.scheduler._action_frame_depth, 1)
            self.assertTrue(sim.auto_ult)

            with self.assertRaises(RuntimeError):
                with sim.scheduler.drain_window(auto_ult=False):
                    self.assertEqual(sim.scheduler._action_frame_depth, 0)
                    self.assertFalse(sim.auto_ult)
                    raise RuntimeError("boom")

            self.assertEqual(sim.scheduler._action_frame_depth, 1)
            self.assertTrue(sim.auto_ult)

        self.assertEqual(sim.scheduler._action_frame_depth, 0)

    def test_scope_cleanup_on_exception_never_leaks_flags(self) -> None:
        """attack_scope 与 turn_phase1_end_scope 在异常退出时绝不泄漏深度或布尔状态标志。"""
        _, rt, _, _, _ = _build_synthetic_vm_env()

        with self.assertRaises(RuntimeError):
            with rt.lifecycle.attack_scope():
                with rt.lifecycle.turn_phase1_end_scope():
                    self.assertEqual(rt.lifecycle.attack_scope_depth, 1)
                    self.assertTrue(rt.lifecycle.in_turn_phase1_end)
                    raise RuntimeError("boom")

        self.assertEqual(rt.lifecycle.attack_scope_depth, 0)
        self.assertFalse(rt.lifecycle.in_turn_phase1_end)
        self.assertEqual(rt.lifecycle.current_phase, ExecutionPhase.IDLE)
        rt.lifecycle.assert_clean()

    def test_coverage_auditor_extracts_task_dispatch_keys(self) -> None:
        """静态覆盖率审计器能准确提取 TaskExecutor._TASK_DISPATCH 分发表中的全部 Task 与 Predicate。"""
        exec_path = Path(__file__).resolve().parent / "vm" / "executor.py"
        tasks, preds = extract_executor_supported_types(exec_path)
        self.assertGreaterEqual(len(tasks), 100)
        self.assertGreaterEqual(len(preds), 90)
        auditor = VMCoverageAuditor(executor_path=exec_path)
        self.assertGreaterEqual(len(auditor.supported_tasks), 100)
        self.assertGreaterEqual(len(auditor.supported_predicates), 100)
        for required_task in (
            "RPG.GameCore.PredicateTaskList",
            "RPG.GameCore.DamageByAttackProperty",
            "RPG.GameCore.TurnInsertAction",
            "ELLFLJKDCAE",
        ):
            self.assertIn(required_task, tasks)

    def test_event_bus_has_zero_vm_or_stage_combat_subscribers(self) -> None:
        """EventBus 已降格为纯只读广播：VMRuntime / TaskExecutor / StageDirector 零订阅。"""
        ally = Entity(
            name="TestTrailblazer",
            base_speed=140.0,
            base_atk=2000.0,
            max_hp=5000.0,
            current_hp=5000.0,
            base_def=1000.0,
            level=80,
            is_enemy=False,
        )
        sim, _director = build_data_driven_stage(30126122, [ally], auto_ult=False)
        for handlers in sim.event_bus._subscribers.values():
            for cb in handlers:
                bound_self = getattr(cb, "__self__", None)
                self.assertNotIsInstance(
                    bound_self,
                    (VMRuntime, TaskExecutor, DataDrivenStageDirector),
                )

    def test_kernel_fact_routing_order_independent_of_observer_subscription_order(self) -> None:
        """先挂载只读 EventBus 订阅再创建 VMRuntime，内核事实仍严格先于外部只读订阅者执行。"""
        ally = Entity(name="测试角色", base_speed=110.0, base_atk=1200.0, max_hp=4000.0, current_hp=4000.0)
        enemy = Entity(name="目标A", base_speed=90.0, base_atk=500.0, max_hp=5000.0, current_hp=5000.0, is_enemy=True)
        sim = TurnSimulator(entities=[ally, enemy], use_techniques=False, auto_ult=False)

        trace: List[str] = []
        sim.event_bus.subscribe(TurnBeginEvent, lambda e: trace.append("obs:TurnBegin"))
        sim.event_bus.subscribe(EnemyDefeatedEvent, lambda e: trace.append("obs:EnemyDefeated"))

        rt = VMRuntime(sim)
        orig_tb = rt.on_turn_begin
        orig_ed = rt.on_enemy_defeated

        def _wrap_tb(evt: TurnBeginEvent) -> None:
            trace.append("vm:TurnBegin")
            orig_tb(evt)

        def _wrap_ed(evt: EnemyDefeatedEvent) -> None:
            trace.append("vm:EnemyDefeated")
            orig_ed(evt)

        rt.on_turn_begin = _wrap_tb  # type: ignore[method-assign]
        rt.on_enemy_defeated = _wrap_ed  # type: ignore[method-assign]

        sim.emit_event(TurnBeginEvent(av=0.0, cycle=0, actor_id=ally.name, actor_name=ally.name, speed=110.0, turn_id=1))
        sim.emit_event(EnemyDefeatedEvent(av=0.0, cycle=0, attacker_name=ally.name, target_name=enemy.name))

        self.assertEqual(
            trace,
            ["vm:TurnBegin", "obs:TurnBegin", "vm:EnemyDefeated", "obs:EnemyDefeated"],
        )

    def test_unified_ability_frame_pre_scope_energy_and_post_hook_order(self) -> None:
        """run_ability_frame 严格执行 前置钩子 -> attack_scope -> 回能 -> 后置钩子，并恢复 skill_name。"""
        sim, rt, ally, _, _ = _build_synthetic_vm_env()
        dispatched: List[str] = []
        orig_dispatch = rt.modifier_engine.dispatch_event

        def _spy(event_name: str, **kwargs: Any) -> Any:
            dispatched.append(event_name)
            return orig_dispatch(event_name, **kwargs)

        rt.modifier_engine.dispatch_event = _spy  # type: ignore[method-assign]
        rt._current_skill_name = "PrevSkill"
        energy_before = ally.energy

        rt.lifecycle.run_ability_frame(
            AbilityFrameSpec(
                caster_id=ally.name,
                ability_name="",
                target_ids=("目标A",),
                skill_target_ids=("目标A",),
                skill_type="Elation",
                attack_type="ElationDamage",
                skill_name="ActiveSkill",
                sp_base=20.0,
                energy_cause="测试回能",
                emit_insert_start=True,
                emit_before_skill=True,
                emit_listen_before_skill=True,
                pass_skill_targets_to_before_hooks=True,
                emit_after_skill=True,
                emit_action_end_hooks=True,
                emit_insert_finish=True,
                emit_settle_callback=True,
            )
        )

        self.assertEqual(
            dispatched,
            [
                "OnListenInsertAbilityStart",
                "OnBeforeSkillUse",
                "OnListenBeforeSkillUse",
                "OnAfterSkillUse",
                "OnActionEnd",
                "OnListenAfterSkillUse",
                "OnListenActionEnd",
                "OnAfterAction",
                "OnListenAfterAction",
                "OnListenInsertAbilityFinish",
                "OnListenInsertActionFinish",
                "CheckParamFlagCallBack",
            ],
        )
        self.assertAlmostEqual(ally.energy - energy_before, 20.0)
        self.assertEqual(rt._current_skill_name, "PrevSkill")
        rt.lifecycle.assert_clean()

    def test_char_action_frame_and_one_more_chain_cleanup(self) -> None:
        """主动作与 UseSkillOneMore 连动共用 _run_kit_action_frame，完整广播事实事件并释放连动锁。"""
        ally = Entity(
            name="连动角色",
            base_speed=130.0,
            base_atk=1200.0,
            max_hp=4000.0,
            current_hp=4000.0,
            policy="E",
        )
        enemy = Entity(
            name="木桩",
            base_speed=90.0,
            base_atk=500.0,
            max_hp=5000.0,
            current_hp=5000.0,
            is_enemy=True,
        )
        sim = TurnSimulator(entities=[ally, enemy], use_techniques=False, auto_ult=False)
        rt = VMRuntime(sim)
        executed: List[ActionKind] = []

        class _OneMoreChainKit(KitHandler):
            def definition(self, kind: ActionKind) -> AbilityDefinition:
                if kind == ActionKind.SKILL:
                    return AbilityDefinition(
                        kind=kind,
                        name="测试连动战技",
                        target_mode=TargetMode.SINGLE_ENEMY,
                        cost=ResourceCost(sp=1),
                    )
                return AbilityDefinition(
                    kind=kind,
                    name="测试普攻",
                    target_mode=TargetMode.SINGLE_ENEMY,
                    cost=ResourceCost(sp=-1),
                )

            def execute(self, ctx: Any) -> None:
                executed.append(ctx.kind)
                if ctx.kind == ActionKind.SKILL and len(executed) == 1:
                    sim.scheduler.continuous_action_hold = True
                    rt._pending_use_skill_one_more.setdefault(self.owner_id, []).append("ControlSkill01")

        ally.kit = _OneMoreChainKit(ally.name, sim.port)
        seen_events: List[str] = []
        sim.event_bus.subscribe(ActionExecuteEvent, lambda e: seen_events.append(f"exec:{e.action_kind.name}"))
        sim.event_bus.subscribe(PrimaryDamageCompleteEvent, lambda e: seen_events.append(f"pdc:{e.action_kind.name}"))
        sim.event_bus.subscribe(ActionEndEvent, lambda e: seen_events.append(f"end:{e.action_kind.name}"))

        sim.step()

        self.assertEqual(executed, [ActionKind.SKILL, ActionKind.BASIC])
        self.assertEqual(
            seen_events,
            [
                "exec:SKILL",
                "pdc:SKILL",
                "end:SKILL",
                "exec:BASIC",
                "pdc:BASIC",
                "end:BASIC",
            ],
        )
        self.assertFalse(sim.scheduler.continuous_action_hold)
        rt.lifecycle.assert_clean()

    def test_vm_layer_has_zero_event_bus_subscribe_or_publish(self) -> None:
        """Phase 3 收口：核心 VM 层（simulator/vm 与 simulator/vm/ops 非测试模块）零 EventBus 订阅或发布。"""
        vm_root = Path(__file__).resolve().parent / "vm"
        candidates = list(vm_root.glob("*.py")) + list((vm_root / "ops").glob("*.py"))
        offenders: List[str] = []
        for py_path in sorted(candidates):
            if py_path.name.startswith("test_") or py_path.name.startswith("_test_"):
                continue
            text = py_path.read_text(encoding="utf-8")
            for idx, line in enumerate(text.splitlines(), start=1):
                if "event_bus.subscribe(" in line or ".event_bus.publish(" in line:
                    offenders.append(f"{py_path.relative_to(vm_root)}:{idx}: {line.strip()}")
        self.assertEqual(offenders, [], f"发现残留 VM EventBus 耦合: {offenders}")

    def test_staged_enemy_sub_action_loop_and_intervention_hook_contract(self) -> None:
        """敌方分步子动作循环与 InterventionHook 契约：按确定顺序触发子动作边界、追击与回合钩子。"""
        sim, rt, ally, _enemy_a, _lvl = _build_synthetic_vm_env()
        enemy_b = sim.get_entity("目标B")
        assert enemy_b is not None
        trace: List[str] = []

        orig_dispatch = rt.modifier_engine.dispatch_event

        def _spy_dispatch(event_name: str, **kwargs: Any) -> Any:
            if event_name == "OnListenBeforeTurnPhase1End":
                trace.append("OnListenBeforeTurnPhase1End")
            return orig_dispatch(event_name, **kwargs)

        rt.modifier_engine.dispatch_event = _spy_dispatch  # type: ignore[method-assign]
        sim.event_bus.subscribe(TurnEndEvent, lambda e: trace.append("TurnEnd"))

        class _StagedTestEnemyKit(EnemyKit):
            supports_staged_sub_actions: bool = True

            def begin_turn_session(self, ctx: EnemyActionContext) -> Any:
                return {"ctx": ctx}

            def execute_next_sub_action(
                self,
                session: Any,
                sub_action_index: int,
            ) -> EnemySubActionOutcome | None:
                if sub_action_index == 1:
                    trace.append("sub1")
                    sim.scheduler.enqueue(
                        ally.name,
                        lambda: trace.append("followup"),
                        name="测试追击",
                        category=ActionScheduleCategory.FOLLOW_UP,
                    )
                    return EnemySubActionOutcome(executed=True, has_next_sub_action=True)
                if sub_action_index == 2:
                    trace.append("sub2")
                    return EnemySubActionOutcome(executed=True, has_next_sub_action=False)
                return None

            def finish_turn_session(self, session: Any) -> EnemyActionResult:
                return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

            def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
                raise AssertionError("staged EnemyKit 不应走 legacy execute_turn()")

        def _on_sub_end(actor: Any, *, sub_action_index: int, has_next_sub_action: bool) -> None:
            self.assertEqual(sim.scheduler._action_frame_depth, 0)
            trace.append(f"hook:sub_end({sub_action_index},{has_next_sub_action})")

        enemy_b.kit = _StagedTestEnemyKit(enemy_b.name, BaseEnemyCombatPortImpl(sim))
        sim.intervention_hook = CallbackInterventionHook(
            on_sub_action_end=_on_sub_end,
            on_pre_turn_end=lambda actor: trace.append("hook:pre_turn_end"),
            on_turn_action_completed=lambda actor: trace.append("hook:turn_done"),
        )

        sim.execute_current_turn(actor=enemy_b)

        self.assertEqual(
            trace,
            [
                "sub1",
                "OnListenBeforeTurnPhase1End",
                "hook:sub_end(1,True)",
                "followup",
                "sub2",
                "hook:pre_turn_end",
                "OnListenBeforeTurnPhase1End",
                "TurnEnd",
                "hook:turn_done",
            ],
        )
        rt.lifecycle.assert_clean()

    def test_capture_damage_targets_records_snapshot_and_cleans_up_on_exception(self) -> None:
        """capture_damage_targets 应在伤害瞬间采集快照（早于退场清理）并在异常时自动清理。"""
        sim, rt, ally, _enemy_a, _lvl = _build_synthetic_vm_env()
        snaps: List[Any] = []
        with rt.lifecycle.capture_damage_targets(ally.name) as captured:
            snaps = captured
            sim.emit_event(
                DamageAppliedEvent(
                    av=0.0,
                    cycle=0,
                    attacker_name=ally.name,
                    target_name="目标B",
                    damage=250.0,
                    is_crit=True,
                    breakdown=None,
                    target_hp_left=4750.0,
                )
            )
            # 模拟退场后才退出作用域（类似忆灵瞬间退场）
            sim.entities[:] = [e for e in sim.entities if e.name != "目标B"]

        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0].target_name, "目标B")
        self.assertTrue(snaps[0].is_enemy)
        self.assertFalse(snaps[0].is_memosprite)
        rt.lifecycle.assert_clean()

        with self.assertRaises(RuntimeError):
            with rt.lifecycle.capture_damage_targets(ally.name):
                raise RuntimeError("capture scope aborted")
        rt.lifecycle.assert_clean()

    def test_single_stat_ledger_zero_mirror_statuses_in_vm_mode(self) -> None:
        """VM ModifierEngine 与 StatusManager 收敛为单账本：无镜像状态且实时联动属性与 MaxHP 等比例缩放。"""
        from simulator.status import StatType

        ally = Entity(
            name="单账本测试",
            base_speed=100.0,
            base_atk=1200.0,
            base_white_atk=1000.0,
            max_hp=5000.0,
            current_hp=2500.0,
            base_white_hp=4000.0,
            is_enemy=False,
        )
        enemy = Entity(
            name="单账本木桩",
            base_speed=90.0,
            base_atk=500.0,
            max_hp=100_000.0,
            current_hp=100_000.0,
            is_enemy=True,
        )
        sim = TurnSimulator(entities=[ally, enemy], use_techniques=False, auto_ult=False)
        rt = VMRuntime(sim)
        sim.vm_runtime = rt
        rt.loader._global_mod_by_name["MSynth_StatLedgerBuff"] = {
            "Properties": {
                "HPAddedRatio": {"IsDynamic": False, "FixedValue": {"Value": 0.5}},
                "AttackAddedRatio": {"IsDynamic": False, "FixedValue": {"Value": 0.4}},
            }
        }
        try:
            rt.modifier_engine.add_modifier(
                owner_id=ally.name,
                caster_id=ally.name,
                mod_name="MSynth_StatLedgerBuff",
            )
            self.assertEqual(sim.status_mgr.get_statuses(ally.name), [])
            self.assertAlmostEqual(sim.port.max_hp(ally.name), 7000.0, places=4)
            self.assertAlmostEqual(ally.current_hp, 3500.0, places=4)
            self.assertAlmostEqual(
                sim.status_mgr.calculate_stat(ally.name, 1200.0, StatType.ATK_BASE, white_base=1000.0),
                1600.0,
                places=4,
            )
            snap = sim.status_mgr.get_detailed_snapshot(ally)
            self.assertTrue(any(b["id"].startswith("MSynth_StatLedgerBuff#") for b in snap["all_statuses"]))

            rt.modifier_engine.remove_modifier(ally.name, "MSynth_StatLedgerBuff")
            self.assertEqual(sim.status_mgr.get_statuses(ally.name), [])
            self.assertAlmostEqual(sim.port.max_hp(ally.name), 5000.0, places=4)
            self.assertAlmostEqual(ally.current_hp, 2500.0, places=4)
            self.assertAlmostEqual(
                sim.status_mgr.calculate_stat(ally.name, 1200.0, StatType.ATK_BASE, white_base=1000.0),
                1200.0,
                places=4,
            )
            rt.lifecycle.assert_clean()
        finally:
            rt.loader._global_mod_by_name.pop("MSynth_StatLedgerBuff", None)

    def test_official_vm_break_modifiers_entangle_and_poison_without_break_helper(self) -> None:
        """弱点击破改由官方 MCommon_Element_* 与 ByBreakDamage 纯 VM 结算，不再依赖外挂辅助类。"""
        from simulator.events import WeaknessBreakEvent
        from simulator.vm.executor import ExecutionContext

        ally = Entity(
            name="破韧角色",
            base_speed=120.0,
            base_atk=1500.0,
            base_break_effect=1.0,
            max_hp=5000.0,
            current_hp=5000.0,
            element="Quantum",
            level=80,
            is_enemy=False,
        )
        _sim_st, director = build_data_driven_stage(30126122, [ally])
        self.assertFalse(hasattr(director, "_break_helper"))
        self.assertFalse(hasattr(director, "on_weakness_break"))
        self.assertFalse(hasattr(director, "on_damage_applied"))

        enemy_q = Entity(
            name="量子弱点敌方",
            base_speed=100.0,
            base_atk=800.0,
            base_def=1000.0,
            level=80,
            max_hp=50_000.0,
            current_hp=50_000.0,
            max_toughness=30.0,
            current_toughness=0.0,
            is_broken=True,
            is_enemy=True,
            weaknesses=["Quantum"],
        )
        boss_w = Entity(
            name="风弱点首领",
            base_speed=100.0,
            base_atk=800.0,
            base_def=1000.0,
            level=80,
            max_hp=100_000.0,
            current_hp=100_000.0,
            max_toughness=90.0,
            current_toughness=0.0,
            is_broken=True,
            is_enemy=True,
            is_boss=True,
            weaknesses=["Wind"],
        )
        sim = TurnSimulator(entities=[ally, enemy_q, boss_w], use_techniques=False, auto_ult=False)
        rt = VMRuntime(sim)
        sim.vm_runtime = rt

        sim.emit_event(
            WeaknessBreakEvent(
                av=0.0,
                cycle=0,
                breaker_name=ally.name,
                target_name=enemy_q.name,
                element="Quantum",
                break_damage=0.0,
                action_delay_pct=0.25,
                entangle_applied=True,
            )
        )
        self.assertTrue(rt.modifier_engine.has_modifier(enemy_q.name, "MCommon_Element_Entangle"))
        ent_mods = rt.modifier_engine.get_modifiers(enemy_q.name, "MCommon_Element_Entangle")
        self.assertEqual(ent_mods[0].layer, 1)

        ctx = ExecutionContext(
            runtime=rt,
            caster_id=ally.name,
            ability_name="TestEntangleHit",
            ability_target_ids=(enemy_q.name,),
            skill_target_ids=(enemy_q.name,),
        )
        rt.execute_tasks(
            [
                {
                    "$type": "RPG.GameCore.DamageByAttackProperty",
                    "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AbilityTargetEntity"},
                    "AttackProperty": {
                        "$type": "RPG.GameCore.AttackData",
                        "DamageType": {"DamageType": "Quantum"},
                        "DamagePercentage": {"IsDynamic": False, "FixedValue": {"Value": 1.0}},
                        "AttackType": "Normal",
                    },
                }
            ],
            ctx,
        )
        sim.resolver.resolve_all()
        self.assertEqual(ent_mods[0].layer, 2)

        hp_before_turn = enemy_q.current_hp
        sim.emit_event(
            TurnBeginEvent(
                av=10.0,
                cycle=0,
                actor_id=enemy_q.name,
                actor_name=enemy_q.name,
                speed=enemy_q.speed,
                turn_id=1,
            )
        )
        sim.resolver.resolve_all()
        self.assertLess(enemy_q.current_hp, hp_before_turn)
        self.assertFalse(rt.modifier_engine.has_modifier(enemy_q.name, "MCommon_Element_Entangle"))

        sim.emit_event(
            WeaknessBreakEvent(
                av=10.0,
                cycle=0,
                breaker_name=ally.name,
                target_name=boss_w.name,
                element="Wind",
                break_damage=0.0,
                action_delay_pct=0.25,
            )
        )
        self.assertTrue(rt.modifier_engine.has_modifier(boss_w.name, "MCommon_Element_Poison"))
        poison_mods = rt.modifier_engine.get_modifiers(boss_w.name, "MCommon_Element_Poison")
        self.assertEqual(poison_mods[0].layer, 3)
        self.assertAlmostEqual(float(poison_mods[0].life_time or 0.0), 2.0, places=4)
        rt.lifecycle.assert_clean()

    def test_enemy_fast_action_uses_official_vm_modifier_without_windwalk_flags(self) -> None:
        """敌方立刻再动收敛为官方 MCommon_FastAction 状态，零保留手工风行布尔壳且破韧自动清除。"""
        from simulator.vm.enemy_kit import DataDrivenEnemyKit
        from simulator.vm.enemy_port import EnemyActionContext

        ally = Entity(
            name="快动测试角色",
            base_speed=140.0,
            base_atk=1500.0,
            max_hp=5000.0,
            current_hp=5000.0,
            is_enemy=False,
        )
        sim, _director = build_data_driven_stage(30126122, [ally])
        enemy = next(e for e in sim.entities if e.is_enemy)
        kit = enemy.kit
        self.assertIsInstance(kit, DataDrivenEnemyKit)
        self.assertFalse(any("windwalk" in attr for attr in vars(kit)))
        self.assertFalse(hasattr(kit, "_ensure_windwalk_init"))

        rt = getattr(sim, "vm_runtime", None) or VMRuntime(sim)
        sim.vm_runtime = rt
        rt.modifier_engine.add_modifier(
            owner_id=enemy.name,
            caster_id=enemy.name,
            mod_name="MCommon_FastAction",
        )
        self.assertTrue(rt.modifier_engine.has_modifier(enemy.name, "MCommon_FastAction"))

        session = kit.begin_turn_session(EnemyActionContext(action_id="fast_1", actor_id=enemy.name))
        self.assertIsNotNone(session)
        res = kit.finish_turn_session(session)
        self.assertEqual(res.reset_distance, 0.0)
        self.assertFalse(rt.modifier_engine.has_modifier(enemy.name, "MCommon_FastAction"))

        rt.modifier_engine.add_modifier(
            owner_id=enemy.name,
            caster_id=enemy.name,
            mod_name="MCommon_FastAction",
        )
        rt.modifier_engine.dispatch_event("OnBeingBreak", owner_id=enemy.name, param_entity_id=ally.name)
        self.assertFalse(rt.modifier_engine.has_modifier(enemy.name, "MCommon_FastAction"))
        rt.lifecycle.assert_clean()


if __name__ == "__main__":
    unittest.main()

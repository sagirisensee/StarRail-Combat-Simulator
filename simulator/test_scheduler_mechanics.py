# coding: utf-8
"""调度器核心机制单测：五级优先级、追击四段位循环左移、连续行动锁、追加回合与拉条/推条。"""

import unittest
from typing import List

from simulator.actions import ActionKind, ActionScheduleCategory, FollowUpPhase
from simulator.core import TurnSimulator
from simulator.entity import Entity
from simulator.status import Modifier, ModifierOp, StatType, StatusInstance


def _make_dummy_entity(
    name: str,
    *,
    speed: float = 100.0,
    is_enemy: bool = False,
    phase: FollowUpPhase | None = None,
) -> Entity:
    ent = Entity(
        name=name,
        base_speed=speed,
        base_atk=1000.0,
        max_hp=5000.0,
        current_hp=5000.0,
        is_enemy=is_enemy,
    )
    if phase is not None:
        ent.follow_up_phase = phase
    return ent


class TestSchedulerMechanics(unittest.TestCase):
    def test_five_tier_priority_and_preempt_follow_up(self) -> None:
        """验证五级队列优先级：preempt即时追加 > 追击 > 默认即时追加 > 预约队列(大招/自动战技/欢愉/预约追加) > 旅姬追加。"""
        a = _make_dummy_entity("角色A", speed=120.0)
        b = _make_dummy_entity("角色B", speed=110.0)
        enemy = _make_dummy_entity("木桩", speed=90.0, is_enemy=True)
        sim = TurnSimulator(entities=[a, b, enemy], use_techniques=False, auto_ult=False)

        order: List[str] = []
        sched = sim.scheduler
        # 故意乱序入队同一介入波次
        sched.enqueue("角色A", lambda: order.append("voyage"), category=ActionScheduleCategory.VOYAGE_EXTRA_TURN)
        sched.enqueue("角色A", lambda: order.append("res_et"), category=ActionScheduleCategory.RESERVED_EXTRA_TURN)
        sched.enqueue("角色A", lambda: order.append("elation"), category=ActionScheduleCategory.ELATION_SKILL)
        sched.enqueue("角色A", lambda: order.append("auto_skill"), category=ActionScheduleCategory.AUTO_SKILL)
        sched.enqueue("角色A", lambda: order.append("ult"), category=ActionScheduleCategory.ULTIMATE)
        sched.enqueue("角色A", lambda: order.append("imm_normal"), category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN, preempt_follow_up=False)
        sched.enqueue("角色B", lambda: order.append("fua"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.enqueue("角色A", lambda: order.append("imm_preempt"), category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN, preempt_follow_up=True)

        res = sched.drain_with_status()
        self.assertFalse(res.blocked)
        self.assertEqual(res.executed_count, 8)
        self.assertEqual(
            order,
            ["imm_preempt", "fua", "imm_normal", "ult", "auto_skill", "elation", "res_et", "voyage"],
        )

    def test_followup_four_phase_sort_and_normal_circular_left_shift(self) -> None:
        """验证同波次追击四段位排序 (FAST -> NORMAL循环左移 -> SLOW -> COUNTER) 与跨波次严格 FIFO。"""
        p1 = _make_dummy_entity("一号位", phase=FollowUpPhase.NORMAL)
        p2 = _make_dummy_entity("二号位", phase=FollowUpPhase.NORMAL)
        p3 = _make_dummy_entity("三号位", phase=FollowUpPhase.NORMAL)
        fast = _make_dummy_entity("快速追击", phase=FollowUpPhase.FAST)
        slow = _make_dummy_entity("慢速追击", phase=FollowUpPhase.SLOW)
        cnt = _make_dummy_entity("反击位", phase=FollowUpPhase.COUNTER)
        enemy = _make_dummy_entity("木桩", is_enemy=True)
        sim = TurnSimulator(entities=[p1, p2, p3, fast, slow, cnt, enemy], use_techniques=False, auto_ult=False)

        order: List[str] = []
        sched = sim.scheduler
        # 第一波次：所有段位混序入队
        sched.enqueue("反击位", lambda: order.append("cnt"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.enqueue("慢速追击", lambda: order.append("slow"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.enqueue("一号位", lambda: order.append("n1"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.enqueue("三号位", lambda: order.append("n3"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.enqueue("二号位", lambda: order.append("n2"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.enqueue("快速追击", lambda: order.append("fast"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.commit_staging_wave()

        # 第二波次：即便来了 FAST，也必须严格排在第一波次之后 (FIFO)
        sched.enqueue("快速追击", lambda: order.append("wave2_fast"), category=ActionScheduleCategory.FOLLOW_UP)
        sched.drain()

        # NORMAL 组 [一号位, 二号位, 三号位] 循环左移 -> [二号位, 三号位, 一号位]
        self.assertEqual(order, ["fast", "n2", "n3", "n1", "slow", "cnt", "wave2_fast"])

    def test_continuous_action_hold_head_of_line_blocking(self) -> None:
        """验证连续行动锁：队首为 ULTIMATE 可穿透执行；队首为非 ULTIMATE 时整条预约队列被阻塞，释放后按原 FIFO 排空。"""
        a = _make_dummy_entity("角色A", speed=120.0)
        enemy = _make_dummy_entity("木桩", speed=90.0, is_enemy=True)
        sim = TurnSimulator(entities=[a, enemy], use_techniques=False, auto_ult=False)

        order: List[str] = []
        sched = sim.scheduler

        # 波次 1：先预约一个 RESERVED_EXTRA_TURN，再在波次 2 预约一个 ULTIMATE
        sched.enqueue("角色A", lambda: order.append("res_et"), category=ActionScheduleCategory.RESERVED_EXTRA_TURN)
        sched.commit_staging_wave()
        sched.enqueue("角色A", lambda: order.append("ult_behind"), category=ActionScheduleCategory.ULTIMATE)
        sched.commit_staging_wave()

        with sched.hold_continuous_action():
            self.assertFalse(sched.has_executable_pending())
            res_blocked = sched.drain_with_status()
            self.assertTrue(res_blocked.blocked)
            self.assertEqual(res_blocked.executed_count, 0)
            self.assertEqual(order, [])

        # 解除锁定后严格按原 FIFO 顺序依次释放
        self.assertTrue(sched.has_executable_pending())
        res_free = sched.drain_with_status()
        self.assertFalse(res_free.blocked)
        self.assertEqual(order, ["res_et", "ult_behind"])

    def test_extra_turn_preserves_buff_duration_and_timeline_av(self) -> None:
        """验证即时追加回合不消耗常规 Buff 持续回合数，也不重置实体在时间轴上的剩余 AV。"""
        a = _make_dummy_entity("角色A", speed=100.0)
        enemy = _make_dummy_entity("木桩", speed=80.0, is_enemy=True)
        sim = TurnSimulator(entities=[a, enemy], use_techniques=False, auto_ult=False)

        sim.status_mgr.add_status(
            StatusInstance(
                id="test_regular_buff",
                name="测试常规增益",
                source=a,
                target=a,
                category="buff",
                duration=2,
                modifiers=[Modifier(stat=StatType.ATK_PERCENT, op=ModifierOp.ADD, value=0.30)],
            )
        )
        av_before = a.remaining_av

        executed = []
        sim.scheduler.enqueue(
            "角色A",
            lambda: executed.append(True),
            category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
            action_kind=ActionKind.SKILL,
        )
        sim.scheduler.drain()

        self.assertEqual(len(executed), 1)
        self.assertAlmostEqual(a.remaining_av, av_before, places=6)
        st = next((s for s in sim.status_mgr.get_statuses("角色A") if s.id == "test_regular_buff"), None)
        self.assertIsNotNone(st)
        self.assertEqual(st.duration, 2)

    def test_action_advance_clamp_and_delay(self) -> None:
        """验证拉条 100% 将 AV 钳位至 0 且不产生负值，推条 50% 正确增加 base_av * 0.5。"""
        a = _make_dummy_entity("角色A", speed=100.0)  # base_av = 100.0
        enemy = _make_dummy_entity("木桩", speed=80.0, is_enemy=True)
        sim = TurnSimulator(entities=[a, enemy], use_techniques=False, auto_ult=False)

        self.assertAlmostEqual(a.remaining_av, 100.0, places=4)
        sim.port.advance("角色A", "角色A", 1.0)
        self.assertAlmostEqual(a.remaining_av, 0.0, places=4)

        sim.port.delay("木桩", "角色A", 0.5)
        self.assertAlmostEqual(a.remaining_av, 50.0, places=4)


if __name__ == "__main__":
    unittest.main()

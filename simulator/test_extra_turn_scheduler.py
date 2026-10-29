"""追加回合 (Extra Turn) 与统一预约动作队列 (Reserved Action Queue) 单元测试套件.

覆盖 Asagi 深度实测视频 1 & 2 (`LNZ7VmsjPAs` / `AWQRc9zjuDc`)、Veritas 官方日志与架构师回归契约：
1. 追加回合的本质是 Action 而非 Turn：不触发 `TurnBeginEvent` / `TurnEndEvent`，不衰减 Buff 回合，不重置跑道；
2. 单回合 SP 消耗归属 (星期日光锥【回到大地的飞行】判定)：自身自然回合内的原动作 + 追加回合共享 SP 消耗计数 (A/D/E/F)，
   队友回合内触发的追加回合不计入自身回合 SP 消耗 (B/C)；
3. 单次攻击的三段介入点 (`before_hit` -> `after_hit` -> `on_kill`) 与 `_reserved_queue` 严格跨波次 FIFO；
4. 五类追加回合全局优先级：`IMMEDIATE_EXTRA_TURN (preempt_follow_up=True)` > `FOLLOW_UP` >
   `IMMEDIATE_EXTRA_TURN (preempt_follow_up=False)` > `_reserved_queue` (`ULTIMATE / AUTO_SKILL / ELATION_SKILL / RESERVED_EXTRA_TURN`) >
   `VOYAGE_EXTRA_TURN` > 时间轴跑条；
5. Archer 连续行动锁定 (`continuous_action_hold`) 下的队首阻塞机制与 `CADB` 终结技锁死复现；
6. 流萤 E2 与希儿【再现】真实 Kit 实测验证。
"""
import unittest

from simulator.actions import (
    AbilityDefinition,
    ActionContext,
    ActionKind,
    ActionScheduleCategory,
    DamageType,
    ResourceCost,
    TargetMode,
)
from simulator.combat_port import BuffSpec
from simulator.core import Entity, TurnSimulator
from simulator.events import (
    ActionExecuteEvent,
    BattleEvent,
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    TurnBeginEvent,
    TurnEndEvent,
)
from simulator.kits.base import KitHandler
from simulator.kits.characters.firefly import FireflyKit
from simulator.kits.characters.seele import SeeleKit
from simulator.status import DurationTiming, Modifier, ModifierOp, StatType


class _DummySPKit(KitHandler):
    """测试专用：每次战技消耗指定 SP 的简易套件。"""

    def __init__(self, owner_id: str, port, sp_cost: int = 2):
        super().__init__(owner_id, port)
        self.sp_cost = sp_cost
        self.seen_action_ids = []

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=ActionKind.BASIC,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=f"{self.owner_id}普攻",
            )
        if kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=ActionKind.SKILL,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=self.sp_cost),
                name=f"{self.owner_id}战技",
            )
        if kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=ActionKind.ULTIMATE,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=100.0),
                name=f"{self.owner_id}终结技",
            )
        raise ValueError(kind)

    def execute(self, ctx: ActionContext) -> None:
        self.seen_action_ids.append(ctx.action_id)


class TestExtraTurnAndReservedQueueScheduler(unittest.TestCase):
    """验证五类追加回合、统一预约动作队列与连续行动锁定机制。"""

    def test_video1_quiz1_extra_turn_is_action_not_turn_lifecycle(self):
        """测试 1: 自然回合主动作 + 两次追加回合仅产生一对 TurnBegin/TurnEnd，1 回合 Buff 不提前过期，action_id 唯一。"""
        hero = Entity(name="希儿", base_speed=150.0, base_atk=1000.0, policy="E")
        enemy = Entity(name="木桩", base_speed=100.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(entities=[hero, enemy], initial_sp=6, max_sp=6, auto_ult=False)
        kit = _DummySPKit("希儿", sim.port, sp_cost=1)
        hero.kit = kit

        # 推进至希儿自然回合开始
        sim.advance_to_next_turn()
        # 挂载 1 回合 Buff (skip_current_clock=False，在当前自然回合结束时应恰好过期)
        sim.port.upsert_status(
            BuffSpec(
                key="OneTurnBuff",
                name="单回合增益",
                source_id="希儿",
                target_id="希儿",
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=False,
            )
        )

        # 在本回合中预约 2 次追加回合，并在每次追加回合执行时断言 1 回合 Buff 依然存在
        buff_alive_during_extra_turns = []

        def _extra_turn_1():
            buff_alive_during_extra_turns.append(sim.port.has_status("希儿", "OneTurnBuff"))
            sim.execute_extra_turn("希儿", action_override=ActionKind.SKILL)

        def _extra_turn_2():
            buff_alive_during_extra_turns.append(sim.port.has_status("希儿", "OneTurnBuff"))
            sim.execute_extra_turn("希儿", action_override=ActionKind.SKILL)

        sim.port.schedule_extra_turn(
            "希儿",
            _extra_turn_1,
            name="再现#1",
            category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
            publish_execute_event=False,
        )
        sim.port.schedule_extra_turn(
            "希儿",
            _extra_turn_2,
            name="再现#2",
            category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
            publish_execute_event=False,
        )

        sim.execute_current_turn(action_override=ActionKind.SKILL)

        turn_begins = [e for e in sim.event_bus.history if isinstance(e, TurnBeginEvent) and e.actor_name == "希儿"]
        turn_ends = [e for e in sim.event_bus.history if isinstance(e, TurnEndEvent) and e.actor_name == "希儿"]
        action_execs = [e for e in sim.event_bus.history if isinstance(e, ActionExecuteEvent) and e.actor_name == "希儿"]

        self.assertEqual(len(turn_begins), 1, "自然回合 + 2 次追加回合只能有 1 次 TurnBeginEvent")
        self.assertEqual(len(turn_ends), 1, "自然回合 + 2 次追加回合只能有 1 次 TurnEndEvent")
        self.assertEqual(len(action_execs), 3, "应实际执行 3 次战技 Action")
        self.assertEqual(buff_alive_during_extra_turns, [True, True], "两次追加回合期间 1 回合 Buff 绝不提前衰减")
        self.assertFalse(sim.port.has_status("希儿", "OneTurnBuff"), "整个自然回合收尾后 1 回合 Buff 正常到期")
        self.assertEqual(len(set(kit.seen_action_ids)), 3, "同 AV 下的多次动作必须具有唯一 action_id")

    def test_video1_quiz1_sunday_lc_own_turn_sp_accounting_adef_vs_bc(self):
        """测试 2 (Video 1 Quiz 1): 星期日光锥【回到大地的飞行】单回合 4 SP 规则 (A/D/E/F 触发 vs B/C 不触发)。"""
        seele = Entity(name="希儿", base_speed=150.0, base_atk=1000.0, policy="E")
        ally = Entity(name="布洛妮娅", base_speed=160.0, base_atk=1000.0, policy="E")
        enemy = Entity(name="木桩", base_speed=90.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(entities=[ally, seele, enemy], initial_sp=8, max_sp=8, auto_ult=False)
        ally.kit = _DummySPKit("布洛妮娅", sim.port, sp_cost=1)
        seele.kit = _DummySPKit("希儿", sim.port, sp_cost=2)

        # --- 情形 B/C: 在队友【布洛妮娅】的自然回合中，【希儿】获得 2 次追加回合共消耗 4 SP ---
        sim.advance_to_next_turn()
        self.assertEqual(sim.current_turn_entity.name, "布洛妮娅")

        seele_sp_in_ally_turn = []

        def _seele_extra_in_ally_turn():
            sim.execute_extra_turn("希儿", action_override=ActionKind.SKILL)
            seele_sp_in_ally_turn.append(sim.port.turn_sp_consumed("希儿"))

        sim.port.schedule_extra_turn(
            "希儿",
            _seele_extra_in_ally_turn,
            category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
            publish_execute_event=False,
        )
        sim.port.schedule_extra_turn(
            "希儿",
            _seele_extra_in_ally_turn,
            category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
            publish_execute_event=False,
        )
        sim.execute_current_turn(action_override=ActionKind.SKILL)
        self.assertEqual(
            seele_sp_in_ally_turn,
            [0, 0],
            "情形 B/C：在队友的自然回合中执行追加回合，希儿的「自身单回合 SP 消耗计数」必须为 0！",
        )

        # --- 情形 A/D/E/F: 在【希儿】自身的自然回合中，主动作消耗 2 SP + 追加回合消耗 2 SP = 累计 4 SP ---
        sim.sp.current_sp = 8
        sim.advance_to_next_turn()
        self.assertEqual(sim.current_turn_entity.name, "希儿")

        seele_sp_in_own_turn = []

        def _seele_extra_in_own_turn():
            sim.execute_extra_turn("希儿", action_override=ActionKind.SKILL)
            seele_sp_in_own_turn.append(sim.port.turn_sp_consumed("希儿"))

        sim.port.schedule_extra_turn(
            "希儿",
            _seele_extra_in_own_turn,
            category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
            publish_execute_event=False,
        )
        sim.execute_current_turn(action_override=ActionKind.SKILL)
        self.assertEqual(
            seele_sp_in_own_turn,
            [4],
            "情形 A/D/E/F：在希儿自身自然回合内，主动作(2 SP) + 追加回合(2 SP) 累计消耗应为 4 SP！",
        )

    def test_video1_quiz2_three_intervention_points_and_reserved_queue_fifo(self):
        """测试 3 (Video 1 Quiz 2): 单次攻击的 3 个介入点 (before_hit -> after_hit -> on_kill) 与 _reserved_queue 严格 FIFO。"""
        # 故意将编队站位设为 [希儿(0), 银狼(1), 珍珠(2)]，与期望触发顺序 [珍珠, 银狼, 希儿] 完全相反！
        seele = Entity(name="希儿", base_speed=150.0, base_atk=2000.0)
        sw = Entity(name="银狼", base_speed=140.0, base_atk=1000.0, max_energy=100.0, energy=100.0)
        pearl = Entity(name="珍珠", base_speed=130.0, base_atk=1000.0)
        enemy = Entity(name="残血小怪", base_speed=90.0, max_hp=500.0, current_hp=500.0, is_enemy=True)
        sim = TurnSimulator(entities=[seele, sw, pearl, enemy], auto_ult=False)
        sw.kit = _DummySPKit("银狼", sim.port, sp_cost=1)

        executed_order = []

        class _InterventionObserverKit(KitHandler):
            def definition(self, kind: ActionKind) -> AbilityDefinition:
                return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, name="测试斩击")

            def execute(self, ctx: ActionContext) -> None:
                # 介入点 1 (before_hit): 攻击开始、命中前，珍珠触发追加回合予約
                sim.port.schedule_extra_turn(
                    "珍珠",
                    lambda: executed_order.append("珍珠(before_hit追加回合)"),
                    category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
                )
                sim.port.attack(
                    self.owner_id,
                    "残血小怪",
                    element="Quantum",
                    atk_multiplier=5.0,
                    toughness_damage=10.0,
                    damage_type=DamageType.SKILL,
                )

            def on_event(self, event: BattleEvent) -> None:
                if isinstance(event, DamageAppliedEvent) and event.attacker_name == "希儿":
                    # 介入点 2 (after_hit): 攻击命中后，银狼触发追加回合予約，同时预约银狼终结技
                    sim.port.queue_ultimate("银狼")
                    sim.port.schedule_extra_turn(
                        "银狼",
                        lambda: executed_order.append("银狼(after_hit追加回合)"),
                        category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
                    )
                elif isinstance(event, EnemyDefeatedEvent) and event.attacker_name == "希儿":
                    # 介入点 3 (on_kill): 敌方被击败时，希儿触发【再现】追加回合予約
                    sim.port.schedule_extra_turn(
                        "希儿",
                        lambda: executed_order.append("希儿(on_kill再现追加回合)"),
                        category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
                    )

        seele.kit = _InterventionObserverKit("希儿", sim.port)
        sim.event_bus.subscribe(
            ActionExecuteEvent,
            lambda e: executed_order.append("银狼(after_hit终结技)")
            if e.actor_name == "银狼" and e.action_kind == ActionKind.ULTIMATE
            else None,
        )

        # 留一个存活木桩避免全灭跳过，执行希儿对残血小怪的击杀攻击
        dummy_alive = Entity(name="存活木桩", base_speed=80.0, max_hp=99999.0, current_hp=99999.0, is_enemy=True)
        sim.add_entity(dummy_alive, trigger_battle_start=False)
        sim.advance_to_next_turn()
        sim.execute_current_turn(action_override=ActionKind.SKILL, target_ids=("残血小怪",))

        self.assertEqual(
            executed_order,
            [
                "珍珠(before_hit追加回合)",
                "银狼(after_hit终结技)",
                "银狼(after_hit追加回合)",
                "希儿(on_kill再现追加回合)",
            ],
            "必须严格按 before_hit -> after_hit (同波次 ULT 先于 EXTRA_TURN) -> on_kill 的预约 FIFO 顺序执行，"
            "后介入点预约的终结技绝不可越过先介入点的珍珠追加回合！",
        )

    def test_video2_quiz1_voyage_himeko_preempted_by_reserved_extra_turn(self):
        """测试 4 (Video 2 Quiz 1): 旅姬小型追加回合 (VOYAGE_EXTRA_TURN) 优先级低于 _reserved_queue (被希儿大招击杀再现抢占)。"""
        seele = Entity(name="希儿", base_speed=150.0, base_atk=1000.0)
        tb = Entity(name="开拓者", base_speed=140.0, base_atk=1000.0)
        himeko = Entity(name="姬子•旅途", base_speed=130.0, base_atk=1000.0)
        enemy = Entity(name="木桩", base_speed=90.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(entities=[seele, tb, himeko, enemy], auto_ult=False)

        executed = []

        with sim.scheduler.action_frame():
            # 1. 旅姬为开拓者赋予支援追加回合 (VOYAGE_EXTRA_TURN)
            def _tb_voyage_turn():
                executed.append("开拓者(旅姬支援追加回合)")
                # 开拓者在支援追加回合前/中，希儿第二次获得再现追加回合
                sim.port.schedule_extra_turn(
                    "希儿",
                    lambda: executed.append("希儿(第2次再现追加回合)"),
                    category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
                )

            sim.port.schedule_extra_turn(
                "开拓者",
                _tb_voyage_turn,
                category=ActionScheduleCategory.VOYAGE_EXTRA_TURN,
            )
            sim.scheduler.commit_reserved_wave()

            # 2. 希儿插队终结技击杀小怪，触发第 1 次【再现】追加回合 (RESERVED_EXTRA_TURN)
            sim.port.schedule_extra_turn(
                "希儿",
                lambda: executed.append("希儿(第1次再现追加回合)"),
                category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
            )

        sim.scheduler.drain()

        self.assertEqual(
            executed,
            [
                "希儿(第1次再现追加回合)",
                "开拓者(旅姬支援追加回合)",
                "希儿(第2次再现追加回合)",
            ],
            "Video 2 Quiz 1 实证：希儿大招击杀的 RESERVED_EXTRA_TURN 必须抢占已在等待的旅姬 VOYAGE_EXTRA_TURN！",
        )

    def test_video2_immediate_extra_turn_preempt_vs_non_preempt_followup(self):
        """测试 5 (Video 2): 即时型追加回合 (IMMEDIATE_EXTRA_TURN) 抢占 _reserved_queue，且支持 preempt_follow_up 开关。"""
        cyrene = Entity(name="昔涟", base_speed=150.0, base_atk=1000.0)
        rappa = Entity(name="乱破", base_speed=140.0, base_atk=1000.0)
        tribbie = Entity(name="缇宝", base_speed=120.0, base_atk=1000.0)
        pearl = Entity(name="珍珠", base_speed=130.0, base_atk=1000.0)
        enemy = Entity(name="木桩", base_speed=90.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(entities=[cyrene, rappa, tribbie, pearl, enemy], auto_ult=False)

        executed = []
        with sim.scheduler.action_frame():
            # 先预约珍珠的 RESERVED_EXTRA_TURN
            sim.port.schedule_extra_turn(
                "珍珠",
                lambda: executed.append("珍珠(RESERVED_EXTRA_TURN)"),
                category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
            )
            sim.scheduler.commit_reserved_wave()

            # 随后乱破大招触发法印 (IMMEDIATE_EXTRA_TURN, preempt_follow_up=False) 与缇宝追击 (FOLLOW_UP)，
            # 以及昔涟首次大招 (IMMEDIATE_EXTRA_TURN, preempt_follow_up=True)
            sim.port.schedule_follow_up(
                "缇宝",
                lambda: executed.append("缇宝(FOLLOW_UP)"),
            )
            sim.port.schedule_extra_turn(
                "乱破",
                lambda: executed.append("乱破(IMMEDIATE_EXTRA_TURN,preempt=False)"),
                category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                preempt_follow_up=False,
            )
            sim.port.schedule_extra_turn(
                "昔涟",
                lambda: executed.append("昔涟(IMMEDIATE_EXTRA_TURN,preempt=True)"),
                category=ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                preempt_follow_up=True,
            )

        sim.scheduler.drain()

        self.assertEqual(
            executed,
            [
                "昔涟(IMMEDIATE_EXTRA_TURN,preempt=True)",
                "缇宝(FOLLOW_UP)",
                "乱破(IMMEDIATE_EXTRA_TURN,preempt=False)",
                "珍珠(RESERVED_EXTRA_TURN)",
            ],
            "优先级顺序必须为：昔涟(preempt_follow_up=True) -> 缇宝追击(FOLLOW_UP) -> 乱破(IMMEDIATE) -> 珍珠(RESERVED)！",
        )

    def test_video2_quiz2_archer_continuous_action_hold_lockout_cadb(self):
        """测试 6 (Video 2 Quiz 2): Archer 连续行动锁定 (continuous_action_hold) 下复现 CADB 大招锁死时序。"""
        archer = Entity(name="Archer", base_speed=150.0, base_atk=1000.0, max_energy=100.0, energy=100.0)
        huohuo = Entity(name="藿藿", base_speed=140.0, base_atk=1000.0, max_energy=100.0, energy=100.0)
        aha = Entity(name="阿哈", base_speed=130.0, base_atk=1000.0)
        enemy = Entity(name="木桩", base_speed=90.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(entities=[archer, huohuo, aha, enemy], initial_sp=6, max_sp=6, auto_ult=False)

        timeline_order = []

        class _HuohuoKit(_DummySPKit):
            def execute(self, ctx: ActionContext) -> None:
                if ctx.kind == ActionKind.ULTIMATE:
                    timeline_order.append("C:藿藿终结技")
                    # 藿藿终结技触发阿哈时刻 (进入 _reserved_queue)
                    sim.port.schedule_extra_action(
                        "阿哈",
                        lambda: timeline_order.append("D:阿哈时刻"),
                        name="阿哈时刻",
                        category=ActionScheduleCategory.ELATION_SKILL,
                    )

        class _ArcherKit(_DummySPKit):
            def execute(self, ctx: ActionContext) -> None:
                if ctx.kind == ActionKind.SKILL:
                    timeline_order.append("A:Archer战技#2")
                elif ctx.kind == ActionKind.ULTIMATE:
                    timeline_order.append("B:Archer终结技")

        huohuo.kit = _HuohuoKit("藿藿", sim.port, sp_cost=1)
        archer.kit = _ArcherKit("Archer", sim.port, sp_cost=2)

        # 1. 进入 Archer 的自然回合，开启连续战技锁定 (continuous_action_hold = True)
        sim.advance_to_next_turn()
        self.assertEqual(sim.current_turn_entity.name, "Archer")
        sim.scheduler.continuous_action_hold = True

        # 2. Archer 施放第 1 发战技后，预约藿藿终结技 (C)
        # 此时 _reserved_queue 队首是藿藿的 ULTIMATE，允许弹出执行；
        # 藿藿终结技诱发阿哈时刻 (D, ELATION_SKILL) 进入 _reserved_queue 队首并被 hold 冻结阻塞！
        sim.cast_ultimate("藿藿")
        self.assertEqual(timeline_order, ["C:藿藿终结技"])
        self.assertTrue(sim.scheduler.last_drain_blocked, "阿哈时刻位于 _reserved_queue 队首，必须被 hold 阻塞")

        # 3. Archer 准备施放第 2 发战技 (A)，同时连点预约 Archer 自己的终结技 (B)
        # 由于 _reserved_queue 队首被阿哈时刻 (D) 堵住，Archer 终结技 (B) 排在 D 之后被一并锁死！
        sim.request_ultimate("Archer")
        sim.execute_current_turn(action_override=ActionKind.SKILL)

        # 验证此时 Archer 的第 2 发战技 (A) 已打出，但 D 与 B 仍被锁在队列中，且 Archer 自然回合尚未结束！
        self.assertEqual(
            timeline_order,
            ["C:藿藿终结技", "A:Archer战技#2"],
            "连续战技锁定解除前，阿哈时刻(D)与排在其后的 Archer 终结技(B)均不得执行！",
        )
        self.assertIsNotNone(sim.current_turn_entity, "连续战技锁定期间自然回合不得提前结束")

        # 4. Archer 结束连续战技状态 -> 解除 hold，按 FIFO 依次释放 D -> B 并结束自然回合
        sim.finish_continuous_turn()

        self.assertEqual(
            timeline_order,
            ["C:藿藿终结技", "A:Archer战技#2", "D:阿哈时刻", "B:Archer终结技"],
            "Video 2 Quiz 2 实证：最终执行顺序必须严格为 C -> A -> D -> B (CADB)！",
        )
        self.assertIsNone(sim.current_turn_entity, "解除锁定并排空派生队列后，自然回合正常收尾")

    def test_firefly_e2_and_seele_resurgence_kits_use_extra_turn_not_advance(self):
        """测试 7: 验证流萤 E2 与希儿【再现】Kit 在击杀时触发真正的 RESERVED_EXTRA_TURN 而非 100% 拉条。"""
        # 7A. 希儿击杀触发【再现】追加回合
        seele = Entity(name="希儿", base_speed=150.0, base_atk=3000.0, policy="E")
        mob = Entity(name="小怪", base_speed=90.0, max_hp=500.0, current_hp=500.0, is_enemy=True)
        boss = Entity(name="首领", base_speed=90.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(entities=[seele, mob, boss], initial_sp=5, max_sp=5, auto_ult=False)
        seele.kit = SeeleKit("希儿", sim.port, eidolon=0)

        sim.advance_to_next_turn()
        sim.execute_current_turn(action_override=ActionKind.SKILL, target_ids=("小怪",))

        turn_begins = [e for e in sim.event_bus.history if isinstance(e, TurnBeginEvent) and e.actor_name == "希儿"]
        turn_ends = [e for e in sim.event_bus.history if isinstance(e, TurnEndEvent) and e.actor_name == "希儿"]
        seele_actions = [e for e in sim.event_bus.history if isinstance(e, ActionExecuteEvent) and e.actor_name == "希儿"]

        self.assertEqual(len(turn_begins), 1, "希儿击杀再现不应产生第 2 个 TurnBeginEvent")
        self.assertEqual(len(turn_ends), 1, "希儿击杀再现不应产生第 2 个 TurnEndEvent")
        self.assertEqual(len(seele_actions), 2, "希儿应在单次自然回合内完成原动作 + 再现追加回合共 2 次行动")

        # 7B. 流萤 E2 击杀触发【自破碎的星空坠落】追加回合，验证完全燃烧 Buff 与 E1 防御穿透 Buff 不在追加回合衰减
        ff = Entity(name="流萤", base_speed=150.0, base_atk=3000.0, max_hp=3000.0, current_hp=3000.0, policy="E")
        mob2 = Entity(name="小怪2", base_speed=90.0, max_hp=500.0, current_hp=500.0, is_enemy=True)
        boss2 = Entity(name="首领2", base_speed=90.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim_ff = TurnSimulator(entities=[ff, mob2, boss2], initial_sp=5, max_sp=5, auto_ult=False)
        ff_kit = FireflyKit("流萤", sim_ff.port, eidolon=2)
        ff_kit.is_combustion = True
        ff.kit = ff_kit

        sim_ff.advance_to_next_turn()
        sim_ff.execute_current_turn(action_override=ActionKind.SKILL, target_ids=("小怪2",))

        ff_turn_begins = [e for e in sim_ff.event_bus.history if isinstance(e, TurnBeginEvent) and e.actor_name == "流萤"]
        ff_actions = [e for e in sim_ff.event_bus.history if isinstance(e, ActionExecuteEvent) and e.actor_name == "流萤"]
        self.assertEqual(len(ff_turn_begins), 1, "流萤 E2 额外回合属于追加回合而非拉条，不应产生新 TurnBeginEvent")
        self.assertEqual(len(ff_actions), 2, "流萤 E2 应在当前自然回合内连续执行 2 次强化战技")


if __name__ == "__main__":
    unittest.main()

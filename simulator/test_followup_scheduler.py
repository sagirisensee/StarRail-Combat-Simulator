# coding: utf-8
"""追加攻击与回合外派生动作调度器单元测试 (Follow-Up & Extra Action Scheduler Tests).

覆盖实机底层四大调度铁律与官方 Veritas 日志分类对齐：
1. 常规追击组 (`FollowUpPhase.NORMAL`) 候选人循环左移规则 (`candidates[1:] + candidates[:1]`) 及全排列验证；
2. 未触发的常规组候选人依然占据 `candidates` 首位参与左移，以及替换非追击角色 (风堇) / 快慢组角色 (砂金/Archer) 时的顺位翻转；
3. 同波次四段位优先级分组 (`FAST` -> `NORMAL` -> `SLOW` -> `COUNTER`)；
4. 追击队列严格 FIFO 铁律 (追击诱发的二段追击追加至队尾，绝不插队超越已入队的慢速组追击)；
5. 动作调度分类 (`ActionScheduleCategory`) 与伤害标签 (`DamageType`) 解耦，以及跨级抢占造成的三连追击穿插奇观。
"""
import itertools
import unittest
from typing import List

from simulator.actions import (
    AbilityDefinition,
    ActionContext,
    ActionKind,
    ActionScheduleCategory,
    DamageType,
    FollowUpPhase,
    ResourceCost,
    TargetMode,
)
from simulator.core import Entity, TurnSimulator
from simulator.events import ActionExecuteEvent, DamageAppliedEvent
from simulator.golden_diff import SKILL_TYPE_BY_KIND
from simulator.kits.base import KitHandler
from simulator.kits.characters.archer import ArcherKit
from simulator.kits.characters.aventurine import AventurineKit
from simulator.kits.characters.bronya import BronyaKit
from simulator.kits.characters.clara import ClaraKit
from simulator.kits.characters.dahlia import DahliaKit
from simulator.kits.characters.moze import MozeKit
from simulator.kits.characters.ratio import RatioKit
from simulator.kits.characters.topaz import TopazKit
from simulator.kits.characters.yunli import YunliKit


class _DummyKit(KitHandler):
    """用于测试编队站位与触发时序的轻量测试 Kit。"""

    def __init__(self, owner_id: str, port, *, phase=None, has_fua_def: bool = True):
        super().__init__(owner_id, port)
        self.follow_up_phase = phase
        self._has_fua_def = has_fua_def

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.FOLLOW_UP and not self._has_fua_def:
            raise ValueError("该角色无追加攻击")
        return AbilityDefinition(
            kind=kind,
            target_mode=TargetMode.SINGLE_ENEMY,
            cost=ResourceCost(sp=0),
            name=f"{self.owner_id}_{kind.name}",
        )

    def execute(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Imaginary",
                atk_multiplier=1.0,
                toughness_damage=10.0,
                damage_type=DamageType.BASIC if ctx.kind == ActionKind.BASIC else DamageType.SKILL,
            )


def _make_ally(name: str, phase=FollowUpPhase.NORMAL, has_fua: bool = True, speed: float = 100.0) -> Entity:
    ent = Entity(name=name, base_speed=speed, follow_up_phase=phase)
    ent.kit = _DummyKit(name, None, phase=phase, has_fua_def=has_fua)
    return ent


def _make_enemy(name: str = "Boss") -> Entity:
    return Entity(name=name, base_speed=80.0, max_hp=1_000_000.0, current_hp=1_000_000.0, is_enemy=True)


class TestFollowUpScheduler(unittest.TestCase):
    """验证实机追加攻击队列与回合外派生动作调度器。"""

    def test_quiz1_and_non_triggering_normal_candidate_shift(self):
        """验证第 1 题与核心对比实验：
        - 编队 [风堇(无追击), 托帕(Normal), 真理(Normal), 星期日(无追击)]：
          常规组候选人 = [托帕, 真理] -> 循环左移后 = [真理, 托帕] (真理先于托帕)；
        - 编队 [飞霄(Normal), 托帕(Normal), 真理(Normal), 星期日(无追击)]：
          即便飞霄是当前主动攻击者、未在本次触发追击，她依然占据常规组候选人 1 号位！
          常规组候选人 = [飞霄, 托帕, 真理] -> 循环左移后 = [托帕, 真理, 飞霄]，
          因此同时触发的托帕与真理顺序翻转为 [托帕, 真理]！
        """
        # 场景 A: 1号位为风堇 (无追击)
        sim_a = TurnSimulator(
            entities=[
                _make_ally("风堇", phase=None, has_fua=False, speed=160.0),
                _make_ally("托帕", phase=FollowUpPhase.NORMAL),
                _make_ally("真理医生", phase=FollowUpPhase.NORMAL),
                _make_ally("星期日", phase=None, has_fua=False),
                _make_enemy(),
            ]
        )
        self.assertEqual(sim_a.scheduler.get_normal_group_candidates(), ["托帕", "真理医生"])
        self.assertEqual(sim_a.scheduler.get_normal_group_shifted_order(), ["真理医生", "托帕"])

        order_a: List[str] = []
        with sim_a.scheduler.action_frame():
            # 故意先入队托帕、后入队真理，验证排序完全由循环左移规则决定而非代码注册先后
            sim_a.port.schedule_follow_up("托帕", lambda: order_a.append("托帕"))
            sim_a.port.schedule_follow_up("真理医生", lambda: order_a.append("真理医生"))
        sim_a.scheduler.drain()
        self.assertEqual(order_a, ["真理医生", "托帕"])

        # 场景 B: 1号位换为飞霄 (属于 Normal 追击组，但本次作为攻击者不触发追击)
        sim_b = TurnSimulator(
            entities=[
                _make_ally("飞霄", phase=FollowUpPhase.NORMAL, speed=160.0),
                _make_ally("托帕", phase=FollowUpPhase.NORMAL),
                _make_ally("真理医生", phase=FollowUpPhase.NORMAL),
                _make_ally("星期日", phase=None, has_fua=False),
                _make_enemy(),
            ]
        )
        self.assertEqual(sim_b.scheduler.get_normal_group_candidates(), ["飞霄", "托帕", "真理医生"])
        self.assertEqual(sim_b.scheduler.get_normal_group_shifted_order(), ["托帕", "真理医生", "飞霄"])

        order_b: List[str] = []
        with sim_b.scheduler.action_frame():
            sim_b.port.schedule_follow_up("真理医生", lambda: order_b.append("真理医生"))
            sim_b.port.schedule_follow_up("托帕", lambda: order_b.append("托帕"))
        sim_b.scheduler.drain()
        self.assertEqual(order_b, ["托帕", "真理医生"])

    def test_quiz2_all_six_permutations_circular_left_shift(self):
        """验证第 2 题及三人全排列：无论 [真理, 托帕, 飞霄] 如何调换站位，同波次触发恒等于 candidates[1:] + candidates[:1]。"""
        chars = ["真理医生", "托帕", "飞霄"]
        for perm in itertools.permutations(chars):
            party = [_make_ally(name, phase=FollowUpPhase.NORMAL) for name in perm]
            party.append(_make_ally("星期日", phase=None, has_fua=False))
            party.append(_make_enemy())
            sim = TurnSimulator(entities=party)

            executed: List[str] = []
            with sim.scheduler.action_frame():
                for name in reversed(perm):
                    sim.port.schedule_follow_up(name, lambda n=name: executed.append(n))
            sim.scheduler.drain()

            expected = list(perm[1:]) + [perm[0]]
            self.assertEqual(executed, expected, f"编队 {perm} 左移排序不符")

        # 单独核对第 2 题标准答案：[真理医生, 飞霄, 托帕] -> [飞霄, 托帕, 真理医生]
        sim_q2 = TurnSimulator(
            entities=[
                _make_ally("真理医生", phase=FollowUpPhase.NORMAL),
                _make_ally("飞霄", phase=FollowUpPhase.NORMAL),
                _make_ally("托帕", phase=FollowUpPhase.NORMAL),
                _make_ally("星期日", phase=None, has_fua=False),
                _make_enemy(),
            ]
        )
        self.assertEqual(
            sim_q2.scheduler.get_normal_group_shifted_order(),
            ["飞霄", "托帕", "真理医生"],
        )

    def test_quiz3_phased_priority_fast_normal_slow_counter(self):
        """验证第 3 题与四段位分组优先级 (FAST -> NORMAL -> SLOW -> COUNTER)：
        编队 [砂金(FAST), 托帕(NORMAL), 真理医生(NORMAL), 大丽花(SLOW)]：
        - 砂金归属 FAST 组，最先执行；
        - 砂金不占用 NORMAL 组候选名额，因此 NORMAL 组候选人为 [托帕, 真理医生]，
          左移后为 [真理医生, 托帕]；
        - 大丽花归属 SLOW 组，最后执行；
        - 最终顺序：砂金 -> 真理医生 -> 托帕 -> 大丽花！
        """
        sim = TurnSimulator(
            entities=[
                _make_ally("砂金", phase=FollowUpPhase.FAST),
                _make_ally("托帕", phase=FollowUpPhase.NORMAL),
                _make_ally("真理医生", phase=FollowUpPhase.NORMAL),
                _make_ally("大丽花", phase=FollowUpPhase.SLOW),
                _make_enemy(),
            ]
        )
        executed: List[str] = []
        with sim.scheduler.action_frame():
            sim.port.schedule_follow_up("大丽花", lambda: executed.append("大丽花"))
            sim.port.schedule_follow_up("托帕", lambda: executed.append("托帕"))
            sim.port.schedule_follow_up("真理医生", lambda: executed.append("真理医生"))
            sim.port.schedule_follow_up("砂金", lambda: executed.append("砂金"))
        sim.scheduler.drain()

        self.assertEqual(executed, ["砂金", "真理医生", "托帕", "大丽花"])

    def test_fifo_queue_no_overtaking_across_waves(self):
        """验证铁律三 (FIFO 队列不可超车)：
        编队 [大丽花(SLOW), 托帕(NORMAL), 真理医生(NORMAL), 星期日]：
        - 第一波同时触发：真理 #1 (NORMAL)、托帕 #1 (NORMAL)、大丽花 #1 (SLOW)；
          根据分组与左移规则，第一波入队顺序为：[真理 #1, 托帕 #1, 大丽花 #1]；
        - 当【托帕 #1】执行攻击时，诱发了真理医生的第 2 次追击【真理 #2 (NORMAL)】；
        - 尽管真理属于 NORMAL 组、大丽花属于 SLOW 组，但【大丽花 #1】早已在队列中排队，
          新诱发的【真理 #2】必须排在队尾，绝不能插队到大丽花前面！
        - 最终执行顺序：真理 #1 -> 托帕 #1 -> 大丽花 #1 -> 真理 #2。
        """
        sim = TurnSimulator(
            entities=[
                _make_ally("大丽花", phase=FollowUpPhase.SLOW),
                _make_ally("托帕", phase=FollowUpPhase.NORMAL),
                _make_ally("真理医生", phase=FollowUpPhase.NORMAL),
                _make_ally("星期日", phase=None, has_fua=False),
                _make_enemy(),
            ]
        )
        executed: List[str] = []

        def topaz_fua():
            executed.append("托帕#1")
            # 托帕追击命中时诱发真理医生第 2 次追击
            sim.port.schedule_follow_up("真理医生", lambda: executed.append("真理医生#2"))

        with sim.scheduler.action_frame():
            sim.port.schedule_follow_up("大丽花", lambda: executed.append("大丽花#1"))
            sim.port.schedule_follow_up("托帕", topaz_fua)
            sim.port.schedule_follow_up("真理医生", lambda: executed.append("真理医生#1"))

        sim.scheduler.drain()
        self.assertEqual(
            executed,
            ["真理医生#1", "托帕#1", "大丽花#1", "真理医生#2"],
        )

    def test_quiz4_category_decoupled_from_damage_type(self):
        """验证第 4 题 (动作调度分类 ActionScheduleCategory 与伤害标签 DamageType 解耦)：
        编队 [绯英(千刃), 托帕/赛飞儿(NORMAL), 真理医生(NORMAL), 星期日/藿藿]：
        - 辅助角色攻击后，同时满足：真理 #1 (FOLLOW_UP)、托帕 #1 (FOLLOW_UP)、绯英【千刃】(AUTO_SKILL，造成 FOLLOW_UP 伤害)；
        - 常规组候选人 [托帕, 真理医生] 循环左移后为 [真理医生, 托帕]；
        - 由于绯英【千刃】在底层调度上属于 AUTO_SKILL (BPSkill)，必须等 _followup_queue 完全排空后才执行；
        - 在【托帕 #1】执行期间，又诱发了【真理 #2 (FOLLOW_UP)】进入 _followup_queue；
        - 因此【真理 #2】继续优先于【绯英•千刃】执行！
        - 最终顺序：真理医生#1 -> 托帕#1 -> 真理医生#2 -> 绯英•千刃。
        """
        sim = TurnSimulator(
            entities=[
                _make_ally("绯英", phase=None, has_fua=False),
                _make_ally("托帕", phase=FollowUpPhase.NORMAL),
                _make_ally("真理医生", phase=FollowUpPhase.NORMAL),
                _make_ally("星期日", phase=None, has_fua=False),
                _make_enemy(),
            ]
        )

        executed: List[str] = []
        action_events: List[ActionExecuteEvent] = []
        damage_events: List[DamageAppliedEvent] = []
        sim.event_bus.subscribe(ActionExecuteEvent, action_events.append)
        sim.event_bus.subscribe(DamageAppliedEvent, damage_events.append)

        def topaz_fua():
            executed.append("托帕#1")
            sim.port.attack(
                "托帕", "Boss", element="Fire", atk_multiplier=1.5, toughness_damage=10.0, damage_type=DamageType.FOLLOW_UP
            )
            sim.port.schedule_follow_up("真理医生", ratio_fua_2, name="我思故我在#2")

        def ratio_fua_1():
            executed.append("真理医生#1")
            sim.port.attack(
                "真理医生", "Boss", element="Imaginary", atk_multiplier=2.7, toughness_damage=10.0, damage_type=DamageType.FOLLOW_UP
            )

        def ratio_fua_2():
            executed.append("真理医生#2")
            sim.port.attack(
                "真理医生", "Boss", element="Imaginary", atk_multiplier=2.7, toughness_damage=10.0, damage_type=DamageType.FOLLOW_UP
            )

        def senji_auto_skill():
            executed.append("绯英•千刃")
            # 千刃在动作调度上是 AUTO_SKILL (ActionKind.SKILL)，但造成的伤害类型是 FOLLOW_UP！
            sim.port.attack(
                "绯英", "Boss", element="Physical", atk_multiplier=3.0, toughness_damage=20.0, damage_type=DamageType.FOLLOW_UP
            )

        with sim.scheduler.action_frame():
            sim.port.schedule_extra_action(
                "绯英",
                senji_auto_skill,
                name="千刃",
                category=ActionScheduleCategory.AUTO_SKILL,
                action_kind=ActionKind.SKILL,
                skill_id=150502,
            )
            sim.port.schedule_follow_up("托帕", topaz_fua, name="猪市？！")
            sim.port.schedule_follow_up("真理医生", ratio_fua_1, name="我思故我在#1")

        sim.scheduler.drain()

        self.assertEqual(
            executed,
            ["真理医生#1", "托帕#1", "真理医生#2", "绯英•千刃"],
        )
        # 验证千刃发布的动作事件是 ActionKind.SKILL (对应官方 BPSkill)，且没有因为 DamageType.FOLLOW_UP 误发第二个 FOLLOW_UP 动作事件
        self.assertEqual(len(action_events), 4)
        self.assertEqual(action_events[3].actor_id, "绯英")
        self.assertEqual(action_events[3].action_kind, ActionKind.SKILL)
        self.assertEqual(SKILL_TYPE_BY_KIND[action_events[3].action_kind], "BPSkill")
        # 同时验证千刃造成的伤害事件类型确实是 DamageType.FOLLOW_UP
        self.assertEqual(damage_events[3].attacker_name, "绯英")
        self.assertEqual(damage_events[3].damage_type, DamageType.FOLLOW_UP)

    def test_three_consecutive_followups_interleaving_cascade(self):
        """验证视频压轴奇观：不死途 (FOLLOW_UP) + 绯英千刃 (AUTO_SKILL) + 爻光欢愉技 (ELATION_SKILL) 级联抢占三连追击！
        1. 初始攻击同时触发：不死途#1 (FOLLOW_UP)、千刃 (AUTO_SKILL)、爻光欢愉技 (ELATION_SKILL)；
        2. 优先级最高的不死途#1 先执行；
        3. 随后轮到 AUTO_SKILL 队列的【千刃】执行，千刃攻击命中又诱发了【不死途#2 (FOLLOW_UP)】；
        4. 【不死途#2】进入 _followup_queue，立即抢占仍在 _elation_skill_queue 等待的【爻光欢愉技】！
        5. 【不死途#2】执行完毕后，终于轮到【爻光欢愉技】执行，其攻击再次诱发【不死途#3 (FOLLOW_UP)】！
        最终序列：不死途#1 -> 绯英•千刃 -> 不死途#2 -> 爻光•欢愉技 -> 不死途#3。
        """
        sim = TurnSimulator(
            entities=[
                _make_ally("不死途", phase=FollowUpPhase.NORMAL),
                _make_ally("绯英", phase=None, has_fua=False),
                _make_ally("爻光", phase=None, has_fua=False),
                _make_enemy(),
            ]
        )
        executed: List[str] = []
        action_kinds: List[ActionKind] = []
        sim.event_bus.subscribe(ActionExecuteEvent, lambda e: action_kinds.append(e.action_kind))

        def senji_skill():
            executed.append("绯英•千刃")
            # 千刃攻击诱发不死途第 2 次追击
            sim.port.schedule_follow_up("不死途", lambda: executed.append("不死途#2"))

        def elation_skill():
            executed.append("爻光•欢愉技")
            # 欢愉技攻击诱发不死途第 3 次追击
            sim.port.schedule_follow_up("不死途", lambda: executed.append("不死途#3"))

        with sim.scheduler.action_frame():
            sim.port.schedule_extra_action(
                "爻光",
                elation_skill,
                name="赠君一卦，火树银花",
                category=ActionScheduleCategory.ELATION_SKILL,
                action_kind=ActionKind.ELATION_SKILL,
                skill_id=150220,
            )
            sim.port.schedule_extra_action(
                "绯英",
                senji_skill,
                name="千刃",
                category=ActionScheduleCategory.AUTO_SKILL,
                action_kind=ActionKind.SKILL,
            )
            sim.port.schedule_follow_up("不死途", lambda: executed.append("不死途#1"))

        sim.scheduler.drain()

        self.assertEqual(
            executed,
            ["不死途#1", "绯英•千刃", "不死途#2", "爻光•欢愉技", "不死途#3"],
        )
        self.assertEqual(
            action_kinds,
            [
                ActionKind.FOLLOW_UP,
                ActionKind.SKILL,
                ActionKind.FOLLOW_UP,
                ActionKind.ELATION_SKILL,
                ActionKind.FOLLOW_UP,
            ],
        )

    def test_official_veritas_categories_and_kit_phases(self):
        """验证官方 Veritas 日志分类枚举与角色 Kit 预设的 follow_up_phase。"""
        self.assertEqual(SKILL_TYPE_BY_KIND[ActionKind.ELATION_SKILL], "ElationDamage")
        self.assertEqual(DamageType.from_tag("Break"), DamageType.BREAK)
        self.assertEqual(DamageType.from_tag("Elation"), DamageType.ELATION)

        self.assertEqual(AventurineKit.follow_up_phase, FollowUpPhase.FAST)
        self.assertEqual(ArcherKit.follow_up_phase, FollowUpPhase.FAST)
        self.assertEqual(RatioKit.follow_up_phase, FollowUpPhase.NORMAL)
        self.assertEqual(TopazKit.follow_up_phase, FollowUpPhase.NORMAL)
        self.assertEqual(DahliaKit.follow_up_phase, FollowUpPhase.SLOW)
        self.assertEqual(MozeKit.follow_up_phase, FollowUpPhase.SLOW)
        self.assertEqual(BronyaKit.follow_up_phase, FollowUpPhase.SLOW)
        self.assertEqual(ClaraKit.follow_up_phase, FollowUpPhase.COUNTER)
        self.assertEqual(YunliKit.follow_up_phase, FollowUpPhase.COUNTER)


if __name__ == "__main__":
    unittest.main()

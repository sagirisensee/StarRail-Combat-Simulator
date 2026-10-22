"""测试战斗模拟器手动交互接口与插队机制 (Manual Action Selection & Ultimate Interrupts)."""
import unittest
from simulator.core import TurnSimulator, Entity
from simulator.actions import ActionKind
from simulator.kits.registry import get_kit_class
from simulator.status import StatType


class TestManualMode(unittest.TestCase):
    def setUp(self):
        # 创建花火与黄泉
        sparkle_cls = get_kit_class(1306) # 花火
        acheron_cls = get_kit_class(1308) # 黄泉

        self.sparkle = Entity(name="花火", base_speed=160.0, base_atk=1500.0, max_hp=5000.0, current_hp=5000.0, is_enemy=False)
        self.sparkle.kit = sparkle_cls("花火", None, eidolon=0)

        self.acheron = Entity(name="黄泉", base_speed=130.0, base_atk=2500.0, max_hp=4000.0, current_hp=4000.0, is_enemy=False)
        self.acheron.kit = acheron_cls("黄泉", None, eidolon=0)

        self.boss = Entity(name="Boss", base_speed=100.0, base_atk=1000.0, max_hp=100000.0, current_hp=100000.0, max_toughness=100.0, current_toughness=100.0, is_enemy=True)

        self.sim = TurnSimulator(
            entities=[self.sparkle, self.acheron, self.boss],
            initial_sp=3,
            max_sp=7,
            use_techniques=False,
            auto_ult=False
        )

    def test_next_entity_and_action_override(self):
        # 1. 速度最快者是花火 (160 > 130 > 100)
        next_ent = self.sim.next_entity
        self.assertIsNotNone(next_ent)
        self.assertEqual(next_ent.name, "花火")

        # 2. 手动指定施放普攻 (即使默认是E，通过 action_override 强制为普攻)
        sp_before = self.sim.sp.current_sp
        actor = self.sim.step(action_override=ActionKind.BASIC)
        self.assertEqual(actor.name, "花火")
        # 普攻应恢复 1 点战技点
        self.assertEqual(self.sim.sp.current_sp, sp_before + 1)

    def test_skill_with_target_ids(self):
        # 花火施放战技，指定目标为黄泉
        self.sim.step(action_override=ActionKind.SKILL, target_ids=("黄泉",))
        # 战技消耗 1 SP (3 - 1 = 2)
        self.assertEqual(self.sim.sp.current_sp, 2)
        # 黄泉应被拉条 50%，立即提前行动
        self.assertLess(self.acheron.remaining_av, 40.0)

    def test_ultimate_interrupt(self):
        # 给黄泉充能 9 层残梦
        self.acheron.kit.slashed_dream = 9
        self.assertTrue(self.sim.can_cast_ultimate("黄泉"))

        ready = self.sim.get_ready_ultimates()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].name, "黄泉")

        # 施放终结技插队
        boss_hp_before = self.boss.current_hp
        ok = self.sim.cast_ultimate("黄泉")
        self.assertTrue(ok)
        self.assertLess(self.boss.current_hp, boss_hp_before)
        # 残梦层数清空
        self.assertEqual(self.acheron.kit.slashed_dream, 0)

    def test_advance_to_next_turn_and_execute_current_turn(self):
        # 跑道推进：让花火到达终点 (0.0 AV)
        actor = self.sim.advance_to_next_turn()
        self.assertEqual(actor.name, "花火")
        self.assertAlmostEqual(actor.remaining_av, 0.0, places=5)
        self.assertEqual(self.sim.current_turn_entity.name, "花火")

        # 在花火行动前，黄泉充能完毕，可以插队施放终结技
        self.acheron.kit.slashed_dream = 9
        ready = self.sim.get_ready_ultimates()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].name, "黄泉")

        # 插队施放终结技
        self.sim.cast_ultimate("黄泉")
        # 终结技施放后，花火依然停留在终点等待行动决策！
        self.assertEqual(self.sim.current_turn_entity.name, "花火")

        # 此时执行花火的行动：战技指定黄泉
        actor_done = self.sim.execute_current_turn(action_override=ActionKind.SKILL, target_ids=("黄泉",))
        self.assertEqual(actor_done.name, "花火")
        self.assertIsNone(self.sim.current_turn_entity)
        # 花火重置跑道距离
        self.assertEqual(self.sparkle.distance_remaining, 10000.0)

    def test_status_snapshot_and_atk_formula(self):
        # 验证 StatusManager.get_detailed_snapshot 与攻击力复合聚合公式
        from simulator.status import StatusInstance, Modifier, ModifierOp, DurationTiming

        # 初始快照
        snap = self.sim.status_mgr.get_detailed_snapshot(self.acheron)
        self.assertEqual(snap["name"], "黄泉")
        self.assertEqual(snap["base_atk"], 2500.0)
        self.assertEqual(snap["current_atk"], 2500.0)
        self.assertEqual(snap["atk_gain_pct"], 0.0)

        # 赋予 40% 攻击力 Buff
        atk_buff = StatusInstance(
            id="Atk_Buff_Test",
            name="攻击强化",
            source=self.sparkle,
            target=self.acheron,
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            modifiers=[Modifier(StatType.ATK_PERCENT, ModifierOp.PERCENT, 0.40)]
        )
        self.sim.status_mgr.add_status(atk_buff)

        # 验证计算后的实时攻击力: 2500 * (1 + 0.40) = 3500.0
        cur_atk = self.sim.status_mgr.calculate_stat("黄泉", self.acheron.base_atk, StatType.ATK_BASE)
        self.assertAlmostEqual(cur_atk, 3500.0)
        self.assertAlmostEqual(self.acheron.atk, 3500.0)

        # 检查快照
        snap_after = self.sim.status_mgr.get_detailed_snapshot(self.acheron)
        self.assertAlmostEqual(snap_after["current_atk"], 3500.0)
        self.assertAlmostEqual(snap_after["atk_gain_pct"], 0.40)
        self.assertEqual(len(snap_after["buffs"]), 1)
        self.assertEqual(snap_after["buffs"][0]["name"], "攻击强化")

    def test_infinite_hp_boss(self):
        # 验证无限木桩首领生命值扣减后依然不倒
        from simulate_battle import create_boss_entity
        inf_boss = create_boss_entity("木桩Boss", infinite_hp=True)
        self.assertEqual(inf_boss.max_hp, float("inf"))
        self.assertEqual(inf_boss.current_hp, float("inf"))
        self.assertTrue(inf_boss.is_infinite_hp)

        # 扣减 999999 伤害
        inf_boss.current_hp -= 999999.0
        self.assertEqual(inf_boss.current_hp, float("inf"))
        self.assertFalse(inf_boss.current_hp <= 0)


if __name__ == "__main__":
    unittest.main()

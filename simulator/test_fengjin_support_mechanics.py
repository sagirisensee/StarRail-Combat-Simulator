# coding: utf-8
"""风堇支援机制回归测试:
1. 小伊卡天赋【牵起晴空的手】的待治疗队列: 多名队友掉血时应逐个结算, 而非只记第一个;
2. 光锥《愿虹光永驻天空》蓄池: 装备者行动耗血蓄池, 忆灵攻击后释放为风堇名下的附加伤害。
"""
import unittest

from simulator.golden_diff import build_default_sim
from simulator.events import DamageAppliedEvent, HealAppliedEvent, TurnBeginEvent


def _run_until_ika(sim, max_steps=400):
    for _ in range(max_steps):
        sim.step()
        if sim.get_entity("小伊卡") is not None:
            return True
    return sim.get_entity("小伊卡") is not None


class TestIkaHealQueue(unittest.TestCase):
    def test_multiple_hurt_allies_all_get_talent_heals(self):
        sim = build_default_sim(av_budget=465.0)
        self.assertTrue(_run_until_ika(sim), "小伊卡应被召唤")
        fengjin_kit = sim.get_entity("风堇").kit
        ika_kit = getattr(fengjin_kit, "ika_kit", None)
        self.assertIsNotNone(ika_kit, "风堇套件应持有小伊卡套件")

        healed = []
        def on_heal(e: HealAppliedEvent):
            if e.source_name == "小伊卡":
                healed.append(e.target_name)
        sim.event_bus.subscribe(HealAppliedEvent, on_heal)

        # 两名队友先后掉血, 在同一结算点前都应被排队
        ika_kit.on_hp_lost("缇宝", 100.0, "test_hurt")
        ika_kit.on_hp_lost("长夜月", 100.0, "test_hurt")
        sim.event_bus.publish(TurnBeginEvent(av=0.0, cycle=0, actor_id="缇宝", actor_name="缇宝", speed=100.0))

        self.assertIn("缇宝", healed, "先掉血的队友应被小伊卡天赋治疗")
        self.assertIn("长夜月", healed, "后掉血的队友不应被单槽队列吞掉")


class TestRainbowsPool(unittest.TestCase):
    def test_pool_discharges_as_fengjin_additional_damage(self):
        sim = build_default_sim(av_budget=465.0)
        fengjin = sim.get_entity("风堇")
        handler = getattr(fengjin, "light_cone", None)
        self.assertIsNotNone(handler, "风堇应装备光锥")
        self.assertEqual(type(handler).__name__, "MayRainbowsRemainInTheSkyHandler")

        additional_hits = []
        def on_damage(e: DamageAppliedEvent):
            if e.attacker_name == "风堇" and getattr(e.damage_type, "value", "") == "Additional":
                additional_hits.append(e)
        sim.event_bus.subscribe(DamageAppliedEvent, on_damage)

        for _ in range(800):
            sim.step()
            if additional_hits:
                break
        self.assertTrue(additional_hits, "光锥蓄池应在小伊卡攻击后释放为风堇的附加伤害")
        for e in additional_hits:
            self.assertGreater(e.damage, 0.0)


if __name__ == "__main__":
    unittest.main()

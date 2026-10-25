# coding: utf-8
"""风堇忆灵小伊卡的实体化实现测试 (官方 1140901/1140903/140904)。"""
import unittest

from simulator.golden_diff import build_default_sim
from simulator.events import ActionExecuteEvent, DamageAppliedEvent


class TestIkaEntity(unittest.TestCase):
    def test_summon_creates_real_entity_and_ika_deals_servant_damage(self):
        sim = build_default_sim(av_budget=465.0)
        ika_damage = []
        ult_ids = []

        def on_damage(e: DamageAppliedEvent):
            if e.attacker_name == "小伊卡":
                ika_damage.append(e)

        def on_action(e: ActionExecuteEvent):
            if e.actor_name == "风堇" and getattr(e, "action_kind", None) is not None and str(e.action_kind) == "ActionKind.ULTIMATE":
                ult_ids.append(e.skill_config_id)

        sim.event_bus.subscribe(DamageAppliedEvent, on_damage)
        sim.event_bus.subscribe(ActionExecuteEvent, on_action)

        ika_seen = None
        for _ in range(240):
            sim.step()
            ent = sim.get_entity("小伊卡")
            if ent is not None and ika_seen is None:
                ika_seen = ent
            if ika_damage:
                break

        # 小伊卡被真正召唤为实体: 忆灵标记、主人归属、速度 0 (不进行动序列)
        self.assertIsNotNone(ika_seen, "风堇施放战技/终结技后小伊卡应作为实体被召唤")
        self.assertTrue(ika_seen.is_memosprite)
        self.assertEqual(ika_seen.master_name, "风堇")
        self.assertEqual(ika_seen.base_speed, 0.0)

        # 【雨过天晴】期间风堇施放技能后, 小伊卡应以 Servant 类型造成伤害 (累计治疗量基数)
        self.assertTrue(ika_damage, "小伊卡应在雨过天晴联动中打出忆灵技伤害")
        for e in ika_damage:
            self.assertEqual(e.damage_type.value, "Servant")
            self.assertGreater(e.damage, 0.0)


if __name__ == "__main__":
    unittest.main()

# coding: utf-8
"""缇宝终结技结界附加伤害 (140303) 与星魂 1 真实伤害、引擎真实伤害语义的测试。"""
import unittest
from types import SimpleNamespace

from simulator.damage import DamageCalculator, DamageRequest
from simulator.golden_diff import build_default_sim
from simulator.events import DamageAppliedEvent


class TestTrueDamageSemantics(unittest.TestCase):
    def test_true_damage_returns_base_value_only(self):
        attacker = SimpleNamespace(name="攻击者", base_atk=1000.0, max_hp=5000.0, crit_rate=1.0, crit_dmg=3.0)
        target = SimpleNamespace(name="目标", base_atk=0.0)
        req = DamageRequest(
            attacker=attacker, target=target,
            skill_multiplier=2.0, target_base_res=0.9,
            target_is_broken=False, is_true_damage=True,
        )
        bd = DamageCalculator.calculate(req)
        # 真实伤害: 不暴击、不吃防御/抗性/未破韧减伤, 基础区 2000 即最终伤害
        self.assertFalse(bd.is_crit)
        self.assertAlmostEqual(bd.final_damage, 2000.0)

    def test_normal_damage_is_reduced(self):
        attacker = SimpleNamespace(name="攻击者", base_atk=1000.0, max_hp=5000.0, crit_rate=0.0, crit_dmg=0.5)
        target = SimpleNamespace(name="目标", base_atk=0.0)
        req = DamageRequest(
            attacker=attacker, target=target,
            skill_multiplier=2.0, target_base_res=0.9,
            target_is_broken=False, is_true_damage=False,
        )
        bd = DamageCalculator.calculate(req)
        self.assertLess(bd.final_damage, 2000.0)


class TestTibaoZone(unittest.TestCase):
    def test_zone_produces_additional_and_true_damage(self):
        sim = build_default_sim(av_budget=465.0)
        hits = {"Additional": 0, "True": 0}

        def on_damage(e: DamageAppliedEvent):
            if e.attacker_name == "缇宝" and e.damage_type is not None:
                key = e.damage_type.value
                if key in hits:
                    hits[key] += 1

        sim.event_bus.subscribe(DamageAppliedEvent, on_damage)
        for _ in range(240):
            sim.step()
            if hits["Additional"] > 0 and hits["True"] > 0:
                break
        # 结界开启后队友攻击应触发缇宝的附加伤害; 账号缇宝为 E6, 星魂 1 真实伤害应同时出现
        self.assertGreater(hits["Additional"], 0, "结界期间应出现缇宝的 Additional 附加伤害")
        self.assertGreater(hits["True"], 0, "星魂 1 应产生缇宝的 True 真实伤害")


if __name__ == "__main__":
    unittest.main()

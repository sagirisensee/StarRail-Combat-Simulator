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

    def test_barrier_target_exclusion_from_true_base_and_zero_true_damage_emission(self):
        """验证: 屏障目标伤害严格不计入真伤池; 孤立屏障目标时真伤事件照发且数值严格为 0.0;
        小怪在场时仅小怪伤害折算真伤, 且全额轰击 Boss 屏障 (不吃减伤)。
        """
        from simulator.actions import ActionKind, DamageType
        from simulator.combat_port import CombatPort
        from simulator.core import Entity, TurnSimulator
        from simulator.kits.characters.tibao import TibaoKit

        tibao = Entity(name="缇宝", base_speed=120.0, max_hp=10000.0, current_hp=10000.0, base_atk=1000.0)
        ally = Entity(name="队友", base_speed=130.0, max_hp=8000.0, current_hp=8000.0, base_atk=1000.0)
        boss = Entity(name="首领", base_speed=100.0, max_hp=5000000.0, current_hp=5000000.0, is_enemy=True, barrier_guarded=True)
        boss.damage_reduction = 0.70
        minion = Entity(name="胚芽", base_speed=100.0, max_hp=1000000.0, current_hp=1000000.0, is_enemy=True, barrier_guarded=False)

        sim = TurnSimulator(entities=[tibao, ally, boss, minion])
        kit = TibaoKit("缇宝", sim.port, eidolon=6)
        tibao.kit = kit
        kit.on_battle_start()

        from simulator.combat_port import BuffSpec
        sim.port.upsert_status(BuffSpec(
            key="Tribbie_Ult_Zone_GuessWhoLivesHere",
            name="猜猜这里住着谁",
            source_id="缇宝",
            target_id="缇宝",
            modifiers=(),
            duration=3,
            category="other",
        ))
        kit._sync_glass_ball_hp()

        recorded_true_damages = []
        def on_damage(e: DamageAppliedEvent):
            if e.attacker_name == "缇宝" and e.damage_type == DamageType.TRUE:
                recorded_true_damages.append((e.target_name, float(e.damage)))

        sim.event_bus.subscribe(DamageAppliedEvent, on_damage)

        from simulator.events import ActionExecuteEvent, ActionEndEvent
        # 场景 1: 队友仅攻击带屏障的 Boss (无小怪参与)
        sim._action_seq = 101
        sim.event_bus.publish(ActionExecuteEvent(av=10.0, cycle=0, actor_id="队友", actor_name="队友", action_type="Skill", action_kind=ActionKind.SKILL, description="Skill", action_id=101))
        # 队友造成 100,000 直伤打在 Boss 身上
        sim.port.attack("队友", "首领", element="Physical", atk_multiplier=100.0, toughness_damage=0.0)
        sim.port.resolve_effects()
        sim.event_bus.publish(ActionEndEvent(av=10.0, cycle=0, actor_id="队友", actor_name="队友", action_kind=ActionKind.SKILL, action_id=101))

        # 断言 1: 屏障 Boss 伤害不入池, 真伤事件触发但数值为严格 0.0
        self.assertEqual(len(recorded_true_damages), 1)
        self.assertEqual(recorded_true_damages[0][0], "首领")
        self.assertEqual(recorded_true_damages[0][1], 0.0)

        # 场景 2: 队友 AoE 同时命中无屏障胚芽与带屏障 Boss
        recorded_true_damages.clear()
        sim._action_seq = 102
        sim.event_bus.publish(ActionExecuteEvent(av=20.0, cycle=0, actor_id="队友", actor_name="队友", action_type="Ultimate", action_kind=ActionKind.ULTIMATE, description="Ultimate", action_id=102))
        # 胚芽承受 200,000 直伤, Boss 承受 50,000 直伤
        sim.port.attack("队友", "胚芽", element="Physical", atk_multiplier=200.0, toughness_damage=0.0)
        sim.port.attack("队友", "首领", element="Physical", atk_multiplier=50.0, toughness_damage=0.0)
        sim.port.resolve_effects()
        sim.event_bus.publish(ActionEndEvent(av=20.0, cycle=0, actor_id="队友", actor_name="队友", action_kind=ActionKind.ULTIMATE, action_id=102))

        # 断言 2: 仅胚芽的伤害进入真伤池, 24% 折算打在 Boss 身上
        self.assertEqual(len(recorded_true_damages), 1)
        target_name, true_val = recorded_true_damages[0]
        self.assertEqual(target_name, "首领")
        # 胚芽承受的实际伤害 * 24%
        self.assertGreater(true_val, 0.0)
        # 严格验证真伤未被 Boss 的 0.70 damage_reduction 扣减 (仅来自胚芽受到的 105,230.77 直伤 * 24%)
        self.assertAlmostEqual(true_val, 25255.38, delta=1.0)


if __name__ == "__main__":
    unittest.main()

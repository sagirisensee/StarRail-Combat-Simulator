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


class TestIkaScatterWindowBudget(unittest.TestCase):
    """【牵起晴空的手】的触发窗口: 终结技开窗后按风堇回合计数共 3 回合
    (开窗簇计第 1 回合)——黄金日志第一场逐簇实测: 终结技 @47.9 开窗,
    常规施放仅 47.9/94.0/140.1 三簇触发, 第 4 簇 186.2 不触发;
    两场官方乌云乌云快走开均为 13 次。"""

    def test_scatter_window_counts_caster_turns(self):
        from simulator.actions import ActionContext, ActionKind

        sim = build_default_sim(av_budget=465.0)
        fengjin = sim.get_entity("风堇")
        kit = fengjin.kit
        scatters = []

        def on_action(e: ActionExecuteEvent):
            if getattr(e, "skill_config_id", 0) == 1140901:
                scatters.append(sim.current_av)

        sim.event_bus.subscribe(ActionExecuteEvent, on_action)

        def cast(kind, av):
            sim.current_av = av
            kit.execute(ActionContext(
                action_id=f"test-{kind}-{av}", actor_id="风堇",
                kind=kind, target_ids=(),
            ))
            sim.resolver.resolve_all()

        # 终结技开窗: 必触发一次
        cast(ActionKind.ULTIMATE, 0.0)
        self.assertEqual(len(scatters), 1)
        # 同簇 (ΔAV<=0.5) 紧随的常规施放: 实机该施放先于终结技落地, 不触发
        cast(ActionKind.SKILL, 0.2)
        self.assertEqual(len(scatters), 1)
        # 窗口内第 2、3 回合: 触发
        cast(ActionKind.SKILL, 46.0)
        cast(ActionKind.SKILL, 92.0)
        self.assertEqual(len(scatters), 3)
        # 第 4 回合: 窗口已闭, 不触发 (旧实现在此仍触发)
        cast(ActionKind.SKILL, 138.0)
        self.assertEqual(len(scatters), 3)
        # 再次终结技刷新窗口: 必触发, 且后续回合恢复触发
        cast(ActionKind.ULTIMATE, 200.0)
        self.assertEqual(len(scatters), 4)
        cast(ActionKind.SKILL, 246.0)
        self.assertEqual(len(scatters), 5)


class TestRainBuffWhiteBase(unittest.TestCase):
    """【雨过天晴】的生命加成口径 (黄金日志 MaxHP 样本逐项实证):
    百分比按目标白字生命结算 (忆灵按主人白字), 固定值 +600 原额;
    E1 的额外 +50% 作用于我方全体 (官方星魂原文), 合计 +80%。
    长夜月 (白字 2,589): 8,108 + 2,071 + 600 = 10,779 (官方样本 10,780);
    风堇本人 (白字 2,250): 5,114 + 1,800 + 600 = 7,514 (官方样本 7,515)。"""

    def test_rain_scales_from_white_base(self):
        from simulator.actions import ActionContext, ActionKind

        sim = build_default_sim(av_budget=465.0)
        fengjin = sim.get_entity("风堇")
        kit = fengjin.kit
        # 以终结技前后的增量断言, 与队内其他常驻生命加成 (如 +518 的前期
        # 分量, 官方长夜月样本 10,698/11,298 中同样存在) 互不干扰
        before_cyy = sim.port.max_hp("长夜月")
        before_fj = sim.port.max_hp("风堇")
        kit.execute(ActionContext(
            action_id="test-rain-ult", actor_id="风堇",
            kind=ActionKind.ULTIMATE, target_ids=(),
        ))
        sim.resolver.resolve_all()

        self.assertAlmostEqual(sim.port.max_hp("长夜月") - before_cyy, 0.80 * 2589 + 600, delta=3.0)
        self.assertAlmostEqual(sim.port.max_hp("风堇") - before_fj, 0.80 * 2250 + 600, delta=3.0)
        # 忆灵小伊卡: 百分比基数是主人的白字生命
        ika = sim.get_entity("小伊卡")
        self.assertIsNotNone(ika)
        self.assertAlmostEqual(ika.base_white_hp, 2250.0, delta=0.1)
        self.assertAlmostEqual(
            sim.port.max_hp("小伊卡") - ika.max_hp, 0.80 * 2250 + 600, delta=3.0)


if __name__ == "__main__":
    unittest.main()

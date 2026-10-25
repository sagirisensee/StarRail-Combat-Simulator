# coding: utf-8
"""golden_diff 对账工具的测试: 解析用仓库内的实机真值日志, 导出用真实模拟运行。"""
import os
import unittest

from simulator.golden_diff import (
    parse_golden_jsonl,
    build_default_sim,
    export_sim_sequence,
    diff_sequences,
    render_markdown,
)

GOLDEN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "battle_logs", "battle_20261025_131019.jsonl",
)


class TestParseGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seq = parse_golden_jsonl(GOLDEN_PATH)

    def test_turn_count_and_total(self):
        self.assertEqual(len(self.seq.turns), 84)
        self.assertAlmostEqual(self.seq.total_damage, 72409554.0, delta=1000.0)
        self.assertAlmostEqual(self.seq.final_av, 464.93, delta=0.5)

    def test_actor_type_aggregates_match_log(self):
        by_attacker = self.seq.damage_by_attacker()
        # 官方日志中长夜 (忆灵) 的 Servant 伤害记在长夜月 uid 下, 解析层拆分展示
        self.assertAlmostEqual(by_attacker["长夜月 (忆灵)"], 30145175.0, delta=1000.0)
        by_type = self.seq.damage_by_type()
        self.assertAlmostEqual(by_type["True"], 10815979.0, delta=1000.0)
        self.assertAlmostEqual(by_type["Servant"], 41141822.0, delta=1000.0)

    def test_enemy_roster_parsed(self):
        self.assertIn("堕神之血•亚婆离", self.seq.enemy_names.values())
        self.assertIn("千星戍卫", self.seq.enemy_names.values())


class TestExportSim(unittest.TestCase):
    def test_export_shape_and_attribution(self):
        sim = build_default_sim(av_budget=200.0)
        seq = export_sim_sequence(sim, av_budget=200.0)
        self.assertGreater(len(seq.turns), 5)
        self.assertGreater(seq.total_damage, 0.0)
        # 倒计时实体的结算不是技能施放, 不应出现在技能序列中
        for key in seq.skill_counts():
            self.assertNotIn("倒计时结算", key)
        # 长夜在开局即被召唤, 其 Servant 伤害应归因为「长夜月 (忆灵)」
        by_attacker = seq.damage_by_attacker()
        self.assertIn("长夜月 (忆灵)", by_attacker)

    def test_self_diff_is_zero_and_renders(self):
        golden = parse_golden_jsonl(GOLDEN_PATH)
        report = diff_sequences(golden, golden)
        for row in report["actors"]:
            if row["deviation_pct"] is not None:
                self.assertAlmostEqual(row["deviation_pct"], 0.0)
        md = render_markdown(report, "golden", "golden")
        self.assertIn("Golden Trace", md)


if __name__ == "__main__":
    unittest.main()


class TestStage30510021(unittest.TestCase):
    def test_wave2_and_sprouts_arrive(self):
        from simulator.golden_diff import build_stage_sim
        sim, director = build_stage_sim()
        names_at_start = {e.name for e in sim.entities}
        self.assertIn("千星戍卫A", names_at_start)
        self.assertNotIn("堕神之血•亚婆离", names_at_start)
        for _ in range(400):
            sim.step()
            director.after_step()
            if float(getattr(sim, "current_av", 0.0)) > 320.0:
                break
        self.assertTrue(director.wave2_started, "第一波全灭后应进入第二波")
        self.assertIsNotNone(sim.get_entity("堕神之血•亚婆离"))
        sprouts = [e for e in sim.entities if e.name.startswith("狂兽的胚芽")]
        self.assertGreaterEqual(len(sprouts), 2)


class TestStageDirectorReinforcements(unittest.TestCase):
    def test_sprout_reinforcements_continue_after_boss_hp_depleted(self):
        """亚婆离为无限生命近似: 其 HP 被打空后增援胚芽仍应按 AV 继续生成。

        回归背景: 导演的存活判定曾只看 current_hp, Boss HP 归零后
        sprout_waves_spawned 永远停在 0, 第二波全场只有首批 2 只胚芽,
        所有全体攻击的命中数系统性偏低。
        """
        from simulator.golden_diff import build_stage_sim
        sim, director = build_stage_sim()
        # 击杀第一波守卫, 触发第二波
        for name in ("千星戍卫A", "千星戍卫B", "千星戍卫C"):
            sim.get_entity(name).current_hp = 0.0
        sim.step()
        director.after_step()
        self.assertTrue(director.wave2_started)
        self.assertIsNotNone(sim.get_entity("狂兽的胚芽1"))
        # 模拟 Boss 生命被打空 (无限生命实体不死)
        boss = sim.get_entity("堕神之血•亚婆离")
        boss.current_hp = 0.0
        # 推进到第一批增援时点之后
        guard = 0
        while float(sim.current_av) < (director.wave2_av or 0.0) + 80.0 and guard < 400:
            sim.step()
            director.after_step()
            guard += 1
        self.assertGreaterEqual(director.sprout_waves_spawned, 1)
        self.assertIsNotNone(sim.get_entity("狂兽的胚芽3"))


class TestStageBossPhases(unittest.TestCase):
    def test_boss_two_pools_and_barrier_floor(self):
        """亚婆离两段血池: 一阶段打空转二阶段回满 12,779,117; 二阶段不低于 3,833,735。

        数值来源: 官方日志 uid 100039 的 CurrentHP 全序 (一阶段 6,389,558 打空、
        二阶段回满 12,779,117、最终冻结于其 30% = 3,833,735)。
        """
        from simulator.golden_diff import build_stage_sim
        from simulator.stage_30510021 import (
            BOSS_PHASE1_FLOOR,
            BOSS_PHASE1_FLOOR_RELEASE_AV,
            BOSS_PHASE2_FLOOR,
            BOSS_PHASE2_HP,
        )
        sim, director = build_stage_sim()
        for name in ("千星戍卫A", "千星戍卫B", "千星戍卫C"):
            sim.get_entity(name).current_hp = 0.0
        sim.step()
        director.after_step()
        boss = sim.get_entity("堕神之血•亚婆离")
        self.assertIsNotNone(boss)
        self.assertEqual(director.boss_phase, 1)
        # 一阶段屏障期内打到地板以下 -> 钳制在冻结值, 不转阶段
        boss.current_hp = BOSS_PHASE1_FLOOR - 100000.0
        director.after_step()
        self.assertEqual(director.boss_phase, 1)
        self.assertEqual(boss.current_hp, BOSS_PHASE1_FLOOR)
        # 屏障释放 (AV 越过脚本时点) 后一阶段可打空 -> 转入二阶段并回满
        sim.current_av = (director.wave2_av or 0.0) + BOSS_PHASE1_FLOOR_RELEASE_AV + 1.0
        boss.current_hp = 0.0
        director.after_step()
        self.assertEqual(director.boss_phase, 2)
        self.assertEqual(boss.current_hp, BOSS_PHASE2_HP)
        self.assertEqual(boss.max_hp, BOSS_PHASE2_HP)
        # 二阶段打到地板以下 -> 钳制在屏障地板
        boss.current_hp = BOSS_PHASE2_FLOOR - 500000.0
        director.after_step()
        self.assertEqual(boss.current_hp, BOSS_PHASE2_FLOOR)


class TestStageBossAI(unittest.TestCase):
    def test_boss_ai_alternates_aoe_and_heavy_single(self):
        """亚婆离攻击模组交替: 第 1 动全体群伤 (多名我方掉血), 第 2 动重单点 (仅 1 名掉血)。"""
        from simulator.golden_diff import build_stage_sim
        sim, director = build_stage_sim()
        for name in ("千星戍卫A", "千星戍卫B", "千星戍卫C"):
            sim.get_entity(name).current_hp = 0.0
        sim.step()
        director.after_step()
        boss = sim.get_entity("堕神之血•亚婆离")
        self.assertIsNotNone(boss.action_callback)

        def hp_snapshot():
            return {e.name: e.current_hp for e in sim.entities if not e.is_enemy}

        before = hp_snapshot()
        boss.action_callback(boss, sim.resolver, "EnemySkill")
        sim.resolver.resolve_all()
        after1 = hp_snapshot()
        hurt_aoe = [n for n in before if after1[n] < before[n]]
        self.assertGreaterEqual(len(hurt_aoe), 3)

        boss.action_callback(boss, sim.resolver, "EnemySkill")
        sim.resolver.resolve_all()
        after2 = hp_snapshot()
        hurt_single = [n for n in after1 if after2[n] < after1[n]]
        self.assertEqual(len(hurt_single), 1)


class TestTrueDamageBarrierSuppression(unittest.TestCase):
    def test_true_damage_zeroed_on_immune_target_only(self):
        """真实伤害免疫标记: 目标免疫时真实伤害归零, 普通伤害不受影响。

        依据: 官方日志屏障期打在亚婆离身上的真实伤害数值均为 0 (事件照常)。
        """
        from simulator.core import Entity
        from simulator.damage import DamageCalculator, DamageRequest
        attacker = Entity(name="攻击者", base_speed=100.0, base_atk=1000.0, max_hp=5000.0, current_hp=5000.0)
        target = Entity(name="目标", base_speed=100.0, base_atk=1000.0, max_hp=5000.0, current_hp=5000.0, is_enemy=True)
        req = DamageRequest(attacker=attacker, target=target, skill_multiplier=1.0, is_true_damage=True)
        self.assertGreater(DamageCalculator.calculate(req).final_damage, 0.0)
        target.true_damage_immune = True
        self.assertEqual(DamageCalculator.calculate(req).final_damage, 0.0)
        normal = DamageRequest(attacker=attacker, target=target, skill_multiplier=1.0)
        self.assertGreater(DamageCalculator.calculate(normal).final_damage, 0.0)

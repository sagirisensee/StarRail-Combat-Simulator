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

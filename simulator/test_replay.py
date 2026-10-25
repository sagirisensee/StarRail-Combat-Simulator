# coding: utf-8
"""回放对齐测试: 决策脚本提取的完整性与回放驱动的可运行性/偏离记录。"""
import os
import unittest

from simulator.golden_diff import (
    extract_decisions,
    run_replay,
    build_stage_sim,
    parse_golden_jsonl,
)

GOLDEN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "battle_logs", "battle_20261025_131019.jsonl",
)


class TestExtractDecisions(unittest.TestCase):
    def test_script_shape_matches_log(self):
        decisions = extract_decisions(GOLDEN_PATH)
        # 日志中玩家主动决策共 52 次: 回合行动 25 (战技 23 + 普攻 2), 终结技 27
        self.assertEqual(len(decisions), 52)
        self.assertEqual(sum(1 for d in decisions if d.kind == "ult"), 27)
        self.assertEqual(sum(1 for d in decisions if d.kind == "skill"), 23)
        self.assertEqual(sum(1 for d in decisions if d.kind == "basic"), 2)
        first = decisions[0]
        self.assertEqual((first.actor, first.skill_id), ("缇宝", 140303))
        # 脚本只包含四名玩家角色, 忆灵与被动触发不入脚本
        self.assertTrue(all(d.actor in ("长夜月", "缇宝", "知更鸟•晴歌", "风堇") for d in decisions))


class TestRunReplay(unittest.TestCase):
    def test_replay_runs_and_records_divergences(self):
        golden = parse_golden_jsonl(GOLDEN_PATH)
        decisions = extract_decisions(GOLDEN_PATH)
        sim, director = build_stage_sim()
        result = run_replay(sim, director, decisions, av_budget=golden.final_av)
        self.assertEqual(result.decisions_total, 52)
        self.assertGreater(result.turn_matched, 0)
        self.assertIsNotNone(result.sequence)
        self.assertGreater(len(result.sequence.turns), 0)
        # 以当前能量经济, 部分终结技无法按脚本时刻施放, 偏离必须被如实记录而非伪造对齐
        kinds = {d.kind for d in result.divergences}
        self.assertTrue(kinds <= {"turn_order", "ult_blocked", "sp_downgrade", "script_exhausted"})


if __name__ == "__main__":
    unittest.main()

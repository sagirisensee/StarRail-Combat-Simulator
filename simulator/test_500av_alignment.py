# coding: utf-8
"""500 AV 专项长程实机对账回归测试。

专项覆盖:
1. battle_20261103_105222.jsonl (长夜月 + 风堇 500 AV 极限长战)
2. battle_20261103_110541.jsonl (缇宝 + 风堇 500 AV 极限长战)
3. 自动化双人队成员解析与槽位对齐
4. 轨迹回放 100% 动作零偏离
5. 关键动作/复合大爆发超低容差对齐
6. 500 AV 全队宏观总伤阶段性工程回归护栏 (≤ 3.0%) 与精度目标 (0.20%)
"""
import math
import os
import unittest

from simulator.golden_diff import (
    attach_exact_crit_oracle,
    build_stage_sim,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_MOON_FENG = os.path.join(ROOT_DIR, "battle_logs", "battle_20261103_105222.jsonl")
LOG_TIBAO_FENG = os.path.join(ROOT_DIR, "battle_logs", "battle_20261103_110541.jsonl")

# 阶段性工程验收预算，不代表理论误差下限。
TEAM_500AV_MAX_REL_ERROR = 0.03

# 后续精度目标；当前宏观护栏通过不代表达到该目标。
TEAM_500AV_TARGET_REL_ERROR = 0.002


def assert_team_500av_damage_budget(
    case: unittest.TestCase,
    report,
    *,
    label: str,
) -> None:
    golden = float(report["golden_total_damage"])
    simulated = float(report["sim_total_damage"])

    case.assertTrue(
        math.isfinite(golden) and golden > 0.0,
        f"{label}: 实机总伤必须是有限正数，实际为 {golden!r}",
    )
    case.assertTrue(
        math.isfinite(simulated) and simulated >= 0.0,
        f"{label}: 模拟总伤必须是有限非负数，实际为 {simulated!r}",
    )

    signed_error = (simulated - golden) / golden

    case.assertLessEqual(
        abs(signed_error),
        TEAM_500AV_MAX_REL_ERROR,
        (
            f"{label}: 500 AV 全队总伤超出阶段性回归预算；"
            f"golden={golden:.3f}, simulated={simulated:.3f}, "
            f"signed_error={signed_error:+.4%}, "
            f"budget={TEAM_500AV_MAX_REL_ERROR:.2%}, "
            f"precision_target={TEAM_500AV_TARGET_REL_ERROR:.2%}"
        ),
    )


class Test500AVMoonFeng(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = parse_golden_jsonl(LOG_MOON_FENG)

    def test_log_metadata_and_duration(self):
        self.assertEqual(self.golden.final_av, 500.0)
        self.assertEqual(len(self.golden.turns), 63)
        self.assertAlmostEqual(self.golden.total_damage, 9597083.0, delta=1000.0)

    def test_auto_team_detection_preserves_standard_order(self):
        sim, _director = build_stage_sim(log_path=LOG_MOON_FENG)
        allies = [
            e.name for e in sim.entities
            if not e.is_enemy and not getattr(e, "is_countdown", False) and not getattr(e, "is_memosprite", False)
        ]
        self.assertEqual(allies, ["长夜月", "风堇"])

    def test_trajectory_replay_zero_divergences(self):
        sim, director = build_stage_sim(log_path=LOG_MOON_FENG)
        tl = extract_timeline(LOG_MOON_FENG)
        traj = run_trajectory_replay(sim, director, tl, av_budget=self.golden.final_av, log_path=LOG_MOON_FENG)
        self.assertEqual(traj.replay.turn_matched, 16)
        self.assertEqual(traj.replay.ult_matched, 9)
        self.assertEqual(len(traj.replay.divergences), 0)

    def test_exact_crit_500av_team_damage_regression_budget(self):
        sim, director = build_stage_sim(log_path=LOG_MOON_FENG)
        attach_exact_crit_oracle(sim, log_path=LOG_MOON_FENG)
        tl = extract_timeline(LOG_MOON_FENG)
        traj = run_trajectory_replay(sim, director, tl, av_budget=self.golden.final_av, log_path=LOG_MOON_FENG)
        rep = diff_sequences(self.golden, traj.replay.sequence)
        assert_team_500av_damage_budget(self, rep, label="长夜月队")


class Test500AVTibaoFeng(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = parse_golden_jsonl(LOG_TIBAO_FENG)

    def test_log_metadata_and_duration(self):
        self.assertEqual(self.golden.final_av, 500.0)
        self.assertEqual(len(self.golden.turns), 43)
        self.assertAlmostEqual(self.golden.total_damage, 10968446.0, delta=1000.0)

    def test_auto_team_detection_preserves_standard_order(self):
        sim, _director = build_stage_sim(log_path=LOG_TIBAO_FENG)
        allies = [
            e.name for e in sim.entities
            if not e.is_enemy and not getattr(e, "is_countdown", False) and not getattr(e, "is_memosprite", False)
        ]
        self.assertEqual(allies, ["缇宝", "风堇"])

    def test_trajectory_replay_zero_divergences(self):
        sim, director = build_stage_sim(log_path=LOG_TIBAO_FENG)
        tl = extract_timeline(LOG_TIBAO_FENG)
        traj = run_trajectory_replay(sim, director, tl, av_budget=self.golden.final_av, log_path=LOG_TIBAO_FENG)
        self.assertEqual(traj.replay.turn_matched, 12)
        self.assertEqual(traj.replay.ult_matched, 12)
        self.assertEqual(len(traj.replay.divergences), 0)

    def test_exact_crit_500av_team_damage_regression_budget(self):
        sim, director = build_stage_sim(log_path=LOG_TIBAO_FENG)
        attach_exact_crit_oracle(sim, log_path=LOG_TIBAO_FENG)
        tl = extract_timeline(LOG_TIBAO_FENG)
        traj = run_trajectory_replay(sim, director, tl, av_budget=self.golden.final_av, log_path=LOG_TIBAO_FENG)
        rep = diff_sequences(self.golden, traj.replay.sequence)
        assert_team_500av_damage_budget(self, rep, label="缇宝队")

    def test_per_action_burst_convergence_under_operation_replication(self):
        sim, director = build_stage_sim(log_path=LOG_TIBAO_FENG)
        attach_exact_crit_oracle(sim, log_path=LOG_TIBAO_FENG)
        tl = extract_timeline(LOG_TIBAO_FENG)
        traj = run_trajectory_replay(sim, director, tl, av_budget=self.golden.final_av, log_path=LOG_TIBAO_FENG)
        seq = traj.replay.sequence

        # 验证 AV 332.15 复合大爆发回合伤害偏差 < 0.05%
        g_332 = sum(d.damage for t in self.golden.turns if abs(t.av - 332.15) < 0.1 for d in t.damages)
        s_332 = sum(d.damage for t in seq.turns if abs(t.av - 332.15) < 0.1 for d in t.damages)
        self.assertGreater(g_332, 0.0, "实机 AV 332.15 窗口未找到伤害")
        self.assertGreater(s_332, 0.0, "模拟 AV 332.15 窗口未找到伤害")
        dev_332 = abs(s_332 - g_332) / g_332 * 100.0
        self.assertLess(dev_332, 0.05, f"AV 332.15 回合伤害偏差应 < 0.05%: 实测 {dev_332:.3f}%")

        # 验证 AV 216.21 爆发回合伤害偏差 < 2.20% (消除打错目标导致的 10% 众愿减免膨胀)
        g_216 = sum(d.damage for t in self.golden.turns if abs(t.av - 216.21) < 0.1 for d in t.damages)
        s_216 = sum(d.damage for t in seq.turns if abs(t.av - 216.21) < 0.1 for d in t.damages)
        self.assertGreater(g_216, 0.0, "实机 AV 216.21 窗口未找到伤害")
        self.assertGreater(s_216, 0.0, "模拟 AV 216.21 窗口未找到伤害")
        dev_216 = abs(s_216 - g_216) / g_216 * 100.0
        self.assertLess(dev_216, 2.20, f"AV 216.21 回合伤害偏差应 < 2.20%: 实测 {dev_216:.3f}%")


if __name__ == "__main__":
    unittest.main()

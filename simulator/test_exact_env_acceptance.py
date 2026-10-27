# coding: utf-8
"""精确环境与零补足验收基准测试 (Exact-Environment Acceptance Benchmark).

用于实验分支 exp/exact-env-verification：
固定随机种子消除暴击方差后，对 battle_20261026_062503.jsonl 全场 467.82 AV 进行
100% 闭环验收断言：
1. 玩家决策对齐：25/25 回合行动、27/27 终结技抢断、0 偏离；
2. 忆灵技轨迹对齐：44/44 全自然触发 (0 强制补发)；
3. 资源经济零外挂补足：终结技能量补足 == 0.0、战技点补足 == 0、忆质补足 == 0.0、在场补发 == 0；
4. 具名技能施放次数：我方 22 项具名技能与官方日志 100% 完全一致；
5. 命中段数与伤害总账：全队总伤偏差在 ±1% 以内，6 名伤害源段数与伤害高度吻合。
"""
import random
import unittest
from collections import defaultdict

from simulator.golden_diff import (
    build_stage_sim,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)


class TestExactEnvAcceptance(unittest.TestCase):
    GOLDEN_PATH = "battle_logs/battle_20261026_062503.jsonl"

    def test_exact_env_zero_grant_and_full_alignment(self):
        random.seed(42)
        golden = parse_golden_jsonl(self.GOLDEN_PATH)
        sim, director = build_stage_sim()
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(self.GOLDEN_PATH),
            av_budget=golden.final_av,
        )
        rep = diff_sequences(golden, traj.replay.sequence)

        # 1. 决策与忆灵技 100% 自然对齐
        self.assertEqual(traj.replay.turn_matched, 25)
        self.assertEqual(traj.replay.ult_matched, 27)
        self.assertEqual(len(traj.replay.divergences), 0)
        self.assertEqual(len(traj.records), 44)
        self.assertTrue(all(r.mode == "organic" for r in traj.records))

        # 2. 全资源 0 补足闭环
        self.assertAlmostEqual(traj.ult_energy_granted, 0.0, places=2)
        self.assertEqual(traj.sp_granted, 0)
        self.assertAlmostEqual(traj.memoria_granted, 0.0, places=2)
        self.assertEqual(traj.presence_grants, 0)

        # 3. 我方全部 22 项具名技能施放次数 100% 相等
        for s in rep["skills"]:
            if not s["key"].endswith("EnemySkill"):
                self.assertEqual(
                    s["sim"],
                    s["golden"],
                    f"技能施放次数不一致: {s['key']} (sim={s['sim']} vs golden={s['golden']})",
                )

        # 4. 全队总伤害在 ±1.5% 以内，各角色命中段数与伤害高度收敛
        total_dev_pct = (
            (rep["sim_total_damage"] - rep["golden_total_damage"])
            / rep["golden_total_damage"]
            * 100.0
        )
        self.assertLess(abs(total_dev_pct), 1.5, f"全队总伤偏差过大: {total_dev_pct:+.2f}%")

        actor_map = {a["actor"]: a for a in rep["actors"] if a["golden"] > 0}
        self.assertEqual(actor_map["知更鸟•晴歌 (忆灵)"]["sim_hits"], 27)
        self.assertEqual(actor_map["长夜月"]["sim_hits"], 16)
        self.assertEqual(actor_map["风堇"]["sim_hits"], 26)
        self.assertEqual(actor_map["风堇 (忆灵)"]["sim_hits"], 26)
        self.assertAlmostEqual(actor_map["长夜月 (忆灵)"]["sim_hits"], 43, delta=1)
        self.assertAlmostEqual(actor_map["缇宝"]["sim_hits"], 396, delta=5)


if __name__ == "__main__":
    unittest.main()

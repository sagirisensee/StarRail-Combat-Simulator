# coding: utf-8
"""双人 500 AV 长战 (105222 长夜月+风堇 / 110541 缇宝+风堇) 对账测试。"""

import os
import subprocess
import tempfile
import unittest

from simulator.golden_diff import (
    attach_exact_crit_oracle,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)
from simulator.stage_30510021_2p import build_stage_30510021_2p

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_500av_log(filename: str) -> str:
    local_path = os.path.join(ROOT_DIR, "battle_logs", filename)
    if os.path.exists(local_path):
        return local_path
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(tmp_path):
        raw = subprocess.check_output(
            ["git", "show", f"origin/feat/align-500av-20261103:battle_logs/{filename}"],
            cwd=ROOT_DIR,
        )
        with open(tmp_path, "wb") as f:
            f.write(raw)
    return tmp_path


class Test500AV2PAlignment(unittest.TestCase):
    """验证双人 500 AV 专用关卡适配器在两场官方日志上的轨迹与总伤对齐。"""

    def test_105222_moon_fengjin_500av(self) -> None:
        log_path = _resolve_500av_log("battle_20261103_105222.jsonl")
        g = parse_golden_jsonl(log_path)
        sim, director = build_stage_30510021_2p(log_path)
        attach_exact_crit_oracle(sim, log_path=log_path)
        traj = run_trajectory_replay(sim, director, extract_timeline(log_path), av_budget=g.final_av, log_path=log_path)
        rep = diff_sequences(g, traj.replay.sequence)
        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertLess(err, 0.02, f"105222 总伤偏差过大: {err:.2%}")

    def test_110541_tibao_fengjin_500av(self) -> None:
        log_path = _resolve_500av_log("battle_20261103_110541.jsonl")
        g = parse_golden_jsonl(log_path)
        sim, director = build_stage_30510021_2p(log_path)
        attach_exact_crit_oracle(sim, log_path=log_path)
        traj = run_trajectory_replay(sim, director, extract_timeline(log_path), av_budget=g.final_av, log_path=log_path)
        rep = diff_sequences(g, traj.replay.sequence)
        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertLess(err, 0.02, f"110541 总伤偏差过大: {err:.2%}")
        tibao = next(a for a in rep["actors"] if a["actor"] == "缇宝")
        self.assertLess(abs(tibao["deviation_pct"]), 0.5, f"缇宝 500 AV 偏差应 < 0.5%: {tibao['deviation_pct']:+.2f}%")


if __name__ == "__main__":
    unittest.main()

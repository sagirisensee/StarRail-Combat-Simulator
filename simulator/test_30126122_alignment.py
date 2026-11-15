# coding: utf-8
"""关卡 30126122 全插件对轴测试 (attach_exact_crit_oracle + run_trajectory_replay + 欢愉/阿哈特殊事件)。"""

import os
import unittest

from simulator.db.character_db import CharacterDB
from simulator.golden_diff import (
    attach_exact_crit_oracle,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)
from simulator.plugins.log_20261114_155925 import attach_log_20261114_155925_plugin
from simulator.plugins.log_20261114_184651 import attach_log_20261114_184651_plugin
from simulator.plugins.log_20261114_184845 import attach_log_20261114_184845_plugin
from simulator.plugins.log_20261114_204943 import attach_log_20261114_204943_plugin
from simulator.plugins.log_20261114_205144 import attach_log_20261114_205144_plugin
from simulator.plugins.log_20261114_220255 import attach_log_20261114_220255_plugin
from simulator.plugins.log_20261114_221208 import attach_log_20261114_221208_plugin
from simulator.plugins.log_20261114_222204 import attach_log_20261114_222204_plugin
from simulator.plugins.non_crit_ledgers import (
    OFFICIAL_20261114_220255_NON_CRITS,
    OFFICIAL_20261114_221208_NON_CRITS,
    OFFICIAL_20261114_222204_NON_CRITS,
)
from simulator.stage_30126122 import build_stage_30126122

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestStage30126122Alignment(unittest.TestCase):
    """验证关卡 30126122 挂载全套对轴插件后，轨迹、终结技、忆灵技与特殊事件的完整对齐。"""

    def test_20261114_155925_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_155925.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        team = [db.to_combat_entity("长夜月"), db.to_combat_entity("风堇")]
        sim, director = build_stage_30126122(team, technique_users=["长夜月", "风堇"])

        # 挂载精准暴击先知 + 本场日志专属随机事件插件 + 全轨迹回放对轴插件
        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=set())
        attach_log_20261114_155925_plugin(sim)
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(log_path),
            av_budget=g.final_av,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        # 1. 回合、终结技、战技点、忆质、忆灵技 100% 对齐
        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        # 2. 特殊事件验证: 3 次终结技 (长夜月x1 + 风堇x2) -> 15 笑点; 第 0/1 轮开始各触发 1 次阿哈 20 笑点额外回合(不消耗笑点)
        self.assertEqual(director.laugh_points, 15)
        self.assertGreaterEqual(len(director.aha_extra_turns), 2)
        self.assertGreater(director.aha_special_damage, 157737.0)
        for rec in director.aha_extra_turns:
            self.assertEqual(rec["fixed_laugh_points"], 20)
            self.assertEqual(rec["consumed_laugh_points"], 0)

        # 3. 伤害量级对齐确认 (总伤偏差 < 0.2%)
        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"30126122 总伤偏差过大: {err:.2%}")

    def test_20261114_184651_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_184651.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        team = [db.to_combat_entity("长夜月"), db.to_combat_entity("风堇")]
        sim, director = build_stage_30126122(team, technique_users=["长夜月", "风堇"])

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=set())
        attach_log_20261114_184651_plugin(sim)
        # 实机在 240.23 AV 施放「爱在虹光洒落时」瞬间即触发 OnBattleEnd（0 伤害结算）
        tl = [item for item in extract_timeline(log_path) if item.av < 240.22]
        traj = run_trajectory_replay(
            sim,
            director,
            tl,
            av_budget=240.0,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"184651 总伤偏差过大: {err:.2%}")

    def test_20261114_184845_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_184845.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        team = [db.to_combat_entity("缇宝"), db.to_combat_entity("风堇")]
        sim, director = build_stage_30126122(team, technique_users=["缇宝", "风堇"])

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=set())
        attach_log_20261114_184845_plugin(sim)
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(log_path),
            av_budget=g.final_av,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"184845 总伤偏差过大: {err:.2%}")

    def test_20261114_204943_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_204943.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        robin_profile = db.get_by_name("知更鸟•晴歌_爱如此刻永恒")
        robin_profile.name = "知更鸟•晴歌"
        team = [db.to_combat_entity("风堇"), db.to_combat_entity("知更鸟•晴歌_爱如此刻永恒")]
        sim, director = build_stage_30126122(team, technique_users=["风堇", "知更鸟•晴歌"])

        attach_exact_crit_oracle(sim, log_path=log_path)
        attach_log_20261114_204943_plugin(sim)
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(log_path),
            av_budget=g.final_av,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"204943 总伤偏差过大: {err:.2%}")

    def test_20261114_205144_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_205144.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        robin_profile = db.get_by_name("知更鸟•晴歌_爱如此刻永恒")
        robin_profile.name = "知更鸟•晴歌"
        team = [
            db.to_combat_entity("缇宝"),
            db.to_combat_entity("风堇"),
            db.to_combat_entity("知更鸟•晴歌_爱如此刻永恒"),
        ]
        sim, director = build_stage_30126122(team, technique_users=["缇宝", "风堇", "知更鸟•晴歌"])

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=set())
        attach_log_20261114_205144_plugin(sim)
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(log_path),
            av_budget=g.final_av,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"205144 总伤偏差过大: {err:.2%}")

    def test_20261114_220255_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_220255.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        rp = db.get_by_name("知更鸟•晴歌_爱如此刻永恒")
        rp.name = "知更鸟•晴歌"
        team = [
            db.to_combat_entity("缇宝"),
            db.to_combat_entity("风堇"),
            db.to_combat_entity(rp),
        ]
        sim, director = build_stage_30126122(team, technique_users=["缇宝", "风堇", "知更鸟•晴歌"])

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=OFFICIAL_20261114_220255_NON_CRITS)
        attach_log_20261114_220255_plugin(sim)
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(log_path),
            av_budget=g.final_av,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"220255 总伤偏差过大: {err:.2%}")

    def test_20261114_221208_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_221208.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        rp = db.get_by_name("知更鸟•晴歌_爱如此刻永恒")
        rp.name = "知更鸟•晴歌"
        team = [
            db.to_combat_entity("长夜月"),
            db.to_combat_entity("风堇"),
            db.to_combat_entity(rp),
        ]
        sim, director = build_stage_30126122(team, technique_users=["长夜月", "风堇", "知更鸟•晴歌"])

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=OFFICIAL_20261114_221208_NON_CRITS)
        attach_log_20261114_221208_plugin(sim)
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(log_path),
            av_budget=g.final_av,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"221208 总伤偏差过大: {err:.2%}")

    def test_20261114_222204_trajectory_and_elation_events(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_222204.jsonl")
        g = parse_golden_jsonl(log_path)

        db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        team = [
            db.to_combat_entity("缇宝"),
            db.to_combat_entity("长夜月"),
            db.to_combat_entity("风堇"),
        ]
        sim, director = build_stage_30126122(team, technique_users=["缇宝", "长夜月", "风堇"])

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=OFFICIAL_20261114_222204_NON_CRITS)
        attach_log_20261114_222204_plugin(sim)
        traj = run_trajectory_replay(
            sim,
            director,
            extract_timeline(log_path),
            av_budget=g.final_av,
            log_path=log_path,
        )
        rep = diff_sequences(g, traj.replay.sequence)

        self.assertEqual(traj.replay.turn_matched, traj.replay.turn_total)
        self.assertEqual(traj.replay.ult_matched, traj.replay.ult_total)
        self.assertEqual(traj.sp_granted, 0)
        self.assertEqual(traj.memoria_granted, 0.0)
        self.assertEqual(traj.presence_grants, 0)
        self.assertTrue(all(r.mode not in ("forced", "failed") for r in traj.records))

        err = abs(rep["sim_total_damage"] - rep["golden_total_damage"]) / rep["golden_total_damage"]
        self.assertLess(err, 0.002, f"222204 总伤偏差过大: {err:.2%}")


if __name__ == "__main__":
    unittest.main()

# coding: utf-8
"""通用 VM 对账生成器 (reconcile_generator.py) 单元测试。"""

import ast
import os
import tempfile
import unittest

from simulator.vm.reconcile_generator import (
    emit_alignment_test,
    extract_log_metadata,
    format_report,
    reconcile_log,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestReconcileGenerator(unittest.TestCase):
    def test_extract_metadata_multi_stage(self) -> None:
        m1 = extract_log_metadata(os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_155925.jsonl"))
        self.assertEqual(m1.stage_id, 30126122)
        self.assertEqual(m1.team_names, ["风堇", "长夜月"])
        self.assertGreater(len(m1.enemy_hits), 0)

        m4 = extract_log_metadata(os.path.join(ROOT_DIR, "battle_logs", "battle_20261115_041608.jsonl"))
        self.assertEqual(m4.stage_id, 30126122)
        self.assertEqual(len(m4.team_names), 4)
        self.assertEqual(m4.team_names[0], "风堇")

        m_new = extract_log_metadata(os.path.join(ROOT_DIR, "battle_logs", "battle_20261115_001502.jsonl"))
        self.assertEqual(m_new.stage_id, 1043176)
        self.assertGreaterEqual(len(m_new.team_names), 3)

    def test_reconcile_benchmark_155925_and_emit(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_155925.jsonl")
        rep = reconcile_log(log_path, force_data_driven=True, threshold=0.0001)
        self.assertEqual(rep.stage_mode, "data_driven(30126122)")
        self.assertEqual(rep.turn_matched, rep.turn_total)
        self.assertEqual(rep.ult_matched, rep.ult_total)
        self.assertLess(rep.total_err, 0.0001)
        self.assertLess(rep.max_turn_err, 0.0001)
        text = format_report(rep, threshold=0.0001)
        self.assertIn("battle_20261114_155925.jsonl", text)

        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "test_gen.py")
            written = emit_alignment_test(rep, output_path=out_path)
            self.assertEqual(written, out_path)
            with open(out_path, "r", encoding="utf-8") as fh:
                src = fh.read()
            ast.parse(src)

    def test_memosprite_deficit_inference_on_184651(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_184651.jsonl")
        rep = reconcile_log(
            log_path,
            use_existing_plugin=False,
            av_budget=155.0,
        )
        inferred = {(h.av, h.kind, h.targets) for h in rep.inferred_memosprite_hits}
        self.assertIn((75.76, "primary", ("小伊卡",)), inferred)
        self.assertIn((151.52, "blast", ("小伊卡",)), inferred)
        for av_ok in (48.05, 96.09, 144.14):
            td = next(t for t in rep.turn_diffs if abs(t.av - av_ok) < 0.05)
            self.assertLess(td.err, 0.002)

    def test_pure_auto_three_person_205144_sub_0_2_pct(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261114_205144.jsonl")
        rep = reconcile_log(log_path, use_existing_plugin=False)
        self.assertEqual(rep.turn_matched, rep.turn_total)
        self.assertEqual(rep.ult_matched, rep.ult_total)
        self.assertEqual(rep.forced_or_failed, 0)
        self.assertLess(rep.total_err, 0.002)
        self.assertLess(rep.max_turn_err, 0.002)


if __name__ == "__main__":
    unittest.main()

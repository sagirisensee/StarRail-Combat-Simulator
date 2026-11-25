# coding: utf-8
"""通用 VM 对账生成器 (reconcile_generator.py) 单元测试。"""

import ast
import os
import tempfile
import unittest

from simulator.db.character_db import CharacterDB
from simulator.vm.reconcile.metadata_post import (
    PlayerAttackRecord,
    reconstruct_shielded_aha_damages,
    resolve_player_and_servant_targets,
    resolve_team_roster,
)
from simulator.vm.reconcile.models import AhaTurnRecord, DEFAULT_CHAR_DB_PATH
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
            self.assertLess(td.err, 0.0001)


class TestMetadataPostProcessors(unittest.TestCase):
    def test_reconstruct_shielded_aha_damages_ratio_and_fallback(self) -> None:
        enemy_uid_map = {101: "A_1", 102: "A_2", 201: "B_1"}
        turns = [
            AhaTurnRecord(
                av=10.0,
                enemy_damages=[(101, 2000.0), (201, 1000.0)],
                ally_chip_hits=["爻光"],
                ally_sp_gain_counts={},
                lethal_enemy_uids=set(),
            ),
            AhaTurnRecord(
                av=20.0,
                enemy_damages=[(102, 0.0), (201, 1500.0)],
                ally_chip_hits=["爻光"],
                ally_sp_gain_counts={},
                lethal_enemy_uids=set(),
            ),
            AhaTurnRecord(
                av=30.0,
                enemy_damages=[(201, 0.0)],
                ally_chip_hits=["爻光"],
                ally_sp_gain_counts={},
                lethal_enemy_uids=set(),
            ),
        ]
        reconstruct_shielded_aha_damages(turns, enemy_uid_map)
        self.assertIn(102, turns[1].shielded_enemy_uids)
        self.assertAlmostEqual(dict(turns[1].enemy_damages)[102], 3000.0, places=3)
        self.assertIn(201, turns[2].shielded_enemy_uids)
        self.assertAlmostEqual(dict(turns[2].enemy_damages)[201], 1500.0, places=3)

    def test_resolve_player_and_servant_targets_single_and_aoe_primary(self) -> None:
        class _DummyMonster:
            def __init__(self, monster_id: int, name: str) -> None:
                self.monster_id = monster_id
                self.name = name

        class _DummyWave:
            def __init__(self) -> None:
                self.monsters = [_DummyMonster(8003060, "伪装体")]

        class _DummyStageSpec:
            waves = [_DummyWave()]

        enemy_uid_map = {101: "伪装体", 201: "金人", 202: "黑潮"}
        records = [
            PlayerAttackRecord(
                atk_key=(12.34, "记忆主"),
                is_servant=True,
                skill_id=1141301,
                skill_type="Servant",
                primary_dmg_hits=1,
                hit_euids=[101, 201],
                dmg_confirmed_euids=[101, 201],
                hit_dmgs={101: 999.0, 201: 5000.0},
                sp_euids=[201],
            ),
            PlayerAttackRecord(
                atk_key=(23.45, "长夜月"),
                is_servant=True,
                skill_id=1141307,
                skill_type="Servant",
                primary_dmg_hits=1,
                hit_euids=[201, 202],
                dmg_confirmed_euids=[201, 202],
                hit_dmgs={201: 4200.0, 202: 1800.0},
                sp_euids=[],
            ),
            PlayerAttackRecord(
                atk_key=(34.56, "星期日"),
                is_servant=False,
                skill_id=131301,
                skill_type="Normal",
                primary_dmg_hits=1,
                hit_euids=[202],
                dmg_confirmed_euids=[202],
                hit_dmgs={202: 1200.0},
                sp_euids=[],
            ),
        ]
        p_tgts, s_tgts = resolve_player_and_servant_targets(records, enemy_uid_map, _DummyStageSpec())
        self.assertEqual(p_tgts[(34.56, "星期日")], ["黑潮"])
        self.assertEqual(s_tgts[(12.34, "记忆主")], ["金人"])
        self.assertEqual(s_tgts[(23.45, "长夜月")], ["金人"])

    def test_resolve_team_roster_slot_ordering_and_override(self) -> None:
        db = CharacterDB().load(DEFAULT_CHAR_DB_PATH)
        uids_ord, names_ord = resolve_team_roster(
            db,
            seen_uids=[1407, 1409],
            inferred_slot_uids=[],
            aoe_heal_slot_uids=[1409, 1407],
            robin_s_init_ad=0.0,
            team_override=None,
        )
        self.assertEqual(uids_ord, [1409, 1407])
        self.assertEqual(names_ord[0], "风堇")

        uids_ov, names_ov = resolve_team_roster(
            db,
            seen_uids=[1407, 1409],
            inferred_slot_uids=[1409, 1407],
            aoe_heal_slot_uids=[],
            robin_s_init_ad=0.0,
            team_override=["长夜月", "风堇"],
        )
        self.assertEqual(names_ov, ["长夜月", "风堇"])
        self.assertEqual(len(uids_ov), 2)


if __name__ == "__main__":
    unittest.main()

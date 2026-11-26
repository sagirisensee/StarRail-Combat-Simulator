# coding: utf-8
"""关卡 1052096（周本・万色返空主，归寂 / 海瑟音 DoT 队）官方 ConfigAbility VM 全自动对账测试套件。"""

import os
import unittest

import pytest

from simulator.db.character_db import CharacterDB
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.models import DEFAULT_CHAR_DB_PATH
from simulator.vm.reconcile.runner import reconcile_log

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVM1052096Alignment(unittest.TestCase):
    """验证关卡 1052096（DoT 队实机录屏）在官方 VM + 纯机械提取 + Layer-4 DoT RNG 求解下的全量对齐（< 0.0001%）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = CharacterDB().load(DEFAULT_CHAR_DB_PATH)
        cls.loader = GameDataLoader()

    @pytest.mark.slow
    def test_vm_log_20261126_060855_alignment(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", "battle_20261126_060855.jsonl")
        rep = reconcile_log(
            log_path,
            db=self.db,
            loader=self.loader,
            force_data_driven=True,
            use_existing_plugin=False,
            threshold=1e-6,
            initial_energies={
                1217: 108.68882052414119,
                1005: 120.0,
                1410: 0.0,
                1307: 84.19999999762513,
            },
            technique_users=["黑天鹅"],
        )

        self.assertEqual(rep.turn_matched, rep.turn_total)
        self.assertEqual(rep.ult_matched, rep.ult_total)
        self.assertEqual(rep.sp_granted, 0)
        self.assertEqual(rep.ult_energy_granted, 0.0)
        self.assertEqual(rep.memoria_granted, 0.0)
        self.assertEqual(rep.presence_grants, 0)
        self.assertEqual(rep.forced_or_failed, 0)
        self.assertEqual(
            rep.enemy_hit_mismatches,
            [],
            f"1052096 存在敌方三方命中审计错配: {rep.enemy_hit_mismatches}",
        )
        self.assertLess(
            rep.total_err,
            1e-6,
            f"1052096 总伤误差过大: {rep.total_err:.6%} (GT={rep.golden_total_damage:.2f}, SIM={rep.sim_total_damage:.2f})",
        )
        self.assertLess(
            rep.max_turn_err,
            1e-6,
            f"1052096 最大单动误差过大: {rep.max_turn_err:.6%}",
        )
        self.assertTrue(rep.dot_diffs, "1052096 应产出逐 AV DoT 对比摘要")
        for d in rep.dot_diffs:
            self.assertLess(
                d.err,
                1e-6,
                f"1052096 AV={d.av:.2f} DoT 偏差过大: {d.err:.6%} (GT={d.gt_total:.2f}, SIM={d.sim_total:.2f})",
            )

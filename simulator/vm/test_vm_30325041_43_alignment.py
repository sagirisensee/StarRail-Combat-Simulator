# coding: utf-8
"""关卡 30325041-30325043（虚构叙事三期）官方 ConfigAbility VM 纯自动机械提取对账测试。"""

import os
import unittest
from typing import Optional, Tuple

import pytest

from simulator.db.character_db import CharacterDB
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.runner import reconcile_log

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVMStage30325041To43Alignment(unittest.TestCase):
    """验证虚构叙事 30325041/30325042/30325043 在官方 ConfigAbility VM + 纯机械日志提取（零手写插件）下的全量对齐与三方命中零错配。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        cls.loader = GameDataLoader()

    def _run_vm_case(
        self,
        tag: str,
        filename: str,
        *,
        extra_maze_buff_ids: Tuple[int, ...],
        av_budget: Optional[float] = None,
        turn_limit: float = 1e-6,
    ) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", filename)
        rep = reconcile_log(
            log_path,
            db=self.db,
            loader=self.loader,
            force_data_driven=True,
            use_existing_plugin=False,
            av_budget=av_budget,
            threshold=turn_limit,
            extra_maze_buff_ids=extra_maze_buff_ids,
        )

        self.assertEqual(rep.turn_matched, rep.turn_total)
        self.assertEqual(rep.ult_matched, rep.ult_total)
        self.assertEqual(rep.sp_granted, 0)
        self.assertEqual(rep.memoria_granted, 0.0)
        self.assertEqual(rep.presence_grants, 0)
        self.assertEqual(rep.forced_or_failed, 0)
        self.assertEqual(
            rep.enemy_hit_mismatches,
            [],
            f"{tag} 存在敌方三方命中审计错配: {rep.enemy_hit_mismatches}",
        )

        for td in rep.turn_diffs:
            self.assertLess(
                td.err,
                turn_limit,
                f"{tag} VM AV={td.av:.2f} 单动伤害偏差过大: {td.err:.6%} "
                f"(limit={turn_limit:.4%}, GT={td.gt_total:.2f}, SIM={td.sim_total:.2f})",
            )

    def test_vm_30325041_20261122_232910(self) -> None:
        self._run_vm_case(
            "30325041_232910",
            "battle_20261122_232910.jsonl",
            extra_maze_buff_ids=(3031359,),
        )

    @pytest.mark.slow
    def test_vm_30325042_20261122_233304(self) -> None:
        self._run_vm_case(
            "30325042_233304",
            "battle_20261122_233304.jsonl",
            extra_maze_buff_ids=(3031359, 3034013),
        )

    @pytest.mark.slow
    def test_vm_30325043_20261122_233727(self) -> None:
        self._run_vm_case(
            "30325043_233727",
            "battle_20261122_233727.jsonl",
            extra_maze_buff_ids=(3031359,),
        )


if __name__ == "__main__":
    unittest.main()

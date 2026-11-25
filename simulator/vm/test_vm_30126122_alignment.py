# coding: utf-8
"""关卡 30126122 官方 ConfigAbility VM 纯自动机械提取对账测试套件。"""

import os
import unittest
from typing import Optional, Sequence

import pytest

from simulator.db.character_db import CharacterDB
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.runner import reconcile_log

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 11 月实机录屏中知更鸟•晴歌佩戴光锥「爱如此刻永恒」(23052) 对应档案
_NOV_ROBIN_PROFILE = "知更鸟•晴歌_爱如此刻永恒"


class TestVMStage30126122Alignment(unittest.TestCase):
    """验证关卡 30126122 在官方 ConfigAbility VM + 纯机械日志提取（零手抄插件）下的轨迹、总伤与逐动对齐。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        cls.loader = GameDataLoader()

    def _run_vm_case(
        self,
        tag: str,
        filename: str,
        names: Sequence[str],
        *,
        av_budget: Optional[float] = None,
        max_tl_av: Optional[float] = None,
        turn_limit: float = 1e-6,
    ) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", filename)
        rep = reconcile_log(
            log_path,
            db=self.db,
            loader=self.loader,
            team_override=names,
            force_data_driven=True,
            use_existing_plugin=False,
            av_budget=av_budget,
            max_tl_av=max_tl_av,
            threshold=turn_limit,
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

    @pytest.mark.slow
    def test_vm_20261114_155925(self) -> None:
        self._run_vm_case("155925", "battle_20261114_155925.jsonl", ["风堇", "长夜月"])

    def test_vm_20261115_041608(self) -> None:
        self._run_vm_case("041608", "battle_20261115_041608.jsonl", ["风堇", "缇宝", "长夜月", _NOV_ROBIN_PROFILE])


if __name__ == "__main__":
    unittest.main()

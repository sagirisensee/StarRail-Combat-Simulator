# coding: utf-8
"""关卡 30510021（异象仲裁）官方 ConfigAbility VM 纯自动机械提取对账测试套件。"""

import os
import unittest
from typing import Optional, Sequence

import pytest

from simulator.db.character_db import CharacterDB
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.runner import reconcile_log

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 10 月录屏中「缇宝_旧」档案导出缺失 4 件套外圈遗器 124（哀歌覆国的诗人），测试夹具显式补齐
_OCT_30510021_LOADOUTS = {
    1403: (1403, 6, 23038, 5, [(124, 4), (319, 2)]),
}


class TestVMStage30510021Alignment(unittest.TestCase):
    """验证关卡 30510021（异象仲裁）在官方 ConfigAbility VM + 纯机械日志提取（零手抄插件）下的对齐（< 0.01%）。"""

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
        total_limit: float = 0.0001,
        turn_limit: float = 0.0001,
    ) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", filename)
        rep = reconcile_log(
            log_path,
            db=self.db,
            loader=self.loader,
            team_override=names,
            loadouts=_OCT_30510021_LOADOUTS,
            force_data_driven=True,
            use_existing_plugin=False,
            av_budget=av_budget,
            threshold=turn_limit,
        )

        self.assertEqual(rep.turn_matched, rep.turn_total)
        self.assertEqual(rep.ult_matched, rep.ult_total)
        self.assertEqual(rep.sp_granted, 0)
        self.assertEqual(rep.memoria_granted, 0.0)
        self.assertEqual(rep.presence_grants, 0)
        self.assertEqual(rep.forced_or_failed, 0)

        self.assertLess(
            rep.total_err,
            total_limit,
            f"{tag} VM 总伤偏差过大: {rep.total_err:.4%} (limit={total_limit:.2%})",
        )
        for td in rep.turn_diffs:
            self.assertLess(
                td.err,
                turn_limit,
                f"{tag} AV={td.av:.2f} 单动偏差过大: {td.err:.4%} "
                f"(GT={td.gt_total:.2f}, SIM={td.sim_total:.2f})",
            )

    def test_vm_log_20261025_131019_alignment(self) -> None:
        self._run_vm_case(
            "20261025_131019",
            "battle_20261025_131019.jsonl",
            ["风堇", "缇宝_旧", "长夜月", "知更鸟•晴歌"],
        )

    @pytest.mark.slow
    def test_vm_log_20261026_062503_alignment(self) -> None:
        self._run_vm_case(
            "20261026_062503",
            "battle_20261026_062503.jsonl",
            ["风堇", "缇宝_旧", "长夜月", "知更鸟•晴歌"],
        )


if __name__ == "__main__":
    unittest.main()

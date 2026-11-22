# coding: utf-8
"""关卡 30126121（步离战首•呼雷）官方 ConfigAbility VM 纯自动机械提取对账测试。"""

import os
import unittest
from typing import Optional, Sequence

from simulator.db.character_db import CharacterDB
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.runner import reconcile_log

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_NOV_ROBIN_PROFILE = "知更鸟•晴歌_爱如此刻永恒"


class TestVMStage30126121Alignment(unittest.TestCase):
    """验证关卡 30126121 在官方 ConfigAbility VM + 纯机械日志提取（零手写插件）下的全量对齐与三方命中零错配。"""

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

    def test_vm_20261122_023506(self) -> None:
        self._run_vm_case(
            "023506",
            "battle_20261122_023506.jsonl",
            ["风堇", _NOV_ROBIN_PROFILE, "缇宝", "长夜月"],
        )


if __name__ == "__main__":
    unittest.main()

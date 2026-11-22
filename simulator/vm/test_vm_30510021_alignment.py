# coding: utf-8
"""关卡 30510021（异象仲裁）官方 ConfigAbility VM 全插件对账测试套件。"""

import os
import unittest
from typing import Callable, Optional, Sequence, Set

from simulator.db.character_db import CharacterDB
from simulator.golden_diff import (
    attach_exact_crit_oracle,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)
from simulator.plugins.log_20261025_131019 import (
    NON_CRITS as OFFICIAL_20261025_131019_NON_CRITS,
    attach_log_20261025_131019_plugin,
)
from simulator.plugins.log_20261026_062503 import (
    NON_CRITS as OFFICIAL_20261026_062503_NON_CRITS,
    attach_log_20261026_062503_plugin,
)
from simulator.vm.factory import build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_sim_adapter import build_data_driven_stage

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVMStage30510021Alignment(unittest.TestCase):
    """验证关卡 30510021（异象仲裁）在官方 ConfigAbility VM 下的轨迹、总伤与逐动对齐（< 0.01%）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = CharacterDB().load(os.path.join(ROOT_DIR, "data", "character_db_export.json"))
        cls.loader = GameDataLoader()

    def _run_vm_case(
        self,
        tag: str,
        filename: str,
        names: Sequence[str],
        plugin_fn: Callable,
        *,
        non_crits: Optional[Set] = None,
        av_budget: Optional[float] = None,
        total_limit: float = 0.0001,
        turn_limit: float = 0.0001,
    ) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", filename)
        g = parse_golden_jsonl(log_path)
        team = build_vm_team(names, db=self.db, loader=self.loader)
        sim, director = build_data_driven_stage(30510021, team, technique_users=list(names))

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=non_crits or set())
        plugin_fn(sim)
        tl = extract_timeline(log_path)

        traj = run_trajectory_replay(
            sim,
            director,
            tl,
            av_budget=av_budget if av_budget is not None else g.final_av,
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
        self.assertLess(err, total_limit, f"{tag} VM 总伤偏差过大: {err:.4%} (limit={total_limit:.2%})")
        self._assert_per_turn_sub_0_01_pct(tag, g, traj, turn_limit=turn_limit)

    def _assert_per_turn_sub_0_01_pct(
        self, tag: str, g: object, traj: object, *, turn_limit: float = 0.0001
    ) -> None:
        gt_by_av: dict[float, float] = {}
        for t in g.turns:
            amt = sum(d.damage for d in t.damages if d.damage_type != "DoT")
            if amt > 0:
                av = round(t.av, 2)
                gt_by_av[av] = gt_by_av.get(av, 0.0) + amt
        sim_by_av: dict[float, float] = {}
        for t in traj.replay.sequence.turns:
            amt = sum(d.damage for d in t.damages if d.damage_type != "DoT")
            if amt > 0:
                av = round(t.av, 2)
                sim_by_av[av] = sim_by_av.get(av, 0.0) + amt
        self.assertEqual(set(sim_by_av.keys()), set(gt_by_av.keys()))
        for av, gt_dmg in sorted(gt_by_av.items()):
            sim_dmg = sim_by_av[av]
            turn_err = abs(sim_dmg - gt_dmg) / gt_dmg
            self.assertLess(
                turn_err,
                turn_limit,
                f"{tag} AV={av:.2f} 单动偏差过大: {turn_err:.4%} (GT={gt_dmg:.2f}, SIM={sim_dmg:.2f})",
            )

    def test_vm_log_20261025_131019_alignment(self) -> None:
        self._run_vm_case(
            "20261025_131019",
            "battle_20261025_131019.jsonl",
            ["风堇", "缇宝_旧", "长夜月", "知更鸟•晴歌_旧"],
            attach_log_20261025_131019_plugin,
            non_crits=OFFICIAL_20261025_131019_NON_CRITS,
        )

    def test_vm_log_20261026_062503_alignment(self) -> None:
        self._run_vm_case(
            "20261026_062503",
            "battle_20261026_062503.jsonl",
            ["风堇", "缇宝_旧", "长夜月", "知更鸟•晴歌_旧"],
            attach_log_20261026_062503_plugin,
            non_crits=OFFICIAL_20261026_062503_NON_CRITS,
        )


if __name__ == "__main__":
    unittest.main()

# coding: utf-8
"""关卡 30126122 官方 ConfigAbility VM 全插件对账测试套件。"""

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
from simulator.plugins.log_20261114_155925 import attach_log_20261114_155925_plugin
from simulator.plugins.log_20261114_184651 import attach_log_20261114_184651_plugin
from simulator.plugins.log_20261114_184845 import attach_log_20261114_184845_plugin
from simulator.plugins.log_20261114_204943 import attach_log_20261114_204943_plugin
from simulator.plugins.log_20261114_205144 import attach_log_20261114_205144_plugin
from simulator.plugins.log_20261114_220255 import attach_log_20261114_220255_plugin
from simulator.plugins.log_20261114_221208 import attach_log_20261114_221208_plugin
from simulator.plugins.log_20261114_222204 import attach_log_20261114_222204_plugin
from simulator.plugins.non_crit_ledgers import (
    OFFICIAL_20261114_204943_NON_CRITS,
    OFFICIAL_20261114_220255_NON_CRITS,
    OFFICIAL_20261114_221208_NON_CRITS,
    OFFICIAL_20261114_222204_NON_CRITS,
)
from simulator.stage_30126122 import build_stage_30126122
from simulator.vm.factory import build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_sim_adapter import build_data_driven_stage

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVMStage30126122Alignment(unittest.TestCase):
    """验证关卡 30126122 在官方 ConfigAbility VM 下的轨迹、总伤与逐动对齐。"""

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
        max_tl_av: Optional[float] = None,
        data_driven: bool = False,
        total_limit: float = 0.002,
        turn_limit: float = 0.002,
        ika_turn_limit: float = 0.02,
    ) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", filename)
        g = parse_golden_jsonl(log_path)
        team = build_vm_team(names, db=self.db, loader=self.loader)
        if data_driven:
            sim, director = build_data_driven_stage(30126122, team, technique_users=list(names))
        else:
            sim, director = build_stage_30126122(team, technique_users=list(names))

        attach_exact_crit_oracle(sim, log_path=log_path, non_crits=non_crits or set())
        plugin_fn(sim)
        tl = extract_timeline(log_path)
        if max_tl_av is not None:
            tl = [item for item in tl if item.av < max_tl_av]

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
        self._assert_per_turn_sub_0_2_pct(tag, g, traj, turn_limit=turn_limit, ika_turn_limit=ika_turn_limit)

    def _assert_per_turn_sub_0_2_pct(
        self, tag: str, g: object, traj: object, *, turn_limit: float = 0.002, ika_turn_limit: float = 0.002
    ) -> None:
        gt_by_av: dict[float, float] = {}
        ika_avs: set[float] = set()
        for t in g.turns:
            amt = sum(d.damage for d in t.damages if d.damage_type != "DoT")
            if amt > 0:
                av = round(t.av, 2)
                gt_by_av[av] = gt_by_av.get(av, 0.0) + amt
                if any(d.attacker in ("风堇", "风堇 (忆灵)", "小伊卡") for d in t.damages if d.damage_type != "DoT"):
                    ika_avs.add(av)
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
            limit = ika_turn_limit if av in ika_avs else turn_limit
            self.assertLess(
                turn_err,
                limit,
                f"{tag} VM AV={av:.2f} 单动伤害偏差过大: {turn_err:.4%} (limit={limit:.2%}, GT={gt_dmg:.2f}, SIM={sim_dmg:.2f})",
            )

    def test_vm_20261114_155925(self) -> None:
        self._run_vm_case(
            "155925",
            "battle_20261114_155925.jsonl",
            ["长夜月", "风堇"],
            attach_log_20261114_155925_plugin,
        )

    def test_vm_20261114_184651(self) -> None:
        self._run_vm_case(
            "184651",
            "battle_20261114_184651.jsonl",
            ["长夜月", "风堇"],
            attach_log_20261114_184651_plugin,
            av_budget=240.0,
            max_tl_av=240.22,
        )

    def test_vm_20261114_184845(self) -> None:
        self._run_vm_case(
            "184845",
            "battle_20261114_184845.jsonl",
            ["缇宝", "风堇"],
            attach_log_20261114_184845_plugin,
        )

    def test_vm_20261114_204943(self) -> None:
        self._run_vm_case(
            "204943",
            "battle_20261114_204943.jsonl",
            ["风堇", "知更鸟•晴歌"],
            attach_log_20261114_204943_plugin,
            non_crits=OFFICIAL_20261114_204943_NON_CRITS,
        )

    def test_vm_20261114_205144(self) -> None:
        self._run_vm_case(
            "205144",
            "battle_20261114_205144.jsonl",
            ["缇宝", "风堇", "知更鸟•晴歌"],
            attach_log_20261114_205144_plugin,
        )

    def test_vm_20261114_220255(self) -> None:
        self._run_vm_case(
            "220255",
            "battle_20261114_220255.jsonl",
            ["缇宝", "风堇", "知更鸟•晴歌"],
            attach_log_20261114_220255_plugin,
            non_crits=OFFICIAL_20261114_220255_NON_CRITS,
        )

    def test_vm_20261114_221208(self) -> None:
        self._run_vm_case(
            "221208",
            "battle_20261114_221208.jsonl",
            ["长夜月", "风堇", "知更鸟•晴歌"],
            attach_log_20261114_221208_plugin,
            non_crits=OFFICIAL_20261114_221208_NON_CRITS,
        )

    def test_vm_20261114_222204(self) -> None:
        self._run_vm_case(
            "222204",
            "battle_20261114_222204.jsonl",
            ["缇宝", "长夜月", "风堇"],
            attach_log_20261114_222204_plugin,
            non_crits=OFFICIAL_20261114_222204_NON_CRITS,
        )


if __name__ == "__main__":
    unittest.main()

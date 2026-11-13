# coding: utf-8
"""逐 AV 忆质 (Memoria) 与气氛值 (Vibes) 视频真值对齐测试。

对照实机视频 `Honkai  Star Rail 2026.10.26 - 06.24.52.01.mp4` 底部 HUD 与
`video_artifacts/harness_ground_truth.json` / `battle_logs/battle_20261026_062503.jsonl`，
对当前 `exp` 分支在全部 38 个独立 AV 节点及 14 次【迷梦，流失，如露】爆发瞬间的
长夜月【忆质】与知更鸟•晴歌【气氛值】进行逐点断言与差异锁定。
"""

import json
import os
import unittest
from typing import Any, Dict, List, Tuple

from simulator.actions import ActionKind
from simulator.events import ActionEndEvent, ActionExecuteEvent
from simulator.golden_diff import (
    attach_exact_crit_oracle,
    build_stage_sim,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_20261026 = os.path.join(ROOT_DIR, "battle_logs", "battle_20261026_062503.jsonl")
GROUND_TRUTH_JSON = os.path.join(ROOT_DIR, "video_artifacts", "harness_ground_truth.json")


# 38 个独立 AV 首动瞬间的视频真值与当前 exp 分支模拟器基线对照表:
# (av, first_action_idx, actor, sim_yizhi, video_yizhi, sim_vibes, video_vibes)
# 说明:
# - video_yizhi / video_vibes 采自视频底部 HUD 角色槽 3 (长夜月 X/16) 与槽 4 (知更鸟•晴歌 X/12)。
# - AV 0.00 (#1) 开局前 (t=12.00s) 视频为 yizhi=10, vibes=7；
# - AV 47.92 (#5) 处视频 t=35.05s 已过风堇专武回合初 1% 扣血 (yizhi 8->12)，ActionExecuteEvent 前为 8；
# - AV 107.91 (#19) 处视频 HUD 在动画后才恢复可见，此处记录 AV 107.91 晴空乐手出手前基线。
AV_YIZHI_VIBES_TABLE: List[Tuple[float, int, str, int, int, int, int]] = [
    (0.00, 1, "长夜", 10, 10, 7, 7),
    (45.04, 4, "知更鸟•晴歌", 8, 8, 11, 11),
    (47.92, 5, "风堇", 8, 8, 11, 11),
    (77.92, 13, "晴空乐手", 4, 4, 29, 29),
    (94.02, 14, "风堇", 7, 7, 32, 32),
    (97.86, 16, "长夜月", 18, 18, 35, 35),
    (105.57, 18, "缇宝", 4, 4, 39, 39),     # #18 结束后为 41 (视频 t=90.20s 含 #18 后置)
    (107.91, 19, "晴空乐手", 4, 4, 42, 42),  # #19 结束后为 44 -> 倒计时 22
    (137.90, 20, "晴空乐手", 7, 7, 23, 23),
    (140.12, 21, "风堇", 10, 10, 27, 27),
    (154.61, 23, "长夜月", 19, 19, 30, 30),
    (167.90, 29, "晴空乐手", 4, 4, 44, 44),  # 视频 t=128.77s 为 #29 血噬前 43，血噬+1 后为 44
    (186.22, 33, "风堇", 4, 4, 50, 50),
    (197.89, 34, "晴空乐手", 8, 8, 26, 26),
    (215.10, 35, "缇宝", 11, 11, 28, 28),    # 视频 t=150.03s 为 #35 血噬前 27，血噬+1 后为 28
    (224.64, 36, "长夜月", 15, 15, 31, 31),
    (227.88, 38, "晴空乐手", 4, 4, 34, 34),
    (232.31, 39, "风堇", 7, 7, 36, 36),
    (257.87, 43, "晴空乐手", 15, 15, 42, 42), # 视频 t=179.19s 为 #43 血噬前 41，血噬+1 后为 42
    (278.41, 44, "风堇", 15, 15, 23, 23),
    (281.39, 46, "长夜月", 32, 32, 26, 26),  # 视频 t=189.23s 为 #46 血噬前 25，血噬+1 后为 26
    (287.87, 54, "晴空乐手", 4, 4, 44, 44),
    (317.86, 55, "晴空乐手", 11, 11, 48, 48), # 视频 t=236.62s 为 AV 309.45 回血前 46，回血+1 与血噬+1 后为 48
    (324.51, 56, "风堇", 14, 14, 50, 50),
    (331.33, 58, "长夜月", 25, 25, 50, 50),
    (337.51, 61, "知更鸟•晴歌", 8, 8, 26, 26),
    (341.56, 67, "缇宝", 4, 4, 39, 40),
    (347.85, 68, "晴空乐手", 4, 4, 41, 41),
    (365.56, 69, "缇宝", 11, 11, 43, 44),
    (370.61, 70, "风堇", 11, 11, 47, 48),
    (377.84, 72, "晴空乐手", 18, 18, 50, 50),
    (407.84, 78, "晴空乐手", 8, 8, 26, 26),
    (416.70, 79, "风堇", 11, 11, 29, 29),
    (432.90, 84, "知更鸟•晴歌", 15, 15, 36, 36),
    (437.83, 90, "晴空乐手", 4, 4, 50, 50),
    (449.74, 91, "缇宝", 11, 11, 50, 50),
    (462.80, 92, "风堇", 15, 15, 50, 50),
    (467.82, 96, "晴空乐手", 29, 29, 50, 50),
]

# 14 次【迷梦，流失，如露】爆发消耗前的忆质峰值 (视频 HUD 实测 vs 当前 exp 分支):
# (burst_idx, action_idx, av, sim_peak_yizhi, video_peak_yizhi)
MEMORIA_BURST_PEAKS: List[Tuple[int, int, float, int, int]] = [
    (1, 3, 0.00, 31, 31),
    (2, 12, 47.92, 68, 70),
    (3, 17, 97.86, 56, 58),
    (4, 24, 154.61, 59, 61),
    (5, 28, 154.61, 36, 36),
    (6, 32, 167.90, 49, 51),
    (7, 37, 224.64, 53, 55),
    (8, 53, 281.39, 131, 139),
    (9, 60, 331.33, 70, 72),
    (10, 66, 337.51, 61, 67),
    (11, 75, 377.84, 39, 39),
    (12, 77, 377.84, 46, 48),
    (13, 86, 432.90, 75, 77),
    (14, 89, 432.90, 36, 36),
]


def _collect_av_yizhi_vibes() -> Dict[str, Any]:
    golden = parse_golden_jsonl(GOLDEN_20261026)
    with open(GROUND_TRUTH_JSON, encoding="utf-8") as f:
        gt = json.load(f)

    sim, director = build_stage_sim(log_path=GOLDEN_20261026)
    attach_exact_crit_oracle(sim, log_path=GOLDEN_20261026)

    cyy = next(e for e in sim.entities if e.name == "长夜月")
    robin = next(e for e in sim.entities if e.name == "知更鸟•晴歌")

    av_first: Dict[float, Tuple[int, str, int, int]] = {}
    bursts: List[Tuple[int, float, int]] = []
    peak_yizhi = 0

    orig_gain = cyy.kit.gain_yizhi

    def tracked_gain(*args: Any, **kwargs: Any) -> Any:
        nonlocal peak_yizhi
        res = orig_gain(*args, **kwargs)
        if cyy.kit.yizhi > peak_yizhi:
            peak_yizhi = cyy.kit.yizhi
        return res

    cyy.kit.gain_yizhi = tracked_gain

    act_idx = 0

    def on_event(e: Any) -> None:
        nonlocal act_idx, peak_yizhi
        if isinstance(e, ActionExecuteEvent):
            ent = next((x for x in sim.entities if x.name == e.actor_name), None)
            if ent is not None and (getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False)):
                return
            kind = getattr(e, "action_kind", None)
            if kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
                return
            raw_name = e.action_type or ""
            if raw_name == "FollowUpAttack" or not raw_name:
                return
            act_idx += 1
            av = round(float(sim.current_av), 2)
            if av not in av_first:
                av_first[av] = (act_idx, e.actor_name, int(cyy.kit.yizhi), int(robin.kit.vibes))
        elif isinstance(e, ActionEndEvent):
            if e.actor_name == "长夜" and "迷梦" in (e.action_type or ""):
                bursts.append((act_idx, round(float(sim.current_av), 2), int(peak_yizhi)))
                peak_yizhi = 0

    sim.event_bus.subscribe(ActionExecuteEvent, on_event)
    sim.event_bus.subscribe(ActionEndEvent, on_event)
    run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)

    gt_avs = sorted({round(float(x["av"]), 2) for x in gt})
    return {
        "gt_avs": gt_avs,
        "av_first": av_first,
        "bursts": bursts,
    }


class TestAVYizhiVibesAlignment(unittest.TestCase):
    """锁定 38 个 AV 的忆质与气氛值轨迹，以及 14 次迷梦爆发忆质峰值。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _collect_av_yizhi_vibes()

    def test_01_all_38_avs_present_and_aligned(self) -> None:
        """全部 38 个独立 AV 节点均应被精确命中 (误差 <= 0.02 AV)。"""
        sim_avs = sorted(self.data["av_first"].keys())
        gt_avs = self.data["gt_avs"]
        self.assertEqual(len(sim_avs), 38)
        self.assertEqual(len(gt_avs), 38)
        for s_av, g_av in zip(sim_avs, gt_avs):
            self.assertAlmostEqual(s_av, g_av, delta=0.02, msg=f"AV 节点错位: SIM={s_av} vs GT={g_av}")

    def test_02_per_av_start_yizhi_matches_exact_baseline(self) -> None:
        """全部 38 个 AV 首动瞬间的长夜月忆质层数应与实测基线 100% 精确一致。"""
        av_first = self.data["av_first"]
        for av, exp_idx, exp_actor, exp_sim_yz, exp_vid_yz, _, _ in AV_YIZHI_VIBES_TABLE:
            self.assertIn(av, av_first, f"缺失 AV {av}")
            act_idx, actor, sim_yz, _ = av_first[av]
            self.assertEqual(act_idx, exp_idx, f"AV {av} 首动序号不符")
            self.assertEqual(actor, exp_actor, f"AV {av} 首动角色不符")
            self.assertEqual(
                sim_yz,
                exp_sim_yz,
                f"AV {av} (#{act_idx} {actor}) 忆质偏差: SIM={sim_yz}, 预期={exp_sim_yz}",
            )
            self.assertEqual(
                sim_yz,
                exp_vid_yz,
                f"AV {av} (#{act_idx} {actor}) 首动前忆质应与视频 HUD 一致: SIM={sim_yz}, Video={exp_vid_yz}",
            )

    def test_03_memoria_burst_peaks_vs_video_ground_truth(self) -> None:
        """锁定 14 次【迷梦，流失，如露】爆发忆质峰值：全部 14 次爆发均与视频 HUD 真值 0 误差完全对齐。"""
        bursts = self.data["bursts"]
        self.assertEqual(len(bursts), 14)
        for (b_idx, exp_act, exp_av, _old_sim_pk, exp_vid_pk), (act_idx, av, sim_pk) in zip(
            MEMORIA_BURST_PEAKS, bursts
        ):
            self.assertEqual(act_idx, exp_act, f"Burst #{b_idx} 动作序号不符")
            self.assertAlmostEqual(av, exp_av, delta=0.02, msg=f"Burst #{b_idx} AV 不符")
            self.assertEqual(
                sim_pk,
                exp_vid_pk,
                f"Burst #{b_idx} (AV {av}) 忆质峰值应与视频 HUD 真值 0 误差对齐: SIM={sim_pk} != Video={exp_vid_pk}",
            )

    def test_04_per_av_vibes_alignment_vs_video_ground_truth(self) -> None:
        """逐 AV 校验知更鸟•晴歌气氛值 (vibes) 与视频真值对照，全部 38/38 AV 严格 0 误差对齐。"""
        av_first = self.data["av_first"]
        for av, exp_idx, exp_actor, _, _, _old_sim_vb, exp_vid_vb in AV_YIZHI_VIBES_TABLE:
            act_idx, actor, _, sim_vb = av_first[av]
            self.assertEqual(
                sim_vb,
                exp_vid_vb,
                f"AV {av} (#{act_idx} {actor}) 气氛值应与视频真值 0 误差对齐: SIM={sim_vb}, Video={exp_vid_vb}",
            )


if __name__ == "__main__":
    unittest.main()

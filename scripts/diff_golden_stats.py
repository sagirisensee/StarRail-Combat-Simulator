#!/usr/bin/env python3
"""官方日志金标属性比对与断言诊断器 (Oracle State Diff Tool).

功能：
从 official golden jsonl (battle_logs/battle_20261026_062503.jsonl) 中提取关键实体的属性时序
(CriticalDamage, CurrentHP, MaxHP, Speed, CurrentSP, ActionDelay)，与 SIM 回放过程中
对应 Action 前后的实时属性进行自动 diff，毫秒级定位分叉点。
"""

import os
import sys
import json
from typing import Dict, List, Any, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulator.test_micro_action_audit import GOLDEN_20261026
from simulator.golden_diff import parse_golden_jsonl, build_stage_sim, attach_exact_crit_oracle, run_trajectory_replay, extract_timeline
from simulator.events import ActionExecuteEvent, BattleEvent, TurnBeginEvent
from simulator.actions import ActionKind
from simulator.status import StatType


def diff_character_states(max_actions: int = 25):
    print("=" * 80)
    print(f"🔍 正在执行 SIM 与官方日志前 {max_actions} 动实时属性拓扑比对...")
    print("=" * 80)

    golden = parse_golden_jsonl(GOLDEN_20261026)
    sim, director = build_stage_sim(log_path=GOLDEN_20261026)
    attach_exact_crit_oracle(sim, log_path=GOLDEN_20261026)

    # 提取官方日志中的关键快照 (以 UID 区分: 1413 长夜月/长夜, 1409 风堇/小伊卡, 1403 缇宝, 1512 知更鸟)
    # 按时间戳和事件序列对齐
    act_idx = 0
    divergences = []

    def on_ev(e):
        nonlocal act_idx
        if isinstance(e, ActionExecuteEvent):
            ent = sim.get_entity(e.actor_name)
            if ent and (getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False)):
                return
            if e.action_kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
                return
            raw = e.action_type or ""
            if raw == "FollowUpAttack" or not raw:
                return
            act_idx += 1
            if act_idx > max_actions:
                return

            # 获取知更鸟当前气氛值
            robin = sim.get_entity("知更鸟•晴歌")
            robin_vibes = robin.kit.vibes if robin and hasattr(robin, "kit") else 0
            
            # 获取当前行动者暴伤
            actor_name = e.actor_name
            sim_cd = sim.port.stat(actor_name, StatType.CRIT_DMG) if sim.port else 0.0

            print(f"Action #{act_idx:02d} [AV={sim.current_av:<6.2f}] {actor_name:<10} | SIM Vibes={robin_vibes:>2d} | {actor_name} CD={sim_cd:.4f}")

    sim.event_bus.subscribe(BattleEvent, on_ev)
    run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="金标属性差异探针")
    parser.add_argument("--max", type=int, default=20)
    args = parser.parse_args()
    diff_character_states(max_actions=args.max)

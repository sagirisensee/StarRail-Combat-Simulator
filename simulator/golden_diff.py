# coding: utf-8
"""Golden Trace 真值对账工具 (Facade 入口)。

具体实现已按职责拆分至 ``simulator/golden/`` 子包：
- ``models.py``: 数据结构与常量
- ``parser.py``: Veritas JSONL 解析、事件流记录器、时间线与目标提取
- ``replay.py``: 回放对齐、轨迹回放与精准暴击先知
- ``diff.py``: 结构化 diff 与 Markdown 报告渲染

用法:
    python -m simulator.golden_diff <golden.jsonl> [--out report.md] [--trajectory]
"""

from __future__ import annotations

import argparse
import json
from typing import Optional, Sequence

from simulator.golden import (
    KNOWN_AVATAR_NAMES,
    SKILL_TYPE_BY_KIND,
    SPIRIT_TRAJECTORY_SKILLS,
    BattleSequence,
    DamageHit,
    Decision,
    Divergence,
    Grant,
    MasterRecord,
    ReplayResult,
    SequenceRecorder,
    SkillCast,
    TimelineItem,
    TrajectoryCast,
    TrajectoryRecord,
    TrajectoryResult,
    TurnRecord,
    _DECISION_KIND_BY_TYPE,
    _golden_actor_display,
    _load_known_avatar_names,
    _sim_player_actors,
    attach_exact_crit_oracle,
    diff_sequences,
    export_sim_sequence,
    extract_decisions,
    extract_enemy_activity,
    extract_enemy_target_plan,
    extract_player_target_plan,
    extract_timeline,
    extract_trajectory,
    parse_golden_jsonl,
    render_enemy_activity_markdown,
    render_markdown,
    render_replay_markdown,
    render_trajectory_markdown,
    resolve_non_crits,
    run_replay,
    run_trajectory_replay,
)

__all__ = [
    "KNOWN_AVATAR_NAMES",
    "SKILL_TYPE_BY_KIND",
    "SPIRIT_TRAJECTORY_SKILLS",
    "BattleSequence",
    "DamageHit",
    "Decision",
    "Divergence",
    "Grant",
    "MasterRecord",
    "ReplayResult",
    "SequenceRecorder",
    "SkillCast",
    "TimelineItem",
    "TrajectoryCast",
    "TrajectoryRecord",
    "TrajectoryResult",
    "TurnRecord",
    "parse_golden_jsonl",
    "export_sim_sequence",
    "extract_decisions",
    "extract_enemy_activity",
    "extract_trajectory",
    "extract_player_target_plan",
    "extract_timeline",
    "extract_enemy_target_plan",
    "diff_sequences",
    "render_markdown",
    "render_replay_markdown",
    "render_enemy_activity_markdown",
    "render_trajectory_markdown",
    "resolve_non_crits",
    "attach_exact_crit_oracle",
    "run_replay",
    "run_trajectory_replay",
    "build_default_sim",
    "build_stage_sim",
    "main",
]


def build_default_sim(av_budget: float):
    """构造与官方日志同阵容的对照模拟 (敌方为单体高耐久桩, 仅作序列/分类对照)。"""
    from simulator.core import Entity, TurnSimulator
    from simulator.db.character_db import CharacterDB
    from simulator.vm.factory import build_vm_team

    db = CharacterDB().load("data/character_db_export.json")
    team = build_vm_team(["长夜月", "缇宝", "知更鸟•晴歌", "风堇"], db=db)
    boss = Entity(
        name="木桩首领",
        base_speed=140.0,
        max_hp=6389558.0,
        current_hp=6389558.0,
        weaknesses=["Ice", "Wind", "Fire", "Imaginary", "Quantum", "Physical", "Thunder"],
        is_enemy=True,
    )
    boss.is_infinite_hp = True
    return TurnSimulator(entities=team + [boss], use_techniques=True, auto_ult=True)


def build_stage_sim(
    team_members: Optional[Sequence[str]] = None,
    log_path: Optional[str] = None,
    technique_users: Optional[Sequence[str]] = None,
    stage_id: int = 30510021,
):
    """基于纯数据驱动 VM 底座构造指定关卡的对照场景, 返回 (sim, director)。"""
    from simulator.db.character_db import CharacterDB
    from simulator.vm.factory import build_vm_team
    from simulator.vm.stage_sim_adapter import build_data_driven_stage

    standard_team = ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]
    if log_path is not None:
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("event") == "OnBattleBegin":
                        sid = int((d.get("data") or {}).get("stage_id") or 0)
                        if sid > 0:
                            stage_id = sid
                        break
        except Exception:
            pass

    if team_members is None:
        if log_path is not None:
            detected_uids = set()
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        ev = d.get("event")
                        data = d.get("data", {})
                        if ev == "OnUseSkill":
                            uid = data.get("avatar", {}).get("uid")
                            if uid:
                                detected_uids.add(uid)
                        elif ev == "OnDamage":
                            uid = data.get("attacker", {}).get("uid")
                            if uid:
                                detected_uids.add(uid)
            except Exception:
                pass
            detected_names = {KNOWN_AVATAR_NAMES[u] for u in detected_uids if u in KNOWN_AVATAR_NAMES}
            if detected_names:
                team_members = [n for n in standard_team if n in detected_names]
        if not team_members:
            team_members = standard_team

    if technique_users is None:
        technique_users = list(team_members)

    db = CharacterDB().load("data/character_db_export.json")
    team = build_vm_team(list(team_members), db=db)
    return build_data_driven_stage(stage_id, team, technique_users=list(technique_users))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Golden Trace 真值对账")
    parser.add_argument("golden", help="官方 Veritas JSONL 路径")
    parser.add_argument("--out", default="", help="报告输出路径 (默认打印到终端)")
    parser.add_argument("--replay", action="store_true", help="回放对齐模式: 按日志中的玩家决策脚本驱动模拟")
    parser.add_argument("--force", action="store_true", help="强制回放: 决策钉死, 能量/战技点按缺口补足并记台账 (隐含 --replay)")
    parser.add_argument("--trajectory", action="store_true", help="轨迹回放: 在强制回放之上再钉死忆灵技轨迹, 缺口补足记账 (隐含 --force)")
    parser.add_argument("--align-crit", action="store_true", help="暴击真值对齐模式: 100%% 对齐实战暴击与未暴击段数")
    args = parser.parse_args(argv)

    golden = parse_golden_jsonl(args.golden)
    sim, director = build_stage_sim(log_path=args.golden)
    if args.align_crit:
        attach_exact_crit_oracle(sim, log_path=args.golden)
    replay_md = ""
    trajectory_md = ""
    if args.trajectory:
        traj = run_trajectory_replay(sim, director, extract_timeline(args.golden), av_budget=golden.final_av, log_path=args.golden)
        replay = traj.replay
        sim_seq = replay.sequence
        replay_md = render_replay_markdown(replay)
        trajectory_md = render_trajectory_markdown(traj)
        sim_label = f"数据驱动关卡 {director.stage_id} + 官方轨迹回放驱动 (决策+忆灵技钉死)"
    elif args.replay or args.force:
        decisions = extract_decisions(args.golden)
        replay = run_replay(sim, director, decisions, av_budget=golden.final_av, force=args.force)
        sim_seq = replay.sequence
        replay_md = render_replay_markdown(replay)
        sim_label = f"数据驱动关卡 {director.stage_id} + 官方决策脚本回放驱动" + (" (强制钉死)" if args.force else "")
    else:
        sim_seq = export_sim_sequence(sim, av_budget=golden.final_av, director=director)
        sim_label = f"数据驱动关卡 {director.stage_id}"
    report = diff_sequences(golden, sim_seq)
    md = render_markdown(report, args.golden, sim_label, replay_md=replay_md)
    md += "\n" + render_enemy_activity_markdown(extract_enemy_activity(args.golden))
    if trajectory_md:
        md += "\n" + trajectory_md
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"报告已写入 {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

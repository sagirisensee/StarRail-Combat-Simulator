# coding: utf-8
"""快速诊断工具：并排对照官方战斗日志 (GT) 与 ConfigAbility VM (SIM) 的逐回合差异与事件时间线。

用法示例:
  # 1) 汇总单场或多场日志的对账误差与首处分叉
  python scripts/diff_log_turn.py battle_logs/battle_20261122_232910.jsonl --extra-maze-buffs 3031359
  python scripts/diff_log_turn.py battle_logs/battle_20261122_233304.jsonl battle_logs/battle_20261122_233727.jsonl

  # 2) 按指定 AV 切片并打印 GT vs SIM 并排时间线（默认自动以 av + 0.5 早停以加速调试）
  python scripts/diff_log_turn.py battle_logs/battle_20261122_232910.jsonl --extra-maze-buffs 3031359 --av 47.87 --timeline
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulator.db.character_db import CharacterDB
from simulator.events import (
    ActionExecuteEvent,
    BattleEvent,
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    TurnBeginEvent,
)
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.metadata import extract_log_metadata
from simulator.vm.reconcile.models import DEFAULT_CHAR_DB_PATH, LogMetadata, ReconcileReport
from simulator.vm.reconcile.runner import reconcile_log


def _parse_extra_buffs(raw: Optional[str]) -> Tuple[int, ...]:
    if not raw:
        return ()
    return tuple(int(x.strip()) for x in raw.split(",") if x.strip())


def _print_summary(
    log_path: str,
    meta: LogMetadata,
    extra_buffs: Tuple[int, ...],
    r: ReconcileReport,
    *,
    threshold: float,
) -> None:
    print(f"=== {log_path} | stage={meta.stage_id} | team={meta.team_names} | extra_buffs={extra_buffs} ===")
    print(
        f"  turn={r.turn_matched}/{r.turn_total}  ult={r.ult_matched}/{r.ult_total}  "
        f"sp={r.sp_granted}  mem={r.memoria_granted}  pres={r.presence_grants}  forced={r.forced_or_failed}"
    )
    print(f"  total_err={r.total_err * 100:.6f}%  max_turn_err={r.max_turn_err * 100:.6f}%")
    if r.enemy_hit_mismatches:
        print(f"  enemy_hit_mismatches ({len(r.enemy_hit_mismatches)}):")
        for m in r.enemy_hit_mismatches:
            print(f"    av={m.av:.2f} {m.enemy_name} log={m.log_hits} sim={m.sim_hits} skill={m.skill_key}")
    else:
        print("  enemy_hit_mismatches: []")
    for td in r.turn_diffs:
        mark = "OK " if td.err <= threshold else "ERR"
        print(f"  [{mark}] av={td.av:6.2f}  gt={td.gt_total:13.2f}  sim={td.sim_total:13.2f}  err={td.err * 100:9.6f}%  atk={td.attackers}")
        if td.err > threshold:
            for k, (gv, sv) in td.breakdown.items():
                ratio_s = f"{sv / gv:.6f}x" if gv > 0 else ("inf" if sv > 0 else "1.0x")
                print(f"        {k:<22s} gt={gv:13.2f}  sim={sv:13.2f}  sim/gt={ratio_s}")


def _print_gt_timeline(log_path: str, target_av: float, window: float) -> None:
    print(f"\n--- GT TIMELINE ({log_path}, av={target_av:.2f} +- {window:.2f}) ---")
    uid_names: Dict[int, str] = {}
    cur_av = 0.0
    tot_dmg = 0.0
    lines = pathlib.Path(log_path).read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines, 1):
        rec = json.loads(line)
        ev = rec.get("event")
        d = rec.get("data", {})
        if ev == "OnInitializeEnemy":
            en = d.get("enemy", {})
            uid = int(en.get("uid", 0) or 0)
            uid_names[uid] = str(en.get("name", f"UID_{uid}"))
        elif ev == "OnBattleBegin":
            for av_info in d.get("avatars", []):
                uid_names[int(av_info.get("uid", 0) or 0)] = str(av_info.get("name", ""))
        if ev == "OnTurnBegin":
            cur_av = float(d.get("action_value", cur_av))
        if abs(cur_av - target_av) > window:
            continue
        if ev == "OnTurnBegin":
            owner = d.get("turn_owner") or {}
            uid = int(owner.get("uid", 0) or 0)
            print(f"  L{idx:4d} [TURN ] av={cur_av:6.2f} team={owner.get('team')} uid={uid} ({uid_names.get(uid, '')})")
        elif ev == "OnInitializeEnemy":
            en = d.get("enemy", {})
            uid = int(en.get("uid", 0) or 0)
            hp = ((en.get("base_stats") or {}).get("properties") or {}).get("MaxHP", 0.0)
            print(f"  L{idx:4d} [SPAWN] av={cur_av:6.2f} uid={uid} {en.get('name')} max_hp={hp:.2f}")
        elif ev == "OnCast":
            caster = d.get("caster", {})
            sk = d.get("skill", {})
            uid = int(caster.get("uid", 0) or 0)
            print(f"  L{idx:4d} [CAST ] av={cur_av:6.2f} uid={uid} ({uid_names.get(uid, '')}) skill={sk.get('name') or sk.get('id')}")
        elif ev == "OnUseSkill":
            avt = d.get("avatar", {})
            sk = d.get("skill", {})
            uid = int(avt.get("uid", 0) or 0)
            sname = sk.get("name") or sk.get("skill_config_id")
            sid = sk.get("skill_config_id", "")
            stype = sk.get("type", "")
            print(f"  L{idx:4d} [SKILL] av={cur_av:6.2f} uid={uid} ({uid_names.get(uid, '')}) skill={sname} ({sid}) [{stype}]")
        elif ev == "OnDamage":
            att = d.get("attacker", {})
            uid = int(att.get("uid", 0) or 0)
            dmg = float(d.get("damage", 0.0) or 0.0)
            ov = float(d.get("overkill_damage", 0.0) or 0.0)
            tp = str(d.get("type", ""))
            if att.get("team") == "Player" and tp != "DoT":
                tot_dmg += dmg
            print(f"  L{idx:4d} [DMG  ] av={cur_av:6.2f} {uid_names.get(uid, uid)}:{tp:<10s} dmg={dmg:12.2f} overkill={ov:10.2f}")
        elif ev == "OnStatChange":
            prop = d.get("property", {})
            ptype = prop.get("type")
            pval = float(prop.get("value", 0.0) or 0.0)
            ent = d.get("entity", {})
            uid = int(ent.get("uid", 0) or 0)
            if ent.get("team") == "Enemy" and ptype == "CurrentHP" and pval == 0.0:
                print(f"  L{idx:4d} [DEAD ] av={cur_av:6.2f} uid={uid} ({uid_names.get(uid, '')})")
            elif ent.get("team") == "Enemy" and ptype == "ActionDelay" and abs(pval) < 1e-6:
                print(f"  L{idx:4d} [AA=0 ] av={cur_av:6.2f} uid={uid} ({uid_names.get(uid, '')})")
    print(f"  => GT window player non-DoT total = {tot_dmg:,.2f}")


def _attach_sim_timeline_recorder(
    sim: Any,
    target_av: float,
    window: float,
    lines_out: List[str],
    tot_dmg_out: List[float],
) -> None:
    seen_enemies = {e.name for e in sim.entities if getattr(e, "is_enemy", False)}

    def _check_spawns(av_val: float) -> None:
        if abs(av_val - target_av) > window:
            seen_enemies.update(e.name for e in sim.entities if getattr(e, "is_enemy", False))
            return
        for e in sim.entities:
            if getattr(e, "is_enemy", False) and e.name not in seen_enemies:
                seen_enemies.add(e.name)
                lines_out.append(
                    f"  [SPAWN] av={av_val:6.2f} {e.name} hp={getattr(e, 'current_hp', 0.0):.2f} dist={getattr(e, 'distance_remaining', 0.0):.2f}"
                )

    def _on_ev(ev: BattleEvent) -> None:
        av_val = float(getattr(sim, "current_av", 0.0) or 0.0)
        _check_spawns(av_val)
        if abs(av_val - target_av) > window:
            return
        if isinstance(ev, TurnBeginEvent):
            lines_out.append(f"  [TURN ] av={av_val:6.2f} actor={ev.actor_name}")
        elif isinstance(ev, ActionExecuteEvent):
            kind = getattr(ev.action_kind, "name", str(ev.action_kind))
            lines_out.append(f"  [ACT  ] av={av_val:6.2f} {ev.actor_name} kind={kind} name={ev.action_type}")
        elif isinstance(ev, EnemyDefeatedEvent):
            lines_out.append(f"  [DEAD ] av={av_val:6.2f} {ev.target_name} (by {ev.attacker_name})")
        elif isinstance(ev, DamageAppliedEvent):
            dtype = getattr(ev.damage_type, "value", str(ev.damage_type))
            atk_ent = sim.get_entity(ev.attacker_name)
            if atk_ent is not None and not getattr(atk_ent, "is_enemy", False) and dtype != "DoT":
                tot_dmg_out[0] += float(ev.damage)
            bd = getattr(ev, "breakdown", None)
            bd_str = ""
            if bd is not None:
                red = float(getattr(bd, "reduction_mult", 1.0) or 1.0)
                bar = float(getattr(bd, "barrier_mult", 1.0) or 1.0)
                bd_str = (
                    f" base={getattr(bd, 'base_dmg', 0.0):.1f}"
                    f" dmg%={getattr(bd, 'dmg_boost_mult', 1.0):.4f}"
                    f" def={getattr(bd, 'def_mult', 1.0):.4f}"
                    f" res={getattr(bd, 'res_mult', 1.0):.4f}"
                    f" vuln={getattr(bd, 'vuln_mult', 1.0):.4f}"
                    f" crit={getattr(bd, 'crit_mult', 1.0):.4f}"
                )
                if abs(red - 1.0) > 1e-6:
                    bd_str += f" red={red:.4f}"
                if abs(bar - 1.0) > 1e-6:
                    bd_str += f" bar={bar:.4f}"
            lines_out.append(
                f"  [DMG  ] av={av_val:6.2f} {ev.attacker_name} -> {ev.target_name} "
                f"{dtype:<10s} dmg={ev.damage:12.2f} crit={ev.is_crit}{bd_str}"
            )

    sim.event_bus.subscribe(BattleEvent, _on_ev)


def _print_sim_timeline_block(log_path: str, target_av: float, window: float, lines: Sequence[str], tot_dmg: float) -> None:
    print(f"\n--- SIM TIMELINE ({log_path}, av={target_av:.2f} +- {window:.2f}) ---")
    for line in lines:
        print(line)
    print(f"  => SIM window player non-DoT total = {tot_dmg:,.2f}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GT vs SIM 快速诊断工具")
    parser.add_argument("logs", nargs="+", help="一个或多个 battle_logs/*.jsonl")
    parser.add_argument("--extra-maze-buffs", default="", help="逗号分隔的额外 MazeBuff ID（如 3031359）")
    parser.add_argument("--av", type=float, default=None, help="聚焦检查指定 AV 窗口")
    parser.add_argument("--av-window", type=float, default=0.20, help="AV 窗口半径（默认 0.20）")
    parser.add_argument("--av-budget", type=float, default=None, help="截断模拟最大 AV")
    parser.add_argument("--full", action="store_true", help="即使传了 --av 也跑完整场而不早停")
    parser.add_argument("--timeline", action="store_true", help="输出 GT 与 SIM 并排事件时间线（需配合 --av）")
    parser.add_argument("--summary", action="store_true", help="同时打印 reconcile_log 摘要")
    parser.add_argument("--threshold", type=float, default=1e-6, help="判定误差阈值（默认 1e-6 = 0.0001%%）")
    args = parser.parse_args(argv)

    extra_buffs = _parse_extra_buffs(args.extra_maze_buffs)
    eff_budget = args.av_budget
    if eff_budget is None and args.av is not None and not args.full:
        eff_budget = args.av + max(args.av_window, 0.2) + 0.3

    char_db = CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    vm_loader = GameDataLoader()

    for lp in args.logs:
        meta = extract_log_metadata(lp, db=char_db)
        show_timeline = bool(args.timeline and args.av is not None)
        sim_lines: List[str] = []
        tot_dmg = [0.0]
        on_sim_ready = None
        if show_timeline:
            _print_gt_timeline(lp, args.av, args.av_window)

            def _on_sim_ready(sim: Any) -> None:
                sim_lines.clear()
                tot_dmg[0] = 0.0
                _attach_sim_timeline_recorder(sim, args.av, args.av_window, sim_lines, tot_dmg)

            on_sim_ready = _on_sim_ready

        # 统一经 reconcile_log 运行，确保自动推断 non_crits 与 RNG overrides 始终生效
        r = reconcile_log(
            lp,
            db=char_db,
            loader=vm_loader,
            meta=meta,
            extra_maze_buff_ids=extra_buffs,
            av_budget=eff_budget,
            threshold=args.threshold,
            on_sim_ready=on_sim_ready,
        )
        if show_timeline:
            _print_sim_timeline_block(lp, args.av, args.av_window, sim_lines, tot_dmg[0])
        if not show_timeline or args.summary:
            _print_summary(lp, meta, extra_buffs, r, threshold=args.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

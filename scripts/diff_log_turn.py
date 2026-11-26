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
    HealAppliedEvent,
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
    show_dots: bool = False,
) -> None:
    print(f"=== {log_path} | stage={meta.stage_id} | team={meta.team_names} | extra_buffs={extra_buffs} ===")
    print(
        f"  turn={r.turn_matched}/{r.turn_total}  ult={r.ult_matched}/{r.ult_total}  "
        f"sp={r.sp_granted}  ult_e={r.ult_energy_granted:.2f}  "
        f"mem={r.memoria_granted}  pres={r.presence_grants}  forced={r.forced_or_failed}  "
        f"nc={sorted(r.non_crits)}"
    )
    print(f"  total_err={r.total_err * 100:.6f}%  max_turn_err={r.max_turn_err * 100:.6f}%")
    dot_diffs = getattr(r, "dot_diffs", ()) or ()
    gt_dot_total = sum(dd.gt_total for dd in dot_diffs)
    sim_dot_total = sum(dd.sim_total for dd in dot_diffs)
    print(
        f"  gt_total={r.golden_total_damage:13.2f}  sim_total={r.sim_total_damage:13.2f}  "
        f"gt_dot_total={gt_dot_total:13.2f}  sim_dot_total={sim_dot_total:13.2f}  "
        f"dot_diff={sim_dot_total - gt_dot_total:+13.2f}"
    )
    if r.enemy_hit_mismatches:
        print(f"  enemy_hit_mismatches ({len(r.enemy_hit_mismatches)}):")
        for m in r.enemy_hit_mismatches:
            print(f"    av={m.av:.2f} {m.enemy_name} log={m.log_hits} sim={m.sim_hits} skill={m.skill_key}")
    else:
        print("  enemy_hit_mismatches: []")
    if getattr(r, "non_crit_details", None):
        print(f"  non_crit_details ({len(r.non_crit_details)}):")
        for det in r.non_crit_details:
            print(f"    {det}")
    for td in r.turn_diffs:
        mark = "OK " if td.err <= threshold else "ERR"
        print(f"  [{mark}] av={td.av:6.2f}  gt={td.gt_total:13.2f}  sim={td.sim_total:13.2f}  err={td.err * 100:9.6f}%  atk={td.attackers}")
        if td.err > threshold:
            for k, (gv, sv) in td.breakdown.items():
                ratio_s = f"{sv / gv:.6f}x" if gv > 0 else ("inf" if sv > 0 else "1.0x")
                print(f"        {k:<22s} gt={gv:13.2f}  sim={sv:13.2f}  sim/gt={ratio_s}")
    if show_dots:
        dot_rng_details = getattr(r, "dot_rng_details", ()) or ()
        if dot_rng_details:
            print(f"  dot_rng_details ({len(dot_rng_details)}):")
            for det in dot_rng_details:
                print(f"    {det}")
        print("  --- DoT summary by AV ---")
        for dd in dot_diffs:
            mark = "OK " if dd.err <= threshold else "ERR"
            print(
                f"  [{mark}] av={dd.av:6.2f}  gt={dd.gt_total:13.2f}  sim={dd.sim_total:13.2f}  "
                f"err={dd.err * 100:9.6f}%  atk={dd.attackers}"
            )
            if dd.err > threshold:
                for k, (gv, sv) in dd.breakdown.items():
                    ratio_s = f"{sv / gv:.6f}x" if gv > 0 else ("inf" if sv > 0 else "1.0x")
                    print(
                        f"        {k:<22s} gt={gv:13.2f}  sim={sv:13.2f}  sim/gt={ratio_s}  diff={sv - gv:+13.2f}"
                    )


def _print_gt_timeline(log_path: str, target_av: float, window: float, *, show_energy: bool = False) -> None:
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
            elif show_energy and ent.get("team") == "Player" and ptype == "CurrentSP":
                print(f"  L{idx:4d} [EN   ] av={cur_av:6.2f} uid={uid} ({uid_names.get(uid, '')}) sp={pval:.4f}")
    print(f"  => GT window player non-DoT total = {tot_dmg:,.2f}")


def _attach_sim_timeline_recorder(
    sim: Any,
    target_av: float,
    window: float,
    lines_out: List[str],
    tot_dmg_out: List[float],
    *,
    dump_mods: bool = False,
    show_energy: bool = False,
) -> None:
    sim._timeline_diag_energy = bool(show_energy)
    seen_enemies = {e.name for e in sim.entities if getattr(e, "is_enemy", False)}
    dumped_mods = [False]

    def _dump_active_mods(av_val: float) -> None:
        if dumped_mods[0]:
            return
        dumped_mods[0] = True
        rt = getattr(sim, "vm_runtime", None)
        me = getattr(rt, "modifier_engine", None) if rt is not None else None
        if me is None:
            return
        for e in sim.entities:
            if getattr(e, "is_countdown", False):
                continue
            mods = me.get_modifiers(e.name)
            m_strs = []
            for m in mods:
                if m._destroyed:
                    continue
                props_s = ", ".join(f"{k}={v:.4g}" for k, v in sorted(m.properties.items()) if abs(float(v)) > 1e-9)
                m_strs.append(f"{m.name}(c={m.caster_id},L={m.layer},{props_s})")
            lines_out.append(f"  [MODS  ] av={av_val:6.2f} {e.name}: " + (" | ".join(m_strs) if m_strs else "(none)"))

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
        if dump_mods:
            _dump_active_mods(av_val)
        if isinstance(ev, TurnBeginEvent):
            lines_out.append(f"  [TURN ] av={av_val:6.2f} actor={ev.actor_name}")
        elif isinstance(ev, ActionExecuteEvent):
            kind = getattr(ev.action_kind, "name", str(ev.action_kind))
            lines_out.append(f"  [ACT  ] av={av_val:6.2f} {ev.actor_name} kind={kind} name={ev.action_type}")
        elif isinstance(ev, EnemyDefeatedEvent):
            lines_out.append(f"  [DEAD ] av={av_val:6.2f} {ev.target_name} (by {ev.attacker_name})")
        elif isinstance(ev, HealAppliedEvent):
            lines_out.append(f"  [HEAL ] av={av_val:6.2f} {ev.source_name} -> {ev.target_name} amt={ev.amount:.2f}")
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
                fat = float(getattr(bd, "fatigue_mult", 1.0) or 1.0)
                bd_str = (
                    f" base={getattr(bd, 'base_dmg', 0.0):.1f}"
                    f" dmg%={getattr(bd, 'dmg_boost_mult', 1.0):.4f}"
                    f" def={getattr(bd, 'def_mult', 1.0):.4f}"
                    f" res={getattr(bd, 'res_mult', 1.0):.4f}"
                    f" vuln={getattr(bd, 'vuln_mult', 1.0):.4f}"
                    f" crit={getattr(bd, 'crit_mult', 1.0):.4f}"
                )
                if getattr(bd, "is_elation_dmg", False):
                    bd_str += (
                        f" el={getattr(bd, 'elation_val', 0.0):.4f}"
                        f" p={getattr(bd, 'elation_point_num', 0.0):.0f}(x{getattr(bd, 'punchline_mult', 1.0):.4f})"
                        f" ex={getattr(bd, 'elation_extra_val', 0.0):.4f}"
                    )
                if abs(red - 1.0) > 1e-6:
                    bd_str += f" red={red:.4f}"
                if abs(bar - 1.0) > 1e-6:
                    bd_str += f" bar={bar:.4f}"
                if abs(fat - 1.0) > 1e-6:
                    bd_str += f" fat={fat:.4f}"
            lines_out.append(
                f"  [DMG  ] av={av_val:6.2f} {ev.attacker_name} -> {ev.target_name} "
                f"{dtype:<10s} dmg={ev.damage:12.2f} hp={float(getattr(ev, 'target_hp_left', 0.0)):.1f} crit={ev.is_crit}{bd_str}"
            )

    def _on_diag(tag: str, msg: str) -> None:
        av_val = float(getattr(sim, "current_av", 0.0) or 0.0)
        if abs(av_val - target_av) <= window:
            lines_out.append(f"  [{tag:<6s}] av={av_val:6.2f} {msg}")

    sim.timeline_diag_cb = _on_diag
    sim.event_bus.subscribe(BattleEvent, _on_ev)


def _print_sim_timeline_block(log_path: str, target_av: float, window: float, lines: Sequence[str], tot_dmg: float) -> None:
    print(f"\n--- SIM TIMELINE ({log_path}, av={target_av:.2f} +- {window:.2f}) ---")
    for line in lines:
        print(line)
    print(f"  => SIM window player non-DoT total = {tot_dmg:,.2f}")


def _parse_init_ep(raw: Optional[str]) -> Optional[Dict[str, float]]:
    if not raw:
        return None
    out: Dict[str, float] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        k, v = item.split(":", 1)
        out[k.strip()] = float(v.strip())
    return out or None


def _parse_tech_users(raw: Optional[str], meta: LogMetadata) -> Optional[Tuple[str, ...]]:
    if raw is None:
        return None
    uid_to_name = dict(zip(meta.team_uids, meta.team_names))
    out: List[str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item.isdigit() and int(item) in uid_to_name:
            out.append(uid_to_name[int(item)])
        else:
            out.append(item)
    return tuple(out)


def _parse_loadouts(raw: Optional[str]) -> Optional[Dict[int, Tuple[Any, ...]]]:
    if not raw:
        return None
    out: Dict[int, Tuple[Any, ...]] = {}
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        uid = int(parts[0])
        eid = int(parts[1])
        lc_id = int(parts[2])
        lc_s = int(parts[3])
        relics = []
        if len(parts) > 4 and parts[4]:
            for rp in parts[4].split("+"):
                rid, cnt = rp.split("x")
                relics.append((int(rid), int(cnt)))
        out[uid] = (uid, eid, lc_id, lc_s, relics)
    return out or None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GT vs SIM 快速诊断工具")
    parser.add_argument("logs", nargs="+", help="一个或多个 battle_logs/*.jsonl")
    parser.add_argument("--extra-maze-buffs", default="", help="逗号分隔的额外 MazeBuff ID（如 3031359）")
    parser.add_argument("--team", default="", help="逗号分隔的队伍档案名覆盖（按 1..4 号位）")
    parser.add_argument(
        "--loadouts",
        default="",
        help="覆盖配装（格式 uid:eid:lc_id:lc_s:set1xN1+set2xN2，多角色分号分隔）",
    )
    parser.add_argument(
        "--init-ep",
        default="",
        help="覆盖进场初始能量（格式 uid_or_name:ep，逗号分隔，如 1217:108.69,1410:0）",
    )
    parser.add_argument(
        "--tech-users",
        default=None,
        help="逗号分隔的开局施放秘技角色（如 1217,1307 或 藿藿,黑天鹅）；不传默认全队",
    )
    parser.add_argument("--av", type=float, default=None, help="聚焦检查指定 AV 窗口")
    parser.add_argument("--av-window", type=float, default=0.20, help="AV 窗口半径（默认 0.20）")
    parser.add_argument("--av-budget", type=float, default=None, help="截断模拟最大 AV")
    parser.add_argument("--full", action="store_true", help="即使传了 --av 也跑完整场而不早停")
    parser.add_argument("--timeline", action="store_true", help="输出 GT 与 SIM 并排事件时间线（需配合 --av）")
    parser.add_argument("--energy", action="store_true", help="在 --timeline 中输出我方能量变动 [EN   ]")
    parser.add_argument("--dump-mods", action="store_true", help="在 --av 窗口首次动作时输出所有实体的激活 Modifier 与属性增量")
    parser.add_argument("--summary", action="store_true", help="同时打印 reconcile_log 摘要")
    parser.add_argument("--dot-summary", action="store_true", help="按 AV 打印 DoT 分项对比摘要")
    parser.add_argument("--no-dot-rng", action="store_true", help="禁用 Layer-4 DoT RNG 自动求解（用于诊断基线偏差）")
    parser.add_argument("--threshold", type=float, default=1e-6, help="判定误差阈值（默认 1e-6 = 0.0001%%）")
    args = parser.parse_args(argv)

    extra_buffs = _parse_extra_buffs(args.extra_maze_buffs)
    team_override = [x.strip() for x in args.team.split(",") if x.strip()] or None
    loadouts_override = _parse_loadouts(args.loadouts)
    init_ep_override = _parse_init_ep(args.init_ep)
    eff_budget = args.av_budget
    if eff_budget is None and args.av is not None and not args.full:
        eff_budget = args.av + max(args.av_window, 0.2) + 0.3

    char_db = CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    vm_loader = GameDataLoader()

    for lp in args.logs:
        meta = extract_log_metadata(lp, db=char_db, team_override=team_override)
        show_timeline = bool(args.timeline and args.av is not None)
        sim_lines: List[str] = []
        tot_dmg = [0.0]
        on_sim_ready = None
        if show_timeline:
            _print_gt_timeline(lp, args.av, args.av_window, show_energy=bool(args.energy))
            for rec in meta.enemy_hits:
                if abs(rec.av - args.av) <= args.av_window:
                    subs = (
                        f" subs={[list(sr.hit_allies) for sr in rec.sub_records]}"
                        if rec.sub_records
                        else ""
                    )
                    print(
                        f"  [EHIT ] av={rec.av:6.2f} euid={rec.enemy_uid}({meta.enemy_uid_map.get(rec.enemy_uid, '?')}) "
                        f"hits={list(rec.hit_allies)} sp={dict(rec.sp_gain_counts)} memo={rec.first_memo_owner}{subs}"
                    )
            rt_groups: Dict[Tuple[float, int], List[int]] = {}
            for p_av, c_uid, v_uid in meta.enemy_retarget_picks:
                if abs(p_av - args.av) <= args.av_window:
                    rt_groups.setdefault((p_av, c_uid), []).append(v_uid)
            for (p_av, c_uid), vuids in rt_groups.items():
                vnames = [meta.enemy_uid_map.get(v, str(v)) for v in vuids]
                print(f"  [META_RT] av={p_av:6.2f} uid={c_uid} count={len(vuids)} picks={vnames}")

            def _on_sim_ready(sim: Any) -> None:
                sim_lines.clear()
                tot_dmg[0] = 0.0
                _attach_sim_timeline_recorder(
                    sim,
                    args.av,
                    args.av_window,
                    sim_lines,
                    tot_dmg,
                    dump_mods=bool(args.dump_mods),
                    show_energy=bool(args.energy),
                )

            on_sim_ready = _on_sim_ready

        # 统一经 reconcile_log 运行，确保自动推断 non_crits 与 RNG overrides 始终生效
        tech_users_override = _parse_tech_users(args.tech_users, meta)
        r = reconcile_log(
            lp,
            db=char_db,
            loader=vm_loader,
            meta=meta,
            team_override=team_override,
            loadouts=loadouts_override,
            extra_maze_buff_ids=extra_buffs,
            av_budget=eff_budget,
            threshold=args.threshold,
            on_sim_ready=on_sim_ready,
            initial_energies=init_ep_override,
            technique_users=tech_users_override,
            resolve_dots=not bool(args.no_dot_rng),
        )
        if show_timeline:
            _print_sim_timeline_block(lp, args.av, args.av_window, sim_lines, tot_dmg[0])
        if not show_timeline or args.summary or args.dot_summary:
            _print_summary(lp, meta, extra_buffs, r, threshold=args.threshold, show_dots=bool(args.dot_summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

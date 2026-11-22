# coding: utf-8
"""VM 端到端对账执行器（单轮回放、自动未暴击检测、多忆灵二次确认收敛）。"""

from __future__ import annotations

import importlib
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from simulator.db.character_db import CharacterDB
from simulator.golden_diff import (
    attach_exact_crit_oracle,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)
from simulator.vm.factory import build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.auto_rng import attach_auto_rng_plugin
from simulator.vm.reconcile.metadata import extract_log_metadata
from simulator.vm.reconcile.models import (
    DEFAULT_CHAR_DB_PATH,
    AmbiguousMemospriteSlot,
    InferredMemospriteHit,
    LogMetadata,
    ReconcileReport,
    TurnDiffEntry,
)
from simulator.vm.stage_sim_adapter import build_data_driven_stage


def _try_load_existing_plugin(tag: str) -> Tuple[Optional[Callable[[Any], None]], Set[Any]]:
    """尝试加载已存在的 simulator/plugins/log_<tag>.py 及对应非暴击账本。"""
    plugin_fn: Optional[Callable[[Any], None]] = None
    non_crits: Set[Any] = set()
    mod_name = f"simulator.plugins.log_{tag}"
    fn_name = f"attach_log_{tag}_plugin"
    try:
        mod = importlib.import_module(mod_name)
        plugin_fn = getattr(mod, fn_name, None)
        if hasattr(mod, "NON_CRITS"):
            non_crits = set(getattr(mod, "NON_CRITS"))
    except ModuleNotFoundError:
        plugin_fn = None
    return plugin_fn, non_crits


def build_stage_for_id(
    stage_id: int,
    team: List[Any],
    *,
    technique_users: Sequence[str],
    force_data_driven: bool = True,
) -> Tuple[Any, Any, str]:
    """统一走纯数据驱动 DataDrivenStageDirector 底座（零手写关卡硬编码）。"""
    sim, director = build_data_driven_stage(
        stage_id,
        team,
        technique_users=list(technique_users),
    )
    return sim, director, f"data_driven({stage_id})"


def _attach_crit_hit_recorder(sim: Any) -> List[Tuple[float, int, int, str, float, float, float]]:
    """包装 sim.crit_oracle 并订阅 DamageAppliedEvent，记录每次玩家暴击的 (av, act_idx, hit_idx, dtype, eff_cr, crit_mult, dmg)。"""
    from simulator.actions import ActionKind
    from simulator.events import ActionExecuteEvent, BattleEvent, DamageAppliedEvent
    from simulator.status import StatType

    records: List[Tuple[float, int, int, str, float, float, float]] = []
    state = {"act_idx": -1, "hit_idx": 0}
    pending: List[Tuple[int, int, float]] = []

    def _on_ev(e: BattleEvent) -> None:
        if isinstance(e, ActionExecuteEvent):
            ent = sim.get_entity(e.actor_name)
            if ent is not None and (getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False)):
                return
            kind = getattr(e, "action_kind", None)
            if kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
                return
            raw_name = e.action_type or ""
            if raw_name == "FollowUpAttack" or not raw_name:
                return
            state["act_idx"] += 1
            state["hit_idx"] = 0
        elif isinstance(e, DamageAppliedEvent):
            if not pending:
                return
            act_i, hit_i, eff_cr = pending.pop(0)
            bd = getattr(e, "breakdown", None)
            if bd is not None:
                dtype = getattr(e.damage_type, "value", str(e.damage_type)) if e.damage_type is not None else ""
                atk_name = getattr(e, "attacker_name", "") or ""
                atk_ent = sim.get_entity(atk_name) if atk_name else None
                if atk_ent is not None and getattr(atk_ent, "is_memosprite", False) and getattr(atk_ent, "master_name", None):
                    atk_name = str(atk_ent.master_name)
                records.append(
                    (
                        round(float(getattr(sim, "current_av", 0.0)), 2),
                        act_i,
                        hit_i,
                        atk_name,
                        dtype,
                        bool(e.is_crit),
                        eff_cr,
                        float(getattr(bd, "crit_mult", 1.0)),
                        float(e.damage),
                    )
                )

    sim.event_bus.subscribe(BattleEvent, _on_ev)

    orig_oracle = sim.crit_oracle

    def _wrapped_oracle(req: Any) -> bool:
        res = orig_oracle(req)
        if not (getattr(req.attacker, "is_enemy", False) or getattr(req.attacker, "is_countdown", False)):
            h_i = state["hit_idx"]
            state["hit_idx"] += 1
            try:
                eff_cr = float(sim.port.stat(req.attacker.name, StatType.CRIT_RATE)) + float(
                    getattr(req, "extra_crit_rate", 0.0) or 0.0
                )
            except Exception:
                eff_cr = 0.5
            pending.append((state["act_idx"], h_i, eff_cr))
        return res

    sim.crit_oracle = _wrapped_oracle
    return records


def _detect_non_crits_from_trace(
    g: Any,
    crit_records: Sequence[Tuple[float, int, int, str, str, bool, float, float, float]],
) -> Set[Tuple[int, int]]:
    """将 SIM 暴击命中与 GT 同 AV 同攻击者同类型伤害逐段比对，精确识别实机未暴击的 (act_idx, hit_idx)。

    严格防呆：
    - 仅检查有效暴击率 < 99.9% 的角色命中；
    - 仅当 sim_dmg / gt_dmg 与该次命中的 1 + CritDMG (crit_mult) 偏差 < 6% 时才判定为未暴击。
    """
    gt_hits: Dict[Tuple[float, str, str], List[float]] = {}
    for t in g.turns:
        av = round(t.av, 2)
        for d in t.damages:
            if d.damage_type == "DoT":
                continue
            atk_base = str(d.attacker).replace(" (忆灵)", "")
            gt_hits.setdefault((av, atk_base, d.damage_type), []).append(float(d.damage))

    sim_grouped: Dict[Tuple[float, str, str], List[Tuple[int, int, bool, float, float, float]]] = {}
    for av, act_i, hit_i, atk_name, dtype, is_crit, eff_cr, crit_mult, dmg in crit_records:
        sim_grouped.setdefault((av, atk_name, dtype), []).append((act_i, hit_i, is_crit, eff_cr, crit_mult, dmg))

    detected: Set[Tuple[int, int]] = set()
    for key, s_list in sim_grouped.items():
        g_list = gt_hits.get(key)
        if not g_list or len(g_list) != len(s_list):
            continue
        for (act_i, hit_i, is_crit, eff_cr, crit_mult, s_dmg), g_dmg in zip(s_list, g_list):
            if not is_crit or crit_mult <= 1.05 or eff_cr >= 0.999 or g_dmg <= 0.0:
                continue
            ratio = s_dmg / g_dmg
            if abs(ratio - crit_mult) / crit_mult < 0.06:
                detected.add((act_i, hit_i))
    return detected


def _run_single_pass(
    log_path: str,
    meta: LogMetadata,
    g: Any,
    tl: List[Any],
    *,
    char_db: CharacterDB,
    vm_loader: GameDataLoader,
    force_data_driven: bool,
    plugin_fn: Optional[Callable[[Any], None]],
    non_crits: Set[Any],
    av_budget: Optional[float],
    memosprite_overrides: Optional[Dict[Tuple[float, int, str], Tuple[str, ...]]] = None,
    record_crits: bool = False,
) -> Tuple[ReconcileReport, List[AmbiguousMemospriteSlot], List[Tuple[float, int, int, str, float, float, float]]]:
    team = build_vm_team(meta.team_names, db=char_db, loader=vm_loader)
    sim, director, stage_mode = build_stage_for_id(
        meta.stage_id,
        team,
        technique_users=[e.name for e in team],
        force_data_driven=force_data_driven,
    )

    ambiguous_slots: List[AmbiguousMemospriteSlot] = []
    inferred_hits: List[InferredMemospriteHit] = []

    attach_exact_crit_oracle(sim, log_path=log_path, non_crits=non_crits)
    crit_records = _attach_crit_hit_recorder(sim) if record_crits else []
    if not getattr(sim, "enemy_uid_map", None) and meta.enemy_uid_map:
        sim.enemy_uid_map = dict(meta.enemy_uid_map)
    if plugin_fn is not None:
        plugin_fn(sim)
        plugin_mode = f"plugin:log_{meta.tag}"
    else:
        attach_auto_rng_plugin(
            sim,
            meta,
            memosprite_overrides=memosprite_overrides,
            ambiguous_out=ambiguous_slots,
            inferred_out=inferred_hits,
        )
        plugin_mode = ""

    traj = run_trajectory_replay(
        sim,
        director,
        tl,
        av_budget=av_budget if av_budget is not None else g.final_av,
        log_path=log_path,
    )
    rep = diff_sequences(g, traj.replay.sequence)

    if plugin_fn is None:
        plugin_mode = (
            f"auto_rng({len([h for h in meta.enemy_hits if h.hit_allies])} avatar hits, "
            f"{len(inferred_hits)} memo/skip inferred, {len(meta.aha_turns)} aha, {len(non_crits)} non_crits)"
        )

    gt_by_av: Dict[float, float] = {}
    gt_atks: Dict[float, Set[str]] = {}
    gt_cat: Dict[float, Dict[str, float]] = {}
    for t in g.turns:
        av = round(t.av, 2)
        for d in t.damages:
            if d.damage_type == "DoT":
                continue
            gt_by_av[av] = gt_by_av.get(av, 0.0) + d.damage
            gt_atks.setdefault(av, set()).add(d.attacker)
            cat = f"{d.attacker}:{d.damage_type}"
            gt_cat.setdefault(av, {})[cat] = gt_cat.setdefault(av, {}).get(cat, 0.0) + d.damage

    sim_by_av: Dict[float, float] = {}
    sim_cat: Dict[float, Dict[str, float]] = {}
    for t in traj.replay.sequence.turns:
        av = round(t.av, 2)
        for d in t.damages:
            if d.damage_type == "DoT":
                continue
            sim_by_av[av] = sim_by_av.get(av, 0.0) + d.damage
            cat = f"{d.attacker}:{d.damage_type}"
            sim_cat.setdefault(av, {})[cat] = sim_cat.setdefault(av, {}).get(cat, 0.0) + d.damage

    all_avs = sorted(set(gt_by_av.keys()) | set(sim_by_av.keys()))
    turn_diffs: List[TurnDiffEntry] = []
    max_turn_err = 0.0
    for av in all_avs:
        gd = gt_by_av.get(av, 0.0)
        sd = sim_by_av.get(av, 0.0)
        if gd > 0.0:
            err = abs(sd - gd) / gd
        else:
            err = 1.0 if sd > 0.0 else 0.0
        max_turn_err = max(max_turn_err, err)
        cats = sorted(set(gt_cat.get(av, {}).keys()) | set(sim_cat.get(av, {}).keys()))
        breakdown = {c: (gt_cat.get(av, {}).get(c, 0.0), sim_cat.get(av, {}).get(c, 0.0)) for c in cats}
        turn_diffs.append(
            TurnDiffEntry(
                av=av,
                gt_total=gd,
                sim_total=sd,
                err=err,
                attackers=sorted(gt_atks.get(av, set())),
                breakdown=breakdown,
            )
        )

    gold_tot = float(rep["golden_total_damage"])
    sim_tot = float(rep["sim_total_damage"])
    tot_err = abs(sim_tot - gold_tot) / gold_tot if gold_tot > 0 else 0.0
    forced_or_failed = sum(1 for r in traj.records if r.mode in ("forced", "failed"))

    report = ReconcileReport(
        meta=meta,
        stage_mode=stage_mode,
        plugin_mode=plugin_mode,
        turn_matched=traj.replay.turn_matched,
        turn_total=traj.replay.turn_total,
        ult_matched=traj.replay.ult_matched,
        ult_total=traj.replay.ult_total,
        sp_granted=traj.sp_granted,
        memoria_granted=traj.memoria_granted,
        presence_grants=traj.presence_grants,
        forced_or_failed=forced_or_failed,
        golden_total_damage=gold_tot,
        sim_total_damage=sim_tot,
        total_err=tot_err,
        max_turn_err=max_turn_err,
        turn_diffs=turn_diffs,
        inferred_memosprite_hits=inferred_hits,
        unresolved_ambiguous_slots=len(ambiguous_slots),
    )
    return report, ambiguous_slots, crit_records


def reconcile_log(
    log_path: str,
    *,
    db: Optional[CharacterDB] = None,
    loader: Optional[GameDataLoader] = None,
    team_override: Optional[Sequence[str]] = None,
    force_data_driven: bool = False,
    use_existing_plugin: bool = True,
    resolve_memosprites: bool = True,
    av_budget: Optional[float] = None,
    max_tl_av: Optional[float] = None,
    threshold: float = 0.0001,
) -> ReconcileReport:
    """对任意官方战斗日志执行端到端 VM 对账并返回逐动诊断报告。"""
    char_db = db if db is not None else CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    vm_loader = loader if loader is not None else GameDataLoader()

    meta = extract_log_metadata(log_path, db=char_db, team_override=team_override)
    g = parse_golden_jsonl(log_path)
    tl = extract_timeline(log_path)
    if max_tl_av is not None:
        tl = [item for item in tl if item.av < max_tl_av]

    plugin_fn: Optional[Callable[[Any], None]] = None
    non_crits: Set[Any] = set()
    if use_existing_plugin:
        plugin_fn, non_crits = _try_load_existing_plugin(meta.tag)

    overrides: Dict[Tuple[float, int, str], Tuple[str, ...]] = {}
    report, ambiguous_slots, crit_records = _run_single_pass(
        log_path,
        meta,
        g,
        tl,
        char_db=char_db,
        vm_loader=vm_loader,
        force_data_driven=force_data_driven,
        plugin_fn=plugin_fn,
        non_crits=non_crits,
        av_budget=av_budget,
        memosprite_overrides=overrides,
        record_crits=True,
    )

    # 自动检测未暴击 (act_idx, hit_idx) 并收敛（允许级联收敛，无新检出立即 break）
    for _nc_round in range(6):
        newly_detected = _detect_non_crits_from_trace(g, crit_records) - non_crits
        if not newly_detected:
            break
        non_crits = set(non_crits) | newly_detected
        report, ambiguous_slots, crit_records = _run_single_pass(
            log_path,
            meta,
            g,
            tl,
            char_db=char_db,
            vm_loader=vm_loader,
            force_data_driven=force_data_driven,
            plugin_fn=plugin_fn,
            non_crits=non_crits,
            av_budget=av_budget,
            memosprite_overrides=overrides,
            record_crits=True,
        )

    if plugin_fn is None and resolve_memosprites and ambiguous_slots:
        resolved_keys: Set[Tuple[float, int, str]] = set()
        for _round in range(min(len(ambiguous_slots), 8)):
            bad_turns = [td for td in report.turn_diffs if td.err >= threshold]
            if not bad_turns:
                break
            first_bad = bad_turns[0]
            preceding = [
                slot
                for slot in ambiguous_slots
                if slot.av <= first_bad.av + 0.05 and slot.key not in resolved_keys
            ]
            if not preceding:
                break
            improved_any = False
            for slot in reversed(preceding[-3:]):
                resolved_keys.add(slot.key)
                best_choice = slot.default_choice
                best_err = first_bad.err
                best_report = report
                best_slots = ambiguous_slots
                for cand in slot.candidates:
                    if cand == slot.default_choice:
                        continue
                    trial_ov = dict(overrides)
                    trial_ov[slot.key] = cand
                    trial_rep, trial_slots, _ = _run_single_pass(
                        log_path,
                        meta,
                        g,
                        tl,
                        char_db=char_db,
                        vm_loader=vm_loader,
                        force_data_driven=force_data_driven,
                        plugin_fn=None,
                        non_crits=non_crits,
                        av_budget=av_budget,
                        memosprite_overrides=trial_ov,
                        record_crits=False,
                    )
                    trial_td = next((td for td in trial_rep.turn_diffs if abs(td.av - first_bad.av) < 0.05), None)
                    trial_err = trial_td.err if trial_td is not None else 1.0
                    if trial_err + 1e-4 < best_err:
                        best_err = trial_err
                        best_choice = cand
                        best_report = trial_rep
                        best_slots = trial_slots
                if best_choice != slot.default_choice:
                    overrides[slot.key] = best_choice
                    report = best_report
                    ambiguous_slots = best_slots
                    improved_any = True
                    break
            if not improved_any:
                break

        if overrides:
            report, ambiguous_slots, crit_records = _run_single_pass(
                log_path,
                meta,
                g,
                tl,
                char_db=char_db,
                vm_loader=vm_loader,
                force_data_driven=force_data_driven,
                plugin_fn=None,
                non_crits=non_crits,
                av_budget=av_budget,
                memosprite_overrides=overrides,
                record_crits=True,
            )
            for _nc_round in range(2):
                newly_detected = _detect_non_crits_from_trace(g, crit_records) - non_crits
                if not newly_detected:
                    break
                non_crits = set(non_crits) | newly_detected
                report, ambiguous_slots, crit_records = _run_single_pass(
                    log_path,
                    meta,
                    g,
                    tl,
                    char_db=char_db,
                    vm_loader=vm_loader,
                    force_data_driven=force_data_driven,
                    plugin_fn=None,
                    non_crits=non_crits,
                    av_budget=av_budget,
                    memosprite_overrides=overrides,
                    record_crits=True,
                )

    report.non_crits = set(non_crits)
    return report

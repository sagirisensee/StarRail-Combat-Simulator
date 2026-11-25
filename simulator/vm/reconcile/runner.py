# coding: utf-8
"""VM 端到端对账执行器（单轮回放、自动未暴击检测、多忆灵二次确认收敛）。"""

from __future__ import annotations

import importlib
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from simulator.db.character_db import CharacterDB
from simulator.golden import (
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
    EnemyHitMismatch,
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
    extra_maze_buff_ids: Sequence[int] = (),
    entry_element: Optional[str] = None,
    entry_toughness: float = 10.0,
) -> Tuple[Any, Any, str]:
    """统一走纯数据驱动 DataDrivenStageDirector 底座（零手写关卡硬编码）。"""
    sim, director = build_data_driven_stage(
        stage_id,
        team,
        technique_users=list(technique_users),
        extra_maze_buff_ids=extra_maze_buff_ids,
        entry_element=entry_element,
        entry_toughness=entry_toughness,
        defer_opening_drain=True,
    )
    return sim, director, f"data_driven({stage_id})"


def _attach_crit_hit_recorder(sim: Any) -> List[Tuple[float, int, int, str, float, float, float]]:
    """包装 sim.crit_oracle 并订阅 DamageAppliedEvent，记录每次玩家暴击的 (av, act_idx, hit_idx, dtype, eff_cr, crit_mult, dmg)。"""
    from simulator.actions import ActionKind
    from simulator.events import ActionExecuteEvent, BattleEvent, DamageAppliedEvent
    from simulator.status import StatType

    records: List[Tuple[float, int, int, str, float, float, float]] = []
    state = {"act_idx": -1, "hit_idx": 0}
    pending: List[Tuple[int, int, float, float]] = []

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
            act_i, hit_i, eff_cr, eff_cm = pending.pop(0)
            bd = getattr(e, "breakdown", None)
            if bd is not None:
                dtype = getattr(e.damage_type, "value", str(e.damage_type)) if e.damage_type is not None else ""
                atk_name = getattr(e, "attacker_name", "") or ""
                atk_ent = sim.get_entity(atk_name) if atk_name else None
                if atk_ent is not None and getattr(atk_ent, "is_memosprite", False) and getattr(atk_ent, "master_name", None):
                    atk_name = str(atk_ent.master_name)
                cm = float(getattr(bd, "crit_mult", 1.0)) if e.is_crit else eff_cm
                records.append(
                    (
                        round(float(getattr(sim, "current_av", 0.0)), 2),
                        act_i,
                        hit_i,
                        atk_name,
                        dtype,
                        bool(e.is_crit),
                        eff_cr,
                        cm,
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
            stat_src = getattr(req, "property_source", None) or req.attacker
            src_name = getattr(stat_src, "name", "") or req.attacker.name
            try:
                eff_cr = float(sim.port.stat(src_name, StatType.CRIT_RATE)) + float(
                    getattr(req, "extra_crit_rate", 0.0) or 0.0
                )
            except Exception:
                eff_cr = 0.5
            try:
                fixed_cd = getattr(req, "fixed_crit_dmg", None)
                base_cd = (
                    float(fixed_cd)
                    if fixed_cd is not None
                    else float(sim.port.stat(src_name, StatType.CRIT_DMG))
                )
                eff_cm = 1.0 + base_cd + float(getattr(req, "extra_crit_dmg", 0.0) or 0.0)
            except Exception:
                eff_cm = 1.0
            pending.append((state["act_idx"], h_i, eff_cr, eff_cm))
        return res

    sim.crit_oracle = _wrapped_oracle
    return records


def _group_gt_and_sim_hits(
    g: Any,
    crit_records: Sequence[Tuple[float, int, int, str, str, bool, float, float, float]],
) -> List[Tuple[Tuple[float, str, str], List[Tuple[int, int, bool, float, float, float]], List[float], bool]]:
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

    groups = []
    for key, s_list in sim_grouped.items():
        g_list = gt_hits.get(key)
        if g_list:
            groups.append((key, s_list, g_list, len(g_list) == len(s_list)))
    return groups


def _detect_non_crits_from_trace(
    g: Any,
    crit_records: Sequence[Tuple[float, int, int, str, str, bool, float, float, float]],
    *,
    details_out: Optional[List[str]] = None,
    round_idx: int = 0,
) -> Set[Tuple[int, int]]:
    """将 SIM 暴击命中与 GT 同 AV 同攻击者同类型伤害逐段比对，精确识别实机未暴击的 (act_idx, hit_idx)。

    严格防呆：
    - 仅检查有效暴击率 < 99.9% 的角色命中；
    - 仅当 sim_dmg / gt_dmg 与该次命中的 1 + CritDMG (crit_mult) 偏差 < 6% 时才判定为未暴击。
    """
    detected: Set[Tuple[int, int]] = set()
    for key, s_list, g_list, same_len in _group_gt_and_sim_hits(g, crit_records):
        for (act_i, hit_i, is_crit, eff_cr, crit_mult, s_dmg), g_dmg in zip(s_list, g_list):
            if g_dmg <= 0.0:
                if not same_len:
                    break
                continue
            if abs(s_dmg - g_dmg) / g_dmg < 1e-4:
                continue
            if is_crit and crit_mult > 1.05 and eff_cr < 0.999:
                ratio = s_dmg / g_dmg
                if abs(ratio - crit_mult) / crit_mult < 0.06:
                    detected.add((act_i, hit_i))
                    if details_out is not None:
                        details_out.append(
                            f"r{round_idx} av={key[0]:.2f} ({act_i},{hit_i}) {key[1]}:{key[2]} "
                            f"sim={s_dmg:.2f} gt={g_dmg:.2f} ratio={ratio:.4f} crit={crit_mult:.4f} eff_cr={eff_cr:.4f}"
                        )
                    if not same_len:
                        break
                    continue
            if not same_len:
                break
    return detected


def _prune_stale_non_crits(
    g: Any,
    crit_records: Sequence[Tuple[float, int, int, str, str, bool, float, float, float]],
    non_crits: Set[Tuple[int, int]],
    *,
    details_out: Optional[List[str]] = None,
    round_idx: int = 0,
) -> Set[Tuple[int, int]]:
    """剔除前期击杀/数量漂移导致的过期误判 (act_idx, hit_idx)。"""
    stale: Set[Tuple[int, int]] = set()
    for key, s_list, g_list, same_len in _group_gt_and_sim_hits(g, crit_records):
        for (act_i, hit_i, is_crit, eff_cr, crit_mult, s_dmg), g_dmg in zip(s_list, g_list):
            if g_dmg <= 0.0:
                if not same_len:
                    break
                continue
            if (act_i, hit_i) in non_crits and not is_crit:
                if abs(s_dmg - g_dmg) / g_dmg >= 1e-4:
                    inv_ratio = (g_dmg / s_dmg) if s_dmg > 0.0 else 0.0
                    if eff_cr >= 0.999 or (crit_mult > 1.05 and abs(inv_ratio - crit_mult) / crit_mult < 0.06):
                        stale.add((act_i, hit_i))
                        if details_out is not None:
                            details_out.append(
                                f"r{round_idx} PRUNE av={key[0]:.2f} ({act_i},{hit_i}) {key[1]}:{key[2]} "
                                f"sim={s_dmg:.2f} gt={g_dmg:.2f} gt/sim={inv_ratio:.4f} crit={crit_mult:.4f} eff_cr={eff_cr:.4f}"
                            )
            if not same_len and abs(s_dmg - g_dmg) / g_dmg >= 1e-4:
                break
    return stale


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
    loadouts: Optional[Dict[int, Any]] = None,
    memosprite_overrides: Optional[Dict[Tuple[float, int, str], Tuple[str, ...]]] = None,
    aha_dmg_overrides: Optional[Dict[Tuple[int, str], float]] = None,
    sim_enemy_hp_out: Optional[Dict[Tuple[float, str], float]] = None,
    record_crits: bool = False,
    extra_maze_buff_ids: Sequence[int] = (),
    on_sim_ready: Optional[Callable[[Any], None]] = None,
) -> Tuple[ReconcileReport, List[AmbiguousMemospriteSlot], List[Tuple[float, int, int, str, float, float, float]]]:
    team = build_vm_team(meta.team_names, db=char_db, loader=vm_loader, loadouts=loadouts)
    if meta.player_obs_speeds:
        for ent in team:
            uid_i = int(getattr(ent, "avatar_id", 0) or 0)
            cands = meta.player_obs_speeds.get(uid_i)
            if not cands:
                continue
            for obs_spd in cands:
                if int(obs_spd) == int(ent.base_speed) and 1e-4 < abs(obs_spd - ent.base_speed) < 0.999:
                    ent.base_speed = float(obs_spd)
                    break
    sim, director, stage_mode = build_stage_for_id(
        meta.stage_id,
        team,
        technique_users=[e.name for e in team],
        force_data_driven=force_data_driven,
        extra_maze_buff_ids=extra_maze_buff_ids,
        entry_element=meta.entry_element,
        entry_toughness=meta.entry_toughness,
    )

    ambiguous_slots: List[AmbiguousMemospriteSlot] = []
    inferred_hits: List[InferredMemospriteHit] = []

    attach_exact_crit_oracle(sim, log_path=log_path, non_crits=non_crits)
    crit_records = _attach_crit_hit_recorder(sim) if record_crits else []

    # 现场逐动三方（官方 TargetInfo 期望 / 日志实录 / 模拟实际）敌方受击一致性检测
    enemy_hit_mismatches: List[EnemyHitMismatch] = []
    # 按 TurnBeginEvent 序号切分敌方回合: (turn_seq, av, enemy_name, sim_hits_set, sim_sp_owners_set, last_skill_meta)
    sim_enemy_turn_records: List[Tuple[int, float, str, Set[str], Set[str], Tuple[int, str, str, Tuple[str, ...]]]] = []
    _audit_turn_seq = [0]
    from simulator.events import BattleEvent as _BE, TurnBeginEvent as _TBE

    def _on_audit_turn_begin(ev: _BE) -> None:
        if isinstance(ev, _TBE):
            _audit_turn_seq[0] += 1

    sim.event_bus.subscribe(_BE, _on_audit_turn_begin)

    def _on_enemy_skill_resolved(
        *,
        av: float,
        enemy_name: str,
        skill_id: int,
        skill_key: str,
        expected_scope: str,
        expected_hits: Tuple[str, ...],
        sim_hits: Tuple[str, ...],
        sim_sp_owners: Tuple[str, ...] = (),
    ) -> None:
        tseq = _audit_turn_seq[0]
        # 1. 现场结构断言：官方 TargetInfo + 当前站位推导的期望命中集合 vs 模拟实际命中集合
        if expected_hits and set(expected_hits) != set(sim_hits):
            enemy_hit_mismatches.append(
                EnemyHitMismatch(
                    av=av,
                    enemy_name=enemy_name,
                    log_hits=(),
                    sim_hits=sim_hits,
                    skill_id=skill_id,
                    skill_key=skill_key,
                    expected_scope=expected_scope,
                    expected_hits=expected_hits,
                )
            )
        # 2. 按敌方回合（TurnBeginEvent）聚合，供与日志 EnemyHitRecord 1 对 1 对撞
        if (
            sim_enemy_turn_records
            and sim_enemy_turn_records[-1][0] == tseq
            and sim_enemy_turn_records[-1][2] == enemy_name
        ):
            sim_enemy_turn_records[-1][3].update(sim_hits)
            sim_enemy_turn_records[-1][4].update(sim_sp_owners)
            sim_enemy_turn_records[-1] = (
                tseq,
                sim_enemy_turn_records[-1][1],
                enemy_name,
                sim_enemy_turn_records[-1][3],
                sim_enemy_turn_records[-1][4],
                (skill_id, skill_key, expected_scope, expected_hits),
            )
        else:
            sim_enemy_turn_records.append(
                (tseq, av, enemy_name, set(sim_hits), set(sim_sp_owners), (skill_id, skill_key, expected_scope, expected_hits))
            )

    sim.on_enemy_skill_resolved = _on_enemy_skill_resolved
    if sim_enemy_hp_out is not None:
        from simulator.events import BattleEvent, DamageAppliedEvent, TurnEndEvent

        def _on_hp_snap(ev: BattleEvent) -> None:
            if isinstance(ev, (DamageAppliedEvent, TurnEndEvent)):
                av_k = round(float(getattr(sim, "current_av", 0.0)), 2)
                for e in getattr(sim, "entities", ()):
                    if getattr(e, "is_enemy", False) and getattr(e, "current_hp", 0.0) > 0.0:
                        sim_enemy_hp_out[(av_k, e.name)] = float(e.current_hp)

        sim.event_bus.subscribe(BattleEvent, _on_hp_snap)
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
            aha_dmg_overrides=aha_dmg_overrides,
            ambiguous_out=ambiguous_slots,
            inferred_out=inferred_hits,
        )
        plugin_mode = ""

    if on_sim_ready is not None:
        on_sim_ready(sim)

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

    # 比对敌方回合实际命中我方本体集合 vs 日志提取受击集合（1 对 1 按 TurnBegin 对齐）
    used_sim_rec: Set[int] = set()
    for h in meta.enemy_hits:
        if not h.hit_allies:
            continue
        log_set = {nm for nm in h.hit_allies if not str(nm).startswith("UID_")}
        has_aoe_sp_union = bool(h.had_hp_drop and len(h.sp_gain_counts) >= 3)
        if not log_set and not has_aoe_sp_union:
            continue
        expected_name = meta.enemy_uid_map.get(h.enemy_uid, f"UID_{h.enemy_uid}")
        best_idx: Optional[int] = None
        best_dt = 0.25
        for idx, (_tseq, s_av, s_atk, _s_tgts, _s_sp_tgts, _sk_meta) in enumerate(sim_enemy_turn_records):
            if idx in used_sim_rec or not _s_tgts:
                continue
            dt = abs(s_av - h.av)
            if dt <= best_dt:
                if s_atk == expected_name or best_idx is None:
                    best_dt = dt
                    best_idx = idx
                    if s_atk == expected_name and dt <= 0.05:
                        break
        if best_idx is not None:
            used_sim_rec.add(best_idx)
            _tseq, _s_av, s_atk, raw_sim_set, raw_sp_set, (sk_id, sk_key, exp_scope, exp_hits) = sim_enemy_turn_records[best_idx]
            # 多段低额全体 AoE（如呼雷 Skill03）可能因单段扣血小未全入 hit_allies，仅全体技能从 sp_gain_counts 补全员
            use_sp_union = bool(exp_scope == "AllEnemy" and has_aoe_sp_union)
            if use_sp_union:
                log_set |= {nm for nm, cnt in h.sp_gain_counts.items() if cnt > 0 and not str(nm).startswith("UID_")}
            if not log_set:
                continue
            raw_set = (raw_sim_set | raw_sp_set) if use_sp_union else raw_sim_set
            sim_set = {nm for nm in raw_set if not str(nm).startswith("UID_")}
            if sim_set != log_set:
                enemy_hit_mismatches.append(
                    EnemyHitMismatch(
                        av=round(h.av, 2),
                        enemy_name=s_atk,
                        log_hits=tuple(sorted(log_set)),
                        sim_hits=tuple(sorted(sim_set)),
                        skill_id=sk_id,
                        skill_key=sk_key,
                        expected_scope=exp_scope,
                        expected_hits=exp_hits,
                    )
                )
        else:
            if has_aoe_sp_union:
                log_set |= {nm for nm, cnt in h.sp_gain_counts.items() if cnt > 0 and not str(nm).startswith("UID_")}
            if not log_set:
                continue
            enemy_hit_mismatches.append(
                EnemyHitMismatch(
                    av=round(h.av, 2),
                    enemy_name=expected_name,
                    log_hits=tuple(sorted(log_set)),
                    sim_hits=(),
                )
            )

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
        enemy_hit_mismatches=enemy_hit_mismatches,
        ult_energy_granted=float(getattr(traj.replay, "ult_energy_granted", 0.0) or 0.0),
    )
    return report, ambiguous_slots, crit_records


def reconcile_log(
    log_path: str,
    *,
    db: Optional[CharacterDB] = None,
    loader: Optional[GameDataLoader] = None,
    team_override: Optional[Sequence[str]] = None,
    loadouts: Optional[Dict[int, Any]] = None,
    force_data_driven: bool = False,
    use_existing_plugin: bool = True,
    resolve_memosprites: bool = True,
    av_budget: Optional[float] = None,
    max_tl_av: Optional[float] = None,
    threshold: float = 0.0001,
    extra_maze_buff_ids: Sequence[int] = (),
    meta: Optional[LogMetadata] = None,
    golden: Optional[Any] = None,
    timeline: Optional[List[Any]] = None,
    on_sim_ready: Optional[Callable[[Any], None]] = None,
) -> ReconcileReport:
    """对任意官方战斗日志执行端到端 VM 对账并返回逐动诊断报告。"""
    char_db = db if db is not None else CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    vm_loader = loader if loader is not None else GameDataLoader()

    if meta is None or (team_override and list(team_override) != list(meta.team_names)):
        meta = extract_log_metadata(log_path, db=char_db, team_override=team_override)
    g = golden if golden is not None else parse_golden_jsonl(log_path)
    tl = list(timeline) if timeline is not None else extract_timeline(log_path)
    if max_tl_av is not None:
        tl = [item for item in tl if item.av < max_tl_av]

    plugin_fn: Optional[Callable[[Any], None]] = None
    non_crits: Set[Any] = set()
    if use_existing_plugin:
        plugin_fn, non_crits = _try_load_existing_plugin(meta.tag)

    overrides: Dict[Tuple[float, int, str], Tuple[str, ...]] = {}
    aha_dmg_overrides: Dict[Tuple[int, str], float] = {}
    has_shielded_aha = any(a.shielded_enemy_uids for a in meta.aha_turns)
    sim_enemy_hp: Dict[Tuple[float, str], float] = {}
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
        loadouts=loadouts,
        memosprite_overrides=overrides,
        aha_dmg_overrides=aha_dmg_overrides,
        sim_enemy_hp_out=sim_enemy_hp if (plugin_fn is None and has_shielded_aha) else None,
        record_crits=True,
        extra_maze_buff_ids=extra_maze_buff_ids,
        on_sim_ready=on_sim_ready,
    )

    non_crit_details: List[str] = []
    seen_nc_states: Set[frozenset] = {frozenset(non_crits)}
    # 自动检测未暴击 (act_idx, hit_idx) 并收敛（允许级联收敛，并自动剔除因早期偏差导致的过期误判）
    for _nc_round in range(8):
        newly_detected = _detect_non_crits_from_trace(
            g, crit_records, details_out=non_crit_details, round_idx=_nc_round
        ) - non_crits
        stale_nc = (
            _prune_stale_non_crits(
                g, crit_records, non_crits, details_out=non_crit_details, round_idx=_nc_round
            )
            if plugin_fn is None and non_crits
            else set()
        )
        next_nc = (set(non_crits) - stale_nc) | newly_detected
        if next_nc == non_crits or frozenset(next_nc) in seen_nc_states:
            break
        non_crits = next_nc
        seen_nc_states.add(frozenset(non_crits))
        sim_enemy_hp.clear()
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
            loadouts=loadouts,
            memosprite_overrides=overrides,
            aha_dmg_overrides=aha_dmg_overrides,
            sim_enemy_hp_out=sim_enemy_hp if (plugin_fn is None and has_shielded_aha) else None,
            record_crits=True,
            extra_maze_buff_ids=extra_maze_buff_ids,
            on_sim_ready=on_sim_ready,
        )

    # 被特殊护盾吸收的阿哈回合伤害：由首个破盾回合的 HP+盾 守恒反推精确吸收量
    if plugin_fn is None and has_shielded_aha and report.max_turn_err >= threshold:
        bad_turns = [td for td in report.turn_diffs if td.err >= threshold]
        if bad_turns:
            first_bad = bad_turns[0]
            shielded_prec = [
                (i, a) for i, a in enumerate(meta.aha_turns)
                if a.av < first_bad.av and a.shielded_enemy_uids
            ]
            if shielded_prec:
                aha_i, aha_rec = shielded_prec[-1]
                calibrated = False
                for euid in aha_rec.shielded_enemy_uids:
                    ename = meta.enemy_uid_map.get(euid, "")
                    if not ename:
                        continue
                    av_k = round(first_bad.av, 2)
                    log_hp = meta.enemy_hp_at_turn_end.get((av_k, ename))
                    sim_hp = sim_enemy_hp.get((av_k, ename))
                    if log_hp is not None and sim_hp is not None and abs(sim_hp - log_hp) > 1.0:
                        delta_aha = (sim_hp - log_hp) - (first_bad.gt_total - first_bad.sim_total)
                        base_aha = sum(
                            float(d) for eu, d in aha_rec.enemy_damages
                            if meta.enemy_uid_map.get(eu) == ename
                        )
                        if abs(delta_aha) > 1.0 and base_aha + delta_aha > 0.0:
                            aha_dmg_overrides[(aha_i, ename)] = base_aha + delta_aha
                            calibrated = True
                if calibrated:
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
                        loadouts=loadouts,
                        memosprite_overrides=overrides,
                        aha_dmg_overrides=aha_dmg_overrides,
                        record_crits=True,
                        extra_maze_buff_ids=extra_maze_buff_ids,
                        on_sim_ready=on_sim_ready,
                    )

    if plugin_fn is None and resolve_memosprites and ambiguous_slots:
        def _later_key(rep: ReconcileReport, focus_av: float) -> Tuple[float, float, float]:
            later_bad = [td for td in rep.turn_diffs if td.av > focus_av + 0.05 and td.err >= threshold]
            if later_bad:
                return (-later_bad[0].av, round(later_bad[0].err, 6), rep.total_err)
            return (float("-inf"), 0.0, rep.total_err)

        def _eval_trial(
            trial_rep: ReconcileReport,
            best_rep: ReconcileReport,
            best_err: float,
            focus_av: float,
        ) -> Optional[float]:
            """评估候选 trial 是否优于当前 best，不劣化更早回合且优先解决后续分叉。"""
            if any(td.av < focus_av - 0.05 and td.err >= threshold for td in trial_rep.turn_diffs):
                return None
            trial_td = next((td for td in trial_rep.turn_diffs if abs(td.av - focus_av) < 0.05), None)
            trial_err = trial_td.err if trial_td is not None else 1.0
            if trial_err < threshold <= best_err:
                return trial_err
            if trial_err < threshold and best_err < threshold:
                if _later_key(trial_rep, focus_av) < _later_key(best_rep, focus_av):
                    return trial_err
                return None
            if trial_err >= threshold and best_err >= threshold and trial_err + 1e-4 < best_err:
                return trial_err
            return None

        resolved_keys: Set[Tuple[float, int, str]] = set()
        for _round in range(8):
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
            for slot in reversed(preceding[-5:]):
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
                        loadouts=loadouts,
                        memosprite_overrides=trial_ov,
                        aha_dmg_overrides=aha_dmg_overrides,
                        record_crits=False,
                        extra_maze_buff_ids=extra_maze_buff_ids,
                    )
                    new_err = _eval_trial(trial_rep, best_report, best_err, first_bad.av)
                    if new_err is not None:
                        best_err = new_err
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
                loadouts=loadouts,
                memosprite_overrides=overrides,
                aha_dmg_overrides=aha_dmg_overrides,
                record_crits=True,
                extra_maze_buff_ids=extra_maze_buff_ids,
                on_sim_ready=on_sim_ready,
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
                    loadouts=loadouts,
                    memosprite_overrides=overrides,
                    aha_dmg_overrides=aha_dmg_overrides,
                    record_crits=True,
                    extra_maze_buff_ids=extra_maze_buff_ids,
                    on_sim_ready=on_sim_ready,
                )

    report.non_crits = set(non_crits)
    report.non_crit_details = list(non_crit_details)
    return report

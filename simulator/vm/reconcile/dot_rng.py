# coding: utf-8
"""通用 Layer-4 DoT 阶段随机分支（RandomConfig / ByRandomChance）追溯与自动对账求解器。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from simulator.actions import DamageType
from simulator.db.character_db import CharacterDB
from simulator.events import BattleEvent, DamageAppliedEvent
from simulator.vm.reconcile.models import LogMetadata, ReconcileReport, _resolve_uid_name

RngSlotKey = Tuple[float, str, str, str, int]


@dataclass(frozen=True)
class GTDotHit:
    """实机日志单次 DoT 伤害事件（由前邻 OnStatChange CurrentHP 锁定受击敌方目标）。"""

    av: float
    target_name: str
    attacker_name: str
    damage: float


@dataclass(frozen=True)
class SimDotHit:
    """模拟器单次 DoT DamageAppliedEvent 记录。"""

    av: float
    target_name: str
    attacker_name: str
    damage: float
    dot_epoch: int = 0


@dataclass(frozen=True)
class RngTraceEntry:
    """单次目标级可调 RNG 抽样记录（仅记录未被 top-level oracle 锁定的调用）。"""

    kind: str  # "RANDCFG" | "CHANCE"
    av: float
    caster_id: str
    target_id: str
    ability_name: str
    weights: Tuple[float, ...]
    n_branches: int
    chosen_idx: int
    seq: int
    dot_epoch: int = 0

    @property
    def key(self) -> RngSlotKey:
        return (self.av, self.caster_id, self.target_id, self.ability_name, self.seq)


def extract_gt_dot_hits(
    log_path: str,
    *,
    meta: Optional[LogMetadata] = None,
    char_db: Optional[CharacterDB] = None,
) -> List[GTDotHit]:
    """从 Veritas JSONL 提取全量实机 DoT 伤害，并与前邻敌方 CurrentHP 目标对齐。"""
    hits: List[GTDotHit] = []
    cur_av = 0.0
    first_enemy_uid: Optional[int] = None
    last_enemy_uid: Optional[int] = None
    prev_enemy_hp: Dict[int, float] = {}
    local_enemy_names: Dict[int, str] = {}
    uid_map = meta.enemy_uid_map if meta is not None else {}

    with open(log_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            entry = json.loads(line)
            ev = entry.get("event")
            data = entry.get("data") or {}

            if ev == "OnBattleEnd":
                break
            if ev == "OnInitializeEnemy":
                enemy = data.get("enemy") or {}
                uid = enemy.get("uid")
                if uid is not None:
                    local_enemy_names[int(uid)] = str(enemy.get("name") or f"UID_{uid}")
                first_enemy_uid = None
                last_enemy_uid = None
            elif ev == "OnTurnBegin":
                cur_av = round(float(data.get("action_value", 0.0) or 0.0), 2)
                first_enemy_uid = None
                last_enemy_uid = None
            elif ev == "OnUseSkill":
                first_enemy_uid = None
                last_enemy_uid = None
            elif ev == "OnStatChange":
                ent = data.get("entity") or {}
                prop = data.get("property") or {}
                if ent.get("team") == "Enemy" and prop.get("type") == "CurrentHP":
                    uid = int(ent.get("uid") or 0)
                    if uid:
                        val = float(prop.get("value", 0.0) or 0.0)
                        prev = prev_enemy_hp.get(uid)
                        prev_enemy_hp[uid] = val
                        if prev is None or val <= prev + 1e-6:
                            if first_enemy_uid is None:
                                first_enemy_uid = uid
                        last_enemy_uid = uid
            elif ev == "OnDamage":
                dmg_type = str(data.get("type") or "")
                tgt_uid = first_enemy_uid if first_enemy_uid is not None else last_enemy_uid
                first_enemy_uid = None
                last_enemy_uid = None
                if dmg_type != "DoT":
                    continue
                attacker = data.get("attacker") or {}
                a_uid = int(attacker.get("uid") or 0)
                a_team = str(attacker.get("team") or "")
                if a_team == "Player":
                    attacker_name = _resolve_uid_name(a_uid, char_db)
                else:
                    attacker_name = uid_map.get(a_uid) or local_enemy_names.get(a_uid) or f"UID_{a_uid}"
                if tgt_uid:
                    target_name = uid_map.get(tgt_uid) or local_enemy_names.get(tgt_uid) or f"UID_{tgt_uid}"
                else:
                    target_name = ""
                dmg = float(data.get("damage", 0.0) or 0.0)
                hits.append(
                    GTDotHit(
                        av=cur_av,
                        target_name=target_name,
                        attacker_name=attacker_name,
                        damage=dmg,
                    )
                )
    return hits


def attach_dot_rng_hooks(
    sim: Any,
    *,
    randcfg_overrides: Optional[Mapping[RngSlotKey, int]] = None,
    chance_overrides: Optional[Mapping[RngSlotKey, bool]] = None,
    rng_trace_out: Optional[List[RngTraceEntry]] = None,
    sim_dot_hits_out: Optional[List[SimDotHit]] = None,
) -> None:
    """挂载目标级 RNG 覆写/追溯钩子及 DoT DamageAppliedEvent 采集器。"""
    rc_ov = dict(randcfg_overrides or {})
    ch_ov = dict(chance_overrides or {})
    rc_counts: Dict[Tuple[float, str, str, str], int] = defaultdict(int)
    ch_counts: Dict[Tuple[float, str, str, str], int] = defaultdict(int)
    dot_epoch_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    pending_slot: List[Optional[Tuple[str, Tuple[float, str, str, str], int]]] = [None]

    def _randcfg_target_provider(
        caster_id: str,
        target_id: str,
        ability_name: str,
        n_branches: int,
        weights: Sequence[float],
    ) -> Optional[int]:
        av = round(float(getattr(sim, "current_av", 0.0) or 0.0), 2)
        base = (av, str(caster_id or ""), str(target_id or ""), str(ability_name or ""))
        seq = rc_counts[base]
        rc_counts[base] = seq + 1
        pending_slot[0] = ("RANDCFG", base, seq)
        return rc_ov.get((*base, seq))

    def _chance_target_provider(
        caster_id: str,
        target_id: str,
        ability_name: str,
        chance: float,
    ) -> Optional[bool]:
        av = round(float(getattr(sim, "current_av", 0.0) or 0.0), 2)
        base = (av, str(caster_id or ""), str(target_id or ""), str(ability_name or ""))
        seq = ch_counts[base]
        ch_counts[base] = seq + 1
        pending_slot[0] = ("CHANCE", base, seq)
        val = ch_ov.get((*base, seq))
        return None if val is None else bool(val)

    def _rng_trace_recorder(
        kind: str,
        av: float,
        caster_id: str,
        target_id: str,
        ability_name: str,
        weights: Sequence[float],
        n_branches: int,
        chosen_idx: int,
    ) -> None:
        pend = pending_slot[0]
        pending_slot[0] = None
        if rng_trace_out is None:
            return
        base = (round(float(av), 2), str(caster_id or ""), str(target_id or ""), str(ability_name or ""))
        if pend is None or pend[0] != kind or pend[1] != base:
            return
        rng_trace_out.append(
            RngTraceEntry(
                kind=kind,
                av=base[0],
                caster_id=base[1],
                target_id=base[2],
                ability_name=base[3],
                weights=tuple(float(w) for w in weights),
                n_branches=int(n_branches),
                chosen_idx=int(chosen_idx),
                seq=pend[2],
                dot_epoch=dot_epoch_counts[(base[2], base[1])],
            )
        )

    sim.random_config_target_provider = _randcfg_target_provider
    sim.random_chance_target_provider = _chance_target_provider
    sim.rng_trace_recorder = _rng_trace_recorder

    if hasattr(sim, "event_bus") and (sim_dot_hits_out is not None or rng_trace_out is not None):

        def _on_dot_dmg(ev: BattleEvent) -> None:
            if isinstance(ev, DamageAppliedEvent) and ev.damage_type == DamageType.DOT:
                tgt = str(ev.target_name or "")
                atk = str(ev.attacker_name or "")
                ep = dot_epoch_counts[(tgt, atk)]
                if sim_dot_hits_out is not None:
                    sim_dot_hits_out.append(
                        SimDotHit(
                            av=round(float(ev.av), 2),
                            target_name=tgt,
                            attacker_name=atk,
                            damage=float(ev.damage),
                            dot_epoch=ep,
                        )
                    )
                dot_epoch_counts[(tgt, atk)] = ep + 1

        sim.event_bus.subscribe(DamageAppliedEvent, _on_dot_dmg)


def _multiset_distance(
    gt_vals: Sequence[float],
    sim_vals: Sequence[float],
    rel_tol: float,
) -> Tuple[int, float, float]:
    """计算两个伤害多重集的精确匹配距离 (unmatched_count, residual_l1, sum_abs_diff)。"""
    n_g = len(gt_vals)
    n_s = len(sim_vals)
    sum_diff = abs(sum(gt_vals) - sum(sim_vals))
    if n_g == 0 and n_s == 0:
        return (0, 0.0, 0.0)

    pairs: List[Tuple[float, int, int]] = []
    for i, gv in enumerate(gt_vals):
        for j, sv in enumerate(sim_vals):
            diff = abs(sv - gv)
            if diff / max(abs(gv), 1.0) <= rel_tol:
                pairs.append((diff, i, j))
    pairs.sort()

    used_g: Set[int] = set()
    used_s: Set[int] = set()
    for _diff, i, j in pairs:
        if i not in used_g and j not in used_s:
            used_g.add(i)
            used_s.add(j)

    rem_g = sorted(gt_vals[i] for i in range(n_g) if i not in used_g)
    rem_s = sorted(sim_vals[j] for j in range(n_s) if j not in used_s)
    unmatched = len(rem_g) + len(rem_s)
    if unmatched == 0:
        return (0, 0.0, sum_diff)

    rem_pairs = sorted((abs(sv - gv), i, j) for i, gv in enumerate(rem_g) for j, sv in enumerate(rem_s))
    r_used_g: Set[int] = set()
    r_used_s: Set[int] = set()
    res_l1 = 0.0
    for diff, i, j in rem_pairs:
        if i not in r_used_g and j not in r_used_s:
            r_used_g.add(i)
            r_used_s.add(j)
            res_l1 += diff
    res_l1 += sum(rem_g[i] for i in range(len(rem_g)) if i not in r_used_g)
    res_l1 += sum(rem_s[j] for j in range(len(rem_s)) if j not in r_used_s)
    return (unmatched, res_l1, sum_diff)


def _align_targets_at_av(
    gt_hits: Sequence[GTDotHit],
    sim_hits: Sequence[SimDotHit],
) -> Dict[str, str]:
    """在同一 AV 内将 GT 目标名对齐到模拟器目标名（同名恒保真，仅未匹配别名按总伤消歧）。"""
    gt_sums: Dict[str, float] = defaultdict(float)
    sim_sums: Dict[str, float] = defaultdict(float)
    for h in gt_hits:
        gt_sums[h.target_name] += h.damage
    for h in sim_hits:
        sim_sums[h.target_name] += h.damage

    mapping: Dict[str, str] = {}
    used_sim: Set[str] = set()
    for gt_t in gt_sums:
        if gt_t in sim_sums:
            mapping[gt_t] = gt_t
            used_sim.add(gt_t)

    unmapped_gt = [t for t in gt_sums if t not in mapping]
    avail_sim = [t for t in sim_sums if t not in used_sim]
    if unmapped_gt and avail_sim:
        pairs = sorted(
            (abs(gt_sums[g] - sim_sums[s]), g, s)
            for g in unmapped_gt
            for s in avail_sim
        )
        for _diff, g, s in pairs:
            if g not in mapping and s not in used_sim:
                mapping[g] = s
                used_sim.add(s)

    for g in unmapped_gt:
        mapping.setdefault(g, g)
    return mapping


def _group_hits_by_av_target(
    gt_hits: Sequence[GTDotHit],
    sim_hits: Sequence[SimDotHit],
) -> Dict[Tuple[float, str], Dict[str, Tuple[List[float], List[float]]]]:
    """按 (av, target_name) -> attacker_name -> (gt_vals, sim_vals) 聚合并做目标对齐。"""
    gt_by_av: Dict[float, List[GTDotHit]] = defaultdict(list)
    sim_by_av: Dict[float, List[SimDotHit]] = defaultdict(list)
    for h in gt_hits:
        gt_by_av[h.av].append(h)
    for h in sim_hits:
        sim_by_av[h.av].append(h)

    grouped: Dict[Tuple[float, str], Dict[str, Tuple[List[float], List[float]]]] = {}
    for av in sorted(set(gt_by_av.keys()) | set(sim_by_av.keys())):
        g_list = gt_by_av.get(av, [])
        s_list = sim_by_av.get(av, [])
        tmap = _align_targets_at_av(g_list, s_list)
        for h in g_list:
            tgt = tmap.get(h.target_name, h.target_name)
            by_atk = grouped.setdefault((av, tgt), {})
            gvals, _svals = by_atk.setdefault(h.attacker_name, ([], []))
            gvals.append(h.damage)
        for h in s_list:
            by_atk = grouped.setdefault((av, h.target_name), {})
            _gvals, svals = by_atk.setdefault(h.attacker_name, ([], []))
            svals.append(h.damage)
    return grouped


def _score_av_target(
    by_atk: Mapping[str, Tuple[List[float], List[float]]],
    rel_tol: float,
) -> Tuple[int, float, float]:
    """汇总某 (av, target_name) 下全部攻击者的多重集误差，并附加总体比例校验。"""
    tot_unmatched = 0
    tot_l1 = 0.0
    tot_sum_diff = 0.0
    for gvals, svals in by_atk.values():
        unm, rl1, sdiff = _multiset_distance(gvals, svals, rel_tol)
        tot_unmatched += unm
        tot_l1 += rl1
        tot_sum_diff += sdiff
    return (tot_unmatched, tot_l1, tot_sum_diff)


def _mismatched_attackers_and_sums(
    gt_hits: Sequence[GTDotHit],
    sim_hits: Sequence[SimDotHit],
    focus_av: float,
    target_name: str,
    rel_tol: float,
) -> Tuple[Set[str], Dict[str, Tuple[float, float]]]:
    """返回指定 (focus_av, target_name) 存在多重集误差的攻击者集合及各攻击者 (gt_sum, sim_sum)。"""
    g_list = [h for h in gt_hits if abs(h.av - focus_av) < 0.05]
    s_list = [h for h in sim_hits if abs(h.av - focus_av) < 0.05]
    tmap = _align_targets_at_av(g_list, s_list)
    by_atk: Dict[str, Tuple[List[float], List[float]]] = {}
    for h in g_list:
        tgt = tmap.get(h.target_name, h.target_name)
        if tgt != target_name:
            continue
        gv, _sv = by_atk.setdefault(h.attacker_name, ([], []))
        gv.append(h.damage)
    for h in s_list:
        if h.target_name != target_name:
            continue
        _gv, sv = by_atk.setdefault(h.attacker_name, ([], []))
        sv.append(h.damage)

    bad_attackers: Set[str] = set()
    sums: Dict[str, Tuple[float, float]] = {}
    for atk, (gvals, svals) in by_atk.items():
        sums[atk] = (sum(gvals), sum(svals))
        sc = _multiset_distance(gvals, svals, rel_tol)
        if sc[0] > 0:
            bad_attackers.add(atk)
    return bad_attackers, sums


def _av_target_dot_signature(
    sim_hits: Sequence[SimDotHit],
    focus_av: float,
    target_name: str,
) -> Tuple[Tuple[str, Tuple[float, ...]], ...]:
    """返回某 (focus_av, target_name) 下各攻击者已排序四舍五入伤害元组，用于识别无影响槽位。"""
    by_atk: Dict[str, List[float]] = defaultdict(list)
    for h in sim_hits:
        if abs(h.av - focus_av) < 0.05 and h.target_name == target_name:
            by_atk[h.attacker_name].append(round(h.damage, 4))
    return tuple((atk, tuple(sorted(vals))) for atk, vals in sorted(by_atk.items()))


def _collect_mismatches(
    gt_hits: Sequence[GTDotHit],
    sim_hits: Sequence[SimDotHit],
    rel_tol: float,
    *,
    max_av: Optional[float] = None,
) -> Tuple[Dict[Tuple[float, str], Tuple[int, float, float]], List[Tuple[float, str, Tuple[int, float, float]]]]:
    """返回全部 (av, target_name) 得分映射及按 AV 升序排列的分歧列表。"""
    grouped = _group_hits_by_av_target(gt_hits, sim_hits)
    scores: Dict[Tuple[float, str], Tuple[int, float, float]] = {}
    bad: List[Tuple[float, str, Tuple[int, float, float]]] = []
    for (av, tgt), by_atk in sorted(grouped.items()):
        if max_av is not None and av > max_av + 1e-6:
            continue
        sc = _score_av_target(by_atk, rel_tol)
        scores[(av, tgt)] = sc
        if sc[0] > 0:
            bad.append((av, tgt, sc))
    return scores, bad


def _is_probe_valid_and_scored(
    focus_av: float,
    target_name: str,
    baseline_scores: Mapping[Tuple[float, str], Tuple[int, float, float]],
    baseline_turn_errs: Mapping[float, float],
    trial_rep: ReconcileReport,
    gt_hits: Sequence[GTDotHit],
    trial_sim_dots: Sequence[SimDotHit],
    rel_tol: float,
    turn_threshold: float,
) -> Optional[Tuple[int, float, float]]:
    """检查候选试算不劣化更早 AV（DoT 与直伤），并返回 (focus_av, target_name) 得分。"""
    for td in trial_rep.turn_diffs:
        if td.av < focus_av - 0.05:
            prev_err = baseline_turn_errs.get(td.av, 0.0)
            if prev_err < turn_threshold and td.err >= turn_threshold:
                return None
            if td.err >= turn_threshold and td.err > prev_err + 1e-4:
                return None

    trial_scores, _ = _collect_mismatches(gt_hits, trial_sim_dots, rel_tol, max_av=focus_av + 0.05)
    for (av_k, tgt_k), base_sc in baseline_scores.items():
        if av_k >= focus_av - 0.05 and not (abs(av_k - focus_av) < 0.05 and tgt_k < target_name):
            continue
        tr_sc = trial_scores.get((av_k, tgt_k), (0, 0.0, 0.0))
        if base_sc[0] == 0 and tr_sc[0] > 0:
            return None
        if tr_sc[0] > base_sc[0]:
            return None
        if tr_sc[0] == base_sc[0] and tr_sc[1] > base_sc[1] + 1.0:
            return None

    return trial_scores.get((focus_av, target_name), (0, 0.0, 0.0))


def _causal_epoch_bounds(
    sim_dots: Sequence[SimDotHit],
    focus_av: float,
    target_name: str,
    caster_id: str,
) -> Tuple[int, Optional[int]]:
    """计算指定 (target_name, caster_id) 在 focus_av 的因果代次边界 (prev_ep, last_ep)。"""
    prev_ep = max(
        (
            h.dot_epoch
            for h in sim_dots
            if h.av < focus_av - 0.05
            and h.target_name == target_name
            and h.attacker_name == caster_id
        ),
        default=-1,
    )
    cur_eps = [
        h.dot_epoch
        for h in sim_dots
        if abs(h.av - focus_av) < 0.05
        and h.target_name == target_name
        and h.attacker_name == caster_id
    ]
    last_ep = max(cur_eps) if cur_eps else None
    return prev_ep, last_ep


def _slot_in_epoch(
    slot: RngTraceEntry,
    prev_ep: int,
    last_ep: Optional[int],
    strict_causal: bool,
) -> bool:
    """判断随机槽位是否属于 focus_av 的因果窗口（禁止修改发生于本轮 DoT 结算之后的槽位）。"""
    if slot.target_id == "":
        return True
    if last_ep is not None and slot.dot_epoch > last_ep:
        return False
    return slot.dot_epoch > prev_ep if strict_causal else True


def _ordered_gt_and_sim_hits_for_caster(
    gt_hits: Sequence[GTDotHit],
    sim_hits: Sequence[SimDotHit],
    focus_av: float,
    target_name: str,
    caster: str,
) -> Tuple[List[float], List[Tuple[int, float]]]:
    """返回指定 (focus_av, target_name, caster) 按结算顺序排列的 GT 伤害与 SIM (dot_epoch, damage) 列表。"""
    g_list = [h for h in gt_hits if abs(h.av - focus_av) < 0.05]
    s_list = [h for h in sim_hits if abs(h.av - focus_av) < 0.05]
    tmap = _align_targets_at_av(g_list, s_list)
    gt_vals = [
        float(h.damage)
        for h in g_list
        if tmap.get(h.target_name, h.target_name) == target_name and h.attacker_name == caster
    ]
    sim_ep_hits = [
        (int(h.dot_epoch), float(h.damage))
        for h in s_list
        if h.target_name == target_name and h.attacker_name == caster
    ]
    return gt_vals, sim_ep_hits


def _sim_hit_for_epoch(
    sim_hits: Sequence[SimDotHit],
    focus_av: float,
    target_name: str,
    caster: str,
    dot_epoch: int,
) -> float:
    """返回指定 (focus_av, target_name, caster, dot_epoch) 的 SIM DoT 伤害合计。"""
    return sum(
        float(h.damage)
        for h in sim_hits
        if abs(h.av - focus_av) < 0.05
        and h.target_name == target_name
        and h.attacker_name == caster
        and h.dot_epoch == dot_epoch
    )


def resolve_dot_rng(
    *,
    gt_hits: Sequence[GTDotHit],
    initial_report: ReconcileReport,
    initial_trace: Sequence[RngTraceEntry],
    initial_sim_dots: Sequence[SimDotHit],
    probe_runner: Callable[
        [Dict[RngSlotKey, int], Dict[RngSlotKey, bool], Optional[float], bool],
        Tuple[ReconcileReport, List[RngTraceEntry], List[SimDotHit]],
    ],
    randcfg_overrides: Optional[Mapping[RngSlotKey, int]] = None,
    chance_overrides: Optional[Mapping[RngSlotKey, bool]] = None,
    final_av: float,
    threshold: float = 0.0001,
    details_out: Optional[List[str]] = None,
) -> Tuple[bool, ReconcileReport, List[RngTraceEntry], List[SimDotHit], Dict[RngSlotKey, int], Dict[RngSlotKey, bool]]:
    """按时间轴逐 (AV, Target) 求解 RandomConfig 与 ByRandomChance，消除 DoT 随机偏差。

    probe_runner(rc_ov, ch_ov, av_budget, record_crits) -> (report, rng_trace, sim_dot_hits)
    """
    if final_av > 0.0:
        gt_hits = [h for h in gt_hits if h.av <= float(final_av) + 1e-6]
    rel_tol = max(min(float(threshold), 1e-4), 1e-5)
    max_solve_av: Optional[float] = float(final_av) if final_av > 0.0 else None
    rc_ov: Dict[RngSlotKey, int] = dict(randcfg_overrides or {})
    ch_ov: Dict[RngSlotKey, bool] = dict(chance_overrides or {})
    report = initial_report
    trace = list(initial_trace)
    sim_dots = list(initial_sim_dots)
    changed = False
    locked_rc_keys: Set[RngSlotKey] = set(rc_ov.keys())
    locked_ch_keys: Set[RngSlotKey] = set(ch_ov.keys())
    attempted_pairs: Set[Tuple[float, str]] = set()
    probe_cnt = [0]
    max_probes_per_pair = 28
    sim_valid_up_to_av = float(final_av) if final_av > 0.0 else float("inf")

    def _probe_budget_for(focus_av: float) -> float:
        return min(float(final_av), focus_av + 0.25) if final_av > 0.0 else focus_av + 0.25

    def _run_target_probe(
        cand_rc: Dict[RngSlotKey, int],
        cand_ch: Dict[RngSlotKey, bool],
        focus_av: float,
    ) -> Tuple[ReconcileReport, List[RngTraceEntry], List[SimDotHit]]:
        probe_cnt[0] += 1
        budget = _probe_budget_for(focus_av)
        return probe_runner(cand_rc, cand_ch, budget, False)

    def _valid_branches(slot: RngTraceEntry) -> List[int]:
        if not slot.weights:
            return list(range(slot.n_branches))
        valid = [b for b in range(slot.n_branches) if b < len(slot.weights) and slot.weights[b] > 0.0]
        return valid if valid else list(range(slot.n_branches))

    def _group_chance_bursts(slots: Sequence[RngTraceEntry]) -> List[List[RngTraceEntry]]:
        grouped: Dict[Tuple[float, str, str, str], List[RngTraceEntry]] = {}
        order: List[Tuple[float, str, str, str]] = []
        for slot in slots:
            bkey = (slot.av, slot.caster_id, slot.target_id, slot.ability_name)
            if bkey not in grouped:
                grouped[bkey] = []
                order.append(bkey)
            grouped[bkey].append(slot)
        bursts: List[List[RngTraceEntry]] = []
        for bkey in reversed(order):
            grp = sorted(grouped[bkey], key=lambda s: s.seq)
            bursts.append(grp)
        bursts.sort(key=lambda grp: grp[0].av, reverse=True)
        return bursts

    for _step in range(max(len(gt_hits) + 8, 32)):
        scores_all, bad_list = _collect_mismatches(gt_hits, sim_dots, rel_tol, max_av=max_solve_av)
        pending_bad = [b for b in bad_list if (b[0], b[1]) not in attempted_pairs]
        if not pending_bad:
            break
        focus_av, target_name, focus_score = pending_bad[0]
        req_budget = _probe_budget_for(focus_av)
        if sim_valid_up_to_av + 1e-6 < req_budget:
            report, trace, sim_dots = _run_target_probe(rc_ov, ch_ov, focus_av)
            sim_valid_up_to_av = req_budget
            scores_all, bad_list = _collect_mismatches(gt_hits, sim_dots, rel_tol, max_av=max_solve_av)
            pending_bad = [b for b in bad_list if (b[0], b[1]) not in attempted_pairs]
            if not pending_bad:
                break
            focus_av, target_name, focus_score = pending_bad[0]
            if _probe_budget_for(focus_av) > sim_valid_up_to_av + 1e-6:
                continue
        if (
            not any(abs(h.av - focus_av) < 0.05 for h in sim_dots)
            and max((h.av for h in sim_dots), default=-1.0) < focus_av - 0.05
        ):
            attempted_pairs.add((focus_av, target_name))
            continue
        attempted_pairs.add((focus_av, target_name))
        probes_before = probe_cnt[0]

        def _pair_cap_hit() -> bool:
            return (probe_cnt[0] - probes_before) >= max_probes_per_pair

        rc_cand_n = sum(
            1
            for e in trace
            if e.kind == "RANDCFG"
            and e.av <= focus_av + 0.05
            and e.target_id in (target_name, "")
            and e.key not in locked_rc_keys
        )
        ch_cand_n = sum(
            1
            for e in trace
            if e.kind == "CHANCE"
            and e.av <= focus_av + 0.05
            and e.target_id in (target_name, "")
            and e.key not in locked_ch_keys
        )
        prefix_scores, _ = _collect_mismatches(gt_hits, sim_dots, rel_tol, max_av=focus_av + 0.05)
        turn_errs = {td.av: td.err for td in report.turn_diffs if td.av < focus_av - 0.05}
        best_score = focus_score
        pair_improved = False
        noop_rc_keys: Set[RngSlotKey] = set()

        def _probe_ch_prefix(
            pool: Sequence[RngTraceEntry],
            k: int,
            flip_to: bool,
            caster: str,
            target_epoch: Optional[int] = None,
        ) -> Tuple[Optional[Tuple[int, float, float]], float, Tuple[ReconcileReport, List[RngTraceEntry], List[SimDotHit]]]:
            cand_ch = dict(ch_ov)
            for s in pool[:k]:
                cand_ch[s.key] = flip_to
            tr_rep, tr_trace, tr_dots = _run_target_probe(rc_ov, cand_ch, focus_av)
            sc = _is_probe_valid_and_scored(
                focus_av,
                target_name,
                prefix_scores,
                turn_errs,
                tr_rep,
                gt_hits,
                tr_dots,
                rel_tol,
                threshold,
            )
            if target_epoch is not None:
                sim_after = _sim_hit_for_epoch(tr_dots, focus_av, target_name, caster, target_epoch)
            else:
                _, sums_tr = _mismatched_attackers_and_sums(gt_hits, tr_dots, focus_av, target_name, rel_tol)
                sim_after = sums_tr.get(caster, (0.0, 0.0))[1]
            return sc, sim_after, (tr_rep, tr_trace, tr_dots)

        def _pick_chance_pool(
            slots: Sequence[RngTraceEntry],
            gt_sum: float,
            sim_sum: float,
        ) -> Tuple[bool, List[RngTraceEntry]]:
            if gt_sum > sim_sum:
                pool = [s for s in slots if not bool(s.chosen_idx)]
                if pool:
                    return True, pool
                return False, [s for s in slots if bool(s.chosen_idx)]
            pool = [s for s in slots if bool(s.chosen_idx)]
            if pool:
                return False, pool
            return True, [s for s in slots if not bool(s.chosen_idx)]

        def _solve_chance_pool(
            pool: Sequence[RngTraceEntry],
            flip_to: bool,
            caster: str,
            *,
            target_epoch: Optional[int] = None,
            target_gt_val: Optional[float] = None,
        ) -> bool:
            nonlocal report, trace, sim_dots, best_score, changed, pair_improved, prefix_scores, sim_valid_up_to_av
            p_len = len(pool)
            if p_len == 0 or _pair_cap_hit():
                return False
            if target_epoch is not None and target_gt_val is not None:
                gt_sum = float(target_gt_val)
                sim_sum = _sim_hit_for_epoch(sim_dots, focus_av, target_name, caster, target_epoch)
            else:
                _, cur_sums = _mismatched_attackers_and_sums(gt_hits, sim_dots, focus_av, target_name, rel_tol)
                gt_sum, sim_sum = cur_sums.get(caster, (0.0, 0.0))

            def _epoch_hit(sc: Optional[Tuple[int, float, float]], s_val: float) -> bool:
                if sc is None:
                    return False
                if sc[0] == 0:
                    return True
                if target_epoch is not None and target_gt_val is not None:
                    return abs(s_val - target_gt_val) / max(abs(target_gt_val), 1.0) <= rel_tol
                return False

            def _commit_eligible(sc: Optional[Tuple[int, float, float]], s_val: float) -> bool:
                if sc is None:
                    return False
                if sc < best_score:
                    return True
                return (
                    target_epoch is not None
                    and target_gt_val is not None
                    and _epoch_hit(sc, s_val)
                    and sc[0] <= best_score[0]
                    and sc[1] <= best_score[1] + 1.0
                )

            def _commit_prefix(k: int, new_sc: Tuple[int, float, float], res: Tuple[ReconcileReport, List[RngTraceEntry], List[SimDotHit]]) -> None:
                nonlocal report, trace, sim_dots, best_score, changed, pair_improved, prefix_scores, sim_valid_up_to_av
                for s in pool[:k]:
                    ch_ov[s.key] = flip_to
                report, trace, sim_dots = res
                sim_valid_up_to_av = _probe_budget_for(focus_av)
                best_score = new_sc
                changed = True
                pair_improved = True
                prefix_scores, _ = _collect_mismatches(gt_hits, sim_dots, rel_tol, max_av=focus_av + 0.05)

            if p_len == 1:
                sc1, s1, res1 = _probe_ch_prefix(pool, 1, flip_to, caster, target_epoch=target_epoch)
                if sc1 is not None and _commit_eligible(sc1, s1):
                    _commit_prefix(1, sc1, res1)
                    return True
                return False

            sc_p, s_p, res_p = _probe_ch_prefix(pool, p_len, flip_to, caster, target_epoch=target_epoch)
            if sc_p is not None and _epoch_hit(sc_p, s_p) and _commit_eligible(sc_p, s_p):
                _commit_prefix(p_len, sc_p, res_p)
                return True

            if (
                sc_p is not None
                and abs(s_p - sim_sum) > 1e-6
                and (sim_sum < gt_sum < s_p or s_p < gt_sum < sim_sum)
                and not _pair_cap_hit()
            ):
                inc = s_p > sim_sum
                k_hat = max(1, min(p_len - 1, int(round(p_len * (gt_sum - sim_sum) / (s_p - sim_sum)))))
                tested: Dict[int, Tuple[Optional[Tuple[int, float, float]], float, Tuple[ReconcileReport, List[RngTraceEntry], List[SimDotHit]]]] = {
                    p_len: (sc_p, s_p, res_p)
                }
                s_by_k: Dict[int, float] = {0: sim_sum, p_len: s_p}
                sc_h, s_h, res_h = _probe_ch_prefix(pool, k_hat, flip_to, caster, target_epoch=target_epoch)
                tested[k_hat] = (sc_h, s_h, res_h)
                if sc_h is not None:
                    s_by_k[k_hat] = s_h
                if sc_h is not None and _epoch_hit(sc_h, s_h) and _commit_eligible(sc_h, s_h):
                    _commit_prefix(k_hat, sc_h, res_h)
                    return True

                lo, hi = 0, p_len
                if sc_h is not None and not _epoch_hit(sc_h, s_h):
                    if (s_h < gt_sum) if inc else (s_h > gt_sum):
                        lo = k_hat
                    else:
                        hi = k_hat
                    for _bstep in range(4):
                        if hi - lo <= 1 or _pair_cap_hit():
                            break
                        s_lo = s_by_k.get(lo)
                        s_hi = s_by_k.get(hi)
                        if s_lo is not None and s_hi is not None and abs(s_hi - s_lo) > 1e-6:
                            mid_est = lo + int(round((hi - lo) * (gt_sum - s_lo) / (s_hi - s_lo)))
                            mid = max(lo + 1, min(hi - 1, mid_est))
                        else:
                            mid = (lo + hi) // 2
                        if mid in tested:
                            mid = (lo + hi) // 2
                            if mid in tested:
                                if mid + 1 < hi and (mid + 1) not in tested:
                                    mid += 1
                                elif mid - 1 > lo and (mid - 1) not in tested:
                                    mid -= 1
                                else:
                                    break
                        sc_m, s_m, res_m = _probe_ch_prefix(pool, mid, flip_to, caster, target_epoch=target_epoch)
                        tested[mid] = (sc_m, s_m, res_m)
                        if sc_m is not None:
                            s_by_k[mid] = s_m
                        if sc_m is not None and _epoch_hit(sc_m, s_m):
                            if _commit_eligible(sc_m, s_m):
                                _commit_prefix(mid, sc_m, res_m)
                                return True
                            break
                        if sc_m is None:
                            break
                        if (s_m < gt_sum) if inc else (s_m > gt_sum):
                            lo = mid
                        else:
                            hi = mid

                best_k: Optional[int] = None
                best_k_sc = best_score
                best_k_res: Optional[Tuple[ReconcileReport, List[RngTraceEntry], List[SimDotHit]]] = None
                for tk, (tsc, _ts, tres) in tested.items():
                    if tsc is not None and tsc < best_k_sc:
                        best_k_sc = tsc
                        best_k = tk
                        best_k_res = tres
                if best_k is not None and best_k_res is not None:
                    _commit_prefix(best_k, best_k_sc, best_k_res)
                    return True
                return False

            if sc_p is not None and _commit_eligible(sc_p, s_p):
                _commit_prefix(p_len, sc_p, res_p)
                return True

            if sc_p is not None:
                if abs(s_p - sim_sum) <= 1e-6:
                    return False
                if (gt_sum - sim_sum) * (s_p - sim_sum) < 0.0:
                    return False

            any_single = False
            noop_streak = 0
            for s in list(reversed(pool))[:6]:
                if _pair_cap_hit():
                    break
                sc_s, ss, res_s = _probe_ch_prefix([s], 1, flip_to, caster, target_epoch=target_epoch)
                if sc_s is not None and _commit_eligible(sc_s, ss):
                    ch_ov[s.key] = flip_to
                    report, trace, sim_dots = res_s
                    sim_valid_up_to_av = _probe_budget_for(focus_av)
                    best_score = sc_s
                    changed = True
                    pair_improved = True
                    any_single = True
                    noop_streak = 0
                    prefix_scores, _ = _collect_mismatches(gt_hits, sim_dots, rel_tol, max_av=focus_av + 0.05)
                    if _epoch_hit(sc_s, ss):
                        break
                    sim_sum = ss
                else:
                    if sc_s is not None and abs(ss - sim_sum) <= 1e-6:
                        noop_streak += 1
                        if noop_streak >= 2:
                            break
                    else:
                        noop_streak = 0
            return any_single

        for _inner in range(2):
            if best_score[0] == 0 or _pair_cap_hit():
                break

            # 1) 求解 RANDCFG 槽位（因果代次优先 + preferred_branch 优先 + noop 剪枝 + 尾段双槽回退）
            preferred_branch: Dict[str, int] = {}
            rc_causal_improved = False
            tested_rc_keys: Set[RngSlotKey] = set()
            for strict_causal in (True, False):
                if best_score[0] == 0 or _pair_cap_hit():
                    break
                if not strict_causal:
                    if rc_causal_improved:
                        break
                    bad_attackers, _ = _mismatched_attackers_and_sums(gt_hits, sim_dots, focus_av, target_name, rel_tol)
                    has_older_rc = False
                    for e in trace:
                        if (
                            e.kind == "RANDCFG"
                            and e.av <= focus_av + 0.05
                            and e.target_id in (target_name, "")
                            and e.key not in locked_rc_keys
                            and e.key not in noop_rc_keys
                            and e.key not in tested_rc_keys
                            and e.caster_id in bad_attackers
                        ):
                            b_ep = _causal_epoch_bounds(sim_dots, focus_av, target_name, e.caster_id)
                            if _slot_in_epoch(e, *b_ep, strict_causal=False):
                                has_older_rc = True
                                break
                    if not has_older_rc:
                        break

                for _rc_sweep in range(3):
                    if best_score[0] == 0 or _pair_cap_hit():
                        break
                    bad_attackers, _ = _mismatched_attackers_and_sums(gt_hits, sim_dots, focus_av, target_name, rel_tol)
                    ep_bounds: Dict[str, Tuple[int, Optional[int]]] = {}

                    def _bounds_for(c_id: str) -> Tuple[int, Optional[int]]:
                        b = ep_bounds.get(c_id)
                        if b is None:
                            b = _causal_epoch_bounds(sim_dots, focus_av, target_name, c_id)
                            ep_bounds[c_id] = b
                        return b

                    all_rc = [
                        e
                        for e in trace
                        if e.kind == "RANDCFG"
                        and e.av <= focus_av + 0.05
                        and e.target_id in (target_name, "")
                        and e.key not in locked_rc_keys
                        and e.key not in noop_rc_keys
                        and (strict_causal or e.key not in tested_rc_keys)
                        and _slot_in_epoch(e, *_bounds_for(e.caster_id), strict_causal=strict_causal)
                    ]
                    scoped_rc = [e for e in all_rc if e.caster_id in bad_attackers]
                    if scoped_rc:
                        rc_slots = scoped_rc
                    else:
                        has_scoped_ch = any(
                            e.kind == "CHANCE"
                            and e.av <= focus_av + 0.05
                            and e.target_id in (target_name, "")
                            and e.key not in locked_ch_keys
                            and e.caster_id in bad_attackers
                            for e in trace
                        )
                        rc_slots = [] if has_scoped_ch else all_rc
                    if not rc_slots:
                        break
                    sweep_improved = False
                    for slot in reversed(rc_slots):
                        if _pair_cap_hit():
                            break
                        if scoped_rc and slot.caster_id not in bad_attackers:
                            continue
                        cands = [b for b in _valid_branches(slot) if b != slot.chosen_idx]
                        if not cands:
                            continue
                        pref = preferred_branch.get(slot.caster_id)
                        if pref is not None and pref in cands:
                            cands = [pref] + [b for b in cands if b != pref]
                        base_sig = _av_target_dot_signature(sim_dots, focus_av, target_name)
                        all_noop = True
                        slot_best_b: Optional[int] = None
                        slot_best_res: Optional[Tuple[ReconcileReport, List[RngTraceEntry], List[SimDotHit]]] = None
                        slot_best_sc = best_score
                        aborted_mid_slot = False
                        for b in cands:
                            if _pair_cap_hit():
                                aborted_mid_slot = True
                                break
                            cand_rc = dict(rc_ov)
                            cand_rc[slot.key] = b
                            tr_rep, tr_trace, tr_dots = _run_target_probe(cand_rc, ch_ov, focus_av)
                            if all_noop and _av_target_dot_signature(tr_dots, focus_av, target_name) != base_sig:
                                all_noop = False
                            sc = _is_probe_valid_and_scored(
                                focus_av,
                                target_name,
                                prefix_scores,
                                turn_errs,
                                tr_rep,
                                gt_hits,
                                tr_dots,
                                rel_tol,
                                threshold,
                            )
                            if sc is not None and sc < slot_best_sc:
                                slot_best_sc = sc
                                slot_best_b = b
                                slot_best_res = (tr_rep, tr_trace, tr_dots)
                                if sc[0] == 0:
                                    break
                                bad_after, _ = _mismatched_attackers_and_sums(
                                    gt_hits, tr_dots, focus_av, target_name, rel_tol
                                )
                                if slot.caster_id not in bad_after:
                                    break
                        if slot_best_b is not None and slot_best_res is not None:
                            rc_ov[slot.key] = slot_best_b
                            preferred_branch[slot.caster_id] = slot_best_b
                            report, trace, sim_dots = slot_best_res
                            sim_valid_up_to_av = _probe_budget_for(focus_av)
                            best_score = slot_best_sc
                            changed = True
                            pair_improved = True
                            sweep_improved = True
                            if strict_causal:
                                rc_causal_improved = True
                            prefix_scores, _ = _collect_mismatches(gt_hits, sim_dots, rel_tol, max_av=focus_av + 0.05)
                            bad_attackers, _ = _mismatched_attackers_and_sums(
                                gt_hits, sim_dots, focus_av, target_name, rel_tol
                            )
                            if best_score[0] == 0 or (scoped_rc and not any(e.caster_id in bad_attackers for e in rc_slots)):
                                break
                        elif not aborted_mid_slot:
                            tested_rc_keys.add(slot.key)
                            if all_noop:
                                noop_rc_keys.add(slot.key)
                    if not sweep_improved:
                        break
                    if scoped_rc and not any(e.caster_id in bad_attackers for e in rc_slots):
                        break

            # 若单槽位未完全归零，仅对当前误差攻击者最近至多 3 个有效 RANDCFG 槽位做双槽联合试探
            if best_score[0] > 0 and not _pair_cap_hit():
                bad_attackers, _ = _mismatched_attackers_and_sums(gt_hits, sim_dots, focus_av, target_name, rel_tol)
                ep_bounds_pair: Dict[str, Tuple[int, Optional[int]]] = {}

                def _pair_bounds(c_id: str) -> Tuple[int, Optional[int]]:
                    b = ep_bounds_pair.get(c_id)
                    if b is None:
                        b = _causal_epoch_bounds(sim_dots, focus_av, target_name, c_id)
                        ep_bounds_pair[c_id] = b
                    return b

                rem_rc = [
                    e
                    for e in trace
                    if e.kind == "RANDCFG"
                    and e.av <= focus_av + 0.05
                    and e.target_id in (target_name, "")
                    and e.key not in locked_rc_keys
                    and e.key not in noop_rc_keys
                    and e.caster_id in bad_attackers
                    and _slot_in_epoch(e, *_pair_bounds(e.caster_id), strict_causal=False)
                ][-3:]
                if len(rem_rc) >= 2:
                    found_pair = False
                    for idx_a in range(len(rem_rc)):
                        if found_pair or _pair_cap_hit():
                            break
                        sa = rem_rc[idx_a]
                        for idx_b in range(idx_a + 1, len(rem_rc)):
                            if found_pair or _pair_cap_hit():
                                break
                            sb = rem_rc[idx_b]
                            for ba in [b for b in _valid_branches(sa) if b != sa.chosen_idx]:
                                if found_pair or _pair_cap_hit():
                                    break
                                for bb in [b for b in _valid_branches(sb) if b != sb.chosen_idx]:
                                    if _pair_cap_hit():
                                        break
                                    cand_rc = dict(rc_ov)
                                    cand_rc[sa.key] = ba
                                    cand_rc[sb.key] = bb
                                    tr_rep, tr_trace, tr_dots = _run_target_probe(cand_rc, ch_ov, focus_av)
                                    sc = _is_probe_valid_and_scored(
                                        focus_av,
                                        target_name,
                                        prefix_scores,
                                        turn_errs,
                                        tr_rep,
                                        gt_hits,
                                        tr_dots,
                                        rel_tol,
                                        threshold,
                                    )
                                    if sc is not None and sc < best_score:
                                        rc_ov[sa.key] = ba
                                        rc_ov[sb.key] = bb
                                        report, trace, sim_dots = tr_rep, tr_trace, tr_dots
                                        sim_valid_up_to_av = _probe_budget_for(focus_av)
                                        best_score = sc
                                        changed = True
                                        pair_improved = True
                                        prefix_scores, _ = _collect_mismatches(
                                            gt_hits, sim_dots, rel_tol, max_av=focus_av + 0.05
                                        )
                                        if best_score[0] == 0:
                                            found_pair = True
                                            break

            if best_score[0] == 0 or _pair_cap_hit():
                break

            # 2) 求解 CHANCE 槽位（按 DoT epoch 逐段聚焦求解，单 epoch 走因果池，未归零再按 burst 回退）
            bad_attackers, _ = _mismatched_attackers_and_sums(gt_hits, sim_dots, focus_av, target_name, rel_tol)
            for caster in sorted(bad_attackers):
                if best_score[0] == 0 or _pair_cap_hit():
                    break
                prev_ep, last_ep = _causal_epoch_bounds(sim_dots, focus_av, target_name, caster)
                gt_vals_ep, sim_ep_hits = _ordered_gt_and_sim_hits_for_caster(
                    gt_hits, sim_dots, focus_av, target_name, caster
                )
                if len(sim_ep_hits) > 1 and len(gt_vals_ep) == len(sim_ep_hits):
                    for idx in range(len(sim_ep_hits)):
                        gt_vals_ep, sim_ep_hits = _ordered_gt_and_sim_hits_for_caster(
                            gt_hits, sim_dots, focus_av, target_name, caster
                        )
                        if idx >= len(sim_ep_hits) or idx >= len(gt_vals_ep) or best_score[0] == 0 or _pair_cap_hit():
                            break
                        ep, sim_v = sim_ep_hits[idx]
                        gt_v = gt_vals_ep[idx]
                        if abs(sim_v - gt_v) / max(abs(gt_v), 1.0) <= rel_tol:
                            continue
                        lo_ep = prev_ep if idx == 0 else sim_ep_hits[idx - 1][0]
                        ep_ch = sorted(
                            [
                                e
                                for e in trace
                                if e.kind == "CHANCE"
                                and e.av <= focus_av + 0.05
                                and e.target_id in (target_name, "")
                                and e.key not in locked_ch_keys
                                and e.caster_id == caster
                                and (e.target_id == "" or lo_ep < e.dot_epoch <= ep)
                            ],
                            key=lambda e: (e.av, e.seq),
                        )
                        if ep_ch:
                            flip_to, pool = _pick_chance_pool(ep_ch, gt_v, sim_v)
                            if pool:
                                _solve_chance_pool(
                                    pool,
                                    flip_to,
                                    caster,
                                    target_epoch=ep,
                                    target_gt_val=gt_v,
                                )
                else:
                    causal_ch = sorted(
                        [
                            e
                            for e in trace
                            if e.kind == "CHANCE"
                            and e.av <= focus_av + 0.05
                            and e.target_id in (target_name, "")
                            and e.key not in locked_ch_keys
                            and e.caster_id == caster
                            and _slot_in_epoch(e, prev_ep, last_ep, strict_causal=True)
                        ],
                        key=lambda e: (e.av, e.seq),
                    )
                    if causal_ch:
                        _, cur_sums = _mismatched_attackers_and_sums(gt_hits, sim_dots, focus_av, target_name, rel_tol)
                        gt_sum, sim_sum = cur_sums.get(caster, (0.0, 0.0))
                        flip_to, pool = _pick_chance_pool(causal_ch, gt_sum, sim_sum)
                        if pool:
                            _solve_chance_pool(pool, flip_to, caster)

                cur_bad, _cur_sums = _mismatched_attackers_and_sums(gt_hits, sim_dots, focus_av, target_name, rel_tol)
                if best_score[0] > 0 and caster in cur_bad and not _pair_cap_hit():
                    older_ch = [
                        e
                        for e in trace
                        if e.kind == "CHANCE"
                        and e.av <= focus_av + 0.05
                        and e.target_id in (target_name, "")
                        and e.key not in locked_ch_keys
                        and e.key not in ch_ov
                        and e.caster_id == caster
                        and _slot_in_epoch(e, prev_ep, last_ep, strict_causal=False)
                    ]
                    if older_ch:
                        for burst in _group_chance_bursts(older_ch)[:3]:
                            if best_score[0] == 0 or _pair_cap_hit():
                                break
                            cur_bad2, cur_sums2 = _mismatched_attackers_and_sums(
                                gt_hits, sim_dots, focus_av, target_name, rel_tol
                            )
                            if caster not in cur_bad2:
                                break
                            gt_sum2, sim_sum2 = cur_sums2.get(caster, (0.0, 0.0))
                            flip_to2, b_pool = _pick_chance_pool(burst, gt_sum2, sim_sum2)
                            if b_pool:
                                _solve_chance_pool(b_pool, flip_to2, caster)

            if not pair_improved:
                break

        for k in rc_ov:
            if k[0] <= focus_av + 0.05 and k[2] in (target_name, ""):
                locked_rc_keys.add(k)
        for k in ch_ov:
            if k[0] <= focus_av + 0.05 and k[2] in (target_name, ""):
                locked_ch_keys.add(k)

        if details_out is not None:
            details_out.append(
                f"[DOT_RNG] av={focus_av:.2f} tgt={target_name} "
                f"score=({focus_score[0]},{focus_score[1]:.1f})->({best_score[0]},{best_score[1]:.1f}) "
                f"probes={probe_cnt[0] - probes_before} rc_cands={rc_cand_n} ch_cands={ch_cand_n}"
            )

        if pair_improved:
            # 锁定修正生效后重置已探视集合，仅跳过无法改善的旧点，确保修正引发的新增 AV 可被重扫
            attempted_pairs = {p for p in attempted_pairs if p[0] <= focus_av + 0.05}

    if changed:
        full_budget = float(final_av) if final_av > 0.0 else None
        report, trace, sim_dots = probe_runner(rc_ov, ch_ov, full_budget, True)
    if details_out is not None and (changed or attempted_pairs):
        details_out.append(
            f"[DOT_RNG_SUM] changed={changed} probes={probe_cnt[0]} "
            f"rc_overrides={len(rc_ov)} ch_overrides={len(ch_ov)}"
        )
    return changed, report, trace, sim_dots, rc_ov, ch_ov

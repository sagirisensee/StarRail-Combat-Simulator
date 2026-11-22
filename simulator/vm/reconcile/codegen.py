# coding: utf-8
"""对账报告格式化与插件/单元测试代码生成器（从 reconcile_generator.py 拆分）。"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Set, Tuple

from simulator.vm.factory import UID_TO_NAME
from .models import EnemyHitRecord, LogMetadata, ROOT_DIR, ReconcileReport


def format_report(report: ReconcileReport, *, threshold: float = 0.0001, verbose: bool = False) -> str:
    """将 ReconcileReport 格式化为可读的终端诊断报告。"""
    over = [td for td in report.turn_diffs if td.err >= threshold]
    lines = [
        f"=== VM Reconcile Report: {os.path.basename(report.meta.log_path)} ===",
        f"Stage      : {report.meta.stage_id} ({report.stage_mode})",
        f"Team       : {report.meta.team_names} (UIDs={report.meta.team_uids})",
        f"RNG Plugin : {report.plugin_mode}",
        f"Trajectory : turns={report.turn_matched}/{report.turn_total} ults={report.ult_matched}/{report.ult_total} "
        f"sp_grant={report.sp_granted} mem_grant={report.memoria_granted:.1f} forced/failed={report.forced_or_failed}",
        f"Damage     : GT={report.golden_total_damage:,.2f}  SIM={report.sim_total_damage:,.2f}  "
        f"total_err={report.total_err:.4%}  max_turn_err={report.max_turn_err:.4%}  over_{threshold:.2%}={len(over)}/{len(report.turn_diffs)}",
    ]
    if report.inferred_memosprite_hits:
        lines.append("Memosprite / skip inferences:")
        for hit in report.inferred_memosprite_hits:
            lines.append(
                f"  AV={hit.av:6.2f} enemy={hit.enemy_uid} kind={hit.kind:7s} -> {list(hit.targets)} [{hit.source}]"
            )
    rows = report.turn_diffs if verbose else over
    if rows:
        lines.append("")
        lines.append(f"Per-turn breakdown ({'ALL' if verbose else f'>= {threshold:.2%}'}):")
        for td in rows:
            lines.append(
                f"  AV={td.av:6.2f}  err={td.err:7.3%}  GT={td.gt_total:11.2f}  SIM={td.sim_total:11.2f}  "
                f"diff={td.sim_total - td.gt_total:+10.2f}  atks={td.attackers}"
            )
            for cat, (gv, sv) in td.breakdown.items():
                if abs(sv - gv) > 1.0:
                    ce = (sv - gv) / gv if gv > 0 else 1.0
                    lines.append(f"      {cat:28s} GT={gv:10.2f} SIM={sv:10.2f} ({ce:+.3%})")
    return "\n".join(lines)


def emit_alignment_test(
    report: ReconcileReport,
    *,
    output_path: Optional[str] = None,
    force_data_driven: bool = False,
) -> str:
    """根据对账报告生成标准 unittest 对账脚本并返回写入路径。"""
    meta = report.meta
    if output_path is None:
        fname = f"test_vm_{meta.stage_id}_{meta.tag}_alignment.py"
        output_path = os.path.join(ROOT_DIR, "simulator", "vm", fname)

    team_literal = repr(meta.team_names)
    rel_log = os.path.basename(meta.log_path)
    code = f'''# coding: utf-8
"""自动生成的 VM 对账测试：stage={meta.stage_id}, log={rel_log}。"""

import os
import unittest

from simulator.vm.reconcile_generator import reconcile_log

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVMStage{meta.stage_id}_{meta.tag}Alignment(unittest.TestCase):
    def test_alignment(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", {rel_log!r})
        rep = reconcile_log(
            log_path,
            team_override={team_literal},
            force_data_driven={force_data_driven!r},
        )
        self.assertEqual(rep.turn_matched, rep.turn_total)
        self.assertEqual(rep.ult_matched, rep.ult_total)
        self.assertEqual(rep.sp_granted, 0)
        self.assertEqual(rep.memoria_granted, 0.0)
        self.assertEqual(rep.forced_or_failed, 0)
        self.assertLess(rep.total_err, 0.0001, f"总伤偏差过大: {{rep.total_err:.4%}}")
        for td in rep.turn_diffs:
            self.assertLess(
                td.err,
                0.0001,
                f"AV={{td.av:.2f}} 单动偏差过大: {{td.err:.3%}} (GT={{td.gt_total:.2f}}, SIM={{td.sim_total:.2f}})",
            )


if __name__ == "__main__":
    unittest.main()
'''
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(code)
    return output_path


def emit_plugin(
    meta: LogMetadata,
    *,
    output_path: Optional[str] = None,
    non_crits: Optional[Set[Tuple[int, int]]] = None,
) -> str:
    """根据实机日志元数据自动提取受击目标、攻击目标、跳过回合、阿哈弹射与未暴击台账，生成标准自包含 plugin 文件。"""
    tag = meta.tag
    if output_path is None:
        fname = f"log_{tag}.py"
        output_path = os.path.join(ROOT_DIR, "simulator", "plugins", fname)

    lines = [
        "# coding: utf-8",
        f'"""实机日志 battle_{tag}.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""',
        "",
        "from typing import Any, Dict, List, Optional, Set, Tuple",
        "from simulator.plugins._helpers import (",
        "    find_ally as _find_ally,",
        "    find_memosprite_name as _find_memosprite_name,",
        "    find_memosprite_of as _find_memosprite_of,",
        ")",
        "",
    ]

    if non_crits:
        lines.append("# 实机自动逆推未暴击台账 (act_idx, hit_idx)")
        lines.append(f"NON_CRITS: Set[Tuple[int, int]] = {set(non_crits)!r}")
        lines.append("")

    lines.extend([
        "",
        f"def attach_log_{tag}_plugin(sim: Any) -> None:",
        f'    """挂载 battle_{tag}.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""',
        "",
        f"    def _target_{tag}_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:",
        '        av = float(getattr(sim, "current_av", 0.0))',
        '        att_name = str(getattr(attacker, "name", "") or "")',
        '        is_enemy = getattr(attacker, "is_enemy", False)',
        "",
    ])

    if meta.player_enemy_targets:
        lines.append("        # 1. 我方攻击敌方单体锁定")
        lines.append("        if not is_enemy and living and all(getattr(e, 'is_enemy', False) for e in living):")
        for (p_av, p_name), enames in sorted(meta.player_enemy_targets.items()):
            lines.append(f"            if abs(av - {p_av:.2f}) < 0.05 and att_name == {p_name!r}:")
            lines.append(f"                tgts = {enames!r}")
            lines.append("                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])")
        lines.append("")

    if meta.servant_targets:
        lines.append("        # 1b. 我方忆灵技主目标（按召唤师归属 + 施放顺序游标）")
        lines.append(
            "        if (not is_enemy and getattr(attacker, 'is_memosprite', False) and living"
            " and all(getattr(e, 'is_enemy', False) for e in living)):"
        )
        lines.append('            _master = str(getattr(attacker, "master_name", "") or "")')
        for (p_av, p_name), seq in sorted(meta.servant_targets.items()):
            lines.append(f"            if abs(av - {p_av:.2f}) < 0.05 and _master == {p_name!r}:")
            lines.append(f"                _seq = {seq!r}")
            lines.append(f"                _key = ({p_av:.2f}, {p_name!r})")
            lines.append("                _idx = _servant_cursor.get(_key, 0)")
            lines.append("                _servant_cursor[_key] = _idx + 1")
            lines.append("                if _idx >= len(_seq) or _seq[_idx] is None: return None")
            lines.append("                return _find_ally(living, _seq[_idx])")
        lines.append("")

    if meta.ally_ult_targets:
        lines.append("        # 2. 我方辅助单点技能目标")
        for caster, tgts in sorted(meta.ally_ult_targets.items()):
            lines.append(f"        if att_name == {caster!r}:")
            lines.append(f"            tgts = {tgts!r}")
            lines.append("            return _find_ally(living, tgts[0]) if tgts else None")
        lines.append("")

    lines.append("        # 3. 敌方回合主受击目标")
    hits_by_key: Dict[Tuple[float, str], List[EnemyHitRecord]] = {}
    for h in meta.enemy_hits:
        ename = meta.enemy_uid_map.get(h.enemy_uid, "")
        if not ename:
            continue
        if h.first_memo_owner or (h.had_hp_drop and h.hit_allies) or (not h.had_hp_drop and h.sp_gain_counts):
            hits_by_key.setdefault((h.av, ename), []).append(h)

    def _fmt_primary_ret(h: EnemyHitRecord) -> str:
        if h.first_memo_owner:
            return f"_find_memosprite_of(living, {h.first_memo_owner!r})"
        if h.had_hp_drop and h.hit_allies:
            return f"_find_ally(living, {h.hit_allies[0]!r})"
        memo_owner = next(iter(h.sp_gain_counts.keys()))
        return f"_find_memosprite_of(living, {memo_owner!r})"

    has_multi_turn = any(len(v) > 1 for v in hits_by_key.values())
    if has_multi_turn:
        lines.insert(
            lines.index(f"    def _target_{tag}_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:"),
            "    _same_av_turn_slots: Dict[Tuple[str, str], List[int]] = {}",
        )
    if meta.servant_targets:
        _provider_def = lines.index(
            f"    def _target_{tag}_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:"
        )
        lines.insert(_provider_def, "")
        lines.insert(_provider_def, "    _servant_cursor: Dict[Tuple[float, str], int] = {}")
    for (hav, ename), hlist in hits_by_key.items():
        if len(hlist) == 1:
            lines.append(f"        if abs(av - {hav:.2f}) < 0.05 and att_name == {ename!r}:")
            lines.append(f"            return {_fmt_primary_ret(hlist[0])}")
        else:
            lines.append(f"        if abs(av - {hav:.2f}) < 0.05 and att_name == {ename!r}:")
            lines.append("            _tid = int(getattr(sim, '_turn_id', 0))")
            lines.append(f"            _slots = _same_av_turn_slots.setdefault(('{hav:.2f}', {ename!r}), [])")
            lines.append("            if _tid not in _slots: _slots.append(_tid)")
            lines.append("            _slot_idx = _slots.index(_tid)")
            for idx_i, hi in enumerate(hlist):
                cond = "if" if idx_i == 0 else "elif"
                if idx_i < len(hlist) - 1:
                    lines.append(f"            {cond} _slot_idx == {idx_i}: return {_fmt_primary_ret(hi)}")
                else:
                    lines.append(f"            return {_fmt_primary_ret(hi)}")
    lines.append("        return None")
    lines.append("")

    lines.extend([
        f"    def _blast_{tag}_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:",
        '        av = float(getattr(sim, "current_av", 0.0))',
        '        att_name = str(getattr(attacker, "name", "") or "")',
    ])
    seen_blast = set()
    for h in meta.enemy_hits:
        ename = meta.enemy_uid_map.get(h.enemy_uid, "")
        if not ename:
            continue
        k = (h.av, ename)
        if k in seen_blast:
            continue
        seen_blast.add(k)
        if h.first_memo_owner:
            extra_chars = list(h.hit_allies)
            memo_owners = [
                ow for ow, sp_c in h.sp_gain_counts.items()
                if ow != h.first_memo_owner and (
                    (ow in h.hit_allies and sp_c >= 2 * h.hit_counts.get(ow, 0) > 0)
                    or (ow not in h.hit_allies and sp_c > 0)
                )
            ]
        else:
            extra_chars = h.hit_allies[1:] if len(h.hit_allies) > 1 else []
            memo_owners = [
                ow for ow, sp_c in h.sp_gain_counts.items()
                if (ow in h.hit_allies and sp_c >= 2 * h.hit_counts.get(ow, 0) > 0)
                or (h.had_hp_drop and h.hit_allies and ow not in h.hit_allies and sp_c > 0)
            ]
        if extra_chars or memo_owners:
            lines.append(f"        if abs(av - {h.av:.2f}) < 0.05 and att_name == {ename!r}:")
            lines.append("            out: List[Any] = []")
            if extra_chars:
                lines.append(f"            for n in {extra_chars!r}:")
                lines.append("                ent = _find_ally(living, n)")
                lines.append("                if ent is not None and ent not in out: out.append(ent)")
            if memo_owners:
                lines.append(f"            for ow in {memo_owners!r}:")
                lines.append("                m_ent = _find_memosprite_of(living, ow)")
                lines.append("                if m_ent is not None and m_ent not in out: out.append(m_ent)")
            lines.append("            return out")
    lines.append("        return []")
    lines.append("")

    lines.extend([
        f"    def _enemy_attack_skip_{tag}(attacker: Any, av: float) -> bool:",
        '        att_name = str(getattr(attacker, "name", "") or "")',
    ])
    skip_conds = []
    seen_skip = set()
    for h in meta.enemy_hits:
        ename = meta.enemy_uid_map.get(h.enemy_uid, "")
        if not ename:
            continue
        k = (h.av, ename)
        if k in seen_skip:
            continue
        seen_skip.add(k)
        if not h.had_hp_drop and not h.sp_gain_counts and not h.had_passive_heal:
            skip_conds.append(f"(att_name == {ename!r} and abs(av - {h.av:.2f}) < 0.05)")
    if skip_conds:
        lines.append(f"        return {' or '.join(skip_conds)}")
    else:
        lines.append("        return False")
    lines.append("")

    ww_names = tuple(sorted({meta.enemy_uid_map[u] for u in meta.windwalk_enemy_uids if u in meta.enemy_uid_map}))
    lines.extend([
        f"    def _enemy_windwalk_{tag}(eagle_name: str, generation: int, idx: int) -> bool:",
        f"        return eagle_name in {ww_names!r}",
        "",
    ])

    retarget_pairs = [
        (p_av, meta.enemy_uid_map.get(c_uid) or UID_TO_NAME.get(c_uid, ""), meta.enemy_uid_map.get(v_uid, ""))
        for p_av, c_uid, v_uid in meta.enemy_retarget_picks
        if (c_uid in meta.enemy_uid_map or c_uid in UID_TO_NAME) and v_uid in meta.enemy_uid_map
    ]
    lines.extend([
        f"    def _enemy_retarget_{tag}(caster: Any, candidates: List[Any]) -> Optional[Any]:",
        '        av = float(getattr(sim, "current_av", 0.0))',
        '        cname = getattr(caster, "name", "")',
    ])
    for p_av, cname, vname in retarget_pairs:
        lines.append(f"        if abs(av - {p_av:.2f}) < 0.05 and cname == {cname!r}:")
        lines.append("            for e in candidates:")
        lines.append(f"                if getattr(e, 'name', '') == {vname!r}: return e")
    lines.extend([
        "        return None",
        "",
    ])

    lines.extend([
        f"    sim.target_provider = _target_{tag}_provider",
        f"    sim.blast_target_provider = _blast_{tag}_provider",
        f"    sim.enemy_attack_skip_provider = _enemy_attack_skip_{tag}",
        f"    sim.enemy_windwalk_provider = _enemy_windwalk_{tag}",
        f"    sim.enemy_retarget_provider = _enemy_retarget_{tag}",
        "",
        f"    def _aha_{tag}_handler(director: Any) -> None:",
        '        av = float(getattr(sim, "current_av", 0.0))',
    ])
    for aha_i, a in enumerate(meta.aha_turns):
        flag = f"_triggered_aha_{aha_i}_{int(round(a.av * 100))}"
        lines.append(f"        if not getattr(director, {flag!r}, False) and av >= {a.av:.6f} - 1e-4:")
        lines.append(f"            setattr(director, {flag!r}, True)")
        lines.append('            if hasattr(sim, "_action_seq"):')
        lines.append("                sim._action_seq += 1")
        dmg_by_enemy: Dict[str, float] = {}
        lethal_names: Set[str] = {meta.enemy_uid_map.get(u, str(u)) for u in a.lethal_enemy_uids}
        for u, d in a.enemy_damages:
            ename = meta.enemy_uid_map.get(u, str(u))
            dmg_by_enemy[ename] = dmg_by_enemy.get(ename, 0.0) + float(d)
        for ename, tot_d in dmg_by_enemy.items():
            eff_d = (tot_d + 10000.0) if ename in lethal_names else tot_d
            lines.append(f"            director.apply_aha_hp_damage({ename!r}, {eff_d:.8f})")

        for owner, sp_cnt in a.ally_sp_gain_counts.items():
            hp_cnt = a.ally_chip_hits.count(owner)
            extra_memo_chips = max(0, sp_cnt - hp_cnt)
            for _ in range(extra_memo_chips):
                lines.append(f"            _mname = _find_memosprite_name(sim, {owner!r})")
                lines.append("            if _mname: director.apply_aha_ally_chip_hit(_mname)")
        for ally in a.ally_chip_hits:
            lines.append(f"            director.apply_aha_ally_chip_hit({ally!r})")
        lines.append("            director.flush_ally_talent_heals()")
        lines.append("")
    lines.append(f"    sim.aha_special_handler = _aha_{tag}_handler")
    aha_avs_literal = [round(float(a.av), 6) for a in meta.aha_turns]
    lines.append(f"    sim.aha_interrupt_avs = {aha_avs_literal!r}")
    if meta.enemy_uid_map:
        lines.append('    if not getattr(sim, "enemy_uid_map", None):')
        lines.append(f"        sim.enemy_uid_map = {dict(meta.enemy_uid_map)!r}")

    code = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(code)
    return output_path

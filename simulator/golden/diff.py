# coding: utf-8
"""Golden Trace 序列对比与 Markdown 报告渲染器（从 golden_diff.py 拆分）。"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict

from simulator.golden.models import BattleSequence, ReplayResult, TrajectoryResult


def diff_sequences(golden: BattleSequence, sim: BattleSequence) -> Dict[str, Any]:
    """对两条标准时序做结构化 diff, 返回可渲染的报告数据。"""
    g_skills = golden.skill_counts()
    s_skills = sim.skill_counts()
    all_skill_keys = sorted(set(g_skills) | set(s_skills))

    g_types = golden.damage_by_type()
    s_types = sim.damage_by_type()
    all_types = sorted(set(g_types) | set(s_types))

    g_actors = golden.damage_by_attacker()
    s_actors = sim.damage_by_attacker()
    g_hits = golden.hits_by_attacker()
    s_hits = sim.hits_by_attacker()
    all_actors = sorted(set(g_actors) | set(s_actors))

    def pct(part: float, whole: float) -> float:
        return (part / whole * 100.0) if whole > 0 else 0.0

    return {
        "golden_turns": len(golden.turns),
        "sim_turns": len(sim.turns),
        "golden_final_av": golden.final_av,
        "sim_final_av": sim.final_av,
        "golden_total_damage": golden.total_damage,
        "sim_total_damage": sim.total_damage,
        "skills": [
            {"key": k, "golden": g_skills.get(k, 0), "sim": s_skills.get(k, 0)}
            for k in all_skill_keys
        ],
        "damage_types": [
            {
                "type": t,
                "golden": g_types.get(t, 0.0),
                "sim": s_types.get(t, 0.0),
                "golden_pct": pct(g_types.get(t, 0.0), golden.total_damage),
                "sim_pct": pct(s_types.get(t, 0.0), sim.total_damage),
            }
            for t in all_types
        ],
        "actors": [
            {
                "actor": a,
                "golden": g_actors.get(a, 0.0),
                "sim": s_actors.get(a, 0.0),
                "golden_hits": g_hits.get(a, 0),
                "sim_hits": s_hits.get(a, 0),
                "deviation_pct": ((s_actors.get(a, 0.0) - g_actors.get(a, 0.0)) / g_actors[a] * 100.0) if g_actors.get(a) else None,
            }
            for a in all_actors
        ],
    }


def render_markdown(report: Dict[str, Any], golden_label: str, sim_label: str, replay_md: str = "") -> str:
    lines = []
    lines.append("# Golden Trace 对账报告")
    lines.append("")
    lines.append(f"- 官方真值: {golden_label}")
    lines.append(f"- 本模拟器: {sim_label}")
    lines.append("- 说明: 序列/分类层面对账; 敌方阵容与玩家操作差异会造成数值偏差, 偏差用于定位机制缺失或多余, 不要求相等。")
    lines.append("")
    lines.append("## 一、 总览")
    lines.append("")
    lines.append("| 指标 | 官方 | 模拟 |")
    lines.append("| :--- | ---: | ---: |")
    lines.append(f"| 回合数 | {report['golden_turns']} | {report['sim_turns']} |")
    lines.append(f"| 最终 AV | {report['golden_final_av']:.2f} | {report['sim_final_av']:.2f} |")
    lines.append(f"| 总伤害 | {report['golden_total_damage']:,.0f} | {report['sim_total_damage']:,.0f} |")
    lines.append("")
    lines.append("## 二、 角色伤害总账")
    lines.append("")
    lines.append("| 角色 | 官方伤害 | 模拟伤害 | 偏差% | 官方命中 | 模拟命中 |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |")
    for a in report["actors"]:
        dev = f"{a['deviation_pct']:+.1f}" if a["deviation_pct"] is not None else "-"
        lines.append(f"| {a['actor']} | {a['golden']:,.0f} | {a['sim']:,.0f} | {dev} | {a['golden_hits']} | {a['sim_hits']} |")
    lines.append("")
    lines.append("## 三、 伤害分类分布 (DamageType)")
    lines.append("")
    lines.append("| 类型 | 官方伤害 | 官方占比% | 模拟伤害 | 模拟占比% |")
    lines.append("| :--- | ---: | ---: | ---: | ---: |")
    for t in report["damage_types"]:
        lines.append(f"| {t['type']} | {t['golden']:,.0f} | {t['golden_pct']:.1f} | {t['sim']:,.0f} | {t['sim_pct']:.1f} |")
    lines.append("")
    lines.append("## 四、 技能施放次数")
    lines.append("")
    lines.append("| 技能 | 官方 | 模拟 |")
    lines.append("| :--- | ---: | ---: |")
    for s in report["skills"]:
        lines.append(f"| {s['key']} | {s['golden']} | {s['sim']} |")
    lines.append("")
    if replay_md:
        lines.append(replay_md)
    return "\n".join(lines)


def render_replay_markdown(result: ReplayResult) -> str:
    lines = []
    title = "## 五、 回放对齐 (按官方决策脚本驱动"
    title += ", 强制模式: 决策钉死)" if result.forced else ")"
    lines.append(title)
    lines.append("")
    lines.append(f"- 决策总数: {result.decisions_total} (回合行动 {result.turn_total}, 终结技 {result.ult_total})")
    lines.append(f"- 回合行动对齐: {result.turn_matched}/{result.turn_total}")
    lines.append(f"- 终结技对齐: {result.ult_matched}/{result.ult_total}")
    lines.append(f"- 偏离记录: {len(result.divergences)} 条")
    lines.append("")
    if result.forced and result.grants:
        lines.append("### 强制补足台账 (模拟自身经济与脚本需求的差额)")
        lines.append("")
        lines.append("| 角色 | 能量补足 (次/总量) | 战技点补足 (次) |")
        lines.append("| :--- | ---: | ---: |")
        actors = sorted({g.actor for g in result.grants})
        for actor in actors:
            eg = [g for g in result.grants if g.actor == actor and g.kind == "energy"]
            sg = [g for g in result.grants if g.actor == actor and g.kind == "sp"]
            lines.append(f"| {actor} | {len(eg)} 次 / {sum(g.amount for g in eg):,.0f} | {len(sg)} 次 |")
        lines.append("")
        lines.append("| AV | 角色 | 类型 | 补足量 |")
        lines.append("| ---: | :--- | :--- | ---: |")
        for g in result.grants:
            lines.append(f"| {g.av:.1f} | {g.actor} | {g.kind} | {g.amount:,.0f} |")
        lines.append("")
    if result.divergences:
        lines.append("| AV | 类型 | 说明 |")
        lines.append("| ---: | :--- | :--- |")
        for d in result.divergences[:30]:
            lines.append(f"| {d.av:.1f} | {d.kind} | {d.detail} |")
        if len(result.divergences) > 30:
            lines.append(f"| ... | ... | 其余 {len(result.divergences) - 30} 条略 |")
        lines.append("")
    return "\n".join(lines)


def render_enemy_activity_markdown(activity: Dict[str, Any]) -> str:
    lines = []
    lines.append("## 六、 敌方行动与受击回能 (官方, OnStatChange 签名提取)")
    lines.append("")
    lines.append("- 说明: OnDamage 仅含我方输出 (DPS 统计口径); 敌方命中以 OnStatChange 中")
    lines.append("  CurrentSP 的受击回能签名 (约 5.0 x ERR/段) 提取, 计数为样本口径下限。")
    lines.append(f"- 敌方回合总数: {activity['enemy_turn_total']} (按 uid: {activity['enemy_turns']})")
    lines.append(f"- 受击回能事件: {activity['hit_energy_total_count']} 次, 合计约 {activity['hit_energy_total']:.1f} 点")
    for uid in sorted(activity["hit_energy"]):
        v = activity["hit_energy"][uid]
        lines.append(f"  - uid {uid}: {v['count']} 次 / {v['total']:.1f} 点")
    lines.append(f"- 群体攻击签名 (>=3 名我方同时受击回能的敌方回合): {activity['wide_actions']} 次")
    lines.append("")
    return "\n".join(lines)


def render_trajectory_markdown(traj: TrajectoryResult) -> str:
    lines = []
    lines.append("## 七、 轨迹回放 (全轨迹按官方 AV 钉死, 缺口补足记账)")
    lines.append("")
    lines.append("- 说明: 本体回合行动以距离延后精确推到官方 AV, 终结技到点抢断,")
    lines.append("  忆灵技到点未自然触发的补前置后强制施放。敌方施放不在日志中, 敌方仍自由行动。")
    lines.append(f"- 补足台账: 终结技能量 {traj.ult_energy_granted:.0f} 点 / 战技点 {traj.sp_granted} 次 / 忆质 {traj.memoria_granted:.0f} 点 / 忆灵在场补发 {traj.presence_grants} 次")
    lines.append("")
    lines.append("### 本体施放 AV 对齐")
    lines.append("")
    lines.append("| 角色 | 排期 | 已施放 | 平均 |ΔAV| | 最大 |ΔAV| |")
    lines.append("| :--- | ---: | ---: | ---: | ---: |")
    by_actor = defaultdict(list)
    for r in traj.master_records:
        by_actor[r.actor].append(r)
    ult_by_actor = defaultdict(list)
    for r in traj.ult_records:
        ult_by_actor[r.actor].append(r)
    for actor in sorted(set(by_actor) | set(ult_by_actor)):
        recs = by_actor.get(actor, []) + ult_by_actor.get(actor, [])
        fired = [r for r in recs if r.fired_av is not None]
        deltas = [abs(r.fired_av - r.official_av) for r in fired]
        mean_d = f"{sum(deltas) / len(deltas):.1f}" if deltas else "-"
        max_d = f"{max(deltas):.1f}" if deltas else "-"
        lines.append(f"| {actor} | {len(recs)} | {len(fired)} | {mean_d} | {max_d} |")
    lines.append("")
    lines.append("### 忆灵技轨迹")
    lines.append("")
    lines.append("| 技能 | 官方 | 自然对齐 | 强制补发 | 失败/不可强制 |")
    lines.append("| :--- | ---: | ---: | ---: | ---: |")
    total = Counter(r.skill_id for r in traj.records)
    modes = Counter((r.skill_id, r.mode) for r in traj.records)
    names = {r.skill_id: r.name for r in traj.records}
    for sid in sorted(total):
        bad = modes.get((sid, "failed"), 0) + modes.get((sid, "unforceable"), 0)
        lines.append(f"| {names[sid]} | {total[sid]} | {modes.get((sid, 'organic'), 0)} | {modes.get((sid, 'forced'), 0)} | {bad} |")
    lines.append("")
    lines.append("### 长夜爆发轨迹 (官方 AV -> 实际 AV)")
    lines.append("")
    for r in [r for r in traj.records if r.skill_id == 1141307]:
        fired = f"{r.fired_av:.1f}" if r.fired_av is not None else "-"
        tag = "" if r.mode == "organic" else f" ({r.mode}{': ' + ', '.join(r.patches) if r.patches else ''})"
        lines.append(f"- {r.official_av:.1f} -> {fired}{tag}")
    lines.append("")
    return "\n".join(lines)

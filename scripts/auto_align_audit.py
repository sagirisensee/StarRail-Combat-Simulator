#!/usr/bin/env python3
"""全自动伤害对齐与微观乘区逆解归因审计器 (Automated Discrepancy & Multiplier Solver).

功能：
1. 逐动对比 96 动录像金标 (video_artifacts/harness_ground_truth.json) 与 SIM 伤害输出；
2. 标出每动的状态 (🟢 <=0.2%, 🟡 <=1.0%, 🔴 >1.0%)；
3. 对偏离动进行【全自动乘区逆解】：
   - 检验知更鸟气氛值 (Vibes) 离散偏差 (每点气氛对应 1.5% 暴伤与 0.5% 结界减防)；
   - 检验灯塔首领众愿免伤 (Wish Stacks) 离散偏差 (每层 5% 独立免伤)；
   - 检验破韧状态 (Broken / Unbroken 10% 韧性减伤)；
   - 检验忆灵白字生命与继承比例偏差；
4. 输出清晰易读的全局归因账单与关键状态分叉点。
"""

import os
import sys
import json
from typing import Dict, List, Any, Optional

# 确保导入路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulator.test_micro_action_audit import run_micro_audit_96, GOLDEN_20261026, GROUND_TRUTH_JSON


def analyze_discrepancy(gt_dmg: float, sim_dmg: float, hits: List[Dict[str, Any]]) -> str:
    """根据伤害比率与已知机制离散步长，自动逆解可能的原因。"""
    if gt_dmg <= 0 or sim_dmg <= 0:
        return "直伤为零或纯辅助施法"
    
    ratio = sim_dmg / gt_dmg
    diff_pct = (ratio - 1.0) * 100.0
    suggestions = []

    # 1. 检验知更鸟气氛值步长
    # 气氛值每点影响: 暴伤 +1.5%, 结界防御穿透 +0.5%
    # 综合复合影响通常在 ~0.65% 左右 (暴伤区 ~0.2%~0.4% + 防御区 ~0.35%~0.4%)
    vibe_step = 0.65
    est_vibe_diff = round(diff_pct / vibe_step)
    if abs(est_vibe_diff) in (1, 2, 3, 4, 5):
        suggestions.append(f"知更鸟气氛值可能偏差 {est_vibe_diff:+d} 点 (当前 SIM 复合偏差 ~{diff_pct:+.2f}%)")

    # 2. 检验众愿免伤层数 (每层 5%)
    # ratio ≈ (1 - 0.05 * (s + d)) / (1 - 0.05 * s)
    for stack_diff in (-3, -2, -1, 1, 2, 3):
        # 假设基准 5~7 层 (0.75 ~ 0.65)
        for base_stacks in (5, 6, 7):
            old_dr = 1.0 - base_stacks * 0.05
            new_dr = 1.0 - (base_stacks + stack_diff) * 0.05
            if old_dr > 0 and new_dr > 0:
                step_ratio = old_dr / new_dr
                if abs(step_ratio - ratio) < 0.005:
                    suggestions.append(f"首领众愿免伤可能偏差 {stack_diff:+d} 层 (每层 5%)")
                    break

    # 3. 检验韧性击破 (0.9 vs 1.0, 约 11.1%)
    if abs(ratio - 1.0 / 0.9) < 0.01:
        suggestions.append("目标处于破韧状态但 SIM 按未破韧 (0.9) 结算，或反之")
    elif abs(ratio - 0.9) < 0.01:
        suggestions.append("目标未破韧 (0.9) 但 SIM 按破韧 (1.0) 结算")

    # 4. 检验分项 Hit 结构
    hit_ratios = []
    for h in hits:
        g = h.get("gt_dmg", 0.0)
        s = h.get("sim_dmg", 0.0)
        if g > 1000 and s > 1000:
            hit_ratios.append(s / g)
    if hit_ratios:
        # 如果所有主 Hit 比例完全一致
        first = hit_ratios[0]
        if all(abs(r - first) < 0.0001 for r in hit_ratios):
            suggestions.append(f"全 Hit 乘区偏差完全一致 (统一缩放因子 {first:.6f})，排除了分项击中数或局部跳字差异")

    return " | ".join(suggestions) if suggestions else f"复合微观偏差 (比值 {ratio:.5f})"


def run_audit(max_actions: int = 96, verbose: bool = False):
    print("=" * 80)
    print("🚀 正在执行 96 动全量伤害金标对齐与自动归因审计...")
    print("=" * 80)

    audit = run_micro_audit_96()
    gt_casts = audit["gt"]
    sim_casts = audit["sim_casts"]

    total_actions = min(len(gt_casts), len(sim_casts), max_actions)
    green_count = 0
    yellow_count = 0
    red_count = 0

    results = []

    for i in range(total_actions):
        gt = gt_casts[i]
        sim = sim_casts[i]

        gt_tot = sum(h["damage"] for h in gt["hits"])
        sim_tot = sum(h["damage"] for h in sim["hits"])

        diff = sim_tot - gt_tot
        err = (diff / gt_tot * 100.0) if gt_tot > 0 else 0.0
        abs_err = abs(err)

        if abs_err <= 0.20:
            status = "🟢 PASS (<=0.2%)"
            green_count += 1
        elif abs_err <= 1.00:
            status = "🟡 WARN (<=1.0%)"
            yellow_count += 1
        else:
            status = "🔴 FAIL (>1.0%)"
            red_count += 1

        hits_summary = []
        max_hits = max(len(gt["hits"]), len(sim["hits"]))
        for h_idx in range(max_hits):
            g_h = gt["hits"][h_idx] if h_idx < len(gt["hits"]) else {}
            s_h = sim["hits"][h_idx] if h_idx < len(sim["hits"]) else {}
            hits_summary.append({
                "target": s_h.get("target") or g_h.get("target", "?"),
                "type": s_h.get("type") or g_h.get("damage_type", "?"),
                "gt_dmg": g_h.get("damage", 0.0),
                "sim_dmg": s_h.get("damage", 0.0),
            })

        diagnosis = ""
        if abs_err > 0.20:
            diagnosis = analyze_discrepancy(gt_tot, sim_tot, hits_summary)

        results.append({
            "idx": i + 1,
            "av": gt["av"],
            "actor": gt["actor"],
            "skill": gt["skill_name"],
            "gt_tot": gt_tot,
            "sim_tot": sim_tot,
            "diff": diff,
            "err": err,
            "status": status,
            "diagnosis": diagnosis,
            "hits": hits_summary,
        })

    # 打印概览看板
    print(f"\n📊 审计执行结果看板 (共审计 {total_actions} 动):")
    print(f"  🟢 极速精准 (<= 0.20%): {green_count:>2d} / {total_actions} ({green_count/total_actions*100:.1f}%)")
    print(f"  🟡 门禁内收敛 (<= 1.00%): {yellow_count:>2d} / {total_actions} ({yellow_count/total_actions*100:.1f}%)")
    print(f"  🔴 待收敛动作 (>  1.00%): {red_count:>2d} / {total_actions} ({red_count/total_actions*100:.1f}%)")
    print("-" * 80)
    print(f"{'#':<4} {'AV':<7} {'角色':<10} {'技能名称':<18} {'GT总伤':>11} {'SIM总伤':>11} {'偏差%':>8}  {'状态'}")
    print("-" * 80)

    for r in results:
        flag = "🟢" if "PASS" in r["status"] else ("🟡" if "WARN" in r["status"] else "🔴")
        print(f"#{r['idx']:02d}  {r['av']:<6.2f} {r['actor']:<10} {r['skill']:<18} {r['gt_tot']:>11.1f} {r['sim_tot']:>11.1f} {r['err']:>+7.3f}%  {flag}")
        if r["diagnosis"]:
            print(f"     └─ 🔍 归因建议: {r['diagnosis']}")
        if verbose and r["diagnosis"]:
            for h_i, h in enumerate(r["hits"]):
                g_d = h["gt_dmg"]
                s_d = h["sim_dmg"]
                ratio = (s_d / g_d) if g_d > 0 else 0.0
                print(f"        Hit #{h_i}: target={h['target']} type={h['type']} GT={g_d:.1f} SIM={s_d:.1f} (ratio={ratio:.5f})")

    print("=" * 80)
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="自动对齐审计看板")
    parser.add_argument("--max", type=int, default=30, help="审计前 N 动 (默认 30)")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出每 Hit 详细拆解")
    args = parser.parse_args()
    run_audit(max_actions=args.max, verbose=args.verbose)

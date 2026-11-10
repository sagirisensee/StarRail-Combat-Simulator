import sys
import os
sys.path.insert(0, '/Users/yunkaichen/Downloads/starrail')
from simulator.test_micro_action_audit import run_micro_audit_96

audit = run_micro_audit_96(seed=1)
gt = audit['gt']
sim_casts = audit['sim_casts']

results = []
le_020 = 0
b_020_050 = 0
b_050_100 = 0
b_100_200 = 0
b_200_500 = 0
gt_500 = 0

for i in range(len(gt)):
    g_hits = gt[i]["hits"]
    s_hits = sim_casts[i]["hits"]
    g_dmg = sum(h["damage"] for h in g_hits)
    s_dmg = sum(h["damage"] for h in s_hits)
    if g_dmg > 0:
        err = (s_dmg - g_dmg) / g_dmg
        abs_err = abs(err)
    else:
        err = 0.0
        abs_err = 0.0
    
    if abs_err <= 0.0020:
        le_020 += 1
    elif abs_err <= 0.0050:
        b_020_050 += 1
    elif abs_err <= 0.0100:
        b_050_100 += 1
    elif abs_err <= 0.0200:
        b_100_200 += 1
    elif abs_err <= 0.0500:
        b_200_500 += 1
    else:
        gt_500 += 1

    results.append({
        "act": i + 1,
        "actor": gt[i]["actor"],
        "skill": gt[i]["skill_name"],
        "gt": g_dmg,
        "sim": s_dmg,
        "err": err,
        "abs_err": abs_err,
    })

print(f"Total actions: {len(results)}")
print(f"<= 0.20%: {le_020} ({le_020/len(results):.1%})")
print(f"0.20% ~ 0.50%: {b_020_050} ({b_020_050/len(results):.1%})")
print(f"0.50% ~ 1.00%: {b_050_100} ({b_050_100/len(results):.1%})")
print(f"1.00% ~ 2.00%: {b_100_200} ({b_100_200/len(results):.1%})")
print(f"2.00% ~ 5.00%: {b_200_500} ({b_200_500/len(results):.1%})")
print(f"> 5.00%: {gt_500} ({gt_500/len(results):.1%})")

print("\n--- 0.20% ~ 0.50% Actions ---")
for r in results:
    if 0.0020 < r["abs_err"] <= 0.0050:
        print(f"Action #{r['act']:02d} [{r['actor']} - {r['skill']}]: GT={r['gt']:,.1f}, SIM={r['sim']:,.1f}, err={r['err']:+.4%}")

print("\n--- Top 15 Highest Error Actions ---")
top_errs = sorted(results, key=lambda x: x["abs_err"], reverse=True)[:15]
for r in top_errs:
    print(f"Action #{r['act']:02d} [{r['actor']} - {r['skill']}]: GT={r['gt']:,.1f}, SIM={r['sim']:,.1f}, err={r['err']:+.4%}")

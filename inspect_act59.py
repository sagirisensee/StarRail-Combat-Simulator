import sys
import json
sys.path.insert(0, '/Users/yunkaichen/Downloads/starrail')
from simulator.test_micro_action_audit import run_micro_audit_96

audit = run_micro_audit_96(seed=1)
gt = audit['gt']
sim_casts = audit['sim_casts']

idx = 58 # Action #59
g = gt[idx]
s = sim_casts[idx]

print(f"Action #59: {g['actor']} - {g['skill_name']}")
print("GT hits:")
for h in g["hits"]:
    print(f"  [{h.get('type')}]: {h['damage']:,.2f}")
print("SIM hits:")
for h in s["hits"]:
    print(f"  {h['attacker']} -> {h['target']} [{h['type']}]: {h['damage']:,.2f}")

g_sum = sum(h["damage"] for h in g["hits"])
s_sum = sum(h["damage"] for h in s["hits"])
print(f"GT Total: {g_sum:,.2f}")
print(f"SIM Total: {s_sum:,.2f}")
print(f"Err: {(s_sum - g_sum)/g_sum:+.4%}")

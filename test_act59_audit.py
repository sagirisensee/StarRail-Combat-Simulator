import sys
sys.path.insert(0, '/Users/yunkaichen/Downloads/starrail')
from simulator.test_micro_action_audit import run_micro_audit_96
import simulator.kits.characters.changyeyue as cyy_module

# 让我们修改 changyeyue.py 的 execute 中 ULTIMATE 分支里的 spirit_cd
# 在 ULTIMATE 分支中，如果 was_spirit_alive 为 True，
# 剔除本次大招施放即时施加的 A2 在战技分享中的重复计算 (0.15 * 0.24 = 0.036)
# 同时由于面板知更鸟偏离和弦相差 1 点气氛值 (0.015 * 0.24 = 0.0036)，
# 看看 spirit_cd 减少 0.03799 之后 Action #59 的误差和全场测试。

audit = run_micro_audit_96(seed=1)
gt = audit['gt']
sim_casts = audit['sim_casts']

idx = 58
g_dmg = sum(h["damage"] for h in gt[idx]["hits"])
s_dmg = sum(h["damage"] for h in sim_casts[idx]["hits"])
print(f"Current Action #59: GT={g_dmg:,.2f}, SIM={s_dmg:,.2f}, err={(s_dmg - g_dmg)/g_dmg:+.4%}")

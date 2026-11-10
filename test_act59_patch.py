import sys
sys.path.insert(0, '/Users/yunkaichen/Downloads/starrail')

from simulator.golden_diff import build_stage_sim, attach_exact_crit_oracle, extract_timeline, run_trajectory_replay, parse_golden_jsonl
from simulator.test_micro_action_audit import run_micro_audit_96
import simulator.kits.characters.changyeyue as cyy_module

# 我们在 changyeyue.py 的终结技分支里测试：
# 当 was_spirit_alive 为 True 时，长夜实体已经有 A2_Skill_CritDmg_Spirit，
# 如果战技分享中包含长夜月本次大招刚施加的 A2 (0.15)，会导致重复叠加 0.15 * 0.24 = 0.036。
# 测试将 fixed_crit_dmg 中的这部分扣除。

orig_execute = cyy_module.ChangyeyueKit.execute

def patched_execute(self, ctx):
    if ctx.kind == cyy_module.ActionKind.ULTIMATE:
        was_spirit_alive = self.spirit_alive
        # 调用原逻辑
        orig_execute(self, ctx)
    else:
        orig_execute(self, ctx)

# 让我们在 DamageCalculator 中直接测试将 Action 59 的 fixed_crit_dmg 调整 0.038 的效果
from simulator.damage import DamageCalculator
orig_calc = DamageCalculator.calculate

def test_calc(req):
    if getattr(req.attacker, "name", "") == "长夜月" and getattr(req, "damage_type", None) and req.damage_type.name == "ULTIMATE":
        # 仅针对 Action 59
        pass
    return orig_calc(req)

audit = run_micro_audit_96(seed=1)
gt = audit['gt']
sim_casts = audit['sim_casts']
g_dmg = sum(h["damage"] for h in gt[58]["hits"])
s_dmg = sum(h["damage"] for h in sim_casts[58]["hits"])
print(f"Action #59 current: GT={g_dmg:,.2f}, SIM={s_dmg:,.2f}, err={(s_dmg - g_dmg)/g_dmg:+.4%}")

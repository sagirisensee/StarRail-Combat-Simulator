import sys
sys.path.insert(0, '/Users/yunkaichen/Downloads/starrail')

from simulator.golden_diff import build_stage_sim, attach_exact_crit_oracle, extract_timeline, run_trajectory_replay, parse_golden_jsonl
from simulator.events import ActionExecuteEvent
from simulator.actions import ActionKind
from simulator.damage import DamageCalculator

GOLDEN_20261026 = "battle_logs/battle_20261026_062503.jsonl"
sim, director = build_stage_sim(log_path=GOLDEN_20261026)
attach_exact_crit_oracle(sim, log_path=GOLDEN_20261026)
golden = parse_golden_jsonl(GOLDEN_20261026)

action_idx = 0
orig_calc = DamageCalculator.calculate

def audit_calc(req):
    bd = orig_calc(req)
    if action_idx == 74 and getattr(req, "damage_type", None) and req.damage_type.name == "ULTIMATE":
        print(f"=== Action #74 ULTIMATE Breakdown [{req.target.name}] ===")
        print(f"base_stat: {bd.base_stat}, skill_multiplier: {bd.skill_multiplier}, base_dmg: {bd.base_dmg}")
        print(f"fixed_crit_dmg: {req.fixed_crit_dmg}, crit_mult: {bd.crit_mult}")
        print(f"dmg_boost_mult: {bd.dmg_boost_mult}, def_mult: {bd.def_mult}, res_mult: {bd.res_mult}, vuln_mult: {bd.vuln_mult}, reduction_mult: {bd.reduction_mult}, barrier_mult: {bd.barrier_mult}")
        print(f"final_damage: {bd.final_damage:,.2f}")
    return bd

DamageCalculator.calculate = staticmethod(audit_calc)

def on_action(e):
    global action_idx
    if isinstance(e, ActionExecuteEvent):
        ent = next((x for x in sim.entities if x.name == e.actor_name), None)
        if ent is not None and (getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False)):
            return
        kind = getattr(e, "action_kind", None)
        if kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
            return
        raw_name = e.action_type or ""
        if raw_name == "FollowUpAttack" or not raw_name:
            return
        action_idx += 1

sim.event_bus.subscribe(ActionExecuteEvent, on_action)
traj = run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)

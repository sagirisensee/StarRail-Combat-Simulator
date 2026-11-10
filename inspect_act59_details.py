import json
import random
import sys
sys.path.insert(0, '/Users/yunkaichen/Downloads/starrail')

from simulator.golden_diff import build_stage_sim, attach_exact_crit_oracle, extract_timeline, run_trajectory_replay, parse_golden_jsonl
from simulator.events import ActionExecuteEvent, DamageAppliedEvent
from simulator.actions import ActionKind

GOLDEN_20261026 = "battle_logs/battle_20261026_062503.jsonl"
sim, director = build_stage_sim(log_path=GOLDEN_20261026)
attach_exact_crit_oracle(sim, log_path=GOLDEN_20261026)
golden = parse_golden_jsonl(GOLDEN_20261026)

action_idx = 0
target_act = 59

def on_battle_event(e):
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
        if action_idx == target_act:
            print(f"=== Triggering Action #{action_idx}: {e.actor_name} - {e.action_type} ===")
            cyy = next((x for x in sim.entities if x.name == "长夜月"), None)
            sp = next((x for x in sim.entities if x.name == "长夜"), None)
            print("长夜月 statuses:")
            for s in sim.port.statuses("长夜月"):
                mods = [(m.stat.name, m.op.name, m.value) for m in s.modifiers]
                print(f"  {s.id}: name={s.name}, mods={mods}")
            if sp:
                print("长夜 statuses:")
                for s in sim.port.statuses("长夜"):
                    mods = [(m.stat.name, m.op.name, m.value) for m in s.modifiers]
                    print(f"  {s.id}: name={s.name}, mods={mods}")
            print(f"长夜月 stat CRIT_DMG: {sim.port.stat('长夜月', simulator.status.StatType.CRIT_DMG)}")
            if sp:
                print(f"长夜 stat CRIT_DMG: {sim.port.stat('长夜', simulator.status.StatType.CRIT_DMG)}")
    elif isinstance(e, DamageAppliedEvent):
        if action_idx == target_act:
            dt = e.damage_type.value if hasattr(e.damage_type, "value") else str(e.damage_type)
            print(f"  HIT: {e.attacker_name} -> {e.target_name} [{dt}]: {e.damage:,.2f}")

sim.event_bus.subscribe(DamageAppliedEvent, on_battle_event)
sim.event_bus.subscribe(ActionExecuteEvent, on_battle_event)

import simulator.status
traj = run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)

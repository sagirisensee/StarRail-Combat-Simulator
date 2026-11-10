import sys
sys.path.insert(0, '/Users/yunkaichen/Downloads/starrail')

from simulator.golden_diff import build_stage_sim, attach_exact_crit_oracle, extract_timeline, run_trajectory_replay, parse_golden_jsonl
from simulator.events import ActionExecuteEvent
from simulator.actions import ActionKind
from simulator.status import StatType

GOLDEN_20261026 = "battle_logs/battle_20261026_062503.jsonl"
sim, director = build_stage_sim(log_path=GOLDEN_20261026)
attach_exact_crit_oracle(sim, log_path=GOLDEN_20261026)
golden = parse_golden_jsonl(GOLDEN_20261026)

action_idx = 0
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
        if action_idx == 59:
            print("=== Action #59 Ultimate ===")
            cyy = sim.get_entity("长夜月")
            kit = cyy.kit
            was_alive = kit.spirit_alive
            print(f"was_spirit_alive: {was_alive}")
            sp_cd = kit._spirit_crit_dmg(include_skill_shared=True)
            print(f"_spirit_crit_dmg(include_skill_shared=True): {sp_cd}")
            # 查看长夜实体身上的状态
            sp_ent = sim.get_entity("长夜")
            if sp_ent:
                print(f"长夜 base_crit_dmg: {sp_ent.base_crit_dmg}")
                for s in sim.port.statuses("长夜"):
                    mods = [(m.stat.name, m.op.name, m.value) for m in s.modifiers if m.stat == StatType.CRIT_DMG]
                    if mods:
                        print(f"  {s.id}: {s.name}, mods={mods}")
            print("长夜月上的暴伤:")
            for s in sim.port.statuses("长夜月"):
                mods = [(m.stat.name, m.op.name, m.value) for m in s.modifiers if m.stat == StatType.CRIT_DMG]
                if mods:
                    print(f"  {s.id}: {s.name}, mods={mods}")

sim.event_bus.subscribe(ActionExecuteEvent, on_action)
traj = run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)

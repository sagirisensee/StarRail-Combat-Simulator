# coding: utf-8
import os
import json
from simulator.golden_diff import build_stage_sim, extract_timeline, attach_exact_crit_oracle, run_trajectory_replay, parse_golden_jsonl
from simulator.events import ActionExecuteEvent, BattleEvent
from simulator.actions import ActionKind
from simulator.status import StatType

golden_path = os.path.join('.', 'battle_logs', 'battle_20261026_062503.jsonl')
golden = parse_golden_jsonl(golden_path)
sim, director = build_stage_sim(log_path=golden_path)
attach_exact_crit_oracle(sim, log_path=golden_path)

timeline = extract_timeline(golden_path)

snapshots = []

def lookup(name):
    for e in sim.entities:
        if e.name == name:
            return e
    return None

def on_action(e):
    if not isinstance(e, ActionExecuteEvent):
        return
    ent = lookup(e.actor_name)
    if ent is not None and (getattr(ent, 'is_countdown', False) or getattr(ent, 'is_enemy', False)):
        return
    kind = getattr(e, 'action_kind', None)
    if kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
        return
    raw_name = e.action_type or ''
    if raw_name == 'FollowUpAttack' or not raw_name:
        return
    
    robin_kit = getattr(lookup('知更鸟•晴歌'), 'kit', None)
    vibes = getattr(robin_kit, 'vibes', 0) if robin_kit else 0
    
    cyy_kit = getattr(lookup('长夜月'), 'kit', None)
    memoria = getattr(cyy_kit, 'yizhi', 0) if cyy_kit else 0
    
    team_data = {}
    for c in ['长夜月', '缇宝', '风堇', '知更鸟•晴歌', '长夜', '小伊卡', '晴空乐手']:
        e_obj = lookup(c)
        if e_obj and not getattr(e_obj, 'unspawned', False):
            crit = (sim.port.stat(c, StatType.CRIT_DMG) or 0.0) * 100
            spd = (sim.port.stat(c, StatType.SPEED) or 0.0)
            chord = 0.0
            for s in sim.port.statuses(c):
                if 'TonalChord' in s.id:
                    for m in s.modifiers:
                        if m.stat == StatType.CRIT_DMG:
                            chord = m.value * 100
            team_data[c] = {
                'ep': float(getattr(e_obj, 'energy', 0.0)),
                'max_ep': float(getattr(e_obj, 'max_energy', 0.0)),
                'crit': float(crit),
                'spd': float(spd),
                'chord': float(chord),
                'hp': float(e_obj.current_hp),
                'max_hp': float(sim.port.max_hp(c))
            }
        else:
            team_data[c] = None

    sp_val = sim.sp.current_sp if hasattr(sim.sp, 'current_sp') else getattr(sim, 'sp', 0)
    idx = len(snapshots) + 1
    snapshots.append({
        'act_idx': idx,
        'av': float(getattr(sim, 'current_av', 0.0)),
        'actor': e.actor_name,
        'skill': raw_name,
        'sp': int(sp_val),
        'vibes': vibes,
        'memoria': memoria,
        'team': team_data
    })

sim.event_bus.subscribe(BattleEvent, on_action)
run_trajectory_replay(sim, director, timeline, av_budget=golden.final_av)

print(f'Captured {len(snapshots)} action snapshots.')
with open('sim_action_snapshots.json', 'w', encoding='utf-8') as f:
    json.dump(snapshots, f, ensure_ascii=False, indent=2)

for s in snapshots[:22]:
    idx = s['act_idx']
    av = s['av']
    actor = s['actor']
    skill = s['skill']
    sp = s['sp']
    vibes = s['vibes']
    mem = s['memoria']
    print(f"Action #{idx:02d} | AV={av:6.2f} | {actor:7s} | {skill:14s} | SP={sp} | Vibes={vibes:2d} | Memoria={mem:2d}")
    for c, d in s['team'].items():
        if d:
            print(f"    {c:7s}: EP={d['ep']:5.1f}/{d['max_ep']:3.0f} | CRIT={d['crit']:5.1f}% | SPD={d['spd']:5.1f} | Chord={d['chord']:5.1f}%")

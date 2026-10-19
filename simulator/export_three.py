from simulator.db.character_db import CharacterDB
import json
import math

db = CharacterDB().load(r'd:\Downloads\ppSR_REL_4.6.5X\misc\freesr-data.json')
targets = ['流萤', '克拉拉', '卡芙卡']
out_data = {}

for name in targets:
    p = db.get_by_name(name)
    panel = p.panel
    rolls = p.get_substat_roll_summary()
    
    hp_w = panel.breakdowns['hp'].base_white
    hp_g = panel.hp - hp_w
    atk_w = panel.breakdowns['atk'].base_white
    atk_g = panel.atk - atk_w
    def_w = panel.breakdowns['def'].base_white
    def_g = panel.def_stat - def_w
    spd_w = panel.breakdowns['spd'].base_white
    spd_g = panel.spd - spd_w
    
    out_data[name] = {
        'avatar_id': p.avatar_id,
        'eidolon': f'E{p.eidolon}',
        'level': f'Lv.{p.level}',
        'light_cone': {
            'name': p.light_cone.name,
            'superimposition': f'S{p.light_cone.superimposition}',
            'level': f'Lv.{p.light_cone.level}'
        } if p.light_cone else None,
        'sets': list({f'{r.set_name} (ID {r.relic_set_id})' for r in p.relics}),
        'panel_display': {
            'HP': f'{math.floor(panel.hp)} ({math.floor(hp_w)}+{math.floor(hp_g)})',
            'ATK': f'{math.floor(panel.atk)} ({math.floor(atk_w)}+{math.floor(atk_g)})',
            'DEF': f'{math.floor(panel.def_stat)} ({math.floor(def_w)}+{math.floor(def_g)})',
            'SPD': f'{math.floor(panel.spd)} ({math.floor(spd_w)}+{math.floor(spd_g)})',
            'CR': f'{panel.crit_rate*100:.1f}%',
            'CD': f'{panel.crit_dmg*100:.1f}%',
            'BE': f'{panel.break_effect*100:.1f}%',
            'ERR': f'{panel.err*100:.1f}%',
            'EHR': f'{panel.ehr*100:.1f}%',
            'RES': f'{panel.res*100:.1f}%',
            'DMG%': f'{panel.dmg_boost*100:.1f}%'
        },
        'panel_exact_float': {
            'HP': round(panel.hp, 2),
            'ATK': round(panel.atk, 2),
            'DEF': round(panel.def_stat, 2),
            'SPD': round(panel.spd, 3)
        },
        'roll_stats': rolls,
        'relics': [
            {
                'slot_name': r.slot_name,
                'set_name': r.set_name,
                'main_affix': f"{r.main_affix_name} {r.main_affix_val*100:.1f}%" if r.is_main_pct else f"{r.main_affix_name} {r.main_affix_val:.1f}",
                'subs': [
                    f"{s['name']} +{s['value']*100:.1f}% ({s['count']}次: 低{s['low_rolls']}中{s['mid_rolls']}高{s['high_rolls']})" if s['is_pct']
                    else f"{s['name']} +{s['value']:.1f} ({s['count']}次: 低{s['low_rolls']}中{s['mid_rolls']}高{s['high_rolls']})"
                    for s in r.sub_affixes
                ]
            }
            for r in p.relics
        ]
    }

with open('three_chars.json', 'w', encoding='utf-8') as f:
    json.dump(out_data, f, ensure_ascii=False, indent=2)
print('Saved three_chars.json successfully!')

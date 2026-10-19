from simulator.db.character_db import CharacterDB
import json
import math

db = CharacterDB().load(r'd:\Downloads\ppSR_REL_4.6.5X\misc\freesr-data.json')

targets = ['流萤', '克拉拉', '卡芙卡']

for name in targets:
    p = db.get_by_name(name)
    panel = p.panel
    rolls = p.get_substat_roll_summary()
    
    print('========================================================')
    print(f'【{p.name}】 (Avatar ID: {p.avatar_id})')
    print(f'  星魂: E{p.eidolon} | 等级: Lv.{p.level} / 晋阶 {p.promotion}')
    if p.light_cone:
        print(f'  装备光锥: 《{p.light_cone.name}》 (ID: {p.light_cone.item_id}, Lv.{p.light_cone.level}, S{p.light_cone.superimposition})')
    else:
        print('  装备光锥: 无')
        
    sets = list({f'{r.set_name} (ID {r.relic_set_id})' for r in p.relics})
    print(f'  遗器套装: {sets}')
    
    hp_w = panel.breakdowns['hp'].base_white
    hp_g = panel.hp - hp_w
    atk_w = panel.breakdowns['atk'].base_white
    atk_g = panel.atk - atk_w
    def_w = panel.breakdowns['def'].base_white
    def_g = panel.def_stat - def_w
    spd_w = panel.breakdowns['spd'].base_white
    spd_g = panel.spd - spd_w
    
    print('  --- 综合面板 (实机显示 / 底层精确浮点) ---')
    print(f'  生命值: {math.floor(panel.hp):<5} (白 {math.floor(hp_w)} + 绿 {math.floor(hp_g)}) | 精确值: {panel.hp:.2f}')
    print(f'  攻击力: {math.floor(panel.atk):<5} (白 {math.floor(atk_w)} + 绿 {math.floor(atk_g)}) | 精确值: {panel.atk:.2f}')
    print(f'  防御力: {math.floor(panel.def_stat):<5} (白 {math.floor(def_w)} + 绿 {math.floor(def_g)}) | 精确值: {panel.def_stat:.2f}')
    print(f'  速度:   {math.floor(panel.spd):<5} (白 {math.floor(spd_w)} + 绿 {math.floor(spd_g)}) | 精确值: {panel.spd:.3f}')
    print(f'  暴击率: {panel.crit_rate*100:.1f}% | 暴击伤害: {panel.crit_dmg*100:.1f}%')
    print(f'  击破特攻: {panel.break_effect*100:.1f}% | 能量恢复效率: {panel.err*100:.1f}%')
    print(f'  效果命中: {panel.ehr*100:.1f}% | 效果抵抗: {panel.res*100:.1f}% | 伤害加成: {panel.dmg_boost*100:.1f}%')
    print(f'  副词条强化概况: 总计 {rolls["total_rolls"]} 次 [低档: {rolls["low_rolls"]} | 中档: {rolls["mid_rolls"]} | 高档: {rolls["high_rolls"]}], 强化品质分: {rolls["quality_score"]}分')
    print(f'  词条命中分布: {rolls["by_stat"]}')
    
    print('  --- 6件遗器逐件明细 ---')
    for r in p.relics:
        main_v = f"{r.main_affix_val*100:.1f}%" if r.is_main_pct else f"{r.main_affix_val:.1f}"
        print(f'    [{r.slot_name}] {r.set_name} +{r.level} | 主词条: {r.main_affix_name} {main_v}')
        sub_strs = []
        for s in r.sub_affixes:
            v_str = f"{s['value']*100:.1f}%" if s['is_pct'] else f"{s['value']:.1f}"
            sub_strs.append(f"{s['name']} +{v_str} ({s['count']}次: 低{s['low_rolls']}中{s['mid_rolls']}高{s['high_rolls']})")
        print('      副词条: ' + ' | '.join(sub_strs))

import json
from simulator.db.character_db import CharacterDB

db = CharacterDB()
db.load(r"d:\Downloads\ppSR_REL_4.6.5X\misc\freesr-data.json")

target_ids = [1310, 1107, 1005, 1306]

for cid in target_ids:
    c = db.get(cid)
    p = c.panel
    s = p.summary_dict()
    r = c.get_substat_roll_summary()
    lc = c.light_cone
    
    b_hp = int(p.breakdowns["hp"].base_white)
    b_atk = int(p.breakdowns["atk"].base_white)
    b_def = int(p.breakdowns["def"].base_white)
    b_spd = int(p.breakdowns["spd"].base_white)
    
    g_hp = s["生命值 (HP)"] - b_hp
    g_atk = s["攻击力 (ATK)"] - b_atk
    g_def = s["防御力 (DEF)"] - b_def
    g_spd = s["速度 (SPD)"] - b_spd
    
    sets = list({f"{relic.set_name} (ID {relic.relic_set_id})" for relic in c.relics})
    
    print("--------------------------------------------------")
    print(f"角色: {c.name} | ID: {c.avatar_id} | 命座: E{c.eidolon} | 等级: 80级")
    print(f"光锥: {lc.name if lc else '无'} (S{lc.superimposition if lc else 0}, {lc.level if lc else 0}级)")
    print(f"套装: {', '.join(sets)}")
    print(f"生命值 (HP): {s['生命值 (HP)']} (白字 {b_hp} + 绿字 +{g_hp}) [底层精算: {p.hp:.2f}]")
    print(f"攻击力 (ATK): {s['攻击力 (ATK)']} (白字 {b_atk} + 绿字 +{g_atk}) [底层精算: {p.atk:.2f}]")
    print(f"防御力 (DEF): {s['防御力 (DEF)']} (白字 {b_def} + 绿字 +{g_def}) [底层精算: {p.def_stat:.2f}]")
    print(f"速度 (SPD): {s['速度 (SPD)']} (白字 {b_spd} + 绿字 +{g_spd}) [实战行动值 AV: {10000/p.spd:.2f}, 精算: {p.spd:.3f}]")
    print(f"暴击率 (CR): {s['暴击率 (CR)']} | 暴击伤害 (CD): {s['暴击伤害 (CD)']}")
    print(f"击破特攻 (BE): {s['击破特攻 (BE)']} | 充能效率 (ERR): {s['能量恢复效率 (ERR)']}")
    print(f"效果命中 (EHR): {s['效果命中 (EHR)']} | 效果抵抗 (RES): {s['效果抵抗 (RES)']}")
    print(f"伤害加成 (DMG%): {s['属性伤害加成 (DMG%)']}")
    q = r['quality_score']
    print(f"遗器词条档位统计: 共 {r['total_rolls']} 次 | 高档: {r['high_rolls']} | 中档: {r['mid_rolls']} | 低档: {r['low_rolls']} | 满分品质得分率: {q}%")

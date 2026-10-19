"""验证 CharacterDB 的加载、属性还原与战斗实体生成。"""
import os
import sys

# 保证 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')

from simulator.db import CharacterDB
from simulator.core import TurnSimulator, Entity

def main():
    db_path = r"d:\Downloads\ppSR_REL_4.6.5X\misc\freesr-data.json"
    if not os.path.exists(db_path):
        db_path = r"d:\Downloads\StarRail_4.6.53\freesr-data.json"

    print(f"正在从 [{db_path}] 加载并编译全角色属性数据库...")
    db = CharacterDB().load(db_path)

    # 1. 基础汇总信息
    all_profiles = db.list_all()
    geared = db.list_fully_geared()
    print(f"✅ 成功编译全库: 总角色 {len(all_profiles)} 位，满配主力 {len(geared)} 位！\n")

    # 2. 抽取几位具有代表性的角色打印面板
    sample_ids = [1306, 1310, 1409, 1221, 1501] # 花火, 流萤, 飞霄, 砂金, 斯帕克西
    print("=== 代表性角色面板抽查 ===")
    for aid in sample_ids:
        p = db.get(aid)
        if not p:
            continue
        lc_name = p.light_cone.name if p.light_cone else "未装备光锥"
        lc_s = f"(S{p.light_cone.superimposition})" if p.light_cone else ""
        print(f"【{p.name}】 (ID {p.avatar_id}, E{p.eidolon}, 80级)")
        print(f"  光锥: {lc_name} {lc_s} | 遗器数: {len(p.relics)} 件")
        import math
        b_spd = p.panel.breakdowns["spd"].base_white if "spd" in p.panel.breakdowns else p.panel.spd
        g_spd = p.panel.spd - b_spd
        s = p.panel.summary_dict()
        print(f"  生命: {s['生命值 (HP)']:<5} | 攻击: {s['攻击力 (ATK)']:<5} | 防御: {s['防御力 (DEF)']:<5} | 速度: {s['速度 (SPD)']} (白字 {math.floor(b_spd)} + 绿字 +{math.floor(g_spd)}, 精算 {p.panel.spd:.3f})")
        print(f"  双暴: {s['暴击率 (CR)']} / {s['暴击伤害 (CD)']} | 击破: {s['击破特攻 (BE)']} | 充能: {s['能量恢复效率 (ERR)']} | 命中: {s['效果命中 (EHR)']}\n")

    # 3. 验证一键转换为战斗模拟器实体
    print("=== 验证战斗模拟器实体对接 ===")
    sparkle_entity = db.to_combat_entity("花火", policy="E")
    feixiao_entity = db.to_combat_entity("飞霄·巡猎", policy="EAA")
    print(f"转换实体成功:")
    print(f"  - {sparkle_entity.name}: 速度={sparkle_entity.base_speed:.1f}, 攻击={sparkle_entity.base_atk:.1f}, 暴伤={sparkle_entity.base_crit_dmg*100:.1f}%")
    print(f"  - {feixiao_entity.name}: 速度={feixiao_entity.base_speed:.1f}, 攻击={feixiao_entity.base_atk:.1f}, 暴击={feixiao_entity.base_crit_rate*100:.1f}%")

    # 4. 组队跑一次快速排轴模拟 (花火 + 飞霄)
    boss = Entity(
        name="测试木桩·卡芙卡",
        base_speed=130.0,
        max_hp=200000.0,
        current_hp=200000.0,
        max_toughness=120.0,
        current_toughness=120.0,
        is_enemy=True
    )

    sim = TurnSimulator([sparkle_entity, feixiao_entity, boss], initial_sp=4, max_sp=7)

    # 监听行动事件
    def on_action(evt):
        print(f"  [AV: {evt.av:.1f} | 轮次: {evt.cycle}] ⚔️ {evt.actor_name} 释放【{evt.action_type}】 -> {evt.description}")

    from simulator.events import ActionExecuteEvent
    sim.event_bus.subscribe(ActionExecuteEvent, on_action)

    print("\n=== 首轮排轴与行动验证 (推进前 3 次行动) ===")
    for _ in range(3):
        sim.step()

    # 5. 导出结构化报表
    out_file = "character_db_export.json"
    db.export_summary_json(out_file)
    print(f"\n✅ 全库属性 JSON 报表已成功导出至: {os.path.abspath(out_file)}")

if __name__ == "__main__":
    main()

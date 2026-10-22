#!/usr/bin/env python3
"""星穹铁道战斗模拟器 (Honkai: Star Rail Combat Simulator) - 实战运行与测试启动入口。

使用方法:
    # 1. 默认一键启动经典基准测试场景 (量子雷暴双虚无队 vs 混沌回忆12层首领):
    python3 simulate_battle.py

    # 2. 切换经典队伍预设 (presets: acheron / firefly / dot / followup / clara):
    python3 simulate_battle.py --preset firefly
    python3 simulate_battle.py --preset dot

    # 3. 自定义任意 4 人编队 (支持全库 62 位角色):
    python3 simulate_battle.py --team "流萤,阮•梅,开拓者,加拉赫"
    python3 simulate_battle.py --team "克拉拉,花火,停云,符玄"

    # 4. 自定义战斗轮次与 Boss 参数:
    python3 simulate_battle.py --cycles 3 --boss-hp 500000 --boss-toughness 120
"""
import os
import sys
import argparse
from typing import List, Dict, Any, Optional

# 强制 UTF-8 标准输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.events import (
    TurnBeginEvent, TurnEndEvent, ActionExecuteEvent, 
    DamageAppliedEvent, WeaknessBreakEvent, ToughnessReduceEvent,
    TechniqueExecuteEvent, ToughnessRecoverEvent
)
from simulator.status import StatType
from simulator.kits.registry import get_kit_class


# 预设阵容
TEAM_PRESETS = {
    "acheron": {
        "name": "黄泉量子雷暴队 (Acheron Hypercarry)",
        "members": ["黄泉", "花火", "银狼", "符玄"],
        "policies": {"黄泉": "E", "花火": "E", "银狼": "EAA", "符玄": "EAA"},
        "desc": "花火拉条与暴伤 + 银狼定向减防植入弱点 + 符玄穷观阵护航，黄泉暴力斩击！"
    },
    "firefly": {
        "name": "流萤超击破国家队 (Firefly Super Break)",
        "members": ["流萤", "阮•梅", "开拓者", "加拉赫"],
        "policies": {"流萤": "E", "阮•梅": "EAA", "开拓者": "E", "加拉赫": "EAA"},
        "desc": "阮•梅全队击破效率与提速 + 同谐主伴舞超击破 + 加拉赫酩酊易伤，流萤死星过载狂轰滥炸！"
    },
    "dot": {
        "name": "卡黑持续伤害引爆队 (DoT Explosion)",
        "members": ["卡芙卡", "黑天鹅", "阮•梅", "藿藿"],
        "policies": {"卡芙卡": "E", "黑天鹅": "EAA", "阮•梅": "EAA", "藿藿": "EAA"},
        "desc": "黑天鹅高额奥迹堆叠 + 阮•梅全队抗穿提速 + 藿藿全队回能加攻，卡芙卡疯狂连锁引爆！"
    },
    "followup": {
        "name": "真理托帕追击队 (FUA Synergy)",
        "members": ["真理医生", "托帕", "知更鸟", "砂金"],
        "policies": {"真理医生": "E", "托帕": "E", "知更鸟": "EAA", "砂金": "EAA"},
        "desc": "托帕负债证明 + 知更鸟协奏全队高额附伤与拉条 + 砂金全队护盾，粉笔与账账连环追击！"
    },
    "clara": {
        "name": "克拉拉反击聚仇队 (Clara Counter)",
        "members": ["克拉拉", "花火", "停云", "符玄"],
        "policies": {"克拉拉": "E", "花火": "E", "停云": "EAA", "符玄": "EAA"},
        "desc": "克拉拉聚仇反击 + 停云大额充能与赐福 + 花火战技点支撑，史瓦罗反击横扫千军！"
    }
}


def create_boss_entity(name: str = "拟真首领 (混沌12层)", hp: float = 450000.0, toughness: float = 120.0, speed: float = 115.0) -> Entity:
    """构建高拟真精英/Boss 实体。"""
    return Entity(
        name=name,
        base_speed=speed,
        base_atk=1600.0,
        max_hp=hp,
        current_hp=hp,
        max_toughness=toughness,
        current_toughness=toughness,
        weaknesses=["Quantum", "Lightning", "Fire", "Imaginary"],
        is_enemy=True
    )


class BattleReporter:
    """战斗事件监听与实时统计报表收集器。"""
    def __init__(self, boss_name: str):
        self.boss_name = boss_name
        self.damage_by_actor: Dict[str, float] = {}
        self.break_count = 0
        self.total_damage = 0.0
        self.action_logs: List[str] = []

    def on_damage(self, event: DamageAppliedEvent):
        actor = event.attacker_name
        dmg = event.damage
        self.damage_by_actor[actor] = self.damage_by_actor.get(actor, 0.0) + dmg
        self.total_damage += dmg

    def on_break(self, event: WeaknessBreakEvent):
        self.break_count += 1


def run_simulation(
    team_members: List[str],
    policies: Optional[Dict[str, str]] = None,
    max_cycles: int = 5,
    max_turns: int = 40,
    use_technique: bool = True,
    boss_hp: float = 450000.0,
    boss_toughness: float = 120.0,
    boss_speed: float = 115.0,
    verbose: bool = True
):
    print("\n" + "═" * 78)
    print("      🚀 崩坏：星穹铁道 战斗模拟系统 (HSR Combat Simulator)")
    print("═" * 78)

    # 1. 加载角色数据库
    db_path = os.path.join(PROJECT_ROOT, "data", "character_db_export.json")
    db = CharacterDB().load(db_path) if os.path.exists(db_path) else CharacterDB()

    # 2. 转换编队实体
    entities: List[Entity] = []
    print(f"👥 【出战队伍构建】")
    for name in team_members:
        pol = (policies or {}).get(name, "E")
        ent = db.to_combat_entity(name, policy=pol)
        entities.append(ent)
        kit_name = ent.kit.__class__.__name__ if getattr(ent, "kit", None) else "None"
        print(f"   • {ent.name:10} | 星魂: E{ent.eidolon} | 速度: {ent.base_speed:6.2f} | 攻击: {ent.base_atk:6.1f} | 暴率/暴伤: {ent.base_crit_rate*100:4.1f}%/{ent.base_crit_dmg*100:5.1f}% | 套件: {kit_name}")

    # 3. 创建 Boss 实体
    boss = create_boss_entity("拟真首领·丰饶玄鹿 (Lv.90)", hp=boss_hp, toughness=boss_toughness, speed=boss_speed)
    entities.append(boss)
    print(f"\n👾 【敌方目标配置】")
    print(f"   • {boss.name:22} | 初始生命: {boss.max_hp:,.0f} | 韧性条: {boss.max_toughness:.0f} 点 | 弱点: {', '.join(boss.weaknesses)}")
    print("─" * 78)

    # 4. 初始化模拟器 (开启战前秘技)
    sim = TurnSimulator(
        entities=entities,
        initial_sp=3,
        max_sp=5,
        use_techniques=use_technique,
        technique_users=team_members if use_technique else None,
        auto_ult=True
    )

    reporter = BattleReporter(boss.name)

    # 绑定事件日志与统计
    def log_technique(e: TechniqueExecuteEvent):
        print(f"✨ [战前秘技] 【{e.actor_name}】{e.description}")

    def log_action(e: ActionExecuteEvent):
        sp_info = f"SP: {sim.sp.current_sp}/{sim.sp.max_sp}"
        tough_pct = (boss.current_toughness / boss.max_toughness) * 100 if boss.max_toughness > 0 else 0
        tough_bar = "█" * int(tough_pct // 10) + "░" * (10 - int(tough_pct // 10))
        print(f"[{e.av:6.1f} AV | 第 {e.cycle} 轮] 👤 {e.actor_name:8} 施放 ➔ {e.action_type:20} │ {sp_info:8} │ 敌韧性: [{tough_bar}] {boss.current_toughness:4.0f}/{boss.max_toughness:.0f}")

    def log_damage(e: DamageAppliedEvent):
        crit_mark = "💥 [暴击]" if e.is_crit else "   [命中]"
        print(f"          ↳ {crit_mark} 对 【{e.target_name}】 造成 {e.damage:10,.1f} 点伤害 (剩余HP: {e.target_hp_left:,.0f})")
        reporter.on_damage(e)

    def log_break(e: WeaknessBreakEvent):
        print(f"          ⚡⚡⚡ 【弱点击破 BREAK!!】由 {e.breaker_name} 触发 {e.element} 击破伤害 {e.break_damage:,.1f} 点！(Boss行动延后25%)")
        reporter.on_break(e)

    def log_toughness_recover(e: ToughnessRecoverEvent):
        print(f"          🔄 【韧性恢复】{e.target_name} 行动结束，韧性条完全重置恢复！")

    sim.event_bus.subscribe(TechniqueExecuteEvent, log_technique)
    sim.event_bus.subscribe(ActionExecuteEvent, log_action)
    sim.event_bus.subscribe(DamageAppliedEvent, log_damage)
    sim.event_bus.subscribe(WeaknessBreakEvent, log_break)
    sim.event_bus.subscribe(ToughnessRecoverEvent, log_toughness_recover)

    print("\n⚔️ 【战斗正式打响 (Combat Start)】")

    turn_count = 0
    while turn_count < max_turns and boss.current_hp > 0:
        # 行动推进
        actor = sim.step()
        turn_count += 1

        # 若已超过指定最大轮次
        if sim.current_cycle > max_cycles:
            break

    # 5. 战斗结果结算报表
    print("\n" + "═" * 78)
    print("                     📊 战 斗 结 算 统 计 报 表")
    print("═" * 78)

    battle_result = "🎉 战斗胜利 (VICTORY)" if boss.current_hp <= 0 else "⏱️ 轮次用尽 (CYCLE LIMIT)"
    print(f"【战斗结果】: {battle_result}")
    print(f"【消耗行动值】: {sim.current_av:.2f} AV  │  【消耗轮次】: {sim.current_cycle} 轮 (Cycle)  │  【总行动数】: {turn_count} 动")
    print(f"【Boss状态】 : 生命剩余 {max(0.0, boss.current_hp):,.1f} / {boss.max_hp:,.1f} (扣减率: {(1.0 - max(0.0, boss.current_hp)/boss.max_hp)*100:.1f}%)")
    print(f"【击破次数】: 共造成 {reporter.break_count} 次弱点击破")
    print(f"【全队总伤害】: {reporter.total_damage:,.1f} 点")

    print("\n📈 【队伍角色伤害贡献统计 (Damage Contribution)】:")
    print("─" * 78)
    print(f"  {'角色名称':12} │ {'累计输出伤害':16} │ {'输出占比':10} │ 贡献可视化")
    print("─" * 78)
    for name in team_members:
        dmg = reporter.damage_by_actor.get(name, 0.0)
        pct = (dmg / reporter.total_damage * 100) if reporter.total_damage > 0 else 0.0
        bar = "■" * int(pct // 5)
        print(f"  {name:12} │ {dmg:14,.1f}   │ {pct:8.2f}%  │ {bar}")
    print("═" * 78 + "\n")


def main():
    parser = argparse.ArgumentParser(description="星穹铁道战斗模拟系统测试启动入口")
    parser.add_argument("--preset", type=str, choices=list(TEAM_PRESETS.keys()), default="acheron",
                        help="选择预设队伍 (acheron / firefly / dot / followup / clara)")
    parser.add_argument("--team", type=str, default="",
                        help="自定义 4 人编队，逗号分隔，如: '流萤,阮•梅,开拓者,加拉赫'")
    parser.add_argument("--cycles", type=int, default=3, help="模拟最大轮次 (Cycle)，默认 3 轮")
    parser.add_argument("--turns", type=int, default=30, help="模拟最大行动回合数，默认 30 动")
    parser.add_argument("--no-technique", action="store_true", help="禁用开战前秘技")
    parser.add_argument("--boss-hp", type=float, default=450000.0, help="Boss 最大生命值，默认 450,000")
    parser.add_argument("--boss-toughness", type=float, default=120.0, help="Boss 韧性条，默认 120 点")

    args = parser.parse_args()

    if args.team:
        team_members = [t.strip() for t in args.team.split(",") if t.strip()]
        policies = {m: "E" for m in team_members}
    else:
        preset = TEAM_PRESETS[args.preset]
        team_members = preset["members"]
        policies = preset.get("policies", {})
        print(f"📌 加载官方精选阵容: 【{preset['name']}】")
        print(f"   说明: {preset['desc']}")

    run_simulation(
        team_members=team_members,
        policies=policies,
        max_cycles=args.cycles,
        max_turns=args.turns,
        use_technique=not args.no_technique,
        boss_hp=args.boss_hp,
        boss_toughness=args.boss_toughness
    )


if __name__ == "__main__":
    main()

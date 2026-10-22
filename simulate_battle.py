#!/usr/bin/env python3
"""星穹铁道战斗模拟系统 (Honkai: Star Rail Combat Simulator) - 实战运行与测试启动入口。

使用方法:
    # 1. 启动手动交互打牌对战模式 (亲自决策普攻/战技/终结技插队):
    python3 simulate_battle.py -i
    # 或直接运行并选择 [1] 手动模式:
    python3 simulate_battle.py

    # 2. 切换经典队伍预设 (presets: acheron / firefly / dot / followup / clara):
    python3 simulate_battle.py --preset firefly -i
    python3 simulate_battle.py --preset dot -i

    # 3. 自定义任意 4 人编队 (支持全库 62 位角色):
    python3 simulate_battle.py --team "流萤,阮•梅,开拓者,加拉赫" -i
    python3 simulate_battle.py --team "克拉拉,花火,停云,符玄" -i

    # 4. 全自动基准推演与输出报表:
    python3 simulate_battle.py --auto --preset acheron
"""
import os
import sys
import argparse
from typing import List, Dict, Any, Optional, Tuple

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
from simulator.actions import ActionKind, TargetMode
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
    def __init__(self, boss_name: str, team_members: List[str]):
        self.boss_name = boss_name
        self.team_members = set(team_members)
        self.damage_by_actor: Dict[str, float] = {}
        self.break_count = 0
        self.total_damage = 0.0
        self.action_logs: List[str] = []

    def on_damage(self, event: DamageAppliedEvent):
        actor = event.attacker_name
        dmg = event.damage
        if actor in self.team_members:
            self.damage_by_actor[actor] = self.damage_by_actor.get(actor, 0.0) + dmg
            self.total_damage += dmg

    def on_break(self, event: WeaknessBreakEvent):
        self.break_count += 1


def render_hud(sim: TurnSimulator, boss: Entity, team_members: List[str], current_actor: Entity):
    """绘制富交互战场状态仪表盘 (HUD)。"""
    print("\n" + "═" * 78)
    sp_str = "✦ " * sim.sp.current_sp + "✧ " * max(0, sim.sp.max_sp - sim.sp.current_sp)
    print(f"⏳ 【战斗仪表盘】 轮次: 第 {sim.current_cycle} 轮  │  行动值: {sim.current_av:6.1f} AV  │  战技点: [{sp_str.strip()}] ({sim.sp.current_sp}/{sim.sp.max_sp})")
    print("─" * 78)

    # Boss 状态条
    hp_pct = max(0.0, (boss.current_hp / boss.max_hp) * 100) if boss.max_hp > 0 else 0.0
    hp_bars = int(hp_pct // 5)
    hp_visual = "█" * hp_bars + "░" * (20 - hp_bars)

    tough_pct = max(0.0, (boss.current_toughness / boss.max_toughness) * 100) if boss.max_toughness > 0 else 0.0
    tough_bars = int(tough_pct // 10)
    tough_visual = "█" * tough_bars + "░" * (10 - tough_bars)
    broken_tag = " ⚠️【弱点击破中!】" if boss.is_broken else ""

    print(f"👾 敌方目标: 【{boss.name}】{broken_tag}")
    print(f"   生命值: [{hp_visual}] {max(0.0, boss.current_hp):9,.0f} / {boss.max_hp:9,.0f} ({hp_pct:5.1f}%)")
    print(f"   韧性条: [{tough_visual}] {max(0.0, boss.current_toughness):4.0f} / {boss.max_toughness:.0f} │ 弱点: {', '.join(boss.weaknesses)}")

    # 获取 Boss 身上的 Debuff
    boss_debuffs = [s.name for s in sim.status_mgr.get_statuses(boss.name)]
    if boss_debuffs:
        shown_debuffs = " | ".join(boss_debuffs[:4])
        if len(boss_debuffs) > 4:
            shown_debuffs += f" ...等{len(boss_debuffs)}个负面"
        print(f"   负面状态: 🔻 {shown_debuffs}")
    print("─" * 78)

    # 我方队伍状态
    print("👥 我方队伍:")
    for idx, name in enumerate(team_members):
        ent = sim.get_entity(name)
        if not ent:
            continue

        # 能量显示 (特殊处理黄泉残梦)
        if getattr(ent, "kit", None) and hasattr(ent.kit, "slashed_dream"):
            stacks = ent.kit.slashed_dream
            energy_str = f"残梦: {stacks}/9"
            ready = stacks >= 9
        else:
            energy_str = f"能量: {ent.energy:3.0f}/{ent.max_energy:3.0f}"
            ready = ent.max_energy > 0 and ent.energy >= ent.max_energy

        ready_tag = " 🔥[READY!]" if ready else "          "
        is_turn = "👉" if ent.name == current_actor.name else "  "

        # 角色 buff 摘要
        buffs = [s.name for s in sim.status_mgr.get_statuses(ent.name)]
        buff_summary = f"({buffs[0][:10]}..)" if buffs else ""

        hp_p = (ent.current_hp / ent.max_hp * 100) if ent.max_hp > 0 else 100.0
        print(f" {is_turn} [{idx+1}] {ent.name:8} (E{ent.eidolon}) │ HP: {ent.current_hp:5.0f}/{ent.max_hp:5.0f} ({hp_p:3.0f}%) │ {energy_str} {ready_tag} │ 距行动: {ent.remaining_av:5.1f} AV {buff_summary}")
    print("═" * 78)


def prompt_ally_target(sim: TurnSimulator, actor: Entity, team_members: List[str], action_name: str = "技能") -> Tuple[str, ...]:
    """提示玩家选择单体辅助/治疗的目标队友。"""
    allies = [e for e in sim.entities if not e.is_enemy]
    print(f"\n🎯 【目标选择】请选择【{actor.name}】施放《{action_name}》的目标队友:")
    for idx, ally in enumerate(allies):
        mark = " (主C)" if idx == 0 else ""
        print(f"   [{idx + 1}] {ally.name:10} (HP: {ally.current_hp:.0f}/{ally.max_hp:.0f}){mark}")

    default_idx = 1
    for idx, ally in enumerate(allies):
        if ally.name != actor.name:
            default_idx = idx + 1
            break

    try:
        choice = input(f"👉 请输入目标序号 [1-{len(allies)}, 默认 {default_idx}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice.isdigit() and 1 <= int(choice) <= len(allies):
        chosen = allies[int(choice) - 1]
    else:
        chosen = allies[default_idx - 1]
    print(f"🎯 已锁定目标: 【{chosen.name}】")
    return (chosen.name,)


def handle_cast_ultimate(sim: TurnSimulator, actor: Entity, team_members: List[str]):
    """处理玩家终结技插队施放，若包含单体队友增益则呼叫目标选择器。"""
    defn = None
    if getattr(actor, "kit", None):
        try:
            defn = actor.kit.definition(ActionKind.ULTIMATE)
        except Exception:
            pass
    target_ids = ()
    if defn and hasattr(defn, "target_mode") and defn.target_mode == TargetMode.SINGLE_ALLY:
        target_ids = prompt_ally_target(sim, actor, team_members, action_name=defn.name)
    sim.cast_ultimate(actor.name, target_ids=target_ids)


def run_simulation(
    team_members: List[str],
    policies: Optional[Dict[str, str]] = None,
    max_cycles: int = 5,
    max_turns: int = 40,
    use_technique: bool = True,
    boss_hp: float = 450000.0,
    boss_toughness: float = 120.0,
    boss_speed: float = 115.0,
    interactive: bool = False,
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

    # 4. 初始化模拟器 (交互模式下 auto_ult=False，由玩家自主选择施放时机)
    sim = TurnSimulator(
        entities=entities,
        initial_sp=3,
        max_sp=5,
        use_techniques=use_technique,
        technique_users=team_members if use_technique else None,
        auto_ult=not interactive
    )

    reporter = BattleReporter(boss.name, team_members)

    # 绑定事件日志与统计
    def log_technique(e: TechniqueExecuteEvent):
        print(f"✨ [战前秘技] 【{e.actor_name}】{e.description}")

    def log_action(e: ActionExecuteEvent):
        sp_info = f"SP: {sim.sp.current_sp}/{sim.sp.max_sp}"
        tough_pct = (boss.current_toughness / boss.max_toughness) * 100 if boss.max_toughness > 0 else 0
        tough_bar = "█" * int(tough_pct // 10) + "░" * (10 - int(tough_pct // 10))
        print(f"[{e.av:6.1f} AV | 第 {e.cycle} 轮] 👤 {e.actor_name:8} 施放 ➔ {e.action_type:20} │ {sp_info:8} │ 敌韧性: [{tough_bar}] {max(0.0, boss.current_toughness):4.0f}/{boss.max_toughness:.0f}")

    def log_damage(e: DamageAppliedEvent):
        crit_mark = "💥 [暴击]" if e.is_crit else "   [命中]"
        print(f"          ↳ {crit_mark} 对 【{e.target_name}】 造成 {e.damage:10,.1f} 点伤害 (剩余HP: {max(0.0, e.target_hp_left):,.0f})")
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

    mode_label = "🎮 手动交互模式 (Interactive Manual)" if interactive else "⚡ 全自动模式 (Headless Auto)"
    print(f"\n⚔️ 【战斗正式打响 (Combat Start)】- 模式: {mode_label}")

    turn_count = 0
    auto_all = not interactive
    user_quit = False

    while turn_count < max_turns and boss.current_hp > 0:
        if sim.current_cycle > max_cycles:
            break

        next_ent = sim.next_entity
        if not next_ent:
            break

        # 全自动推演分支
        if auto_all:
            if sim.auto_ult:
                sim.check_and_cast_ultimates()
            sim.step()
            turn_count += 1
            continue

        # 敌方回合分支：提示玩家是否有终结技抢断
        if next_ent.is_enemy:
            ready_ults = sim.get_ready_ultimates()
            if ready_ults:
                print(f"\n⚠️  【敌方行动预警】 敌方【{next_ent.name}】即将行动！")
                print("🔥 当前就绪终结技:")
                for i, u in enumerate(ready_ults):
                    u_defn = u.kit.definition(ActionKind.ULTIMATE) if getattr(u, "kit", None) else None
                    u_name = u_defn.name if u_defn else "终结技"
                    print(f"   [U{i+1}] 【{u.name}】➔ 《{u_name}》")
                try:
                    user_in = input("👉 请输入抢断终结技编号 (如 U1, U2) 或直接按 [Enter] 让敌方行动: ").strip().upper()
                except (EOFError, KeyboardInterrupt):
                    user_in = ""

                if user_in.startswith("U"):
                    idx_str = user_in[1:]
                    if idx_str.isdigit() and 1 <= int(idx_str) <= len(ready_ults):
                        target_char = ready_ults[int(idx_str) - 1]
                        handle_cast_ultimate(sim, target_char, team_members)
                        if boss.current_hp <= 0:
                            break
                        continue
                elif user_in.isdigit() and 1 <= int(user_in) <= len(ready_ults):
                    target_char = ready_ults[int(user_in) - 1]
                    handle_cast_ultimate(sim, target_char, team_members)
                    if boss.current_hp <= 0:
                        break
                    continue

            # 敌方正常行动
            sim.step()
            turn_count += 1
            continue

        # 我方角色回合分支
        render_hud(sim, boss, team_members, next_ent)

        action_override = None
        target_ids = ()

        while True:
            ready_ults = sim.get_ready_ultimates()
            defn_basic = next_ent.kit.definition(ActionKind.BASIC) if getattr(next_ent, "kit", None) else None
            defn_skill = next_ent.kit.definition(ActionKind.SKILL) if getattr(next_ent, "kit", None) else None
            sp_cost = defn_skill.cost.sp if (defn_skill and hasattr(defn_skill, "cost")) else 1
            can_use_skill = sim.sp.can_consume(sp_cost)

            print(f"\n🎮 【{next_ent.name}】回合行动决策 (当前战技点: {sim.sp.current_sp}/{sim.sp.max_sp}):")
            basic_name = defn_basic.name if defn_basic else "普攻"
            print(f"  [1] 普攻 ({basic_name} ➔ 回复 1 SP)")
            skill_name = defn_skill.name if defn_skill else "战技"
            skill_status = f"消耗 {sp_cost} SP" if can_use_skill else "⚠️ 战技点不足"
            print(f"  [2] 战技 ({skill_name} ➔ {skill_status})")

            for i, u in enumerate(ready_ults):
                u_defn = u.kit.definition(ActionKind.ULTIMATE) if getattr(u, "kit", None) else None
                u_name = u_defn.name if u_defn else "终结技"
                print(f"  [U{i+1}] 终结技抢断: 【{u.name}】➔ 《{u_name}》 (Ready!)")

            print(f"  [A]  本回合托管自动 (Auto)")
            print(f"  [AA] 开启全自动战斗 (Full Auto)")
            print(f"  [Q]  认输 / 退出模拟")

            try:
                cmd = input(f"👉 请输入指令 [1/2/U1/A/AA/Q, 默认 1]: ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                cmd = "Q"

            if not cmd:
                cmd = "1"

            if cmd == "1":
                action_override = ActionKind.BASIC
                break
            elif cmd == "2":
                if not can_use_skill:
                    print(f"❌ 战技点不足 (当前 {sim.sp.current_sp} 点，需要 {sp_cost} 点)，无法施放战技！")
                    continue
                action_override = ActionKind.SKILL
                if defn_skill and hasattr(defn_skill, "target_mode") and defn_skill.target_mode == TargetMode.SINGLE_ALLY:
                    target_ids = prompt_ally_target(sim, next_ent, team_members, action_name=defn_skill.name)
                break
            elif cmd.startswith("U") or (cmd.isdigit() and int(cmd) > 2):
                idx_str = cmd[1:] if cmd.startswith("U") else cmd
                if idx_str.isdigit() and 1 <= int(idx_str) <= len(ready_ults):
                    target_char = ready_ults[int(idx_str) - 1]
                    handle_cast_ultimate(sim, target_char, team_members)
                    if boss.current_hp <= 0:
                        break
                    render_hud(sim, boss, team_members, next_ent)
                    continue
                else:
                    print("❌ 无效的终结技编号！")
                    continue
            elif cmd == "A":
                action_override = None
                break
            elif cmd == "AA":
                print("⚡ 已开启全程自动战斗托管！")
                auto_all = True
                sim.auto_ult = True
                action_override = None
                break
            elif cmd == "Q":
                print("🏳️ 玩家主动撤退退出模拟。")
                user_quit = True
                break
            else:
                print("❌ 指令有误，请输入 1 / 2 / U1 / A / AA / Q")

        if user_quit or boss.current_hp <= 0:
            break

        # 执行指定动作
        sim.step(action_override=action_override, target_ids=target_ids)
        turn_count += 1

    # 5. 战斗结果结算报表
    print("\n" + "═" * 78)
    print("                     📊 战 斗 结 算 统 计 报 表")
    print("═" * 78)

    if boss.current_hp <= 0:
        battle_result = "🎉 战斗胜利 (VICTORY)"
    elif user_quit:
        battle_result = "🏳️ 玩家撤退 (RETREAT)"
    else:
        battle_result = "⏱️ 轮次用尽 (CYCLE LIMIT)"

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
    parser.add_argument("--interactive", "-i", action="store_true", help="启动手动交互打牌对战模式 (Manual Turn-by-Turn)")
    parser.add_argument("--auto", action="store_true", help="强制自动推演基准测试 (Auto Benchmark)")
    parser.add_argument("--preset", type=str, choices=list(TEAM_PRESETS.keys()), default=None,
                        help="选择预设队伍 (acheron / firefly / dot / followup / clara)")
    parser.add_argument("--team", type=str, default="",
                        help="自定义 4 人编队，逗号分隔，如: '流萤,阮•梅,开拓者,加拉赫'")
    parser.add_argument("--cycles", type=int, default=3, help="模拟最大轮次 (Cycle)，默认 3 轮")
    parser.add_argument("--turns", type=int, default=40, help="模拟最大行动回合数，默认 40 动")
    parser.add_argument("--no-technique", action="store_true", help="禁用开战前秘技")
    parser.add_argument("--boss-hp", type=float, default=450000.0, help="Boss 最大生命值，默认 450,000")
    parser.add_argument("--boss-toughness", type=float, default=120.0, help="Boss 韧性条，默认 120 点")

    args = parser.parse_args()

    # 判定运行模式：交互 vs 全自动
    interactive_mode = args.interactive
    if not args.interactive and not args.auto:
        # 在交互式终端环境下，默认展示引导菜单并推荐手动交互模式
        if sys.stdin.isatty():
            print("\n" + "═" * 78)
            print("      🎮 欢迎启动【崩坏：星穹铁道】战斗推演模拟器")
            print("═" * 78)
            print("请选择运行模式:")
            print("  [1] 🎮 手动交互对战 (Manual Mode - 亲自选择普攻/战技/终结技插队) [默认]")
            print("  [2] ⚡ 全自动基准推演 (Auto Benchmark - 高速推演并输出统计报表)")
            try:
                mode_choice = input("\n请选择模式 [1/2, 默认 1]: ").strip()
                interactive_mode = (mode_choice != "2")
            except (EOFError, KeyboardInterrupt):
                interactive_mode = False
        else:
            interactive_mode = False

    if args.team:
        team_members = [t.strip() for t in args.team.split(",") if t.strip()]
        policies = {m: "E" for m in team_members}
    elif args.preset:
        preset = TEAM_PRESETS[args.preset]
        team_members = preset["members"]
        policies = preset.get("policies", {})
        print(f"📌 加载指定精选阵容: 【{preset['name']}】")
        print(f"   说明: {preset['desc']}")
    else:
        # 终端交互模式且未指定队伍时，提供队伍选择
        if interactive_mode and sys.stdin.isatty():
            print("\n📋 请选择对战阵容预设:")
            print("  [1] ⚡ 黄泉量子雷暴队 (Acheron Hypercarry) [默认]")
            print("  [2] 🔥 流萤超击破国家队 (Firefly Super Break)")
            print("  [3] 🟣 卡黑持续伤害引爆队 (DoT Explosion)")
            print("  [4] 🎯 真理托帕追击队 (FUA Synergy)")
            print("  [5] 🤖 克拉拉反击聚仇队 (Clara Counter)")
            try:
                preset_choice = input("\n请选择队伍 [1-5, 默认 1]: ").strip()
            except (EOFError, KeyboardInterrupt):
                preset_choice = "1"
            preset_map = {"1": "acheron", "2": "firefly", "3": "dot", "4": "followup", "5": "clara"}
            selected_preset_key = preset_map.get(preset_choice, "acheron")
        else:
            selected_preset_key = "acheron"

        preset = TEAM_PRESETS[selected_preset_key]
        team_members = preset["members"]
        policies = preset.get("policies", {})
        print(f"📌 加载精选阵容: 【{preset['name']}】")
        print(f"   说明: {preset['desc']}")

    run_simulation(
        team_members=team_members,
        policies=policies,
        max_cycles=args.cycles,
        max_turns=args.turns,
        use_technique=not args.no_technique,
        boss_hp=args.boss_hp,
        boss_toughness=args.boss_toughness,
        interactive=interactive_mode
    )


if __name__ == "__main__":
    main()

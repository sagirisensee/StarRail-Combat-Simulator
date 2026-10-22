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
import math
import argparse
from typing import List, Dict, Any, Optional, Tuple

def floor_val(val: float, decimals: int = 1) -> float:
    """遵循星铁引擎统一向下截断规范 (Floor Truncation，含浮点精度微小容差防抖)。"""
    factor = 10 ** decimals
    return math.floor(val * factor + 1e-4) / factor

def floor_int(val: float) -> int:
    """遵循星铁实机整数显示规范。"""
    return math.floor(val + 1e-4)

def floor_str(val: float, decimals: int = 1) -> str:
    """遵循星铁引擎统一向下截断字符串格式化。"""
    return f"{floor_val(val, decimals):.{decimals}f}"

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
    "changyeyue": {
        "name": "长夜月队 (Evernight Moon Synergy)",
        "members": ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"],
        "policies": {"长夜月": "E", "缇宝": "EAA", "知更鸟•晴歌": "EAA", "风堇": "E"},
        "desc": "长夜月永夜冰华 + 缇宝暴伤抗穿追击 + 知更鸟晴歌全队协奏拉条附伤 + 风堇忆灵生命增益，极致爆发！"
    }
}

TARGET_MODE_NAMES = {
    TargetMode.SELF: "自身",
    TargetMode.SINGLE_ALLY: "我方单体",
    TargetMode.ALL_ALLIES: "我方全体",
    TargetMode.SINGLE_ENEMY: "敌方单体",
    TargetMode.ALL_ENEMIES: "敌方全体",
    TargetMode.BLAST: "扩散",
}


STAGE_CONFIG = {
    "id": 1004,
    "name": "将杀王棋 (キングへの挑戦)",
    "level": 100,
    "url": "https://hsr.nanoka.cc/peak/10",
    "mechanics": ["血噬"],
    "buffs": [
        {
            "id": 3033082,
            "name": "狂喜之夜",
            "desc": "我方编队中第 1 位角色造成的欢愉伤害增效 50%（纯净对账：本队无欢愉伤害，等同属性零影响）。",
            "effect_type": "none",
            "modifiers": []
        },
        {
            "id": 3033083,
            "name": "领航誓言 (導き手の誓い)",
            "desc": "我方编队中第 1 位角色 (长夜月) 造成的战技和终结技伤害的全属性抗性穿透提高 50%。",
            "effect_type": "res_pen",
            "modifiers": [("res_pen", 0.50)]
        },
        {
            "id": 3033084,
            "name": "胞吞作用",
            "desc": "【稳态失衡】对【血脑屏障】造成的伤害提高 50%。",
            "effect_type": "break_barrier",
            "modifiers": []
        }
    ],
    "waves": [
        {
            "wave": 1,
            "name": "Wave 1/2 - 精英双锋前驱 (月夜天马 + 「灯塔」)",
            "enemies": [
                {
                    "name": "月夜天马 (Lv.100)",
                    "id": 4023020,
                    "hp": 550000.0,
                    "toughness": 160.0,
                    "speed": 100.0,
                    "weaknesses": ["Fire", "Quantum", "Imaginary"],
                    "damage_res": {"Fire": 0.0, "Quantum": 0.0, "Imaginary": 0.0, "Physical": 0.2, "Wind": 0.2, "Thunder": 0.2, "Ice": 0.2},
                    "infinite_hp": False
                },
                {
                    "name": "「灯塔」 (Lv.100)",
                    "id": 8033020,
                    "hp": 650000.0,
                    "toughness": 160.0,
                    "speed": 144.0,
                    "weaknesses": ["Fire", "Wind", "Quantum"],
                    "damage_res": {"Fire": 0.0, "Wind": 0.0, "Quantum": 0.0, "Physical": 0.2, "Thunder": 0.2, "Ice": 0.2, "Imaginary": 0.2},
                    "infinite_hp": False
                }
            ]
        },
        {
            "wave": 2,
            "name": "Wave 2/2 - 决战首领 堕神之血•亚婆离",
            "enemies": [
                {
                    "name": "堕神之血•亚婆离 (Lv.100)",
                    "id": 5034010,
                    "hp": float("inf"),
                    "toughness": 360.0,
                    "speed": 180.0,
                    "weaknesses": ["Ice", "Quantum", "Imaginary"],
                    "damage_res": {
                        "Ice": 0.0,
                        "Quantum": 0.0,
                        "Imaginary": 0.0,
                        "Physical": 0.20,
                        "Fire": 0.20,
                        "Thunder": 0.20,
                        "Wind": 0.20
                    },
                    "effect_res": 0.30,
                    "infinite_hp": True
                }
            ]
        }
    ]
}


def create_enemy_from_config(cfg: Dict[str, Any]) -> Entity:
    """按 nanoka 官方规范构建敌方单位实体。"""
    infinite = cfg.get("infinite_hp", False)
    eff_hp = float("inf") if infinite else cfg.get("hp", 500000.0)
    enemy = Entity(
        name=cfg["name"],
        base_speed=cfg.get("speed", 120.0),
        base_atk=cfg.get("base_atk", 1600.0),
        base_effect_res=cfg.get("effect_res", 0.30),
        max_hp=eff_hp,
        current_hp=eff_hp,
        max_toughness=cfg.get("toughness", 160.0),
        current_toughness=cfg.get("toughness", 160.0),
        weaknesses=list(cfg.get("weaknesses", ["Ice", "Quantum"])),
        is_enemy=True
    )
    enemy.is_infinite_hp = infinite
    if "damage_res" in cfg:
        enemy.damage_res = cfg["damage_res"]
    return enemy


def create_boss_entity(name: str = "堕神之血•亚婆离 (Lv.100)", hp: float = float("inf"), toughness: float = 360.0, speed: float = 180.0, infinite_hp: bool = True) -> Entity:
    """构建高拟真精英/Boss 实体 (默认开启无限生命木桩对账模式)。"""
    return create_enemy_from_config({
        "name": name,
        "hp": hp,
        "toughness": toughness,
        "speed": speed,
        "weaknesses": ["Ice", "Quantum", "Imaginary"],
        "damage_res": {"Ice": 0.0, "Quantum": 0.0, "Imaginary": 0.0, "Physical": 0.2, "Fire": 0.2, "Thunder": 0.2, "Wind": 0.2},
        "effect_res": 0.30,
        "infinite_hp": infinite_hp
    })


class BattleReporter:
    """战斗事件监听与实时统计报表收集器。"""
    def __init__(self, team_members: List[str]):
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


def render_hud(sim: TurnSimulator, enemies: List[Entity], team_members: List[str], current_actor: Entity, wave_desc: str = ""):
    """绘制富交互战场状态仪表盘 (HUD)。"""
    print("\n" + "═" * 78)
    sp_str = "✦ " * sim.sp.current_sp + "✧ " * max(0, sim.sp.max_sp - sim.sp.current_sp)
    wave_tag = f"  │  🌊 【{wave_desc}】" if wave_desc else ""
    print(f"⏳ 【战斗仪表盘】 轮次: 第 {sim.current_cycle} 轮  │  行动值: {sim.current_av:6.1f} AV  │  战技点: [{sp_str.strip()}] ({sim.sp.current_sp}/{sim.sp.max_sp}){wave_tag}")
    print("─" * 78)

    # 敌方存活目标列表
    alive_enemies = [e for e in enemies if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
    for idx, e in enumerate(alive_enemies, 1):
        is_inf = getattr(e, "is_infinite_hp", False) or e.max_hp == float("inf")
        if is_inf:
            hp_line = "生命值: [████████████████████] ∞ / ∞ (无限木桩对账模式)"
        else:
            hp_pct = max(0.0, (e.current_hp / e.max_hp) * 100) if e.max_hp > 0 else 0.0
            hp_bars = int(hp_pct // 5)
            hp_visual = "█" * hp_bars + "░" * (20 - hp_bars)
            hp_line = f"生命值: [{hp_visual}] {max(0.0, e.current_hp):9,.0f} / {e.max_hp:9,.0f} ({hp_pct:5.1f}%)"

        tough_pct = max(0.0, (e.current_toughness / e.max_toughness) * 100) if e.max_toughness > 0 else 0.0
        tough_bars = int(tough_pct // 10)
        tough_visual = "█" * tough_bars + "░" * (10 - tough_bars)
        broken_tag = " ⚠️【弱点击破中!】" if e.is_broken else ""

        is_enemy_turn = "👉" if e.name == current_actor.name else "  "
        print(f" {is_enemy_turn} [{idx}] 👾 敌方目标: 【{e.name}】{broken_tag} │ 速度: {e.speed:5.1f} │ 距行动: {e.remaining_av:5.1f} AV")
        print(f"       {hp_line}")
        print(f"       韧性条: [{tough_visual}] {max(0.0, e.current_toughness):4.0f} / {e.max_toughness:.0f} │ 弱点: {', '.join(e.weaknesses)}")

        # 获取敌方身上的 Debuff
        e_debuffs = [s.name for s in sim.status_mgr.get_statuses(e.name)]
        if e_debuffs:
            shown_debuffs = " | ".join(e_debuffs[:3])
            if len(e_debuffs) > 3:
                shown_debuffs += f" ...等{len(e_debuffs)}个负面"
            print(f"       负面状态: 🔻 {shown_debuffs}")
    print("─" * 78)

    # 我方队伍状态
    print("👥 我方队伍:")
    for idx, name in enumerate(team_members):
        ent = sim.get_entity(name)
        if not ent:
            continue

        # 能量与就绪状态显示 (通过协议解耦)
        if getattr(ent, "kit", None) and hasattr(ent.kit, "get_energy_display"):
            energy_str = f"{ent.kit.get_energy_display(ent):>11}"
        else:
            energy_str = f"能量: {ent.energy:3.0f}/{ent.max_energy:3.0f}"
        ready = sim.can_cast_ultimate(ent.name)

        ready_tag = " 🔥[READY!]" if ready else "          "
        is_turn = "👉" if ent.name == current_actor.name else "  "

        # 角色 buff 摘要
        buffs = [s.name for s in sim.status_mgr.get_statuses(ent.name)]
        buff_summary = f"({buffs[0][:10]}..)" if buffs else ""

        hp_p = (ent.current_hp / ent.max_hp * 100) if (ent.max_hp > 0 and ent.max_hp != float("inf")) else 100.0
        print(f" {is_turn} [{idx+1}] {ent.name:8} (E{ent.eidolon}) │ HP: {ent.current_hp:5.0f}/{ent.max_hp:5.0f} ({hp_p:3.0f}%) │ {energy_str} {ready_tag} │ 距行动: {ent.remaining_av:5.1f} AV {buff_summary}")
    print("═" * 78)


def render_inspect_panel(sim: TurnSimulator, target_key: str, team_members: List[str], current_actor: Optional[Entity] = None):
    """透析并打印指定角色的实时全量动态属性与所有生效 Buff/Debuff 详情 (对账利器)。"""
    target_clean = target_key.strip().lower() if target_key else ""

    # 优先支持透析伴生忆灵 (如 "长夜")
    memos = sim.status.get("memosprites", {})
    if target_clean in ("长夜", "忆灵", "memosprite") or target_key in memos:
        msnap = memos.get(target_key) or memos.get("长夜") or (next(iter(memos.values())) if memos else None)
        if msnap:
            print("\n" + "━" * 78)
            print(f"🔍 【{msnap['name']}】 伴生忆灵实时状态透析 │ 👻 伴生忆灵 (主体: {msnap['owner']})")
            print("━" * 78)
            print("📊 忆灵动态面板 (遵循星铁实机面板规范):")
            print(f"   • 在场状态          : {'🟢 在场战斗中' if msnap['is_alive'] else '🔴 已离场'}")
            print(f"   • 生命值 (HP)       : {floor_int(msnap['current_hp']):,d} / {floor_int(msnap['max_hp']):,d} ({msnap['hp_pct']*100:.1f}%)")
            print(f"   • 行动速度 (SPD)    : {msnap['speed']:.1f}")
            print(f"   • 实时攻击 (ATK)    : {msnap.get('base_atk', 1072)} + {msnap.get('bonus_atk', 371)} ({msnap.get('current_atk', 1443)})")
            print(f"   • 实时防御 (DEF)    : {msnap.get('base_def', 979)} + {msnap.get('bonus_def', 47)} ({msnap.get('current_def', 1026)})")
            print(f"   • 暴击率 (CRIT)     : {msnap.get('crit_rate', 1.036)*100:.1f}%")
            print(f"   • 暴击伤害 (CDMG)   : {msnap.get('crit_dmg', 6.641)*100:.1f}%")
            print(f"   • 基础嘲讽值        : {msnap.get('aggro', 125)}")
            buff_list = msnap.get("buffs", [])
            print(f"\n🛡️ 忆灵生效增益列表 ({len(buff_list)}项):")
            for idx, b in enumerate(buff_list, 1):
                b_desc = b.get('desc') or b.get('value', '')
                print(f"   [{idx:02d}] {b['name']:24} │ {b_desc}")
            other_list = msnap.get("other_effects", [])
            if other_list:
                print(f"\n⚠️  环境/特殊效果列表:")
                for o in other_list:
                    print(f"   • {o}")
            print("\n⚔️ 忆灵技能与机制组:")
            for s in msnap.get("skills", []):
                print(f"   • {s}")
            print("━" * 78 + "\n")
            return
    ent = None
    target_clean = target_key.strip().lower() if target_key else ""
    if not target_clean:
        ent = current_actor or sim.current_turn_entity or sim.get_entity(team_members[0])
    elif target_clean.isdigit():
        idx = int(target_clean)
        if 1 <= idx <= len(team_members):
            ent = sim.get_entity(team_members[idx - 1])
    elif target_clean in ("boss", "enemy", "0"):
        for e in sim.entities:
            if e.is_enemy:
                ent = e
                break
    else:
        ent = sim.get_entity(target_key)
        if not ent:
            for m in team_members:
                if target_clean in m.lower():
                    ent = sim.get_entity(m)
                    break
        if not ent:
            for e in sim.entities:
                if target_clean in e.name.lower():
                    ent = e
                    break

    if not ent:
        print(f"❌ 未找到指定角色: '{target_key}' (支持输入: 1-{len(team_members)}, 角色名如'长夜月', 或 'boss')")
        return

    snap = sim.status_mgr.get_detailed_snapshot(ent)
    print("\n" + "━" * 78)
    elem_path = f"[{snap['element']}/{snap['path']}] " if snap['element'] else ""
    role_tag = "👾 敌方首领" if getattr(ent, "is_enemy", False) else f"👥 队伍成员 (星魂: E{snap['eidolon']} │ Lv.{snap['level']} │ {elem_path})"
    print(f"🔍 【{snap['name']}】 实时属性与 Buff 全量透析 │ {role_tag}")
    print("━" * 78)
    print("📊 实时动态面板 (Dynamic Attributes - 遵循星铁向下截断规范):")
    hp_str = f"{floor_int(snap['current_hp']):,d} / {floor_int(snap['max_hp']):,d}" if snap['max_hp'] != float("inf") else "∞ / ∞ (无限生命测试木桩)"
    if snap.get('shield', 0.0) > 0:
        hp_str += f" │ 护盾: {floor_int(snap['shield']):,d}"
    print(f"   • 生命值 (HP)       : {hp_str}")
    print(f"   • 行动速度 (SPD)    : {floor_str(snap['current_speed'], 2)} (基础 {floor_str(snap['base_speed'], 2)} │ 面板显示: {round(snap['current_speed'])}) ➔ 距行动: {floor_str(snap['remaining_av'], 2)} AV")
    print(f"   • 实时攻击 (ATK)    : {floor_int(snap['current_atk']):,d} (基础 {floor_int(snap['base_atk']):,d})")
    print(f"   • 实时防御 (DEF)    : {floor_int(snap['current_def']):,d} (基础 {floor_int(snap['base_def']):,d})")
    print(f"   • 暴击率 (CRIT)     : {floor_str(snap['current_crit_rate']*100, 1)}% (基础 {floor_str(snap['base_crit_rate']*100, 1)}%)")
    print(f"   • 暴击伤害 (CDMG)   : {floor_str(snap['current_crit_dmg']*100, 1)}% (基础 {floor_str(snap['base_crit_dmg']*100, 1)}%)")
    if snap.get('outgoing_healing', 0.0) > 0:
        print(f"   • 治疗量加成 (HEAL) : +{floor_str(snap['outgoing_healing']*100, 1)}% (基础 +{floor_str(snap.get('base_outgoing_healing', 0.0)*100, 1)}%)")
    print(f"   • 全属性增伤 (DMG)  : +{floor_str(snap['dmg_boost']*100, 1)}%")
    print(f"   • 属性抗性穿透(PEN) : +{floor_str(snap['res_pen']*100, 1)}%")
    print(f"   • 受到易伤加深(VULN): +{floor_str(snap['vulnerability']*100, 1)}%")
    if snap.get('def_shred', 0.0) > 0:
        print(f"   • 防御削减 (DEF SHRED): +{floor_str(snap['def_shred']*100, 1)}%")
    print(f"   • 击破特攻 (BE)     : +{floor_str(snap['break_effect']*100, 1)}%")
    print(f"   • 效果抵抗 (RES)    : {floor_str(snap['effect_res']*100, 1)}%")
    if snap.get('effect_hit_rate', 0.0) > 0:
        print(f"   • 效果命中 (EHR)    : {floor_str(snap['effect_hit_rate']*100, 1)}%")
    print(f"   • 能量状态 (ENERGY) : {floor_int(snap['current_energy'])} / {floor_int(snap['max_energy'])} (实机精算: {floor_str(snap['current_energy'], 1)})")

    if snap.get("kit_state"):
        print("\n⚙️ 角色专属机制与层数 (Kit Mechanics State):")
        for k, v in snap["kit_state"].items():
            print(f"   • {k}: {v}")

    buffs = snap.get("buffs", [])
    print(f"\n🔮 增益效果 (Buffs - 共 {len(buffs)} 个):")
    if not buffs:
        print("   (暂无增益效果)")
    else:
        for idx, b in enumerate(buffs, 1):
            dur_str = f"{b['duration']} 回合" if b['duration'] is not None else "常驻"
            print(f"   [{idx}] 《{b['name']}》 (ID: {b['id']})")
            print(f"       • 来源: {b['source']} │ 剩余: {dur_str} │ 结算时序: {b['timing']}")
            print(f"       • 效果: {b['modifiers_desc']}")

    debuffs = snap.get("debuffs", [])
    if debuffs:
        print(f"\n🔻 负面效果 (Debuffs - 共 {len(debuffs)} 个):")
        for idx, b in enumerate(debuffs, 1):
            dur_str = f"{b['duration']} 回合" if b['duration'] is not None else "常驻"
            print(f"   [{idx}] 《{b['name']}》 (ID: {b['id']})")
            print(f"       • 来源: {b['source']} │ 剩余: {dur_str} │ 结算时序: {b['timing']}")
            print(f"       • 效果: {b['modifiers_desc']}")

    other_effects = snap.get("other_effects", [])
    if other_effects:
        print(f"\n🌀 其他效果 (Other Effects - 共 {len(other_effects)} 个):")
        for idx, b in enumerate(other_effects, 1):
            dur_str = f"{b['duration']} 回合" if b['duration'] is not None else "常驻/领域"
            print(f"   [{idx}] 《{b['name']}》 (ID: {b['id']})")
            print(f"       • 来源: {b['source']} │ 剩余: {dur_str} │ 结算时序: {b['timing']}")
            print(f"       • 效果: {b['modifiers_desc']}")
    print("━" * 78)


def prompt_enemy_target(sim: TurnSimulator, actor: Entity, action_name: str = "攻击") -> Tuple[str, ...]:
    """提示玩家选择敌方单体目标（在场上有多名敌人时）。"""
    enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
    if len(enemies) <= 1:
        return (enemies[0].name,) if enemies else ()
    print(f"\n🎯 【目标选择】请选择【{actor.name}】施放《{action_name}》的目标敌方:")
    for idx, e in enumerate(enemies, 1):
        hp_str = f"{e.current_hp:,.0f}/{e.max_hp:,.0f}" if e.max_hp != float("inf") else "∞ / ∞"
        print(f"   [{idx}] 【{e.name}】 (HP: {hp_str} │ 韧性: {e.current_toughness:.0f}/{e.max_toughness:.0f} │ 弱点: {', '.join(e.weaknesses)})")

    try:
        choice = input(f"👉 请输入目标序号 [1-{len(enemies)}, 默认 1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"

    if choice.isdigit() and 1 <= int(choice) <= len(enemies):
        chosen = enemies[int(choice) - 1]
    else:
        chosen = enemies[0]
    print(f"🎯 已锁定敌方目标: 【{chosen.name}】")
    return (chosen.name,)


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
    """处理玩家终结技插队施放，若包含单体队友增益或单体敌方目标则呼叫选择器。"""
    defn = None
    if getattr(actor, "kit", None):
        try:
            defn = actor.kit.definition(ActionKind.ULTIMATE)
        except Exception:
            pass
    target_ids = ()
    if defn and hasattr(defn, "target_mode"):
        if defn.target_mode == TargetMode.SINGLE_ALLY:
            target_ids = prompt_ally_target(sim, actor, team_members, action_name=defn.name)
        elif defn.target_mode == TargetMode.SINGLE_ENEMY:
            target_ids = prompt_enemy_target(sim, actor, action_name=defn.name)
    sim.cast_ultimate(actor.name, target_ids=target_ids)


def run_simulation(
    team_members: List[str],
    policies: Optional[Dict[str, str]] = None,
    max_cycles: int = 5,
    max_turns: int = 40,
    use_technique: bool = True,
    start_wave: int = 1,
    stage_buff_idx: int = 0,
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
        # 遵循星铁混沌回忆/实战基准规则：角色进场默认享有 50% 基础能量充能
        if ent.max_energy > 0 and ent.energy == 0.0:
            ent.energy = ent.max_energy * 0.5
        entities.append(ent)
        kit_name = ent.kit.__class__.__name__ if getattr(ent, "kit", None) else "None"
        print(f"   • {ent.name:10} | 星魂: E{ent.eidolon} | 速度: {ent.base_speed:6.2f} | 攻击: {ent.base_atk:6.1f} | 暴率/暴伤: {ent.base_crit_rate*100:4.1f}%/{ent.base_crit_dmg*100:5.1f}% | 套件: {kit_name}")

    lead_char = entities[0]
    buffs_list = STAGE_CONFIG.get("buffs", [])
    selected_buff = buffs_list[stage_buff_idx] if 0 <= stage_buff_idx < len(buffs_list) else buffs_list[0]
    print(f"\n🏰 【对战关卡】: {STAGE_CONFIG['name']} (Lv.{STAGE_CONFIG['level']})")
    print(f"   • 关卡祝福: 《{selected_buff['name']}》 - {selected_buff['desc']}")

    # 3. 创建首发波次敌方实体
    current_wave_idx = max(0, min(len(STAGE_CONFIG["waves"]) - 1, start_wave - 1))
    current_wave_cfg = STAGE_CONFIG["waves"][current_wave_idx]
    current_enemies = [create_enemy_from_config(c) for c in current_wave_cfg["enemies"]]
    for e in current_enemies:
        entities.append(e)

    print(f"\n🌊 【{current_wave_cfg['name']}】 敌方目标配置:")
    for e in current_enemies:
        hp_disp = f"{e.max_hp:,.0f}" if e.max_hp != float("inf") else "∞ (无限木桩模式)"
        print(f"   • {e.name:22} | 初始生命: {hp_disp} | 速度: {e.speed:5.1f} | 韧性条: {e.max_toughness:.0f} 点 | 弱点: {', '.join(e.weaknesses)}")
    print("─" * 78)

    # 4. 初始化模拟器 (交互模式下 auto_ult=False，由玩家自主选择施放时机)
    sim = TurnSimulator(
        entities=entities,
        initial_sp=3,
        max_sp=5,
        use_techniques=use_technique,
        technique_users=team_members if use_technique else None,
        auto_ult=not interactive,
        stage_mechanics=STAGE_CONFIG.get("mechanics", [])
    )
    sim.wave_info = {"current": current_wave_idx + 1, "total": len(STAGE_CONFIG["waves"]), "name": current_wave_cfg["name"]}

    # 装配所选关卡祝福到 1 号位角色
    from simulator.status import StatusInstance, Modifier, ModifierOp, DurationTiming
    buff_mods = []
    for stat_name, val in selected_buff.get("modifiers", []):
        if stat_name == "res_pen":
            buff_mods.append(Modifier(StatType.RES_PEN, ModifierOp.ADD, val))
    sim.status_mgr.add_status(StatusInstance(
        id=f"StageBuff_{selected_buff['id']}",
        name=f"关卡祝福: {selected_buff['name']}",
        source=lead_char,
        target=lead_char,
        duration=None,
        timing=DurationTiming.TARGET_TURN_END,
        modifiers=buff_mods
    ))

    reporter = BattleReporter(team_members)

    # 绑定事件日志与统计
    def log_technique(e: TechniqueExecuteEvent):
        print(f"✨ [战前秘技] 【{e.actor_name}】{e.description}")

    def log_action(e: ActionExecuteEvent):
        sp_info = f"SP: {sim.sp.current_sp}/{sim.sp.max_sp}"
        print(f"[{e.av:6.1f} AV | 第 {e.cycle} 轮] 👤 {e.actor_name:8} 施放 ➔ {e.action_type:20} │ {sp_info:8}")

    def log_damage(e: DamageAppliedEvent):
        crit_mark = "💥 [暴击]" if e.is_crit else "   [命中]"
        target_ent = sim.get_entity(e.target_name)
        is_inf = getattr(target_ent, "is_infinite_hp", False) if target_ent else False
        hp_left_str = "∞ (木桩)" if (e.target_hp_left == float("inf") or is_inf) else f"{max(0.0, e.target_hp_left):,.0f}"
        print(f"          ↳ {crit_mark} 对 【{e.target_name}】 造成 {e.damage:10,.1f} 点伤害 (剩余HP: {hp_left_str})")
        reporter.on_damage(e)

    def log_break(e: WeaknessBreakEvent):
        print(f"          ⚡⚡⚡ 【弱点击破 BREAK!!】由 {e.breaker_name} 触发 {e.element} 击破伤害 {e.break_damage:,.1f} 点！(行动延后25%)")
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
    skip_wave = False

    # 4.1 开场就绪决策 (Battle Start Decision)
    if interactive:
        while True:
            ready_ults = sim.get_ready_ultimates()
            alive_enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
            if not alive_enemies:
                break

            print("\n" + "═" * 78)
            print(f"🚩 【开场就绪决策 (Battle Opening)】 - 战前秘技与关卡祝福已生效 │ 🌊 【{current_wave_cfg['name']}】")
            print("─" * 78)
            print(f"当前战技点: {sim.sp.current_sp}/{sim.sp.max_sp} │ 跑道初始行动值: 0.0 AV")
            print("👥 我方编队起始状态:")
            for idx, m_name in enumerate(team_members):
                m_ent = sim.get_entity(m_name)
                if m_ent:
                    buff_cnt = len(sim.status_mgr.get_statuses(m_name))
                    print(f"   [{idx+1}] 【{m_ent.name}】(E{m_ent.eidolon}) │ 速度: {m_ent.speed:.1f} │ 能量: {m_ent.energy:.0f}/{m_ent.max_energy:.0f} │ 距行动: {m_ent.remaining_av:.1f} AV │ Buff: {buff_cnt}个")

            if ready_ults:
                print("\n🔥【队伍就绪终结技 (可立即先手施放)】:")
                for i, u in enumerate(ready_ults):
                    u_defn = u.kit.definition(ActionKind.ULTIMATE) if getattr(u, "kit", None) else None
                    u_name = u_defn.name if u_defn else "终结技"
                    t_desc = TARGET_MODE_NAMES.get(getattr(u_defn, "target_mode", None), "敌方全体")
                    e_desc = u.kit.get_energy_display(u) if (getattr(u, "kit", None) and hasattr(u.kit, "get_energy_display")) else f"能量: {u.energy:.0f}/{u.max_energy:.0f}"
                    print(f"  [U{i+1}] 【{u.name}】 · 《{u_name}》 ({e_desc} │ 目标: {t_desc})")

            print("\n【可选决策】:")
            print("  [Enter]    起跑，推进跑道行动")
            if ready_ults:
                print("  [U<序号>]  先手抢施对应终结技 (如 U1)")
            print("  [I <目标>] 透析角色实时属性与生效Buff (如 I 1, I 2, I 长夜月, I boss, I 灯塔)")
            if current_wave_idx + 1 < len(STAGE_CONFIG["waves"]):
                print("  [NW]       跳过当前波次直接进入下一波 (Next Wave)")
            print("  [AA]       开启全自动战斗")
            print("  [Q]        认输 / 退出模拟")
            print("─" * 78)

            try:
                raw_cmd = input("👉 请输入开场决策指令 [Enter/I 1/U1/NW/AA/Q, 默认 Enter]: ").strip()
            except (EOFError, KeyboardInterrupt):
                raw_cmd = ""

            cmd = raw_cmd.upper()

            if not cmd:
                break
            elif cmd == "I" or cmd.startswith("I ") or (len(cmd) > 1 and cmd[0] == "I" and cmd[1:].strip()):
                target_key = raw_cmd[1:].strip()
                render_inspect_panel(sim, target_key, team_members)
                continue
            elif cmd == "NW":
                skip_wave = True
                break
            elif cmd.startswith("U") or (cmd.isdigit() and ready_ults):
                idx_str = cmd[1:] if cmd.startswith("U") else cmd
                if idx_str.isdigit() and 1 <= int(idx_str) <= len(ready_ults):
                    target_char = ready_ults[int(idx_str) - 1]
                    handle_cast_ultimate(sim, target_char, team_members)
                    continue
                else:
                    print("❌ 无效的终结技编号！")
            elif cmd == "AA":
                print("⚡ 已开启全程自动战斗托管！")
                auto_all = True
                sim.auto_ult = True
                break
            elif cmd == "Q":
                user_quit = True
                break
            else:
                print("❌ 指令有误，请输入 Enter / I 1 / U1 / NW / AA / Q")

    # 4.2 战斗回合主循环 (当跑道有单位到达终点 0.0 AV 时触发决策，支持多波次推进)
    while turn_count < max_turns:
        if sim.current_cycle > max_cycles or user_quit:
            break

        # 波次检查与切换判定
        alive_enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
        if not alive_enemies or skip_wave:
            if current_wave_idx + 1 < len(STAGE_CONFIG["waves"]):
                current_wave_idx += 1
                next_wave_cfg = STAGE_CONFIG["waves"][current_wave_idx]
                print("\n" + "🏁 " + "═" * 76)
                if skip_wave:
                    print(f"⚡ 【跳过波次】玩家手动触发切波！直接进入 【{next_wave_cfg['name']}】！")
                else:
                    print(f"🏁 【波次通关 (Wave {current_wave_idx} Complete)】 敌方已全部肃清！")
                    print(f"   🌊 正在进入 【{next_wave_cfg['name']}】...")
                print("   (全队当前行动值、能量、战技点与身上增益无损继承！)")
                print("🏁 " + "═" * 76 + "\n")

                # 移除旧波次敌人，加入新波次敌人
                sim.entities = [e for e in sim.entities if not e.is_enemy]
                new_enemies = [create_enemy_from_config(c) for c in next_wave_cfg["enemies"]]
                for ne in new_enemies:
                    sim.add_entity(ne, trigger_battle_start=False)

                current_wave_cfg = next_wave_cfg
                sim.wave_info = {"current": current_wave_idx + 1, "total": len(STAGE_CONFIG["waves"]), "name": current_wave_cfg["name"]}
                skip_wave = False
                continue
            else:
                print("🎉 【战斗大捷】所有波次敌方首领均已肃清！")
                break

        # 跑道推进：让最快到达终点的单位抵达终点 (0.0 AV) 并结算回合开始状态
        actor = sim.advance_to_next_turn()
        if not actor:
            break

        # 敌方死绝检查
        alive_enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
        if not alive_enemies:
            continue

        # 全自动推演分支
        if auto_all:
            if sim.auto_ult:
                sim.check_and_cast_ultimates()
            sim.execute_current_turn()
            turn_count += 1
            continue

        # 敌方单位到达终点：提示玩家敌方即将行动，列出所有可触发的插队终结技
        if actor.is_enemy:
            while True:
                ready_ults = sim.get_ready_ultimates()
                alive_enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
                if not ready_ults or not alive_enemies:
                    sim.execute_current_turn()
                    turn_count += 1
                    break

                print("\n" + "═" * 78)
                print(f"⚠️  【敌方行动预警】 敌方【{actor.name}】已到达终点 (0.0 AV)，即将行动！│ 🌊 【{current_wave_cfg['name']}】")
                print("─" * 78)
                print("🔥【我方队伍就绪终结技 (可在此刻抢断插队，先发制人)】:")
                for i, u in enumerate(ready_ults):
                    u_defn = u.kit.definition(ActionKind.ULTIMATE) if getattr(u, "kit", None) else None
                    u_name = u_defn.name if u_defn else "终结技"
                    t_desc = TARGET_MODE_NAMES.get(getattr(u_defn, "target_mode", None), "敌方全体")
                    e_desc = u.kit.get_energy_display(u) if (getattr(u, "kit", None) and hasattr(u.kit, "get_energy_display")) else f"能量: {u.energy:.0f}/{u.max_energy:.0f}"
                    print(f"  [U{i+1}] 【{u.name}】 · 《{u_name}》 ({e_desc} │ 目标: {t_desc})")

                print("\n【可选决策】:")
                print("  [Enter]    不抢断，继续敌方行动")
                if ready_ults:
                    print("  [U<序号>]  抢断施放对应终结技 (如 U1)")
                print("  [I <目标>] 透析角色实时属性与Buff (如 I 1, I 长夜月, I boss)")
                print("  [AA]       开启全自动战斗")
                print("  [Q]        认输 / 退出模拟")
                print("─" * 78)

                try:
                    raw_cmd = input("👉 请输入决策指令 [Enter/U1/I 1/AA/Q, 默认 Enter]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    raw_cmd = ""

                cmd = raw_cmd.upper()

                if not cmd:
                    sim.execute_current_turn()
                    turn_count += 1
                    break
                elif cmd == "I" or cmd.startswith("I ") or (len(cmd) > 1 and cmd[0] == "I" and cmd[1:].strip()):
                    target_key = raw_cmd[1:].strip()
                    render_inspect_panel(sim, target_key, team_members, current_actor=actor)
                    continue
                elif cmd.startswith("U") or cmd.isdigit():
                    idx_str = cmd[1:] if cmd.startswith("U") else cmd
                    if idx_str.isdigit() and 1 <= int(idx_str) <= len(ready_ults):
                        target_char = ready_ults[int(idx_str) - 1]
                        handle_cast_ultimate(sim, target_char, team_members)
                        continue
                    else:
                        print("❌ 无效的终结技编号！")
                elif cmd == "AA":
                    auto_all = True
                    sim.auto_ult = True
                    sim.execute_current_turn()
                    turn_count += 1
                    break
                elif cmd == "Q":
                    user_quit = True
                    break

            if user_quit:
                break
            continue

        # 我方角色到达终点：展示完整战场仪表盘与所有可触发决策
        while True:
            alive_enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
            render_hud(sim, alive_enemies, team_members, actor, wave_desc=current_wave_cfg["name"])
            ready_ults = sim.get_ready_ultimates()

            defn_basic = actor.kit.definition(ActionKind.BASIC) if getattr(actor, "kit", None) else None
            defn_skill = actor.kit.definition(ActionKind.SKILL) if getattr(actor, "kit", None) else None
            sp_cost = defn_skill.cost.sp if (defn_skill and hasattr(defn_skill, "cost")) else 1
            can_use_skill = sim.sp.can_consume(sp_cost)

            basic_name = defn_basic.name if defn_basic else "普攻"
            basic_target = TARGET_MODE_NAMES.get(getattr(defn_basic, "target_mode", None), "敌方单体")
            skill_name = defn_skill.name if defn_skill else "战技"
            skill_target = TARGET_MODE_NAMES.get(getattr(defn_skill, "target_mode", None), "敌方单体")

            print(f"\n🎮 【当前决策窗口】 轮到【{actor.name}】行动 (距终点: 0.0 AV │ 战技点: {sim.sp.current_sp}/{sim.sp.max_sp}):")
            print("─" * 78)
            print("【本回合行动决策】:")
            print(f"  [1] 普攻: 《{basic_name}》 (回复 1 SP │ 目标: {basic_target})")
            skill_sp_desc = f"消耗 {sp_cost} SP" if can_use_skill else f"⚠️ 战技点不足 (需 {sp_cost} 点)"
            print(f"  [2] 战技: 《{skill_name}》 ({skill_sp_desc} │ 目标: {skill_target})")

            if ready_ults:
                print("\n🔥【队伍就绪终结技 (可随时抢断插队)】:")
                for i, u in enumerate(ready_ults):
                    u_defn = u.kit.definition(ActionKind.ULTIMATE) if getattr(u, "kit", None) else None
                    u_name = u_defn.name if u_defn else "终结技"
                    t_desc = TARGET_MODE_NAMES.get(getattr(u_defn, "target_mode", None), "敌方全体")
                    e_desc = u.kit.get_energy_display(u) if (getattr(u, "kit", None) and hasattr(u.kit, "get_energy_display")) else f"能量: {u.energy:.0f}/{u.max_energy:.0f}"
                    is_self_tag = " (当前行动者)" if u.name == actor.name else ""
                    print(f"  [U{i+1}] 【{u.name}】 · 《{u_name}》 ({e_desc} │ 目标: {t_desc}){is_self_tag}")

            print("\n【透析与控制】:")
            print("  [I <目标>] 透析属性与Buff (直接按 I 查当前角色，或 I 1 / I 2 / I boss)")
            if current_wave_idx + 1 < len(STAGE_CONFIG["waves"]):
                print("  [NW]       跳过当前波次直接进入下一波 (Next Wave)")
            print("  [A]        本回合托管自动 (Auto)")
            print("  [AA]       开启全自动战斗 (Full Auto)")
            print("  [Q]        认输 / 退出模拟")
            print("─" * 78)

            try:
                raw_cmd = input(f"👉 请输入决策指令 [1/2/U1/I/NW/A/AA/Q, 默认 1]: ").strip()
            except (EOFError, KeyboardInterrupt):
                raw_cmd = "Q"

            cmd = raw_cmd.upper()

            if not cmd:
                cmd = "1"

            if cmd == "1":
                target_ids = ()
                if defn_basic and hasattr(defn_basic, "target_mode") and defn_basic.target_mode == TargetMode.SINGLE_ENEMY:
                    target_ids = prompt_enemy_target(sim, actor, action_name=basic_name)
                sim.execute_current_turn(action_override=ActionKind.BASIC, target_ids=target_ids)
                turn_count += 1
                break
            elif cmd == "2":
                if not can_use_skill:
                    print(f"❌ 战技点不足 (当前 {sim.sp.current_sp} 点，需要 {sp_cost} 点)，无法施放战技！")
                    continue
                target_ids = ()
                if defn_skill and hasattr(defn_skill, "target_mode"):
                    if defn_skill.target_mode == TargetMode.SINGLE_ALLY:
                        target_ids = prompt_ally_target(sim, actor, team_members, action_name=defn_skill.name)
                    elif defn_skill.target_mode == TargetMode.SINGLE_ENEMY:
                        target_ids = prompt_enemy_target(sim, actor, action_name=defn_skill.name)
                sim.execute_current_turn(action_override=ActionKind.SKILL, target_ids=target_ids)
                turn_count += 1
                break
            elif cmd == "NW":
                skip_wave = True
                break
            elif cmd == "I" or cmd.startswith("I ") or (len(cmd) > 1 and cmd[0] == "I" and cmd[1:].strip()):
                target_key = raw_cmd[1:].strip()
                render_inspect_panel(sim, target_key, team_members, current_actor=actor)
                continue
            elif cmd.startswith("U") or (cmd.isdigit() and int(cmd) > 2):
                idx_str = cmd[1:] if cmd.startswith("U") else cmd
                if idx_str.isdigit() and 1 <= int(idx_str) <= len(ready_ults):
                    target_char = ready_ults[int(idx_str) - 1]
                    handle_cast_ultimate(sim, target_char, team_members)
                    continue
                else:
                    print("❌ 无效的终结技编号！")
                    continue
            elif cmd == "A":
                sim.execute_current_turn(action_override=None)
                turn_count += 1
                break
            elif cmd == "AA":
                print("⚡ 已开启全程自动战斗托管！")
                auto_all = True
                sim.auto_ult = True
                sim.execute_current_turn(action_override=None)
                turn_count += 1
                break
            elif cmd == "Q":
                print("🏳️ 玩家主动撤退退出模拟。")
                user_quit = True
                break
            else:
                print("❌ 指令有误，请输入 1 / 2 / U1 / I / NW / A / AA / Q")

        if user_quit:
            break

    # 5. 战斗结果结算报表
    print("\n" + "═" * 78)
    print("                     📊 战 斗 结 算 统 计 报 表")
    print("═" * 78)

    alive_enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
    if not alive_enemies and current_wave_idx + 1 >= len(STAGE_CONFIG["waves"]):
        battle_result = "🎉 战斗大捷 (VICTORY - 全波次肃清)"
    elif user_quit:
        battle_result = "🏳️ 玩家撤退 (RETREAT)"
    else:
        battle_result = "⏱️ 轮次用尽 (CYCLE LIMIT)"

    print(f"【战斗结果】: {battle_result}")
    print(f"【推进进度】: 当前波次 {current_wave_idx + 1}/{len(STAGE_CONFIG['waves'])} ({current_wave_cfg['name']})")
    print(f"【消耗行动值】: {sim.current_av:.2f} AV  │  【消耗轮次】: {sim.current_cycle} 轮 (Cycle)  │  【总行动数】: {turn_count} 动")
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
    parser.add_argument("--preset", type=str, choices=list(TEAM_PRESETS.keys()), default="changyeyue",
                        help="选择预设队伍 (changyeyue)")
    parser.add_argument("--team", type=str, default="",
                        help="自定义 4 人编队，逗号分隔，如: '长夜月,缇宝,知更鸟•晴歌,风堇'")
    parser.add_argument("--cycles", type=int, default=3, help="模拟最大轮次 (Cycle)，默认 3 轮")
    parser.add_argument("--turns", type=int, default=40, help="模拟最大行动回合数，默认 40 动")
    parser.add_argument("--wave", type=int, choices=[1, 2], default=1,
                        help="选择起始波次 (1: 精英双锋 月夜天马+灯塔, 2: 堕神之血•亚婆离)")
    parser.add_argument("--stage-buff", type=int, choices=[1, 2, 3], default=1,
                        help="关卡全局祝福选择 (1: 狂喜之夜 [默认/欢愉纯净对账], 2: 领航誓言 [抗穿+50%%], 3: 胞吞作用)")
    parser.add_argument("--no-technique", action="store_true", help="禁用开战前秘技")

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
    else:
        # 终端交互模式且未显式指定自定义队伍时，展示阵容确认
        if interactive_mode and sys.stdin.isatty():
            print("\n📋 当前精选阵容预设:")
            print("  [1] 🌙 长夜月队 (长夜月, 缇宝, 知更鸟•晴歌, 风堇) [默认]")
            try:
                preset_choice = input("\n请选择队伍 [1, 默认 1]: ").strip()
            except (EOFError, KeyboardInterrupt):
                preset_choice = "1"
            selected_preset_key = "changyeyue"
        else:
            selected_preset_key = args.preset or "changyeyue"

        preset = TEAM_PRESETS[selected_preset_key]
        team_members = preset["members"]
        policies = preset.get("policies", {})
        print(f"📌 加载精选阵容: 【{preset['name']}】")
        print(f"   说明: {preset['desc']}")

    wave_choice = args.wave
    if interactive_mode and sys.stdin.isatty() and args.wave == 1:
        print("\n🌊 请选择关卡起始波次:")
        print("  [1] Wave 1: 月夜天马 + 「灯塔」 (双精英开局) [默认]")
        print("  [2] Wave 2: 堕神之血•亚婆离 (决战首领直达)")
        try:
            w_input = input("请选择波次 [1/2, 默认 1]: ").strip()
            if w_input in ("1", "2"):
                wave_choice = int(w_input)
        except (EOFError, KeyboardInterrupt):
            wave_choice = 1

    stage_buff_choice = args.stage_buff
    if interactive_mode and sys.stdin.isatty() and args.stage_buff == 1:
        print("\n🔮 请选择关卡全局祝福:")
        print("  [1] 狂喜之夜 (欢愉伤害增效50% - 纯净对账模式，队伍无欢愉伤害) [默认]")
        print("  [2] 领航誓言 (长夜月战技/终结技全属性抗穿+50%)")
        print("  [3] 胞吞作用 (稳态失衡对血脑屏障伤害提高50%)")
        try:
            b_input = input("请选择关卡祝福 [1-3, 默认 1]: ").strip()
            if b_input in ("1", "2", "3"):
                stage_buff_choice = int(b_input)
        except (EOFError, KeyboardInterrupt):
            stage_buff_choice = 1

    run_simulation(
        team_members=team_members,
        policies=policies,
        max_cycles=args.cycles,
        max_turns=args.turns,
        use_technique=not args.no_technique,
        start_wave=wave_choice,
        stage_buff_idx=stage_buff_choice - 1,
        interactive=interactive_mode
    )


if __name__ == "__main__":
    main()

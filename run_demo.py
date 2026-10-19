"""Honkai: Star Rail Combat Simulator & Database - Entrypoint Demo.

Runs:
1. End-to-end combat simulation with Boss toughness, break, action advance, delay, buffs, damage
2. High-precision character database inspection and verification
"""
import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulator.demo import demo as run_combat_demo


def run_db_demo():
    print("\n" + "=" * 76)
    print("  【全角色高精属性数据库与实战对接】 (CharacterDB Engine)")
    print("=" * 76)

    export_path = os.path.join(os.path.dirname(__file__), "data", "character_db_export.json")
    if os.path.exists(export_path):
        import json
        with open(export_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chars = data.get("characters", [])
        print(f"✅ 已加载持久化数据库：全库收录 {data.get('total_avatars', len(chars))} 位角色档案！\n")
        
        sample_names = ["开拓者·同谐", "知更鸟·晴歌", "克拉拉", "流萤", "花火"]
        print("--- 重点角色面板抽检（验证实机展示与底层浮点） ---")
        for c in chars:
            if c.get("name") in sample_names:
                summary = c.get("stats_summary", {})
                print(f"【{c['name']}】({c['element']} / {c['path']}, 80级)")
                print(f"  面板速度展示: {summary.get('速度面板显示')} | 实战精算浮点: {summary.get('速度实战精算')}")
                print(f"  生命: {summary.get('生命值 (HP)')} | 攻击: {summary.get('攻击力 (ATK)')} | 防御: {summary.get('防御力 (DEF)')}")
                print(f"  双暴: {summary.get('暴击率 (CR)')} / {summary.get('暴击伤害 (CD)')} | 击破: {summary.get('击破特攻 (BE)')}\n")
    print("=" * 76)


if __name__ == "__main__":
    run_combat_demo()
    run_db_demo()

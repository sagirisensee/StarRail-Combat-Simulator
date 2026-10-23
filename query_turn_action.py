#!/usr/bin/env python3
"""星穹铁道回合与行动状态机械查询脚本 (Query Turn & Action State)。

机械化调用战斗模拟引擎底层真实状态，直接输出：
1. 当前行动值 (AV) 与轮次 (Cycle)
2. 目前是谁的回合 (Current Actor)
3. 本回合当前行动者可行动的 Action (Available Actions for Current Actor)
4. 当前队伍中就绪可抢断插队的终结技 (Ready Ultimates)

使用方法:
  python query_turn_action.py              # 查询开局第 1 动 (开场顶轴 0.0 AV) 决策状态
  python query_turn_action.py --step 1     # 推进 1 动并查询第 2 动决策状态
  python query_turn_action.py --step 2     # 推进 2 动并查询第 3 动决策状态
"""
import os
import sys
import argparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulate_battle import STAGE_CONFIG, create_enemy_from_config, render_inspect_panel


def run_query(step_count: int = 0, team_names: list = None, enemy_type: str = "boss", inspect_target: str = "", interactive: bool = False):
    if team_names is None:
        team_names = ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]

    db_path = os.path.join(PROJECT_ROOT, "data", "character_db_export.json")
    db = CharacterDB().load(db_path) if os.path.exists(db_path) else CharacterDB()

    team = []
    for name in team_names:
        ent = db.to_combat_entity(name)
        if ent.max_energy > 0 and ent.energy == 0.0:
            ent.energy = ent.max_energy * 0.5
        team.append(ent)

    if enemy_type == "boss":
        # 使用无限生命决战首领木桩进行纯净对账推演
        enemies = [Entity(
            name="堕神之血•亚婆离 (Lv.100)",
            base_speed=180.0,
            max_hp=float("inf"),
            current_hp=float("inf"),
            max_toughness=360.0,
            current_toughness=360.0,
            weaknesses=["Ice", "Quantum", "Imaginary"],
            is_enemy=True
        )]
        enemies[0].is_infinite_hp = True
    else:
        enemies = [create_enemy_from_config(c) for c in STAGE_CONFIG["waves"][0]["enemies"]]

    sim = TurnSimulator(
        entities=team + enemies,
        initial_sp=3,
        max_sp=5,
        use_techniques=True,
        technique_users=team_names,
        auto_ult=False,
        stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
    )

    # 推进模式：若指定 --interactive 则跳过非玩家交互动作，直达首个玩家决策点
    if interactive:
        sim.advance_to_interactive_turn()
        for i in range(step_count):
            actor = sim.step()
            if not actor:
                break
    else:
        # 推进指定步数
        for i in range(step_count):
            actor = sim.step()
            if not actor:
                break

    # 输出当前决策窗口信息
    sim.print_turn_action_info()

    if inspect_target:
        render_inspect_panel(sim, inspect_target, team_names)


def main():
    parser = argparse.ArgumentParser(description="星穹铁道回合与行动状态机械查询工具")
    parser.add_argument("--step", type=int, default=0, help="推进指定步数后查询 (默认0: 开局顶轴)")
    parser.add_argument("--interactive", action="store_true", help="跳过系统自动施放动作(如长夜入场自动喷水)，直达首个玩家可操作决策回合")
    parser.add_argument("--team", type=str, default="长夜月,缇宝,知更鸟•晴歌,风堇", help="队伍角色名 (逗号分隔)")
    parser.add_argument("--enemy", type=str, default="boss", choices=["boss", "wave1"], help="对战敌方配置")
    parser.add_argument("--status", type=str, default="", help="查询指定角色或忆灵的实时状态透析面板 (如 '长夜月' 或 '长夜')")
    args = parser.parse_args()

    team_members = [n.strip() for n in args.team.split(",") if n.strip()]
    run_query(step_count=args.step, team_names=team_members, enemy_type=args.enemy, inspect_target=args.status, interactive=args.interactive)


if __name__ == "__main__":
    main()

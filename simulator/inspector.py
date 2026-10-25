"""战场状态透析与只读查询视图服务 (Battle Inspector & Query DSL).

职责边界：
- 从 `TurnSimulator` 微内核中剥离所有只读视图、快照汇总、点号路径检索（`query_status`）与终端打印逻辑；
- 保持 `TurnSimulator` 专注于时间轴跑条与战斗状态机流转。
"""
import sys
from typing import Dict, Any, TYPE_CHECKING
from .actions import ActionKind, TargetMode

if TYPE_CHECKING:
    from .core import TurnSimulator


class BattleInspector:
    """战场实时状态快照构建器与查询解析器。"""

    def __init__(self, sim: "TurnSimulator"):
        self.sim = sim

    def get_turn_action_info(self) -> Dict[str, Any]:
        """获取当前决策窗口的核心信息（AV、当前行动者、可选 Action 列表、就绪终结技）。"""
        actor = self.sim.current_turn_entity
        if actor is None:
            alive = [e for e in self.sim.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
            if alive:
                actor = self.sim.peek_next_actor()
                av = self.sim.current_av + (actor.remaining_av if actor else 0.0)
            else:
                actor = None
                av = self.sim.current_av
        else:
            av = self.sim.current_av

        actor_name = actor.name if actor else "无"
        is_memosprite = getattr(actor, "is_memosprite", False)
        if is_memosprite:
            actor_type = "伴生忆灵"
        elif actor and actor.is_enemy:
            actor_type = "敌方目标"
        else:
            actor_type = "我方角色"

        target_map = {
            TargetMode.SELF: "自身",
            TargetMode.SINGLE_ALLY: "我方单体",
            TargetMode.ALL_ALLIES: "我方全体",
            TargetMode.SINGLE_ENEMY: "敌方单体",
            TargetMode.ALL_ENEMIES: "敌方全体",
            TargetMode.BLAST: "扩散",
            TargetMode.BOUNCE: "弹射",
        }

        actions = []
        if actor and getattr(actor, "kit", None) is not None:
            for kind in (ActionKind.SKILL, ActionKind.BASIC):
                try:
                    defn = actor.kit.definition(kind)
                    if defn:
                        if any(a["name"] == defn.name for a in actions):
                            continue
                        sp_cost = getattr(defn.cost, "sp", 0)
                        can_afford = (sp_cost <= 0) or self.sim.sp.can_consume(sp_cost)
                        target_desc = target_map.get(getattr(defn, "target_mode", None), "敌方单体")

                        custom_tag = getattr(defn, "tag", "")
                        if custom_tag:
                            tag = custom_tag
                        elif is_memosprite:
                            tag = "忆灵技"
                        elif kind == ActionKind.SKILL:
                            tag = "战技"
                        else:
                            tag = "普攻"

                        actions.append({
                            "kind": kind.name,
                            "name": defn.name,
                            "cost_sp": sp_cost,
                            "available": can_afford,
                            "target": target_desc,
                            "tag": tag,
                            "is_auto": getattr(defn, "is_auto", False)
                        })
                except Exception:
                    pass
        elif actor:
            actions.append({
                "kind": "NORMAL",
                "name": "敌方行动" if actor.is_enemy else "普通行动",
                "cost_sp": 0,
                "available": True,
                "target": "我方" if actor.is_enemy else "敌方",
                "tag": "行动"
            })

        ready_ults = []
        for u in self.sim.get_ready_ultimates():
            u_defn = u.kit.definition(ActionKind.ULTIMATE) if getattr(u, "kit", None) else None
            u_name = u_defn.name if u_defn else "终结技"
            e_raw = u.kit.get_energy_display(u) if (getattr(u, "kit", None) and hasattr(u.kit, "get_energy_display")) else f"{math.floor(u.energy)}/{math.floor(u.max_energy)}"
            e_desc = e_raw.replace("能量:", "").replace("能量", "").strip()
            ready_ults.append({
                "name": u.name,
                "action_name": u_name,
                "energy": e_desc,
                "is_current_actor": (u.name == actor_name)
            })

        return {
            "av": round(av, 2),
            "cycle": self.sim.current_cycle,
            "current_actor": actor_name,
            "actor_type": actor_type,
            "is_memosprite": is_memosprite,
            "actions": actions,
            "ready_ultimates": ready_ults,
            "sp": {"current": self.sim.sp.current_sp, "max": self.sim.sp.max_sp}
        }

    def print_turn_action_info(self) -> None:
        """格式化输出当前回合行动信息，供脚本演算与实时查看。"""
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        info = self.get_turn_action_info()
        all_auto = len(info['actions']) > 0 and all(a.get('is_auto', False) for a in info['actions'])
        actor_state = f"{info['actor_type']} · 自动行动中(不可手动操作)" if all_auto else f"{info['actor_type']} · 玩家可操作回合"
        print("=" * 70)
        print(f"[行动时钟]: {info['av']:.1f} AV (第 {info['cycle']} 轮) | 战技点: {info['sp']['current']}/{info['sp']['max']}")
        print(f"[目前是谁的回合]: 【{info['current_actor']}】 ({actor_state})")
        print("-" * 70)
        print("[本回合可行动的 Action]:")
        for idx, act in enumerate(info['actions'], 1):
            if act.get('is_auto'):
                avail_tag = "[系统自动施放 · 官方设定不可手动操作]"
            else:
                avail_tag = "[玩家可操作]" if act['available'] else "[战技点不足]"
            sp_tag = f"消耗 {act['cost_sp']} SP" if act['cost_sp'] > 0 else "无消耗"
            print(f"  [{idx}] 【{act['tag']}】《{act['name']}》 ({sp_tag} | 目标: {act['target']} | {avail_tag})")
        if info['ready_ultimates']:
            print("\n[当前可抢断插队的终结技 (Ready Ultimates)]:")
            for idx, ult in enumerate(info['ready_ultimates'], 1):
                self_tag = " (当前行动者)" if ult['is_current_actor'] else ""
                print(f"  [U{idx}] 【{ult['name']}】 · 《{ult['action_name']}》 (能量: {ult['energy']} [就绪!]){self_tag}")
        else:
            print("\n[当前可抢断插队的终结技]: 暂无角色就绪")
        print("=" * 70)

    def get_battle_status(self) -> Dict[str, Any]:
        """获取当前全战场统一状态视图 (Single Source of Truth: status)。"""
        timeline = []
        for e in sorted(self.sim.entities, key=lambda x: x.remaining_av):
            timeline.append({
                "name": e.name,
                "remaining_av": round(e.remaining_av, 2),
                "distance": round(e.distance_remaining, 1),
                "speed": round(e.speed, 2),
                "is_enemy": e.is_enemy
            })

        ready_ults = [u.name for u in self.sim.get_ready_ultimates()]

        meta = {
            "av": round(self.sim.current_av, 2),
            "cycle": self.sim.current_cycle,
            "sp": {
                "current": self.sim.sp.current_sp,
                "max": self.sim.sp.max_sp
            },
            "current_actor": self.sim.current_turn_entity.name if self.sim.current_turn_entity else None,
            "ready_ultimates": ready_ults,
            "timeline": timeline
        }

        team = {}
        enemies = {}
        memosprites = {}

        for e in self.sim.entities:
            snap = self.sim.status_mgr.get_detailed_snapshot(e)
            if e.is_enemy:
                enemies[e.name] = snap
            else:
                team[e.name] = snap
            kit = getattr(e, "kit", None)
            if kit and hasattr(kit, "get_memosprite_snapshot"):
                msnap = kit.get_memosprite_snapshot()
                if msnap:
                    memosprites[msnap["name"]] = msnap

        return {
            "meta": meta,
            "team": team,
            "enemies": enemies,
            "memosprites": memosprites
        }

    def query_status(self, query: str = "") -> Any:
        """从统一 status 中智能检索信息，支持快捷名称、属性名或点号路径。"""
        st = self.get_battle_status()
        query = query.strip()
        if not query:
            return st

        if query.lower() in ("sp", "skill_points", "战技点"):
            return st["meta"]["sp"]
        if query.lower() in ("av", "action_value", "行动值"):
            return st["meta"]["av"]
        if query.lower() in ("cycle", "轮次"):
            return st["meta"]["cycle"]
        if query.lower() in ("timeline", "跑道", "行动顺序"):
            return st["meta"]["timeline"]
        if query.lower() in ("boss", "enemy", "怪物", "首领"):
            return next(iter(st["enemies"].values())) if st["enemies"] else None

        if "memosprites" in st and query in st["memosprites"]:
            return st["memosprites"][query]
        for name, data in st["team"].items():
            if query == name:
                return data
        for name, data in st["enemies"].items():
            if query == name:
                return data
        for m_name, m_data in st.get("memosprites", {}).items():
            if query.lower() in m_name.lower():
                return m_data
        for name, data in st["team"].items():
            if query.lower() in name.lower():
                return data
        for name, data in st["enemies"].items():
            if query.lower() in name.lower():
                return data

        parts = query.split(".")
        first_part = parts[0]
        curr_root = None
        all_targets = {**st["team"], **st["enemies"], **st.get("memosprites", {})}
        for name, data in all_targets.items():
            if first_part == name:
                curr_root = data
                parts = parts[1:]
                break
        if curr_root is None:
            for name, data in all_targets.items():
                if first_part.lower() in name.lower():
                    curr_root = data
                    parts = parts[1:]
                    break

        curr: Any = curr_root if curr_root is not None else st
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            elif isinstance(curr, dict):
                found = False
                for k, v in curr.items():
                    if k.lower() == p.lower():
                        curr = v
                        found = True
                        break
                if not found:
                    return None
            else:
                return None
        return curr

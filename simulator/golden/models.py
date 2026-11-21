# coding: utf-8
"""Golden Trace 数据模型与常量（从 golden_diff.py 拆分）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from simulator.actions import ActionKind

# 我方 ActionKind -> 官方 OnUseSkill 的 skill.type 对照
SKILL_TYPE_BY_KIND = {
    ActionKind.BASIC: "Normal",
    ActionKind.SKILL: "BPSkill",
    ActionKind.ULTIMATE: "Ultra",
    ActionKind.MEMOSPRITE_SKILL: "Servant",
    ActionKind.ELATION_SKILL: "ElationDamage",
}

# 官方技能类型 -> 决策类型 (仅玩家角色本体的主动决策; 忆灵技与被动触发为自动行为, 不入脚本)
_DECISION_KIND_BY_TYPE = {"Normal": "basic", "BPSkill": "skill", "Ultra": "ult"}

# 官方全部伴生忆灵 ServantID -> 中文名映射（对齐 AvatarServantConfig + TextMapCHS）
SERVANT_NAMES: Dict[int, str] = {
    11402: "衣匠",
    11407: "死龙•玻吕刻斯",
    11409: "小伊卡",
    11413: "长夜",
    11415: "德谬歌",
    11512: "晴空乐手",
    18007: "迷迷",
}


def _load_spirit_trajectory_skills() -> Dict[int, str]:
    """从官方 ExcelOutput/AvatarServantSkillConfig.json 自动加载全部主动忆灵技 SkillID -> 忆灵名映射。"""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "TurnBasedGameData",
        "ExcelOutput",
        "AvatarServantSkillConfig.json",
    )
    out: Dict[int, str] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for row in rows:
                    if row.get("AttackType") != "Servant":
                        continue
                    sid = int(row.get("SkillID") or 0)
                    if sid <= 0 or sid in out:
                        continue
                    servant_id = sid // 100
                    out[sid] = SERVANT_NAMES.get(servant_id, f"Servant_{servant_id}")
        except Exception:
            pass
    if not out:
        out = {
            1141301: "长夜",
            1141307: "长夜",
            1140901: "小伊卡",
            1151201: "晴空乐手",
        }
    return out


SPIRIT_TRAJECTORY_SKILLS: Dict[int, str] = _load_spirit_trajectory_skills()


def _load_known_avatar_names() -> Dict[int, str]:
    """从角色数据库自动加载全部 avatar_id -> 角色名映射，避免在通用框架中硬编码阵容。"""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "character_db_export.json",
    )
    mapping: Dict[int, str] = {}
    if os.path.exists(db_path):
        with open(db_path, encoding="utf-8") as f:
            raw = json.load(f)
        for ch in raw.get("characters") or ():
            aid = ch.get("avatar_id")
            name = ch.get("name")
            if aid is not None and name:
                mapping[int(aid)] = str(name)
    return mapping


KNOWN_AVATAR_NAMES: Dict[int, str] = _load_known_avatar_names()


@dataclass
class SkillCast:
    actor: str
    name: str
    skill_type: str = "Unknown"
    config_id: Optional[int] = None


@dataclass
class DamageHit:
    attacker: str
    damage_type: str
    damage: float


@dataclass
class TurnRecord:
    index: int
    av: float
    owner: str
    skills: List[SkillCast] = field(default_factory=list)
    damages: List[DamageHit] = field(default_factory=list)

    @property
    def total_damage(self) -> float:
        return sum(d.damage for d in self.damages)


@dataclass
class BattleSequence:
    source: str
    turns: List[TurnRecord] = field(default_factory=list)
    total_damage: float = 0.0
    final_av: float = 0.0
    enemy_names: Dict[int, str] = field(default_factory=dict)

    def damage_by_attacker(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for t in self.turns:
            for d in t.damages:
                out[d.attacker] = out.get(d.attacker, 0.0) + d.damage
        return out

    def hits_by_attacker(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for t in self.turns:
            for d in t.damages:
                out[d.attacker] = out.get(d.attacker, 0) + 1
        return out

    def damage_by_type(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for t in self.turns:
            for d in t.damages:
                out[d.damage_type] = out.get(d.damage_type, 0.0) + d.damage
        return out

    def skill_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for t in self.turns:
            for s in t.skills:
                if s.name:
                    out[f"{s.actor}: {s.name}"] = out.get(f"{s.actor}: {s.name}", 0) + 1
        return out


@dataclass
class Decision:
    """官方日志中的一次玩家决策 (角色回合行动或终结技抢断)。"""

    actor: str
    kind: str  # "basic" | "skill" | "ult"
    skill_id: int
    name: str


@dataclass
class Divergence:
    av: float
    kind: str  # "turn_order" | "ult_blocked" | "ult_failed" | "sp_downgrade" | "script_exhausted"
    detail: str


@dataclass
class Grant:
    """强制回放中为钉死决策而补足的资源 (即模拟自身经济产出与脚本需求的差额)。"""

    av: float
    actor: str
    kind: str  # "energy" | "sp"
    amount: float


@dataclass
class ReplayResult:
    decisions_total: int
    turn_matched: int
    turn_total: int
    ult_matched: int
    ult_total: int
    divergences: List[Divergence] = field(default_factory=list)
    sequence: Optional[BattleSequence] = None
    forced: bool = False
    grants: List[Grant] = field(default_factory=list)


@dataclass
class TrajectoryCast:
    av: float
    actor: str
    skill_id: int
    name: str
    order: int = -1


@dataclass
class TrajectoryRecord:
    skill_id: int
    name: str
    official_av: float
    fired_av: Optional[float]
    mode: str  # "organic" | "forced" | "failed" | "unforceable"
    patches: Tuple[str, ...] = ()


@dataclass
class TimelineItem:
    av: float
    kind: str  # "basic" | "skill" | "ult" | "spirit"
    actor: str
    skill_id: int
    name: str
    target_ids: Optional[Tuple[str, ...]] = None
    turn_owner: str = ""
    turn_seq: int = 0
    target_uids: Optional[Tuple[int, ...]] = None
    between_enemy_sub_actions: bool = False


@dataclass
class MasterRecord:
    actor: str
    skill_id: int
    name: str
    official_av: float
    fired_av: Optional[float]


@dataclass
class TrajectoryResult:
    replay: Any
    records: List[TrajectoryRecord] = field(default_factory=list)
    master_records: List[MasterRecord] = field(default_factory=list)
    ult_records: List[MasterRecord] = field(default_factory=list)
    memoria_granted: float = 0.0
    presence_grants: int = 0
    ult_energy_granted: float = 0.0
    sp_granted: int = 0
    sunk_turns: int = 0


def _golden_actor_display(uid: Any, team: str, enemy_names: Dict[int, str], dmg_type: str = "") -> str:
    if team == "Enemy":
        return enemy_names.get(uid, f"敌人#{uid}")
    return KNOWN_AVATAR_NAMES.get(uid, f"UID_{uid}")


def _sim_player_actors(sim: Any) -> Set[str]:
    """从当前模拟器实体列表动态提取我方参战角色本体名集合。"""
    return {
        e.name
        for e in getattr(sim, "entities", ())
        if not getattr(e, "is_enemy", False)
        and not getattr(e, "is_memosprite", False)
        and not getattr(e, "is_countdown", False)
    }

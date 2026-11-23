# coding: utf-8
"""对账与插件自动生成器数据模型与公共辅助（从 reconcile_generator.py 拆分）。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from simulator.db.character_db import CharacterDB

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_CHAR_DB_PATH = os.path.join(ROOT_DIR, "data", "character_db_export.json")
SKIP_SENTINEL = "__SKIP__"

_SERVANT_SKILL_EFFECT_CACHE: Optional[Dict[int, str]] = None
_AVATAR_SKILL_EFFECT_CACHE: Optional[Dict[int, str]] = None
_AVATAR_SKILL_STANCE_CACHE: Optional[Dict[int, float]] = None
_AVATAR_DAMAGE_TYPE_CACHE: Optional[Dict[int, str]] = None


def _get_servant_skill_effects() -> Dict[int, str]:
    """从官方 ExcelOutput/AvatarServantSkillConfig.json 加载 SkillID -> SkillEffect 映射。"""
    global _SERVANT_SKILL_EFFECT_CACHE
    if _SERVANT_SKILL_EFFECT_CACHE is not None:
        return _SERVANT_SKILL_EFFECT_CACHE
    out: Dict[int, str] = {}
    path = os.path.join(
        ROOT_DIR, "data", "TurnBasedGameData", "ExcelOutput", "AvatarServantSkillConfig.json"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for row in rows:
                    sid = int(row.get("SkillID") or 0)
                    eff = str(row.get("SkillEffect") or "")
                    if sid and eff and sid not in out:
                        out[sid] = eff
        except Exception:
            pass
    _SERVANT_SKILL_EFFECT_CACHE = out
    return out


def _get_avatar_skill_effects() -> Dict[int, str]:
    """从官方 ExcelOutput/AvatarSkillConfig.json 加载 SkillID -> SkillEffect 映射。"""
    global _AVATAR_SKILL_EFFECT_CACHE
    if _AVATAR_SKILL_EFFECT_CACHE is not None:
        return _AVATAR_SKILL_EFFECT_CACHE
    out: Dict[int, str] = {}
    path = os.path.join(
        ROOT_DIR, "data", "TurnBasedGameData", "ExcelOutput", "AvatarSkillConfig.json"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for row in rows:
                    sid = int(row.get("SkillID") or 0)
                    eff = str(row.get("SkillEffect") or "")
                    if sid and eff and sid not in out:
                        out[sid] = eff
        except Exception:
            pass
    _AVATAR_SKILL_EFFECT_CACHE = out
    return out


def _get_avatar_skill_stances() -> Dict[int, float]:
    """从官方 ExcelOutput/AvatarSkillConfig.json 加载 SkillID -> 主目标削韧值映射。"""
    global _AVATAR_SKILL_STANCE_CACHE
    if _AVATAR_SKILL_STANCE_CACHE is not None:
        return _AVATAR_SKILL_STANCE_CACHE
    out: Dict[int, float] = {}
    path = os.path.join(
        ROOT_DIR, "data", "TurnBasedGameData", "ExcelOutput", "AvatarSkillConfig.json"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for row in rows:
                    sid = int(row.get("SkillID") or 0)
                    if not sid or sid in out:
                        continue
                    ssl = row.get("ShowStanceList") or []
                    vals = [
                        float(v.get("Value", 0.0) if isinstance(v, dict) else (v or 0.0))
                        for v in ssl
                    ]
                    max_s = max(vals) if vals else 0.0
                    if max_s > 0.0:
                        out[sid] = max_s
        except Exception:
            pass
    _AVATAR_SKILL_STANCE_CACHE = out
    return out


def _get_avatar_damage_types() -> Dict[int, str]:
    """从官方 ExcelOutput/AvatarConfig.json 加载 AvatarID -> 规范元素名映射。"""
    global _AVATAR_DAMAGE_TYPE_CACHE
    if _AVATAR_DAMAGE_TYPE_CACHE is not None:
        return _AVATAR_DAMAGE_TYPE_CACHE
    out: Dict[int, str] = {}
    path = os.path.join(
        ROOT_DIR, "data", "TurnBasedGameData", "ExcelOutput", "AvatarConfig.json"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for row in rows:
                    aid = int(row.get("AvatarID") or 0)
                    dt = str(row.get("DamageType") or "")
                    if aid and dt:
                        out[aid] = "Lightning" if dt == "Thunder" else dt
        except Exception:
            pass
    _AVATAR_DAMAGE_TYPE_CACHE = out
    return out


@dataclass
class EnemyHitRecord:
    """从实机日志敌方回合自动提取的我方受击目标记录。"""

    av: float
    enemy_uid: int
    hit_allies: List[str] = field(default_factory=list)
    hit_counts: Dict[str, int] = field(default_factory=dict)
    had_hp_drop: bool = False
    had_passive_heal: bool = False
    sp_gain_counts: Dict[str, int] = field(default_factory=dict)
    first_memo_owner: Optional[str] = None


@dataclass
class AhaTurnRecord:
    """从实机日志自动提取的阿哈回合（敌方弹射扣血 + 我方伴生微伤）。"""

    av: float
    enemy_damages: List[Tuple[int, float]] = field(default_factory=list)
    ally_chip_hits: List[str] = field(default_factory=list)
    ally_sp_gain_counts: Dict[str, int] = field(default_factory=dict)
    lethal_enemy_uids: Set[int] = field(default_factory=set)
    shielded_enemy_uids: Set[int] = field(default_factory=set)


@dataclass
class AmbiguousMemospriteSlot:
    """敌方回合内存在差额 (missing_hits > 0) 且有多种分配候选的待确认位点。"""

    key: Tuple[float, int, str]
    av: float
    enemy_uid: int
    kind: str
    candidates: List[Tuple[str, ...]]
    default_choice: Tuple[str, ...]


@dataclass
class InferredMemospriteHit:
    """差额反推或二次确认锁定的忆灵受击/敌方跳过记录。"""

    av: float
    enemy_uid: int
    kind: str
    targets: Tuple[str, ...]
    source: str


@dataclass
class EnemyHitMismatch:
    """敌方回合现场三方（官方期望 / 日志实录 / 模拟实际）命中集合不一致的诊断项。"""

    av: float
    enemy_name: str
    log_hits: Tuple[str, ...]
    sim_hits: Tuple[str, ...]
    skill_id: int = 0
    skill_key: str = ""
    expected_scope: str = ""
    expected_hits: Tuple[str, ...] = ()


@dataclass
class LogMetadata:
    """从实机战斗日志提取的通用元信息。"""

    log_path: str
    tag: str
    stage_id: int
    team_uids: List[int]
    team_names: List[str]
    enemy_hits: List[EnemyHitRecord]
    final_av: float
    enemy_uid_map: Dict[int, str] = field(default_factory=dict)
    ally_ult_targets: Dict[str, List[str]] = field(default_factory=dict)
    enemy_retarget_picks: List[Tuple[float, int, int]] = field(default_factory=list)
    player_enemy_targets: Dict[Tuple[float, str], List[str]] = field(default_factory=dict)
    servant_targets: Dict[Tuple[float, str], List[Optional[str]]] = field(default_factory=dict)
    aha_turns: List[AhaTurnRecord] = field(default_factory=list)
    windwalk_enemy_uids: Set[int] = field(default_factory=set)
    slow_hits: Set[Tuple[float, str]] = field(default_factory=set)
    enemy_hp_at_turn_end: Dict[Tuple[float, str], float] = field(default_factory=dict)
    enemy_spawns: List[Tuple[float, int, str]] = field(default_factory=list)
    gluttony_enemy_names: Set[str] = field(default_factory=set)
    entry_element: Optional[str] = None
    entry_toughness: float = 10.0


@dataclass
class TurnDiffEntry:
    """单动伤害对比条目。"""

    av: float
    gt_total: float
    sim_total: float
    err: float
    attackers: List[str]
    breakdown: Dict[str, Tuple[float, float]]


@dataclass
class ReconcileReport:
    """通用对账运行结果。"""

    meta: LogMetadata
    stage_mode: str
    plugin_mode: str
    turn_matched: int
    turn_total: int
    ult_matched: int
    ult_total: int
    sp_granted: int
    memoria_granted: float
    presence_grants: int
    forced_or_failed: int
    golden_total_damage: float
    sim_total_damage: float
    total_err: float
    max_turn_err: float
    turn_diffs: List[TurnDiffEntry]
    inferred_memosprite_hits: List[InferredMemospriteHit] = field(default_factory=list)
    unresolved_ambiguous_slots: int = 0
    non_crits: Set[Tuple[int, int]] = field(default_factory=set)
    enemy_hit_mismatches: List[EnemyHitMismatch] = field(default_factory=list)


def _extract_tag(log_path: str) -> str:
    base = os.path.basename(log_path)
    m = re.search(r"battle_(\d{8}_\d{6})", base)
    if m:
        return m.group(1)
    return os.path.splitext(base)[0]


def _resolve_uid_name(uid: int, db: CharacterDB) -> str:
    rp = db.get(uid)
    if rp is not None:
        return rp.name
    return f"UID_{uid}"

# coding: utf-8
"""官方 ExcelOutput 数据驱动的基础属性查表层（零手写白值/词条硬编码）。

直接从 `data/TurnBasedGameData/ExcelOutput/` 加载 7 张官方原始配置表：
- `AvatarConfig.json` + `AvatarPromotionConfig.json` + `AvatarSkillTreeConfig.json`
- `EquipmentConfig.json` + `EquipmentPromotionConfig.json` + `EquipmentSkillConfig.json`
- `RelicMainAffixConfig.json` + `RelicSubAffixConfig.json` + `RelicSetConfig.json` + `RelicSetSkillConfig.json`

同时提供：
- 任意等级/突破/叠影精确公式函数（`get_avatar_base_stats` / `get_lightcone_stats` /
  `get_relic_main_value` / `get_relic_sub_rule`）
- 与既有调用方兼容的 `AVATAR_STATS` / `LIGHTCONE_STATS` / `RELIC_MAIN_VALUES` /
  `RELIC_SUB_RULES` / `RELIC_SETS` 视图。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_EXCEL_DIR = os.path.join(_ROOT_DIR, "data", "TurnBasedGameData", "ExcelOutput")

# 官方 PropertyType -> 面板内部键名、是否百分比、中文显示名
_PROP_META: Dict[str, Tuple[str, bool, str]] = {
    "HPDelta": ("flat_hp", False, "生命值"),
    "HPAddedRatio": ("hp_pct", True, "生命值%"),
    "AttackDelta": ("flat_atk", False, "攻击力"),
    "AttackAddedRatio": ("atk_pct", True, "攻击力%"),
    "DefenceDelta": ("flat_def", False, "防御力"),
    "DefenceAddedRatio": ("def_pct", True, "防御力%"),
    "SpeedDelta": ("spd", False, "速度"),
    "BaseSpeed": ("spd", False, "速度"),
    "SpeedAddedRatio": ("spd_pct", True, "速度%"),
    "CriticalChanceBase": ("crit_rate", True, "暴击率"),
    "CriticalDamageBase": ("crit_dmg", True, "暴击伤害"),
    "StatusProbabilityBase": ("ehr", True, "效果命中"),
    "StatusResistanceBase": ("res", True, "效果抵抗"),
    "BreakDamageAddedRatioBase": ("break_effect", True, "击破特攻"),
    "SPRatioBase": ("err", True, "能量恢复效率"),
    "HealRatioBase": ("outgoing_healing", True, "治疗量加成"),
    "HealTakenRatio": ("heal_taken", True, "受治疗量加成"),
    "AllDamageTypeAddedRatio": ("dmg_boost", True, "全属性增伤"),
    "PhysicalAddedRatio": ("physical_dmg", True, "物理伤害提高"),
    "FireAddedRatio": ("fire_dmg", True, "火属性伤害提高"),
    "IceAddedRatio": ("ice_dmg", True, "冰属性伤害提高"),
    "ThunderAddedRatio": ("lightning_dmg", True, "雷属性伤害提高"),
    "WindAddedRatio": ("wind_dmg", True, "风属性伤害提高"),
    "QuantumAddedRatio": ("quantum_dmg", True, "量子伤害提高"),
    "ImaginaryAddedRatio": ("imaginary_dmg", True, "虚数伤害提高"),
    "ElationDamageAddedRatioBase": ("elation_dmg", True, "欢愉伤害提高"),
}

_OFFICIAL_ELEMENT_MAP: Dict[str, str] = {
    "Physical": "Physical",
    "Fire": "Fire",
    "Ice": "Ice",
    "Thunder": "Lightning",
    "Wind": "Wind",
    "Quantum": "Quantum",
    "Imaginary": "Imaginary",
}

_OFFICIAL_PATH_MAP: Dict[str, str] = {
    "Warrior": "Destruction",
    "Rogue": "Hunt",
    "Mage": "Erudition",
    "Shaman": "Harmony",
    "Warlock": "Nihility",
    "Knight": "Preservation",
    "Priest": "Abundance",
    "Memory": "Remembrance",
    "Elation": "Elation",
}


def _load_excel(filename: str) -> List[Dict[str, Any]]:
    path = os.path.join(_EXCEL_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _num_val(v: Any) -> float:
    if isinstance(v, dict):
        return float(v.get("Value", 0.0) or 0.0)
    return float(v or 0.0)


def _extract_prop_pair(entry: Dict[str, Any]) -> Tuple[Optional[str], float]:
    """兼容官方 PropertyList 的混淆键名，提取 (PropertyType, Value)。"""
    if "PropertyType" in entry:
        return str(entry["PropertyType"]), _num_val(entry.get("Value"))
    prop_type: Optional[str] = None
    val = 0.0
    for v in entry.values():
        if isinstance(v, str) and v in _PROP_META:
            prop_type = v
        elif isinstance(v, dict) and "Value" in v:
            val = float(v["Value"])
    return prop_type, val


# =====================================================================
# 底层官方原始索引表（按任意等级/突破/叠影精确查询）
# =====================================================================
_AVATAR_CONFIG: Dict[int, Dict[str, Any]] = {}
_AVATAR_PROMO: Dict[Tuple[int, int], Dict[str, Any]] = {}
_AVATAR_TRACES: Dict[int, Dict[str, float]] = {}

_EQUIP_CONFIG: Dict[int, Dict[str, Any]] = {}
_EQUIP_PROMO: Dict[Tuple[int, int], Dict[str, Any]] = {}
_EQUIP_SKILL_PROPS: Dict[Tuple[int, int], Dict[str, float]] = {}

_RELIC_MAIN_RAW: Dict[Tuple[int, int], Dict[str, Any]] = {}
_RELIC_SUB_RAW: Dict[Tuple[int, int], Dict[str, Any]] = {}
_RELIC_SET_RAW: Dict[int, Dict[str, Any]] = {}

# 向后兼容的标准 80 级 / +15 视图字典
AVATAR_STATS: Dict[int, Dict[str, Any]] = {}
LIGHTCONE_STATS: Dict[int, Dict[str, Any]] = {}
RELIC_MAIN_VALUES: Dict[int, Dict[int, Dict[str, Any]]] = {s: {} for s in range(1, 7)}
RELIC_SUB_RULES: Dict[int, Dict[str, Any]] = {}
RELIC_SETS: Dict[int, Dict[str, Any]] = {}

DEFAULT_5STAR_STATS: Dict[str, Any] = {
    "name": "未知5星角色",
    "element": "Physical",
    "path": "Destruction",
    "base_hp": 1200.0,
    "base_atk": 640.0,
    "base_def": 460.0,
    "base_spd": 100.0,
    "traces": {},
}
DEFAULT_4STAR_STATS: Dict[str, Any] = {
    "name": "未知4星角色",
    "element": "Physical",
    "path": "Destruction",
    "base_hp": 1000.0,
    "base_atk": 540.0,
    "base_def": 400.0,
    "base_spd": 100.0,
    "traces": {},
}
DEFAULT_5STAR_LC: Dict[str, Any] = {
    "name": "未知5星光锥",
    "path": None,
    "base_hp": 1058.4,
    "base_atk": 529.2,
    "base_def": 396.9,
    "passive_stats": {},
}
DEFAULT_4STAR_LC: Dict[str, Any] = {
    "name": "未知4星光锥",
    "path": None,
    "base_hp": 952.56,
    "base_atk": 476.28,
    "base_def": 330.75,
    "passive_stats": {},
}


def _init_official_tables() -> None:
    # 1. 角色配置 + 突破成长 + 小行迹属性节点 (PointType == 1)
    for row in _load_excel("AvatarConfig.json"):
        aid = int(row.get("AvatarID") or 0)
        if aid:
            _AVATAR_CONFIG[aid] = row

    for row in _load_excel("AvatarPromotionConfig.json"):
        aid = int(row.get("AvatarID") or 0)
        promo = int(row.get("Promotion") or 0)
        if aid:
            _AVATAR_PROMO[(aid, promo)] = row

    for row in _load_excel("AvatarSkillTreeConfig.json"):
        if int(row.get("PointType") or 0) != 1 or int(row.get("EnhancedID") or 0) != 0:
            continue
        aid = int(row.get("AvatarID") or 0)
        if not aid:
            continue
        tb = _AVATAR_TRACES.setdefault(aid, {})
        for s in row.get("StatusAddList", ()):
            p_type, val = _extract_prop_pair(s)
            if p_type in _PROP_META and val:
                key = _PROP_META[p_type][0]
                tb[key] = tb.get(key, 0.0) + val

    for aid, cfg in _AVATAR_CONFIG.items():
        stats = get_avatar_base_stats(aid, level=80, promotion=6)
        if stats is not None:
            AVATAR_STATS[aid] = stats

    # 2. 光锥配置 + 突破成长 + 1~5 叠影常驻属性
    for row in _load_excel("EquipmentConfig.json"):
        eid = int(row.get("EquipmentID") or 0)
        if eid:
            _EQUIP_CONFIG[eid] = row

    for row in _load_excel("EquipmentPromotionConfig.json"):
        eid = int(row.get("EquipmentID") or 0)
        promo = int(row.get("Promotion") or 0)
        if eid:
            _EQUIP_PROMO[(eid, promo)] = row

    for row in _load_excel("EquipmentSkillConfig.json"):
        sid = int(row.get("SkillID") or 0)
        lv = int(row.get("Level") or 1)
        if not sid:
            continue
        props: Dict[str, float] = {}
        for s in row.get("AbilityProperty", ()):
            p_type, val = _extract_prop_pair(s)
            if p_type in _PROP_META and val:
                key = _PROP_META[p_type][0]
                props[key] = props.get(key, 0.0) + val
        _EQUIP_SKILL_PROPS[(sid, lv)] = props

    for eid in _EQUIP_CONFIG:
        lc = get_lightcone_stats(eid, level=80, promotion=6, rank=1)
        if lc is not None:
            LIGHTCONE_STATS[eid] = lc

    # 3. 遗器主词条 + 副词条 + 套装 2/4 件套常驻属性
    for row in _load_excel("RelicMainAffixConfig.json"):
        gid = int(row.get("GroupID") or 0)
        aid = int(row.get("AffixID") or 0)
        if gid and aid:
            _RELIC_MAIN_RAW[(gid, aid)] = row
            if 51 <= gid <= 56:
                slot = gid - 50
                p_type = str(row.get("Property") or "")
                key, is_pct, cn_name = _PROP_META.get(p_type, ("unknown", False, p_type))
                val = _num_val(row.get("BaseValue")) + _num_val(row.get("LevelAdd")) * 15
                RELIC_MAIN_VALUES[slot][aid] = {
                    "name": cn_name,
                    "key": key,
                    "val": val,
                    "is_pct": is_pct,
                }

    for row in _load_excel("RelicSubAffixConfig.json"):
        gid = int(row.get("GroupID") or 0)
        aid = int(row.get("AffixID") or 0)
        if gid and aid:
            _RELIC_SUB_RAW[(gid, aid)] = row
            if gid == 5:
                p_type = str(row.get("Property") or "")
                key, is_pct, cn_name = _PROP_META.get(p_type, ("unknown", False, p_type))
                RELIC_SUB_RULES[aid] = {
                    "name": cn_name,
                    "key": key,
                    "base": _num_val(row.get("BaseValue")),
                    "step_val": _num_val(row.get("StepValue")),
                    "is_pct": is_pct,
                }

    for row in _load_excel("RelicSetConfig.json"):
        sid = int(row.get("SetID") or 0)
        if sid:
            _RELIC_SET_RAW[sid] = {"name": f"套装{sid}", "2pc": {}, "4pc": {}}

    for row in _load_excel("RelicSetSkillConfig.json"):
        sid = int(row.get("SetID") or 0)
        req = int(row.get("RequireNum") or 0)
        if not sid or req not in (2, 4):
            continue
        entry = _RELIC_SET_RAW.setdefault(sid, {"name": f"套装{sid}", "2pc": {}, "4pc": {}})
        bucket = entry["2pc"] if req == 2 else entry["4pc"]
        for item in row.get("PropertyList", ()):
            p_type, val = _extract_prop_pair(item)
            if p_type in _PROP_META and val:
                key = _PROP_META[p_type][0]
                bucket[key] = bucket.get(key, 0.0) + val

    RELIC_SETS.update(_RELIC_SET_RAW)


def get_avatar_base_stats(
    avatar_id: int, *, level: int = 80, promotion: int = 6
) -> Optional[Dict[str, Any]]:
    """按官方 AvatarPromotionConfig 公式计算角色任意等级与突破的精确白值与小行迹。"""
    cfg = _AVATAR_CONFIG.get(avatar_id)
    promo = _AVATAR_PROMO.get((avatar_id, promotion))
    if promo is None:
        # 若请求突破档不存在，回退到该角色最高突破档
        avail = [p for (a, p) in _AVATAR_PROMO if a == avatar_id]
        if not avail:
            return None
        promo = _AVATAR_PROMO[(avatar_id, max(avail))]

    lv = max(1, int(level))
    base_hp = _num_val(promo.get("HPBase")) + _num_val(promo.get("HPAdd")) * (lv - 1)
    base_atk = _num_val(promo.get("AttackBase")) + _num_val(promo.get("AttackAdd")) * (lv - 1)
    base_def = _num_val(promo.get("DefenceBase")) + _num_val(promo.get("DefenceAdd")) * (lv - 1)
    base_spd = _num_val(promo.get("SpeedBase"))

    elem = _OFFICIAL_ELEMENT_MAP.get(str((cfg or {}).get("DamageType") or ""), "Physical")
    path = _OFFICIAL_PATH_MAP.get(str((cfg or {}).get("AvatarBaseType") or ""), "Destruction")
    max_energy = _num_val((cfg or {}).get("SPNeed")) or 120.0

    return {
        "name": f"角色{avatar_id}",
        "element": elem,
        "path": path,
        "base_hp": base_hp,
        "base_atk": base_atk,
        "base_def": base_def,
        "base_spd": base_spd,
        "max_energy": max_energy,
        "traces": dict(_AVATAR_TRACES.get(avatar_id, {})),
    }


def get_lightcone_stats(
    item_id: int, *, level: int = 80, promotion: int = 6, rank: int = 1
) -> Optional[Dict[str, Any]]:
    """按官方 EquipmentPromotionConfig + EquipmentSkillConfig 计算光锥任意等级/叠影精确白值与常驻属性。"""
    cfg = _EQUIP_CONFIG.get(item_id)
    promo = _EQUIP_PROMO.get((item_id, promotion))
    if promo is None:
        avail = [p for (e, p) in _EQUIP_PROMO if e == item_id]
        if not avail:
            return None
        promo = _EQUIP_PROMO[(item_id, max(avail))]

    lv = max(1, int(level))
    base_hp = _num_val(promo.get("BaseHP")) + _num_val(promo.get("BaseHPAdd")) * (lv - 1)
    base_atk = _num_val(promo.get("BaseAttack")) + _num_val(promo.get("BaseAttackAdd")) * (lv - 1)
    base_def = _num_val(promo.get("BaseDefence")) + _num_val(promo.get("BaseDefenceAdd")) * (lv - 1)

    skill_id = int((cfg or {}).get("SkillID") or item_id)
    sup = max(1, min(5, int(rank)))
    passive = dict(_EQUIP_SKILL_PROPS.get((skill_id, sup), {}))
    path = _OFFICIAL_PATH_MAP.get(str((cfg or {}).get("AvatarBaseType") or ""))

    return {
        "name": f"光锥{item_id}",
        "path": path,
        "base_hp": base_hp,
        "base_atk": base_atk,
        "base_def": base_def,
        "passive_stats": passive,
    }


def get_relic_main_value(
    slot: int, affix_id: int, *, level: int = 15, rarity: int = 5
) -> Dict[str, Any]:
    """按官方 RelicMainAffixConfig 计算任意星级与强化等级的遗器主词条精确值。"""
    gid = rarity * 10 + slot
    row = _RELIC_MAIN_RAW.get((gid, affix_id)) or _RELIC_MAIN_RAW.get((50 + slot, affix_id))
    if row is None:
        return {"name": f"词条{affix_id}", "key": "unknown", "val": 0.0, "is_pct": False}
    p_type = str(row.get("Property") or "")
    key, is_pct, cn_name = _PROP_META.get(p_type, ("unknown", False, p_type))
    val = _num_val(row.get("BaseValue")) + _num_val(row.get("LevelAdd")) * max(0, int(level))
    return {"name": cn_name, "key": key, "val": val, "is_pct": is_pct}


def get_relic_sub_rule(affix_id: int, *, rarity: int = 5) -> Optional[Dict[str, Any]]:
    """按官方 RelicSubAffixConfig 获取任意星级的遗器副词条档位规则。"""
    row = _RELIC_SUB_RAW.get((rarity, affix_id)) or _RELIC_SUB_RAW.get((5, affix_id))
    if row is None:
        return None
    p_type = str(row.get("Property") or "")
    key, is_pct, cn_name = _PROP_META.get(p_type, ("unknown", False, p_type))
    return {
        "name": cn_name,
        "key": key,
        "base": _num_val(row.get("BaseValue")),
        "step_val": _num_val(row.get("StepValue")),
        "is_pct": is_pct,
    }


_init_official_tables()

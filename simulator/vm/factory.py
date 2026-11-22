# coding: utf-8
"""官方 ConfigAbility VM 队伍与实体构建工厂。

纯数据驱动：直接从 `CharacterDB` 角色档案动态推导 `(avatar_id, eidolon, light_cone, relic_sets)`
并挂载官方 VM 适配器 (`ConfigAbilityKitAdapter` / `LightCone` / `Relic`)，零配队/角色名硬编码。
"""
from __future__ import annotations

import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from simulator.db.character_db import CharacterDB
from simulator.entity import Entity
from simulator.vm.loader import GameDataLoader
from simulator.vm.runtime import (
    ConfigAbilityKitAdapter,
    ConfigAbilityLightConeAdapter,
    ConfigAbilityRelicAdapter,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CHAR_DB_PATH = os.path.join(ROOT_DIR, "data", "character_db_export.json")


def resolve_vm_uid(
    uid_or_name: Union[int, str],
    *,
    db: Optional[CharacterDB] = None,
) -> int:
    """将角色 UID 或名称解析为标准 avatar_id（支持 CharacterDB 内任意角色及变体档案）。"""
    if isinstance(uid_or_name, int):
        return uid_or_name
    text = str(uid_or_name).strip()
    if text.isdigit():
        return int(text)
    char_db = db if db is not None else CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    rp = char_db.get_by_name(text)
    if rp is None and "_" in text:
        rp = char_db.get_by_name(text.split("_", 1)[0])
    if rp is not None:
        return int(rp.avatar_id)
    raise KeyError(f"未知 VM 角色标识: {uid_or_name!r}")


def _infer_loadout_from_profile(rp: object) -> Tuple[int, int, Optional[int], int, List[Tuple[int, int]]]:
    """从 CharacterDB 档案动态推导 (avatar_id, eidolon, lc_id, lc_s, relic_sets)。"""
    aid = int(getattr(rp, "avatar_id"))
    eid = int(getattr(rp, "eidolon", 0))
    lc = getattr(rp, "light_cone", None)
    lc_id = int(lc.item_id) if lc is not None and getattr(lc, "item_id", 0) else None
    lc_s = int(getattr(lc, "superimposition", 1)) if lc is not None else 1
    counts: Dict[int, int] = {}
    for rel in getattr(rp, "relics", []) or []:
        sid = int(getattr(rel, "relic_set_id", 0))
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    relic_sets: List[Tuple[int, int]] = []
    for sid, cnt in sorted(counts.items()):
        if cnt >= 4:
            relic_sets.append((sid, 4))
        elif cnt >= 2:
            relic_sets.append((sid, 2))
    return aid, eid, lc_id, lc_s, relic_sets


def build_vm_entity(
    uid_or_name: Union[int, str],
    *,
    db: Optional[CharacterDB] = None,
    loader: Optional[GameDataLoader] = None,
    loadout: Optional[Tuple[int, int, Optional[int], int, List[Tuple[int, int]]]] = None,
    db_path: str = DEFAULT_CHAR_DB_PATH,
) -> Entity:
    """构建单个挂载官方 VM 适配器 (`Kit`/`LightCone`/`Relic`) 的战斗实体。"""
    char_db = db if db is not None else CharacterDB().load(db_path)
    vm_loader = loader if loader is not None else GameDataLoader()
    uid = resolve_vm_uid(uid_or_name, db=char_db)

    raw_key = str(uid_or_name).strip() if isinstance(uid_or_name, str) else ""
    if raw_key and not raw_key.isdigit():
        rp = char_db.get_by_name(raw_key) or char_db.get(uid)
    else:
        rp = char_db.get(uid)
    if rp is None:
        raise KeyError(f"CharacterDB 中未找到角色档案: {uid_or_name!r} (uid={uid})")

    canonical = char_db.get(uid)
    name = canonical.name if canonical is not None else rp.name.split("_", 1)[0]
    ent = char_db.to_combat_entity(rp)
    ent.name = name

    if loadout is not None:
        aid, eid, lc_id, lc_s, relics = loadout
    else:
        aid, eid, lc_id, lc_s, relics = _infer_loadout_from_profile(rp)

    ent.kit = ConfigAbilityKitAdapter(name, aid, eidolon=eid, loader=vm_loader)
    if lc_id is not None:
        ent.light_cone = ConfigAbilityLightConeAdapter(name, lc_id, superimposition=lc_s)
    ent.relic_handlers = [ConfigAbilityRelicAdapter(name, sid, pieces=pc) for sid, pc in relics]
    return ent


def build_vm_team(
    uids_or_names: Sequence[Union[int, str]],
    *,
    db: Optional[CharacterDB] = None,
    loader: Optional[GameDataLoader] = None,
    loadouts: Optional[Mapping[int, Tuple[int, int, Optional[int], int, List[Tuple[int, int]]]]] = None,
    db_path: str = DEFAULT_CHAR_DB_PATH,
) -> List[Entity]:
    """按传入顺序构建整支 VM 队伍，严格保留站位顺序。"""
    char_db = db if db is not None else CharacterDB().load(db_path)
    vm_loader = loader if loader is not None else GameDataLoader()
    team: List[Entity] = []
    for item in uids_or_names:
        uid = resolve_vm_uid(item, db=char_db)
        ov = loadouts.get(uid) if loadouts is not None else None
        team.append(build_vm_entity(item, db=char_db, loader=vm_loader, loadout=ov, db_path=db_path))
    return team

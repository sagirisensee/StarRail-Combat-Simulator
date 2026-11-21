# coding: utf-8
"""官方 ConfigAbility VM 队伍与实体构建工厂。

从 `vm_reconciliation.py` 抽离标准配队表 (`TEAM_VM_LOADOUT`) 与面板去重逻辑
（扣除 `character_db_export.json` 中已预烘焙、但官方 VM 进场/局内会主动添加的被动属性），
供 `VMReconciliationHarness` 与完整关卡对账 (`build_stage_30126122` + `run_trajectory_replay`) 共用。
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

UID_TO_NAME: Dict[int, str] = {
    1403: "缇宝",
    1409: "风堇",
    1413: "长夜月",
    1512: "知更鸟•晴歌",
}

NAME_TO_UID: Dict[str, int] = {
    "缇宝": 1403,
    "风堇": 1409,
    "长夜月": 1413,
    "知更鸟•晴歌": 1512,
    "知更鸟•晴歌_爱如此刻永恒": 1512,
}

# 本队官方配置表: uid -> (avatar_id, eidolon, lc_id, lc_superimposition, relics)
TEAM_VM_LOADOUT: Dict[int, Tuple[int, int, int, int, List[Tuple[int, int]]]] = {
    1403: (1403, 6, 23038, 5, [(124, 4), (319, 2)]),
    1409: (1409, 1, 23042, 1, [(125, 4), (320, 2)]),
    1413: (1413, 2, 23040, 1, [(127, 4), (319, 2)]),
    1512: (1512, 0, 23052, 1, [(127, 4), (323, 2)]),
}


def resolve_vm_uid(
    uid_or_name: Union[int, str],
    *,
    db: Optional[CharacterDB] = None,
) -> int:
    """将角色 UID 或名称解析为标准 avatar_id（支持 CharacterDB 内任意角色）。"""
    if isinstance(uid_or_name, int):
        return uid_or_name
    text = str(uid_or_name).strip()
    if text.isdigit():
        return int(text)
    if text in NAME_TO_UID:
        return NAME_TO_UID[text]
    if db is not None:
        rp = db.get_by_name(text)
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
    loadout: Optional[Tuple[int, int, int, int, List[Tuple[int, int]]]] = None,
    db_path: str = DEFAULT_CHAR_DB_PATH,
) -> Entity:
    """构建单个挂载官方 VM 适配器 (`Kit`/`LightCone`/`Relic`) 的战斗实体。"""
    char_db = db if db is not None else CharacterDB().load(db_path)
    vm_loader = loader if loader is not None else GameDataLoader()
    uid = resolve_vm_uid(uid_or_name, db=char_db)
    known_name = UID_TO_NAME.get(uid)

    if known_name == "知更鸟•晴歌":
        rp = char_db.get_by_name("知更鸟•晴歌_爱如此刻永恒") or char_db.get_by_name(known_name)
        if rp is not None:
            rp.name = "知更鸟•晴歌"
    elif known_name is not None:
        rp = char_db.get_by_name(known_name)
    else:
        rp = char_db.get(uid) or (
            char_db.get_by_name(str(uid_or_name).strip()) if isinstance(uid_or_name, str) else None
        )
    if rp is None:
        raise KeyError(f"CharacterDB 中未找到角色档案: {uid_or_name!r} (uid={uid})")

    name = known_name or rp.name
    ent = char_db.to_combat_entity(rp)
    ent.name = name

    if loadout is not None:
        aid, eid, lc_id, lc_s, relics = loadout
    elif uid in TEAM_VM_LOADOUT:
        aid, eid, lc_id, lc_s, relics = TEAM_VM_LOADOUT[uid]
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
    loadouts: Optional[Mapping[int, Tuple[int, int, int, int, List[Tuple[int, int]]]]] = None,
    db_path: str = DEFAULT_CHAR_DB_PATH,
) -> List[Entity]:
    """按传入顺序构建整支 VM 队伍，严格保留站位顺序。"""
    char_db = db if db is not None else CharacterDB().load(db_path)
    vm_loader = loader if loader is not None else GameDataLoader()
    team: List[Entity] = []
    for item in uids_or_names:
        uid = resolve_vm_uid(item, db=char_db)
        ov = loadouts.get(uid) if loadouts is not None else None
        team.append(build_vm_entity(uid, db=char_db, loader=vm_loader, loadout=ov, db_path=db_path))
    return team

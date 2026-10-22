"""
官方资产仓库 (Asset Repository).
提供针对 Nanoka 4.6 归一化资产的只读检索与实体转换。
"""

import json
from pathlib import Path
from typing import Optional, Dict

from .models import (
    RelicBonusSpec,
    RelicSetAsset,
    LightConeAsset,
    CharacterSkillAsset,
    EidolonAsset,
    EidolonSkillBonus,
    CharacterAsset,
)

DEFAULT_VERSION = "4.6"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class AssetRepository:
    """Nanoka 4.6 资产内存仓库。"""

    _instance: Optional["AssetRepository"] = None

    def __init__(self, version: str = DEFAULT_VERSION):
        self.version = version
        self.base_dir = ROOT_DIR / "data" / "nanoka" / "normalized" / version

        self._relic_sets_by_id: Dict[str, RelicSetAsset] = {}
        self._relic_sets_by_name: Dict[str, RelicSetAsset] = {}

        self._light_cones_by_id: Dict[str, LightConeAsset] = {}
        self._light_cones_by_name: Dict[str, LightConeAsset] = {}

        self._characters_by_id: Dict[str, CharacterAsset] = {}
        self._characters_by_name: Dict[str, CharacterAsset] = {}

        self._load_all()

    @classmethod
    def get_instance(cls) -> "AssetRepository":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_all(self) -> None:
        self._load_relics()
        self._load_light_cones()
        self._load_characters()

    def _load_relics(self) -> None:
        relics_path = self.base_dir / "relic_sets.json"
        if not relics_path.exists():
            return
        with open(relics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for rid, raw in data.items():
            bonuses = tuple(
                RelicBonusSpec(
                    required_pieces=b["required_pieces"],
                    params=tuple(b.get("params", [])),
                    desc=b.get("desc", ""),
                )
                for b in raw.get("bonuses", [])
            )
            asset = RelicSetAsset(id=str(rid), name=raw.get("name", ""), bonuses=bonuses)
            self._relic_sets_by_id[str(rid)] = asset
            self._relic_sets_by_name[asset.name] = asset

    def _load_light_cones(self) -> None:
        lc_path = self.base_dir / "lightcones.json"
        if not lc_path.exists():
            return
        with open(lc_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for lcid, raw in data.items():
            refs_raw = raw.get("refinements", {})
            refs = {
                int(lvl): tuple(refs_raw[lvl].get("params", []))
                for lvl in refs_raw
            }
            asset = LightConeAsset(
                id=str(lcid),
                name=raw.get("name", ""),
                path=raw.get("path", ""),
                rarity=raw.get("rarity", 4),
                skill_name=raw.get("skill_name", ""),
                skill_desc=raw.get("skill_desc", ""),
                refinements=refs,
            )
            self._light_cones_by_id[str(lcid)] = asset
            self._light_cones_by_name[asset.name] = asset

    def _load_characters(self) -> None:
        char_path = self.base_dir / "characters.json"
        if not char_path.exists():
            return
        with open(char_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for cid, raw in data.items():
            skills = {}
            for sid, sraw in raw.get("skills", {}).items():
                pbl = {
                    int(lvl): tuple(sraw.get("params_by_level", {}).get(lvl, []))
                    for lvl in sraw.get("params_by_level", {})
                }
                skills[str(sid)] = CharacterSkillAsset(
                    id=str(sid),
                    name=sraw.get("name", ""),
                    type=sraw.get("type", ""),
                    type_name=sraw.get("type_name", ""),
                    tag=sraw.get("tag", ""),
                    sp_base=sraw.get("sp_base"),
                    bp_need=sraw.get("bp_need"),
                    bp_add=sraw.get("bp_add"),
                    desc=sraw.get("desc", ""),
                    params_by_level=pbl,
                )

            eidolons = {}
            for rk, rraw in raw.get("eidolons", {}).items():
                eidolons[int(rk)] = EidolonAsset(
                    rank=int(rk),
                    name=rraw.get("name", ""),
                    desc=rraw.get("desc", ""),
                    params=tuple(rraw.get("params", [])),
                )

            bonuses = tuple(
                EidolonSkillBonus(
                    eidolon=b["eidolon"],
                    skill_type=b["skill_type"],
                    skill_type_cn=b["skill_type_cn"],
                    delta=b["delta"],
                    max_level=b["max_level"],
                )
                for b in raw.get("eidolon_skill_bonuses", [])
            )

            asset = CharacterAsset(
                id=str(cid),
                name=raw.get("name", ""),
                damage_type=raw.get("damage_type", ""),
                path=raw.get("path", ""),
                rarity=raw.get("rarity", 4),
                skills=skills,
                eidolons=eidolons,
                eidolon_skill_bonuses=bonuses,
            )
            self._characters_by_id[str(cid)] = asset
            self._characters_by_name[asset.name] = asset

    def get_relic_set(self, id_or_name: str) -> Optional[RelicSetAsset]:
        return self._relic_sets_by_id.get(str(id_or_name)) or self._relic_sets_by_name.get(str(id_or_name))

    def get_light_cone(self, id_or_name: str) -> Optional[LightConeAsset]:
        return self._light_cones_by_id.get(str(id_or_name)) or self._light_cones_by_name.get(str(id_or_name))

    def get_character(self, id_or_name: str) -> Optional[CharacterAsset]:
        return self._characters_by_id.get(str(id_or_name)) or self._characters_by_name.get(str(id_or_name))

    def all_relic_sets(self) -> tuple[RelicSetAsset, ...]:
        return tuple(self._relic_sets_by_id.values())

    def all_light_cones(self) -> tuple[LightConeAsset, ...]:
        return tuple(self._light_cones_by_id.values())

    def all_characters(self) -> tuple[CharacterAsset, ...]:
        return tuple(self._characters_by_id.values())

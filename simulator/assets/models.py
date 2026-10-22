"""
数据资产领域模型 (Asset Models).
遵循 Nanoka 官方 4.6 规约模型，严格只读无副作用。
"""

from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass(frozen=True)
class RelicBonusSpec:
    required_pieces: int
    params: tuple[float, ...]
    desc: str


@dataclass(frozen=True)
class RelicSetAsset:
    id: str
    name: str
    bonuses: tuple[RelicBonusSpec, ...]


@dataclass(frozen=True)
class LightConeAsset:
    id: str
    name: str
    path: str
    rarity: int
    skill_name: str
    skill_desc: str
    refinements: Mapping[int, tuple[float, ...]]  # 1..5 -> tuple of floats


@dataclass(frozen=True)
class CharacterSkillAsset:
    id: str
    name: str
    type: str  # Normal, BPSkill, Ultra, Talent, Maze, etc.
    type_name: str
    tag: str
    sp_base: Optional[int]
    bp_need: Optional[int]
    bp_add: Optional[int]
    desc: str
    params_by_level: Mapping[int, tuple[float, ...]]  # level -> tuple of floats


@dataclass(frozen=True)
class EidolonAsset:
    rank: int
    name: str
    desc: str
    params: tuple[float, ...]


@dataclass(frozen=True)
class EidolonSkillBonus:
    eidolon: int
    skill_type: str
    skill_type_cn: str
    delta: int
    max_level: int


@dataclass(frozen=True)
class CharacterAsset:
    id: str
    name: str
    damage_type: str
    path: str
    rarity: int
    skills: Mapping[str, CharacterSkillAsset]  # skill_id -> skill
    eidolons: Mapping[int, EidolonAsset]  # rank 1..6 -> eidolon
    eidolon_skill_bonuses: tuple[EidolonSkillBonus, ...]

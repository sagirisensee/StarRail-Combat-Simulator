"""
技能缩放模型 (Skill Scaling Models).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SkillBinding:
    semantic_key: str  # "basic", "skill", "ultra", "talent", "technique"
    skill_id: str
    skill_type: str
    skill_name: str
    default_trained_level: int

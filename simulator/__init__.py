"""Honkai: Star Rail Turn-based Combat Simulator & Character Database Engine.

Modules:
- core: TurnSimulator, Entity, Action scheduler
- damage: DamageCalculator, DamageRequest, DamageBreakdown
- effects: Effect system, AdvanceActionEffect, ApplyStatusEffect
- events: EventBus, battle event definitions
- sp: SkillPointManager
- status: StatusManager, Buff/Debuff system
- db: CharacterDB, StatCalculator, models
"""
from .core import Entity, TurnSimulator
from .damage import DamageCalculator, DamageRequest, DamageBreakdown
from .effects import AdvanceActionEffect, ApplyStatusEffect, ApplyDamageEffect
from .events import EventBus, BattleEvent
from .sp import SkillPointManager
from .status import StatusManager, StatusInstance, StatType, Modifier, ModifierOp, DurationTiming
from .db import CharacterDB, CharacterProfile, CharacterPanel, StatCalculator

__all__ = [
    "Entity",
    "TurnSimulator",
    "DamageCalculator",
    "DamageRequest",
    "DamageBreakdown",
    "AdvanceActionEffect",
    "ApplyStatusEffect",
    "ApplyDamageEffect",
    "EventBus",
    "BattleEvent",
    "SkillPointManager",
    "StatusManager",
    "StatusInstance",
    "StatType",
    "Modifier",
    "ModifierOp",
    "CharacterDB",
    "CharacterProfile",
    "CharacterPanel",
    "StatCalculator",
]

"""Honkai: Star Rail Turn-based Combat Simulator & Character Database Engine.

Core Architecture Exports:
- Engine & Entities: TurnSimulator, Entity, BattleInspector
- Port & Contracts: CombatPort, SimulatorCombatPort, BuffSpec, ActionKind, ActionContext, AbilityDefinition, TargetMode, ResourceCost
- Plugin Bases & Decorators:
  * KitHandler, register_kit, get_kit_class
  * LightConeHandler, LightConeRegistry, register_light_cone
  * RelicSetHandler, RelicRegistry, register_relic_set
  * StageMechanicPlugin, StageMechanicRegistry, register_stage_mechanic
- Status & Events: StatusManager, StatusInstance, StatType, Modifier, ModifierOp, DurationTiming, StatusTag, EventBus, BattleEvent
- Damage & DB: DamageCalculator, DamageRequest, DamageBreakdown, CharacterDB, CharacterProfile, CharacterPanel, StatCalculator
"""
from .entity import Entity
from .core import TurnSimulator
from .inspector import BattleInspector
from .combat_port import CombatPort, SimulatorCombatPort, BuffSpec
from .actions import ActionKind, ActionContext, AbilityDefinition, TargetMode, ResourceCost
from .damage import DamageCalculator, DamageRequest, DamageBreakdown
from .effects import AdvanceActionEffect, ApplyStatusEffect, ApplyDamageEffect
from .events import (
    EventBus, BattleEvent, TurnBeginEvent, TurnEndEvent, ActionExecuteEvent,
    DamageAppliedEvent, HealAppliedEvent, ShieldAppliedEvent, HPLostEvent,
    SpiritSummonedEvent, SpiritDespawnEvent
)
from .sp import SkillPointManager
from .status import StatusManager, StatusInstance, StatType, Modifier, ModifierOp, DurationTiming, StatusTag
from .stage_mechanics import StageMechanicPlugin, StageMechanicRegistry, register_stage_mechanic
from .kits import KitHandler, register_kit, get_kit_class
from .light_cones import LightConeHandler, LightConeRegistry, register_light_cone
from .relics import RelicSetHandler, RelicRegistry, register_relic_set
from .db import CharacterDB, CharacterProfile, CharacterPanel, StatCalculator

__all__ = [
    "Entity",
    "TurnSimulator",
    "BattleInspector",
    "CombatPort",
    "SimulatorCombatPort",
    "BuffSpec",
    "ActionKind",
    "ActionContext",
    "AbilityDefinition",
    "TargetMode",
    "ResourceCost",
    "DamageCalculator",
    "DamageRequest",
    "DamageBreakdown",
    "AdvanceActionEffect",
    "ApplyStatusEffect",
    "ApplyDamageEffect",
    "EventBus",
    "BattleEvent",
    "TurnBeginEvent",
    "TurnEndEvent",
    "ActionExecuteEvent",
    "DamageAppliedEvent",
    "HealAppliedEvent",
    "ShieldAppliedEvent",
    "HPLostEvent",
    "SpiritSummonedEvent",
    "SpiritDespawnEvent",
    "SkillPointManager",
    "StatusManager",
    "StatusInstance",
    "StatType",
    "Modifier",
    "ModifierOp",
    "DurationTiming",
    "StatusTag",
    "StageMechanicPlugin",
    "StageMechanicRegistry",
    "register_stage_mechanic",
    "KitHandler",
    "register_kit",
    "get_kit_class",
    "LightConeHandler",
    "LightConeRegistry",
    "register_light_cone",
    "RelicSetHandler",
    "RelicRegistry",
    "register_relic_set",
    "CharacterDB",
    "CharacterProfile",
    "CharacterPanel",
    "StatCalculator",
]

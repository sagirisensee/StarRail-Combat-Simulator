"""星穹铁道战斗动作抽象与请求模型 (Action Definitions & Context)."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple


class ActionKind(Enum):
    BASIC = auto()          # 普通攻击
    SKILL = auto()          # 战技
    ULTIMATE = auto()       # 终结技 (插队执行)
    TECHNIQUE = auto()      # 秘技 (开战前触发)
    TALENT = auto()         # 天赋/被动触发


class TargetMode(Enum):
    SELF = auto()           # 自身
    SINGLE_ALLY = auto()    # 我方单体
    ALL_ALLIES = auto()     # 我方全体
    SINGLE_ENEMY = auto()   # 敌方单体
    ALL_ENEMIES = auto()    # 敌方全体
    BLAST = auto()          # 扩散 (主目标 + 相邻目标)


@dataclass(frozen=True)
class ResourceCost:
    sp: int = 0                         # 战技点消耗 (正为耗点, 负为回点)
    energy: float = 0.0                 # 终结技能量消耗
    technique_points: int = 0           # 秘技点消耗


@dataclass(frozen=True)
class AbilityDefinition:
    kind: ActionKind
    target_mode: TargetMode
    cost: ResourceCost = ResourceCost()
    allow_self: bool = True
    name: str = ""
    priority: int = 1                   # 秘技/动作准备执行优先级 (值越小越先结算，如全队增益=0, 默认=1, 领域展开=2)


@dataclass(frozen=True)
class ActionRequest:
    actor_id: str
    kind: ActionKind
    primary_target_id: Optional[str] = None


@dataclass(frozen=True)
class ActionContext:
    action_id: str
    actor_id: str
    kind: ActionKind
    target_ids: Tuple[str, ...]         # 目标 ID 元组 (已校验)
    is_natural_turn_action: bool = True # 是否为常规自然回合动作 (终结技插队为 False)

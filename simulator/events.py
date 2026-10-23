"""星穹铁道战斗事件系统 (Battle Event System)。

架构原则：
1. 事件是不可变的战斗事实记录 (Immutable Facts)；
2. 任何状态变更 (血量、SP、拉条、伤害、韧性削减、弱点击破) 都产生对应的标准事件；
3. 支持事件总线 (EventBus) 订阅与广播。
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Type, Any


@dataclass(frozen=True)
class BattleEvent:
    av: float                   # 事件发生时的全局行动值
    cycle: int                  # 所在轮次


@dataclass(frozen=True)
class TurnBeginEvent(BattleEvent):
    actor_id: str
    actor_name: str
    speed: float


@dataclass(frozen=True)
class TurnEndEvent(BattleEvent):
    actor_id: str
    actor_name: str


@dataclass(frozen=True)
class ActionExecuteEvent(BattleEvent):
    actor_id: str
    actor_name: str
    action_type: str            # "BasicAttack", "Skill", "Ultimate", "FollowUp", "Technique"
    description: str


@dataclass(frozen=True)
class TechniqueExecuteEvent(BattleEvent):
    actor_id: str
    actor_name: str
    technique_name: str
    description: str


@dataclass(frozen=True)
class ActionAdvanceEvent(BattleEvent):
    source_name: str
    target_name: str
    percent: float              # 拉条比例 (0.5 = 50%)
    distance_before: float
    distance_after: float


@dataclass(frozen=True)
class ActionDelayEvent(BattleEvent):
    source_name: str
    target_name: str
    percent: float              # 推条比例 (0.25 = 25%)
    distance_before: float
    distance_after: float


@dataclass(frozen=True)
class SPChangeEvent(BattleEvent):
    actor_name: str
    delta: int                  # 变动量 (+1, -1, +4 等)
    current_sp: int
    max_sp: int
    reason: str


@dataclass(frozen=True)
class StatusApplyEvent(BattleEvent):
    source_name: str
    target_name: str
    status_id: str
    status_name: str
    duration: int


@dataclass(frozen=True)
class StatusExpireEvent(BattleEvent):
    target_name: str
    status_id: str
    status_name: str


@dataclass(frozen=True)
class DamageAppliedEvent(BattleEvent):
    attacker_name: str
    target_name: str
    damage: float
    is_crit: bool
    breakdown: Any              # DamageBreakdown
    target_hp_left: float


@dataclass(frozen=True)
class HealAppliedEvent(BattleEvent):
    source_name: str
    target_name: str
    amount: float


@dataclass(frozen=True)
class ShieldAppliedEvent(BattleEvent):
    source_name: str
    target_name: str
    amount: float


@dataclass(frozen=True)
class ToughnessReduceEvent(BattleEvent):
    attacker_name: str
    target_name: str
    amount: float
    toughness_left: float
    max_toughness: float


@dataclass(frozen=True)
class WeaknessBreakEvent(BattleEvent):
    breaker_name: str
    target_name: str
    element: str
    break_damage: float
    action_delay_pct: float


@dataclass(frozen=True)
class ToughnessRecoverEvent(BattleEvent):
    target_name: str
    max_toughness: float


class EventBus:
    """全局战斗事件总线，负责事件发布与监听。"""
    def __init__(self):
        self._subscribers: Dict[Type[BattleEvent], List[Callable[[Any], None]]] = {}
        self.history: List[BattleEvent] = []

    def subscribe(self, event_type: Type[BattleEvent], handler: Callable[[Any], None]):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def publish(self, event: BattleEvent):
        self.history.append(event)
        called = set()
        for cls in type(event).__mro__:
            if issubclass(cls, BattleEvent):
                for handler in self._subscribers.get(cls, []):
                    if handler not in called:
                        called.add(handler)
                        handler(event)

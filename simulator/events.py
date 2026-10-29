"""星穹铁道战斗事件系统 (Battle Event System)。

架构原则：
1. 事件是不可变的战斗事实记录 (Immutable Facts)；
2. 任何状态变更 (血量、SP、拉条、伤害、治疗、护盾、韧性削减、弱点击破、召唤物退场) 都产生对应的标准事件；
3. 支持事件总线 (EventBus) 订阅与广播，驱动角色 Kit、光锥、遗器与关卡插件解耦响应。
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Type, Any
from .actions import DamageType


@dataclass(frozen=True)
class BattleEvent:
    av: float                   # 事件发生时的全局行动值
    cycle: int                  # 所在轮次


@dataclass(frozen=True)
class TurnBeginEvent(BattleEvent):
    actor_id: str
    actor_name: str
    speed: float

    @property
    def entity_name(self) -> str:
        return self.actor_name


@dataclass(frozen=True)
class TurnEndEvent(BattleEvent):
    actor_id: str
    actor_name: str

    @property
    def entity_name(self) -> str:
        return self.actor_name


@dataclass(frozen=True)
class ActionExecuteEvent(BattleEvent):
    actor_id: str
    actor_name: str
    action_type: str            # "BasicAttack", "Skill", "Ultimate", "FollowUpAttack", "Technique"
    description: str
    action_kind: Any = None     # 可选 ActionKind 枚举，便于强类型判断
    skill_config_id: int = 0    # 官方 skill_config_id (与实机日志 OnUseSkill 对齐); 0 表示未知/不适用


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
    duration: Any


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
    damage_tag: str = "direct"
    damage_type: Any = None     # DamageType 枚举 (伤害分类的权威字段, damage_tag 仅作展示兼容)
    target_killed: bool = False # 本次伤害是否将该目标从存活击杀至 0 HP

    def __post_init__(self):
        # 手工构造事件未显式给出 damage_type 时, 由 damage_tag 经官方映射收编, 保证该字段恒为枚举
        if self.damage_type is None:
            object.__setattr__(self, "damage_type", DamageType.from_tag(self.damage_tag))


@dataclass(frozen=True)
class EnemyDefeatedEvent(BattleEvent):
    """敌方目标被击败事实事件 (对应单次攻击的第 3 介入点 on_kill，如希儿【再现】、流萤 E2 击杀触发)。"""
    attacker_name: str
    target_name: str


@dataclass(frozen=True)
class HPLostEvent(BattleEvent):
    """实体生命值降低事实事件（含受击扣血、技能自耗血、环境流血等）。"""
    entity_name: str
    amount: float
    hp_left: float
    cause: str = ""


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


@dataclass(frozen=True)
class SpiritSummonedEvent(BattleEvent):
    """伴生忆灵/召唤物入场事实事件。"""
    owner_name: str
    spirit_name: str


@dataclass(frozen=True)
class SpiritDespawnEvent(BattleEvent):
    """伴生忆灵/召唤物退场消失事实事件。"""
    owner_name: str
    spirit_name: str
    reason: str = ""


class EventBus:
    """全局战斗事件总线，负责事件发布与按继承树广播监听。"""
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

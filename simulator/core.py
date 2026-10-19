"""星穹铁道核心战斗调度框架（完整集成：状态时钟、伤害管线与韧性击破系统）。

遵从架构师规范：
1. 状态生命周期时钟与调度循环闭环；
2. 属性动态求值：角色速度、双暴等均由 StatusManager 实时采样；
3. 伤害管线集成：DamageCalculator 负责纯计算，Resolver 负责扣血与事件记录；
4. 韧性与击破：削韧清零触发弱点击破，自动执行 25% 推条并消除 10% 减伤；敌方行动后恢复韧性。
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Any

from .events import (
    EventBus, TurnBeginEvent, TurnEndEvent, ActionExecuteEvent, 
    ToughnessRecoverEvent
)
from .effects import (
    EffectResolver, AdvanceActionEffect, DelayActionEffect, ModifySPEffect, 
    InterruptActionEffect, ApplyStatusEffect, ApplyDamageEffect, ReduceToughnessEffect
)
from .sp import SkillPointManager
from .status import StatusManager, StatType


@dataclass
class Entity:
    name: str
    base_speed: float
    base_atk: float = 1000.0
    base_crit_rate: float = 0.05          # 基础 5% 暴击
    base_crit_dmg: float = 0.50           # 基础 50% 暴伤
    max_hp: float = 10000.0
    current_hp: float = 10000.0
    # 韧性系统 (仅敌方有)
    max_toughness: float = 0.0
    current_toughness: float = 0.0
    weaknesses: List[str] = field(default_factory=list)
    is_broken: bool = False
    # 距离终点的剩余路程（初始为 10,000）
    distance_remaining: float = 10000.0
    # 策略循环：例如 "EAA", "E", "A"
    policy: str = "E"
    policy_index: int = 0
    is_enemy: bool = False
    # 绑定所属的模拟器引用
    simulator: Optional[Any] = None
    # 动作回调：(actor: Entity, resolver: EffectResolver, action_type: str)
    action_callback: Optional[Callable[["Entity", "EffectResolver", str], None]] = None

    @property
    def speed(self) -> float:
        """从状态管理器动态计算实时速度，无缝支持速度 Buff/Debuff。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return max(1.0, self.simulator.status_mgr.calculate_stat(self.name, self.base_speed, StatType.SPEED))
        return max(1.0, self.base_speed)

    @property
    def crit_rate(self) -> float:
        """动态计算实时暴击率。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return self.simulator.status_mgr.calculate_stat(self.name, self.base_crit_rate, StatType.CRIT_RATE)
        return self.base_crit_rate

    @property
    def crit_dmg(self) -> float:
        """动态计算实时暴击伤害。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return self.simulator.status_mgr.calculate_stat(self.name, self.base_crit_dmg, StatType.CRIT_DMG)
        return self.base_crit_dmg

    @property
    def remaining_av(self) -> float:
        """到达终点所需的剩余行动值 (Action Value)。"""
        return self.distance_remaining / self.speed

    def advance_action(self, percent: float):
        distance_cut = 10000.0 * percent
        self.distance_remaining = max(0.0, self.distance_remaining - distance_cut)

    def delay_action(self, percent: float):
        self.distance_remaining += 10000.0 * percent

    def reset_distance(self):
        self.distance_remaining = 10000.0

    def get_next_action_intent(self) -> str:
        if not self.policy:
            return "E"
        return self.policy[self.policy_index % len(self.policy)]

    def advance_policy(self):
        self.policy_index += 1


class TurnSimulator:
    def __init__(self, entities: Optional[List[Entity]] = None, initial_sp: int = 3, max_sp: int = 5):
        self.entities: List[Entity] = []
        self.current_av: float = 0.0
        self.event_bus: EventBus = EventBus()
        self.sp: SkillPointManager = SkillPointManager(initial_sp=initial_sp, max_sp=max_sp)
        self.status_mgr: StatusManager = StatusManager(self)
        self.resolver: EffectResolver = EffectResolver(self)

        if entities:
            for e in entities:
                self.add_entity(e)

    def add_entity(self, entity: Entity):
        entity.simulator = self
        self.entities.append(entity)

    @property
    def current_cycle(self) -> int:
        if self.current_av <= 150.0:
            return 0
        return 1 + int((self.current_av - 150.0) // 100.0)

    def get_action_order(self) -> List[Entity]:
        return sorted(self.entities, key=lambda e: e.remaining_av)

    def step(self) -> Optional[Entity]:
        if not self.entities:
            return None

        # 1. 寻找最快到达终点者
        active_entity = min(self.entities, key=lambda e: e.remaining_av)
        delta_av = active_entity.remaining_av

        # 2. 全员沿跑道行进 delta_av 距离
        if delta_av > 0:
            for entity in self.entities:
                travel_distance = entity.speed * delta_av
                entity.distance_remaining = max(0.0, entity.distance_remaining - travel_distance)
            self.current_av += delta_av

        # 3. 状态时钟：结算【目标回合开始】类型状态 (如持续伤害)
        self.status_mgr.tick_on_turn_begin(active_entity)

        # 4. 发布【回合开始】事件
        self.event_bus.publish(TurnBeginEvent(
            av=round(self.current_av, 2),
            cycle=self.current_cycle,
            actor_id=active_entity.name,
            actor_name=active_entity.name,
            speed=round(active_entity.speed, 1)
        ))

        # 5. 决定动作意图与战技点处理 (敌方行动不耗己方战技点)
        intent = active_entity.get_next_action_intent()
        if not active_entity.is_enemy:
            if intent == "E":
                if self.sp.can_consume(1):
                    actual_action = "Skill"
                    self.resolver.enqueue(ModifySPEffect(active_entity.name, -1, "施放战技"))
                else:
                    actual_action = "BasicAttack (SP不足降级)"
                    self.resolver.enqueue(ModifySPEffect(active_entity.name, 1, "战技点不足，降级普攻"))
            else:
                actual_action = "BasicAttack"
                self.resolver.enqueue(ModifySPEffect(active_entity.name, 1, "施放普攻"))
        else:
            actual_action = "EnemySkill"

        active_entity.advance_policy()

        # 发布【动作执行】事件
        self.event_bus.publish(ActionExecuteEvent(
            av=round(self.current_av, 2),
            cycle=self.current_cycle,
            actor_id=active_entity.name,
            actor_name=active_entity.name,
            action_type=actual_action,
            description=f"执行 {actual_action}"
        ))

        # 6. 执行技能回调与效果结算
        if active_entity.action_callback:
            active_entity.action_callback(active_entity, self.resolver, actual_action)

        self.resolver.resolve_all()

        # 7. 状态时钟：结算【目标行动结束】与【施法者行动结束】状态
        self.status_mgr.tick_on_turn_end(active_entity)

        # 8. 弱点恢复判定：若当前行动者处于破韧状态，行动后恢复韧性条并移除破韧
        if active_entity.is_broken:
            active_entity.is_broken = False
            active_entity.current_toughness = active_entity.max_toughness
            self.event_bus.publish(ToughnessRecoverEvent(
                av=round(self.current_av, 2),
                cycle=self.current_cycle,
                target_name=active_entity.name,
                max_toughness=active_entity.max_toughness
            ))

        # 9. 发布【回合结束】事件并重置跑道距离
        self.event_bus.publish(TurnEndEvent(
            av=round(self.current_av, 2),
            cycle=self.current_cycle,
            actor_id=active_entity.name,
            actor_name=active_entity.name
        ))
        active_entity.reset_distance()
        return active_entity

    def insert_ultimate(self, entity: Entity, description: str = "释放终结技", sp_change: int = 0):
        self.resolver.enqueue(InterruptActionEffect(
            actor=entity,
            description=description,
            sp_change=sp_change
        ))
        self.resolver.resolve_all()

    def run_until_av(self, max_av: float = 150.0):
        while True:
            next_av = min(self.entities, key=lambda e: e.remaining_av).remaining_av
            if self.current_av + next_av > max_av:
                break
            actor = self.step()
            yield actor

"""星穹铁道核心战斗调度框架（完整集成：状态时钟、伤害管线与韧性击破系统）。

遵从架构师规范：
1. 状态生命周期时钟与调度循环闭环；
2. 属性动态求值：角色速度、双暴等均由 StatusManager 实时采样；
3. 伤害管线集成：DamageCalculator 负责纯计算，Resolver 负责扣血与事件记录；
4. 韧性与击破：削韧清零触发弱点击破，自动执行 25% 推条并消除 10% 减伤；敌方行动后恢复韧性。
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Any, Tuple

from .events import (
    EventBus, BattleEvent, TurnBeginEvent, TurnEndEvent, ActionExecuteEvent, 
    ToughnessRecoverEvent, TechniqueExecuteEvent
)
from .effects import (
    EffectResolver, AdvanceActionEffect, DelayActionEffect, ModifySPEffect, 
    InterruptActionEffect, ApplyStatusEffect, ApplyDamageEffect, ReduceToughnessEffect
)
from .sp import SkillPointManager
from .status import StatusManager, StatType, StatusInstance, Modifier, ModifierOp, DurationTiming, StackPolicy
from .combat_port import CombatPort, BuffSpec
from .actions import ActionKind, ActionContext, ActionRequest


class SimulatorCombatPort:
    """TurnSimulator 与 KitHandler 之间的基础设施桥接端口。"""
    def __init__(self, simulator: "TurnSimulator"):
        self.sim = simulator

    def _get_entity(self, name_or_id: str) -> Optional["Entity"]:
        for e in self.sim.entities:
            if e.name == name_or_id or str(getattr(e, "avatar_id", "")) == str(name_or_id):
                return e
        return None

    def allies(self, actor_id: str) -> Tuple[str, ...]:
        actor = self._get_entity(actor_id)
        if not actor:
            return ()
        return tuple(e.name for e in self.sim.entities if e.is_enemy == actor.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False)))

    def enemies(self, actor_id: str) -> Tuple[str, ...]:
        actor = self._get_entity(actor_id)
        if not actor:
            return ()
        return tuple(e.name for e in self.sim.entities if e.is_enemy != actor.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False)))

    def stat(self, entity_id: str, stat: StatType) -> float:
        ent = self._get_entity(entity_id)
        if not ent:
            return 0.0
        base_val = 0.0
        if stat == StatType.CRIT_DMG:
            base_val = ent.base_crit_dmg
        elif stat == StatType.CRIT_RATE:
            base_val = ent.base_crit_rate
        elif stat == StatType.SPEED:
            base_val = ent.base_speed
        elif stat == StatType.ATK_BASE:
            base_val = ent.base_atk
        return self.sim.status_mgr.calculate_stat(ent.name, base_val, stat)

    def has_status(self, target_id: str, key: str) -> bool:
        ent = self._get_entity(target_id)
        return self.sim.status_mgr.has_status(ent.name, key) if ent else False

    def upsert_status(self, spec: BuffSpec) -> None:
        src = self._get_entity(spec.source_id)
        tgt = self._get_entity(spec.target_id)
        if not src or not tgt:
            return
        status = StatusInstance(
            id=spec.key,
            name=spec.name,
            source=src,
            target=tgt,
            duration=spec.duration,
            timing=spec.timing,
            modifiers=list(spec.modifiers),
            stack_policy=spec.stack_policy,
            skip_current_clock=spec.skip_current_clock
        )
        self.sim.status_mgr.add_status(status)

    def remove_status(self, target_id: str, key: str) -> None:
        ent = self._get_entity(target_id)
        if ent:
            self.sim.status_mgr.remove_status(ent.name, key)

    def advance(self, source_id: str, target_id: str, ratio: float) -> None:
        tgt = self._get_entity(target_id)
        if tgt:
            self.sim.resolver.enqueue(AdvanceActionEffect(source_id, tgt, ratio))

    def delay(self, source_id: str, target_id: str, ratio: float) -> None:
        tgt = self._get_entity(target_id)
        if tgt:
            self.sim.resolver.enqueue(DelayActionEffect(source_id, tgt, ratio))

    def change_sp(self, source_id: str, amount: int, reason: str) -> None:
        self.sim.resolver.enqueue(ModifySPEffect(source_id, amount, reason))

    def set_sp_cap(self, new_cap: int) -> None:
        self.sim.sp.set_max_sp(new_cap)

    def gain_energy(self, entity_id: str, amount: float) -> None:
        ent = self._get_entity(entity_id)
        if ent:
            ent.energy = min(ent.max_energy, ent.energy + amount)

    def heal(self, source_id: str, target_id: str, amount: float) -> None:
        tgt = self._get_entity(target_id)
        if tgt and hasattr(tgt, "current_hp"):
            tgt.current_hp = min(tgt.max_hp, tgt.current_hp + amount)

    def add_shield(self, source_id: str, target_id: str, amount: float, duration: int = 3) -> None:
        tgt = self._get_entity(target_id)
        if tgt and hasattr(tgt, "shield"):
            tgt.shield = max(tgt.shield, amount)

    def dispel(self, target_id: str, is_debuff: bool = True) -> None:
        pass

    def max_energy(self, entity_id: str) -> float:
        ent = self._get_entity(entity_id)
        return ent.max_energy if ent else 120.0

    def hp_ratio(self, entity_id: str) -> float:
        ent = self._get_entity(entity_id)
        if ent and getattr(ent, "max_hp", 0) > 0:
            return ent.current_hp / ent.max_hp
        return 1.0

    def attack(
        self,
        source_id: str,
        target_id: str,
        *,
        element: str,
        atk_multiplier: float,
        toughness_damage: float,
        damage_tag: str = "direct",
        ignore_weakness: bool = False
    ) -> None:
        tgt = self._get_entity(target_id)
        src = self._get_entity(source_id)
        if not tgt or not src:
            return
        from .effects import DamageRequest
        base_res = 0.20
        if hasattr(tgt, "damage_res") and isinstance(tgt.damage_res, dict) and element in tgt.damage_res:
            base_res = tgt.damage_res[element]
        elif hasattr(tgt, "weaknesses") and element in tgt.weaknesses:
            base_res = 0.0
        req = DamageRequest(
            attacker=src,
            target=tgt,
            skill_multiplier=atk_multiplier,
            target_base_res=base_res,
            target_is_broken=tgt.is_broken
        )
        self.sim.resolver.enqueue(ApplyDamageEffect(
            request=req,
            toughness_reduction=toughness_damage,
            element=element,
            ignore_weakness=ignore_weakness
        ))


@dataclass
class Entity:
    name: str
    base_speed: float
    base_atk: float = 1000.0
    base_crit_rate: float = 0.05          # 基础 5% 暴击
    base_crit_dmg: float = 0.50           # 基础 50% 暴伤
    max_hp: float = 10000.0
    current_hp: float = 10000.0
    shield: float = 0.0
    energy: float = 0.0
    max_energy: float = 120.0
    avatar_id: int = 0
    eidolon: int = 0
    base_def: float = 600.0
    base_effect_res: float = 0.10
    base_effect_hit_rate: float = 0.0
    base_break_effect: float = 0.0
    base_err: float = 1.0
    base_dmg_boost: float = 0.0
    element: str = ""
    path: str = ""
    level: int = 80
    # 关联的技能套件 (Kit)
    kit: Optional[Any] = None
    # 关联的光锥独立运行时 (LightConeHandler)
    light_cone: Optional[Any] = None
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
    def atk(self) -> float:
        """从状态管理器动态计算实时攻击力。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return self.simulator.status_mgr.calculate_stat(self.name, self.base_atk, StatType.ATK_BASE)
        return self.base_atk

    @property
    def defense(self) -> float:
        """从状态管理器动态计算实时防御力。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return self.simulator.status_mgr.calculate_stat(self.name, self.base_def, StatType.DEF_PERCENT)
        return self.base_def

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
    def err(self) -> float:
        """动态计算实时能量恢复效率。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return self.simulator.status_mgr.calculate_stat(self.name, self.base_err, StatType.ERR)
        return self.base_err

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
    def __init__(
        self,
        entities: Optional[List[Entity]] = None,
        initial_sp: int = 3,
        max_sp: int = 5,
        use_techniques: bool = False,
        technique_users: Optional[List[str]] = None,
        auto_ult: bool = True
    ):
        self.entities: List[Entity] = []
        self.current_av: float = 0.0
        self.event_bus: EventBus = EventBus()
        self.sp: SkillPointManager = SkillPointManager(initial_sp=initial_sp, max_sp=max_sp)
        self.status_mgr: StatusManager = StatusManager(self)
        self.resolver: EffectResolver = EffectResolver(self)
        self.port: SimulatorCombatPort = SimulatorCombatPort(self)
        self.auto_ult: bool = auto_ult
        self._current_turn_entity: Optional[Entity] = None

        # 注册事件总线转发至各实体挂载的光锥
        def _forward_event_to_light_cones(evt: BattleEvent):
            for ent in self.entities:
                if getattr(ent, "light_cone", None) is not None:
                    ent.light_cone.on_event(evt)
        self.event_bus.subscribe(BattleEvent, _forward_event_to_light_cones)

        if entities:
            for e in entities:
                self.add_entity(e, trigger_battle_start=False)

            # 1. 结算进场常态被动与基础光环 (如花火天赋扩展SP上限至7点、光锥进战回能与谕示)
            for e in self.entities:
                if getattr(e, "kit", None) is not None:
                    e.kit.on_battle_start()
                if getattr(e, "light_cone", None) is not None:
                    e.light_cone.on_battle_start()

            # 2. 结算战前秘技 (Techniques)
            if use_techniques:
                target_users = technique_users or [e.name for e in self.entities if not e.is_enemy]
                for user_id in target_users:
                    self.use_technique(user_id)
            elif technique_users:
                for user_id in technique_users:
                    self.use_technique(user_id)

            self.resolver.resolve_all()

    def get_entity(self, name_or_id: str) -> Optional[Entity]:
        for e in self.entities:
            if e.name == name_or_id or str(getattr(e, "avatar_id", "")) == str(name_or_id):
                return e
        return None

    def _get_entity(self, name_or_id: str) -> Optional[Entity]:
        return self.get_entity(name_or_id)

    def use_technique(self, actor_id: str) -> None:
        """在开战前执行指定角色的秘技。"""
        ent = self._get_entity(actor_id)
        if ent and getattr(ent, "kit", None) is not None:
            try:
                defn = ent.kit.definition(ActionKind.TECHNIQUE)
                tech_name = defn.name if defn else "秘技"
            except Exception:
                tech_name = "秘技"

            self.event_bus.publish(TechniqueExecuteEvent(
                av=0.0,
                cycle=0,
                actor_id=ent.name,
                actor_name=ent.name,
                technique_name=tech_name,
                description=f"施放秘技【{tech_name}】"
            ))

            ent.kit.use_technique()
            self.resolver.resolve_all()

    def add_entity(self, entity: Entity, trigger_battle_start: bool = True):
        entity.simulator = self
        self.entities.append(entity)
        if getattr(entity, "kit", None) is not None:
            entity.kit.port = self.port
            if trigger_battle_start:
                entity.kit.on_battle_start()
        if getattr(entity, "light_cone", None) is not None:
            entity.light_cone.port = self.port
            if trigger_battle_start:
                entity.light_cone.on_battle_start()

    @property
    def current_cycle(self) -> int:
        if self.current_av <= 150.0:
            return 0
        return 1 + int((self.current_av - 150.0) // 100.0)

    @property
    def next_entity(self) -> Optional[Entity]:
        """获取当前跑道上最先到达行动终点的存活实体。"""
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not alive:
            return None
        return min(alive, key=lambda e: e.remaining_av)

    def get_action_order(self) -> List[Entity]:
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        return sorted(alive, key=lambda e: e.remaining_av)

    @property
    def current_turn_entity(self) -> Optional[Entity]:
        """获取当前已到达跑道终点、处于行动决策窗口中的实体。"""
        return self._current_turn_entity

    def advance_to_next_turn(self) -> Optional[Entity]:
        """将跑道推进至最快到达终点的实体 (0.0 AV)，结算【回合开始】状态时钟并发布 TurnBeginEvent。"""
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not alive:
            return None

        # 1. 寻找最快到达终点者
        active_entity = min(alive, key=lambda e: e.remaining_av)
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

        self._current_turn_entity = active_entity
        return active_entity

    def execute_current_turn(
        self, 
        action_override: Optional[ActionKind] = None, 
        target_ids: Optional[Tuple[str, ...]] = None
    ) -> Entity:
        """执行当前到达终点实体的回合动作，结算伤害、终结技抢断、状态时钟与回合结束。"""
        active_entity = self._current_turn_entity
        if active_entity is None:
            active_entity = self.advance_to_next_turn()
            if active_entity is None:
                raise RuntimeError("场上无可用实体执行行动")

        # 5. 决定动作意图与执行路径 (优先走 KitHandler 架构)
        intent = active_entity.get_next_action_intent()
        if getattr(active_entity, "kit", None) is not None:
            if action_override is not None:
                req_kind = action_override
            else:
                req_kind = ActionKind.SKILL if intent == "E" else ActionKind.BASIC
            defn = active_entity.kit.definition(req_kind)

            # 校验 SP 资源
            if defn.cost.sp > 0 and not self.sp.can_consume(defn.cost.sp):
                actual_kind = ActionKind.BASIC
                defn = active_entity.kit.definition(actual_kind)
                actual_action = f"{defn.name} (SP不足降级)"
            else:
                actual_kind = req_kind
                actual_action = defn.name

            # 统一扣除/返还 SP 成本
            if defn.cost.sp != 0:
                self.resolver.enqueue(ModifySPEffect(active_entity.name, -defn.cost.sp, f"施放{defn.name}"))

            active_entity.advance_policy()

            self.event_bus.publish(ActionExecuteEvent(
                av=round(self.current_av, 2),
                cycle=self.current_cycle,
                actor_id=active_entity.name,
                actor_name=active_entity.name,
                action_type=actual_action,
                description=f"施放【{defn.name}】"
            ))

            ctx = ActionContext(
                action_id=f"{active_entity.name}_{self.current_av:.1f}",
                actor_id=active_entity.name,
                kind=actual_kind,
                target_ids=target_ids if target_ids is not None else ()
            )
            if getattr(active_entity, "light_cone", None) is not None:
                active_entity.light_cone.on_action_before(ctx)
            active_entity.kit.execute(ctx)
            if getattr(active_entity, "light_cone", None) is not None:
                active_entity.light_cone.on_action_after(ctx)
        else:
            # 兼容模式：传统回调执行路径
            if not active_entity.is_enemy:
                is_skill = (action_override == ActionKind.SKILL) if action_override is not None else (intent == "E")
                if is_skill:
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

            self.event_bus.publish(ActionExecuteEvent(
                av=round(self.current_av, 2),
                cycle=self.current_cycle,
                actor_id=active_entity.name,
                actor_name=active_entity.name,
                action_type=actual_action,
                description=f"执行 {actual_action}"
            ))

            if active_entity.action_callback:
                active_entity.action_callback(active_entity, self.resolver, actual_action)
            elif active_entity.is_enemy:
                allies = [e for e in self.entities if not e.is_enemy]
                if allies:
                    import random
                    target = max(allies, key=lambda a: self.status_mgr.calculate_stat(a.name, 100.0, StatType.AGGRO) + random.uniform(0, 30))
                    from .effects import ApplyDamageEffect, DamageRequest
                    req = DamageRequest(attacker=active_entity, target=target, skill_multiplier=1.2)
                    self.resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
                    self.port.gain_energy(target.name, 10.0)

        self.resolver.resolve_all()

        if self.auto_ult:
            self.check_and_cast_ultimates()

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
        self._current_turn_entity = None
        return active_entity

    def step(
        self, 
        action_override: Optional[ActionKind] = None, 
        target_ids: Optional[Tuple[str, ...]] = None
    ) -> Optional[Entity]:
        if not self.entities:
            return None
        if self._current_turn_entity is None:
            actor = self.advance_to_next_turn()
            if not actor:
                return None
        return self.execute_current_turn(action_override=action_override, target_ids=target_ids)

    def can_cast_ultimate(self, actor_id: str) -> bool:
        """检查指定角色当前是否满足终结技施放条件 (满能量或满特殊层数)。"""
        ent = self.get_entity(actor_id)
        if not ent or getattr(ent, "kit", None) is None:
            return False
        if hasattr(ent.kit, "slashed_dream"):
            return getattr(ent.kit, "slashed_dream", 0) >= 9
        return ent.max_energy > 0 and ent.energy >= ent.max_energy

    def get_ready_ultimates(self) -> List[Entity]:
        """获取当前所有终结技充能就绪的我方角色。"""
        ready = []
        for e in self.entities:
            if not e.is_enemy and self.can_cast_ultimate(e.name):
                ready.append(e)
        return ready

    def cast_ultimate(self, actor_id: str, target_ids: Optional[Tuple[str, ...]] = None) -> bool:
        """立即插入并施放指定角色的终结技。"""
        ent = self.get_entity(actor_id)
        if not ent or getattr(ent, "kit", None) is None:
            return False

        try:
            defn = ent.kit.definition(ActionKind.ULTIMATE)
        except Exception:
            return False

        # 校验并消耗能量 / 特殊机制 (如黄泉残梦)
        if hasattr(ent.kit, "slashed_dream"):
            if ent.kit.slashed_dream < 9:
                return False
            ent.kit.slashed_dream = 0
        else:
            if ent.max_energy > 0 and ent.energy < ent.max_energy:
                return False
            ent.energy = 0.0

        self.event_bus.publish(ActionExecuteEvent(
            av=round(self.current_av, 2),
            cycle=self.current_cycle,
            actor_id=ent.name,
            actor_name=ent.name,
            action_type=f"Ultimate ({defn.name})",
            description=f"【{ent.name}】能量充盈，抢断插入终结技【{defn.name}】！"
        ))

        ctx = ActionContext(
            action_id=f"{ent.name}_ult_{self.current_av:.1f}",
            actor_id=ent.name,
            kind=ActionKind.ULTIMATE,
            target_ids=target_ids if target_ids is not None else ()
        )
        if getattr(ent, "light_cone", None) is not None:
            ent.light_cone.on_action_before(ctx)
        ent.kit.execute(ctx)
        if getattr(ent, "light_cone", None) is not None:
            ent.light_cone.on_action_after(ctx)
        self.resolver.resolve_all()
        return True

    def check_and_cast_ultimates(self) -> List[str]:
        """检查场上全员能量，自动抢断施放所有就绪的终结技。"""
        casted = []
        for e in self.get_ready_ultimates():
            if self.cast_ultimate(e.name):
                casted.append(e.name)
        return casted

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

    def get_battle_status(self) -> Dict[str, Any]:
        """获取当前全战场统一状态视图 (Single Source of Truth: status)。"""
        timeline = []
        for e in sorted(self.entities, key=lambda x: x.remaining_av):
            timeline.append({
                "name": e.name,
                "remaining_av": round(e.remaining_av, 2),
                "distance": round(e.distance_remaining, 1),
                "speed": round(e.speed, 2),
                "is_enemy": e.is_enemy
            })

        ready_ults = [u.name for u in self.get_ready_ultimates()]

        meta = {
            "av": round(self.current_av, 2),
            "cycle": self.current_cycle,
            "sp": {
                "current": self.sp.current_sp,
                "max": self.sp.max_sp
            },
            "current_actor": self.current_turn_entity.name if self.current_turn_entity else None,
            "ready_ultimates": ready_ults,
            "timeline": timeline
        }

        team = {}
        enemies = {}

        for e in self.entities:
            snap = self.status_mgr.get_detailed_snapshot(e)
            if e.is_enemy:
                enemies[e.name] = snap
            else:
                team[e.name] = snap

        return {
            "meta": meta,
            "team": team,
            "enemies": enemies
        }

    @property
    def status(self) -> Dict[str, Any]:
        """战场全量实时状态字典属性，作为全系统事实真理源。"""
        return self.get_battle_status()

    def query_status(self, query: str = "") -> Any:
        """从统一 status 中智能检索信息，支持快捷名称、属性名或点号路径。
        例如:
        - query_status("长夜月") -> 返回长夜月全量 snapshot
        - query_status("长夜月.current_atk") -> 返回 1444.1
        - query_status("长夜月.buffs") -> 返回 Buff 列表
        - query_status("sp") -> {"current": 5, "max": 5}
        - query_status("meta.av") -> 41.4
        - query_status("boss") -> 返回首领状态
        """
        st = self.status
        query = query.strip()
        if not query:
            return st

        # 快捷别名支持
        if query.lower() in ("sp", "skill_points", "战技点"):
            return st["meta"]["sp"]
        if query.lower() in ("av", "action_value", "行动值"):
            return st["meta"]["av"]
        if query.lower() in ("cycle", "轮次"):
            return st["meta"]["cycle"]
        if query.lower() in ("timeline", "跑道", "行动顺序"):
            return st["meta"]["timeline"]
        if query.lower() in ("boss", "enemy", "怪物", "首领"):
            return next(iter(st["enemies"].values())) if st["enemies"] else None

        # 检查是否是队伍中角色名
        for name, data in st["team"].items():
            if query == name or query.lower() in name.lower():
                return data

        # 检查是否是敌方单位名
        for name, data in st["enemies"].items():
            if query == name or query.lower() in name.lower():
                return data

        # 点号分段遍历
        parts = query.split(".")
        # 支持以角色名或怪物名开头点号访问，例如 "长夜月.current_atk" 或 "月夜天马.current_hp"
        first_part = parts[0]
        curr_root = None
        for name, data in {**st["team"], **st["enemies"]}.items():
            if first_part == name or first_part.lower() in name.lower():
                curr_root = data
                parts = parts[1:]
                break

        curr: Any = curr_root if curr_root is not None else st
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            elif isinstance(curr, dict):
                found = False
                for k, v in curr.items():
                    if k.lower() == p.lower():
                        curr = v
                        found = True
                        break
                if not found:
                    return None
            else:
                return None
        return curr

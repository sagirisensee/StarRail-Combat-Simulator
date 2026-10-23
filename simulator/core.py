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
        if name_or_id in ("长夜", "忆灵", "memosprite"):
            for e in self.sim.entities:
                if "长夜月" in e.name:
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
        elif stat in (StatType.ATK_BASE, StatType.ATK_PERCENT, StatType.ATK):
            base_val = ent.base_atk
        elif stat in (StatType.DEF, StatType.DEF_PERCENT, StatType.DEF_BASE):
            base_val = getattr(ent, "base_def", 0.0)
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
            skip_current_clock=spec.skip_current_clock,
            category=getattr(spec, "category", "buff"),
            description=getattr(spec, "description", None)
        )
        self.sim.status_mgr.add_status(status)

    def remove_status(self, target_id: str, key: str) -> None:
        ent = self._get_entity(target_id)
        if ent:
            self.sim.status_mgr.remove_status(ent.name, key)

    def advance(self, source_id: str, target_id: str, ratio: float) -> None:
        tgt = self._get_entity(target_id)
        if tgt:
            if ratio >= 1.0 and (self.sim.current_turn_entity == tgt or getattr(tgt, "extra_immediate_action", False)):
                tgt.extra_immediate_action = True
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
        ignore_weakness: bool = False,
        scaling_stat: str = "atk"
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
            target_is_broken=tgt.is_broken,
            scaling_stat=scaling_stat
        )
        if damage_tag == "FollowUpAttack":
            self.sim.event_bus.publish(ActionExecuteEvent(
                av=round(self.sim.current_av, 2),
                cycle=self.sim.current_cycle,
                actor_id=source_id,
                actor_name=source_id,
                action_type="FollowUpAttack",
                description=f"【{source_id}】触发追加攻击"
            ))
        self.sim.resolver.enqueue(ApplyDamageEffect(
            request=req,
            toughness_reduction=toughness_damage,
            element=element,
            ignore_weakness=ignore_weakness
        ))

    def max_hp(self, entity_id: str) -> float:
        ent = self._get_entity(entity_id)
        if ent:
            base_max_hp = getattr(ent, "max_hp", 0.0)
            if hasattr(self.sim, "status_mgr") and base_max_hp > 0 and base_max_hp != float("inf"):
                white_hp = getattr(ent, "base_white_hp", 0.0) or base_max_hp
                hp_pct_sum = 0.0
                hp_flat_sum = 0.0
                for status in self.sim.status_mgr.get_statuses(ent.name):
                    for mod in status.modifiers:
                        if mod.stat == StatType.MAX_HP_PERCENT:
                            val = mod.value * status.stacks
                            if mod.op == ModifierOp.PERCENT:
                                hp_pct_sum += val
                            elif mod.op == ModifierOp.ADD:
                                if val > 1.0:
                                    hp_flat_sum += val
                                else:
                                    hp_pct_sum += val
                return base_max_hp + (white_hp * hp_pct_sum) + hp_flat_sum
            return base_max_hp
        return 0.0

    def lose_hp(self, entity_id: str, amount: float, cause: str = "") -> None:
        ent = self._get_entity(entity_id)
        if ent:
            actual = min(ent.current_hp, amount)
            ent.current_hp = max(1.0, ent.current_hp - actual)
            for e in list(self.sim.entities):
                if getattr(e, "kit", None) and hasattr(e.kit, "on_hp_lost"):
                    e.kit.on_hp_lost(entity_id, actual, cause)

    def summon_spirit(self, owner_id: str, name: str, base_speed: float, max_hp: float, kit_class: Any = None, kit_args: Optional[dict] = None) -> Any:
        existing = self.sim.get_entity(name)
        if existing:
            return existing
        owner = self._get_entity(owner_id)
        spirit = Entity(
            name=name,
            base_speed=base_speed,
            base_atk=0.0,
            max_hp=max_hp,
            current_hp=max_hp,
            base_crit_rate=owner.base_crit_rate if owner else 0.05,
            base_crit_dmg=owner.base_crit_dmg if owner else 0.50,
            is_enemy=False,
            is_memosprite=True,
            master_name=owner_id,
            policy="A"
        )
        if kit_class:
            spirit.kit = kit_class(name, self, **(kit_args or {}))
        self.sim.add_entity(spirit, trigger_battle_start=False)
        # 关卡环境机制：若关卡配置了入场环境生命削减 (如【血噬】)，对新入场实体统一调用 lose_hp 扣减生命并通知生命降低事件
        if hasattr(self.sim, "stage_mechanics") and any("血" in m for m in self.sim.stage_mechanics):
            self.lose_hp(name, 500.0, cause="stage_mechanic_bleed_summon")
        return spirit

    def despawn_spirit(self, name: str, reason: str = "") -> None:
        ent = self.sim.get_entity(name)
        if ent and ent in self.sim.entities:
            self.sim.entities.remove(ent)
            if self.sim._current_turn_entity == ent:
                self.sim._current_turn_entity = None


@dataclass
class Entity:
    name: str
    base_speed: float
    base_atk: float = 1000.0
    base_crit_rate: float = 0.05          # 基础 5% 暴击
    base_crit_dmg: float = 0.50           # 基础 50% 暴伤
    max_hp: float = 10000.0
    current_hp: float = 10000.0
    base_white_hp: float = 0.0            # 基础白字生命 (角色白字+光锥白字，用于百分比生命加成)
    base_white_speed: float = 0.0         # 基础白字速度 (角色基础白字速度，用于百分比速度加成)
    base_white_atk: float = 0.0           # 基础白字攻击
    base_white_def: float = 0.0           # 基础白字防御
    base_outgoing_healing: float = 0.0    # 基础治疗量加成
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
    # 关联的遗器独立运行时列表 (List[RelicSetHandler])
    relic_handlers: List[Any] = field(default_factory=list)
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
    is_memosprite: bool = False
    master_name: Optional[str] = None
    extra_immediate_action: bool = False
    # 绑定所属的模拟器引用
    simulator: Optional[Any] = None
    # 动作回调：(actor: Entity, resolver: EffectResolver, action_type: str)
    action_callback: Optional[Callable[["Entity", "EffectResolver", str], None]] = None

    @property
    def speed(self) -> float:
        """从状态管理器动态计算实时速度，无缝支持速度 Buff/Debuff。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return max(1.0, self.simulator.status_mgr.calculate_stat(self.name, self.base_speed, StatType.SPEED, white_base=getattr(self, "base_white_speed", 0.0)))
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
        if getattr(self, "extra_immediate_action", False):
            self.distance_remaining = 0.0
            self.extra_immediate_action = False
        else:
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
        auto_ult: bool = True,
        stage_mechanics: Optional[List[str]] = None
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
        self.stage_mechanics: List[str] = list(stage_mechanics or [])

        # 注册事件总线转发至各实体挂载的技能套件、光锥与遗器
        def _forward_event_to_handlers(evt: BattleEvent):
            for ent in self.entities:
                if getattr(ent, "kit", None) is not None and hasattr(ent.kit, "on_event"):
                    ent.kit.on_event(evt)
                if getattr(ent, "light_cone", None) is not None:
                    ent.light_cone.on_event(evt)
                for rh in getattr(ent, "relic_handlers", []):
                    rh.on_event(evt)
        self.event_bus.subscribe(BattleEvent, _forward_event_to_handlers)

        if entities:
            for e in entities:
                self.add_entity(e, trigger_battle_start=False)
                # 角色固有队伍被动（如花火战技点上限提升至7/8点）在战前秘技生效前预初始化
                if "花火" in e.name or "Sparkle" in e.name:
                    sp_cap = 8 if getattr(e, "eidolon", 0) >= 4 else 7
                    self.port.set_sp_cap(sp_cap)

            # 1. 战前秘技 (Techniques 在入场前生效)
            if use_techniques:
                target_users = technique_users or [e.name for e in self.entities if not e.is_enemy]
                if not technique_users:
                    def _tech_order(uid):
                        ent = self._get_entity(uid)
                        if ent and getattr(ent, "kit", None):
                            try:
                                d = ent.kit.definition(ActionKind.TECHNIQUE)
                                name = d.name if d else ""
                            except Exception:
                                name = ""
                            if "银狼" in name or "瓦尔特" in name or "卡芙卡" in name or "黑天鹅" in name:
                                return 0
                            if "自律" in name or "知更鸟" in name or "星期日" in name:
                                return 2
                        return 1
                    target_users = sorted(target_users, key=_tech_order)
                for user_id in target_users:
                    self.use_technique(user_id)
            elif technique_users:
                for user_id in technique_users:
                    self.use_technique(user_id)

            # 2. 关卡环境机制 (Stage Mechanics 环境效果在进战时挂载)
            if stage_mechanics:
                for mech in stage_mechanics:
                    for e in self.entities:
                        self.status_mgr.add_status(StatusInstance(
                            id=f"Stage_Mechanic_{mech}_{e.name}",
                            name=mech,
                            source=e,
                            target=e,
                            duration=None,
                            timing=DurationTiming.TARGET_TURN_END,
                            modifiers=[],
                            category="other",
                            description="关卡全局环境机制"
                        ))

            # 3. 战斗开始被动与光环 (on_battle_start)
            for e in self.entities:
                if getattr(e, "kit", None) is not None:
                    e.kit.on_battle_start()
                if getattr(e, "light_cone", None) is not None:
                    e.light_cone.on_battle_start()
                for rh in getattr(e, "relic_handlers", []):
                    rh.port = self.port
                    rh.on_battle_start()

            self.resolver.resolve_all()

    def get_entity(self, name_or_id: str) -> Optional[Entity]:
        for e in self.entities:
            if e.name == name_or_id or str(getattr(e, "avatar_id", "")) == str(name_or_id):
                return e
        return None

    def _get_entity(self, name_or_id: str) -> Optional[Entity]:
        ent = self.get_entity(name_or_id)
        if not ent and name_or_id in ("长夜", "忆灵", "memosprite"):
            return self.get_entity("长夜月")
        return ent

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
        for rh in getattr(entity, "relic_handlers", []):
            rh.port = self.port
            if trigger_battle_start:
                rh.on_battle_start()

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

        # 1. 寻找最快到达终点者 (若有多个单位 remaining_av == 0，优先忆灵/拉条者)
        active_entity = min(alive, key=lambda e: (round(e.remaining_av, 4), 0 if getattr(e, "is_memosprite", False) else 1))
        delta_av = active_entity.remaining_av

        # 2. 全员沿跑道行进 delta_av 距离
        if delta_av > 0:
            for entity in self.entities:
                travel_distance = entity.speed * delta_av
                entity.distance_remaining = max(0.0, entity.distance_remaining - travel_distance)
            self.current_av += delta_av

        # 3. 状态时钟：结算【目标回合开始】类型状态 (如持续伤害)
        self.status_mgr.tick_on_turn_begin(active_entity)

        # 关卡环境机制：若关卡配置了行动回合开始环境生命削减 (如【血噬】)，对当前我方行动实体统一结算扣血
        if hasattr(self, "stage_mechanics") and any("血" in m for m in self.stage_mechanics) and not active_entity.is_enemy:
            self.port.lose_hp(active_entity.name, 500.0, cause="stage_mechanic_bleed_turn_begin")

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
        target_ids: Optional[Tuple[str, ...]] = None,
        actor: Optional[Entity] = None
    ) -> Entity:
        """执行当前到达终点实体的回合动作，结算伤害、终结技抢断、状态时钟与回合结束。"""
        active_entity = actor if actor is not None else self._current_turn_entity
        if active_entity is None:
            active_entity = self.advance_to_next_turn()
            if active_entity is None:
                raise RuntimeError("场上无可用实体执行行动")

        # 5. 决定动作意图与执行路径 (优先走 KitHandler 架构)
        intent = active_entity.get_next_action_intent()
        if getattr(active_entity, "kit", None) is not None:
            if action_override is not None:
                req_kind = action_override
            elif getattr(active_entity, "is_memosprite", False):
                req_kind = ActionKind.SKILL
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
            for rh in getattr(active_entity, "relic_handlers", []):
                rh.on_action_before(ctx)
            active_entity.kit.execute(ctx)
            if getattr(active_entity, "light_cone", None) is not None:
                active_entity.light_cone.on_action_after(ctx)
            for rh in getattr(active_entity, "relic_handlers", []):
                rh.on_action_after(ctx)
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
        """检查指定角色当前是否满足终结技施放条件 (通过 Kit 协议解耦)。"""
        ent = self.get_entity(actor_id)
        if not ent or getattr(ent, "kit", None) is None:
            return False
        if hasattr(ent.kit, "can_cast_ultimate"):
            return ent.kit.can_cast_ultimate(ent)
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

        # 校验并消耗能量 / 特殊机制 (通过 Kit 协议解耦)
        if hasattr(ent.kit, "consume_ultimate_cost"):
            if not ent.kit.consume_ultimate_cost(ent):
                return False
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
        for rh in getattr(ent, "relic_handlers", []):
            rh.on_action_before(ctx)
        ent.kit.execute(ctx)
        if getattr(ent, "light_cone", None) is not None:
            ent.light_cone.on_action_after(ctx)
        for rh in getattr(ent, "relic_handlers", []):
            rh.on_action_after(ctx)
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

    def get_turn_action_info(self) -> Dict[str, Any]:
        """获取当前决策窗口的核心信息：
        - 当前行动值 (AV) 与轮次 (Cycle)
        - 目前是谁的回合 (Current Actor)
        - 当前行动者可行动的 Action (Available Actions for Current Actor)
        - 全队就绪可抢断插队的终结技 (Ready Ultimates)
        """
        actor = self.current_turn_entity
        if actor is None:
            alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
            if alive:
                actor = min(alive, key=lambda e: (round(e.remaining_av, 4), 0 if getattr(e, "is_memosprite", False) else 1))
                av = self.current_av + (actor.remaining_av if actor else 0.0)
            else:
                actor = None
                av = self.current_av
        else:
            av = self.current_av

        actor_name = actor.name if actor else "无"
        is_memosprite = getattr(actor, "is_memosprite", False)
        if is_memosprite:
            actor_type = "伴生忆灵"
        elif actor and actor.is_enemy:
            actor_type = "敌方目标"
        else:
            actor_type = "我方角色"

        actions = []
        if actor and getattr(actor, "kit", None) is not None:
            for kind in (ActionKind.SKILL, ActionKind.BASIC):
                try:
                    defn = actor.kit.definition(kind)
                    if defn:
                        if any(a["name"] == defn.name for a in actions):
                            continue
                        sp_cost = getattr(defn.cost, "sp", 0)
                        can_afford = (sp_cost <= 0) or self.sp.can_consume(sp_cost)
                        
                        target_desc = "敌方单体"
                        if hasattr(defn, "target_mode"):
                            from .actions import TargetMode
                            tm = defn.target_mode
                            target_map = {
                                TargetMode.SELF: "自身",
                                TargetMode.SINGLE_ALLY: "我方单体",
                                TargetMode.ALL_ALLIES: "我方全体",
                                TargetMode.SINGLE_ENEMY: "敌方单体",
                                TargetMode.ALL_ENEMIES: "敌方全体",
                                TargetMode.BLAST: "扩散"
                            }
                            target_desc = target_map.get(tm, "敌方单体")

                        if is_memosprite:
                            tag = "终极爆发" if "迷梦" in defn.name else "忆灵技"
                        elif kind == ActionKind.SKILL:
                            tag = "战技"
                        else:
                            tag = "普攻"

                        actions.append({
                            "kind": kind.name,
                            "name": defn.name,
                            "cost_sp": sp_cost,
                            "available": can_afford,
                            "target": target_desc,
                            "tag": tag
                        })
                except Exception:
                    pass
        elif actor:
            actions.append({
                "kind": "NORMAL",
                "name": "敌方行动" if actor.is_enemy else "普通行动",
                "cost_sp": 0,
                "available": True,
                "target": "我方" if actor.is_enemy else "敌方",
                "tag": "行动"
            })

        ready_ults = []
        for u in self.get_ready_ultimates():
            u_defn = u.kit.definition(ActionKind.ULTIMATE) if getattr(u, "kit", None) else None
            u_name = u_defn.name if u_defn else "终结技"
            e_raw = u.kit.get_energy_display(u) if (getattr(u, "kit", None) and hasattr(u.kit, "get_energy_display")) else f"{u.energy:.0f}/{u.max_energy:.0f}"
            e_desc = e_raw.replace("能量:", "").replace("能量", "").strip()
            ready_ults.append({
                "name": u.name,
                "action_name": u_name,
                "energy": e_desc,
                "is_current_actor": (u.name == actor_name)
            })

        return {
            "av": round(av, 2),
            "cycle": self.current_cycle,
            "current_actor": actor_name,
            "actor_type": actor_type,
            "is_memosprite": is_memosprite,
            "actions": actions,
            "ready_ultimates": ready_ults,
            "sp": {"current": self.sp.current_sp, "max": self.sp.max_sp}
        }

    def print_turn_action_info(self) -> None:
        """格式化输出当前回合行动信息，供脚本演算与实时查看。"""
        import sys
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        info = self.get_turn_action_info()
        print("=" * 70)
        print(f"[行动时钟]: {info['av']:.1f} AV (第 {info['cycle']} 轮) | 战技点: {info['sp']['current']}/{info['sp']['max']}")
        print(f"[目前是谁的回合]: 【{info['current_actor']}】 ({info['actor_type']})")
        print("-" * 70)
        print("[本回合可行动的 Action]:")
        for idx, act in enumerate(info['actions'], 1):
            avail_tag = "[可施放]" if act['available'] else "[战技点不足]"
            sp_tag = f"消耗 {act['cost_sp']} SP" if act['cost_sp'] > 0 else "无消耗"
            print(f"  [{idx}] 【{act['tag']}】《{act['name']}》 ({sp_tag} | 目标: {act['target']} | {avail_tag})")
        if info['ready_ultimates']:
            print("\n[当前可抢断插队的终结技 (Ready Ultimates)]:")
            for idx, ult in enumerate(info['ready_ultimates'], 1):
                self_tag = " (当前行动者)" if ult['is_current_actor'] else ""
                print(f"  [U{idx}] 【{ult['name']}】 · 《{ult['action_name']}》 (能量: {ult['energy']} [就绪!]){self_tag}")
        else:
            print("\n[当前可抢断插队的终结技]: 暂无角色就绪")
        print("=" * 70)

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
        memosprites = {}

        for e in self.entities:
            snap = self.status_mgr.get_detailed_snapshot(e)
            if e.is_enemy:
                enemies[e.name] = snap
            else:
                team[e.name] = snap
            kit = getattr(e, "kit", None)
            if kit and hasattr(kit, "get_memosprite_snapshot"):
                msnap = kit.get_memosprite_snapshot()
                if msnap:
                    memosprites[msnap["name"]] = msnap

        return {
            "meta": meta,
            "team": team,
            "enemies": enemies,
            "memosprites": memosprites
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

        # 1. 精确匹配伴生忆灵 (避免 "长夜" 被子串命中为 "长夜月")
        if "memosprites" in st and query in st["memosprites"]:
            return st["memosprites"][query]

        # 2. 精确匹配队伍角色名
        for name, data in st["team"].items():
            if query == name:
                return data

        # 3. 精确匹配敌方单位名
        for name, data in st["enemies"].items():
            if query == name:
                return data

        # 4. 模糊匹配伴生忆灵
        for m_name, m_data in st.get("memosprites", {}).items():
            if query.lower() in m_name.lower():
                return m_data

        # 5. 模糊匹配队伍角色名
        for name, data in st["team"].items():
            if query.lower() in name.lower():
                return data

        # 6. 模糊匹配敌方单位名
        for name, data in st["enemies"].items():
            if query.lower() in name.lower():
                return data

        # 点号分段遍历
        parts = query.split(".")
        # 支持以角色名、怪物名或忆灵名开头点号访问，例如 "长夜月.current_atk" 或 "长夜.current_hp"
        first_part = parts[0]
        curr_root = None
        all_targets = {**st["team"], **st["enemies"], **st.get("memosprites", {})}
        for name, data in all_targets.items():
            if first_part == name:
                curr_root = data
                parts = parts[1:]
                break
        if curr_root is None:
            for name, data in all_targets.items():
                if first_part.lower() in name.lower():
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

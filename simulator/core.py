"""星穹铁道核心战斗跑条调度微内核 (TurnSimulator Microkernel)。

职责边界（轻量化拆分后）：
- `simulator/core.py`: 仅保留 `TurnSimulator` 跑条推进、回合执行、大招抢断与生命周期编排（~330 行）；
- `simulator/entity.py`: 抽离 `Entity` 战斗实体模型与动态属性只读计算属性；
- `simulator/combat_port.py`: 抽离 `CombatPort` 契约与 `SimulatorCombatPort` 桥接适配器；
- `simulator/inspector.py`: 抽离 `BattleInspector` 状态快照与 `query_status` 查询引擎。
（注：在 `core.py` 中重导出了 `Entity` 与 `SimulatorCombatPort`，确保外部 100% 向后兼容）。
"""
from typing import List, Optional, Dict, Any, Tuple

from .entity import Entity
from .combat_port import CombatPort, BuffSpec, SimulatorCombatPort
from .inspector import BattleInspector
from .events import (
    EventBus, BattleEvent, TurnBeginEvent, TurnEndEvent, ActionExecuteEvent, 
    ToughnessRecoverEvent, TechniqueExecuteEvent
)
from .effects import (
    EffectResolver, ModifySPEffect, InterruptActionEffect, ApplyDamageEffect, DamageRequest
)
from .sp import SkillPointManager
from .status import StatusManager, StatType
from .actions import ActionKind, ActionContext


class TurnSimulator:
    """纯粹的回合与行动值 (AV) 调度微内核。"""

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
        self.inspector: BattleInspector = BattleInspector(self)
        self.auto_ult: bool = auto_ult
        self._current_turn_entity: Optional[Entity] = None
        self.stage_mechanics: List[str] = list(stage_mechanics or [])
        from .stage_mechanics import StageMechanicRegistry, StageMechanicPlugin
        self.stage_plugins: List[StageMechanicPlugin] = [
            StageMechanicRegistry.create(m) for m in (stage_mechanics or [])
        ]

        # 注册事件总线转发至各实体挂载的技能套件、光锥与遗器
        def _forward_event_to_handlers(evt: BattleEvent):
            for ent in list(self.entities):
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
                if getattr(e, "kit", None) and hasattr(e.kit, "get_initial_sp_cap"):
                    sp_cap = e.kit.get_initial_sp_cap()
                    if sp_cap:
                        self.port.set_sp_cap(sp_cap)

            # 1. 战前秘技 (Techniques 在入场前按 priority 排序生效)
            if use_techniques:
                target_users = list(technique_users or [e.name for e in self.entities if not e.is_enemy])
                def _tech_order(uid):
                    ent = self._get_entity(uid)
                    if ent and getattr(ent, "kit", None):
                        try:
                            d = ent.kit.definition(ActionKind.TECHNIQUE)
                            if d:
                                return getattr(d, "priority", 1)
                        except Exception:
                            pass
                    return 1
                target_users = sorted(target_users, key=_tech_order)
                for user_id in target_users:
                    self.use_technique(user_id)
            elif technique_users:
                for user_id in technique_users:
                    self.use_technique(user_id)

            # 2. 关卡环境机制插件初始化 (Stage Mechanics Plugins)
            for plugin in self.stage_plugins:
                plugin.on_battle_start(self)

            # 3. 战斗开始被动与光环 (on_battle_start)
            for e in list(self.entities):
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
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not alive:
            return None
        return min(alive, key=lambda e: e.remaining_av)

    def get_action_order(self) -> List[Entity]:
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        return sorted(alive, key=lambda e: e.remaining_av)

    @property
    def current_turn_entity(self) -> Optional[Entity]:
        return self._current_turn_entity

    def advance_to_next_turn(self) -> Optional[Entity]:
        """将跑道推进至最快到达终点的实体 (0.0 AV)，结算【回合开始】状态时钟并发布 TurnBeginEvent。"""
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not alive:
            return None

        active_entity = min(alive, key=lambda e: (round(e.remaining_av, 4), 0 if getattr(e, "is_memosprite", False) else 1))
        delta_av = active_entity.remaining_av

        if delta_av > 0:
            for entity in self.entities:
                travel_distance = entity.speed * delta_av
                entity.distance_remaining = max(0.0, entity.distance_remaining - travel_distance)
            self.current_av += delta_av

        self.status_mgr.tick_on_turn_begin(active_entity)

        for plugin in getattr(self, "stage_plugins", []):
            plugin.on_turn_begin(active_entity, self)

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

        intent = active_entity.get_next_action_intent()
        if getattr(active_entity, "kit", None) is not None:
            if action_override is not None:
                req_kind = action_override
            elif getattr(active_entity, "is_memosprite", False):
                req_kind = ActionKind.SKILL
            else:
                req_kind = ActionKind.SKILL if intent == "E" else ActionKind.BASIC
            defn = active_entity.kit.definition(req_kind)

            if defn.cost.sp > 0 and not self.sp.can_consume(defn.cost.sp):
                actual_kind = ActionKind.BASIC
                defn = active_entity.kit.definition(actual_kind)
                actual_action = f"{defn.name} (SP不足降级)"
            else:
                actual_kind = req_kind
                actual_action = defn.name

            if defn.cost.sp != 0:
                self.resolver.enqueue(ModifySPEffect(active_entity.name, -defn.cost.sp, f"施放{defn.name}"))

            active_entity.advance_policy()

            self.event_bus.publish(ActionExecuteEvent(
                av=round(self.current_av, 2),
                cycle=self.current_cycle,
                actor_id=active_entity.name,
                actor_name=active_entity.name,
                action_type=actual_action,
                description=f"施放【{defn.name}】",
                action_kind=actual_kind
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
                    req = DamageRequest(attacker=active_entity, target=target, skill_multiplier=1.2)
                    self.resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
                    self.port.gain_energy(target.name, 10.0)

        self.resolver.resolve_all()

        if self.auto_ult:
            self.check_and_cast_ultimates()

        self.status_mgr.tick_on_turn_end(active_entity)

        if active_entity.is_broken:
            active_entity.is_broken = False
            active_entity.current_toughness = active_entity.max_toughness
            self.event_bus.publish(ToughnessRecoverEvent(
                av=round(self.current_av, 2),
                cycle=self.current_cycle,
                target_name=active_entity.name,
                max_toughness=active_entity.max_toughness
            ))

        self.event_bus.publish(TurnEndEvent(
            av=round(self.current_av, 2),
            cycle=self.current_cycle,
            actor_id=active_entity.name,
            actor_name=active_entity.name
        ))
        active_entity.reset_distance()
        self._current_turn_entity = None
        return active_entity

    def is_current_turn_auto(self) -> bool:
        """判断当前准备行动的实体动作是否为全自动非交互式动作 (如长夜开局由天赋拉条的自动喷水《追忆，蹁跹，如雨》)。"""
        info = self.inspector.get_turn_action_info()
        actions = info.get("actions", [])
        return len(actions) > 0 and all(a.get("is_auto", False) for a in actions)

    def advance_to_interactive_turn(self, max_auto_steps: int = 10) -> Optional[Entity]:
        """自动顺次执行所有全自动非交互式动作，直接推进并停在第一个真正需要玩家手动操作决策的回合。"""
        for _ in range(max_auto_steps):
            if self.is_current_turn_auto():
                self.step()
            else:
                break
        return self._current_turn_entity or self.advance_to_next_turn()

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
        ent = self.get_entity(actor_id)
        if not ent or getattr(ent, "kit", None) is None:
            return False
        if hasattr(ent.kit, "can_cast_ultimate"):
            return ent.kit.can_cast_ultimate(ent)
        return ent.max_energy > 0 and ent.energy >= ent.max_energy

    def get_ready_ultimates(self) -> List[Entity]:
        return [e for e in self.entities if not e.is_enemy and self.can_cast_ultimate(e.name)]

    def cast_ultimate(self, actor_id: str, target_ids: Optional[Tuple[str, ...]] = None) -> bool:
        ent = self.get_entity(actor_id)
        if not ent or getattr(ent, "kit", None) is None:
            return False

        try:
            defn = ent.kit.definition(ActionKind.ULTIMATE)
        except Exception:
            return False

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
            description=f"【{ent.name}】能量充盈，抢断插入终结技【{defn.name}】！",
            action_kind=ActionKind.ULTIMATE
        ))

        ctx = ActionContext(
            action_id=f"{ent.name}_ult_{self.current_av:.1f}",
            actor_id=ent.name,
            kind=ActionKind.ULTIMATE,
            target_ids=target_ids if target_ids is not None else (),
            is_natural_turn_action=False
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
            alive_allies = [e for e in self.entities if not e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
            alive_enemies = [e for e in self.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
            if not alive_allies or not alive_enemies:
                break
            next_av = min(self.entities, key=lambda e: e.remaining_av).remaining_av
            if self.current_av + next_av > max_av:
                break
            actor = self.step()
            yield actor

    # --- 状态快照与查询委托接口 (由 BattleInspector 提供实现) ---
    def get_turn_action_info(self) -> Dict[str, Any]:
        return self.inspector.get_turn_action_info()

    def print_turn_action_info(self) -> None:
        self.inspector.print_turn_action_info()

    def get_battle_status(self) -> Dict[str, Any]:
        return self.inspector.get_battle_status()

    @property
    def status(self) -> Dict[str, Any]:
        return self.inspector.get_battle_status()

    def query_status(self, query: str = "") -> Any:
        return self.inspector.query_status(query)


__all__ = ["TurnSimulator", "Entity", "SimulatorCombatPort"]

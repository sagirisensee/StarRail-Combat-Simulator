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


# 官方 skill_config_id 的槽位规则: avatar_id * 100 + 槽位 (普攻 01 / 战技 02 / 终结技 03 / 天赋 04 / 秘技 07)
_SKILL_ID_SLOTS = {
    ActionKind.BASIC: 1,
    ActionKind.SKILL: 2,
    ActionKind.ULTIMATE: 3,
    ActionKind.TALENT: 4,
    ActionKind.TECHNIQUE: 7,
}


def resolve_skill_config_id(entity: Any, defn: Any, kind: Any) -> int:
    """解析一次施放的官方 skill_config_id: 技能定义显式声明优先, 否则按角色 avatar_id 与槽位推导。

    忆灵技等不在槽位表内的动作返回 0, 须由忆灵 Kit 在 AbilityDefinition 中显式声明 skill_id。
    """
    declared = getattr(defn, "skill_id", 0) if defn is not None else 0
    if declared:
        return int(declared)
    avatar_id = getattr(entity, "avatar_id", 0) or 0
    slot = _SKILL_ID_SLOTS.get(kind)
    if avatar_id and slot:
        return int(avatar_id) * 100 + slot
    return 0


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
        from .tracer import ActionCausalTracer
        self.tracer: ActionCausalTracer = ActionCausalTracer(self)
        self.auto_ult: bool = auto_ult
        self._current_turn_entity: Optional[Entity] = None
        # 行动就绪队列 (Ready Queue): 存放当前 AV 到达终点 (距离为 0) 的待行动实体
        # 1. 自然跑条到达终点者按自然速度序追加至队尾 (append);
        # 2. 拉条至 0 (包含 100% 拉条) 者插队至队首 (insert(0));
        # 3. 若有连续拉条 100%，最晚拉条者插在最前面 (后拉条优先出手)。
        self._ready_queue: List[str] = []
        self.stage_mechanics: List[str] = list(stage_mechanics or [])
        from .stage_mechanics import StageMechanicRegistry, StageMechanicPlugin
        self.stage_plugins: List[StageMechanicPlugin] = [
            StageMechanicRegistry.create(m) for m in (stage_mechanics or [])
        ]
        self.battle_started: bool = False
        self._in_technique_phase: bool = False

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
            self._in_technique_phase = True
            try:
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
            finally:
                self._in_technique_phase = False

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

            # 4. 战斗开局根据全队秘技与进场光环对满血角色生命值进行上限初始化对齐 (满血进场)
            for e in list(self.entities):
                if not e.is_enemy:
                    base_m = getattr(e, "max_hp", 0.0)
                    if base_m > 0 and e.current_hp >= base_m:
                        max_hp_val = self.port.max_hp(e.name)
                        if max_hp_val and max_hp_val > 0 and max_hp_val != float("inf"):
                            e.current_hp = max_hp_val

        self.battle_started = True

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
        if not alive:
            return []
        current = self._current_turn_entity
        alive_names = {e.name for e in alive}
        self._ready_queue = [name for name in self._ready_queue if name in alive_names]
        if not self._ready_queue and not current:
            self._scan_due_turns(alive)

        queued_rank = {name: i for i, name in enumerate(self._ready_queue)}
        def sort_key(e: Entity):
            is_current = 0 if (current and e.name == current.name) else 1
            if e.name in queued_rank:
                return (is_current, 0, queued_rank[e.name], 0.0)
            return (is_current, 1, 0, round(e.remaining_av, 4))
        return sorted(alive, key=sort_key)

    @property
    def current_turn_entity(self) -> Optional[Entity]:
        return self._current_turn_entity

    # --- 行动就绪队列 (Ready Queue - 基于纯拉条机制) ---
    def notify_entity_ready(self, entity_name: str) -> None:
        """当实体通过拉条使剩余距离降至 0 时触发:
        新拉条者插在就绪队列最前端 (最晚被拉条 100% 的实体优先出手)。
        """
        ent = self.get_entity(entity_name)
        if ent is None or (ent.current_hp <= 0 and not getattr(ent, "is_infinite_hp", False)):
            return
        if entity_name in self._ready_queue:
            self._ready_queue.remove(entity_name)
        self._ready_queue.insert(0, entity_name)

    def request_immediate_action(self, entity_name: str) -> None:
        """请求立即行动（统一按 100% 拉条机制处理）。"""
        self.port.advance(entity_name, entity_name, 1.0)

    def cancel_immediate_action(self, entity_name: str) -> None:
        """撤销某实体待服务的立即行动/拉条 (如对账驱动已直接补发该次施放)。"""
        self._ready_queue = [name for name in self._ready_queue if name != entity_name]
        ent = self.get_entity(entity_name)
        if ent:
            ent.distance_remaining = 10000.0

    def _scan_due_turns(self, alive: List[Entity]) -> None:
        """扫描已自然到达终点 (remaining_av <= 0) 的实体并入队。"""
        current_name = self._current_turn_entity.name if self._current_turn_entity is not None else None
        due = [
            e for e in alive
            if e.name != current_name
            and round(e.remaining_av, 4) <= 0.0
            and e.name not in self._ready_queue
        ]
        if not due:
            return
        due.sort(key=lambda e: (round(e.remaining_av, 4), -e.speed))
        for e in due:
            self._ready_queue.append(e.name)

    def advance_clock(self, delta_av: float) -> None:
        """仅推进时钟与全体跑道距离, 不服务任何行动。

        供需要在步进中点精确落点中断事件的调用方使用 (如对账驱动在某次
        步进的旅行区间内放行到点终结技): 距离按各自速度同比缩减, 到达
        终点者在下一次服务时由 due 扫描入队。
        """
        if delta_av <= 0:
            return
        for entity in self.entities:
            entity.distance_remaining = max(0.0, entity.distance_remaining - entity.speed * delta_av)
        self.current_av += delta_av

    def peek_landing_av(self) -> float:
        """预览下一次行动服务将落点的 AV: 当前回合进行中或就绪队列非空时
        即当前 AV (服务不产生旅行), 否则为推进到最近终点后的 AV。"""
        if self._current_turn_entity is not None:
            return self.current_av
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not alive:
            return self.current_av
        alive_names = {e.name for e in alive}
        self._ready_queue = [name for name in self._ready_queue if name in alive_names]
        if not self._ready_queue:
            self._scan_due_turns(alive)
        if self._ready_queue:
            return self.current_av
        return self.current_av + min(e.remaining_av for e in alive)

    def peek_next_actor(self) -> Optional[Entity]:
        """预览下一行动者: 当前回合进行中则为当前实体; 否则为就绪队首; 队列为空时为距离最近的存活实体。"""
        if self._current_turn_entity is not None:
            return self._current_turn_entity
        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not alive:
            return None
        alive_names = {e.name for e in alive}
        self._ready_queue = [name for name in self._ready_queue if name in alive_names]
        if not self._ready_queue:
            self._scan_due_turns(alive)
        if self._ready_queue:
            return self.get_entity(self._ready_queue[0])
        return min(alive, key=lambda e: round(e.remaining_av, 4))

    def advance_to_next_turn(self) -> Optional[Entity]:
        """服务行动队列中的下一行动:
        就绪队列非空时从队首取实体服务 (时钟不推进);
        就绪队列为空时推进跑道至最近的终点并入队后服务。
        """
        if self._current_turn_entity is not None:
            return self._current_turn_entity

        alive = [e for e in self.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not alive:
            return None

        alive_names = {e.name for e in alive}
        self._ready_queue = [name for name in self._ready_queue if name in alive_names]

        # 始终扫描已就绪 (remaining_av <= 0) 的存活实体补充到队列末尾
        self._scan_due_turns(alive)

        # 若队列仍为空，推进时钟直至下一个实体自然到达终点
        if not self._ready_queue:
            delta_av = min(e.remaining_av for e in alive)
            if delta_av > 0:
                for entity in self.entities:
                    travel_distance = entity.speed * delta_av
                    entity.distance_remaining = max(0.0, entity.distance_remaining - travel_distance)
                self.current_av += delta_av
            self._scan_due_turns(alive)

        if not self._ready_queue:
            return None

        next_name = self._ready_queue.pop(0)
        active_entity = self.get_entity(next_name)
        if active_entity is None:
            return None

        self.status_mgr.tick_on_turn_begin(active_entity)
        self.event_bus.publish(TurnBeginEvent(
            av=round(self.current_av, 2),
            cycle=self.current_cycle,
            actor_id=active_entity.name,
            actor_name=active_entity.name,
            speed=round(active_entity.speed, 1)
        ))
        self.run_stage_turn_begin(active_entity)
        self._current_turn_entity = active_entity
        return active_entity

    def run_stage_turn_begin(self, active_entity: Entity) -> None:
        """结算关卡机制插件的回合开始钩子 (如【血噬】回合初扣血)。

        两类调用: 调度器在 advance_to_next_turn 中对自然回合调用; 回合外强制
        执行的「自身行动」(如忆灵被召唤后的立即行动、由对账驱动补发的忆灵技)
        也须先经此结算, 与自然回合走同一套关卡机制时序——实机中忆灵每次行动
        同样被【血噬】扣血并据此联动 (长夜月天赋按生命降低获得忆质)。
        本方法不发布 TurnBeginEvent、不推进状态持续时钟: 额外行动不是完整回合。
        """
        for plugin in getattr(self, "stage_plugins", []):
            plugin.on_turn_begin(active_entity, self)

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
                action_kind=actual_kind,
                skill_config_id=resolve_skill_config_id(active_entity, defn, actual_kind)
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
                allies = [e for e in self.entities if not e.is_enemy and not getattr(e, "is_countdown", False)]
                if allies:
                    import random
                    target = max(allies, key=lambda a: self.status_mgr.calculate_stat(a.name, 100.0, StatType.AGGRO) + random.uniform(0, 30))
                    req = DamageRequest(attacker=active_entity, target=target, skill_multiplier=1.2)
                    self.resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))

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
        if active_entity.distance_remaining <= 0.0:
            self.notify_entity_ready(active_entity.name)
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
        # 战斗结束判定: 任一方无存活实体时不再推进回合
        # (否则行动方会在空目标列表上执行动作; 波次切换由驱动方在 step 之间完成)
        def _side_alive(is_enemy_side: bool) -> bool:
            return any(
                e.is_enemy == is_enemy_side and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))
                for e in self.entities
            )
        if not _side_alive(True) or not _side_alive(False):
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

        old_e = ent.energy
        if hasattr(ent.kit, "consume_ultimate_cost"):
            if not ent.kit.consume_ultimate_cost(ent):
                return False
        else:
            if ent.max_energy > 0 and ent.energy < ent.max_energy:
                return False
            ent.energy = 0.0

        cost_e = old_e - ent.energy
        if hasattr(self, "tracer") and self.tracer and cost_e > 0:
            self.tracer.record_energy_change(
                entity=ent.name,
                old_val=old_e,
                new_val=ent.energy,
                max_energy=ent.max_energy,
                cause_desc=f"施放终结技《{defn.name}》消耗能量 (-{cost_e:.1f} 点)",
                source_plugin="终结技施放"
            )

        self.event_bus.publish(ActionExecuteEvent(
            av=round(self.current_av, 2),
            cycle=self.current_cycle,
            actor_id=ent.name,
            actor_name=ent.name,
            action_type=f"Ultimate ({defn.name})",
            description=f"【{ent.name}】能量充盈，抢断插入终结技【{defn.name}】！",
            action_kind=ActionKind.ULTIMATE,
            skill_config_id=resolve_skill_config_id(ent, defn, ActionKind.ULTIMATE)
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
            nxt = self.peek_next_actor()
            next_av = nxt.remaining_av if nxt is not None else float("inf")
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

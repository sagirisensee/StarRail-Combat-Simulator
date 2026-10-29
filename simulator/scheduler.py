"""星穹铁道回合外派生动作、追加攻击与五类追加回合统一调度器 (Extra Action, Follow-Up & Extra Turn Scheduler).

核心架构原则 (对齐 Asagi 实测视频 1~3 与 Veritas 官方日志)：
1. 四层派生队列 + 时间轴跑条的五级全局优先级架构：
   - Tier 0 `_immediate_queue` (`IMMEDIATE_EXTRA_TURN = 50`): 即时型追加回合 (如昔涟大招、乱破大招、风堇小伊卡)。
     始终优先于预约动作队列 (`_reserved_queue`)；当 `preempt_follow_up=True` (如昔涟首次大招全队激活) 时甚至抢占 `_followup_queue`，
     默认 `preempt_follow_up=False` (如乱破、风堇小伊卡) 则在 `_followup_queue` 排空后立即抢占 `_reserved_queue` 执行；
   - Tier 1 `_followup_queue` (`FOLLOW_UP = 100`): 真正追加攻击队列。
     同一动作波次内按四段位 (`FAST -> NORMAL循环左移 -> SLOW -> COUNTER`) 排序，跨波次严格 FIFO；
   - Tier 2 `_reserved_queue` (`ULTIMATE = 150`, `AUTO_SKILL = 200`, `ELATION_SKILL = 300`, `RESERVED_EXTRA_TURN = 350`):
     统一预约动作队列。将预约终结技、自动战技 (千刃/希儿残血追加/互动陷阱)、自动欢愉技 (阿哈时刻) 与预约型追加回合
     (希儿再现/珍珠/流萤E2/银狼E2) 统一收编至同一条严格 FIFO 队列：
     * 同一介入时点 (同波次) 同时入队时，按 `ULTIMATE -> AUTO_SKILL -> ELATION_SKILL -> RESERVED_EXTRA_TURN` 排序后追加至队尾；
     * 跨介入时点 (`before_hit` 攻击开始 -> `after_hit` 命中后 -> `on_kill` 击杀时) 严格按预约先后顺序 FIFO 执行，绝不跨波次超车；
     * 在连续行动锁定 (`continuous_action_hold=True`, 如 Archer 连续战技回合) 期间，仅检查 `_reserved_queue` 队首元素：
       若队首为 `ULTIMATE` 则允许弹出执行；若队首为非 `ULTIMATE` 动作 (如欢愉技或追加回合)，则队首被冻结阻塞 (`BLOCKED`)，
       排在其后的 `ULTIMATE` 亦被一并锁死，直至连续行动锁定解除后按原 FIFO 顺序依次释放！
   - Tier 3 `_voyage_queue` (`VOYAGE_EXTRA_TURN = 400`): 旅姬小型追加回合队列。
     优先级低于整个 `_reserved_queue` (会被大招与希儿再现等预约动作抢占)，但高于时间轴自然跑条回合。
"""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional, TYPE_CHECKING

from .actions import (
    ActionKind,
    ActionScheduleCategory,
    FollowUpPhase,
    ScheduledActionIntent,
)
from .events import ActionExecuteEvent, ActionEndEvent

if TYPE_CHECKING:
    from .core import TurnSimulator
    from .entity import Entity


MAX_SCHEDULED_ACTIONS_PER_DRAIN = 100

RESERVED_CATEGORY_ORDER = {
    ActionScheduleCategory.ULTIMATE: 1,
    ActionScheduleCategory.AUTO_SKILL: 2,
    ActionScheduleCategory.ELATION_SKILL: 3,
    ActionScheduleCategory.RESERVED_EXTRA_TURN: 4,
}

_EMPTY = "EMPTY"
_BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class DrainResult:
    """单次调度排空结果：记录实际执行动作数与是否因连续行动锁定 (continuous_action_hold) 而挂起阻塞。"""
    executed_count: int
    blocked: bool = False


class ActionScheduler:
    """管理回合外派生动作 (即时追加回合 / 追加攻击 / 统一预约动作队列 / 旅姬追加回合) 的分波收集、排序与级联排空。"""

    def __init__(self, simulator: "TurnSimulator"):
        self.sim = simulator
        self._staging_intents: List[ScheduledActionIntent] = []
        self._immediate_queue: Deque[ScheduledActionIntent] = deque()
        self._followup_queue: Deque[ScheduledActionIntent] = deque()
        self._reserved_queue: Deque[ScheduledActionIntent] = deque()
        self._voyage_queue: Deque[ScheduledActionIntent] = deque()
        self._seq_counter: int = 0
        self._draining: bool = False
        self._action_frame_depth: int = 0
        self._hold_depth: int = 0
        self.active_intent: Optional[ScheduledActionIntent] = None
        self.last_drain_blocked: bool = False
        self.last_drain_result: DrainResult = DrainResult(0, False)

    @property
    def continuous_action_hold(self) -> bool:
        """当前是否处于连续行动锁定状态 (如 Archer 灵子回路连接连续施放战技期间)。"""
        return self._hold_depth > 0

    @continuous_action_hold.setter
    def continuous_action_hold(self, value: bool) -> None:
        self._hold_depth = 1 if value else 0

    def acquire_continuous_action_hold(self) -> None:
        """开启或加深连续行动锁定。"""
        self._hold_depth += 1

    def release_continuous_action_hold(self) -> None:
        """解除一层连续行动锁定。"""
        self._hold_depth = max(0, self._hold_depth - 1)

    @contextmanager
    def hold_continuous_action(self):
        """在上下文内保持连续行动锁定 (`continuous_action_hold=True`)。"""
        self.acquire_continuous_action_hold()
        try:
            yield
        finally:
            self.release_continuous_action_hold()

    @contextmanager
    def action_frame(self):
        """标记一个原子动作执行帧 (如自然回合主动作、追加回合动作或终结技)，帧内不发生半途插队。"""
        self._action_frame_depth += 1
        try:
            yield
        finally:
            self._action_frame_depth = max(0, self._action_frame_depth - 1)

    def can_auto_drain(self) -> bool:
        """当不处于原子动作帧内且未在 drain 循环中时，允许 EffectResolver.resolve_all() 自动触发排空。"""
        return self._action_frame_depth == 0 and not self._draining

    def has_pending(self) -> bool:
        return bool(
            self._staging_intents
            or self._immediate_queue
            or self._followup_queue
            or self._reserved_queue
            or self._voyage_queue
        )

    def has_executable_pending(self) -> bool:
        """判断当前是否存在未被 continuous_action_hold 锁死的可执行派生动作。"""
        if self._staging_intents or self._immediate_queue or self._followup_queue:
            return True
        if self._reserved_queue:
            if not self.continuous_action_hold:
                return True
            return self._reserved_queue[0].category == ActionScheduleCategory.ULTIMATE
        if self._voyage_queue and not self.continuous_action_hold:
            return True
        return False

    def has_pending_ultimate(self, actor_id: str) -> bool:
        """检查指定角色是否已在暂存波次或预约队列中挂起了终结技。"""
        ent = self.sim.get_entity(actor_id)
        resolved = ent.name if ent is not None else actor_id
        for intent in self._staging_intents:
            if intent.category == ActionScheduleCategory.ULTIMATE and intent.actor_id == resolved:
                return True
        for intent in self._reserved_queue:
            if intent.category == ActionScheduleCategory.ULTIMATE and intent.actor_id == resolved:
                return True
        return False

    def _party_slot(self, actor_id: str) -> int:
        for idx, ent in enumerate(self.sim.entities):
            if ent.name == actor_id or str(getattr(ent, "avatar_id", "")) == str(actor_id):
                return idx
        return 999

    def resolve_entity_phase(self, entity: Optional["Entity"]) -> Optional[FollowUpPhase]:
        """解析某我方实体的追加攻击分组 (FollowUpPhase)。若该实体不具备追加攻击机制则返回 None。"""
        if entity is None or getattr(entity, "is_enemy", False) or getattr(entity, "is_countdown", False):
            return None
        explicit_ent_phase = getattr(entity, "follow_up_phase", None)
        if isinstance(explicit_ent_phase, FollowUpPhase):
            return explicit_ent_phase

        kit = getattr(entity, "kit", None)
        if kit is not None:
            explicit_kit_phase = getattr(kit, "follow_up_phase", None)
            if isinstance(explicit_kit_phase, FollowUpPhase):
                return explicit_kit_phase
            try:
                defn = kit.definition(ActionKind.FOLLOW_UP)
                if defn is not None:
                    return FollowUpPhase.NORMAL
            except Exception:
                pass
        return None

    def get_normal_group_candidates(self, current_wave_normal_actors: Optional[set] = None) -> List[str]:
        """按编队站位顺序获取全场属于常规追击组 (`FollowUpPhase.NORMAL`) 的存活我方实体名称列表。"""
        wave_actors = current_wave_normal_actors or set()
        candidates: List[str] = []
        for ent in self.sim.entities:
            if getattr(ent, "is_enemy", False) or getattr(ent, "is_countdown", False):
                continue
            if getattr(ent, "current_hp", 0.0) <= 0 and not getattr(ent, "is_infinite_hp", False):
                continue
            phase = self.resolve_entity_phase(ent)
            if phase == FollowUpPhase.NORMAL or (phase is None and ent.name in wave_actors):
                candidates.append(ent.name)
        return candidates

    def get_normal_group_shifted_order(self, current_wave_normal_actors: Optional[set] = None) -> List[str]:
        """计算常规追击组循环左移后的先后顺位 (`candidates[1:] + candidates[:1]`)。"""
        candidates = self.get_normal_group_candidates(current_wave_normal_actors)
        if len(candidates) <= 1:
            return candidates
        return candidates[1:] + candidates[:1]

    def enqueue(
        self,
        actor_id: str,
        callback: Callable[[], None],
        *,
        name: str = "",
        category: ActionScheduleCategory = ActionScheduleCategory.FOLLOW_UP,
        phase: Optional[FollowUpPhase] = None,
        action_kind: Optional[ActionKind] = None,
        skill_id: int = 0,
        publish_execute_event: bool = True,
        preempt_follow_up: bool = False,
    ) -> ScheduledActionIntent:
        """将一个派生动作意图挂入当前介入波次的暂存列表 (`_staging_intents`)。"""
        ent = self.sim.get_entity(actor_id)
        resolved_actor_id = ent.name if ent is not None else actor_id

        if phase is None:
            ent_phase = self.resolve_entity_phase(ent)
            resolved_phase = ent_phase if ent_phase is not None else FollowUpPhase.NORMAL
        else:
            resolved_phase = phase

        if action_kind is None:
            if category == ActionScheduleCategory.FOLLOW_UP:
                resolved_kind = ActionKind.FOLLOW_UP
            elif category == ActionScheduleCategory.ULTIMATE:
                resolved_kind = ActionKind.ULTIMATE
            elif category == ActionScheduleCategory.AUTO_SKILL:
                resolved_kind = ActionKind.SKILL
            elif category == ActionScheduleCategory.ELATION_SKILL:
                resolved_kind = ActionKind.ELATION_SKILL
            elif category in (
                ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                ActionScheduleCategory.RESERVED_EXTRA_TURN,
                ActionScheduleCategory.VOYAGE_EXTRA_TURN,
            ):
                resolved_kind = ActionKind.SKILL
            else:
                resolved_kind = ActionKind.FOLLOW_UP
        else:
            resolved_kind = action_kind

        cur_turn_ent = getattr(self.sim, "_current_turn_entity", None)
        owner_turn_actor = cur_turn_ent.name if cur_turn_ent is not None else None
        owner_turn_id = getattr(self.sim, "_turn_id", None)

        self._seq_counter += 1
        intent = ScheduledActionIntent(
            actor_id=resolved_actor_id,
            callback=callback,
            name=name or (
                "FollowUpAttack"
                if resolved_kind == ActionKind.FOLLOW_UP
                else resolved_kind.name
            ),
            category=category,
            phase=resolved_phase,
            action_kind=resolved_kind,
            skill_id=skill_id,
            enqueue_seq=self._seq_counter,
            publish_execute_event=publish_execute_event,
            preempt_follow_up=preempt_follow_up,
            owner_turn_id=owner_turn_id,
            owner_turn_actor_id=owner_turn_actor,
        )
        self._staging_intents.append(intent)
        return intent

    def commit_reserved_wave(self) -> None:
        """将当前介入点 (如 `before_hit` / `after_hit` / `on_kill`) 暂存的非追击意图提交至各自队列尾部，
        同时保留 `FOLLOW_UP` 意图在 `_staging_intents` 中直至当前动作帧结束统一按追击波次排序。
        """
        if not self._staging_intents:
            return

        remaining_followups: List[ScheduledActionIntent] = []
        immediates: List[ScheduledActionIntent] = []
        reserved: List[ScheduledActionIntent] = []
        voyages: List[ScheduledActionIntent] = []

        for intent in self._staging_intents:
            if intent.category == ActionScheduleCategory.FOLLOW_UP:
                remaining_followups.append(intent)
            elif intent.category == ActionScheduleCategory.IMMEDIATE_EXTRA_TURN:
                immediates.append(intent)
            elif intent.category in RESERVED_CATEGORY_ORDER:
                reserved.append(intent)
            elif intent.category == ActionScheduleCategory.VOYAGE_EXTRA_TURN:
                voyages.append(intent)
            else:
                reserved.append(intent)

        self._staging_intents = remaining_followups

        if immediates:
            immediates.sort(key=lambda i: (0 if i.preempt_follow_up else 1, i.enqueue_seq))
            self._immediate_queue.extend(immediates)

        if reserved:
            def _reserved_sort_key(intent: ScheduledActionIntent):
                cat_rank = RESERVED_CATEGORY_ORDER.get(intent.category, 99)
                if intent.category == ActionScheduleCategory.ULTIMATE:
                    # 终结技按预约先后顺序 (enqueue_seq) 排列
                    return (cat_rank, intent.enqueue_seq, 0)
                # 同介入波次同时被动触发的 AUTO_SKILL / ELATION_SKILL / RESERVED_EXTRA_TURN 按类别 -> 编队站位 -> 入队序号排列
                return (cat_rank, self._party_slot(intent.actor_id), intent.enqueue_seq)

            reserved.sort(key=_reserved_sort_key)
            self._reserved_queue.extend(reserved)

        if voyages:
            voyages.sort(key=lambda i: (self._party_slot(i.actor_id), i.enqueue_seq))
            self._voyage_queue.extend(voyages)

    def commit_staging_wave(self) -> None:
        """将当前动作边界内收集到的全部暂存意图按实机规则排序，并提交到各自优先级的执行队列尾部。"""
        if not self._staging_intents:
            return

        self.commit_reserved_wave()
        if not self._staging_intents:
            return

        followups = list(self._staging_intents)
        self._staging_intents.clear()

        if followups:
            normal_actors = {
                i.actor_id for i in followups if i.phase == FollowUpPhase.NORMAL
            }
            shifted_normal = self.get_normal_group_shifted_order(normal_actors)
            normal_rank = {name: idx for idx, name in enumerate(shifted_normal)}

            def _fua_sort_key(intent: ScheduledActionIntent):
                if intent.phase == FollowUpPhase.NORMAL:
                    pos_rank = normal_rank.get(intent.actor_id, self._party_slot(intent.actor_id) + 100)
                else:
                    pos_rank = self._party_slot(intent.actor_id)
                return (intent.phase.value, pos_rank, intent.enqueue_seq)

            followups.sort(key=_fua_sort_key)
            self._followup_queue.extend(followups)

    def _is_entity_alive(self, actor_id: str) -> bool:
        ent = self.sim.get_entity(actor_id)
        if ent is None:
            return True
        return getattr(ent, "current_hp", 1.0) > 0 or getattr(ent, "is_infinite_hp", False)

    def _discard_dead_heads(self) -> None:
        """清理各队列队首已阵亡实体的失效动作意图，防止阵亡角色造成死锁阻塞。"""
        for q in (self._immediate_queue, self._followup_queue, self._reserved_queue, self._voyage_queue):
            while q and not self._is_entity_alive(q[0].actor_id):
                q.popleft()

    def _pop_next_intent(self) -> object:
        """按严格四层优先级弹出下一个待执行动作；若被 continuous_action_hold 锁死则返回 `_BLOCKED`，全空返回 `_EMPTY`。"""
        self._discard_dead_heads()

        # 1. Tier 0 (preempt_follow_up=True, 如昔涟首次大招全队激活): 甚至抢占 _followup_queue
        if self._immediate_queue and self._immediate_queue[0].preempt_follow_up:
            return self._immediate_queue.popleft()

        # 2. Tier 1 (_followup_queue): 真正追加攻击队列
        if self._followup_queue:
            return self._followup_queue.popleft()

        # 3. Tier 0 (preempt_follow_up=False, 如乱破大招、风堇小伊卡): _followup_queue 排空后立即抢占 _reserved_queue
        if self._immediate_queue:
            return self._immediate_queue.popleft()

        # 4. Tier 2 (_reserved_queue): 统一预约动作队列 (ULTIMATE / AUTO_SKILL / ELATION_SKILL / RESERVED_EXTRA_TURN)
        if self._reserved_queue:
            head = self._reserved_queue[0]
            if (
                self.continuous_action_hold
                and head.category != ActionScheduleCategory.ULTIMATE
            ):
                return _BLOCKED
            return self._reserved_queue.popleft()

        # 5. Tier 3 (_voyage_queue): 旅姬小型追加回合 (连续行动锁定期间同样挂起等待)
        if self._voyage_queue:
            if self.continuous_action_hold:
                return _BLOCKED
            return self._voyage_queue.popleft()

        return _EMPTY

    def drain_with_status(self) -> DrainResult:
        """级联排空所有可执行派生动作，返回 `DrainResult(executed_count, blocked)`。"""
        if self._draining:
            return DrainResult(0, self.last_drain_blocked)

        self.commit_staging_wave()
        if not self.has_pending():
            self.last_drain_blocked = False
            self.last_drain_result = DrainResult(0, False)
            return self.last_drain_result

        self._draining = True
        executed_count = 0
        blocked = False
        try:
            while True:
                if self._staging_intents:
                    self.commit_staging_wave()

                popped = self._pop_next_intent()
                if popped is _EMPTY:
                    blocked = False
                    break
                if popped is _BLOCKED:
                    blocked = True
                    break

                intent: ScheduledActionIntent = popped  # type: ignore[assignment]
                if not self._is_entity_alive(intent.actor_id):
                    continue

                executed_count += 1
                if executed_count > MAX_SCHEDULED_ACTIONS_PER_DRAIN:
                    raise RuntimeError(
                        f"派生动作调度步数超过上限 ({MAX_SCHEDULED_ACTIONS_PER_DRAIN})，检测到潜在的无限递归追击/追加回合！"
                    )

                prev_intent = self.active_intent
                self.active_intent = intent
                try:
                    with self.action_frame():
                        if intent.publish_execute_event:
                            if intent.category == ActionScheduleCategory.FOLLOW_UP:
                                desc = f"【{intent.actor_id}】触发追加攻击【{intent.name}】"
                            elif intent.category in (
                                ActionScheduleCategory.IMMEDIATE_EXTRA_TURN,
                                ActionScheduleCategory.RESERVED_EXTRA_TURN,
                                ActionScheduleCategory.VOYAGE_EXTRA_TURN,
                            ):
                                desc = f"【{intent.actor_id}】获得追加回合施放【{intent.name}】"
                            else:
                                desc = f"【{intent.actor_id}】自动施放【{intent.name}】"
                            self.sim.event_bus.publish(
                                ActionExecuteEvent(
                                    av=round(getattr(self.sim, "current_av", 0.0), 2),
                                    cycle=getattr(self.sim, "current_cycle", 0),
                                    actor_id=intent.actor_id,
                                    actor_name=intent.actor_id,
                                    action_type=intent.name,
                                    description=desc,
                                    action_kind=intent.action_kind,
                                    skill_config_id=intent.skill_id,
                                )
                            )

                        intent.callback()
                        self.sim.resolver.resolve_all()
                        if intent.publish_execute_event:
                            self.sim.event_bus.publish(
                                ActionEndEvent(
                                    av=round(getattr(self.sim, "current_av", 0.0), 2),
                                    cycle=getattr(self.sim, "current_cycle", 0),
                                    actor_id=intent.actor_id,
                                    actor_name=intent.actor_id,
                                    action_type=intent.name,
                                    action_kind=intent.action_kind,
                                    skill_config_id=intent.skill_id,
                                )
                            )
                finally:
                    self.active_intent = prev_intent

                # 当前派生动作完整结算完毕后，将其诱发的新一波暂存动作立即排序入队，
                # 以便下一轮循环从最高优先级队列重新检查（实现跨级抢占与队列内 FIFO）
                self.commit_staging_wave()
                if getattr(self.sim, "auto_ult", False) and hasattr(self.sim, "enqueue_ready_ultimates"):
                    self.sim.enqueue_ready_ultimates()
                    self.commit_staging_wave()
        finally:
            self._draining = False

        self.last_drain_blocked = blocked
        self.last_drain_result = DrainResult(executed_count=executed_count, blocked=blocked)
        return self.last_drain_result

    def drain(self) -> int:
        """级联排空所有可执行派生动作，返回本次实际执行的动作数量。"""
        return self.drain_with_status().executed_count

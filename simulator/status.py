"""星穹铁道状态 (Buff/Debuff) 与动态属性计算系统。

核心机制（遵从架构师规范）：
1. 状态生命周期时钟 (DurationTiming)：
   - TARGET_TURN_START: 承伤者/目标自身回合开始扣减（如持续伤害 DoT、裂伤等）；
   - TARGET_TURN_END:   目标自身行动结束扣减（常规 Buff，如花火战技暴伤）；
   - CASTER_TURN_END:   施法者自身行动结束扣减（结界类技能，如符玄穷观阵、阮·梅结界）；
2. 属性动态计算流水线 (Modifier Pipeline)：
   - 杜绝直接原地加减数值导致的状态漂移；
   - 每次按 基础属性 + sum(固定值加成) * (1 + sum(百分比加成)) 动态采样。
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Dict, Optional, Any


class DurationTiming(Enum):
    """状态衰减时钟锚点。"""
    TARGET_TURN_START = auto()   # 目标自身回合开始扣减
    TARGET_TURN_END = auto()     # 目标自身回合结束扣减
    CASTER_TURN_END = auto()     # 施法者自身回合结束扣减 (结界时钟)


class StackPolicy(Enum):
    """状态刷新与叠层策略。"""
    REPLACE = auto()             # 覆盖数值、刷新时长
    REFRESH = auto()             # 仅刷新持续时间
    STACK = auto()               # 叠加层数并刷新
    INDEPENDENT = auto()         # 独立多实例


class StatType(Enum):
    """战斗属性枚举。"""
    SPEED = "speed"              # 速度
    ATK_BASE = "atk_base"        # 基础攻击
    ATK_PERCENT = "atk_pct"      # 攻击百分比
    CRIT_RATE = "crit_rate"      # 暴击率
    CRIT_DMG = "crit_dmg"        # 暴击伤害
    DMG_BOOST = "dmg_boost"      # 增伤区
    DEF_SHRED = "def_shred"      # 减防区
    RES_PEN = "res_pen"          # 抗性穿透
    BREAK_EFFECT = "break_effect"# 击破特攻
    BREAK_EFFICIENCY = "break_eff"# 击破效率
    ELATION = "elation"          # 欢愉伤害/度
    DEF_PERCENT = "def_pct"      # 防御力百分比
    MAX_HP_PERCENT = "max_hp_pct"# 生命上限百分比
    EFFECT_RES = "effect_res"    # 效果抵抗


class ModifierOp(Enum):
    ADD = auto()                 # 加算 (如 +12% 暴击率, +10 速度)
    PERCENT = auto()             # 百分比算


@dataclass
class Modifier:
    stat: StatType
    op: ModifierOp
    value: float


@dataclass
class StatusInstance:
    id: str                                  # 唯一标识符，如 "MatrixOfPrescience"
    name: str                                # 展示名称，如 "穷观阵"
    source: Any                              # 施法者 Entity
    target: Any                              # 承载者 Entity
    duration: Optional[int] = 1              # 剩余持续回合数 (None 表示常驻，不自动衰减)
    timing: DurationTiming = DurationTiming.TARGET_TURN_END # 扣减时序
    modifiers: List[Modifier] = field(default_factory=list)
    stacks: int = 1                          # 当前层数
    max_stacks: int = 1                      # 最大层数
    stack_policy: StackPolicy = StackPolicy.REPLACE # 合并策略
    skip_current_clock: bool = False         # 施加当回合是否豁免扣减

    @property
    def is_expired(self) -> bool:
        if self.duration is None:
            return False
        return self.duration <= 0


class StatusManager:
    """全局状态与 Buff 管理器。"""
    def __init__(self, simulator: Any):
        self.simulator = simulator
        # entity_name -> list of StatusInstance
        self.statuses: Dict[str, List[StatusInstance]] = {}

    def get_statuses(self, entity_name: str) -> List[StatusInstance]:
        return self.statuses.get(entity_name, [])

    def get_status(self, entity_name: str, status_id: str) -> Optional[StatusInstance]:
        """获取目标指定 ID 的状态实例。"""
        return next((s for s in self.get_statuses(entity_name) if s.id == status_id), None)

    def add_status(self, status: StatusInstance):
        """向目标添加状态（严格执行 REPLACE/STACK 策略与数值更新）。"""
        target_name = status.target.name
        if target_name not in self.statuses:
            self.statuses[target_name] = []

        existing = next((s for s in self.statuses[target_name] if s.id == status.id), None)
        if existing:
            # 策略分支
            if status.stack_policy == StackPolicy.REPLACE:
                # 覆盖最新数值（如重放战技更新暴伤采样值）
                existing.modifiers = list(status.modifiers)
                existing.duration = status.duration if status.duration is not None else existing.duration
                existing.stacks = min(existing.max_stacks, max(existing.stacks, status.stacks))
                existing.skip_current_clock = status.skip_current_clock
            elif status.stack_policy == StackPolicy.STACK:
                existing.stacks = min(existing.max_stacks, existing.stacks + status.stacks)
                if status.duration is not None:
                    existing.duration = max(existing.duration or 0, status.duration)
            elif status.stack_policy == StackPolicy.REFRESH:
                if status.duration is not None:
                    existing.duration = max(existing.duration or 0, status.duration)
        else:
            self.statuses[target_name].append(status)

    def remove_status(self, target_name: str, status_id: str):
        """显式移除指定状态。"""
        if target_name in self.statuses:
            self.statuses[target_name] = [s for s in self.statuses[target_name] if s.id != status_id]

    def has_status(self, target_name: str, status_id: str) -> bool:
        """检查目标是否持有指定状态。"""
        return any(s.id == status_id for s in self.get_statuses(target_name))

    def tick_on_turn_begin(self, actor: Any):
        """在回合开始时结算 TARGET_TURN_START 类型的状态。"""
        self._tick_and_clean(
            condition=lambda s: s.target.name == actor.name and s.timing == DurationTiming.TARGET_TURN_START,
            actor_name=actor.name,
            phase="回合开始"
        )

    def tick_on_turn_end(self, actor: Any):
        """在回合结束时结算 TARGET_TURN_END 与 CASTER_TURN_END 类型的状态。"""
        # 1. 作为目标自身行动结束
        self._tick_and_clean(
            condition=lambda s: s.target.name == actor.name and s.timing == DurationTiming.TARGET_TURN_END,
            actor_name=actor.name,
            phase="自身行动结束"
        )
        # 2. 作为施法者行动结束（如符玄自身行动结算穷观阵）
        self._tick_and_clean(
            condition=lambda s: s.source.name == actor.name and s.timing == DurationTiming.CASTER_TURN_END,
            actor_name=actor.name,
            phase="施法者行动结束"
        )

    def _tick_and_clean(self, condition, actor_name: str, phase: str):
        from .events import StatusExpireEvent
        bus = self.simulator.event_bus
        av = self.simulator.current_av
        cycle = self.simulator.current_cycle

        for target_name, status_list in list(self.statuses.items()):
            active = []
            for s in status_list:
                if condition(s):
                    # 如果标记了跳过当前生效时钟（如本行动刚刚施加的自身速度Buff）
                    if s.skip_current_clock:
                        s.skip_current_clock = False
                        active.append(s)
                        continue

                    if s.duration is not None:
                        s.duration -= 1
                        if s.duration <= 0:
                            bus.publish(StatusExpireEvent(
                                av=round(av, 2),
                                cycle=cycle,
                                target_name=s.target.name,
                                status_id=s.id,
                                status_name=s.name
                            ))
                            continue
                active.append(s)
            self.statuses[target_name] = active

    def calculate_stat(self, entity_name: str, base_val: float, stat_type: StatType) -> float:
        """动态计算指定属性的加成总值。"""
        flat_sum = 0.0
        pct_sum = 0.0

        for status in self.get_statuses(entity_name):
            for mod in status.modifiers:
                if mod.stat == stat_type:
                    total_mod_val = mod.value * status.stacks
                    if mod.op == ModifierOp.ADD:
                        flat_sum += total_mod_val
                    elif mod.op == ModifierOp.PERCENT:
                        pct_sum += total_mod_val

        return (base_val + flat_sum) * (1.0 + pct_sum)

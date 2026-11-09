"""星穹铁道战斗实体模型 (Combat Entity Model).

职责边界：
- 封装角色、伴生忆灵（召唤物）、敌方首领的静态面板白值与局内资源状态（HP、能量、护盾、韧性条、跑道剩余距离）；
- 提供基于 `StatusManager` 的实时属性只读计算属性（`speed`, `atk`, `defense`, `crit_rate`, `crit_dmg`, `err`, `remaining_av`）；
- 提供纯跑道距离推拉计算（`advance_action`, `delay_action`, `reset_distance`）。
"""
from dataclasses import dataclass, field, InitVar
from typing import Callable, List, Optional, Any, TYPE_CHECKING
from .status import StatType

if TYPE_CHECKING:
    from .effects import EffectResolver
    from .actions import FollowUpPhase


@dataclass
class Entity:
    name: str
    base_speed: float
    base_atk: float = 1000.0
    base_crit_rate: float = 0.05          # 基础 5% 暴击
    base_crit_dmg: float = 0.50           # 基础 50% 暴伤
    # 兼容构造参数位置与签名：max_hp 作为 InitVar 支持位置/关键字传参，实际写入 base_max_hp
    max_hp: InitVar[Optional[float]] = None
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
    # 关联的技能套件 (KitHandler)
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
    is_countdown: bool = False
    # 屏障护体 (如【血脑屏障】展开期间): 受到的真实伤害归零、附加伤害按
    # 25% 结算, 直接伤害不受影响; 由关卡/机制侧按状态切换
    barrier_guarded: bool = False
    # 敌方未击破弱点时的常规韧性减免率 (标准星铁规则为 0.10，承伤 0.90x; 特殊形态首领可配置为 0.0 即 1.00x)
    toughness_dmg_reduction: float = 0.10
    # 是否为关卡头目/首领级实体 (用于自动战斗首领优先规则)
    is_boss: bool = False
    master_name: Optional[str] = None
    extra_immediate_action: bool = False
    # 追加攻击调度分组 (FollowUpPhase.FAST / NORMAL / SLOW / COUNTER; None 表示无追加攻击或由 kit 决定)
    follow_up_phase: Optional["FollowUpPhase"] = None
    # 绑定所属的模拟器引用
    simulator: Optional[Any] = None
    # 动作回调：(actor: Entity, resolver: EffectResolver, action_type: str)
    action_callback: Optional[Callable[["Entity", "EffectResolver", str], None]] = None

    # 底层静态面板白板生命 (放在字段末尾避免破坏现有位置参数签名)
    base_max_hp: float = 10000.0
    _in_max_hp_calc: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self, max_hp: Optional[float]) -> None:
        if max_hp is not None:
            self.base_max_hp = float(max_hp)

    def clamp_hp(self) -> None:
        """上限下降（Buff 移除或过期）后，把当前生命压回上限以内。"""
        cap = self.max_hp
        if self.current_hp > cap:
            self.current_hp = cap

    @property
    def speed(self) -> float:
        """从状态管理器动态计算实时速度，无缝支持速度 Buff/Debuff。"""
        if self.simulator and hasattr(self.simulator, "status_mgr"):
            return max(
                1.0,
                self.simulator.status_mgr.calculate_stat(
                    self.name,
                    self.base_speed,
                    StatType.SPEED,
                    white_base=getattr(self, "base_white_speed", 0.0)
                )
            )
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

    def advance_action(self, percent: float) -> None:
        distance_cut = 10000.0 * percent
        self.distance_remaining = max(0.0, self.distance_remaining - distance_cut)

    def delay_action(self, percent: float) -> None:
        self.distance_remaining += 10000.0 * percent

    def reset_distance(self, base_distance: float = 10000.0) -> None:
        if getattr(self, "extra_immediate_action", False):
            self.distance_remaining = 0.0
            self.extra_immediate_action = False
        elif getattr(self, "custom_reset_distance", None) is not None:
            self.distance_remaining = float(self.custom_reset_distance)
            self.custom_reset_distance = None
        else:
            self.distance_remaining = base_distance

    def get_next_action_intent(self) -> str:
        if not self.policy:
            return "E"
        return self.policy[self.policy_index % len(self.policy)]

    def advance_policy(self) -> None:
        self.policy_index += 1


def _get_max_hp(self: Entity) -> float:
    """实时生命上限：从状态管理器动态采样生命上限修正（含白字基准与百分比/固定值生命加成）。"""
    if getattr(self, "_in_max_hp_calc", False):
        return self.base_max_hp
    if self.base_max_hp == float("inf") or self.base_max_hp <= 0:
        return self.base_max_hp
    if not (self.simulator and hasattr(self.simulator, "status_mgr")):
        return self.base_max_hp

    self._in_max_hp_calc = True
    try:
        white_hp = getattr(self, "base_white_hp", 0.0) or self.base_max_hp
        val = self.simulator.status_mgr.calculate_stat(
            self.name,
            self.base_max_hp,
            StatType.MAX_HP_PERCENT,
            white_base=white_hp,
        )
        return max(1.0, val)
    finally:
        self._in_max_hp_calc = False


def _set_max_hp(self: Entity, value: float) -> None:
    """setter 只写入白板基础生命上限，不固化局内 Buff。"""
    self.base_max_hp = float(value)


# 在 @dataclass 之后挂载 property，确保构造函数签名与 InitVar 完美协同
Entity.max_hp = property(_get_max_hp, _set_max_hp, doc=_get_max_hp.__doc__)  # type: ignore[assignment]

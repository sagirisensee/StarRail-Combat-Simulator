"""角色战斗技能套件基类 (Character Kit Handler Base).

定义了角色技能与天赋的所有标准生命周期与扩展钩子（Extension Hooks）：
- `definition(kind)` / `execute(ctx)`: 技能声明与动作执行（必填）
- `apply_trace_passives(entity)`: 战前常驻行迹/实机面板基线注入
- `get_initial_sp_cap()`: 进战前战技点上限扩展（如花火天赋）
- `on_battle_start()` / `on_battle_end()`: 进战初始化与退场清理
- `on_event(event)`: 订阅全局 `EventBus` 事实事件
- `on_hp_lost(entity_id, actual_loss, cause)`: 实体生命降低回调
- `intercept_incoming_damage(target_id, raw_damage)`: 伤害分摊/减免拦截钩子（如符玄穷观阵）
- `can_cast_ultimate(entity)` / `consume_ultimate_cost(entity)` / `get_energy_display(entity)`: 特殊充能体系扩展（如黄泉残梦）
- `get_memosprite_snapshot()`: 伴生忆灵独立状态透析快照
"""
from abc import ABC, abstractmethod
from typing import Optional, Any
from ..actions import ActionContext, ActionKind, AbilityDefinition
from ..combat_port import CombatPort


class KitHandler(ABC):
    """所有角色技能行为处理器的抽象基类。"""

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        if not 0 <= eidolon <= 6:
            raise ValueError(f"星魂等阶必须在 0 到 6 之间，当前为: {eidolon}")
        self.owner_id = owner_id
        self.port = port
        self.eidolon = eidolon
        self.skill_levels = skill_levels or {}
        self.scaling: Optional[Any] = None

    def bind_scaling(self, scaling: Any) -> None:
        """绑定官方数据驱动的技能等级缩放器。"""
        self.scaling = scaling

    def skill_param(self, skill_key: str, index: int = 0, default: float = 0.0) -> float:
        """获取指定技能在当前星魂/等级下的官方实机数值。"""
        if self.scaling is not None:
            return self.scaling.value(skill_key, index, default)
        return default

    def eidolon_param(self, rank: int, index: int = 0, default: float = 0.0) -> float:
        """获取指定星魂阶数 (1~6) 的第 index 项官方参数。"""
        if self.scaling is not None and hasattr(self.scaling, "eidolon_value"):
            return self.scaling.eidolon_value(rank, index, default)
        return default

    @abstractmethod
    def definition(self, kind: ActionKind) -> AbilityDefinition:
        """声明指定动作类型的目标模式与资源消耗。"""
        pass

    @abstractmethod
    def execute(self, ctx: ActionContext) -> None:
        """执行指定动作的具体战斗逻辑。"""
        pass

    def apply_trace_passives(self, entity: Any) -> None:
        """战前静态阶段：将角色专属行迹被动或实机白字基线注入 Entity。"""
        pass

    def get_initial_sp_cap(self) -> Optional[int]:
        """若角色天赋修改全队战技点上限（如花火），返回新的上限值；否则返回 None。"""
        return None

    def use_technique(self) -> None:
        """执行角色的进战前秘技逻辑。"""
        try:
            defn = self.definition(ActionKind.TECHNIQUE)
            if not defn:
                return
            ctx = ActionContext(
                action_id=f"{self.owner_id}_technique",
                actor_id=self.owner_id,
                kind=ActionKind.TECHNIQUE,
                target_ids=()
            )
            self.execute(ctx)
        except (ValueError, KeyError, NotImplementedError):
            pass

    def on_battle_start(self) -> None:
        """战斗开始时的初始化被动与光环激活。"""
        pass

    def on_battle_end(self) -> None:
        """战斗结束时的清理。"""
        pass

    def on_event(self, event: Any) -> None:
        """响应事件总线发布的事实事件（如友方耗点、治疗、击破、回合切换等）。"""
        pass

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """当场上任意实体损失生命值时触发的回调钩子。"""
        pass

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
        """伤害结算前的分摊/拦截钩子（如符玄穷观阵分摊队友 65% 伤害）。返回分摊后目标实际承受的伤害值。"""
        return raw_damage

    def can_cast_ultimate(self, entity: Any) -> bool:
        """检查是否满足终结技施放条件。通用默认基于能量满槽，特殊机制角色可覆写。"""
        max_energy = getattr(entity, "max_energy", 120.0)
        energy = getattr(entity, "energy", 0.0)
        return max_energy > 0 and energy >= (max_energy - 1e-4)

    def consume_ultimate_cost(self, entity: Any) -> bool:
        """扣除终结技资源消耗。通用默认清空能量，特殊机制角色可覆写。"""
        if not self.can_cast_ultimate(entity):
            return False
        entity.energy = 0.0
        return True

    def get_energy_display(self, entity: Any) -> str:
        """返回终结技充能状态的可读文本（如 '能量: 120/120' 或 '残梦: 9/9'），遵循星铁向下截断规范。"""
        energy = getattr(entity, "energy", 0.0)
        max_energy = getattr(entity, "max_energy", 120.0)
        import math
        return f"能量: {math.floor(energy)}/{math.floor(max_energy)}"

    def get_memosprite_snapshot(self) -> Optional[dict]:
        """若角色拥有伴生忆灵/召唤物，返回其独立实时战斗状态快照；否则返回 None。"""
        return None

    def trace_variables(self) -> list:
        """向因果追踪器自申报本角色的可追踪机制变量 (TraceVariableSpec 列表)。

        申报后, 追踪器即可按变量名通用渲染其流转, 无需在核心层写死任何角色变量名。
        """
        return []

    def get_trace_panel_section(self) -> Optional[tuple]:
        """返回本角色专属的因果报表段落 (标题, 行列表), 由追踪器统一编号拼接；无则返回 None。"""
        return None

    def get_kit_state(self) -> dict:
        """返回该角色独有的机制层状态字典（如充能层数、印记、协奏状态等）。"""
        excluded = {"owner_id", "port", "skill_levels", "scaling"}
        state = {}
        for k, v in self.__dict__.items():
            if k not in excluded and not k.startswith("_"):
                if isinstance(v, (int, float, bool, str, list, dict)):
                    state[k] = v
        return state

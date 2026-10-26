"""关卡环境机制系统与插件注册中心 (Stage Mechanics & Plugins)。

核心设计：
- 核心调度引擎 (TurnSimulator) 仅感知通用事件与生命周期钩子，不硬编码任何具体玩法名称或数值；
- 关卡机制（如血噬、混沌乱流、虚构叙事光环）作为独立的 StageMechanicPlugin 插件实现，通过 StageMechanicRegistry 动态注册与实例化；
- 支持 `@register_stage_mechanic("机制名", "别名")` 装饰器即插即用注册，零修改引擎内核。
"""
from typing import Protocol, Type, Dict, Any, Callable
from .combat_port import BuffSpec
from .status import DurationTiming, StatusTag


class StageMechanicPlugin(Protocol):
    """关卡环境机制插件协议契约。"""
    def on_battle_start(self, sim: Any) -> None: ...
    def on_turn_begin(self, active_entity: Any, sim: Any) -> None: ...
    def on_entity_summoned(self, entity: Any, sim: Any) -> None: ...


class StageMechanicRegistry:
    """关卡环境机制工厂与注册中心。"""
    _registry: Dict[str, Type[StageMechanicPlugin]] = {}

    @classmethod
    def register(cls, mechanic_name: str, plugin_class: Type[StageMechanicPlugin]) -> None:
        cls._registry[mechanic_name] = plugin_class
        cls._registry[mechanic_name.lower()] = plugin_class

    @classmethod
    def create(cls, mechanic_name: str) -> StageMechanicPlugin:
        # 1. 精确匹配注册表 (支持传入动态名称与忽略大小写，严禁子串模糊匹配)
        plugin_cls = cls._registry.get(mechanic_name) or cls._registry.get(mechanic_name.lower())
        if plugin_cls:
            try:
                return plugin_cls(name=mechanic_name)
            except TypeError:
                return plugin_cls()
        # 2. 兜底通用机制
        return GenericStageMechanicPlugin(name=mechanic_name)


def register_stage_mechanic(*names: str) -> Callable[[Type[StageMechanicPlugin]], Type[StageMechanicPlugin]]:
    """关卡环境机制插件类装饰器，支持一键注册多个中英文别名。"""
    def _decorator(cls: Type[StageMechanicPlugin]) -> Type[StageMechanicPlugin]:
        for name in names:
            StageMechanicRegistry.register(name, cls)
        return cls
    return _decorator


@register_stage_mechanic("血噬", "血嗜", "流血环境", "BloodDevour", "Bleed")
class BloodDevourMechanicPlugin:
    """【血噬/血嗜】关卡环境扣血机制插件：
    - 实体入场召唤时，挂载环境状态标识供战斗视图透析；
    - 我方角色回合开始时，造成环境生命削减 500 点。
    """
    def __init__(self, name: str = "血噬", bleed_damage: float = 500.0):
        self.name = name
        self.bleed_damage = bleed_damage

    def _apply_stage_status(self, port: Any, entity_name: str) -> None:
        port.upsert_status(BuffSpec(
            key=f"Stage_Mechanic_{self.name}_{entity_name}",
            name=self.name,
            source_id=entity_name,
            target_id=entity_name,
            modifiers=(),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="other",
            tags=(StatusTag.AURA_SHARED, StatusTag.SUPPRESS_STATUS_APPLY_EVENT),
            description="关卡全局环境机制"
        ))

    def on_battle_start(self, sim: Any) -> None:
        for e in sim.entities:
            self._apply_stage_status(sim.port, e.name)

    def on_turn_begin(self, active_entity: Any, sim: Any) -> None:
        if not active_entity.is_enemy:
            sim.port.lose_hp(active_entity.name, self.bleed_damage, cause="stage_mechanic_bleed_turn_begin")

    def on_entity_summoned(self, entity: Any, sim: Any) -> None:
        self._apply_stage_status(sim.port, entity.name)


# 向因果追踪器自注册本机制的扣血来源描述 (供 tracer 因果报表引用, 核心层不写死本机制信息)
from .tracer import ActionCausalTracer as _Tracer

_Tracer.register_cause_plugin(
    "stage_mechanic_bleed_turn_begin",
    "关卡",
    "《血噬》 (Stage Mechanic)",
    "回合开始受到 500 点环境流血伤害",
)


class GenericStageMechanicPlugin:
    """通用默认关卡机制插件（仅挂载状态标记，无额外扣血动作）。"""
    def __init__(self, name: str):
        self.name = name

    def _apply_stage_status(self, port: Any, entity_name: str) -> None:
        port.upsert_status(BuffSpec(
            key=f"Stage_Mechanic_{self.name}_{entity_name}",
            name=self.name,
            source_id=entity_name,
            target_id=entity_name,
            modifiers=(),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="other",
            tags=(StatusTag.AURA_SHARED, StatusTag.SUPPRESS_STATUS_APPLY_EVENT),
            description="关卡全局环境机制"
        ))

    def on_battle_start(self, sim: Any) -> None:
        for e in sim.entities:
            self._apply_stage_status(sim.port, e.name)

    def on_turn_begin(self, active_entity: Any, sim: Any) -> None:
        pass

    def on_entity_summoned(self, entity: Any, sim: Any) -> None:
        self._apply_stage_status(sim.port, entity.name)

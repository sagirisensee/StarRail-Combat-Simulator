"""关卡环境机制系统与插件注册中心 (Stage Mechanics & Plugins)。

核心设计：
- 核心调度引擎 (TurnSimulator) 仅感知通用事件与生命周期钩子，不硬编码任何具体玩法名称或数值；
- 关卡机制（如血噬、混沌乱流、虚构叙事光环）作为独立的 StageMechanicPlugin 插件实现，通过 StageMechanicRegistry 动态注册与实例化；
- 无论机制名称如何变更（如从“血噬”到“血嗜”或英文“Bleed”），只需在配置或别名中映射插件即可，零修改引擎内核。
"""
from typing import Protocol, Type, Dict, List, Optional, Any
from .status import StatusInstance, DurationTiming


class StageMechanicPlugin(Protocol):
    """关卡环境机制插件协议契约。"""
    def on_battle_start(self, sim: Any) -> None: ...
    def on_turn_begin(self, active_entity: Any, sim: Any) -> None: ...
    def on_entity_summoned(self, entity: Any, sim: Any) -> None: ...


class BloodDevourMechanicPlugin:
    """【血噬/血嗜】关卡环境扣血机制插件：
    - 实体入场召唤时，造成环境生命削减 500 点；
    - 我方角色回合开始时，造成环境生命削减 500 点；
    - 挂载环境状态标识供战斗视图透析。
    """
    def __init__(self, name: str = "血噬", bleed_damage: float = 500.0):
        self.name = name
        self.bleed_damage = bleed_damage

    def on_battle_start(self, sim: Any) -> None:
        # 为全场实体挂载环境机制状态标记 (category="other")
        for e in sim.entities:
            sim.status_mgr.add_status(StatusInstance(
                id=f"Stage_Mechanic_{self.name}_{e.name}",
                name=self.name,
                source=e,
                target=e,
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                modifiers=[],
                category="other",
                description="关卡全局环境机制"
            ))

    def on_turn_begin(self, active_entity: Any, sim: Any) -> None:
        if not active_entity.is_enemy:
            sim.port.lose_hp(active_entity.name, self.bleed_damage, cause="stage_mechanic_bleed_turn_begin")

    def on_entity_summoned(self, entity: Any, sim: Any) -> None:
        sim.port.lose_hp(entity.name, self.bleed_damage, cause="stage_mechanic_bleed_summon")
        # 为新入场实体补充环境状态标记
        sim.status_mgr.add_status(StatusInstance(
            id=f"Stage_Mechanic_{self.name}_{entity.name}",
            name=self.name,
            source=entity,
            target=entity,
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            modifiers=[],
            category="other",
            description="关卡全局环境机制"
        ))


class GenericStageMechanicPlugin:
    """通用默认关卡机制插件（仅挂载状态标记，无额外扣血动作）。"""
    def __init__(self, name: str):
        self.name = name

    def on_battle_start(self, sim: Any) -> None:
        for e in sim.entities:
            sim.status_mgr.add_status(StatusInstance(
                id=f"Stage_Mechanic_{self.name}_{e.name}",
                name=self.name,
                source=e,
                target=e,
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                modifiers=[],
                category="other",
                description="关卡全局环境机制"
            ))

    def on_turn_begin(self, active_entity: Any, sim: Any) -> None:
        pass

    def on_entity_summoned(self, entity: Any, sim: Any) -> None:
        sim.status_mgr.add_status(StatusInstance(
            id=f"Stage_Mechanic_{self.name}_{entity.name}",
            name=self.name,
            source=entity,
            target=entity,
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            modifiers=[],
            category="other",
            description="关卡全局环境机制"
        ))


class StageMechanicRegistry:
    """关卡环境机制工厂与注册中心。"""
    _registry: Dict[str, Type[StageMechanicPlugin]] = {}

    @classmethod
    def register(cls, mechanic_name: str, plugin_class: Type[StageMechanicPlugin]) -> None:
        cls._registry[mechanic_name] = plugin_class

    @classmethod
    def create(cls, mechanic_name: str) -> StageMechanicPlugin:
        # 1. 精确匹配注册表 (支持传入动态名称)
        if mechanic_name in cls._registry:
            try:
                return cls._registry[mechanic_name](name=mechanic_name)
            except TypeError:
                return cls._registry[mechanic_name]()
        # 2. 语义别名匹配 (如包含 "血" 或 "bleed")
        if "血" in mechanic_name or "bleed" in mechanic_name.lower():
            return BloodDevourMechanicPlugin(name=mechanic_name)
        # 3. 兜底通用机制
        return GenericStageMechanicPlugin(name=mechanic_name)


# 默认预注册
StageMechanicRegistry.register("血噬", BloodDevourMechanicPlugin)
StageMechanicRegistry.register("血嗜", BloodDevourMechanicPlugin)
StageMechanicRegistry.register("BloodDevour", BloodDevourMechanicPlugin)
StageMechanicRegistry.register("Bleed", BloodDevourMechanicPlugin)

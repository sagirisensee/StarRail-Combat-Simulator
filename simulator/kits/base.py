"""角色战斗技能套件基类 (Character Kit Handler Base)."""
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

    @abstractmethod
    def definition(self, kind: ActionKind) -> AbilityDefinition:
        """声明指定动作类型的目标模式与资源消耗。"""
        pass

    @abstractmethod
    def execute(self, ctx: ActionContext) -> None:
        """执行指定动作的具体战斗逻辑。"""
        pass

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
        """响应事件总线发布的事件（如友方耗点、击破、回合切换等）。"""
        pass

    def get_kit_state(self) -> dict:
        """返回该角色独有的机制层状态字典（如充能层数、印记、协奏状态等）。"""
        excluded = {"owner_id", "port", "skill_levels"}
        state = {}
        for k, v in self.__dict__.items():
            if k not in excluded and not k.startswith("_"):
                if isinstance(v, (int, float, bool, str, list, dict)):
                    state[k] = v
        return state

"""光锥战斗处理器抽象基类 (Light Cone Handler Base)."""
from abc import ABC
from typing import Optional, Any, Sequence, TypeVar
from ..actions import ActionContext
from ..combat_port import CombatPort
from .models import LightConeSpec

T = TypeVar("T")


class LightConeHandler(ABC):
    """独立光锥运行时处理器基类。每场战斗、每位装备者独立实例化。"""

    def __init__(
        self,
        owner_id: str,
        port: Optional[CombatPort] = None,
        *,
        superimposition: int = 1,
        spec: Optional[LightConeSpec] = None
    ) -> None:
        if not isinstance(superimposition, int) or not 1 <= superimposition <= 5:
            raise ValueError(f"光锥叠影阶数必须是 1~5 之间的整数，当前为: {superimposition}")
        self.owner_id = owner_id
        self.port = port
        self.superimposition = superimposition
        self.spec = spec

    def scale(self, values: Sequence[T]) -> T:
        """根据当前叠影阶数 (S1~S5) 快速检索对应数值 (长度需为 5)。"""
        if len(values) != 5:
            raise ValueError(f"叠影数值序列必须包含 5 个元素 (S1~S5)，当前长度: {len(values)}")
        return values[self.superimposition - 1]

    def on_attach(self) -> None:
        """光锥装配至实体时的初始化。"""
        pass

    def on_battle_start(self) -> None:
        """战斗开始时触发被动与光环（如进战回能、初始开局 Buff 等）。"""
        pass

    def on_action_before(self, ctx: ActionContext) -> None:
        """装备者即将执行动作前的触发点。"""
        pass

    def on_action_after(self, ctx: ActionContext) -> None:
        """装备者动作执行完成后的结算点。"""
        pass

    def on_turn_start(self) -> None:
        """装备者自身回合开始时的触发点。"""
        pass

    def on_turn_end(self) -> None:
        """装备者自身回合结束时的触发点。"""
        pass

    def on_event(self, event: Any) -> None:
        """接收领域战斗事件 (如受到伤害、击杀、触发追加攻击、队友行动等)。"""
        pass

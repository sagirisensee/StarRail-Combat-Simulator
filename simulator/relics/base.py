"""遗器战斗运行时处理器抽象基类 (Relic Set Handler Base)."""
from abc import ABC
from typing import Optional, Any
from ..actions import ActionContext
from ..combat_port import CombatPort
from .models import RelicSetSpec


class RelicSetHandler(ABC):
    """独立遗器套装运行时处理器基类。每位装备者独立实例化。"""

    def __init__(
        self,
        owner_id: str,
        port: Optional[CombatPort] = None,
        *,
        pieces: int = 4,
        spec: Optional[RelicSetSpec] = None
    ) -> None:
        if pieces not in (2, 4):
            raise ValueError(f"遗器套装件数必须为 2 或 4，当前为: {pieces}")
        self.owner_id = owner_id
        self.port = port
        self.pieces = pieces
        self.spec = spec

    def apply_panel_passives(self, entity: Any) -> None:
        """应用遗器套装被动/常驻属性加成至实体基础面板。"""
        pass

    def on_attach(self) -> None:
        """遗器装配至角色时的初始化回调。"""
        pass

    def on_battle_start(self) -> None:
        """战斗开始时的被动/光环挂载触发点。"""
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
        """接收领域战斗事件 (如受到伤害、击杀、触发追击、造成治疗等)。"""
        pass


def apply_equipped_relics_affixes(relics: Any, entity: Any) -> None:
    """从装备的具体遗器部件中解析主词条属性并注入实体基础属性 (如治疗衣)。"""
    if not relics:
        return
    for r in relics:
        main_affix = getattr(r, "main_affix_name", "")
        if "治疗量" in main_affix:
            # 5 星治疗衣 +15 主词条通常为 +34.5% (0.345)
            entity.base_outgoing_healing += 0.345


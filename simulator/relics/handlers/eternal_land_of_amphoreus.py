"""永恒之地翁法罗斯 (Eternal Land of Amphoreus - ID 323) 位面产物独立运行时处理器。"""
from typing import Any
from ..base import RelicSetHandler
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class EternalLandOfAmphoreusHandler(RelicSetHandler):
    """永恒之地翁法罗斯 (ID 323):
    - 2件套: 使装备者的暴击率提高 8% (面板中已计入)。
            装备者的忆灵在场时，我方全体速度提高 8%，该效果无法叠加。
    """

    BUFF_KEY = "Relic_Amphoreus_Team_Speed"

    def on_battle_start(self) -> None:
        if self.pieces >= 2:
            self._sync_speed_buff()

    def on_event(self, event: Any) -> None:
        if self.pieces < 2:
            return
        from ...events import ActionExecuteEvent, TurnBeginEvent, SpiritSummonedEvent, SpiritDespawnEvent
        # 仅在实体召唤、退场或行动轮次变化等关键时机同步，避免高频细粒度事件的无效遍历
        if isinstance(event, (SpiritSummonedEvent, SpiritDespawnEvent, ActionExecuteEvent, TurnBeginEvent)):
            self._sync_speed_buff()

    def _has_memosprite_on_field(self) -> bool:
        """检查装备者自身是否有存活在场的伴生忆灵。"""
        if not self.port:
            return False
        for ally_name in self.port.allies(self.owner_id):
            if self.port.is_own_memosprite(self.owner_id, ally_name):
                return True
        return False

    def _is_any_other_amphoreus_active(self) -> bool:
        """检查是否有其他队友也装备了翁法罗斯且其忆灵仍在场（确保退场时不误删不可叠加的全队效果）。"""
        if not self.port:
            return False
        for ally_name in self.port.allies(self.owner_id):
            if ally_name == self.owner_id:
                continue
            ent = getattr(self.port, "_get_entity", lambda _: None)(ally_name)
            if not ent or not getattr(ent, "relic_handlers", None):
                continue
            for handler in ent.relic_handlers:
                if isinstance(handler, EternalLandOfAmphoreusHandler) and handler.pieces >= 2:
                    if handler._has_memosprite_on_field():
                        return True
        return False

    def _sync_speed_buff(self) -> None:
        if not self.port or self.pieces < 2:
            return
        active = self._has_memosprite_on_field()
        for ally in self.port.allies(self.owner_id):
            # 排除非战斗角色/倒计时跑条实体
            if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                continue
            has_buff = self.port.has_status(ally, self.BUFF_KEY)
            if active and not has_buff:
                self.port.upsert_status(BuffSpec(
                    key=self.BUFF_KEY,
                    name="永恒之地翁法罗斯",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.08),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="装备者的忆灵在场，我方全体速度提高 +8.0%"
                ))
            elif not active and has_buff:
                # 只有当全队没有任何其他装备者的忆灵在场时，才真正移除全队增益（保证“该效果无法叠加”时的正确生命周期）
                if not self._is_any_other_amphoreus_active():
                    self.port.remove_status(ally, self.BUFF_KEY)

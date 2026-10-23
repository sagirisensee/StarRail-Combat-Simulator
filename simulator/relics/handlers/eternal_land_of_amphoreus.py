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
        if self.pieces >= 2:
            self._sync_speed_buff()

    def _has_memosprite_on_field(self) -> bool:
        if not self.port:
            return False
        for ally_name in self.port.allies(self.owner_id):
            if self.port.is_own_memosprite(self.owner_id, ally_name):
                if "倒计时" not in ally_name and "Countdown" not in ally_name:
                    return True
        return False

    def _sync_speed_buff(self) -> None:
        if not self.port or self.pieces < 2:
            return
        active = self._has_memosprite_on_field()
        for ally in self.port.allies(self.owner_id):
            if "倒计时" in ally or "Countdown" in ally:
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
                self.port.remove_status(ally, self.BUFF_KEY)

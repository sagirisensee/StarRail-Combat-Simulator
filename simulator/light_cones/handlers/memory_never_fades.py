"""光锥：记忆永不落幕 (Memory Never Fades - ID 24005).

命途：记忆 (黑塔商店兑换光锥)
核心效果【收取】：
1. 装备者速度提高 6% / 7.5% / 9% / 10.5% / 12% (基础面板已计入)；
2. 装备者施放战技后，使我方全体造成的伤害提高 8% / 10% / 12% / 14% / 16%，持续 3 回合。
"""
from typing import Any
from ..base import LightConeHandler
from ...actions import ActionContext, ActionKind
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class MemoryNeverFadesHandler(LightConeHandler):
    """《记忆永不落幕》专属战斗逻辑处理器。"""

    DMG_BOOST_VALUES = (0.08, 0.10, 0.12, 0.14, 0.16)

    def on_action_after(self, ctx: ActionContext) -> None:
        """装备者施放战技后，为我方全体提供全伤害增益。"""
        if not self.port or ctx.actor_id != self.owner_id:
            return
        if ctx.kind == ActionKind.SKILL:
            dmg_val = self.scale(self.DMG_BOOST_VALUES)
            for ally in self.port.allies(self.owner_id):
                if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                    continue
                self.port.upsert_status(BuffSpec(
                    key="LC_MemoryNeverFades_DmgBuff",
                    name=f"收取 (记忆永不落幕S{self.superimposition}全队增伤{dmg_val*100:.0f}%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_val),),
                    duration=3,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True,
                ))

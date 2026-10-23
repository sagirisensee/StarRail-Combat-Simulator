"""再创天地的救世主 (Creator of the New World - ID 127) 遗器运行时处理器。"""
from typing import Any
from ..base import RelicSetHandler
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType
from ...events import ActionExecuteEvent
from ...actions import ActionKind


class CreatorOfNewWorldHandler(RelicSetHandler):
    """再创天地的救世主 (ID 127):
    - 2件套: 暴击率提高 8% (面板中已计入)
    - 4件套: 装备者施放普攻或战技后，若装备者的忆灵在场，使装备者及其忆灵生命上限提高 24%，
            我方全体造成的伤害提高 15%，持续至装备者下次施放普攻或战技后。
    """

    BUFF_HP_KEY = "Relic_Creator_Self_Memosprite_HP"
    BUFF_DMG_KEY = "Relic_Creator_Team_Dmg"

    def apply_panel_passives(self, entity: Any) -> None:
        """2件套暴击率 +8% 已计入静态导出面板，此处无需二次叠加。"""
        pass

    def _has_own_memosprite(self) -> bool:
        if not self.port:
            return False
        for ally in self.port.allies(self.owner_id):
            if self.port.is_own_memosprite(self.owner_id, ally):
                if "倒计时" not in ally and "Countdown" not in ally:
                    return True
        return False

    def _trigger_4pc_buff(self) -> None:
        if not self._has_own_memosprite():
            return
        # 1. 自身与自身忆灵生命上限提高 24%
        memos = [
            ally for ally in self.port.allies(self.owner_id)
            if self.port.is_own_memosprite(self.owner_id, ally)
        ]
        for tgt in [self.owner_id] + memos:
            old_max = self.port.max_hp(tgt)
            self.port.upsert_status(BuffSpec(
                key=f"{self.BUFF_HP_KEY}_{tgt}",
                name="再创天地的救世主 (生命+24%)",
                source_id=self.owner_id,
                target_id=tgt,
                modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.24),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="施放普攻或战技且忆灵在场，生命上限提高 +24.0%"
            ))
            new_max = self.port.max_hp(tgt)
            hp_delta = new_max - old_max
            if hp_delta > 0:
                ent = getattr(self.port, "_get_entity", lambda x: None)(tgt)
                if ent:
                    ent.current_hp = min(new_max, getattr(ent, "current_hp", 0.0) + hp_delta)

        # 2. 我方全体造成的伤害提高 15%
        for ally in self.port.allies(self.owner_id):
            if "倒计时" in ally or "Countdown" in ally:
                continue
            self.port.upsert_status(BuffSpec(
                key=f"{self.BUFF_DMG_KEY}_{ally}",
                name="再创天地的救世主 (增伤+15%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.15),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="全队造成伤害提高 +15.0%"
            ))

    def on_action_after(self, ctx: Any) -> None:
        if self.pieces < 4 or not self.port:
            return
        actor = getattr(ctx, "actor_id", "")
        kind = getattr(ctx, "kind", None)
        if actor == self.owner_id and kind in (ActionKind.BASIC, ActionKind.SKILL):
            self._trigger_4pc_buff()

    def on_event(self, event: Any) -> None:
        if self.pieces < 4 or not self.port:
            return
        if isinstance(event, ActionExecuteEvent):
            actor = event.actor_name or getattr(event, "actor_id", "")
            action_kind = getattr(event, "action_kind", None)
            if actor == self.owner_id and action_kind in (ActionKind.BASIC, ActionKind.SKILL):
                self._trigger_4pc_buff()

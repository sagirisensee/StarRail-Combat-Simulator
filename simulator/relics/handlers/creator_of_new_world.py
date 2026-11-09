"""再创天地的救世主 (Creator of the New World - ID 127) 遗器运行时处理器。"""
from typing import Any
from ..base import RelicSetHandler
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType
from ...events import SpiritSummonedEvent
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
            if self.port.is_own_memosprite(self.owner_id, ally) and not self.port.is_countdown(ally):
                return True
        return False

    def is_active(self) -> bool:
        if not self.port:
            return False
        return self.port.has_status(self.owner_id, f"{self.BUFF_HP_KEY}_{self.owner_id}")

    def _apply_buffs(self) -> None:
        """生效救世主4件套：自身与忆灵生命上限提高24%，我方全体增伤15%。"""
        if not self.port:
            return
        # 1. 自身与自身忆灵生命上限提高 24%
        memos = [
            ally for ally in self.port.allies(self.owner_id)
            if self.port.is_own_memosprite(self.owner_id, ally) and not self.port.is_countdown(ally)
        ]
        for tgt in [self.owner_id] + memos:
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

        # 2. 我方全体造成的伤害提高 15% (光环式增伤)
        for ally in self.port.allies(self.owner_id):
            if self.port.is_countdown(ally):
                continue
            self.port.upsert_status(BuffSpec(
                key=f"{self.BUFF_DMG_KEY}_{self.owner_id}_{ally}",
                name=f"再创天地的救世主 (增伤+15% [{self.owner_id}])",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.15),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="全队造成伤害提高 +15.0%"
            ))

    def _clear_buffs(self) -> None:
        """清除本装备者提供的救世主效果。"""
        if not self.port:
            return
        self.port.remove_status(self.owner_id, f"{self.BUFF_HP_KEY}_{self.owner_id}")
        for ally in self.port.allies(self.owner_id):
            self.port.remove_status(ally, f"{self.BUFF_HP_KEY}_{ally}")
            self.port.remove_status(ally, f"{self.BUFF_DMG_KEY}_{self.owner_id}_{ally}")

    def on_action_after(self, ctx: Any) -> None:
        """装备者施放普攻或战技后判定：若忆灵在场则获得/续期光环，若不在场则失效。"""
        if self.pieces < 4 or not self.port:
            return
        actor = getattr(ctx, "actor_id", "")
        kind = getattr(ctx, "kind", None)
        if actor == self.owner_id and kind in (ActionKind.BASIC, ActionKind.SKILL):
            if self._has_own_memosprite():
                self._apply_buffs()
            else:
                self._clear_buffs()

    def on_event(self, event: Any) -> None:
        if self.pieces < 4 or not self.port:
            return
        if isinstance(event, SpiritSummonedEvent):
            target = getattr(event, "spirit_name", "")
            # 若本装备者的救世主光环处于激活状态，新召唤上来的忆灵作为我方目标也能吃到救世主
            if self.is_active() and target and self.port.entity_exists(target):
                if not self.port.is_countdown(target):
                    self.port.upsert_status(BuffSpec(
                        key=f"{self.BUFF_DMG_KEY}_{self.owner_id}_{target}",
                        name=f"再创天地的救世主 (增伤+15% [{self.owner_id}])",
                        source_id=self.owner_id,
                        target_id=target,
                        modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.15),),
                        duration=None,
                        timing=DurationTiming.TARGET_TURN_END,
                        category="buff",
                        description="全队造成伤害提高 +15.0%"
                    ))
                    if self.port.is_own_memosprite(self.owner_id, target):
                        self.port.upsert_status(BuffSpec(
                            key=f"{self.BUFF_HP_KEY}_{target}",
                            name="再创天地的救世主 (生命+24%)",
                            source_id=self.owner_id,
                            target_id=target,
                            modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.24),),
                            duration=None,
                            timing=DurationTiming.TARGET_TURN_END,
                            category="buff",
                            description="施放普攻或战技且忆灵在场，生命上限提高 +24.0%"
                        ))

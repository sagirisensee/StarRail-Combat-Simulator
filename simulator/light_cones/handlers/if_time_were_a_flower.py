"""光锥：如果时间是一朵花 (If Time Were a Flower - ID 23038).

命途：同谐
核心效果【希冀】：
1. 暴击伤害提高 36% / 42% / 48% / 54% / 60% (基础面板已计入)；
2. 进入战斗时，装备者恢复 21 点能量，并获得【谕示】，持续 2 回合；
3. 持有【谕示】时，我方全体目标的暴击伤害提高 48% / 60% / 72% / 84% / 96%；
4. 装备者施放追加攻击后，额外恢复 12 点能量，并刷新【谕示】持续 2 回合。
"""
from typing import Any
from ..base import LightConeHandler
from ...actions import ActionContext
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class IfTimeWereAFlowerHandler(LightConeHandler):
    """《如果时间是一朵花》专属战斗逻辑处理器。"""

    ORACLE_CRIT_DMG = (0.48, 0.60, 0.72, 0.84, 0.96)

    def apply_oracle_buff(self) -> None:
        """为我方全体施加/刷新【谕示】全队暴伤增益。"""
        if not self.port:
            return
        crit_val = self.scale(self.ORACLE_CRIT_DMG)
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="LC_IfTimeWereAFlower_Oracle",
                name="谕示",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, crit_val),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"全队暴击伤害 +{crit_val*100:.1f}%"
            ))

    def on_battle_start(self) -> None:
        """进战瞬间：恢复 21 点能量 (享受 ERR 放大) 并展开【谕示】。"""
        if not self.port:
            return
        ent = self.port._get_entity(self.owner_id) if hasattr(self.port, "_get_entity") else None
        err = getattr(ent, "err", 1.0) if ent else 1.0
        self.port.gain_energy(self.owner_id, 21.0 * err)
        self.apply_oracle_buff()

    def on_action_after(self, ctx: ActionContext) -> None:
        """施放动作后判定：若是追加攻击，则回能 12 点并刷新【谕示】。"""
        if not self.port:
            return
        if getattr(ctx, "damage_tag", None) == "FollowUpAttack" or "FollowUp" in getattr(ctx, "action_id", ""):
            self.port.gain_energy(self.owner_id, 12.0)
            self.apply_oracle_buff()

    def on_action_before(self, ctx: ActionContext) -> None:
        self._fua_triggered_this_action = False

    def on_event(self, event: Any) -> None:
        """监听可能产生的追击事件，确保每次追击只触发一次回能与刷新。"""
        if getattr(event, "actor_id", "") == self.owner_id:
            action_type = getattr(event, "action_type", "")
            event_name = type(event).__name__
            if ("FollowUp" in action_type or "FollowUp" in event_name) and not getattr(self, "_fua_triggered_this_action", False):
                self._fua_triggered_this_action = True
                if self.port:
                    ent = self.port._get_entity(self.owner_id) if hasattr(self.port, "_get_entity") else None
                    err = getattr(ent, "err", 1.0) if ent else 1.0
                    self.port.gain_energy(self.owner_id, 12.0 * err)
                    self.apply_oracle_buff()

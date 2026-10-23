"""光锥：让告别，更美一些 (Make Farewells More Beautiful - ID 23040).

命途：记忆 (长夜月专属)
核心效果【铭刻】：
1. 装备者生命上限提高 30% / 37.5% / 45% / 52.5% / 60% (基础面板已计入)；
2. 当装备者或装备者的忆灵损失生命值时，装备者获得【冥花】；
   拥有【冥花】时，造成伤害无视目标 30% / 35% / 40% / 45% / 50% 防御力，持续 2 回合；
3. 忆灵消失时，使装备者行动提前 12% / 15% / 18% / 21% / 24% (每次施放终结技重置触发)。
"""
from typing import Any
from ..base import LightConeHandler
from ...actions import ActionContext, ActionKind
from ...combat_port import BuffSpec
from ...events import HPLostEvent, SpiritDespawnEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class MakeFarewellsMoreBeautifulHandler(LightConeHandler):
    """《让告别，更美一些》专属战斗逻辑处理器（纯事件总线驱动，与角色套件零耦合）。"""

    DEF_IGNORE_VALUES = (0.30, 0.35, 0.40, 0.45, 0.50)
    ACTION_ADVANCE_VALUES = (0.12, 0.15, 0.18, 0.21, 0.24)

    def __init__(self, owner_id: str, port: Any = None, *, superimposition: int = 1, spec: Any = None):
        super().__init__(owner_id, port, superimposition=superimposition, spec=spec)
        self.advance_triggered: bool = False

    def trigger_flower_buff(self) -> None:
        """触发并挂载【冥花】状态（无视防御力）。"""
        if not self.port:
            return
        def_shred_val = self.scale(self.DEF_IGNORE_VALUES)
        self.port.upsert_status(BuffSpec(
            key="LC_Farewells_FlowerBuff",
            name="冥花",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, def_shred_val),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"《让告别，更美一些》无视防御 {def_shred_val*100:.1f}%"
        ))

    def on_action_after(self, ctx: ActionContext) -> None:
        """在装备者自身回合内施放技能时激活【冥花】；施放终结技重置拉条触发次数。"""
        if ctx.actor_id != self.owner_id:
            return
        if ctx.kind in (ActionKind.SKILL, ActionKind.BASIC):
            self.trigger_flower_buff()
        elif ctx.kind == ActionKind.ULTIMATE:
            self.advance_triggered = False

    def on_event(self, event: Any) -> None:
        """监听标准领域事件 HPLostEvent 与 SpiritDespawnEvent，彻底消除角色套件跨层直接调用光锥方法。"""
        if not self.port:
            return
        if isinstance(event, HPLostEvent):
            is_owner = (event.entity_name == self.owner_id)
            is_own_spirit = self.port.is_own_memosprite(self.owner_id, event.entity_name)
            if (is_owner or is_own_spirit) and event.amount > 0:
                self.trigger_flower_buff()
        elif isinstance(event, SpiritDespawnEvent):
            if event.owner_name == self.owner_id and not self.advance_triggered:
                self.advance_triggered = True
                adv_ratio = self.scale(self.ACTION_ADVANCE_VALUES)
                self.port.advance(self.owner_id, self.owner_id, adv_ratio)

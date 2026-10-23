"""【新人开发标准脚手架模板】光锥战斗处理器 (_template.py)。

使用方式：
1. 复制本文件为 `simulator/light_cones/handlers/<lc_snake_case>.py`（去掉开头的下划线 `_`）；
2. 取消 `@register_light_cone(...)` 装饰器注释并填写光锥 ID、名称、命途与别名；
3. 系统会自动扫描 `handlers/` 目录并完成注册，**无需手动修改 `catalog.py`**！

核心守则：
- 叠影 S1~S5 数值请定义为 5 元组常量，并通过 `self.scale(VALUES)` 动态读取；
- 监听生命变化、忆灵退场、治疗或追击请统一在 `on_event` 中通过 `BattleEvent` 子类判断。
"""
from typing import Any
from ..base import LightConeHandler
from ..registry import register_light_cone
from ...actions import ActionContext, ActionKind
from ...combat_port import BuffSpec
from ...events import HPLostEvent, SpiritDespawnEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType


# 复制后取消下方装饰器注释即可自动注册，无需修改 catalog.py：
# @register_light_cone(cone_id="29999", name="示例光锥", path="Remembrance", rarity=5, aliases=("example_lc",))
class ExampleLightConeHandler(LightConeHandler):
    """《示例光锥》独立战斗运行时处理器模板。"""

    DMG_BOOST_VALUES = (0.24, 0.30, 0.36, 0.42, 0.48)

    def on_battle_start(self) -> None:
        """进战触发被动或能量恢复。"""
        if not self.port:
            return
        val = self.scale(self.DMG_BOOST_VALUES)
        self.port.upsert_status(BuffSpec(
            key=f"LC_Example_Buff_{self.owner_id}",
            name="示例光锥增益",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, val),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description=f"造成伤害提高 +{val * 100:.1f}%"
        ))

    def on_action_after(self, ctx: ActionContext) -> None:
        """装备者执行动作后的结算钩子。"""
        if not self.port or ctx.actor_id != self.owner_id:
            return
        if ctx.kind == ActionKind.ULTIMATE:
            pass

    def on_event(self, event: Any) -> None:
        """监听标准领域事实事件（如 HPLostEvent / SpiritDespawnEvent / HealAppliedEvent）。"""
        if not self.port:
            return
        if isinstance(event, HPLostEvent):
            if event.entity_name == self.owner_id or self.port.is_own_memosprite(self.owner_id, event.entity_name):
                pass

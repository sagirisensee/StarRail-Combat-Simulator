"""【新人开发标准脚手架模板】遗器套装战斗处理器 (_template.py)。

使用方式：
1. 复制本文件为 `simulator/relics/handlers/<relic_snake_case>.py`（去掉开头的下划线 `_`）；
2. 取消 `@register_relic_set(...)` 装饰器注释并填写套装 ID、名称、类型 (`"cavern"` 或 `"planar"`) 与别名；
3. 系统会自动扫描 `handlers/` 目录并完成注册，**无需手动修改 `catalog.py`**！
"""
from typing import Any
from ..base import RelicSetHandler
from ..registry import register_relic_set
from ...combat_port import BuffSpec
from ...events import HealAppliedEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType


# 复制后取消下方装饰器注释即可自动注册，无需修改 catalog.py：
# @register_relic_set(set_id=999, name="示例遗器四件套", set_type="cavern", aliases=("example_relic",))
class ExampleRelicSetHandler(RelicSetHandler):
    """《示例遗器四件套》运行时处理器模板。"""

    def apply_panel_passives(self, entity: Any) -> None:
        """战前静态阶段：若需修正面板基础属性可在此处处理（常规2件套已在数据表结算，无需重复添加）。"""
        pass

    def on_battle_start(self) -> None:
        """进战挂载 4 件套或 2 件套光环状态。"""
        if self.pieces < 4 or not self.port:
            return
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Relic_Example_CritDmg_{ally}",
                name="示例遗器全队暴伤",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="全队暴击伤害 +15.0%"
            ))

    def on_event(self, event: Any) -> None:
        """响应标准战斗事件（如治疗触发套装增益）。"""
        if self.pieces < 4 or not self.port:
            return
        if isinstance(event, HealAppliedEvent) and event.source_name == self.owner_id:
            pass

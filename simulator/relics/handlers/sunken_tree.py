"""渊思寂虑的巨树 (Sunken Tree - ID 320) 位面产物独立运行时处理器。"""
from typing import Any
from ..base import RelicSetHandler


class SunkenTreeHandler(RelicSetHandler):
    """渊思寂虑的巨树 (ID 320):
    - 2件套: 使装备者的速度提高 6% (已计入面板)。
            当装备者的速度大于等于 135/180 时，使装备者及其忆灵的治疗量提高 12%/20%。
    """

    def apply_panel_passives(self, entity: Any) -> None:
        """速度 >= 180 时，治疗量提高 20% (0.20)；>= 135 时提高 12% (0.12)。"""
        if self.pieces >= 2:
            spd = getattr(entity, "base_speed", 0.0)
            if spd >= 180.0:
                entity.base_outgoing_healing += 0.20
            elif spd >= 135.0:
                entity.base_outgoing_healing += 0.12

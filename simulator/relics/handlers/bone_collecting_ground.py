"""谧宁拾骨地 (Bone-Collecting Ground - ID 319) 位面产物独立运行时处理器。"""
from typing import Any
from ..base import RelicSetHandler


class BoneCollectingGroundHandler(RelicSetHandler):
    """谧宁拾骨地 (ID 319):
    - 2件套: 使装备者的生命上限提高 12% (已计入面板)。
            当装备者的生命上限大于等于 5000 时，暴击伤害提高 28%。
    """

    def apply_panel_passives(self, entity: Any) -> None:
        """生命上限 >= 5000 时，自身暴击伤害提高 28% (0.28)。"""
        if self.pieces >= 2:
            max_hp = getattr(entity, "max_hp", 0.0)
            if max_hp >= 5000.0:
                entity.base_crit_dmg += 0.28

"""哀歌覆国的诗人 / 沉醉于狂欢的诗人 (Poet of Mourning - ID 124) 遗器运行时处理器。"""
from ..base import RelicSetHandler
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class PoetOfMourningHandler(RelicSetHandler):
    """哀歌覆国的诗人 (ID 124):
    - 2件套: 量子属性伤害提高 10% (静态计算已包含)
    - 4件套: 速度降低 8% (静态计算已包含)。
            进战时若装备者速度低于 110/95，使装备者的暴击率分别提高 20%/32%。
    """

    def on_battle_start(self) -> None:
        if self.pieces < 4 or not self.port:
            return

        ent = self.port._get_entity(self.owner_id) if hasattr(self.port, "_get_entity") else None
        spd = getattr(ent, "base_speed", 100.0) if ent else 100.0

        crit_bonus = 0.0
        if spd < 95.0:
            crit_bonus = 0.32
        elif spd < 110.0:
            crit_bonus = 0.20

        if crit_bonus > 0.0:
            self.port.upsert_status(BuffSpec(
                key="Relic_PoetOfMourning_4pc",
                name="哀歌覆国的诗人",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, crit_bonus),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"自身暴击率提高 +{crit_bonus * 100:.1f}%"
            ))

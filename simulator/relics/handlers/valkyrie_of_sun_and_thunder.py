"""烈阳惊雷的女武神 (The Valkyrie of Sun and Thunder - ID 125) 遗器运行时处理器。"""
from ..base import RelicSetHandler
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class ValkyrieOfSunAndThunderHandler(RelicSetHandler):
    """烈阳惊雷的女武神 (ID 125):
    - 2件套: 速度提高 6% (在基础属性静态结算中已计入)
    - 4件套: 进战或产生治疗后，持有【甘霖】使我方全体暴击伤害提高 15%。
    """

    def on_battle_start(self) -> None:
        if self.pieces < 4 or not self.port:
            return

        for ally in self.port.allies(self.owner_id):
            is_wearer = (ally == self.owner_id)
            mods = [Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15)]
            if is_wearer:
                # 装备者持有【甘霖】时，速度提高 6%
                mods.append(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.06))

            self.port.upsert_status(BuffSpec(
                key=f"Relic_Valkyrie_GentleRain_{ally}",
                name="甘霖",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="全队暴击伤害 +15.0%" + ("，自身速度 +6.0%" if is_wearer else "")
            ))

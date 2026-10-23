"""烈阳惊雷的女武神 (The Valkyrie of Sun and Thunder - ID 125) 遗器运行时处理器。"""
from ..base import RelicSetHandler
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class ValkyrieOfSunAndThunderHandler(RelicSetHandler):
    """烈阳惊雷的女武神 (ID 125):
    - 2件套: 速度提高 6% (在基础属性静态结算中已计入)
    - 4件套: 当装备者及其忆灵为装备者及其忆灵以外的我方目标提供治疗后，使装备者获得【甘霖】，每回合最多触发1次，持续2回合。
            装备者持有【甘霖】时，速度提高 6%，我方全体暴击伤害提高 15%，该效果无法叠加。
    """

    def on_battle_start(self) -> None:
        if self.pieces < 4 or not self.port:
            return

        # 1. 装备者自身持有【甘霖】：速度提高 6% (仅风堇持有)
        self.port.upsert_status(BuffSpec(
            key=f"Relic_Valkyrie_GentleRain_{self.owner_id}",
            name="甘霖",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.06),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="速度提高 +6.0%"
        ))

        # 2. 全体友方（含装备者自身与忆灵）获得套装增益【烈阳惊雷的女武神】：暴击伤害提高 15%
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Relic_Valkyrie_CritDmg_{ally}",
                name="烈阳惊雷的女武神",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="全队暴击伤害 +15.0%"
            ))

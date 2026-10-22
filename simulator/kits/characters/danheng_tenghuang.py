"""丹恒•腾荒 (ID 1414, 物理 / 存护) 战斗技能套件。"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import CombatPort


class DanHengTenghuangKit(KitHandler):
    """丹恒•腾荒 (ID 1414, 物理 / 存护)."""

    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES if kind != ActionKind.BASIC else TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="腾荒之壁")

    def execute(self, ctx: ActionContext):
        for a in self.port.allies(self.owner_id):
            self.port.add_shield(self.owner_id, a, 1800.0, duration=3)
        self.port.gain_energy(self.owner_id, 30.0)

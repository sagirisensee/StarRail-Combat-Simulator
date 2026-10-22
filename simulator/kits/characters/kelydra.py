"""刻律德菈 (ID 1412, 风 / 同谐) 战斗技能套件。"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import CombatPort


class KelydraKit(KitHandler):
    """刻律德菈 (ID 1412, 风 / 同谐)."""

    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="风之奏鸣")

    def execute(self, ctx: ActionContext):
        for a in self.port.allies(self.owner_id):
            self.port.advance(self.owner_id, a, 0.25)
        self.port.gain_energy(self.owner_id, 30.0)

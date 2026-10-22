"""大丽花 (Dahlia - ID 1321, 火 / 虚无) 战斗技能套件。"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import CombatPort


class DahliaKit(KitHandler):
    """大丽花 (Dahlia - ID 1321, 火 / 虚无)."""

    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="冥火大丽花")

    def execute(self, ctx: ActionContext):
        for e in self.port.enemies(self.owner_id):
            self.port.attack(self.owner_id, e, element="Fire", atk_multiplier=1.8, toughness_damage=20.0, damage_tag="Hellfire")
        self.port.gain_energy(self.owner_id, 30.0)

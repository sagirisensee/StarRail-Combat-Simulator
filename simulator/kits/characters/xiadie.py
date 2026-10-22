"""遐蝶 (ID 1407, 量子 / 记忆) 战斗技能套件。"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import CombatPort


class XiadieKit(KitHandler):
    """遐蝶 (ID 1407, 量子 / 记忆)."""

    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="幻蝶之翩")

    def execute(self, ctx: ActionContext):
        t = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(self.owner_id, t, element="Quantum", atk_multiplier=2.5, toughness_damage=20.0, damage_tag="Butterfly")
        self.port.gain_energy(self.owner_id, 30.0)

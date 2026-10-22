"""昔涟 (ID 1415, 冰 / 记忆) 战斗技能套件。"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import CombatPort


class XilianKit(KitHandler):
    """昔涟 (ID 1415, 冰 / 记忆)."""

    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1 if kind == ActionKind.BASIC else (1 if kind == ActionKind.SKILL else 0)), name="昔涟之忆")

    def execute(self, ctx: ActionContext):
        t = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(self.owner_id, t, element="Ice", atk_multiplier=2.0, toughness_damage=20.0, damage_tag="Memory")
        self.port.gain_energy(self.owner_id, 20.0)

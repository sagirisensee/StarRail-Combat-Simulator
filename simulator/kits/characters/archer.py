"""Archer (ID 1015) 战斗技能套件。"""
from typing import Optional
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class ArcherKit(KitHandler):
    """Archer - 无限剑制与投影魔术 (量子/巡猎)."""

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 1, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="干将·莫邪斩击")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1), name="伪·螺旋剑 (Caladbolg II)")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=130.0), name="无限剑制 (Unlimited Blade Works)")
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 投影专精 (暴击率提高 15%)。"""
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key="Archer_E1_Crit",
                name="投影专精 (Archer E1暴击率提高15%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                description="自身暴击率提高 15%"
            ))

    def execute(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if ctx.kind == ActionKind.BASIC:
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 2.40 * (1.20 if self.eidolon >= 2 else 1.0) # E2 战技增伤 20%
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=mult, toughness_damage=20.0, damage_tag="Skill")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.60 if self.eidolon >= 6 else 2.80 # E6 固有结界完全展开
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=ult_mult, toughness_damage=30.0, damage_tag="Ultimate")
            # 结界自拉条 100%
            if self.eidolon >= 4:
                self.port.advance(self.owner_id, self.owner_id, 1.0)
            self.port.gain_energy(self.owner_id, 5.0)

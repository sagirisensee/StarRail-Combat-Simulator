"""远坂凛 (Tohsaka Rin - ID 1508) 战斗技能套件。"""
from typing import Optional
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class TohsakaRinKit(KitHandler):
    """远坂凛 (Tohsaka Rin) - 宝石魔术与阴弹射击 (量子/智识)."""

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 0, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.gem_count: int = 5

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="阴弹 (Gandr)")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1), name="宝石魔术·五芒星散射")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=120.0), name="极光之镜·宝石剑爆发")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            mult = 1.20 if self.eidolon >= 1 else 1.00 # E1 普攻强化
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=mult, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 1.60 if self.eidolon >= 2 else 1.40 # E2 战技增伤
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=mult, toughness_damage=10.0, damage_tag="Skill")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.20 if self.eidolon >= 6 else 2.60 # E6 宝石剑毁灭爆发
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=ult_mult, toughness_damage=20.0, damage_tag="Ultimate")
                # E4: 减防 20%
                if self.eidolon >= 4:
                    self.port.upsert_status(BuffSpec(
                        key="Rin_E4_DefShred",
                        name="魔力瓦解 (远坂凛E4减防20%)",
                        source_id=self.owner_id,
                        target_id=enemy,
                        modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                        duration=2,
                        timing=DurationTiming.TARGET_TURN_END,
                        skip_current_clock=True,
                        category="debuff",
                        description="受到防御削减 20%"
                    ))
            self.port.gain_energy(self.owner_id, 5.0)

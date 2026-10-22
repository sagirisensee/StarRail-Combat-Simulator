"""娜塔莎 (Natasha) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【仁慈的背面】：造成物理伤害，恢复 1 点战技点，回能 20 点；
2. 战技【爱、抚慰与救赎】：消耗 1 点 SP，单体急救回血并提供 2 回合持续治疗；
3. 终结技【新生之礼】：消耗 90 能量，为我方全体紧急回复大额生命值。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class NatashaKit(KitHandler):
    HOT_BUFF = "Natasha_Heal_Over_Time"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="仁慈的背面"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="爱、抚慰与救赎"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=90.0),
                allow_self=True,
                name="新生之礼"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="催眠研究"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【催眠研究】：对敌方单体造成 80% 物理伤害并使敌方全体伤害降低 30% 持续 1 回合。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Physical",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key="Natasha_Technique_Weaken",
                name="虚弱 (娜塔莎秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.30),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # E6: 普攻额外附加 40% 生命上限伤害 (总倍率约 1.8x)
        mult = 1.80 if self.eidolon >= 6 else 1.0
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = self.port.allies(self.owner_id)
            target_id = allies[0] if allies else self.owner_id

        self.port.heal(self.owner_id, target_id, 1800.0)
        self.port.upsert_status(BuffSpec(
            key=self.HOT_BUFF,
            name="抚慰 (娜塔莎持续治疗)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.heal(self.owner_id, ally, 2500.0)
            # E2: 生命 <= 30% 目标获得持续治疗
            if self.eidolon >= 2 and self.port.hp_ratio(ally) <= 0.30:
                self.port.upsert_status(BuffSpec(
                    key=self.HOT_BUFF,
                    name="抚慰 (娜塔莎E2急救持续治疗)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(),
                    duration=1,
                    timing=DurationTiming.TARGET_TURN_START,
                    skip_current_clock=True
                ))

        self.port.gain_energy(self.owner_id, 5.0)

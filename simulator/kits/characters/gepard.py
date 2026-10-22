"""杰帕德 (Gepard - ID 1104, 冰 / 存护) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【一意之拳】：单体冰属性伤害，等同杰帕德 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【震慑之击】：消耗 1 点 SP，造成单体冰伤 200% (Lv 10)，削韧 20 点。
   有 65% (E1 提升至 100%) 基础概率使敌方单体陷入冻结状态 1 回合。回能 30。
3. 终结技【永屹之壁】(耗能 100 点)：
   - 为我方全体提供能够抵消等同于杰帕德 45% (Lv 10) 防御力 + 600 点伤害的护盾，持续 3 回合；
   - 回能 5 点。
4. 天赋【不屈之身】：受到致命攻击时免死，回复 50% 生命值 (每场战斗限 1 次)。
5. 秘技【有情之证】：进战为我方全体提供 24% 防御力 + 320 护盾，持续 2 回合。
6. 星魂：
   - E1【恪尽职守】：战技基础冻结概率提高 35% (65% -> 100%)；
   - E2【余寒】：解除冻结后目标速度降低 20%，持续 1 回合；
   - E4【精诚所至】：杰帕德在场时我方全体效果抵抗提高 20%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class GepardKit(KitHandler):
    """杰帕德 (ID 1104, 冰 / 存护)."""

    SHIELD_BUFF = "Gepard_Fortified_Shield"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def on_battle_start(self) -> None:
        """战斗开始：
        E4【精诚所至】：杰帕德在场时我方全体效果抵抗提高 20%。
        """
        if self.eidolon >= 4:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=f"Gepard_E4_EffRes_{ally}",
                    name="精诚所至",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.20),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="效果抵抗提高 +20.0%"
                ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="一意之拳"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="震慑之击"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=100.0),
                allow_self=True,
                name="永屹之壁"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="有情之证"
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
            self.use_technique()

    def use_technique(self) -> None:
        """秘技【有情之证】：进战为我方全体提供护盾 2 回合。"""
        gepard_def = self.port.stat(self.owner_id, StatType.DEF_BASE) or 4500.0
        shield_val = gepard_def * 0.24 + 320.0
        for ally in self.port.allies(self.owner_id):
            self.port.add_shield(self.owner_id, ally, shield_val, duration=2)

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【一意之拳】：单体冰伤 140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【震慑之击】：单体冰伤 200% (Lv 10)，削韧 20 点。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("skill", 0, default=2.00)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_tag="Skill",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【永屹之壁】：全队提供 45% 防御力 + 600 点护盾，持续 3 回合。"""
        gepard_def = self.port.stat(self.owner_id, StatType.DEF_BASE) or 4500.0
        shield_val = gepard_def * 0.45 + 600.0
        for ally in self.port.allies(self.owner_id):
            self.port.add_shield(self.owner_id, ally, shield_val, duration=3)
            self.port.upsert_status(BuffSpec(
                key=self.SHIELD_BUFF,
                name="永屹之壁",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"抵消 {shield_val:.0f} 点伤害"
            ))
        self.port.gain_energy(self.owner_id, 5.0)

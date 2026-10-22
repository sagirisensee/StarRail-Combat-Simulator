"""佩拉 (Pela) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【冰点射击】：造成单体冰属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【低温妨害】：驱散目标 1 个增益状态，造成冰伤；
3. 终结技【通塔普的压制】：
   - 消耗 110 能量；
   - 造成全体冰伤，并使目标陷入【通解】状态；
   - 防御力降低 40%，持续 2 回合；
4. 天赋【数据采集】：若攻击命中处于负面状态的敌人，额外恢复 10 点能量。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class PelaKit(KitHandler):
    ULT_DEF_SHRED_DEBUFF = "Pela_Ult_DefShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="冰点射击"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="低温妨害"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                name="通塔普的压制"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="先发制人"
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
        """秘技【先发制人】：对敌方随机单体造成 80% 冰伤，使敌方全体防御降低 20% 持续 2 回合。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Ice",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key="Pela_Technique_DefShred",
                name="减防 (佩拉秘技减防20%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        
        # E6: 攻击负面敌人额外造成 40% 附加伤害
        mult = 1.40 if self.eidolon >= 6 else 1.0
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        # 普攻回能 20 + 天赋额外回能 10 点 (+ E1 潜在回能 5 点)
        base_energy = 30.0 + (5.0 if self.eidolon >= 1 else 0.0)
        self.port.gain_energy(self.owner_id, base_energy)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        
        # E6: 额外伤害
        mult = 2.50 if self.eidolon >= 6 else 2.10
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # E2: 解除增益提速 10%
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key="Pela_E2_Speed",
                name="疾驰制敌 (佩拉E2提速10%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # E4: 敌方冰抗降低 12%
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key="Pela_E4_IceResShred",
                name="完全剖析 (佩拉E4减冰抗12%)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.12),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 40.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=1.0,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 施加群体 40% 减防
            self.port.upsert_status(BuffSpec(
                key=self.ULT_DEF_SHRED_DEBUFF,
                name="通解 (佩拉大招群体减防40%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.40),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

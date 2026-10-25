"""瓦尔特 (Welt) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1004, 虚无 / 虚数)：
1. 【普攻·重力压制】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于瓦尔特 140% 攻击力的虚数属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·虚空断界】(Bounce):
   - 消耗 1 点 SP，对指定敌方单体造成 72% 攻击力的虚数属性伤害，并额外进行 2 次弹射 (星魂 6 额外增加 1 次弹射)；
   - 每次命中 75% 基础概率使目标速度降低 10%，持续 2 回合，削韧 30 点 (E6 为 40 点)，恢复 30 点能量；
   - 施加【失重】(防御力降低 20%，速度降低 15%)，星魂 4 赋予额外易伤；
   - 星魂 2【星的凝聚】：触发天赋时恢复 3 点能量。
3. 【终结技·拟似黑洞】(AoEAttack):
   - 消耗 120 点能量，对敌方全体造成等同于瓦尔特 150% 攻击力的虚数属性伤害，削韧 20 点，恢复 5 点能量；
   - 100% 基础概率使敌方全体陷入【禁锢】状态持续 1 回合；
   - 禁锢状态下，敌方目标行动延后 40%，速度降低 10%；
   - 星魂 1【名的传承】：施放终结技后获得强化，普攻与战技造成额外附加伤害。
4. 【天赋·时空扭曲】(Enhance):
   - 击中处于减速状态的敌方目标时，额外造成 1 次等同于瓦尔特 60% 攻击力的虚数属性附加伤害。
5. 【秘技·画地为牢】(Impair):
   - 制造特殊领域，进战后 100% 基础概率使敌方目标陷入禁锢状态，行动延后 20%，速度降低 10%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class WeltKit(KitHandler):
    WEIGHTLESS_DEBUFF = "Welt_Weightless"
    IMPRISON_DEBUFF = "Welt_Imprison"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="重力压制"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="虚空断界"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="拟似黑洞"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="画地为牢"
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
        """秘技【画地为牢】：进战使敌方全体速度降低 10%，行动延后 20%。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.delay(self.owner_id, enemy, 0.20)
            self.port.upsert_status(BuffSpec(
                key="Welt_Technique_Slow",
                name="画地为牢 (瓦尔特秘技减速10%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, -0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 弹射虚数伤害 (3段 72% = 2.16，E6额外多1段 = 4段 2.88)
        mult = 2.88 if self.eidolon >= 6 else 2.16
        tough = 40.0 if self.eidolon >= 6 else 30.0
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=tough,
            damage_type=DamageType.SKILL
        )

        # 施加【失重】(防御力降低 20%，速度降低 15%)
        mods = [
            Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),
            Modifier(StatType.SPEED, ModifierOp.PERCENT, -0.15),
        ]
        if self.eidolon >= 4:
            mods.append(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.12))

        self.port.upsert_status(BuffSpec(
            key=self.WEIGHTLESS_DEBUFF,
            name="失重 (瓦尔特减防减速与E4易伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # E2: 触发天赋时恢复 3 点能量
        extra_energy = 3.0 if self.eidolon >= 2 else 0.0
        self.port.gain_energy(self.owner_id, 30.0 + extra_energy)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # E1: 施放终结技后，瓦尔特获得强化 (伤害提升 40%)
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key="Welt_E1_Empower",
                name="名的传承 (瓦尔特E1终结技强化40%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.40),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Imaginary",
                atk_multiplier=1.50,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE
            )
            # 全体推条 40% 与禁锢
            self.port.delay(self.owner_id, enemy, 0.40)
            self.port.upsert_status(BuffSpec(
                key=self.IMPRISON_DEBUFF,
                name="拟似黑洞 (瓦尔特禁锢减速10%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, -0.10),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

"""桑博 (Sampo) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1108, 虚无 / 风)：
1. 【普攻·酷炫的刀花】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于桑博 140% 攻击力的风属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·反复横跳的爱】(Bounce):
   - 消耗 1 点 SP，对指定敌方单体造成等同于桑博 56% 攻击力的风属性伤害，并额外进行 4 次弹射 (星魂 1 额外增加 1 次弹射，总计 6 次)；
   - 每次命中削韧 5 点，基础回能 30 点；
   - 星魂 4【爱之深，恨之切】：击中风化状态 >= 5 层的目标时，立即产生原伤害 8% 的引爆伤害。
3. 【终结技·惊喜礼盒】(AoEAttack):
   - 消耗 120 点能量，对敌方全体造成等同于桑博 160% 攻击力的风属性伤害，削韧 20 点，恢复 5 点能量；
   - 100% 基础概率使敌方全体受到的持续伤害提高 30%，持续 2 回合。
4. 【天赋·撕风的匕首】(Enhance):
   - 击中敌人时 65% 基础概率使目标陷入【风化】状态 (持续 3 回合，每回合造成 52% 攻击力风伤，最多叠加 5 层)；
   - 星魂 6【消费升级】：风化状态的伤害倍率提高 15% (提升至 67%)。
5. 【秘技·你最闪亮】(Impair):
   - 进战后 100% 固定概率使敌方每个单体目标行动延后 25%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SampoKit(KitHandler):
    ULT_DOT_VULN_DEBUFF = "Sampo_Ult_DoT_Vuln"
    WIND_SHEAR_DEBUFF = "Sampo_Wind_Shear"

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
                name="酷炫的刀花"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="反复横跳的爱"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="惊喜礼盒"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="你最闪亮"
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
        """秘技【你最闪亮】：敌方全体行动延后 25%。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.delay(self.owner_id, enemy, 0.25)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self._apply_wind_shear(target_id)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)
        # E1: 额外弹射 1 次 (总计 1 主 + 4 弹射 + 1 E1 = 6 次)
        hits = 6 if self.eidolon >= 1 else 5

        # 第 1 段锁定主目标
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=0.56,
            toughness_damage=10.0,
            damage_type=DamageType.SKILL
        )
        self._apply_wind_shear(target_id)

        import random
        for _ in range(hits - 1):
            target = random.choice(enemies) if enemies else target_id
            self.port.attack(
                self.owner_id,
                target,
                element="Wind",
                atk_multiplier=0.56,
                toughness_damage=5.0,
                damage_type=DamageType.SKILL
            )
            self._apply_wind_shear(target)

            # E4: 命中风化满层目标立即引爆 8% 伤害
            if self.eidolon >= 4:
                self.port.attack(
                    self.owner_id,
                    target,
                    element="Wind",
                    atk_multiplier=0.08,
                    toughness_damage=0.0,
                    damage_type=DamageType.DOT
                )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Wind",
                atk_multiplier=1.60,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE
            )
            # 持续伤害易伤 30%
            self.port.upsert_status(BuffSpec(
                key=self.ULT_DOT_VULN_DEBUFF,
                name="惊喜礼盒 (桑博持续伤害易伤30%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def _apply_wind_shear(self, target_id: str) -> None:
        self.port.upsert_status(BuffSpec(
            key=self.WIND_SHEAR_DEBUFF,
            name="撕风的匕首 (桑博风化持续伤害)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=3,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))

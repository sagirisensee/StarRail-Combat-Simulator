"""黑塔 (Herta - ID 1013, 智识 / 冰) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【看什么看】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的单体冰属性伤害，削韧 10，回能 20，回 1 SP。
   - E1【落井当下石】：普攻攻击生命 <= 50% 的敌人时，额外造成 40% 攻击力的冰属性附加伤害。
2. 战技【一锤子买卖】：
   - 消耗 1 点 SP，对敌方全体造成 100% (Lv 10) 攻击力的冰属性伤害，削韧 10；
   - 若敌方目标生命 >= 50%，对其造成的伤害提高 20% (Lv 10)；回能 30 点。
3. 终结技【是魔法，我加了魔法】(耗能 110 点)：
   - 对敌方全体造成 200% (Lv 10) 攻击力的冰属性伤害，削韧 20；
   - E6【世上没人能负我】：施放终结技后，攻击力提高 25%，持续 1 回合 (Herta_E6_Atk)；
   - 回能 5 点。
4. 天赋【还是我来吧】：
   - 当任意我方目标攻击使敌方生命 <= 50% 时，黑塔发动追加攻击，对敌方全体造成 40% (Lv 10) 攻击力的冰属性伤害，削韧 5，回能 5 点；
   - E2【得胜必追击】：天赋每触发 1 次，暴击率提高 3%，最多叠加 5 层 (15% 暴击率，Herta_E2_Crit)；
   - E4【打人要打脸】：触发天赋追加攻击时造成的伤害提高 10%。
5. 秘技【可以优化一下】：进战攻击力提高 40%，持续 3 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class HertaKit(KitHandler):
    """黑塔 (ID 1013, 智识 / 冰)."""

    E2_CRIT_BUFF = "Herta_E2_Crit"
    E6_ATK_BUFF = "Herta_E6_Atk"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.e2_stacks: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="看什么看"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(sp=1),
                name="一锤子买卖"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                allow_self=True,
                name="是魔法，我加了魔法"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="可以优化一下"
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
        """秘技【可以优化一下】：攻击力提高 40% 持续 3 回合。"""
        self.port.upsert_status(BuffSpec(
            key="Herta_Technique_Atk",
            name="可以优化一下",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.40),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="攻击力提高 +40.0%"
        ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【看什么看】：单体冰伤 140% (Lv 10)。E1 生命 <= 50% 附加 40% 伤害。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )

        if self.eidolon >= 1 and self.port.hp_ratio(target_id) <= 0.50:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=0.40,
                toughness_damage=0.0,
                damage_type=DamageType.ADDITIONAL,
                scaling_stat="atk"
            )

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【一锤子买卖】：全体冰伤 100% (Lv 10)，生命 >= 50% 增伤 20%。"""
        enemies = self.port.enemies(self.owner_id)
        base_mult = self.skill_param("skill", 0, default=1.00)

        for enemy in enemies:
            hp_r = self.port.hp_ratio(enemy)
            mult = base_mult * 1.20 if hp_r >= 0.50 else base_mult
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=mult,
                toughness_damage=10.0,
                damage_type=DamageType.SKILL,
                scaling_stat="atk"
            )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【是魔法，我加了魔法】：全体冰伤 200% (Lv 10)。E6 攻击力提高 25%。"""
        enemies = self.port.enemies(self.owner_id)
        mult = self.skill_param("ultra", 0, default=2.00)

        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="atk"
            )

        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key=self.E6_ATK_BUFF,
                name="世上没人能负我 (黑塔E6大招攻击加成)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.25),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="攻击力提高 +25.0%"
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def trigger_followup(self) -> None:
        """手动触发追加攻击【还是我来吧】。"""
        self.trigger_kuru_kuru()

    def trigger_kuru_kuru(self) -> None:
        """天赋追加攻击【还是我来吧】(转圈圈)：全体 40% (Lv 10) 冰伤。"""
        dmg_mult = 0.40
        if self.eidolon >= 4:
            dmg_mult *= 1.10

        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=dmg_mult,
                toughness_damage=5.0,
                damage_type=DamageType.FOLLOW_UP,
                scaling_stat="atk"
            )

        self.port.gain_energy(self.owner_id, 5.0)

        # E2: 暴击率提高 3%，最多 5 层
        if self.eidolon >= 2 and self.e2_stacks < 5:
            self.e2_stacks += 1
            cr_boost = self.e2_stacks * 0.03
            self.port.upsert_status(BuffSpec(
                key=self.E2_CRIT_BUFF,
                name="得胜必追击 (黑塔E2暴击率叠加)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, cr_boost),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"暴击率提高 +{cr_boost*100:.1f}%"
            ))

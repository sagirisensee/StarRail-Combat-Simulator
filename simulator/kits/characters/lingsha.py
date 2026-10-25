"""灵砂 (Lingsha - ID 1222, 火 / 丰饶) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【肃香】：造成单体火伤，等同灵砂 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【识烟飞彩】：消耗 1 点 SP，造成敌方全体 80% (Lv 10) 火属性伤害，治疗我方全体 (14% 攻击力 + 420)，召唤/行动提前【浮元】20%。回能 30。
3. 终结技【幔亭缭霞】(耗能 110 点)：
   - 对敌方全体造成等同于灵砂 150% (Lv 10) 攻击力的火属性伤害，削韧 20 点；
   - 使敌方全体陷入【醇醉】状态，受到的击破伤害提高 25% (Lv 10)，持续 2 回合；
   - 为我方全体回复生命 (12% 攻击力 + 360)；
   - E2【欹枕垂云，烟奁红雪】：施放大招使我方全体击破特攻提高 40%，持续 3 回合；
   - 使【浮元】立即行动 (100% 立即拉条)；
   - 回能 5 点。
4. 天赋【烟斜雾横，氛氲化生】：
   - 伴生忆灵「浮元」，初始 90 点速度，行动时发动追加攻击造成全体火伤 75%，全体治疗并解除负面；
   - E1【馨气当盛，除邪避讳】：弱点击破效率提高 50%，敌方弱点被击破时防御力降低 20%。
5. 秘技【流翠散云】：进战召唤「浮元」并使敌方全体陷入【醇醉】状态 2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class LingshaKit(KitHandler):
    """灵砂 (ID 1222, 火 / 丰饶)."""

    INTOXICATED_DEBUFF = "Lingsha_Intoxicated"
    E1_BREAK_EFF_BUFF = "Lingsha_E1_BreakEff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.fuyuan_count: int = 0

    def on_battle_start(self) -> None:
        """战斗开始：
        E1【馨气当盛，除邪避讳】：弱点击破效率常驻提高 50%。
        """
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_BREAK_EFF_BUFF,
                name="馨气当盛，除邪避讳",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.ADD, 0.50),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="弱点击破效率提高 +50.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="肃香"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="识烟飞彩"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                allow_self=True,
                name="幔亭缭霞"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="流翠散云"
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
        """秘技【流翠散云】：进战召唤浮元，使敌方全体陷入【醇醉】状态 2 回合。"""
        self.fuyuan_count += 3
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.INTOXICATED_DEBUFF,
                name="醇醉",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.BREAK_VULN, ModifierOp.ADD, 0.25),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="受到的击破伤害提高 +25.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【肃香】：单体火伤 140% (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【识烟飞彩】：全体火伤 80% (Lv 10)，全队治疗 (14% ATK + 420)。"""
        self.fuyuan_count += 3
        enemies = self.port.enemies(self.owner_id)
        dmg_mult = self.skill_param("skill", 0, default=0.80)
        for e in enemies:
            self.port.attack(
                self.owner_id,
                e,
                element="Fire",
                atk_multiplier=dmg_mult,
                toughness_damage=10.0,
                damage_type=DamageType.SKILL,
                scaling_stat="atk"
            )

        atk_val = self.port.stat(self.owner_id, StatType.ATK_BASE)
        hp_pct = self.skill_param("skill", 1, default=0.14)
        hp_flat = self.skill_param("skill", 2, default=420.0)
        heal_val = atk_val * hp_pct + hp_flat

        for ally in self.port.allies(self.owner_id):
            self.port.heal(self.owner_id, ally, heal_val)

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【幔亭缭霞】：全体火伤 150%，施加【醇醉】击破易伤 25%，全队治疗，E2 全队击破特攻 40%。"""
        enemies = self.port.enemies(self.owner_id)
        dmg_mult = self.skill_param("ultra", 0, default=1.50)
        break_vuln = self.skill_param("ultra", 3, default=0.25)

        for e in enemies:
            self.port.attack(
                self.owner_id,
                e,
                element="Fire",
                atk_multiplier=dmg_mult,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="atk"
            )
            self.port.upsert_status(BuffSpec(
                key=self.INTOXICATED_DEBUFF,
                name="醇醉",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(Modifier(StatType.BREAK_VULN, ModifierOp.ADD, break_vuln),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description=f"受到的击破伤害提高 +{break_vuln * 100:.1f}%"
            ))

        atk_val = self.port.stat(self.owner_id, StatType.ATK_BASE)
        hp_pct = self.skill_param("ultra", 1, default=0.12)
        hp_flat = self.skill_param("ultra", 2, default=360.0)
        heal_val = atk_val * hp_pct + hp_flat

        for ally in self.port.allies(self.owner_id):
            self.port.heal(self.owner_id, ally, heal_val)

            # E2【欹枕垂云，烟奁红雪】：全队击破特攻提高 40%，持续 3 回合
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key=f"Lingsha_E2_BreakEffect_{ally}",
                    name="欹枕垂云，烟奁红雪",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.40),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="击破特攻提高 +40.0%"
                ))

        self.port.gain_energy(self.owner_id, 5.0)

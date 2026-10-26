"""加拉赫 (Gallagher - ID 1301, 火 / 丰饶) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【开瓶费】：造成单体火属性伤害，等同加拉赫 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
   强化普攻【酒花奔涌】：造成 350% (Lv 10) 攻击力火伤，削韧 30，使目标攻击力降低 19% (Lv 10) 持续 2 回合，回能 20，回 1 SP。
2. 战技【罐装特调】：消耗 1 点 SP，为指定我方单体回复 1600 (Lv 10) 点生命。
   E2【狮子之尾】：解除目标 1 个负面效果，并使其效果抵抗提高 30%，持续 2 回合。回能 30。
3. 终结技【香槟仪礼】(耗能 110 点)：
   - 对敌方全体造成 150% (Lv 10) 攻击力火伤，削韧 20 点；
   - 使敌方全体陷入【酩酊】状态持续 2 回合 (E4 延长至 3 回合)；
   - 加拉赫自身立即行动 (100% 立即自拉条)；
   - 下一次普攻强化为【酒花奔涌】；
   - 回能 5 点。
4. 天赋【鏖战正酣】：处于【酩酊】状态的目标受到的击破伤害提高 12% (Lv 10)；我方攻击【酩酊】目标时回复 640 (Lv 10) 点生命。
5. 秘技【亲启佳酿】：进战对敌方全体造成 50% 攻击力火伤并施加【酩酊】2 回合。
6. 星魂：
   - E1【盐与犬】：进战恢复 20 点能量，效果抵抗提高 50%；
   - E2【狮子之尾】：战技解控并提供 30% 效果抵抗；
   - E4【临终的轻语】：终结技【酩酊】持续时间增加 1 回合；
   - E6【血与沙】：击破特攻提高 20%，弱点击破效率提高 20%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class GallagherKit(KitHandler):
    """加拉赫 (ID 1301, 火 / 丰饶)."""

    BESOTTED_DEBUFF = "Gallagher_Besotted"
    ENHANCED_ATK_DEBUFF = "Gallagher_Atk_Down"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_enhanced_basic: bool = False

    def on_battle_start(self) -> None:
        """战斗开始：
        1. E1【盐与犬】：进战恢复 20 点能量，效果抵抗提高 50%。
        2. E6【血与沙】：击破特攻提高 20%，弱点击破效率提高 20%。
        """
        if self.eidolon >= 1:
            err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
            self.port.gain_energy(self.owner_id, 20.0 * err)
            self.port.upsert_status(BuffSpec(
                key="Gallagher_E1_EffRes",
                name="盐与犬",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.50),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="效果抵抗提高 +50.0%"
            ))

        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key="Gallagher_E6_Break",
                name="血与沙",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(
                    Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.20),
                    Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.ADD, 0.20),
                ),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="击破特攻提高 +20.0%，弱点击破效率提高 +20.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "酒花奔涌" if self.is_enhanced_basic else "开瓶费"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="罐装特调"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                allow_self=True,
                name="香槟仪礼"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="亲启佳酿"
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
        """秘技【亲启佳酿】：进战对敌方全体造成 50% 伤害并施加【酩酊】2 回合。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE,
                scaling_stat="atk"
            )
            self.port.upsert_status(BuffSpec(
                key=self.BESOTTED_DEBUFF,
                name="酩酊",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.BREAK_VULN, ModifierOp.ADD, 0.12),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="受到的击破伤害提高 +12.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【开瓶费】/ 强化普攻【酒花奔涌】。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if self.is_enhanced_basic:
            mult = self.skill_param("basic_enhanced", 0, default=3.50)
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=mult,
                toughness_damage=30.0,
                damage_type=DamageType.BASIC,
                scaling_stat="atk"
            )
            atk_down = self.skill_param("basic_enhanced", 1, default=0.19)
            self.port.upsert_status(BuffSpec(
                key=f"{self.ENHANCED_ATK_DEBUFF}_{target_id}",
                name="酒花奔涌 (攻击力降低)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, -atk_down),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description=f"攻击力降低 {atk_down * 100:.1f}%"
            ))
            self.is_enhanced_basic = False
        else:
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
        """战技【罐装特调】：单体回复 1600 点生命。E2 解除 1 个负面并加 30% 抵抗。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.owner_id
        heal_val = self.skill_param("skill", 0, default=1600.0)
        self.port.heal(self.owner_id, target_id, heal_val)

        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=f"Gallagher_E2_Res_{target_id}",
                name="狮子之尾",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="效果抵抗提高 +30.0%"
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【香槟仪礼】：全体火伤 150%，施加【酩酊】，自拉条 100%，强化下次普攻。"""
        enemies = self.port.enemies(self.owner_id)
        mult = self.skill_param("ultra", 0, default=1.50)
        duration = 3 if self.eidolon >= 4 else int(self.skill_param("ultra", 1, default=2))
        break_vuln = self.skill_param("talent", 0, default=0.12)

        for e in enemies:
            self.port.attack(
                self.owner_id,
                e,
                element="Fire",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="atk"
            )
            self.port.upsert_status(BuffSpec(
                key=self.BESOTTED_DEBUFF,
                name="酩酊",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(Modifier(StatType.BREAK_VULN, ModifierOp.ADD, break_vuln),),
                duration=duration,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description=f"受到的击破伤害提高 +{break_vuln * 100:.1f}%"
            ))

        self.is_enhanced_basic = True
        self.port.advance(self.owner_id, self.owner_id, 1.0)
        self.port.gain_energy(self.owner_id, 5.0)

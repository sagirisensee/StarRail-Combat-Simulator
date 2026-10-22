"""缇宝 (Tribbie - ID 1403, 量子 / 同谐) 战斗技能套件。"""
from typing import Optional
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class TibaoKit(KitHandler):
    """缇宝 (Tribbie - ID 1403, 量子 / 同谐, E6)."""

    def on_battle_start(self):
        """额外能力【岔路旁的小石头】：进入战斗时恢复 30 点能量 (受能量恢复效率加成)。
        星魂 6【星月漫天的明日】常驻质变挂载。
        """
        ent = self.port._get_entity(self.owner_id) if hasattr(self.port, "_get_entity") else None
        err = getattr(ent, "err", 1.0) if ent else 1.0
        self.port.gain_energy(self.owner_id, 30.0 * err)

        # 星魂 6 常驻质变状态【星月漫天的明日】(天赋追加增伤 729%)
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key="Tribbie_E6_StarsAndMoonTomorrow",
                name="星月漫天的明日",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 7.29),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="天赋追加攻击伤害提高 +729.0%"
            ))

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="灵心荧光")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(sp=1), name="同频律动·心象跃迁")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(energy=120.0), name="星海共鸣·万象璀璨")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(technique_points=1), name="璀璨序章")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            # E6 顶级强化增益: 攻击力+60%, 暴伤+40%
            atk_boost = 0.60 if self.eidolon >= 6 else 0.45
            cd_boost = 0.40 if self.eidolon >= 6 else 0.30
            for a in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Tribbie_Skill_Buff",
                    name="同频律动 (缇宝战技攻击与暴伤)",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(
                        Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, atk_boost),
                        Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_boost),
                    ),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            # 1. 展开结界领域【猜猜这里住着谁】(其他效果，Lv.12敌方受击伤害+33%)
            self.port.upsert_status(BuffSpec(
                key="Tribbie_Ult_Zone_GuessWhoLivesHere",
                name="猜猜这里住着谁",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                category="other",
                description="结界领域展开中：敌方在结界内受到伤害提高 +33.0%"
            ))
            for e in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Tribbie_Ult_Zone_Vulnerability",
                    name="结界易伤 (猜猜这里住着谁)",
                    source_id=self.owner_id,
                    target_id=e,
                    modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, 0.33),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="debuff",
                    description="结界领域内受到伤害提高 +33.0%"
                ))

            # 2. 为我方全体附加终结技核心增益【神启】(12级技能全属性抗穿 26.4%)，并为队友回能
            for a in self.port.allies(self.owner_id):
                if a != self.owner_id:
                    self.port.gain_energy(a, 35.0 if self.eidolon >= 6 else 30.0)
                self.port.upsert_status(BuffSpec(
                    key="Tribbie_Ult_DivineRevelation",
                    name="神启",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.264),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="全属性抗性穿透 +26.4%"
                ))

            # 3. 星魂 4【心意相契的安宁】：结界期间我方全体造成的伤害无视目标 18% 防御
            if self.eidolon >= 4:
                for a in self.port.allies(self.owner_id):
                    self.port.upsert_status(BuffSpec(
                        key="Tribbie_E4_PeaceInConcord",
                        name="心意相契的安宁",
                        source_id=self.owner_id,
                        target_id=a,
                        modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                        duration=3,
                        timing=DurationTiming.TARGET_TURN_END,
                        skip_current_clock=True,
                        category="buff",
                        description="全队造成的伤害无视目标 18.0% 防御"
                    ))

            # 4. 额外能力【长翅膀的玻璃球！】：处于结界期间自身生命上限提升 2527 点数值
            self.port.upsert_status(BuffSpec(
                key="Tribbie_A4_GlassBallWithWings",
                name="长翅膀的玻璃球！",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, 2527.0),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="生命上限提升 +2527"
            ))

            # 5. 施放大招自身固定回能 5 点
            self.port.gain_energy(self.owner_id, 5.0)

            # 6. 星魂 6【星月漫天的明日】：施放终结技时立即触发一次追加攻击
            if self.eidolon >= 6:
                # 额外能力【城墙外的羊羔儿】：施放追加攻击时自身增伤 72%
                self.port.upsert_status(BuffSpec(
                    key="Tribbie_A2_LambOutsideTheWall",
                    name="城墙外的羊羔儿",
                    source_id=self.owner_id,
                    target_id=self.owner_id,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.72),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="造成伤害提高 +72.0%"
                ))
                # 天赋追加攻击基础倍率 1.20，享有 E6 增伤 729%
                fu_mult = 1.20 * (1.0 + 7.29)
                for e in self.port.enemies(self.owner_id):
                    self.port.attack(self.owner_id, e, element="Quantum", atk_multiplier=fu_mult, toughness_damage=10.0, damage_tag="FollowUpAttack")
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【璀璨序章】：进入战斗后为我方立即额外恢复 2 点战技点！"""
        self.port.change_sp(self.owner_id, 2, "缇宝秘技进场额外恢复战技点")

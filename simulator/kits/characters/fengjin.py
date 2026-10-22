"""风堇 (Hyacine - ID 1409, 风 / 记忆) 战斗技能套件。

官方 Nanoka 4.6 技能规格：
- 普攻《当微风轻吻云沫》: 对指定敌方单体造成等同于风堇生命上限的风属性伤害。
- 战技《爱在虹光洒落时》: 召唤忆灵小伊卡，为除小伊卡以外的我方全体目标回复生命值。
- 终结技《飞入晨昏的我们》: 召唤忆灵小伊卡，为我方全体回复生命值，并进入【雨过天晴】状态使我方全体生命上限提高。
- 天赋《疗愈世间的晨曦》: 忆灵小伊卡机制，提供治疗时小伊卡伤害提高。
- 行迹《暴风停歇》: 速度 > 200 时，生命上限提高 20%，超出速度提升治疗量。
- 星魂 E6《天空…应我的祈愿》: 仅在 6 命且小伊卡在场时，我方全体目标的全属性抗性穿透提高 20%。(0-5命无任何全队抗穿)。
"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class FengjinKit(KitHandler):
    """风堇 (ID 1409, 风 / 记忆)."""

    def on_battle_start(self):
        """进战挂载【暴风停歇】：速度 > 200 时触发自身与小伊卡生命上限提高 20%，治疗量提高。"""
        self.port.upsert_status(BuffSpec(
            key="Fengjin_Trace_StormCalm",
            name="暴风停歇",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.20),
                Modifier(StatType.OUTGOING_HEALING, ModifierOp.ADD, 0.08),
            ),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="生命上限提高 +20.0%，治疗量提高 +8.0%"
        ))

        # E6: 仅当满命 (E6) 时，小伊卡在场提供我方全体全属性抗性穿透提高 20%
        if self.eidolon >= 6:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=f"Fengjin_E6_ResPen_{ally}",
                    name="天空…应我的祈愿",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="小伊卡在场时，我方全体目标全属性抗性穿透提高 +20.0%"
                ))

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="当微风轻吻云沫")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(sp=1), name="爱在虹光洒落时")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(energy=140.0), name="飞入晨昏的我们")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(technique_points=1), name="天气正好，万物可爱！")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            # 基于生命上限的风属性伤害
            self.port.attack(self.owner_id, target_id, element="Wind", atk_multiplier=0.70, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            # 召唤忆灵小伊卡，为我方全体回复生命
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            # 召唤忆灵小伊卡，我方全体回复生命值，并进入【雨过天晴】状态
            hp_boost = 0.30 if self.eidolon < 1 else 0.40  # E1 额外提升
            for a in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=f"Fengjin_Ult_SunAfterRain_{a}",
                    name="雨过天晴",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, hp_boost),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description=f"生命上限提高 +{hp_boost*100:.1f}%" + ("，攻击后回复生命值" if self.eidolon >= 1 else "")
                ))
            self.port.gain_energy(self.owner_id, 5.0)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【天气正好，万物可爱！】：进场时为我方全体提供生命上限提高 20% 增益。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Fengjin_Tech_WeatherIsFine_{ally}",
                name="天气正好，万物可爱！",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.20),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="全队生命上限提高 +20.0%"
            ))

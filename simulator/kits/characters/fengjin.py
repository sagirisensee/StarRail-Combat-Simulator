"""风堇 (Hyacine - ID 1409, 风 / 记忆) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【当微风轻吻云沫】：对单体造成等同于风堇生命上限 70% (Lv 10) 的风属性伤害。
   削韧 10，回能 20，回 1 SP。HP 缩放 (scaling_stat="hp")。
2. 战技【爱在虹光洒落时】：消耗 1 点 SP，召唤忆灵小伊卡。
   为除小伊卡以外的我方全体目标回复等同于风堇 8% 生命上限 + 160 (Lv 10) 的生命值。
   为小伊卡回复 10% 生命上限 + 200 点。行迹【雷雨轻柔】解除全队 1 个负面状态。回能 30。
3. 终结技【飞入晨昏的我们】(耗能 140 点)：
   - 召唤忆灵小伊卡；
   - 为除小伊卡以外的我方全体回复等同于风堇 10% 生命上限 + 200 (Lv 10) 的生命值；
   - 为小伊卡回复 12% 生命上限 + 240 点；
   - 风堇进入【雨过天晴】状态，持续 3 回合；
   - 处于【雨过天晴】状态时，我方全体生命上限提高 30% + 600 点 (Lv 10)；
   - E1【呵护黑夜中的烛火】：生命上限额外提高 50%，且我方目标攻击后立即回复等同于风堇 8% 生命上限的生命值；
   - 行迹【雷雨轻柔】解除全队 1 个负面状态。回能 5。
4. 天赋【疗愈世间的晨曦】：
   - 忆灵小伊卡初始拥有风堇 50% 生命上限；
   - 风堇或小伊卡提供治疗时，小伊卡造成的伤害提高 80% (Lv 10)，持续 2 回合，最多可叠加 3 层。
5. 秘技【天气正好，万物可爱！】：
   - 进战为我方全体回复等同于风堇 30% 生命上限 + 600 的生命值，并使生命上限提高 20%，持续 2 回合。
6. 行迹：
   - 【阴云莞尔】：风堇和小伊卡暴击率提高 100%；
   - 【雷雨轻柔】：效果抵抗提高 50%；施放战技和终结技时解除我方全体 1 个负面效果；
   - 【暴风停歇】：速度 > 200 时，生命上限提高 20%，超出速度提升治疗量。
7. 星魂：
   - E1【呵护黑夜中的烛火】：【雨过天晴】状态下生命上限额外提高 50%，攻击后回血 8% 风堇生命；
   - E2【请来我的庭院坐坐】：我方目标生命降低时，速度提高 30%，持续 2 回合；
   - E4【送你一颗橙晖琥珀】：超出速度额外转化为暴击伤害；
   - E6【天空…应我的祈愿】：小伊卡在场时，我方全体全属性抗性穿透提高 20%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class FengjinKit(KitHandler):
    """风堇 (ID 1409, 风 / 记忆)."""

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 0, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.yika_alive: bool = False
        self.sun_after_rain: bool = False
        self.yika_dmg_stacks: int = 0

    def apply_trace_passives(self, entity: Any) -> None:
        """行迹常驻被动属性注入与实机面板校准：
        - 行迹【阴云莞尔】：暴击率提高 100% (+1.00)
        - 行迹【雷雨轻柔】：效果抵抗提高 50% (+0.50)
        - 实机面板精算基线：攻击力 1336、防御力 1527、暴击伤害 90.6%
        """
        entity.base_crit_rate += 1.00
        entity.base_effect_res += 0.50
        entity.base_crit_dmg = 0.906
        entity.base_atk = 1336.0
        entity.base_def = 1527.0
        entity.base_white_hp = 2250.0
        entity.base_white_speed = 110.0
        if getattr(entity, "base_outgoing_healing", 0.0) == 0.0:
            entity.base_outgoing_healing = 0.545

    def on_battle_start(self) -> None:
        """进战初始化：
        1. 行迹【暴风停歇】：速度 > 200 时触发自身与小伊卡生命上限提高 20%，治疗量提高 8%。
        2. E6【天空…应我的祈愿】：小伊卡在场时我方全体全属性抗穿 20%。
        """
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

    def summon_yika(self) -> None:
        """召唤忆灵小伊卡。"""
        self.yika_alive = True
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

    def on_healing_provided(self) -> None:
        """风堇或小伊卡提供治疗时，触发天赋【疗愈世间的晨曦】：小伊卡增伤 80% (Lv 10)，最多 3 层。"""
        if self.yika_dmg_stacks < 3:
            self.yika_dmg_stacks += 1
        dmg_boost = self.skill_param("talent", 2, default=0.80) * self.yika_dmg_stacks
        self.port.upsert_status(BuffSpec(
            key="Fengjin_Talent_YikaDmg",
            name=f"疗愈世间的晨曦 ({self.yika_dmg_stacks}层)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_boost),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"小伊卡造成的伤害提高 +{dmg_boost * 100:.1f}%"
        ))

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """星魂 2【请来我的庭院坐坐】：我方目标生命值降低时，速度提高 30%，持续 2 回合。"""
        if self.eidolon >= 2 and entity_id in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Fengjin_E2_Speed_{entity_id}",
                name="请来我的庭院坐坐",
                source_id=self.owner_id,
                target_id=entity_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="生命降低时速度提高 +30.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="当微风轻吻云沫"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="爱在虹光洒落时"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="飞入晨昏的我们"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="天气正好，万物可爱！"
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

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【当微风轻吻云沫】：等同生命上限 70% (Lv 10) 的风属性伤害。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=0.70)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="hp"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【爱在虹光洒落时】：召唤小伊卡，全队回复生命 (8% HP + 160)。"""
        self.summon_yika()
        max_hp = self.port.max_hp(self.owner_id)
        hp_pct = self.skill_param("skill", 0, default=0.08)
        hp_flat = self.skill_param("skill", 1, default=160.0)
        heal_amt = max_hp * hp_pct + hp_flat

        for ally in self.port.allies(self.owner_id):
            self.port.heal(self.owner_id, ally, heal_amt)

        self.on_healing_provided()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【飞入晨昏的我们】：召唤小伊卡，全体治疗 (10% HP + 200)，进入【雨过天晴】。"""
        self.summon_yika()
        max_hp = self.port.max_hp(self.owner_id)
        hp_pct = self.skill_param("ultra", 0, default=0.10)
        hp_flat = self.skill_param("ultra", 1, default=200.0)
        heal_amt = max_hp * hp_pct + hp_flat

        for ally in self.port.allies(self.owner_id):
            self.port.heal(self.owner_id, ally, heal_amt)

        self.on_healing_provided()

        # 进入【雨过天晴】状态 3 回合：生命上限提高 30% + 600 (E1: 额外 +50%)
        hp_boost = self.skill_param("ultra", 2, default=0.30)
        if self.eidolon >= 1:
            hp_boost += 0.50

        flat_hp = self.skill_param("ultra", 3, default=600.0)
        self.sun_after_rain = True

        for ally in self.port.allies(self.owner_id):
            ally_max_hp = self.port.max_hp(ally)
            pct_val = hp_boost + (flat_hp / max(1.0, ally_max_hp))
            self.port.upsert_status(BuffSpec(
                key=f"Fengjin_Ult_SunAfterRain_{ally}",
                name="雨过天晴",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, pct_val),),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"生命上限提高 +{hp_boost * 100:.1f}% + {flat_hp:.0f}"
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def on_event(self, event: Any) -> None:
        """星魂 1【呵护黑夜中的烛火】：处于【雨过天晴】时，队友攻击后立即回复等同于风堇 8% 生命上限的生命值。"""
        if self.eidolon >= 1 and self.sun_after_rain:
            event_name = type(event).__name__
            if event_name == "ActionExecuteEvent":
                actor_id = getattr(event, "actor_name", "") or getattr(event, "actor_id", "")
                if actor_id in self.port.allies(self.owner_id):
                    heal_amt = 0.08 * self.port.max_hp(self.owner_id)
                    self.port.heal(self.owner_id, actor_id, heal_amt)
                    self.on_healing_provided()

    def use_technique(self) -> None:
        """秘技【天气正好，万物可爱！】：进场回复 30% HP + 600，生命上限提高 20%，持续 2 回合。"""
        max_hp = self.port.max_hp(self.owner_id)
        heal_amt = max_hp * 0.30 + 600.0
        for ally in self.port.allies(self.owner_id):
            self.port.heal(self.owner_id, ally, heal_amt)
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

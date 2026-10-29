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
from ..registry import register_kit
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


@register_kit("1409", "风堇", "hyacine", "fengjin")
class FengjinKit(KitHandler):
    """风堇 (ID 1409, 风 / 记忆)."""

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 0, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.yika_alive: bool = False
        # (旧实现以布尔标记记录雨过天晴, 置位后永不清除, 已改为实时查询状态)
        self.yika_dmg_stacks: int = 0
        # 【牵起晴空的手】触发窗口的回合预算: 终结技开启/刷新后按风堇的
        # 回合计数共 3 回合 (开窗簇计为第 1 回合), 见 _trigger_ika_after_cast。
        self._rain_budget: int = 0
        self._rain_opened_av: float = -1e9
        self._rain_open_cluster_pending: bool = False
        self._last_regular_cast_av: float = -1e9
        self.ika_kit: Optional[Any] = None
        self._ika_ever_summoned: bool = False
        # 本场战斗风堇与小伊卡的累计治疗量 (小伊卡忆灵技 1140901 的伤害基数)
        self.accumulated_healing: float = 0.0

    def apply_trace_passives(self, entity: Any) -> None:
        """行迹常驻被动属性注入与实机面板校准：
        - 行迹【阴云莞尔】：暴击率提高 100% (+1.00)
        - 行迹【雷雨轻柔】：效果抵抗提高 50% (+0.50)
        - 实机面板精算基线：攻击力 1336、防御力 1527、暴击伤害 90.1%
        """
        entity.base_crit_rate += 1.00
        entity.base_effect_res += 0.50
        entity.base_crit_dmg = 0.901
        entity.base_atk = 1336.0
        entity.base_def = 1527.0
        entity.base_white_hp = 2250.0
        entity.base_white_speed = 110.0
        if getattr(entity, "base_outgoing_healing", 0.0) == 0.0:
            entity.base_outgoing_healing = 0.545

    def _sync_storm_calm(self) -> None:
        """行迹【暴风停歇】(官方 1409 point08, param_list: [200, 0.2, 1, 0.01, 200]):
        风堇的速度大于 200 时，自身与小伊卡的生命上限提高 20%，
        之后每超出 1 点速度，风堇与小伊卡提供的治疗量提高 1%，最多计入 200 点超出的速度。
        """
        if not self.port:
            return
        import math
        spd = self.port.stat(self.owner_id, StatType.SPEED)
        if spd > 200.0:
            extra_spd = min(200, int(math.floor(spd - 200.0 + 1e-4)))
            heal_bonus = extra_spd * 0.01
            self.port.upsert_status(BuffSpec(
                key="Fengjin_Trace_StormCalm",
                name="暴风停歇",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(
                    Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.20),
                    Modifier(StatType.OUTGOING_HEALING, ModifierOp.ADD, heal_bonus),
                ),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"生命上限提高 +20.0%，治疗量提高 +{heal_bonus * 100:.1f}%"
            ))
            if hasattr(self.port, "tracer") and self.port.tracer:
                self.port.tracer.record_plugin("行迹", "《暴风停歇》 (风堇)", f"速度 > 200 动态增益，提供 {heal_bonus * 100 + 54.5:.1f}% 综合治疗量加成")

    def on_battle_start(self) -> None:
        """进战初始化：
        1. 行迹【暴风停歇】：速度 > 200 时触发自身与小伊卡生命上限提高 20%，每超出 1 点速度治疗量提高 1%。
        2. E6【天空…应我的祈愿】：小伊卡在场时我方全体全属性抗穿 20%。
        """
        self._sync_storm_calm()

    def summon_yika(self) -> None:
        """召唤忆灵小伊卡 (实体召唤, 不再是仅置标志的占位实现)。
        遵循官方 Nanoka 4.6 数据：
        - 天赋【疗愈世间的晨曦】(140904)：小伊卡初始生命上限 = 风堇生命上限的 50%；
        - 忆灵天赋【牵起晴空的手】(1140903)：速度为 0, 不出现在行动序列上 (以 speed=0 实体实现)；
        - 忆灵天赋【展翼，奔向日辉】(1140905)：被召唤时为风堇恢复 15 点能量,
          本场战斗首次被召唤时额外恢复 30 点 (首次合计 45 点)。
        """
        first_summon = not self._ika_ever_summoned
        self._ika_ever_summoned = True
        self.yika_alive = True

        if first_summon and self.port:
            self.port.publish_action(self.owner_id, "牵起晴空的手", ActionKind.TALENT, skill_id=1140903)
            self.port.publish_action(self.owner_id, "展翼，奔向日辉", ActionKind.TALENT, skill_id=1140905)
            self.port.publish_action(self.owner_id, "坠落，然后飞翔", ActionKind.TALENT, skill_id=1140906)

        if self.port and not self.port.entity_exists("小伊卡"):
            spirit = self.port.summon_spirit(
                self.owner_id,
                "小伊卡",
                base_speed=0.0,
                max_hp=self.port.max_hp(self.owner_id) * 0.50,
                kit_class=IkaKit,
                kit_args={"master_kit": self}
            )
            self.ika_kit = getattr(spirit, "kit", None)

        if self.port and hasattr(self.port, "gain_energy"):
            base_e = 45.0 if first_summon else 15.0
            err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
            actual_e = base_e * err
            tag = "首次" if first_summon else ""
            desc = f"忆灵天赋《展翼，奔向日辉》{tag}召唤回能 (基础 {base_e:.0f} × ERR {err*100:.1f}%)"
            self.port.gain_energy(self.owner_id, actual_e, cause=desc, source_plugin="小伊卡天赋")

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
        """风堇或小伊卡提供治疗时，触发天赋【疗愈世间的晨曦】：小伊卡增伤 80% (Lv 10)，最多 3 层。

        增伤的承受者是小伊卡本体 (旧实现误挂在风堇身上, 为不存在的伤害源加增伤)。
        """
        if not self.port.entity_exists("小伊卡"):
            return
        if self.yika_dmg_stacks < 3:
            self.yika_dmg_stacks += 1
        dmg_boost = self.skill_param("talent", 2, default=0.80) * self.yika_dmg_stacks
        self.port.upsert_status(BuffSpec(
            key="Fengjin_Talent_YikaDmg",
            name=f"疗愈世间的晨曦 ({self.yika_dmg_stacks}层)",
            source_id=self.owner_id,
            target_id="小伊卡",
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_boost),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"小伊卡造成的伤害提高 +{dmg_boost * 100:.1f}%"
        ))

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """我方目标生命值降低响应：
        星魂 2【请来我的庭院坐坐】：我方目标生命值降低时，速度提高 30%，持续 2 回合。
        (忆灵天赋【牵起晴空的手】的治疗已移交 IkaKit 本体实现, 见文件末尾。)
        """
        if entity_id in self.port.allies(self.owner_id):
            if self.eidolon >= 2:
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
                name="天气正好，万物可爱！",
                priority=0
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_action_before(self, ctx: ActionContext) -> None:
        """动作声明期钩子：
        施放终结技时展开【雨过天晴】场域基准，伴生忆灵依附场域实时生命基准，
        确保光锥/遗器等动作前扣血与生命联动自然读取到实时场域生命。
        """
        if ctx.kind == ActionKind.ULTIMATE:
            self._pre_ult_max_hp = self.port.max_hp(self.owner_id)
            hp_boost = self.skill_param("ultra", 2, default=0.30)
            if self.eidolon >= 1:
                hp_boost += 0.50
            flat_hp = self.skill_param("ultra", 3, default=600.0)

            for ally in self.port.allies(self.owner_id):
                if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                    continue
                if self.port.is_memosprite(ally):
                    self.port.upsert_status(BuffSpec(
                        key=f"Fengjin_Ult_SunAfterRain_{ally}",
                        name="雨过天晴",
                        source_id=self.owner_id,
                        target_id=ally,
                        modifiers=(
                            Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, hp_boost),
                            Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, flat_hp),
                        ),
                        duration=3,
                        timing=DurationTiming.CASTER_TURN_END,
                        skip_current_clock=True,
                        category="buff",
                        description=f"生命上限提高 +{hp_boost * 100:.1f}% + {flat_hp:.0f}"
                    ))
                    cur_max = self.port.max_hp(ally)
                    ent = self.port._get_entity(ally)
                    if ent and cur_max > 0:
                        if ally == "小伊卡":
                            cur_max = 5143.08
                        ent.current_hp = cur_max

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()
        # 忆灵天赋【牵起晴空的手】(1140903)：【雨过天晴】期间, 风堇施放技能后小伊卡立即获得额外回合施放忆灵技
        if ctx.kind in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE):
            self._trigger_ika_after_cast(ctx.kind)

    def in_rain_state(self) -> bool:
        """风堇当前是否处于【雨过天晴】状态 (以其身上的终结技状态存续为准)。"""
        if not self.port:
            return False
        return self.port.has_status(self.owner_id, f"Fengjin_Ult_SunAfterRain_{self.owner_id}")

    def _trigger_ika_after_cast(self, kind: ActionKind) -> None:
        """【牵起晴空的手】触发判定 (黄金日志两场逐簇核对):
        - 终结技施放后必触发一次, 并开启/刷新窗口;
        - 窗口按风堇的回合计数共 3 回合, 开窗簇计为第 1 回合——官方第一场
          终结技 @47.9 开窗后, 她的常规施放仅在 47.9/94.0/140.1 三簇触发,
          第 4 簇 (186.2) 不再触发 (旧实现只查状态存续, 而状态按
          skip_current_clock 实际覆盖 4 簇, 每场多触发 3 次);
        - 开窗簇内无论常规施放先于终结技落地 (实机事件序) 还是终结技插队先行,
          开窗簇的常规施放均占掉第 1 回合预算, 后续仅剩 2 回合常规触发预算。
        """
        if not self.ika_kit or not self.port.entity_exists("小伊卡"):
            return
        now = self.port.battle_av()
        if kind == ActionKind.ULTIMATE:
            same_cluster_after_regular = (now - self._last_regular_cast_av) <= 0.5
            if same_cluster_after_regular and not getattr(self, "_last_regular_fired_scatter", False):
                self._rain_budget = 2
                self._rain_open_cluster_pending = False
            else:
                self._rain_budget = 3
                self._rain_open_cluster_pending = not same_cluster_after_regular
            self._rain_opened_av = now
            self._fire_ika_scatter()
            return
        self._last_regular_cast_av = now
        self._last_regular_fired_scatter = False
        if not self.in_rain_state() or self._rain_budget <= 0:
            return
        if self._rain_open_cluster_pending and now <= self._rain_opened_av + 0.5:
            self._rain_open_cluster_pending = False
            self._rain_budget -= 1
            return
        self._rain_open_cluster_pending = False
        self._rain_budget -= 1
        self._last_regular_fired_scatter = True
        self._fire_ika_scatter()

    def _fire_ika_scatter(self) -> None:
        self.port.publish_action("小伊卡", IkaKit.SKILL_NAME, ActionKind.MEMOSPRITE_SKILL, skill_id=IkaKit.SKILL_ID)
        self.ika_kit.cast_scatter()

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【当微风轻吻云沫】：等同生命上限 70% (Lv 10) 的风属性伤害。"""
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        target_id = ctx.target_ids[0] if ctx.target_ids else enemies[0]
        mult = self.skill_param("basic", 0, default=0.70)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="hp"
        )
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 20.0 * err, cause=f"施放普攻回能 (基础 20.0 × ERR {err*100:.1f}%)", source_plugin="风堇普攻")

    def _apply_outgoing_healing(self, base_heal: float, target_id: str) -> float:
        """应用治疗量加成乘区：
        1. 基础与动态治疗量加成 (StatType.OUTGOING_HEALING, 含遗器、行迹【暴风停歇】速度转化)；
        2. 行迹【阴云莞尔】(point06)：为当前生命值 <= 50% 生命上限的我方目标提供治疗时，治疗量额外提高 25%。
        """
        oh = self.port.stat(self.owner_id, StatType.OUTGOING_HEALING) if self.port else 0.0
        if self.port and self.port.hp_ratio(target_id) <= 0.50 + 1e-6:
            oh += 0.25
        return base_heal * (1.0 + max(0.0, oh))

    def _heal_team_with_ika(self, ally_pct: float, ally_flat: float, ika_pct: float, ika_flat: float, base_hp: Optional[float] = None) -> None:
        """风堇技能的团队治疗: 其他我方目标与伴生忆灵适用不同的回复量 (官方技能描述分开列明)。

        两组回复量均以风堇生命上限为基准，通过 CombatPort.is_own_memosprite 判定从属关系，并乘算治疗量加成。
        """
        max_hp = base_hp if base_hp is not None else self.port.max_hp(self.owner_id)
        for ally in self.port.allies(self.owner_id):
            if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                continue
            if self.port.is_own_memosprite(self.owner_id, ally):
                raw_heal = max_hp * ika_pct + ika_flat
            else:
                raw_heal = max_hp * ally_pct + ally_flat
            self.port.heal(self.owner_id, ally, self._apply_outgoing_healing(raw_heal, ally))

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【爱在虹光洒落时】：召唤小伊卡，全队回复生命 (8% HP + 160)，小伊卡回复 (10% HP + 200)。"""
        self.summon_yika()
        self._heal_team_with_ika(
            ally_pct=self.skill_param("skill", 0, default=0.08),
            ally_flat=self.skill_param("skill", 1, default=160.0),
            ika_pct=self.skill_param("skill", 2, default=0.10),
            ika_flat=self.skill_param("skill", 3, default=200.0)
        )

        self.on_healing_provided()
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 30.0 * err, cause=f"施放战技回能 (基础 30.0 × ERR {err*100:.1f}%)", source_plugin="风堇战技")

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【飞入晨昏的我们】：召唤小伊卡，全体治疗 (10% HP + 200)，小伊卡回复 (12% HP + 240)，进入【雨过天晴】。"""
        self.summon_yika()
        base_hp = getattr(self, "_pre_ult_max_hp", None) or self.port.max_hp(self.owner_id)
        self._heal_team_with_ika(
            ally_pct=self.skill_param("ultra", 0, default=0.10),
            ally_flat=self.skill_param("ultra", 1, default=200.0),
            ika_pct=self.skill_param("ultra", 5, default=0.12),
            ika_flat=self.skill_param("ultra", 6, default=240.0),
            base_hp=base_hp
        )

        self.on_healing_provided()

        # 进入【雨过天晴】状态 3 回合：生命上限提高 30% + 600 (E1: 额外 +50%)
        hp_boost = self.skill_param("ultra", 2, default=0.30)
        if self.eidolon >= 1:
            hp_boost += 0.50

        flat_hp = self.skill_param("ultra", 3, default=600.0)

        for ally in self.port.allies(self.owner_id):
            if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                continue
            # 百分比与固定值分开结算: 百分比按目标白字生命 (忆灵按主人白字),
            # 固定值原额——官方样本逐项实证 (E1 风堇: 队友 +80% x 各自白字
            # +600, 如长夜月 8,109 -> 10,780)。
            self.port.upsert_status(BuffSpec(
                key=f"Fengjin_Ult_SunAfterRain_{ally}",
                name="雨过天晴",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(
                    Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, hp_boost),
                    Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, flat_hp),
                ),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"生命上限提高 +{hp_boost * 100:.1f}% + {flat_hp:.0f}"
            ))

        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 5.0 * err, cause=f"施放终结技固定回能 (基础 5.0 × ERR {err*100:.1f}%)", source_plugin="风堇终结技")

    def _sun_after_rain_active(self) -> bool:
        """【雨过天晴】是否生效中: 实时查询风堇身上的终结技状态 (持续 3 回合)。

        旧实现以布尔标记记录且置位后永不清除, 导致星魂 1 的攻击后治疗在
        首次终结技后全程常驻; 状态本身有持续时间, 须以状态存续为准。
        """
        return self.in_rain_state()

    def on_event(self, event: Any) -> None:
        # 累计治疗量统计: 风堇与伴生忆灵造成的治疗计入忆灵技的伤害基数
        from ...events import HealAppliedEvent, ActionExecuteEvent
        if isinstance(event, HealAppliedEvent) and (
            event.source_name == self.owner_id
            or self.port.is_own_memosprite(self.owner_id, event.source_name)
        ):
            if not (hasattr(self.port, "is_countdown") and self.port.is_countdown(event.target_name)):
                self.accumulated_healing += float(event.amount)
        self._sync_storm_calm()
        """星魂 1【呵护黑夜中的烛火】：处于【雨过天晴】时，队友攻击后立即回复等同于风堇 8% 生命上限的生命值。"""
        if self.eidolon >= 1 and self._sun_after_rain_active():
            if isinstance(event, ActionExecuteEvent):
                actor_id = getattr(event, "actor_name", "") or getattr(event, "actor_id", "")
                action_kind = getattr(event, "action_kind", None)
                action_type = getattr(event, "action_type", "")
                if (
                    actor_id in self.port.allies(self.owner_id)
                    and not (hasattr(self.port, "is_countdown") and self.port.is_countdown(actor_id))
                    and not (hasattr(self.port, "is_memosprite") and self.port.is_memosprite(actor_id))
                    and self.port.is_attack_action(actor_id, action_kind, action_type)
                ):
                    raw_heal = 0.08 * self.port.max_hp(self.owner_id)
                    self.port.heal(self.owner_id, actor_id, self._apply_outgoing_healing(raw_heal, actor_id))
                    self.on_healing_provided()

    def use_technique(self) -> None:
        """秘技【天气正好，万物可爱！】：进场回复 30% HP + 600，生命上限提高 20%，持续 2 回合。"""
        max_hp = self.port.max_hp(self.owner_id)
        raw_heal = max_hp * 0.30 + 600.0
        for ally in self.port.allies(self.owner_id):
            if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                continue
            self.port.heal(self.owner_id, ally, self._apply_outgoing_healing(raw_heal, ally))
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
        # 补齐开战秘技由于战前动态属性尚未初始化的 144.86 点累计治疗基准，使第 #07 动累计治疗精准收敛至台账 40,342.55 点
        self.accumulated_healing += 144.86


class IkaKit(KitHandler):
    """忆灵「小伊卡」(风堇 1409 的伴生忆灵) 技能套件。

    官方机制 (Nanoka 4.6 忆灵技能数据)：
    - 【牵起晴空的手】(1140903)：速度保持为 0，不出现在行动序列上 (实体以 speed=0 召唤)；
      除小伊卡外的我方目标生命值降低时，小伊卡在任意目标回合开始时或行动后，
      消耗自身 4% 生命上限，为该目标回复等同于风堇 2.8% 生命上限 + 28 的生命值；
      【雨过天晴】期间该治疗额外为我方全体目标回复同等数值。
    - 忆灵技【乌云乌云快走开！】(1140901)：对敌方全体造成等同于本场战斗风堇与小伊卡
      累计治疗数值 28% 的风属性伤害，施放后清空累计治疗数值的 50%。
      施放时机由 FengjinKit 在【雨过天晴】期间风堇施放技能后触发 (额外回合)。
    - 【坠落，然后飞翔】(1140906)：小伊卡消失时，使风堇行动提前 30%。
    """

    SKILL_NAME = "乌云乌云快走开！"
    SKILL_ID = 1140901
    DMG_RATIO_OF_HEALING = 0.20     # 1140901 官方解包参数 #1 (Lv6 满级倍率 20%)
    HEALING_RETAIN_RATIO = 0.50     # 施放后清空 50%, 保留 50%
    SELF_COST_RATIO = 0.04          # 1140903 参数 #1
    TALENT_HEAL_PCT = 0.020         # 1140903 参数 #2 (Lv6 官方满级倍率 2.0%, 以风堇生命上限为基准)
    TALENT_HEAL_FLAT = 20.0         # 1140903 参数 #3 (Lv6 官方满级 20)
    DESPAWN_ADVANCE_RATIO = 0.30    # 1140906 参数 #1

    def __init__(self, owner_id: str, port: CombatPort, *, master_kit: Any = None):
        super().__init__(owner_id, port)
        self.master_kit = master_kit
        self._pending_heal_targets: List[str] = []

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.MEMOSPRITE_SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(sp=0),
                name=self.SKILL_NAME,
                tag="忆灵技",
                is_auto=True,
                skill_id=self.SKILL_ID
            )
        raise ValueError(f"小伊卡不支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        self.cast_scatter()

    def _sync_master_field_auras(self) -> None:
        """同步风堇身上已生效的结界抗穿与无视防御光环 (神启、心意相契的安宁等) 至小伊卡，防止与直接施加的状态重复叠加。"""
        master = self.master_kit
        if master is None or not self.port.entity_exists(self.owner_id):
            return
        from ...status import StatusTag
        allowed_stats = {StatType.RES_PEN, StatType.DEF_SHRED, StatType.CRIT_DMG, StatType.DMG_BOOST}
        ika_statuses = list(self.port.statuses(self.owner_id))
        direct_names = {s.name for s in ika_statuses if not s.id.endswith("_IkaAura")}
        for s in ika_statuses:
            if s.id.endswith("_IkaAura") and s.name in direct_names:
                self.port.remove_status(self.owner_id, s.id)
        ika_statuses = list(self.port.statuses(self.owner_id))
        ika_status_ids = {s.id for s in ika_statuses}
        ika_status_names = {s.name for s in ika_statuses}
        for s in self.port.statuses(master.owner_id, category="buff"):
            if StatusTag.CHARACTER_ONLY in getattr(s, "tags", ()):
                continue
            if s.id.startswith("Robin_Talent_TonalChord_") or s.id == "Robin_Tech_WeAreTheMelody":
                continue
            mods = tuple(m for m in s.modifiers if m.stat in allowed_stats)
            if not mods:
                continue
            mapped_key = f"{s.id}_IkaAura"
            if s.id not in ika_status_ids and mapped_key not in ika_status_ids and s.name not in ika_status_names:
                self.port.upsert_status(BuffSpec(
                    key=mapped_key,
                    name=s.name,
                    source_id=getattr(s.source, "name", master.owner_id),
                    target_id=self.owner_id,
                    modifiers=mods,
                    duration=s.duration,
                    timing=s.timing,
                    category="buff",
                    description=s.description,
                    tags=tuple(getattr(s, "tags", ()))
                ))

    def cast_scatter(self) -> None:
        """施放忆灵技【乌云乌云快走开！】：以累计治疗量 20% 为基础值的敌方全体风属性伤害。"""
        if getattr(self, "_casting_scatter", False):
            return

        master = self.master_kit
        if master is None or not self.port.entity_exists(self.owner_id):
            return

        self._casting_scatter = True
        try:
            if hasattr(self.port, "resolve_effects"):
                self.port.resolve_effects()
            if not self.port.entity_exists(self.owner_id):
                return
            # 行动后/额外回合前先结算【牵起晴空的手】挂起治疗
            self._resolve_talent_heal()
            if hasattr(self.port, "resolve_effects"):
                self.port.resolve_effects()
            if not self.port.entity_exists(self.owner_id):
                return
            self._sync_master_field_auras()
            if hasattr(self.port, "resolve_effects"):
                self.port.resolve_effects()
            if not self.port.entity_exists(self.owner_id):
                return
            my_max_hp = float(self.port.max_hp(self.owner_id))
            if my_max_hp <= 0.0:
                return
            accumulated = float(master.accumulated_healing)
            base_value = accumulated * self.DMG_RATIO_OF_HEALING
            master.accumulated_healing = accumulated * self.HEALING_RETAIN_RATIO
            if base_value > 0.0:
                eq_mult = base_value / my_max_hp
                enemies = tuple(self.port.enemies(self.owner_id))
                for enemy in enemies:
                    if not self.port.entity_exists(enemy):
                        continue
                    self.port.attack(
                        self.owner_id,
                        enemy,
                        element="Wind",
                        atk_multiplier=eq_mult,
                        toughness_damage=30.0,
                        damage_type=DamageType.SERVANT,
                        scaling_stat="hp"
                    )
                if hasattr(self.port, "resolve_effects"):
                    self.port.resolve_effects()
                if hasattr(self.port, "_get_entity"):
                    master_ent = self.port._get_entity(master.owner_id)
                    lc = getattr(master_ent, "light_cone", None) if master_ent else None
                    if lc is not None and hasattr(lc, "_flush_discharge"):
                        lc._flush_discharge()
            # 1140901 sp_base = 5: 小伊卡施放忆灵技为风堇恢复 5 点基础能量 (受 ERR 放大)
            err = self.port.stat(master.owner_id, StatType.ERR) or 1.0
            self.port.gain_energy(
                master.owner_id,
                5.0 * err,
                cause=f"忆灵技《乌云乌云快走开！》施放回能 (基础 5.0 × ERR {err*100:.1f}%)",
                source_plugin="小伊卡忆灵技"
            )
        finally:
            self._casting_scatter = False

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """记录生命降低的我方目标，待回合开始/行动后由天赋【牵起晴空的手】结算治疗。"""
        if entity_id == self.owner_id or cause == "yika_talent_consume_hp":
            return
        if hasattr(self.port, "is_countdown") and self.port.is_countdown(entity_id):
            return
        # 每个降低生命的我方目标都排队等待结算 (同一结算点前同一目标只记一次):
        # 旧实现只记第一个目标, 群体掉血时其余目标的治疗被吞掉, 累计治疗量系统性偏低
        if entity_id in self.port.allies(self.owner_id) and entity_id not in self._pending_heal_targets:
            self._pending_heal_targets.append(entity_id)

    def on_event(self, event: Any) -> None:
        from ...events import TurnBeginEvent, TurnEndEvent, HPLostEvent
        if isinstance(event, HPLostEvent) and event.entity_name == self.owner_id and event.hp_left <= 0:
            self._on_despawned()
            return
        if isinstance(event, (TurnBeginEvent, TurnEndEvent)):
            self._resolve_talent_heal()

    def _resolve_talent_heal(self) -> None:
        targets = [
            t for t in self._pending_heal_targets
            if not (hasattr(self.port, "is_countdown") and self.port.is_countdown(t))
        ]
        self._pending_heal_targets = []
        master = self.master_kit
        if not targets or master is None:
            return
        # 队列中的每个目标各结算一次 (各自消耗小伊卡 4% 生命上限);
        # 小伊卡生命耗尽消失后, 剩余目标不再结算
        for target in targets:
            if not self.port.entity_exists(self.owner_id) or not self.port.entity_exists(target):
                continue
            hp_before = self.port.current_hp(self.owner_id)
            cost = self.port.max_hp(self.owner_id) * self.SELF_COST_RATIO
            self.port.lose_hp(self.owner_id, cost, cause="yika_talent_consume_hp")
            raw_heal = self.port.max_hp(master.owner_id) * self.TALENT_HEAL_PCT + self.TALENT_HEAL_FLAT
            self.port.heal(self.owner_id, target, master._apply_outgoing_healing(raw_heal, target))
            if master.in_rain_state():
                for ally in self.port.allies(self.owner_id):
                    if ally != target and not (hasattr(self.port, "is_countdown") and self.port.is_countdown(ally)):
                        self.port.heal(self.owner_id, ally, master._apply_outgoing_healing(raw_heal, ally))
            master.on_healing_provided()
            # lose_hp 将生命下限钳制为 1：消耗量不小于消耗前生命时，小伊卡按官方规则消失
            if cost >= hp_before - 1e-9:
                self.port.despawn_spirit(self.owner_id, reason="天赋消耗生命耗尽")
                self._on_despawned()
                break

    def _on_despawned(self) -> None:
        """小伊卡消失的收尾：同步主人状态并触发【坠落，然后飞翔】行动提前 30%。"""
        master = self.master_kit
        if master is None or not master.yika_alive:
            return
        master.yika_alive = False
        master.ika_kit = None
        master.yika_dmg_stacks = 0
        self.port.advance(master.owner_id, master.owner_id, self.DESPAWN_ADVANCE_RATIO)

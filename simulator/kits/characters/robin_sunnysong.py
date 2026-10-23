"""知更鸟•晴歌 (Robin: Sunny Song - ID 1512, 风 / 记忆) 战斗技能套件完整实现。

严格契合 Nanoka 4.6 官方实机机制与公式 (1512.json)：
1. 普攻【音浪，为海风定调】(151201)：
   - 对敌方单体造成等同于知更鸟•晴歌 70% 生命上限 (Lv10) 的风属性伤害 (HP 缩放)；
   - 削韧 10 点，恢复 1 点 SP，回能 20 点。
2. 战技【盛夏是灵魂的乐手】(151202)：
   - 消耗 1 点 SP，回能 30 点；
   - 若伴生忆灵「晴空乐手」未在场，召唤「晴空乐手」贝茜 (Bessie)；
   - 若任意「晴空乐手」已在场，解除其控制状态，为其回复等同于其 100% 生命上限的生命值，并获得 6 点气氛值。
3. 终结技【跃入这片蔚蓝狂想】(151203)：
   - 消耗 140 点能量，回能 5 点；
   - 使除知更鸟•晴歌外的指定我方单体行动提前 100%，固定恢复等同于 20% 能量上限的能量；
   - 赋予目标【特邀嘉宾】效果持续 2 回合 (持有者及其召唤物攻击时额外使知更鸟获得 2 点气氛值，且无法使其他友方目标获得行动提前效果)。
4. 天赋【巡游在无界的天空】(151204) & 伴生忆灵【晴空乐手】(11512xx)：
   - 晴空乐手继承知更鸟 70% 生命上限与 180% 速度；
   - 气氛值上限 50 点 (星魂 2 提升至 70 点)；
   - 我方目标施放攻击时或任意目标回合首次提供治疗/护盾时，知更鸟获得 1 点气氛值；
   - 贝茜在场时，气氛值 >= 6 召唤啾米 (Drummie)，>= 12 召唤派丁 (Paddie)；
   - 每位乐手被召唤时为知更鸟回能 20 点 (1151205)；
   - 晴空乐手在场提供易伤光环 (1151203)：1人 11.2% / 2人 16.8% / 3人 22.4% (Lv10)；
   - 全员登台进入【Fever】状态：
     * 解除并免疫控制；
     * 知更鸟在 Fever 结束前不进入自身回合；
     * 结界内我方目标造成伤害无视 (15% + 气氛值 * 0.5%) 防御力；
     * 知更鸟与乐手增伤 (84% + 气氛值 * 2.8%)；
     * 行动序列召唤倒计时实体 (速度 140)，回合开始扣除 50% 气氛值 (至少 12 点)；
     * 晴空乐手在行动序列施放忆灵技【叽叽啾啾四重奏】(210% HP 风属性全体伤害，回 1 SP，回能 20 点)；
     * 气氛值归零时 Fever 结束，乐手与倒计时离场，知更鸟行动提前 50% (1151206)。
5. 行迹：
   - A2【偏离和弦】(point06)：我方目标使知更鸟获得气氛值时，若该目标攻击力 > 知更鸟，
     使其攻击力提高等同于知更鸟生命上限的 (16% + 气氛值 * 0.4%)；否则使其暴伤提高 (40% + 气氛值 * 1.5%)，持续 2 回合。
   - A4【即兴蓝调】(point07)：受队友治疗/护盾时获得 12 层【律动】(上限 12 层)；在任意目标回合首次获得气氛值时消耗 1 层律动并回能 3 点。
   - A6【重构谐乐】(point08)：知更鸟与「晴空乐手」暴击率提高 50%。
6. 秘技【我们自成旋律】(151207)：
   - 进战自身行动提前 20%，立即获得 6 点气氛值，我方全体造成的伤害提高 30%，持续 2 回合。
7. 星魂 (E1~E6，严格对照 Nanoka 4.6 1512.json 参数表)：
   - E1【夏日离群飞鸟】：记录我方 100% 非真实伤害，忆灵技对生命最高敌方额外造成 (11% + 气氛值 * 0.1%) 真实伤害，随后清空记录值的 50%；
   - E2【心似一片湖水】：全队全属性抗穿提高 18%，气氛值上限+20，任意目标回合首次施放技能使知更鸟获气氛值时额外+2；
   - E3【拾取沿途遗音】：战技+2，天赋+2，忆灵天赋+1；
   - E4【聆听众弦的变奏】：进入 Fever 立即获得 12 点气氛值，乐手速度提高 (20% + 气氛值 * 0.5%)；
   - E5【然后再次共逐新晨】：终结技+2，普攻+1，忆灵技+1；
   - E6【唱一首未命名的歌】：忆灵技倍率提高原倍率的 100%，Fever 期间终结技可储存 2 次，首进 Fever 或倒计时回合开始固定恢复 140 点能量。
"""

from typing import Optional, List, Any
import math
from ..base import KitHandler
from ..registry import register_kit
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...events import (
    ActionExecuteEvent, DamageAppliedEvent, HealAppliedEvent, ShieldAppliedEvent, TurnBeginEvent
)
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StatusTag


class SunnyMusiciansKit(KitHandler):
    """伴生忆灵「晴空乐手」(Sunny Musicians) 技能套件。"""

    def __init__(self, owner_id: str, port: CombatPort, *, master_kit: Any = None):
        super().__init__(owner_id, port)
        self.master_kit = master_kit

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        return AbilityDefinition(
            kind=ActionKind.SKILL,
            target_mode=TargetMode.ALL_ENEMIES,
            cost=ResourceCost(sp=-1),  # bp_need = -1 -> 产生 1 点 SP
            name="叽叽啾啾四重奏",
            tag="忆灵技",
            is_auto=True
        )

    def execute(self, ctx: ActionContext) -> None:
        """施放忆灵技【叽叽啾啾四重奏】(1151201)。"""
        if not self.master_kit:
            return

        # 1151201 官方倍率 (Lv10 为 210% 生命上限)
        mult = self.master_kit.skill_param("1151201", 1, default=2.10)
        if self.master_kit.eidolon >= 6:
            # E6【唱一首未命名的歌】：忆灵技的伤害倍率提高原倍率的 100% (#1=1.0)
            e6_boost = self.master_kit.eidolon_param(6, 0, default=1.0)
            mult *= (1.0 + e6_boost)

        enemies = self.port.enemies(self.owner_id)
        for enemy_id in enemies:
            self.port.attack(
                self.owner_id,
                enemy_id,
                element="Wind",
                atk_multiplier=mult,
                toughness_damage=30.0,
                damage_tag="MemospriteSkill",
                scaling_stat="hp"
            )

        # 1151201 sp_base = 20：施放忆灵技回能 20 点
        self.port.gain_energy(self.master_kit.owner_id, 20.0)

        # 星魂 1【夏日离群飞鸟】：对生命值最高的敌方目标额外造成记录伤害总额 (11% + 气氛值 * 0.1%) 的真实伤害，随后清空记录值的 50%
        if self.master_kit.eidolon >= 1 and getattr(self.master_kit, "recorded_damage", 0.0) > 0 and enemies:
            highest_hp_enemy = max(enemies, key=lambda e: self.port.max_hp(e))
            base_true_pct = self.master_kit.eidolon_param(1, 0, default=0.11)
            vibe_true_pct = self.master_kit.eidolon_param(1, 1, default=0.001)
            clear_ratio = self.master_kit.eidolon_param(1, 3, default=0.50)

            true_mult = base_true_pct + self.master_kit.vibes * vibe_true_pct
            true_dmg = self.master_kit.recorded_damage * true_mult
            self.port.lose_hp(highest_hp_enemy, true_dmg, cause="Robin_E1_TrueDamage")
            self.master_kit.recorded_damage = max(0.0, self.master_kit.recorded_damage * (1.0 - clear_ratio))


class FeverCountdownKit(KitHandler):
    """【Fever】倒计时实体行动套件 (基础速度 140)。"""

    def __init__(self, owner_id: str, port: CombatPort, *, master_kit: Any = None):
        super().__init__(owner_id, port)
        self.master_kit = master_kit

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        return AbilityDefinition(
            kind=ActionKind.SKILL,
            target_mode=TargetMode.SELF,
            cost=ResourceCost(sp=0),
            name="Fever倒计时结算",
            tag="倒计时",
            is_auto=True
        )

    def execute(self, ctx: ActionContext) -> None:
        if self.master_kit:
            self.master_kit.on_countdown_turn()


@register_kit("1512", "知更鸟•晴歌", "知更鸟·晴歌", "知更鸟晴歌", "robin_sunnysong")
class RobinSunnySongKit(KitHandler):
    """知更鸟•晴歌 (ID 1512, 风 / 记忆) 官方战斗套件完整实现。"""

    MUSICIAN_NAME = "晴空乐手"
    COUNTDOWN_NAME = "晴空乐手•倒计时"

    # 状态 Key 常量
    ULT_SPECIAL_GUEST_BUFF = "Robin_Ult_SpecialGuest"
    FEVER_DEF_IGNORE_BUFF = "Robin_Fever_DefIgnore"
    FEVER_DMG_BUFF = "Robin_Fever_DmgBoost"
    MUSICIANS_VULNERABILITY_BUFF = "Robin_Musicians_Vulnerability"
    E2_RES_PEN_BUFF = "Robin_E2_ResPen"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.in_concerto: bool = False  # 兼容字段
        self.in_fever: bool = False     # 真实【Fever】状态

        # 气氛值核心系统
        self.vibes: int = 0             # 气氛值
        self._custom_max_vibes: Optional[int] = None

        # 行迹【即兴蓝调】
        self.rhythm_stacks: int = 0     # 律动层数 (上限 12 层)
        self._rhythm_consumed_in_current_turn: bool = False
        self._healed_this_turn: bool = False
        self._e2_vibe_bonus_in_turn: bool = False

        # 伴生乐手成员状态
        self.musicians_alive: bool = False
        self.has_bessie: bool = False
        self.has_drummie: bool = False
        self.has_paddie: bool = False
        self.member_count: int = 0

        # E1 真实伤害记录器
        self.recorded_damage: float = 0.0

    @property
    def max_vibes(self) -> int:
        """气氛值上限：基础 50 点 (talent #5)，星魂 2 额外提高 20 点 (E2 #1)。"""
        if self._custom_max_vibes is not None:
            return self._custom_max_vibes
        base_cap = int(self.skill_param("talent", 4, default=50.0))
        if self.eidolon >= 2:
            base_cap += int(self.eidolon_param(2, 0, default=20.0))
        return base_cap

    @max_vibes.setter
    def max_vibes(self, val: int) -> None:
        self._custom_max_vibes = int(val)

    @property
    def current_members(self) -> List[str]:
        members = []
        if self.has_bessie:
            members.append("贝茜")
        if self.has_drummie:
            members.append("啾米")
        if self.has_paddie:
            members.append("派丁")
        return members

    @property
    def musician_max_hp(self) -> float:
        robin_hp = self.port.max_hp(self.owner_id) if self.port else 6000.0
        hp_inherit = self.skill_param("talent", 0, default=0.70)
        return robin_hp * hp_inherit

    @property
    def musician_speed(self) -> float:
        robin_spd = self.port.stat(self.owner_id, StatType.SPEED) if self.port else 95.0
        spd_inherit = self.skill_param("talent", 1, default=1.80)
        base_m_spd = robin_spd * spd_inherit
        if self.eidolon >= 4 and self.in_fever:
            # E4【聆听众弦的变奏】：晴空乐手的速度提高 (20% + 当前气氛值 * 0.5%)
            e4_base = self.eidolon_param(4, 1, default=0.20)
            e4_per_vibe = self.eidolon_param(4, 2, default=0.005)
            bonus_spd_pct = e4_base + self.vibes * e4_per_vibe
            return base_m_spd * (1.0 + bonus_spd_pct)
        return base_m_spd

    def apply_trace_passives(self, entity: Any) -> None:
        """行迹常驻被动属性注入与基线对齐：能量上限为 140 点。"""
        entity.max_energy = 140.0

    def can_cast_ultimate(self, entity: Any) -> bool:
        """支持常规 140 能量施放，以及 E6 Fever 期间最多储存 2 次终结技。"""
        energy = getattr(entity, "energy", 0.0)
        return energy >= (140.0 - 1e-4)

    def consume_ultimate_cost(self, entity: Any) -> bool:
        """扣除终结技 140 点能量；E6 处于 Fever 状态时保留溢出储存能量。"""
        if not self.can_cast_ultimate(entity):
            return False
        if self.eidolon >= 6 and self.in_fever:
            entity.energy = max(0.0, getattr(entity, "energy", 0.0) - 140.0)
        else:
            entity.energy = 0.0
        return True

    def _sync_rhythm_status(self) -> None:
        """同步【律动】机制层数至 Status 视图。"""
        self.port.upsert_status(BuffSpec(
            key="Robin_Talent_Rhythm",
            name="律动",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="other",
            stacks=self.rhythm_stacks,
            max_stacks=12,
            description=f"知更鸟•晴歌专属机制，当前持有 {self.rhythm_stacks} 层"
        ))

    def on_battle_start(self) -> None:
        """战斗开始：
        1. 挂载行迹【重构谐乐】：自身与伴生忆灵暴击率提高 50%；
        2. E2【心似一片湖水】：我方目标全属性抗性穿透提高 18%；
        3. 同步【律动】至其他效果列表。
        """
        self.port.upsert_status(BuffSpec(
            key="Robin_A6_HarmonicReconstruction",
            name="重构谐乐",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.50),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="知更鸟•晴歌与「晴空乐手」的暴击率提高 +50.0%"
        ))

        if self.eidolon >= 2:
            res_pen_val = self.eidolon_param(2, 2, default=0.18)
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E2_RES_PEN_BUFF,
                    name="心似一片湖水",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, res_pen_val),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description=f"全队全属性抗性穿透提高 +{res_pen_val * 100:.1f}%"
                ))

        if self.rhythm_stacks > 0:
            self._sync_rhythm_status()

    def gain_vibes(self, amount: int = 1, trigger_ally_id: Optional[str] = None) -> None:
        """增加气氛值：
        - 若处于任意目标回合内首次获得气氛值且持有【律动】，消耗 1 层律动并固定恢复 3 点能量 (行迹【即兴蓝调】)；
        - 触发行迹【偏离和弦】属性增益；
        - 若已处于【Fever】状态，实时同步结界无视防御、增伤与 E4 乐手速度；
        - 检测并推进伴生忆灵「晴空乐手」登台阶梯 (贝茜在场时，6 点啾米，12 点派丁)。
        """
        old_val = self.vibes
        self.vibes = min(self.max_vibes, self.vibes + amount)

        if hasattr(self.port, "tracer") and self.port.tracer:
            hp_cause = getattr(self.port.tracer, "current_hp_cause", "")
            if getattr(self, "_healed_this_turn", False):
                if hp_cause == "stage_mechanic_bleed_turn_begin":
                    cause_str = "长夜月回合内受到关卡《血噬》扣血引发小伊卡回复全队 ➔ 首次受治疗获得气氛值 +1 点"
                else:
                    cause_str = f"队友回合内首次提供治疗效果 (来源: {trigger_ally_id or '队友'}) ➔ +{amount} 点"
            else:
                cause_str = f"施放技能/攻击获得气氛值 ➔ +{amount} 点"

            note = "🌟 阈值激活: 气氛达 12 点! 第三位乐手「派丁」登台 ➔ 全员登台开启 Fever，全队造成的伤害无视 21% 防御!" if (self.vibes >= 12 and old_val < 12) else ""
            self.port.tracer.record_var_change(
                entity=self.owner_id,
                var_name="气氛值",
                old_val=old_val,
                new_val=self.vibes,
                source_plugin="知更鸟天赋《偏离和弦》",
                cause_desc=cause_str,
                extra_note=note
            )
            if self.in_fever:
                self.port.tracer.record_plugin("天赋", "《偏离和弦 / 全员登台》 (知更鸟•晴歌)", "回合首治获气氛、12 气氛召唤派丁进入 Fever、全队 21% 无视防御")

        # 行迹【即兴蓝调】回能与律动消耗 (仅在实战回合或动作内有效，排除战前秘技)
        if self.port.is_in_turn() and not getattr(self, "_rhythm_consumed_in_current_turn", False):
            if self.rhythm_stacks > 0:
                old_r = self.rhythm_stacks
                self._rhythm_consumed_in_current_turn = True
                self.rhythm_stacks -= 1
                self.port.gain_energy(self.owner_id, 3.0)
                self._sync_rhythm_status()
                if hasattr(self.port, "tracer") and self.port.tracer:
                    self.port.tracer.record_var_change(
                        entity=self.owner_id,
                        var_name="律动层数",
                        old_val=old_r,
                        new_val=self.rhythm_stacks,
                        source_plugin="知更鸟行迹《即兴蓝调》",
                        cause_desc="回合内首次获得气氛值且持有律动，消耗 1 层律动并恢复 3 点能量 ➔ -1 层"
                    )
                    self.port.tracer.record_plugin("行迹", "《即兴蓝调》 (知更鸟•晴歌)", "获气氛消耗 1 层律动回能 3 点")

        # 行迹【偏离和弦】
        if trigger_ally_id:
            self.apply_tonal_chord_to_ally(trigger_ally_id)

        # 若处于 Fever 期间，实时刷新结界属性与乐手速度
        if self.in_fever:
            self._sync_fever_buffs()
            if self.port.entity_exists(self.MUSICIAN_NAME):
                self.port.set_base_speed(self.MUSICIAN_NAME, self.musician_speed)

        # 乐手登台与全员登台检定 (贝茜在场为前提)
        if self.musicians_alive and self.has_bessie:
            self._check_musician_stage_progression()

    def _check_musician_stage_progression(self) -> None:
        """检测并推进「晴空乐手」啾米与派丁的登台。"""
        drummie_threshold = int(self.skill_param("talent", 5, default=6.0))
        paddie_threshold = int(self.skill_param("talent", 6, default=12.0))
        summon_energy = self.skill_param("1151205", 0, default=20.0)

        if self.vibes >= drummie_threshold and not self.has_drummie:
            self.has_drummie = True
            self.member_count = max(self.member_count, 2)
            # 1151205 贴近海的心跳：被召唤时为知更鸟恢复 20 点能量
            self.port.gain_energy(self.owner_id, summon_energy, cause="忆灵天赋《贴近海的心跳》召唤「啾米」登台回能 (+20.0 点)", source_plugin="晴空乐手天赋")
            self._update_musician_aura()

        if self.vibes >= paddie_threshold and not self.has_paddie:
            self.has_paddie = True
            self.member_count = 3
            # 1151205 贴近海的心跳：被召唤时为知更鸟恢复 20 点能量
            self.port.gain_energy(self.owner_id, summon_energy, cause="忆灵天赋《贴近海的心跳》召唤「派丁」登台回能 (+20.0 点)", source_plugin="晴空乐手天赋")
            self._update_musician_aura()

        # 全员登台 -> 开启【Fever】状态与结界
        if self.has_bessie and self.has_drummie and self.has_paddie and not self.in_fever:
            self.enter_fever()

    def summon_musicians(self) -> None:
        """召唤伴生忆灵「晴空乐手」贝茜登台。"""
        if self.musicians_alive:
            return

        self.musicians_alive = True
        self.has_bessie = True
        self.member_count = 1

        # 1151205 贴近海的心跳：召唤贝茜为知更鸟恢复 20 点能量
        summon_energy = self.skill_param("1151205", 0, default=20.0)
        self.port.gain_energy(self.owner_id, summon_energy, cause="忆灵天赋《贴近海的心跳》召唤「贝茜」登台回能 (+20.0 点)", source_plugin="晴空乐手天赋")

        # 注册实体至跑道
        musician_ent = self.port.summon_spirit(
            owner_id=self.owner_id,
            name=self.MUSICIAN_NAME,
            base_speed=self.musician_speed,
            max_hp=self.musician_max_hp,
            kit_class=SunnyMusiciansKit,
            kit_args={"master_kit": self}
        )
        if musician_ent:
            # 未进入 Fever 期间，乐手处于准备登台阶段，不先行插入常规行动
            self.port.set_distance(self.MUSICIAN_NAME, 999999.0)

            # 行迹【重构谐乐】：晴空乐手暴击率提高 50%
            self.port.upsert_status(BuffSpec(
                key="Robin_A6_HarmonicReconstruction_Musician",
                name="重构谐乐",
                source_id=self.owner_id,
                target_id=self.MUSICIAN_NAME,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.50),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                tags=(StatusTag.MEMOSPRITE_ONLY,),
                description="「晴空乐手」暴击率提高 +50.0%"
            ))

        self._update_musician_aura()
        # 若召唤贝茜时气氛值已经 >= 6 或 >= 12，立刻连带召唤后续成员
        self._check_musician_stage_progression()

    def _update_musician_aura(self) -> None:
        """更新忆灵在场时的敌方全体易伤光环 (1151203 扑翅雀跃的和声：11.2% / 16.8% / 22.4%)。"""
        if not self.musicians_alive or self.member_count <= 0:
            return

        v1 = self.skill_param("1151203", 2, default=0.112)
        v2 = self.skill_param("1151203", 3, default=0.168)
        v3 = self.skill_param("1151203", 4, default=0.224)
        vul_map = {1: v1, 2: v2, 3: v3}
        vul_pct = vul_map.get(min(self.member_count, 3), v1)

        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.MUSICIANS_VULNERABILITY_BUFF,
                name="扑翅雀跃的和声",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, vul_pct),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="debuff",
                description=f"晴空乐手在场，敌方受到的伤害提高 +{vul_pct * 100:.1f}% (当前乐手: {self.member_count} 人)"
            ))

    def enter_fever(self) -> None:
        """进入【Fever】状态并展开防御无视结界。"""
        if self.in_fever:
            return

        self.in_fever = True

        # 天赋：解除知更鸟•晴歌与「晴空乐手」陷入的控制类负面状态
        self.port.dispel(self.owner_id, is_debuff=True)
        if self.port.entity_exists(self.MUSICIAN_NAME):
            self.port.dispel(self.MUSICIAN_NAME, is_debuff=True)

        # 星魂 4【聆听众弦的变奏】：进入【Fever】状态时，立即获得 12 点气氛值 (#1=12)
        if self.eidolon >= 4:
            e4_vibes = int(self.eidolon_param(4, 0, default=12.0))
            self.gain_vibes(e4_vibes)

        # 星魂 6【唱一首未命名的歌】：本场战斗中第一次进入【Fever】状态固定恢复 140 点能量 (#2=140)
        if self.eidolon >= 6 and not getattr(self, "_e6_first_fever_energy", False):
            self._e6_first_fever_energy = True
            e6_energy = self.eidolon_param(6, 1, default=140.0)
            self.port.gain_energy(self.owner_id, e6_energy)

        # 1. 结界内我方目标无视防御力 (15% + 气氛值 * 0.5%)
        # 2. 知更鸟•晴歌与晴空乐手造成的伤害提高 (84% + 气氛值 * 2.8%)
        self._sync_fever_buffs()

        # 3. 将晴空乐手正式部署至行动序列 (起跑点 10000 距离，即刻按速度排轴)
        if self.port.entity_exists(self.MUSICIAN_NAME):
            self.port.set_base_speed(self.MUSICIAN_NAME, self.musician_speed)
            self.port.set_distance(self.MUSICIAN_NAME, 10000.0)

        # 4. 在行动序列上召唤倒计时实体 (速度 140)
        countdown_spd = self.skill_param("1151203", 8, default=140.0)
        countdown_ent = self.port.summon_spirit(
            owner_id=self.owner_id,
            name=self.COUNTDOWN_NAME,
            base_speed=countdown_spd,
            max_hp=1000.0,
            kit_class=FeverCountdownKit,
            kit_args={"master_kit": self},
            is_memosprite=False,
            is_countdown=True
        )
        if countdown_ent:
            self.port.set_distance(self.COUNTDOWN_NAME, 10000.0)

        # 5. 【Fever】状态结束前知更鸟•晴歌不会进入自己的回合 (挂起知更鸟跑条)
        self.port.set_distance(self.owner_id, 999999.0)

    def _sync_fever_buffs(self) -> None:
        """同步【Fever】结界防御无视与增伤数值。"""
        if not self.in_fever:
            return

        def_base = self.skill_param("talent", 7, default=0.15)
        def_per_vibe = self.skill_param("talent", 8, default=0.005)
        def_ignore = round(def_base + self.vibes * def_per_vibe, 4)

        dmg_base = self.skill_param("1151203", 0, default=0.84)
        dmg_per_vibe = self.skill_param("1151203", 1, default=0.028)
        dmg_boost = round(dmg_base + self.vibes * dmg_per_vibe, 4)

        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.FEVER_DEF_IGNORE_BUFF,
                name="巡游在无界的天空",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, def_ignore),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"【Fever】结界内造成伤害无视敌方 +{def_ignore * 100:.1f}% 防御力"
            ))

        for target_id in (self.owner_id, self.MUSICIAN_NAME):
            if self.port.entity_exists(target_id):
                self.port.upsert_status(BuffSpec(
                    key=self.FEVER_DMG_BUFF,
                    name="扑翅雀跃的和声 (Fever增伤)",
                    source_id=self.owner_id,
                    target_id=target_id,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_boost),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description=f"【Fever】状态下造成的伤害提高 +{dmg_boost * 100:.1f}%"
                ))

    def on_countdown_turn(self) -> None:
        """倒计时回合开始时结算：
        1. 扣除 50% 当前气氛值 (至少扣除 12 点)；
        2. E6: 固定恢复 140 点能量；
        3. 气氛值归零时，「晴空乐手」消失并退出【Fever】状态，知更鸟行动提前 50%。
        """
        # 星魂 6【唱一首未命名的歌】：倒计时回合开始时固定恢复 140 点能量 (#2=140)
        if self.eidolon >= 6:
            e6_energy = self.eidolon_param(6, 1, default=140.0)
            self.port.gain_energy(self.owner_id, e6_energy)

        # 扣除 50% 气氛值，至少扣除 12 点
        min_deduct = int(self.skill_param("1151203", 5, default=12.0))
        deduct_ratio = self.skill_param("1151203", 9, default=0.50)
        deduct_vibes = max(min_deduct, math.floor(self.vibes * deduct_ratio))
        self.vibes = max(0, self.vibes - deduct_vibes)

        if self.vibes <= 0:
            self.exit_fever()
        else:
            self._sync_fever_buffs()
            if self.port.entity_exists(self.MUSICIAN_NAME):
                self.port.set_base_speed(self.MUSICIAN_NAME, self.musician_speed)

    def exit_fever(self) -> None:
        """退出【Fever】状态，乐手与倒计时离场，知更鸟行动提前 50% (1151206 乘上夏夜晚风)。"""
        self.in_fever = False
        self.musicians_alive = False
        self.has_bessie = False
        self.has_drummie = False
        self.has_paddie = False
        self.member_count = 0

        # 通过 CombatPort 标准契约清除结界增益、自身 Fever 增伤与敌方易伤
        for ally in self.port.allies(self.owner_id):
            self.port.remove_status(ally, self.FEVER_DEF_IGNORE_BUFF)
        for target_id in (self.owner_id, self.MUSICIAN_NAME):
            self.port.remove_status(target_id, self.FEVER_DMG_BUFF)
        for enemy in self.port.enemies(self.owner_id):
            self.port.remove_status(enemy, self.MUSICIANS_VULNERABILITY_BUFF)

        # 离场忆灵与倒计时实体
        self.port.despawn_spirit(self.MUSICIAN_NAME, reason="fever_end")
        self.port.despawn_spirit(self.COUNTDOWN_NAME, reason="fever_end")

        # 1151206 乘上夏夜晚风：「晴空乐手」消失时，使知更鸟•晴歌行动提前 50%
        adv_ratio = self.skill_param("1151206", 0, default=0.50)
        self.port.set_distance(self.owner_id, 10000.0 * (1.0 - adv_ratio))

    def apply_tonal_chord_to_ally(self, ally_id: str) -> None:
        """行迹【偏离和弦】(point06)：
        我方目标使知更鸟•晴歌获得气氛值时：
        - 若该目标攻击力 > 知更鸟：使该目标的攻击力提高等同于知更鸟生命上限的 (16% + 气氛值 * 0.4%)；
        - 否则：使该目标的暴击伤害提高 (40% + 气氛值 * 1.5%)；
        持续 2 回合。
        """
        target_atk = self.port.stat(ally_id, StatType.ATK_BASE)
        robin_atk = self.port.stat(self.owner_id, StatType.ATK_BASE)

        if target_atk > robin_atk:
            robin_hp = self.port.max_hp(self.owner_id)
            atk_ratio = 0.16 + self.vibes * 0.004
            flat_atk = robin_hp * atk_ratio
            mods = (Modifier(StatType.ATK_BASE, ModifierOp.ADD, flat_atk),)
            desc = f"攻击力提高 +{flat_atk:.1f} (知更鸟生命上限的 {atk_ratio * 100:.1f}%)"
        else:
            cd_val = round(0.40 + self.vibes * 0.015, 4)
            mods = (Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),)
            desc = f"暴击伤害 +{cd_val * 100:.1f}%"

        tags = (StatusTag.MEMOSPRITE_ONLY,) if self.port.is_memosprite(ally_id) else ()
        self.port.upsert_status(BuffSpec(
            key=f"Robin_Talent_TonalChord_{ally_id}",
            name="偏离和弦",
            source_id=self.owner_id,
            target_id=ally_id,
            modifiers=mods,
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=desc,
            tags=tags
        ))

    def _is_special_guest_actor(self, actor_name: str) -> bool:
        """检测当前行动目标是否为【特邀嘉宾】持有者或其伴生召唤物。"""
        if self.port.has_status(actor_name, self.ULT_SPECIAL_GUEST_BUFF):
            return True
        if self.port.is_memosprite(actor_name):
            master = self.port.get_master_name(actor_name)
            if master and self.port.has_status(master, self.ULT_SPECIAL_GUEST_BUFF):
                return True
        return False

    def on_event(self, event: Any) -> None:
        """监听行动、治疗、护盾、伤害与回合时钟事件。"""
        if isinstance(event, TurnBeginEvent):
            # 新回合开始：重置本回合律动消耗门禁、治疗门禁与 E2 技能首获门禁
            self._last_turn_actor = getattr(event, "actor_name", getattr(event, "entity_name", ""))
            self._rhythm_consumed_in_current_turn = False
            self._healed_this_turn = False
            self._e2_vibe_bonus_in_turn = False

        elif isinstance(event, (HealAppliedEvent, ShieldAppliedEvent)):
            is_target_robin = (event.target_name == self.owner_id) or (
                self.port.is_own_memosprite(self.owner_id, event.target_name)
            )
            is_teammate_source = self.port.is_ally(event.source_name) and event.source_name != self.owner_id
            
            # 行迹【即兴蓝调】：知更鸟•晴歌或「晴空乐手」受到队友提供的治疗或护盾时，获得 12 层【律动】
            if is_target_robin and is_teammate_source:
                old_r = self.rhythm_stacks
                self.rhythm_stacks = 12
                self._sync_rhythm_status()
                if hasattr(self.port, "tracer") and self.port.tracer and old_r != 12:
                    self.port.tracer.record_var_change(
                        entity=self.owner_id,
                        var_name="律动层数",
                        old_val=old_r,
                        new_val=12,
                        source_plugin="知更鸟行迹《即兴蓝调》",
                        cause_desc="受到队友提供的治疗，【律动】层数瞬间回满至上限 ➔ 重置为 12 层"
                    )
                    self.port.tracer.record_plugin("行迹", "《即兴蓝调》 (知更鸟•晴歌)", "受治疗重置 12 层律动")

            # 天赋：在任意目标回合第一次提供治疗效果或护盾时，知更鸟•晴歌获得 1 点气氛值 (排除战前非回合治疗)
            if is_teammate_source and not getattr(self, "_healed_this_turn", False):
                self._healed_this_turn = True
                extra = 0
                if self.eidolon >= 2 and not self._e2_vibe_bonus_in_turn:
                    self._e2_vibe_bonus_in_turn = True
                    extra += int(self.eidolon_param(2, 1, default=2.0))
                self.gain_vibes(1 + extra, trigger_ally_id=event.source_name)

        elif isinstance(event, ActionExecuteEvent):
            # 若行动者发生切换 (无论是常规回合还是终结技插队)，保证重置动作与律动门禁
            if getattr(self, "_last_turn_actor", None) != event.actor_name:
                self._last_turn_actor = event.actor_name
                self._rhythm_consumed_in_current_turn = False
                self._healed_this_turn = False
                self._e2_vibe_bonus_in_turn = False
            # 天赋：我方目标施放攻击时获得 1 点气氛值 (排除纯辅助技能与 Fever 倒计时实体)
            if (
                self.port.is_ally(event.actor_name)
                and self.port.is_attack_action(
                    event.actor_name,
                    getattr(event, "action_kind", None),
                    getattr(event, "action_type", "")
                )
            ):
                extra = 0
                # 终结技【特邀嘉宾】联动：持有【特邀嘉宾】的角色及其召唤物攻击时额外获得 2 点气氛值
                if self._is_special_guest_actor(event.actor_name):
                    extra += int(self.skill_param("ultra", 1, default=2.0))
                # 星魂 2【心似一片湖水】：任意目标回合内第一次施放技能使知更鸟获得气氛值额外 +2 (#2=2)
                if self.eidolon >= 2 and not self._e2_vibe_bonus_in_turn:
                    self._e2_vibe_bonus_in_turn = True
                    extra += int(self.eidolon_param(2, 1, default=2.0))
                self.gain_vibes(1 + extra, trigger_ally_id=event.actor_name)

        elif isinstance(event, DamageAppliedEvent):
            # 星魂 1【夏日离群飞鸟】：记录我方目标造成的非真实伤害的 100% (#3=1.0)
            if self.eidolon >= 1 and self.port.is_ally(event.attacker_name):
                record_ratio = self.eidolon_param(1, 2, default=1.0)
                self.recorded_damage += event.damage * record_ratio

    def use_technique(self) -> None:
        """秘技【我们自成旋律】(151207)：
        进战行动提前 20%，立即获得 6 点气氛值，我方全体造成的伤害提高 30%，持续 2 回合。
        """
        tech_vibes = int(self.skill_param("technique", 0, default=6.0))
        tech_dmg = self.skill_param("technique", 1, default=0.30)
        tech_adv = self.skill_param("technique", 2, default=0.20)

        self.port.advance(self.owner_id, self.owner_id, tech_adv)
        self.gain_vibes(tech_vibes, trigger_ally_id=self.owner_id)

        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Robin_Tech_WeAreTheMelody",
                name="我们自成旋律",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, tech_dmg),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"全队造成伤害提高 +{tech_dmg * 100:.1f}%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="音浪，为海风定调"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="盛夏是灵魂的乐手"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(energy=140.0),
                allow_self=False,
                name="跃入这片蔚蓝狂想"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="我们自成旋律",
                priority=2
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
        self.use_technique()

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【音浪，为海风定调】：
        对敌方单体造成等同于知更鸟•晴歌 70% 生命上限 (Lv10) 的风属性伤害，回能 20 点。
        """
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        target_id = ctx.target_ids[0] if ctx.target_ids else enemies[0]
        # 151201 Lv10 倍率为 0.70 (SkillScaling 默认普攻按 6 级计为 0.50，实机满级面板按 0.70 对齐)
        mult = max(0.70, self.skill_param("basic", 0, default=0.70))
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
        """战技【盛夏是灵魂的乐手】：
        召唤忆灵「晴空乐手」贝茜。若已在场，解除控制状态，回复 100% 生命上限并获得 6 点气氛值。
        回能 30 点。
        """
        self.port.gain_energy(self.owner_id, 30.0, cause="施放战技《盛夏是灵魂的乐手》回能", source_plugin="知更鸟•晴歌战技")
        if not self.musicians_alive:
            self.summon_musicians()
        else:
            self.port.dispel(self.MUSICIAN_NAME, is_debuff=True)
            heal_ratio = self.skill_param("skill", 0, default=1.0)
            vibe_gain = int(self.skill_param("skill", 1, default=6.0))
            musician_hp = self.port.max_hp(self.MUSICIAN_NAME) or self.musician_max_hp
            self.port.heal(self.owner_id, self.MUSICIAN_NAME, musician_hp * heal_ratio)
            extra = 0
            if self.eidolon >= 2 and not self._e2_vibe_bonus_in_turn:
                self._e2_vibe_bonus_in_turn = True
                extra += int(self.eidolon_param(2, 1, default=2.0))
            self.gain_vibes(vibe_gain + extra, trigger_ally_id=self.owner_id)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【跃入这片蔚蓝狂想】：
        使除自身外的指定我方单体行动提前 100%，固定恢复其 20% 能量上限，并赋予【特邀嘉宾】2 回合。
        """
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        else:
            # 默认选择除自身外的首位非忆灵我方角色（零角色名硬编码）
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id and not self.port.is_memosprite(a)]
            if allies:
                target_id = allies[0]

        if not target_id:
            return

        # 终结技自带回能 5 点 (sp_base = 5)
        self.port.gain_energy(self.owner_id, 5.0)

        # 1. 指定我方单体行动提前 100% (#1=1.0)
        adv_ratio = self.skill_param("ultra", 0, default=1.0)
        self.port.advance(self.owner_id, target_id, adv_ratio)

        # 2. 固定恢复等同于 20% 能量上限的能量 (Lv10 #3=0.20)
        energy_ratio = self.skill_param("ultra", 2, default=0.20)
        target_max_energy = self.port.max_energy(target_id)
        if target_max_energy > 0:
            self.port.gain_energy(target_id, target_max_energy * energy_ratio)

        # 3. 赋予【特邀嘉宾】效果，持续 2 回合（携带 CANNOT_ADVANCE_OTHER_ALLIES 标签）
        guest_vibes = int(self.skill_param("ultra", 1, default=2.0))
        self.port.upsert_status(BuffSpec(
            key=self.ULT_SPECIAL_GUEST_BUFF,
            name="特邀嘉宾",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True,
            category="buff",
            tags=(StatusTag.CANNOT_ADVANCE_OTHER_ALLIES,),
            description=f"持有【特邀嘉宾】的角色及其召唤物攻击时额外使知更鸟•晴歌获得 {guest_vibes} 点气氛值，且无法使其他友方目标获得行动提前效果"
        ))

    def get_memosprite_snapshot(self) -> Optional[dict]:
        """返回伴生忆灵「晴空乐手」独立实时战斗快照（100% 经由 CombatPort 采样）。"""
        if not self.musicians_alive:
            return None
        max_hp = self.musician_max_hp
        cur_hp = self.port.current_hp(self.MUSICIAN_NAME) or max_hp
        crit_rate = self.port.stat(self.MUSICIAN_NAME, StatType.CRIT_RATE)
        crit_dmg = self.port.stat(self.MUSICIAN_NAME, StatType.CRIT_DMG)
        buffs = []
        for s in self.port.statuses(self.MUSICIAN_NAME):
            if getattr(s, "category", "buff") == "buff":
                buffs.append({"name": s.name, "desc": s.description or ""})
        return {
            "name": self.MUSICIAN_NAME,
            "owner": self.owner_id,
            "is_memosprite": True,
            "is_alive": True,
            "member_count": self.member_count,
            "members": self.current_members,
            "in_fever": self.in_fever,
            "current_hp": round(cur_hp, 1),
            "max_hp": round(max_hp, 1),
            "speed": round(self.musician_speed, 1),
            "crit_rate": round(crit_rate, 4),
            "crit_dmg": round(crit_dmg, 4),
            "buffs": buffs
        }

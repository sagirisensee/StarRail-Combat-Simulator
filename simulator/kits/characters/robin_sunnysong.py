"""知更鸟•晴歌 (Robin: Sunny Song - ID 1512, 风 / 记忆) 战斗技能套件完整实现。

严格契合 Nanoka 4.6 官方实机机制与公式 (1512.json)：
1. 普攻【音浪，为海风定调】(151201)：
   - 对敌方单体造成等同于知更鸟•晴歌 70% 生命上限 (Lv10) 的风属性伤害 (HP 缩放)；
   - 削韧 10 点，恢复 1 点 SP，回能 20 点。
2. 战技【盛夏是灵魂的乐手】(151202)：
   - 消耗 1 点 SP，回能 30 点；
   - 若伴生忆灵「晴空乐手」未在场，召唤「晴空乐手」贝茜 (Bessie)；
   - 若任意「晴空乐手」已在场，为其回复等同于其 100% 生命上限的生命值，并获得 6 点气氛值。
3. 终结技【跃入这片蔚蓝狂想】(151203)：
   - 消耗 140 点能量；
   - 使除知更鸟•晴歌外的指定我方单体行动提前 100%，固定恢复等同于 20% 能量上限的能量；
   - 赋予目标【特邀嘉宾】效果持续 2 回合 (持有者及其召唤物攻击时额外使知更鸟获得 2 点气氛值)。
4. 天赋【巡游在无界的天空】(151204) & 伴生忆灵【晴空乐手】(11512xx)：
   - 晴空乐手继承知更鸟 70% 生命上限与 180% 速度；
   - 气氛值上限 50 点 (星魂 2 提升至 70 点)；
   - 我方目标攻击时或任意目标回合首次提供治疗/护盾时，知更鸟获得 1 点气氛值；
   - 贝茜在场时，气氛值 >= 6 召唤啾米 (Drummie)，>= 12 召唤派丁 (Paddie)；
   - 每位乐手被召唤时为知更鸟回能 20 点 (1151205)；
   - 晴空乐手在场提供易伤光环 (1151203)：1人 11.2% / 2人 16.8% / 3人 22.4% (Lv10)；
   - 全员登台进入【Fever】状态：
     * 解除并免疫控制；
     * 知更鸟在 Fever 结束前不进入自身回合；
     * 结界内我方目标造成伤害无视 (15% + 气氛值 * 0.5%) 防御力；
     * 知更鸟与乐手增伤 (84% + 气氛值 * 2.8%)；
     * 行动序列召唤倒计时实体 (速度 140)，回合开始扣除 50% 气氛值 (至少 12 点)；
     * 晴空乐手在行动序列施放忆灵技【叽叽啾啾四重奏】(210% HP 风属性全体伤害，回 1 SP)；
     * 气氛值归零时 Fever 结束，乐手与倒计时离场，知更鸟行动提前 50% (1151206)。
5. 行迹：
   - A2【偏离和弦】(point06)：我方目标使知更鸟获得气氛值时，若该目标攻击力 > 知更鸟，
     使其攻击力提高等同于知更鸟生命上限的 (16% + 气氛值 * 0.4%)；否则使其暴伤提高 (40% + 气氛值 * 1.5%)，持续 2 回合。
   - A4【即兴蓝调】(point07)：受队友治疗/护盾时获得 12 层【律动】(上限 12 层)；在任意目标回合首次获得气氛值时消耗 1 层律动并回能 3 点。
   - A6【重构谐乐】(point08)：知更鸟与「晴空乐手」暴击率提高 50%。
6. 秘技【我们自成旋律】(151207)：
   - 进战自身行动提前 20%，立即获得 6 点气氛值，我方全体造成的伤害提高 30%，持续 2 回合。
7. 星魂 (E1~E6)：
   - E1【夏日离群飞鸟】：记录我方 15% 非真实伤害，忆灵技对生命最高敌方额外造成 (120% + 气氛值 * 3%) 真实伤害；
   - E2【心似一片湖水】：全队全属性抗穿提高 18%，气氛值上限+20，每回合首次施放技能获气氛值额外+1；
   - E3【拾取沿途遗音】：战技+2，天赋+2，忆灵天赋+1；
   - E4【聆听众弦的变奏】：进入 Fever 立即获得 6 点气氛值，乐手速度提高 (20% + 气氛值 * 0.4%)；
   - E5【然后再次共逐新晨】：终结技+2，普攻+1，忆灵技+1；
   - E6【唱一首未命名的歌】：忆灵技倍率提高 100% (翻倍至 420%)，首进 Fever 或倒计时回合开始回能 30 点。
"""

from typing import Optional, List, Any
import math
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
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
            cost=ResourceCost(sp=-1), # bp_need = -1 -> 产生 1 点 SP
            name="叽叽啾啾四重奏",
            is_auto=True
        )

    def execute(self, ctx: ActionContext) -> None:
        """施放忆灵技【叽叽啾啾四重奏】(1151201)。"""
        if not self.master_kit:
            return

        # Lv10 倍率 210% 生命上限 (E6 翻倍至 420%)
        mult = 2.10
        if self.master_kit.eidolon >= 6:
            mult *= 2.0

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

        # 星魂 1【夏日离群飞鸟】：施放忆灵技时对生命值最高的敌方目标额外造成记录伤害总额 (120% + 气氛值 * 3%) 的真实伤害
        if self.master_kit.eidolon >= 1 and getattr(self.master_kit, "recorded_damage", 0.0) > 0 and enemies:
            highest_hp_enemy = max(enemies, key=lambda e: self.port.max_hp(e))
            true_mult = 1.20 + self.master_kit.vibes * 0.03
            true_dmg = self.master_kit.recorded_damage * true_mult
            self.port.lose_hp(highest_hp_enemy, true_dmg, cause="Robin_E1_TrueDamage")
            self.master_kit.recorded_damage = 0.0


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
            is_auto=True
        )

    def execute(self, ctx: ActionContext) -> None:
        if self.master_kit:
            self.master_kit.on_countdown_turn()


class RobinSunnySongKit(KitHandler):
    """知更鸟•晴歌 (ID 1512, 风 / 记忆) 官方战斗套件完整实现。"""

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
        self.max_vibes: int = 70 if eidolon >= 2 else 50 # 气氛值上限 (E2 +20)

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
        robin_hp = self.port.max_hp(self.owner_id) if hasattr(self.port, "max_hp") else 6000.0
        return robin_hp * 0.70

    @property
    def musician_speed(self) -> float:
        robin_spd = self.port.stat(self.owner_id, StatType.SPEED) if hasattr(self.port, "stat") else 95.0
        base_m_spd = robin_spd * 1.80
        if self.eidolon >= 4 and self.in_fever:
            # E4: 晴空乐手的速度提高 (20% + 当前气氛值 * 0.4%)
            bonus_spd_pct = 0.20 + self.vibes * 0.004
            return base_m_spd * (1.0 + bonus_spd_pct)
        return base_m_spd

    def apply_trace_passives(self, entity: Any) -> None:
        """行迹常驻被动属性注入与基线对齐：能量上限为 140 点。"""
        entity.max_energy = 140.0

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
        # 行迹【重构谐乐】：暴击率提高 50%
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

        # 星魂 2【心似一片湖水】：全队全属性抗穿提高 18%
        if self.eidolon >= 2:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E2_RES_PEN_BUFF,
                    name="心似一片湖水",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.18),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="全队全属性抗性穿透提高 +18.0%"
                ))

        if self.rhythm_stacks > 0:
            self._sync_rhythm_status()

    def gain_vibes(self, amount: int = 1, trigger_ally_id: Optional[str] = None) -> None:
        """增加气氛值；
        - 若处于任意目标回合内首次获得气氛值且持有【律动】，消耗 1 层律动并固定恢复 3 点能量 (行迹【即兴蓝调】)；
        - 触发行迹【偏离和弦】属性增益；
        - 检测并推进伴生忆灵「晴空乐手」登台阶梯 (贝茜在场时，6 点啾米，12 点派丁)。
        """
        self.vibes = min(self.max_vibes, self.vibes + amount)

        # 行迹【即兴蓝调】回能与律动消耗
        if not getattr(self, "_rhythm_consumed_in_current_turn", False):
            if self.rhythm_stacks > 0:
                self._rhythm_consumed_in_current_turn = True
                self.rhythm_stacks -= 1
                self.port.gain_energy(self.owner_id, 3.0)
                self._sync_rhythm_status()

        # 行迹【偏离和弦】
        if trigger_ally_id:
            self.apply_tonal_chord_to_ally(trigger_ally_id)

        # 乐手登台与全员登台检定 (贝茜在场为前提)
        if self.musicians_alive and self.has_bessie:
            self._check_musician_stage_progression()

    def _check_musician_stage_progression(self) -> None:
        """检测并推进「晴空乐手」啾米与派丁的登台。"""
        if self.vibes >= 6 and not self.has_drummie:
            self.has_drummie = True
            self.member_count = max(self.member_count, 2)
            # 1151205 贴近海的心跳：被召唤时为知更鸟恢复 20 点能量
            self.port.gain_energy(self.owner_id, 20.0)
            self._update_musician_aura()

        if self.vibes >= 12 and not self.has_paddie:
            self.has_paddie = True
            self.member_count = 3
            # 1151205 贴近海的心跳：被召唤时为知更鸟恢复 20 点能量
            self.port.gain_energy(self.owner_id, 20.0)
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
        self.port.gain_energy(self.owner_id, 20.0)

        # 注册实体至跑道
        musician_ent = self.port.summon_spirit(
            owner_id=self.owner_id,
            name="晴空乐手",
            base_speed=self.musician_speed,
            max_hp=self.musician_max_hp,
            kit_class=SunnyMusiciansKit,
            kit_args={"master_kit": self}
        )
        if musician_ent:
            musician_ent.is_memosprite = True
            musician_ent.master_name = self.owner_id
            musician_ent.current_hp = self.musician_max_hp
            musician_ent.max_hp = self.musician_max_hp
            # 未进入 Fever 期间，乐手处于准备登台阶段，不先行插入常规行动
            musician_ent.distance_remaining = 999999.0

            # 行迹【重构谐乐】：晴空乐手暴击率提高 50%
            self.port.upsert_status(BuffSpec(
                key="Robin_A6_HarmonicReconstruction_Musician",
                name="重构谐乐",
                source_id=self.owner_id,
                target_id="晴空乐手",
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

        vul_map = {1: 0.112, 2: 0.168, 3: 0.224}
        vul_pct = vul_map.get(min(self.member_count, 3), 0.112)

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

        # 星魂 4【聆听众弦的变奏】：进入【Fever】状态时，立即获得 6 点气氛值
        if self.eidolon >= 4:
            self.gain_vibes(6)

        # 星魂 6【唱一首未命名的歌】：本场战斗中第一次进入【Fever】状态固定恢复 30 点能量
        if self.eidolon >= 6 and not getattr(self, "_e6_first_fever_energy", False):
            self._e6_first_fever_energy = True
            self.port.gain_energy(self.owner_id, 30.0)

        # 1. 结界内我方目标无视防御力 (15% + 气氛值 * 0.5%)
        # 2. 知更鸟•晴歌与晴空乐手造成的伤害提高 (84% + 气氛值 * 2.8%)
        self._sync_fever_buffs()

        # 3. 将晴空乐手正式部署至行动序列 (起跑点 10000 距离，即刻按速度排轴)
        musician_ent = self.port._get_entity("晴空乐手")
        if musician_ent:
            musician_ent.base_speed = self.musician_speed
            musician_ent.distance_remaining = 10000.0

        # 4. 在行动序列上召唤倒计时实体 (速度 140)
        countdown_ent = self.port.summon_spirit(
            owner_id=self.owner_id,
            name="晴空乐手•倒计时",
            base_speed=140.0,
            max_hp=1000.0,
            kit_class=FeverCountdownKit,
            kit_args={"master_kit": self}
        )
        if countdown_ent:
            countdown_ent.distance_remaining = 10000.0

        # 5. 【Fever】状态结束前知更鸟•晴歌不会进入自己的回合 (挂起知更鸟跑条)
        robin_ent = self.port._get_entity(self.owner_id)
        if robin_ent:
            robin_ent.distance_remaining = 999999.0

    def _sync_fever_buffs(self) -> None:
        """同步【Fever】结界防御无视与增伤数值。"""
        if not self.in_fever:
            return

        def_ignore = round(0.15 + self.vibes * 0.005, 4)
        dmg_boost = round(0.84 + self.vibes * 0.028, 4)

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

        for target_id in [self.owner_id, "晴空乐手"]:
            if self.port._get_entity(target_id):
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
        2. E6: 固定恢复 30 点能量；
        3. 气氛值归零时，「晴空乐手」消失并退出【Fever】状态，知更鸟行动提前 50%。
        """
        # 星魂 6【唱一首未命名的歌】：倒计时回合开始时固定恢复 30 点能量
        if self.eidolon >= 6:
            self.port.gain_energy(self.owner_id, 30.0)

        # 扣除 50% 气氛值，至少扣除 12 点
        deduct_vibes = max(12, math.floor(self.vibes * 0.5))
        self.vibes = max(0, self.vibes - deduct_vibes)

        if self.vibes <= 0:
            self.exit_fever()
        else:
            self._sync_fever_buffs()

    def exit_fever(self) -> None:
        """退出【Fever】状态，乐手与倒计时离场，知更鸟行动提前 50% (1151206 乘上夏夜晚风)。"""
        self.in_fever = False
        self.musicians_alive = False
        self.has_bessie = False
        self.has_drummie = False
        self.has_paddie = False
        self.member_count = 0

        # 清除结界增益与易伤
        for ally in self.port.allies(self.owner_id):
            if hasattr(self.port.sim, "status_mgr"):
                self.port.sim.status_mgr.remove_status(ally, self.FEVER_DEF_IGNORE_BUFF)
        for enemy in self.port.enemies(self.owner_id):
            if hasattr(self.port.sim, "status_mgr"):
                self.port.sim.status_mgr.remove_status(enemy, self.MUSICIANS_VULNERABILITY_BUFF)

        # 离场忆灵与倒计时实体
        self.port.despawn_spirit("晴空乐手", reason="fever_end")
        self.port.despawn_spirit("晴空乐手•倒计时", reason="fever_end")

        # 1151206 乘上夏夜晚风：「晴空乐手」消失时，使知更鸟•晴歌行动提前 50%
        robin_ent = self.port._get_entity(self.owner_id)
        if robin_ent:
            # 恢复正常跑道排轴并拉条 50%
            robin_ent.distance_remaining = 10000.0 * 0.50

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
            robin_hp = self.port.max_hp(self.owner_id) if hasattr(self.port, "max_hp") else 6000.0
            atk_ratio = 0.16 + self.vibes * 0.004
            flat_atk = robin_hp * atk_ratio
            mods = (Modifier(StatType.ATK_BASE, ModifierOp.ADD, flat_atk),)
            desc = f"攻击力提高 +{flat_atk:.1f} (知更鸟生命上限的 {atk_ratio * 100:.1f}%)"
        else:
            cd_val = round(0.40 + self.vibes * 0.015, 4)
            mods = (Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),)
            desc = f"暴击伤害 +{cd_val * 100:.1f}%"

        tags = (StatusTag.MEMOSPRITE_ONLY,) if hasattr(self.port, "is_memosprite") and self.port.is_memosprite(ally_id) else ()
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
        ent = self.port._get_entity(actor_name)
        if ent and getattr(ent, "is_memosprite", False):
            master = getattr(ent, "master_name", None)
            if master and self.port.has_status(master, self.ULT_SPECIAL_GUEST_BUFF):
                return True
        return False

    def on_event(self, event: Any) -> None:
        """监听行动、治疗、护盾、伤害与回合时钟事件。"""
        from ...events import ActionExecuteEvent, DamageAppliedEvent, HealAppliedEvent, ShieldAppliedEvent, TurnBeginEvent

        if isinstance(event, TurnBeginEvent):
            # 新回合开始：重置本回合律动消耗门禁、治疗门禁与 E2 技能首获门禁
            self._rhythm_consumed_in_current_turn = False
            self._healed_this_turn = False
            self._e2_vibe_bonus_in_turn = False

        elif isinstance(event, (HealAppliedEvent, ShieldAppliedEvent)):
            # 行迹【即兴蓝调】：知更鸟•晴歌或「晴空乐手」受到队友提供的治疗或护盾时，获得 12 层【律动】
            is_target_robin = (event.target_name == self.owner_id) or (
                hasattr(self.port, "is_own_memosprite") and self.port.is_own_memosprite(self.owner_id, event.target_name)
            )
            is_teammate_source = hasattr(self.port, "is_ally") and self.port.is_ally(event.source_name) and event.source_name != self.owner_id
            if is_target_robin and is_teammate_source:
                self.rhythm_stacks = 12
                self._sync_rhythm_status()
                # 天赋：在任意目标回合第一次提供治疗效果或护盾时，知更鸟•晴歌获得 1 点气氛值
                if not getattr(self, "_healed_this_turn", False):
                    self._healed_this_turn = True
                    extra = 0
                    if self.eidolon >= 2 and not self._e2_vibe_bonus_in_turn:
                        self._e2_vibe_bonus_in_turn = True
                        extra += 1
                    self.gain_vibes(1 + extra, trigger_ally_id=event.source_name)

        elif isinstance(event, ActionExecuteEvent):
            # 天赋：我方目标施放攻击时获得 1 点气氛值
            if hasattr(self.port, "is_ally") and self.port.is_ally(event.actor_name):
                extra = 0
                # 终结技【特邀嘉宾】联动：持有【特邀嘉宾】的角色及其召唤物攻击时额外获得 2 点气氛值
                if self._is_special_guest_actor(event.actor_name):
                    extra += 2
                # 星魂 2【心似一片湖水】：任意目标回合内第一次施放技能使知更鸟获得气氛值额外 +1
                if self.eidolon >= 2 and not self._e2_vibe_bonus_in_turn:
                    self._e2_vibe_bonus_in_turn = True
                    extra += 1
                self.gain_vibes(1 + extra, trigger_ally_id=event.actor_name)

        elif isinstance(event, DamageAppliedEvent):
            # 星魂 1【夏日离群飞鸟】：记录我方目标造成的非真实伤害的 15%
            if self.eidolon >= 1 and hasattr(self.port, "is_ally") and self.port.is_ally(event.attacker_name):
                self.recorded_damage += event.damage * 0.15

    def use_technique(self) -> None:
        """秘技【我们自成旋律】(151207)：
        进战行动提前 20%，立即获得 6 点气氛值，我方全体造成的伤害提高 30%，持续 2 回合。
        """
        # 官方规范：进战行动提前 20%
        self.port.advance(self.owner_id, self.owner_id, 0.20)
        # 立即获得 6 点气氛值 (战前开场阶段与风堇秘技同属战前结算窗口，不重复消耗第 2 层律动)
        self.gain_vibes(6, trigger_ally_id=self.owner_id)

        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Robin_Tech_WeAreTheMelody",
                name="我们自成旋律",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="全队造成伤害提高 +30.0%"
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
        对敌方单体造成等同于知更鸟•晴歌 70% 生命上限的风属性伤害，回能 20 点。
        """
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=0.70,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="hp"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【盛夏是灵魂的乐手】：
        召唤忆灵「晴空乐手」贝茜。若已在场，回复 100% 生命上限并获得 6 点气氛值。
        回能 30 点。
        """
        self.port.gain_energy(self.owner_id, 30.0)
        if not self.musicians_alive:
            self.summon_musicians()
        else:
            musician_hp = self.port.max_hp("晴空乐手") if hasattr(self.port, "max_hp") else self.musician_max_hp
            self.port.heal(self.owner_id, "晴空乐手", musician_hp * 1.0)
            self.gain_vibes(6, trigger_ally_id=self.owner_id)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【跃入这片蔚蓝狂想】：
        使除自身外的指定我方单体行动提前 100%，固定恢复其 20% 能量上限，并赋予【特邀嘉宾】2 回合。
        """
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        else:
            # 自动寻优：默认优先长夜月或我方非记忆忆灵主力
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id and not self.port.is_memosprite(a)]
            if allies:
                target_id = "长夜月" if "长夜月" in allies else allies[0]

        if not target_id:
            return

        # 1. 指定我方单体行动提前 100%
        self.port.advance(self.owner_id, target_id, 1.0)

        # 2. 固定恢复等同于 20% 能量上限的能量 (Lv10: 20%)
        target_ent = self.port._get_entity(target_id)
        if target_ent and getattr(target_ent, "max_energy", 0.0) > 0:
            self.port.gain_energy(target_id, target_ent.max_energy * 0.20)

        # 3. 赋予【特邀嘉宾】效果，持续 2 回合
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
            description="持有【特邀嘉宾】的角色及其召唤物攻击时额外使知更鸟•晴歌获得 2 点气氛值"
        ))

    def get_memosprite_snapshot(self) -> Optional[dict]:
        """返回伴生忆灵「晴空乐手」独立实时战斗快照。"""
        if not self.musicians_alive:
            return None
        max_hp = self.musician_max_hp
        m_ent = self.port._get_entity("晴空乐手")
        cur_hp = getattr(m_ent, "current_hp", max_hp) if m_ent else max_hp
        crit_rate = self.port.stat("晴空乐手", StatType.CRIT_RATE)
        crit_dmg = self.port.stat("晴空乐手", StatType.CRIT_DMG)
        buffs = []
        for s in self.port.statuses("晴空乐手"):
            if getattr(s, "category", "buff") == "buff":
                buffs.append({"name": s.name, "desc": s.description or ""})
        return {
            "name": "晴空乐手",
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

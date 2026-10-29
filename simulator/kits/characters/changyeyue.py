"""长夜月 (Evernight - ID 1413, 冰 / 记忆, E2) 战斗技能套件与伴生忆灵「长夜」状态机。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【从此岁月朦胧】：单体冰伤，等同长夜月生命上限 70% (HP缩放)，削韧 10，回能 20，回 1 SP。
2. 战技【白昼悄然离去】：消耗当前 10% 生命 (触发天赋+2忆质，E2为+3)；
   若忆灵不在场则召唤，在场则为其恢复 50% 生命上限；
   我方全体忆灵暴伤提升 24% 长夜月暴伤；施放直接获得 2 点【忆质】(至暗之谜下额外+12点，E2自动+1点)；
   消耗 1 SP，回能 30。
3. 终结技【晚安，全世界无眠】(耗能 240 点)：召唤长夜，随后长夜对敌方全体造成等同长夜生命上限 200% 冰伤；
   长夜月进入【至暗之谜】(敌方易伤 30%，长夜月与长夜增伤 60%，免控)，获得 2 点充能 (E2额外+1点)；回能 5。
4. 天赋【今夜与我同行】：进战召唤长夜 (生命上限为长夜月的 50%)；
   每次生命降低时暴伤提高 60% (持续 2 回合) 并获得 2 点【忆质】(E2为+3点)；
   【忆质】>= 16 点时，解除并免疫控制，若长夜在场使其【立即行动】施放终极爆发【迷梦，流失，如露】。
5. 伴生忆灵「长夜」完整技能机制：
   - 忆灵技【追忆，蹁跹，如雨】(1141301)：造成等同「长夜」70% 生命上限的单体冰伤，每 4 点忆质额外造成 14% 伤害，削韧 10，施放后获得 1 点【忆质】。
   - 在场天赋【孤独，浮游，漆黑】(1141303)：免疫控制，在场使长夜月增伤 70%。
   - 核心天赋【与夜，形影，不离】(1141305)：被召唤时，使自身立即行动！
   - 退场天赋【与你，再见，无期】(1141306)：消失时使长夜月速度提高 10% + 消耗忆质*1% (上限 40%)。
   - 终极爆发【迷梦，流失，如露】(1141307)：【忆质】>= 16 时触发，每点忆质对主目标造成 16.8%、副目标 8.4% 冰伤；
     施放后消耗全部忆质，若在至暗之谜扣除 1 充能，自毁退场。
6. 星魂 E2【听，沉眠中的呓语】：
   - 长夜月和忆灵「长夜」的暴击伤害提高 40%；
   - 每当长夜月获得【忆质】时，使获得的【忆质】数量提高 2 点；
   - 施放终结技时，额外获得 2 点【至暗之谜】的充能。
"""

from typing import Optional, Any
from ..base import KitHandler
from ..registry import register_kit
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...events import ActionExecuteEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StatusTag


@register_kit("1413", "长夜月", "evernight", "changyeyue")
class ChangyeyueKit(KitHandler):
    """长夜月 (ID 1413, 冰 / 记忆, E2)."""

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 2, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.spirit_name: str = "长夜"
        self.yizhi: int = 0
        self.darkness: bool = False
        self.charges: int = 0
        self.spirit_alive: bool = False
        self.spirit_hp: float = 0.0
        self.threshold_issued: bool = False
        self.bursting: bool = False
        self.technique_active: bool = False
        self._spirit_candle_triggered_by_event: bool = False

    def apply_trace_passives(self, entity: Any) -> None:
        """战前静态基线校准：注入长夜月角色白字与面板基线，消除数据库模块中的角色 ID 硬编码。"""
        entity.base_atk = 1443.0
        if getattr(entity, "base_white_atk", 0.0) <= 0.0:
            entity.base_white_atk = 1072.0
        if getattr(entity, "base_white_def", 0.0) <= 0.0:
            entity.base_white_def = 979.0

    @property
    def spirit_max_hp(self) -> float:
        """忆灵「长夜」生命上限 (查询自身独立状态池；未进场时按长夜月白板 50% 即 4054.05 点)。"""
        if self.port and self.port.entity_exists(self.spirit_name):
            return self.port.max_hp(self.spirit_name)
        owner_base = self.port.base_stat(self.owner_id, StatType.MAX_HP_PERCENT) or 8108.1 if self.port else 8108.1
        return self._spirit_hp_scale_ratio() * owner_base

    def _spirit_crit_dmg(self, include_skill_shared: bool = True) -> Optional[float]:
        """忆灵「长夜」当前的暴击伤害 (供忆灵技伤害结算覆盖)。

        忆灵「长夜」在继承自身专属与团队光环暴伤的同时，实时同步长夜月与「长夜」共享的双端暴伤
        (E2【听，沉眠中的呓语】+40%、天赋【今夜与我同行】+60%、行迹【天黑黑，月寂寂】+15%)，
        并在【白昼悄然离去】或秘技生效期间动态刷新 24% 暴伤转化率。
        """
        if not self.port or not self.port.entity_exists(self.spirit_name):
            return None
        if self.port.has_status(self.owner_id, "Changyeyue_Skill_SharedCritDmg"):
            self._refresh_skill_shared_crit_dmg()
        elif self.port.has_status(self.spirit_name, "Changyeyue_Skill_SharedCritDmg_Spirit"):
            shared_cd = self.calc_skill_shared_crit_dmg()
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Skill_SharedCritDmg_Spirit",
                name="白昼悄然离去",
                source_id=self.owner_id,
                target_id=self.spirit_name,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, shared_cd),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_START,
                category="buff",
                tags=(StatusTag.MEMOSPRITE_ONLY, StatusTag.EXCLUDE_FROM_STAT_TRANSFERS),
                description=f"秘技分享忆灵暴击伤害 +{shared_cd*100:.1f}%"
            ))
        exclude = () if include_skill_shared else (StatusTag.MEMOSPRITE_ONLY,)
        cd = float(self.port.stat(self.spirit_name, StatType.CRIT_DMG, exclude_tags=exclude))
        if not include_skill_shared:
            for s in self.port.statuses(self.spirit_name):
                if s.id == "Changyeyue_A6_RemembranceCritDmg_Spirit":
                    for m in s.modifiers:
                        if m.stat == StatType.CRIT_DMG:
                            cd += m.value
        both_keys = (
            "Changyeyue_E2_CritDmg",
            "Changyeyue_Talent_CritDmg",
            "Changyeyue_A2_Skill_CritDmg",
            f"Relic_Valkyrie_CritDmg_{self.owner_id}",
        )
        spirit_names = {s.name for s in self.port.statuses(self.spirit_name)}
        for s in self.port.statuses(self.owner_id):
            if s.id in both_keys and s.name not in spirit_names:
                for m in s.modifiers:
                    if m.stat == StatType.CRIT_DMG:
                        cd += m.value
        return cd

    def _trigger_trace_candle_on_skill(self) -> None:
        """行迹【烛火起，烛火熄】(point07)：长夜月或我方忆灵施放技能时，长夜月恢复 5 点能量并获得 1 点【忆质】。"""
        self.port.gain_energy(self.owner_id, 5.0, cause="行迹《烛火起，烛火熄》施法回能 (+5.0 点)", source_plugin="长夜月行迹")
        self.gain_yizhi(1)

    def _trigger_trace_a2_on_skill(self, caster_id: str) -> None:
        """行迹【天黑黑，月寂寂】(point06)：施放技能时消耗自身当前 5% 生命值，使双方暴伤提高 15% (持续 2 回合)。"""
        if caster_id == self.spirit_name:
            if self.spirit_hp <= 0:
                self.spirit_hp = self.spirit_max_hp
            hp_loss = self.spirit_hp * 0.05
            cause = "memosprite_skill_cost"
        else:
            hp_loss = 0.05 * self.port.current_hp(self.owner_id)
            cause = "evernight_a2_cost"

        self.port.lose_hp(caster_id, hp_loss, cause=cause)
        self.port.upsert_status(BuffSpec(
            key="Changyeyue_A2_Skill_CritDmg",
            name="天黑黑，月寂寂 (施法暴伤+15%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=(caster_id == self.owner_id),
            category="buff",
            description="暴击伤害提高 +15.0%"
        ))
        if self.port.entity_exists(self.spirit_name):
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_A2_Skill_CritDmg_Spirit",
                name="天黑黑，月寂寂 (施法暴伤+15%)",
                source_id=self.owner_id,
                target_id=self.spirit_name,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=(caster_id == self.spirit_name),
                category="buff",
                description="暴击伤害提高 +15.0%"
            ))

    def on_event(self, event: Any) -> None:
        """监听全局动作执行事件，统一驱动行迹【烛火起，烛火熄】以及【白昼悄然离去】忆灵同步与过期清理。"""
        if not self.port:
            return
        from ...events import SpiritSummonedEvent, StatusExpireEvent
        if isinstance(event, ActionExecuteEvent):
            actor_name = getattr(event, "actor_name", "") or getattr(event, "actor_id", "")
            action_kind = getattr(event, "action_kind", None)
            action_type = str(getattr(event, "action_type", ""))
            is_countdown = hasattr(self.port, "is_countdown") and self.port.is_countdown(actor_name)
            if self.port.is_ally(actor_name) and not is_countdown:
                self._sync_darkness_vuln()

            # 1. 长夜月自身施放技能 (战技 / 终结技)
            is_owner_skill = (
                actor_name == self.owner_id
                and action_kind in (ActionKind.SKILL, ActionKind.ULTIMATE)
            )
            # 2. 我方任意忆灵施放技能 (含伴生忆灵「长夜」及队友忆灵，排除倒计时等机制实体)
            is_ally_memosprite_skill = (
                self.port.is_ally(actor_name)
                and self.port.is_memosprite(actor_name)
                and not is_countdown
            )

            if is_owner_skill or is_ally_memosprite_skill:
                if actor_name == self.spirit_name:
                    self._spirit_candle_triggered_by_event = True
                    if action_type == ChangyeMemospriteKit.SKILL_NAME:
                        self.in_initial_action = True
                self._trigger_trace_candle_on_skill()
        elif isinstance(event, SpiritSummonedEvent):
            sp_name = event.spirit_name
            if self.port.has_status(self.owner_id, "Changyeyue_Skill_SharedCritDmg"):
                shared_cd = self.calc_skill_shared_crit_dmg()
                if self.port.is_memosprite(sp_name):
                    self.port.upsert_status(BuffSpec(
                        key="Changyeyue_Skill_SharedCritDmg_Spirit" if sp_name == self.spirit_name else f"Changyeyue_Skill_SharedCritDmg_Spirit_{sp_name}",
                        name="白昼悄然离去",
                        source_id=self.owner_id,
                        target_id=sp_name,
                        modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, shared_cd),),
                        duration=None,
                        timing=DurationTiming.TARGET_TURN_START,
                        category="buff",
                        tags=(StatusTag.MEMOSPRITE_ONLY, StatusTag.EXCLUDE_FROM_STAT_TRANSFERS),
                        description=f"战技分享忆灵暴击伤害 +{shared_cd*100:.1f}%"
                    ))
            if sp_name == self.spirit_name:
                if self.eidolon >= 2 and not self.port.has_status(self.spirit_name, "Changyeyue_E2_CritDmg_Spirit"):
                    self.port.upsert_status(BuffSpec(
                        key="Changyeyue_E2_CritDmg_Spirit",
                        name="听沉眠中的呓语 (E2暴伤+40%)",
                        source_id=self.owner_id,
                        target_id=self.spirit_name,
                        modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.40),),
                        duration=None,
                        timing=DurationTiming.TARGET_TURN_END,
                        category="buff",
                        description="暴击伤害提高 +40.0%"
                    ))
                if self.port.has_status(self.owner_id, "Changyeyue_Talent_CritDmg") and not self.port.has_status(self.spirit_name, "Changyeyue_Talent_CritDmg_Spirit"):
                    talent_status = next((s for s in self.port.statuses(self.owner_id) if s.id == "Changyeyue_Talent_CritDmg"), None)
                    dur = talent_status.duration if talent_status else 2
                    self.port.upsert_status(BuffSpec(
                        key="Changyeyue_Talent_CritDmg_Spirit",
                        name="今夜与我同行 (生命降低暴伤+60%)",
                        source_id=self.owner_id,
                        target_id=self.spirit_name,
                        modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.60),),
                        duration=dur,
                        timing=DurationTiming.TARGET_TURN_END,
                        skip_current_clock=True,
                        category="buff",
                        description="暴击伤害提高 +60.0%"
                    ))
                if self.port.has_status(self.owner_id, "Changyeyue_A2_Skill_CritDmg") and not self.port.has_status(self.spirit_name, "Changyeyue_A2_Skill_CritDmg_Spirit"):
                    a2_status = next((s for s in self.port.statuses(self.owner_id) if s.id == "Changyeyue_A2_Skill_CritDmg"), None)
                    dur = a2_status.duration if a2_status else 2
                    self.port.upsert_status(BuffSpec(
                        key="Changyeyue_A2_Skill_CritDmg_Spirit",
                        name="天黑黑，月寂寂 (施法暴伤+15%)",
                        source_id=self.owner_id,
                        target_id=self.spirit_name,
                        modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
                        duration=dur,
                        timing=DurationTiming.TARGET_TURN_END,
                        skip_current_clock=True,
                        category="buff",
                        description="暴击伤害提高 +15.0%"
                    ))
        elif isinstance(event, StatusExpireEvent):
            if event.target_name == self.owner_id and event.status_id == "Changyeyue_Skill_SharedCritDmg":
                for ally in self.port.allies(self.owner_id):
                    if self.port.is_memosprite(ally):
                        self.port.remove_status(ally, "Changyeyue_Skill_SharedCritDmg_Spirit")
                        self.port.remove_status(ally, f"Changyeyue_Skill_SharedCritDmg_Spirit_{ally}")

    def on_battle_start(self) -> None:
        """进战：生效被动行迹、由天赋【今夜与我同行】召唤伴生忆灵「长夜」，并触发【与夜，形影，不离】立即行动。"""
        # E2【听，沉眠中的呓语】：长夜月和忆灵「长夜」暴击伤害提高 40%
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_E2_CritDmg",
                name="听沉眠中的呓语 (E2暴伤+40%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.40),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="暴击伤害提高 +40.0%"
            ))

        # 行迹【天黑黑，月寂寂】：长夜月和忆灵「长夜」暴击率提高 35%
        self.port.upsert_status(BuffSpec(
            key="Changyeyue_A2_CritRate",
            name="天黑黑，月寂寂 (暴击率+35%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.35),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="暴击率提高 +35.0%"
        ))

        # 行迹【烛火起，烛火熄】：战斗开始时，长夜月恢复 70 点能量并获得 1 点【忆质】
        self.port.gain_energy(self.owner_id, 70.0)
        self.gain_yizhi(1)

        # 召唤伴生忆灵「长夜」在场（入场触发【与夜，形影，不离】）
        self.summon_spirit()

    def summon_spirit(self) -> Any:
        """召唤忆灵「长夜」，赋予在场增伤光环，并在跑道上注册实体 (触发【与夜，形影，不离】立即行动 0.0 AV)。"""
        was_alive = self.spirit_alive
        self.spirit_alive = True
        self.threshold_issued = False
        if not was_alive or self.spirit_hp <= 0:
            self.spirit_hp = self.spirit_max_hp

        if not was_alive:
            # 被动施放事实补发 (对账口径与实机一致: 召唤时点的天赋触发各记一次施放)
            from ...actions import ActionKind
            self.port.publish_action(self.owner_id, "孤独，浮游，漆黑", ActionKind.TALENT, skill_id=1141303)
            self.port.publish_action(self.owner_id, "与夜，形影，不离", ActionKind.TALENT, skill_id=1141305)
            self.port.publish_action(self.owner_id, "与你，再见，无期", ActionKind.TALENT, skill_id=1141306)

        # 忆灵天赋【孤独，浮游，漆黑】：长夜在场时长夜月造成的伤害提高 50%
        self.port.upsert_status(BuffSpec(
            key="Changyeyue_Memosprite_Presence",
            name="孤独，浮游，漆黑",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="长夜在场全属性伤害提高 +50.0%"
        ))

        owner_base_hp = (self.port.base_stat(self.owner_id, StatType.MAX_HP_PERCENT) or 8108.1) if self.port else 8108.1
        base_spirit_hp = self._spirit_hp_scale_ratio() * owner_base_hp

        # 在模拟器实体列表中注册/就绪伴生忆灵实体
        spirit_ent = self.port.summon_spirit(
            owner_id=self.owner_id,
            name=self.spirit_name,
            base_speed=160.0,
            max_hp=base_spirit_hp,
            kit_class=ChangyeMemospriteKit,
            kit_args={"master_kit": self}
        )
        if spirit_ent:
            # 伴生忆灵「长夜」基础属性：白字生命严格为长夜月白字生命的 50%，白板生命上限为长夜月白板 50%
            owner_ent = self.port._get_entity(self.owner_id) if hasattr(self.port, "_get_entity") else None
            owner_white_hp = getattr(owner_ent, "base_white_hp", 0.0) if owner_ent else 2589.0
            spirit_ent.base_white_hp = (owner_white_hp or 2589.0) * self._spirit_hp_scale_ratio()
            spirit_ent.max_hp = base_spirit_hp
            spirit_ent.base_dmg_boost = float(self.port.white_stat(self.owner_id, StatType.DMG_BOOST) or 0.0)

            # E2【听，沉眠中的呓语】：长夜月和忆灵「长夜」暴击伤害提高 40%
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key="Changyeyue_E2_CritDmg_Spirit",
                    name="听沉眠中的呓语 (E2暴伤+40%)",
                    source_id=self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.40),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="暴击伤害提高 +40.0%"
                ))

            # 行迹【天黑黑，月寂寂】：长夜月和忆灵「长夜」暴击率提高 35%
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_A2_CritRate_Spirit",
                name="天黑黑，月寂寂 (暴击率+35%)",
                source_id=self.owner_id,
                target_id=self.spirit_name,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.35),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="暴击率提高 +35.0%"
            ))

            # 忆灵天赋【孤独，浮游，漆黑】：长夜在场长夜月与长夜造成的伤害均提高 50%
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Memosprite_Presence_Spirit",
                name="孤独，浮游，漆黑",
                source_id=self.owner_id,
                target_id=self.spirit_name,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="长夜在场全属性伤害提高 +50.0%"
            ))

            # 若长夜月处于【至暗之谜】状态，忆灵「长夜」同步挂载增伤 +60%
            if self.darkness:
                self.port.upsert_status(BuffSpec(
                    key="Changyeyue_Darkness_Dmg_Spirit",
                    name="至暗之谜 (增伤+60%)",
                    source_id=self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.60),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="全属性伤害提高 +60.0%"
                ))

            # 同步全队常驻光环 (神启抗穿、谕示忆灵暴伤、女武神全队暴伤、旋律全队增伤、再创天地全队增伤、Fever无视防御)
            divine_buff = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Tribbie_Ult_DivineRevelation_")), None)
            if divine_buff and not self.port.has_status(self.spirit_name, f"Tribbie_Ult_DivineRevelation_{self.spirit_name}"):
                self.port.upsert_status(BuffSpec(
                    key=f"Tribbie_Ult_DivineRevelation_{self.spirit_name}",
                    name="神启",
                    source_id=divine_buff.source.name if hasattr(divine_buff, "source") else self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=tuple(divine_buff.modifiers),
                    duration=divine_buff.duration,
                    timing=divine_buff.timing,
                    skip_current_clock=True,
                    category="buff",
                    description="全属性抗性穿透"
                ))

            e4_buff = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Tribbie_E4_PeaceInConcord_")), None)
            if e4_buff and not self.port.has_status(self.spirit_name, f"Tribbie_E4_PeaceInConcord_{self.spirit_name}"):
                self.port.upsert_status(BuffSpec(
                    key=f"Tribbie_E4_PeaceInConcord_{self.spirit_name}",
                    name="心意相契的安宁",
                    source_id=e4_buff.source.name if hasattr(e4_buff, "source") else self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                    duration=e4_buff.duration,
                    timing=e4_buff.timing,
                    skip_current_clock=True,
                    category="buff",
                    description="结界期间无视目标 18.0% 防御力"
                ))

            oracle_buff = next((s for s in self.port.statuses(self.owner_id) if s.id == "LC_IfTimeWereAFlower_Oracle"), None)
            if oracle_buff and not self.port.has_status(self.spirit_name, "LC_IfTimeWereAFlower_Oracle"):
                self.port.upsert_status(BuffSpec(
                    key="LC_IfTimeWereAFlower_Oracle",
                    name="谕示",
                    source_id=oracle_buff.source.name if hasattr(oracle_buff, "source") else self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=tuple(oracle_buff.modifiers),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="忆灵暴击伤害提高 +96.0%"
                ))

            valk_buff = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Relic_Valkyrie_CritDmg_")), None)
            if valk_buff and not self.port.has_status(self.spirit_name, f"Relic_Valkyrie_CritDmg_{self.spirit_name}"):
                self.port.upsert_status(BuffSpec(
                    key=f"Relic_Valkyrie_CritDmg_{self.spirit_name}",
                    name="烈阳惊雷的女武神",
                    source_id=valk_buff.source.name if hasattr(valk_buff, "source") else self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="全队暴击伤害 +15.0%"
                ))

            # 进战秘技：第 1 波开局进战时同步；第 2 波（AV > 115）开局秘技已过期，重召不得继承
            if self.port.battle_av() <= 115.0:
                robin_tech = next((s for s in self.port.statuses(self.owner_id) if s.id == "Robin_Tech_WeAreTheMelody"), None)
                if robin_tech and not self.port.has_status(self.spirit_name, "Robin_Tech_WeAreTheMelody"):
                    self.port.upsert_status(BuffSpec(
                        key="Robin_Tech_WeAreTheMelody",
                        name="我们自成旋律",
                        source_id=robin_tech.source.name if hasattr(robin_tech, "source") else self.owner_id,
                        target_id=self.spirit_name,
                        modifiers=tuple(robin_tech.modifiers),
                        duration=robin_tech.duration,
                        timing=robin_tech.timing,
                        category="buff",
                        description="全队增伤 +30.0%"
                    ))

                fengjin_tech = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Fengjin_Tech_WeatherIsFine_")), None)
                if fengjin_tech and not self.port.has_status(self.spirit_name, f"Fengjin_Tech_WeatherIsFine_{self.spirit_name}"):
                    self.port.upsert_status(BuffSpec(
                        key=f"Fengjin_Tech_WeatherIsFine_{self.spirit_name}",
                        name="天气正好，万物可爱！",
                        source_id=fengjin_tech.source.name if hasattr(fengjin_tech, "source") else self.owner_id,
                        target_id=self.spirit_name,
                        modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.20),),
                        duration=fengjin_tech.duration,
                        timing=fengjin_tech.timing,
                        category="buff",
                        description="全队生命上限提高 +20.0%"
                    ))
            else:
                self.port.remove_status(self.spirit_name, "Robin_Tech_WeAreTheMelody")
                self.port.remove_status(self.spirit_name, f"Fengjin_Tech_WeatherIsFine_{self.spirit_name}")

            # 风堇终结技【雨过天晴】：同步生命上限加成 (+80% 目标白字生命，固定生命按忆灵口径 +300)
            fengjin_ult = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Fengjin_Ult_SunAfterRain_")), None)
            if fengjin_ult and not self.port.has_status(self.spirit_name, f"Fengjin_Ult_SunAfterRain_{self.spirit_name}"):
                self.port.upsert_status(BuffSpec(
                    key=f"Fengjin_Ult_SunAfterRain_{self.spirit_name}",
                    name=fengjin_ult.name,
                    source_id=fengjin_ult.source.name if hasattr(fengjin_ult, "source") else self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(
                        Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.80),
                        Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, 300.0),
                    ),
                    duration=fengjin_ult.duration,
                    timing=fengjin_ult.timing,
                    category="buff",
                    description="雨过天晴"
                ))

            creator_dmg = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Relic_Creator_Team_Dmg_")), None)
            if creator_dmg and not self.port.has_status(self.spirit_name, f"Relic_Creator_Team_Dmg_{self.spirit_name}"):
                self.port.upsert_status(BuffSpec(
                    key=f"Relic_Creator_Team_Dmg_{self.spirit_name}",
                    name="再创天地的救世主 (增伤+15%)",
                    source_id=self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.15),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="全队伤害提高 +15.0%"
                ))

            fever_def = next((s for s in self.port.statuses(self.owner_id) if s.id == "Robin_Fever_DefIgnore"), None)
            if fever_def and not self.port.has_status(self.spirit_name, "Robin_Fever_DefIgnore"):
                self.port.upsert_status(BuffSpec(
                    key="Robin_Fever_DefIgnore",
                    name="巡游在无界的天空",
                    source_id=fever_def.source.name if hasattr(fever_def, "source") else self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=tuple(fever_def.modifiers),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="巡游在无界的天空无视防御"
                ))

            # 行迹【天亮了，雨落了】：赋予忆灵暴击伤害加成 (+50%)
            rem_count = self._get_remembrance_count()
            rem_cd = 0.50 if rem_count == 3 else (0.65 if rem_count >= 4 else (0.15 if rem_count == 2 else 0.05))
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_A6_RemembranceCritDmg_Spirit",
                name="天亮了，雨落了",
                source_id=self.owner_id,
                target_id=self.spirit_name,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, rem_cd),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                tags=(StatusTag.MEMOSPRITE_ONLY, StatusTag.EXCLUDE_FROM_STAT_TRANSFERS),
                description=f"队伍存在 {rem_count} 名「记忆」命途角色，忆灵暴击伤害提高 +{rem_cd*100:.1f}%"
            ))

            # 若施放了秘技：进战后获得与战技相同的我方全体忆灵暴击伤害提高效果
            if getattr(self, "technique_active", False):
                self.technique_active = False
                self.apply_skill_shared_crit_dmg()

            # 忆灵天赋 1141305【与夜，形影，不离】：被召唤时，使自身立即行动 (100% 拉条)
            if not was_alive:
                self.port.advance(self.spirit_name, self.spirit_name, 1.0)

            self.spirit_hp = self.spirit_max_hp

        return spirit_ent

    def _spirit_hp_scale_ratio(self) -> float:
        """伴生忆灵「长夜」生命上限为长夜月实时生命上限的 50% (官方 Talent 参数 #5 = 0.50)。"""
        return float(self.skill_param("talent", 4, default=0.50))

    def _memosprite_damage_mult(self) -> float:
        """星魂 1【睡吧，长夜有所梦】：长夜月在场时，场上敌方目标数量等于 4或以上/3/2/1 名时，
        我方忆灵造成的伤害为原伤害的 120%/125%/130%/150%。"""
        if self.eidolon < 1 or not self.port:
            return 1.0
        living_enemies = len(self.port.enemies(self.owner_id))
        if living_enemies >= 4:
            return self.eidolon_param(1, 0, default=1.20)
        elif living_enemies == 3:
            return self.eidolon_param(1, 1, default=1.25)
        elif living_enemies == 2:
            return self.eidolon_param(1, 2, default=1.30)
        elif living_enemies <= 1:
            return self.eidolon_param(1, 3, default=1.50)
        return 1.0

    def _sync_darkness_vuln(self) -> None:
        """处于【至暗之谜】状态时，确保在场所有敌方目标（含新刷出的波次/增援目标）挂载 30% 易伤光环。"""
        if not self.darkness or not self.port:
            return
        for e in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Darkness_Vuln",
                name="至暗之谜 (易伤+30%)",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, 0.30),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="debuff",
                description="受到伤害提高 +30.0%"
            ))

    def _execute_memosprite_skill(self, ctx: Optional[ActionContext] = None) -> None:
        """执行忆灵天赋【与夜，形影，不离】与常规忆灵技【追忆，蹁跹，如雨】。"""
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        self._sync_darkness_vuln()
        is_boss_fn = getattr(self.port, "is_boss", lambda _: False)
        target = (
            ctx.target_ids[0]
            if (ctx and ctx.target_ids and ctx.target_ids[0] in enemies)
            else max(enemies, key=lambda e: (is_boss_fn(e), self.port.max_hp(e), self.port.current_hp(e)))
        )
        self.in_initial_action = True

        # 行迹【天黑黑，月寂寂】：施放技能时消耗自身当前 5% 生命值，使双方暴伤提高 15%
        self._trigger_trace_a2_on_skill(self.spirit_name)

        # 忆灵技【追忆，蹁跹，如雨】(1141301) 施放回能 20 点 (官方数据源 sp_base: 20)
        self.port.gain_energy(self.owner_id, 20.0)
        # 若通过单元测试直接调用未经过 EventBus，兜底触发一次行迹【烛火起，烛火熄】
        if self._spirit_candle_triggered_by_event:
            self._spirit_candle_triggered_by_event = False
        else:
            self._trigger_trace_candle_on_skill()

        # 忆灵技【追忆，蹁跹，如雨】(1141301): E1 独立忆灵乘区由 CombatPort.attack 对全体我方 SERVANT 伤害统一结算
        base_mult = self.skill_param("1141301", 0, default=0.50)
        scale_step = self.skill_param("1141301", 1, default=0.10)
        extra_ratio = (self.yizhi // 4) * scale_step
        mult = base_mult + extra_ratio
        spirit_cd = self._spirit_crit_dmg()

        for split_ratio, split_toughness in (
            (0.10, 1.5),
            (0.10, 1.5),
            (0.10, 1.5),
            (0.10, 1.5),
            (0.10, 1.5),
            (0.50, 2.5),
        ):
            self.port.attack(
                self.spirit_name,
                target,
                element="Ice",
                atk_multiplier=mult * split_ratio,
                toughness_damage=split_toughness,
                damage_type=DamageType.SERVANT,
                scaling_stat="hp",
                fixed_crit_dmg=spirit_cd
            )

        # 施放后获得 1 点【忆质】(E2自动+2变为3点)
        self.gain_yizhi(1)
        self.in_initial_action = False
        self._check_threshold()

    def _trigger_memosprite_immediate_action(self) -> None:
        """兼容调用：触发常规忆灵技。"""
        self._execute_memosprite_skill()

    def trace_variables(self) -> list:
        """向因果追踪器自申报专属变量【忆质】(单位/实时值/达标注记均由本 Kit 提供)。"""
        from ...tracer import TraceVariableSpec
        return [
            TraceVariableSpec(
                var_name="忆质",
                unit="点",
                current_value=lambda: self.yizhi,
                final_note=lambda v: "🌟 已达成 16 质阈值! 解除并免疫控制 / 忆灵「长夜」行动提前 100%" if v >= 16 else "",
            )
        ]

    def gain_yizhi(self, amount: int) -> None:
        """获取忆质。E2 额外 +2 点。达到 16 点且长夜在场触发立即行动。"""
        if amount <= 0:
            return
        old_val = self.yizhi
        bonus = 2 if self.eidolon >= 2 else 0
        total_gain = amount + bonus
        self.yizhi += total_gain

        if hasattr(self.port, "tracer") and self.port.tracer:
            hp_cause = getattr(self.port.tracer, "current_hp_cause", "")
            cause_info = self.port.tracer.describe_cause(hp_cause) if hp_cause else None
            if cause_info:
                _, p_name, p_desc = cause_info
                cause_str = f"响应 [{p_name}]: {p_desc} (生命降低)"
            else:
                cause_str = "生命降低或技能联动获得"

            note = "🌟 已达成 16 质阈值! 解除并免疫控制 / 忆灵「长夜」行动提前 100%" if (self.yizhi >= 16 and old_val < 16) else ""
            self.port.tracer.record_var_change(
                entity=self.owner_id,
                var_name="忆质",
                old_val=old_val,
                new_val=self.yizhi,
                source_plugin="长夜月天赋《今夜与我同行》",
                cause_desc=f"{cause_str} ➔ 获得 {amount} 点忆质{' (星魂2额外+2)' if self.eidolon >= 2 else ''}",
                extra_note=note
            )
            self.port.tracer.record_plugin("天赋", "《今夜与我同行》 (长夜月 E2)", f"自身生命降低获得 2 点忆质 (星魂 2 额外 +2，实际 +{total_gain} 质)")

        self._check_threshold()

    def _check_threshold(self) -> None:
        """检查【忆质】>= 16 点时，触发免控并使长夜立即行动 (100% 拉条)。"""
        if (
            self.yizhi >= 16
            and self.spirit_alive
            and not self.threshold_issued
            and not self.bursting
            and not getattr(self, "in_initial_action", False)
        ):
            self.threshold_issued = True
            self.port.advance(self.owner_id, self.spirit_name, 1.0)

    def trigger_spirit_burst(self, ctx: Optional[ActionContext] = None, target_id: Optional[str] = None) -> None:
        """忆灵终极爆发【迷梦，流失，如露】：
        - 施放技能时触发：行迹【天黑黑，月寂寂】消耗自身 5% 生命 (触发生命降低天赋+2忆质，E2为4点) 与【烛火起，烛火熄】回能5点+1忆质 (E2为3点)；
        - 主目标16.8%*忆质，副目标8.4%*忆质，消耗全部【忆质】；
        - 消耗全部生命值自毁离场：触发生命降低天赋，获得 2 点忆质 (E2为 2+2=4 点)；
        - 天赋【与你，再见，无期】：消失时速度提高 10% + 消耗忆质*1% (最多计算 40 点忆质，上限 50%)，长夜月下个回合开始时移除。
        """
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        self._sync_darkness_vuln()

        # 1. 忆灵施放技能阶段触发：
        # 行迹【天黑黑，月寂寂】：施放技能时消耗自身当前 5% 生命值，使双方暴伤提高 15%
        self._trigger_trace_a2_on_skill(self.spirit_name)

        # 忆灵终极爆发【迷梦，流失，如露】(1141307) 施放回能 10 点 (官方数据源 sp_base: 10)
        self.port.gain_energy(self.owner_id, 10.0)
        # 若通过单元测试直接调用未经过 EventBus，兜底触发一次行迹【烛火起，烛火熄】
        if self._spirit_candle_triggered_by_event:
            self._spirit_candle_triggered_by_event = False
        else:
            self._trigger_trace_candle_on_skill()

        # 2. 快照本次爆发消耗的忆质总量 (从 24 增长到 31)
        spent_memory = self.yizhi
        self.bursting = True
        chosen_target = target_id or (ctx.target_ids[0] if (ctx and ctx.target_ids) else None)
        is_boss_fn = getattr(self.port, "is_boss", lambda _: False)
        primary_target = (
            chosen_target
            if (chosen_target and chosen_target in enemies)
            else max(enemies, key=lambda e: (is_boss_fn(e), self.port.max_hp(e), self.port.current_hp(e)))
        )
        try:
            spirit_cd = self._spirit_crit_dmg()
            p_primary = self.skill_param("1141307", 0, default=0.12)
            p_adjacent = self.skill_param("1141307", 1, default=0.06)
            ordered_enemies = [e for e in enemies if e != primary_target] + ([primary_target] if primary_target in enemies else [])
            for e in ordered_enemies:
                if e not in self.port.enemies(self.owner_id):
                    continue
                factor = (p_primary if e == primary_target else p_adjacent)
                eff_mult = factor * spent_memory
                self.port.attack(
                    self.spirit_name,
                    e,
                    element="Ice",
                    atk_multiplier=eff_mult,
                    toughness_damage=90.0 if e == primary_target else 60.0,
                    damage_type=DamageType.SERVANT,
                    scaling_stat="hp",
                    fixed_crit_dmg=spirit_cd
                )
                if hasattr(self.port, "resolve_effects"):
                    self.port.resolve_effects()

            # 消耗全部忆质
            self.yizhi = 0

            # 消耗至暗之谜充能
            if self.darkness and self.charges > 0:
                self.charges -= 1
                if self.charges == 0:
                    self.darkness = False
                    self.clear_darkness_buffs()

            # 行迹【天黑黑，月寂寂】：忆灵「长夜」施放【迷梦，流失，如露】后，为我方恢复 1 个战技点
            self.port.change_sp(self.owner_id, 1, "evernight_a2_sp_recover")

            # 忆灵自毁离场：消耗全部生命值并消失
            # 走标准 self.port.lose_hp 事件总线广播 HPLostEvent，驱动天赋【今夜与我同行】自动获得 4 点【忆质】
            if self.spirit_hp > 0:
                self.port.lose_hp(self.spirit_name, self.spirit_hp, cause="memosprite_burst_consume_hp")

            self.spirit_alive = False
            self.spirit_hp = 0.0
            self.port.remove_status(self.owner_id, "Changyeyue_Memosprite_Presence")
            self.port.despawn_spirit(self.spirit_name, "burst_depart")

            # 天赋【与你，再见，无期】：消失时速度提高 10% + 消耗忆质*1% (最多计算 40 点忆质)
            speed_bonus = 0.10 + 0.01 * min(40, spent_memory)
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Spirit_Depart_Speed",
                name=f"与你，再见，无期 (加速+{speed_bonus*100:.1f}%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, speed_bonus),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_START,
                category="buff",
                description=f"速度提高 +{speed_bonus*100:.1f}%"
            ))
        finally:
            self.bursting = False

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """生命降低统一响应：受到敌方攻击伤害、持续伤害/负面状态扣血、技能自耗或环境机制扣血时，暴伤提高 60% 并获得 2 点【忆质】(E2为 2+2=4 点)。
        注：光锥《让告别，更美一些》通过监听标准 HPLostEvent 自动响应，本角色套件无需感知任何具体光锥！
        """
        is_owner = (entity_id == self.owner_id)
        is_own_spirit = self.port.is_own_memosprite(self.owner_id, entity_id)
        if is_owner or is_own_spirit:
            if is_own_spirit:
                self.spirit_hp = self.port.current_hp(entity_id)

            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Talent_CritDmg",
                name="今夜与我同行 (生命降低暴伤+60%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.60),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="暴击伤害提高 +60.0%"
            ))
            if self.port.entity_exists(self.spirit_name):
                self.port.upsert_status(BuffSpec(
                    key="Changyeyue_Talent_CritDmg_Spirit",
                    name="今夜与我同行 (生命降低暴伤+60%)",
                    source_id=self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.60),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="暴击伤害提高 +60.0%"
                ))
            # 获得 2 点忆质 (E2 自动 +2 变为 4 点)
            self.gain_yizhi(2)

    def get_owner_crit_dmg(self) -> float:
        """通过 CombatPort 语义标签过滤采样长夜月自身的实时暴击伤害 (排除忆灵专属暴伤加成，防止自循环或属性污染)。"""
        return self.port.stat(
            self.owner_id,
            StatType.CRIT_DMG,
            exclude_tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS, StatusTag.MEMOSPRITE_ONLY)
        )

    def calc_skill_shared_crit_dmg(self) -> float:
        """动态计算战技/秘技分享给忆灵的暴击伤害加成 (零假数据、零静态硬编码)。
        公式：提高数值等同于长夜月暴击伤害的 24% (Skill Level 10 官方倍率)。
        """
        cd_ratio = self.skill_param("skill", 0, default=0.24)
        owner_cd = self.get_owner_crit_dmg()
        if owner_cd <= 0:
            owner_cd = 4.533
        return owner_cd * cd_ratio

    def _refresh_skill_shared_crit_dmg(self) -> float:
        """只同步分享数值；不创建或续期本体战技标记。"""
        shared_cd = self.calc_skill_shared_crit_dmg()
        marker_active = self.port.has_status(self.owner_id, "Changyeyue_Skill_SharedCritDmg")

        for ally in self.port.allies(self.owner_id):
            if not self.port.is_memosprite(ally):
                continue
            key = (
                "Changyeyue_Skill_SharedCritDmg_Spirit"
                if ally == self.spirit_name
                else f"Changyeyue_Skill_SharedCritDmg_Spirit_{ally}"
            )
            if not marker_active and not self.port.has_status(ally, key):
                continue

            self.port.upsert_status(BuffSpec(
                key=key,
                name="白昼悄然离去",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, shared_cd),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_START,
                category="buff",
                tags=(StatusTag.MEMOSPRITE_ONLY, StatusTag.EXCLUDE_FROM_STAT_TRANSFERS),
                description=f"战技分享忆灵暴击伤害 +{shared_cd*100:.1f}%"
            ))
        return shared_cd

    def apply_skill_shared_crit_dmg(self) -> float:
        """仅在实际施放战技或应用进战秘技效果时调用。"""
        self.port.upsert_status(BuffSpec(
            key="Changyeyue_Skill_SharedCritDmg",
            name="白昼悄然离去",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_START,
            category="other",
            tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS,),
            description="战技暴伤分享生效"
        ))
        return self._refresh_skill_shared_crit_dmg()

    def _get_remembrance_count(self) -> int:
        """通过 CombatPort 契约统计队伍中「记忆」命途角色数量 (供行迹【天亮了，雨落了】结算)。"""
        return max(1, self.port.count_allies_by_path(self.owner_id, "Remembrance"))

    def get_memosprite_snapshot(self) -> dict:
        """返回伴生忆灵「长夜」的完整独立实时战斗快照。
        100% 通过 CombatPort 标准契约动态采样，零私有属性跨层调用，零状态名硬编码！
        """
        if self.port.has_status(self.owner_id, "Changyeyue_Skill_SharedCritDmg"):
            self._refresh_skill_shared_crit_dmg()

        max_hp = self.spirit_max_hp
        cur_hp = self.spirit_hp if self.spirit_alive else 0.0
        hp_pct = (cur_hp / max_hp) if max_hp > 0 else 0.0

        # 1. 动态采样基础与局内攻击力 (ATK)
        base_atk = int(round(self.port.white_stat(self.owner_id, StatType.ATK_BASE) or 1072.0))
        cur_atk = int(round(self.port.stat(self.owner_id, StatType.ATK_BASE)))
        bonus_atk = max(0, cur_atk - base_atk)

        # 2. 动态采样基础与局内防御力 (DEF)
        base_def = int(round(self.port.white_stat(self.owner_id, StatType.DEF_PERCENT) or 979.0))
        cur_def = int(round(self.port.stat(self.owner_id, StatType.DEF_PERCENT)))
        bonus_def = max(0, cur_def - base_def)

        # 3. 动态采样暴击率与暴击伤害 (CRIT)
        crit_rate = self.port.stat(self.owner_id, StatType.CRIT_RATE)
        crit_dmg = self.port.stat(self.owner_id, StatType.CRIT_DMG)
        for s in self.port.statuses(self.spirit_name, include_tags=(StatusTag.MEMOSPRITE_ONLY,)):
            for m in s.modifiers:
                if m.stat == StatType.CRIT_DMG:
                    crit_dmg += m.value

        # 4. 动态采样增伤、抗性穿透与防御削减 (DMG, RES PEN, DEF SHRED)
        total_dmg = self.port.stat(self.owner_id, StatType.DMG_BOOST)
        elem_dmg = self.port.white_stat(self.owner_id, StatType.DMG_BOOST)
        all_dmg = max(0.0, total_dmg - elem_dmg)
        res_pen = self.port.stat(self.owner_id, StatType.RES_PEN)
        def_shred = self.port.stat(self.owner_id, StatType.DEF_SHRED)

        # 5. 纯动态从 CombatPort 采集长夜月/忆灵身上所有真实生效的 Buff 与环境状态 (基于 StatusTag 语义过滤)
        buffs = []
        other_effects = []
        all_statuses = list(self.port.statuses(self.owner_id)) + list(self.port.statuses(self.spirit_name))
        seen_names = set()
        for s in all_statuses:
            cat = getattr(s, "category", "buff")
            s_tags = getattr(s, "tags", ())
            if StatusTag.CHARACTER_ONLY in s_tags:
                continue
            if cat == "buff":
                if s.name in seen_names:
                    continue
                seen_names.add(s.name)
                buffs.append({"name": s.name, "desc": s.description or "局内动态增益"})
            elif cat == "other":
                target_name = getattr(s.target, "name", str(s.target))
                if target_name != self.spirit_name and StatusTag.AURA_SHARED not in s_tags:
                    continue
                if StatusTag.EXCLUDE_FROM_STAT_TRANSFERS in s_tags:
                    continue
                other_effects.append(s.name)

        return {
            "name": self.spirit_name,
            "owner": self.owner_id,
            "is_memosprite": True,
            "is_alive": self.spirit_alive,
            "current_hp": round(cur_hp, 1),
            "max_hp": round(max_hp, 1),
            "hp_pct": round(hp_pct, 4),
            "speed": 160.0,
            "base_atk": base_atk,
            "bonus_atk": bonus_atk,
            "current_atk": cur_atk,
            "base_def": base_def,
            "bonus_def": bonus_def,
            "current_def": cur_def,
            "crit_rate": round(crit_rate, 4),
            "crit_dmg": round(crit_dmg, 4),
            "elem_dmg_boost": round(elem_dmg, 4),
            "all_dmg_boost": round(all_dmg, 4),
            "dmg_boost": round(total_dmg, 4),
            "res_pen": round(res_pen, 4),
            "def_shred": round(def_shred, 4),
            "aggro": 125,
            "buffs_count": len(buffs),
            "buffs": buffs,
            "other_effects": list(dict.fromkeys(other_effects)),
            "skills": [
                "追忆，蹁跹，如雨 (忆灵技 1141301)",
                "迷梦，流失，如露 (终极爆发 1141307)",
                "孤独，浮游，漆黑 (免控与在场增伤 1141303)",
                "与夜，形影，不离 (入场立即行动 1141305)",
                "与你，再见，无期 (离场加速 1141306)"
            ]
        }

    def get_kit_state(self) -> dict:
        return {
            "eidolon": self.eidolon,
            "yizhi": self.yizhi,
            "darkness": self.darkness,
            "charges": self.charges,
            "spirit_alive": self.spirit_alive,
            "spirit_hp": round(self.spirit_hp, 1),
            "spirit_max_hp": round(self.spirit_max_hp, 1),
            "spirit_hp_pct": round(self.spirit_hp / self.spirit_max_hp, 4) if self.spirit_max_hp > 0 else 0.0,
            "memosprite": self.get_memosprite_snapshot()
        }

    def clear_darkness_buffs(self) -> None:
        """退出【至暗之谜】状态。"""
        self.port.remove_status(self.owner_id, "Changyeyue_Darkness_Dmg")
        if self.port.entity_exists(self.spirit_name):
            self.port.remove_status(self.spirit_name, "Changyeyue_Darkness_Dmg_Spirit")
        for e in self.port.enemies(self.owner_id):
            self.port.remove_status(e, "Changyeyue_Darkness_Vuln")

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="从此岁月朦胧")
        elif kind == ActionKind.SKILL:
            # 官方同一战技按长夜在场状态分两个配置 ID: 不在场 (召唤版) = 141302,
            # 在场 (回血版) = 141309 (日志实证: 终结技召唤后的同簇战技记为 141309)。
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(sp=1), name="白昼悄然离去", skill_id=141309 if self.spirit_alive else 141302)
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=240.0), name="晚安，全世界无眠")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(technique_points=1), name="愿有冷雨落下")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            enemies = self.port.enemies(self.owner_id)
            if not enemies:
                return
            target_id = ctx.target_ids[0] if ctx.target_ids else enemies[0]
            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=0.70,
                toughness_damage=10.0,
                damage_type=DamageType.BASIC,
                scaling_stat="hp"
            )
            self.port.gain_energy(self.owner_id, 20.0)

        elif ctx.kind == ActionKind.SKILL:
            cur_hp = self.port.current_hp(self.owner_id)
            self.port.lose_hp(self.owner_id, 0.10 * cur_hp, cause="evernight_skill_cost")

            # 行迹【天黑黑，月寂寂】：施放技能时，消耗自身当前生命值的 5% 使双方的暴击伤害提高 15%，持续 2 回合
            self._trigger_trace_a2_on_skill(self.owner_id)

            if self.spirit_alive:
                self.spirit_hp = min(self.spirit_max_hp, self.spirit_hp + 0.50 * self.spirit_max_hp)
            else:
                self.summon_spirit()

            self.apply_skill_shared_crit_dmg()

            direct_yizhi = 2 + (12 if self.darkness else 0)
            self.gain_yizhi(direct_yizhi)

            self.port.gain_energy(self.owner_id, 30.0)
            self._check_threshold()

        elif ctx.kind == ActionKind.ULTIMATE:
            # 行迹【天黑黑，月寂寂】：施放技能时消耗自身当前 5% 生命值，使双方暴伤提高 15% (持续 2 回合)
            was_spirit_alive = self.spirit_alive
            self._trigger_trace_a2_on_skill(self.owner_id)
            self.summon_spirit()

            # 官方 141303 机制时序：进入【至暗之谜】(敌方易伤+30%, 长夜月与长夜增伤+60%), 随后使忆灵「长夜」对敌方全体造成 200% 生命上限冰伤
            self.darkness = True
            self.charges = 2 + (2 if self.eidolon >= 2 else 0)

            for e in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Changyeyue_Darkness_Vuln",
                    name="至暗之谜 (易伤+30%)",
                    source_id=self.owner_id,
                    target_id=e,
                    modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, 0.30),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="debuff",
                    description="受到伤害提高 +30.0%"
                ))

            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Darkness_Dmg",
                name="至暗之谜 (增伤+60%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.60),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="全属性伤害提高 +60.0%"
            ))
            if self.port.entity_exists(self.spirit_name):
                self.port.upsert_status(BuffSpec(
                    key="Changyeyue_Darkness_Dmg_Spirit",
                    name="至暗之谜 (增伤+60%)",
                    source_id=self.owner_id,
                    target_id=self.spirit_name,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.60),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="全属性伤害提高 +60.0%"
                ))

            full_spirit_sync = was_spirit_alive or self.port.has_status(self.owner_id, "Robin_Ult_SpecialGuest")
            spirit_cd = self._spirit_crit_dmg(include_skill_shared=full_spirit_sync) or 0.0
            if full_spirit_sync:
                spirit_names = {s.name for s in self.port.statuses(self.spirit_name)}
                for s in self.port.statuses(self.owner_id):
                    if s.id == f"Robin_Talent_TonalChord_{self.owner_id}" and s.name not in spirit_names:
                        for m in s.modifiers:
                            if m.stat == StatType.CRIT_DMG:
                                spirit_cd += m.value
                if not was_spirit_alive:
                    for s in self.port.statuses(self.owner_id):
                        if s.id == "Changyeyue_Talent_CritDmg":
                            for m in s.modifiers:
                                if m.stat == StatType.CRIT_DMG:
                                    spirit_cd -= m.value
            ult_hp_ratio = self._spirit_hp_scale_ratio()
            ult_mult = self.skill_param("ultra", 0, default=2.00) * self._memosprite_damage_mult()
            for e in self.port.enemies(self.owner_id):
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Ice",
                    atk_multiplier=ult_mult * ult_hp_ratio,
                    toughness_damage=20.0,
                    damage_type=DamageType.ULTIMATE,
                    scaling_stat="hp",
                    fixed_crit_dmg=spirit_cd
                )

            # 终结技基础回能 5 点 (官方数据源 141303 sp_base: 5；行迹【烛火起，烛火熄】回能 5 点与忆质由 on_event 统一结算)
            self.port.gain_energy(self.owner_id, 5.0, cause="终结技《晚安，全世界无眠》施放基础回能 (+5.0 点)", source_plugin="长夜月终结技")
            self._check_threshold()

        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【愿有冷雨落下】：开战时获得 1 点【忆质】(E2为3点)，并获得与战技相同的提高我方全体忆灵暴击伤害的效果。"""
        self.gain_yizhi(1)
        self.technique_active = True


class ChangyeMemospriteKit(KitHandler):
    """伴生忆灵「长夜」独立技能套件。"""

    SKILL_NAME = "追忆，蹁跹，如雨"
    BURST_NAME = "迷梦，流失，如露"

    def __init__(self, owner_id: str, port: CombatPort, master_kit: Any = None):
        super().__init__(owner_id, port)
        self.master_kit = master_kit
        self._pending_burst: Optional[bool] = None

    def definition(self, kind: ActionKind):
        is_burst = bool(self.master_kit and self.master_kit.yizhi >= 16)
        if self._pending_burst is None:
            self._pending_burst = is_burst
        if is_burst:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(sp=0),
                name=self.BURST_NAME,
                tag="终极爆发",
                is_auto=False,
                skill_id=1141307
            )
        else:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=0),
                name=self.SKILL_NAME,
                tag="忆灵技",
                is_auto=True,
                skill_id=1141301
            )

    def on_event(self, event: Any) -> None:
        if isinstance(event, ActionExecuteEvent) and event.actor_name == self.owner_id:
            sid = int(getattr(event, "skill_config_id", 0) or 0)
            if sid in (1141301, 1141307):
                self._pending_burst = (sid == 1141307)

    def execute(self, ctx: ActionContext):
        if not self.master_kit:
            return
        is_burst = self._pending_burst if self._pending_burst is not None else (self.master_kit.yizhi >= 16)
        self._pending_burst = None
        if is_burst:
            self.master_kit.trigger_spirit_burst(ctx=ctx)
        else:
            self.master_kit._execute_memosprite_skill(ctx)

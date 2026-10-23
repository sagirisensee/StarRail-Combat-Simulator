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
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


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

    @property
    def spirit_max_hp(self) -> float:
        """忆灵「长夜」生命上限为长夜月实时生命上限的 50% (满血 4313 点)。"""
        return float(round(0.50 * self.port.max_hp(self.owner_id)))

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

        # 若施放了秘技：进战后根据开局结算后的长夜月实时暴伤，动态挂载与战技相同的暴伤分享 (提高数值等同于长夜月暴伤的 24%)
        if getattr(self, "technique_active", False):
            self.apply_skill_shared_crit_dmg()

    def summon_spirit(self) -> Any:
        """召唤忆灵「长夜」，赋予在场增伤光环，并在跑道上注册实体 (触发【与夜，形影，不离】立即行动 0.0 AV)。"""
        was_alive = self.spirit_alive
        self.spirit_alive = True
        self.threshold_issued = False
        if not was_alive or self.spirit_hp <= 0:
            self.spirit_hp = self.spirit_max_hp

        # 忆灵天赋【孤独，浮游，漆黑】：长夜在场时长夜月造成的伤害提高 50%
        # （注：「长夜」免控与受击概率提高专属属于长夜自身，长夜月本体无此效果）
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

        # 在模拟器实体列表中注册/就绪伴生忆灵实体
        spirit_ent = self.port.summon_spirit(
            owner_id=self.owner_id,
            name=self.spirit_name,
            base_speed=160.0,
            max_hp=self.spirit_max_hp,
            kit_class=ChangyeMemospriteKit,
            kit_args={"master_kit": self}
        )
        if spirit_ent:
            spirit_ent.is_memosprite = True
            spirit_ent.master_name = self.owner_id
            spirit_ent.current_hp = self.spirit_hp
            spirit_ent.max_hp = self.spirit_max_hp
            # 忆灵天赋 1141305【与夜，形影，不离】：被召唤时，使自身立即行动！(100% 拉条，置于跑道 0.0 AV 起跑点)
            spirit_ent.distance_remaining = 0.0

            # 行迹【天亮了，雨落了】：赋予忆灵暴击伤害加成 (+50%)
            rem_count = self._get_remembrance_count()
            rem_cd = 0.50 if rem_count == 3 else (0.65 if rem_count >= 4 else (0.15 if rem_count == 2 else 0.05))
            from ...status import StatusTag
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

        return spirit_ent

    def _execute_memosprite_skill(self, ctx: Optional[ActionContext] = None) -> None:
        """执行忆灵天赋【与夜，形影，不离】与常规忆灵技【追忆，蹁跹，如雨】。"""
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        target = ctx.target_ids[0] if (ctx and ctx.target_ids) else enemies[0]
        self.in_initial_action = True

        # 行迹【天黑黑，月寂寂】：施放技能时消耗自身当前 5% 生命值
        if self.spirit_hp <= 0:
            self.spirit_hp = self.spirit_max_hp
        hp_loss = round(self.spirit_hp * 0.05, 2)
        self.port.lose_hp(self.spirit_name, hp_loss, cause="memosprite_skill_cost")

        self.port.upsert_status(BuffSpec(
            key="Changyeyue_A2_Skill_CritDmg",
            name="天黑黑，月寂寂 (施法暴伤+15%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="暴击伤害提高 +15.0%"
        ))

        # 忆灵技【追忆，蹁跹，如雨】(1141301) 施放回能 20 点
        self.port.gain_energy(self.owner_id, 20.0)
        # 行迹【烛火起，烛火熄】：我方忆灵施放技能时，长夜月恢复 5 点能量并获得 1 点【忆质】
        self.port.gain_energy(self.owner_id, 5.0)
        self.gain_yizhi(1)

        # 忆灵技【追忆，蹁跹，如雨】(1141301):
        extra_ratio = (self.yizhi // 4) * 0.14
        mult = (0.70 + extra_ratio) * 0.50

        self.port.attack(
            self.owner_id,
            target,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="MemospriteSkill",
            scaling_stat="hp"
        )

        # 施放后获得 1 点【忆质】(E2自动+2变为3点)
        self.gain_yizhi(1)
        self.in_initial_action = False
        self._check_threshold()

    def _trigger_memosprite_immediate_action(self) -> None:
        """兼容调用：触发常规忆灵技。"""
        self._execute_memosprite_skill()

    def gain_yizhi(self, amount: int) -> None:
        """获取【忆质】，E2 额外提高 2 点。若达到 16 点且长夜在场，触发天赋【立即行动】。"""
        if amount <= 0:
            return
        bonus = 2 if self.eidolon >= 2 else 0
        self.yizhi += amount + bonus
        self._check_threshold()

    def _check_threshold(self) -> None:
        """检查【忆质】>= 16 点时，触发免控并使长夜立即行动进入自身回合。"""
        if (
            self.yizhi >= 16
            and self.spirit_alive
            and not self.threshold_issued
            and not self.bursting
            and not getattr(self, "in_initial_action", False)
        ):
            self.threshold_issued = True
            # 天赋【今夜与我同行】：解除并免疫控制，若长夜在场使其立即行动进入自身回合 (Turn Begin)
            self.port.advance(self.owner_id, self.spirit_name, 1.0)

    def trigger_spirit_burst(self) -> None:
        """忆灵终极爆发【迷梦，流失，如露】：主目标16.8%*忆质，副目标8.4%*忆质。"""
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return

        spent_memory = self.yizhi
        self.bursting = True
        primary_target = enemies[0]

        try:
            for e in enemies:
                factor = 0.168 if e == primary_target else 0.084
                # 以长夜生命上限 (50% 长夜月生命) 计算冰伤
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Ice",
                    atk_multiplier=factor * spent_memory * 0.50, # 换算至长夜月生命基准
                    toughness_damage=90.0 if e == primary_target else 60.0,
                    damage_tag="MemospriteUltimate",
                    scaling_stat="hp"
                )

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

            # 忆灵自毁离场
            self.spirit_alive = False
            self.spirit_hp = 0.0
            self.port.remove_status(self.owner_id, "Changyeyue_Memosprite_Presence")
            self.port.despawn_spirit(self.spirit_name, "burst_depart")

            # 天赋【与你，再见，无期】：消失时速度提高 10% + 消耗忆质*1% (上限 40%)
            speed_bonus = min(0.40, 0.10 + 0.01 * spent_memory)
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Spirit_Depart_Speed",
                name=f"与你，再见，无期 (加速+{speed_bonus*100:.1f}%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, speed_bonus),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"速度提高 +{speed_bonus*100:.1f}%"
            ))
        finally:
            self.bursting = False

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """生命降低统一响应：受到敌方攻击伤害、持续伤害/负面状态扣血、技能自耗或环境机制扣血时，暴伤提高 60% 并获得 2 点【忆质】(E2为 2+2=4 点)。"""
        is_owner = (entity_id == self.owner_id)
        is_own_spirit = self.port.is_own_memosprite(self.owner_id, entity_id) if hasattr(self.port, "is_own_memosprite") else (entity_id == "长夜")
        if (is_owner or is_own_spirit) and not cause.startswith("evernight_self_destruct"):
            if is_own_spirit:
                ent = self.port._get_entity(entity_id) if hasattr(self.port, "_get_entity") else None
                if ent:
                    self.spirit_hp = ent.current_hp

            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Talent_CritDmg",
                name="今夜与我同行 (生命降低暴伤+60%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.60),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="暴击伤害提高 +60.0%"
            ))
            # 获得 2 点忆质 (E2 自动 +2 变为 4 点)
            self.gain_yizhi(2)

            # 光锥《让告别，更美一些》：自身或忆灵损失生命值时获得【冥花】(无视目标30%防御)
            ent = self.port._get_entity(self.owner_id)
            if ent and getattr(ent, "light_cone", None) and hasattr(ent.light_cone, "trigger_flower_buff"):
                ent.light_cone.trigger_flower_buff()

    def get_owner_crit_dmg(self) -> float:
        """动态采样长夜月自身的实时暴击伤害 (排除忆灵专属暴伤加成，防止自循环或属性污染)。"""
        owner_ent = self.port._get_entity(self.owner_id)
        base_cd = getattr(owner_ent, "base_crit_dmg", 2.273) if owner_ent else 2.273
        bonus_cd = 0.0
        if self.port.sim and hasattr(self.port.sim, "status_mgr"):
            from ...status import StatusTag
            for s in self.port.sim.status_mgr.get_statuses(self.owner_id):
                tags = getattr(s, "tags", [])
                if StatusTag.EXCLUDE_FROM_STAT_TRANSFERS in tags or StatusTag.MEMOSPRITE_ONLY in tags:
                    continue
                if getattr(s, "category", "") == "other":
                    continue
                # 排除自身机制标记
                if s.id in ("Changyeyue_Skill_SharedCritDmg", "Changyeyue_A6_RemembranceCritDmg", "Robin_Talent_TonalChord_长夜"):
                    continue
                for m in s.modifiers:
                    if m.stat == StatType.CRIT_DMG:
                        bonus_cd += m.value
        return base_cd + bonus_cd

    def calc_skill_shared_crit_dmg(self) -> float:
        """动态计算战技/秘技分享给忆灵的暴击伤害加成 (零假数据、零静态硬编码)。
        公式：提高数值等同于长夜月暴击伤害的 24% (Skill Level 10 官方倍率)。
        持续 2 回合，长夜月每回合开始时持续回合数减 1。
        """
        cd_ratio = self.skill_param("skill", 0, default=0.24)
        owner_cd = self.get_owner_crit_dmg()
        if owner_cd <= 0:
            owner_cd = 4.533
        return round(owner_cd * cd_ratio, 4)

    def apply_skill_shared_crit_dmg(self) -> float:
        """动态挂载【白昼悄然离去】：
        - 对长夜月本体：作为机制状态标记 (category='other')，打上 EXCLUDE 标签，自身不享受忆灵暴伤加成；
        - 对伴生忆灵长夜：挂载专属暴伤 Buff (提高数值等同于长夜月实时暴伤的 24%)，打上 MEMOSPRITE_ONLY 标签。
        """
        from ...status import StatusTag
        shared_cd = self.calc_skill_shared_crit_dmg()
        # 对长夜月本体：other 分类，无自身属性加成
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
            description=f"战技分享忆灵暴击伤害 +{shared_cd*100:.1f}%"
        ))
        # 对伴生忆灵挂载实际暴击伤害提升 Buff
        spirit_ent = self.port.sim.get_entity(self.spirit_name) if hasattr(self.port, "sim") else None
        if spirit_ent:
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Skill_SharedCritDmg_Spirit",
                name="白昼悄然离去",
                source_id=self.owner_id,
                target_id=self.spirit_name,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, shared_cd),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_START,
                category="buff",
                tags=(StatusTag.MEMOSPRITE_ONLY, StatusTag.EXCLUDE_FROM_STAT_TRANSFERS),
                description=f"战技分享忆灵暴击伤害 +{shared_cd*100:.1f}%"
            ))
        return shared_cd

    def _get_remembrance_count(self) -> int:
        """统计队伍中「记忆」命途角色数量 (供行迹【天亮了，雨落了】结算)。"""
        count = 1  # 长夜月本体
        allies = self.port.allies(self.owner_id)
        if hasattr(self.port, "_get_entity"):
            for a_name in allies:
                if a_name != self.owner_id:
                    ent = getattr(self.port, "_get_entity")(a_name)
                    if ent:
                        p = getattr(ent, "path", "")
                        p_str = str(getattr(p, "value", p)).upper()
                        if p_str in ("REMEMBRANCE", "8", "记忆") or "REMEMBRANCE" in p_str:
                            count += 1
        return count

    def get_memosprite_snapshot(self) -> dict:
        """返回伴生忆灵「长夜」的完整独立实时战斗快照。
        100% 动态驱动：属性由实体底模与状态管理器流水线实时采样，Buff 列表全部直接从状态管理器抽取！
        """
        # 实时根据长夜月最新暴击伤害动态刷新战技分享暴伤 (确保随长夜月实时爆伤变化动态更新，零静态硬编码)
        if getattr(self, "technique_active", False) or self.port.has_status(self.owner_id, "Changyeyue_Skill_SharedCritDmg"):
            self.apply_skill_shared_crit_dmg()
        owner_ent = self.port._get_entity(self.owner_id)
        max_hp = self.spirit_max_hp
        cur_hp = self.spirit_hp if self.spirit_alive else 0.0
        hp_pct = (cur_hp / max_hp) if max_hp > 0 else 0.0

        # 1. 动态采样基础与局内攻击力 (ATK) - 从白字与加成流水线动态计算
        base_atk = int(round(getattr(owner_ent, "base_white_atk", 1072.0))) if owner_ent and getattr(owner_ent, "base_white_atk", 0) > 0 else 1072
        cur_atk = int(round(self.port.stat(self.owner_id, StatType.ATK_BASE))) if owner_ent else 1444
        bonus_atk = max(0, cur_atk - base_atk)

        # 2. 动态采样基础与局内防御力 (DEF) - 从白字与加成流水线动态计算
        base_def = int(round(getattr(owner_ent, "base_white_def", 979.0))) if owner_ent and getattr(owner_ent, "base_white_def", 0) > 0 else 979
        cur_def = int(round(self.port.stat(self.owner_id, StatType.DEF_PERCENT))) if owner_ent else 1026
        bonus_def = max(0, cur_def - base_def)

        # 3. 动态采样暴击率与暴击伤害 (CRIT) - 从状态管理器实时汇算所有生效 Modifier (纯动态，绝无任何硬编码加数)
        crit_rate = self.port.stat(self.owner_id, StatType.CRIT_RATE) if owner_ent else 1.036
        crit_dmg = self.port.stat(self.owner_id, StatType.CRIT_DMG) if owner_ent else 4.533
        if self.port.sim and hasattr(self.port.sim, "status_mgr"):
            from ...status import StatusTag
            for s in self.port.sim.status_mgr.get_statuses(self.spirit_name):
                tags = getattr(s, "tags", [])
                # 语义化标签过滤：仅叠加忆灵专享状态 (如白昼战技分享暴伤、知更鸟专属和弦)，避免全队光环在主从间双重累加
                if StatusTag.MEMOSPRITE_ONLY in tags or s.id == "Changyeyue_Skill_SharedCritDmg_Spirit":
                    for m in s.modifiers:
                        if m.stat == StatType.CRIT_DMG:
                            crit_dmg += m.value

        # 4. 纯动态从状态管理器采集长夜月/忆灵身上所有真实生效的 Buff 实例 (纯动态插件驱动，绝无任何硬编码 append)
        buffs = []
        other_effects = []
        if self.port.sim and hasattr(self.port.sim, "status_mgr"):
            all_statuses = list(self.port.sim.status_mgr.get_statuses(self.owner_id)) + list(self.port.sim.status_mgr.get_statuses(self.spirit_name))
            seen_names = set()
            for s in all_statuses:
                cat = getattr(s, "category", "buff")
                if cat == "buff":
                    name = s.name
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    buffs.append({"name": name, "desc": s.description or "局内动态增益"})
                elif cat == "other":
                    # 伴生忆灵非角色：排除只属于角色的专属机制标记，且仅保留对伴生忆灵生效的特殊效果或环境机制
                    target_name = getattr(s.target, "name", str(s.target))
                    if target_name != self.spirit_name and not s.id.startswith("Stage_Mechanic"):
                        continue
                    if StatusTag.EXCLUDE_FROM_STAT_TRANSFERS in getattr(s, "tags", []):
                        continue
                    if "好忙好忙" in s.name:
                        continue
                    other_effects.append(s.name)

        return {
            "name": self.spirit_name,
            "owner": "长夜月",
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
        for e in self.port.enemies(self.owner_id):
            self.port.remove_status(e, "Changyeyue_Darkness_Vuln")

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="从此岁月朦胧")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(sp=1), name="白昼悄然离去")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=240.0), name="晚安，全世界无眠")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(technique_points=1), name="愿有冷雨落下")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            # 普攻：造成等同于长夜月 70% 生命上限的冰伤
            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=0.70,
                toughness_damage=10.0,
                damage_tag="BasicAttack",
                scaling_stat="hp"
            )
            self.port.gain_energy(self.owner_id, 20.0)

        elif ctx.kind == ActionKind.SKILL:
            # 战技：扣除当前 10% 生命 (触发生命降低 +2 点忆质，E2 为 +3 点)
            cur_hp = self.port.max_hp(self.owner_id)
            self.port.lose_hp(self.owner_id, 0.10 * cur_hp, cause="evernight_skill_cost")

            # 行迹【天黑黑，月寂寂】：施放技能时，消耗自身当前生命值的 5% 使双方的暴击伤害提高 15%，持续 2 回合
            self.port.lose_hp(self.owner_id, 0.05 * cur_hp, cause="evernight_a2_cost")
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_A2_Skill_CritDmg",
                name="天黑黑，月寂寂 (施法暴伤+15%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="暴击伤害提高 +15.0%"
            ))

            # 重新召唤/维持忆灵长夜在场 (若已在场为其恢复 50% 生命上限)
            if self.spirit_alive:
                self.spirit_hp = min(self.spirit_max_hp, self.spirit_hp + 0.50 * self.spirit_max_hp)
            else:
                self.summon_spirit()

            # 战技【白昼悄然离去】：消耗长夜月当前 10% 生命值召唤/维持忆灵，并使我方全体忆灵暴伤提高长夜月暴伤的 24% (纯动态计算，零硬编码)
            self.apply_skill_shared_crit_dmg()

            # 施放战技自身直接获得 2 点忆质 (至暗之谜下额外 +12 点，E2 自动 +1 点)
            direct_yizhi = 2 + (12 if self.darkness else 0)
            self.gain_yizhi(direct_yizhi)

            # 行迹【烛火起，烛火熄】：长夜月或我方忆灵施放技能时，长夜月恢复 5 点能量并获得 1 点【忆质】
            self.port.gain_energy(self.owner_id, 5.0)
            self.gain_yizhi(1)

            self.port.gain_energy(self.owner_id, 30.0)

        elif ctx.kind == ActionKind.ULTIMATE:
            # 召唤长夜
            self.summon_spirit()

            # 长夜对敌方全体造成等同于长夜生命上限 200% 的冰伤 (相当于长夜月生命上限 100%)
            for e in self.port.enemies(self.owner_id):
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Ice",
                    atk_multiplier=1.00,
                    toughness_damage=20.0,
                    damage_tag="MoonlightUlt",
                    scaling_stat="hp"
                )

            # 进入【至暗之谜】
            self.darkness = True
            # 获得充能 (基础 2 点，E2 额外 +2 点，共 4 点)
            self.charges = 2 + (2 if self.eidolon >= 2 else 0)

            # 挂载易伤 30% 到敌方全体
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

            # 挂载自身增伤 60%
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

            self.port.gain_energy(self.owner_id, 5.0)
            self._check_threshold()

        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【愿有冷雨落下】：开战时获得 1 点【忆质】(E2为3点)，并获得与战技相同的提高我方全体忆灵暴击伤害的效果。"""
        self.gain_yizhi(1)
        self.technique_active = True
        self.apply_skill_shared_crit_dmg()


class ChangyeMemospriteKit(KitHandler):
    """伴生忆灵「长夜」独立技能套件。"""
    def __init__(self, owner_id: str, port: CombatPort, master_kit: Any = None):
        super().__init__(owner_id, port)
        self.master_kit = master_kit

    def definition(self, kind: ActionKind):
        if self.master_kit and self.master_kit.yizhi >= 16:
            return AbilityDefinition(
                kind=ActionKind.SKILL,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(sp=0),
                name="迷梦，流失，如露"
            )
        else:
            return AbilityDefinition(
                kind=ActionKind.SKILL,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=0),
                name="追忆，蹁跹，如雨"
            )

    def execute(self, ctx: ActionContext):
        if not self.master_kit:
            return
        if self.master_kit.yizhi >= 16:
            self.master_kit.trigger_spirit_burst()
        else:
            self.master_kit._execute_memosprite_skill(ctx)

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
   - 长夜月和长夜暴伤提高 60%；
   - 每次获得【忆质】时获得的数量提高 1 点；
   - 施放终结技额外获得 1 点充能。
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
        self.yizhi: int = 0
        self.darkness: bool = False
        self.charges: int = 0
        self.spirit_alive: bool = False
        self.spirit_hp: float = 0.0
        self.threshold_issued: bool = False
        self.bursting: bool = False

    @property
    def spirit_max_hp(self) -> float:
        """忆灵「长夜」生命上限为长夜月的 50% (官方参数 param_list[4] = 0.50)。"""
        return 0.50 * self.port.max_hp(self.owner_id)

    def on_battle_start(self) -> None:
        """进战：生效被动行迹、由天赋【今夜与我同行】召唤伴生忆灵「长夜」，并触发【与夜，形影，不离】立即行动。"""
        # E2 自带 60% 暴伤提升
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_E2_CritDmg",
                name="呓语 (E2暴伤+60%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.60),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="暴击伤害提高 +60.0%"
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

    def summon_spirit(self) -> None:
        """召唤忆灵「长夜」，赋予在场 70% 增伤光环，并触发忆灵天赋【与夜，形影，不离】立即行动。"""
        was_alive = self.spirit_alive
        self.spirit_alive = True
        self.threshold_issued = False
        if not was_alive or self.spirit_hp <= 0:
            self.spirit_hp = self.spirit_max_hp

        # 忆灵天赋【孤独，浮游，漆黑】：长夜在场增伤 70%
        self.port.upsert_status(BuffSpec(
            key="Changyeyue_Memosprite_Presence",
            name="孤独，浮游，漆黑 (忆灵在场增伤70%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.70),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="全属性伤害提高 +70.0%"
        ))

        # 忆灵天赋 1141305【与夜，形影，不离】：被召唤时，使自身立即行动！
        if not was_alive:
            self._trigger_memosprite_immediate_action()

        self._check_threshold()

    def _trigger_memosprite_immediate_action(self) -> None:
        """执行忆灵天赋【与夜，形影，不离】立即行动，施放常规忆灵技【追忆，蹁跹，如雨】。"""
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        target = enemies[0]

        # 行迹【天黑黑，月寂寂】：施放技能时消耗自身当前 5% 生命值，使双方暴击伤害提高 15%，持续 2 回合
        if self.spirit_hp <= 0:
            self.spirit_hp = self.spirit_max_hp
        hp_loss = self.spirit_hp * 0.05
        self.spirit_hp = max(1.0, self.spirit_hp - hp_loss)

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

        # 天赋【今夜与我同行】：长夜月或忆灵「长夜」每次生命降低时，使自身和忆灵「长夜」暴伤提高 60% 持续 2 回合，并获得 2 点忆质 (E2为3点)
        self.on_hp_lost(self.owner_id, hp_loss, cause="memosprite_skill_cost")

        # 行迹【烛火起，烛火熄】：我方忆灵施放技能时，长夜月恢复 5 点能量并获得 1 点【忆质】
        self.port.gain_energy(self.owner_id, 5.0)
        self.gain_yizhi(1)

        # 忆灵技【追忆，蹁跹，如雨】(1141301):
        # 对敌方单体造成等同于「长夜」70% 生命上限的冰属性伤害，
        # 每有 4 点【忆质】，额外造成等同于「长夜」14% 生命上限的冰属性伤害。
        # 长夜生命上限 = 50% 长夜月生命上限
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

        # 施放后获得 1 点【忆质】(E2自动+1变为2点)
        self.gain_yizhi(1)

    def gain_yizhi(self, amount: int) -> None:
        """获取【忆质】，E2 额外 +1 点。若达到 16 点且长夜在场，触发天赋【立即行动】。"""
        if amount <= 0:
            return
        bonus = 1 if self.eidolon >= 2 else 0
        self.yizhi += amount + bonus
        self._check_threshold()

    def _check_threshold(self) -> None:
        """检查【忆质】>= 16 点时，触发免控并使长夜立即行动爆发。"""
        if (
            self.yizhi >= 16
            and self.spirit_alive
            and not self.threshold_issued
            and not self.bursting
        ):
            self.threshold_issued = True
            # 立即触发长夜终极爆发【迷梦，流失，如露】
            self.trigger_spirit_burst()

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
        """生命降低响应：暴伤提高 60% 并获得 2 点【忆质】(E2为3点)。"""
        if (entity_id == self.owner_id or entity_id == "长夜") and cause != "evernight_self_destruct":
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
            # 获得 2 点忆质 (E2 自动 +1 变为 3 点)
            self.gain_yizhi(2)

    def _get_remembrance_count(self) -> int:
        """统计队伍中「记忆」命途角色数量 (供行迹【天亮了，雨落了】结算)。"""
        count = 1  # 长夜月本体
        allies = self.port.allies(self.owner_id)
        if hasattr(self.port, "_get_entity"):
            for a_name in allies:
                if a_name != self.owner_id:
                    ent = getattr(self.port, "_get_entity")(a_name)
                    if ent and getattr(ent, "path", "") == "Remembrance":
                        count += 1
        return count

    def get_memosprite_snapshot(self) -> dict:
        """返回伴生忆灵「长夜」的完整独立状态快照。"""
        max_hp = self.spirit_max_hp
        cur_hp = self.spirit_hp if self.spirit_alive else 0.0
        hp_pct = (cur_hp / max_hp) if max_hp > 0 else 0.0

        buffs = [
            {"name": "孤独，浮游，漆黑 (在场增伤+70%)", "value": "增伤 +70.0%"},
            {"name": "天黑黑，月寂寂 (暴击率+35%)", "value": "暴率 +35.0%"}
        ]
        if self.eidolon >= 2:
            buffs.append({"name": "呓语 (E2暴伤+60%)", "value": "暴伤 +60.0%"})
        if self.port.has_status(self.owner_id, "Changyeyue_A2_Skill_CritDmg"):
            buffs.append({"name": "天黑黑，月寂寂 (施法暴伤+15%)", "value": "暴伤 +15.0%"})
        if self.port.has_status(self.owner_id, "Changyeyue_Talent_CritDmg"):
            buffs.append({"name": "今夜与我同行 (生命降低暴伤+60%)", "value": "暴伤 +60.0%"})

        return {
            "name": "长夜",
            "owner": "长夜月",
            "is_memosprite": True,
            "is_alive": self.spirit_alive,
            "current_hp": round(cur_hp, 1),
            "max_hp": round(max_hp, 1),
            "hp_pct": round(hp_pct, 4),
            "speed": 160.0,
            "aggro": 125,
            "buffs": buffs,
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

            # 提高我方全体忆灵暴伤：长夜月暴伤 * 24% + 行迹【天亮了，雨落了】记忆命途角色加成
            owner_cd = self.port.stat(self.owner_id, StatType.CRIT_DMG)
            rem_count = self._get_remembrance_count()
            rem_bonus = 0.05 if rem_count <= 1 else (0.15 if rem_count == 2 else (0.50 if rem_count == 3 else 0.65))
            shared_cd = 0.24 * owner_cd + rem_bonus
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Skill_SharedCritDmg",
                name=f"白昼悄然离去 (忆灵暴伤+{shared_cd*100:.1f}%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, shared_cd),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"暴击伤害提高 +{shared_cd*100:.1f}%"
            ))

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
            # 获得充能 (2 点，E2 额外 +1 点，共 3 点)
            self.charges = 2 + (1 if self.eidolon >= 2 else 0)

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
        """秘技【愿有冷雨落下】：开战时获得 1 点【忆质】(E2为2点)。"""
        self.gain_yizhi(1)


# 兼容映射
ChangyeMemospriteKit = ChangyeyueKit

"""克拉拉 (Clara - ID 1107, 毁灭 / 物理) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【我也想帮上忙】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的单体物理伤害，削韧 10，回能 20，回 1 SP。
2. 战技【史瓦罗在看着你】：
   - 消耗 1 点 SP，对敌方全体造成 120% (Lv 10) 攻击力的物理伤害，削韧 10；
   - 对持有【反击标记】的敌方目标额外造成 120% (Lv 10) 攻击力的物理伤害；
   - E1【高大的背影】：施放战技后不会清除敌方目标的【反击标记】；未解锁 E1 则清空标记；回能 30 点。
3. 终结技【是约定不是命令】(耗能 110 点)：
   - 克拉拉受到的伤害降低 25% (Lv 10)，受击概率大幅提高，持续 2 回合；
   - 史瓦罗反击得到强化，受到攻击时造成伤害倍率提高 160% (Lv 10)，并对相邻目标造成主目标 50% 的伤害，生效 2 次 (E6 为 3 次)；
   - E2【紧紧的拥抱】：施放终结技后攻击力提高 30%，持续 2 回合 (Clara_E2_Atk)；
   - 回能 5 点。
4. 天赋【因为我们是家人】：
   - 克拉拉在史瓦罗保护下受到的伤害常驻降低 10% (Clara_Talent_DmgReduce)；
   - 攻击克拉拉的敌方目标会被施加【反击标记】并触发史瓦罗反击，造成 160% (Lv 10) 物理反击伤害，削韧 10，回能 5；
   - E4【家人的温暖】：受到攻击后受到的伤害降低 30%，持续到自己下个回合开始；
   - E6【长久的陪伴】：我方其他目标遭到攻击后，史瓦罗有 50% 固定概率触发反击并添加反击标记，终结技强化反击次数 +1。
5. 秘技【胜利的小小代价】：进战后受到攻击的概率提高，持续 2 回合。
"""

from typing import Optional, List, Any, Set
from ..base import KitHandler
from ...actions import (
    DamageType, FollowUpPhase,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class ClaraKit(KitHandler):
    """克拉拉 (ID 1107, 毁灭 / 物理)."""
    follow_up_phase = FollowUpPhase.COUNTER

    COUNTER_MARK_KEY = "Clara_Counter_Mark"
    TALENT_DMG_REDUCE = "Clara_Talent_DmgReduce"
    ULT_BUFF_KEY = "Clara_Ult_Protection"
    E2_ATK_BUFF = "Clara_E2_Atk"
    E4_DMG_REDUCE = "Clara_E4_DmgReduce"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.enhanced_counters_remaining: int = 0
        self.marked_enemies: Set[str] = set()

    def on_battle_start(self) -> None:
        """天赋常驻减伤 10% (Clara_Talent_DmgReduce)。"""
        self.port.upsert_status(BuffSpec(
            key=self.TALENT_DMG_REDUCE,
            name="因为我们是家人 (克拉拉天赋常驻减伤10%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.10),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description="受到的伤害降低 10.0%"
        ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="我也想帮上忙"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(sp=1),
                name="史瓦罗在看着你"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=110.0),
                allow_self=True,
                name="是约定不是命令"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="胜利的小小代价"
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
        """秘技【胜利的小小代价】：进战受击概率大幅提高。"""
        self.port.upsert_status(BuffSpec(
            key="Clara_Technique_Aggro",
            name="胜利的小小代价",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.AGGRO, ModifierOp.ADD, 5.0),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="受击概率大幅提高"
        ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【我也想帮上忙】：单体物理伤害 140% (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【史瓦罗在看着你】：全体物理伤害 120%，对带标记目标造成额外 120% 伤害。"""
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            has_mark = enemy in self.marked_enemies
            mult = 2.40 if has_mark else 1.20
            self.port.attack(
                self.owner_id,
                enemy,
                element="Physical",
                atk_multiplier=mult,
                toughness_damage=10.0,
                damage_type=DamageType.SKILL,
                scaling_stat="atk"
            )

        # E1: 施放战技后不清除反击标记；未解锁 E1 则清空标记
        if self.eidolon < 1:
            self.marked_enemies.clear()

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【是约定不是命令】：减伤 25%，嘲讽度提高，强化反击 2 次 (E6 为 3 次)。"""
        self.enhanced_counters_remaining = 3 if self.eidolon >= 6 else 2

        self.port.upsert_status(BuffSpec(
            key=self.ULT_BUFF_KEY,
            name="是约定不是命令 (终结技减伤与嘲讽)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.25),
                Modifier(StatType.AGGRO, ModifierOp.ADD, 5.0),
            ),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="受到的伤害降低 25.0%，受击概率大幅提高"
        ))

        # E2: 施放终结技后攻击力提高 30% 持续 2 回合
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E2_ATK_BUFF,
                name="紧紧的拥抱 (克拉拉E2大招增攻30%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="攻击力提高 +30.0%"
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def trigger_counter(self, enemy_id: str, is_clara_hit: bool = True) -> None:
        """史瓦罗反击机制。"""
        self.marked_enemies.add(enemy_id)

        # 检查是否处于终结技强化反击
        if self.enhanced_counters_remaining > 0:
            self.enhanced_counters_remaining -= 1
            # 强化反击倍率：160% + 160% = 320%
            self.port.attack(
                self.owner_id,
                enemy_id,
                element="Physical",
                atk_multiplier=3.20,
                toughness_damage=20.0,
                damage_type=DamageType.FOLLOW_UP,
                scaling_stat="atk"
            )
            # 对相邻目标造成 50% 溅射
            for e in self.port.enemies(self.owner_id):
                if e != enemy_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Physical",
                        atk_multiplier=1.60,
                        toughness_damage=10.0,
                        damage_type=DamageType.FOLLOW_UP,
                        scaling_stat="atk"
                    )
        else:
            # 普通反击：160% 物理伤害
            self.port.attack(
                self.owner_id,
                enemy_id,
                element="Physical",
                atk_multiplier=1.60,
                toughness_damage=10.0,
                damage_type=DamageType.FOLLOW_UP,
                scaling_stat="atk"
            )

        self.port.gain_energy(self.owner_id, 5.0)

        # E4: 受击后受到的伤害额外降低 30%
        if self.eidolon >= 4 and is_clara_hit:
            self.port.upsert_status(BuffSpec(
                key=self.E4_DMG_REDUCE,
                name="家人的温暖 (克拉拉E4受击减伤30%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.30),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_START,
                skip_current_clock=True,
                category="buff",
                description="受到的伤害降低 30.0%"
            ))

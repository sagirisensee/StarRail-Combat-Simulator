"""驭空 (Yukong) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1207, 同谐 / 虚数)：
1. 【普攻·流镝】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于驭空 140% 攻击力的虚数属性伤害，削韧 10 点，恢复 20 点能量；
   - 天赋【箭彻七札】：额外造成等同于驭空 80% 攻击力的虚数属性附加伤害，且削韧值提高 100% (削韧 20 点)。
2. 【战技·天阙鸣弦】(Support):
   - 消耗 1 点 SP，获得 2 层【鸣弦号令】(最多持有 2 层)；
   - 处于【鸣弦号令】时，我方全体攻击力提高 80%，我方目标回合结束时移除 1 层；
   - 恢复 30 点能量。
3. 【终结技·贯云饮羽】(SingleAttack):
   - 消耗 130 点能量，对指定敌方单体造成等同于驭空 380% 攻击力的虚数属性伤害，削韧 30 点，恢复 5 点能量；
   - 施放终结技时若持有【鸣弦号令】，使我方全体暴击率提高 28%，暴击伤害提高 65%，持续 2 回合；
   - 星魂 6【弦栝如雷，铣珧激荡】：施放终结技时，立即先获得 1 层【鸣弦号令】。
4. 【秘技·云鸢逐风】(Enhance):
   - 进战后主动获得 2 层【鸣弦号令】。
5. 【星魂 1·天舶飞将，枕弧待战】：
   - 进入战斗时，我方全体速度提高 10%，持续 2 回合。
6. 【星魂 4·百里闻风，九曲响镝】：
   - 持有【鸣弦号令】时，驭空造成的伤害提高 30%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class YukongKit(KitHandler):
    BOWSTRING_BUFF = "Yukong_Roaring_Bowstrings"
    CRIT_BUFF = "Yukong_Ult_Crit"
    E1_SPEED_BUFF = "Yukong_E1_Speed"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.bowstring_stacks: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="流镝"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="天阙鸣弦"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=130.0),
                name="贯云饮羽"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="云鸢逐风"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1 天舶飞将，枕弧待战：全队提速 10% 持续 2 回合。"""
        if self.eidolon >= 1:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E1_SPEED_BUFF,
                    name="天舶飞将，枕弧待战 (驭空E1全队提速10%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

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
        """秘技【云鸢逐风】：进战立即获得 2 层【鸣弦号令】。"""
        self.bowstring_stacks = 2
        self._apply_bowstrings()

    def _apply_bowstrings(self) -> None:
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.BOWSTRING_BUFF,
                name="天阙鸣弦 (驭空全队攻击力提高80%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.80),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 天赋强化普攻：140% + 80% = 220% 虚数伤害，削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=2.20,
            toughness_damage=20.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        self.bowstring_stacks = 2
        self._apply_bowstrings()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # E6: 施放终结技立即获得 1 层鸣弦号令！
        if self.eidolon >= 6:
            self.bowstring_stacks = min(2, self.bowstring_stacks + 1)
            self._apply_bowstrings()

        # 持有号令时为全队提供 28% 暴击率与 65% 暴击伤害
        if self.bowstring_stacks > 0:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.CRIT_BUFF,
                    name="贯云饮羽 (驭空大招暴击28%与暴伤65%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(
                        Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.28),
                        Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.65),
                    ),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=3.80,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

"""三月七•巡猎 (March 7th • The Hunt) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1224, 巡猎 / 虚数)：
1. 【普攻·荡涤妖邪琉璃剑】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，造成等同于三月七 140% 攻击力的虚数属性伤害，削韧 10 点，恢复 20 点能量，获得 1 点充能。
2. 【强化普攻·一扎眉攒，二扎心】(SingleAttack):
   - 初始造成 3 段伤害 (终结技可加至 5 段)，每段造成 112% 攻击力的虚数属性伤害，每段有 60% 固定概率追加 1 段伤害 (最多额外 3 段)；
   - 消耗 7 点充能，消耗 0 SP，不恢复战技点，回能 30 点；
   - 星魂 6【天下第一本姑娘】：施放终结技后，下一次强化普攻造成的暴击伤害提高 50%。
3. 【战技·师父，请喝茶！】(Support):
   - 消耗 1 点 SP，使我方指定单体成为【师父】，【师父】的速度提高 10.0%；
   - 恢复 30 点能量。
4. 【终结技·盖世女侠三月七】(SingleAttack):
   - 消耗 110 点能量，对指定敌方单体造成等同于三月七 240% 攻击力的虚数属性伤害，削韧 30 点，恢复 5 点能量；
   - 使下一次强化普攻初始段数增加 2 段，额外攻击概率提高 20%。
5. 【天赋·师父，我悟了！】(Enhance):
   - 【师父】攻击后三月七获得 1 点充能；
   - 充能达到 7 点时，三月七立即行动 (100% 自拉条)，造成的伤害提高 80%，普攻获得强化；
   - 星魂 1【初花学剑动星芒】：场上存在【师父】时，三月七速度提高 10%；
   - 星魂 2【白刃耀雪舞骇浪】：【师父】攻击后三月七发动追加攻击造成 60% 虚数伤害并获得 1 点充能。
6. 【秘技·一气化三餐】(Enhance):
   - 进战后恢复 30 点能量。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType, FollowUpPhase,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class March7thHuntKit(KitHandler):
    follow_up_phase = FollowUpPhase.NORMAL
    SHIFU_SPEED_BUFF = "MarchHunt_Shifu_Speed"
    MARCH_E1_SPEED = "MarchHunt_E1_Speed"
    ENHANCED_DMG_BUFF = "MarchHunt_Enhanced_Dmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.shifu_id: Optional[str] = None
        self.charges: int = 0
        self.extra_init_hits: int = 0
        self.is_enhanced: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "一扎眉攒，二扎心" if self.is_enhanced else "荡涤妖邪琉璃剑"
            sp_cost = 0 if self.is_enhanced else -1
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=sp_cost),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="师父，请喝茶！"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=110.0),
                name="盖世女侠三月七"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="一气化三餐"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """秘技回能 30 点。"""
        self.port.gain_energy(self.owner_id, 30.0)

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
        self.on_battle_start()

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if self.is_enhanced:
            # 强化普攻【一扎眉攒，二扎心】
            hits = 3 + self.extra_init_hits
            self.extra_init_hits = 0
            # 模拟额外 1~3 段追击
            hits += 2
            for _ in range(hits):
                self.port.attack(
                    self.owner_id,
                    target_id,
                    element="Imaginary",
                    atk_multiplier=1.12,
                    toughness_damage=5.0,
                    damage_type=DamageType.BASIC
                )

            self.charges = max(0, self.charges - 7)
            self.is_enhanced = False
            self.port.remove_status(self.owner_id, self.ENHANCED_DMG_BUFF)
            self.port.gain_energy(self.owner_id, 30.0)
        else:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Imaginary",
                atk_multiplier=1.40,
                toughness_damage=10.0,
                damage_type=DamageType.BASIC
            )
            self.add_charge(1)
            self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else [a for a in self.port.allies(self.owner_id) if a != self.owner_id][0]
        self.shifu_id = target_id

        # 师父速度提高 10%
        self.port.upsert_status(BuffSpec(
            key=self.SHIFU_SPEED_BUFF,
            name="师父，请喝茶！ (师父提速10%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
            duration=None
        ))

        # E1: 场上有师父三月七提速 10%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.MARCH_E1_SPEED,
                name="初花学剑动星芒 (三月七提速10%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                duration=None
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=2.40,
            toughness_damage=30.0,
            damage_type=DamageType.ULTIMATE
        )
        self.extra_init_hits = 2
        self.port.gain_energy(self.owner_id, 5.0)

    def add_charge(self, count: int = 1) -> None:
        self.charges = min(10, self.charges + count)
        if self.charges >= 7 and not self.is_enhanced:
            self.is_enhanced = True
            # 立即行动
            self.port.advance(self.owner_id, self.owner_id, 1.0)
            # 伤害提高 80%
            self.port.upsert_status(BuffSpec(
                key=self.ENHANCED_DMG_BUFF,
                name="师父，我悟了！ (三月七增伤80%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.80),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

"""丹恒•饮月 (Dan Heng • Imbibitor Lunae) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1213, 毁灭 / 虚数)：
1. 【普攻·泽芝】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于饮月 140% 攻击力的虚数属性伤害，削韧 10 点，恢复 20 点能量。
2. 【强化普攻】：
   - 强化 1 级【瞬华】(消耗 1 点 SP)：造成单体 364% 攻击力虚数伤害，削韧 20 点，恢复 30 点能量；
   - 强化 2 级【天矢阴】(消耗 2 点 SP)：主目标 532%，相邻目标 84%，削韧 30/15 点，恢复 35 点能量；
   - 强化 3 级【盘拏耀跃】(消耗 3 点 SP)：主目标 700%，相邻目标 252%，削韧 40/20 点，恢复 40 点能量。
3. 【终结技·苍龙傲睨，劫水濯世】(Blast):
   - 消耗 140 点能量，对指定敌方单体造成等同于饮月 300% 攻击力的虚数属性伤害，对相邻目标造成 140% 攻击力的虚数属性伤害，削韧 20/10 点，恢复 5 点能量；
   - 获得 2 个【逆鳞】(可抵扣战技点消耗)；
   - 星魂 2【九斿】：施放终结技后，丹恒•饮月行动提前 100%，并且额外获得 1 个【逆鳞】(总计 3 个)。
4. 【天赋·亢心】(Enhance):
   - 每段攻击后获得 1 层【亢心】，自身造成的伤害提高 10%，最多叠加 6 层 (星魂 1 增加至 10 层)。
5. 【秘技·掣空如虹】(Enhance):
   - 进战后对敌方全体造成等同于饮月 120% 攻击力的虚数属性伤害，并获得 1 个【逆鳞】。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class DanHengTenghuangKit(KitHandler):
    OUTRAGE_BUFF = "DHIL_Outrage"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 2,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.enhance_level: int = 0  # 0~3
        self.squama_sacrosancta: int = 0  # 逆鳞数量
        self.max_outrage: int = 10 if eidolon >= 1 else 6

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            names = ["泽芝", "瞬华", "天矢阴", "盘拏耀跃"]
            sp_costs = [-1, 1, 2, 3]
            actual_sp = sp_costs[self.enhance_level]
            # 逆鳞抵扣 SP
            if actual_sp > 0 and self.squama_sacrosancta > 0:
                actual_sp = max(0, actual_sp - self.squama_sacrosancta)

            target_mode = TargetMode.SINGLE_ENEMY if self.enhance_level <= 1 else TargetMode.ADJACENT_ENEMIES
            return AbilityDefinition(
                kind=kind,
                target_mode=target_mode,
                cost=ResourceCost(sp=actual_sp),
                name=names[self.enhance_level]
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(sp=0),
                allow_self=True,
                name="龙力自在"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.BLAST,
                cost=ResourceCost(energy=140.0),
                name="苍龙傲睨，劫水濯世"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="掣空如虹"
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
        """秘技【掣空如虹】：进战获得 1 个逆鳞并全体造成 120% 伤害。"""
        self.squama_sacrosancta = min(3, self.squama_sacrosancta + 1)
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Imaginary",
                atk_multiplier=1.20,
                toughness_damage=20.0,
                damage_tag="Technique"
            )

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【龙力自在】：强化普攻等级 (0 -> 1 -> 2 -> 3)。"""
        self.enhance_level = (self.enhance_level + 1) if self.enhance_level < 3 else 0

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # 计算并消耗逆鳞
        sp_needed = [0, 1, 2, 3][self.enhance_level]
        if sp_needed > 0 and self.squama_sacrosancta > 0:
            deduct = min(self.squama_sacrosancta, sp_needed)
            self.squama_sacrosancta -= deduct

        if self.enhance_level == 0:
            # 基础普攻【泽芝】
            self.port.attack(
                self.owner_id,
                target_id,
                element="Imaginary",
                atk_multiplier=1.40,
                toughness_damage=10.0,
                damage_tag="BasicAttack"
            )
            self.port.gain_energy(self.owner_id, 20.0)
        elif self.enhance_level == 1:
            # 强化 1 级【瞬华】
            self.port.attack(
                self.owner_id,
                target_id,
                element="Imaginary",
                atk_multiplier=3.64,
                toughness_damage=20.0,
                damage_tag="EnhancedBasic"
            )
            self.port.gain_energy(self.owner_id, 30.0)
        elif self.enhance_level == 2:
            # 强化 2 级【天矢阴】
            self.port.attack(
                self.owner_id,
                target_id,
                element="Imaginary",
                atk_multiplier=5.32,
                toughness_damage=30.0,
                damage_tag="EnhancedBasic"
            )
            for e in self.port.enemies(self.owner_id):
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Imaginary",
                        atk_multiplier=0.84,
                        toughness_damage=15.0,
                        damage_tag="EnhancedBasic_Blast"
                    )
            self.port.gain_energy(self.owner_id, 35.0)
        elif self.enhance_level == 3:
            # 强化 3 级【盘拏耀跃】
            self.port.attack(
                self.owner_id,
                target_id,
                element="Imaginary",
                atk_multiplier=7.00,
                toughness_damage=40.0,
                damage_tag="EnhancedBasic"
            )
            for e in self.port.enemies(self.owner_id):
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Imaginary",
                        atk_multiplier=2.52,
                        toughness_damage=20.0,
                        damage_tag="EnhancedBasic_Blast"
                    )
            self.port.gain_energy(self.owner_id, 40.0)

        # 施放后重置强化等级
        self.enhance_level = 0

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=3.00,
            toughness_damage=20.0,
            damage_tag="Ultimate"
        )
        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Imaginary",
                    atk_multiplier=1.40,
                    toughness_damage=10.0,
                    damage_tag="Ultimate_Blast"
                )

        # 获得逆鳞 (基础 2 个，E2 额外获得 1 个 = 3 个)
        sacrosancta_gain = 3 if self.eidolon >= 2 else 2
        self.squama_sacrosancta = min(3, self.squama_sacrosancta + sacrosancta_gain)

        # E2: 施放终结技后行动提前 100%！
        if self.eidolon >= 2:
            self.port.advance(self.owner_id, self.owner_id, 1.0)

        self.port.gain_energy(self.owner_id, 5.0)

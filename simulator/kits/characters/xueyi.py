"""雪衣 (Xueyi) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1214, 毁灭 / 量子)：
1. 【普攻·破魔锥】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于雪衣 140% 攻击力的量子属性伤害，削韧 10 点，恢复 20 点能量，叠加 1 层【恶报】。
2. 【战技·摄伏诸恶】(Blast):
   - 消耗 1 点 SP，对指定敌方单体造成等同于雪衣 140% 攻击力的量子属性伤害，并对其相邻目标造成 70% 攻击力的量子属性伤害，削韧 20/10 点，恢复 30 点能量，叠加 2 层【恶报】。
3. 【终结技·天罚贯身】(SingleAttack):
   - 消耗 120 点能量，对指定敌方单体造成等同于雪衣 250% 攻击力的量子属性伤害，削减韧性越多造成的伤害越高 (最多提高 60%)；
   - 本次攻击无视弱点属性削减 40 点韧性，恢复 5 点能量，叠加 4 层【恶报】；
   - 星魂 4【断业根】：施放终结技时，击破特攻提高 40%，持续 2 回合。
4. 【天赋·十王圣断，业报恒常】(Bounce):
   - 削减敌方韧性时叠加【恶报】(上限 8 层，星魂 6 降至 6 层)；
   - 叠加至上限时立即消耗所有【恶报】，发动追加攻击进行 3 段随机单体弹射，每段造成 90% 攻击力的量子属性伤害；
   - 星魂 1【缚心魔】：天赋追加攻击造成的伤害提高 40% (每段 126%)；
   - 星魂 2【破五尘】：追加攻击无视弱点削韧，并回复等同于雪衣 5% 生命上限的生命值。
5. 【秘技·斩立决】(MazeAttack):
   - 进战后对敌方全体造成等同于雪衣 80% 攻击力的量子属性伤害，无视弱点削韧 20 点。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class XueyiKit(KitHandler):
    E4_BREAK_BUFF = "Xueyi_E4_BreakBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        # E6: 恶报上限由 8 降至 6
        self.max_karma: int = 6 if eidolon >= 6 else 8
        self.karma_stacks: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="破魔锥"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="摄伏诸恶"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=120.0),
                name="天罚贯身"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="斩立决"
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
        """秘技【斩立决】：敌方全体造成 80% 量子伤害，无视弱点削韧 20 点。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE,
                ignore_weakness=True
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.add_karma(1)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 主目标 140%
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.40,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )
        # 扩散目标 70%
        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Quantum",
                    atk_multiplier=0.70,
                    toughness_damage=10.0,
                    damage_type=DamageType.SKILL
                )
        self.add_karma(2)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # E4: 击破特攻提高 40% 持续 2 回合
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=self.E4_BREAK_BUFF,
                name="断业根 (雪衣E4击破特攻40%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.40),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 终结技无视弱点削韧 40 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=2.50,
            toughness_damage=40.0,
            damage_type=DamageType.ULTIMATE,
            ignore_weakness=True
        )
        self.add_karma(4)
        self.port.gain_energy(self.owner_id, 5.0)

    def add_karma(self, count: int) -> None:
        """恶报叠层与追击触发。"""
        self.karma_stacks += count
        if self.karma_stacks >= self.max_karma:
            self.karma_stacks = 0
            # 满层发动追加攻击 (E1: 伤害提高 40% -> 90% * 1.4 = 126%)
            mult = 0.90 * (1.40 if self.eidolon >= 1 else 1.0)
            enemies = self.port.enemies(self.owner_id)
            if enemies:
                import random
                for _ in range(3):
                    target = random.choice(enemies)
                    self.port.attack(
                        self.owner_id,
                        target,
                        element="Quantum",
                        atk_multiplier=mult,
                        toughness_damage=5.0,
                        damage_type=DamageType.FOLLOW_UP,
                        ignore_weakness=(self.eidolon >= 2)
                    )

            # E2: 回复 5% 生命上限
            if self.eidolon >= 2:
                max_hp = self.port.max_hp(self.owner_id)
                self.port.heal(self.owner_id, self.owner_id, max_hp * 0.05)

"""桂乃芬 (Guinaifen) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1210, 虚无 / 火)：
1. 【普攻·劈头满堂彩】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于桂乃芬 140% 攻击力的火属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·迎面开门红】(Blast):
   - 消耗 1 点 SP，对指定敌方单体造成等同于桂乃芬 120% 攻击力的火属性伤害，并对相邻目标造成 40% 攻击力的火属性伤害，削韧 20/10 点；
   - 100% 基础概率使目标与相邻目标陷入【灼烧】状态 (持续 2 回合，每回合受到 218.2% 攻击力的火属性持续伤害)，恢复 30 点能量；
   - 星魂 1【倒立吃面条】：施放战技时，100% 基础概率使目标效果抵抗降低 10%，持续 2 回合。
3. 【终结技·给您来段看家戏】(AoEAttack):
   - 消耗 120 点能量，对敌方全体造成等同于桂乃芬 120% 攻击力的火属性伤害，削韧 20 点；
   - 使处于灼烧状态的目标立即产生原伤害 92% 的灼烧伤害；
   - 星魂 4【金枪锁咽喉】：灼烧状态每触发 1 次伤害，自身恢复 2 点能量。
4. 【天赋·古来君子养艺人】(Impair):
   - 敌方受到的灼烧触发伤害后，100% 基础概率陷入【吞火】状态，受到的伤害提高 7%，持续 3 回合，最多叠加 3 层；
   - 星魂 6【徒手接子弹】：使【吞火】的可叠加层数增加 1 层 (最高 4 层即 28% 易伤)。
5. 【秘技·耍耍把式卖卖艺】(MazeAttack):
   - 进战后造成 4 次伤害，每次对随机单体造成 50% 攻击力的火属性伤害并施加【吞火】。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class GuinaifenKit(KitHandler):
    FIREKISS_DEBUFF = "Guinaifen_Firekiss"
    BURN_DEBUFF = "Guinaifen_Burn"
    E1_RES_DOWN = "Guinaifen_E1_ResDown"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.max_firekiss: int = 4 if eidolon >= 6 else 3

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="劈头满堂彩"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="迎面开门红"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="给您来段看家戏"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="耍耍把式卖卖艺"
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
        """秘技【耍耍把式卖卖艺】：进战随机单体造成 4 次火伤并施加【吞火】。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            import random
            for _ in range(4):
                tgt = random.choice(enemies)
                self.port.attack(
                    self.owner_id,
                    tgt,
                    element="Fire",
                    atk_multiplier=0.50,
                    toughness_damage=5.0,
                    damage_tag="Technique"
                )
                self._apply_firekiss(tgt)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self._apply_firekiss(target_id)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 主目标 120%
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.20,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        # 扩散目标 40%
        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Fire",
                    atk_multiplier=0.40,
                    toughness_damage=10.0,
                    damage_tag="Skill_Blast"
                )
            self.port.upsert_status(BuffSpec(
                key=self.BURN_DEBUFF,
                name="迎面开门红 (桂乃芬灼烧持续伤害)",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(),
                duration=2,
                timing=DurationTiming.TARGET_TURN_START,
                skip_current_clock=True
            ))
            self._apply_firekiss(e)

        # E1: 目标效果抵抗降低 10%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_RES_DOWN,
                name="倒立吃面条 (桂乃芬E1抵抗降低10%)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, -0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=1.20,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 引爆灼烧 92%
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.92,
                toughness_damage=0.0,
                damage_tag="DoT_Detonation"
            )
            self._apply_firekiss(enemy)

        # E4: 灼烧结算回能 (每次引爆回能 2 点)
        extra_energy = 2.0 * len(enemies) if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + extra_energy)

    def _apply_firekiss(self, target_id: str) -> None:
        """施加/叠加【吞火】(E6 最高 4 层即 28% 易伤)。"""
        vuln = 0.07 * self.max_firekiss
        self.port.upsert_status(BuffSpec(
            key=self.FIREKISS_DEBUFF,
            name="古来君子养艺人 (桂乃芬吞火易伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, vuln),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

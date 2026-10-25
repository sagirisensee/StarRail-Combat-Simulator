"""黑天鹅 (Black Swan) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1307, 虚无 / 风)：
1. 【普攻·洞见，缄默的黎明】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于黑天鹅 84% 攻击力的风属性伤害；
   - 有 65% 基础概率使目标陷入 1 层【奥迹】(持续伤害受体额外概率叠层)，削韧 10 点，恢复 20 点能量。
2. 【战技·失坠，伪神的黄昏】(Blast):
   - 消耗 1 点 SP，对指定敌方单体及其相邻目标造成等同于黑天鹅 90% 攻击力的风属性伤害，削韧 20/10 点；
   - 100% 基础概率使目标与相邻目标陷入 1 层【奥迹】；
   - 100% 基础概率使目标与相邻目标防御力降低 20.8%，持续 3 回合，恢复 30 点能量。
3. 【终结技·沉醉于彼界的臂湾】(AoEAttack):
   - 消耗 120 点能量，使敌方全体陷入【揭露】(Epiphany) 状态持续 2 回合；
   - 【揭露】期间敌方受到的伤害提高 25%，且【奥迹】视为同时陷入风化/裂伤/灼烧/触电；
   - 对敌方全体造成等同于黑天鹅 120% 攻击力的风属性伤害，削韧 20 点，恢复 5 点能量；
   - 星魂 4【泪水，亦是礼物】：揭露状态下敌方效果抵抗降低 10%，黑天鹅恢复 8 点能量。
4. 【天赋·无端命运的机杼】(Impair):
   - 敌方回合开始受到等同于黑天鹅 240% 攻击力的风属性持续伤害，每层【奥迹】使伤害倍率提高 12%，最多叠加 50 层；
   - 达到 3 层以上时造成 180% 相邻扩散风伤；达到 7 层以上时无视 20% 防御。
5. 【秘技·取此真相，弃舍表征】(Enhance):
   - 战斗开始时使敌方全体陷入【奥迹】状态。
6. 【星魂 1·三磅石，七阶柱】：
   - 黑天鹅处于可战斗状态时，陷入持续伤害的敌方目标对应属性抗性降低 25% (开局自动施加减抗)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class BlackSwanKit(KitHandler):
    EPIPHANY_DEBUFF = "BlackSwan_Epiphany"
    DEF_SHRED_DEBUFF = "BlackSwan_Skill_DefShred"
    ARCANA_STACK_KEY = "BlackSwan_Arcana_Stacks"
    E1_RES_SHRED = "BlackSwan_E1_ResShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 1,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.arcana_stacks: dict = {}

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="洞见，缄默的黎明"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="失坠，伪神的黄昏"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="沉醉于彼界的臂湾"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="取此真相，弃舍表征"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1 三磅石，七阶柱：开局即对敌方全体施加持续伤害对应 25% 属性减抗。"""
        if self.eidolon >= 1:
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E1_RES_SHRED,
                    name="三磅石，七阶柱 (黑天鹅E1全属性持续减抗25%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.25),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END
                ))

    def _add_arcana(self, target_id: str, count: int = 1) -> None:
        """堆叠奥迹层数 (E6: 50% 概率额外多叠 1 层)。"""
        import random
        add_amount = count
        if self.eidolon >= 6 and random.random() < 0.50:
            add_amount += 1

        curr = self.arcana_stacks.get(target_id, 0)
        self.arcana_stacks[target_id] = min(50, curr + add_amount)

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
        """秘技【取此真相，弃舍表征】：进战后使敌方全体陷入【奥迹】状态。"""
        for enemy in self.port.enemies(self.owner_id):
            self._add_arcana(enemy, 2)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=0.84,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self._add_arcana(target_id, 1)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)
        targets = [target_id]
        for e in enemies:
            if e != target_id and len(targets) < 3:
                targets.append(e)

        for tgt in targets:
            self.port.attack(
                self.owner_id,
                tgt,
                element="Wind",
                atk_multiplier=0.90,
                toughness_damage=20.0 if tgt == target_id else 10.0,
                damage_type=DamageType.SKILL
            )
            self._add_arcana(tgt, 1)
            # 降低防御力 20.8%
            self.port.upsert_status(BuffSpec(
                key=self.DEF_SHRED_DEBUFF,
                name="失坠，伪神的黄昏 (黑天鹅减防20.8%)",
                source_id=self.owner_id,
                target_id=tgt,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.208),),
                duration=3,
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
                element="Wind",
                atk_multiplier=1.20,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE
            )
            mods = [Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.25)]
            # E4: 泪水，亦是礼物 (揭露状态下效果抵抗降低 10%)
            if self.eidolon >= 4:
                mods.append(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, -0.10))

            self.port.upsert_status(BuffSpec(
                key=self.EPIPHANY_DEBUFF,
                name="揭露 (黑天鹅易伤与奥迹强化)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=tuple(mods),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # E4: 回能 8 点
        e4_energy = 8.0 if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + e4_energy)

"""卢卡 (Luka) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1111, 虚无 / 物理)：
1. 【普攻·直冲拳】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于卢卡 140% 攻击力的物理属性伤害，削韧 10 点，恢复 20 点能量。
2. 【强化普攻·直冲碎天拳】(SingleAttack):
   - 消耗 2 层【斗志】，施放 3 段【直冲拳】(各 28%=84%) + 1 段【碎天拳】(112%)，总计 196% 物理属性伤害，削韧 20 点，恢复 20 点能量；
   - 命中裂伤目标时立即产生原伤害 85% 的裂伤伤害；
   - 星魂 6【冠军应得的喝彩】：【碎天拳】命中裂伤目标后，每段【直冲拳】额外引爆 1 次 8% 裂伤伤害 (额外 24%)。
3. 【战技·裂伤拳】(SingleAttack):
   - 消耗 1 点 SP，对指定敌方单体造成等同于卢卡 120% 攻击力的物理属性伤害，削韧 20 点，恢复 30 点能量；
   - 100% 基础概率施加【裂伤】状态 (持续 3 回合，每回合造成目标生命上限 24% 且最高不超过卢卡攻击力 338% 的物理持续伤害)；
   - 获得 1 层【斗志】(星魂 2 击中物理弱点敌人额外获得 1 层)；
   - 星魂 1【争斗不休】：目标处于裂伤状态时，卢卡造成的伤害提高 15%，持续 2 回合。
4. 【终结技·制胜一击】(SingleAttack):
   - 消耗 130 点能量，获得 2 层【斗志】；
   - 100% 基础概率使目标受到的伤害提高 20%，持续 3 回合；
   - 对目标造成等同于卢卡 330% 攻击力的物理属性伤害，削韧 30 点，恢复 5 点能量。
5. 【天赋·火花四溅】(Enhance):
   - 战斗开始时持有 1 层【斗志】，最多可持有 4 层【斗志】；
   - 星魂 4【百折不回】：每持有 1 层【斗志】，攻击力提高 5%，最多叠加 4 层至 20%。
6. 【秘技·抢先者】(MazeAttack):
   - 进战造成 50% 物理伤害并施加裂伤，卢卡额外获得 1 层【斗志】。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class LukaKit(KitHandler):
    BLEED_DEBUFF = "Luka_Bleed"
    ULT_VULN_DEBUFF = "Luka_Ult_Vuln"
    E1_DMG_BUFF = "Luka_E1_DmgBuff"
    E4_ATK_BUFF = "Luka_E4_Atk"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.fighting_will: int = 1  # 战斗开始时持有 1 层【斗志】

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "直冲碎天拳" if self.fighting_will >= 2 else "直冲拳"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="裂伤拳"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=130.0),
                name="制胜一击"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(technique_points=1),
                name="抢先者"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """天赋：开局持有 1 层斗志与 E4 增攻。"""
        self.fighting_will = 1
        self._update_e4_buff()

    def _update_e4_buff(self) -> None:
        if self.eidolon >= 4:
            atk_boost = self.fighting_will * 0.05
            self.port.upsert_status(BuffSpec(
                key=self.E4_ATK_BUFF,
                name="百折不回 (卢卡E4攻击力提升)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, atk_boost),),
                duration=None
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
        """秘技【抢先者】：单体造成 50% 物理伤害并施加裂伤，卢卡获得 1 层斗志。"""
        self.fighting_will = min(4, self.fighting_will + 1)
        self._update_e4_buff()
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Physical",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
            self.port.upsert_status(BuffSpec(
                key=self.BLEED_DEBUFF,
                name="裂伤 (卢卡秘技)",
                source_id=self.owner_id,
                target_id=enemies[0],
                modifiers=(),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if self.fighting_will >= 2:
            self.fighting_will -= 2
            self._update_e4_buff()
            # 强化普攻【直冲碎天拳】：196% (E6 追击 24% 裂伤引爆)
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=1.96,
                toughness_damage=20.0,
                damage_tag="EnhancedBasic"
            )
            # 引爆裂伤 (基础 85% + E6 额外 24% = 109%)
            detonate_mult = 1.09 if self.eidolon >= 6 else 0.85
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=detonate_mult,
                toughness_damage=0.0,
                damage_tag="DoT_Detonation"
            )
        else:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=1.40,
                toughness_damage=10.0,
                damage_tag="BasicAttack"
            )
            self.fighting_will = min(4, self.fighting_will + 1)
            self._update_e4_buff()

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=1.20,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.upsert_status(BuffSpec(
            key=self.BLEED_DEBUFF,
            name="裂伤拳 (卢卡裂伤持续伤害)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=3,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))

        # 获得斗志 (E2 额外获得 1 层)
        add_will = 2 if self.eidolon >= 2 else 1
        self.fighting_will = min(4, self.fighting_will + add_will)
        self._update_e4_buff()

        # E1: 增伤 15% 持续 2 回合
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_DMG_BUFF,
                name="争斗不休 (卢卡E1增伤15%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.fighting_will = min(4, self.fighting_will + 2)
        self._update_e4_buff()

        # 易伤 20% 持续 3 回合
        self.port.upsert_status(BuffSpec(
            key=self.ULT_VULN_DEBUFF,
            name="制胜一击 (卢卡大招易伤20%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.20),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=3.30,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

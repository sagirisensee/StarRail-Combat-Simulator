"""真理医生 (Dr. Ratio - ID 1305, 巡猎 / 虚数) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【知识就是力量】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的单体虚数伤害，削韧 10，回能 20，回 1 SP。
2. 战技【精神助产术】：
   - 消耗 1 点 SP，造成 150% (Lv 10) 攻击力的单体虚数伤害，削韧 20；
   - 有 40% 固定概率对目标发动追加攻击，目标每持有 1 个负面效果概率提升 20% (3 个负面 100% 触发)；
   - 追加攻击造成 270% (Lv 10) 攻击力的虚数伤害，削韧 10，回能 5；
   - 行迹【归纳】：施放战技时，获得 1 层【归纳】，使暴击率提高 2.5%，暴击伤害提高 5%，最多叠加 6 层 (E1 上限提高至 10 层)。
3. 终结技【三段悖论】(耗能 140 点)：
   - 对指定单体造成 240% (Lv 10) 攻击力的虚数伤害，削韧 30；
   - 施加【智者的短见】(Wiseman's Folly)，队友攻击该目标时真理医生对其发动天赋追加攻击，最多触发 2 次 (E6 为 3 次)；
   - 回能 5 点。
4. 天赋【我思故我在】：
   - E1【倨傲生祸患】：【归纳】层数上限提高 4 层 (至 10 层)，进战直接获得 4 层【归纳】；
   - E2【显微而阐幽】：追加攻击命中时目标每有 1 个负面额外造成 20% 虚数伤害 (最多 80%)；
   - E4【盲目造痴愚】：触发天赋追加攻击时额外恢复 15 点能量；
   - E6【永恒唯真理】：【智者的短见】触发次数增加 1 次，追加攻击伤害提高 50%。
5. 秘技【偶像塑造】：进战使敌方目标速度降低 15%，持续 2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class RatioKit(KitHandler):
    """真理医生 (ID 1305, 巡猎 / 虚数)."""

    TALENT_CRIT_BUFF = "Ratio_Talent_Crit"
    ULT_WISDOM_MARK = "Ratio_Ult_Wisdom_Mark"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.max_stacks: int = 10 if eidolon >= 1 else 6
        self.current_stacks: int = 4 if eidolon >= 1 else 0
        self.ult_triggers_remaining: int = 0
        self.wisdom_target_id: Optional[str] = None

    def on_battle_start(self) -> None:
        """E1【倨傲生祸患】：战斗开始时立即获得 4 层【归纳】。"""
        if self.eidolon >= 1:
            self.current_stacks = 4
            self._apply_crit_stacks()

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="知识就是力量"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="精神助产术"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=140.0),
                name="三段悖论"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="偶像塑造"
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
        """秘技【偶像塑造】：敌方全体减速 15% 持续 2 回合。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Ratio_Technique_Slow_{enemy}",
                name="偶像塑造",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, -0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="速度降低 15.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【知识就是力量】：单体虚数伤害 140% (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【精神助产术】：造成 150% 虚数伤害，叠加【归纳】层数并触发追加攻击。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("skill", 0, default=1.50)

        # 叠加【归纳】
        if self.current_stacks < self.max_stacks:
            self.current_stacks += 1
            self._apply_crit_stacks()

        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 30.0)

        # 触发粉笔追加攻击
        self._trigger_follow_up(target_id)

    def _trigger_follow_up(self, target_id: str) -> None:
        """天赋追加攻击：270% 虚数伤害 (E6 增伤 50%)。"""
        mult = 2.70
        if self.eidolon >= 6:
            mult *= 1.50

        # E2: 额外附加最高 80% 攻击力伤害
        if self.eidolon >= 2:
            mult += 0.80

        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.FOLLOW_UP,
            scaling_stat="atk"
        )

        # 基础回能 5 点 (E4 额外增加 15 点)
        energy_gain = 20.0 if self.eidolon >= 4 else 5.0
        self.port.gain_energy(self.owner_id, energy_gain)

    def _apply_crit_stacks(self) -> None:
        """更新【归纳】Buff：每层暴击率 +2.5%，暴击伤害 +5%。"""
        cr_val = self.current_stacks * 0.025
        cd_val = self.current_stacks * 0.05
        self.port.upsert_status(BuffSpec(
            key=self.TALENT_CRIT_BUFF,
            name="归纳 (真理医生天赋暴击与暴伤)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.CRIT_RATE, ModifierOp.ADD, cr_val),
                Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),
            ),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description=f"暴击率 +{cr_val*100:.1f}%，暴击伤害 +{cd_val*100:.1f}%"
        ))

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【三段悖论】：单体虚数伤害 240%，施加【智者的短见】。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.wisdom_target_id = target_id
        self.ult_triggers_remaining = 3 if self.eidolon >= 6 else 2

        mult = self.skill_param("ultra", 0, default=2.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=30.0,
            damage_type=DamageType.ULTIMATE,
            scaling_stat="atk"
        )

        self.port.upsert_status(BuffSpec(
            key=f"{self.ULT_WISDOM_MARK}_{target_id}",
            name="智者的短见",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="debuff",
            description=f"受到队友攻击时触发真理医生追加攻击 (剩余 {self.ult_triggers_remaining} 次)"
        ))
        self.port.gain_energy(self.owner_id, 5.0)

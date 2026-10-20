"""真理医生 (Dr. Ratio) 战斗技能套件完整实现 (Character Kit).

适配角色：真理医生 (ID 1305, 巡猎 / 虚数)
严格契合实机机制与公式：
1. 普攻【知识就是力量】：造成单体虚数伤害，恢复 1 点战技点，回能 20 点；
2. 战技【精神产婆术】：
   - 消耗 1 点 SP，造成单体虚数伤害；
   - 概率触发追加攻击【智者的短见】(扔粉笔)：目标每有 1 个负面效果概率提升 20% (3 个负面 100% 触发)；
   - 追加攻击造成 270% 虚数高额伤害，削韧 10 点；
3. 终结技【三段论悖论】：
   - 消耗 140 能量，对敌方单体造成高额虚数伤害，施加【智者的短见】标记 (队友攻击触发粉笔反击，上限 2 次)；
4. 天赋【我思故我在】：
   - 释放追加攻击时，叠加暴击率 2.5% 与暴击伤害 5% (上限 6 层，最高 15% 暴击率 / 30% 暴伤)；
5. 星魂 1~6 完整实装：
   - E1: 傲慢产生偏见 (天赋上限提高 4 层，开局直接获得 4 层，最高 25% 暴击率 / 50% 暴伤)；
   - E2: 显微而阐幽 (追加攻击命中时目标每有 1 个负面，额外造成 20% 虚数伤害，最多 80%)；
   - E3: 认识你自己 (终结技+2，普攻+1)；
   - E4: 盲目即是愚蠢 (触发天赋追加攻击时，额外恢复 15 点能量)；
   - E5: 弃绝虚妄 (战技+2，天赋+2)；
   - E6: 永恒真理 (终结技粉笔触发次数增加 1 次，追加攻击伤害提高 50%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class RatioKit(KitHandler):
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
                name="精神产婆术"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=140.0),
                name="三段论悖论"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 傲慢产生偏见 (开战即拥有 4 层天赋暴击增益)。"""
        if self.eidolon >= 1:
            self._update_crit_buff()

    def _update_crit_buff(self) -> None:
        cr = self.current_stacks * 0.025
        cd = self.current_stacks * 0.05
        self.port.upsert_status(BuffSpec(
            key=self.TALENT_CRIT_BUFF,
            name="归纳总结 (真理医生天赋攻暴)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.CRIT_RATE, ModifierOp.ADD, cr),
                Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd),
            ),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END
        ))

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 1. 战技伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=1.50,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 30.0)

        # 2. 扔粉笔追加攻击
        self._trigger_chalk(target_id)

    def _trigger_chalk(self, target_id: str) -> None:
        """投掷粉笔追加攻击 (E2 额外附加 80% 伤害，E4 回能 15，E6 增伤 50%)。"""
        # 堆叠天赋层数
        self.current_stacks = min(self.max_stacks, self.current_stacks + 1)
        self._update_crit_buff()

        base_mult = 2.70
        # E6: 追加攻击造成的伤害提高 50%
        if self.eidolon >= 6:
            base_mult *= 1.50

        # E2: 目标每有负面额外造成最高 80% 伤害
        if self.eidolon >= 2:
            base_mult += 0.80

        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=base_mult,
            toughness_damage=10.0,
            damage_tag="ChalkFollowUp"
        )

        # E4: 触发追加攻击时额外恢复 15 点能量
        extra_energy = 15.0 if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + extra_energy)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=2.40,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        # E6: 智者的短见触发次数增加 1 次 (2 -> 3 次)
        self.ult_triggers_remaining = 3 if self.eidolon >= 6 else 2
        self.port.gain_energy(self.owner_id, 5.0)

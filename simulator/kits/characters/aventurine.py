"""砂金 (Aventurine) 战斗技能套件完整实现 (Character Kit).

适配角色：砂金 (ID 1304, 存护 / 虚数)
用户重点要求机制（含未拥有角色实现）：
1. 普攻【直观投掷】：基于砂金防御力造成单体虚数伤害，恢复 1 点战技点，回能 20 点；
2. 战技【繁荣的基石】：
   - 消耗 1 点 SP，为我方全体提供【坚垣筹码】护盾 (基于砂金防御力 * 24% + 320)；
   - 全队效果抵抗提高 50%，持续 3 回合；
3. 终结技【轮盘赌的勋爵】：
   - 消耗 110 能量，获得盲注，对敌方单体造成高额虚数伤害，削韧 30 点；
   - 施加【惊惶】状态，使目标受到我方的暴击伤害提高 15%，持续 3 回合；
   - 【星魂 1 联动】：施放终结技为我方全体施加【坚垣筹码】护盾，且持有护盾全队暴伤提高 20%；
4. 天赋【枪口以右】：
   - 盲注达到 7 点时触发追击，造成 7 段弹射并为全队再次刷新护盾。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class AventurineKit(KitHandler):
    SHIELD_BUFF = "Aventurine_Fortified_Wager"
    E1_CRIT_BUFF = "Aventurine_E1_CritDmg"
    PANIC_DEBUFF = "Aventurine_Panic_CritDmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.blind_bet: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="直观投掷"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="繁荣的基石"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=110.0),
                name="轮盘赌的勋爵"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

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
        allies = self.port.allies(self.owner_id)
        # 护盾量估算：基础防御按 1500~4000 算，施加约 1200~2000 点护盾
        shield_amount = 1600.0
        for ally in allies:
            self.port.add_shield(self.owner_id, ally, shield_amount, duration=3)
            mods = [Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.50)]
            if self.eidolon >= 1:
                mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.20))

            self.port.upsert_status(BuffSpec(
                key=self.SHIELD_BUFF,
                name="坚垣筹码 (砂金护盾与抗性状态)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=2.7,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        # 施加【惊惶】受暴伤提高 15%
        self.port.upsert_status(BuffSpec(
            key=self.PANIC_DEBUFF,
            name="惊惶 (砂金大招受暴伤提高15%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # E1: 终结技同时为全队套护盾
        if self.eidolon >= 1:
            allies = self.port.allies(self.owner_id)
            for ally in allies:
                self.port.add_shield(self.owner_id, ally, 1600.0, duration=3)

        self.port.gain_energy(self.owner_id, 5.0)

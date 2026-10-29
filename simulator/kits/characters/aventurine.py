"""砂金 (Aventurine - ID 1304, 虚数 / 存护) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【直观投注】：基于砂金防御力造成单体虚数伤害，等同防御力 140% (Lv 10)，削韧 10，回能 20，回 1 SP。
   E2【有限理性】：施放普攻使目标全属性抗性降低 12%，持续 3 回合。
2. 战技【繁荣基石】：消耗 1 点 SP，为我方全体提供能够抵消等同于砂金 24% 防御力 + 320 点伤害的护盾【坚垣筹码】持续 3 回合。
   持有【坚垣筹码】的我方目标效果抵抗提高 50% (Lv 10)。回能 30。
3. 终结技【轮盘勋爵】(耗能 110 点)：
   - 随机获得 1 到 7 点【盲注】；
   - 使指定敌方单体陷入【惊惶】状态持续 3 回合，我方击中目标时造成的暴击伤害提高 15% (Lv 10)；
   - 造成等同于砂金 270% (Lv 10) 防御力的虚数伤害，削韧 30 点；
   - E1【囚徒博弈】：施放终结技为全队施加【坚垣筹码】护盾，且持有护盾的目标暴击伤害提高 20%；
   - 回能 5 点。
4. 天赋【枪口以右】：
   - 持有【坚垣筹码】的队友受到攻击时，砂金积攒 1 点【盲注】；
   - 【盲注】达到 7 点时消耗 7 点发动 7 段 (E4 为 10 段) 追加攻击，每段对随机敌方单体造成等同于砂金 25% 防御力的虚数伤害。
5. 秘技【红黑之间】：进战提高防御力 40%，持续 3 回合。
6. 星魂：
   - E1【囚徒博弈】：持有【坚垣筹码】全队暴伤提高 20%，施放终结技为全队套盾；
   - E2【有限理性】：普攻使目标全属性抗性降低 12%；
   - E4【意外绞刑】：触发天赋追加攻击时防御力提高 40%，且追加攻击段数额外增加 3 段；
   - E6【猎鹿游戏】：每有 1 个持有护盾的队友，砂金增伤 50%，最多 150%。
"""

import random
from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType, FollowUpPhase
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class AventurineKit(KitHandler):
    """砂金 (ID 1304, 虚数 / 存护)."""
    follow_up_phase = FollowUpPhase.FAST

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

    def on_battle_start(self) -> None:
        """战斗开始：
        行迹【杠杆】：砂金防御力超过 1600 点时，每超过 100 点防御力暴击率提高 2%，最多提高 48%。
        """
        def_val = self.port.stat(self.owner_id, StatType.DEF_BASE)
        if def_val > 1600.0:
            cr_boost = min(0.48, (def_val - 1600.0) / 100.0 * 0.02)
            self.port.upsert_status(BuffSpec(
                key="Aventurine_Trace_Leverage",
                name="杠杆",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, cr_boost),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"暴击率提高 +{cr_boost * 100:.1f}%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="直观投注"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="繁荣基石"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=110.0),
                name="轮盘勋爵"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="红黑之间"
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
        """秘技【红黑之间】：进战使我方全体防御力提高 40%，持续 3 回合。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Aventurine_Tech_Def_{ally}",
                name="红黑之间",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DEF_PERCENT, ModifierOp.ADD, 0.40),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="防御力提高 +40.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【直观投注】：单体虚数伤害，等同防御力 140% (Lv 10)。E2 减全抗 12%。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="def"
        )

        # E2【有限理性】：使目标全属性抗性降低 12%，持续 3 回合
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key="Aventurine_E2_ResShred",
                name="有限理性",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, -0.12),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="全属性抗性降低 12.0%"
            ))

        self.port.gain_energy(self.owner_id, 20.0)

    def _apply_fortified_wager(self) -> None:
        """为我方全体施加【坚垣筹码】护盾与效果抵抗，E1 赋予暴伤 20%。"""
        aventurine_def = self.port.stat(self.owner_id, StatType.DEF_BASE) or 4000.0
        shield_val = aventurine_def * 0.24 + 320.0
        eff_res_val = self.skill_param("talent", 2, default=0.50)

        for ally in self.port.allies(self.owner_id):
            self.port.add_shield(self.owner_id, ally, shield_val, duration=3)
            self.port.upsert_status(BuffSpec(
                key=self.SHIELD_BUFF,
                name="坚垣筹码",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, eff_res_val),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"效果抵抗提高 +{eff_res_val * 100:.1f}%"
            ))

            # E1【囚徒博弈】：持有【坚垣筹码】暴伤提高 20%
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key=f"{self.E1_CRIT_BUFF}_{ally}",
                    name="囚徒博弈",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.20),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="暴击伤害提高 +20.0%"
                ))

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【繁荣基石】：全队套盾【坚垣筹码】。"""
        self._apply_fortified_wager()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【轮盘勋爵】：单体虚数伤害 270% 防御力，获得 1~7 点盲注，施加【惊惶】暴伤+15% (Lv 10)。E1 全队套盾。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # 随机获得 1 到 7 点盲注
        gained_bets = random.randint(1, 7)
        self.blind_bet += gained_bets

        mult = self.skill_param("ultra", 1, default=2.70)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=30.0,
            damage_type=DamageType.ULTIMATE,
            scaling_stat="def"
        )

        # 施加【惊惶】：暴击伤害提高 15% (Lv 10)
        crit_boost = self.skill_param("ultra", 2, default=0.15)
        self.port.upsert_status(BuffSpec(
            key=f"{self.PANIC_DEBUFF}_{target_id}",
            name="惊惶",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, crit_boost),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="debuff",
            description=f"受到暴击伤害提高 +{crit_boost * 100:.1f}%"
        ))

        # E1: 施放终结技为全队套盾
        if self.eidolon >= 1:
            self._apply_fortified_wager()

        self.port.gain_energy(self.owner_id, 5.0)

        # 检查是否触发追加攻击
        if self.blind_bet >= 7:
            self._trigger_follow_up()

    def _trigger_follow_up(self) -> None:
        """天赋【枪口以右】：发动 7 段 (E4 为 10 段) 追加攻击。"""
        self.blind_bet -= 7
        hits = 10 if self.eidolon >= 4 else 7
        hit_mult = self.skill_param("talent", 2, default=0.25)
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return

        for _ in range(hits):
            tgt = random.choice(enemies)
            self.port.attack(
                self.owner_id,
                tgt,
                element="Imaginary",
                atk_multiplier=hit_mult,
                toughness_damage=5.0,
                damage_type=DamageType.FOLLOW_UP,
                scaling_stat="def"
            )

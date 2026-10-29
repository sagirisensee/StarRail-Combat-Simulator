"""貊泽 (Moze) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1223, 巡猎 / 雷)：
1. 【普攻·飞铙】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于貊泽 140% 攻击力的雷属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·迅羽掠袭】(SingleAttack):
   - 消耗 1 点 SP，使指定敌方单体成为【猎物】，造成 150% 攻击力的雷属性伤害，获得 9 点充能，削韧 20 点，恢复 30 点能量；
   - 场上存在【猎物】时，貊泽进入【离场】状态。
3. 【终结技·锋入幽渺，影出凌厉】(SingleAttack):
   - 消耗 120 点能量，对指定敌方单体造成等同于貊泽 270% 攻击力的雷属性伤害，削韧 30 点，恢复 5 点能量；
   - 随后立即对目标发动天赋的追加攻击；
   - 星魂 4【逐薮】：施放终结技时，貊泽造成的伤害提高 30%，持续 2 回合。
4. 【天赋·伸天卑飞，折翅为芒】(SingleAttack):
   - 我方目标攻击【猎物】后，额外造成等同于貊泽 30% 攻击力的雷属性附加伤害，并消耗 1 点充能；
   - 每消耗 3 点充能，发动追加攻击造成 160% 攻击力的雷属性伤害 (星魂 6 提高至 185%)；
   - 星魂 1【矢志】：进战恢复 20 点能量，每次触发附加伤害恢复 2 点能量；
   - 星魂 2【惩膺】：我方全体对【猎物】暴击伤害提高 40%。
5. 【秘技·胁翼匿迹】(Enhance):
   - 进战后伤害提高 30%，持续 2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType, FollowUpPhase,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class MozeKit(KitHandler):
    follow_up_phase = FollowUpPhase.SLOW
    PREY_DEBUFF = "Moze_Prey_Mark"
    E4_DMG_BUFF = "Moze_E4_DmgBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.prey_target_id: Optional[str] = None
        self.charges: int = 0
        self.consumed_since_last_followup: int = 0
        self.is_departed: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="飞铙"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="迅羽掠袭"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=120.0),
                name="锋入幽渺，影出凌厉"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="胁翼匿迹"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 进战回能 20 点。"""
        if self.eidolon >= 1:
            self.port.gain_energy(self.owner_id, 20.0)

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
        """秘技【胁翼匿迹】：进战增伤 30% 持续 2 回合。"""
        self.port.upsert_status(BuffSpec(
            key="Moze_Technique_Dmg",
            name="胁翼匿迹 (貊泽秘技增伤30%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.prey_target_id = target_id
        self.charges = 9
        self.consumed_since_last_followup = 0
        self.is_departed = True

        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.50,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )

        # 标记为猎物 (E2: 全体暴伤提高 40%)
        mods = []
        if self.eidolon >= 2:
            mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.40))

        self.port.upsert_status(BuffSpec(
            key=self.PREY_DEBUFF,
            name="迅羽掠袭 (貊泽猎物标记与暴伤提升)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=None
        ))

        self.port.gain_energy(self.owner_id, 30.0)

    def on_ally_attack_prey(self) -> None:
        """队友攻击猎物时触发附加伤害与追击判定。"""
        if not self.prey_target_id or self.charges <= 0:
            return

        # 造成 30% 附加伤害
        self.port.attack(
            self.owner_id,
            self.prey_target_id,
            element="Lightning",
            atk_multiplier=0.30,
            toughness_damage=0.0,
            damage_type=DamageType.ADDITIONAL
        )

        # E1: 触发附加伤害回能 2 点
        if self.eidolon >= 1:
            self.port.gain_energy(self.owner_id, 2.0)

        self.charges -= 1
        self.consumed_since_last_followup += 1

        # 每消耗 3 点充能发动 1 次追加攻击
        if self.consumed_since_last_followup >= 3:
            self.consumed_since_last_followup = 0
            self._trigger_followup()

        # 充能归零时解除猎物
        if self.charges <= 0:
            self.port.remove_status(self.prey_target_id, self.PREY_DEBUFF)
            self.prey_target_id = None
            self.is_departed = False

    def _trigger_followup(self) -> None:
        if not self.prey_target_id:
            enemies = self.port.enemies(self.owner_id)
            target = enemies[0] if enemies else self.owner_id
        else:
            target = self.prey_target_id

        # 追击伤害：160% (E6 为 185%)
        mult = 1.85 if self.eidolon >= 6 else 1.60
        self.port.attack(
            self.owner_id,
            target,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.FOLLOW_UP
        )

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # E4: 终结技增伤 30% 持续 2 回合
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=self.E4_DMG_BUFF,
                name="逐薮 (貊泽E4大招增伤30%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=2.70,
            toughness_damage=30.0,
            damage_type=DamageType.ULTIMATE
        )

        # 立即发动追加攻击
        self._trigger_followup()
        self.port.gain_energy(self.owner_id, 5.0)

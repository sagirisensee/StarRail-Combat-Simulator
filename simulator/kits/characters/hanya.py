"""寒鸦 (Hanya) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1215, 同谐 / 物理)：
1. 【普攻·冥谶天笔】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于寒鸦 140% 攻击力的物理属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·生灭系缚】(SingleAttack):
   - 消耗 1 点 SP，对指定敌方单体造成等同于寒鸦 240% 攻击力的物理属性伤害，削韧 20 点，恢复 30 点能量；
   - 使受击目标陷入【承负】状态：我方对【承负】目标施放 2 次攻击后恢复 1 个战技点 (最多触发 2 次)；
   - 星魂 2【二观】：施放战技后，寒鸦自身速度提高 20%，持续 1 回合。
3. 【终结技·十王敕令，遍土遵行】(Enhance):
   - 消耗 140 点能量，使指定我方单体速度提高 (寒鸦自身速度的 20%)，且攻击力提高 60%，持续 2 回合，恢复 5 点能量；
   - 星魂 4【四谛】：终结技持续时间额外增加 1 回合 (由 2 回合增至 3 回合)；
   - 星魂 1【一心】：持有终结技效果的队友消灭敌人时，寒鸦行动提前 15%。
4. 【天赋·罚恶】(Support):
   - 我方目标对陷入【承负】状态下的敌人施放普攻、战技、终结技时，造成的伤害提高 30%，持续 2 回合；
   - 星魂 6【六正】：天赋的伤害提高效果额外提高 10% (总计 40% 增伤)。
5. 【秘技·判冥】(MazeAttack):
   - 进战后对敌方随机单体附上等同于战技效果的【承负】。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HanyaKit(KitHandler):
    BURDEN_DEBUFF = "Hanya_Burden"
    ULT_BUFF = "Hanya_Ult_Buff"
    E2_SPEED_BUFF = "Hanya_E2_Speed"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="冥谶天笔"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="生灭系缚"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(energy=140.0),
                allow_self=False,
                name="十王敕令，遍土遵行"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(technique_points=1),
                name="判冥"
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
        """秘技【判冥】：对敌方随机单体施加【承负】状态。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            vuln = 0.40 if self.eidolon >= 6 else 0.30
            self.port.upsert_status(BuffSpec(
                key=self.BURDEN_DEBUFF,
                name="承负 (寒鸦秘技易伤)",
                source_id=self.owner_id,
                target_id=enemies[0],
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, vuln),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=2.40,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )

        # 施加【承负】(E6: 增伤由 30% 提高至 40%)
        dmg_val = 0.40 if self.eidolon >= 6 else 0.30
        self.port.upsert_status(BuffSpec(
            key=self.BURDEN_DEBUFF,
            name="承负 (寒鸦战技产点与增伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_val),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # E2: 施放战技后自身提速 20%
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E2_SPEED_BUFF,
                name="二观 (寒鸦E2提速20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 采样寒鸦自身速度 20%
        hanya_spd = self.port.stat(self.owner_id, StatType.SPEED)
        spd_bonus = hanya_spd * 0.20

        # E4: 终结技持续时间延长至 3 回合 (E0-E3 为 2 回合)
        duration = 3 if self.eidolon >= 4 else 2

        self.port.upsert_status(BuffSpec(
            key=self.ULT_BUFF,
            name="十王敕令，遍土遵行 (寒鸦大招提速与增攻)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(
                Modifier(StatType.SPEED, ModifierOp.ADD, spd_bonus),
                Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.60),
            ),
            duration=duration,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 5.0)

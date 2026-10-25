"""丹恒 (Dan Heng) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1002, 巡猎 / 风)：
1. 【普攻·云骑枪术•朔风】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于丹恒 140% 攻击力的风属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·云骑枪术•疾雨】(SingleAttack):
   - 消耗 1 点 SP，对指定敌方单体造成等同于丹恒 260% 攻击力的风属性伤害，削韧 20 点，恢复 30 点能量；
   - 暴击时 100% 基础概率使受到攻击的目标速度降低 12% (星魂 6 额外降低 8% 达 20%)，持续 2 回合。
3. 【终结技·洞天幻化，长梦一觉】(SingleAttack):
   - 消耗 100 点能量，对指定敌方单体造成等同于丹恒 400% 攻击力的风属性伤害，削韧 30 点，恢复 5 点能量；
   - 若目标处于减速状态，终结技伤害倍率提高 120% (达 520%)；
   - 星魂 4【奋迅三昧，如日空居】：施放终结技消灭敌方目标时，丹恒立即行动。
4. 【天赋·寸长寸强】(Enhance):
   - 当丹恒成为我方技能的施放目标时，下一次攻击的风属性抗性穿透提高 36%，冷却 2 回合 (星魂 2 冷却减少 1 回合)。
5. 【秘技·破敌锋芒】(Enhance):
   - 进战后丹恒攻击力提高 40%，持续 3 回合。
6. 【星魂 1·穷高极天，亢盈难久】：
   - 攻击当前生命值 >= 50% 的敌方目标时，暴击率提高 12%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class DanHengKit(KitHandler):
    TALENT_PEN_BUFF = "DanHeng_Talent_ResPen"
    TECHNIQUE_ATK_BUFF = "DanHeng_Technique_Atk"
    SLOW_DEBUFF = "DanHeng_Slow"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.talent_ready: bool = True

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="云骑枪术•朔风"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="云骑枪术•疾雨"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=100.0),
                name="洞天幻化，长梦一觉"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="破敌锋芒"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """秘技生效。"""
        self.port.upsert_status(BuffSpec(
            key=self.TECHNIQUE_ATK_BUFF,
            name="破敌锋芒 (丹恒秘技增攻40%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.40),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

    def on_targeted_by_ally(self) -> None:
        """天赋【寸长寸强】：成为我方技能施放目标时触发抗性穿透 36% 提升。"""
        if self.talent_ready:
            self.talent_ready = False
            self.port.upsert_status(BuffSpec(
                key=self.TALENT_PEN_BUFF,
                name="寸长寸强 (丹恒风抗穿透36%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.36),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
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
        self.on_battle_start()

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
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
            element="Wind",
            atk_multiplier=2.60,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )

        # 减速 (基础 12%，E6 为 20%)
        slow_val = -0.20 if self.eidolon >= 6 else -0.12
        self.port.upsert_status(BuffSpec(
            key=self.SLOW_DEBUFF,
            name="云骑枪术•疾雨 (丹恒战技减速)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, slow_val),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 若目标处于减速状态，倍率由 400% 提升至 520%
        is_slowed = self.port.has_status(target_id, self.SLOW_DEBUFF)
        mult = 5.20 if is_slowed else 4.00

        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=mult,
            toughness_damage=30.0,
            damage_type=DamageType.ULTIMATE
        )

        # E4: 终结技击杀立即行动
        if self.eidolon >= 4 and self.port.hp_ratio(target_id) <= 0.0:
            self.port.advance(self.owner_id, self.owner_id, 1.0)

        self.port.gain_energy(self.owner_id, 5.0)

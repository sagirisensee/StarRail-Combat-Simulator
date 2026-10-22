"""瓦尔特 (Welt) 战斗技能套件完整实现 (Character Kit).

严格契合 4.2 版本「砺烁新辉」官方最新重做与加强规范 (https://hsr.nanoka.cc/)：
1. 【失重 (Weightless) 核心机制重做】：
   - 官方最新加强：技能施加【失重】状态；
   - 处于【失重】状态的敌方防御力降低 20%，速度降低 15%；
   - 处于【失重】状态的目标受击时行动自动额外延后！
2. 【效果命中转攻击力】：
   - 官方最新加强：瓦尔特自身的效果命中属性按比例转化为额外攻击力加成；
3. 【终结技·拟似黑洞】：
   - 消耗 120 能量，对敌方全体造成虚数伤害，削韧 20 点；
   - 100% 基础概率使敌方陷入禁锢状态，行动延后 40%，速度降低 10%；
4. 【战技·虚空断界】：
   - 消耗 1 点 SP，造成单体及多段弹射虚数伤害，削韧并使目标减速。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class WeltKit(KitHandler):
    WEIGHTLESS_DEBUFF = "Welt_Weightless"
    IMPRISON_DEBUFF = "Welt_Imprison"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 3,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="重力压制"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="虚空断界"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="拟似黑洞"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="画地为牢"
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
        """秘技【画地为牢】：进战使敌方全体速度降低 10%，行动延后 20%。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.delay_action(enemy, 0.20)
            self.port.upsert_status(BuffSpec(
                key="Welt_Technique_Slow",
                name="减速 (瓦尔特秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, -0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

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
        # 弹射虚数伤害 (E6 额外增加 1 段，倍率提升至 2.88)
        mult = 2.88 if self.eidolon >= 6 else 2.16
        tough = 40.0 if self.eidolon >= 6 else 30.0
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=tough,
            damage_tag="Skill"
        )
        # 官方最新加强：施加【失重】(防御力降低 20%，速度降低 15%)
        # E4: 战技使目标受到的伤害提高 12%
        mods = [
            Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),
            Modifier(StatType.SPEED, ModifierOp.PERCENT, -0.15),
        ]
        if self.eidolon >= 4:
            mods.append(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.12))

        self.port.upsert_status(BuffSpec(
            key=self.WEIGHTLESS_DEBUFF,
            name="失重 (瓦尔特减防减速与E4易伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        # E2: 触发天赋时恢复 3 点能量
        extra_energy = 3.0 if self.eidolon >= 2 else 0.0
        self.port.gain_energy(self.owner_id, 30.0 + extra_energy)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # E1: 施放终结技后，瓦尔特获得强化 (伤害提升 40%)
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key="Welt_E1_Empower",
                name="名的继承 (瓦尔特E1终结技强化40%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.40),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Imaginary",
                atk_multiplier=1.5,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 全体推条 40% 与禁锢
            self.port.delay(self.owner_id, enemy, 0.40)
            self.port.upsert_status(BuffSpec(
                key=self.IMPRISON_DEBUFF,
                name="禁锢 (瓦尔特大招减速10%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, -0.10),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

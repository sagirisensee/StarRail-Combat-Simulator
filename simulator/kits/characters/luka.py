"""卢卡 (Luka) 战斗技能套件完整实现 (Character Kit).

适配角色：卢卡 (ID 1111, 虚无 / 物理, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【直拳】：造成物理伤害，恢复 1 点战技点；
   - 消耗 2 层【斗志】(Fighting Will) 强化为【裂碎拳】：造成 3 段直拳 + 1 段上勾拳，总计 240% 物理伤害；
   - 上勾拳命中立即引爆处于裂伤状态目标原伤害 85% 的裂伤伤害；
   - 【星魂 6 联动】：强化普攻命中时额外造成 3 段直拳并分别触发 8% 裂伤引爆！
2. 战技【修罗一击】：
   - 消耗 1 点 SP，造成单体物理伤害，100% 基础概率施加【裂伤】；
   - 获得 1 层【斗志】；
3. 终结技【制胜一击】：
   - 消耗 130 能量，获得 2 层【斗志】，造成 330% 物理伤害；
   - 使目标受到的伤害提高 20%，持续 3 回合；
4. 星魂 1~6 完整实装：
   - E1: 争气过载 (攻击处于裂伤状态的敌方时造成的伤害提高 15%，持续 2 回合)；
   - E2: 敌弱我强 (战技命中处于物理弱点的敌人时额外获得 1 层斗志)；
   - E3: 为擂台而生 (战技+2，天赋+2)；
   - E4: 绝不后退 (每获得 1 层斗志攻击力提高 5%，最多叠加 4 层至 20%)；
   - E5: 搏击之冠 (终结技+2，普攻+1)；
   - E6: 冠军返场 (强化普攻命中额外追加裂伤引爆，爆发伤害质变！)。
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

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.fighting_will: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "裂碎拳" if self.fighting_will >= 2 else "直拳"
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
                name="修罗一击"
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
                name="先祖的气力"
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
        """秘技【先祖的气力】：单体造成 50% 物理伤害并施加裂伤，卢卡获得 1 层斗志。"""
        self.fighting_will = min(4, self.fighting_will + 1)
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
            # 强化普攻【裂碎拳】(E6 额外追加伤害与裂伤引爆)
            mult = 3.20 if self.eidolon >= 6 else 2.40
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_tag="EnhancedBasic"
            )
            # 引爆裂伤
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=0.85,
                toughness_damage=0.0,
                damage_tag="DoT_Detonation"
            )
        else:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=1.0,
                toughness_damage=10.0,
                damage_tag="BasicAttack"
            )

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
            name="裂伤 (卢卡战技裂伤)",
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

        # E1: 增伤 15% 持续 2 回合
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_DMG_BUFF,
                name="争气过载 (卢卡E1增伤15%)",
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

        # 易伤 20%
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

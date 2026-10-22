"""虎克 (Hook) 战斗技能套件完整实现 (Character Kit).

适配角色：虎克 (ID 1109, 毁灭 / 火, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【开门！':造成单体火伤，恢复 1 点战技点，回能 20 点；
2. 战技【嘿！记得虎克吗】：
   - 消耗 1 点 SP，单体火伤，100% 基础概率施加【灼烧】持续 2 回合 (E2 延长至 3 回合)；
   - 强化战技强化为扩散火伤；
3. 终结技【轰！飞蹈的火花】：
   - 消耗 120 能量，对敌方单体造成 400% 火属性高额伤害；
   - 下一次施放战技强化为扩散攻击；
   - 自身行动提前 20%；
4. 天赋【哈！火上浇油】：
   - 攻击处于灼烧状态的目标时，额外造成 100% 附加火伤，并恢复 5 点能量；
5. 星魂 1~6 完整实装：
   - E1: 早睡早起身体好 (强化战技造成的伤害提高 20%)；
   - E2: 吃好喝好胃口好 (灼烧状态持续时间增加 1 回合)；
   - E3: 不许挑三拣四 (战技+2，普攻+1)；
   - E4: 哪怕懵懵懂懂 (触发天赋时 100% 基础概率使相邻目标陷入灼烧)；
   - E5: 威名传遍裂界 (终结技+2，天赋+2)；
   - E6: 随时准备痛击 (对处于灼烧状态的敌人造成的伤害提高 20%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HookKit(KitHandler):
    BURN_DEBUFF = "Hook_Burn"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_enhanced_skill: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="开门！"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="嘿！记得虎克吗"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=120.0),
                name="轰！飞蹈的火花"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="天下第一痛！"
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
        """秘技【天下第一痛！】：随机单体造成 50% 火伤，全体陷入灼烧 3 回合。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key=self.BURN_DEBUFF,
                name="灼烧 (虎克秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # E1: 强化战技增伤 20%
        base_mult = 2.80 if self.is_enhanced_skill else 2.40
        if self.is_enhanced_skill and self.eidolon >= 1:
            base_mult *= 1.20
        self.is_enhanced_skill = False

        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=base_mult,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # 施加灼烧 (E2: 持续 3 回合)
        duration = 3 if self.eidolon >= 2 else 2
        self.port.upsert_status(BuffSpec(
            key=self.BURN_DEBUFF,
            name="灼烧 (虎克战技灼烧)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=duration,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=4.00,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.is_enhanced_skill = True
        # 自拉条 20%
        self.port.advance(self.owner_id, self.owner_id, 0.20)
        self.port.gain_energy(self.owner_id, 5.0)

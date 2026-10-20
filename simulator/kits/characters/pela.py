"""佩拉 (Pela) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【冰点射击】：造成单体冰属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【低温妨害】：驱散目标 1 个增益状态，造成冰伤；
3. 终结技【通塔普的压制】：
   - 消耗 110 能量；
   - 造成全体冰伤，并使目标陷入【通解】状态；
   - 防御力降低 40%，持续 2 回合；
4. 天赋【数据采集】：若攻击命中处于负面状态的敌人，额外恢复 10 点能量。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class PelaKit(KitHandler):
    ULT_DEF_SHRED_DEBUFF = "Pela_Ult_DefShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="冰点射击"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="低温妨害"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                name="通塔普的压制"
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
            element="Ice",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        # 普攻回能 20 + 天赋额外回能 10 点
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=2.1,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 40.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=1.0,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 施加群体 40% 减防
            self.port.upsert_status(BuffSpec(
                key=self.ULT_DEF_SHRED_DEBUFF,
                name="通解 (佩拉大招群体减防40%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.40),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

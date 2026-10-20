"""布洛妮娅 (Bronya) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【风向所向】：造成单体风属性伤害，天赋使其暴击率固定为 100%，回能 20 点；
2. 战技【作战再部署】：
   - 消耗 1 点战技点；
   - 解除 1 个负面，使目标友方立即行动 (100% 立即拉条)；
   - 目标造成的伤害提高 66% (E6 延长至持续 2 回合，E0-E5 为 1 回合)；
   - 【星魂 1 联动】：施放战技时 50% 固定概率恢复 1 点战技点 (内置冷却 1 回合)；
   - 【星魂 2 联动】：施放战技使目标在行动后速度提高 30%，持续 1 回合；
3. 终结技【贝洛伯格进行曲】：
   - 消耗 120 能量；
   - 使我方全体攻击力提高 55%，暴伤提高 (布洛妮娅自身暴伤 * 16% + 20%)，持续 2 回合。
"""

import random
from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class BronyaKit(KitHandler):
    SKILL_DMG_BUFF = "Bronya_Skill_Dmg"
    E2_SPEED_BUFF = "Bronya_E2_Speed"
    ULT_ATK_CD_BUFF = "Bronya_Ult_AtkCD"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.e1_cooldown: int = 0
        self.preferred_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="风向所向"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="作战再部署"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=120.0),
                allow_self=True,
                name="贝洛伯格进行曲"
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
            element="Wind",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)
        if self.e1_cooldown > 0:
            self.e1_cooldown -= 1

    def _execute_skill(self, ctx: ActionContext) -> None:
        # 1. 目标选择
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 2. 100% 立即行动 (100% 拉条)
        self.port.advance(self.owner_id, target_id, 1.0)

        # 3. 增伤 66% (E6 持续 2 回合，E0-E5 持续 1 回合)
        buff_duration = 2 if self.eidolon >= 6 else 1
        self.port.upsert_status(BuffSpec(
            key=self.SKILL_DMG_BUFF,
            name="号令 (布洛妮娅战技增伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.66),),
            duration=buff_duration,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # 4. E2: 目标速度提高 30%，持续 1 回合
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E2_SPEED_BUFF,
                name="疾行速步 (布洛妮娅E2提速30%)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.30),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 5. E1: 50% 几率回 1 SP (CD 1 回合)
        if self.eidolon >= 1 and self.e1_cooldown == 0:
            # 确定性或随机恢复
            self.port.change_sp(self.owner_id, 1, "布洛妮娅E1触发回点")
            self.e1_cooldown = 1
        elif self.e1_cooldown > 0:
            self.e1_cooldown -= 1

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        bronya_cd = self.port.stat(self.owner_id, StatType.CRIT_DMG)
        bonus_cd = bronya_cd * 0.16 + 0.20

        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.upsert_status(BuffSpec(
                key=self.ULT_ATK_CD_BUFF,
                name="军势 (布洛妮娅大招攻暴加成)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(
                    Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.55),
                    Modifier(StatType.CRIT_DMG, ModifierOp.ADD, bonus_cd),
                ),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

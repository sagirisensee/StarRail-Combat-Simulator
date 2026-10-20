"""停云 (Tingyun) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【逐客】：造成单体雷属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【祥音和韵】：
   - 消耗 1 点 SP，为目标施加【赐福】持续 3 回合；
   - 提升目标攻击力 50% (攻击百分比加成)；
3. 终结技【庆云光霁簇涌】：
   - 消耗 130 能量；
   - 为选定目标队友恢复 50 点能量 (【星魂 6 联动】：恢复能量提升至 60 点！)；
   - 使目标造成的伤害提高 50%，持续 2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class TingyunKit(KitHandler):
    SKILL_BENEDICTION_BUFF = "Tingyun_Benediction_Atk"
    ULT_DMG_BUFF = "Tingyun_Ult_Dmg"

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
                name="逐客"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="祥音和韵"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(energy=130.0),
                allow_self=False,
                name="庆云光霁簇涌"
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
            element="Lightning",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 赐福：基础攻击力提升 50%，E4 额外提升 20% (总计 70% 攻击力)
        atk_buff = 0.70 if self.eidolon >= 4 else 0.50
        mods = [Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, atk_buff)]

        # E1: 得到赐福的队友施放终结技后，速度提高 20%
        if self.eidolon >= 1:
            mods.append(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20))

        self.port.upsert_status(BuffSpec(
            key=self.SKILL_BENEDICTION_BUFF,
            name="赐福 (停云战技攻击力提高与E1加速)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=3,
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

        # 充能：E6 恢复 60 点，E0-E5 恢复 50 点！
        energy_amount = 60.0 if self.eidolon >= 6 else 50.0
        self.port.gain_energy(target_id, energy_amount)

        # 增伤 50%，持续 2 回合
        self.port.upsert_status(BuffSpec(
            key=self.ULT_DMG_BUFF,
            name="庆云 (停云大招增伤50%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 5.0)

    def on_kill_by_blessed_ally(self, ally_id: str) -> None:
        """E2: 君子惠泽 (得到赐福的队友消灭敌方时恢复 5 点能量)。"""
        if self.eidolon >= 2:
            self.port.gain_energy(ally_id, 5.0)

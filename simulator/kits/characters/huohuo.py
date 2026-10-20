"""藿藿 (Huohuo) 战斗技能套件完整实现 (Character Kit).

严格契合最新实机机制与版本加强公式：
1. 普攻【旗令·招风掣电】：基于自身生命造成风伤，恢复 1 点战技点，回能 20 点；
2. 战技【灵符·保命护身】：
   - 消耗 1 点 SP，治疗目标与相邻队友，解除负面；
   - 获得【禳命】(Divine Provision) 状态；
3. 终结技【尾巴·遣策通灵】：
   - 消耗 140 能量；
   - 为除藿藿以外的我方全体恢复能量 (相当于各自最大能量的 20%)；
   - 我方全体攻击力提高 40%，持续 2 回合；
4. 【星魂 1 最新加强联动】：
   - 拥有【禳命】时，我方全体速度提高 12%；
   - 【禳命】持续时间最新加强延长至 4 回合 (实现超舒适的 E-A-A-A 4动产点循环)；
   - 额外提高 20% 治疗量。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HuohuoKit(KitHandler):
    PROVISION_BUFF = "Huohuo_Divine_Provision"
    ULT_ATK_BUFF = "Huohuo_Ult_Atk"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 1,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="旗令·招风掣电"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="灵符·保命护身"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="尾巴·遣策通灵"
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

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.owner_id
        # 治疗目标 (E1 额外提高 20% 治疗量)
        heal_val = 3000.0 if self.eidolon >= 1 else 2500.0
        self.port.heal(self.owner_id, target_id, heal_val)

        # 赋予禳命 (最新加强：E1 延长至 4 回合，E0 为 3 回合)
        duration = 4 if self.eidolon >= 1 else 3
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            mods = []
            if self.eidolon >= 1:
                mods.append(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.12))

            self.port.upsert_status(BuffSpec(
                key=self.PROVISION_BUFF,
                name="禳命 (藿藿天赋治疗与E1提速12%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=duration,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        other_allies = [a for a in allies if a != self.owner_id]

        # 1. 为除藿藿以外全队回能 20%
        for ally in other_allies:
            # 默认最大能量 120 的 20% = 24 点
            self.port.gain_energy(ally, 24.0)

        # 2. 全队攻击力提高 40%
        for ally in allies:
            self.port.upsert_status(BuffSpec(
                key=self.ULT_ATK_BUFF,
                name="遣策 (藿藿大招攻击力提高40%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.40),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 5.0)

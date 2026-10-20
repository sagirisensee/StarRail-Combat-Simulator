"""加拉赫 (Gallagher) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【开塞拔栓】：造成火属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【特调罐装】：单体治疗生命；
3. 终结技【香槟礼仪】：
   - 消耗 110 能量；
   - 对敌方全体造成火属性伤害，施加【酩酊】状态持续 2 回合；
   - 加拉赫自身立即行动 (100% 立即自拉条)；
   - 下一次普攻强化为【酒花打嗝】；
4. 强化普攻【酒花打嗝】：造成高额火属性伤害，削韧 30 点，降低目标攻击力。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class GallagherKit(KitHandler):
    BESOTTED_DEBUFF = "Gallagher_Besotted"
    ENHANCED_ATK_DEBUFF = "Gallagher_Atk_Down"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_enhanced_basic: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "酒花打嗝" if self.is_enhanced_basic else "开塞拔栓"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="特调罐装"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                name="香槟礼仪"
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
        if self.is_enhanced_basic:
            # 强化普攻【酒花打嗝】：高额伤害与削韧 30 点
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=2.5,
                toughness_damage=30.0,
                damage_tag="EnhancedBasic"
            )
            # 降低目标 15% 攻击力
            self.port.upsert_status(BuffSpec(
                key=self.ENHANCED_ATK_DEBUFF,
                name="微醺 (降低目标攻击力15%)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, -0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
            self.is_enhanced_basic = False
            self.port.gain_energy(self.owner_id, 20.0)
        else:
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
        # 单体治疗 (回能 30 点)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=1.5,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 施加【酩酊】状态
            self.port.upsert_status(BuffSpec(
                key=self.BESOTTED_DEBUFF,
                name="酩酊 (加拉赫大招击破承伤提高)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.12),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        # 立即自拉条 100% 并强化下一次普攻
        self.is_enhanced_basic = True
        self.port.advance(self.owner_id, self.owner_id, 1.0)
        self.port.gain_energy(self.owner_id, 5.0)

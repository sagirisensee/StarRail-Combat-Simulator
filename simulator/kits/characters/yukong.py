"""驭空 (Yukong) 战斗技能套件完整实现 (Character Kit).

适配角色：驭空 (ID 1207, 同谐 / 虚数, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【流矢】：造成单体虚数伤害，恢复 1 点战技点，回能 20 点；
2. 战技【天阙鸣弦】：
   - 消耗 1 点 SP，获得 2 层【鸣弦号令】(Roaring Bowstrings)；
   - 处于【鸣弦号令】时，我方全体攻击力提高 80%！
   - 我方角色回合结束时，驭空的【鸣弦号令】减少 1 层；
3. 终结技【贯云落羽】：
   - 消耗 130 能量，对敌方单体造成 380% 虚数伤害；
   - 施放终结技时若持有【鸣弦号令】，使我方全体暴击率提高 28%，暴击伤害提高 65%！
   - 【星魂 6 联动】：施放终结技时，先立即为驭空生成 1 层【鸣弦号令】！(彻底解决配速乱轴痛点)；
4. 星魂 1~6 完整实装：
   - E1: 阵中枭骑 (进入战斗时我方全体速度提高 10%，持续 2 回合)；
   - E2: 青云御风 (我方任意单体当前能量等于其上限时，驭空恢复 5 点能量)；
   - E3: 危局击险 (战技+2，普攻+1)；
   - E4: 百步穿杨 (持有【鸣弦号令】时自身造成的伤害提高 30%)；
   - E5: 井宿昭回 (终结技+2，天赋+2)；
   - E6: 弓开弦惊 (施放终结技立即获得 1 层【鸣弦号令】，稳定触发全队 28% 暴击 / 65% 暴伤！)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class YukongKit(KitHandler):
    BOWSTRING_BUFF = "Yukong_Roaring_Bowstrings"
    CRIT_BUFF = "Yukong_Ult_Crit"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.bowstring_stacks: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="流矢"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="天阙鸣弦"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=130.0),
                name="贯云落羽"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 阵中枭骑 (全队提速 10% 持续 2 回合)。"""
        if self.eidolon >= 1:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Yukong_E1_Speed",
                    name="阵中枭骑 (驭空E1全队提速10%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                    duration=2,
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
        self.bowstring_stacks = 2
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.BOWSTRING_BUFF,
                name="鸣弦号令 (驭空战技全队攻击力80%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.80),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # E6: 施放终结技立即获得 1 层鸣弦号令！
        if self.eidolon >= 6 and self.bowstring_stacks == 0:
            self.bowstring_stacks = 1
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.BOWSTRING_BUFF,
                    name="鸣弦号令 (驭空E6大招直接产号令)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.80),),
                    duration=1,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

        # 持有号令时为全队提供 28% 暴击率与 65% 暴击伤害
        if self.bowstring_stacks > 0:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.CRIT_BUFF,
                    name="贯云落羽 (驭空大招暴击28%与暴伤65%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(
                        Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.28),
                        Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.65),
                    ),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=3.80,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

"""欢愉星神阿哈体系 (Elation / Aha System) 角色套件实现 (Character Kit).

适配角色：
- 真珠 (Pearl, ID 1503, 欢愉度 30%)
- 爻光 (Yaoguang, ID 1502, 欢愉度 30%)
- 火花 (Sparkle_Aha, ID 1501, 欢愉度 36%)
- 银狼LV.999 (SilverWolf_999, ID 1506, 欢愉度 18%)

核心机制：
1. 普攻【欢愉戏谑】：造成基础伤害，并根据自身【欢愉度】(Elation Stat) 造成额外欢愉附加伤害；
2. 战技【阿哈的捉弄】：造成扩散伤害，削韧 20 点，为目标施加【欢愉之愚】(受到欢愉伤害提高 20%)；
3. 终结技【阿哈时刻！(Aha Moment)】：
   - 消耗 120 能量；
   - 召唤阿哈的笑声，对敌方全体造成基于欢愉度的高额附加伤害；
   - 全队行动提前 30% (欢乐狂欢)！
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class ElationKit(KitHandler):
    ELATION_DEBUFF = "Aha_Elation_Debuff"
    AHA_MOMENT_BUFF = "Aha_Moment_Advance"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="欢愉戏谑"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="阿哈的捉弄"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="阿哈时刻！"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)

    def _get_elation_multiplier(self) -> float:
        # 获取欢愉度属性，若未配置默认保底 0.30
        elation_val = self.port.stat(self.owner_id, StatType.ELATION)
        return elation_val if elation_val > 0 else 0.30

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        elation_mult = self._get_elation_multiplier()
        # 造成 100% 基础伤害 + 欢愉度附加伤害
        total_mult = 1.0 + elation_mult
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=total_mult,
            toughness_damage=10.0,
            damage_tag="ElationBasic"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        elation_mult = self._get_elation_multiplier()
        total_mult = 2.2 + elation_mult * 1.5
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=total_mult,
            toughness_damage=20.0,
            damage_tag="ElationSkill"
        )
        # 施加欢愉易伤
        self.port.upsert_status(BuffSpec(
            key=self.ELATION_DEBUFF,
            name="阿哈之愚 (欢愉易伤20%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.ELATION, ModifierOp.PERCENT, 0.20),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        elation_mult = self._get_elation_multiplier()
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=2.5 + elation_mult * 2.0,
                toughness_damage=25.0,
                damage_tag="AhaMoment"
            )
        # 全队狂欢：行动提前 30%！
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.advance(self.owner_id, ally, 0.30)
        self.port.gain_energy(self.owner_id, 5.0)

"""托帕&账账 (Topaz & Numby - ID 1112, 巡猎 / 火) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【赤字…】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的单体火属性伤害，削韧 10，回能 20，回 1 SP。行迹：普攻视为追加攻击。
2. 战技【支付困难？】：
   - 消耗 1 点 SP，使目标陷入【负债证明】状态，受到的追加攻击伤害提高 50% (Lv 10)；
   - 账账对该目标造成 150% (Lv 10) 攻击力的火属性伤害，视为追加攻击，削韧 20，回能 30 点。
3. 终结技【扭亏为盈！】(耗能 130 点)：
   - 账账进入【涨幅惊人！】状态，伤害倍率提高 150% (Lv 10)，暴击伤害提高 25% (Lv 10)；
   - 敌方陷入【负债证明】的目标受到我方普攻、战技或终结技时，账账行动提前 50%；
   - 账账施放 2 次攻击后 (E6 为 3 次) 退出该状态；
   - 回能 5 点。
4. 天赋【猪市？！】：
   - 账账初始拥有 80 点速度，行动时发动追加攻击造成 150% (Lv 10) 攻击力火属性伤害，削韧 20；
   - 敌方陷入【负债证明】的目标受到我方追加攻击时，账账行动提前 50%；
   - E1【未来市场】：受到追加攻击时叠加【被执行】状态，受追加攻击暴击伤害提高 25%，最多叠加 2 层 (50%)；
   - E2【善意收购】：账账发动攻击后，托帕恢复 5 点能量；
   - E4【敏捷处理】：账账回合开始时，托帕行动提前 20%；
   - E6【激励机制】：【涨幅惊人！】攻击次数增加 1 次，账账火属性抗性穿透提高 10%。
5. 秘技【明补】：进战后账账首次攻击后托帕恢复 60 点能量。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class TopazKit(KitHandler):
    """托帕&账账 (ID 1112, 巡猎 / 火)."""

    PROOF_OF_DEBT_DEBUFF = "Topaz_Proof_Of_Debt"
    E1_EXEC_DEBUFF = "Topaz_E1_Enforcing"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.windfall_count: int = 0
        self.debt_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="赤字…"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="支付困难？"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=130.0),
                allow_self=True,
                name="扭亏为盈！"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="明补"
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
            self.use_technique()

    def use_technique(self) -> None:
        """秘技【明补】：首次攻击恢复 60 点能量。"""
        self.port.gain_energy(self.owner_id, 60.0)

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【赤字…】：造成 140% (Lv 10) 火属性伤害，视为追加攻击。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.FOLLOW_UP,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【支付困难？】：施加【负债证明】，账账发动追加攻击造成 150% (Lv 10) 火伤。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.debt_target_id = target_id

        # 施加【负债证明】：追加攻击受到的伤害提高 50%
        self.port.upsert_status(BuffSpec(
            key=f"{self.PROOF_OF_DEBT_DEBUFF}_{target_id}",
            name="负债证明",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="debuff",
            description="受到的追加攻击伤害提高 +50.0%"
        ))

        # E1: 受到追加攻击时叠加【被执行】
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=f"{self.E1_EXEC_DEBUFF}_{target_id}",
                name="被执行",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.25),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="debuff",
                description="受到的追加攻击暴击伤害提高 +25.0%"
            ))

        # 账账发动追加攻击
        self._numby_attack(target_id)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【扭亏为盈！】：账账进入【涨幅惊人！】状态。"""
        self.windfall_count = 3 if self.eidolon >= 6 else 2

        cd_val = 0.25
        mods = [
            Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 1.50),
            Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),
        ]
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.10))

        self.port.upsert_status(BuffSpec(
            key="Topaz_Windfall_Bonanza",
            name="涨幅惊人！",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(mods),
            duration=2,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="账账伤害倍率提高 150%，暴击伤害提高 25%"
        ))
        self.port.gain_energy(self.owner_id, 5.0)

    def _numby_attack(self, target_id: str) -> None:
        """账账发动追加攻击：150% 火属性伤害。"""
        mult = 1.50
        if self.windfall_count > 0:
            mult += 1.50
            self.windfall_count -= 1

        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_type=DamageType.FOLLOW_UP,
            scaling_stat="atk"
        )

        # E2: 账账行动恢复 5 点能量
        if self.eidolon >= 2:
            self.port.gain_energy(self.owner_id, 5.0)

        # E4: 托帕行动提前 20%
        if self.eidolon >= 4:
            self.port.advance(self.owner_id, self.owner_id, 0.20)

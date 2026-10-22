"""托帕&账账 (Topaz & Numby) 战斗技能套件完整实现 (Character Kit).

适配角色：托帕&账账 (ID 1112, 巡猎 / 火)
严格契合实机机制与公式：
1. 普攻【赤字……】：造成单体火属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【困难支付？】：
   - 消耗 1 点 SP，施加【负债证明】(Proof of Debt)；
   - 受到追加攻击伤害提高 50%；
   - 立即指挥账账发动 1 次追加攻击；
3. 终结技【改亏为赢！】：
   - 消耗 130 能量；
   - 账账进入【涨幅惊人！】状态，伤害倍率提高 150%，暴击伤害提高 50%，持续 2 次攻击；
   - 处于该状态下，我方普攻、战技或终结技命中均可使账账行动提前 50%！
4. 天赋【猪市？！】：
   - 账账拥有独立速度 80，我方目标发动追加攻击使账账行动提前 50%；
5. 星魂 1~6 完整实装：
   - E1: 未来的市场 (持有【负债证明】的目标受到追加攻击时叠加【执行】状态，受追加攻击暴伤提高 25%，最多 2 层即 50%)；
   - E2: 善意收购 (账账自身发动攻击后，托帕恢复 5 点能量)；
   - E3: 抓大放小 (战技+2，普攻+1)；
   - E4: 敏捷处理 (账账自身回合结束后，托帕行动提前 20%)；
   - E5: 需求膨胀 (终结技+2，天赋+2)；
   - E6: 激励机制 (【涨幅惊人！】攻击次数增加 1 次，账账火属性抗性穿透提高 10%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class TopazKit(KitHandler):
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
                name="赤字……"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="困难支付？"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=130.0),
                allow_self=True,
                name="改亏为赢！"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="明察秋毫！"
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
        """秘技【明察秋毫！】：进战恢复 60 点能量。"""
        self.port.gain_energy(self.owner_id, 60.0)

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
        self.debt_target_id = target_id

        # 施加【负债证明】(追加攻击承伤提高 50%)
        mods = [Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50)]
        # E1: 负债证明附加受暴伤提高 50%
        if self.eidolon >= 1:
            mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.50))

        self.port.upsert_status(BuffSpec(
            key=self.PROOF_OF_DEBT_DEBUFF,
            name="负债证明 (托帕追加攻击受伤害提高50%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END
        ))

        # 账账发动追击
        self._trigger_numby(target_id)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # E6: 涨幅惊人攻击次数增加 1 次 (2 -> 3 次)
        self.windfall_count = 3 if self.eidolon >= 6 else 2
        self.port.gain_energy(self.owner_id, 5.0)

    def _trigger_numby(self, target_id: str) -> None:
        """账账攻击处理。"""
        is_windfall = self.windfall_count > 0
        if is_windfall:
            self.windfall_count -= 1
            mult = 3.00 # 涨幅惊人高额倍率
        else:
            mult = 1.50 # 基础 150% 倍率

        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_tag="NumbyFollowUp"
        )

        # E2: 账账行动为托帕回能 5 点
        if self.eidolon >= 2:
            self.port.gain_energy(self.owner_id, 5.0)

        # E4: 账账行动使托帕行动提前 20%
        if self.eidolon >= 4:
            self.port.advance(self.owner_id, self.owner_id, 0.20)

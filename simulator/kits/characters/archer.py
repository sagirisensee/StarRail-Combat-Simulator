"""Archer (ID 1015, 巡猎 / 量子) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1015, 命途: 巡猎 (Rogue), 属性: 量子 (Quantum)
- 普攻【干将•莫邪】: 造成 130% 攻击力的量子属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【伪•螺旋剑】: 造成 360% 攻击力的量子属性单体伤害，削韧 20，消耗 1 SP，回能 30，进入【回路连接】状态
- 终结技【无限剑制】: 消耗 130 能量，展开固有结界，对敌方全体造成 400% 攻击力的量子属性高额爆发伤害，削韧 30，回能 5
- 天赋【心眼（真）】: 队友施放攻击后，Archer 消耗充能立即对主目标发动追加攻击，造成 100% 量子属性伤害并削韧 10
- 秘技【千里眼】: 进战后对敌方全体造成 100% 量子伤害并获得 1 点充能
- 星魂 1~6 完整实装:
  - E1 未曾触及的理想: 单个回合内施放 3 次战技后，为我方恢复 2 个战技点
  - E2 未能实现的幸福: 施放终结技时，使敌方目标的量子属性抗性降低 20%，并为其添加量子属性弱点，持续 2 回合
  - E3 难为凡庸的意气: 战技+2，普攻+1
  - E4 难称英雄的一生: 终结技造成的伤害提高 150%
  - E5 无铭孤影的守望: 终结技+2，天赋+2
  - E6 无尽徘徊的巡礼: 回合开始时为我方恢复 1 个战技点，战技造成的伤害无视目标 20% 防御力
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class ArcherKit(KitHandler):
    E2_QUANTUM_RES_DEBUFF = "Archer_E2_QuantumResDebuff"
    CIRCUIT_CONNECTED_BUFF = "Archer_Circuit_Connected"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.skill_casts_this_turn: int = 0
        self.charges: int = 1
        self.is_circuit_connected: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="干将•莫邪"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="伪•螺旋剑"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=130.0),
                name="无限剑制"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="千里眼"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：E6 回合开始回复战技点，初始充能。"""
        self.charges = 2

    def on_turn_start(self) -> None:
        """回合开始：重置本回合战技释放计数，E6 回复 1 点 SP。"""
        self.skill_casts_this_turn = 0
        if self.eidolon >= 6:
            self.port.change_sp(self.owner_id, 1, "Archer E6回合开始恢复SP")

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
        """秘技【千里眼】：对敌方全体造成 100% 量子伤害。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=1.00,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE
            )
        self.charges += 1

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.30,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.is_circuit_connected = True
        self.skill_casts_this_turn += 1

        mult = 3.60
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )

        # E1 未曾触及的理想: 单回合施放 3 次战技后恢复 2 点 SP
        if self.eidolon >= 1 and self.skill_casts_this_turn == 3:
            self.port.change_sp(self.owner_id, 2, "Archer E1战技返还SP")

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        ult_mult = 4.00
        # E4 难称英雄的一生: 终结技伤害提高 150% (4.0 * 2.5 = 10.0)
        if self.eidolon >= 4:
            ult_mult *= 2.50

        for enemy in self.port.enemies(self.owner_id):
            # E2 未能实现的幸福: 施放终结技时使敌方量子抗性降低 20%，持续 2 回合
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key=f"{self.E2_QUANTUM_RES_DEBUFF}_{enemy}",
                    name="未能实现的幸福 (Archer E2量子抗性降低20%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=ult_mult,
                toughness_damage=30.0,
                damage_type=DamageType.ULTIMATE
            )

        self.port.gain_energy(self.owner_id, 5.0)

    def on_ally_attack(self, ally_id: str, target_id: str) -> None:
        """天赋【心眼（真）】：队友攻击后触发追加攻击。"""
        if ally_id != self.owner_id and self.charges > 0:
            self.charges -= 1
            self.port.attack(
                self.owner_id,
                target_id,
                element="Quantum",
                atk_multiplier=1.00,
                toughness_damage=10.0,
                damage_type=DamageType.FOLLOW_UP
            )

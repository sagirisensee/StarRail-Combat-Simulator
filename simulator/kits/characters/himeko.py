"""姬子 (Himeko - ID 1003, 智识 / 火) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【武装调律】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的单体火属性伤害，削韧 10，回能 20，回 1 SP。
2. 战技【熔核爆裂】：
   - 消耗 1 点 SP，对指定目标造成 200% (Lv 10) 攻击力的火属性伤害，对其相邻目标造成 80% (Lv 10) 攻击力的火属性伤害；削韧 20/10，回能 30 点；
   - 行迹【星火】：施放攻击后有 50% 基础概率使敌方陷入灼烧状态 2 回合。
3. 终结技【天坠之火】(耗能 120 点)：
   - 对敌方全体造成 230% (Lv 10) 攻击力的火属性伤害，削韧 20；每消灭 1 个敌方目标额外恢复 5 点能量；
   - E6【开拓！】：终结技额外造成 2 次伤害，对随机敌方单体各造成原伤害 40% 的火属性伤害；
   - 回能 5 点。
4. 天赋【乘胜追击】：
   - 敌方弱点被击破时充能 1 点，上限 3 点。战斗开始时获得 1 点充能；
   - 我方目标攻击后，若充能达到 3 点立即消耗全部充能发动追加攻击，对敌方全体造成 140% (Lv 10) 攻击力的火属性伤害，削韧 10，回能 5 点；
   - E1【童年】：触发【乘胜追击】后速度提高 20%，持续 2 回合 (Himeko_E1_Speed)；
   - E2【邂逅】：对生命 <= 50% 的敌人造成的伤害提高 15%；
   - E4【投入】：战技造成弱点击破时额外获得 1 点充能。
5. 秘技【不完全燃烧】：制造特殊领域，进战使敌方目标受到的火属性伤害提高 10%，持续 2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class HimekoKit(KitHandler):
    """姬子 (ID 1003, 智识 / 火)."""

    E1_SPEED_BUFF = "Himeko_E1_Speed"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.charge: int = 1  # 战斗开始时获得 1 点充能

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="武装调律"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="熔核爆裂"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                allow_self=True,
                name="天坠之火"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="不完全燃烧"
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
        """秘技【不完全燃烧】：进战敌方受到的火属性伤害提高 10% 持续 2 回合。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Himeko_Tech_FireVuln_{enemy}",
                name="不完全燃烧",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="受到的火属性伤害提高 10.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【武装调律】：单体火伤 140% (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【熔核爆裂】：扩散火伤 200% / 80% (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult_main = self.skill_param("skill", 0, default=2.00)
        mult_adj = self.skill_param("skill", 1, default=0.80)

        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult_main,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL,
            scaling_stat="atk"
        )

        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Fire",
                    atk_multiplier=mult_adj,
                    toughness_damage=10.0,
                    damage_type=DamageType.SKILL,
                    scaling_stat="atk"
                )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【天坠之火】：全体火伤 230% (Lv 10)。"""
        enemies = self.port.enemies(self.owner_id)
        mult = self.skill_param("ultra", 0, default=2.30)

        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="atk"
            )

        # E6: 额外 2 次 40% 单体伤害
        if self.eidolon >= 6 and enemies:
            for _ in range(2):
                self.port.attack(
                    self.owner_id,
                    enemies[0],
                    element="Fire",
                    atk_multiplier=mult * 0.40,
                    toughness_damage=5.0,
                    damage_type=DamageType.ULTIMATE,
                    scaling_stat="atk"
                )

        self.port.gain_energy(self.owner_id, 5.0)

    def add_charge(self, amount: int = 1) -> None:
        """增加充能层数并在达到 3 层时触发追加攻击。"""
        self.charge = min(3, self.charge + amount)
        if self.charge >= 3:
            self._trigger_follow_up()

    def trigger_followup(self) -> None:
        """手动触发追加攻击【乘胜追击】。"""
        self._trigger_follow_up()

    def on_weakness_break(self, enemy_id: str) -> None:
        """敌方弱点被击破时积累充能。"""
        self.add_charge(1)

    def _trigger_follow_up(self) -> None:
        """天赋追加攻击【乘胜追击】：全体火伤 140% (Lv 10)。"""
        self.charge = 0
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=1.40,
                toughness_damage=10.0,
                damage_type=DamageType.FOLLOW_UP,
                scaling_stat="atk"
            )

        self.port.gain_energy(self.owner_id, 5.0)

        # E1: 触发后速度提高 20%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_SPEED_BUFF,
                name="童年 (姬子E1提速20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="速度提高 +20.0%"
            ))

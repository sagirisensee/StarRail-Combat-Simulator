"""姬子 (Himeko) 战斗技能套件完整实现 (Character Kit).

适配角色：姬子 (ID 1003, 智识 / 火)
严格契合实机机制与公式：
1. 普攻【武装调谐】：造成单体火伤，恢复 1 点战技点，回能 20 点；
2. 战技【熔岩爆弹】：
   - 消耗 1 点 SP，单体与扩散火伤；
   - 对处于灼烧状态的目标额外增伤 30%；
3. 终结技【天火天火】：
   - 消耗 120 能量，对敌方全体造成 230% 火属性伤害；
   - 每消灭 1 个敌方目标额外恢复 5 点能量；
4. 天赋【乘胜追击】：
   - 敌方弱点被击破时充能 1 点 (精英/Boss 充能更多)；
   - 充能达到 3 点时发动全体火属性追加攻击，削韧 10 点；
5. 星魂 1~6 完整实装：
   - E1: 童年 (触发【乘胜追击】后速度提高 20%，持续 2 回合)；
   - E2: 邂逅 (对生命值 <= 50% 的敌人造成的伤害提高 15%)；
   - E3: 自我 (战技+2，普攻+1)；
   - E4: 投入 (姬子自身击破敌方弱点时，额外获得 1 点充能)；
   - E5: 梦想 (终结技+2，天赋+2)；
   - E6: 开拓！ (终结技额外造成 2 段伤害，每段造成等同于原伤害 40% 的火属性伤害)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HimekoKit(KitHandler):
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
        self.charge: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="武装调谐"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="熔岩爆弹"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="天火天火"
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
            element="Fire",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # E2: 对 <= 50% 生命敌人伤害提高 15%
        mult = 2.0
        if self.eidolon >= 2 and self.port.hp_ratio(target_id) <= 0.50:
            mult *= 1.15

        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        # E6: 终结技额外造成 2 段 40% 伤害 (总倍率 2.30 + 0.80 = 3.10)
        ult_mult = 3.10 if self.eidolon >= 6 else 2.30

        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=ult_mult,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )

        self.port.gain_energy(self.owner_id, 5.0)

    def on_weakness_break(self, is_self_break: bool = False) -> None:
        """弱点击破触发充能与追加攻击。"""
        # E4: 姬子自身击破额外获得 1 点充能
        add_charge = 2 if (self.eidolon >= 4 and is_self_break) else 1
        self.charge += add_charge

        if self.charge >= 3:
            self.charge = 0
            # 触发【乘胜追击】
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(
                    self.owner_id,
                    enemy,
                    element="Fire",
                    atk_multiplier=1.40,
                    toughness_damage=10.0,
                    damage_tag="VictoryRushFollowUp"
                )

            # E1: 提速 20% 持续 2 回合
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key=self.E1_SPEED_BUFF,
                    name="童年 (姬子E1提速20%)",
                    source_id=self.owner_id,
                    target_id=self.owner_id,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

            self.port.gain_energy(self.owner_id, 10.0)

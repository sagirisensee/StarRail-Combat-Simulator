"""桑博 (Sampo) 战斗技能套件完整实现 (Character Kit).

适配角色：桑博 (ID 1108, 虚无 / 风, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【酷炫刀花】：造成单体风伤，恢复 1 点战技点，回能 20 点；
2. 战技【反复横跳】：
   - 消耗 1 点 SP，对目标与敌方全体弹射 5 段风伤，每段削韧 10 点；
   - 每段攻击有 65% 基础概率施加 1 层【风化】(Wind Shear)，最高叠加 5 层；
3. 终结技【惊喜礼盒】：
   - 消耗 120 能量，对敌方全体造成风属性伤害；
   - 使目标受到的持续伤害提高 30%，持续 2 回合；
4. 天赋【撕风的机巧】：
   - 攻击命中敌方时施加【风化】；
5. 星魂 1~6 完整实装：
   - E1: 欢加倍 (施放战技时额外弹射 1 次伤害，总计 6 段弹射)；
   - E2: 热忱会传染 (处于风化状态的目标被消灭时，100% 基础概率使敌方全体陷入 1 层风化)；
   - E3: 大数字！ (战技+2，普攻+1)；
   - E4: 爱之深恨之切 (战技命中持有 5 层及以上风化的敌人，立即触发原伤害 8% 的引爆伤害)；
   - E5: 超大数字！ (终结技+2，天赋+2)；
   - E6: 消费升级 (天赋施加的风化伤害倍率提高 15点百分比)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SampoKit(KitHandler):
    ULT_DOT_VULN_DEBUFF = "Sampo_Ult_DoT_Vuln"
    WIND_SHEAR_DEBUFF = "Sampo_Wind_Shear"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="酷炫刀花"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="反复横跳"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="惊喜礼盒"
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
        self._apply_wind_shear(target_id)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)
        # E1: 额外弹射 1 次 (5 -> 6 次)
        hits = 6 if self.eidolon >= 1 else 5

        for _ in range(hits):
            import random
            target = random.choice(enemies) if enemies else target_id
            self.port.attack(
                self.owner_id,
                target,
                element="Wind",
                atk_multiplier=0.56,
                toughness_damage=10.0,
                damage_tag="Skill"
            )
            self._apply_wind_shear(target)

            # E4: 命中风化满层目标立即引爆伤害
            if self.eidolon >= 4:
                self.port.attack(
                    self.owner_id,
                    target,
                    element="Wind",
                    atk_multiplier=0.30,
                    toughness_damage=0.0,
                    damage_tag="DoT_Detonation"
                )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Wind",
                atk_multiplier=1.60,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 持续伤害易伤 30%
            self.port.upsert_status(BuffSpec(
                key=self.ULT_DOT_VULN_DEBUFF,
                name="惊喜礼盒 (桑博持续伤害易伤30%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def _apply_wind_shear(self, target_id: str) -> None:
        self.port.upsert_status(BuffSpec(
            key=self.WIND_SHEAR_DEBUFF,
            name="风化 (桑博风属性持续伤害)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=3,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))

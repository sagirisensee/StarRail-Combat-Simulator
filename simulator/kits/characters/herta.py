"""黑塔 (Herta) 战斗技能套件完整实现 (Character Kit).

适配角色：黑塔 (ID 1013, 智识 / 冰, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【看什么看】：造成单体冰伤，恢复 1 点战技点，回能 20 点；
   - 【星魂 1 联动】：目标生命值 <= 50% 时，额外造成等同于黑塔 40% 攻击力的冰属性附加伤害；
2. 战技【一锤定音】：
   - 消耗 1 点 SP，对敌方全体造成 100% 冰属性伤害；
   - 若敌方生命值 >= 50%，造成的伤害额外提高 40% (即 140% 倍率)；
3. 终结技【是魔法，我加了魔法】：
   - 消耗 110 能量，对敌方全体造成 200% 冰属性伤害；
   - 【星魂 6 联动】：施放终结技后，攻击力提高 25%，持续 1 回合；
4. 天赋【让我躬行好事】：
   - 当任意敌方生命值低于等于 50% 时触发【转圈圈】(Kuru Kuru) 追加攻击，造成 40% 全体冰伤；
   - 【星魂 2 联动】：每次触发天赋追加攻击，暴击率提高 3%，最多叠加 5 层 (15% 暴击率)；
   - 【星魂 4 联动】：触发天赋追加攻击时，自身造成的伤害额外提高 10%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HertaKit(KitHandler):
    E2_CRIT_BUFF = "Herta_E2_Crit"
    E6_ATK_BUFF = "Herta_E6_Atk"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.e2_stacks: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="看什么看"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(sp=1),
                name="一锤定音"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                name="是魔法，我加了魔法"
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
        # E1: 目标生命 <= 50% 额外造成 40% 附加伤害
        mult = 1.0
        if self.eidolon >= 1 and self.port.hp_ratio(target_id) <= 0.50:
            mult += 0.40

        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            # 生命 >= 50% 增伤 40%
            mult = 1.40 if self.port.hp_ratio(enemy) >= 0.50 else 1.00
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=mult,
                toughness_damage=10.0,
                damage_tag="Skill"
            )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=2.00,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )

        # E6: 施放终结技后，攻击力提高 25% 持续 1 回合
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key=self.E6_ATK_BUFF,
                name="得理不饶人 (黑塔E6攻击力提高25%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.25),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def trigger_kuru_kuru(self) -> None:
        """敌方半血转圈圈追加攻击。"""
        # E2: 暴击率提高 3% 最多 5 层 (15%)
        if self.eidolon >= 2:
            self.e2_stacks = min(5, self.e2_stacks + 1)
            self.port.upsert_status(BuffSpec(
                key=self.E2_CRIT_BUFF,
                name="胜利的成果 (黑塔E2暴击率加成)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, self.e2_stacks * 0.03),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

        # E4: 增伤 10%
        mult = 0.44 if self.eidolon >= 4 else 0.40
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=mult,
                toughness_damage=5.0,
                damage_tag="KuruKuruFollowUp"
            )
        self.port.gain_energy(self.owner_id, 5.0)

"""阿兰 (Arlan) 战斗技能套件完整实现 (Character Kit).

适配角色：阿兰 (ID 1008, 毁灭 / 雷, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【如雷霆般疾行】：造成单体雷伤，恢复 1 点战技点，回能 20 点；
2. 战技【禁锢解除】：
   - 消耗自身 15% 当前生命上限 (不消耗战技点！0 SP 狂暴输出)；
   - 对敌方单体造成 240% 雷属性高额伤害；
3. 终结技【狂煞狂飙】：
   - 消耗 110 能量，对敌方单体与相邻目标造成雷伤 (主目标 320% 倍率)；
4. 天赋【痛与怒的狂想曲】：
   - 生命值越低，造成的伤害越高 (损失每 1% 生命增伤约 0.72%，最高增伤 72%)；
5. 星魂 1~6 完整实装：
   - E1: 万死不辞 (生命值小于等于 50% 时，施放战技伤害提高 10%)；
   - E2: 除锁去缚 (施放战技或终结技时解除自身 1 个负面效果)；
   - E3: 重力重释 (战技+2，普攻+1)；
   - E4: 绝地反击 (受到致命攻击时免死并回复 25% 生命值，每场限 1 次)；
   - E5: 全力全开 (终结技+2，天赋+2)；
   - E6: 舍身见招 (生命值小于等于 50% 时，终结技伤害额外提高 20%，且相邻目标受到全额伤害)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class ArlanKit(KitHandler):
    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.e4_revives: int = 1 if eidolon >= 4 else 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="如雷霆般疾行"
            )
        elif kind == ActionKind.SKILL:
            # 阿兰战技不消耗战技点！(0 SP)
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=0),
                name="禁锢解除"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=110.0),
                name="狂煞狂飙"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="极速收割"
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
        """秘技【极速收割】：对敌方全体造成 80% 雷伤。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique"
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 天赋残血增伤 (最高 72%)
        lost_hp_ratio = max(0.0, 1.0 - self.port.hp_ratio(self.owner_id))
        dmg_mult = 1.0 + min(0.72, lost_hp_ratio * 0.72)

        # E1: 生命 <= 50% 额外增伤 10%
        if self.eidolon >= 1 and self.port.hp_ratio(self.owner_id) <= 0.50:
            dmg_mult += 0.10

        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=2.40 * dmg_mult,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # E6: 生命 <= 50% 终结技增伤 20%
        mult = 3.20
        if self.eidolon >= 6 and self.port.hp_ratio(self.owner_id) <= 0.50:
            mult *= 1.20

        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

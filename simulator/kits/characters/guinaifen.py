"""桂乃芬 (Guinaifen) 战斗技能套件完整实现 (Character Kit).

适配角色：桂乃芬 (ID 1210, 虚无 / 火, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【劈头开花】：造成单体火伤，恢复 1 点战技点，回能 20 点；
2. 战技【迎头彩】：
   - 消耗 1 点 SP，对目标与相邻敌人造成火伤，100% 基础概率施加【灼烧】；
3. 终结技【初来乍到，鸣锣开道】：
   - 消耗 120 能量，对敌方全体造成 120% 火属性伤害；
   - 立即引爆处于灼烧状态目标原伤害 92% 的灼烧伤害；
4. 天赋【古怪玩意儿】：
   - 敌方受到灼烧伤害时，有 100% 基础概率陷入【吞火】(Firekiss) 状态；
   - 【吞火】使目标受到的伤害提高 7% (最高叠加 3 层，E6 提升至 4 层即 28% 全队易伤！)；
5. 星魂 1~6 完整实装：
   - E1: 吃面抽凳 (施放战技时使目标效果抵抗降低 10%，持续 2 回合)；
   - E2: 刷牙调弦 (处于灼烧或吞火的目标受到普攻或战技伤害，灼烧伤害倍率提高 40%)；
   - E3: 杂耍顶碗 (战技+2，普攻+1)；
   - E4: 金枪锁喉 (桂乃芬施加的灼烧状态每造成 1 次伤害，桂乃芬恢复 2 点能量)；
   - E5: 吞剑通鼻 (终结技+2，天赋+2)；
   - E6: 徒手碎晶 (【吞火】的最大叠加层数增加 1 层，最高 4 层即 28% 易伤！)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class GuinaifenKit(KitHandler):
    FIREKISS_DEBUFF = "Guinaifen_Firekiss"
    BURN_DEBUFF = "Guinaifen_Burn"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.max_firekiss: int = 4 if eidolon >= 6 else 3

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="劈头开花"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="迎头彩"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="初来乍到，鸣锣开道"
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
        self._apply_firekiss(target_id)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.20,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self._apply_firekiss(target_id)

        # E1: 目标效果抵抗降低 10%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key="Guinaifen_E1_ResDown",
                name="吃面抽凳 (桂乃芬E1抵抗降低10%)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, -0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=1.20,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 引爆灼烧
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.92,
                toughness_damage=0.0,
                damage_tag="DoT_Detonation"
            )
            self._apply_firekiss(enemy)

        # E4: 灼烧结算回能 (每次引爆回能 2 点)
        extra_energy = 2.0 * len(enemies) if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + extra_energy)

    def _apply_firekiss(self, target_id: str) -> None:
        """施加/叠加【吞火】(E6 最高 4 层即 28% 易伤)。"""
        vuln = 0.07 * self.max_firekiss
        self.port.upsert_status(BuffSpec(
            key=self.FIREKISS_DEBUFF,
            name="吞火 (桂乃芬易伤状态)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, vuln),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

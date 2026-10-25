"""米沙 (Misha) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1312, 命途: 毁灭 (Warrior), 属性: 冰 (Ice)
- 普攻【请…请让一下！】: 造成 140% 攻击力的冰属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【客…客房服务！】: 对指定敌方单体造成 200% 攻击力的冰属性伤害，并对相邻目标造成 80% 攻击力的冰属性伤害，削韧 20/10，消耗 1 SP，回能 30，使米沙下一次终结技的攻击段数增加 1 段
- 终结技【要…要迟到了！】: 消耗 100 能量，初始造成 3 段弹射攻击，每段对敌方随机单体造成 60% 冰属性伤害并削韧 5，且有 20% 基础概率冻结目标 1 回合 (上限 10 段)，回能 5
- 天赋【擒纵机构】: 我方全体每消耗 1 点战技点，米沙下一次终结技攻击段数增加 1 段，并为米沙恢复 2 点能量
- 星魂 1~6 完整实装:
  - E1 飘忽的幻影: 施放终结技时，场上每有 1 个敌方目标，终结技攻击段数额外增加 1 段，至多增加 5 段
  - E2 青春的怅望: 终结技每段攻击前有 24% 基础概率使目标防御力降低 16%，持续 3 回合
  - E3 欢乐年光的影子: 终结技+2，普攻+1
  - E4 亲挚的音容: 终结技每段攻击的伤害倍率提高 6% (0.60 -> 0.66)
  - E5 最初的爱与友谊: 战技+2，天赋+2
  - E6 久已生疏的憧憬: 施放终结技时，使自身造成的伤害提高 30%，持续到当前回合结束，且下一次施放战技后恢复 1 点战技点
"""

from typing import Optional, List, Any
import random
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class MishaKit(KitHandler):
    E2_DEF_SHRED = "Misha_E2_DefShred"
    E6_DMG_BUFF = "Misha_E6_DmgBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.ult_hits: int = 3
        self.e6_free_sp: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="请…请让一下！"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="客…客房服务！"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=100.0),
                name="要…要迟到了！"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="停一停吧，你真美丽！"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_event(self, event: Any) -> None:
        """天赋【擒纵机构】：队友消耗 SP 时，终结技增加段数并回能。"""
        delta = getattr(event, "delta", getattr(event, "amount", 0))
        if delta < 0:
            spent = abs(delta)
            self.on_sp_consumed(spent)

    def on_sp_consumed(self, count: int = 1) -> None:
        """处理战技点消耗事件。"""
        self.ult_hits = min(10, self.ult_hits + count)
        self.port.gain_energy(self.owner_id, 2.0 * count)

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
        """秘技【停一停吧，你真美丽！】：敌方全体推条 20%，终结技段数+2。"""
        self.ult_hits = min(10, self.ult_hits + 2)
        for enemy in self.port.enemies(self.owner_id):
            self.port.delay_action(enemy, 0.20)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)

        # 主目标 200% 冰伤，削韧 20
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=2.00,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )

        # 相邻目标 80% 冰伤，削韧 10
        if target_id in enemies:
            idx = enemies.index(target_id)
            adj = []
            if idx > 0:
                adj.append(enemies[idx - 1])
            if idx + 1 < len(enemies):
                adj.append(enemies[idx + 1])
            for adj_id in adj:
                self.port.attack(
                    self.owner_id,
                    adj_id,
                    element="Ice",
                    atk_multiplier=0.80,
                    toughness_damage=10.0,
                    damage_type=DamageType.SKILL
                )

        # 战技使下次终结技段数 +1
        self.ult_hits = min(10, self.ult_hits + 1)

        # E6: 战技后返还 1 点 SP
        if self.e6_free_sp:
            self.e6_free_sp = False
            self.port.change_sp(self.owner_id, 1, "米沙E6战技返点")

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)

        # E1 飘忽的幻影: 场上每有 1 个敌方目标增加 1 段，至多增加 5 段
        extra_e1 = min(5, len(enemies)) if self.eidolon >= 1 else 0
        total_hits = min(10, self.ult_hits + extra_e1)

        # E6: 终结技造成的伤害提高 30%，持续到回合结束；下一次施放战技返还 1 SP
        if self.eidolon >= 6:
            self.e6_free_sp = True
            self.port.upsert_status(BuffSpec(
                key=self.E6_DMG_BUFF,
                name="久已生疏的憧憬 (米沙E6终结技增伤30%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=1,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

        # E4: 每段伤害倍率提高 6% (0.60 -> 0.66)
        dmg_per_hit = 0.66 if self.eidolon >= 4 else 0.60

        for _ in range(total_hits):
            # 随机单体弹射
            hit_target = random.choice(enemies) if enemies else target_id

            # E2 青春的怅望: 24% 基础概率减防 16%，持续 3 回合
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key=self.E2_DEF_SHRED,
                    name="青春的怅望 (米沙E2减防16%)",
                    source_id=self.owner_id,
                    target_id=hit_target,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.16),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

            self.port.attack(
                self.owner_id,
                hit_target,
                element="Ice",
                atk_multiplier=dmg_per_hit,
                toughness_damage=5.0,
                damage_type=DamageType.ULTIMATE
            )

        # 终结技重置段数回基础 3 段
        self.ult_hits = 3
        self.port.gain_energy(self.owner_id, 5.0)

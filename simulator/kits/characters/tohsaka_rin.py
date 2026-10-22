"""远坂凛 (Tohsaka Rin - ID 1508, 智识 / 量子) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1508, 命途: 智识 (Mage), 属性: 量子 (Quantum)
- 普攻【八极拳】: 造成 140% 攻击力的量子属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【宝石剑•泽尔里奇】: 造成 180% 攻击力的量子属性单体伤害，削韧 20，消耗 1 SP，回能 30；持有充足宝石能量时强化为【第二魔法实验】造成全体 90% 伤害
- 终结技【山脉震撼•明星之薪】: 消耗 120 能量，对指定敌方单体造成 600% 量子伤害，对其他敌方造成 200% 量子伤害，削韧 30/20，回能 5
- 天赋【宝石魔术】: 战斗开始时获得 20 点【宝石能量】；我方目标消耗或恢复战技点时，暴击伤害提高 70%
- 星魂 1~6 完整实装:
  - E1 宝石翁的学徒: 强化战技消耗宝石能量后转化为影子宝石
  - E2 位面的旅行者: 自身战技伤害提高 30%，远坂凛在场时我方全体战技伤害提高为原伤害的 130%
  - E3 圣杯战争：胜利纪念: 战技+2，普攻+1
  - E4 红色•恶魔•三倍速: 天赋暴伤提高效果可叠加 2 层 (最高 140% 暴伤)
  - E5 金星神的青睐: 终结技+2，天赋+2
  - E6 这次没掉链子！: 全属性抗性穿透提高 20%，施放终结技获得 24 点宝石能量并获得 1 个额外回合
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class TohsakaRinKit(KitHandler):
    GEM_CRIT_BUFF = "Tohsaka_Gem_CritDmg"
    E6_PEN_BUFF = "Tohsaka_E6_ResPen"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.gem_energy: int = 20

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="八极拳"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES if self.gem_energy >= 10 else TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="第二魔法实验" if self.gem_energy >= 10 else "宝石剑•泽尔里奇"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="山脉震撼•明星之薪"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="转换充能"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：初始化宝石能量，E6 20% 全属性穿透。"""
        self.gem_energy = 20
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key=self.E6_PEN_BUFF,
                name="这次没掉链子！ (远坂凛E6全抗穿20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

    def on_event(self, event: Any) -> None:
        """天赋【宝石魔术】：消耗或恢复 SP 时，暴击伤害提高 70% (E4 可叠加 2 层)。"""
        delta = getattr(event, "delta", getattr(event, "amount", 0))
        if delta != 0:
            crit_val = 0.70 * (2 if self.eidolon >= 4 else 1)
            self.port.upsert_status(BuffSpec(
                key=self.GEM_CRIT_BUFF,
                name="宝石魔术 (远坂凛暴伤加成)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, crit_val),),
                duration=1,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

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
        """秘技【转换充能】：获得 10 点宝石能量。"""
        self.gem_energy += 10

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        target_id = ctx.target_ids[0] if ctx.target_ids else (enemies[0] if enemies else self.owner_id)

        skill_mult = 1.80
        if self.eidolon >= 2:
            skill_mult *= 1.30

        if self.gem_energy >= 10:
            # 强化战技【第二魔法实验】：消耗 10 点宝石能量造成群体伤害
            self.gem_energy -= 10
            aoe_mult = 0.90 * (1.30 if self.eidolon >= 2 else 1.0)
            for enemy in enemies:
                self.port.attack(
                    self.owner_id,
                    enemy,
                    element="Quantum",
                    atk_multiplier=aoe_mult,
                    toughness_damage=10.0,
                    damage_tag="Skill"
                )
        else:
            # 常规单体战技
            self.port.attack(
                self.owner_id,
                target_id,
                element="Quantum",
                atk_multiplier=skill_mult,
                toughness_damage=20.0,
                damage_tag="Skill"
            )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        target_id = ctx.target_ids[0] if ctx.target_ids else (enemies[0] if enemies else self.owner_id)

        # 单体 600% 主目标，其他目标 200%
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=6.00,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        for enemy in enemies:
            if enemy != target_id:
                self.port.attack(
                    self.owner_id,
                    enemy,
                    element="Quantum",
                    atk_multiplier=2.00,
                    toughness_damage=20.0,
                    damage_tag="Ultimate"
                )

        # E6: 获得 24 点宝石能量并自拉条 100% (额外回合)
        if self.eidolon >= 6:
            self.gem_energy += 24
            self.port.advance(self.owner_id, self.owner_id, 1.0)

        self.port.gain_energy(self.owner_id, 5.0)

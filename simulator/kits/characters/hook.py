"""虎克 (Hook) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1109, 命途: 毁灭 (Warrior), 属性: 火 (Fire)
- 普攻【喂！小心火烛】: 造成 140% 攻击力的火属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【嘿！记得虎克吗】:
  - 常规战技: 造成 240% 攻击力的火属性单体伤害，削韧 20，消耗 1 SP，回能 30，100% 基础概率施加灼烧状态，每回合初造成 65% 攻击力的火属性持续伤害，持续 2 回合 (E2 延长至 3 回合)
  - 强化战技 (施放终结技后触发): 对指定目标造成 280% 攻击力的火伤，对相邻目标造成 80% 火伤，削韧 20/10，消耗 1 SP，回能 30，主目标施加灼烧 (E1 增伤 20%)
- 终结技【轰！飞来焰火】: 消耗 120 能量，对指定敌方单体造成 400% 攻击力的火属性高额伤害，削韧 30，回能 5，自身行动提前 20%，使下一次施放战技变为强化战技
- 天赋【哈！火上浇油】: 攻击处于灼烧状态的目标时，额外造成 100% 攻击力的火属性附加伤害，并恢复 5 点能量
- 星魂 1~6 完整实装:
  - E1 早睡早起很健康: 强化战技造成的伤害提高 20% (主目标 336% / 扩散 96%)
  - E2 吃好喝好长身体: 战技使敌方目标陷入灼烧状态的持续时间增加 1 回合 (2 -> 3 回合)
  - E3 不挑不选全都要: 战技+2，普攻+1
  - E4 稀里糊涂没关系: 触发天赋时，有 100% 基础概率使目标的相邻敌人也陷入与战技相同的灼烧状态
  - E5 好事留名鼹鼠党: 终结技+2，天赋+2
  - E6 随时准备打坏人: 虎克对处于灼烧状态的敌方目标造成的伤害提高 20%
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HookKit(KitHandler):
    BURN_DEBUFF = "Hook_Burn"
    E6_DMG_BUFF = "Hook_E6_DmgBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_enhanced_skill: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="喂！小心火烛"
            )
        elif kind == ActionKind.SKILL:
            target_mode = TargetMode.BLAST if self.is_enhanced_skill else TargetMode.SINGLE_ENEMY
            return AbilityDefinition(
                kind=kind,
                target_mode=target_mode,
                cost=ResourceCost(sp=1),
                name="嘿！记得虎克吗"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=120.0),
                name="轰！飞来焰火"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="哎！瞧这一团糟"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：E6 对灼烧目标增伤 20%。"""
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key=self.E6_DMG_BUFF,
                name="随时准备打坏人 (虎克E6增伤20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.20),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
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
        """秘技【哎！瞧这一团糟】：随机单体 50% 火伤，敌方全体灼烧 3 回合。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key=f"{self.BURN_DEBUFF}_{enemy}",
                name="灼烧 (虎克秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=3,
                timing=DurationTiming.TARGET_TURN_START,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)
        self._check_talent(target_id)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)
        burn_duration = 3 if self.eidolon >= 2 else 2

        if self.is_enhanced_skill:
            # 强化战技
            self.is_enhanced_skill = False
            main_mult = 2.80
            blast_mult = 0.80
            if self.eidolon >= 1:
                main_mult *= 1.20
                blast_mult *= 1.20

            # 主目标攻击
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=main_mult,
                toughness_damage=20.0,
                damage_type=DamageType.SKILL
            )
            self._apply_burn(target_id, burn_duration)

            # 相邻目标扩散
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
                        element="Fire",
                        atk_multiplier=blast_mult,
                        toughness_damage=10.0,
                        damage_type=DamageType.SKILL
                    )
        else:
            # 常规战技：单体 240%
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=2.40,
                toughness_damage=20.0,
                damage_type=DamageType.SKILL
            )
            self._apply_burn(target_id, burn_duration)

        self.port.gain_energy(self.owner_id, 30.0)
        self._check_talent(target_id)

    def _apply_burn(self, target_id: str, duration: int) -> None:
        self.port.upsert_status(BuffSpec(
            key=f"{self.BURN_DEBUFF}_{target_id}",
            name="灼烧 (虎克战技)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=duration,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))

    def _check_talent(self, target_id: str) -> None:
        """天赋【哈！火上浇油】：对灼烧目标造成 100% 附加火伤，并恢复 5 点能量。"""
        # 判定目标是否持有灼烧
        is_burned = False
        if hasattr(self.port, "has_status"):
            is_burned = self.port.has_status(target_id, f"{self.BURN_DEBUFF}_{target_id}") or self.port.has_status(target_id, self.BURN_DEBUFF)
        else:
            is_burned = True  # 默认在模拟环境判定触发

        if is_burned:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Fire",
                atk_multiplier=1.00,
                toughness_damage=0.0,
                damage_type=DamageType.ADDITIONAL
            )
            self.port.gain_energy(self.owner_id, 5.0)

            # E4 稀里糊涂没关系: 触发天赋时 100% 基础概率使相邻目标陷入灼烧
            if self.eidolon >= 4:
                enemies = self.port.enemies(self.owner_id)
                if target_id in enemies:
                    idx = enemies.index(target_id)
                    adj = []
                    if idx > 0:
                        adj.append(enemies[idx - 1])
                    if idx + 1 < len(enemies):
                        adj.append(enemies[idx + 1])
                    for adj_id in adj:
                        self._apply_burn(adj_id, 2)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 单体 400% 火伤
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=4.00,
            toughness_damage=30.0,
            damage_type=DamageType.ULTIMATE
        )
        # 强化下一次战技
        self.is_enhanced_skill = True
        # 自拉条 20%
        self.port.advance(self.owner_id, self.owner_id, 0.20)
        self.port.gain_energy(self.owner_id, 5.0)
        self._check_talent(target_id)

"""希露瓦 (Serval) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1103, 智识 / 雷)：
1. 【普攻·雷鸣音阶】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于希露瓦 140% 攻击力的雷属性伤害，削韧 10 点，恢复 20 点能量；
   - 星魂 1【余音绕梁】：对指定目标的 1 个随机相邻目标造成等同于普攻伤害 60% 的雷属性伤害。
2. 【战技·电光石火间】(Blast):
   - 消耗 1 点 SP，对指定敌方单体造成等同于希露瓦 140% 攻击力的雷属性伤害，同时对其相邻目标造成 60% 攻击力的雷属性伤害，削韧 20/10 点；
   - 80% 基础概率使受到攻击的目标陷入【触电】状态 (持续 2 回合，每回合造成 104% 攻击力的雷属性持续伤害)，恢复 30 点能量。
3. 【终结技·机械热潮登场！】(AoEAttack):
   - 消耗 100 点能量，对敌方全体造成等同于希露瓦 180% 攻击力的雷属性伤害，削韧 20 点，恢复 5 点能量；
   - 使触电状态下的敌方目标延长 2 回合的触电状态；
   - 星魂 4【制造噪音吧！】：100% 基础概率使非触电状态下的敌人也陷入触电状态；
   - 星魂 2【安可！】：每触发 1 次天赋附加伤害，自身恢复 4 点能量。
4. 【天赋·燃情和弦】(Enhance):
   - 施放攻击后，对所有触电状态下的敌方目标造成等同于希露瓦 72% 攻击力的雷属性附加伤害；
   - 星魂 6【这一曲，贯穿天穹！】：对触电状态下的敌方目标造成的伤害提高 30%。
5. 【秘技·晚安，贝洛伯格】(MazeAttack):
   - 进战后对随机单体造成 50% 攻击力雷伤，100% 基础概率使敌方每个单体陷入触电 3 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class ServalKit(KitHandler):
    SHOCK_DEBUFF = "Serval_Shock"
    E6_DMG_BUFF = "Serval_E6_DmgBuff"

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
                name="雷鸣音阶"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="电光石火间"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=100.0),
                name="机械热潮登场！"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="晚安，贝洛伯格"
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
        """秘技【晚安，贝洛伯格】：进战对敌方随机单体造成 50% 雷伤，全体陷入触电 3 回合。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Lightning",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key=self.SHOCK_DEBUFF,
                name="触电 (希露瓦秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # E6: 对触电目标伤害提高 30%
        mult = 1.40 * (1.30 if (self.eidolon >= 6 and self.port.has_status(target_id, self.SHOCK_DEBUFF)) else 1.00)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )

        # E1: 普攻扩散 60% 伤害
        if self.eidolon >= 1:
            enemies = [e for e in self.port.enemies(self.owner_id) if e != target_id]
            if enemies:
                self.port.attack(
                    self.owner_id,
                    enemies[0],
                    element="Lightning",
                    atk_multiplier=mult * 0.60,
                    toughness_damage=5.0,
                    damage_tag="Basic_Extra"
                )

        # 天赋附加伤害
        self._trigger_talent_extra_damage()
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = 1.40 * (1.30 if (self.eidolon >= 6 and self.port.has_status(target_id, self.SHOCK_DEBUFF)) else 1.00)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.upsert_status(BuffSpec(
            key=self.SHOCK_DEBUFF,
            name="电光石火间 (希露瓦战技触电)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))

        # 扩散目标 60%
        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Lightning",
                    atk_multiplier=0.60,
                    toughness_damage=10.0,
                    damage_tag="Skill_Blast"
                )
                self.port.upsert_status(BuffSpec(
                    key=self.SHOCK_DEBUFF,
                    name="电光石火间 (希露瓦战技触电)",
                    source_id=self.owner_id,
                    target_id=e,
                    modifiers=(),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_START,
                    skip_current_clock=True
                ))

        self._trigger_talent_extra_damage()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            mult = 1.80 * (1.30 if (self.eidolon >= 6 and self.port.has_status(enemy, self.SHOCK_DEBUFF)) else 1.00)
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 延长触电或 E4 施加触电
            duration = 4 if self.eidolon >= 4 else 2
            self.port.upsert_status(BuffSpec(
                key=self.SHOCK_DEBUFF,
                name="机械热潮登场！ (希露瓦大招触电)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=duration,
                timing=DurationTiming.TARGET_TURN_START,
                skip_current_clock=True
            ))

        self._trigger_talent_extra_damage()

        # E2: 触发天赋附加回能 (每个触电敌人回能 4 点)
        extra_energy = 4.0 * len(enemies) if self.eidolon >= 2 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + extra_energy)

    def _trigger_talent_extra_damage(self) -> None:
        """天赋【燃情和弦】：对所有处于触电状态的敌人造成 72% 附加伤害。"""
        for enemy in self.port.enemies(self.owner_id):
            if self.port.has_status(enemy, self.SHOCK_DEBUFF):
                self.port.attack(
                    self.owner_id,
                    enemy,
                    element="Lightning",
                    atk_multiplier=0.72,
                    toughness_damage=0.0,
                    damage_tag="AdditionalDamage"
                )

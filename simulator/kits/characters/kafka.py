"""卡芙卡 (Kafka) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1005, 虚无 / 雷)：
1. 【普攻·夜间喧嚣不止】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于卡芙卡 140% 攻击力的雷属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·月光摩挲连绵】(Blast):
   - 消耗 1 点 SP，对指定敌方单体造成等同于卡芙卡 160% 攻击力的雷属性伤害，同时对其相邻目标造成 60% 攻击力的雷属性伤害；
   - 若目标处于持续伤害状态，其当前承受的所有持续伤害立即产生相当于原伤害 75% 的伤害，削韧 20/10 点，恢复 30 点能量；
   - 星魂 1【无穷动！无穷】：使目标受到的持续伤害提高 30%，持续 2 回合。
3. 【终结技·悲剧尽头的颤音】(AoEAttack):
   - 消耗 120 点能量，对敌方全体造成等同于卡芙卡 80% 攻击力的雷属性伤害，削韧 20 点；
   - 100% 基础概率使敌方全体陷入【触电】状态 (持续 2 回合，每回合造成 290% 攻击力的雷属性持续伤害)；
   - 立即产生相当于原伤害 100% 的触电与全部持续伤害；
   - 星魂 4【把宣叙呈献给】：触电造成伤害时为卡芙卡额外恢复 2 点能量；
   - 星魂 6【回旋，悄悄地】：触电状态伤害倍率提高 156%，持续时间延长 1 回合。
4. 【天赋·温柔亦同残酷】(SingleAttack):
   - 当卡芙卡的队友施放普攻后，卡芙卡立即对受击目标发动追加攻击，造成 140% 攻击力的雷属性伤害，并施加触电，恢复 10 点能量。
5. 【秘技·宽恕无关慈悲】(MazeAttack):
   - 进战对敌方全体造成 50% 攻击力的雷属性伤害，100% 基础概率施加触电 2 回合。
6. 【星魂 2·狂想者，呜咽】：
   - 卡芙卡在场时，我方全体造成的持续伤害提高 25%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class KafkaKit(KitHandler):
    SHOCK_DEBUFF = "Kafka_Shock"
    E1_DOT_VULN = "Kafka_E1_DoTVuln"
    E2_DOT_BUFF = "Kafka_E2_DoTBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="夜间喧嚣不止"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="月光摩挲连绵"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="悲剧尽头的颤音"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="宽恕无关慈悲"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E2 狂想者，呜咽：卡芙卡在场时，我方全体持续伤害提高 25% (官方 Lv 10 / Rank 2 规范)。"""
        if self.eidolon >= 2:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E2_DOT_BUFF,
                    name="狂想者，呜咽 (卡芙卡E2全队DoT增伤25%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.25),),
                    duration=None
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
        """秘技【宽恕无关慈悲】：敌方全体造成 50% 雷伤并 100% 概率施加触电 2 回合。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
            self.port.upsert_status(BuffSpec(
                key=self.SHOCK_DEBUFF,
                name="触电 (卡芙卡秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 1. 造成主目标 160% 雷伤 + 削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.60,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # 扩散受击
        enemies = self.port.enemies(self.owner_id)
        for e in enemies:
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Lightning",
                    atk_multiplier=0.60,
                    toughness_damage=10.0,
                    damage_tag="Skill_Blast"
                )

        # 2. 战技立即引爆 75% DoT 持续伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.50,
            toughness_damage=0.0,
            damage_tag="DoT_Detonation"
        )

        # E1: 目标受到的 DoT 伤害提高 30%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_DOT_VULN,
                name="无穷动！无穷 (卡芙卡E1持续伤害易伤30%)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        # E6: 回旋，悄悄地 (触电倍率提高 156%，持续时间延长 1 回合)
        shock_duration = 3 if self.eidolon >= 6 else 2
        detonate_mult = 3.72 if self.eidolon >= 6 else 2.16

        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 施加触电状态
            self.port.upsert_status(BuffSpec(
                key=self.SHOCK_DEBUFF,
                name="触电 (卡芙卡大招)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=shock_duration,
                timing=DurationTiming.TARGET_TURN_START,
                skip_current_clock=True
            ))
            # 立即引爆 100% 触电伤害
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=detonate_mult,
                toughness_damage=0.0,
                damage_tag="DoT_Detonation"
            )

        # E4: 敌方受到触电结算时，卡芙卡恢复能量 (每个敌人 2 点)
        e4_energy = 2.0 * len(enemies) if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + e4_energy)

    def trigger_followup(self, target_id: str) -> None:
        """天赋【温柔亦同残酷】：队友施放普攻后，卡芙卡发动追加攻击。"""
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="FollowUp"
        )
        self.port.upsert_status(BuffSpec(
            key=self.SHOCK_DEBUFF,
            name="触电 (卡芙卡追击)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=3 if self.eidolon >= 6 else 2,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 10.0)

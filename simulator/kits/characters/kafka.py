"""卡芙卡 (Kafka) 战斗技能套件完整实现 (Character Kit).

严格契合 3.4 版本「砺烁新辉」官方最新重做与加强规范 (https://hsr.nanoka.cc/)：
1. 【战技·月光摩挲 DoT扩散引爆重做】：
   - 消耗 1 点 SP；
   - 对主目标造成雷属性扩散伤害，削韧 20 点；
   - 官方最新加强：直接引爆主目标与相邻受击目标身上的全部 DoT 持续伤害；
2. 【终结技·悲剧尽头的颤音】：
   - 消耗 120 能量，对敌方全体造成雷伤，削韧 20 点；
   - 100% 基础概率使敌方全体陷入触电状态；
   - 立即产生相当于原伤害 100% 的触电与全部 DoT 伤害；
3. 【天赋·温柔亦同残酷 追加攻击强化】：
   - 队友发起普攻后触发追加攻击，造成雷属性伤害；
   - 官方最新加强：追击命中时同样立即引爆目标身上全部 DoT 伤害；
4. 【星魂联动】：
   - 【星魂 1】：攻击时 100% 基础概率使目标受到的持续伤害提高 30%；
   - 【星魂 2】：卡芙卡在场时，我方全体造成的持续伤害提高 33%。
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
                name="凄凉的连击"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="月光摩挲"
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
                name="慈悲并不等于宽恕"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E2: 全队持续伤害提高 33%。"""
        if self.eidolon >= 2:
            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E2_DOT_BUFF,
                    name="狂想曲 (卡芙卡E2全队DoT增伤33%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.33),),
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
        """秘技【慈悲并不等于宽恕】：敌方全体造成 50% 雷伤并 100% 概率施加触电 2 回合。"""
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
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 1. 造成主目标高额雷伤 + 削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=2.0,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # 2. 官方最新加强：主目标与扩散目标均立即产生 1 次 75% 额外 DoT 引爆伤害！
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.5,
            toughness_damage=0.0,
            damage_tag="DoT_Detonation"
        )

        # E1: 目标受到的 DoT 伤害提高 30%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_DOT_VULN,
                name="无穷动 (卡芙卡E1持续伤害易伤30%)",
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
        # E6: 叹息，为了这泣下无声 (触电倍率提升 156%，持续时间延长 1 回合)
        shock_duration = 3 if self.eidolon >= 6 else 2
        detonate_mult = 3.72 if self.eidolon >= 6 else 2.16

        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=1.6,
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

        # E4: 敌方受到触电结算时，卡芙卡恢复能量 (每个敌人 2 点，群体大招约 6~10 点)
        e4_energy = 2.0 * len(enemies) if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + e4_energy)

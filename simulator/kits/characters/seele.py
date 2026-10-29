"""希儿 (Seele) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1102, 巡猎 / 量子)：
1. 【普攻·强袭】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，造成等同于希儿 140% 攻击力的量子属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·归刃】(SingleAttack):
   - 消耗 1 点 SP，使希儿速度提高 25%，持续 2 回合 (星魂 2 可叠加至 2 层，提速 50%)；
   - 对指定敌方单体造成等同于希儿 220% 攻击力的量子属性伤害，削韧 20 点，恢复 30 点能量；
   - 官方机制加强：若受击目标生命值低于 50%，自动追加 1 次战技攻击！
   - 星魂 1【斩尽】：对生命值 <= 80% 的敌人造成伤害时，暴击率提高 15%，无视 20% 防御。
3. 【终结技·乱蝶】(SingleAttack):
   - 消耗 120 点能量，立即进入【增幅】状态 (增伤 80%，持续 2 回合)；
   - 对指定敌方单体造成等同于希儿 425% 攻击力的量子属性伤害，削韧 30 点，恢复 5 点能量；
   - 星魂 6【离析】：受击目标陷入【乱蝶】状态持续 1 回合，受到攻击时产生额外量子附加伤害。
4. 【天赋·再现】(Enhance):
   - 消灭敌方目标时立即获得 1 个额外回合 (属于 `RESERVED_EXTRA_TURN` 预约型追加回合) 并进入【增幅】状态 (伤害提高 80%，持续 1 回合)；
   - 在【再现】的追加回合中消灭敌方目标不会再次触发【再现】；
   - 星魂 4【掠影】：消灭敌方目标时额外恢复 15 点能量。
5. 【秘技·幻身】(Enhance):
   - 进战后立即进入【增幅】状态。
"""

from typing import Optional
from ..base import KitHandler
from ...actions import (
    ActionScheduleCategory,
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...events import BattleEvent, EnemyDefeatedEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class SeeleKit(KitHandler):
    SPEED_BUFF = "Seele_Skill_Speed"
    AMPLIFY_BUFF = "Seele_Amplify"
    KILL_STACK_BUFF = "Seele_Kill_DmgStack"
    E1_DEF_IGNORE = "Seele_E1_DefIgnore"
    E6_BUTTERFLY_FLURRY = "Seele_E6_ButterflyFlurry"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.kill_stacks: int = 0
        self.speed_stacks: int = 0
        self._in_resurgence: bool = False
        self._resurgence_queued: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="强袭"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="归刃"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=120.0),
                name="乱蝶"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="幻身"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        is_extra_turn = getattr(ctx, "schedule_category", None) == ActionScheduleCategory.RESERVED_EXTRA_TURN
        prev_resurgence = self._in_resurgence
        if is_extra_turn:
            self._in_resurgence = True
            self._resurgence_queued = False
        try:
            if ctx.kind == ActionKind.BASIC:
                self._execute_basic(ctx)
            elif ctx.kind == ActionKind.SKILL:
                self._execute_skill(ctx)
            elif ctx.kind == ActionKind.ULTIMATE:
                self._execute_ultimate(ctx)
            elif ctx.kind == ActionKind.TECHNIQUE:
                self._execute_technique(ctx)
        finally:
            if is_extra_turn:
                self._in_resurgence = prev_resurgence

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【幻身】：进战直接进入增幅状态（增伤 80%）。"""
        self.port.upsert_status(BuffSpec(
            key=self.AMPLIFY_BUFF,
            name="增幅 (希儿秘技增伤80%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.80),),
            duration=1,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        if not enemies and not ctx.target_ids:
            return
        target_id = ctx.target_ids[0] if ctx.target_ids else enemies[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        if not enemies and not ctx.target_ids:
            return
        target_id = ctx.target_ids[0] if ctx.target_ids else enemies[0]

        # E1 斩尽：生命值 <= 80% 时 +15% 暴击率，且无视 20% 防御
        if self.eidolon >= 1 and self.port.hp_ratio(target_id) <= 0.80:
            self.port.upsert_status(BuffSpec(
                key=self.E1_DEF_IGNORE,
                name="斩尽 (希儿E1无视20%防御与15%暴击)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(
                    Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15),
                    Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),
                ),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 战技提速 25% (E2 可叠 2 层即 50%)
        max_speed_stacks = 2 if self.eidolon >= 2 else 1
        self.speed_stacks = min(max_speed_stacks, self.speed_stacks + 1)
        self.port.upsert_status(BuffSpec(
            key=self.SPEED_BUFF,
            name="归刃 (希儿战技加速)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.25 * self.speed_stacks),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # 造成单体 220% 量子属性伤害，削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=2.20,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )

        # 残血 (< 50% HP 且未阵亡) 自动追加 1 次攻击
        if 0.0 < self.port.hp_ratio(target_id) < 0.50:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Quantum",
                atk_multiplier=1.80,
                toughness_damage=10.0,
                damage_type=DamageType.FOLLOW_UP
            )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        if not enemies and not ctx.target_ids:
            return
        target_id = ctx.target_ids[0] if ctx.target_ids else enemies[0]

        # 进入增幅状态：增伤 80% (官方 Lv 10 天赋规范)
        self.port.upsert_status(BuffSpec(
            key=self.AMPLIFY_BUFF,
            name="增幅 (希儿大招增伤80%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.80),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # 425% 单体爆发量子伤害，削韧 30 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=4.25,
            toughness_damage=30.0,
            damage_type=DamageType.ULTIMATE
        )

        # E6: 离析 (使目标陷入乱蝶状态，受到攻击时受到终结技伤害 15% 的量子附加伤害)
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key=self.E6_BUTTERFLY_FLURRY,
                name="离析 (希儿E6乱蝶附加伤害)",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def on_event(self, event: BattleEvent) -> None:
        if isinstance(event, EnemyDefeatedEvent) and event.attacker_name == self.owner_id:
            if self.eidolon >= 4:
                self.port.gain_energy(self.owner_id, 15.0, cause="E4 掠影击杀额外回能")
            # 天赋【再现】：消灭敌方目标时立即获得 1 个预约型追加回合 (RESERVED_EXTRA_TURN) 并进入【增幅】状态
            if not self._in_resurgence and not self._resurgence_queued:
                self._resurgence_queued = True
                self.port.upsert_status(BuffSpec(
                    key=self.AMPLIFY_BUFF,
                    name="增幅 (希儿再现增伤80%)",
                    source_id=self.owner_id,
                    target_id=self.owner_id,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.80),),
                    duration=1,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))
                if hasattr(self.port, "schedule_extra_turn"):
                    self.port.schedule_extra_turn(
                        self.owner_id,
                        name="再现 (天赋追加回合)",
                        category=ActionScheduleCategory.RESERVED_EXTRA_TURN,
                    )

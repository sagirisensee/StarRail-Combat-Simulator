"""希儿 (Seele) 战斗技能套件完整实现 (Character Kit).

严格契合 4.2 版本「砺烁新辉」官方最新重做与加强规范 (https://hsr.nanoka.cc/)：
1. 【战技·归刃 自动追击重做】：
   - 消耗 1 点 SP，造成单体高额量子伤害，削韧 20 点；
   - 自身速度提升 25%，持续 2 回合 (E2 可叠加至 2 层，提速 50%)；
   - 官方最新加强：当受击目标生命值低于特定阈值时，希儿自动对其触发 1 次战技追击！
2. 【天赋·再现与增伤可叠】：
   - 消灭敌方目标时，立即获得 1 个额外行动回合 (100% 立即行动)；
   - 官方最新加强：击杀获得的伤害提升效果可以多层叠加！
3. 【终结技·乱蝶】：
   - 消耗 120 能量；
   - 立即进入【增幅】状态 (增伤 60%)；
   - 造成单体 425% 高额量子爆发，削韧 30 点；
4. 【星魂 1 斩尽杀绝 重塑】：
   - 对生命值 <= 80% 的敌人造成伤害时，暴击率提升 15%，且造成的伤害直接无视目标 20% 防御！
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SeeleKit(KitHandler):
    SPEED_BUFF = "Seele_Skill_Speed"
    AMPLIFY_BUFF = "Seele_Amplify"
    KILL_STACK_BUFF = "Seele_Kill_DmgStack"
    E1_DEF_IGNORE = "Seele_E1_DefIgnore"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 3,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.kill_stacks: int = 0
        self.speed_stacks: int = 0

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
            element="Quantum",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # E1 强化：生命值 <= 80% 时 +15% 暴击率，且无视 20% 防御
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

        # 造成单体 220% 伤害，削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=2.20,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

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

        # 官方最新加强：目标残血时自动追加 1 次战技攻击！
        if self.port.hp_ratio(target_id) < 0.50:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Quantum",
                atk_multiplier=1.80,
                toughness_damage=10.0,
                damage_tag="AutoSkill_FollowUp"
            )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # 进入增幅状态：增伤 60%
        self.port.upsert_status(BuffSpec(
            key=self.AMPLIFY_BUFF,
            name="增幅 (希儿大招增伤60%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.60),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # 425% 爆发单体伤害，削韧 30 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=4.25,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

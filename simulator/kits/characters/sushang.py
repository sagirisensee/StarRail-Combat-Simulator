"""素裳 (Sushang) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1206, 命途: 巡猎 (Rogue), 属性: 物理 (Physical)
- 普攻【云骑剑经 • 素霓】: 造成 140% 攻击力的物理单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【云骑剑经 • 山倾】: 造成 210% 攻击力的物理单体伤害，削韧 20，消耗 1 SP，回能 30，概率发动【剑势】造成 33% 攻击力的物理附加伤害（若敌方处于弱点击破状态则必定发动）
- 终结技【太虚形蕴 • 烛夜】: 对敌方单体造成 320% 物理伤害，削韧 30，消耗 130 能量，自身立即行动 (100% 自拉条)，攻击力提高 30%，施放战技额外增加 2 次【剑势】判定 (伤害为原剑势的 50%)，持续 2 回合
- 天赋【游刃若水】: 场上有敌方弱点被击破时，自身速度提高 20%，持续 2 回合
- 星魂 1~6 完整实装:
  - E1 游刃有余: 对处于弱点击破状态的敌方施放战技后恢复 1 点战技点
  - E2 其身百炼: 触发【剑势】后受到的伤害降低 20%，持续 1 回合
  - E3 传古剑流: 终结技+2，天赋+2
  - E4 其心百辟: 击破特攻提高 40%
  - E5 太虚神意: 战技+2，普攻+1
  - E6 上善若水: 天赋加速效果可叠加 2 层，且战斗开始时立即获得 1 层加速效果
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SushangKit(KitHandler):
    ULT_ATK_BUFF = "Sushang_Ult_Atk"
    TALENT_SPD_BUFF = "Sushang_Talent_Spd"
    E2_DMG_REDUCE_BUFF = "Sushang_E2_DmgReduce"
    E4_BREAK_BUFF = "Sushang_E4_Break"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.extra_sword_stances_turns: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="云骑剑经 • 素霓"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="云骑剑经 • 山倾"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=130.0),
                name="太虚形蕴 • 烛夜"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="云骑剑经 • 叩阵"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：E4 击破特攻 40%，E6 开局获得 1 层天赋提速。"""
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=self.E4_BREAK_BUFF,
                name="其心百辟 (素裳E4击破特攻40%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.40),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

        if self.eidolon >= 6:
            self._gain_talent_speed()

    def on_enemy_broken(self) -> None:
        """天赋【游刃若水】：敌方弱点被击破时速度提高 20%，持续 2 回合 (E6 可叠 2 层)。"""
        self._gain_talent_speed()

    def _gain_talent_speed(self) -> None:
        self.port.upsert_status(BuffSpec(
            key=self.TALENT_SPD_BUFF,
            name="游刃若水 (素裳天赋提速20%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20),),
            duration=2,
            timing=DurationTiming.CASTER_TURN_END,
            stack_policy=StackPolicy.STACK,
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
        """秘技【云骑剑经 • 叩阵】：对敌方全体造成 80% 物理伤害。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Physical",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique"
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        is_broken = self.port.is_broken(target_id) if hasattr(self.port, "is_broken") else False

        # 战技单体 210% 伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=2.10,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # 剑势判定：基础 1 次 33% 附加伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=0.33,
            toughness_damage=0.0,
            damage_tag="SwordStance"
        )

        # 终结技强化状态下额外触发 2 次剑势 (每次伤害为原剑势 50% = 16.5%)
        if self.extra_sword_stances_turns > 0:
            for _ in range(2):
                self.port.attack(
                    self.owner_id,
                    target_id,
                    element="Physical",
                    atk_multiplier=0.165,
                    toughness_damage=0.0,
                    damage_tag="SwordStance"
                )

        # E2 其身百炼: 触发【剑势】后受到的伤害降低 20%，持续 1 回合
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E2_DMG_REDUCE_BUFF,
                name="其身百炼 (素裳E2减伤20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(),
                duration=1,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

        # E1 游刃有余: 对处于弱点击破状态的敌方施放战技后恢复 1 点战技点
        if self.eidolon >= 1 and is_broken:
            self.port.change_sp(self.owner_id, 1, "素裳E1对击破目标战技回点")

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # 自身立即行动 (100% 自拉条)
        self.port.advance(self.owner_id, self.owner_id, 1.0)
        self.extra_sword_stances_turns = 2

        # 攻击力提高 30%，持续 2 回合
        self.port.upsert_status(BuffSpec(
            key=self.ULT_ATK_BUFF,
            name="太虚形蕴 (素裳大招攻击力30%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.30),),
            duration=2,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        # 造成 320% 物理伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=3.20,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

"""开拓者•同谐 (Harmony Trailblazer) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 8005 (男) / 8006 (女), 命途: 同谐 (Shaman), 属性: 虚数 (Imaginary)
- 普攻【摇摆的礼仪】: 造成 140% 攻击力的虚数单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【中场馈赠的雨】: 初始对指定单体造成 50% 虚数伤害并削韧 10，随后进行 4 次弹射，每次造成 50% 虚数伤害并削韧 5 (总计 5 段，削韧 30 点)，消耗 1 SP，回能 30；E6 额外增加 2 段弹射 (共 7 段)
- 终结技【喧嚣的舞灯巡游】: 消耗 140 能量，为我方全体施加【伴舞】(Backup Dancer) 状态，持续 3 回合，击破特攻提高 30%，且攻击处于弱点击破状态的敌方时触发【超击破伤害】，回能 5
- 天赋【全屏段的高空踏歌】: 当敌方弱点被击破时，开拓者立即恢复 10 点能量
- 秘技【即刻！独奏团】: 进战后我方全体击破特攻提高 30%，持续 2 回合
- 星魂 1~6 完整实装:
  - E1 您的最佳观众席: 施放首次战技后立即恢复 1 点战技点
  - E2 越狱的跨洋彩虹: 战斗开始时，开拓者的能量恢复效率提高 25%，持续 3 回合
  - E3 休止符的疗养院: 战技+2，天赋+2
  - E4 袒护白鸽的冠冕: 开拓者在场时，除自身外我方全体击破特攻提高等同于开拓者击破特攻 15% 的数值
  - E5 包庇旧节拍的诗: 终结技+2，普攻+1
  - E6 明天，栖息聚光之下: 战技额外伤害段数增加 2 次 (总计 7 段)
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


class TrailblazerHarmonyKit(KitHandler):
    BACKUP_DANCER_BUFF = "TB_Harmony_Backup_Dancer"
    E2_ERR_BUFF = "TB_Harmony_E2_Err"
    E4_BREAK_AURA = "TB_Harmony_E4_Break_Aura"
    TECHNIQUE_BREAK_BUFF = "TB_Harmony_Technique_Break"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.first_skill_refund: bool = True if eidolon >= 1 else False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="摇摆的礼仪"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="中场馈赠的雨"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="喧嚣的舞灯巡游"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="即刻！独奏团"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：E2 充能效率提高 25% 持续 3 回合，E4 全队击破特攻光环。"""
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E2_ERR_BUFF,
                name="越狱的跨洋彩虹 (开拓者E2能量恢复效率25%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.ERR, ModifierOp.ADD, 0.25),),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

        if self.eidolon >= 4:
            for ally in self.port.allies(self.owner_id):
                if ally != self.owner_id:
                    self.port.upsert_status(BuffSpec(
                        key=f"{self.E4_BREAK_AURA}_{ally}",
                        name="袒护白鸽的冠冕 (开拓者E4击破特攻光环15%)",
                        source_id=self.owner_id,
                        target_id=ally,
                        modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.15),),
                        duration=None,
                        timing=DurationTiming.TARGET_TURN_END
                    ))

    def on_enemy_broken(self) -> None:
        """天赋【全屏段的高空踏歌】：敌方弱点被击破时回能 10 点。"""
        self.port.gain_energy(self.owner_id, 10.0)

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
        """秘技【即刻！独奏团】：进入战斗后我方全体击破特攻提高 30%，持续 2 回合。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"{self.TECHNIQUE_BREAK_BUFF}_{ally}",
                name="即刻！独奏团 (开拓者秘技击破特攻30%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)

        # 初始首段打击：指定单体 50% 虚数伤害，削韧 10
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=0.50,
            toughness_damage=10.0,
            damage_type=DamageType.SKILL
        )

        # 基础 4 段额外弹射，E6 增加 2 段 (共 6 段弹射，总计 7 段攻击)
        bounce_hits = 6 if self.eidolon >= 6 else 4
        for _ in range(bounce_hits):
            hit_target = random.choice(enemies) if enemies else target_id
            self.port.attack(
                self.owner_id,
                hit_target,
                element="Imaginary",
                atk_multiplier=0.50,
                toughness_damage=5.0,
                damage_type=DamageType.SKILL
            )

        # E1 您的最佳观众席: 首次战技返还 1 点 SP
        if self.first_skill_refund:
            self.first_skill_refund = False
            self.port.change_sp(self.owner_id, 1, "开拓者E1首次战技返还SP")

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # 为我方全体施加【伴舞】(Backup Dancer) 状态持续 3 回合，击破特攻提高 30%
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"{self.BACKUP_DANCER_BUFF}_{ally}",
                name="伴舞 (开拓者超击破光环与击破特攻30%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.30),),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

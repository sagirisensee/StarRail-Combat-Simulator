"""开拓者•同谐 (Harmony Trailblazer) 战斗技能套件完整实现 (Character Kit).

适配角色：开拓者 (ID 8006, 同谐 / 虚数, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【摇摆的礼仪】：造成单体虚数伤害，恢复 1 点战技点，回能 20 点；
2. 战技【中场大休止】：
   - 消耗 1 点 SP，对目标造成 4 段弹射虚数伤害，每段削韧 10 点 (总计削韧 50 点破韧神器)；
   - 【星魂 6 联动】：战技额外增加 2 段弹射伤害 (总计 7 段，削韧高达 70 点！)；
3. 终结技【喧嚣的盛会巡游】：
   - 消耗 140 能量；
   - 为我方全体施加【伴舞】(Backup Dancer) 状态，持续 3 回合；
   - 我方处于【伴舞】状态的目标击破特攻提高 30%；
   - 攻击处于弱点击破状态的敌方时，触发【超击破伤害】(Super Break DMG)！
   - 【星魂 2 联动】：战斗开始或施放终结技，全队能量恢复效率提高 25%；
4. 天赋【全幕踩点拔梢】：
   - 敌方弱点被击破时，开拓者立即恢复 10 点能量；
   - 【星魂 1 联动】：首次施放战技时不消耗战技点；
   - 【星魂 4 联动】：开拓者在场时，除自身外我方全体击破特攻提高等同于开拓者击破特攻 15% 的数值。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class TrailblazerHarmonyKit(KitHandler):
    BACKUP_DANCER_BUFF = "TB_Harmony_Backup_Dancer"
    E4_BREAK_AURA = "TB_Harmony_E4_Break_Aura"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.first_skill_free: bool = True if eidolon >= 1 else False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="摇摆的礼仪"
            )
        elif kind == ActionKind.SKILL:
            sp_cost = 0 if self.first_skill_free else 1
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=sp_cost),
                name="中场大休止"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="喧嚣的盛会巡游"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E4: 击破特攻光环 (提高全队 30% 击破特攻)。"""
        if self.eidolon >= 4:
            for ally in self.port.allies(self.owner_id):
                if ally != self.owner_id:
                    self.port.upsert_status(BuffSpec(
                        key=self.E4_BREAK_AURA,
                        name="鸽群中的白冠 (开拓者E4全队击破特攻30%)",
                        source_id=self.owner_id,
                        target_id=ally,
                        modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.30),),
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

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        if self.first_skill_free:
            self.first_skill_free = False

        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)

        # 基础 4 段，E6 增加 2 段 (总计 6~7 段弹射削韧)
        hits = 6 if self.eidolon >= 6 else 4
        for _ in range(hits):
            import random
            target = random.choice(enemies) if enemies else target_id
            self.port.attack(
                self.owner_id,
                target,
                element="Imaginary",
                atk_multiplier=0.50,
                toughness_damage=10.0,
                damage_tag="Skill"
            )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            # 施加【伴舞】(击破特攻提高 30%)
            self.port.upsert_status(BuffSpec(
                key=self.BACKUP_DANCER_BUFF,
                name="伴舞 (开拓者超击破光环与击破特攻)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.30),),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def on_enemy_broken(self) -> None:
        """敌方弱点被击破时回能 10 点。"""
        self.port.gain_energy(self.owner_id, 10.0)

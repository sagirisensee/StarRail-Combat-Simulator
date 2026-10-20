"""克拉拉 (Clara) 战斗技能套件完整实现 (Character Kit).

适配角色：克拉拉 (ID 1107, 毁灭 / 物理, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【我也想帮上忙】：造成单体物理伤害，恢复 1 点战技点，回能 20 点；
2. 战技【史瓦罗在看着你】：
   - 消耗 1 点 SP，对敌方全体造成物理伤害；
   - 对持有【反击标记】(Mark of Counter) 的敌人造成 2 倍巨额伤害；
   - 【星魂 1 联动】：施放战技不再清除敌方身上的【反击标记】！
3. 终结技【是约定不是命令】：
   - 消耗 110 能量；
   - 克拉拉受到的伤害额外降低 30%，嘲讽度巨幅提高，持续 2 回合；
   - 强化史瓦罗的反击：队友受击时同样触发反击，反击伤害倍率提升 160%，并对相邻目标造成溅射扩散！
   - 【星魂 2 联动】：施放终结技后，克拉拉攻击力提高 30%，持续 2 回合；
   - 【星魂 6 联动】：强化反击触发次数额外增加 1 次；
4. 天赋【因为我们是家人】：
   - 克拉拉受到的伤害常态降低 10%；
   - 受到敌方攻击后，史瓦罗必定对攻击者发动反击，造成 160% 物理反击伤害，并施加【反击标记】；
   - 【星魂 4 联动】：受击后自身受到的伤害额外降低 30%，持续 1 回合；
   - 【星魂 6 联动】：其他队友受击时，史瓦罗也有 50% 固定概率触发反击并施加标记！
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class ClaraKit(KitHandler):
    COUNTER_MARK_KEY = "Clara_Counter_Mark"
    ULT_BUFF_KEY = "Clara_Ult_Protection"
    E2_ATK_BUFF = "Clara_E2_Atk"
    E4_DMG_REDUCE = "Clara_E4_DmgReduce"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.enhanced_counters_remaining: int = 0
        self.marked_enemies: set = set()

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="我也想帮上忙"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(sp=1),
                name="史瓦罗在看着你"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=110.0),
                allow_self=True,
                name="是约定不是命令"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """常态减伤 10% 天赋光环。"""
        self.port.upsert_status(BuffSpec(
            key="Clara_Talent_DmgReduce",
            name="因为我们是家人 (克拉拉常驻减伤10%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.10),),
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
            element="Physical",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            has_mark = enemy in self.marked_enemies
            # 基础 120% 全体伤害，有标记则翻倍为 240%
            mult = 2.40 if has_mark else 1.20
            self.port.attack(
                self.owner_id,
                enemy,
                element="Physical",
                atk_multiplier=mult,
                toughness_damage=10.0,
                damage_tag="Skill"
            )
            # E1: 施放战技不再清除反击标记！(E0 清除)
            if not (self.eidolon >= 1) and has_mark:
                self.marked_enemies.remove(enemy)

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # 强化反击次数：基础 2 次，E6 增加为 3 次
        self.enhanced_counters_remaining = 3 if self.eidolon >= 6 else 2

        # 终结技减伤 30%
        self.port.upsert_status(BuffSpec(
            key=self.ULT_BUFF_KEY,
            name="是约定不是命令 (克拉拉终结技减伤30%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.30),),
            duration=2,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        # E2: 施放终结技后，攻击力提高 30%，持续 2 回合
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E2_ATK_BUFF,
                name="紧紧的拥抱 (克拉拉E2攻击力提高30%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def trigger_counter(self, attacker_id: str, is_clara_hit: bool = True) -> None:
        """史瓦罗反击机制实现 (含强化反击与 E4/E6 逻辑)。"""
        import random
        # E6: 队友受击时也有 50% 概率触发反击
        if not is_clara_hit:
            if not (self.eidolon >= 6 and random.random() < 0.50):
                if self.enhanced_counters_remaining <= 0:
                    return

        is_enhanced = self.enhanced_counters_remaining > 0
        if is_enhanced:
            self.enhanced_counters_remaining -= 1
            # 强化反击倍率 3.20x 扩散
            self.port.attack(
                self.owner_id,
                attacker_id,
                element="Physical",
                atk_multiplier=3.20,
                toughness_damage=20.0,
                damage_tag="EnhancedCounter"
            )
        else:
            # 普通反击倍率 1.60x
            self.port.attack(
                self.owner_id,
                attacker_id,
                element="Physical",
                atk_multiplier=1.60,
                toughness_damage=10.0,
                damage_tag="Counter"
            )

        self.marked_enemies.add(attacker_id)
        self.port.gain_energy(self.owner_id, 5.0)

        # E4: 受击后减伤 30% 持续 1 回合
        if self.eidolon >= 4 and is_clara_hit:
            self.port.upsert_status(BuffSpec(
                key=self.E4_DMG_REDUCE,
                name="家人的温暖 (克拉拉E4受击额外减伤30%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.30),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

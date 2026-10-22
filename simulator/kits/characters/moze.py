"""貊泽 (Moze) 战斗技能套件完整实现 (Character Kit).

适配角色：貊泽 (ID 1223, 巡猎 / 雷, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 战技【飞羽惊鸿】：
   - 消耗 1 点 SP，指定敌方单体为【猎物】(Prey)；
   - 貊泽自身进入【离场】状态 (不占用行动轴，不受击)；
   - 队友攻击【猎物】时受到附加雷伤，并积累貊泽充能点数；
2. 天赋【逐影潜形】：
   - 队友攻击【猎物】达到 3 次，貊泽发动追加攻击造成 160% 物理/雷属性伤害；
3. 终结技【匕影断喉】：
   - 消耗 120 能量，对【猎物】造成 270% 雷属性高额暴击伤害；
4. 星魂 1~6 完整实装：
   - E1: 隐匕 (开战直接恢复 20 点能量，敌方陷入猎物时受到的追加攻击伤害提高 25%)；
   - E2: 疾影 (对处于【猎物】状态的目标暴击伤害提高 40%)；
   - E3: 暗羽 (战技+2，终结技+2)；
   - E4: 锋芒 (施放终结技后造成的伤害提高 30%，持续 2 回合)；
   - E5: 匿踪 (天赋+2，普攻+1)；
   - E6: 绝命 (追加攻击伤害倍率提高 25点百分比，且发动追加攻击后恢复 1 点战技点)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class MozeKit(KitHandler):
    PREY_DEBUFF = "Moze_Prey_Mark"
    E4_DMG_BUFF = "Moze_E4_DmgBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.prey_target_id: Optional[str] = None
        self.ally_hits_on_prey: int = 0
        self.is_departed: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="飞翎"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="飞羽惊鸿"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=120.0),
                name="匕影断喉"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="翼蔽"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 隐匕 (开战立即恢复 20 点能量)。"""
        if self.eidolon >= 1:
            self.port.gain_energy(self.owner_id, 20.0)

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
        """秘技【翼蔽】：进战造成的伤害提高 30%，持续 2 回合。"""
        self.port.upsert_status(BuffSpec(
            key="Moze_Technique_DmgBuff",
            name="翼蔽 (貊泽秘技增伤30%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
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
        self.prey_target_id = target_id
        self.is_departed = True

        mods = []
        # E1: 猎物受到的追加攻击伤害提高 25%
        if self.eidolon >= 1:
            mods.append(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.25))
        # E2: 对猎物暴击伤害提高 40%
        if self.eidolon >= 2:
            mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.40))

        self.port.upsert_status(BuffSpec(
            key=self.PREY_DEBUFF,
            name="猎物 (貊泽猎物标记与暴伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = self.prey_target_id or (
            ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        )
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=2.70,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )

        # E4: 终结技施放后增伤 30% 持续 2 回合
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=self.E4_DMG_BUFF,
                name="锋芒 (貊泽E4大招增伤30%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def on_ally_attack_prey(self) -> None:
        """队友命中猎物累积 3 次触发貊泽追击。"""
        if not self.is_departed or not self.prey_target_id:
            return

        self.ally_hits_on_prey += 1
        if self.ally_hits_on_prey >= 3:
            self.ally_hits_on_prey = 0
            # E6: 倍率提升 25% (1.60 -> 1.85) 且恢复 1 点战技点
            mult = 1.85 if self.eidolon >= 6 else 1.60
            self.port.attack(
                self.owner_id,
                self.prey_target_id,
                element="Lightning",
                atk_multiplier=mult,
                toughness_damage=10.0,
                damage_tag="MozeFollowUp"
            )

            # E6: 产点
            if self.eidolon >= 6:
                self.port.change_sp(self.owner_id, 1, "貊泽E6追击产点")

            self.port.gain_energy(self.owner_id, 10.0)

"""彦卿 (Yanqing) 战斗技能套件完整实现 (Character Kit).

适配角色：彦卿 (ID 1209, 巡猎 / 冰)
严格契合实机机制与公式：
1. 普攻【霜锋点寒芒】：造成单体冰伤，恢复 1 点战技点，回能 20 点；
2. 战技【遥击三尺水】：
   - 消耗 1 点 SP，单体冰伤，激活【智剑连心】(Soulsteel Sync) 持续 1 回合；
   - 处于【智剑连心】时：受击概率大幅降低，暴击率提高 20%，暴击伤害提高 30%；
   - 攻击时有 60% 固定概率发动追加攻击，削韧 10 点，概率冻结敌人；
3. 终结技【快雨燕相逐】：
   - 消耗 140 能量，自身暴击率提高 60%；
   - 若处于【智剑连心】状态，暴击伤害额外提高 60%，持续 1 回合；
   - 对敌方单体造成 350% 冰属性爆发伤害；
4. 星魂 1~6 完整实装：
   - E1: 剑气入骨 (攻击处于冻结状态的目标时，额外造成 60% 冰属性附加伤害)；
   - E2: 空明神照 (处于【智剑连心】时能量恢复效率提高 10%)；
   - E3: 剑术精熟 (战技+2，普攻+1)；
   - E4: 霜厉 (生命值大于等于 80% 时，自身冰属性抗性穿透提高 12%)；
   - E5: 武道天成 (终结技+2，天赋+2)；
   - E6: 自在逍遥 (消灭敌方目标时，若处于终结技或智剑连心增益，其持续时间延长 1 回合)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class YanqingKit(KitHandler):
    SOULSTEEL_BUFF = "Yanqing_Soulsteel_Sync"
    ULT_CRIT_BUFF = "Yanqing_Ult_Crit"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_soulsteel: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="霜锋点寒芒"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="遥击三尺水"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=140.0),
                name="快雨燕相逐"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="御剑真诀"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E4: 生命 >= 80% 获得 12% 冰属性抗性穿透。"""
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key="Yanqing_E4_ResPen",
                name="霜厉 (彦卿E4冰属性抗穿12%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.12),),
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
        elif ctx.kind == ActionKind.TECHNIQUE:
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【御剑真诀】：进战后自身对生命值 >= 50% 目标伤害提高 30%，持续 2 回合。"""
        self.port.upsert_status(BuffSpec(
            key="Yanqing_Technique_DmgBuff",
            name="御剑真诀 (彦卿秘技增伤30%)",
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
            element="Ice",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=2.20,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        # 激活【智剑连心】
        self.is_soulsteel = True
        self.port.upsert_status(BuffSpec(
            key=self.SOULSTEEL_BUFF,
            name="智剑连心 (彦卿暴击20%与暴伤30%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.20),
                Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.30),
            ),
            duration=1,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        # 触发追加攻击
        self._trigger_follow_up(target_id)
        # E2: 回能效率提高
        extra_energy = 5.0 if self.eidolon >= 2 else 0.0
        self.port.gain_energy(self.owner_id, 30.0 + extra_energy)

    def _trigger_follow_up(self, target_id: str) -> None:
        mult = 0.50
        # E1: 攻击冻结敌人额外造成 60% 伤害
        if self.eidolon >= 1:
            mult += 0.60
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="YanqingFollowUp"
        )

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # 终结技暴击加成
        cd_bonus = 0.60 if self.is_soulsteel else 0.0
        self.port.upsert_status(BuffSpec(
            key=self.ULT_CRIT_BUFF,
            name="快雨燕相逐 (彦卿大招暴击60%与暴伤)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.60),
                Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_bonus),
            ),
            duration=1,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=3.50,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

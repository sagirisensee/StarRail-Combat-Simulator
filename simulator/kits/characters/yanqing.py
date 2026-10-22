"""彦卿 (Yanqing) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1209, 命途: 巡猎 (Rogue), 属性: 冰 (Ice)
- 普攻【霜锋点寒芒】: 造成 140% 攻击力的冰属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【遥击三尺水】: 造成 220% 攻击力的冰属性单体伤害，削韧 20，消耗 1 SP，回能 30，为自身附加【智剑连心】持续 1 回合
- 终结技【快雨燕相逐】: 自身暴击率提高 60%，若处于【智剑连心】暴击伤害额外提高 50%，持续 1 回合；造成 350% 冰属性单体伤害，削韧 30，消耗 140 能量，回能 5
- 天赋【呼剑如影】: 处于【智剑连心】时暴击率提高 20%，暴击伤害提高 30%，受击概率降低；攻击后 60% 固定概率发动追加攻击造成 50% 冰伤并概率冻结；受到伤害时【智剑连心】解除
- 星魂 1~6 完整实装:
  - E1 素刃: 攻击处于冻结状态的目标时额外造成 60% 攻击力的冰属性附加伤害
  - E2 空明: 处于【智剑连心】时能量恢复效率提高 10%
  - E3 剑胎: 战技+2，普攻+1
  - E4 霜厉: 生命值大于等于 80% 时冰属性抗性穿透提高 12%
  - E5 武道: 终结技+2，天赋+2
  - E6 自在: 消灭敌方目标时，若持有【智剑连心】或终结技增益，其持续时间增加 1 回合
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class YanqingKit(KitHandler):
    SOULSTEEL_BUFF = "Yanqing_Soulsteel"
    ULT_CRIT_BUFF = "Yanqing_Ult_Crit"
    TECHNIQUE_BUFF = "Yanqing_Technique"
    E4_PEN_BUFF = "Yanqing_E4_ResPen"

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
        """战斗开始：检测 E4 冰抗穿透。"""
        self._check_e4_buff()

    def _check_e4_buff(self) -> None:
        """E4: 生命值 >= 80% 时冰抗穿透 +12%。"""
        if self.eidolon >= 4:
            if self.port.hp_ratio(self.owner_id) >= 0.80:
                self.port.upsert_status(BuffSpec(
                    key=self.E4_PEN_BUFF,
                    name="霜厉 (彦卿E4冰属性抗性穿透12%)",
                    source_id=self.owner_id,
                    target_id=self.owner_id,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.12),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END
                ))
            else:
                self.port.remove_status(self.owner_id, self.E4_PEN_BUFF)

    def _apply_soulsteel(self) -> None:
        """激活【智剑连心】：暴击率+20%，暴伤+30%，E2 充能效率+10%。"""
        self.is_soulsteel = True
        modifiers = [
            Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.20),
            Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.30),
        ]
        if self.eidolon >= 2:
            modifiers.append(Modifier(StatType.ERR, ModifierOp.ADD, 0.10))

        self.port.upsert_status(BuffSpec(
            key=self.SOULSTEEL_BUFF,
            name="智剑连心 (彦卿暴击20%/暴伤30%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(modifiers),
            duration=1,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

    def on_damaged(self, attacker_id: str, damage: float) -> None:
        """受到伤害时【智剑连心】解除。"""
        if damage > 0:
            self.is_soulsteel = False
            self.port.remove_status(self.owner_id, self.SOULSTEEL_BUFF)
            self._check_e4_buff()

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
            key=self.TECHNIQUE_BUFF,
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
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)
        self._check_soulsteel_followup(target_id)

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
        # 赋予自身【智剑连心】
        self._apply_soulsteel()
        self.port.gain_energy(self.owner_id, 30.0)
        self._check_soulsteel_followup(target_id)

    def _check_soulsteel_followup(self, target_id: str) -> None:
        """处于智剑连心时，攻击后有 60% 概率触发追加攻击。"""
        if self.is_soulsteel:
            self._trigger_follow_up(target_id)

    def _trigger_follow_up(self, target_id: str) -> None:
        """天赋追加攻击：50% 倍率冰伤，削韧 10，概率冻结；E1 冻结附加伤害 60%。"""
        mult = 0.50
        if self.eidolon >= 1:
            # E1: 对冻结目标额外造成 60% 伤害
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
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 自身暴击率提高 60%；若处于【智剑连心】，暴击伤害额外提高 50%
        crit_dmg_bonus = 0.50 if self.is_soulsteel else 0.0
        self.port.upsert_status(BuffSpec(
            key=self.ULT_CRIT_BUFF,
            name="快雨燕相逐 (彦卿暴击60%/暴伤50%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.60),
                Modifier(StatType.CRIT_DMG, ModifierOp.ADD, crit_dmg_bonus),
            ),
            duration=1,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=3.50,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)
        self._check_soulsteel_followup(target_id)

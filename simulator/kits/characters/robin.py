"""知更鸟 (Robin - ID 1309, 物理 / 同谐) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【扑翼白声】：单体物理伤害，等同知更鸟 100% (Lv 6) / 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【翎之咏叹调】：消耗 1 点 SP，我方全体造成的伤害提高 50% (Lv 10)，持续 3 回合。回能 30。
3. 终结技【千音迭奏，群星赋格】(耗能 160 点)：
   - 知更鸟进入【协奏】(Concerto) 状态；
   - 除自身以外的我方全体立即行动 (100% 立即拉条)！
   - 基于知更鸟自身攻击力，使我方全体攻击力提高 (知更鸟攻击力 * 22.8% + 200)；
   - 我方目标每次施放攻击后，知更鸟额外造成 1 次等同于其自身 120% 攻击力的物理附加伤害；
     该附加伤害暴击率固定为 100%，暴击伤害固定为 150%；
   - 处于【协奏】状态时，知更鸟免疫控制，不进入自己的回合且无法行动；
   - 行动序列上出现【协奏】倒计时，固定速度 90 点；倒计时回合开始时退出【协奏】并使知更鸟立即行动；
   - E1【微笑的国度】：处于【协奏】状态时，我方全体全属性抗性穿透提高 24%；
   - E2【两者的午茶】：处于【协奏】状态时，我方全体速度提高 16%，天赋回能额外提高 1 点；
   - E4【雨滴的钥匙】：施放大招时解除我方全体控制，协奏期间我方全体效果抵抗提高 50%；
   - E6【月隐的午夜】：处于【协奏】状态时，终结技附加伤害暴伤额外提高 450%，前 8 次生效，施放大招重置。
4. 天赋【调性合颂】：
   - 使我方全体暴击伤害提高 20% (Lv 10)；
   - 我方目标攻击敌方目标后，知更鸟额外为自身恢复 2 点能量 (E2 提升至 3 点)。
5. 秘技【酣醉序曲】：进入战斗后每个波次开始知更鸟恢复 5 点能量。
6. 行迹【模进咏叹】：战斗开始时知更鸟自身行动提前 25%。
"""

from typing import Optional, Any
from ..base import KitHandler
from ..registry import register_kit
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...events import ActionExecuteEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class ConcertoCountdownKit(KitHandler):
    """知更鸟【协奏】倒计时实体套件 (固定速度 90)。"""

    def __init__(self, owner_id: str, port: CombatPort, *, master_kit: Any = None):
        super().__init__(owner_id, port)
        self.master_kit = master_kit

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        return AbilityDefinition(
            kind=ActionKind.SKILL,
            target_mode=TargetMode.SELF,
            cost=ResourceCost(sp=0),
            name="协奏倒计时结算",
            tag="倒计时",
            is_auto=True
        )

    def execute(self, ctx: ActionContext) -> None:
        if self.master_kit:
            self.master_kit.exit_concerto()


@register_kit("1309", "知更鸟", "robin")
class RobinKit(KitHandler):
    """知更鸟 (Robin - ID 1309, 物理 / 同谐)."""

    COUNTDOWN_NAME = "协奏•倒计时"
    SKILL_DMG_BUFF = "Robin_Skill_Aria"
    ULT_CONCERTO_BUFF = "Robin_Concerto_Atk"
    E1_RES_PEN_BUFF = "Robin_E1_ResPen"
    E2_SPEED_BUFF = "Robin_E2_Speed"
    E4_EFFECT_RES_BUFF = "Robin_E4_EffectRes"

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 0, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.in_concerto: bool = False
        self.e6_hits_remaining: int = 8

    def on_battle_start(self) -> None:
        """战斗开始：
        1. 天赋【调性合颂】：我方全体常驻暴伤提高 20% (Lv 10)。
        2. 行迹【模进咏叹】：战斗开始时知更鸟行动提前 25%。
        """
        cd_val = self.skill_param("talent", 0, default=0.20)
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Robin_Talent_TonalHarmony_{ally}",
                name="调性合颂",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"暴击伤害提高 +{cd_val * 100:.1f}%"
            ))

        # 行迹【模进咏叹】：行动提前 25%
        self.port.advance(self.owner_id, self.owner_id, 0.25)

    def use_technique(self) -> None:
        """秘技【酣醉序曲】：进入战斗后每个波次开始知更鸟恢复 5 点能量。"""
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        tech_energy = self.skill_param("technique", 1, default=5.0)
        self.port.gain_energy(self.owner_id, tech_energy * err)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="扑翼白声"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="翎之咏叹调"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=160.0),
                allow_self=True,
                name="千音迭奏，群星赋格"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="酣醉序曲",
                priority=2
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【扑翼白声】：单体物理伤害。"""
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        target_id = ctx.target_ids[0] if ctx.target_ids else enemies[0]
        mult = self.skill_param("basic", 0, default=1.00)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【翎之咏叹调】：我方全体增伤 50%，持续 3 回合。"""
        dmg_boost = self.skill_param("skill", 0, default=0.50)
        turns = int(self.skill_param("skill", 1, default=3))
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.SKILL_DMG_BUFF,
                name="翎之咏叹调",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_boost),),
                duration=turns,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"我方全体造成的伤害提高 +{dmg_boost * 100:.1f}%"
            ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【千音迭奏，群星赋格】：进入【协奏】，拉条全队除自身，全队加攻，召唤速度 90 倒计时。"""
        self.in_concerto = True
        self.e6_hits_remaining = 8
        allies = self.port.allies(self.owner_id)
        other_allies = [a for a in allies if a != self.owner_id]

        # 1. 全队除知更鸟外立即 100% 行动！
        for ally in other_allies:
            self.port.advance(self.owner_id, ally, 1.0)

        # 2. 攻击力提升数值：知更鸟攻击力 * 22.8% + 200 (Lv 10)
        robin_atk = self.port.stat(self.owner_id, StatType.ATK_BASE)
        atk_pct = self.skill_param("ultra", 0, default=0.228)
        atk_flat = self.skill_param("ultra", 2, default=200.0)
        bonus_atk = robin_atk * atk_pct + atk_flat

        for ally in allies:
            if self.eidolon >= 4:
                self.port.dispel(ally, is_debuff=True)

            self.port.upsert_status(BuffSpec(
                key=self.ULT_CONCERTO_BUFF,
                name="协奏 (千音迭奏，群星赋格)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_BASE, ModifierOp.ADD, bonus_atk),),
                duration=None,
                timing=DurationTiming.CASTER_TURN_END,
                category="buff",
                description=f"攻击力提高 +{bonus_atk:.1f}"
            ))

            # 星魂 1【微笑的国度】：协奏期间我方全体全属性抗性穿透提高 24%
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key=self.E1_RES_PEN_BUFF,
                    name="微笑的国度",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.24),),
                    duration=None,
                    timing=DurationTiming.CASTER_TURN_END,
                    category="buff",
                    description="全属性抗性穿透提高 +24.0%"
                ))

            # 星魂 2【两者的午茶】：协奏期间我方全体速度提高 16%
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key=self.E2_SPEED_BUFF,
                    name="两者的午茶",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.16),),
                    duration=None,
                    timing=DurationTiming.CASTER_TURN_END,
                    category="buff",
                    description="速度提高 +16.0%"
                ))

            # 星魂 4【雨滴的钥匙】：协奏期间我方全体效果抵抗提高 50%
            if self.eidolon >= 4:
                self.port.upsert_status(BuffSpec(
                    key=self.E4_EFFECT_RES_BUFF,
                    name="雨滴的钥匙",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.50),),
                    duration=None,
                    timing=DurationTiming.CASTER_TURN_END,
                    category="buff",
                    description="效果抵抗提高 +50.0%"
                ))

        # 3. 召唤固定速度 90 的【协奏】倒计时实体，并挂起知更鸟自身回合
        countdown_spd = self.skill_param("ultra", 1, default=90.0)
        countdown_ent = self.port.summon_spirit(
            owner_id=self.owner_id,
            name=self.COUNTDOWN_NAME,
            base_speed=countdown_spd,
            max_hp=1000.0,
            kit_class=ConcertoCountdownKit,
            kit_args={"master_kit": self},
            is_memosprite=False,
            is_countdown=True
        )
        if countdown_ent:
            self.port.set_distance(self.COUNTDOWN_NAME, 10000.0)
        self.port.set_distance(self.owner_id, 999999.0)

        # 施放大招自身固定回能 5 点
        self.port.gain_energy(self.owner_id, 5.0)

    def exit_concerto(self) -> None:
        """【协奏】倒计时回合开始时：退出【协奏】状态，移除协奏光环，并使知更鸟立即行动。"""
        self.in_concerto = False
        for ally in self.port.allies(self.owner_id):
            self.port.remove_status(ally, self.ULT_CONCERTO_BUFF)
            self.port.remove_status(ally, self.E1_RES_PEN_BUFF)
            self.port.remove_status(ally, self.E2_SPEED_BUFF)
            self.port.remove_status(ally, self.E4_EFFECT_RES_BUFF)
        self.port.despawn_spirit(self.COUNTDOWN_NAME, reason="concerto_end")
        self.port.set_distance(self.owner_id, 0.0)

    def on_event(self, event: Any) -> None:
        """响应事件：
        1. 我方攻击后：天赋【调性合颂】知更鸟恢复 2 点能量 (E2 为 3 点)。
        2. 协奏期间我方攻击后：触发 120% 攻击力的物理附加伤害 (固定 100% 暴击率，150% 暴伤，E6 前 8 次暴伤+450%)。
        """
        if isinstance(event, ActionExecuteEvent):
            actor_id = getattr(event, "actor_name", "") or getattr(event, "actor_id", "")
            action_kind = getattr(event, "action_kind", None)
            action_type = getattr(event, "action_type", "")

            if (
                self.port.is_ally(actor_id)
                and self.port.is_attack_action(actor_id, action_kind, action_type)
            ):
                # 1. 天赋【调性合颂】回能: 2 点 (E2 为 3 点)
                base_energy = self.skill_param("talent", 1, default=2.0) + (1.0 if self.eidolon >= 2 else 0.0)
                err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
                self.port.gain_energy(self.owner_id, base_energy * err)

                # 2. 处于【协奏】状态时造成物理附加伤害 (固定 100% 暴击率、150% 暴伤)
                enemies = self.port.enemies(self.owner_id)
                if self.in_concerto and enemies:
                    target_ids = getattr(event, "target_ids", ())
                    target_id = target_ids[0] if target_ids else enemies[0]
                    add_mult = self.skill_param("ultra", 3, default=1.20)
                    fixed_cd = self.skill_param("ultra", 5, default=1.50)
                    if self.eidolon >= 6 and self.e6_hits_remaining > 0:
                        fixed_cd += 4.50
                        self.e6_hits_remaining -= 1
                    self.port.attack(
                        self.owner_id,
                        target_id,
                        element="Physical",
                        atk_multiplier=add_mult,
                        toughness_damage=0.0,
                        damage_type=DamageType.ADDITIONAL,
                        scaling_stat="atk",
                        force_crit=True,
                        fixed_crit_dmg=fixed_cd
                    )

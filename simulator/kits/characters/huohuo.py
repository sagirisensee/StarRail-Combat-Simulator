"""藿藿 (Huohuo - ID 1217, 风 / 丰饶) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【令旗•征风召雨】：单体风属性伤害，等同藿藿 70% (Lv 10) 生命上限，削韧 10，回能 20，回 1 SP。HP 缩放 (scaling_stat="hp")。
2. 战技【灵符•保命护身】：
   - 消耗 1 点 SP，解除指定我方单体 1 个负面，回复生命 (21% HP + 560)，并对其他队友回复生命 (16.8% HP + 448)；
   - 激活/刷新【禳命】(E1 为 4 回合，E0 为 3 回合)；
   - 若队伍中存在生命低于 50% 残血目标，额外触发急救回复；
   - E6【同休共戚，相须而行】：治疗目标时造成伤害提高 50%，持续 2 回合；
   - 回能 30 点。
3. 终结技【尾巴•遣神役鬼】(耗能 140 点)：
   - 为除自身外全队恢复等同各自能量上限 20% 的能量；
   - 全队攻击力提高 40% (Lv 10)，高能量上限 (>= 160) 目标特化提高 64%，持续 2 回合；
   - 同样刷新并维持【禳命】状态；
   - 回能 5 点。
4. 天赋【凭附•气通天真】：
   - 行迹【不敢自专】：战斗开始时立即恢复 30 点能量，并直接为全队激活【禳命】；
   - 【禳命】期间队友回合开始或施放大招回复生命并解除 1 个负面；
   - E1【岁阳寄体，妖邪依凭】：【禳命】持续 4 回合，且全队速度提高 12%。
5. 秘技【凶煞•劾压鬼物】：进战使敌方目标攻击力降低 25%，持续 2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class HuohuoKit(KitHandler):
    """藿藿 (ID 1217, 风 / 丰饶)."""

    PROVISION_BUFF = "Huohuo_Divine_Provision"
    ULT_ATK_BUFF = "Huohuo_Ult_Atk"
    E6_DMG_BUFF = "Huohuo_E6_DmgBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def on_battle_start(self) -> None:
        """行迹【不敢自专】：开局立即恢复 30 点能量，并直接为全队激活【禳命】。"""
        self.port.gain_energy(self.owner_id, 30.0)
        self._apply_divine_provision()

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="令旗•征风召雨"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="灵符•保命护身"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="尾巴•遣神役鬼"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="凶煞•劾压鬼物"
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

    def use_technique(self) -> None:
        """秘技【凶煞•劾压鬼物】：进战使敌方目标攻击力降低 25%，持续 2 回合。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Huohuo_Tech_AtkDown_{enemy}",
                name="凶煞•劾压鬼物",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, -0.25),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="攻击力降低 25.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【令旗•征风召雨】：单体风属性伤害，70% (Lv 10) 生命上限。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=0.70)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="hp"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _apply_divine_provision(self) -> None:
        """施加/刷新【禳命】状态 (E1 为 4 回合，E0 为 3 回合)。"""
        duration = 4 if self.eidolon >= 1 else 3
        for ally in self.port.allies(self.owner_id):
            mods = []
            desc = "回合开始或施放大招回复生命"

            if self.eidolon >= 1:
                mods.append(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.12))
                desc += "，速度提高 +12.0%"

            self.port.upsert_status(BuffSpec(
                key=self.PROVISION_BUFF,
                name="凭附•气通天真 (禳命)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=duration,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=desc
            ))

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【灵符•保命护身】：单体与扩散治疗，解除负面，激活【禳命】。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.owner_id
        if hasattr(self.port, "dispel_debuff"):
            self.port.dispel_debuff(target_id)

        max_hp = self.port.max_hp(self.owner_id)
        heal_val = max_hp * 0.21 + 560.0
        self.port.heal(self.owner_id, target_id, heal_val)

        if self.eidolon >= 6:
            self._apply_e6_buff(target_id)

        # 扩散治疗与残血急救
        allies = self.port.allies(self.owner_id)
        for a in allies:
            if a != target_id:
                adj_heal = max_hp * 0.168 + 448.0
                self.port.heal(self.owner_id, a, adj_heal)
                if self.eidolon >= 6:
                    self._apply_e6_buff(a)
            # 残血 < 50% 急救机制
            if self.port.hp_ratio(a) < 0.50:
                self.port.heal(self.owner_id, a, 1500.0)
                if self.eidolon >= 6:
                    self._apply_e6_buff(a)

        self._apply_divine_provision()
        self.port.gain_energy(self.owner_id, 30.0)

    def _apply_e6_buff(self, target_id: str) -> None:
        """E6【同休共戚，相须而行】：治疗目标时伤害提高 50%，持续 2 回合。"""
        self.port.upsert_status(BuffSpec(
            key=self.E6_DMG_BUFF,
            name="同气连枝 (藿藿E6增伤50%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="造成的伤害提高 +50.0%"
        ))

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【尾巴•遣神役鬼】：全队回能 20%，常规攻击提高 40%，高能量上限 (>=160) 特化提高 64%。"""
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            target_max_energy = self.port.max_energy(ally) if hasattr(self.port, "max_energy") else 120.0
            if ally != self.owner_id:
                self.port.gain_energy(ally, target_max_energy * 0.20)

            is_high_energy = target_max_energy >= 160.0
            bonus_atk_pct = 0.64 if is_high_energy else 0.40

            self.port.upsert_status(BuffSpec(
                key=self.ULT_ATK_BUFF,
                name="尾巴•遣神役鬼 (高能量特化64%)" if is_high_energy else "尾巴•遣神役鬼 (攻击提高40%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, bonus_atk_pct),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"攻击力提高 +{bonus_atk_pct*100:.1f}%"
            ))

        self._apply_divine_provision()
        self.port.gain_energy(self.owner_id, 5.0)

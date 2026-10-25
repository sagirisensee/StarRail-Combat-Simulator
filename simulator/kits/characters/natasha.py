"""娜塔莎 (Natasha - ID 1105, 物理 / 丰饶) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【仁慈的背面】：单体物理伤害，等同娜塔莎 140% (Lv 10) / 100% (Lv 6) 攻击力，削韧 10，回能 20，回 1 SP。
   - E6【医者仁心】：施放普攻时额外造成等同于自身生命上限 40% 的物理属性伤害。
2. 战技【爱，救护与抉择】：消耗 1 点 SP，为指定我方单体立即回复生命 (10.5% 生命上限 + 280)，解除 1 个负面状态 (行迹【舒缓】)，并附上 2 回合持续治疗 (每回合开始回复 7.2% 生命上限 + 192)。回能 30。
3. 终结技【新生之礼】(耗能 90 点)：
   - 立即为我方全体回复生命 (13.8% 生命上限 + 368)；
   - E2【临床研学】：施放终结技时，对当前生命值 <= 30% 的我方目标附加 1 回合持续治疗 (6% 生命上限 + 160)；
   - 回能 5 点。
4. 天赋【生机焕发】：
   - 为生命值 <= 30% 的我方目标提供治疗时，治疗量提高 50% (Lv 10) (对持续治疗同样生效)；
   - E1【遍识药理】：受到攻击后若生命 <= 30%，立即自疗 15% 生命上限 + 400 (单场限 1 次)；
   - E4【妙手回春】：受到攻击后额外恢复 5 点能量。
5. 秘技【催眠研习】：进战对敌方单体造成 80% 攻击力物理伤害 (削韧 20)，并使敌方陷入虚弱状态 (伤害降低 30%，持续 1 回合)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class NatashaKit(KitHandler):
    """娜塔莎 (ID 1105, 物理 / 丰饶)."""

    HOT_BUFF = "Natasha_Heal_Over_Time"
    E2_HOT_BUFF = "Natasha_E2_HoT"
    TECHNIQUE_WEAKEN_BUFF = "Natasha_Technique_Weaken"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None
        self._e1_triggered = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="仁慈的背面"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="爱，救护与抉择"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=90.0),
                allow_self=True,
                name="新生之礼"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="催眠研习"
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
        """秘技【催眠研习】：攻击敌人并使敌方陷入虚弱状态 (伤害降低 30%，持续 1 回合)。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Physical",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE,
                scaling_stat="atk"
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key=f"{self.TECHNIQUE_WEAKEN_BUFF}_{enemy}",
                name="虚弱",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.30),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="造成的伤害降低 30%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【仁慈的背面】：单体物理伤害，Lv 10 为 140% 攻击力。E6 附加 40% 生命上限伤害。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )

        # E6【医者仁心】：额外造成等同自身生命上限 40% 的物理属性伤害
        if self.eidolon >= 6:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=0.40,
                toughness_damage=0.0,
                damage_type=DamageType.ADDITIONAL,
                scaling_stat="hp"
            )

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【爱，救护与抉择】：单体急救回复、解控并附加 2 回合持续治疗。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = self.port.allies(self.owner_id)
            target_id = allies[0] if allies else self.owner_id

        # 解除 1 个负面效果 (行迹【舒缓】)
        if hasattr(self.port, "dispel_debuff"):
            self.port.dispel_debuff(target_id)

        natasha_hp = self.port.max_hp(self.owner_id)

        # 立即回复：10.5% 生命上限 + 280
        heal_val = natasha_hp * 0.105 + 280.0
        # 天赋【生机焕发】：目标生命 <= 30% 治疗量提高 50%
        if self.port.hp_ratio(target_id) <= 0.30:
            heal_val *= 1.50
        self.port.heal(self.owner_id, target_id, heal_val)

        # 持续治疗 Buff (2 回合)
        self.port.upsert_status(BuffSpec(
            key=f"{self.HOT_BUFF}_{target_id}",
            name="持续治疗 (爱，救护与抉择)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True,
            category="buff",
            description="回合开始时持续回复生命"
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【新生之礼】：我方全体大额急救回复。"""
        allies = self.port.allies(self.owner_id)
        natasha_hp = self.port.max_hp(self.owner_id)

        for ally in allies:
            heal_val = natasha_hp * 0.138 + 368.0
            is_low_hp = self.port.hp_ratio(ally) <= 0.30
            if is_low_hp:
                heal_val *= 1.50
            self.port.heal(self.owner_id, ally, heal_val)

            # E2【临床研学】：对生命 <= 30% 目标附加 1 回合持续治疗 (6% HP + 160)
            if self.eidolon >= 2 and is_low_hp:
                self.port.upsert_status(BuffSpec(
                    key=f"{self.E2_HOT_BUFF}_{ally}",
                    name="临床研学持续治疗",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(),
                    duration=1,
                    timing=DurationTiming.TARGET_TURN_START,
                    skip_current_clock=True,
                    category="buff",
                    description="回合开始时持续回复生命"
                ))

        self.port.gain_energy(self.owner_id, 5.0)

    def on_turn_start(self, event: Any) -> None:
        """目标回合开始时触发持续治疗回复。"""
        target_id = getattr(event, "target_id", None) or getattr(event, "entity_id", None)
        if not target_id or target_id not in self.port.allies(self.owner_id):
            return

        natasha_hp = self.port.max_hp(self.owner_id)
        hot_key = f"{self.HOT_BUFF}_{target_id}"
        e2_hot_key = f"{self.E2_HOT_BUFF}_{target_id}"

        has_skill_hot = self.port.has_buff(target_id, hot_key)
        has_e2_hot = self.port.has_buff(target_id, e2_hot_key)

        if not (has_skill_hot or has_e2_hot):
            return

        total_heal = 0.0
        if has_skill_hot:
            total_heal += (natasha_hp * 0.072 + 192.0)
        if has_e2_hot:
            total_heal += (natasha_hp * 0.060 + 160.0)

        if self.port.hp_ratio(target_id) <= 0.30:
            total_heal *= 1.50

        if total_heal > 0:
            self.port.heal(self.owner_id, target_id, total_heal)

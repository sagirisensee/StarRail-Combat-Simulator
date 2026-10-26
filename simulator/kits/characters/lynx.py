"""玲可 (Lynx - ID 1110, 量子 / 丰饶) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【冰攀前齿技术】：单体量子伤害，等同自身生命上限 70% (Lv 10) / 50% (Lv 6)，削韧 10，回能 20，回 1 SP。HP 缩放 (scaling_stat="hp")。
2. 战技【盐渍野营罐头】：消耗 1 点 SP，为指定我方单体附上【求生反应】持续 2 回合：
   - 提高生命上限 (7.5% 玲可生命上限 + 200)；若目标为「毁灭」或「存护」命途，受击概率大幅提高 (受击概率 +500%)；
   - 立即为该目标回复生命 (12% 玲可生命上限 + 320)；
   - 触发天赋持续治疗 2 回合；
   - E1【远行雪杖的清晨】：生命 <= 50% 的目标受治疗量提高 20%；
   - E2【便携炉具的正午】：持有【求生反应】的目标抵抗 1 次负面效果；
   - E4【露营篝火的薄暮】：获得【求生反应】时提高攻击力，等同于玲可 3% 生命上限，持续 1 回合；
   - E6【测绘图纸的黎明】：【求生反应】生命上限额外提高玲可 6% 生命上限，并使其效果抵抗提高 30%。
3. 终结技【雪原急救方案】(耗能 100 点)：
   - 解除我方全体 1 个负面效果；
   - 立即为我方全体回复生命 (13.5% 玲可生命上限 + 360)；
   - 触发天赋：为我方全体附加持续治疗 2 回合；
   - 回能 5 点。
4. 天赋【户外生存经验】：
   - 施放战技或终结技时，使目标获得 2 回合持续治疗；
   - 目标每回合开始时回复生命 (3.6% 玲可生命上限 + 96)；
   - 若目标持有【求生反应】，持续治疗额外回复 (4.5% 玲可生命上限 + 120)。
5. 秘技【巧克力能量棒】：进战为我方全体附加天赋的持续治疗效果 2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class LynxKit(KitHandler):
    """玲可 (ID 1110, 量子 / 丰饶)."""

    SURVIVAL_RESPONSE_BUFF = "Lynx_Survival_Response"
    TALENT_HOT_BUFF = "Lynx_Talent_HoT"
    E4_ATK_BUFF = "Lynx_E4_AtkBoost"

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

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="冰攀前齿技术"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="盐渍野营罐头"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=100.0),
                allow_self=True,
                name="雪原急救方案"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="巧克力能量棒"
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
        """秘技【巧克力能量棒】：进战为我方全体附加天赋持续治疗 2 回合。"""
        for ally in self.port.allies(self.owner_id):
            self._apply_talent_hot(ally, duration=2)

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【冰攀前齿技术】：单体量子伤害，等同自身生命上限 70% (Lv 10) / 50% (Lv 6)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=0.70)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="hp"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【盐渍野营罐头】：单体大额治疗并附上【求生反应】。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = self.port.allies(self.owner_id)
            target_id = allies[0] if allies else self.owner_id

        lynx_hp = self.port.max_hp(self.owner_id)

        # 立即回复生命：12% 玲可生命上限 + 320
        heal_val = lynx_hp * 0.12 + 320.0
        # E1【远行雪杖的清晨】：目标生命百分比 <= 50% 时治疗量提升 20%
        if self.eidolon >= 1 and self.port.hp_ratio(target_id) <= 0.50:
            heal_val *= 1.20
        self.port.heal(self.owner_id, target_id, heal_val)

        # 【求生反应】Buff
        # 生命上限加成: 基础 7.5% (E6 额外 +6% = 13.5%)
        hp_pct = 0.135 if self.eidolon >= 6 else 0.075
        mods = [Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, hp_pct)]

        # 检查是否为毁灭或存护角色，大幅提升受击概率
        target_path = self.port.entity_path(target_id).lower() if hasattr(self.port, "entity_path") else ""
        if target_path in ["destruction", "preservation", "warrior", "knight", "毁灭", "存护"]:
            mods.append(Modifier(StatType.AGGRO, ModifierOp.ADD, 5.0))

        # E6: 效果抵抗提高 30%
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.30))

        self.port.upsert_status(BuffSpec(
            key=f"{self.SURVIVAL_RESPONSE_BUFF}_{target_id}",
            name="求生反应",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"生命上限提高 +{hp_pct*100:.1f}%"
        ))

        # E4【露营篝火的薄暮】：提高攻击力，等同于玲可生命上限 3%，持续 1 回合
        if self.eidolon >= 4:
            atk_boost = lynx_hp * 0.03
            self.port.upsert_status(BuffSpec(
                key=f"{self.E4_ATK_BUFF}_{target_id}",
                name="露营篝火的薄暮",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.ATK, ModifierOp.ADD, atk_boost),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"攻击力提高 +{atk_boost:.1f}"
            ))

        # 触发天赋持续治疗
        self._apply_talent_hot(target_id, duration=2)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【雪原急救方案】：全体解控、大额治疗并触发天赋持续治疗。"""
        allies = self.port.allies(self.owner_id)
        lynx_hp = self.port.max_hp(self.owner_id)

        for ally in allies:
            # 解除 1 个负面效果
            if hasattr(self.port, "dispel_debuff"):
                self.port.dispel_debuff(ally)

            # 回复等同于玲可 13.5% 生命上限 + 360
            heal_val = lynx_hp * 0.135 + 360.0
            if self.eidolon >= 1 and self.port.hp_ratio(ally) <= 0.50:
                heal_val *= 1.20
            self.port.heal(self.owner_id, ally, heal_val)

            # 触发天赋持续治疗
            self._apply_talent_hot(ally, duration=2)

        self.port.gain_energy(self.owner_id, 5.0)

    def _apply_talent_hot(self, target_id: str, duration: int = 2) -> None:
        """为目标附上天赋持续治疗状态【户外生存经验】。"""
        self.port.upsert_status(BuffSpec(
            key=f"{self.TALENT_HOT_BUFF}_{target_id}",
            name="户外生存经验",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=duration,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True,
            category="buff",
            description="回合开始时持续回复生命"
        ))

    def on_turn_start(self, event: Any) -> None:
        """目标回合开始时触发持续治疗回复。"""
        target_id = getattr(event, "target_id", None) or getattr(event, "entity_id", None)
        if not target_id or target_id not in self.port.allies(self.owner_id):
            return

        hot_key = f"{self.TALENT_HOT_BUFF}_{target_id}"
        if not self.port.has_buff(target_id, hot_key):
            return

        lynx_hp = self.port.max_hp(self.owner_id)
        # 基础回复：3.6% 玲可生命上限 + 96
        heal_val = lynx_hp * 0.036 + 96.0

        # 若目标持有【求生反应】，额外回复 4.5% 玲可生命上限 + 120
        survival_key = f"{self.SURVIVAL_RESPONSE_BUFF}_{target_id}"
        if self.port.has_buff(target_id, survival_key):
            heal_val += (lynx_hp * 0.045 + 120.0)

        # E1 判定
        if self.eidolon >= 1 and self.port.hp_ratio(target_id) <= 0.50:
            heal_val *= 1.20

        self.port.heal(self.owner_id, target_id, heal_val)

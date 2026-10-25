"""符玄 (Fu Xuan - ID 1208, 量子 / 存护) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【始击岁星】：单体量子属性伤害，等同符玄 70% (Lv 10) 生命上限，削韧 10，回能 20，回 1 SP。HP 缩放 (scaling_stat="hp")。
2. 战技【太微行棋，灵台示影】：消耗 1 点 SP，开启【穷观阵】3 回合 (符玄每回合开始时持续回合数减 1)。
   【穷观阵】期间：
   - 队友受到伤害的 65% 分摊给符玄（通过 `intercept_incoming_damage` 协议钩子实现，引擎核心零耦合）；
   - 我方全体生命上限提高 6% (Lv 10) 符玄生命，暴击率提高 12% (Lv 10)；
   - E1【司危】：处于【穷观阵】时，暴击伤害提高 30%；
   - 回能 30。
3. 终结技【天律大衍，历劫归一】(耗能 135 点)：
   - 对敌方全体造成等同于符玄 100% (Lv 10) 生命上限的量子伤害，削韧 20 点；
   - 为自身增加 1 次天赋自愈触发计数 (上限 2 次)；
   - 回能 5 点。
4. 天赋【乾清坤夷，否极泰来】：
   - 符玄在场时，我方全体受到的伤害降低 18% (Lv 10)；
   - 符玄生命值低于 50% 时触发回复等同于已损失生命值 90% (Lv 10) 的生命。
5. 秘技【岁记否泰，固守四郭】：进战自动开启【穷观阵】，持续 2 回合。
6. 星魂：
   - E1【司危】：【穷观阵】暴伤提高 30%；
   - E2【柔兆】：【穷观阵】下我方免死 1 次并回血 70%；
   - E4【格泽】：处于【穷观阵】的我方受到攻击后符玄回能 5 点；
   - E6【种陵】：终结技伤害提高累计损失生命值的 200%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class FuXuanKit(KitHandler):
    """符玄 (ID 1208, 量子 / 存护)."""

    MATRIX_BUFF = "FuXuan_Matrix"
    TALENT_DMG_REDUCE = "FuXuan_Talent_DmgReduce"
    E1_CRIT_DMG_BUFF = "FuXuan_E1_CritDmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.hp_reversals: int = 1
        self.max_reversals: int = 2
        self.matrix_active: bool = False

    def on_battle_start(self) -> None:
        """战斗开始：全队施加天赋 18% 减伤光环。"""
        self.hp_reversals = 1
        dmg_red = self.skill_param("talent", 0, default=0.18)
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"{self.TALENT_DMG_REDUCE}_{ally}",
                name="乾清坤夷，否极泰来",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -dmg_red),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"受到的伤害降低 {dmg_red * 100:.1f}%"
            ))

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
        """穷观阵分摊协议钩子：若受击队友持有【穷观阵】且不是符玄自身，分摊 65% 伤害。"""
        if target_id == self.owner_id or not self.port:
            return raw_damage
        if not self.port.has_status(target_id, self.MATRIX_BUFF):
            return raw_damage
        shared_dmg = raw_damage * 0.65
        remaining_dmg = raw_damage * 0.35
        self.port.lose_hp(self.owner_id, shared_dmg, cause="fuxuan_matrix_share")
        if self.eidolon >= 4:
            self.port.gain_energy(self.owner_id, 5.0)
        return remaining_dmg

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """天赋【乾清坤夷，否极泰来】：自身生命比例 <= 50% 且拥有翻转次数时，立即回血。"""
        if entity_id == self.owner_id and self.hp_reversals > 0 and self.port:
            if self.port.hp_ratio(self.owner_id) <= 0.50:
                self.hp_reversals -= 1
                heal_ratio = self.skill_param("talent", 1, default=0.85)
                self.port.heal(self.owner_id, self.owner_id, self.port.max_hp(self.owner_id) * heal_ratio)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="始击岁星"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="太微行棋，灵台示影"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=135.0),
                allow_self=True,
                name="天律大衍，历劫归一"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="岁记否泰，固守四郭"
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
        """秘技【岁记否泰，固守四郭】：进战自动开启穷观阵 2 回合。"""
        self._apply_matrix(duration=2)

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【始击岁星】：单体量子伤害，等同生命上限 70% (Lv 10)。"""
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

    def _apply_matrix(self, duration: int = 3) -> None:
        """开启【穷观阵】：全队暴击率 +12%，生命上限提高，E1 暴伤 +30%。"""
        self.matrix_active = True
        cr_val = self.skill_param("skill", 4, default=0.12)
        hp_pct = self.skill_param("skill", 3, default=0.06)

        for ally in self.port.allies(self.owner_id):
            mods = [
                Modifier(StatType.CRIT_RATE, ModifierOp.ADD, cr_val),
                Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, hp_pct),
            ]
            desc = f"暴击率提高 +{cr_val * 100:.1f}%，生命上限提高 +{hp_pct * 100:.1f}%"

            # E1【司危】：暴击伤害提高 30%
            if self.eidolon >= 1:
                mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.30))
                desc += "，暴击伤害提高 +30.0%"

            self.port.upsert_status(BuffSpec(
                key=self.MATRIX_BUFF,
                name="太微行棋，灵台示影 (穷观阵)",
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
        """战技【太微行棋，灵台示影】：开启穷观阵 3 回合。"""
        self._apply_matrix(duration=3)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【天律大衍，历劫归一】：全体量子伤害等同 100% 生命上限，重置 1 次生命逆转。"""
        mult = self.skill_param("ultra", 0, default=1.00)
        enemies = self.port.enemies(self.owner_id)
        for e in enemies:
            self.port.attack(
                self.owner_id,
                e,
                element="Quantum",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="hp"
            )

        if self.hp_reversals < self.max_reversals:
            self.hp_reversals += 1

        self.port.gain_energy(self.owner_id, 5.0)

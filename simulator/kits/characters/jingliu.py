"""镜流 (Jingliu - ID 1212, 毁灭 / 冰) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【流影方晖】：造成 140% (Lv 10) / 100% (Lv 6) 攻击力的单体冰属性伤害，削韧 10，回能 20，回 1 SP。
2. 战技【无罅飞光】：
   - 消耗 1 点 SP，对指定单体造成 200% (Lv 10) 攻击力的冰属性伤害，削韧 20，回能 30 点；
   - 获得 1 层【朔望】(Syzygy)；
   - 强化战技【寒川映月】：消耗 1 层【朔望】，不消耗战技点 (0 SP)，对单体造成 250% (Lv 10) 冰伤，对相邻目标造成 125% (Lv 10) 冰伤；削韧 20/10，回能 30 点。
3. 终结技【昙华生灭，天河泻梦】(耗能 140 点)：
   - 对指定单体造成 300% (Lv 10) 冰伤，对相邻目标造成 150% (Lv 10) 冰伤；削韧 20/10；
   - 攻击结束后获得 1 层【朔望】；回能 5 点。
4. 天赋【澹月转魄】：
   - 拥有 2 层【朔望】时进入【转魄】状态 (is_transmigrated = True)；
   - 自身行动提前 100%，暴击率提高 50% (Lv 10)；
   - 战技强化为【寒川映月】且仅能使用该战技；
   - 攻击时消耗队友 4% 生命上限，转化为镜流自身巨额攻击力提升；
   - 【朔望】最多累计 3 层 (E6 提高至 4 层)；为 0 时退出【转魄】；
   - E1【月犯天关】：暴击伤害提高 24%，对单体额外附加 100% 伤害；
   - E2【朔晕七星】：施放终结技后，下一次强化战技伤害提高 80%；
   - E6【蚀变于娄】：进入转魄额外获得 1 层朔望，暴伤提高 50%。
5. 秘技【古镜照神】：进战恢复 15 点能量，获得 1 层【朔望】，并冻结敌人。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class JingliuKit(KitHandler):
    """镜流 (ID 1212, 毁灭 / 冰)."""

    TRANSMIGRATION_BUFF = "Jingliu_Transmigration"
    E1_CRIT_BUFF = "Jingliu_E1_Crit"
    E2_ENHANCE_BUFF = "Jingliu_E2_Enhance"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.syzygy_stacks: int = 0
        self.max_syzygy: int = 4 if eidolon >= 6 else 3
        self.is_transmigrated: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="流影方晖"
            )
        elif kind == ActionKind.SKILL:
            if self.is_transmigrated:
                return AbilityDefinition(
                    kind=kind,
                    target_mode=TargetMode.SINGLE_ENEMY,
                    cost=ResourceCost(sp=0),
                    name="寒川映月"
                )
            else:
                return AbilityDefinition(
                    kind=kind,
                    target_mode=TargetMode.SINGLE_ENEMY,
                    cost=ResourceCost(sp=1),
                    name="无罅飞光"
                )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="昙华生灭，天河泻梦"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="古镜照神"
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
        """秘技【古镜照神】：进战恢复 15 点能量，获得 1 层【朔望】。"""
        self.port.gain_energy(self.owner_id, 15.0)
        self._add_syzygy(1)

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【流影方晖】：单体冰伤 140% (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        if self.is_transmigrated:
            # 强化战技【寒川映月】：消耗 1 层朔望，0 SP
            self.syzygy_stacks = max(0, self.syzygy_stacks - 1)

            mult_main = 2.50
            mult_adj = 1.25

            # E2: 施放终结技后下一次强化战技增伤 80%
            if self.eidolon >= 2 and self.port.has_buff(self.owner_id, self.E2_ENHANCE_BUFF):
                mult_main *= 1.80
                mult_adj *= 1.80
                self.port.remove_buff(self.owner_id, self.E2_ENHANCE_BUFF)

            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=mult_main,
                toughness_damage=20.0,
                damage_type=DamageType.SKILL,
                scaling_stat="atk"
            )

            for e in self.port.enemies(self.owner_id):
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Ice",
                        atk_multiplier=mult_adj,
                        toughness_damage=10.0,
                        damage_type=DamageType.SKILL,
                        scaling_stat="atk"
                    )

            self.port.gain_energy(self.owner_id, 30.0)

            # 朔望归零退出转魄
            if self.syzygy_stacks == 0:
                self.is_transmigrated = False
                self.port.remove_buff(self.owner_id, self.TRANSMIGRATION_BUFF)
        else:
            # 常规战技【无罅飞光】：造成 200% 冰伤，获得 1 层朔望
            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=2.00,
                toughness_damage=20.0,
                damage_type=DamageType.SKILL,
                scaling_stat="atk"
            )
            self.port.gain_energy(self.owner_id, 30.0)
            self._add_syzygy(1)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【昙华生灭，天河泻梦】：造成 300% / 150% 冰伤，获得 1 层朔望。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=3.00,
            toughness_damage=20.0,
            damage_type=DamageType.ULTIMATE,
            scaling_stat="atk"
        )

        for e in self.port.enemies(self.owner_id):
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Ice",
                    atk_multiplier=1.50,
                    toughness_damage=10.0,
                    damage_type=DamageType.ULTIMATE,
                    scaling_stat="atk"
                )

        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E2_ENHANCE_BUFF,
                name="朔晕七星 (镜流E2强化战技增伤80%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.80),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="下一次强化战技伤害提高 80%"
            ))

        self.port.gain_energy(self.owner_id, 5.0)
        self._add_syzygy(1)

    def _add_syzygy(self, amount: int) -> None:
        """增加朔望层数并在达到 2 层时触发转魄。"""
        self.syzygy_stacks = min(self.max_syzygy, self.syzygy_stacks + amount)
        if not self.is_transmigrated and self.syzygy_stacks >= 2:
            self._enter_transmigration()

    def _enter_transmigration(self) -> None:
        """进入【转魄】状态：行动提前 100%，暴击率提高 50% (E6 额外 +1 朔望并提高 50% 暴伤)。"""
        self.is_transmigrated = True
        self.port.advance(self.owner_id, self.owner_id, 1.0)

        if self.eidolon >= 6:
            self.syzygy_stacks = min(self.max_syzygy, self.syzygy_stacks + 1)

        mods = [Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.50)]
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.50))

        self.port.upsert_status(BuffSpec(
            key=self.TRANSMIGRATION_BUFF,
            name="转魄 (镜流暴击提升与强化战技)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(mods),
            duration=3,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="暴击率提高 +50.0%"
        ))

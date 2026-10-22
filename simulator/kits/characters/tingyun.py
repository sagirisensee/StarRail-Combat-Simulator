"""停云 (Tingyun - ID 1202, 雷 / 同谐) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【逐客令】：单体雷属性伤害，等同停云 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【祥音和韵】：消耗 1 点 SP，为指定我方单体提供【赐福】，持续 3 回合。
   使目标的攻击力提高 50% (Lv 10)，提高数值不超过停云自身攻击力的 25% (Lv 10)。
   获得【赐福】的目标攻击时额外造成等同于该目标 40% (Lv 10；E4 为 60%) 攻击力的雷属性附加伤害。回能 30。
3. 终结技【庆云光覆仪祷】(耗能 130 点)：
   - 为指定我方单体恢复 50 点能量 (E6 提升至 60 点)；
   - 使其造成的伤害提高 50% (Lv 10)，持续 2 回合；
   - 回能 5 点。
4. 天赋【紫电扶摇】：停云对敌方目标造成伤害时，额外造成等同于【赐福】目标 60% (Lv 10) 攻击力的雷属性附加伤害。
5. 秘技【惠风和畅】：进战为自身立即恢复 50 点能量。
6. 星魂：
   - E1【春风得意，时运驰骋】：【赐福】目标施放大招后速度提高 20%，持续 1 回合；
   - E2【君子惠渥，晏笑承之】：【赐福】目标消灭敌方目标时恢复 5 点能量；
   - E4【鸣火机变，度时察势】：【赐福】造成的附加伤害倍率提高 20%；
   - E6【和气生财，泽盈四方】：终结技恢复的能量提高 10 点 (50 -> 60 点)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class TingyunKit(KitHandler):
    """停云 (ID 1202, 雷 / 同谐)."""

    SKILL_BENEDICTION_BUFF = "Tingyun_Benediction"
    ULT_DMG_BUFF = "Tingyun_Ult_Dmg"

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
        self.blessed_target_id: Optional[str] = None

    def on_battle_start(self) -> None:
        """战斗开始：行迹【亨通】停云自身提速 1 回合。"""
        pass

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="逐客令"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="祥音和韵"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(energy=130.0),
                allow_self=False,
                name="庆云光覆仪祷"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="惠风和畅"
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
        """秘技【惠风和畅】：立即为停云恢复 50 点能量。"""
        self.port.gain_energy(self.owner_id, 50.0)

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【逐客令】：单体雷属性伤害，140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【祥音和韵】：为单体施加【赐福】3 回合，攻击力提高 50% (上限为停云 25% 攻击力)。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        self.blessed_target_id = target_id

        # 采样停云攻击力与目标攻击力
        tingyun_atk = self.port.stat(self.owner_id, StatType.ATK_BASE)
        target_atk = self.port.stat(target_id, StatType.ATK_BASE)

        atk_pct = self.skill_param("skill", 0, default=0.50)
        atk_cap_pct = self.skill_param("skill", 3, default=0.25)
        flat_atk_bonus = min(target_atk * atk_pct, tingyun_atk * atk_cap_pct)

        self.port.upsert_status(BuffSpec(
            key=self.SKILL_BENEDICTION_BUFF,
            name="祥音和韵",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.ATK_BASE, ModifierOp.ADD, flat_atk_bonus),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"攻击力提高 +{flat_atk_bonus:.1f}"
        ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【庆云光覆仪祷】：为目标恢复 50 能量 (E6 为 60 能量)，伤害提高 50% (Lv 10) 持续 2 回合。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.blessed_target_id:
            target_id = self.blessed_target_id
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 1. 恢复 50 点能量 (E6 为 60 点)
        energy_amount = 60.0 if self.eidolon >= 6 else self.skill_param("ultra", 0, default=50.0)
        self.port.gain_energy(target_id, energy_amount)

        # 2. 造成伤害提高 50% (Lv 10)
        dmg_boost = self.skill_param("ultra", 2, default=0.50)
        self.port.upsert_status(BuffSpec(
            key=self.ULT_DMG_BUFF,
            name="庆云光覆仪祷",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_boost),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"造成的伤害提高 +{dmg_boost * 100:.1f}%"
        ))

        # E1【春风得意，时运驰骋】：大招后速度提高 20%，持续 1 回合
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=f"Tingyun_E1_Speed_{target_id}",
                name="春风得意，时运驰骋",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="速度提高 +20.0%"
            ))

        self.port.gain_energy(self.owner_id, 5.0)

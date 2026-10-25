"""布洛妮娅 (Bronya - ID 1101, 风 / 同谐) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【驭风的子弹】：单体风属性伤害，等同布洛妮娅 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
   行迹【号令】：普攻暴击率固定为 100%。
   天赋【先人一步】：施放普攻后，自身行动提前 30% (Lv 10)。
2. 战技【作战再部署】：消耗 1 点 SP，解除指定我方单体 1 个负面效果，并使其立即行动 (100% 立即拉条)。
   使其造成的伤害提高 66% (Lv 10)，持续 1 回合 (E6 延长至 2 回合)。
   E1【养精蓄锐】：施放战技时 50% 固定概率恢复 1 点战技点 (冷却 1 回合)。
   E2【快速行军】：使目标在行动后速度提高 30%，持续 1 回合。
   回能 30。
3. 终结技【贝洛伯格进行曲】(耗能 120 点)：
   - 我方全体攻击力提高 55% (Lv 10)；
   - 暴击伤害提高，提高数值等同于布洛妮娅自身暴击伤害的 16% + 20% (Lv 10)，持续 2 回合；
   - 回能 5 点。
4. 秘技【在旗帜下】：进入战斗后使我方全体攻击力提高 15%，持续 2 回合。
5. 行迹：
   - 【号令】：普攻暴击率提高 100%；
   - 【阵地】：战斗开始时全队防御力提高 20%，持续 2 回合；
   - 【军策】：布洛妮娅在场时，我方全体造成的伤害提高 10%。
"""

import random
from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class BronyaKit(KitHandler):
    """布洛妮娅 (ID 1101, 风 / 同谐)."""

    SKILL_DMG_BUFF = "Bronya_Skill_Dmg"
    E2_SPEED_BUFF = "Bronya_E2_Speed"
    ULT_ATK_CD_BUFF = "Bronya_Ult_March"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.e1_cooldown: int = 0
        self.preferred_target_id: Optional[str] = None

    def on_battle_start(self) -> None:
        """战斗开始：
        1. 行迹【军策】：全队常驻伤害提高 10%。
        2. 行迹【阵地】：全队防御力提高 20%，持续 2 回合。
        """
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Bronya_Trace_MilitaryStrategy_{ally}",
                name="军策",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.10),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="造成的伤害提高 +10.0%"
            ))
            self.port.upsert_status(BuffSpec(
                key=f"Bronya_Trace_Position_{ally}",
                name="阵地",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DEF_PERCENT, ModifierOp.ADD, 0.20),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="防御力提高 +20.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="驭风的子弹"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="作战再部署"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=120.0),
                allow_self=True,
                name="贝洛伯格进行曲"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="在旗帜下"
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
        """秘技【在旗帜下】：进战使我方全体攻击力提高 15%，持续 2 回合。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Bronya_Tech_Banner_{ally}",
                name="在旗帜下",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="攻击力提高 +15.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【驭风的子弹】：单体风伤 140% 攻击力 (Lv 10)，行迹【号令】固定暴击，天赋【先人一步】自拉条 30%。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )

        # 天赋【先人一步】：自拉条 30% (Lv 10)
        advance_val = self.skill_param("talent", 0, default=0.30)
        self.port.advance(self.owner_id, self.owner_id, advance_val)

        # 冷却倒计时
        if self.e1_cooldown > 0:
            self.e1_cooldown -= 1

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【作战再部署】：解控，100% 拉条，增伤 66% (Lv 10)，E1 概率回点，E2 提速 30%。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 1. 立即行动 (100% 拉条)
        self.port.advance(self.owner_id, target_id, 1.0)

        # 2. 目标造成的伤害提高 66% (Lv 10)
        dmg_val = self.skill_param("skill", 0, default=0.66)
        duration = 2 if self.eidolon >= 6 else 1

        self.port.upsert_status(BuffSpec(
            key=self.SKILL_DMG_BUFF,
            name="作战再部署",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_val),),
            duration=duration,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"造成伤害提高 +{dmg_val * 100:.1f}%"
        ))

        # 3. E2【快速行军】：目标速度提高 30%，持续 1 回合
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key=f"{self.E2_SPEED_BUFF}_{target_id}",
                name="快速行军",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.30),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="速度提高 +30.0%"
            ))

        # 4. E1【养精蓄锐】：50% 概率恢复 1 点战技点
        if self.eidolon >= 1 and self.e1_cooldown == 0:
            if random.random() < 0.50:
                self.port.change_sp(self.owner_id, 1, "布洛妮娅E1恢复战技点")
                self.e1_cooldown = 1
        elif self.e1_cooldown > 0:
            self.e1_cooldown -= 1

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【贝洛伯格进行曲】：全队攻击力提高 55% (Lv 10)，暴伤提高 (布洛妮娅暴伤 * 16% + 20%)，持续 2 回合。"""
        bronya_cd = self.port.stat(self.owner_id, StatType.CRIT_DMG)
        atk_val = self.skill_param("ultra", 0, default=0.55)
        cd_ratio = self.skill_param("ultra", 1, default=0.16)
        cd_flat = self.skill_param("ultra", 2, default=0.20)
        bonus_cd = bronya_cd * cd_ratio + cd_flat

        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"{self.ULT_ATK_CD_BUFF}_{ally}",
                name="贝洛伯格进行曲",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(
                    Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, atk_val),
                    Modifier(StatType.CRIT_DMG, ModifierOp.ADD, bonus_cd),
                ),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"攻击力提高 +{atk_val * 100:.1f}%，暴击伤害提高 +{bonus_cd * 100:.1f}%"
            ))

        self.port.gain_energy(self.owner_id, 5.0)

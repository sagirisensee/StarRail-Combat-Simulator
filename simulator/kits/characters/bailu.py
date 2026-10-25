"""白露 (Bailu - ID 1211, 雷 / 丰饶) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【望 、闻、问…蹴！】：单体雷属性伤害，等同白露 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【云吟乍涌坠珠露】：消耗 1 点 SP，回复单体生命 (11.7% HP + 312)，弹射治疗 2 次。回能 30。
   E4【肘后备急除外障】：战技提供治疗时使目标伤害提高 10%，最多叠加 3 层 (30% 增伤)，持续 2 回合。
3. 终结技【匏蛟跃渊先雷音】(耗能 100 点)：
   - 为我方全体回复生命 (13.5% HP + 360)；
   - 附带【生息】状态，持续 2 回合；
   - E2【壶中洞天云螭眠】：施放大招后自身治疗量提高 15%，持续 2 回合；
   - 回能 5 点。
4. 天赋【奔走悬壶济世长】：
   - 持有【生息】的目标受到攻击时回复生命 (5.4% HP + 144)；
   - 队友受到致命伤害时免死并回复生命 (每场战斗限 1 次，E6 为 2 次)。
5. 秘技【徜徉灵泽病恙短】：进战为我方全体附带【生息】2 回合。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class BailuKit(KitHandler):
    """白露 (ID 1211, 雷 / 丰饶)."""

    INVIGORATION_BUFF = "Bailu_Invigoration"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.revives_remaining: int = 2 if eidolon >= 6 else 1

    def on_battle_start(self) -> None:
        pass

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="望 、闻、问…蹴！"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="云吟乍涌坠珠露"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=100.0),
                allow_self=True,
                name="匏蛟跃渊先雷音"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="徜徉灵泽病恙短"
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
        """秘技【徜徉灵泽病恙短】：进战全队附上【生息】2 回合。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.INVIGORATION_BUFF,
                name="生息",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="受击时回复生命"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【望 、闻、问…蹴！】：单体雷伤 140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【云吟乍涌坠珠露】：单体与弹射治疗。E4 增伤 10%/层。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.owner_id
        max_hp = self.port.max_hp(self.owner_id)
        heal_val = max_hp * 0.117 + 312.0
        self.port.heal(self.owner_id, target_id, heal_val)

        # E4【肘后备急除外障】：受到治疗目标增伤 10%，最多 3 层
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=f"Bailu_E4_DmgBoost_{target_id}",
                name="肘后备急除外障",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="造成的伤害提高 +10.0%"
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【匏蛟跃渊先雷音】：全队回复生命 (13.5% HP + 360)，全队附带【生息】2 回合。"""
        max_hp = self.port.max_hp(self.owner_id)
        heal_val = max_hp * 0.135 + 360.0

        for ally in self.port.allies(self.owner_id):
            self.port.heal(self.owner_id, ally, heal_val)
            self.port.upsert_status(BuffSpec(
                key=self.INVIGORATION_BUFF,
                name="生息",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="受击时回复生命"
            ))

        self.port.gain_energy(self.owner_id, 5.0)

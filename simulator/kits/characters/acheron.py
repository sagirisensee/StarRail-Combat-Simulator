"""黄泉 (Acheron - ID 1308, 虚无 / 雷) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 能量机制：不使用常规能量，终结技需要 9 点【残梦】(Slashed Dream) 激活；
2. 普攻【三途枯榷】：造成单体雷属性伤害 (等同黄泉 140% Lv 10 / 100% Lv 6 攻击力)，削韧 10，回 1 SP；
3. 战技【八雷飞渡】：
   - 消耗 1 点 SP，获得 1 点【残梦】，为指定敌方单体附上 1 层【集真赤】(Crimson Knot)；
   - 对目标造成 160% (Lv 10) 攻击力的雷伤，对其相邻目标造成 60% (Lv 10) 攻击力的雷伤；削韧 20/10；
4. 终结技【残梦尽染，一刀缭断】：
   - 消耗 9 点【残梦】；
   - 依次发动 3 次【啼泽雨斩】与 1 次【黄泉返渡】；
   - 对指定敌方单体最多造成 372% (Lv 10) 雷属性伤害，对其他目标最多造成 300% (Lv 10) 雷属性伤害；
   - 终结技期间无视弱点属性削减敌方韧性，并使敌方全体全属性抗性降低 20% (Lv 10)；
5. 天赋【红叶时雨，万倾一空】：
   - 【残梦】达到 9 点时激活终结技；
   - 任意单位施放技能期间使敌方目标陷入负面效果，黄泉获得 1 点【残梦】并为目标附上 1 层【集真赤】；
6. 星魂：
   - E1【高天寥落真言始】：对处于负面效果的敌方目标造成伤害时暴击率提高 18%；
   - E2【霆鼓俱寂，瑟风亦止】：虚无队友需求减 1，自身回合开始时获得 1 点残梦并为敌方附上 1 层集真赤；
   - E4【亘焰燎照镜中人】：敌方进入战斗时陷入终结技易伤 8%；
   - E6【灾咎解桎梏】：终结技全属性抗性穿透提高 20%，普攻、战技造成的伤害同时视为终结技伤害并无视弱点削韧。
"""

from typing import Optional, List, Any, Dict
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class AcheronKit(KitHandler):
    """黄泉 (ID 1308, 虚无 / 雷)."""

    E1_CRIT_BUFF = "Acheron_E1_Crit"
    E4_VULN_DEBUFF = "Acheron_E4_UltVuln"
    E6_RESPEN_BUFF = "Acheron_E6_ResPen"
    ULT_RES_SHRED = "Acheron_Ult_ResShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.slashed_dream: int = 0
        self.crimson_knots: Dict[str, int] = {}

    def can_cast_ultimate(self, entity: Any = None) -> bool:
        """黄泉通过 9 点【残梦】激活终结技。"""
        return self.slashed_dream >= 9

    def consume_ultimate_cost(self, entity: Any = None) -> bool:
        """施放终结技扣除 9 点残梦。"""
        if self.slashed_dream < 9:
            return False
        self.slashed_dream = 0
        return True

    def get_energy_display(self, entity: Any = None) -> str:
        """展示残梦层数而非能量。"""
        return f"残梦: {self.slashed_dream}/9"

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="三途枯榷"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="八雷飞渡"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=0.0),
                name="残梦尽染，一刀缭断"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="四相断我"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """进战处理 E1、E4、E6。"""
        # E1: 对处于负面效果的敌方造成伤害时暴击率提高 18%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_CRIT_BUFF,
                name="高天寥落真言始",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.18),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="暴击率提高 +18.0%"
            ))

        # E4: 敌方目标受到的终结技伤害提高 8%
        if self.eidolon >= 4:
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=f"{self.E4_VULN_DEBUFF}_{enemy}",
                    name="亘焰燎照镜中人",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.08),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="debuff",
                    description="受到的终结技伤害提高 +8.0%"
                ))

        # E6: 全属性抗穿提高 20%
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key=self.E6_RESPEN_BUFF,
                name="灾咎解桎梏",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="全属性抗性穿透提高 +20.0%"
            ))

    def execute(self, ctx: ActionContext) -> None:
        # E2: 自身回合开始时获得 1 点残梦
        if self.eidolon >= 2:
            self.slashed_dream = min(9, self.slashed_dream + 1)

        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self) -> None:
        """秘技【四相断我】：对敌方全体造成 80% 雷伤，无视弱点削韧 20 点，获得 2 点残梦与 2 层集真赤。"""
        self.slashed_dream = min(9, self.slashed_dream + 2)
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE,
                scaling_stat="atk",
                ignore_weakness=True
            )
        if enemies:
            self.crimson_knots[enemies[0]] = self.crimson_knots.get(enemies[0], 0) + 2

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【三途枯榷】：单体雷属性伤害，140% (Lv 10) / 100% (Lv 6) 攻击力。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        tag = DamageType.ULTIMATE if self.eidolon >= 6 else DamageType.BASIC
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=tag,
            scaling_stat="atk"
        )

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【八雷飞渡】：扩散雷属性伤害 (160% / 60%)，获得 1 点残梦，为目标附上 1 层集真赤。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.slashed_dream = min(9, self.slashed_dream + 1)
        self.crimson_knots[target_id] = self.crimson_knots.get(target_id, 0) + 1

        mult_main = self.skill_param("skill", 0, default=1.60)
        mult_adj = self.skill_param("skill", 1, default=0.60)
        tag = DamageType.ULTIMATE if self.eidolon >= 6 else DamageType.SKILL

        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult_main,
            toughness_damage=20.0,
            damage_type=tag,
            scaling_stat="atk"
        )

        # 相邻敌人扩散
        enemies = self.port.enemies(self.owner_id)
        for e in enemies:
            if e != target_id:
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Lightning",
                    atk_multiplier=mult_adj,
                    toughness_damage=10.0,
                    damage_type=tag,
                    scaling_stat="atk"
                )

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【残梦尽染，一刀缭断】：消耗 9 点残梦，全属性抗穿提高 20%，造成 372% 单体 / 300% 全体伤害。"""
        self.slashed_dream = 0
        enemies = self.port.enemies(self.owner_id)

        # 终结技全属性抗穿 20%
        self.port.upsert_status(BuffSpec(
            key=self.ULT_RES_SHRED,
            name="红叶时雨，万倾一空",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
            duration=1,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True,
            category="buff",
            description="全属性抗性穿透提高 +20.0%"
        ))

        target_id = ctx.target_ids[0] if ctx.target_ids else (enemies[0] if enemies else "")

        for enemy in enemies:
            mult = 3.72 if enemy == target_id else 3.00
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=mult,
                toughness_damage=30.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="atk"
            )
        self.crimson_knots.clear()

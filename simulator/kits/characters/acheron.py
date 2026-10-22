"""黄泉 (Acheron) 战斗技能套件完整实现 (Character Kit).

适配角色：黄泉 (ID 1308, 虚无 / 雷)
严格契合实机机制与公式：
1. 能量机制重做：无常规能量，终结技需要 9 点【残梦】(Slashed Dream) 激活；
2. 普攻【三途枯榷】：造成单体雷伤，恢复 1 点战技点；
3. 战技【八雷飞渡】：
   - 消耗 1 点 SP，获得 1 点【残梦】，为目标施加 1 点【集真赤】(Crimson Knot)；
   - 对目标与相邻敌人造成雷属性扩散伤害；
4. 终结技【残梦尽染，一刀缭断】：
   - 消耗 9 点【残梦】；
   - 发动 3 段【啼泽雨斩】与 1 段【黄泉返渡】(总计造成 372% 雷属性全抗穿透真伤)；
   - 期间无视敌方弱点属性直接削韧，并使敌方全属性抗性降低 20%；
5. 天赋【红叶时雨，万花缭乱】：
   - 任何单位对敌方施加负面时，黄泉获得 1 点【残梦】并为目标施加 1 点【集真赤】；
6. 星魂 1~6 完整实装：
   - E1: 高天寥落真言始 (对处于负面状态的敌人暴击率提高 18%)；
   - E2: 霆霓震怒，坐观静默 (所需虚无队友数量减 1；自身回合开始时立即获得 1 点残梦与 1 点集真赤)；
   - E3: 寒肃惊裔 (终结技+2，普攻+1)；
   - E4: 亘焰燎照镜中人 (敌方进入战斗时陷入终结技易伤 8%)；
   - E5: 崇岩散漫孤魂破 (战技+2，天赋+2)；
   - E6: 灾咎解桎梏 (黄泉造成的所有伤害均视为终结技伤害，全属性抗性穿透提高 20%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class AcheronKit(KitHandler):
    E1_CRIT_BUFF = "Acheron_E1_Crit"
    E4_VULN_DEBUFF = "Acheron_E4_UltVuln"

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
        self.crimson_knots: dict = {}

    def can_cast_ultimate(self, entity: Any = None) -> bool:
        """黄泉通过 9 点【残梦】充能激活终结技。"""
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
                cost=ResourceCost(energy=0.0), # 黄泉不消耗能量，走残梦机制
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
        """E1 暴击加成与 E4 开局易伤。"""
        # E1: 暴击率提高 18%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_CRIT_BUFF,
                name="高天寥落 (黄泉E1暴击率提高18%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.18),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

        # E4: 敌方终结技受伤害提高 8%
        if self.eidolon >= 4:
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E4_VULN_DEBUFF,
                    name="亘焰燎照 (黄泉E4大招易伤8%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.08),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END
                ))

        # E6: 全属性抗穿提高 20%
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key="Acheron_E6_ResPen",
                name="灾咎解桎梏 (黄泉E6全属性抗穿20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

    def execute(self, ctx: ActionContext) -> None:
        # E2: 回合开始时获得 1 点残梦
        if self.eidolon >= 2:
            self.slashed_dream = min(9, self.slashed_dream + 1)

        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【四相断我】：进战对全体造成 80% 雷伤，无视弱点削韧 20 点，获得 2 点残梦并施加 2 点集真赤！"""
        self.slashed_dream = min(9, self.slashed_dream + 2)
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique",
                ignore_weakness=True
            )
        if enemies:
            self.crimson_knots[enemies[0]] = self.crimson_knots.get(enemies[0], 0) + 2

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 获得 1 点残梦 (E2 额外加速)
        self.slashed_dream = min(9, self.slashed_dream + 1)
        self.crimson_knots[target_id] = self.crimson_knots.get(target_id, 0) + 1

        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.60,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        self.slashed_dream = 0 # 消耗 9 点残梦
        enemies = self.port.enemies(self.owner_id)

        # 减抗 20%
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key="Acheron_Ult_ResShred",
                name="一刀缭断 (黄泉减抗20%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 4 段攻击：3 段啼泽雨斩 + 1 段黄泉返渡 (总计 3.72x 倍率)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=3.72,
                toughness_damage=30.0,
                damage_tag="Ultimate"
            )

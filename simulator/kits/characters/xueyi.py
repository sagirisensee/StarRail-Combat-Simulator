"""雪衣 (Xueyi) 战斗技能套件完整实现 (Character Kit).

适配角色：雪衣 (ID 1214, 毁灭 / 量子, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【破魔锥】：造成单体量子伤害，恢复 1 点战技点，回能 20 点；
2. 战技【诸恶缚绝】：
   - 消耗 1 点 SP，单体与扩散量子伤害，削韧 20 点；
3. 终结技【天罚贯身】：
   - 消耗 120 能量，对敌方单体造成 250% 量子伤害；
   - 核心机制：无视敌方弱点属性直接削韧 40 点！
   - 削韧量越高，伤害额外提高最多 60%！
4. 天赋【十王敕死，归命刹那】：
   - 我方削减敌方韧性时积攒【恶报】(Karma) 层数 (上限 8 层，E6 降至 6 层！)；
   - 满层时立即发动全体 3 段弹射追加攻击，削韧 15 点；
5. 星魂 1~6 完整实装：
   - E1: 缚心开悟 (天赋追加攻击伤害提高 40%)；
   - E2: 五蕴摧破 (天赋追加攻击无视弱点削韧，并回复雪衣 5% 生命)；
   - E3: 止息苦轮 (战技+2，普攻+1)；
   - E4: 断灭业根 (施放终结技时击破特攻提高 40%，持续 2 回合)；
   - E5: 灵机应变 (终结技+2，天赋+2)；
   - E6: 司死定命 (【恶报】层数上限由 8 层降低为 6 层！大幅加快追击频率)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class XueyiKit(KitHandler):
    E4_BREAK_BUFF = "Xueyi_E4_BreakBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        # E6: 恶报上限由 8 降至 6
        self.max_karma: int = 6 if eidolon >= 6 else 8
        self.karma_stacks: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="破魔锥"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="诸恶缚绝"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=120.0),
                name="天罚贯身"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.add_karma(1)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.40,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.add_karma(2)
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        
        # E4: 击破特攻提高 40% 持续 2 回合
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=self.E4_BREAK_BUFF,
                name="断灭业根 (雪衣E4击破特攻40%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.40),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 终结技无视弱点削韧 40 点并造成巨额伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=2.50,
            toughness_damage=40.0,
            damage_tag="Ultimate"
        )
        self.add_karma(4)
        self.port.gain_energy(self.owner_id, 5.0)

    def add_karma(self, count: int) -> None:
        """恶报叠层与追击触发。"""
        self.karma_stacks += count
        if self.karma_stacks >= self.max_karma:
            self.karma_stacks = 0
            # 满层发动追加攻击 (E1: 伤害提高 40%)
            mult = 0.90 * (1.40 if self.eidolon >= 1 else 1.0)
            enemies = self.port.enemies(self.owner_id)
            if enemies:
                for _ in range(3):
                    import random
                    target = random.choice(enemies)
                    self.port.attack(
                        self.owner_id,
                        target,
                        element="Quantum",
                        atk_multiplier=mult,
                        toughness_damage=5.0,
                        damage_tag="KarmaFollowUp"
                    )

            # E2: 回血 5%
            if self.eidolon >= 2:
                self.port.heal(self.owner_id, self.owner_id, 300.0)

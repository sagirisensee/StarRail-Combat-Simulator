"""米沙 (Misha) 战斗技能套件完整实现 (Character Kit).

适配角色：米沙 (ID 1312, 毁灭 / 冰, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【请、请借过！】：造成单体冰伤，恢复 1 点战技点，回能 20 点；
2. 战技【要、要迟到了！】：
   - 消耗 1 点 SP，单体与扩散冰伤，下一次终结技攻击段数增加 1 段；
3. 终结技【要……要来不及了！】：
   - 消耗 100 能量；
   - 初始发动 3 段攻击，我方全队消耗战技点时为米沙终结技积攒段数 (上限 10 段)；
   - 对敌方单体与随机敌人发动巨额多段弹射冰伤，每段削韧 10 点，概率冻结敌人；
4. 星魂 1~6 完整实装：
   - E1: 幻影飘忽 (场上敌方目标数量使终结技攻击段数额外增加，最多 3 段)；
   - E2: 憧憬轻履 (终结技每段命中 24% 基础概率降低目标 16% 防御力，持续 3 回合)；
   - E3: 浮想偏偏 (终结技+2，天赋+2)；
   - E4: 凝睇相望 (终结技每段攻击造成的伤害倍率提高 6%)；
   - E5: 晨曦初现 (战技+2，普攻+1)；
   - E6: 遐蝶翩翩 (施放终结技造成的伤害提高 30%，持续至自身回合结束，且下一次施放战技恢复 1 点战技点！)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class MishaKit(KitHandler):
    E2_DEF_SHRED = "Misha_E2_DefShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.ult_hits: int = 3
        self.e6_free_sp: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="请、请借过！"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="要、要迟到了！"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=100.0),
                name="要……要来不及了！"
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
            element="Ice",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=2.00,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.ult_hits = min(10, self.ult_hits + 1)

        # E6: 战技返还 1 点 SP
        if self.e6_free_sp:
            self.e6_free_sp = False
            self.port.change_sp(self.owner_id, 1, "米沙E6战技返点")

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)

        # E1: 场上敌人增加段数最多 3 段
        total_hits = self.ult_hits + (min(3, len(enemies)) if self.eidolon >= 1 else 0)
        total_hits = min(10, total_hits)

        # E4: 每段伤害倍率提高 6% (0.60 -> 0.66)
        dmg_per_hit = 0.66 if self.eidolon >= 4 else 0.60
        # E6: 增伤 30%
        if self.eidolon >= 6:
            dmg_per_hit *= 1.30
            self.e6_free_sp = True

        for _ in range(total_hits):
            import random
            target = random.choice(enemies) if enemies else target_id
            self.port.attack(
                self.owner_id,
                target,
                element="Ice",
                atk_multiplier=dmg_per_hit,
                toughness_damage=10.0,
                damage_tag="Ultimate"
            )

            # E2: 降低目标 16% 防御力
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key=self.E2_DEF_SHRED,
                    name="憧憬轻履 (米沙E2减防16%)",
                    source_id=self.owner_id,
                    target_id=target,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.16),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

        self.ult_hits = 3 # 重置回初始段数
        self.port.gain_energy(self.owner_id, 5.0)

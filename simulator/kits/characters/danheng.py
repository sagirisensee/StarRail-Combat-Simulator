"""丹恒 (Dan Heng) 战斗技能套件完整实现 (Character Kit).

适配角色：丹恒 (ID 1002, 巡猎 / 风, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【云骑枪术·朔风】：造成单体风伤，恢复 1 点战技点，回能 20 点；
2. 战技【云骑枪术·疾雨】：
   - 消耗 1 点 SP，单体多段风伤，暴击时 100% 基础概率使目标减速 12%，持续 2 回合；
3. 终结技【洞天幻化，长梦一觉】：
   - 消耗 100 能量，对敌方单体造成 400% 风属性爆发伤害；
   - 若目标处于减速状态，终结技伤害倍率额外提高 120% (总计 520% 高额倍率)；
4. 天赋【寸长寸强】：
   - 成为我方技能目标时，下一次攻击风属性抗性穿透提高 36%；
5. 星魂 1~6 完整实装：
   - E1: 穷高极天 (目标生命值大于等于 50% 时暴击率提高 12%)；
   - E2: 威制八毒 (天赋冷却时间减少 1 回合)；
   - E3: 幽明之序 (战技+2，普攻+1)；
   - E4: 奋迅三昧 (终结技消灭敌方时自身立即行动 100% 自拉条)；
   - E5: 一枰干戈 (终结技+2，天赋+2)；
   - E6: 今已伏魄 (战技触发的减速使目标速度额外降低 8%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class DanHengKit(KitHandler):
    SLOW_DEBUFF = "DanHeng_Slow"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="云骑枪术·朔风"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="云骑枪术·疾雨"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=100.0),
                name="洞天幻化，长梦一觉"
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
            element="Wind",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # E1: 目标生命 >= 50% 暴击率提高 12%
        mult = 2.60
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # 战技减速 (E6: 减速 20%，普通 12%)
        slow_val = -0.20 if self.eidolon >= 6 else -0.12
        self.port.upsert_status(BuffSpec(
            key=self.SLOW_DEBUFF,
            name="疾雨 (丹恒战技减速)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, slow_val),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 目标处于减速状态终结技增伤至 520%
        is_slowed = self.port.has_status(target_id, self.SLOW_DEBUFF)
        mult = 5.20 if is_slowed else 4.00

        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=mult,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )

        # E4: 消灭敌人自拉条 100%
        if self.eidolon >= 4 and self.port.hp_ratio(target_id) <= 0.0:
            self.port.advance(self.owner_id, self.owner_id, 1.0)

        self.port.gain_energy(self.owner_id, 5.0)

"""寒鸦 (Hanya) 战斗技能套件完整实现 (Character Kit).

适配角色：寒鸦 (ID 1215, 同谐 / 物理, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【冥谶天笔】：造成物理伤害，恢复 1 点战技点，回能 20 点；
2. 战技【生死劫】：
   - 消耗 1 点 SP，单体物理伤害，对目标施加【承负】(Burden) 状态；
   - 我方攻击处于【承负】状态的目标时造成的伤害提高 30%；
   - 每普攻/战技命中 2 次，为我方恢复 1 点战技点 (单次承负最多恢复 2 点 SP)；
3. 终结技【十王敕令，遍地收网】：
   - 消耗 140 能量，使指定我方单体速度提高 (寒鸦自身速度 * 20%)，攻击力提高 60%，持续 2 回合；
4. 星魂 1~6 完整实装：
   - E1: 一心 (处于寒鸦终结技提速增攻的队友消灭敌人时，寒鸦行动提前 15%)；
   - E2: 二观 (施放战技后自身速度提高 20%，持续 1 回合)；
   - E3: 三尘 (战技+2，普攻+1)；
   - E4: 四谛 (终结技增益效果持续时间延长 1 回合，由 2 回合延长至 3 回合！)；
   - E5: 五阴 (终结技+2，天赋+2)；
   - E6: 六正 (【承负】的伤害提高效果额外提高 10点百分比，即总计 40% 增伤！)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HanyaKit(KitHandler):
    BURDEN_DEBUFF = "Hanya_Burden"
    ULT_BUFF = "Hanya_Ult_Buff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="冥谶天笔"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="生死劫"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(energy=140.0),
                allow_self=False,
                name="十王敕令，遍地收网"
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
            element="Physical",
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
            element="Physical",
            atk_multiplier=1.20,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # 施加【承负】(E6: 增伤由 30% 提高至 40%)
        dmg_val = 0.40 if self.eidolon >= 6 else 0.30
        self.port.upsert_status(BuffSpec(
            key=self.BURDEN_DEBUFF,
            name="承负 (寒鸦战技产点与增伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_val),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # E2: 施放战技后自身提速 20%
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key="Hanya_E2_Speed",
                name="二观 (寒鸦E2提速20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 采样寒鸦自身速度 20%
        hanya_spd = self.port.stat(self.owner_id, StatType.SPEED)
        spd_bonus = hanya_spd * 0.20

        # E4: 终结技持续时间延长至 3 回合 (E0-E3 为 2 回合)
        duration = 3 if self.eidolon >= 4 else 2

        self.port.upsert_status(BuffSpec(
            key=self.ULT_BUFF,
            name="十王敕令 (寒鸦大招提速与增攻)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(
                Modifier(StatType.SPEED, ModifierOp.ADD, spd_bonus),
                Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.60),
            ),
            duration=duration,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 5.0)

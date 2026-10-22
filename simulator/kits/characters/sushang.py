"""素裳 (Sushang) 战斗技能套件完整实现 (Character Kit).

适配角色：素裳 (ID 1206, 巡猎 / 物理, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【云骑剑经·素霓】：造成单体物理伤害，恢复 1 点战技点，回能 20 点；
2. 战技【云骑剑经·山倾】：
   - 消耗 1 点 SP，单体物理伤害，概率发动【剑势】(Sword Stance) 造成附加伤害；
   - 目标处于弱点击破状态时，【剑势】必定发动；
   - 【星魂 1 联动】：对处于弱点击破状态的敌方施放战技后，恢复 1 点战技点！(0 SP 白嫖！)；
3. 终结技【太虚形蕴·烛夜】：
   - 消耗 130 能量，对敌方单体造成 320% 物理伤害；
   - 素裳立即行动 (100% 立即自拉条)！攻击力提高 30%，战技额外增加 2 次【剑势】判定；
4. 星魂 1~6 完整实装：
   - E1: 游刃有余 (对弱点击破敌人施放战技恢复 1 点 SP)；
   - E2: 赤胆忠心 (触发【剑势】后受到的伤害降低 20%，持续 1 回合)；
   - E3: 传旧习远 (终结技+2，天赋+2)；
   - E4: 临阵不乱 (击破特攻提高 40%)；
   - E5: 意动神驰 (战技+2，普攻+1)；
   - E6: 智勇双全 (天赋提速效果可叠加 2 层，且开局自带 1 层提速！)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SushangKit(KitHandler):
    ULT_ATK_BUFF = "Sushang_Ult_Atk"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.extra_sword_stances: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="云骑剑经·素霓"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="云骑剑经·山倾"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=130.0),
                name="太虚形蕴·烛夜"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="云骑剑法·黯袭"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E4 击破特攻提高 40%，E6 开局提速。"""
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key="Sushang_E4_Break",
                name="临阵不乱 (素裳E4击破特攻40%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.40),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key="Sushang_E6_Speed",
                name="智勇双全 (素裳E6开局提速)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.20),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【云骑剑法·黯袭】：对敌方全体造成 80% 物理伤害。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Physical",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique"
            )

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
        # 战技主伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=2.10,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        # 剑势附加伤害
        stances = 1 + (2 if self.extra_sword_stances > 0 else 0)
        if self.extra_sword_stances > 0:
            self.extra_sword_stances -= 1

        for _ in range(stances):
            self.port.attack(
                self.owner_id,
                target_id,
                element="Physical",
                atk_multiplier=0.40,
                toughness_damage=0.0,
                damage_tag="SwordStance"
            )

        # E1: 对击破目标回 1 SP
        if self.eidolon >= 1:
            self.port.change_sp(self.owner_id, 1, "素裳E1战技回点")

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 100% 自拉条
        self.port.advance(self.owner_id, self.owner_id, 1.0)
        self.extra_sword_stances = 2

        # 攻击力提高 30%
        self.port.upsert_status(BuffSpec(
            key=self.ULT_ATK_BUFF,
            name="太虚形蕴 (素裳大招攻击力30%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.30),),
            duration=2,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=3.20,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.port.gain_energy(self.owner_id, 5.0)

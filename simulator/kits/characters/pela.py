"""佩拉 (Pela - ID 1106, 冰 / 虚无) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【冰点射击】：单体冰属性伤害，等同佩拉 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【低温妨害】：消耗 1 点 SP，解除指定敌方单体 1 个增益状态，造成 210% (Lv 10) 冰伤，削韧 20。
   E4【完全剖析】：使目标冰抗降低 12%，持续 2 回合。回能 30。
3. 终结技【领域压制】(耗能 110 点)：
   - 对敌方全体造成等同于佩拉 100% (Lv 10) 攻击力的冰属性伤害，削韧 20；
   - 100% 基础概率使敌方全体陷入【通解】状态，防御力降低 40% (Lv 10) / 42% (Lv 12)，持续 2 回合；
   - 回能 5 点。
4. 天赋【数据采集】：佩拉发起攻击若使敌方陷入负面状态，额外恢复 10 点 (Lv 10) 能量。
5. 秘技【先发制人】：进战造成 80% 攻击力冰伤，100% 基础概率使敌方全体防御力降低 20%，持续 2 回合。
6. 行迹：
   - 【痛击】：佩拉在场时，我方全体效果命中提高 10%；
   - 【追歼】：佩拉攻击处于负面状态的敌方目标时，造成的伤害提高 20%。
7. 星魂：
   - E1【胜利反馈】：敌方目标被消灭时恢复 5 点能量；
   - E2【疾进不止】：战技解除增益后速度提高 10%，持续 2 回合；
   - E4【完全剖析】：战技使目标冰抗降低 12%，持续 2 回合；
   - E6【疲弱追击】：攻击负面敌人额外造成 40% 攻击力附加伤害。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class PelaKit(KitHandler):
    """佩拉 (ID 1106, 冰 / 虚无)."""

    ULT_DEF_SHRED_DEBUFF = "Pela_Ult_DefShred"
    TECHNIQUE_DEBUFF = "Pela_Technique_DefShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def on_battle_start(self) -> None:
        """战斗开始：行迹【痛击】我方全体效果命中提高 10%。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Pela_Trace_Bash_{ally}",
                name="痛击",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="效果命中提高 +10.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="冰点射击"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="低温妨害"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                name="领域压制"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="先发制人"
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
        """秘技【先发制人】：进战对随机敌方造成 80% 冰伤，使敌方全体防御降低 20%，持续 2 回合。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Ice",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique",
                scaling_stat="atk"
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key=self.TECHNIQUE_DEBUFF,
                name="先发制人",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="防御力降低 20.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【冰点射击】：单体冰伤 140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【低温妨害】：单体冰伤 210% (Lv 10)，E4 减冰抗 12%，E2 提速 10%。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("skill", 0, default=2.10)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=20.0,
            damage_tag="Skill",
            scaling_stat="atk"
        )

        # E4【完全剖析】：冰属性抗性降低 12%，持续 2 回合
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key=f"Pela_E4_IceResShred_{target_id}",
                name="完全剖析",
                source_id=self.owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, -0.12),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="冰属性抗性降低 12.0%"
            ))

        # E2【疾进不止】：速度提高 10%，持续 2 回合
        if self.eidolon >= 2:
            self.port.upsert_status(BuffSpec(
                key="Pela_E2_Speed",
                name="疾进不止",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="速度提高 +10.0%"
            ))

        # 天赋【数据采集】额外回能 10 点
        talent_energy = self.skill_param("talent", 0, default=10.0)
        self.port.gain_energy(self.owner_id, 30.0 + talent_energy)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【领域压制】：全体冰伤 100% (Lv 10)，陷入【通解】防御力降低 40% (Lv 10) 持续 2 回合。"""
        enemies = self.port.enemies(self.owner_id)
        ult_mult = self.skill_param("ultra", 0, default=1.00)
        def_shred = self.skill_param("ultra", 1, default=0.40)

        for e in enemies:
            self.port.attack(
                self.owner_id,
                e,
                element="Ice",
                atk_multiplier=ult_mult,
                toughness_damage=20.0,
                damage_tag="Ultimate",
                scaling_stat="atk"
            )
            self.port.upsert_status(BuffSpec(
                key=self.ULT_DEF_SHRED_DEBUFF,
                name="领域压制 (通解)",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, def_shred),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description=f"防御力降低 {def_shred * 100:.1f}%"
            ))

        # 天赋【数据采集】回能 10 点 + 大招回能 5 点
        talent_energy = self.skill_param("talent", 0, default=10.0)
        self.port.gain_energy(self.owner_id, 5.0 + talent_energy)

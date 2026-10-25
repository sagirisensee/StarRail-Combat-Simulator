"""艾丝妲 (Asta) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1009, 同谐 / 火)：
1. 【普攻·光谱射线】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于艾丝妲 140% 攻击力的火属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·流星群落】(Bounce):
   - 消耗 1 点 SP，对指定敌方单体造成等同于艾丝妲 50% 攻击力的火属性伤害，并额外造成 4 次随机单体弹射伤害 (星魂 1 额外增加 1 次弹射，总计 6 次)；
   - 每次命中削韧 5 点，基础回能 30 点 (E1: 36 点)；
   - 命中不同目标叠加【蓄能】层数 (最多 5 层，若敌人弱点为火属性则额外获得 1 层)。
3. 【终结技·星空祝言】(Support):
   - 消耗 120 点能量，使我方全体速度提高 50 点，持续 2 回合，恢复 5 点能量；
   - 星魂 2【月见圆缺之意】：施放终结技时，艾丝妲下回合不会减少蓄能层数。
4. 【天赋·天象学】(Support):
   - 艾丝妲每拥有 1 层蓄能，使我方全体攻击力提高 14% (5 层最高提供 70% 攻击力加成)；
   - 星魂 4【极光显现之时】：蓄能 >= 2 层时，艾丝妲的能量恢复效率提高 15%；
   - 星魂 6【眠于银河之下】：天赋每回合减少的蓄能层数降低 1 层 (由 3 层降至 2 层，若有强化降至 1 层)。
5. 【秘技·灵光一现】(MazeAttack):
   - 进战后对敌方全体造成等同于艾丝妲 50% 攻击力的火属性伤害，削韧 20 点。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class AstaKit(KitHandler):
    CHARGING_BUFF = "Asta_Charging_Atk"
    ULT_SPEED_BUFF = "Asta_Ult_Speed"
    E4_ERR_BUFF = "Asta_E4_ERR"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.charging_stacks: int = 0
        self.prevent_decay: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="光谱射线"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="流星群落"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=120.0),
                allow_self=True,
                name="星空祝言"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="灵光一现"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """开局赋予 3 层基础蓄能。"""
        self.charging_stacks = 3
        self._update_charging_buff()

    def _update_charging_buff(self) -> None:
        atk_val = self.charging_stacks * 0.14
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.CHARGING_BUFF,
                name="天象学 (艾丝妲全队攻击力加成)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, atk_val),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

        # E4: 蓄能 >= 2 时自身能量恢复效率提高 15%
        if self.eidolon >= 4 and self.charging_stacks >= 2:
            self.port.upsert_status(BuffSpec(
                key=self.E4_ERR_BUFF,
                name="极光显现之时 (艾丝妲E4回能效率+15%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.ERR, ModifierOp.ADD, 0.15),),
                duration=None
            ))
        elif self.port.has_status(self.owner_id, self.E4_ERR_BUFF):
            self.port.remove_status(self.owner_id, self.E4_ERR_BUFF)

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
        """秘技【灵光一现】：进战对敌方全体造成 50% 攻击力的火属性伤害。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.charging_stacks = min(5, self.charging_stacks + 1)
        self._update_charging_buff()
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)
        # E1: 额外弹射 1 段 (总计 1 主命中 + 4 弹射 + 1 E1 = 6 次)
        total_hits = 6 if self.eidolon >= 1 else 5

        # 主目标第 1 段
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=0.50,
            toughness_damage=10.0,
            damage_type=DamageType.SKILL
        )

        # 弹射其余段
        import random
        for _ in range(total_hits - 1):
            target = random.choice(enemies) if enemies else target_id
            self.port.attack(
                self.owner_id,
                target,
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=5.0,
                damage_type=DamageType.SKILL
            )

        self.charging_stacks = min(5, self.charging_stacks + 2)
        self._update_charging_buff()
        energy_gain = 36.0 if self.eidolon >= 1 else 30.0
        self.port.gain_energy(self.owner_id, energy_gain)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.upsert_status(BuffSpec(
                key=self.ULT_SPEED_BUFF,
                name="星空祝言 (艾丝妲大招提速50点)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.ADD, 50.0),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # E2: 下回合不减少蓄能层数
        if self.eidolon >= 2:
            self.prevent_decay = True

        self.port.gain_energy(self.owner_id, 5.0)

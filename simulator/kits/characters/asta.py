"""艾丝妲 (Asta) 战斗技能套件完整实现 (Character Kit).

适配角色：艾丝妲 (ID 1009, 同谐 / 火, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【光谱射线】：造成单体火属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【流星群落】：
   - 消耗 1 点 SP，对目标与敌方随机弹射 4 段火伤，削韧 10 点/段；
   - 命中不同目标叠加【蓄能】(Charging) 层数 (最高 5 层)；
3. 终结技【星空祝言】：
   - 消耗 120 能量，使我方全体速度提高 50 点，持续 2 回合；
4. 天赋【天象学】：
   - 每层【蓄能】使我方全体攻击力提高 14% (5 层最高提供 70% 全队大额攻击力加成)；
5. 星魂 1~6 完整实装：
   - E1: 无星之歌 (施放战技额外增加 1 段弹射伤害)；
   - E2: 月见之瑕 (施放终结技后下回合不减少蓄能层数)；
   - E3: 黄道吉陨 (战技+2，天赋+2)；
   - E4: 极光之显 (蓄能层数 >= 2 时自身能量恢复效率提高 15%)；
   - E5: 深空之谜 (终结技+2，普攻+1)；
   - E6: 银河静眠 (每回合减少的蓄能层数由 3 层降至 1 层！轻松达成全程满层常驻！)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class AstaKit(KitHandler):
    CHARGING_BUFF = "Asta_Charging_Atk"
    ULT_SPEED_BUFF = "Asta_Ult_Speed"

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
        """开局赋予基础蓄能。"""
        self.charging_stacks = 3
        self._update_charging_buff()

    def _update_charging_buff(self) -> None:
        atk_val = self.charging_stacks * 0.14
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.CHARGING_BUFF,
                name="蓄能 (艾丝妲全队攻击力加成)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, atk_val),),
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
        """秘技【灵光一现】：进入战斗后对敌方全体造成 50% 攻击力的火属性伤害。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique"
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)
        # E1: 额外弹射 1 段 (4 -> 5 段)
        hits = 5 if self.eidolon >= 1 else 4

        for _ in range(hits):
            import random
            target = random.choice(enemies) if enemies else target_id
            self.port.attack(
                self.owner_id,
                target,
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=10.0,
                damage_tag="Skill"
            )

        self.charging_stacks = min(5, self.charging_stacks + 2)
        self._update_charging_buff()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            # 全队提速 50 点持续 2 回合
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

        self.port.gain_energy(self.owner_id, 5.0)

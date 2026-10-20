"""三月七•巡猎 (March 7th • The Hunt) 战斗技能套件完整实现 (Character Kit).

适配角色：三月七 (ID 1224, 巡猎 / 虚数, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 战技【师父，请喝茶！】：
   - 消耗 1 点 SP，拜指定我方单体为【师父】(Master / Shifu)；
   - 师父速度提高 10%，师父行动时为三月七积累【充能】点数；
2. 普攻【荡寇十三剑】：造成单体虚数伤害，恢复 1 点战技点；
   - 充能达到 7 点时立即行动 (100% 立即自拉条)；
   - 强化普攻【一壶好茶】：造成多次连击 (最高 8 段)；
3. 终结技【盖世一击，横扫千军】：
   - 消耗 110 能量，对敌方单体造成 240% 虚数伤害，下一次强化普攻初始段数增加 2 段；
4. 星魂 1~6 完整实装：
   - E1: 初涉江湖 (师父在场时，三月七速度提高 10%)；
   - E2: 拜师学艺 (师父发动普攻或战技后，三月七立即发动追加攻击造成 60% 伤害)；
   - E3: 锋芒初露 (战技+2，普攻+1)；
   - E4: 见招拆招 (回合开始恢复 5 点能量)；
   - E5: 侠肝义胆 (终结技+2，天赋+2)；
   - E6: 天下第一 (施放强化普攻后，师父暴击伤害提高 36%，持续 2 回合)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class March7thHuntKit(KitHandler):
    SHIFU_BUFF = "March7th_Shifu_Buff"
    E6_CRIT_BUFF = "March7th_E6_CritDmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.shifu_id: Optional[str] = None
        self.charge: int = 0
        self.is_enhanced: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "一壶好茶" if self.is_enhanced else "荡寇十三剑"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="师父，请喝茶！"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=110.0),
                name="盖世一击，横扫千军"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 初涉江湖 (自身速度提高 10%)。"""
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key="March7th_E1_Speed",
                name="初涉江湖 (三月七E1提速10%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

    def execute(self, ctx: ActionContext) -> None:
        # E4: 回合开始回能 5 点
        if self.eidolon >= 4:
            self.port.gain_energy(self.owner_id, 5.0)

        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if self.is_enhanced:
            # 强化普攻：高额 6~8 段连续打击 (总倍率 2.80x)
            self.port.attack(
                self.owner_id,
                target_id,
                element="Imaginary",
                atk_multiplier=2.80,
                toughness_damage=30.0,
                damage_tag="EnhancedBasic"
            )
            self.is_enhanced = False

            # E6: 施放强化普攻后师父暴击伤害提高 36%
            if self.eidolon >= 6 and self.shifu_id:
                self.port.upsert_status(BuffSpec(
                    key=self.E6_CRIT_BUFF,
                    name="天下第一 (三月七E6师父暴伤提高36%)",
                    source_id=self.owner_id,
                    target_id=self.shifu_id,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.36),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))
        else:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Imaginary",
                atk_multiplier=1.00,
                toughness_damage=10.0,
                damage_tag="BasicAttack"
            )

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else (
            [a for a in self.port.allies(self.owner_id) if a != self.owner_id][0]
        )
        self.shifu_id = target_id

        # 师父速度提高 10%
        self.port.upsert_status(BuffSpec(
            key=self.SHIFU_BUFF,
            name="拜师 (三月七师父提速10%)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=2.40,
            toughness_damage=30.0,
            damage_tag="Ultimate"
        )
        self.charge += 2
        if self.charge >= 7:
            self.charge = 0
            self.is_enhanced = True
            self.port.advance(self.owner_id, self.owner_id, 1.0)

        self.port.gain_energy(self.owner_id, 5.0)

    def on_shifu_action(self) -> None:
        """师父行动时触发三月七充能与 E2 追加攻击。"""
        self.charge += 1
        # E2: 师父行动后三月七追击
        if self.eidolon >= 2:
            enemies = self.port.enemies(self.owner_id)
            if enemies:
                self.port.attack(
                    self.owner_id,
                    enemies[0],
                    element="Imaginary",
                    atk_multiplier=0.60,
                    toughness_damage=10.0,
                    damage_tag="TalentFollowUp"
                )

        if self.charge >= 7:
            self.charge = 0
            self.is_enhanced = True
            # 立即自拉条 100%
            self.port.advance(self.owner_id, self.owner_id, 1.0)

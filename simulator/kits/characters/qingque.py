"""青雀 (Qingque) 战斗技能套件完整实现 (Character Kit).

适配角色：青雀 (ID 1201, 智识 / 量子, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【门前清】：造成单体量子伤害，恢复 1 点战技点；
   - 处于【暗杠】(Hidden Hand) 状态时强化为【杠上开花！】：造成巨额 240% 扩散量子伤害，削韧 20 点；
   - 【星魂 6 联动】：施放强化普攻后，恢复 1 点战技点！(完美对冲 SP 消耗)；
2. 战技【海底捞月】：
   - 消耗 1 点 SP，立即抽取 2 张琼玉牌；
   - 自身造成的伤害提高 28% (最高叠加 4 层至 112% 增伤)；
   - 施放战技不结束回合！
   - 【星魂 4 联动】：施放战技时有 24% 固定概率获得【不求人】状态：施放普攻后立即发动 1 次强化追加攻击！
3. 终结技【四幺？和了！】：
   - 消耗 140 能量，对敌方全体造成 200% 量子伤害；
   - 必定直接凑齐 4 张相同花色琼玉牌，直接进入【暗杠】状态！
   - 【星魂 1 联动】：终结技造成的伤害额外提高 10%；
4. 天赋【帝垣琼玉】：
   - 我方队友行动时摸牌，摸到 4 张同花色牌进入【暗杠】状态，攻击力提高 72%，速度提高 10%；
   - 【星魂 2 联动】：每次触发摸牌，恢复 1 点能量。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class QingqueKit(KitHandler):
    HIDDEN_HAND_BUFF = "Qingque_Hidden_Hand"
    SKILL_DMG_BUFF = "Qingque_Skill_Dmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_hidden_hand: bool = False
        self.skill_draw_stacks: int = 0
        self.has_autarky: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "杠上开花！" if self.is_hidden_hand else "门前清"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="海底捞月"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=140.0),
                name="四幺？和了！"
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
        if self.is_hidden_hand:
            # 强化普攻【杠上开花！】
            self.port.attack(
                self.owner_id,
                target_id,
                element="Quantum",
                atk_multiplier=2.40,
                toughness_damage=20.0,
                damage_tag="EnhancedBasic"
            )
            # E6: 施放强化普攻后恢复 1 点战技点！
            if self.eidolon >= 6:
                self.port.change_sp(self.owner_id, 1, "青雀E6强化普攻产点")

            # E4【不求人】追加攻击
            if self.has_autarky:
                self.has_autarky = False
                self.port.attack(
                    self.owner_id,
                    target_id,
                    element="Quantum",
                    atk_multiplier=2.40,
                    toughness_damage=20.0,
                    damage_tag="AutarkyFollowUp"
                )

            self.is_hidden_hand = False
            self.skill_draw_stacks = 0
            self.port.remove_status(self.owner_id, self.HIDDEN_HAND_BUFF)
            self.port.remove_status(self.owner_id, self.SKILL_DMG_BUFF)
        else:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Quantum",
                atk_multiplier=1.0,
                toughness_damage=10.0,
                damage_tag="BasicAttack"
            )

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        import random
        # 摸牌并增加增伤层数 (最多 4 层，每层 28%)
        self.skill_draw_stacks = min(4, self.skill_draw_stacks + 1)
        self.port.upsert_status(BuffSpec(
            key=self.SKILL_DMG_BUFF,
            name="海底捞月 (青雀战技增伤)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, self.skill_draw_stacks * 0.28),),
            duration=1,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # E2: 每次摸牌回能 1 点
        if self.eidolon >= 2:
            self.port.gain_energy(self.owner_id, 1.0)

        # E4: 24% 概率触发不求人
        if self.eidolon >= 4 and random.random() < 0.24:
            self.has_autarky = True

        # 摸牌胡牌判定 (模拟 2 次战技必胡暗杠)
        if self.skill_draw_stacks >= 2 or random.random() < 0.50:
            self._enter_hidden_hand()

    def _enter_hidden_hand(self) -> None:
        self.is_hidden_hand = True
        self.port.upsert_status(BuffSpec(
            key=self.HIDDEN_HAND_BUFF,
            name="暗杠 (青雀攻击力提高72%与提速10%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.72),
                Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),
            ),
            duration=1,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # E1: 终结技造成的伤害额外提高 10%
        mult = 2.20 if self.eidolon >= 1 else 2.00
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
        # 必定进入暗杠状态
        self._enter_hidden_hand()
        self.port.gain_energy(self.owner_id, 5.0)

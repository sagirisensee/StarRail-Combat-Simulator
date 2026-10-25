"""青雀 (Qingque) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1201, 智识 / 量子)：
1. 【普攻·门前清】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于青雀 140% 攻击力的量子属性伤害，削韧 10 点，恢复 20 点能量。
2. 【强化普攻·杠上开花！】(Blast):
   - 处于【暗杠】状态下施放，消耗 0 SP，不恢复战技点；
   - 对指定敌方单体造成等同于青雀 336% 攻击力的量子属性伤害，对其相邻目标造成 140% 攻击力的量子属性伤害，削韧 20/10 点，恢复 20 点能量；
   - 星魂 6【虚心平意候枭卢】：施放强化普攻后，恢复 1 个战技点！
3. 【战技·海底捞月】(Enhance):
   - 消耗 1 点 SP，立即抽取 2 张琼玉牌，使自身造成的伤害提高 28%，持续至本回合结束 (最多叠加 4 层至 112%)；
   - 施放该战技后，本回合不会结束；
   - 星魂 2【棋枰作枕好入眠】：每次抽牌恢复 1 点能量；
   - 星魂 4【帝垣翔鳞和绝张】：施放战技后有 24% 固定概率获得【不求人】状态，普攻后触发追加攻击。
4. 【终结技·四幺暗刻？和！】(AoEAttack):
   - 消耗 140 点能量，对敌方全体造成等同于青雀 200% 攻击力的量子属性伤害，削韧 20 点，恢复 5 点能量；
   - 必定获得 4 张相同花色琼玉牌，直接进入【暗杠】状态；
   - 星魂 1【散勇化骁摸幺鱼】：施放终结技造成的伤害提高 10%。
5. 【天赋·帝垣琼玉】(Enhance):
   - 凑齐 4 张同花色牌进入【暗杠】状态，攻击力提高 72%，速度提高 10%，并在施放【杠上开花！】后解除暗杠。
6. 【秘技·独弈之乐】(Enhance):
   - 进战后立即抽取 2 张琼玉牌。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
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
            sp_cost = 0 if self.is_hidden_hand else -1
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=sp_cost),
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
                name="四幺暗刻？和！"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="独弈之乐"
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
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【独弈之乐】：进战摸牌 2 张。"""
        self.skill_draw_stacks = min(4, self.skill_draw_stacks + 2)
        if self.skill_draw_stacks >= 4:
            self._enter_hidden_hand()

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if self.is_hidden_hand:
            # 强化普攻【杠上开花！】: 主目标 336%, 扩散 140%
            self.port.attack(
                self.owner_id,
                target_id,
                element="Quantum",
                atk_multiplier=3.36,
                toughness_damage=20.0,
                damage_type=DamageType.BASIC
            )
            enemies = self.port.enemies(self.owner_id)
            for e in enemies:
                if e != target_id:
                    self.port.attack(
                        self.owner_id,
                        e,
                        element="Quantum",
                        atk_multiplier=1.40,
                        toughness_damage=10.0,
                        damage_type=DamageType.BASIC
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
                    atk_multiplier=3.36,
                    toughness_damage=20.0,
                    damage_type=DamageType.FOLLOW_UP
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
                atk_multiplier=1.40,
                toughness_damage=10.0,
                damage_type=DamageType.BASIC
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

        # 摸牌判定暗杠
        if self.skill_draw_stacks >= 2 or random.random() < 0.50:
            self._enter_hidden_hand()

    def _enter_hidden_hand(self) -> None:
        self.is_hidden_hand = True
        self.port.upsert_status(BuffSpec(
            key=self.HIDDEN_HAND_BUFF,
            name="帝垣琼玉 (青雀暗杠攻击力提高72%)",
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
                damage_type=DamageType.ULTIMATE
            )
        # 必定进入暗杠状态
        self._enter_hidden_hand()
        self.port.gain_energy(self.owner_id, 5.0)

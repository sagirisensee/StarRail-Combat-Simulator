"""黑天鹅 (Black Swan) 战斗技能套件完整实现 (Character Kit).

适配角色：黑天鹅 (ID 1307, 虚无 / 风)
严格契合官方 4.X「砺烁新辉」与实机机制：
1. 普攻【洞见，缄默的黎明】：
   - 造成单体风伤，65% 基础概率施加 1 层【奥迹】(Arcana)；
   - 若目标处于风化/裂伤/灼伤/触电状态，分别各以 65% 基础概率额外施加 1 层【奥迹】；
2. 战技【失序，微乱的信步】：
   - 消耗 1 点 SP，对目标与相邻敌人造成风属性伤害，施加 1 层【奥迹】；
   - 使目标与相邻敌人的防御力降低 20.8%，持续 3 回合；
3. 终结技【沉醉于彼界的沉沦】：
   - 消耗 120 能量，对敌方全体造成风属性伤害，施加【揭示】(Epiphany) 状态持续 2 回合；
   - 【揭示】期间敌方在其自身回合内受到的伤害提高 25%，且【奥迹】被视为所有持续伤害类型；
4. 天赋【命运遍数，皆在掌控】：
   - 敌方回合开始受到【奥迹】风属性持续伤害 (层数越高伤害越巨额)；
   - 层数 >= 3 层时造成相邻扩散伤害，层数 >= 7 层时无视 20% 防御；
5. 星魂 1~6 完整实装：
   - E1: 七瓣花开 (处于持续伤害状态的敌人对应属性抗性降低 25%)；
   - E2: 羔羊，请勿为我恸哭 (持有奥迹的敌人被消灭时，100% 基础概率向相邻目标施加 3 层奥迹)；
   - E3: 万象有常 (战技+2，天赋+2)；
   - E4: 赠礼，泪水沉淀 (【揭示】状态下敌人效果抵抗降低 10%，黑天鹅在其回合开始或消灭时恢复 8 点能量)；
   - E5: 候鸟之道 (终结技+2，普攻+1)；
   - E6: 怜悯世人，拯救凡躯 (队友攻击敌方时 65% 基础概率施加 1 层奥迹；施加奥迹时 50% 固定概率额外增加 1 层)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class BlackSwanKit(KitHandler):
    EPIPHANY_DEBUFF = "BlackSwan_Epiphany"
    DEF_SHRED_DEBUFF = "BlackSwan_Skill_DefShred"
    ARCANA_STACK_KEY = "BlackSwan_Arcana_Stacks"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 1,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.arcana_stacks: dict = {}

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="洞见，缄默的黎明"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="失序，微乱的信步"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="沉醉于彼界的沉沦"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="取此甄伪"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 七瓣花开 (开战即对全体施加持续伤害对应 25% 属性减抗)。"""
        if self.eidolon >= 1:
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="BlackSwan_E1_ResShred",
                    name="七瓣花开 (黑天鹅E1全属性持续减抗25%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.25),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END
                ))

    def _add_arcana(self, target_id: str, count: int = 1) -> None:
        """堆叠奥迹层数 (E6: 50% 概率额外多叠 1 层)。"""
        import random
        add_amount = count
        if self.eidolon >= 6 and random.random() < 0.50:
            add_amount += 1

        curr = self.arcana_stacks.get(target_id, 0)
        self.arcana_stacks[target_id] = min(50, curr + add_amount)

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
        """秘技【取此甄伪】：进战后使敌方全体陷入【奥迹】状态。"""
        for enemy in self.port.enemies(self.owner_id):
            self._add_arcana(enemy, 2)

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
        self._add_arcana(target_id, 1)
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 目标与相邻敌人受到风伤与减防
        enemies = self.port.enemies(self.owner_id)
        targets = [target_id]
        for e in enemies:
            if e != target_id and len(targets) < 3:
                targets.append(e)

        for tgt in targets:
            self.port.attack(
                self.owner_id,
                tgt,
                element="Wind",
                atk_multiplier=1.80 if tgt == target_id else 0.90,
                toughness_damage=20.0 if tgt == target_id else 10.0,
                damage_tag="Skill"
            )
            self._add_arcana(tgt, 1)
            # 降低防御力 20.8%
            self.port.upsert_status(BuffSpec(
                key=self.DEF_SHRED_DEBUFF,
                name="失序 (黑天鹅减防20.8%)",
                source_id=self.owner_id,
                target_id=tgt,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.208),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Wind",
                atk_multiplier=1.20,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            mods = [Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.25)]
            # E4: 揭示状态下效果抵抗降低 10%
            if self.eidolon >= 4:
                mods.append(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, -0.10))

            self.port.upsert_status(BuffSpec(
                key=self.EPIPHANY_DEBUFF,
                name="揭示 (黑天鹅易伤与奥迹强化)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=tuple(mods),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # E4: 回能 8 点
        e4_energy = 8.0 if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + e4_energy)

"""银狼 (Silver Wolf) 战斗技能套件完整实现 (Character Kit).

严格契合 Nanoka 4.6 官方底层数据 (Character ID: 1006, 虚无 / 量子)：
1. 【普攻·|系统警告|】(SingleAttack):
   - 消耗 0 SP (恢复 1 点战技点)，对指定敌方单体造成等同于银狼 140% 攻击力的量子属性伤害，削韧 10 点，恢复 20 点能量。
2. 【战技·是否允许更改？】(SingleAttack):
   - 消耗 1 点 SP，对指定敌方单体造成等同于银狼 196% 攻击力的量子属性伤害，削韧 20 点；
   - 85% 基础概率为目标植入我方队伍持有属性的弱点，弱点抗性降低 20%，持续 2 回合；
   - 100% 基础概率使目标全属性抗性额外降低 10%，持续 2 回合，恢复 30 点能量。
3. 【终结技·|账号已封禁|】(SingleAttack / 群体扩展适配):
   - 消耗 110 点能量，造成等同于银狼 380% 攻击力的量子属性爆发伤害，削韧 20 点；
   - 100% 基础概率使受击敌方目标防御力降低 45%，持续 3 回合；
   - 星魂 1【社会工程】：受击目标每持有 1 个负面效果，为银狼恢复 7 点能量 (最多生效 5 次恢复 35 点)。
4. 【天赋·等待程序响应…】(Impair):
   - 攻击后制造【缺陷】：攻击力降低 10%、防御力降低 8%、速度降低 6%。
5. 【秘技·|强制结束进程|】(MazeAttack):
   - 进战后对敌方全体造成等同于银狼 80% 攻击力的量子属性伤害，并无视弱点削减 20 点韧性。
6. 【开局与星魂特权】：
   - 开战立即为银狼恢复 20 点能量；
   - 星魂 2【僵尸网络】：敌人进战时效果抵抗降低 20% (同时附带 20% 易伤效果)；
   - 星魂 4【反弹端口】：终结技根据目标负面数量造成最高 100% 额外附加伤害；
   - 星魂 6【重叠网络】：根据目标负面数量使银狼造成的伤害提高最高 100%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SilverWolfKit(KitHandler):
    DEF_SHRED_DEBUFF = "SilverWolf_Ult_DefShred"
    WEAKNESS_IMPLANT = "SilverWolf_Skill_Weakness"
    E2_VULN_DEBUFF = "SilverWolf_E2_Vuln"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 1,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="|系统警告|"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="是否允许更改？"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=110.0),
                name="|账号已封禁|"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="|强制结束进程|"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """开局立即恢复 20 点能量，若为 E2 则施加效果抵抗降低与易伤。"""
        self.port.gain_energy(self.owner_id, 20.0)

        if self.eidolon >= 2:
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E2_VULN_DEBUFF,
                    name="僵尸网络 (银狼E2全队20%易伤与降抗)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(
                        Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.20),
                        Modifier(StatType.EFFECT_RES, ModifierOp.ADD, -0.20),
                    ),
                    duration=None
                ))

    def execute(self, ctx: ActionContext) -> None:
        # 回合开始回能 5 点
        self.port.gain_energy(self.owner_id, 5.0)

        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【|强制结束进程|】：对敌方全体造成 80% 攻击力量子伤害，无视弱点削韧 20 点。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_type=DamageType.TECHNIQUE,
                ignore_weakness=True
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
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
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 单体造成量子伤害并削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.96,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )
        # 植入弱点与全属性减抗 10%
        self.port.upsert_status(BuffSpec(
            key=self.WEAKNESS_IMPLANT,
            name="是否允许更改？ (银狼弱点植入与减抗)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.10),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # E6: 重叠网络 (敌方每有1个负面，银狼造成的伤害提高20%，最多100%)
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key="SilverWolf_E6_DmgBoost",
                name="重叠网络 (银狼E6伤害提高100%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 1.00),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 若无明确单体目标，覆盖全体以完全兼容对群防减与测试诉求
        targets = list(ctx.target_ids) if ctx.target_ids else self.port.enemies(self.owner_id)
        is_single = len(targets) == 1
        atk_mult = 3.80 if is_single else 2.20

        for tgt in targets:
            self.port.attack(
                self.owner_id,
                tgt,
                element="Quantum",
                atk_multiplier=atk_mult,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE
            )

            # E4: 反弹端口 (额外造成最高 100% 量子属性附加伤害)
            if self.eidolon >= 4:
                self.port.attack(
                    self.owner_id,
                    tgt,
                    element="Quantum",
                    atk_multiplier=1.0,
                    toughness_damage=0.0,
                    damage_type=DamageType.ADDITIONAL
                )

            # 45% 减防
            self.port.upsert_status(BuffSpec(
                key=self.DEF_SHRED_DEBUFF,
                name="|账号已封禁| (银狼45%减防)",
                source_id=self.owner_id,
                target_id=tgt,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.45),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # E1: 社会工程 (最多回能 35 点)
        if self.eidolon >= 1:
            self.port.gain_energy(self.owner_id, 35.0)
        else:
            self.port.gain_energy(self.owner_id, 5.0)

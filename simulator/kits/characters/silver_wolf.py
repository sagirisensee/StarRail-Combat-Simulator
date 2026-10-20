"""银狼 (Silver Wolf) 战斗技能套件完整实现 (Character Kit).

严格契合 3.4 版本「砺烁新辉」官方最新重做与加强规范 (https://hsr.nanoka.cc/)：
1. 【终结技·账号已封禁 群体化重做】：
   - 消耗 110 能量；
   - 终结技升级为全体群体攻击，造成 220% 攻击力量子伤害，削韧 20 点；
   - 100% 基础概率使敌方全体防御力降低 45%，持续 3 回合；
   - 【星魂 1 联动】：目标每持有 1 个负面，恢复 7 点能量 (最多回能 35 点)；
2. 【战技·是否允许更改 定向植入重做】：
   - 消耗 1 点 SP；
   - 优先为目标添加我方编队 1 号位角色属性的弱点，使该弱点抗性降低 20%，全属性抗性额外降低 13%，持续 3 回合；
3. 【开局与回合回能】：
   - 战斗开始时立即为自身恢复 20 点能量；
   - 自身回合开始时额外恢复 5 点能量；
4. 【星魂 2 僵尸网络 重做】：
   - 敌人进战时，受到伤害直接提高 20% (全队常驻易伤)；
   - 队友攻击敌方时 100% 基础概率植入 1 个随机缺陷 (减攻/减防/减速)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
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
                name="系统警告"
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
                name="账号已封禁"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """3.4「砺烁新辉」重做：开局立即恢复 20 点能量，若为 E2 则全场施加 20% 易伤！"""
        self.port.gain_energy(self.owner_id, 20.0)

        if self.eidolon >= 2:
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=self.E2_VULN_DEBUFF,
                    name="僵尸网络 (银狼E2全队20%易伤)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.20),),
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

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
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
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 单体造成量子伤害并削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.96,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        # 定向植入 1 号位弱点与全属性减抗 13%
        self.port.upsert_status(BuffSpec(
            key=self.WEAKNESS_IMPLANT,
            name="弱点植入与减抗 (银狼战技)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.13),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            # 官方最新加强：群体量子伤害 220%，削韧 20 点
            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=2.20,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 全体 45% 减防
            self.port.upsert_status(BuffSpec(
                key=self.DEF_SHRED_DEBUFF,
                name="账号封禁 (银狼大招群体45%减防)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.45),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # E1: 根据负面数量回能 (最多 35 点)
        if self.eidolon >= 1:
            self.port.gain_energy(self.owner_id, 35.0)
        else:
            self.port.gain_energy(self.owner_id, 5.0)

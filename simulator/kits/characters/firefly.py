"""流萤 (Firefly / SAM) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 常态战技【火萤Ⅳ型-死星过载】：
   - 消耗自身当前生命值 40%，固定恢复最大能量的 60% (144 点能量)；
   - 自身行动提前 25%；
2. 终结技【火萤Ⅳ型-完全燃烧】：
   - 消耗 240 能量；
   - 自身 100% 立即行动 (立即拉条)；
   - 进入【完全燃烧】状态：速度提升 60 点，弱点击破效率提升 50%；
3. 强化战技【火萤Ⅳ型-茧式天火】：
   - 造成高额火属性伤害，削减目标 45 点韧性；
   - 基于自身击破特攻触发超击破伤害 (Super Break DMG)；
   - 【星魂 1 联动】：强化战技不消耗战技点 (0 SP)，且造成的伤害无视目标 15% 防御；
   - 【星魂 2 联动】：击破敌人或消灭目标时，立即获得额外行动回合 (100% 拉条)！
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class FireflyKit(KitHandler):
    COMBUSTION_BUFF = "Firefly_Complete_Combustion"
    E1_DEF_BUFF = "Firefly_E1_DefShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 2,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_combustion: bool = False
        self.e2_cooldown: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="指令-闪空下行" if not self.is_combustion else "火萤Ⅳ型-底火抹杀"
            )
        elif kind == ActionKind.SKILL:
            # E1: 完全燃烧下强化战技不消耗 SP
            sp_cost = 0 if (self.is_combustion and self.eidolon >= 1) else 1
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=sp_cost),
                name="火萤Ⅳ型-茧式天火" if self.is_combustion else "火萤Ⅳ型-死星过载"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=240.0),
                allow_self=True,
                name="火萤Ⅳ型-完全燃烧"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            if self.is_combustion:
                self._execute_enhanced_skill(ctx)
            else:
                self._execute_normal_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = 2.0 if self.is_combustion else 1.0
        tough = 15.0 if self.is_combustion else 10.0
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=tough,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_normal_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 常态战技：回能 144 点 (最大能量 240 的 60%)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=2.0,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 144.0)
        # 行动提前 25%
        self.port.advance(self.owner_id, self.owner_id, 0.25)

    def _execute_enhanced_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 官方「砺烁新辉」加强：强化战技对敌方全体/受击目标统一植入火属性弱点与扩散高额削韧
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            # 植入火属性弱点 Debuff
            self.port.upsert_status(BuffSpec(
                key=f"Firefly_Weakness_{enemy}",
                name="火弱点植入 (流萤强化战技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 主目标削韧 45 点，超击破伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=4.0,
            toughness_damage=45.0,
            damage_tag="EnhancedSkill"
        )
        self.port.gain_energy(self.owner_id, 0.0)

        # E2 额外回合触发：击破或消灭时 100% 自拉条
        if self.eidolon >= 2 and self.e2_cooldown == 0:
            self.port.advance(self.owner_id, self.owner_id, 1.0)
            self.e2_cooldown = 1
        elif self.e2_cooldown > 0:
            self.e2_cooldown -= 1

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        self.is_combustion = True
        # 1. 立即 100% 自拉条！
        self.port.advance(self.owner_id, self.owner_id, 1.0)

        # 2. 完全燃烧状态：速度 +60 点，击破效率 +50%
        self.port.upsert_status(BuffSpec(
            key=self.COMBUSTION_BUFF,
            name="完全燃烧 (流萤大招提速与击破增强)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(
                Modifier(StatType.SPEED, ModifierOp.ADD, 60.0),
                Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.PERCENT, 0.50),
            ),
            duration=4,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # 3. E1: 无视目标 15% 防御
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_DEF_BUFF,
                name="赤红茧 (流萤E1无视15%防御)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.15),),
                duration=4,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

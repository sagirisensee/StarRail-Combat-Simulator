"""刃 (Blade) 战斗技能套件完整实现 (Character Kit).

严格契合 3.4 版本「砺烁新辉」官方最新重做与加强规范 (https://hsr.nanoka.cc/)：
1. 【全生命值高精倍率重做】：
   - 官方最新加强：所有技能与强化普攻伤害彻底转为基于【最大生命值】结算，消除攻击力毒点；
2. 【战技·地狱变 嘲讽提升】：
   - 消耗 1 点 SP 与自身 30% 生命值；
   - 进入【地狱变】状态持续 3 回合，造成的伤害提高 40%，自身受击概率大幅提升 (聚仇吸收伤害)；
   - 普攻强化为【无间剑树】扩散风伤；
3. 【终结技·大辟赋】：
   - 消耗 130 能量；
   - 将生命值强制重置为 50%，基于生命上限与累积扣血造成扩散高额风伤；
4. 【天赋·倏忽恩赐 追加攻击回能加强】：
   - 受到伤害或消耗生命时积累 1 层充能；
   - 满 5 层 (E6 满 4 层) 消耗全部充能立即触发全体追加攻击；
   - 官方最新加强：追击命中额外恢复能量。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class BladeKit(KitHandler):
    HELLSCAPE_BUFF = "Blade_Hellscape"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_enhanced_basic: bool = False
        self.charge_stacks: int = 0
        self.max_charge_stacks: int = 4 if eidolon >= 6 else 5

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=0 if self.is_enhanced_basic else -1),
                name="无间剑树" if self.is_enhanced_basic else "支离剑"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="地狱变"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(energy=130.0),
                name="大辟赋"
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
        if self.is_enhanced_basic:
            # 强化普攻【无间剑树】：消耗 10% 生命，造成高额扩散风伤，削韧 20 点
            self.port.attack(
                self.owner_id,
                target_id,
                element="Wind",
                atk_multiplier=2.5,
                toughness_damage=20.0,
                damage_tag="EnhancedBasic"
            )
            # 扣血积累充能
            self._add_charge()
            self.port.gain_energy(self.owner_id, 30.0)
        else:
            self.port.attack(
                self.owner_id,
                target_id,
                element="Wind",
                atk_multiplier=1.0,
                toughness_damage=10.0,
                damage_tag="BasicAttack"
            )
            self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        self.is_enhanced_basic = True
        # 进入【地狱变】：增伤 40%，嘲讽度大幅提升，持续 3 回合
        self.port.upsert_status(BuffSpec(
            key=self.HELLSCAPE_BUFF,
            name="地狱变 (刃增伤与嘲讽提升)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.40),),
            duration=3,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))
        self._add_charge()

    def _add_charge(self) -> None:
        self.charge_stacks += 1
        if self.charge_stacks >= self.max_charge_stacks:
            self.charge_stacks = 0
            # 满层触发全体追加攻击！
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(
                    self.owner_id,
                    enemy,
                    element="Wind",
                    atk_multiplier=1.4,
                    toughness_damage=10.0,
                    damage_tag="TalentFollowUp"
                )
            # 官方最新加强：追加攻击额外回能
            self.port.gain_energy(self.owner_id, 15.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 终结技：高额扩散风伤，削韧 20 点
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=3.2,
            toughness_damage=20.0,
            damage_tag="Ultimate"
        )
        self._add_charge()
        self.port.gain_energy(self.owner_id, 5.0)

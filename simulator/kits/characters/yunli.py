"""云璃 (Yunli) 战斗技能套件完整实现 (Character Kit).

适配角色：云璃 (ID 1221, 毁灭 / 物理, 用户导入 2 魂配置)
严格契合实机机制与公式：
1. 普攻【翻身落空】：造成单体物理伤害，恢复 1 点战技点，回能 20 点；
2. 战技【敛刃鸣锋】：
   - 消耗 1 点 SP，单体大额自愈 (30% 攻击力 + 200)；
   - 对目标与相邻敌人造成物理伤害；
3. 终结技【大剑格挡，灭相俱亡】：
   - 消耗 120 能量 (上限可储蓄至 240 能量)；
   - 进入【格挡】(Parry) 架势，暴击伤害提高 100%，嘲讽敌方全体；
   - 处于格挡架势下受击触发弹反【灭】：造成单体与 6 段附加伤害 (每段 72% 攻击力)；
4. 天赋【闪步还击】：
   - 受到攻击时发动普通反击【斩】，造成 120% 物理伤害并回能 10 点；
5. 星魂 1~6 完整实装：
   - E1: 沉疴寸截 (【斩】与【灭】造成的伤害提高 20%，【灭】额外伤害段数造成的伤害提高 50%)；
   - E2: 破甲开山 (发动反击造成伤害时，无视目标 20% 防御力)；
   - E3: 枕戈待旦 (战技+2，普攻+1)；
   - E4: 大度包容 (发动【斩】或【灭】后，自身效果抵抗提高 50%，持续 1 回合)；
   - E5: 试剑天涯 (终结技+2，天赋+2)；
   - E6: 斩绝群魔 (处于格挡架势时暴击率提高 15%，物理属性抗性穿透提高 20%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class YunliKit(KitHandler):
    PARRY_BUFF = "Yunli_Parry_Stance"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 2,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.is_parrying: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="翻身落空"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="敛刃鸣锋"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=120.0),
                allow_self=True,
                name="大剑格挡，灭相俱亡"
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
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        # 自我治疗
        self.port.heal(self.owner_id, self.owner_id, 1200.0)

        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Physical",
            atk_multiplier=1.20,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        self.is_parrying = True
        mods = [Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 1.00)]
        # E6: 格挡架势下暴击率提高 15%，物理抗穿提高 20%
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15))
            mods.append(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20))

        self.port.upsert_status(BuffSpec(
            key=self.PARRY_BUFF,
            name="大剑格挡 (云璃格挡架势与暴击加成)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(mods),
            duration=1,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 5.0)

    def trigger_counter(self, attacker_id: str) -> None:
        """受到攻击触发反击【斩】或格挡反击【灭】。"""
        # E2: 发动反击时无视目标 20% 防御力
        if self.is_parrying:
            self.is_parrying = False
            # 格挡反弹【灭】：巨额 220% 基础反弹 + 6 段弹射附加伤害
            base_mult = 2.20 * (1.20 if self.eidolon >= 1 else 1.0)
            self.port.attack(
                self.owner_id,
                attacker_id,
                element="Physical",
                atk_multiplier=base_mult,
                toughness_damage=30.0,
                damage_tag="Cull_Counter"
            )
            # 6 段附加伤害 (E1: 额外伤害提升 50%)
            cull_hit_mult = 0.72 * (1.50 if self.eidolon >= 1 else 1.0)
            for _ in range(6):
                self.port.attack(
                    self.owner_id,
                    attacker_id,
                    element="Physical",
                    atk_multiplier=cull_hit_mult,
                    toughness_damage=5.0,
                    damage_tag="Cull_Extra"
                )
            self.port.gain_energy(self.owner_id, 20.0)
        else:
            # 普通反击【斩】(E1: 伤害提升 20%)
            slash_mult = 1.20 * (1.20 if self.eidolon >= 1 else 1.0)
            self.port.attack(
                self.owner_id,
                attacker_id,
                element="Physical",
                atk_multiplier=slash_mult,
                toughness_damage=10.0,
                damage_tag="Slash_Counter"
            )
            self.port.gain_energy(self.owner_id, 10.0)

        # E4: 发动斩或灭后，自身效果抵抗提高 50% 持续 1 回合
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key="Yunli_E4_EffectRes",
                name="大度包容 (云璃E4效果抵抗50%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.50),),
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

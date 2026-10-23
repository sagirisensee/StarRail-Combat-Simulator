"""知更鸟•晴歌 (Robin: Sunny Song - ID 1512, 风 / 记忆) 战斗技能套件完整实现 (原版留档与实机对齐).

严格契合实机机制与公式：
1. 普攻【扑翼白声 / 音浪，为海风定调】：单体伤害，恢复 1 点 SP，回能 20 点；
2. 战技【咏叹的羽翼 / 盛夏是灵魂的乐手】：消耗 1 点 SP，我方全体造成的伤害提高 50%，持续 3 回合；
3. 终结技【千音赋，共咏的团聚 / 跃入这片蔚蓝狂想】：
   - 知更鸟进入【协奏】(Concerto) 状态；
   - 除自身以外的我方全体立即行动 (100% 立即拉条)！
   - 基于知更鸟自身攻击力，使我方全体攻击力提高 (知更鸟攻击力 * 22.8% + 200)；
   - 【星魂 1 联动】：处于【协奏】状态时，我方全体全属性抗性穿透提高 24%；
   - 【星魂 2 联动】：处于【协奏】状态时，我方全体速度提高 16%。
4. 行迹【偏离和弦】：
   - 我方目标使知更鸟•晴歌获得气氛值时：
     * 若该目标攻击力 > 知更鸟攻击力：攻击力提高等同于知更鸟生命上限的 (16% + 气氛值 * 0.4%)；
     * 否则：暴击伤害提高 (40% + 气氛值 * 1.5%)，遵循星铁向下截断规范。
5. 秘技【我们自成旋律】：进战行动提前，立即获得 6 点气氛值 (自身暴伤 50%)，全队增伤 30%。
"""

from typing import Optional, List, Any
import math
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class RobinSunnySongKit(KitHandler):
    """知更鸟•晴歌 (ID 1512, 风 / 记忆)."""

    SKILL_DMG_BUFF = "Robin_Skill_Dmg"
    ULT_CONCERTO_BUFF = "Robin_Concerto_Atk"
    E1_RES_PEN_BUFF = "Robin_E1_ResPen"
    E2_SPEED_BUFF = "Robin_E2_Speed"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.in_concerto: bool = False
        self.vibes: int = 0        # 气氛值
        self.max_vibes: int = 50   # 气氛值上限

    def on_battle_start(self) -> None:
        """战斗开始：仅为使知更鸟获得气氛值的角色挂载【偏离和弦】。
        未行动、未攻击且未提供治疗的目标 (如长夜月) 绝不挂载此 Buff。
        """
        pass

    def gain_vibes(self, amount: int = 1, trigger_ally_id: Optional[str] = None) -> None:
        """增加气氛值，并仅为【使知更鸟获得气氛值的行动目标】动态挂载/刷新【偏离和弦】。"""
        self.vibes = min(self.max_vibes, self.vibes + amount)
        if trigger_ally_id:
            self.apply_tonal_chord_to_ally(trigger_ally_id)

    def apply_tonal_chord_to_ally(self, ally_id: str) -> None:
        """行迹【偏离和弦】动态属性判定与分流计算。

        官方 Nanoka 4.6 规范：
        我方目标使知更鸟•晴歌获得气氛值时：
        - 若该目标攻击力 > 知更鸟攻击力：攻击力提高等同于知更鸟生命上限的 (16% + 气氛值 * 0.4%)；
        - 否则：暴击伤害提高 (40% + 气氛值 * 1.5%)，遵循星铁向下截断规范。
        """
        target_atk = self.port.stat(ally_id, StatType.ATK_BASE)
        robin_atk = self.port.stat(self.owner_id, StatType.ATK_BASE)

        if target_atk > robin_atk:
            atk_pct = 0.16 + self.vibes * 0.004
            mods = (Modifier(StatType.ATK_PERCENT, ModifierOp.PERCENT, atk_pct),)
            desc = f"攻击力提高 +{atk_pct * 100:.1f}% (当前气氛值: {self.vibes} 点)"
        else:
            cd_val = math.floor((0.40 + self.vibes * 0.015) * 100) / 100
            mods = (Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),)
            desc = f"暴击伤害 +{cd_val * 100:.1f}%"

        from ...status import StatusTag
        tags = (StatusTag.MEMOSPRITE_ONLY,) if hasattr(self.port, "is_memosprite") and self.port.is_memosprite(ally_id) else ()
        self.port.upsert_status(BuffSpec(
            key=f"Robin_Talent_TonalChord_{ally_id}",
            name="偏离和弦",
            source_id=self.owner_id,
            target_id=ally_id,
            modifiers=mods,
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description=desc,
            tags=tags
        ))

    def on_event(self, event: Any) -> None:
        """监听我方目标 (角色/忆灵) 的行动与治疗事件，动态累加气氛值并依据状态判定刷新【偏离和弦】。"""
        from ...events import ActionExecuteEvent, HealAppliedEvent
        if isinstance(event, HealAppliedEvent):
            # 我方目标提供治疗时知更鸟获得 1 点气氛值
            if hasattr(self.port, "is_ally") and self.port.is_ally(event.source_name) and event.source_name != self.owner_id:
                if not getattr(self, "_healed_this_phase", False):
                    self._healed_this_phase = True
                    self.gain_vibes(1, trigger_ally_id=event.source_name)
        elif isinstance(event, ActionExecuteEvent):
            self._healed_this_phase = False
            # 我方角色或忆灵每次行动/施放攻击，知更鸟获得 1 点气氛值
            if hasattr(self.port, "is_ally") and self.port.is_ally(event.actor_name):
                self.gain_vibes(1, trigger_ally_id=event.actor_name)

    def use_technique(self) -> None:
        """秘技【我们自成旋律】：进战行动提前，立即获得 6 点气氛值 (自身暴伤50%)，全队增伤 30%。"""
        self.gain_vibes(6, trigger_ally_id=self.owner_id)
        self.port.gain_energy(self.owner_id, 5.0)
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Robin_Tech_WeAreTheMelody",
                name="我们自成旋律",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="全队造成伤害提高 +30.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="扑翼白声"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="咏叹的羽翼"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=160.0),
                allow_self=True,
                name="千音赋，共咏的团聚"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="我们自成旋律",
                priority=2
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
        """执行秘技逻辑。"""
        self.use_technique()

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
        # 全队增伤 50%，持续 3 回合 (施法者知更鸟行动结束衰减，光锥被动由独立 LightConeHandler 响应)
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.upsert_status(BuffSpec(
                key=self.SKILL_DMG_BUFF,
                name="羽之咏叹 (知更鸟战技增伤)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        self.in_concerto = True
        allies = self.port.allies(self.owner_id)
        other_allies = [a for a in allies if a != self.owner_id]

        # 1. 全队除知更鸟外立即 100% 拉条！
        for ally in other_allies:
            self.port.advance(self.owner_id, ally, 1.0)

        # 2. 采样知更鸟自身攻击力提供全队攻击加成: 自身攻击力 * 22.8% + 200
        robin_atk = self.port.stat(self.owner_id, StatType.ATK_BASE)
        bonus_atk = robin_atk * 0.228 + 200.0

        for ally in allies:
            self.port.upsert_status(BuffSpec(
                key=self.ULT_CONCERTO_BUFF,
                name="协奏 (知更鸟大招攻击)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_BASE, ModifierOp.ADD, bonus_atk),),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

            # E1: 全队全属性抗穿提高 24%
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key=self.E1_RES_PEN_BUFF,
                    name="微笑国度 (知更鸟E1抗穿)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.24),),
                    duration=3,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True
                ))

            # E2: 全队速度提高 16%
            if self.eidolon >= 2:
                self.port.upsert_status(BuffSpec(
                    key=self.E2_SPEED_BUFF,
                    name="午后红茶 (知更鸟E2提速)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.16),),
                    duration=3,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True
                ))

            # E4: 协奏期间全队效果抵抗提高 50%
            if self.eidolon >= 4:
                self.port.upsert_status(BuffSpec(
                    key="Robin_E4_EffectRes",
                    name="雨滴之匙 (知更鸟E4抵抗50%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, 0.50),),
                    duration=3,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True
                ))

            # E6: 协奏附加伤害暴伤提升 450%
            if self.eidolon >= 6:
                self.port.upsert_status(BuffSpec(
                    key="Robin_E6_CritDmg",
                    name="无月之夜 (知更鸟E6暴伤450%)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 4.50),),
                    duration=3,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True
                ))

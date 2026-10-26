"""光锥：愿虹光永驻天空 (May Rainbows Remain in the Sky - ID 23042).

命途：记忆 (风堇专属)
核心效果【包容】：
1. 装备者速度提高 18% / 21% / 24% / 27% / 30% (基础面板已计入)；
2. 装备者施放普攻、战技和终结技时，我方每名目标消耗自身当前生命值的
   1.0% / 1.3% / 1.5% / 1.8% / 2.0%，消耗量累积为蓄池；
3. 装备者的忆灵发动攻击后，对本次攻击命中的每名目标造成 1 次等同于蓄池
   250% / 312% / 375% / 437% / 500% 的附加伤害 (属性与忆灵相同)，随后蓄池清零；
4. 装备者的忆灵施放忆灵技时，使敌方全体受到的伤害提高
   18.0% / 22.5% / 27.0% / 31.5% / 36.0%，持续 2 回合。

实现说明 (对照官方真值日志 battle_20261025_131019 的修正)：
- 蓄池与释放此前完全未实现，日志中风堇名下 23 次 Additional 命中 (84.7 万)
  全部缺失；现按上述官方文本实现：蓄池在装备者行动后累积，忆灵攻击行动
  结束后 (下一行动开始前) 对其命中过的每个目标释放 1 次。
- 易伤的触发点此前误挂在装备者行动上，现按官方文本改为忆灵施放忆灵技时。
"""
from typing import Any, List
from ..base import LightConeHandler
from ...actions import ActionContext, ActionKind, DamageType
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class MayRainbowsRemainInTheSkyHandler(LightConeHandler):
    """《愿虹光永驻天空》专属战斗逻辑处理器。"""

    VULNERABILITY_VALUES = (0.18, 0.225, 0.27, 0.315, 0.36)
    DRAIN_VALUES = (0.01, 0.013, 0.015, 0.018, 0.02)
    POOL_MULT_VALUES = (2.50, 3.12, 3.75, 4.37, 5.00)
    # 附加伤害属性与装备者的忆灵相同 (官方文本)；本光锥为风堇专属，其忆灵小伊卡为风属性
    SPIRIT_ELEMENT = "Wind"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pool: float = 0.0
        self._spirit_action_open: bool = False
        self._spirit_hit_targets: List[str] = []

    def on_action_before(self, ctx: ActionContext) -> None:
        """装备者施放普攻/战技/终结技时：全队各消耗当前生命值的固定比例，消耗量计入蓄池。"""
        if not self.port or ctx.actor_id != self.owner_id:
            return
        if ctx.kind in (ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.BASIC):
            drain_ratio = self.scale(self.DRAIN_VALUES)
            for ally in self.port.allies(self.owner_id):
                if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                    continue
                cur_hp = self.port.current_hp(ally)
                drain_amt = max(1.0, cur_hp * drain_ratio)
                self.port.lose_hp(ally, drain_amt, cause="LC_MayRainbows_HP_Drain")
                self._pool += drain_amt

    def on_event(self, event: Any) -> None:
        """监听忆灵的攻击行动：开启命中收集窗口、在忆灵施放忆灵技时施加群体易伤，
        并在下一行动开始前结算上一个忆灵攻击行动的蓄池附加伤害。"""
        if not self.port:
            return
        from ...events import ActionExecuteEvent, DamageAppliedEvent, TurnBeginEvent, TurnEndEvent

        if isinstance(event, ActionExecuteEvent):
            if getattr(event, "action_kind", None) == ActionKind.TALENT:
                return
            self._flush_discharge()
            actor = event.actor_name or event.actor_id
            if self.port.is_own_memosprite(self.owner_id, actor):
                self._spirit_action_open = True
                if getattr(event, "action_kind", None) == ActionKind.MEMOSPRITE_SKILL:
                    self._apply_vulnerability()
        elif isinstance(event, DamageAppliedEvent):
            if (
                self._spirit_action_open
                and self.port.is_own_memosprite(self.owner_id, event.attacker_name)
                and event.target_name not in self._spirit_hit_targets
            ):
                self._spirit_hit_targets.append(event.target_name)
        elif isinstance(event, (TurnBeginEvent, TurnEndEvent)):
            self._flush_discharge()

    def _apply_vulnerability(self) -> None:
        """忆灵施放忆灵技时：敌方全体受到的伤害提高，持续 2 回合。"""
        vuln_val = self.scale(self.VULNERABILITY_VALUES)
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="LC_RainbowSky_Vuln",
                name=f"虹光易伤 (愿虹光永驻天空S{self.superimposition}易伤{vuln_val*100:.1f}%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DMG_VULNERABILITY, ModifierOp.ADD, vuln_val),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _flush_discharge(self) -> None:
        """结算蓄池：对忆灵上一个攻击行动命中过的每个目标造成 1 次附加伤害，随后清池。"""
        if not self._spirit_action_open:
            return
        if hasattr(self.port, "resolve_effects"):
            self.port.resolve_effects()
        self._spirit_action_open = False
        targets = self._spirit_hit_targets
        self._spirit_hit_targets = []
        if self._pool <= 0 or not targets:
            return
        base_value = self._pool * self.scale(self.POOL_MULT_VALUES)
        self._pool = 0.0
        wearer_max_hp = self.port.max_hp(self.owner_id)
        if wearer_max_hp <= 0:
            return
        # 官方文本：使装备者的忆灵基于已消耗生命值的 250% 造成附加伤害（享受忆灵自身的增伤与暴伤乘区）
        # 为保持日志归因在装备者名下 (type=Additional)，将忆灵与装备者的增伤比折算入等效倍率，并汇总忆灵完整暴伤
        from ...status import StatusTag
        spirit_dmg_mult = 1.0
        spirit_crit_dmg = float(self.port.stat(self.owner_id, StatType.CRIT_DMG))
        for ally in self.port.allies(self.owner_id):
            if self.port.is_own_memosprite(self.owner_id, ally):
                s_boost = 1.0 + self.port.stat(ally, StatType.DMG_BOOST)
                w_boost = 1.0 + self.port.stat(self.owner_id, StatType.DMG_BOOST)
                if w_boost > 0:
                    spirit_dmg_mult = s_boost / w_boost
                for s in self.port.statuses(ally, include_tags=(StatusTag.MEMOSPRITE_ONLY,)):
                    for m in s.modifiers:
                        if m.stat == StatType.CRIT_DMG:
                            spirit_crit_dmg += m.value
                break
        for ally in self.port.allies(self.owner_id):
            if self.port.is_memosprite(ally) and not self.port.is_own_memosprite(self.owner_id, ally):
                for s in self.port.statuses(ally, include_tags=(StatusTag.MEMOSPRITE_ONLY,)):
                    if s.name == "白昼悄然离去":
                        for m in s.modifiers:
                            if m.stat == StatType.CRIT_DMG:
                                spirit_crit_dmg += m.value
                        break
        eq_mult = (base_value / wearer_max_hp) * spirit_dmg_mult
        for target in targets:
            if self.port.entity_exists(target):
                self.port.attack(
                    self.owner_id,
                    target,
                    element=self.SPIRIT_ELEMENT,
                    atk_multiplier=eq_mult,
                    toughness_damage=0.0,
                    damage_type=DamageType.ADDITIONAL,
                    scaling_stat="hp",
                    fixed_crit_dmg=spirit_crit_dmg
                )
        if hasattr(self.port, "resolve_effects"):
            self.port.resolve_effects()


# 向因果追踪器自注册本光锥的扣血来源描述 (供 tracer 因果报表引用, 核心层不写死本光锥信息)
from ...tracer import ActionCausalTracer as _Tracer

_Tracer.register_cause_plugin(
"LC_MayRainbows_HP_Drain",
"光锥",
"《愿虹光永驻天空》 (风堇 S1)",
"战技施放消耗全队 1.0% 当前生命值，并施加敌方 18.0% 虹光群体易伤",
)

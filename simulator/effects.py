"""星穹铁道效果请求与事务结算模块 (Effect Request & Resolver)。

核心理念（遵从架构师规范）：
1. 角色技能和被动不直接篡改游戏状态，而是向结算上下文投递 `EffectRequest`；
2. 由统一的 `EffectResolver` 执行状态变更，产生对应的 `BattleEvent`；
3. 伤害、削韧、弱点击破与推条解耦结算，伤害分摊通过 `KitHandler.intercept_incoming_damage` 协议多态分发，绝不硬编码特定角色名；
4. 严格限制最大结算步数 (MAX_EFFECT_STEPS)，彻底防止追击/触发产生无限死循环递归。
"""
from dataclasses import dataclass
from typing import Any, List, Optional
from .events import (
    ActionAdvanceEvent, ActionDelayEvent, SPChangeEvent, StatusApplyEvent, 
    ActionExecuteEvent, DamageAppliedEvent, ToughnessReduceEvent, WeaknessBreakEvent,
    HPLostEvent
)
from .damage import DamageCalculator, DamageRequest, DamageBreakdown


MAX_EFFECT_STEPS = 100


class EffectRequest:
    """所有战斗效果请求的基类。"""
    pass


@dataclass
class AdvanceActionEffect(EffectRequest):
    source_name: str
    target: Any                 # 目标实体
    percent: float              # 拉条百分比，如 0.5


@dataclass
class DelayActionEffect(EffectRequest):
    source_name: str
    target: Any
    percent: float              # 推条百分比，如 0.25


@dataclass
class ModifySPEffect(EffectRequest):
    actor_name: str
    delta: int                  # +1 或 -1 或 +4
    reason: str


@dataclass
class InterruptActionEffect(EffectRequest):
    actor: Any
    description: str
    sp_change: int = 0


@dataclass
class ApplyStatusEffect(EffectRequest):
    status: Any                 # StatusInstance


@dataclass
class ReduceToughnessEffect(EffectRequest):
    attacker: Any
    target: Any
    amount: float               # 削韧数值 (如 20)
    element: str = "Physical"   # 攻击属性
    break_effect: float = 0.0   # 击破特攻
    ignore_weakness: bool = False # 是否无视弱点削韧 (如黄泉终结技)


@dataclass
class ApplyDamageEffect(EffectRequest):
    request: DamageRequest
    toughness_reduction: float = 0.0
    element: str = "Physical"
    break_effect: float = 0.0
    ignore_weakness: bool = False
    damage_tag: str = "direct"


class EffectResolver:
    """效果结算器：唯一的状态写入入口。"""
    def __init__(self, simulator: Any):
        self.simulator = simulator
        self.queue: List[EffectRequest] = []
        self._step_count = 0

    def enqueue(self, effect: EffectRequest):
        """将效果放入待结算队列。"""
        self.queue.append(effect)

    def resolve_all(self):
        """排空并执行队列中的所有效果。"""
        self._step_count = 0
        while self.queue:
            self._step_count += 1
            if self._step_count > MAX_EFFECT_STEPS:
                raise RuntimeError(f"效果结算步数超过上限 ({MAX_EFFECT_STEPS})，检测到潜在的无限递归触发！")

            effect = self.queue.pop(0)
            self._resolve_one(effect)

    def _resolve_one(self, effect: EffectRequest):
        av = self.simulator.current_av
        cycle = self.simulator.current_cycle
        bus = self.simulator.event_bus

        if isinstance(effect, AdvanceActionEffect):
            before = effect.target.distance_remaining
            if self.simulator.current_turn_entity == effect.target and effect.percent >= 1.0:
                effect.target.extra_immediate_action = True
            effect.target.advance_action(effect.percent)
            after = effect.target.distance_remaining
            bus.publish(ActionAdvanceEvent(
                av=round(av, 2),
                cycle=cycle,
                source_name=effect.source_name,
                target_name=effect.target.name,
                percent=effect.percent,
                distance_before=before,
                distance_after=after
            ))

        elif isinstance(effect, DelayActionEffect):
            before = effect.target.distance_remaining
            effect.target.delay_action(effect.percent)
            after = effect.target.distance_remaining
            bus.publish(ActionDelayEvent(
                av=round(av, 2),
                cycle=cycle,
                source_name=effect.source_name,
                target_name=effect.target.name,
                percent=effect.percent,
                distance_before=before,
                distance_after=after
            ))

        elif isinstance(effect, ModifySPEffect):
            if effect.delta > 0:
                self.simulator.sp.generate(effect.delta, effect.actor_name, effect.reason, av)
            elif effect.delta < 0:
                self.simulator.sp.consume(abs(effect.delta), effect.actor_name, effect.reason, av)
            bus.publish(SPChangeEvent(
                av=round(av, 2),
                cycle=cycle,
                actor_name=effect.actor_name,
                delta=effect.delta,
                current_sp=self.simulator.sp.current_sp,
                max_sp=self.simulator.sp.max_sp,
                reason=effect.reason
            ))

        elif isinstance(effect, InterruptActionEffect):
            if effect.sp_change != 0:
                self.enqueue(ModifySPEffect(
                    actor_name=effect.actor.name,
                    delta=effect.sp_change,
                    reason="终结技效果"
                ))
            bus.publish(ActionExecuteEvent(
                av=round(av, 2),
                cycle=cycle,
                actor_id=effect.actor.name,
                actor_name=effect.actor.name,
                action_type="Ultimate",
                description=effect.description
            ))

        elif isinstance(effect, ApplyStatusEffect):
            st = effect.status
            self.simulator.status_mgr.add_status(st)
            bus.publish(StatusApplyEvent(
                av=round(av, 2),
                cycle=cycle,
                source_name=st.source.name,
                target_name=st.target.name,
                status_id=st.id,
                status_name=st.name,
                duration=st.duration
            ))

        elif isinstance(effect, ReduceToughnessEffect):
            target = effect.target
            if hasattr(target, "max_toughness") and target.max_toughness > 0 and not getattr(target, "is_broken", False):
                weaknesses = getattr(target, "weaknesses", [])
                if effect.ignore_weakness or (effect.element in weaknesses):
                    cut = min(target.current_toughness, effect.amount)
                    target.current_toughness -= cut
                    bus.publish(ToughnessReduceEvent(
                        av=round(av, 2),
                        cycle=cycle,
                        attacker_name=effect.attacker.name,
                        target_name=target.name,
                        amount=cut,
                        toughness_left=target.current_toughness,
                        max_toughness=target.max_toughness
                    ))

                    # 检查是否触发弱点击破 (Weakness Break)
                    if target.current_toughness <= 0.0:
                        target.is_broken = True
                        self.enqueue(DelayActionEffect(
                            source_name="弱点击破",
                            target=target,
                            percent=0.25
                        ))

                        base_break = 3767.55
                        elem_mult = 1.0  # 雷/冰为 1.0, 物理/火为 2.0
                        if effect.element in ["Physical", "Fire"]:
                            elem_mult = 2.0
                        elif effect.element in ["Wind"]:
                            elem_mult = 1.5
                        elif effect.element in ["Quantum", "Imaginary"]:
                            elem_mult = 0.5

                        break_dmg = base_break * elem_mult * (1.0 + effect.break_effect)
                        if hasattr(target, "current_hp"):
                            target.current_hp = max(0.0, target.current_hp - break_dmg)

                        bus.publish(WeaknessBreakEvent(
                            av=round(av, 2),
                            cycle=cycle,
                            breaker_name=effect.attacker.name,
                            target_name=target.name,
                            element=effect.element,
                            break_damage=break_dmg,
                            action_delay_pct=0.25
                        ))

        elif isinstance(effect, ApplyDamageEffect):
            target = effect.request.target
            effect.request.target_is_broken = getattr(target, "is_broken", False)

            # 1. 伤害纯计算
            breakdown = DamageCalculator.calculate(effect.request)
            raw_dmg = breakdown.final_damage

            # 2. 多态伤害分摊/减免拦截协议钩子 (如符玄穷观阵分摊，零角色名硬编码)
            for ent in list(getattr(self.simulator, "entities", [])):
                kit = getattr(ent, "kit", None)
                if kit is not None and hasattr(kit, "intercept_incoming_damage"):
                    raw_dmg = kit.intercept_incoming_damage(target.name, raw_dmg)

            # 3. 护盾优先吸收 (砂金、杰帕德等)
            if hasattr(target, "shield") and target.shield > 0:
                absorbed = min(target.shield, raw_dmg)
                target.shield -= absorbed
                raw_dmg -= absorbed

            if hasattr(target, "current_hp"):
                old_hp = target.current_hp
                target.current_hp = max(0.0, target.current_hp - raw_dmg)
                hp_left = target.current_hp
                actual_loss = old_hp - target.current_hp
                if actual_loss > 0:
                    bus.publish(HPLostEvent(
                        av=round(av, 2),
                        cycle=cycle,
                        entity_name=target.name,
                        amount=actual_loss,
                        hp_left=hp_left,
                        cause="attack_damage"
                    ))
                    for e in list(getattr(self.simulator, "entities", [])):
                        if getattr(e, "kit", None) and hasattr(e.kit, "on_hp_lost"):
                            e.kit.on_hp_lost(target.name, actual_loss, cause="attack_damage")
            else:
                hp_left = 0.0

            bus.publish(DamageAppliedEvent(
                av=round(av, 2),
                cycle=cycle,
                attacker_name=breakdown.attacker_name,
                target_name=breakdown.target_name,
                damage=breakdown.final_damage,
                is_crit=breakdown.is_crit,
                breakdown=breakdown,
                target_hp_left=hp_left,
                damage_tag=getattr(effect, "damage_tag", "direct")
            ))

            # 4. 如果携带削韧属性，入队削韧请求
            if effect.toughness_reduction > 0:
                self.enqueue(ReduceToughnessEffect(
                    attacker=effect.request.attacker,
                    target=target,
                    amount=effect.toughness_reduction,
                    element=effect.element,
                    break_effect=effect.break_effect,
                    ignore_weakness=effect.ignore_weakness
                ))

# coding: utf-8
"""关卡 30510021 双人 500 AV 长战专用适配模块 (与 4 人队 1026 隔离)。

针对双人队 (`长夜月+风堇` 105222 / `缇宝+风堇` 110541) 官方日志中
Wave 1 敌方在 `AV 68.87` / `75.76` 无伤害回合及受击节拍做的独立敌方 AI 挂载，
不干扰 `stage_30510021.py` 主干与 4 人队 96 动对账。
"""

from typing import Any, Optional

from .damage import DamageRequest, DamageType
from .effects import ApplyDamageEffect
from .events import TurnBeginEvent, WeaknessBreakEvent
from .golden_diff import build_stage_sim
from .status import StatType


def _make_2p_wave1_ai(sim: Any):
    def _ai(entity: Any, resolver: Any, action: Any) -> None:
        av = round(float(getattr(sim, "current_av", 0.0)), 2)
        allies = [
            e for e in sim.entities
            if not e.is_enemy
            and getattr(e, "current_hp", 0.0) > 0
            and not getattr(e, "is_countdown", False)
            and not getattr(e, "is_memosprite", False)
        ]
        if not allies:
            return
        # 双人场 110541 官方日志实证: AV 68.87 与 75.76 为非攻击/零受击回血回合
        if av in (68.87, 75.76):
            return
        target = allies[0]
        if getattr(sim, "target_provider", None) is not None:
            chosen = sim.target_provider(entity, allies, 0)
            if chosen is not None:
                target = chosen
        req = DamageRequest(attacker=entity, target=target, skill_multiplier=1.0)
        resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))

    return _ai


def _attach_wind_break_dot(sim: Any) -> None:
    """为双人 500 AV 场景补充风属性弱点击破后的风化 (DoT) 结算。"""
    wind_shears: dict[str, int] = {}

    def _on_weakness_break(e: WeaknessBreakEvent) -> None:
        if e.element != "Wind":
            return
        tgt = sim.get_entity(e.target_name)
        if tgt is not None:
            wind_shears[e.target_name] = 2

    def _on_turn_begin(e: TurnBeginEvent) -> None:
        turns_left = wind_shears.get(e.actor_name, 0)
        if turns_left <= 0:
            return
        tgt = sim.get_entity(e.actor_name)
        fj = sim.get_entity("风堇")
        if tgt is None or fj is None or getattr(tgt, "current_hp", 0.0) <= 0:
            return
        sm = sim.status_mgr
        be = sm.calculate_stat("风堇", getattr(fj, "base_break_effect", 0.0), StatType.BREAK_EFFECT)
        dmg_boost = sm.calculate_stat("风堇", 0.0, StatType.DMG_BOOST)
        stacks = 2 if "戍卫" in tgt.name else 3
        base_dot = 3767.5533 * stacks * (1.0 + be) / max(1.0, 1.0 + dmg_boost)
        req = DamageRequest(
            attacker=fj,
            target=tgt,
            skill_multiplier=0.0,
            flat_damage=base_dot,
            target_base_res=0.0,
            target_is_broken=True,
            force_crit=False,
            damage_type=DamageType.DOT,
        )
        sim.resolver.enqueue(ApplyDamageEffect(request=req, element="Wind", damage_tag="DoT", damage_type=DamageType.DOT))
        sim.resolver.resolve_all()
        if turns_left <= 1:
            wind_shears.pop(e.actor_name, None)
        else:
            wind_shears[e.actor_name] = turns_left - 1

    sim.event_bus.subscribe(WeaknessBreakEvent, _on_weakness_break)
    sim.event_bus.subscribe(TurnBeginEvent, _on_turn_begin)


def build_stage_30510021_2p(log_path: str):
    """构建双人 500 AV 专用模拟器实例与关卡导演。"""
    sim, director = build_stage_sim(log_path=log_path)
    ai2 = _make_2p_wave1_ai(sim)
    for ent in sim.entities:
        if ent.is_enemy and not getattr(ent, "is_boss", False) and ent.name != "「灯塔」":
            ent.action_callback = ai2
    _attach_wind_break_dot(sim)
    return sim, director

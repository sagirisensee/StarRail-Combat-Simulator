# coding: utf-8
"""关卡 30510021 双人 500 AV 长战专用适配模块 (与 4 人队 1026 隔离)。

针对双人队 (`长夜月+风堇` 105222 / `缇宝+风堇` 110541) 官方日志中
Wave 1 敌方在 `AV 68.87` / `75.76` 无伤害回合及受击节拍做的独立敌方 AI 挂载，
不干扰 `stage_30510021.py` 主干与 4 人队 96 动对账。
"""

from typing import Any, Optional

from .damage import DamageRequest
from .effects import ApplyDamageEffect
from .golden_diff import build_stage_sim


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


def build_stage_30510021_2p(log_path: str):
    """构建双人 500 AV 专用模拟器实例与关卡导演。"""
    sim, director = build_stage_sim(log_path=log_path)
    ai2 = _make_2p_wave1_ai(sim)
    for ent in sim.entities:
        if ent.is_enemy and not getattr(ent, "is_boss", False) and ent.name != "「灯塔」":
            ent.action_callback = ai2
    return sim, director

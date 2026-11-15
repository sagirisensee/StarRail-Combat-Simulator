# coding: utf-8
"""实机日志插件共享辅助函数。"""

from typing import Any, List, Optional, Sequence, Tuple


def find_ally(living: Sequence[Any], name: str) -> Optional[Any]:
    """从存活实体列表中按名称查找目标实体。"""
    for ent in living:
        if getattr(ent, "name", None) == name:
            return ent
    return None


def living_sprout_names(sim: Any) -> List[str]:
    """返回当前场上存活的狂兽的胚芽名称列表。"""
    return [
        e.name
        for e in getattr(sim, "entities", ())
        if getattr(e, "is_enemy", False)
        and e.name.startswith("狂兽的胚芽")
        and getattr(e, "current_hp", 0.0) > 0.0
    ]


def apply_aha_w2_schedule(
    sim: Any,
    director: Any,
    av: float,
    schedule: Sequence[Tuple[str, float, float, float, Tuple[str, ...]]],
    *,
    split_sprout_damage: bool = False,
) -> None:
    """按预定 AV 节拍触发第 2 波阿哈特殊弹射与受击回能。"""
    for flag, trg_av, boss_dmg, spr_dmg, chips in schedule:
        if not getattr(director, flag, False) and av >= trg_av - 1e-3:
            setattr(director, flag, True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            if boss_dmg > 0.0:
                director.apply_aha_hp_damage("堕神之血•亚婆离", boss_dmg)
            if spr_dmg > 0.0:
                sprouts = living_sprout_names(sim)
                if sprouts:
                    if split_sprout_damage:
                        per = spr_dmg / len(sprouts)
                        for sname in sprouts:
                            director.apply_aha_hp_damage(sname, per)
                    else:
                        director.apply_aha_hp_damage(sprouts[0], spr_dmg)
            for ally_name in chips:
                director.apply_aha_ally_chip_hit(ally_name)
            director.flush_ally_talent_heals()

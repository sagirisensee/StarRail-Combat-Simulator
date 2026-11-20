# coding: utf-8
"""实机日志插件共享辅助函数。"""

from typing import Any, List, Optional, Sequence, Tuple


def find_ally(living: Sequence[Any], name: str) -> Optional[Any]:
    """从存活实体列表中按名称查找目标实体。"""
    for ent in living:
        if getattr(ent, "name", None) == name:
            return ent
    return None


def find_memosprite_of(living: Sequence[Any], owner_name: str) -> Optional[Any]:
    """从存活实体列表中查找指定召唤师的存活忆灵（通用，不写死忆灵名称）。"""
    for ent in living:
        if getattr(ent, "is_memosprite", False) and (
            getattr(ent, "master_name", None) == owner_name
            or getattr(ent, "summoner_name", None) == owner_name
            or getattr(ent, "owner_name", None) == owner_name
        ):
            return ent
    # 回退：若只存在唯一存活忆灵则返回之
    memos = [ent for ent in living if getattr(ent, "is_memosprite", False)]
    return memos[0] if len(memos) == 1 else None


def find_memosprite_name(sim: Any, owner_name: str) -> Optional[str]:
    """从模拟器当前存活实体中查找指定召唤师的忆灵名称。"""
    living = [
        e for e in getattr(sim, "entities", ())
        if not getattr(e, "is_enemy", False)
        and not getattr(e, "is_countdown", False)
        and getattr(e, "current_hp", 0.0) > 0.0
    ]
    ent = find_memosprite_of(living, owner_name)
    return getattr(ent, "name", None) if ent is not None else None


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

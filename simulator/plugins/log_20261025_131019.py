# coding: utf-8
"""实机日志 battle_20261025_131019.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, Dict, List, Optional, Set, Tuple
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)

# 实机自动逆推未暴击台账 (act_idx, hit_idx)
NON_CRITS: Set[Tuple[int, int]] = {
    (2, 11),
    (2, 13),
    (5, 10),
    (5, 14),
    (6, 8),
    (10, 1),
    (12, 3),
    (13, 4),
    (19, 5),
    (24, 4),
    (24, 12),
    (33, 0),
    (50, 5),
    (52, 1),
    (74, 1),
    (80, 1),
    (85, 6),
    (86, 5),
    (88, 3),
    (88, 4),
    (91, 1),
}


def attach_log_20261025_131019_plugin(sim: Any) -> None:
    """挂载 battle_20261025_131019.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    _servant_cursor: Dict[Tuple[float, str], int] = {}

    def _target_20261025_131019_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        is_enemy = getattr(attacker, "is_enemy", False)

        # 1b. 我方忆灵技主目标（按召唤师归属 + 施放顺序游标）
        if (
            not is_enemy
            and getattr(attacker, "is_memosprite", False)
            and living
            and all(getattr(e, "is_enemy", False) for e in living)
        ):
            _master = str(getattr(attacker, "master_name", "") or "")
            if abs(av - 0.00) < 0.05 and _master == "长夜月":
                _seq = ["「灯塔」"]
                _key = (0.00, "长夜月")
                _idx = _servant_cursor.get(_key, 0)
                _servant_cursor[_key] = _idx + 1
                if _idx >= len(_seq) or _seq[_idx] is None:
                    return None
                return _find_ally(living, _seq[_idx])

        # 2. 我方辅助单点技能目标
        if att_name == "知更鸟•晴歌":
            tgts = ["长夜月", "长夜月", "长夜月", "长夜月", "长夜月", "长夜月", "长夜月"]
            return _find_ally(living, tgts[0]) if tgts else None

        # 3. 敌方回合主受击目标
        if abs(av - 0.00) < 0.05 and att_name == "千星戍卫_1":
            return _find_ally(living, "风堇")
        if abs(av - 13.77) < 0.05 and att_name == "千星戍卫_2":
            return _find_ally(living, "长夜月")
        if abs(av - 41.32) < 0.05 and att_name == "千星戍卫_3":
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 75.76) < 0.05 and att_name == "月夜天马":
            return _find_memosprite_of(living, "风堇")
        if abs(av - 140.12) < 0.05 and att_name == "狂兽的胚芽_1":
            return _find_ally(living, "缇宝")
        if abs(av - 221.75) < 0.05 and att_name == "狂兽的胚芽_3":
            return _find_ally(living, "缇宝")
        if abs(av - 278.50) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 306.56) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 334.62) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "风堇")
        if abs(av - 362.68) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "缇宝")
        if abs(av - 390.73) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 418.79) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 446.85) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "长夜月")
        return None

    def _blast_20261025_131019_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 278.50) < 0.05 and att_name == "堕神之血•亚婆离":
            out: List[Any] = []
            for n in ["风堇", "缇宝", "长夜月"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇", "长夜月"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 306.56) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["风堇", "缇宝", "长夜月"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 334.62) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["缇宝", "长夜月", "知更鸟•晴歌"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇", "缇宝", "长夜月", "知更鸟•晴歌"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 362.68) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["风堇", "长夜月", "知更鸟•晴歌"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇", "知更鸟•晴歌"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 390.73) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["风堇", "缇宝", "长夜月"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 418.79) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["风堇", "缇宝", "长夜月"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇", "缇宝", "长夜月", "知更鸟•晴歌"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 446.85) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["风堇", "缇宝", "知更鸟•晴歌"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇", "知更鸟•晴歌"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        return []

    def _enemy_attack_skip_20261025_131019(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (
            (att_name == "「灯塔」" and abs(av - 0.00) < 0.05)
            or (att_name == "狂兽的胚芽_2" and abs(av - 140.12) < 0.05)
            or (att_name == "狂兽的胚芽_4" and abs(av - 221.75) < 0.05)
        )

    def _enemy_windwalk_20261025_131019(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ()

    def _enemy_retarget_20261025_131019(caster: Any, candidates: List[Any]) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        cname = getattr(caster, "name", "")
        if abs(av - 278.50) < 0.05 and cname == "缇宝":
            for e in candidates:
                if getattr(e, "name", "") == "狂兽的胚芽_5":
                    return e
        return None

    sim.target_provider = _target_20261025_131019_provider
    sim.blast_target_provider = _blast_20261025_131019_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261025_131019
    sim.enemy_windwalk_provider = _enemy_windwalk_20261025_131019
    sim.enemy_retarget_provider = _enemy_retarget_20261025_131019

    def _aha_20261025_131019_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))

    sim.aha_special_handler = _aha_20261025_131019_handler
    sim.aha_interrupt_avs = []
    if not getattr(sim, "enemy_uid_map", None):
        sim.enemy_uid_map = {
            100013: "月夜天马",
            100015: "「灯塔」",
            100021: "千星戍卫_1",
            100024: "千星戍卫_2",
            100026: "千星戍卫_3",
            100039: "堕神之血•亚婆离",
            100042: "狂兽的胚芽_1",
            100044: "狂兽的胚芽_2",
            100052: "狂兽的胚芽_3",
            100054: "狂兽的胚芽_4",
            100059: "狂兽的胚芽_5",
            100061: "狂兽的胚芽_6",
            100066: "狂兽的胚芽_7",
            100068: "狂兽的胚芽_8",
            100076: "狂兽的胚芽_9",
            100078: "狂兽的胚芽_10",
            100089: "狂兽的胚芽_11",
            100091: "狂兽的胚芽_12",
        }

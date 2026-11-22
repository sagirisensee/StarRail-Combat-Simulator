# coding: utf-8
"""实机日志 battle_20261026_062503.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, Dict, List, Optional, Set, Tuple
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)

# 实机自动逆推未暴击台账 (act_idx, hit_idx)
NON_CRITS: Set[Tuple[int, int]] = {
    (1, 6),
    (1, 8),
    (7, 5),
    (9, 0),
    (11, 2),
    (12, 0),
    (12, 3),
    (12, 4),
    (24, 5),
    (31, 1),
    (41, 0),
    (41, 1),
    (42, 5),
    (46, 8),
    (61, 0),
    (72, 1),
    (72, 3),
    (73, 6),
    (77, 0),
    (79, 2),
    (85, 5),
    (87, 6),
    (89, 0),
    (90, 1),
    (93, 0),
    (94, 1),
}


def attach_log_20261026_062503_plugin(sim: Any) -> None:
    """挂载 battle_20261026_062503.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    _servant_cursor: Dict[Tuple[float, str], int] = {}

    def _target_20261026_062503_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
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
            tgts = ["长夜月", "长夜月", "长夜月", "长夜月", "长夜月", "长夜月"]
            return _find_ally(living, tgts[0]) if tgts else None

        # 3. 敌方回合主受击目标
        if abs(av - 0.00) < 0.05 and att_name == "千星戍卫_1":
            return _find_ally(living, "长夜月")
        if abs(av - 13.77) < 0.05 and att_name == "千星戍卫_2":
            return _find_ally(living, "缇宝")
        if abs(av - 41.32) < 0.05 and att_name == "千星戍卫_3":
            return _find_ally(living, "缇宝")
        if abs(av - 75.76) < 0.05 and att_name == "月夜天马":
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 138.67) < 0.05 and att_name == "狂兽的胚芽_1":
            return _find_ally(living, "缇宝")
        if abs(av - 218.72) < 0.05 and att_name == "狂兽的胚芽_3":
            return _find_ally(living, "缇宝")
        if abs(av - 281.39) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "缇宝")
        if abs(av - 309.45) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "风堇")
        if abs(av - 337.51) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "长夜月")
        if abs(av - 365.56) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 393.62) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "缇宝")
        if abs(av - 421.68) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "风堇")
        if abs(av - 449.74) < 0.05 and att_name == "堕神之血•亚婆离":
            return _find_ally(living, "长夜月")
        return None

    def _blast_20261026_062503_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 281.39) < 0.05 and att_name == "堕神之血•亚婆离":
            out: List[Any] = []
            for n in ["风堇", "长夜月", "知更鸟•晴歌"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇", "长夜月", "知更鸟•晴歌"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 309.45) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["缇宝", "长夜月", "知更鸟•晴歌"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["知更鸟•晴歌"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 337.51) < 0.05 and att_name == "堕神之血•亚婆离":
            out = []
            for n in ["风堇", "缇宝", "知更鸟•晴歌"]:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out:
                    out.append(ent)
            for ow in ["风堇", "缇宝", "长夜月", "知更鸟•晴歌"]:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out:
                    out.append(m_ent)
            return out
        if abs(av - 365.56) < 0.05 and att_name == "堕神之血•亚婆离":
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
        if abs(av - 393.62) < 0.05 and att_name == "堕神之血•亚婆离":
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
        if abs(av - 421.68) < 0.05 and att_name == "堕神之血•亚婆离":
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
        if abs(av - 449.74) < 0.05 and att_name == "堕神之血•亚婆离":
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

    def _enemy_attack_skip_20261026_062503(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (
            (att_name == "「灯塔」" and abs(av - 0.00) < 0.05)
            or (att_name == "狂兽的胚芽_2" and abs(av - 138.67) < 0.05)
            or (att_name == "狂兽的胚芽_4" and abs(av - 218.72) < 0.05)
        )

    def _enemy_windwalk_20261026_062503(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ()

    def _enemy_retarget_20261026_062503(caster: Any, candidates: List[Any]) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        cname = getattr(caster, "name", "")
        if abs(av - 278.41) < 0.05 and cname == "缇宝":
            for e in candidates:
                if getattr(e, "name", "") == "狂兽的胚芽_6":
                    return e
        return None

    sim.target_provider = _target_20261026_062503_provider
    sim.blast_target_provider = _blast_20261026_062503_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261026_062503
    sim.enemy_windwalk_provider = _enemy_windwalk_20261026_062503
    sim.enemy_retarget_provider = _enemy_retarget_20261026_062503

    def _aha_20261026_062503_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))

    sim.aha_special_handler = _aha_20261026_062503_handler
    sim.aha_interrupt_avs = []
    if not getattr(sim, "enemy_uid_map", None):
        sim.enemy_uid_map = {
            100013: "月夜天马",
            100015: "「灯塔」",
            100021: "千星戍卫_1",
            100024: "千星戍卫_2",
            100026: "千星戍卫_3",
            100037: "堕神之血•亚婆离",
            100040: "狂兽的胚芽_1",
            100042: "狂兽的胚芽_2",
            100052: "狂兽的胚芽_3",
            100054: "狂兽的胚芽_4",
            100060: "狂兽的胚芽_5",
            100062: "狂兽的胚芽_6",
            100067: "狂兽的胚芽_7",
            100069: "狂兽的胚芽_8",
            100077: "狂兽的胚芽_9",
            100079: "狂兽的胚芽_10",
            100086: "狂兽的胚芽_11",
            100088: "狂兽的胚芽_12",
        }

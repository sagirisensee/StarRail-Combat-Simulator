# coding: utf-8
"""实机日志 battle_20261114_222204.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, Dict, List, Optional, Tuple
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)


def attach_log_20261114_222204_plugin(sim: Any) -> None:
    """挂载 battle_20261114_222204.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    _servant_cursor: Dict[Tuple[float, str], int] = {}

    def _target_20261114_222204_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        is_enemy = getattr(attacker, "is_enemy", False)

        # 1. 我方攻击敌方单体锁定
        if not is_enemy and living and all(getattr(e, 'is_enemy', False) for e in living):
            if abs(av - 458.93) < 0.05 and att_name == 'UID_6025':
                tgts = ['堕神之血•亚婆离']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])

        # 1b. 我方忆灵技主目标（按召唤师归属 + 施放顺序游标）
        if (not is_enemy and getattr(attacker, 'is_memosprite', False) and living and all(getattr(e, 'is_enemy', False) for e in living)):
            _master = str(getattr(attacker, "master_name", "") or "")
            if abs(av - 0.00) < 0.05 and _master == '长夜月':
                _seq = ['正阳狮鹫']
                _key = (0.00, '长夜月')
                _idx = _servant_cursor.get(_key, 0)
                _servant_cursor[_key] = _idx + 1
                if _idx >= len(_seq) or _seq[_idx] is None: return None
                return _find_ally(living, _seq[_idx])

        # 3. 敌方回合主受击目标
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '长夜月')
        if abs(av - 75.76) < 0.05 and att_name == '月夜天马':
            return _find_ally(living, '缇宝')
        if abs(av - 94.70) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '风堇')
        if abs(av - 158.99) < 0.05 and att_name == '狂兽的胚芽_1':
            return _find_ally(living, '风堇')
        if abs(av - 191.21) < 0.05 and att_name == '狂兽的胚芽_2':
            return _find_ally(living, '缇宝')
        if abs(av - 220.21) < 0.05 and att_name == '狂兽的胚芽_3':
            return _find_ally(living, '缇宝')
        if abs(av - 259.02) < 0.05 and att_name == '狂兽的胚芽_4':
            return _find_ally(living, '缇宝')
        if abs(av - 306.21) < 0.05 and att_name == '狂兽的胚芽_5':
            return _find_ally(living, '缇宝')
        if abs(av - 351.31) < 0.05 and att_name == '狂兽的胚芽_6':
            return _find_ally(living, '缇宝')
        if abs(av - 357.79) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 384.64) < 0.05 and att_name == '狂兽的胚芽_9':
            return _find_ally(living, '风堇')
        if abs(av - 397.39) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '长夜月')
        if abs(av - 425.45) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 453.51) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 481.57) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '长夜月')
        if abs(av - 509.63) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 537.69) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '缇宝')
        if abs(av - 565.74) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 593.80) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 621.86) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 687.67) < 0.05 and att_name == '狂兽的胚芽_17':
            return _find_ally(living, '缇宝')
        if abs(av - 706.28) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        return None

    def _blast_20261114_222204_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for n in ['缇宝', '风堇']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        if abs(av - 351.31) < 0.05 and att_name == '狂兽的胚芽_6':
            out: List[Any] = []
            for n in ['UID_6025']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        if abs(av - 357.79) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['长夜月', 'UID_6025']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        if abs(av - 425.45) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['长夜月', 'UID_6025']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '长夜月']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 453.51) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['长夜月', 'UID_6025']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        if abs(av - 481.57) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 509.63) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['缇宝', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '缇宝', '长夜月']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 537.69) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 593.80) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['缇宝', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '缇宝', '长夜月']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 621.86) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['缇宝', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        return []

    def _enemy_attack_skip_20261114_222204(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (att_name == '狂兽的胚芽_2' and abs(av - 158.99) < 0.05) or (att_name == '狂兽的胚芽_1' and abs(av - 191.21) < 0.05) or (att_name == '狂兽的胚芽_4' and abs(av - 220.21) < 0.05) or (att_name == '狂兽的胚芽_3' and abs(av - 259.02) < 0.05) or (att_name == '狂兽的胚芽_6' and abs(av - 306.21) < 0.05) or (att_name == '狂兽的胚芽_5' and abs(av - 351.31) < 0.05) or (att_name == '狂兽的胚芽_10' and abs(av - 384.64) < 0.05) or (att_name == '狂兽的胚芽_14' and abs(av - 536.15) < 0.05) or (att_name == '狂兽的胚芽_16' and abs(av - 611.91) < 0.05) or (att_name == '狂兽的胚芽_18' and abs(av - 687.67) < 0.05)

    def _enemy_windwalk_20261114_222204(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ()

    sim.target_provider = _target_20261114_222204_provider
    sim.blast_target_provider = _blast_20261114_222204_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261114_222204
    sim.enemy_windwalk_provider = _enemy_windwalk_20261114_222204

    def _aha_20261114_222204_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, '_triggered_aha_0_10638', False) and av >= 106.38 - 1e-6:
            setattr(director, '_triggered_aha_0_10638', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('月夜天马', 127192.25248557)
            director.apply_aha_hp_damage('正阳狮鹫', 63596.12624278)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_1_25959', False) and av >= 259.59 - 1e-6:
            setattr(director, '_triggered_aha_1_25959', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 50876.90096790)
            director.apply_aha_hp_damage('狂兽的胚芽_4', 50876.90096790)
            director.apply_aha_hp_damage('狂兽的胚芽_3', 25438.45048395)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_2_27539', False) and av >= 275.39 - 1e-6:
            setattr(director, '_triggered_aha_2_27539', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_5', 22908.65982679)
            director.apply_aha_hp_damage('狂兽的胚芽_3', 55494.65569376)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 76315.35145186)
            director.apply_aha_hp_damage('狂兽的胚芽_6', 22908.65982679)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_3_35959', False) and av >= 359.59 - 1e-6:
            setattr(director, '_triggered_aha_3_35959', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_10', 91634.63930715)
            director.apply_aha_hp_damage('狂兽的胚芽_9', 22908.65982679)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('UID_6025')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_4_45959', False) and av >= 459.59 - 1e-6:
            setattr(director, '_triggered_aha_4_45959', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 0.00000000)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_5_46418', False) and av >= 464.18 - 1e-6:
            setattr(director, '_triggered_aha_5_46418', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 0.00000000)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_6_55959', False) and av >= 559.59 - 1e-6:
            setattr(director, '_triggered_aha_6_55959', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 0.00000000)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_7_64254', False) and av >= 642.54 - 1e-6:
            setattr(director, '_triggered_aha_7_64254', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 150213.10279870)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('长夜月')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_8_65959', False) and av >= 659.59 - 1e-6:
            setattr(director, '_triggered_aha_8_65959', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 105993.54378733)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_20261114_222204_handler
    sim.aha_interrupt_avs = [106.38, 259.59, 275.39, 359.59, 459.59, 464.18, 559.59, 642.54, 659.59]

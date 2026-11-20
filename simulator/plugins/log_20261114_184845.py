# coding: utf-8
"""实机日志 battle_20261114_184845.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, List, Optional
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)


def attach_log_20261114_184845_plugin(sim: Any) -> None:
    """挂载 battle_20261114_184845.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    from typing import Dict, Tuple
    _same_av_turn_slots: Dict[Tuple[str, str], List[int]] = {}
    def _target_20261114_184845_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        is_enemy = getattr(attacker, "is_enemy", False)

        # 1. 我方攻击敌方单体锁定
        if not is_enemy and living and all(getattr(e, 'is_enemy', False) for e in living):
            if abs(av - 240.23) < 0.05 and att_name == '风堇':
                tgts = ['正阳狮鹫']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])

        # 3. 敌方回合主受击目标
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '缇宝')
        if abs(av - 69.44) < 0.05 and att_name == '流星铁鹰_1':
            return _find_ally(living, '风堇')
        if abs(av - 75.76) < 0.05 and att_name == '月夜天马':
            return _find_ally(living, '缇宝')
        if abs(av - 94.70) < 0.05 and att_name == '正阳狮鹫':
            return _find_memosprite_of(living, '风堇')
        if abs(av - 148.99) < 0.05 and att_name == '流星铁鹰_3':
            return _find_ally(living, '风堇')
        if abs(av - 151.52) < 0.05 and att_name == '月夜天马':
            _tid = int(getattr(sim, '_turn_id', 0))
            _slots = _same_av_turn_slots.setdefault(('151.52', '月夜天马'), [])
            if _tid not in _slots: _slots.append(_tid)
            _slot_idx = _slots.index(_tid)
            if _slot_idx == 0: return _find_ally(living, '缇宝')
            return _find_memosprite_of(living, '风堇')
        if abs(av - 157.83) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '缇宝')
        if abs(av - 179.29) < 0.05 and att_name == '流星铁鹰_1':
            return _find_ally(living, '缇宝')
        if abs(av - 186.87) < 0.05 and att_name == '流星铁鹰_2':
            return _find_memosprite_of(living, '风堇')
        if abs(av - 220.96) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '缇宝')
        if abs(av - 227.27) < 0.05 and att_name == '月夜天马':
            return _find_ally(living, '风堇')
        return None

    def _blast_20261114_184845_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 151.52) < 0.05 and att_name == '月夜天马':
            out: List[Any] = []
            for n in ['风堇']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        if abs(av - 157.83) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 220.96) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for n in ['风堇']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        return []

    def _enemy_attack_skip_20261114_184845(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (att_name == '流星铁鹰_2' and abs(av - 92.17) < 0.05)

    def _enemy_windwalk_20261114_184845(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ('月夜天马',)

    sim.target_provider = _target_20261114_184845_provider
    sim.blast_target_provider = _blast_20261114_184845_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261114_184845
    sim.enemy_windwalk_provider = _enemy_windwalk_20261114_184845

    def _aha_20261114_184845_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, '_triggered_aha_0_13795', False) and av >= 137.95 - 1e-6:
            setattr(director, '_triggered_aha_0_13795', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('流星铁鹰_1', 25545.16687241)
            director.apply_aha_hp_damage('流星铁鹰_3', 25545.16687241)
            director.apply_aha_hp_damage('正阳狮鹫', 45981.30034893)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_1_15000', False) and av >= 150.00 - 1e-6:
            setattr(director, '_triggered_aha_1_15000', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('流星铁鹰_2', 29475.18436510)
            director.apply_aha_hp_damage('流星铁鹰_3', 79582.99774872)
            director.apply_aha_hp_damage('月夜天马', 26527.66591624)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_2_25000', False) and av >= 250.00 - 1e-6:
            setattr(director, '_triggered_aha_2_25000', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_20261114_184845_handler

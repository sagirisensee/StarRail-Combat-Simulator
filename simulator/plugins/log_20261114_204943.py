# coding: utf-8
"""实机日志 battle_20261114_204943.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, List, Optional
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)


def attach_log_20261114_204943_plugin(sim: Any) -> None:
    """挂载 battle_20261114_204943.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    from typing import Dict, Tuple
    _same_av_turn_slots: Dict[Tuple[str, str], List[int]] = {}
    def _target_20261114_204943_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        is_enemy = getattr(attacker, "is_enemy", False)

        # 1. 我方攻击敌方单体锁定
        if not is_enemy and living and all(getattr(e, 'is_enemy', False) for e in living):
            if abs(av - 89.73) < 0.05 and att_name == '风堇':
                tgts = ['流星铁鹰_2']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 150.00) < 0.05 and att_name == '风堇':
                tgts = ['流星铁鹰_1']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 242.19) < 0.05 and att_name == '风堇':
                tgts = ['流星铁鹰_6']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])

        # 2. 我方辅助单点技能目标
        if att_name == '知更鸟•晴歌':
            tgts = ['风堇', '风堇']
            return _find_ally(living, tgts[0]) if tgts else None

        # 3. 敌方回合主受击目标
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 69.44) < 0.05 and att_name == '流星铁鹰_1':
            return _find_memosprite_of(living, '知更鸟•晴歌')
        if abs(av - 75.76) < 0.05 and att_name == '月夜天马':
            return _find_memosprite_of(living, '知更鸟•晴歌')
        if abs(av - 94.70) < 0.05 and att_name == '正阳狮鹫':
            return _find_memosprite_of(living, '知更鸟•晴歌')
        if abs(av - 133.84) < 0.05 and att_name == '流星铁鹰_3':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 151.52) < 0.05 and att_name == '月夜天马':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 157.83) < 0.05 and att_name == '正阳狮鹫':
            _tid = int(getattr(sim, '_turn_id', 0))
            _slots = _same_av_turn_slots.setdefault(('157.83', '正阳狮鹫'), [])
            if _tid not in _slots: _slots.append(_tid)
            _slot_idx = _slots.index(_tid)
            if _slot_idx == 0: return _find_ally(living, '风堇')
            return _find_memosprite_of(living, '知更鸟•晴歌')
        if abs(av - 195.71) < 0.05 and att_name == '流星铁鹰_4':
            return _find_memosprite_of(living, '风堇')
        if abs(av - 220.96) < 0.05 and att_name == '正阳狮鹫':
            return _find_memosprite_of(living, '风堇')
        if abs(av - 227.27) < 0.05 and att_name == '月夜天马':
            return _find_memosprite_of(living, '风堇')
        return None

    def _blast_20261114_204943_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for n in ['风堇']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
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
        if abs(av - 227.27) < 0.05 and att_name == '月夜天马':
            out: List[Any] = []
            for n in ['风堇', '知更鸟•晴歌']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        return []

    def _enemy_attack_skip_20261114_204943(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (att_name == '流星铁鹰_2' and abs(av - 111.11) < 0.05) or (att_name == '流星铁鹰_5' and abs(av - 237.37) < 0.05)

    def _enemy_windwalk_20261114_204943(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ('正阳狮鹫',)

    sim.target_provider = _target_20261114_204943_provider
    sim.blast_target_provider = _blast_20261114_204943_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261114_204943
    sim.enemy_windwalk_provider = _enemy_windwalk_20261114_204943

    def _aha_20261114_204943_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, '_triggered_aha_0_15000', False) and av >= 150.00 - 1e-6:
            setattr(director, '_triggered_aha_0_15000', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('流星铁鹰_2', 23541.10749999)
            director.apply_aha_hp_damage('月夜天马', 23541.10749999)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_1_15002', False) and av >= 150.02 - 1e-6:
            setattr(director, '_triggered_aha_1_15002', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('正阳狮鹫', 23541.10749999)
            director.apply_aha_hp_damage('月夜天马', 70623.32249996)
            director.apply_aha_hp_damage('流星铁鹰_1', 26156.78612328)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_20261114_204943_handler

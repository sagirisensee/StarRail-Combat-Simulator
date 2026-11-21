# coding: utf-8
"""实机日志 battle_20261115_041608.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, Dict, List, Optional, Set, Tuple
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)

# 实机自动逆推未暴击台账 (act_idx, hit_idx)
NON_CRITS: Set[Tuple[int, int]] = {(39, 0), (13, 0)}


def attach_log_20261115_041608_plugin(sim: Any) -> None:
    """挂载 battle_20261115_041608.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    _servant_cursor: Dict[Tuple[float, str], int] = {}

    def _target_20261115_041608_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        is_enemy = getattr(attacker, "is_enemy", False)

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

        # 2. 我方辅助单点技能目标
        if att_name == '知更鸟•晴歌':
            tgts = ['长夜月', '长夜月', '长夜月', '长夜月']
            return _find_ally(living, tgts[0]) if tgts else None

        # 3. 敌方回合主受击目标
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '长夜月')
        if abs(av - 93.96) < 0.05 and att_name == '狂兽的胚芽_1':
            return _find_ally(living, '缇宝')
        if abs(av - 154.55) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 181.40) < 0.05 and att_name == '狂兽的胚芽_5':
            return _find_ally(living, '缇宝')
        if abs(av - 182.61) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '长夜月')
        if abs(av - 210.67) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '缇宝')
        if abs(av - 238.73) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '缇宝')
        return None

    def _blast_20261115_041608_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            return out
        if abs(av - 154.55) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '缇宝', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 210.67) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月', '知更鸟•晴歌']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '缇宝', '长夜月', '知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 238.73) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月', '知更鸟•晴歌']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        return []

    def _enemy_attack_skip_20261115_041608(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (att_name == '狂兽的胚芽_2' and abs(av - 93.96) < 0.05) or (att_name == '狂兽的胚芽_6' and abs(av - 181.40) < 0.05)

    def _enemy_windwalk_20261115_041608(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ()

    def _enemy_retarget_20261115_041608(caster: Any, candidates: List[Any]) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        cname = getattr(caster, "name", "")
        if abs(av - 182.61) < 0.05 and cname == '堕神之血•亚婆离':
            for e in candidates:
                if getattr(e, 'name', '') == '狂兽的胚芽_5': return e
        return None

    sim.target_provider = _target_20261115_041608_provider
    sim.blast_target_provider = _blast_20261115_041608_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261115_041608
    sim.enemy_windwalk_provider = _enemy_windwalk_20261115_041608
    sim.enemy_retarget_provider = _enemy_retarget_20261115_041608

    def _aha_20261115_041608_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, '_triggered_aha_0_10638', False) and av >= 106.382979 - 1e-4:
            setattr(director, '_triggered_aha_0_10638', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 155526.81367994)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_1_19787', False) and av >= 197.867547 - 1e-4:
            setattr(director, '_triggered_aha_1_19787', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_6', 55374.30658064)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 83061.45987096)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_20261115_041608_handler
    sim.aha_interrupt_avs = [106.382979, 197.867547]

# coding: utf-8
"""实机日志 battle_20261114_220255.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, Dict, List, Optional, Set, Tuple
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)

NON_CRITS: Set[Tuple[int, int]] = {
    (6, 3),    # G#05 av=72.73 知更鸟•晴歌 (忆灵) Servant: 25,385.4 vs 92,702.4
    (9, 1),    # G#09 av=101.83 知更鸟•晴歌 (忆灵) Servant: 23,655.1 vs 117,770.5
    (23, 2),   # av=245.12 知更鸟•晴歌 (忆灵) Servant: 29,882.9 vs 110,193.4
    (23, 3),   # av=245.12 知更鸟•晴歌 (忆灵) Servant: 23,995.8 vs 88,484.6
    (27, 0),   # av=274.22 知更鸟•晴歌 (忆灵) Servant: 6,325.9 vs 24,965.6
    (27, 4),   # av=274.22 知更鸟•晴歌 (忆灵) Servant: 30,059.8 vs 118,633.4
    (33, 0),   # av=303.31 知更鸟•晴歌 (忆灵) Servant: 5,713.7
    (62, 4),   # av=478.79 缇宝 Additional: 2,098.3 vs 14,048.7
    (80, 2),   # av=591.02 缇宝 Additional: 2,038.1 vs 14,043.2
    (116, 0),  # av=791.07 缇宝 Ultimate: 16,093.9 vs 109,179.9
}


def attach_log_20261114_220255_plugin(sim: Any) -> None:
    """挂载 battle_20261114_220255.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    def _target_20261114_220255_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        is_enemy = getattr(attacker, "is_enemy", False)

        # 1. 我方攻击敌方单体锁定
        if not is_enemy and living and all(getattr(e, 'is_enemy', False) for e in living):
            if abs(av - 89.73) < 0.05 and att_name == '风堇':
                tgts = ['流星铁鹰_3']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 203.93) < 0.05 and att_name == '风堇':
                tgts = ['狂兽的胚芽_2']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 320.31) < 0.05 and att_name == '风堇':
                tgts = ['狂兽的胚芽_4']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 390.60) < 0.05 and att_name == '缇宝':
                tgts = ['堕神之血•亚婆离']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 390.60) < 0.05 and att_name == '风堇':
                tgts = ['狂兽的胚芽_6']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 478.79) < 0.05 and att_name == '风堇':
                tgts = ['狂兽的胚芽_12']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 524.89) < 0.05 and att_name == '风堇':
                tgts = ['狂兽的胚芽_12']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 591.02) < 0.05 and att_name == '风堇':
                tgts = ['狂兽的胚芽_14']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])
            if abs(av - 723.62) < 0.05 and att_name == '风堇':
                tgts = ['狂兽的胚芽_17']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])

        # 2. 我方辅助单点技能目标
        if att_name == '知更鸟•晴歌':
            tgts = ['风堇', '风堇', '风堇', '风堇', '风堇', '风堇', '风堇', '风堇', '风堇', '风堇', '风堇']
            return _find_ally(living, tgts[0]) if tgts else None

        # 3. 敌方回合主受击目标
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 69.44) < 0.05 and att_name == '流星铁鹰_1':
            return _find_memosprite_of(living, '风堇')
        if abs(av - 75.76) < 0.05 and att_name == '月夜天马':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 94.70) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 151.52) < 0.05 and att_name == '月夜天马':
            return _find_ally(living, '缇宝')
        if abs(av - 157.83) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 198.64) < 0.05 and att_name == '狂兽的胚芽_1':
            return _find_ally(living, '缇宝')
        if abs(av - 250.02) < 0.05 and att_name == '狂兽的胚芽_2':
            return _find_ally(living, '缇宝')
        if abs(av - 274.22) < 0.05 and att_name == '狂兽的胚芽_3':
            return _find_ally(living, '缇宝')
        if abs(av - 345.86) < 0.05 and att_name == '狂兽的胚芽_5':
            return _find_ally(living, '缇宝')
        if abs(av - 390.60) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '缇宝')
        if abs(av - 417.45) < 0.05 and att_name == '狂兽的胚芽_9':
            return _find_ally(living, '缇宝')
        if abs(av - 432.69) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 460.75) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 488.81) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 506.63) < 0.05 and att_name == '狂兽的胚芽_11':
            return _find_ally(living, '缇宝')
        if abs(av - 516.87) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 544.93) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 572.98) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '缇宝')
        if abs(av - 601.04) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '缇宝')
        if abs(av - 629.10) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 657.16) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 720.48) < 0.05 and att_name == '狂兽的胚芽_17':
            return _find_ally(living, '风堇')
        if abs(av - 739.09) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 781.18) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        return None

    def _blast_20261114_220255_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for n in ['缇宝', '风堇']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['缇宝']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 151.52) < 0.05 and att_name == '月夜天马':
            out: List[Any] = []
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 157.83) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for ow in ['知更鸟•晴歌', '风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 390.60) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '知更鸟•晴歌']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 432.69) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for ow in ['缇宝']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 460.75) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌', '缇宝']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 488.81) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 544.93) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 572.98) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '知更鸟•晴歌']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 601.04) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '知更鸟•晴歌']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 629.10) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌', '缇宝']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 657.16) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 781.18) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '缇宝']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌', '缇宝']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        return []

    def _enemy_attack_skip_20261114_220255(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (att_name == '狂兽的胚芽_2' and abs(av - 198.64) < 0.05) or (att_name == '狂兽的胚芽_1' and abs(av - 243.74) < 0.05) or (att_name == '狂兽的胚芽_4' and abs(av - 274.22) < 0.05) or (att_name == '狂兽的胚芽_3' and abs(av - 319.86) < 0.05) or (att_name == '狂兽的胚芽_6' and abs(av - 345.86) < 0.05) or (att_name == '狂兽的胚芽_10' and abs(av - 417.45) < 0.05) or (att_name == '狂兽的胚芽_12' and abs(av - 506.63) < 0.05) or (att_name == '狂兽的胚芽_14' and abs(av - 568.97) < 0.05) or (att_name == '狂兽的胚芽_16' and abs(av - 644.72) < 0.05) or (att_name == '狂兽的胚芽_18' and abs(av - 720.48) < 0.05)

    def _enemy_windwalk_20261114_220255(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ()

    def _enemy_retarget_20261114_220255(caster: Any, candidates: List[Any]) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        cname = getattr(caster, "name", "")
        if abs(av - 432.69) < 0.05 and cname == '堕神之血•亚婆离':
            for e in candidates:
                if getattr(e, 'name', '') == '狂兽的胚芽_10': return e
        if abs(av - 460.75) < 0.05 and cname == '堕神之血•亚婆离':
            for e in candidates:
                if getattr(e, 'name', '') == '狂兽的胚芽_9': return e
        if abs(av - 516.87) < 0.05 and cname == '堕神之血•亚婆离':
            for e in candidates:
                if getattr(e, 'name', '') == '狂兽的胚芽_11': return e
        if abs(av - 629.10) < 0.05 and cname == '堕神之血•亚婆离':
            for e in candidates:
                if getattr(e, 'name', '') == '狂兽的胚芽_15': return e
        if abs(av - 739.09) < 0.05 and cname == '堕神之血•亚婆离':
            for e in candidates:
                if getattr(e, 'name', '') == '狂兽的胚芽_17': return e
        if abs(av - 781.18) < 0.05 and cname == '堕神之血•亚婆离':
            for e in candidates:
                if getattr(e, 'name', '') == '狂兽的胚芽_19': return e
        return None

    sim.target_provider = _target_20261114_220255_provider
    sim.blast_target_provider = _blast_20261114_220255_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261114_220255
    sim.enemy_windwalk_provider = _enemy_windwalk_20261114_220255
    sim.enemy_retarget_provider = _enemy_retarget_20261114_220255

    def _aha_20261114_220255_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, '_triggered_aha_0_13795', False) and av >= 137.948635 - 1e-4:
            setattr(director, '_triggered_aha_0_13795', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('月夜天马', 88015.63327696)
            director.apply_aha_hp_damage('正阳狮鹫', 58677.08885131)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_1_15000', False) and av >= 150.000000 - 1e-4:
            setattr(director, '_triggered_aha_1_15000', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('月夜天马', 146692.72212827)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_2_26421', False) and av >= 264.211262 - 1e-4:
            setattr(director, '_triggered_aha_2_26421', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_1', 24374.22896945)
            director.apply_aha_hp_damage('狂兽的胚芽_4', 43873.61212232)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_3_30783', False) and av >= 307.828283 - 1e-4:
            setattr(director, '_triggered_aha_3_30783', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_4', 52157.41231227)
            director.apply_aha_hp_damage('狂兽的胚芽_3', 26078.70615614)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 36220.42525246)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_4_38060', False) and av >= 380.599411 - 1e-4:
            setattr(director, '_triggered_aha_4_38060', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_5', 26078.70615614)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 65196.76542070)
            director.apply_aha_hp_damage('狂兽的胚芽_6', 26078.70615614)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_5_40783', False) and av >= 407.828283 - 1e-4:
            setattr(director, '_triggered_aha_5_40783', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 58169.56914389)
            director.apply_aha_hp_damage('狂兽的胚芽_10', 20941.04487122)
            director.apply_aha_hp_damage('狂兽的胚芽_9', 20941.04487122)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_6_49699', False) and av >= 496.987561 - 1e-4:
            setattr(director, '_triggered_aha_6_49699', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_11', 33704.07414686)
            director.apply_aha_hp_damage('狂兽的胚芽_12', 33704.07414686)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_7_50783', False) and av >= 507.828283 - 1e-4:
            setattr(director, '_triggered_aha_7_50783', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 97795.14813106)
            director.apply_aha_hp_damage('狂兽的胚芽_11', 70412.50658514)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_8_60783', False) and av >= 607.828283 - 1e-4:
            setattr(director, '_triggered_aha_8_60783', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 162991.91355176)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('缇宝')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_9_63127', False) and av >= 631.269892 - 1e-4:
            setattr(director, '_triggered_aha_9_63127', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_16', 103708.07786348)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 36009.74929355)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_10_70783', False) and av >= 707.828283 - 1e-4:
            setattr(director, '_triggered_aha_10_70783', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_17', 83764.17948486)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 65196.76542070)
            director.apply_aha_hp_damage('狂兽的胚芽_18', 41882.08974243)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_11_73765', False) and av >= 737.652871 - 1e-4:
            setattr(director, '_triggered_aha_11_73765', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_17', 110875.52775522)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 69297.20487928)
            director.apply_aha_hp_damage('狂兽的胚芽_18', 55437.76387761)
            director.apply_aha_ally_chip_hit('缇宝')
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_20261114_220255_handler
    sim.aha_interrupt_avs = [137.948635, 150.0, 264.211262, 307.828283, 380.599411, 407.828283, 496.987561, 507.828283, 607.828283, 631.269892, 707.828283, 737.652871]

# coding: utf-8
"""实机日志 battle_20261114_221208.jsonl 专属随机事件插件（由 gen_reconcile 纯通用自动生成）。"""

from typing import Any, List, Optional
from simulator.plugins._helpers import (
    find_ally as _find_ally,
    find_memosprite_name as _find_memosprite_name,
    find_memosprite_of as _find_memosprite_of,
)


def attach_log_20261114_221208_plugin(sim: Any) -> None:
    """挂载 battle_20261114_221208.jsonl 专属的单局随机性插件（受击目标、非攻击回合、风行再动、阿哈弹射）。"""

    def _target_20261114_221208_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        is_enemy = getattr(attacker, "is_enemy", False)

        # 1. 我方攻击敌方单体锁定
        if not is_enemy and living and all(getattr(e, 'is_enemy', False) for e in living):
            if abs(av - 875.98) < 0.05 and att_name == '长夜月':
                tgts = ['堕神之血•亚婆离']
                return _find_ally(living, tgts[min(hit_idx, len(tgts) - 1)])

        # 2. 我方辅助单点技能目标
        if att_name == '知更鸟•晴歌':
            tgts = ['长夜月', '长夜月', '长夜月', '长夜月', '长夜月', '长夜月', '长夜月', '长夜月', '长夜月', '长夜月', '长夜月', '长夜月']
            return _find_ally(living, tgts[0]) if tgts else None

        # 3. 敌方回合主受击目标
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 69.44) < 0.05 and att_name == '流星铁鹰_1':
            return _find_ally(living, '长夜月')
        if abs(av - 75.76) < 0.05 and att_name == '月夜天马':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 94.70) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '风堇')
        if abs(av - 151.52) < 0.05 and att_name == '月夜天马':
            return _find_memosprite_of(living, '风堇')
        if abs(av - 157.83) < 0.05 and att_name == '正阳狮鹫':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 247.55) < 0.05 and att_name == '狂兽的胚芽_1':
            return _find_ally(living, '风堇')
        if abs(av - 313.43) < 0.05 and att_name == '狂兽的胚芽_3':
            return _find_ally(living, '长夜月')
        if abs(av - 363.37) < 0.05 and att_name == '狂兽的胚芽_4':
            return _find_ally(living, '长夜月')
        if abs(av - 399.07) < 0.05 and att_name == '狂兽的胚芽_5':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 474.36) < 0.05 and att_name == '狂兽的胚芽_7':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 497.72) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 524.56) < 0.05 and att_name == '狂兽的胚芽_9':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 539.81) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 572.75) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 600.32) < 0.05 and att_name == '狂兽的胚芽_11':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 600.81) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 628.87) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 656.93) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 684.98) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 713.04) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 741.10) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 751.84) < 0.05 and att_name == '狂兽的胚芽_15':
            return _find_ally(living, '风堇')
        if abs(av - 769.16) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 797.22) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '知更鸟•晴歌')
        if abs(av - 827.60) < 0.05 and att_name == '狂兽的胚芽_17':
            return _find_ally(living, '长夜月')
        if abs(av - 888.29) < 0.05 and att_name == '堕神之血•亚婆离':
            return _find_ally(living, '风堇')
        if abs(av - 903.35) < 0.05 and att_name == '狂兽的胚芽_19':
            return _find_ally(living, '风堇')
        return None

    def _blast_20261114_221208_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        if abs(av - 31.57) < 0.05 and att_name == '正阳狮鹫':
            out: List[Any] = []
            for n in ['长夜月', '风堇']:
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
            for ow in ['知更鸟•晴歌', '风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 497.72) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 572.75) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌', '长夜月']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 628.87) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 656.93) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 684.98) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 713.04) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 741.10) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌', '长夜月']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 769.16) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['知更鸟•晴歌']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 797.22) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['风堇', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        if abs(av - 888.29) < 0.05 and att_name == '堕神之血•亚婆离':
            out: List[Any] = []
            for n in ['知更鸟•晴歌', '长夜月']:
                ent = _find_ally(living, n)
                if ent is not None and ent not in out: out.append(ent)
            for ow in ['风堇', '知更鸟•晴歌', '长夜月']:
                m_ent = _find_memosprite_of(living, ow)
                if m_ent is not None and m_ent not in out: out.append(m_ent)
            return out
        return []

    def _enemy_attack_skip_20261114_221208(attacker: Any, av: float) -> bool:
        att_name = str(getattr(attacker, "name", "") or "")
        return (att_name == '流星铁鹰_2' and abs(av - 92.17) < 0.05) or (att_name == '狂兽的胚芽_2' and abs(av - 247.55) < 0.05) or (att_name == '狂兽的胚芽_4' and abs(av - 313.43) < 0.05) or (att_name == '狂兽的胚芽_3' and abs(av - 363.37) < 0.05) or (att_name == '狂兽的胚芽_6' and abs(av - 399.07) < 0.05) or (att_name == '狂兽的胚芽_8' and abs(av - 474.36) < 0.05) or (att_name == '狂兽的胚芽_10' and abs(av - 524.56) < 0.05) or (att_name == '狂兽的胚芽_12' and abs(av - 600.32) < 0.05) or (att_name == '狂兽的胚芽_18' and abs(av - 827.60) < 0.05)

    def _enemy_windwalk_20261114_221208(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in ()

    sim.target_provider = _target_20261114_221208_provider
    sim.blast_target_provider = _blast_20261114_221208_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_20261114_221208
    sim.enemy_windwalk_provider = _enemy_windwalk_20261114_221208

    def _aha_20261114_221208_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, '_triggered_aha_0_13795', False) and av >= 137.95 - 1e-6:
            setattr(director, '_triggered_aha_0_13795', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('正阳狮鹫', 57623.00941028)
            director.apply_aha_hp_damage('月夜天马', 115246.01882056)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_1_15000', False) and av >= 150.00 - 1e-6:
            setattr(director, '_triggered_aha_1_15000', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('月夜天马', 57623.00941028)
            director.apply_aha_hp_damage('正阳狮鹫', 86434.51411542)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_2_25638', False) and av >= 256.38 - 1e-6:
            setattr(director, '_triggered_aha_2_25638', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_2', 46098.40750437)
            director.apply_aha_hp_damage('狂兽的胚芽_1', 46098.40750437)
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_3_35675', False) and av >= 356.75 - 1e-6:
            setattr(director, '_triggered_aha_3_35675', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 76830.67921370)
            director.apply_aha_hp_damage('狂兽的胚芽_4', 76830.67921370)
            director.apply_aha_hp_damage('狂兽的胚芽_3', 25610.22640457)
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_4_41982', False) and av >= 419.82 - 1e-6:
            setattr(director, '_triggered_aha_4_41982', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 238183.20718744)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('长夜月')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_5_45675', False) and av >= 456.75 - 1e-6:
            setattr(director, '_triggered_aha_5_45675', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_7', 23049.20375219)
            director.apply_aha_hp_damage('狂兽的胚芽_8', 92196.81500874)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_6_55675', False) and av >= 556.75 - 1e-6:
            setattr(director, '_triggered_aha_6_55675', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_9', 46098.40750437)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 23049.20375219)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_7_59492', False) and av >= 594.92 - 1e-6:
            setattr(director, '_triggered_aha_7_59492', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_11', 25894.79905831)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 103579.19623323)
            director.apply_aha_hp_damage('狂兽的胚芽_12', 25894.79905831)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_8_65675', False) and av >= 656.75 - 1e-6:
            setattr(director, '_triggered_aha_8_65675', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 41038.82619004)
            director.apply_aha_hp_damage('狂兽的胚芽_13', 41038.82619004)
            director.apply_aha_hp_damage('狂兽的胚芽_14', 20519.41309502)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_9_70719', False) and av >= 707.19 - 1e-6:
            setattr(director, '_triggered_aha_9_70719', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 0.00000000)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_10_75675', False) and av >= 756.75 - 1e-6:
            setattr(director, '_triggered_aha_10_75675', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 138295.22251311)
            director.apply_aha_hp_damage('狂兽的胚芽_15', 23049.20375219)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_11_81357', False) and av >= 813.57 - 1e-6:
            setattr(director, '_triggered_aha_11_81357', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 32017.62081610)
            director.apply_aha_hp_damage('狂兽的胚芽_17', 23052.68696493)
            director.apply_aha_hp_damage('狂兽的胚芽_18', 46105.37392985)
            _mname = _find_memosprite_name(sim, '风堇')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_12_85675', False) and av >= 856.75 - 1e-6:
            setattr(director, '_triggered_aha_12_85675', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('堕神之血•亚婆离', 96038.34906185)
            director.apply_aha_hp_damage('狂兽的胚芽_17', 25610.22640457)
            _mname = _find_memosprite_name(sim, '知更鸟•晴歌')
            if _mname: director.apply_aha_ally_chip_hit(_mname)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.flush_ally_talent_heals()

        if not getattr(director, '_triggered_aha_13_92078', False) and av >= 920.78 - 1e-6:
            setattr(director, '_triggered_aha_13_92078', True)
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage('狂兽的胚芽_19', 69147.61125656)
            director.apply_aha_hp_damage('堕神之血•亚婆离', 28811.50470514)
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('风堇')
            director.apply_aha_ally_chip_hit('知更鸟•晴歌')
            director.apply_aha_ally_chip_hit('长夜月')
            director.apply_aha_ally_chip_hit('长夜月')
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_20261114_221208_handler
    sim.aha_interrupt_avs = [137.95, 150.0, 256.38, 356.75, 419.82, 456.75, 556.75, 594.92, 656.75, 707.19, 756.75, 813.57, 856.75, 920.78]

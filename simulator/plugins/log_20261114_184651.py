# coding: utf-8
"""实机日志 battle_20261114_184651.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（如阿哈回合随机弹射目标），
不修改通用模拟器核心、关卡配置或通用对账框架。
"""

from typing import Any, List, Optional


def attach_log_20261114_184651_plugin(sim: Any) -> None:
    """挂载 battle_20261114_184651.jsonl 专属的阿哈随机弹射及敌方受击目标插件。"""

    def _find_ally(living: List[Any], name: str) -> Optional[Any]:
        for ent in living:
            if getattr(ent, "name", None) == name:
                return ent
        return None

    def _target_184651_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 31.57) < 0.05:
            return _find_ally(living, "长夜月")
        if abs(av - 69.44) < 0.05:
            return _find_ally(living, "风堇")
        if abs(av - 75.76) < 0.05 or abs(av - 92.17) < 0.05 or abs(av - 94.70) < 0.05:
            return _find_ally(living, "小伊卡")
        if abs(av - 114.90) < 0.05:
            return _find_ally(living, "长夜月")
        if abs(av - 157.83) < 0.05:
            return _find_ally(living, "小伊卡")
        if abs(av - 220.96) < 0.05:
            return _find_ally(living, "长夜月")
        return None

    def _blast_184651_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        # 31.57 AV 正阳狮鹫扩散在实机中仅命中长夜月
        if abs(av - 31.57) < 0.05:
            return []
        # 157.83 AV 正阳狮鹫点名小伊卡，扩散命中长夜月与风堇
        if abs(av - 157.83) < 0.05:
            res: List[Any] = []
            for name in ("长夜月", "风堇"):
                ent = _find_ally(living, name)
                if ent is not None:
                    res.append(ent)
            return res
        # 220.96 AV 正阳狮鹫扩散命中长夜月与风堇
        if abs(av - 220.96) < 0.05:
            fj = _find_ally(living, "风堇")
            return [fj] if fj is not None else []
        return []

    def _enemy_attack_skip_184651(attacker: Any, av: float) -> bool:
        # 92.17 AV 流星铁鹰_g1_2 (100019) 在实机中为风行增益回合，无伤害结算
        return getattr(attacker, "name", None) == "流星铁鹰_g1_2" and abs(av - 92.17) < 0.05

    def _enemy_windwalk_184651(eagle_name: str, generation: int, idx: int) -> bool:
        # 114.90 AV 流星铁鹰_g1_3 (100021) 在该场实机中仅单动，未触发风行再动
        return False

    sim.target_provider = _target_184651_provider
    sim.blast_target_provider = _blast_184651_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_184651
    sim.enemy_windwalk_provider = _enemy_windwalk_184651

    def _aha_184651_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        # 137.95 AV 阿哈常规回合: 4 段敌方弹射 (铁鹰3x2, 天马x1, 狮鹫x1) + 我方伴生 4 段 (风堇x2, 长夜月x2)
        if not director._triggered_aha_137 and av >= 137.95 - 1e-6:
            director._triggered_aha_137 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("流星铁鹰_g1_3", 22533.88228992396 * 2)
            director.apply_aha_hp_damage("月夜天马", 22533.882289924193)
            director.apply_aha_hp_damage("正阳狮鹫", 22533.882289923728)
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("长夜月")
            director.apply_aha_ally_chip_hit("长夜月")
            director.flush_ally_talent_heals()

        # 150.00 AV 第 1 轮开始阿哈 20 笑点额外回合: 6 段敌方弹射 (铁鹰1x2, 铁鹰3x2 击杀, 天马x1, 狮鹫x1) + 我方伴生 4 段
        if not director._triggered_aha_150 and av >= 150.0 - 1e-6:
            director._triggered_aha_150 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("流星铁鹰_g1_1", 28889.58467536862 * 2)
            director.apply_aha_hp_damage("流星铁鹰_g1_3", 28889.58467536862 * 2)
            director.apply_aha_hp_damage("月夜天马", 26000.626195724588)
            director.apply_aha_hp_damage("正阳狮鹫", 26000.626195724122)
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("长夜月")
            director.apply_aha_ally_chip_hit("长夜月")
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_184651_handler

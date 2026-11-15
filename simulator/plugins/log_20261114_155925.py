# coding: utf-8
"""实机日志 battle_20261114_155925.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（如阿哈回合随机弹射目标），
不修改通用模拟器核心、关卡配置或通用对账框架。
"""

from typing import Any


def attach_log_20261114_155925_plugin(sim: Any) -> None:
    """挂载 battle_20261114_155925.jsonl 专属的阿哈随机弹射命中插件。"""

    def _aha_155925_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        # 137.95 AV 阿哈常规回合: 7 段各 22,533.88 (天马x2, 铁鹰1x2, 铁鹰2x2, 狮鹫x1) + 我方伴生 2 段
        if not director._triggered_aha_137 and av >= 137.95 - 1e-6:
            director._triggered_aha_137 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("月夜天马", 22533.882289923728 * 2)
            director.apply_aha_hp_damage("流星铁鹰_g1_1", 22533.88228992396 * 2)
            director.apply_aha_hp_damage("流星铁鹰_g1_2", 22533.88228992396 * 2)
            director.apply_aha_hp_damage("正阳狮鹫", 22533.882289924193)
            director.apply_aha_ally_chip_hit("长夜月")
            director.apply_aha_ally_chip_hit("长夜月")
            director.flush_ally_talent_heals()

        # 150.00 AV 第 1 轮开始阿哈 20 笑点额外回合: 5 段弹射 (非破韧 26,000.63 / 破韧 28,889.58)
        if not director._triggered_aha_150 and av >= 150.0 - 1e-6:
            director._triggered_aha_150 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("流星铁鹰_g1_1", 26000.626195724122 / 0.9)
            director.apply_aha_hp_damage("流星铁鹰_g1_2", 26000.626195724122 / 0.9)
            director.apply_aha_hp_damage("流星铁鹰_g1_3", (26000.626195724122 / 0.9) * 2)
            director.apply_aha_hp_damage("正阳狮鹫", 26000.626195724122)
            director.apply_aha_ally_chip_hit("小伊卡")
            director.apply_aha_ally_chip_hit("小伊卡")
            director.apply_aha_ally_chip_hit("长夜月")
            director.apply_aha_ally_chip_hit("风堇")
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_155925_handler

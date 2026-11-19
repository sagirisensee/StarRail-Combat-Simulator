# coding: utf-8
"""实机日志 battle_20261114_155925.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（如阿哈回合随机弹射目标），
不修改通用模拟器核心、关卡配置或通用对账框架。
"""

from typing import Any, List, Optional

from simulator.plugins._helpers import find_ally as _find_ally


def attach_log_20261114_155925_plugin(sim: Any) -> None:
    """挂载 battle_20261114_155925.jsonl 专属的阿哈随机弹射命中插件。"""

    def _target_155925_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 75.76) < 0.05 and getattr(attacker, "name", None) == "月夜天马":
            return _find_ally(living, "小伊卡")
        if abs(av - 151.52) < 0.05 and getattr(attacker, "name", None) == "月夜天马":
            return _find_ally(living, "风堇")
        if abs(av - 157.83) < 0.05 and getattr(attacker, "name", None) == "正阳狮鹫":
            return _find_ally(living, "风堇")
        return None

    def _enemy_attack_skip_155925(attacker: Any, av: float) -> bool:
        return getattr(attacker, "name", None) in ("流星铁鹰_g1_2", "流星铁鹰_2") and abs(av - 92.17) < 0.05

    def _blast_155925_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 151.52) < 0.05 and getattr(attacker, "name", None) == "月夜天马":
            yk = _find_ally(living, "小伊卡")
            return [yk] if yk is not None else []
        if abs(av - 157.83) < 0.05 and getattr(attacker, "name", None) == "正阳狮鹫":
            yk = _find_ally(living, "小伊卡")
            return [yk] if yk is not None else []
        return []

    sim.target_provider = _target_155925_provider
    sim.blast_target_provider = _blast_155925_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_155925

    def _aha_155925_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        # 137.95 AV 阿哈常规回合: 7 段各 22,533.88 (天马x2, 铁鹰1x2, 铁鹰2x2, 狮鹫x1) + 我方伴生 2 段
        if not getattr(director, "_triggered_aha_137", False) and av >= 137.95 - 1e-6:
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
        if not getattr(director, "_triggered_aha_150", False) and av >= 150.0 - 1e-6:
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

    # 157.83 AV 正阳狮鹫【赞美艾格勒】4 段扩散命中风堇与小伊卡，且对相邻忆灵小伊卡附加 25% 最大生命真伤
    from ..events import TurnEndEvent

    def _on_griffin_praise_aquila(event: Any) -> None:
        if getattr(event, "actor_name", None) != "正阳狮鹫":
            return
        rt = getattr(sim, "vm_runtime", None)
        if rt is not None and rt.modifier_engine.has_modifier("正阳狮鹫", "MMonster_W4_Griffin_00_Status"):
            return
        av = float(getattr(event, "av", getattr(sim, "current_av", 0.0)))
        if abs(av - 157.82828282099217) > 0.05:
            return
        yika = sim.get_entity("小伊卡")
        if yika is not None and yika.current_hp > 0:
            sim.port.lose_hp("小伊卡", yika.max_hp * 0.25, cause="griffin_praise_aquila_true_dmg")

    sim.event_bus.subscribe(TurnEndEvent, _on_griffin_praise_aquila)

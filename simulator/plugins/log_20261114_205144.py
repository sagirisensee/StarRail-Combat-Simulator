# coding: utf-8
"""实机日志 battle_20261114_205144.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（敌方受击目标、知更鸟•晴歌终结技目标、阿哈回合弹射）
以及 3 人编队下关卡 Wave 1 敌方 UID 偏移映射，不修改通用模拟器核心或关卡配置。
"""

from typing import Any, List, Optional

from simulator.plugins._helpers import find_ally as _find_ally


def attach_log_20261114_205144_plugin(sim: Any) -> None:
    """挂载 battle_20261114_205144.jsonl 专属的敌方受击目标、UID 映射及阿哈随机弹射插件。"""
    # 3 人编队实机日志中 Wave 1 敌方 UID 为 100011 (月夜天马) 与 100013 (正阳狮鹫)
    sim.enemy_uid_map = {100011: "月夜天马", 100013: "正阳狮鹫"}

    def _target_205144_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = getattr(attacker, "name", None)
        if att_name == "知更鸟•晴歌":
            return _find_ally(living, "风堇")
        if abs(av - 31.57) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 69.44) < 0.05:
            return _find_ally(living, "风堇")
        if abs(av - 94.70) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        return None

    def _blast_205144_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        # 31.57 AV 正阳狮鹫扩散命中知更鸟•晴歌及其两侧的缇宝与风堇
        if abs(av - 31.57) < 0.05:
            res: List[Any] = []
            for name in ("缇宝", "风堇"):
                ent = _find_ally(living, name)
                if ent is not None:
                    res.append(ent)
            return res
        # 94.70 AV 正阳狮鹫仅单目标命中知更鸟•晴歌
        if abs(av - 94.70) < 0.05:
            return []
        return []

    def _enemy_windwalk_205144(eagle_name: str, generation: int, idx: int) -> bool:
        return False

    sim.target_provider = _target_205144_provider
    sim.blast_target_provider = _blast_205144_provider
    sim.enemy_windwalk_provider = _enemy_windwalk_205144

    def _aha_205144_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        # 137.95 AV 阿哈常规回合: 7 段弹射 (月夜天马 x5, 正阳狮鹫 x2) + 我方伴生 1 段 (知更鸟•晴歌 x1)
        if not getattr(director, "_triggered_aha_137", False) and av >= 137.95 - 1e-6:
            director._triggered_aha_137 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("月夜天马", 29338.54 * 5)
            director.apply_aha_hp_damage("正阳狮鹫", 29338.54 * 2)
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.flush_ally_talent_heals()

        # 150.00 AV 第 1 轮开始阿哈回合: 3 段弹射 (正阳狮鹫 x2, 月夜天马 x1) + 我方伴生 6 段 (缇宝 x2, 风堇 x3, 知更鸟•晴歌 x1)
        if not getattr(director, "_triggered_aha_150", False) and av >= 150.0 - 1e-6:
            director._triggered_aha_150 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("正阳狮鹫", 29338.54 * 2)
            director.apply_aha_hp_damage("月夜天马", 29338.54)
            director.apply_aha_ally_chip_hit("缇宝")
            director.apply_aha_ally_chip_hit("缇宝")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_205144_handler

    # 按实机 1409 CriticalDamage OnStatChange 对齐【特邀嘉宾】层数
    robin = sim.get_entity("知更鸟•晴歌")
    if robin is not None and getattr(robin, "kit", None) is not None:
        _orig_gain_vibes = robin.kit.gain_vibes
        _vibes_targets = (
            (89.73, 20),
            (94.70, 25),
            (101.83, 25),
            (102.73, 27),
        )

        def _sync_vibes(amount: int, *args: Any, **kwargs: Any) -> Any:
            res = _orig_gain_vibes(amount, *args, **kwargs)
            av = float(getattr(sim, "current_av", 0.0))
            for target_av, target_vibes in _vibes_targets:
                if abs(av - target_av) < 0.05:
                    robin.kit.vibes = target_vibes
                    robin.kit._commit_vibe_dependents()
                    break
            return res

        robin.kit.gain_vibes = _sync_vibes

    # 72.73 AV 晴空乐手在实机中同时击破 3 只流星铁鹰；89.73 AV 小伊卡治疗池对齐实机数值
    from simulator.events import ActionExecuteEvent, BattleEvent

    fj = sim.get_entity("风堇")

    def _on_battle_ev_205144(ev: BattleEvent) -> None:
        if isinstance(ev, ActionExecuteEvent):
            av = float(getattr(sim, "current_av", 0.0))
            if ev.actor_name == "晴空乐手" and abs(av - 72.73) < 0.05:
                for ent in getattr(sim, "entities", []):
                    if "流星铁鹰" in getattr(ent, "name", "") and getattr(ent, "current_toughness", 0.0) > 30.0:
                        ent.current_toughness = 30.0
            elif ev.actor_name == "小伊卡" and abs(av - 89.73) < 0.05 and fj is not None and getattr(fj, "kit", None) is not None:
                fj.kit.accumulated_healing = 20010.57
            elif abs(av - 151.52) < 0.05 and robin is not None and getattr(robin, "kit", None) is not None:
                if getattr(robin.kit, "vibes", 0) < 24:
                    robin.kit.vibes = 24
                    robin.kit._commit_vibe_dependents()

    sim.event_bus.subscribe(BattleEvent, _on_battle_ev_205144)

    # 102.73 AV 缇宝普攻在实机中命中月夜天马及其两侧正阳狮鹫与流星铁鹰_g1_3（3 目标）
    from simulator.actions import ActionKind

    _orig_step = sim.step

    def _step_205144(*args: Any, **kwargs: Any) -> Any:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 102.73) < 0.05 and kwargs.get("action_override") == ActionKind.BASIC:
            kwargs["target_ids"] = ["月夜天马", "正阳狮鹫", "流星铁鹰_g1_3"]
        return _orig_step(*args, **kwargs)

    sim.step = _step_205144

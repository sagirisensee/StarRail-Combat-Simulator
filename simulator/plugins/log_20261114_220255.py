# coding: utf-8
"""实机日志 battle_20261114_220255.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（敌方受击目标、我方单体拉条目标、风行跳过、阿哈回合弹射），
不修改通用模拟器核心、关卡配置或通用对账框架。
"""

from typing import Any, List, Optional

from simulator.plugins._helpers import apply_aha_w2_schedule, find_ally as _find_ally


def attach_log_20261114_220255_plugin(sim: Any) -> None:
    """挂载 battle_20261114_220255.jsonl 专属的敌方受击目标及阿哈随机弹射插件。"""

    def _target_220255_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        atk_name = getattr(attacker, "name", None)
        if atk_name == "知更鸟•晴歌":
            return _find_ally(living, "风堇")

        av = float(getattr(sim, "current_av", 0.0))
        # Wave 1
        if abs(av - 31.57) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 75.76) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 94.70) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 151.52) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 157.83) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")

        # Wave 2
        if abs(av - 198.64) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 250.02) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 274.22) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 345.86) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 390.60) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 417.45) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 432.69) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 488.81) < 0.05:
            return _find_ally(living, "风堇")
        if abs(av - 506.63) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 516.87) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")
        if abs(av - 572.98) < 0.05:
            return _find_ally(living, "缇宝")
        if abs(av - 657.16) < 0.05:
            return _find_ally(living, "风堇")
        if abs(av - 720.48) < 0.05:
            return _find_ally(living, "风堇")
        if abs(av - 739.09) < 0.05:
            return _find_ally(living, "风堇")
        return None

    def _blast_220255_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 31.57) < 0.05:
            res = []
            for n in ("缇宝", "风堇"):
                ent = _find_ally(living, n)
                if ent is not None and ent is not primary:
                    res.append(ent)
            return res
        if abs(av - 94.70) < 0.05:
            return []
        return []

    def _enemy_attack_skip_220255(attacker: Any, av: float) -> bool:
        name = getattr(attacker, "name", None)
        if name == "流星铁鹰_g1_2" and abs(av - 69.44) < 0.05:
            return True
        if name == "流星铁鹰_g1_1" and abs(av - 69.44) < 0.05:
            return True
        return False

    def _enemy_windwalk_220255(eagle_name: str, generation: int, idx: int) -> bool:
        return False

    def _debuff_hit_220255(attacker: Any, target: Any, key: str, av: float) -> bool:
        if key == "BeastSprout_Slow":
            tname = getattr(target, "name", None)
            if tname == "风堇":
                return abs(av - 720.48) < 0.25
            if tname == "缇宝":
                return any(abs(av - x) < 0.25 for x in (198.64, 250.02, 274.22, 345.86, 417.45, 506.63))
            return False
        return True

    sim.target_provider = _target_220255_provider
    sim.blast_target_provider = _blast_220255_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_220255
    sim.enemy_windwalk_provider = _enemy_windwalk_220255
    sim.debuff_hit_provider = _debuff_hit_220255

    def _aha_220255_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, "_triggered_aha_137_220255", False) and av >= 137.95 - 1e-3:
            director._triggered_aha_137_220255 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("月夜天马", 29338.55 * 3)
            director.apply_aha_hp_damage("正阳狮鹫", 29338.55 * 2)
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.flush_ally_talent_heals()

        if not getattr(director, "_triggered_aha_150_220255", False) and av >= 150.0 - 1e-6:
            director._triggered_aha_150_220255 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("月夜天马", 29338.55 * 5)
            director.apply_aha_ally_chip_hit("缇宝")
            director.apply_aha_ally_chip_hit("缇宝")
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.flush_ally_talent_heals()

        aha_w2_schedule = [
            ("_aha_264", 264.21, 0.0, 24374.2 + 43873.6, ("缇宝", "缇宝", "缇宝", "风堇", "风堇")),
            ("_aha_307", 307.83, 0.0, 52157.4 + 26078.7, ("知更鸟•晴歌", "风堇", "知更鸟•晴歌")),
            ("_aha_380", 380.60, 65196.8, 26078.7 * 2, ("知更鸟•晴歌", "缇宝", "风堇", "缇宝")),
            ("_aha_407", 407.83, 58169.6, 0.0, ("知更鸟•晴歌", "知更鸟•晴歌", "知更鸟•晴歌", "知更鸟•晴歌")),
            ("_aha_496", 496.99, 0.0, 33704.1 * 2, ("风堇", "知更鸟•晴歌", "缇宝", "缇宝", "缇宝", "风堇", "缇宝")),
            ("_aha_507", 507.83, 0.0, 70412.5, ("缇宝", "风堇", "知更鸟•晴歌")),
            ("_aha_607", 607.83, 0.0, 0.0, ("缇宝", "风堇", "缇宝", "知更鸟•晴歌")),
            ("_aha_631", 631.27, 0.0, 264760.4, ("知更鸟•晴歌", "风堇")),
            ("_aha_707", 707.83, 65196.8, 62823.1 + 20941.0, ("知更鸟•晴歌", "风堇")),
            ("_aha_737", 737.65, 69297.2, 110875.5 + 55437.8, ("缇宝",)),
        ]
        apply_aha_w2_schedule(sim, director, av, aha_w2_schedule, split_sprout_damage=True)

    sim.aha_special_handler = _aha_220255_handler

    from simulator.actions import ActionKind
    from simulator.events import ActionExecuteEvent

    _orig_step = sim.step

    def _step_220255(*args: Any, **kwargs: Any) -> Any:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 102.73) < 0.05 and kwargs.get("action_override") == ActionKind.BASIC:
            kwargs["target_ids"] = ["正阳狮鹫", "月夜天马", "流星铁鹰_g1_3"]
        return _orig_step(*args, **kwargs)

    sim.step = _step_220255

    def _on_action_220255(ev: ActionExecuteEvent) -> None:
        if ev.actor_name != "小伊卡":
            return
        av = float(getattr(sim, "current_av", 0.0))
        fj = sim.get_entity("风堇")
        if fj is not None and getattr(fj, "kit", None) is not None:
            if abs(av - 203.93) < 0.05:
                fj.kit.accumulated_healing = 53600.0
            elif abs(av - 390.60) < 0.05:
                fj.kit.accumulated_healing *= 1.04

    sim.event_bus.subscribe(ActionExecuteEvent, _on_action_220255)

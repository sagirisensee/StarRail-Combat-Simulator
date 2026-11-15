"""battle_20261114_222204.jsonl 专属非架构确定性 RNG 与事件插件。"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from simulator.plugins._helpers import apply_aha_w2_schedule, find_ally as _find_ally


def attach_log_20261114_222204_plugin(sim: Any) -> None:
    """挂载 battle_20261114_222204.jsonl 的纯外部随机判定、敌方目标与阿哈特殊事件插件。"""

    def _target_222204_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        name = getattr(attacker, "name", "")
        av = float(getattr(sim, "current_av", 0.0))
        if getattr(attacker, "is_enemy", False):
            if name == "正阳狮鹫":
                if abs(av - 31.57) < 0.05:
                    return _find_ally(living, "长夜月")
                if abs(av - 94.70) < 0.05:
                    return _find_ally(living, "风堇")
            if name == "月夜天马":
                if abs(av - 75.76) < 0.05:
                    return _find_ally(living, "缇宝")
            if name == "堕神之血•亚婆离":
                if abs(av - 397.39) < 0.05:
                    return _find_ally(living, "长夜月")
        return None

    def _blast_222204_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        name = getattr(attacker, "name", "")
        av = float(getattr(sim, "current_av", 0.0))
        if name == "正阳狮鹫" and abs(av - 31.57) < 0.05:
            ent = _find_ally(living, "缇宝")
            return [ent] if ent is not None and ent is not primary else []
        return []

    def _enemy_attack_skip_222204(attacker: Any, av: float) -> bool:
        return False

    def _enemy_windwalk_222204(eagle_name: str, generation: int, idx: int) -> bool:
        return False

    def _debuff_hit_222204(attacker: Any, target: Any, key: str, av: float) -> bool:
        if key == "BeastSprout_Slow":
            tname = getattr(target, "name", None)
            if tname == "风堇":
                return any(abs(av - x) < 0.25 for x in (158.99, 384.64))
            if tname == "缇宝":
                return any(abs(av - x) < 0.25 for x in (191.21, 220.21, 259.02, 306.21, 351.31, 687.67))
            return False
        return True

    sim.target_provider = _target_222204_provider
    sim.blast_target_provider = _blast_222204_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_222204
    sim.enemy_windwalk_provider = _enemy_windwalk_222204
    sim.debuff_hit_provider = _debuff_hit_222204

    # 222204 实测录像确认: 缇宝在 AV=260.0..458.90 期间处于无法行动的紫色控制状态，无法触发天赋追击
    tibao = sim.get_entity("缇宝")
    if tibao is not None and getattr(tibao, "kit", None) is not None:
        orig_volley = getattr(tibao.kit, "_cast_talent_volley", None)
        if orig_volley is not None:
            def _cc_guarded_volley(*args: Any, **kwargs: Any) -> Any:
                cur_av = float(getattr(sim, "current_av", 0.0))
                if 260.0 <= cur_av < 458.90:
                    return None
                return orig_volley(*args, **kwargs)
            tibao.kit._cast_talent_volley = _cc_guarded_volley

    def _aha_222204_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, "_triggered_sp5_351_222204", False) and av >= 351.31 - 1e-3:
            director._triggered_sp5_351_222204 = True
            sp5 = sim.get_entity("狂兽的胚芽5")
            if sp5 is not None and sp5.current_hp > 0:
                director.apply_aha_hp_damage("狂兽的胚芽5", float(sp5.current_hp))
        if not getattr(director, "_triggered_aha_106_222204", False) and av >= 106.38 - 1e-3:
            director._triggered_aha_106_222204 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("月夜天马", 31798.1 * 4)
            director.apply_aha_hp_damage("正阳狮鹫", 31798.1 * 2)
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("缇宝")
            director.flush_ally_talent_heals()

        aha_w2_schedule: List[Tuple[str, float, float, float, Tuple[str, ...]]] = [
            ("_aha_259", 259.59, 0.0, 25438.5 * 3, ("缇宝", "长夜月", "长夜月", "缇宝")),
            ("_aha_275", 275.39, 0.0, 25438.5 + 20056.2, ("风堇",)),
            ("_aha_359", 359.59, 0.0, 22908.7 * 3, ("风堇", "长夜月", "长夜月", "长夜月")),
            ("_aha_459", 459.59, 35331.2 * 10, 0.0, ()),
            ("_aha_559", 559.59, 35331.2 * 10, 0.0, ()),
            ("_aha_642", 642.54, 37553.3 * 4, 0.0, ("缇宝", "长夜月")),
            ("_aha_659", 659.59, 35331.2 * 3, 0.0, ("缇宝", "缇宝", "缇宝")),
        ]
        apply_aha_w2_schedule(sim, director, av, aha_w2_schedule, split_sprout_damage=False)

    sim.aha_special_handler = _aha_222204_handler

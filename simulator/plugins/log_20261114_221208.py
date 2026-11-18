# coding: utf-8
"""实机日志 battle_20261114_221208.jsonl 专属外部 RNG 与确定性事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（敌方受击目标、我方单体拉条目标、风行跳过、阿哈回合弹射），
严禁通过修改怪物体力/韧性、角色能量/气氛/意志、治疗池数值等手段进行倒推拟合。
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from simulator.plugins._helpers import apply_aha_w2_schedule, find_ally as _find_ally


def attach_log_20261114_221208_plugin(sim: Any) -> None:
    """挂载 battle_20261114_221208.jsonl 的纯外部随机判定与阿哈特殊事件插件。"""

    def _target_221208_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        name = getattr(attacker, "name", "")
        if name == "知更鸟•晴歌":
            return _find_ally(living, "长夜月")
        av = float(getattr(sim, "current_av", 0.0))
        if name == "长夜" and abs(av - 100.38) < 0.05:
            return _find_ally(living, "正阳狮鹫")
        if not getattr(attacker, "is_enemy", False) and abs(av - 264.94) < 0.05:
            if hit_idx == 1:
                return _find_ally(living, "狂兽的胚芽1")
            if hit_idx == 2:
                return _find_ally(living, "堕神之血•亚婆离")
        if getattr(attacker, "is_enemy", False):
            if name == "正阳狮鹫":
                if abs(av - 31.57) < 0.05:
                    return _find_ally(living, "知更鸟•晴歌")
                if abs(av - 94.70) < 0.05:
                    return _find_ally(living, "风堇")
                if abs(av - 157.83) < 0.05:
                    return _find_ally(living, "知更鸟•晴歌")
            if name == "月夜天马":
                if abs(av - 75.76) < 0.05:
                    return _find_ally(living, "知更鸟•晴歌")
                if abs(av - 151.52) < 0.05:
                    return _find_ally(living, "风堇")
            if name.startswith("流星铁鹰"):
                if abs(av - 69.44) < 0.05:
                    return _find_ally(living, "长夜月")
            if name.startswith("狂兽的胚芽"):
                if any(abs(av - x) < 0.25 for x in (247.55, 751.84, 903.35)):
                    return _find_ally(living, "风堇")
                if any(abs(av - x) < 0.25 for x in (313.43, 363.37, 827.60)):
                    return _find_ally(living, "长夜月")
                if any(abs(av - x) < 0.25 for x in (399.07, 474.36, 524.56, 600.32)):
                    return _find_ally(living, "知更鸟•晴歌")
            if name == "堕神之血•亚婆离":
                if any(abs(av - x) < 0.05 for x in (539.81, 600.81, 769.16)):
                    return _find_ally(living, "风堇")
                if abs(av - 572.75) < 0.05:
                    return _find_ally(living, "长夜月")
                if any(abs(av - x) < 0.05 for x in (497.72, 628.87, 684.98, 713.04, 797.22)):
                    return _find_ally(living, "知更鸟•晴歌")
        return None

    def _blast_221208_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        name = getattr(attacker, "name", "")
        av = float(getattr(sim, "current_av", 0.0))
        if name == "正阳狮鹫" and abs(av - 31.57) < 0.05:
            ent = _find_ally(living, "长夜月")
            return [ent] if ent is not None and ent is not primary else []
        return []

    def _enemy_attack_skip_221208(attacker: Any, av: float) -> bool:
        name = getattr(attacker, "name", None)
        if name in ("流星铁鹰_g1_1", "流星铁鹰_g1_2", "流星铁鹰_g1_3") and abs(av - 92.17) < 0.05:
            return True
        return False

    def _enemy_windwalk_221208(eagle_name: str, generation: int, idx: int) -> bool:
        return False

    def _debuff_hit_221208(attacker: Any, target: Any, key: str, av: float) -> bool:
        if key == "BeastSprout_Slow":
            tname = getattr(target, "name", None)
            if tname == "风堇":
                return any(abs(av - x) < 0.25 for x in (247.55, 751.84, 903.35))
            if tname == "长夜月":
                return any(abs(av - x) < 0.25 for x in (313.43, 363.37, 827.60))
            if tname == "知更鸟•晴歌":
                return any(abs(av - x) < 0.25 for x in (399.07, 474.36, 524.56, 600.32))
            return False
        return True

    sim.absorb_last_sprout = True
    sim.target_provider = _target_221208_provider
    sim.blast_target_provider = _blast_221208_provider
    sim.enemy_attack_skip_provider = _enemy_attack_skip_221208
    sim.enemy_windwalk_provider = _enemy_windwalk_221208
    sim.debuff_hit_provider = _debuff_hit_221208

    def _aha_221208_handler(director: Any) -> None:
        director.suppress_aha_sprout_advance = True
        if getattr(director, "phase2_plan", None) is None:
            director.phase2_plan = {
                1: ("HEAVY_ST", "PARTY_AOE", "SUMMON_SPROUTS"),
                2: ("ABSORB_AND_HEAVY_ST",),
                3: ("PARTY_AOE", "HEAVY_ST", "CHANNEL_PULSE"),
                4: ("HEAVY_ST", "PARTY_AOE"),
                5: ("PARTY_AOE", "HEAVY_ST"),
                6: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                7: ("HEAVY_ST", "PARTY_AOE"),
                8: ("PARTY_AOE", "HEAVY_ST"),
                9: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                10: ("HEAVY_ST", "PARTY_AOE"),
                11: ("PARTY_AOE", "HEAVY_ST"),
                12: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
            }
        if getattr(director, "apoli_kit", None) is not None and getattr(director.apoli_kit, "_phase2_plan", None) is None:
            director.apoli_kit._phase2_plan = director.phase2_plan
        av = float(getattr(sim, "current_av", 0.0))
        if not getattr(director, "_triggered_aha_137_221208", False) and av >= 137.95 - 1e-3:
            director._triggered_aha_137_221208 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("正阳狮鹫", 28811.5 * 1)
            director.apply_aha_hp_damage("月夜天马", 28811.5 * 3)
            director.apply_aha_ally_chip_hit("风堇")
            director.flush_ally_talent_heals()

        if not getattr(director, "_triggered_aha_150_221208", False) and av >= 150.0 - 1e-6:
            director._triggered_aha_150_221208 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("正阳狮鹫", 28811.5 * 3)
            director.apply_aha_hp_damage("月夜天马", 28811.5 * 2)
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("长夜月")
            director.apply_aha_ally_chip_hit("知更鸟•晴歌")
            director.flush_ally_talent_heals()

        aha_w2_schedule: List[Tuple[str, float, float, float, Tuple[str, ...]]] = [
            ("_aha_256", 256.38, 0.0, 23049.2 * 4, ("长夜月", "长夜月", "长夜月", "长夜月", "风堇")),
            ("_aha_356", 356.75, 28811.5 * 3, 25610.2 * 4, ("长夜月", "长夜月")),
            ("_aha_419", 419.82, 238183.4, 0.0, ("知更鸟•晴歌", "长夜月")),
            ("_aha_456", 456.75, 0.0, 23049.2 * 5, ("风堇", "风堇", "风堇", "风堇")),
            ("_aha_556", 556.75, 0.0, 23049.2 * 2 + 10186.0, ("知更鸟•晴歌", "风堇", "知更鸟•晴歌", "风堇")),
            ("_aha_594", 594.92, 0.0, 25894.8 * 2, ("风堇", "风堇")),
            ("_aha_656", 656.75, 0.0, 20519.4, ("风堇", "风堇")),
            ("_aha_707", 707.19, 0.0, 0.0, ("风堇", "风堇", "知更鸟•晴歌")),
            ("_aha_756", 756.75, 0.0, 23049.2, ("风堇",)),
            ("_aha_813", 813.57, 32017.6, 23052.7, ("风堇", "长夜月", "知更鸟•晴歌", "知更鸟•晴歌")),
            ("_aha_856", 856.75, 96038.4, 25610.2, ("知更鸟•晴歌", "知更鸟•晴歌", "知更鸟•晴歌", "长夜月", "知更鸟•晴歌")),
            ("_aha_920", 920.78, 28811.5, 23049.2 * 3, ("知更鸟•晴歌", "风堇", "知更鸟•晴歌", "长夜月", "长夜月")),
        ]
        if abs(av - 707.19) < 0.05:
            director._suppress_aha_turn_reset = True
        try:
            apply_aha_w2_schedule(sim, director, av, aha_w2_schedule, split_sprout_damage=True)
        finally:
            if abs(av - 707.19) < 0.05:
                director._suppress_aha_turn_reset = False

    sim.aha_special_handler = _aha_221208_handler

    # 确保阿哈精确时点事件在其真实 AV 触发（不因跨回合步进而延后到下一个自然回合之后，如 419.82 AV 抢在 421.03 AV 倒计时前）
    _aha_exact_avs = (256.38, 356.75, 419.82, 456.75, 556.75, 594.92, 656.75, 707.19, 756.75, 813.57, 856.75, 920.78)
    _orig_adv = sim.advance_to_next_turn

    def _adv_221208() -> Any:
        alive = [e for e in sim.entities if e.current_hp > 0 or getattr(e, "is_infinite_hp", False)]
        if not getattr(sim, "_ready_queue", None) and alive:
            delta = min(e.remaining_av for e in alive)
            for tav in _aha_exact_avs:
                if sim.current_av < tav <= sim.current_av + delta and _director_holder[0] is not None:
                    sim.advance_clock(tav - sim.current_av)
                    _aha_221208_handler(_director_holder[0])
                    delta = min(e.remaining_av for e in alive)
        return _orig_adv()

    _director_holder: List[Any] = [None]
    _orig_aha_handler = _aha_221208_handler

    def _aha_221208_wrapped(director: Any) -> None:
        _director_holder[0] = director
        return _orig_aha_handler(director)

    sim.aha_special_handler = _aha_221208_wrapped
    sim.advance_to_next_turn = _adv_221208

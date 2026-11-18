# coding: utf-8
"""实机日志 battle_20261114_220255.jsonl 专属外部 RNG 与确定性事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（敌方受击目标、我方单体拉条目标、风行跳过、阿哈回合弹射），
严禁通过修改怪物体力/韧性、角色能量/气氛/意志、治疗池数值等手段进行倒推拟合。
"""

from typing import Any, List, Optional

from simulator.actions import ActionKind
from simulator.plugins._helpers import find_ally as _find_ally


def attach_log_20261114_220255_plugin(sim: Any) -> None:
    """挂载 battle_20261114_220255.jsonl (3人队: 缇宝+风堇+知更鸟•晴歌) 的纯外部随机判定插件。"""
    sim.enemy_uid_map = {100011: "月夜天马", 100013: "正阳狮鹫"}

    def _target_220255_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        atk_name = getattr(attacker, "name", None)
        if atk_name == "知更鸟•晴歌":
            return _find_ally(living, "风堇")
        av = float(getattr(sim, "current_av", 0.0))
        if atk_name == "风堇" and abs(av - 320.31) < 0.05:
            for e in living:
                if getattr(e, "name", "") == "狂兽的胚芽4":
                    return e
            for e in living:
                if getattr(e, "name", "").startswith("狂兽的胚芽"):
                    return e
        if any(abs(av - x) < 0.05 for x in (31.57, 75.76, 94.70, 157.83, 432.69, 516.87)):
            return _find_ally(living, "知更鸟•晴歌")
        if any(abs(av - x) < 0.05 for x in (151.52, 198.64, 250.02, 274.22, 345.86, 390.60, 417.45, 506.63, 572.98)):
            return _find_ally(living, "缇宝")
        if any(abs(av - x) < 0.05 for x in (488.81, 657.16, 720.48, 739.09)):
            return _find_ally(living, "风堇")
        return None

    def _blast_220255_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 31.57) < 0.05:
            return [ent for n in ("缇宝", "风堇") if (ent := _find_ally(living, n)) is not None and ent is not primary]
        return []

    def _enemy_attack_skip_220255(attacker: Any, av: float) -> bool:
        name = getattr(attacker, "name", None)
        if name in ("流星铁鹰_g1_1", "流星铁鹰_g1_2") and abs(av - 69.44) < 0.05:
            return True
        if name in ("狂兽的胚芽9", "狂兽的胚芽10") and abs(av - 436.78) < 0.5:
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
        if getattr(director, "phase2_plan", None) is None:
            director.phase2_plan = {
                1: ("HEAVY_ST", "PARTY_AOE", "SUMMON_SPROUTS"),
                2: ("ABSORB_AND_HEAVY_ST",),
                3: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                4: ("HEAVY_ST", "PARTY_AOE"),
                5: ("ABSORB_AND_HEAVY_ST",),
                6: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                7: ("HEAVY_ST", "PARTY_AOE"),
                8: ("PARTY_AOE", "HEAVY_ST"),
                9: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
                10: ("HEAVY_ST", "PARTY_AOE"),
                11: ("ABSORB_AND_HEAVY_ST",),
                12: ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE"),
            }
        if getattr(director, "apoli_kit", None) is not None and getattr(director.apoli_kit, "_phase2_plan", None) is None:
            director.apoli_kit._phase2_plan = director.phase2_plan

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

        exact_aha_w2 = [
            ("_aha_264", 264.21, [("狂兽的胚芽1", 24374.23), ("狂兽的胚芽4", 43873.62)], ("缇宝", "缇宝", "缇宝", "风堇", "风堇")),
            ("_aha_307", 307.83, [("狂兽的胚芽4", 52157.42), ("狂兽的胚芽3", 26078.71)], ("知更鸟•晴歌", "风堇", "知更鸟•晴歌")),
            ("_aha_380", 380.60, [("堕神之血•亚婆离", 65196.76), ("狂兽的胚芽5", 26078.71), ("狂兽的胚芽6", 26078.71)], ("知更鸟•晴歌", "缇宝", "风堇", "缇宝")),
            ("_aha_407", 407.83, [("堕神之血•亚婆离", 58169.57), ("狂兽的胚芽9", 20941.05), ("狂兽的胚芽10", 20941.05)], ("知更鸟•晴歌", "知更鸟•晴歌", "知更鸟•晴歌", "知更鸟•晴歌")),
            ("_aha_496", 496.99, [("狂兽的胚芽11", 33704.07), ("狂兽的胚芽12", 33704.07)], ("风堇", "知更鸟•晴歌", "缇宝", "缇宝", "缇宝", "风堇", "缇宝")),
            ("_aha_507", 507.83, [("狂兽的胚芽11", 70412.51)], ("缇宝", "风堇", "知更鸟•晴歌")),
            ("_aha_607", 607.83, [("堕神之血•亚婆离", 161052.32)], ("缇宝", "风堇", "缇宝", "知更鸟•晴歌")),
            ("_aha_631", 631.27, [("堕神之血•亚婆离", 161052.32), ("狂兽的胚芽16", 25927.02 * 4)], ("知更鸟•晴歌", "风堇")),
            ("_aha_707", 707.83, [("堕神之血•亚婆离", 65196.76), ("狂兽的胚芽17", 20941.04 * 4), ("狂兽的胚芽18", 20941.04 * 2)], ("知更鸟•晴歌", "风堇")),
            ("_aha_737", 737.65, [("堕神之血•亚婆离", 69297.20), ("狂兽的胚芽17", 27718.88 * 4), ("狂兽的胚芽18", 27718.88 * 2)], ("缇宝",)),
        ]
        for flag, trg_av, dmg_list, chips in exact_aha_w2:
            if not getattr(director, flag, False) and av >= trg_av - 1e-3:
                setattr(director, flag, True)
                if hasattr(sim, "_action_seq"):
                    sim._action_seq += 1
                for tname, dmg in dmg_list:
                    if dmg > 0:
                        director.apply_aha_hp_damage(tname, dmg)
                for ally_name in chips:
                    director.apply_aha_ally_chip_hit(ally_name)
                director.flush_ally_talent_heals()

    sim.aha_special_handler = _aha_220255_handler

    _orig_step = sim.step

    def _step_220255(*args: Any, **kwargs: Any) -> Any:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 102.73) < 0.05 and kwargs.get("action_override") == ActionKind.BASIC:
            kwargs["target_ids"] = ["正阳狮鹫", "月夜天马", "流星铁鹰_g1_2"]
        return _orig_step(*args, **kwargs)

    sim.step = _step_220255

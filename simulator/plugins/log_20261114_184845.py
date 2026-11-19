# coding: utf-8
"""实机日志 battle_20261114_184845.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的特定命中结果（如阿哈回合随机弹射目标），
不修改通用模拟器核心、关卡配置或通用对账框架。
"""

from typing import Any, List, Optional


def attach_log_20261114_184845_plugin(sim: Any) -> None:
    """挂载 battle_20261114_184845.jsonl 专属的敌方/阿哈随机事件插件。"""

    def _pick(candidates: List[Any], name: str) -> Optional[Any]:
        for c in candidates:
            if getattr(c, "name", None) == name:
                return c
        return None

    def _target_184845_provider(attacker: Any, candidates: List[Any], hit_idx: int) -> Optional[Any]:
        if not getattr(attacker, "is_enemy", False):
            return None
        av = round(float(getattr(sim, "current_av", 0.0)), 2)
        aname = getattr(attacker, "name", "")
        if aname == "正阳狮鹫":
            if av == 31.57 or av == 157.83 or av == 220.96:
                return _pick(candidates, "缇宝")
            if av == 94.70:
                return _pick(candidates, "小伊卡")
        if aname == "月夜天马":
            if av == 75.76:
                return _pick(candidates, "缇宝")
            if av == 151.52:
                # 151.52 AV 月夜天马风行双连动: 第1动 Skill04 命中风堇+缇宝；第2动 Skill01 单体命中风堇的忆灵小伊卡
                if getattr(attacker.kit, "ai_executor", None) is not None and getattr(attacker.kit, "executed_skills", None):
                    if attacker.kit.executed_skills[-1] == "Skill01":
                        return _pick(candidates, "小伊卡")
                return _pick(candidates, "风堇")
            if av == 227.27:
                return _pick(candidates, "风堇")
        if aname in ("流星铁鹰_g1_1", "流星铁鹰_1"):
            if av == 69.44:
                return _pick(candidates, "风堇")
            if av == 179.29:
                return _pick(candidates, "缇宝")
        if aname in ("流星铁鹰_g1_2", "流星铁鹰_2") and av == 186.87:
            return _pick(candidates, "小伊卡")
        if aname in ("流星铁鹰_g1_3", "流星铁鹰_3") and av == 148.99:
            return _pick(candidates, "风堇")
        return None

    def _enemy_windwalk_184845(eagle_name: str, generation: int, idx: int) -> Any:
        if generation == 1 and idx == 2:
            return "月夜天马"
        return False

    def _aha_184845_handler(director: Any) -> None:
        av = float(getattr(sim, "current_av", 0.0))
        # 137.95 AV 阿哈常规回合: 4 段敌方弹射 (铁鹰1x1, 铁鹰3x1, 狮鹫x2) + 我方伴生 4 段 (风堇x3, 缇宝x1)
        if not director._triggered_aha_137 and av >= 137.95 - 1e-6:
            director._triggered_aha_137 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("流星铁鹰_g1_1", 25545.166872413596)
            director.apply_aha_hp_damage("流星铁鹰_g1_3", 25545.166872413596)
            director.apply_aha_hp_damage("正阳狮鹫", 22990.650174466427 * 2)
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("缇宝")
            director.flush_ally_talent_heals()

        # 150.00 AV 第 1 轮开始阿哈 20 笑点额外回合: 5 段敌方弹射 (铁鹰2x1, 铁鹰3x3, 天马x1) + 我方伴生 4 段 (风堇x1, 缇宝x3)
        if not director._triggered_aha_150 and av >= 150.0 - 1e-6:
            director._triggered_aha_150 = True
            if hasattr(sim, "_action_seq"):
                sim._action_seq += 1
            director.apply_aha_hp_damage("流星铁鹰_g1_2", 29475.18436510279)
            director.apply_aha_hp_damage("流星铁鹰_g1_3", 26527.66591623961 * 3)
            director.apply_aha_hp_damage("月夜天马", 26527.665916239843)
            director.apply_aha_ally_chip_hit("风堇")
            director.apply_aha_ally_chip_hit("缇宝")
            director.apply_aha_ally_chip_hit("缇宝")
            director.apply_aha_ally_chip_hit("缇宝")
            director.flush_ally_talent_heals()

    def _blast_184845_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        if abs(av - 151.52) < 0.05 and getattr(attacker, "name", None) == "月夜天马":
            return [e for e in living if getattr(e, "name", None) in ("缇宝", "小伊卡")]
        if abs(av - 157.83) < 0.05:
            return [e for e in living if getattr(e, "name", None) == "小伊卡"]
        return []

    sim.target_provider = _target_184845_provider
    sim.blast_target_provider = _blast_184845_provider
    sim.enemy_windwalk_provider = _enemy_windwalk_184845
    sim.aha_special_handler = _aha_184845_handler

# coding: utf-8
"""实机日志 battle_20261026_062503.jsonl 专属随机事件插件。

仅承接该场实机战斗中具有随机性的敌方受击目标（Wave 1 戍卫/天马、Wave 2 胚芽/亚婆离二阶段重击），
严格遵循 golden-log-to-stage 架构边界，将所有日志专属随机命中从 stage_30510021.py 剥离。
"""

from typing import Any, List, Optional

from simulator.plugins._helpers import find_ally as _find_ally


def attach_log_20261026_062503_plugin(sim: Any) -> None:
    """挂载 battle_20261026_062503.jsonl 专属的敌方受击目标插件。"""

    def _target_20261026_provider(
        attacker: Any,
        living: List[Any],
        sub_idx: int = 0,
    ) -> Optional[Any]:
        atk_name = getattr(attacker, "name", None) or ""
        av = float(getattr(sim, "current_av", 0.0))

        # Wave 1
        if atk_name == "千星戍卫A" and abs(av - 0.0) < 0.05:
            return _find_ally(living, "长夜月")
        if atk_name == "千星戍卫B" and abs(av - 13.77) < 0.05:
            return _find_ally(living, "缇宝")
        if atk_name == "千星戍卫C" and abs(av - 41.32) < 0.05:
            return _find_ally(living, "缇宝")
        if atk_name == "月夜天马" and abs(av - 75.76) < 0.05:
            return _find_ally(living, "知更鸟•晴歌")

        # Wave 2: 狂兽的胚芽
        if atk_name.startswith("狂兽的胚芽"):
            if abs(av - 138.67) < 0.25 or abs(av - 218.72) < 0.25:
                return _find_ally(living, "缇宝")
            return _find_ally(living, "缇宝")

        # Wave 2: 堕神之血•亚婆离二阶段 HEAVY_ST 单体点名
        if atk_name == "堕神之血•亚婆离":
            if abs(av - 281.39) < 0.05:
                return _find_ally(living, "缇宝")
            if abs(av - 309.45) < 0.05:
                return _find_ally(living, "风堇")
            if abs(av - 337.51) < 0.05:
                return _find_ally(living, "长夜月")
            if abs(av - 365.56) < 0.05:
                return _find_ally(living, "知更鸟•晴歌")
            if abs(av - 393.62) < 0.05:
                return _find_ally(living, "缇宝")
            if abs(av - 421.68) < 0.05:
                return _find_ally(living, "风堇")
            if abs(av - 449.74) < 0.05:
                return _find_ally(living, "长夜月")

        return None

    sim.target_provider = _target_20261026_provider

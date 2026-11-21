# coding: utf-8
"""Read-only adapter bridging StageFactory / StageRunner / StageAILoader to TurnSimulator (Facade).

具体实现已按职责拆分至：
- ``simulator/vm/enemy_kit.py``: ``DataDrivenEnemyKit``
- ``simulator/vm/stage_director.py``: ``DataDrivenStageDirector`` 与 ``build_data_driven_stage``
"""

from __future__ import annotations

from simulator.vm.enemy_kit import DataDrivenEnemyKit
from simulator.vm.stage_director import DataDrivenStageDirector, build_data_driven_stage

__all__ = [
    "DataDrivenEnemyKit",
    "DataDrivenStageDirector",
    "build_data_driven_stage",
]

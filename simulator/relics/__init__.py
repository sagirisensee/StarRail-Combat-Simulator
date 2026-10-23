"""遗器战斗系统模块 (Relics Combat Subsystem)."""
from .base import RelicSetHandler
from .models import RelicSetSpec
from .registry import RelicRegistry, register_relic_set
from . import catalog  # 触发自动注册

__all__ = [
    "RelicSetHandler",
    "RelicSetSpec",
    "RelicRegistry",
    "register_relic_set",
]

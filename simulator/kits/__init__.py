"""角色技能套件模块。"""
from .base import KitHandler
from .registry import register_kit, get_kit_class, auto_discover_kits, GenericKit
from .characters.sparkle import SparkleKit

__all__ = [
    "KitHandler",
    "register_kit",
    "get_kit_class",
    "auto_discover_kits",
    "GenericKit",
    "SparkleKit",
]

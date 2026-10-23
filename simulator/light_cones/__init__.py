"""星穹铁道独立光锥模块 (Light Cones Module)."""
from .models import LightConeEquipment, LightConeSpec
from .base import LightConeHandler
from .registry import LightConeRegistry, register_light_cone
from . import catalog  # 触发内置光锥显式注册

__all__ = [
    "LightConeEquipment",
    "LightConeSpec",
    "LightConeHandler",
    "LightConeRegistry",
    "register_light_cone",
]

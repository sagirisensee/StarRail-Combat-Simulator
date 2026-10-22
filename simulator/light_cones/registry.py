"""光锥注册中心 (Light Cone Registry)."""
from typing import Dict, Optional, Type, List, Tuple
from .models import LightConeSpec
from .base import LightConeHandler
from ..combat_port import CombatPort


class LightConeRegistry:
    """光锥规范与处理器类型注册中心。"""

    _specs_by_id: Dict[str, LightConeSpec] = {}
    _handlers_by_id: Dict[str, Type[LightConeHandler]] = {}
    _alias_to_id: Dict[str, str] = {}

    @classmethod
    def register(cls, spec: LightConeSpec, handler_cls: Type[LightConeHandler]) -> None:
        """显式注册光锥。"""
        cls._specs_by_id[spec.cone_id] = spec
        cls._handlers_by_id[spec.cone_id] = handler_cls
        cls._alias_to_id[spec.cone_id.lower()] = spec.cone_id
        cls._alias_to_id[spec.name.lower()] = spec.cone_id
        for alias in spec.aliases:
            cls._alias_to_id[alias.lower()] = spec.cone_id

    @classmethod
    def resolve_id(cls, cone_id_or_name: str) -> Optional[str]:
        """按 ID、名称或别名解析标准 cone_id。"""
        key = cone_id_or_name.strip().lower()
        return cls._alias_to_id.get(key)

    @classmethod
    def get(cls, cone_id_or_name: str) -> Optional[Tuple[LightConeSpec, Type[LightConeHandler]]]:
        """获取光锥规格与处理器类。"""
        resolved_id = cls.resolve_id(cone_id_or_name)
        if not resolved_id:
            return None
        spec = cls._specs_by_id.get(resolved_id)
        handler_cls = cls._handlers_by_id.get(resolved_id)
        if spec and handler_cls:
            return spec, handler_cls
        return None

    @classmethod
    def create(
        cls,
        cone_id_or_name: str,
        owner_id: str,
        port: Optional[CombatPort] = None,
        superimposition: int = 1
    ) -> Optional[LightConeHandler]:
        """实例化并返回指定光锥的独立处理器。"""
        entry = cls.get(cone_id_or_name)
        if not entry:
            return None
        spec, handler_cls = entry
        handler = handler_cls(
            owner_id=owner_id,
            port=port,
            superimposition=superimposition,
            spec=spec
        )
        handler.on_attach()
        return handler

    @classmethod
    def list_all(cls) -> List[LightConeSpec]:
        """列出所有已注册的光锥规格。"""
        return list(cls._specs_by_id.values())

"""遗器注册中心 (Relic Registry)."""
from typing import Dict, Type, Optional, Tuple, Any
from .base import RelicSetHandler
from .models import RelicSetSpec


class RelicRegistry:
    """全局遗器套装注册表。"""

    _registry_by_id: Dict[int, Tuple[RelicSetSpec, Type[RelicSetHandler]]] = {}
    _registry_by_name: Dict[str, Tuple[RelicSetSpec, Type[RelicSetHandler]]] = {}

    @classmethod
    def register(cls, spec: RelicSetSpec, handler_cls: Type[RelicSetHandler]) -> None:
        cls._registry_by_id[spec.set_id] = (spec, handler_cls)
        cls._registry_by_name[spec.name.lower()] = (spec, handler_cls)
        cls._registry_by_name[str(spec.set_id)] = (spec, handler_cls)
        for alias in spec.aliases:
            cls._registry_by_name[alias.lower()] = (spec, handler_cls)

    @classmethod
    def get(cls, key: Any) -> Optional[Tuple[RelicSetSpec, Type[RelicSetHandler]]]:
        if isinstance(key, int):
            return cls._registry_by_id.get(key)
        key_str = str(key).strip().lower()
        if key_str.isdigit():
            return cls._registry_by_id.get(int(key_str))
        return cls._registry_by_name.get(key_str)

    @classmethod
    def create(
        cls,
        key: Any,
        owner_id: str,
        port: Optional[Any] = None,
        pieces: int = 4
    ) -> Optional[RelicSetHandler]:
        entry = cls.get(key)
        if not entry:
            return None
        spec, handler_cls = entry
        return handler_cls(owner_id=owner_id, port=port, pieces=pieces, spec=spec)

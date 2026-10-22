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
        if entry:
            spec, handler_cls = entry
            return handler_cls(owner_id=owner_id, port=port, pieces=pieces, spec=spec)

        # 优雅回退：全量 62 套官方资产通用运行时
        try:
            from ..assets import AssetRepository
            from .generic import GenericRelicSetHandler
            repo = AssetRepository.get_instance()
            asset = repo.get_relic_set(key)
            if asset:
                set_id_int = int(asset.id) if asset.id.isdigit() else 0
                spec = RelicSetSpec(
                    set_id=set_id_int,
                    name=asset.name,
                    set_type="cavern" if set_id_int < 300 else "planar"
                )
                return GenericRelicSetHandler(
                    owner_id=owner_id,
                    port=port,
                    pieces=pieces,
                    spec=spec,
                    asset=asset
                )
        except Exception:
            pass

        return None

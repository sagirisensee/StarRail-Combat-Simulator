"""遗器注册中心 (Relic Registry).

支持两种注册方式：
1. 装饰器自注册（推荐新人开发使用）：在 `simulator/relics/handlers/<name>.py` 中使用 `@register_relic_set(...)`，无需修改中心目录文件；
2. 显式调用：`RelicRegistry.register(spec, handler_cls)`。
"""
import importlib
import pkgutil
from pathlib import Path
from typing import Dict, Type, Optional, Tuple, Any, Sequence, Callable
from .base import RelicSetHandler
from .models import RelicSetSpec


class RelicRegistry:
    """全局遗器套装注册表。"""

    _registry_by_id: Dict[int, Tuple[RelicSetSpec, Type[RelicSetHandler]]] = {}
    _registry_by_name: Dict[str, Tuple[RelicSetSpec, Type[RelicSetHandler]]] = {}
    _discovered: bool = False

    @classmethod
    def register(cls, spec: RelicSetSpec, handler_cls: Type[RelicSetHandler]) -> None:
        cls._registry_by_id[spec.set_id] = (spec, handler_cls)
        cls._registry_by_name[spec.name.lower()] = (spec, handler_cls)
        cls._registry_by_name[str(spec.set_id)] = (spec, handler_cls)
        for alias in spec.aliases:
            cls._registry_by_name[alias.lower()] = (spec, handler_cls)

    @classmethod
    def auto_discover(cls) -> None:
        """自动扫描并加载 handlers 目录下的所有遗器套装插件模块（忽略以 _ 开头的模版文件）。"""
        if cls._discovered:
            return
        cls._discovered = True
        handlers_dir = Path(__file__).resolve().parent / "handlers"
        if not handlers_dir.exists():
            return
        pkg_prefix = f"{__package__}.handlers."
        for mod_info in pkgutil.iter_modules([str(handlers_dir)]):
            if not mod_info.name.startswith("_"):
                importlib.import_module(pkg_prefix + mod_info.name)

    @classmethod
    def get(cls, key: Any) -> Optional[Tuple[RelicSetSpec, Type[RelicSetHandler]]]:
        cls.auto_discover()
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


def register_relic_set(
    set_id: int,
    name: str,
    set_type: str = "cavern",
    aliases: Sequence[str] = ()
) -> Callable[[Type[RelicSetHandler]], Type[RelicSetHandler]]:
    """遗器套装处理器类装饰器：声明式完成 RelicSetSpec 构建与自动注册。"""
    def _decorator(handler_cls: Type[RelicSetHandler]) -> Type[RelicSetHandler]:
        spec = RelicSetSpec(
            set_id=int(set_id),
            name=name,
            set_type=set_type,
            aliases=tuple(aliases)
        )
        RelicRegistry.register(spec, handler_cls)
        return handler_cls
    return _decorator

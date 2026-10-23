"""光锥注册中心 (Light Cone Registry).

支持两种注册方式：
1. 装饰器自注册（推荐新人开发使用）：在 `simulator/light_cones/handlers/<name>.py` 中使用 `@register_light_cone(...)`，无需修改中心目录文件；
2. 显式调用：`LightConeRegistry.register(spec, handler_cls)`。
"""
import importlib
import pkgutil
from pathlib import Path
from typing import Dict, Optional, Type, List, Tuple, Sequence, Callable
from .models import LightConeSpec
from .base import LightConeHandler
from ..combat_port import CombatPort


class LightConeRegistry:
    """光锥规范与处理器类型注册中心。"""

    _specs_by_id: Dict[str, LightConeSpec] = {}
    _handlers_by_id: Dict[str, Type[LightConeHandler]] = {}
    _alias_to_id: Dict[str, str] = {}
    _discovered: bool = False

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
    def auto_discover(cls) -> None:
        """自动扫描并加载 handlers 目录下的所有光锥插件模块（忽略以 _ 开头的模版文件）。"""
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
    def resolve_id(cls, cone_id_or_name: str) -> Optional[str]:
        """按 ID、名称或别名解析标准 cone_id。"""
        cls.auto_discover()
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
        if entry:
            spec, handler_cls = entry
            handler = handler_cls(
                owner_id=owner_id,
                port=port,
                superimposition=superimposition,
                spec=spec
            )
            handler.on_attach()
            return handler

        # 优雅回退：全量 170 顶官方光锥通用运行时
        try:
            from ..assets import AssetRepository
            from .generic import GenericLightConeHandler
            repo = AssetRepository.get_instance()
            asset = repo.get_light_cone(cone_id_or_name)
            if asset:
                spec = LightConeSpec(
                    cone_id=asset.id,
                    name=asset.name,
                    path=asset.path,
                    rarity=asset.rarity,
                )
                handler = GenericLightConeHandler(
                    owner_id=owner_id,
                    port=port,
                    superimposition=superimposition,
                    spec=spec,
                    asset=asset
                )
                handler.on_attach()
                return handler
        except Exception:
            pass

        return None

    @classmethod
    def list_all(cls) -> List[LightConeSpec]:
        """列出所有已注册的光锥规格。"""
        cls.auto_discover()
        return list(cls._specs_by_id.values())


def register_light_cone(
    cone_id: str,
    name: str,
    path: str = "",
    rarity: int = 5,
    aliases: Sequence[str] = ()
) -> Callable[[Type[LightConeHandler]], Type[LightConeHandler]]:
    """光锥处理器类装饰器：声明式完成 LightConeSpec 构建与自动注册。"""
    def _decorator(handler_cls: Type[LightConeHandler]) -> Type[LightConeHandler]:
        spec = LightConeSpec(
            cone_id=str(cone_id),
            name=name,
            path=path,
            rarity=rarity,
            aliases=tuple(aliases)
        )
        LightConeRegistry.register(spec, handler_cls)
        return handler_cls
    return _decorator

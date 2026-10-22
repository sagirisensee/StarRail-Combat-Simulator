"""光锥数据模型 (Light Cone Models)."""
from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class LightConeEquipment:
    """光锥装备配置信息。"""
    cone_id: str
    name: str
    superimposition: int = 1
    level: int = 80

    def __post_init__(self) -> None:
        if not isinstance(self.superimposition, int) or not 1 <= self.superimposition <= 5:
            raise ValueError(f"光锥叠影阶数必须是 1~5 之间的整数，当前为: {self.superimposition}")


@dataclass(frozen=True)
class LightConeSpec:
    """光锥规格与注册元数据。"""
    cone_id: str
    name: str
    path: str
    aliases: Tuple[str, ...] = field(default_factory=tuple)

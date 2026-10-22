"""遗器元数据与配置定义 (Relic Spec & Models)."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class RelicSetSpec:
    """遗器套装静态规格描述。"""
    set_id: int                         # 官方套装 ID (如 124, 125)
    name: str                           # 官方标准套装中文名
    set_type: str = "cavern"            # "cavern" (外圈4件套) 或 "planar" (内圈2件套)
    aliases: Tuple[str, ...] = ()       # 别名/历史译名

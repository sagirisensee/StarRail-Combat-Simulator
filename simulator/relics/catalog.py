"""遗器套装编目与注册入口 (Relic Catalog)."""
from .models import RelicSetSpec
from .registry import RelicRegistry
from .handlers.valkyrie_of_sun_and_thunder import ValkyrieOfSunAndThunderHandler
from .handlers.poet_of_mourning import PoetOfMourningHandler


def register_all_relics() -> None:
    """批量向 RelicRegistry 注册已支持的遗器套装。"""
    # 1. 烈阳惊雷的女武神 (ID 125)
    RelicRegistry.register(
        RelicSetSpec(
            set_id=125,
            name="烈阳惊雷的女武神",
            set_type="cavern",
            aliases=("valkyrie_of_sun_and_thunder", "女武神")
        ),
        ValkyrieOfSunAndThunderHandler
    )

    # 2. 哀歌覆国的诗人 / 沉醉于狂欢的诗人 (ID 124)
    RelicRegistry.register(
        RelicSetSpec(
            set_id=124,
            name="哀歌覆国的诗人",
            set_type="cavern",
            aliases=("沉醉于狂欢的诗人", "poet_of_mourning", "诗人")
        ),
        PoetOfMourningHandler
    )


# 模块加载时自动执行注册
register_all_relics()

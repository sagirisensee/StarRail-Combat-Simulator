"""遗器套装编目与注册入口 (Relic Catalog)."""
from .models import RelicSetSpec
from .registry import RelicRegistry
from .handlers.valkyrie_of_sun_and_thunder import ValkyrieOfSunAndThunderHandler
from .handlers.poet_of_mourning import PoetOfMourningHandler
from .handlers.bone_collecting_ground import BoneCollectingGroundHandler
from .handlers.sunken_tree import SunkenTreeHandler
from .handlers.eternal_land_of_amphoreus import EternalLandOfAmphoreusHandler
from .handlers.creator_of_new_world import CreatorOfNewWorldHandler


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

    # 3. 谧宁拾骨地 (ID 319, 位面饰品)
    RelicRegistry.register(
        RelicSetSpec(
            set_id=319,
            name="谧宁拾骨地",
            set_type="planar",
            aliases=("bone_collecting_ground", "拾骨地", "谧宁拾骨地")
        ),
        BoneCollectingGroundHandler
    )

    # 4. 渊思寂虑的巨树 (ID 320, 位面饰品)
    RelicRegistry.register(
        RelicSetSpec(
            set_id=320,
            name="渊思寂虑的巨树",
            set_type="planar",
            aliases=("sunken_tree", "巨树", "渊思寂虑的巨树")
        ),
        SunkenTreeHandler
    )

    # 5. 永恒之地翁法罗斯 (ID 323, 位面饰品)
    RelicRegistry.register(
        RelicSetSpec(
            set_id=323,
            name="永恒之地翁法罗斯",
            set_type="planar",
            aliases=("amphoreus", "翁法罗斯", "永恒之地翁法罗斯")
        ),
        EternalLandOfAmphoreusHandler
    )

    # 6. 再创天地的救世主 (ID 127)
    RelicRegistry.register(
        RelicSetSpec(
            set_id=127,
            name="再创天地的救世主",
            set_type="cavern",
            aliases=("creator_of_new_world", "救世主", "再创天地的救世主")
        ),
        CreatorOfNewWorldHandler
    )


# 模块加载时自动执行注册
register_all_relics()

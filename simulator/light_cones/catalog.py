"""光锥目录与显式注册登记 (Light Cone Catalog & Registration)."""
from .models import LightConeSpec
from .registry import LightConeRegistry
from .handlers.if_time_were_a_flower import IfTimeWereAFlowerHandler
from .handlers.make_farewells_more_beautiful import MakeFarewellsMoreBeautifulHandler
from .handlers.memory_never_fades import MemoryNeverFadesHandler
from .handlers.may_rainbows_remain_in_the_sky import MayRainbowsRemainInTheSkyHandler


def register_all_light_cones() -> None:
    """显式注册系统内置的所有光锥处理器。"""

    # 1. 如果时间是一朵花 (缇宝专属, 同谐)
    LightConeRegistry.register(
        LightConeSpec(
            cone_id="23038",
            name="如果时间是一朵花",
            path="Harmony",
            aliases=("时间是一朵花", "tribbie_lc", "23038")
        ),
        IfTimeWereAFlowerHandler
    )

    # 2. 让告别，更美一些 (长夜月专属, 记忆)
    LightConeRegistry.register(
        LightConeSpec(
            cone_id="23040",
            name="让告别，更美一些",
            path="Remembrance",
            aliases=("让告别更美一些", "changyeyue_lc", "23040")
        ),
        MakeFarewellsMoreBeautifulHandler
    )

    # 3. 记忆永不落幕 (黑塔商店兑换, 记忆)
    LightConeRegistry.register(
        LightConeSpec(
            cone_id="24005",
            name="记忆永不落幕",
            path="Remembrance",
            aliases=("记忆不落幕", "24005")
        ),
        MemoryNeverFadesHandler
    )

    # 4. 愿虹光永驻天空 (风堇专属, 记忆)
    LightConeRegistry.register(
        LightConeSpec(
            cone_id="23042",
            name="愿虹光永驻天空",
            path="Remembrance",
            aliases=("虹光永驻天空", "fengjin_lc", "23042")
        ),
        MayRainbowsRemainInTheSkyHandler
    )


# 模块导入时自动执行显式注册
register_all_light_cones()

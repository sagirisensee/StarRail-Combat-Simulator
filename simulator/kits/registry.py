"""角色技能套件注册中心 (Kit Registry)."""
from typing import Dict, Type, Optional, Any
from .base import KitHandler
from .characters.sparkle import SparkleKit
from .characters.robin import RobinKit
from .characters.ruan_mei import RuanMeiKit
from .characters.bronya import BronyaKit
from .characters.tingyun import TingyunKit
from .characters.firefly import FireflyKit
from .characters.pela import PelaKit
from .characters.gallagher import GallagherKit
from .characters.elation import ElationKit

# 生存位 (Preservation & Abundance)
from .characters.fuxuan import FuXuanKit
from .characters.aventurine import AventurineKit
from .characters.huohuo import HuohuoKit
from .characters.lingsha import LingshaKit
from .characters.luocha import LuochaKit
from .characters.gepard import GepardKit
from .characters.bailu import BailuKit
from .characters.lynx import LynxKit
from .characters.natasha import NatashaKit


# 角色 ID / 规范角色名 -> KitHandler 类
_KIT_REGISTRY: Dict[str, Type[KitHandler]] = {
    # 花火 (Sparkle)
    "1306": SparkleKit,
    "花火": SparkleKit,
    "sparkle": SparkleKit,

    # 知更鸟 (Robin)
    "1309": RobinKit,
    "1512": RobinKit,
    "知更鸟": RobinKit,
    "知更鸟•晴歌": RobinKit,
    "robin": RobinKit,

    # 阮•梅 (Ruan Mei)
    "1303": RuanMeiKit,
    "阮•梅": RuanMeiKit,
    "阮梅": RuanMeiKit,
    "ruan mei": RuanMeiKit,
    "ruanmei": RuanMeiKit,

    # 布洛妮娅 (Bronya)
    "1101": BronyaKit,
    "布洛妮娅": BronyaKit,
    "bronya": BronyaKit,

    # 停云 (Tingyun)
    "1202": TingyunKit,
    "停云": TingyunKit,
    "tingyun": TingyunKit,

    # 流萤 (Firefly / SAM)
    "1310": FireflyKit,
    "流萤": FireflyKit,
    "firefly": FireflyKit,
    "sam": FireflyKit,

    # 佩拉 (Pela)
    "1106": PelaKit,
    "佩拉": PelaKit,
    "pela": PelaKit,

    # 加拉赫 (Gallagher)
    "1301": GallagherKit,
    "加拉赫": GallagherKit,
    "gallagher": GallagherKit,

    # 符玄 (Fu Xuan)
    "1208": FuXuanKit,
    "符玄": FuXuanKit,
    "fuxuan": FuXuanKit,

    # 砂金 (Aventurine)
    "1304": AventurineKit,
    "砂金": AventurineKit,
    "aventurine": AventurineKit,

    # 藿藿 (Huohuo)
    "1217": HuohuoKit,
    "藿藿": HuohuoKit,
    "huohuo": HuohuoKit,

    # 灵砂 (Lingsha)
    "1222": LingshaKit,
    "灵砂": LingshaKit,
    "lingsha": LingshaKit,

    # 罗刹 (Luocha)
    "1203": LuochaKit,
    "罗刹": LuochaKit,
    "luocha": LuochaKit,

    # 杰帕德 (Gepard)
    "1104": GepardKit,
    "杰帕德": GepardKit,
    "gepard": GepardKit,

    # 白露 (Bailu)
    "1211": BailuKit,
    "白露": BailuKit,
    "bailu": BailuKit,

    # 玲可 (Lynx)
    "1110": LynxKit,
    "玲可": LynxKit,
    "lynx": LynxKit,

    # 娜塔莎 (Natasha)
    "1105": NatashaKit,
    "娜塔莎": NatashaKit,
    "natasha": NatashaKit,

    # 欢愉阿哈四人组 (Elation Quartet)
    "1503": ElationKit,
    "真珠": ElationKit,
    "pearl": ElationKit,
    "1502": ElationKit,
    "爻光": ElationKit,
    "yaoguang": ElationKit,
    "1501": ElationKit,
    "火花": ElationKit,
    "sparkle_aha": ElationKit,
    "1506": ElationKit,
    "银狼lv.999": ElationKit,
    "银狼999": ElationKit,
    "silverwolf_999": ElationKit,
}


def register_kit(name_or_id: str, kit_cls: Type[KitHandler]):
    """动态注册角色的 Kit 类。"""
    _KIT_REGISTRY[str(name_or_id).lower()] = kit_cls


def get_kit_class(name_or_id: str) -> Optional[Type[KitHandler]]:
    """查找指定角色的 KitHandler 类。"""
    key = str(name_or_id).lower()
    return _KIT_REGISTRY.get(key)


class GenericKit(KitHandler):
    """通用保底 Kit (用于尚未编写专属机制的角色)。"""

    def definition(self, kind: Any):
        from ..actions import ActionKind, AbilityDefinition, TargetMode, ResourceCost
        if kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1), name="战技")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(energy=120.0), name="终结技")
        return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="普攻")

    def execute(self, ctx: Any):
        target = ctx.target_ids[0] if ctx.target_ids else (self.port.enemies(self.owner_id)[0] if self.port.enemies(self.owner_id) else self.owner_id)
        if ctx.kind.name == "SKILL":
            self.port.attack(self.owner_id, target, element="Physical", atk_multiplier=2.0, toughness_damage=20.0, damage_tag="Skill")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind.name == "ULTIMATE":
            self.port.attack(self.owner_id, target, element="Physical", atk_multiplier=3.0, toughness_damage=30.0, damage_tag="Ultimate")
            self.port.gain_energy(self.owner_id, 5.0)
        else:
            self.port.attack(self.owner_id, target, element="Physical", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="Basic")
            self.port.gain_energy(self.owner_id, 20.0)

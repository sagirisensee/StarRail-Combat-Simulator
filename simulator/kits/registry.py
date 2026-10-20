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

# 砺烁新辉官方加强重做英雄 (Resplendent Radiance Reworked Characters)
from .characters.silver_wolf import SilverWolfKit
from .characters.kafka import KafkaKit
from .characters.seele import SeeleKit
from .characters.blade import BladeKit
from .characters.welt import WeltKit
from .characters.black_swan import BlackSwanKit
from .characters.jingliu import JingliuKit

# 核心主力输出与追击体系 (Carry Archetypes)
from .characters.clara import ClaraKit
from .characters.yunli import YunliKit
from .characters.ratio import RatioKit
from .characters.topaz import TopazKit
from .characters.acheron import AcheronKit
from .characters.herta import HertaKit
from .characters.himeko import HimekoKit
from .characters.qingque import QingqueKit

# 击破与同谐辅助扩展体系 (Break & Harmony / Nihility Archetypes)
from .characters.trailblazer_harmony import TrailblazerHarmonyKit
from .characters.fugue import FugueKit
from .characters.sunday import SundayKit
from .characters.march7th_hunt import March7thHuntKit
from .characters.moze import MozeKit
from .characters.xueyi import XueyiKit
from .characters.guinaifen import GuinaifenKit
from .characters.sampo import SampoKit
from .characters.luka import LukaKit
from .characters.asta import AstaKit
from .characters.hanya import HanyaKit
from .characters.yukong import YukongKit
from .characters.serval import ServalKit

# 巡猎、毁灭与联动全量角色扩展 (Full Roster Expansion & Collab)
from .characters.yanqing import YanqingKit
from .characters.sushang import SushangKit
from .characters.danheng import DanHengKit
from .characters.hook import HookKit
from .characters.arlan import ArlanKit
from .characters.misha import MishaKit
from .characters.collab_and_future import (
    TohsakaRinKit, ArcherKit, XilianKit, DanHengTenghuangKit,
    ChangyeyueKit, KelydraKit, FengjinKit, XiadieKit, TibaoKit, DahliaKit
)


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

    # 银狼 (Silver Wolf - 3.4 砺烁新辉加强版)
    "1006": SilverWolfKit,
    "银狼": SilverWolfKit,
    "silver wolf": SilverWolfKit,
    "silverwolf": SilverWolfKit,

    # 卡芙卡 (Kafka - 3.4 砺烁新辉加强版)
    "1005": KafkaKit,
    "卡芙卡": KafkaKit,
    "kafka": KafkaKit,

    # 希儿 (Seele - 4.2 砺烁新辉加强版)
    "1102": SeeleKit,
    "希儿": SeeleKit,
    "seele": SeeleKit,

    # 刃 (Blade - 3.4 砺烁新辉加强版)
    "1205": BladeKit,
    "刃": BladeKit,
    "blade": BladeKit,

    # 瓦尔特 (Welt - 4.2 砺烁新辉加强版)
    "1004": WeltKit,
    "瓦尔特": WeltKit,
    "welt": WeltKit,

    # 黑天鹅 (Black Swan - 4.0 砺烁新辉加强版)
    "1307": BlackSwanKit,
    "黑天鹅": BlackSwanKit,
    "black swan": BlackSwanKit,
    "blackswan": BlackSwanKit,

    # 镜流 (Jingliu - 3.4 砺烁新辉加强版)
    "1212": JingliuKit,
    "镜流": JingliuKit,
    "jingliu": JingliuKit,

    # 克拉拉 (Clara)
    "1107": ClaraKit,
    "克拉拉": ClaraKit,
    "clara": ClaraKit,

    # 云璃 (Yunli)
    "1221": YunliKit,
    "云璃": YunliKit,
    "yunli": YunliKit,

    # 真理医生 (Dr. Ratio)
    "1305": RatioKit,
    "真理医生": RatioKit,
    "ratio": RatioKit,
    "dr. ratio": RatioKit,

    # 托帕&账账 (Topaz & Numby)
    "1112": TopazKit,
    "托帕": TopazKit,
    "托帕&账账": TopazKit,
    "topaz": TopazKit,

    # 黄泉 (Acheron)
    "1308": AcheronKit,
    "黄泉": AcheronKit,
    "acheron": AcheronKit,

    # 黑塔 (Herta)
    "1013": HertaKit,
    "黑塔": HertaKit,
    "herta": HertaKit,

    # 姬子 (Himeko)
    "1003": HimekoKit,
    "姬子": HimekoKit,
    "himeko": HimekoKit,

    # 青雀 (Qingque)
    "1201": QingqueKit,
    "青雀": QingqueKit,
    "qingque": QingqueKit,

    # 开拓者•同谐 (Harmony Trailblazer)
    "8006": TrailblazerHarmonyKit,
    "开拓者": TrailblazerHarmonyKit,
    "trailblazer": TrailblazerHarmonyKit,

    # 忘归人 (Tingyun • Fugue)
    "1225": FugueKit,
    "忘归人": FugueKit,
    "fugue": FugueKit,

    # 星期日 (Sunday)
    "1313": SundayKit,
    "星期日": SundayKit,
    "sunday": SundayKit,

    # 三月七•巡猎 (March 7th • The Hunt)
    "1224": March7thHuntKit,
    "三月七": March7thHuntKit,
    "三月七•巡猎": March7thHuntKit,
    "march 7th": March7thHuntKit,
    "march7th": March7thHuntKit,

    # 貊泽 (Moze)
    "1223": MozeKit,
    "貊泽": MozeKit,
    "moze": MozeKit,

    # 雪衣 (Xueyi)
    "1214": XueyiKit,
    "雪衣": XueyiKit,
    "xueyi": XueyiKit,

    # 桂乃芬 (Guinaifen)
    "1210": GuinaifenKit,
    "桂乃芬": GuinaifenKit,
    "guinaifen": GuinaifenKit,

    # 桑博 (Sampo)
    "1108": SampoKit,
    "桑博": SampoKit,
    "sampo": SampoKit,

    # 卢卡 (Luka)
    "1111": LukaKit,
    "卢卡": LukaKit,
    "luka": LukaKit,

    # 艾丝妲 (Asta)
    "1009": AstaKit,
    "艾丝妲": AstaKit,
    "asta": AstaKit,

    # 寒鸦 (Hanya)
    "1215": HanyaKit,
    "寒鸦": HanyaKit,
    "hanya": HanyaKit,

    # 驭空 (Yukong)
    "1207": YukongKit,
    "驭空": YukongKit,
    "yukong": YukongKit,

    # 希露瓦 (Serval)
    "1103": ServalKit,
    "希露瓦": ServalKit,
    "serval": ServalKit,

    # 彦卿 (Yanqing)
    "1209": YanqingKit,
    "彦卿": YanqingKit,
    "yanqing": YanqingKit,

    # 素裳 (Sushang)
    "1206": SushangKit,
    "素裳": SushangKit,
    "sushang": SushangKit,

    # 丹恒 (Dan Heng)
    "1002": DanHengKit,
    "丹恒": DanHengKit,
    "dan heng": DanHengKit,
    "danheng": DanHengKit,

    # 虎克 (Hook)
    "1109": HookKit,
    "虎克": HookKit,
    "hook": HookKit,

    # 阿兰 (Arlan)
    "1008": ArlanKit,
    "阿兰": ArlanKit,
    "arlan": ArlanKit,

    # 米沙 (Misha)
    "1312": MishaKit,
    "米沙": MishaKit,
    "misha": MishaKit,

    # 远坂凛 (Tohsaka Rin)
    "1508": TohsakaRinKit,
    "远坂凛": TohsakaRinKit,
    "tohsaka rin": TohsakaRinKit,
    "rin": TohsakaRinKit,

    # Archer
    "1015": ArcherKit,
    "archer": ArcherKit,

    # 昔涟
    "1415": XilianKit,
    "昔涟": XilianKit,

    # 丹恒•腾荒
    "1414": DanHengTenghuangKit,
    "丹恒•腾荒": DanHengTenghuangKit,
    "丹恒腾荒": DanHengTenghuangKit,

    # 长夜月
    "1413": ChangyeyueKit,
    "长夜月": ChangyeyueKit,

    # 刻律德菈
    "1412": KelydraKit,
    "刻律德菈": KelydraKit,

    # 风堇
    "1409": FengjinKit,
    "风堇": FengjinKit,

    # 遐蝶
    "1407": XiadieKit,
    "遐蝶": XiadieKit,

    # 缇宝 (Tribbie)
    "1403": TibaoKit,
    "缇宝": TibaoKit,
    "tribbie": TibaoKit,

    # 大丽花 (Dahlia)
    "1321": DahliaKit,
    "大丽花": DahliaKit,
    "dahlia": DahliaKit,

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

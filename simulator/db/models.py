"""全角色属性数据库（Character Stats DB）数据模型定义。

遵循架构师分层规范：
1. 属性类型枚举与多层数值拆解结构体；
2. 遗器部件与词条模型；
3. 光锥装配模型；
4. 综合面板结果（包含白值、绿字、百分比与来源拆解）；
5. 角色档案完整模型（支持快速转换为战斗实体）。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class StatType(str, Enum):
    HP = "hp"
    ATK = "atk"
    DEF = "def"
    SPD = "spd"
    CRIT_RATE = "crit_rate"
    CRIT_DMG = "crit_dmg"
    BREAK_EFFECT = "break_effect"
    ERR = "err"                          # 能量恢复效率 (Energy Regeneration Rate)
    EHR = "ehr"                          # 效果命中 (Effect Hit Rate)
    RES = "res"                          # 效果抵抗 (Effect RES)
    DMG_BOOST = "dmg_boost"              # 属性增伤总和


class Element(str, Enum):
    PHYSICAL = "Physical"
    FIRE = "Fire"
    ICE = "Ice"
    THUNDER = "Thunder"
    WIND = "Wind"
    QUANTUM = "Quantum"
    IMAGINARY = "Imaginary"

    @classmethod
    def from_str(cls, val: str) -> "Element":
        for member in cls:
            if member.value.lower() == str(val).lower():
                return member
        return cls.PHYSICAL


class Path(str, Enum):
    DESTRUCTION = "Warrior"      # 毁灭
    HUNT = "Rogue"              # 巡猎
    ERUDITION = "Mage"          # 智识
    HARMONY = "Shaman"          # 同谐
    NIHILITY = "Warlock"        # 虚无
    PRESERVATION = "Knight"     # 存护
    ABUNDANCE = "Priest"        # 丰饶
    REMEMBRANCE = "Remembrance" # 记忆
    MEMORY = "Memory"           # 记忆 (别名)
    ELATION = "Elation"         # 欢愉

    @classmethod
    def from_str(cls, val: str) -> "Path":
        mapping = {
            "warrior": cls.DESTRUCTION, "destruction": cls.DESTRUCTION,
            "rogue": cls.HUNT, "hunt": cls.HUNT,
            "mage": cls.ERUDITION, "erudition": cls.ERUDITION,
            "shaman": cls.HARMONY, "harmony": cls.HARMONY,
            "warlock": cls.NIHILITY, "nihility": cls.NIHILITY,
            "knight": cls.PRESERVATION, "preservation": cls.PRESERVATION,
            "priest": cls.ABUNDANCE, "abundance": cls.ABUNDANCE,
            "memory": cls.REMEMBRANCE, "remembrance": cls.REMEMBRANCE,
            "elation": cls.ELATION
        }
        return mapping.get(str(val).lower(), cls.DESTRUCTION)


@dataclass(frozen=True)
class StatBreakdown:
    """单个属性的完整分层计算账单。"""
    base_white: float            # 基础白值 (角色白值 + 光锥白值)
    flat_bonus: float            # 固定值加成 (遗器固定词条等)
    percent_bonus: float         # 百分比加成总和 (遗器百分比 + 行迹 + 套装)
    final_value: float           # 最终计算值: base_white * (1 + percent_bonus) + flat_bonus

    def to_dict(self) -> dict:
        return {
            "base_white": round(self.base_white, 2),
            "flat_bonus": round(self.flat_bonus, 2),
            "percent_bonus": f"{self.percent_bonus * 100:.2f}%",
            "final_value": round(self.final_value, 2),
        }


@dataclass
class CharacterPanel:
    """角色的全套最终面板属性。"""
    hp: float
    atk: float
    def_stat: float
    spd: float
    crit_rate: float
    crit_dmg: float
    break_effect: float
    err: float
    ehr: float
    res: float
    dmg_boost: float
    # 乘区与来源追溯
    breakdowns: Dict[str, StatBreakdown] = field(default_factory=dict)

    def summary_dict(self) -> dict:
        import math
        def floor_pct(val: float) -> str:
            # 官方百分比截断至一位小数 (例如 10.368% 截断显示 10.3%)
            return f"{math.floor(round(val * 10000, 4) / 10) / 10:.1f}%"

        b_spd = self.breakdowns["spd"].base_white if "spd" in self.breakdowns else self.spd
        
        # 官方面板速度展示规则（严格向下取整）：
        # 面板最终总速度 = floor(实际总速度)
        # 面板白字 = floor(基础白值)
        # 面板绿字/红字 = 面板总速度 - 面板白字 (保证白字+绿字永远精确等于总速度)
        disp_b_spd = math.floor(b_spd)
        disp_total_spd = math.floor(self.spd)
        disp_g_spd = disp_total_spd - disp_b_spd

        return {
            "生命值 (HP)": math.floor(self.hp),
            "攻击力 (ATK)": math.floor(self.atk),
            "防御力 (DEF)": math.floor(self.def_stat),
            "速度 (SPD)": disp_total_spd,
            "速度面板显示": f"{disp_total_spd} (白字 {disp_b_spd} + 绿字 {disp_g_spd:+d})",
            "速度实战精算": round(self.spd, 3),
            "暴击率 (CR)": floor_pct(self.crit_rate),
            "暴击伤害 (CD)": floor_pct(self.crit_dmg),
            "击破特攻 (BE)": floor_pct(self.break_effect),
            "能量恢复效率 (ERR)": floor_pct(self.err),
            "效果命中 (EHR)": floor_pct(self.ehr),
            "效果抵抗 (RES)": floor_pct(self.res),
            "属性伤害加成 (DMG%)": floor_pct(self.dmg_boost),
        }


@dataclass
class EquippedRelic:
    """单件装备的遗器数据。"""
    internal_uid: int
    relic_id: int
    relic_set_id: int
    set_name: str
    slot: int                    # 1:头, 2:手, 3:身, 4:脚, 5:球, 6:绳
    slot_name: str
    level: int
    main_affix_id: int
    main_affix_name: str
    main_affix_val: float
    is_main_pct: bool
    sub_affixes: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class EquippedLightCone:
    """角色装备的光锥。"""
    internal_uid: int
    item_id: int
    name: str
    level: int
    promotion: int
    superimposition: int         # 叠影阶数 (1-5)
    base_hp: float
    base_atk: float
    base_def: float
    passive_desc: str = ""
    passive_stats: Dict[str, float] = field(default_factory=dict)


@dataclass
class CharacterProfile:
    """完整的角色数据档案。"""
    avatar_id: int
    name: str
    element: Element
    path: Path
    level: int
    promotion: int
    eidolon: int                 # 星魂 (0-6)
    skills: Dict[int, int]       # 技能 ID -> 等级
    max_sp: int                  # 大招能量上限
    init_sp: int                 # 进场初始能量
    light_cone: Optional[EquippedLightCone]
    relics: List[EquippedRelic]
    panel: CharacterPanel

    def is_fully_geared(self) -> bool:
        """是否同时配齐了光锥和 6 件遗器。"""
        return self.light_cone is not None and len(self.relics) == 6

    def get_substat_roll_summary(self) -> Dict[str, Any]:
        """统计该角色全套装备的低/中/高档位命中与词条分布。"""
        tot_rolls = 0
        tot_low = 0
        tot_mid = 0
        tot_high = 0
        by_stat: Dict[str, int] = {}
        for r in self.relics:
            for s in r.sub_affixes:
                cnt = s.get("count", 0)
                l = s.get("low_rolls", 0)
                m = s.get("mid_rolls", 0)
                h = s.get("high_rolls", 0)
                name = s.get("name", "未知")
                tot_rolls += cnt
                tot_low += l
                tot_mid += m
                tot_high += h
                by_stat[name] = by_stat.get(name, 0) + cnt

        avg_quality = (tot_mid * 1.0 + tot_high * 2.0) / (tot_rolls * 2.0) * 100.0 if tot_rolls > 0 else 0.0
        return {
            "total_rolls": tot_rolls,
            "low_rolls": tot_low,
            "mid_rolls": tot_mid,
            "high_rolls": tot_high,
            "quality_score": round(avg_quality, 1),
            "by_stat": by_stat
        }


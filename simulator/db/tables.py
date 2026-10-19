"""全角色与装备数值常量与规则表 (Tables & Configs)。

包含：
1. 角色 80 级基础白值表 (AVATAR_STATS)；
2. 光锥 80 级基础白值与被动常驻属性表 (LIGHTCONE_STATS)；
3. 五星遗器 +15 级主词条属性表 (RELIC_MAIN_AFFIXES)；
4. 五星遗器副词条基础值与档位加权规则表 (RELIC_SUB_AFFIX_RULES)；
5. 遗器套装效果表 (RELIC_SET_EFFECTS)。
"""
from typing import Dict, Any

# ==========================================
# 1. 角色 80 级基准属性表 (Avatar Base Stats)
# ==========================================
AVATAR_STATS: Dict[int, Dict[str, Any]] = {
    # 常用主力角色 (包含官方精确白值与行迹被动属性加成)
    1001: {
        "name": "三月七", "element": "Ice", "path": "Knight",
        "base_hp": 1058.4, "base_atk": 511.56, "base_def": 573.3, "base_spd": 101.0, "max_sp": 120,
        "traces": {"def_pct": 0.225, "ice_dmg": 0.144, "res": 0.10}
    },
    1002: {
        "name": "丹恒", "element": "Wind", "path": "Rogue",
        "base_hp": 882.0, "base_atk": 546.84, "base_def": 396.9, "base_spd": 110.0, "max_sp": 100,
        "traces": {"wind_dmg": 0.224, "atk_pct": 0.18, "def_pct": 0.125}
    },
    1003: {
        "name": "姬子", "element": "Fire", "path": "Mage",
        "base_hp": 1023.1, "base_atk": 756.76, "base_def": 436.59, "base_spd": 96.0, "max_sp": 120,
        "traces": {"fire_dmg": 0.224, "crit_rate": 0.12, "res": 0.10}
    },
    1004: {
        "name": "瓦尔特", "element": "Imaginary", "path": "Warlock",
        "base_hp": 1125.4, "base_atk": 620.93, "base_def": 507.15, "base_spd": 102.0, "max_sp": 120,
        "traces": {"imaginary_dmg": 0.144, "atk_pct": 0.28, "res": 0.10}
    },
    1005: {
        "name": "卡芙卡", "element": "Thunder", "path": "Warlock",
        "base_hp": 1086.6, "base_atk": 679.14, "base_def": 485.1, "base_spd": 100.0, "max_sp": 120,
        "traces": {"atk_pct": 0.28, "ehr": 0.18, "hp_pct": 0.10}
    },
    1006: {
        "name": "银狼", "element": "Quantum", "path": "Warlock",
        "base_hp": 1047.8, "base_atk": 640.33, "base_def": 460.85, "base_spd": 107.0, "max_sp": 110,
        "traces": {"quantum_dmg": 0.08, "atk_pct": 0.28, "ehr": 0.18}
    },
    1009: {
        "name": "艾丝妲", "element": "Fire", "path": "Shaman",
        "base_hp": 1023.1, "base_atk": 511.56, "base_def": 463.05, "base_spd": 106.0, "max_sp": 120,
        "traces": {"fire_dmg": 0.224, "crit_rate": 0.067, "def_pct": 0.225}
    },
    1013: {
        "name": "黑塔", "element": "Ice", "path": "Mage",
        "base_hp": 952.6, "base_atk": 582.12, "base_def": 396.9, "base_spd": 100.0, "max_sp": 110,
        "traces": {"ice_dmg": 0.224, "crit_rate": 0.12, "def_pct": 0.225}
    },
    1101: {
        "name": "布洛妮娅", "element": "Wind", "path": "Shaman",
        "base_hp": 1241.9, "base_atk": 582.12, "base_def": 533.61, "base_spd": 99.0, "max_sp": 120,
        "traces": {"crit_dmg": 0.24, "wind_dmg": 0.224, "res": 0.10}
    },
    1102: {
        "name": "希儿", "element": "Quantum", "path": "Rogue",
        "base_hp": 931.4, "base_atk": 640.33, "base_def": 363.83, "base_spd": 115.0, "max_sp": 120,
        "traces": {"crit_dmg": 0.24, "atk_pct": 0.28, "def_pct": 0.125}
    },
    1104: {
        "name": "杰帕德", "element": "Ice", "path": "Knight",
        "base_hp": 1397.0, "base_atk": 543.31, "base_def": 654.89, "base_spd": 92.0, "max_sp": 100,
        "traces": {"def_pct": 0.35, "ice_dmg": 0.144, "res": 0.18}
    },
    1106: {
        "name": "佩拉", "element": "Ice", "path": "Warlock",
        "base_hp": 987.8, "base_atk": 511.56, "base_def": 463.05, "base_spd": 105.0, "max_sp": 110,
        "traces": {"ice_dmg": 0.224, "ehr": 0.10, "atk_pct": 0.18}
    },
    1107: {
        "name": "克拉拉", "element": "Physical", "path": "Warrior",
        "base_hp": 1241.9, "base_atk": 737.35, "base_def": 485.1, "base_spd": 90.0, "max_sp": 110,
        "traces": {"physical_dmg": 0.144, "atk_pct": 0.28, "hp_pct": 0.10}
    },
    1204: {
        "name": "景元", "element": "Thunder", "path": "Mage",
        "base_hp": 1164.2, "base_atk": 698.54, "base_def": 485.1, "base_spd": 99.0, "max_sp": 130,
        "traces": {"crit_rate": 0.12, "atk_pct": 0.28, "def_pct": 0.125}
    },
    1205: {
        "name": "刃", "element": "Wind", "path": "Warrior",
        "base_hp": 1358.3, "base_atk": 543.31, "base_def": 485.1, "base_spd": 97.0, "max_sp": 130,
        "traces": {"hp_pct": 0.28, "crit_rate": 0.12, "res": 0.10}
    },
    1208: {
        "name": "符玄", "element": "Quantum", "path": "Knight",
        "base_hp": 1474.7, "base_atk": 465.7, "base_def": 606.38, "base_spd": 100.0, "max_sp": 135,
        "traces": {"hp_pct": 0.18, "crit_rate": 0.187, "res": 0.10}
    },
    1211: {
        "name": "白露", "element": "Thunder", "path": "Priest",
        "base_hp": 1319.5, "base_atk": 562.72, "base_def": 485.1, "base_spd": 98.0, "max_sp": 100,
        "traces": {"hp_pct": 0.28, "def_pct": 0.225, "res": 0.10}
    },
    1212: {
        "name": "镜流", "element": "Ice", "path": "Warrior",
        "base_hp": 1428.0, "base_atk": 679.14, "base_def": 485.1, "base_spd": 96.0, "max_sp": 140,
        "traces": {"crit_dmg": 0.373, "spd": 9.0, "hp_pct": 0.10}
    },
    1213: {
        "name": "丹恒·饮月", "element": "Imaginary", "path": "Warrior",
        "base_hp": 1241.9, "base_atk": 698.54, "base_def": 363.83, "base_spd": 102.0, "max_sp": 140,
        "traces": {"imaginary_dmg": 0.224, "crit_rate": 0.12, "hp_pct": 0.10}
    },
    1217: {
        "name": "藿藿", "element": "Wind", "path": "Priest",
        "base_hp": 1358.3, "base_atk": 601.52, "base_def": 507.15, "base_spd": 98.0, "max_sp": 140,
        "traces": {"hp_pct": 0.28, "res": 0.18, "spd": 5.0}
    },
    1220: {
        "name": "飞霄", "element": "Wind", "path": "Rogue",
        "base_hp": 1047.8, "base_atk": 601.52, "base_def": 388.08, "base_spd": 112.0, "max_sp": 12,
        "traces": {"crit_dmg": 0.24, "atk_pct": 0.28, "def_pct": 0.125}
    },
    1221: {
        "name": "云璃", "element": "Physical", "path": "Warrior",
        "base_hp": 1358.3, "base_atk": 679.14, "base_def": 460.85, "base_spd": 94.0, "max_sp": 240,
        "traces": {"crit_rate": 0.067, "atk_pct": 0.28, "hp_pct": 0.18}
    },
    1222: {
        "name": "灵砂", "element": "Fire", "path": "Priest",
        "base_hp": 1358.3, "base_atk": 679.14, "base_def": 436.59, "base_spd": 98.0, "max_sp": 110,
        "traces": {"break_effect": 0.373, "atk_pct": 0.18, "hp_pct": 0.10}
    },
    1224: {
        "name": "三月七·巡猎", "element": "Imaginary", "path": "Rogue",
        "base_hp": 1058.4, "base_atk": 562.72, "base_def": 441.0, "base_spd": 102.0, "max_sp": 110,
        "traces": {"crit_dmg": 0.24, "atk_pct": 0.18, "def_pct": 0.125}
    },
    1225: {
        "name": "忘归人", "element": "Fire", "path": "Warlock",
        "base_hp": 1164.2, "base_atk": 582.12, "base_def": 533.61, "base_spd": 104.0, "max_sp": 130,
        "traces": {"break_effect": 0.373, "spd": 9.0, "atk_pct": 0.18}
    },
    1301: {
        "name": "加拉赫", "element": "Fire", "path": "Priest",
        "base_hp": 1305.4, "base_atk": 529.2, "base_def": 441.0, "base_spd": 98.0, "max_sp": 110,
        "traces": {"break_effect": 0.133, "res": 0.28, "hp_pct": 0.18}
    },
    1303: {
        "name": "阮·梅", "element": "Ice", "path": "Shaman",
        "base_hp": 1086.6, "base_atk": 659.74, "base_def": 485.1, "base_spd": 104.0, "max_sp": 130,
        "traces": {"break_effect": 0.373, "spd": 5.0, "def_pct": 0.225}
    },
    1304: {
        "name": "砂金", "element": "Imaginary", "path": "Knight",
        "base_hp": 1203.1, "base_atk": 446.29, "base_def": 654.89, "base_spd": 106.0, "max_sp": 110,
        "traces": {"def_pct": 0.35, "imaginary_dmg": 0.144, "res": 0.10}
    },
    1305: {
        "name": "真理医生", "element": "Imaginary", "path": "Rogue",
        "base_hp": 1047.8, "base_atk": 776.16, "base_def": 460.85, "base_spd": 103.0, "max_sp": 140,
        "traces": {"crit_rate": 0.12, "atk_pct": 0.28, "def_pct": 0.125}
    },
    1306: {
        "name": "花火", "element": "Quantum", "path": "Shaman",
        "base_hp": 1397.0, "base_atk": 523.9, "base_def": 485.1, "base_spd": 101.0, "max_sp": 110,
        "traces": {"crit_dmg": 0.24, "hp_pct": 0.28, "res": 0.10}
    },
    1307: {
        "name": "黑天鹅", "element": "Wind", "path": "Warlock",
        "base_hp": 1086.6, "base_atk": 659.74, "base_def": 485.1, "base_spd": 102.0, "max_sp": 120,
        "traces": {"wind_dmg": 0.144, "ehr": 0.10, "atk_pct": 0.28}
    },
    1308: {
        "name": "黄泉", "element": "Thunder", "path": "Warlock",
        "base_hp": 1125.4, "base_atk": 698.54, "base_def": 436.59, "base_spd": 101.0, "max_sp": 9,
        "traces": {"crit_dmg": 0.24, "atk_pct": 0.28, "thunder_dmg": 0.08}
    },
    1309: {
        "name": "知更鸟", "element": "Physical", "path": "Shaman",
        "base_hp": 1280.8, "base_atk": 640.33, "base_def": 485.1, "base_spd": 102.0, "max_sp": 160,
        "traces": {"atk_pct": 0.28, "hp_pct": 0.18, "spd": 5.0}
    },
    1310: {
        "name": "流萤", "element": "Fire", "path": "Warrior",
        "base_hp": 814.97, "base_atk": 523.9, "base_def": 776.16, "base_spd": 104.0, "max_sp": 240,
        "traces": {"break_effect": 0.373, "spd": 5.0, "res": 0.18}
    },
    1313: {
        "name": "星期日", "element": "Imaginary", "path": "Shaman",
        "base_hp": 1241.9, "base_atk": 640.33, "base_def": 533.61, "base_spd": 96.0, "max_sp": 130,
        "traces": {"crit_dmg": 0.373, "res": 0.18, "imaginary_dmg": 0.144}
    },
    1315: {
        "name": "波提欧", "element": "Physical", "path": "Rogue",
        "base_hp": 1023.1, "base_atk": 620.93, "base_def": 460.85, "base_spd": 107.0, "max_sp": 115,
        "traces": {"break_effect": 0.373, "hp_pct": 0.18, "crit_dmg": 0.133}
    },
    1317: {
        "name": "乱破", "element": "Imaginary", "path": "Mage",
        "base_hp": 1086.6, "base_atk": 717.94, "base_def": 460.85, "base_spd": 96.0, "max_sp": 140,
        "traces": {"break_effect": 0.373, "atk_pct": 0.28, "spd": 5.0}
    },
    1402: {
        "name": "雅格莱雅", "element": "Thunder", "path": "Remembrance",
        "base_hp": 1241.9, "base_atk": 679.14, "base_def": 485.1, "base_spd": 102.0, "max_sp": 140,
        "traces": {"crit_dmg": 0.24, "crit_rate": 0.12, "spd": 5.0}
    },
    1407: {
        "name": "遐蝶", "element": "Quantum", "path": "Remembrance",
        "base_hp": 1397.0, "base_atk": 620.93, "base_def": 533.61, "base_spd": 101.0, "max_sp": 140,
        "traces": {"crit_dmg": 0.24, "hp_pct": 0.28, "res": 0.10}
    },
    1409: {
        "name": "飞霄·巡猎", "element": "Wind", "path": "Rogue",
        "base_hp": 1047.8, "base_atk": 601.52, "base_def": 388.08, "base_spd": 112.0, "max_sp": 12,
        "traces": {"crit_dmg": 0.24, "atk_pct": 0.28, "def_pct": 0.125}
    },
    1501: {
        "name": "斯帕克西 (Sparxie)", "element": "Quantum", "path": "Shaman",
        "base_hp": 1397.0, "base_atk": 523.9, "base_def": 485.1, "base_spd": 101.0, "max_sp": 160,
        "traces": {"crit_dmg": 0.24, "hp_pct": 0.28, "spd": 5.0}
    },
    1502: {
        "name": "瑶光 (Yaoguang)", "element": "Imaginary", "path": "Shaman",
        "base_hp": 1241.9, "base_atk": 601.52, "base_def": 507.15, "base_spd": 102.0, "max_sp": 180,
        "traces": {"res": 0.18, "hp_pct": 0.18, "spd": 5.0}
    },
    1503: {
        "name": "雅格莱雅 (Aglaea)", "element": "Thunder", "path": "Remembrance",
        "base_hp": 1241.9, "base_atk": 679.14, "base_def": 485.1, "base_spd": 102.0, "max_sp": 180,
        "traces": {"crit_dmg": 0.24, "crit_rate": 0.12, "spd": 5.0}
    },
    1505: {
        "name": "依万妮西亚 (Evanescia)", "element": "Ice", "path": "Remembrance",
        "base_hp": 1358.3, "base_atk": 640.33, "base_def": 485.1, "base_spd": 99.0, "max_sp": 480,
        "traces": {"crit_dmg": 0.24, "crit_rate": 0.12, "hp_pct": 0.18}
    },
    1506: {
        "name": "银狼LV.999", "element": "Imaginary", "path": "Elation",
        "base_hp": 1153.6, "base_atk": 440.6, "base_def": 654.8, "base_spd": 110.0, "max_sp": 60,
        "traces": {"spd": 30.0, "crit_rate": 0.187}
    },
    1508: {
        "name": "远坂凛", "element": "Quantum", "path": "Mage",
        "base_hp": 1047.8, "base_atk": 640.33, "base_def": 460.85, "base_spd": 107.0, "max_sp": 160,
        "traces": {"crit_rate": 0.12, "quantum_dmg": 0.144, "atk_pct": 0.28}
    },
    1511: {
        "name": "姬子·新星 (Himeko Nova)", "element": "Fire", "path": "Mage",
        "base_hp": 1023.1, "base_atk": 756.76, "base_def": 436.59, "base_spd": 96.0, "max_sp": 8,
        "traces": {"crit_rate": 0.12, "fire_dmg": 0.224, "atk_pct": 0.18}
    },
    1512: {
        "name": "知更鸟·晴歌", "element": "Wind", "path": "Memory",
        "base_hp": 1203.1, "base_atk": 601.52, "base_def": 485.1, "base_spd": 95.0, "max_sp": 140,
        "traces": {"hp_pct": 0.18, "crit_rate": 0.067, "spd": 15.0}
    },
    8006: {
        "name": "开拓者·同谐", "element": "Imaginary", "path": "Shaman",
        "base_hp": 1086.6, "base_atk": 446.29, "base_def": 679.14, "base_spd": 105.0, "max_sp": 140,
        "traces": {"break_effect": 0.373, "imaginary_dmg": 0.144, "res": 0.10}
    },
    8008: {
        "name": "开拓者·记忆", "element": "Ice", "path": "Remembrance",
        "base_hp": 1164.2, "base_atk": 543.31, "base_def": 606.38, "base_spd": 100.0, "max_sp": 160,
        "traces": {"crit_dmg": 0.24, "ice_dmg": 0.144, "hp_pct": 0.10}
    },
    8010: {
        "name": "开拓者·欢愉", "element": "Fire", "path": "Elation",
        "base_hp": 1203.1, "base_atk": 620.93, "base_def": 533.61, "base_spd": 100.0, "max_sp": 160,
        "traces": {"atk_pct": 0.28, "crit_rate": 0.12, "def_pct": 0.125}
    }
}

# 通用 5 星 / 4 星角色保底白值模板 (针对未在字典内显式列出的角色)
DEFAULT_5STAR_STATS = {
    "name": "未知五星角色", "element": "Quantum", "path": "Warrior",
    "base_hp": 1241.9, "base_atk": 640.33, "base_def": 485.1, "base_spd": 100.0, "max_sp": 120,
    "traces": {"atk_pct": 0.18, "hp_pct": 0.10, "res": 0.10}
}
DEFAULT_4STAR_STATS = {
    "name": "未知四星角色", "element": "Physical", "path": "Warrior",
    "base_hp": 1058.4, "base_atk": 529.2, "base_def": 441.0, "base_spd": 100.0, "max_sp": 110,
    "traces": {"atk_pct": 0.14, "hp_pct": 0.10, "res": 0.08}
}

# ==========================================
# 2. 光锥 80 级基准属性表 (Lightcone Base Stats)
# ==========================================
LIGHTCONE_STATS: Dict[int, Dict[str, Any]] = {
    # 常用 5 星专属光锥
    23000: {"name": "银河铁道之夜", "path": "Mage", "base_hp": 1164.2, "base_atk": 582.1, "base_def": 396.9, "passive_stats": {"atk_pct": 0.24}},
    23001: {"name": "于夜色中", "path": "Rogue", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"crit_rate": 0.18}},
    23002: {"name": "如泥酣眠", "path": "Rogue", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"crit_dmg": 0.30}},
    23003: {"name": "但战斗还未结束", "path": "Shaman", "base_hp": 1164.2, "base_atk": 529.2, "base_def": 463.1, "passive_stats": {"err": 0.10}},
    23006: {"name": "只需等待", "path": "Warlock", "base_hp": 1058.4, "base_atk": 582.12, "base_def": 463.05, "passive_stats": {"dmg_boost": 0.24}},
    23008: {"name": "棺的余晖", "path": "Priest", "base_hp": 1164.2, "base_atk": 582.1, "base_def": 396.9, "passive_stats": {"atk_pct": 0.24}},
    23011: {"name": "她已闭上双眼", "path": "Knight", "base_hp": 1270.1, "base_atk": 423.4, "base_def": 529.2, "passive_stats": {"hp_pct": 0.24, "err": 0.12}},
    23019: {"name": "镜中故我", "path": "Shaman", "base_hp": 1058.4, "base_atk": 529.2, "base_def": 529.2, "passive_stats": {"break_effect": 0.60}},
    23021: {"name": "游戏尘寰", "path": "Shaman", "base_hp": 1164.2, "base_atk": 529.2, "base_def": 463.1, "passive_stats": {"crit_dmg": 0.32}},
    23022: {"name": "重塑时光的忆念", "path": "Warlock", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"ehr": 0.40}},
    23024: {"name": "行于流逝的岸", "path": "Warlock", "base_hp": 1058.4, "base_atk": 635.0, "base_def": 396.9, "passive_stats": {"crit_dmg": 0.36}},
    23025: {"name": "梦应归于何处", "path": "Warrior", "base_hp": 1164.2, "base_atk": 476.3, "base_def": 529.2, "passive_stats": {"break_effect": 0.60}},
    23026: {"name": "夜色流光溢彩", "path": "Shaman", "base_hp": 952.6, "base_atk": 635.0, "base_def": 463.1, "passive_stats": {"err": 0.15}},
    23030: {"name": "命运从未公平", "path": "Knight", "base_hp": 1058.4, "base_atk": 423.4, "base_def": 661.5, "passive_stats": {"def_pct": 0.40, "crit_dmg": 0.40}},
    23038: {"name": "落日时起舞", "path": "Warrior", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"crit_dmg": 0.36}},
    23040: {"name": "偏偏希望无价", "path": "Mage", "base_hp": 952.6, "base_atk": 582.1, "base_def": 529.2, "passive_stats": {"crit_rate": 0.16}},
    23042: {"name": "长路终有归途", "path": "Rogue", "base_hp": 952.6, "base_atk": 635.0, "base_def": 463.1, "passive_stats": {"crit_rate": 0.15}},
    23043: {"name": "雨一直下", "path": "Warlock", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"ehr": 0.24, "crit_rate": 0.12}},
    23046: {"name": "唯有香如故", "path": "Priest", "base_hp": 1058.4, "base_atk": 529.2, "base_def": 529.2, "passive_stats": {"break_effect": 0.60}},
    23052: {"name": "忍法帖·缭乱破魔", "path": "Mage", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"break_effect": 0.60}},
    23053: {"name": "遐蝶专属光锥", "path": "Remembrance", "base_hp": 1164.2, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"crit_dmg": 0.32, "hp_pct": 0.18}},
    23057: {"name": "欢迎来到银河城", "path": "Elation", "base_hp": 1058.4, "base_atk": 423.4, "base_def": 529.2, "passive_stats": {}},
    23058: {"name": "依万妮西亚专属光锥", "path": "Remembrance", "base_hp": 1164.2, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"crit_dmg": 0.32}},
    23065: {"name": "姬子新星专属光锥", "path": "Mage", "base_hp": 1058.4, "base_atk": 635.0, "base_def": 396.9, "passive_stats": {"crit_rate": 0.18}},
    24001: {"name": "纯粹思维的洗礼", "path": "Rogue", "base_hp": 952.6, "base_atk": 582.1, "base_def": 529.2, "passive_stats": {"crit_dmg": 0.20}},
    24004: {"name": "拂晓之前", "path": "Mage", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {"crit_dmg": 0.36}},
    24005: {"name": "记忆永不落幕", "path": "Memory", "base_hp": 1058.4, "base_atk": 529.2, "base_def": 396.9, "passive_stats": {"spd_pct": 0.12}},
    # 常用 5 星黑塔光锥
    22000: {"name": "星海巡航", "path": "Rogue", "base_hp": 952.6, "base_atk": 529.2, "base_def": 463.1, "passive_stats": {"crit_rate": 0.16}},
    22005: {"name": "记忆5星光锥", "path": "Remembrance", "base_hp": 1058.4, "base_atk": 529.2, "base_def": 463.1, "passive_stats": {"crit_dmg": 0.24}},
    22006: {"name": "同谐5星光锥", "path": "Shaman", "base_hp": 1058.4, "base_atk": 529.2, "base_def": 463.1, "passive_stats": {"break_effect": 0.40}},
    # 常用 4 星光锥
    21000: {"name": "等价交换", "path": "Priest", "base_hp": 952.6, "base_atk": 423.4, "base_def": 396.9, "passive_stats": {}},
    21004: {"name": "过往未来", "path": "Shaman", "base_hp": 952.6, "base_atk": 423.4, "base_def": 396.9, "passive_stats": {}},
    21007: {"name": "此时恰好", "path": "Priest", "base_hp": 952.6, "base_atk": 423.4, "base_def": 396.9, "passive_stats": {"res": 0.32}},
    21014: {"name": "一场术后对话", "path": "Priest", "base_hp": 1058.4, "base_atk": 423.4, "base_def": 330.8, "passive_stats": {"err": 0.16}},
    21015: {"name": "决心如汗珠般闪耀", "path": "Warlock", "base_hp": 952.6, "base_atk": 476.3, "base_def": 330.8, "passive_stats": {}},
    21016: {"name": "朗道的选择", "path": "Knight", "base_hp": 952.6, "base_atk": 423.4, "base_def": 396.9, "passive_stats": {}},
    21018: {"name": "舞！舞！舞！", "path": "Shaman", "base_hp": 952.6, "base_atk": 423.4, "base_def": 396.9, "passive_stats": {}},
    21021: {"name": "记忆中的模样", "path": "Shaman", "base_hp": 952.6, "base_atk": 423.4, "base_def": 396.9, "passive_stats": {"break_effect": 0.56}},
    21023: {"name": "我们是地火", "path": "Knight", "base_hp": 740.88, "base_atk": 476.28, "base_def": 463.05, "passive_stats": {}},
    21024: {"name": "论剑", "path": "Rogue", "base_hp": 952.6, "base_atk": 476.3, "base_def": 330.8, "passive_stats": {}},
    21034: {"name": "今日亦是和平的一日", "path": "Mage", "base_hp": 846.72, "base_atk": 529.2, "base_def": 330.75, "passive_stats": {}},
    21056: {"name": "追逐风的时候", "path": "Shaman", "base_hp": 1058.4, "base_atk": 476.28, "base_def": 396.9, "passive_stats": {}},
    21064: {"name": "新4星光锥", "path": "Remembrance", "base_hp": 952.6, "base_atk": 476.3, "base_def": 330.8, "passive_stats": {"crit_dmg": 0.32}},
}

DEFAULT_5STAR_LC = {
    "name": "未知五星光锥", "path": "Warrior", "base_hp": 1058.4, "base_atk": 582.1, "base_def": 463.1, "passive_stats": {}
}
DEFAULT_4STAR_LC = {
    "name": "未知四星光锥", "path": "Warrior", "base_hp": 952.6, "base_atk": 423.4, "base_def": 396.9, "passive_stats": {}
}

# ==========================================
# 3. 5 星遗器 +15 级主词条属性表 (Relic Main Affix Values)
# ==========================================
RELIC_MAIN_VALUES: Dict[int, Dict[int, Dict[str, Any]]] = {
    # 部件 1: 头部 (Head)
    1: {1: {"name": "生命值", "key": "flat_hp", "val": 705.6, "is_pct": False}},
    # 部件 2: 手部 (Hands)
    2: {1: {"name": "攻击力", "key": "flat_atk", "val": 352.8, "is_pct": False}},
    # 部件 3: 躯干 (Body)
    3: {
        1: {"name": "生命值 %", "key": "hp_pct", "val": 0.432, "is_pct": True},
        2: {"name": "攻击力 %", "key": "atk_pct", "val": 0.432, "is_pct": True},
        3: {"name": "防御力 %", "key": "def_pct", "val": 0.540, "is_pct": True},
        4: {"name": "暴击率 %", "key": "crit_rate", "val": 0.324, "is_pct": True},
        5: {"name": "暴击伤害 %", "key": "crit_dmg", "val": 0.648, "is_pct": True},
        6: {"name": "治疗加成 %", "key": "outgoing_healing", "val": 0.345, "is_pct": True},
        7: {"name": "效果命中 %", "key": "ehr", "val": 0.432, "is_pct": True},
    },
    # 部件 4: 脚部 (Feet)
    4: {
        1: {"name": "生命值 %", "key": "hp_pct", "val": 0.432, "is_pct": True},
        2: {"name": "攻击力 %", "key": "atk_pct", "val": 0.432, "is_pct": True},
        3: {"name": "防御力 %", "key": "def_pct", "val": 0.540, "is_pct": True},
        4: {"name": "速度", "key": "spd", "val": 25.032, "is_pct": False},
    },
    # 部件 5: 位面球 (Planar Sphere)
    5: {
        1: {"name": "生命值 %", "key": "hp_pct", "val": 0.432, "is_pct": True},
        2: {"name": "攻击力 %", "key": "atk_pct", "val": 0.432, "is_pct": True},
        3: {"name": "防御力 %", "key": "def_pct", "val": 0.540, "is_pct": True},
        4: {"name": "物理伤害加成 %", "key": "dmg_boost", "val": 0.3888, "is_pct": True},
        5: {"name": "火属性伤害加成 %", "key": "dmg_boost", "val": 0.3888, "is_pct": True},
        6: {"name": "冰属性伤害加成 %", "key": "dmg_boost", "val": 0.3888, "is_pct": True},
        7: {"name": "雷属性伤害加成 %", "key": "dmg_boost", "val": 0.3888, "is_pct": True},
        8: {"name": "风属性伤害加成 %", "key": "dmg_boost", "val": 0.3888, "is_pct": True},
        9: {"name": "量子伤害加成 %", "key": "dmg_boost", "val": 0.3888, "is_pct": True},
        10: {"name": "虚数伤害加成 %", "key": "dmg_boost", "val": 0.3888, "is_pct": True},
    },
    # 部件 6: 连结绳 (Link Rope)
    6: {
        1: {"name": "击破特攻 %", "key": "break_effect", "val": 0.648, "is_pct": True},
        2: {"name": "能量恢复效率 %", "key": "err", "val": 0.1944, "is_pct": True},
        3: {"name": "生命值 %", "key": "hp_pct", "val": 0.432, "is_pct": True},
        4: {"name": "攻击力 %", "key": "atk_pct", "val": 0.432, "is_pct": True},
        5: {"name": "防御力 %", "key": "def_pct", "val": 0.540, "is_pct": True},
    }
}

# ==========================================
# 4. 5 星遗器副词条规则表 (Sub-affix Base & Step)
# ==========================================
# 游戏内精确计算公式：Value = count * base + step * step_val
RELIC_SUB_RULES: Dict[int, Dict[str, Any]] = {
    1: {"name": "生命值 (固定值)", "key": "flat_hp", "base": 33.87004, "step_val": 4.233755, "is_pct": False},
    2: {"name": "攻击力 (固定值)", "key": "flat_atk", "base": 16.935019, "step_val": 2.116877, "is_pct": False},
    3: {"name": "防御力 (固定值)", "key": "flat_def", "base": 16.935019, "step_val": 2.116877, "is_pct": False},
    4: {"name": "生命值 %", "key": "hp_pct", "base": 0.034560002, "step_val": 0.0043200003, "is_pct": True},
    5: {"name": "攻击力 %", "key": "atk_pct", "base": 0.034560002, "step_val": 0.0043200003, "is_pct": True},
    6: {"name": "防御力 %", "key": "def_pct", "base": 0.0432, "step_val": 0.0054, "is_pct": True},
    7: {"name": "速度", "key": "spd", "base": 2.016, "step_val": 0.288, "is_pct": False},
    8: {"name": "暴击率 %", "key": "crit_rate", "base": 0.02592, "step_val": 0.0032400002, "is_pct": True},
    9: {"name": "暴击伤害 %", "key": "crit_dmg", "base": 0.05184, "step_val": 0.0064800004, "is_pct": True},
    10: {"name": "效果命中 %", "key": "ehr", "base": 0.034560002, "step_val": 0.0043200003, "is_pct": True},
    11: {"name": "效果抵抗 %", "key": "res", "base": 0.034560002, "step_val": 0.0043200003, "is_pct": True},
    12: {"name": "击破特攻 %", "key": "break_effect", "base": 0.05184, "step_val": 0.0064800004, "is_pct": True},
}

# ==========================================
# 5. 遗器套装效果表 (Relic Sets 2pc & 4pc)
# ==========================================
RELIC_SETS: Dict[int, Dict[str, Any]] = {
    # 常用外圈 4 件套 (Cavern Relics 101 ~ 134)
    101: {"name": "云无留迹的过客", "2pc": {"outgoing_healing": 0.10}, "4pc": {}},
    102: {"name": "野穗伴行的快枪手", "2pc": {"atk_pct": 0.12}, "4pc": {"spd_pct": 0.06}},
    103: {"name": "净庭教宗的圣骑士", "2pc": {"def_pct": 0.15}, "4pc": {}},
    104: {"name": "密林卧雪的猎人", "2pc": {"dmg_boost": 0.10}, "4pc": {}},
    105: {"name": "街头出身的拳王", "2pc": {"dmg_boost": 0.10}, "4pc": {}},
    106: {"name": "戍卫风雪的铁卫", "2pc": {"dmg_reduction": 0.08}, "4pc": {}},
    107: {"name": "熔岩锻铸的火匠", "2pc": {"dmg_boost": 0.10}, "4pc": {}},
    108: {"name": "繁星璀璨的天才", "2pc": {"dmg_boost": 0.10}, "4pc": {}},
    109: {"name": "激奏雷电的乐队", "2pc": {"dmg_boost": 0.10}, "4pc": {"atk_pct": 0.20}},
    110: {"name": "晨昏交界的翔鹰", "2pc": {"dmg_boost": 0.10}, "4pc": {}},
    111: {"name": "流星追迹的怪盗", "2pc": {"break_effect": 0.16}, "4pc": {"break_effect": 0.16}},
    112: {"name": "盗匪荒漠的废土客", "2pc": {"dmg_boost": 0.10}, "4pc": {}},
    113: {"name": "宝命长存的莳者", "2pc": {"hp_pct": 0.12}, "4pc": {"crit_rate": 0.16}},
    114: {"name": "骇域漫游的信使", "2pc": {"spd_pct": 0.06}, "4pc": {}},
    115: {"name": "毁烬焚骨的大公", "2pc": {"dmg_boost": 0.20}, "4pc": {}},
    116: {"name": "幽锁深牢的系囚", "2pc": {"atk_pct": 0.12}, "4pc": {}},
    117: {"name": "死水深潜的先驱", "2pc": {"dmg_boost": 0.12}, "4pc": {"crit_rate": 0.04}},
    118: {"name": "机心戏梦的钟表匠", "2pc": {"break_effect": 0.16}, "4pc": {}},
    119: {"name": "荡除蠹灾的铁骑", "2pc": {"break_effect": 0.16}, "4pc": {}},
    120: {"name": "风举云飞的勇烈", "2pc": {"atk_pct": 0.12}, "4pc": {"crit_rate": 0.06}},
    121: {"name": "重循苦旅的司舵", "2pc": {"spd_pct": 0.06}, "4pc": {}},
    122: {"name": "识海迷坠的学者", "2pc": {"crit_rate": 0.08}, "4pc": {}},
    123: {"name": "凯歌祝捷的英豪", "2pc": {"atk_pct": 0.12}, "4pc": {}},
    124: {"name": "沉醉于狂欢的诗人", "2pc": {"quantum_dmg": 0.10}, "4pc": {"spd_pct": -0.08}},
    125: {"name": "烈阳惊雷的女武神", "2pc": {"spd_pct": 0.06}, "4pc": {}},
    126: {"name": "恶海逐波的船长", "2pc": {"crit_dmg": 0.16}, "4pc": {}},
    127: {"name": "再创天地的救世主", "2pc": {"crit_rate": 0.08}, "4pc": {}},
    128: {"name": "自匿星芒的隐士", "2pc": {}, "4pc": {}},
    129: {"name": "闪耀功勋的魔法少女", "2pc": {"crit_dmg": 0.16}, "4pc": {}},
    130: {"name": "应天涉远的卜者", "2pc": {"spd_pct": 0.06}, "4pc": {}},
    131: {"name": "星如我见的领航员", "2pc": {"atk_pct": 0.12}, "4pc": {}},
    132: {"name": "叩问天工的名冶", "2pc": {"hp_pct": 0.12}, "4pc": {}},
    133: {"name": "戏梦点星的伶人", "2pc": {"spd_pct": 0.06}, "4pc": {}},
    134: {"name": "贪婪禁果的异端", "2pc": {"crit_dmg": 0.16}, "4pc": {}},

    # 常用内圈 2 件套 (Planar Ornaments 301 ~ 328)
    301: {"name": "太空封印站", "2pc": {"atk_pct": 0.12}},
    302: {"name": "不老者的仙舟", "2pc": {"hp_pct": 0.12}},
    303: {"name": "泛银河商业公司", "2pc": {"ehr": 0.10}},
    304: {"name": "筑城者的贝洛伯格", "2pc": {"def_pct": 0.15}},
    305: {"name": "星体差分机", "2pc": {"crit_dmg": 0.16}},
    306: {"name": "停转的萨尔索图", "2pc": {"crit_rate": 0.08}},
    307: {"name": "盗贼公国塔利亚", "2pc": {"break_effect": 0.16}},
    308: {"name": "生命的翁瓦克", "2pc": {"err": 0.05}},
    309: {"name": "繁星竞技场", "2pc": {"crit_rate": 0.08}},
    310: {"name": "折断的龙骨", "2pc": {"res": 0.10}},
    311: {"name": "苍穹战线格拉默", "2pc": {"atk_pct": 0.12}},
    312: {"name": "梦想之地匹诺康尼", "2pc": {"err": 0.05}},
    313: {"name": "无主荒星茨冈尼亚", "2pc": {"crit_rate": 0.04}},
    314: {"name": "出云显世与高天神国", "2pc": {"atk_pct": 0.12}},
    315: {"name": "奔狼的都蓝王朝", "2pc": {}},
    316: {"name": "劫火莲灯铸炼宫", "2pc": {"spd_pct": 0.06}},
    317: {"name": "沉陆海域露莎卡", "2pc": {"err": 0.05}},
    318: {"name": "奇想蕉乐园", "2pc": {"crit_dmg": 0.16}},
    319: {"name": "谧宁拾骨地", "2pc": {"hp_pct": 0.12}},
    320: {"name": "渊思寂虑的巨树", "2pc": {"spd_pct": 0.06}},
    322: {"name": "沉欢醉饮的海隅", "2pc": {"atk_pct": 0.12}},
    323: {"name": "永恒之地翁法罗斯", "2pc": {"crit_rate": 0.08}},
    324: {"name": "天国@直播间", "2pc": {"crit_dmg": 0.16}},
    325: {"name": "零号关卡朋克洛德", "2pc": {"dmg_boost": 0.08}},
    326: {"name": "新位面饰品", "2pc": {}},
    327: {"name": "坠星启航地", "2pc": {"crit_rate": 0.08}},
}

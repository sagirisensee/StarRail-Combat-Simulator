"""角色属性精确还原与计算引擎 (Stat Calculator)。

实现：
1. 基础白值叠加 (角色 80 级白值 + 光锥 80 级白值)；
2. 遗器主副词条档位解析与累加；
3. 套装 2 件套与 4 件套常驻效果激活；
4. 属性节点与被动光环常驻汇总；
5. 输出全套 CharacterPanel 与可溯源的 StatBreakdown。
"""
from typing import Dict, List, Optional, Tuple, Any
from .models import (
    StatBreakdown, CharacterPanel, EquippedRelic, EquippedLightCone, 
    Element, Path
)
from .tables import (
    AVATAR_STATS, DEFAULT_5STAR_STATS, DEFAULT_4STAR_STATS,
    LIGHTCONE_STATS, DEFAULT_5STAR_LC, DEFAULT_4STAR_LC,
    RELIC_MAIN_VALUES, RELIC_SUB_RULES, RELIC_SETS
)


class StatCalculator:
    """纯函数面板计算引擎。"""

    SLOT_NAMES = {
        1: "头部 (Head)",
        2: "手部 (Hands)",
        3: "躯干 (Body)",
        4: "脚部 (Feet)",
        5: "位面球 (Planar Sphere)",
        6: "连结绳 (Link Rope)",
    }

    @classmethod
    def calculate(
        cls,
        avatar_raw: Dict[str, Any],
        lc_raw: Optional[Dict[str, Any]],
        relics_raw: List[Dict[str, Any]]
    ) -> Tuple[CharacterPanel, Optional[EquippedLightCone], List[EquippedRelic]]:
        avatar_id = int(avatar_raw.get("avatar_id", 0))
        
        # 1. 获取角色基础白值与行迹
        c_stats = AVATAR_STATS.get(avatar_id)
        if not c_stats:
            c_stats = DEFAULT_5STAR_STATS if avatar_id >= 1000 else DEFAULT_4STAR_STATS

        char_hp = float(c_stats["base_hp"])
        char_atk = float(c_stats["base_atk"])
        char_def = float(c_stats["base_def"])
        char_spd = float(c_stats["base_spd"])
        trace_bonuses = dict(c_stats.get("traces", {}))

        # 2. 解析光锥白值与常驻被动
        equipped_lc: Optional[EquippedLightCone] = None
        lc_hp, lc_atk, lc_def = 0.0, 0.0, 0.0
        lc_passive_stats: Dict[str, float] = {}

        if lc_raw:
            item_id = int(lc_raw.get("item_id", 0))
            lc_cfg = LIGHTCONE_STATS.get(item_id)
            if not lc_cfg:
                lc_cfg = DEFAULT_5STAR_LC if item_id >= 23000 else DEFAULT_4STAR_LC

            lc_hp = float(lc_cfg["base_hp"])
            lc_atk = float(lc_cfg["base_atk"])
            lc_def = float(lc_cfg["base_def"])
            lc_path = lc_cfg.get("path")
            char_path = c_stats.get("path")
            if lc_path and char_path and lc_path != char_path:
                lc_passive_stats = {}  # 跨命途装备光锥，被动技能不生效
            else:
                lc_passive_stats = dict(lc_cfg.get("passive_stats", {}))

            equipped_lc = EquippedLightCone(
                internal_uid=lc_raw.get("internal_uid", 0),
                item_id=item_id,
                name=lc_cfg["name"],
                level=lc_raw.get("level", 80),
                promotion=lc_raw.get("promotion", 6),
                superimposition=lc_raw.get("rank", 1),
                base_hp=lc_hp,
                base_atk=lc_atk,
                base_def=lc_def,
                passive_stats=lc_passive_stats,
            )

        # 基础白值汇总
        base_white_hp = char_hp + lc_hp
        base_white_atk = char_atk + lc_atk
        base_white_def = char_def + lc_def
        base_white_spd = char_spd  # 光锥不提供基础速度

        # 3. 统计遗器词条与套装
        equipped_relics: List[EquippedRelic] = []
        set_counts: Dict[int, int] = {}
        relic_flat_bonuses: Dict[str, float] = {}
        relic_pct_bonuses: Dict[str, float] = {}

        for r_raw in relics_raw:
            r_id = str(r_raw.get("relic_id", 0))
            slot = int(r_id[-1]) if r_id and r_id[-1].isdigit() and int(r_id[-1]) in range(1, 7) else 1
            set_id = int(r_raw.get("relic_set_id", 0))
            level = int(r_raw.get("level", 15))
            main_affix_id = int(r_raw.get("main_affix_id", 1))
            
            set_counts[set_id] = set_counts.get(set_id, 0) + 1
            set_name = RELIC_SETS.get(set_id, {}).get("name", f"套装{set_id}")

            # 解析主词条
            slot_main_table = RELIC_MAIN_VALUES.get(slot, {})
            main_info = slot_main_table.get(main_affix_id, {"name": f"词条{main_affix_id}", "key": "unknown", "val": 0.0, "is_pct": False})
            m_key = main_info["key"]
            m_val = float(main_info["val"])
            m_pct = bool(main_info["is_pct"])

            if m_pct:
                relic_pct_bonuses[m_key] = relic_pct_bonuses.get(m_key, 0.0) + m_val
            else:
                relic_flat_bonuses[m_key] = relic_flat_bonuses.get(m_key, 0.0) + m_val

            # 解析副词条
            parsed_subs: List[Dict[str, Any]] = []
            for sub in r_raw.get("sub_affixes", []):
                sid = int(sub.get("sub_affix_id", 0))
                cnt = int(sub.get("count", 1))
                stp = int(sub.get("step", 0))

                sub_rule = RELIC_SUB_RULES.get(sid)
                if sub_rule:
                    s_key = sub_rule["key"]
                    s_val = cnt * sub_rule["base"] + stp * sub_rule["step_val"]
                    s_pct = sub_rule["is_pct"]

                    if s_pct:
                        relic_pct_bonuses[s_key] = relic_pct_bonuses.get(s_key, 0.0) + s_val
                    else:
                        relic_flat_bonuses[s_key] = relic_flat_bonuses.get(s_key, 0.0) + s_val

                    # 计算低、中、高档位命中次数
                    min_high = max(0, stp - cnt)
                    high = min_high
                    mid = stp - 2 * high
                    low = cnt - mid - high
                    quality = round((stp / (cnt * 2.0)) * 100, 1) if cnt > 0 else 0.0

                    parsed_subs.append({
                        "name": sub_rule["name"],
                        "key": s_key,
                        "value": round(s_val, 4),
                        "count": cnt,
                        "step": stp,
                        "low_rolls": low,
                        "mid_rolls": mid,
                        "high_rolls": high,
                        "quality_pct": quality,
                        "is_pct": s_pct
                    })

            equipped_relics.append(EquippedRelic(
                internal_uid=r_raw.get("internal_uid", 0),
                relic_id=int(r_id),
                relic_set_id=set_id,
                set_name=set_name,
                slot=slot,
                slot_name=cls.SLOT_NAMES.get(slot, f"部件{slot}"),
                level=level,
                main_affix_id=main_affix_id,
                main_affix_name=main_info["name"],
                main_affix_val=m_val,
                is_main_pct=m_pct,
                sub_affixes=parsed_subs
            ))

        # 按部件 1-6 排序
        equipped_relics.sort(key=lambda r: r.slot)

        # 4. 激活套装属性加成
        set_bonuses: Dict[str, float] = {}
        for sid, cnt in set_counts.items():
            set_rule = RELIC_SETS.get(sid, {})
            if cnt >= 2:
                for k, v in set_rule.get("2pc", {}).items():
                    set_bonuses[k] = set_bonuses.get(k, 0.0) + v
            if cnt >= 4:
                for k, v in set_rule.get("4pc", {}).items():
                    set_bonuses[k] = set_bonuses.get(k, 0.0) + v

        # 5. 各属性汇总计算
        # HP
        hp_pct = trace_bonuses.get("hp_pct", 0.0) + relic_pct_bonuses.get("hp_pct", 0.0) + set_bonuses.get("hp_pct", 0.0) + lc_passive_stats.get("hp_pct", 0.0)
        flat_hp = relic_flat_bonuses.get("flat_hp", 0.0)
        final_hp = base_white_hp * (1.0 + hp_pct) + flat_hp

        # ATK
        atk_pct = trace_bonuses.get("atk_pct", 0.0) + relic_pct_bonuses.get("atk_pct", 0.0) + set_bonuses.get("atk_pct", 0.0) + lc_passive_stats.get("atk_pct", 0.0)
        flat_atk = relic_flat_bonuses.get("flat_atk", 0.0)
        final_atk = base_white_atk * (1.0 + atk_pct) + flat_atk

        # DEF
        def_pct = trace_bonuses.get("def_pct", 0.0) + relic_pct_bonuses.get("def_pct", 0.0) + set_bonuses.get("def_pct", 0.0) + lc_passive_stats.get("def_pct", 0.0)
        flat_def = relic_flat_bonuses.get("flat_def", 0.0)
        final_def = base_white_def * (1.0 + def_pct) + flat_def

        # SPD
        # 速度百分比加成作用于角色基础速度
        spd_pct = set_bonuses.get("spd_pct", 0.0) + lc_passive_stats.get("spd_pct", 0.0)
        flat_spd = trace_bonuses.get("spd", 0.0) + relic_flat_bonuses.get("spd", 0.0)
        final_spd = base_white_spd * (1.0 + spd_pct) + flat_spd

        # 暴击率 (CRIT Rate)
        crit_rate = (
            0.05
            + trace_bonuses.get("crit_rate", 0.0)
            + lc_passive_stats.get("crit_rate", 0.0)
            + relic_pct_bonuses.get("crit_rate", 0.0)
            + set_bonuses.get("crit_rate", 0.0)
        )

        # 暴击伤害 (CRIT DMG)
        crit_dmg = (
            0.50
            + trace_bonuses.get("crit_dmg", 0.0)
            + lc_passive_stats.get("crit_dmg", 0.0)
            + relic_pct_bonuses.get("crit_dmg", 0.0)
            + set_bonuses.get("crit_dmg", 0.0)
        )

        # 击破特攻 (Break Effect)
        break_effect = (
            0.0
            + trace_bonuses.get("break_effect", 0.0)
            + lc_passive_stats.get("break_effect", 0.0)
            + relic_pct_bonuses.get("break_effect", 0.0)
            + set_bonuses.get("break_effect", 0.0)
        )

        # 能量恢复效率 (ERR)
        err = (
            1.0
            + trace_bonuses.get("err", 0.0)
            + lc_passive_stats.get("err", 0.0)
            + relic_pct_bonuses.get("err", 0.0)
            + set_bonuses.get("err", 0.0)
        )

        # 效果命中 (EHR)
        ehr = (
            0.0
            + trace_bonuses.get("ehr", 0.0)
            + lc_passive_stats.get("ehr", 0.0)
            + relic_pct_bonuses.get("ehr", 0.0)
            + set_bonuses.get("ehr", 0.0)
        )

        # 效果抵抗 (RES)
        res = (
            0.0
            + trace_bonuses.get("res", 0.0)
            + lc_passive_stats.get("res", 0.0)
            + relic_pct_bonuses.get("res", 0.0)
            + set_bonuses.get("res", 0.0)
        )

        # 属性增伤总和 (DMG Boost) - 根据角色自身元素属性精确对应
        char_elem = c_stats.get("element", "Physical").lower()
        elem_key = f"{char_elem}_dmg"
        char_elem_trace = trace_bonuses.get(elem_key, 0.0)
        char_elem_relic = relic_pct_bonuses.get("dmg_boost", 0.0) + relic_pct_bonuses.get(elem_key, 0.0)
        char_elem_set = set_bonuses.get("dmg_boost", 0.0) + set_bonuses.get(elem_key, 0.0)
        dmg_boost = (
            0.0
            + char_elem_trace
            + lc_passive_stats.get("dmg_boost", 0.0)
            + char_elem_relic
            + char_elem_set
        )

        # 构造可追溯的 StatBreakdown 字典
        breakdowns = {
            "hp": StatBreakdown(base_white=base_white_hp, flat_bonus=flat_hp, percent_bonus=hp_pct, final_value=final_hp),
            "atk": StatBreakdown(base_white=base_white_atk, flat_bonus=flat_atk, percent_bonus=atk_pct, final_value=final_atk),
            "def": StatBreakdown(base_white=base_white_def, flat_bonus=flat_def, percent_bonus=def_pct, final_value=final_def),
            "spd": StatBreakdown(base_white=base_white_spd, flat_bonus=flat_spd, percent_bonus=spd_pct, final_value=final_spd),
            "crit_rate": StatBreakdown(base_white=0.05, flat_bonus=0.0, percent_bonus=crit_rate - 0.05, final_value=crit_rate),
            "crit_dmg": StatBreakdown(base_white=0.50, flat_bonus=0.0, percent_bonus=crit_dmg - 0.50, final_value=crit_dmg),
        }

        panel = CharacterPanel(
            hp=final_hp,
            atk=final_atk,
            def_stat=final_def,
            spd=final_spd,
            crit_rate=crit_rate,
            crit_dmg=crit_dmg,
            break_effect=break_effect,
            err=err,
            ehr=ehr,
            res=res,
            dmg_boost=dmg_boost,
            breakdowns=breakdowns
        )

        return panel, equipped_lc, equipped_relics

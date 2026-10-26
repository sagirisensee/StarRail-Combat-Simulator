"""全角色属性数据库管理与转换服务 (CharacterDB Service)。

实现：
1. 玩家存档数据加载与多格式兼容；
2. 全量角色装备、光锥与遗器批量关联与属性计算；
3. 角色档案高效缓存与按 ID / 角色名多维度查询；
4. 一键导出至战斗模拟器 Entity 实体（零特定角色 ID 硬编码，角色行迹与基线校准统一由 KitHandler.apply_trace_passives 多态处理）；
5. 全量属性持久化导出为 JSON 报表。
"""
import json
from typing import Dict, List, Optional, Union, Any

from .models import (
    CharacterProfile, CharacterPanel, Element, Path
)
from .tables import AVATAR_STATS, DEFAULT_5STAR_STATS, DEFAULT_4STAR_STATS, RELIC_SETS
from .calculator import StatCalculator

# 延迟导入模拟器核心 Entity，避免循环引用
try:
    from ..core import Entity
except ImportError:
    Entity = None


class CharacterDB:
    """全角色属性数据库服务。"""

    def __init__(self):
        self._profiles_by_id: Dict[int, CharacterProfile] = {}
        self._profiles_by_name: Dict[str, CharacterProfile] = {}
        self._raw_data: Optional[Dict[str, Any]] = None

    def load(self, source: Union[str, Dict[str, Any]]) -> "CharacterDB":
        """加载存档数据并完成全量角色属性编译。"""
        if isinstance(source, str):
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
        elif isinstance(source, dict):
            data = source
        else:
            raise ValueError(f"不支持的输入源类型: {type(source)}")

        self._raw_data = data
        self._compile()
        return self

    def _compile(self):
        """核心编译过程：关联角色、光锥与遗器，计算综合面板。"""
        if not self._raw_data:
            return

        self._profiles_by_id.clear()
        self._profiles_by_name.clear()

        # 兼容模式：直接加载已导出并精准计算的结构化报表 (如 character_db_export.json)
        if "characters" in self._raw_data:
            self._compile_from_export()
            return

        avatars_dict = self._raw_data.get("avatars", {})
        relics_list = self._raw_data.get("relics", [])
        lightcones_list = self._raw_data.get("lightcones", [])

        # 1. 建立装备与角色关联索引
        relics_by_avatar: Dict[int, List[Dict[str, Any]]] = {}
        for r in relics_list:
            eq = int(r.get("equip_avatar", 0))
            if eq > 0:
                relics_by_avatar.setdefault(eq, []).append(r)

        lc_by_avatar: Dict[int, Dict[str, Any]] = {}
        for lc in lightcones_list:
            eq = int(lc.get("equip_avatar", 0))
            if eq > 0:
                lc_by_avatar[eq] = lc

        # 2. 逐一编译全角色
        for aid_str, a_data in avatars_dict.items():
            aid = int(aid_str)
            raw_data_block = a_data.get("data", {})
            eidolon = int(raw_data_block.get("rank", 0))
            skills = {int(k): int(v) for k, v in raw_data_block.get("skills", {}).items()}
            level = int(a_data.get("level", 80))
            promotion = int(a_data.get("promotion", 6))
            max_sp = int(a_data.get("sp_max", 120))
            init_sp = int(a_data.get("sp_value", 0))

            # 获取基础名称、属性与命途
            c_cfg = AVATAR_STATS.get(aid)
            if not c_cfg:
                c_cfg = DEFAULT_5STAR_STATS if aid >= 1000 else DEFAULT_4STAR_STATS

            name = c_cfg["name"]
            element = Element.from_str(c_cfg["element"])
            path = Path.from_str(c_cfg["path"])

            # 关联专属装备并调用纯函数计算面板
            lc_raw = lc_by_avatar.get(aid)
            relics_raw = relics_by_avatar.get(aid, [])

            panel, equipped_lc, equipped_relics = StatCalculator.calculate(
                avatar_raw={"avatar_id": aid, "level": level, "promotion": promotion},
                lc_raw=lc_raw,
                relics_raw=relics_raw
            )

            profile = CharacterProfile(
                avatar_id=aid,
                name=name,
                element=element,
                path=path,
                level=level,
                promotion=promotion,
                eidolon=eidolon,
                skills=skills,
                max_sp=max_sp,
                init_sp=init_sp,
                light_cone=equipped_lc,
                relics=equipped_relics,
                panel=panel
            )

            self._profiles_by_id[aid] = profile
            self._profiles_by_name[name] = profile

    def _compile_from_export(self):
        """从高精导出的结构化 JSON 报表直接编译角色档案。"""
        from .models import StatBreakdown, EquippedRelic, EquippedLightCone
        chars = self._raw_data.get("characters", [])
        for c in chars:
            aid = int(c["avatar_id"])
            name = c["name"]
            element = Element.from_str(c.get("element", "Physical"))
            raw_path = str(c.get("path", "Warrior"))
            path = Path.from_str(raw_path)

            level = int(c.get("level", 80))
            eidolon_str = str(c.get("eidolon", "E0"))
            eidolon = int(eidolon_str.replace("E", "")) if eidolon_str.startswith("E") else 0

            # 光锥
            lc_raw = c.get("light_cone")
            equipped_lc = None
            if lc_raw:
                lc_s_str = str(lc_raw.get("superimposition", "S1"))
                lc_s = int(lc_s_str.replace("S", "")) if lc_s_str.startswith("S") else 1
                equipped_lc = EquippedLightCone(
                    internal_uid=0,
                    item_id=int(lc_raw.get("item_id", 0)),
                    name=lc_raw.get("name", ""),
                    level=int(lc_raw.get("level", 80)),
                    promotion=6,
                    superimposition=lc_s,
                    base_hp=0.0,
                    base_atk=0.0,
                    base_def=0.0
                )

            # 遗器
            name_to_set_id: Dict[str, int] = {}
            for sid_tbl, sinfo in RELIC_SETS.items():
                name_to_set_id[sinfo.get("name", "")] = sid_tbl
            for rs in c.get("relic_sets", []):
                if "(ID " in rs and rs.endswith(")"):
                    try:
                        s_name = rs.split(" (ID ")[0].strip()
                        s_id = int(rs.split(" (ID ")[1][:-1])
                        name_to_set_id[s_name] = s_id
                    except Exception:
                        pass

            relics_list = []
            for r in c.get("relic_details", []):
                r_set_name = r.get("set_name", "")
                r_set_id = name_to_set_id.get(r_set_name, 0)
                relics_list.append(EquippedRelic(
                    internal_uid=0,
                    relic_id=0,
                    relic_set_id=r_set_id,
                    set_name=r_set_name,
                    slot=int(r.get("slot", 1)),
                    slot_name=r.get("slot_name", ""),
                    level=15,
                    main_affix_id=0,
                    main_affix_name=r.get("main_affix", ""),
                    main_affix_val=0.0,
                    is_main_pct=False,
                    sub_affixes=r.get("sub_affixes", [])
                ))

            # 面板
            s = c.get("stats_summary", {})
            b = c.get("breakdowns", {})
            
            def parse_pct(val_str: str) -> float:
                if isinstance(val_str, (int, float)):
                    return float(val_str)
                return float(str(val_str).replace("%", "").strip()) / 100.0 if "%" in str(val_str) else float(val_str)

            breakdowns = {}
            for k, bd in b.items():
                pct_str = bd.get("percent_bonus", "0%")
                pct_val = parse_pct(pct_str)
                breakdowns[k] = StatBreakdown(
                    base_white=float(bd.get("base_white", 0.0)),
                    flat_bonus=float(bd.get("flat_bonus", 0.0)),
                    percent_bonus=pct_val,
                    final_value=float(bd.get("final_value", 0.0))
                )

            hp_exact = float(b.get("hp", {}).get("final_value", s.get("生命值 (HP)", 0)))
            atk_exact = float(b.get("atk", {}).get("final_value", s.get("攻击力 (ATK)", 0)))
            def_exact = float(b.get("def", {}).get("final_value", s.get("防御力 (DEF)", 0)))
            spd_exact = float(s.get("速度实战精算", b.get("spd", {}).get("final_value", s.get("速度 (SPD)", 100))))

            panel = CharacterPanel(
                hp=hp_exact,
                atk=atk_exact,
                def_stat=def_exact,
                spd=spd_exact,
                crit_rate=parse_pct(s.get("暴击率 (CR)", "5.0%")),
                crit_dmg=parse_pct(s.get("暴击伤害 (CD)", "50.0%")),
                break_effect=parse_pct(s.get("击破特攻 (BE)", "0.0%")),
                err=parse_pct(s.get("能量恢复效率 (ERR)", "100.0%")),
                ehr=parse_pct(s.get("效果命中 (EHR)", "0.0%")),
                res=parse_pct(s.get("效果抵抗 (RES)", "0.0%")),
                dmg_boost=parse_pct(s.get("属性伤害加成 (DMG%)", "0.0%")),
                elation=parse_pct(s.get("欢愉度 (Elation)", "0.0%")),
                breakdowns=breakdowns
            )

            profile = CharacterProfile(
                avatar_id=aid,
                name=name,
                element=element,
                path=path,
                level=level,
                promotion=6,
                eidolon=eidolon,
                skills={},
                max_sp=120,
                init_sp=0,
                light_cone=equipped_lc,
                relics=relics_list,
                panel=panel
            )

            self._profiles_by_id[aid] = profile
            self._profiles_by_name[name] = profile

    def get(self, avatar_id_or_name: Union[int, str]) -> Optional[CharacterProfile]:
        """根据角色 ID 或名称查询档案。"""
        if isinstance(avatar_id_or_name, int):
            return self._profiles_by_id.get(avatar_id_or_name)
        return self.get_by_name(str(avatar_id_or_name))

    def get_by_name(self, name: str) -> Optional[CharacterProfile]:
        """根据角色名称模糊或精确查询档案 (忽略中点•、·、空格与大小写差异)。"""
        if name in self._profiles_by_name:
            return self._profiles_by_name[name]

        norm = lambda s: str(s).replace("•", "").replace("·", "").replace(".", "").replace(" ", "").lower()
        target_norm = norm(name)

        for cname, p in self._profiles_by_name.items():
            if norm(cname) == target_norm:
                return p

        for cname, p in self._profiles_by_name.items():
            if target_norm in norm(cname) or norm(cname) in target_norm:
                return p
        return None

    def list_all(self) -> List[CharacterProfile]:
        """列出数据库中所有角色档案。"""
        return list(self._profiles_by_id.values())

    def list_fully_geared(self) -> List[CharacterProfile]:
        """列出配齐光锥和 6 件遗器的角色。"""
        return [p for p in self._profiles_by_id.values() if p.is_fully_geared()]

    def to_combat_entity(self, avatar_id_or_name_or_profile: Union[int, str, CharacterProfile], policy: str = "EAA") -> Any:
        """一键转换为战斗模拟器中的行动与伤害实体 (Entity)。"""
        if isinstance(avatar_id_or_name_or_profile, CharacterProfile):
            profile = avatar_id_or_name_or_profile
        elif isinstance(avatar_id_or_name_or_profile, int):
            profile = self.get(avatar_id_or_name_or_profile)
        else:
            profile = self.get_by_name(str(avatar_id_or_name_or_profile))

        from ..core import Entity
        try:
            from ..kits.registry import get_kit_class
        except ImportError:
            get_kit_class = None

        if not profile:
            char_name = str(avatar_id_or_name_or_profile)
            kit_cls = get_kit_class(char_name) if get_kit_class else None
            kit_inst = kit_cls(owner_id=char_name, port=None, eidolon=0) if kit_cls else None
            if kit_inst:
                try:
                    from ..scaling import SkillScalingFactory
                    scaling = SkillScalingFactory.create(char_name, eidolon=0)
                    if scaling:
                        kit_inst.bind_scaling(scaling)
                except Exception:
                    pass
            max_energy = 120.0
            if kit_inst:
                try:
                    from ..actions import ActionKind
                    ult_defn = kit_inst.definition(ActionKind.ULTIMATE)
                    if ult_defn and ult_defn.cost.energy > 0:
                        max_energy = ult_defn.cost.energy
                except Exception:
                    pass
            ent = Entity(
                name=char_name,
                base_speed=134.0,
                base_atk=2600.0,
                base_crit_rate=0.60,
                base_crit_dmg=1.30,
                max_hp=10000.0,
                current_hp=10000.0,
                energy=0.0,
                max_energy=max_energy,
                kit=kit_inst,
                distance_remaining=10000.0,
                policy=policy,
                is_enemy=False
            )
            if kit_inst and hasattr(kit_inst, "apply_trace_passives"):
                kit_inst.apply_trace_passives(ent)
            return ent

        panel = profile.panel

        # 自动尝试装配对应的 KitHandler (未专门定制的角色优雅回退至 GenericKit)
        kit_inst = None
        if get_kit_class:
            kit_cls = get_kit_class(profile.name) or get_kit_class(str(profile.avatar_id))
            if not kit_cls:
                from ..kits.registry import GenericKit
                kit_cls = GenericKit
            if kit_cls:
                kit_inst = kit_cls(owner_id=profile.name, port=None, eidolon=profile.eidolon)
                try:
                    from ..scaling import SkillScalingFactory
                    scaling = SkillScalingFactory.create(profile.name or str(profile.avatar_id), eidolon=profile.eidolon)
                    if scaling:
                        kit_inst.bind_scaling(scaling)
                except Exception:
                    pass

        max_energy = 120.0
        if kit_inst:
            try:
                from ..actions import ActionKind
                ult_defn = kit_inst.definition(ActionKind.ULTIMATE)
                if ult_defn and ult_defn.cost.energy > 0:
                    max_energy = ult_defn.cost.energy
            except Exception:
                pass

        # 自动尝试装配对应的独立 LightConeHandler
        lc_inst = None
        if profile.light_cone:
            try:
                from ..light_cones import LightConeRegistry
                s_val = int(profile.light_cone.superimposition) if hasattr(profile.light_cone, "superimposition") else 1
                lc_name = profile.light_cone.name if hasattr(profile.light_cone, "name") else str(profile.light_cone)
                lc_inst = LightConeRegistry.create(lc_name, owner_id=profile.name, port=None, superimposition=s_val)
            except Exception:
                pass

        # 自动尝试装配对应的独立 RelicSetHandler
        relic_handlers = []
        set_counts: Dict[str, int] = {}
        if getattr(profile, "relics", None):
            try:
                from ..relics import RelicRegistry
                set_keys: Dict[str, Any] = {}
                for r in profile.relics:
                    sid = getattr(r, "relic_set_id", 0)
                    sname = getattr(r, "set_name", "")
                    key = sname if sname else str(sid)
                    set_counts[key] = set_counts.get(key, 0) + 1
                    set_keys[key] = sid if sid > 0 else sname

                for key, cnt in set_counts.items():
                    lookup_key = set_keys.get(key, key)
                    if cnt >= 4:
                        h = RelicRegistry.create(lookup_key, owner_id=profile.name, port=None, pieces=4)
                        if not h and isinstance(lookup_key, int) and key != str(lookup_key):
                            h = RelicRegistry.create(key, owner_id=profile.name, port=None, pieces=4)
                        if h:
                            relic_handlers.append(h)
                    elif cnt >= 2:
                        h = RelicRegistry.create(lookup_key, owner_id=profile.name, port=None, pieces=2)
                        if not h and isinstance(lookup_key, int) and key != str(lookup_key):
                            h = RelicRegistry.create(key, owner_id=profile.name, port=None, pieces=2)
                        if h:
                            relic_handlers.append(h)
            except Exception:
                pass

        breakdowns = getattr(panel, "breakdowns", {}) or {}
        base_white_hp = getattr(breakdowns.get("hp"), "base_white", panel.hp)
        base_white_speed = getattr(breakdowns.get("spd"), "base_white", panel.spd)
        base_white_atk = getattr(breakdowns.get("atk"), "base_white", 0.0)
        base_white_def = getattr(breakdowns.get("def"), "base_white", 0.0)

        entity = Entity(
            name=profile.name,
            base_speed=panel.spd,
            base_white_speed=base_white_speed,
            base_white_atk=base_white_atk,
            base_white_def=base_white_def,
            base_atk=panel.atk,
            base_def=getattr(panel, "def_stat", 600.0),
            base_crit_rate=panel.crit_rate,
            base_crit_dmg=panel.crit_dmg,
            base_break_effect=getattr(panel, "break_effect", 0.0),
            base_effect_res=getattr(panel, "res", 0.10),
            base_effect_hit_rate=getattr(panel, "ehr", 0.0),
            base_err=getattr(panel, "err", 1.0),
            base_dmg_boost=getattr(panel, "dmg_boost", 0.0),
            element=profile.element.name if hasattr(profile.element, "name") else str(profile.element),
            path=profile.path.name if hasattr(profile.path, "name") else str(profile.path),
            level=getattr(profile, "level", 80),
            max_hp=panel.hp,
            current_hp=panel.hp,
            base_white_hp=base_white_hp,
            base_outgoing_healing=0.0,
            energy=0.0,
            max_energy=max_energy,
            avatar_id=profile.avatar_id,
            eidolon=profile.eidolon,
            kit=kit_inst,
            light_cone=lc_inst,
            relic_handlers=relic_handlers,
            distance_remaining=10000.0,
            policy=policy,
            is_enemy=False
        )

        # 1. 遗器被动属性与主词条提取 (解耦委托至遗器模块自身处理)
        from ..relics.base import apply_equipped_relics_affixes
        apply_equipped_relics_affixes(getattr(profile, "relics", None), entity)
        for rh in relic_handlers:
            if hasattr(rh, "apply_panel_passives"):
                rh.apply_panel_passives(entity)

        # 2. 角色行迹常驻被动属性与白字基准提取 (多态委托至各角色的技能套件 Kit 自身处理)
        if kit_inst and hasattr(kit_inst, "apply_trace_passives"):
            kit_inst.apply_trace_passives(entity)

        return entity

    def export_summary_json(self, output_path: str):
        """将全库角色属性导出为人类可读的结构化 JSON 报表。"""
        records = []
        for p in self.list_all():
            rec = {
                "avatar_id": p.avatar_id,
                "name": p.name,
                "element": p.element.value,
                "path": p.path.value,
                "level": p.level,
                "eidolon": f"E{p.eidolon}",
                "light_cone": {
                    "item_id": p.light_cone.item_id,
                    "name": p.light_cone.name,
                    "superimposition": f"S{p.light_cone.superimposition}",
                    "level": p.light_cone.level
                } if p.light_cone else None,
                "relic_count": len(p.relics),
                "relic_sets": list({f"{r.set_name} (ID {r.relic_set_id})" for r in p.relics}),
                "stats_summary": p.panel.summary_dict(),
                "breakdowns": {k: v.to_dict() for k, v in p.panel.breakdowns.items()},
                "substat_roll_stats": p.get_substat_roll_summary(),
                "relic_details": [
                    {
                        "slot": r.slot,
                        "slot_name": r.slot_name,
                        "set_name": r.set_name,
                        "main_affix": f"{r.main_affix_name} +{r.main_affix_val if not r.is_main_pct else f'{r.main_affix_val*100:.1f}%'}",
                        "sub_affixes": r.sub_affixes
                    }
                    for r in p.relics
                ]
            }
            records.append(rec)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "total_avatars": len(records),
                "fully_geared_count": len(self.list_fully_geared()),
                "characters": records
            }, f, ensure_ascii=False, indent=2)

    def summary_text(self) -> str:
        """生成数据库的汇总统计文本。"""
        all_chars = self.list_all()
        geared_chars = self.list_fully_geared()
        
        lines = [
            f"=== 星穹铁道全角色属性数据库 (Character Stats DB) 汇总 ===",
            f"  总收录角色数: {len(all_chars)} 位",
            f"  满配主力 (光锥+6件遗器): {len(geared_chars)} 位",
            f"\n【前 10 位高练度主力角色面板快照】:"
        ]
        
        import math
        for p in geared_chars[:10]:
            lc_str = f"{p.light_cone.name} (S{p.light_cone.superimposition})" if p.light_cone else "无光锥"
            lines.append(
                f"  - [{p.name}] (E{p.eidolon}, 80级) | 光锥: {lc_str}\n"
                f"    HP: {math.floor(p.panel.hp):<5} | ATK: {math.floor(p.panel.atk):<5} | DEF: {math.floor(p.panel.def_stat):<5} | "
                f"SPD: {math.floor(p.panel.spd)} (精算 {p.panel.spd:.2f}) | 双暴: {p.panel.crit_rate*100:.1f}% / {p.panel.crit_dmg*100:.1f}%"
            )
        return "\n".join(lines)


# 模块级单例工厂方法
_GLOBAL_DB: Optional[CharacterDB] = None

def get_character_db(data_path: Optional[str] = None) -> CharacterDB:
    global _GLOBAL_DB
    if _GLOBAL_DB is None:
        _GLOBAL_DB = CharacterDB()
        if data_path:
            _GLOBAL_DB.load(data_path)
    return _GLOBAL_DB

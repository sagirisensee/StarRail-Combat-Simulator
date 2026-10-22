"""
Nanoka 4.6 Data Normalizer
Converts raw JSON snapshots from data/nanoka/raw/4.6/ into normalized assets:
- data/nanoka/normalized/4.6/relic_sets.json
- data/nanoka/normalized/4.6/lightcones.json
- data/nanoka/normalized/4.6/characters.json
"""

import json
import re
from pathlib import Path

VERSION = "4.6"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT_DIR / "data" / "nanoka" / "raw" / VERSION
NORM_DIR = ROOT_DIR / "data" / "nanoka" / "normalized" / VERSION


def normalize_relic_sets(raw_relics: dict) -> dict:
    normalized = {}
    for set_id, data in raw_relics.items():
        name = data.get("zh", data.get("en", str(set_id)))
        bonuses = []
        set_bonuses = data.get("set", {})
        for pieces_str in sorted(set_bonuses.keys(), key=lambda x: int(x)):
            bonus_info = set_bonuses[pieces_str]
            bonuses.append({
                "required_pieces": int(pieces_str),
                "params": bonus_info.get("ParamList", []),
                "desc": bonus_info.get("zh", bonus_info.get("en", "")),
            })
        normalized[str(set_id)] = {
            "id": str(set_id),
            "name": name,
            "bonuses": bonuses,
        }
    return normalized


def normalize_lightcones(raw_index: dict, detail_dir: Path) -> dict:
    normalized = {}
    for lc_id, idx_data in raw_index.items():
        detail_path = detail_dir / f"{lc_id}.json"
        detail_data = {}
        if detail_path.exists():
            with open(detail_path, "r", encoding="utf-8") as f:
                detail_data = json.load(f)

        name = detail_data.get("name") or idx_data.get("zh", idx_data.get("en", str(lc_id)))
        base_type = detail_data.get("base_type") or idx_data.get("baseType", "")
        rarity_str = detail_data.get("rarity") or idx_data.get("rank", "CombatPowerLightconeRarity4")
        # Extract rarity integer from string e.g. CombatPowerLightconeRarity5 -> 5
        rarity_match = re.search(r"(\d+)", str(rarity_str))
        rarity = int(rarity_match.group(1)) if rarity_match else 4

        ref_info = detail_data.get("refinements", {})
        skill_name = ref_info.get("name", "")
        skill_desc = ref_info.get("desc", "")
        levels_raw = ref_info.get("level", {})
        refinements = {}
        for lvl_str in sorted(levels_raw.keys(), key=lambda x: int(x)):
            refinements[lvl_str] = {
                "params": levels_raw[lvl_str].get("param_list", [])
            }

        normalized[str(lc_id)] = {
            "id": str(lc_id),
            "name": name,
            "path": base_type,
            "rarity": rarity,
            "skill_name": skill_name,
            "skill_desc": skill_desc,
            "refinements": refinements,
            "stats": detail_data.get("stats", []),
        }
    return normalized


def parse_eidolon_skill_bonuses(ranks: dict) -> list[dict]:
    """Parse E3 / E5 skill upgrades from rank descriptions."""
    bonuses = []
    # e.g. "终结技等级+2，最多不超过15级；普攻等级+1，最多不超过10级。"
    # e.g. "战技等级+2，最多不超过15级；天赋等级+2，最多不超过15级。"
    pattern = re.compile(r"(普攻|战技|终结技|天赋)等级\+(\d+)(?:，最多不超过(\d+)级)?")
    type_map = {
        "普攻": "Normal",
        "战技": "BPSkill",
        "终结技": "Ultra",
        "天赋": "Talent",
    }
    for rank_str, rank_data in ranks.items():
        desc = rank_data.get("desc", "")
        matches = pattern.findall(desc)
        for skill_cn, delta_str, max_str in matches:
            bonuses.append({
                "eidolon": int(rank_str),
                "skill_type": type_map.get(skill_cn, skill_cn),
                "skill_type_cn": skill_cn,
                "delta": int(delta_str),
                "max_level": int(max_str) if max_str else (15 if skill_cn != "普攻" else 10),
            })
    return bonuses


def normalize_characters(raw_index: dict, detail_dir: Path) -> dict:
    normalized = {}
    for char_id, idx_data in raw_index.items():
        detail_path = detail_dir / f"{char_id}.json"
        detail_data = {}
        if detail_path.exists():
            with open(detail_path, "r", encoding="utf-8") as f:
                detail_data = json.load(f)

        name = detail_data.get("name") or idx_data.get("zh", idx_data.get("en", str(char_id)))
        damage_type = detail_data.get("damage_type") or idx_data.get("damageType", "")
        base_type = detail_data.get("base_type") or idx_data.get("baseType", "")
        rarity_str = detail_data.get("rarity") or idx_data.get("rank", "CombatPowerAvatarRarityType4")
        rarity_match = re.search(r"(\d+)", str(rarity_str))
        rarity = int(rarity_match.group(1)) if rarity_match else 4

        # Process skills
        skills_raw = detail_data.get("skills", {})
        skills = {}
        for sid, sdata in skills_raw.items():
            stype = sdata.get("type", "")
            # Talent often has type=None or type='' in raw, but type_name='天赋'
            if not stype or stype == "None":
                type_name = sdata.get("type_name", "")
                if "天赋" in type_name:
                    stype = "Talent"
                elif "秘技" in type_name:
                    stype = "Maze"
                elif "普攻" in type_name:
                    stype = "Normal"
                elif "战技" in type_name:
                    stype = "BPSkill"
                elif "终结技" in type_name:
                    stype = "Ultra"

            levels_raw = sdata.get("level", {})
            params_by_level = {}
            for lvl_k in sorted(levels_raw.keys(), key=lambda x: int(x)):
                params_by_level[lvl_k] = levels_raw[lvl_k].get("param_list", [])

            skills[str(sid)] = {
                "id": str(sid),
                "name": sdata.get("name", ""),
                "type": stype,
                "type_name": sdata.get("type_name", ""),
                "tag": sdata.get("tag", ""),
                "sp_base": sdata.get("sp_base"),
                "bp_need": sdata.get("bp_need"),
                "bp_add": sdata.get("bp_add"),
                "desc": sdata.get("desc", ""),
                "params_by_level": params_by_level,
            }

        # Process ranks (eidolons)
        ranks_raw = detail_data.get("ranks", {})
        eidolons = {}
        for rk, rv in ranks_raw.items():
            eidolons[str(rk)] = {
                "rank": int(rk),
                "name": rv.get("name", ""),
                "desc": rv.get("desc", ""),
                "params": rv.get("params", []),
            }

        eidolon_bonuses = parse_eidolon_skill_bonuses(ranks_raw)

        normalized[str(char_id)] = {
            "id": str(char_id),
            "name": name,
            "damage_type": damage_type,
            "path": base_type,
            "rarity": rarity,
            "skills": skills,
            "eidolons": eidolons,
            "eidolon_skill_bonuses": eidolon_bonuses,
            "stats": detail_data.get("stats", []),
            "skill_trees": detail_data.get("skill_trees", {}),
        }
    return normalized


def main():
    NORM_DIR.mkdir(parents=True, exist_ok=True)
    print(f"=== Normalizing Nanoka HSR Version {VERSION} ===")

    # 1. Relic Sets
    with open(RAW_DIR / "relicset.json", "r", encoding="utf-8") as f:
        raw_relics = json.load(f)
    norm_relics = normalize_relic_sets(raw_relics)
    relics_out = NORM_DIR / "relic_sets.json"
    with open(relics_out, "w", encoding="utf-8") as f:
        json.dump(norm_relics, f, ensure_ascii=False, indent=2)
    print(f"✓ Normalized {len(norm_relics)} relic sets -> {relics_out}")

    # 2. Light Cones
    with open(RAW_DIR / "lightcone.json", "r", encoding="utf-8") as f:
        raw_lc = json.load(f)
    lc_detail_dir = RAW_DIR / "zh" / "lightcone"
    norm_lc = normalize_lightcones(raw_lc, lc_detail_dir)
    lc_out = NORM_DIR / "lightcones.json"
    with open(lc_out, "w", encoding="utf-8") as f:
        json.dump(norm_lc, f, ensure_ascii=False, indent=2)
    print(f"✓ Normalized {len(norm_lc)} light cones -> {lc_out}")

    # 3. Characters
    with open(RAW_DIR / "character.json", "r", encoding="utf-8") as f:
        raw_char = json.load(f)
    char_detail_dir = RAW_DIR / "zh" / "character"
    norm_char = normalize_characters(raw_char, char_detail_dir)
    char_out = NORM_DIR / "characters.json"
    with open(char_out, "w", encoding="utf-8") as f:
        json.dump(norm_char, f, ensure_ascii=False, indent=2)
    print(f"✓ Normalized {len(norm_char)} characters -> {char_out}")

    print("=== Normalization complete ===")


if __name__ == "__main__":
    main()

"""
Nanoka 4.6 Data Validator
Verifies integrity, completeness, and boundary correctness of normalized assets.
"""

import json
from pathlib import Path

VERSION = "4.6"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
NORM_DIR = ROOT_DIR / "data" / "nanoka" / "normalized" / VERSION


def validate():
    print(f"=== Validating Normalized Nanoka Assets (Version {VERSION}) ===")

    # 1. Relic Sets
    with open(NORM_DIR / "relic_sets.json", "r", encoding="utf-8") as f:
        relics = json.load(f)
    assert len(relics) == 62, f"Expected 62 relic sets, got {len(relics)}"
    for rid, rdata in relics.items():
        assert "name" in rdata and rdata["name"], f"Relic {rid} missing name"
        assert len(rdata["bonuses"]) >= 1, f"Relic {rid} has no bonuses"
        for b in rdata["bonuses"]:
            assert b["required_pieces"] in (2, 4), f"Relic {rid} invalid piece threshold {b['required_pieces']}"
            assert isinstance(b["params"], list), f"Relic {rid} params is not a list"
    print(f"✓ Relic sets verified: {len(relics)} sets valid")

    # 2. Light Cones
    with open(NORM_DIR / "lightcones.json", "r", encoding="utf-8") as f:
        lcs = json.load(f)
    assert len(lcs) == 170, f"Expected 170 light cones, got {len(lcs)}"
    for lcid, lcdata in lcs.items():
        assert "name" in lcdata and lcdata["name"], f"LC {lcid} missing name"
        assert "path" in lcdata, f"LC {lcid} missing path"
        assert 3 <= lcdata["rarity"] <= 5, f"LC {lcid} invalid rarity {lcdata['rarity']}"
        # Check refinements for 3, 4, 5 star light cones
        if lcdata["rarity"] >= 3:
            for lvl in ("1", "2", "3", "4", "5"):
                assert lvl in lcdata["refinements"], f"LC {lcid} missing refinement {lvl}"
                assert isinstance(lcdata["refinements"][lvl]["params"], list), f"LC {lcid} S{lvl} params not a list"
    print(f"✓ Light cones verified: {len(lcs)} light cones valid (S1-S5 complete)")

    # 3. Characters
    with open(NORM_DIR / "characters.json", "r", encoding="utf-8") as f:
        chars = json.load(f)
    assert len(chars) == 98, f"Expected 98 characters, got {len(chars)}"
    char_with_eidolons = 0
    char_with_bonuses = 0
    for cid, cdata in chars.items():
        assert "name" in cdata and cdata["name"], f"Char {cid} missing name"
        assert len(cdata["skills"]) >= 3, f"Char {cid} has fewer than 3 skills"
        if len(cdata["eidolons"]) == 6:
            char_with_eidolons += 1
        if len(cdata["eidolon_skill_bonuses"]) >= 2:
            char_with_bonuses += 1
    print(f"✓ Characters verified: {len(chars)} characters valid ({char_with_eidolons} with full E1-E6, {char_with_bonuses} with E3/E5 bonuses parsed)")

    print("=== All 4.6 asset validations passed! ===")


if __name__ == "__main__":
    validate()

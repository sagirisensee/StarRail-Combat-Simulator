# coding: utf-8
"""官方 ConfigAbility / Modifier / Hash / Excel 配置秒查工具。

复用 GameDataLoader 本地磁盘缓存索引（首次构建后 <0.2s 热启动），替代临时遍历脚本。

用法示例:
  python scripts/inspect_ability.py MEquip_23042_Main --max-chars 800
  python scripts/inspect_ability.py Hyacine --list
  python scripts/inspect_ability.py --hash -1998280268 1557799697
  python scripts/inspect_ability.py --equip 23042
  python scripts/inspect_ability.py --buff 3034003
  python scripts/inspect_ability.py --battle-event 20049
  python scripts/inspect_ability.py --monster 5014023
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulator.vm.expr import dotnet_hash
from simulator.vm.loader import GameDataLoader


def _dump_json(obj: Any, *, max_chars: int, full: bool) -> str:
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    if not full and max_chars > 0 and len(txt) > max_chars:
        return txt[:max_chars] + f"\n... <truncated {len(txt) - max_chars} chars; pass --full or larger --max-chars>"
    return txt


def _iter_symbol_entries(loader: GameDataLoader) -> List[Tuple[str, str, str, Any]]:
    loader.ensure_ability_index()
    entries: List[Tuple[str, str, str, Any]] = []
    for name, ab in loader._ability_by_name.items():
        entries.append(("Ability", name, loader._symbol_sources.get(name, ""), ab))
    for name, mod in loader._global_mod_by_name.items():
        entries.append(("GlobalMod", name, loader._symbol_sources.get(name, ""), mod))
    for mname, (ab_name, rel_path) in loader._ability_mod_index.items():
        info = loader.get_inner_modifier(mname)
        mdef = info[2] if info is not None else {}
        entries.append(("InnerMod", mname, f"{rel_path}::{ab_name}", mdef))
    for name, tpl in loader._global_tpl_by_name.items():
        entries.append(("GlobalTpl", name, loader._symbol_sources.get(name, ""), tpl))
    return entries


def _cmd_query(
    loader: GameDataLoader,
    query: str,
    *,
    list_only: bool,
    limit: int,
    max_chars: int,
    full: bool,
) -> int:
    entries = _iter_symbol_entries(loader)
    exact = [e for e in entries if e[1] == query]
    matches = exact if exact else [e for e in entries if query.lower() in e[1].lower()]
    if not matches:
        print(f"No matching Ability/Modifier/Template found for {query!r}.")
        return 1
    shown = matches[:limit] if limit > 0 else matches
    if list_only:
        print(f"Matched {len(matches)} symbol(s) for {query!r} (showing {len(shown)}):")
        for kind, name, src, _obj in shown:
            print(f"  [{kind:<9s}] {name}  ({src})")
        return 0
    for kind, name, src, obj in shown:
        print(f"=== [{kind}] {name}  (source: {src}) ===")
        print(_dump_json(obj, max_chars=max_chars, full=full))
    if len(matches) > len(shown):
        print(f"... {len(matches) - len(shown)} more match(es) omitted; pass --list or higher --limit.")
    return 0


def _collect_hash_candidates_and_refs(
    loader: GameDataLoader,
    target_hashes: Set[int],
) -> Tuple[Dict[int, Set[str]], Dict[int, List[Tuple[str, str]]]]:
    loader.ensure_ability_index()
    key_fields = ("DynamicKey", "TriggerKey", "FromDynamicKey", "ToDynamicKey", "Key", "PointTriggerKey", "DynamicFloatSet", "ModifierName", "AbilityName")
    cand_strings: Set[str] = set()
    refs: Dict[int, List[Tuple[str, str]]] = {h: [] for h in target_hashes}
    seen_refs: Dict[int, Set[Tuple[str, str]]] = {h: set() for h in target_hashes}

    def _record_str(val: Any) -> None:
        if isinstance(val, str) and val:
            cand_strings.add(val)

    def _walk(node: Any, owner_kind: str, owner_name: str) -> None:
        if isinstance(node, dict):
            for kf in key_fields:
                v = node.get(kf)
                if isinstance(v, str):
                    _record_str(v)
                elif isinstance(v, dict):
                    _record_str(v.get("Value"))
                    _record_str(v.get("RawString"))
                    hv = v.get("Hash")
                    if isinstance(hv, int) and hv in refs:
                        pair = (owner_kind, owner_name)
                        if pair not in seen_refs[hv]:
                            seen_refs[hv].add(pair)
                            refs[hv].append(pair)
            dv = node.get("DynamicValues")
            if isinstance(dv, dict):
                for sub_k, sub_v in dv.items():
                    if isinstance(sub_v, dict):
                        for inner_k in sub_v.keys():
                            if isinstance(inner_k, str):
                                _record_str(inner_k)
                    elif isinstance(sub_k, str):
                        _record_str(sub_k)
            mods = node.get("Modifiers")
            if isinstance(mods, dict):
                for mn in mods.keys():
                    _record_str(mn)
            dhashes = node.get("DynamicHashes")
            if isinstance(dhashes, list):
                for hv in dhashes:
                    if isinstance(hv, int) and hv in refs:
                        pair = (owner_kind, owner_name)
                        if pair not in seen_refs[hv]:
                            seen_refs[hv].add(pair)
                            refs[hv].append(pair)
            for val in node.values():
                if isinstance(val, (dict, list)):
                    _walk(val, owner_kind, owner_name)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    _walk(item, owner_kind, owner_name)

    for name, ab in loader._ability_by_name.items():
        _record_str(name)
        _walk(ab, "Ability", name)
    for name, mod in loader._global_mod_by_name.items():
        _record_str(name)
        _walk(mod, "GlobalMod", name)
    for name, tpl in loader._global_tpl_by_name.items():
        _record_str(name)
        _walk(tpl, "GlobalTpl", name)

    # Also harvest CustomValues keys from Config/ConfigCharacter JSONs
    char_dir = os.path.join(loader.data_root, "Config", "ConfigCharacter")
    stack = [char_dir]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=True):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=True) and entry.name.endswith(".json") and not entry.name.endswith(".layout.json"):
                        try:
                            with open(entry.path, "r", encoding="utf-8") as f:
                                doc = json.load(f)
                        except Exception:
                            continue
                        cv = doc.get("CustomValues")
                        if isinstance(cv, dict):
                            for ck in cv.keys():
                                _record_str(ck)
        except OSError:
            continue

    by_hash: Dict[int, Set[str]] = {h: set() for h in target_hashes}
    for s in cand_strings:
        dh = dotnet_hash(s)
        if dh in by_hash:
            by_hash[dh].add(s)
    return by_hash, refs


def _cmd_hash(loader: GameDataLoader, hashes: Sequence[int], *, limit: int) -> int:
    targets = {int(h) for h in hashes}
    by_hash, refs = _collect_hash_candidates_and_refs(loader, targets)
    for h in hashes:
        names = sorted(by_hash.get(int(h), ()))
        ref_list = refs.get(int(h), [])
        shown_refs = ref_list[:limit] if limit > 0 else ref_list
        print(f"=== Hash {h} ===")
        print(f"  Candidate key(s): {names if names else '[] (not found in scanned keys)'}")
        print(f"  Referenced in ({len(ref_list)} symbol(s), showing {len(shown_refs)}):")
        for kind, sym in shown_refs:
            src = loader._symbol_sources.get(sym, "")
            print(f"    [{kind:<9s}] {sym}  ({src})")
    return 0


def _cmd_equip(loader: GameDataLoader, equip_id: int, *, max_chars: int, full: bool) -> int:
    try:
        equips = loader._read_excel("EquipmentConfig.json")
        skills = loader._read_excel("EquipmentSkillConfig.json")
    except Exception as exc:
        print(f"Failed to read Equipment tables: {exc}")
        return 1
    eq_row = next((r for r in equips if int(r.get("EquipmentID", 0) or 0) == equip_id), None)
    skill_id = int(eq_row["SkillID"]) if eq_row and "SkillID" in eq_row else equip_id
    sk_rows = [r for r in skills if int(r.get("SkillID", 0) or 0) == skill_id]
    if not eq_row and not sk_rows:
        print(f"Equipment/Skill ID {equip_id} not found.")
        return 1
    if eq_row:
        print("=== EquipmentConfig ===")
        print(_dump_json(eq_row, max_chars=max_chars, full=full))
    if sk_rows:
        print("=== EquipmentSkillConfig ===")
        ab_names: List[str] = []
        for r in sk_rows:
            lv = r.get("Level")
            abn = str(r.get("AbilityName") or "")
            if abn and abn not in ab_names:
                ab_names.append(abn)
            params = [p.get("Value", p) if isinstance(p, dict) else p for p in (r.get("ParamList") or ())]
            print(f"  Level={lv}  SkillID={r.get('SkillID')}  AbilityName={abn}  ParamList={params}")
        for abn in ab_names:
            ab = loader.get_ability(abn)
            src = loader._symbol_sources.get(abn, "")
            print(f"\n=== Ability: {abn}  (source: {src}) ===")
            print(_dump_json(ab, max_chars=max_chars, full=full))
    return 0


def _cmd_buff(loader: GameDataLoader, buff_id: int, *, max_chars: int, full: bool) -> int:
    try:
        rows = loader._read_excel("MazeBuff.json")
    except Exception as exc:
        print(f"Failed to read MazeBuff.json: {exc}")
        return 1
    matched = [r for r in rows if int(r.get("ID", 0) or 0) == buff_id]
    if not matched:
        print(f"MazeBuff ID {buff_id} not found.")
        return 1
    for r in matched:
        print(f"=== MazeBuff {buff_id} (Lv={r.get('Lv')}) ===")
        print(_dump_json(r, max_chars=max_chars, full=full))
        for field_name in ("InBattleBindingKey", "ModifierName"):
            sym = str(r.get(field_name) or "")
            if not sym:
                continue
            ab = loader.get_ability(sym)
            if ab is not None:
                print(f"\n=== Bound Ability ({field_name}): {sym} ({loader._symbol_sources.get(sym, '')}) ===")
                print(_dump_json(ab, max_chars=max_chars, full=full))
            gm = loader.get_global_modifier(sym)
            if gm is not None:
                print(f"\n=== Bound GlobalMod ({field_name}): {sym} ({loader._symbol_sources.get(sym, '')}) ===")
                print(_dump_json(gm, max_chars=max_chars, full=full))
    return 0


def _cmd_battle_event(loader: GameDataLoader, be_id: int, *, max_chars: int, full: bool) -> int:
    be_cfg = [r for r in loader._read_excel("BattleEventConfig.json") if int(r.get("BattleEventID", 0) or 0) == be_id]
    be_data = [r for r in loader._read_excel("BattleEventData.json") if int(r.get("BattleEventID", 0) or 0) == be_id]
    skill_ids: Set[int] = set()
    for row in be_data:
        for sid in row.get("SkillIDList") or ():
            skill_ids.add(int(sid))
    sk_rows = [
        r for r in loader._read_excel("BattleEventSkillConfig.json")
        if int(r.get("SkillID", 0) or 0) == be_id or int(r.get("SkillID", 0) or 0) in skill_ids
    ]
    if not be_cfg and not be_data and not sk_rows:
        print(f"BattleEvent {be_id} not found.")
        return 1
    if be_cfg:
        print("=== BattleEventConfig ===")
        print(_dump_json(be_cfg, max_chars=max_chars, full=full))
    if be_data:
        print("=== BattleEventData ===")
        print(_dump_json(be_data, max_chars=max_chars, full=full))
        for row in be_data:
            cfg_rel = str(row.get("Config") or "")
            if cfg_rel:
                try:
                    cfg_doc = loader._read_json(cfg_rel)
                    print(f"=== {cfg_rel} ===")
                    print(_dump_json(cfg_doc, max_chars=max_chars, full=full))
                except OSError:
                    pass
    if sk_rows:
        print("=== BattleEventSkillConfig ===")
        print(_dump_json(sk_rows, max_chars=max_chars, full=full))
    return 0


def _cmd_monster(loader: GameDataLoader, monster_id: int, *, max_chars: int, full: bool) -> int:
    loader._ensure_monsters()
    mrow = loader._monsters.get(monster_id)
    if mrow is None:
        print(f"MonsterID {monster_id} not found.")
        return 1
    tmpl_id = int(mrow.get("MonsterTemplateID", 0) or 0)
    trows = loader._read_excel("MonsterTemplateConfig.json")
    trow = next((r for r in trows if int(r.get("MonsterTemplateID", 0) or 0) == tmpl_id), None)
    print(f"=== MonsterConfig {monster_id} ===")
    print(_dump_json(mrow, max_chars=max_chars, full=full))
    if trow is not None:
        print(f"=== MonsterTemplateConfig {tmpl_id} ===")
        print(_dump_json(trow, max_chars=max_chars, full=full))
        jcfg = str(mrow.get("OverrideJsonConfig") or trow.get("JsonConfig") or "")
        if jcfg:
            try:
                cfg_doc = loader._read_json(jcfg)
                print(f"=== {jcfg} ===")
                print(_dump_json(cfg_doc, max_chars=max_chars, full=full))
            except OSError as exc:
                print(f"(could not read {jcfg}: {exc})")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="官方 HSR ConfigAbility / Hash / Excel 配置秒查工具")
    parser.add_argument("query", nargs="?", default=None, help="Ability / Modifier / Template 名称或子串")
    parser.add_argument("--hash", dest="hashes", type=int, nargs="+", default=None, help="反查一个或多个 .NET Hash 值对应的 Key 与引用位置")
    parser.add_argument("--equip", type=int, default=None, help="查询光锥 EquipmentID / SkillID 与绑定 Ability")
    parser.add_argument("--buff", type=int, default=None, help="查询 MazeBuff ID 与绑定 Ability / Modifier")
    parser.add_argument("--battle-event", type=int, default=None, help="查询 BattleEvent ID / SkillID 配置")
    parser.add_argument("--monster", type=int, default=None, help="查询 MonsterID 与 JsonConfig")
    parser.add_argument("--list", action="store_true", help="仅列出匹配符号名和源路径")
    parser.add_argument("--limit", type=int, default=20, help="多条结果最大展示数量（默认 20，0 为不限）")
    parser.add_argument("--max-chars", type=int, default=4000, help="每段 JSON 输出字符上限（默认 4000）")
    parser.add_argument("--full", action="store_true", help="输出完整 JSON 不截断")
    args = parser.parse_args(argv)

    loader = GameDataLoader()
    if args.hashes:
        return _cmd_hash(loader, args.hashes, limit=args.limit)
    if args.equip is not None:
        return _cmd_equip(loader, args.equip, max_chars=args.max_chars, full=args.full)
    if args.buff is not None:
        return _cmd_buff(loader, args.buff, max_chars=args.max_chars, full=args.full)
    if args.battle_event is not None:
        return _cmd_battle_event(loader, args.battle_event, max_chars=args.max_chars, full=args.full)
    if args.monster is not None:
        return _cmd_monster(loader, args.monster, max_chars=args.max_chars, full=args.full)
    if args.query:
        return _cmd_query(
            loader,
            args.query,
            list_only=args.list,
            limit=args.limit,
            max_chars=args.max_chars,
            full=args.full,
        )
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

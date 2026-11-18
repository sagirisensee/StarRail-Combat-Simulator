"""Global DynamicHash Reverse Dictionary, Obfuscated OpCode Registry & Flat IR Cache Compiler.

Read-only Phase 3 pre-compiler module aligned with ``docs/ARCHITECTURE_BLUEPRINT.md``:
1. Builds a global ``DynamicHash`` reverse dictionary (``int32 -> str``) across
   Avatars, Servants, Light Cones, Relics, Monsters, Stage/BattleEvents, and ConfigAI.
2. Registers obfuscated ``$type`` instructions (e.g. ``JDOLDFECMPL``, ``GFODFDCBFJF``)
   into semantic OpCodes and scans ``ConfigAbility`` for obfuscated nodes.
3. Compiles nested ``ConfigAbility`` ASTs into flat, role-tagged IR
   (``CompiledIRAbility`` / ``CompiledIRTask``) with pre-decoded ``CompiledPostfixExpr``.
4. Caches symbol tables and compiled IR keyed by the ``TurnBasedGameData`` source
   fingerprint (git HEAD or deterministic file-stat digest).

Strictly read-only: never modifies any existing simulator or game data files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import glob
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from simulator.vm.expr import BUILTIN_FUNCS, CompiledPostfixExpr, dotnet_hash
from simulator.vm.loader import DEFAULT_TBGD_ROOT, GameDataLoader, prune_ability

IR_COMPILER_VERSION = "1.0.0"


class AbilityRole(str, Enum):
    """Explicit semantic role classification for compiled abilities."""

    PASSIVE_INIT = "PASSIVE_INIT"
    TURN_INSERT = "TURN_INSERT"
    ACTIVE_SKILL = "ACTIVE_SKILL"
    SERVANT_SKILL = "SERVANT_SKILL"
    BATTLE_EVENT = "BATTLE_EVENT"
    MONSTER_SKILL = "MONSTER_SKILL"
    EQUIPMENT_OR_RELIC = "EQUIPMENT_OR_RELIC"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ObfuscatedOpSpec:
    """Semantic mapping for an obfuscated ConfigAbility ``$type`` instruction."""

    raw_type: str
    semantic_opcode: str
    domain: str
    description: str


# Known obfuscated $type instructions documented in ARCHITECTURE_BLUEPRINT.md & TurnBasedGameData
KNOWN_OBFUSCATED_OPS: Dict[str, ObfuscatedOpSpec] = {
    "RPG.GameCore.JDOLDFECMPL": ObfuscatedOpSpec(
        raw_type="RPG.GameCore.JDOLDFECMPL",
        semantic_opcode="AddElationPoint",
        domain="BattleEvent",
        description="Modify team Elation / Laugh points (BattleEventAbility_2 / 30149)",
    ),
    "RPG.GameCore.GFODFDCBFJF": ObfuscatedOpSpec(
        raw_type="RPG.GameCore.GFODFDCBFJF",
        semantic_opcode="ChangeActionDelayBit",
        domain="Avatar",
        description="Action delay / advance bit-flag operation (RobinS / Avatar)",
    ),
}

# Semantic OpCode rewrites for ambiguous official task names
SEMANTIC_OPCODE_ALIASES: Dict[str, str] = {
    "RPG.GameCore.ModifySPNew": "ModifyEnergy",
    "RPG.GameCore.ModifySkillPoint": "ModifySkillPoint",
}

COMMON_RUNTIME_SYMBOLS: Tuple[str, ...] = (
    "AIFlag",
    "BattleEventTurnLeftParam",
    "SummonID01",
    "SummonID02",
    "SummonID03",
    "HyperValue",
    "Count",
    "Stack",
    "Phase",
    "CurrentPhase",
    "ElationPoint",
    "TurnCount",
    "WaveIndex",
    "IsBroken",
)


def _is_obfuscated_type_name(type_str: str) -> bool:
    if not type_str:
        return False
    short = type_str.rsplit(".", 1)[-1]
    return len(short) >= 8 and short.isupper() and short.isalpha()


@dataclass(frozen=True)
class DynamicHashRegistry:
    """Global ``int32 -> symbol`` reverse dictionary with per-domain coverage stats."""

    hash_to_symbol: Mapping[int, str]
    symbol_to_hash: Mapping[str, int]
    domain_counts: Mapping[str, int]
    collisions: Mapping[int, Tuple[str, ...]] = field(default_factory=dict)
    readinfo_labels: Mapping[int, str] = field(default_factory=dict)

    def resolve(self, hash_val: int) -> Optional[str]:
        h = int(hash_val)
        return self.hash_to_symbol.get(h) or self.readinfo_labels.get(h)

    def resolve_or_hex(self, hash_val: int) -> str:
        sym = self.resolve(hash_val)
        if sym is not None:
            return sym
        return f"hash:{int(hash_val)}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hash_to_symbol": {str(k): v for k, v in self.hash_to_symbol.items()},
            "domain_counts": dict(self.domain_counts),
            "collisions": {str(k): list(v) for k, v in self.collisions.items()},
            "readinfo_labels": {str(k): v for k, v in self.readinfo_labels.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DynamicHashRegistry":
        h2s = {int(k): str(v) for k, v in data.get("hash_to_symbol", {}).items()}
        s2h = {v: k for k, v in h2s.items()}
        dcounts = {str(k): int(v) for k, v in data.get("domain_counts", {}).items()}
        cols = {int(k): tuple(str(x) for x in v) for k, v in data.get("collisions", {}).items()}
        ri = {int(k): str(v) for k, v in data.get("readinfo_labels", {}).items()}
        return cls(
            hash_to_symbol=h2s,
            symbol_to_hash=s2h,
            domain_counts=dcounts,
            collisions=cols,
            readinfo_labels=ri,
        )


def _collect_symbols_from_json(node: Any, out: Set[str]) -> None:
    """Extract candidate DynamicKey / TriggerKey / CustomString / AbilityName symbols from JSON."""
    if isinstance(node, list):
        for item in node:
            _collect_symbols_from_json(item, out)
        return
    if not isinstance(node, Mapping):
        return

    for key in (
        "DynamicKey",
        "Key",
        "TriggerKey",
        "SkillTriggerKey",
        "PointTriggerKey",
        "SkillName",
        "AbilityName",
        "ModifierName",
        "CustomString",
        "Name",
        "AIName",
    ):
        val = node.get(key)
        if isinstance(val, str) and val:
            out.add(val)
        elif isinstance(val, Mapping):
            inner = val.get("Value") or val.get("RawString")
            if isinstance(inner, str) and inner:
                out.add(inner)

    for map_key in ("CustomValues", "OverrideProperties", "Modifiers", "GlobalModifiers"):
        m = node.get(map_key)
        if isinstance(m, Mapping):
            for k in m.keys():
                if isinstance(k, str) and k:
                    out.add(k)

    for k, v in node.items():
        if isinstance(v, (dict, list)):
            _collect_symbols_from_json(v, out)


def build_global_symbol_registry(
    tbgd_root: Path | str = DEFAULT_TBGD_ROOT,
) -> DynamicHashRegistry:
    """Scan ``TurnBasedGameData`` across all domains to build ``DynamicHashRegistry``."""
    root = Path(tbgd_root)
    domain_symbols: Dict[str, Set[str]] = {
        "Builtin": set(BUILTIN_FUNCS.keys()) | set(COMMON_RUNTIME_SYMBOLS),
        "Avatar": set(),
        "LightCone": set(),
        "Relic": set(),
        "Monster": set(),
        "Stage": set(),
        "ConfigAI": set(),
    }

    excel_root = root / "ExcelOutput"
    excel_domain_files: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
        ("Avatar", "AvatarSkillConfig.json", ("SkillTriggerKey", "SkillName")),
        ("Avatar", "AvatarServantSkillConfig.json", ("SkillTriggerKey", "SkillName")),
        ("Avatar", "AvatarSkillTreeConfig.json", ("PointTriggerKey",)),
        ("LightCone", "EquipmentSkillConfig.json", ("AbilityName",)),
        ("Relic", "RelicSetSkillConfig.json", ("AbilityName",)),
        ("Monster", "MonsterSkillConfig.json", ("SkillTriggerKey",)),
        ("Stage", "BattleEventConfig.json", ("AbilityName",)),
    )
    for dom, fname, fields in excel_domain_files:
        fpath = excel_root / fname
        if not fpath.exists():
            continue
        rows = json.loads(fpath.read_text(encoding="utf-8"))
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                for fld in fields:
                    v = row.get(fld)
                    if isinstance(v, str) and v:
                        domain_symbols[dom].add(v)
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str) and item:
                                domain_symbols[dom].add(item)

    # ConfigCharacter (Avatar / Servant / Monster)
    readinfo_labels: Dict[int, str] = {}
    char_root = root / "Config" / "ConfigCharacter"
    for sub, dom in (("Avatar", "Avatar"), ("Servant", "Avatar"), ("Monster", "Monster")):
        sub_dir = char_root / sub
        if not sub_dir.exists():
            continue
        for p in sub_dir.glob("*.json"):
            if p.name.endswith(".layout.json"):
                continue
            doc = json.loads(p.read_text(encoding="utf-8"))
            _collect_symbols_from_json(doc, domain_symbols[dom])
            floats = doc.get("DynamicValues", {}).get("Floats", {})
            if isinstance(floats, Mapping):
                for h_str, entry in floats.items():
                    if not isinstance(entry, Mapping):
                        continue
                    ri = entry.get("ReadInfo", {})
                    if not isinstance(ri, Mapping):
                        continue
                    rtype = str(ri.get("Type", "None"))
                    tkey = str(ri.get("TriggerKey", ""))
                    idx = ri.get("Index", 0)
                    if rtype != "None" and tkey:
                        try:
                            readinfo_labels.setdefault(int(h_str), f"{rtype}:{tkey}[{idx}]")
                        except ValueError:
                            pass

    # ConfigAbility
    ab_root = root / "Config" / "ConfigAbility"
    if ab_root.exists():
        for p in ab_root.rglob("*.json"):
            if p.name.endswith(".layout.json"):
                continue
            rel_parts = p.relative_to(ab_root).parts
            top = rel_parts[0] if rel_parts else ""
            if top in ("Avatar", "Servant"):
                dom = "Avatar"
            elif top in ("Equipment", "LightCone"):
                dom = "LightCone"
            elif top in ("Relic", "RelicSet"):
                dom = "Relic"
            elif top == "Monster":
                dom = "Monster"
            else:
                dom = "Stage"
            doc = json.loads(p.read_text(encoding="utf-8"))
            _collect_symbols_from_json(doc, domain_symbols[dom])

    # ConfigAI
    ai_root = root / "Config" / "ConfigAI"
    if ai_root.exists():
        for p in ai_root.rglob("*.json"):
            if p.name.endswith(".layout.json"):
                continue
            doc = json.loads(p.read_text(encoding="utf-8"))
            _collect_symbols_from_json(doc, domain_symbols["ConfigAI"])

    h2s: Dict[int, str] = {}
    s2h: Dict[str, int] = {}
    collisions: Dict[int, List[str]] = {}

    for dom, syms in domain_symbols.items():
        for sym in sorted(syms):
            h = dotnet_hash(sym)
            s2h[sym] = h
            if h in h2s and h2s[h] != sym:
                bucket = collisions.setdefault(h, [h2s[h]])
                if sym not in bucket:
                    bucket.append(sym)
            else:
                h2s[h] = sym

    return DynamicHashRegistry(
        hash_to_symbol=h2s,
        symbol_to_hash=s2h,
        domain_counts={dom: len(syms) for dom, syms in domain_symbols.items()},
        collisions={k: tuple(v) for k, v in collisions.items()},
        readinfo_labels=readinfo_labels,
    )


def compute_tbgd_fingerprint(tbgd_root: Path | str = DEFAULT_TBGD_ROOT) -> str:
    """Compute a deterministic fingerprint for ``TurnBasedGameData``."""
    root = Path(tbgd_root)
    if (root / ".git").exists():
        try:
            res = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            commit = res.stdout.strip()
            if commit:
                return f"git:{commit}:v{IR_COMPILER_VERSION}"
        except (OSError, subprocess.SubprocessError):
            pass

    hasher = hashlib.sha256()
    hasher.update(f"v{IR_COMPILER_VERSION}".encode("utf-8"))
    for rel in (
        "ExcelOutput/StageConfig.json",
        "ExcelOutput/MonsterConfig.json",
        "ExcelOutput/AvatarConfig.json",
        "ExcelOutput/EquipmentConfig.json",
        "ExcelOutput/BattleEventConfig.json",
    ):
        p = root / rel
        if p.exists():
            st = p.stat()
            hasher.update(f"{rel}:{st.st_size}:{int(st.st_mtime_ns)}".encode("utf-8"))
    return f"stat:{hasher.hexdigest()[:24]}"


@dataclass(frozen=True)
class CompiledIRTask:
    """Flattened, de-obfuscated IR instruction node."""

    index: int
    parent_index: Optional[int]
    hook: str
    raw_type: str
    opcode: str
    is_obfuscated: bool
    resolved_keys: Mapping[str, str] = field(default_factory=dict)
    expr_count: int = 0
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompiledIRAbility:
    """Compiled flat IR representation of a single ConfigAbility."""

    ability_name: str
    role: AbilityRole
    instructions: Tuple[CompiledIRTask, ...]
    referenced_symbols: Tuple[str, ...]
    obfuscated_types: Tuple[str, ...]


def infer_ability_role(ability_name: str, ability_dict: Mapping[str, Any]) -> AbilityRole:
    """Classify an ability's semantic ``AbilityRole`` from naming and structure."""
    if ability_name.startswith(("BattleEventAbility_", "StageBattleEventAbility")):
        return AbilityRole.BATTLE_EVENT
    if ability_name.startswith("Monster_"):
        return AbilityRole.MONSTER_SKILL
    if ability_name.startswith(("Equipment_", "Relic_")):
        return AbilityRole.EQUIPMENT_OR_RELIC
    if "_Insert" in ability_name or ability_name.endswith("Insert"):
        return AbilityRole.TURN_INSERT
    if ability_name.startswith("Servant_"):
        return AbilityRole.SERVANT_SKILL
    if "_Passive" in ability_name or ability_name.endswith("_Talent"):
        return AbilityRole.PASSIVE_INIT
    if ability_dict.get("OnStart") or ability_dict.get("OnAdd"):
        return AbilityRole.ACTIVE_SKILL
    return AbilityRole.UNKNOWN


class AbilityIRCompiler:
    """Compiles pruned ``ConfigAbility`` ASTs into flat ``CompiledIRAbility`` objects."""

    def __init__(
        self,
        registry: Optional[DynamicHashRegistry] = None,
        obfuscated_ops: Optional[Mapping[str, ObfuscatedOpSpec]] = None,
        tbgd_root: Path | str = DEFAULT_TBGD_ROOT,
    ) -> None:
        self.tbgd_root = Path(tbgd_root)
        self.registry = registry or build_global_symbol_registry(self.tbgd_root)
        self.obfuscated_ops = dict(KNOWN_OBFUSCATED_OPS)
        if obfuscated_ops:
            self.obfuscated_ops.update(obfuscated_ops)

    def resolve_opcode(self, raw_type: str) -> Tuple[str, bool]:
        if raw_type in self.obfuscated_ops:
            return self.obfuscated_ops[raw_type].semantic_opcode, True
        if raw_type in SEMANTIC_OPCODE_ALIASES:
            return SEMANTIC_OPCODE_ALIASES[raw_type], False
        is_obf = _is_obfuscated_type_name(raw_type)
        short = raw_type.rsplit(".", 1)[-1] if raw_type else "Unknown"
        return short, is_obf

    def _inspect_task_keys_and_exprs(
        self,
        node: Mapping[str, Any],
        resolved_keys: Dict[str, str],
        referenced_syms: Set[str],
    ) -> int:
        expr_count = 0

        def _walk(v: Any, path: str) -> None:
            nonlocal expr_count
            if isinstance(v, Mapping):
                if "PostfixExpr" in v and isinstance(v["PostfixExpr"], Mapping):
                    # Validate bytecode decoding at compile time
                    pe = CompiledPostfixExpr.from_dict(v["PostfixExpr"])
                    expr_count += 1
                    for h in pe.dynamic_hashes:
                        sym = self.registry.resolve(h)
                        if sym is not None:
                            resolved_keys[f"hash:{h}"] = sym
                            referenced_syms.add(sym)
                if "Hash" in v and isinstance(v["Hash"], int):
                    h = v["Hash"]
                    sym = self.registry.resolve(h)
                    if sym is not None:
                        resolved_keys[path or f"hash:{h}"] = sym
                        referenced_syms.add(sym)
                for k, sub in v.items():
                    if k in ("TaskList", "SuccessTaskList", "FailedTaskList", "CallbackConfig", "OnSuccess", "OnFail"):
                        continue
                    _walk(sub, f"{path}.{k}" if path else k)
            elif isinstance(v, list):
                for idx, item in enumerate(v):
                    _walk(item, f"{path}[{idx}]")

        _walk(node, "")
        return expr_count

    def compile_ability(
        self,
        ability_name: str,
        ability_dict: Mapping[str, Any],
        *,
        prune_presentation: bool = True,
    ) -> CompiledIRAbility:
        ab = prune_ability(ability_dict) if prune_presentation else dict(ability_dict)
        role = infer_ability_role(ability_name, ab)
        instructions: List[CompiledIRTask] = []
        referenced_syms: Set[str] = set()
        obfuscated_found: Set[str] = set()

        def _flatten(tasks: Any, hook: str, parent_idx: Optional[int]) -> None:
            if not isinstance(tasks, list):
                return
            for task in tasks:
                if not isinstance(task, Mapping):
                    continue
                raw_type = str(task.get("$type", ""))
                opcode, is_obf = self.resolve_opcode(raw_type)
                if is_obf:
                    obfuscated_found.add(raw_type)

                resolved_keys: Dict[str, str] = {}
                expr_cnt = self._inspect_task_keys_and_exprs(task, resolved_keys, referenced_syms)
                idx = len(instructions)
                payload = {
                    k: v
                    for k, v in task.items()
                    if k
                    not in (
                        "$type",
                        "TaskList",
                        "SuccessTaskList",
                        "FailedTaskList",
                        "CallbackConfig",
                        "OnSuccess",
                        "OnFail",
                    )
                }
                instructions.append(
                    CompiledIRTask(
                        index=idx,
                        parent_index=parent_idx,
                        hook=hook,
                        raw_type=raw_type,
                        opcode=opcode,
                        is_obfuscated=is_obf,
                        resolved_keys=resolved_keys,
                        expr_count=expr_cnt,
                        payload=payload,
                    )
                )
                for child_key in (
                    "TaskList",
                    "SuccessTaskList",
                    "FailedTaskList",
                    "CallbackConfig",
                    "OnSuccess",
                    "OnFail",
                ):
                    if isinstance(task.get(child_key), list):
                        _flatten(task[child_key], f"{hook}.{child_key}", idx)

        _flatten(ab.get("OnStart", []), "OnStart", None)
        _flatten(ab.get("OnAdd", []), "OnAdd", None)
        for mod_name, mod in ab.get("Modifiers", {}).items():
            if not isinstance(mod, Mapping):
                continue
            for cb in mod.get("_CallbackList", []):
                if isinstance(cb, Mapping):
                    evt = str(cb.get("Event", "Callback"))
                    _flatten(cb.get("CallbackConfig", []), f"Modifier:{mod_name}:{evt}", None)

        return CompiledIRAbility(
            ability_name=ability_name,
            role=role,
            instructions=tuple(instructions),
            referenced_symbols=tuple(sorted(referenced_syms)),
            obfuscated_types=tuple(sorted(obfuscated_found)),
        )

    def scan_obfuscated_types(self, game_loader: Optional[GameDataLoader] = None) -> Dict[str, int]:
        """Scan all indexed ``ConfigAbility`` definitions for obfuscated ``$type`` nodes."""
        loader = game_loader or GameDataLoader(data_root=str(self.tbgd_root))
        loader.ensure_ability_index()
        counts: Dict[str, int] = {}

        def _walk(obj: Any) -> None:
            if isinstance(obj, list):
                for item in obj:
                    _walk(item)
            elif isinstance(obj, Mapping):
                t = obj.get("$type")
                if isinstance(t, str) and _is_obfuscated_type_name(t):
                    counts[t] = counts.get(t, 0) + 1
                for v in obj.values():
                    _walk(v)

        for ab in loader._ability_by_name.values():
            _walk(ab)
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


@dataclass(frozen=True)
class IRCacheBundle:
    """Fingerprint-validated cache bundle of symbol registry & compiled IR abilities."""

    fingerprint: str
    registry: DynamicHashRegistry
    obfuscated_counts: Mapping[str, int]
    abilities: Mapping[str, CompiledIRAbility]

    def save_to_dir(self, cache_dir: Path | str) -> Path:
        cdir = Path(cache_dir)
        cdir.mkdir(parents=True, exist_ok=True)
        out_path = cdir / "ir_cache.json"
        payload = {
            "fingerprint": self.fingerprint,
            "registry": self.registry.to_dict(),
            "obfuscated_counts": dict(self.obfuscated_counts),
            "abilities": {
                name: {
                    "ability_name": ir.ability_name,
                    "role": ir.role.value,
                    "instructions": [asdict(inst) for inst in ir.instructions],
                    "referenced_symbols": list(ir.referenced_symbols),
                    "obfuscated_types": list(ir.obfuscated_types),
                }
                for name, ir in self.abilities.items()
            },
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return out_path

    @classmethod
    def load_from_dir(
        cls,
        cache_dir: Path | str,
        *,
        expected_fingerprint: str,
    ) -> Optional["IRCacheBundle"]:
        cache_file = Path(cache_dir) / "ir_cache.json"
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("fingerprint") != expected_fingerprint:
            return None
        reg = DynamicHashRegistry.from_dict(data["registry"])
        abilities: Dict[str, CompiledIRAbility] = {}
        for name, raw_ir in data.get("abilities", {}).items():
            insts = tuple(CompiledIRTask(**inst) for inst in raw_ir.get("instructions", []))
            abilities[name] = CompiledIRAbility(
                ability_name=raw_ir["ability_name"],
                role=AbilityRole(raw_ir["role"]),
                instructions=insts,
                referenced_symbols=tuple(raw_ir.get("referenced_symbols", ())),
                obfuscated_types=tuple(raw_ir.get("obfuscated_types", ())),
            )
        return cls(
            fingerprint=data["fingerprint"],
            registry=reg,
            obfuscated_counts=dict(data.get("obfuscated_counts", {})),
            abilities=abilities,
        )


def build_or_load_ir_cache(
    *,
    tbgd_root: Path | str = DEFAULT_TBGD_ROOT,
    cache_dir: Optional[Path | str] = None,
    ability_names: Optional[Sequence[str]] = None,
) -> Tuple[IRCacheBundle, bool]:
    """Build or load a fingerprint-validated ``IRCacheBundle`` (returns ``(bundle, cache_hit)``)."""
    fp = compute_tbgd_fingerprint(tbgd_root)
    if cache_dir is not None:
        cached = IRCacheBundle.load_from_dir(cache_dir, expected_fingerprint=fp)
        if cached is not None:
            return cached, True

    reg = build_global_symbol_registry(tbgd_root)
    compiler = AbilityIRCompiler(registry=reg, tbgd_root=tbgd_root)
    loader = GameDataLoader(data_root=str(tbgd_root))
    loader.ensure_ability_index()

    target_names = list(ability_names) if ability_names is not None else sorted(loader._ability_by_name.keys())
    compiled: Dict[str, CompiledIRAbility] = {}
    for name in target_names:
        ab = loader.get_ability(name)
        if ab is not None:
            compiled[name] = compiler.compile_ability(name, ab)

    obf_counts = compiler.scan_obfuscated_types(loader)
    bundle = IRCacheBundle(
        fingerprint=fp,
        registry=reg,
        obfuscated_counts=obf_counts,
        abilities=compiled,
    )
    if cache_dir is not None:
        bundle.save_to_dir(cache_dir)
    return bundle, False

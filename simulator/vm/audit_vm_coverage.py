"""Static coverage auditor for official TurnBasedGameData ConfigAbility vs VMExecutor.

Scans ``data/TurnBasedGameData/Config/ConfigAbility/`` across:
1. ``BattleEvent`` (``BattleEvent/*.json``, ``BattleEventAbility*.json``, ``StageBattleEventAbility.json``)
2. ``Monster`` (``Monster/*.json``)
3. 5-Star Avatars (resolved from ``ExcelOutput/AvatarConfig.json`` ``CombatPowerAvatarRarityType5``)
4. 5-Star Light Cones (resolved from ``ExcelOutput/EquipmentConfig.json`` ``CombatPowerLightconeRarity5``)
5. Relic Sets (resolved from ``ExcelOutput/RelicSetSkillConfig.json``)

Compares all discovered ``$type`` Task/Predicate nodes and ``PostfixExpr`` opcodes/builtin
functions against:
- Registered handlers in ``simulator/vm/executor.py`` (parsed statically via ``ast``)
- Prunable presentation nodes in ``simulator/vm/loader.py`` (``PRUNABLE_PRESENTATION_TYPES``)
- Supported bytecode opcodes & ``BUILTIN_FUNC_HASHES`` in ``simulator/vm/expr.py``

Read-only tool: never modifies any existing simulator or game data files.
"""

from __future__ import annotations

import ast
import base64
from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from simulator.vm.expr import BUILTIN_FUNC_HASHES
from simulator.vm.ir_compiler import KNOWN_OBFUSCATED_OPS
from simulator.vm.loader import DEFAULT_TBGD_ROOT, GameDataLoader, PRUNABLE_PRESENTATION_TYPES
from simulator.vm.stage_prunable_types import (
    ALL_SAFE_PRUNABLE_TYPES,
    STAGE_MECHANICAL_PREDICATE_TYPES,
    STAGE_MECHANICAL_TASK_TYPES,
)

MODERN_OPCODES: Set[int] = {0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 16, 17}
LEGACY_OPCODES: Set[int] = {0, 1, 2, 3, 4, 5, 7, 9, 10}

# Non-executable data/value $type names that appear as nested property structs rather than
# Task or Predicate instructions in ConfigAbility JSONs.
STRUCTURAL_DATA_TYPES: Set[str] = {
    "RPG.GameCore.AttackData",
    "RPG.GameCore.TargetAlias",
    "RPG.GameCore.TargetSequence",
    "RPG.GameCore.TargetConcat",
    "RPG.GameCore.TargetFilter",
    "RPG.GameCore.TargetShuffle",
    "RPG.GameCore.TargetSortByProperty",
    "RPG.GameCore.TargetSortByFormation",
    "RPG.GameCore.TargetTake",
    "RPG.GameCore.TargetRandom",
    "RPG.GameCore.TargetIndex",
    "RPG.GameCore.TargetProperty",
    "RPG.GameCore.LinearProjectileData",
    "RPG.GameCore.HalfBoomerangProjectileData",
    "RPG.GameCore.TurnInsertAbilityCondition",
    "RPG.GameCore.MonsterEnergyBarTutorialConfig",
}


def extract_executor_supported_types(executor_path: Path) -> Tuple[Set[str], Set[str]]:
    """Statically parse ``simulator/vm/executor.py`` and ``simulator/vm/ops/*.py`` via AST to extract supported Task & Predicate ``$type`` strings."""
    supported_predicates: Set[str] = set()
    supported_tasks: Set[str] = set()

    def _collect_strings_from_method(func_node: ast.FunctionDef, out: Set[str]) -> None:
        for node in ast.walk(func_node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val.startswith("RPG.GameCore.") or (
                    len(val) >= 8 and val.isupper() and val.isalpha()
                ):
                    out.add(val)

    scan_paths: List[Path] = [executor_path]
    ops_dir = executor_path.parent / "ops"
    if ops_dir.is_dir():
        scan_paths.extend(sorted(ops_dir.glob("*.py")))

    target_classes = {"TaskExecutor", "PredicateOpsMixin", "CombatOpsMixin", "TurnOpsMixin"}
    task_methods = {"execute_task", "_dispatch_combat_op", "_dispatch_turn_op"}

    for path in scan_paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in target_classes:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        if item.name == "_eval_predicate_raw":
                            _collect_strings_from_method(item, supported_predicates)
                        elif item.name in task_methods:
                            _collect_strings_from_method(item, supported_tasks)

    return supported_tasks, supported_predicates


def _walk_config_ability(
    obj: Any,
    *,
    task_counts: Counter[str],
    predicate_counts: Counter[str],
    expr_opcode_counts: Counter[Tuple[str, int]],
    unknown_func_hashes: Counter[int],
    in_predicate: bool = False,
) -> None:
    """Recursively inspect Tasks, Predicates, and PostfixExprs in a ConfigAbility JSON subtree."""
    if isinstance(obj, list):
        for item in obj:
            _walk_config_ability(
                item,
                task_counts=task_counts,
                predicate_counts=predicate_counts,
                expr_opcode_counts=expr_opcode_counts,
                unknown_func_hashes=unknown_func_hashes,
                in_predicate=in_predicate,
            )
        return
    if not isinstance(obj, Mapping):
        return

    # Inspect PostfixExpr bytecode if present
    if "PostfixExpr" in obj and isinstance(obj["PostfixExpr"], Mapping):
        pe = obj["PostfixExpr"]
        raw_b64 = pe.get("OpCodes", "")
        if raw_b64:
            ops = tuple(base64.b64decode(raw_b64))
            is_legacy = bool(ops and ops[-1] == 10)
            mode = "legacy" if is_legacy else "modern"
            hashes = tuple(int(h) for h in pe.get("DynamicHashes", ()))
            i = 0
            n = len(ops)
            stack_refs: List[Optional[int]] = []
            while i < n:
                op = ops[i]
                expr_opcode_counts[(mode, op)] += 1
                if op == 0:
                    stack_refs.append(None)
                    i += 2
                elif op == 1:
                    idx = ops[i + 1] if i + 1 < n else -1
                    stack_refs.append(hashes[idx] if 0 <= idx < len(hashes) else None)
                    i += 2
                elif (is_legacy and op == 9) or (not is_legacy and op == 16):
                    argc = ops[i + 1] if i + 1 < n else 0
                    for _ in range(argc):
                        if stack_refs:
                            stack_refs.pop()
                    fn_h = stack_refs.pop() if stack_refs else None
                    if fn_h is not None and fn_h not in BUILTIN_FUNC_HASHES:
                        unknown_func_hashes[fn_h] += 1
                    stack_refs.append(None)
                    i += 2
                elif (is_legacy and op == 7) or (not is_legacy and op == 14):
                    if stack_refs:
                        stack_refs[-1] = None
                    i += 1
                elif not is_legacy and op == 13:
                    for _ in range(min(3, len(stack_refs))):
                        stack_refs.pop()
                    stack_refs.append(None)
                    i += 1
                elif (is_legacy and op == 10) or (not is_legacy and op == 17):
                    i += 1
                else:
                    if len(stack_refs) >= 2:
                        stack_refs.pop()
                        stack_refs[-1] = None
                    i += 1

    node_type = obj.get("$type")
    if isinstance(node_type, str) and node_type and node_type not in STRUCTURAL_DATA_TYPES:
        if in_predicate or node_type.startswith("RPG.GameCore.By"):
            predicate_counts[node_type] += 1
        else:
            task_counts[node_type] += 1

    for key, val in obj.items():
        if key == "$type":
            continue
        if key in ("Predicate", "PredicateList"):
            _walk_config_ability(
                val,
                task_counts=task_counts,
                predicate_counts=predicate_counts,
                expr_opcode_counts=expr_opcode_counts,
                unknown_func_hashes=unknown_func_hashes,
                in_predicate=True,
            )
        else:
            _walk_config_ability(
                val,
                task_counts=task_counts,
                predicate_counts=predicate_counts,
                expr_opcode_counts=expr_opcode_counts,
                unknown_func_hashes=unknown_func_hashes,
                in_predicate=False,
            )


@dataclass(frozen=True)
class DomainCoverageStats:
    """Coverage summary for a single ConfigAbility domain (e.g. BattleEvent, Monster)."""

    domain: str
    files_scanned: int
    abilities_scanned: int
    task_total_occurrences: int
    task_supported_occurrences: int
    task_pruned_occurrences: int
    task_missing_occurrences: int
    unique_tasks_total: int
    unique_tasks_supported: int
    unique_tasks_pruned: int
    missing_tasks: Mapping[str, int]
    predicate_total_occurrences: int
    predicate_supported_occurrences: int
    predicate_missing_occurrences: int
    unique_predicates_total: int
    unique_predicates_supported: int
    missing_predicates: Mapping[str, int]
    unsupported_opcodes: Mapping[Tuple[str, int], int]
    unknown_expr_func_hashes: Mapping[int, int]

    @property
    def task_occurrence_coverage(self) -> float:
        if self.task_total_occurrences == 0:
            return 1.0
        return (
            self.task_supported_occurrences + self.task_pruned_occurrences
        ) / self.task_total_occurrences

    @property
    def predicate_occurrence_coverage(self) -> float:
        if self.predicate_total_occurrences == 0:
            return 1.0
        return self.predicate_supported_occurrences / self.predicate_total_occurrences


@dataclass(frozen=True)
class CoverageAuditReport:
    """Aggregated VM instruction coverage audit across all target domains."""

    tbgd_root: str
    executor_path: str
    supported_task_types: Tuple[str, ...]
    supported_predicate_types: Tuple[str, ...]
    prunable_types_count: int
    domains: Mapping[str, DomainCoverageStats]

    def to_markdown(self, top_n: int = 25) -> str:
        """Render a concise Markdown summary highlighting missing tasks & predicates."""
        lines: List[str] = [
            "# VM ConfigAbility 静态覆盖率审计报告",
            "",
            f"- 已注册 Task 节点数: `{len(self.supported_task_types)}` | "
            f"已注册 Predicate 节点数: `{len(self.supported_predicate_types)}` | "
            f"可裁剪表现节点数: `{self.prunable_types_count}`",
            "",
            "| 领域 | 扫描文件/Ability | Task 实例覆盖率 | Task 唯一类型 (已支持+可裁剪/总数) | Predicate 实例覆盖率 | 缺失 Predicate 类型数 | 未支持 OpCode |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for dom_name, st in self.domains.items():
            covered_unique = st.unique_tasks_supported + st.unique_tasks_pruned
            lines.append(
                f"| {dom_name} | {st.files_scanned}/{st.abilities_scanned} | "
                f"{st.task_occurrence_coverage:.1%} | {covered_unique}/{st.unique_tasks_total} | "
                f"{st.predicate_occurrence_coverage:.1%} | {len(st.missing_predicates)} | "
                f"{len(st.unsupported_opcodes)} |"
            )

        for dom_name in ("BattleEvent", "Monster"):
            if dom_name not in self.domains:
                continue
            st = self.domains[dom_name]
            lines.extend(["", f"## {dom_name} 高频缺失清单 (Top {top_n})"])
            if st.missing_tasks:
                lines.append("### 缺失 Task `$type`")
                for k, cnt in list(st.missing_tasks.items())[:top_n]:
                    lines.append(f"- `{k}`: {cnt}")
            if st.missing_predicates:
                lines.append("### 缺失 Predicate `$type`")
                for k, cnt in list(st.missing_predicates.items())[:top_n]:
                    lines.append(f"- `{k}`: {cnt}")
            if st.unsupported_opcodes:
                lines.append("### 未知 PostfixExpr OpCode")
                for (mode, op), cnt in st.unsupported_opcodes.items():
                    lines.append(f"- `{mode} opcode={op}`: {cnt}")
            if st.unknown_expr_func_hashes:
                lines.append("### 未知 PostfixExpr Call Hash")
                for h, cnt in st.unknown_expr_func_hashes.items():
                    lines.append(f"- `{h}`: {cnt}")

        return "\n".join(lines)


class VMCoverageAuditor:
    """Static coverage auditor comparing TurnBasedGameData ConfigAbility against VMExecutor."""

    def __init__(
        self,
        tbgd_root: Path | str = DEFAULT_TBGD_ROOT,
        executor_path: Optional[Path | str] = None,
    ) -> None:
        self.tbgd_root = Path(tbgd_root)
        self.executor_path = (
            Path(executor_path)
            if executor_path is not None
            else Path(__file__).resolve().with_name("executor.py")
        )
        self.supported_tasks, self.supported_predicates = extract_executor_supported_types(
            self.executor_path
        )
        # Include Phase 3 StageRunner / StageAI / IRCompiler / StagePrunableTypes coverage
        self.supported_tasks |= set(STAGE_MECHANICAL_TASK_TYPES) | set(KNOWN_OBFUSCATED_OPS.keys()) | {
            "RPG.GameCore.UseSkill",
            "RPG.GameCore.SelectAISkillTarget",
            "RPG.GameCore.AIStepperDecisionGroupConfig",
        }
        self.supported_predicates |= set(STAGE_MECHANICAL_PREDICATE_TYPES)
        self.prunable_types: Set[str] = set(PRUNABLE_PRESENTATION_TYPES) | set(ALL_SAFE_PRUNABLE_TYPES)

    def _audit_ability_docs(
        self,
        domain: str,
        docs: Sequence[Tuple[Path, Mapping[str, Any]]],
    ) -> DomainCoverageStats:
        task_counts: Counter[str] = Counter()
        predicate_counts: Counter[str] = Counter()
        expr_opcode_counts: Counter[Tuple[str, int]] = Counter()
        unknown_func_hashes: Counter[int] = Counter()
        abilities_scanned = 0
        files_seen: Set[Path] = set()

        for path, doc in docs:
            files_seen.add(path)
            abilities_scanned += len(doc.get("AbilityList", [])) + len(doc.get("GlobalModifiers", {}))
            _walk_config_ability(
                doc,
                task_counts=task_counts,
                predicate_counts=predicate_counts,
                expr_opcode_counts=expr_opcode_counts,
                unknown_func_hashes=unknown_func_hashes,
            )

        task_total = sum(task_counts.values())
        task_supported = 0
        task_pruned = 0
        task_missing = 0
        unique_supported = 0
        unique_pruned = 0
        missing_tasks: Dict[str, int] = {}

        for ttype, cnt in task_counts.most_common():
            if ttype in self.supported_tasks:
                task_supported += cnt
                unique_supported += 1
            elif ttype in self.prunable_types or ttype.endswith("ClientOnly"):
                task_pruned += cnt
                unique_pruned += 1
            else:
                task_missing += cnt
                missing_tasks[ttype] = cnt

        pred_total = sum(predicate_counts.values())
        pred_supported = 0
        pred_missing = 0
        unique_pred_supported = 0
        missing_preds: Dict[str, int] = {}

        for ptype, cnt in predicate_counts.most_common():
            if ptype in self.supported_predicates:
                pred_supported += cnt
                unique_pred_supported += 1
            else:
                pred_missing += cnt
                missing_preds[ptype] = cnt

        unsupported_opcodes: Dict[Tuple[str, int], int] = {}
        for (mode, op), cnt in expr_opcode_counts.items():
            allowed = LEGACY_OPCODES if mode == "legacy" else MODERN_OPCODES
            if op not in allowed:
                unsupported_opcodes[(mode, op)] = cnt

        return DomainCoverageStats(
            domain=domain,
            files_scanned=len(files_seen),
            abilities_scanned=abilities_scanned,
            task_total_occurrences=task_total,
            task_supported_occurrences=task_supported,
            task_pruned_occurrences=task_pruned,
            task_missing_occurrences=task_missing,
            unique_tasks_total=len(task_counts),
            unique_tasks_supported=unique_supported,
            unique_tasks_pruned=unique_pruned,
            missing_tasks=missing_tasks,
            predicate_total_occurrences=pred_total,
            predicate_supported_occurrences=pred_supported,
            predicate_missing_occurrences=pred_missing,
            unique_predicates_total=len(predicate_counts),
            unique_predicates_supported=unique_pred_supported,
            missing_predicates=missing_preds,
            unsupported_opcodes=unsupported_opcodes,
            unknown_expr_func_hashes=dict(unknown_func_hashes.most_common()),
        )

    def _load_json_files(self, paths: Iterable[Path]) -> List[Tuple[Path, Mapping[str, Any]]]:
        docs: List[Tuple[Path, Mapping[str, Any]]] = []
        for p in sorted(set(paths)):
            if not p.exists() or p.name.endswith(".layout.json"):
                continue
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, Mapping):
                docs.append((p, data))
        return docs

    def audit_all(self) -> CoverageAuditReport:
        """Run static coverage audit across BattleEvent, Monster, 5-Star Avatar, 5-Star LC, and Relic."""
        ab_root = self.tbgd_root / "Config" / "ConfigAbility"
        excel_root = self.tbgd_root / "ExcelOutput"

        # 1. BattleEvent
        be_files = list((ab_root / "BattleEvent").glob("*.json")) if (ab_root / "BattleEvent").exists() else []
        be_files.extend(ab_root.glob("BattleEventAbility*.json"))
        if (ab_root / "StageBattleEventAbility.json").exists():
            be_files.append(ab_root / "StageBattleEventAbility.json")
        be_stats = self._audit_ability_docs("BattleEvent", self._load_json_files(be_files))

        # 2. Monster
        monster_files = list((ab_root / "Monster").glob("*.json")) if (ab_root / "Monster").exists() else []
        monster_stats = self._audit_ability_docs("Monster", self._load_json_files(monster_files))

        # Index all ConfigAbility files once via GameDataLoader for 5-star Avatars, LCs, and Relics
        g_loader = GameDataLoader(data_root=str(self.tbgd_root))
        g_loader.ensure_ability_index()

        # 3. 5-Star Avatars (and their associated Servants)
        avatar_cfg = json.loads((excel_root / "AvatarConfig.json").read_text(encoding="utf-8"))
        five_star_avatar_ids = {
            int(r["AvatarID"])
            for r in avatar_cfg
            if r.get("Rarity") == "CombatPowerAvatarRarityType5"
        }
        avatar_ab_names: Set[str] = set()
        for r in avatar_cfg:
            aid = int(r["AvatarID"])
            if aid not in five_star_avatar_ids:
                continue
            jpath = r.get("JsonPath", "")
            if jpath and (self.tbgd_root / jpath).exists():
                char_cfg = json.loads((self.tbgd_root / jpath).read_text(encoding="utf-8"))
                avatar_ab_names.update(str(a) for a in char_cfg.get("AbilityList", []) if a)
                for sa in char_cfg.get("SkillAbilityList", []):
                    avatar_ab_names.update(str(a) for a in sa.get("AbilityList", []) if a)
        # Also include servant abilities for 5-star remembrance avatars
        servant_cfg_path = excel_root / "AvatarServantConfig.json"
        if servant_cfg_path.exists():
            for sr in json.loads(servant_cfg_path.read_text(encoding="utf-8")):
                sid = int(sr["ServantID"])
                if (sid - 10000) in five_star_avatar_ids:
                    spath = sr.get("Config", "")
                    if spath and (self.tbgd_root / spath).exists():
                        scfg = json.loads((self.tbgd_root / spath).read_text(encoding="utf-8"))
                        avatar_ab_names.update(str(a) for a in scfg.get("AbilityList", []) if a)
                        for sa in scfg.get("SkillAbilityList", []):
                            avatar_ab_names.update(str(a) for a in sa.get("AbilityList", []) if a)

        avatar_docs = [
            (Path(f"AvatarAbility:{name}"), g_loader._ability_by_name[name])
            for name in sorted(avatar_ab_names)
            if name in g_loader._ability_by_name
        ]
        avatar_stats = self._audit_ability_docs("5StarAvatar", avatar_docs)

        # 4. 5-Star Light Cones
        equip_cfg = json.loads((excel_root / "EquipmentConfig.json").read_text(encoding="utf-8"))
        equip_skill_cfg = json.loads((excel_root / "EquipmentSkillConfig.json").read_text(encoding="utf-8"))
        five_star_skill_ids = {
            int(r["SkillID"])
            for r in equip_cfg
            if r.get("Rarity") == "CombatPowerLightconeRarity5" and "SkillID" in r
        }
        lc_ab_names = {
            str(r["AbilityName"])
            for r in equip_skill_cfg
            if int(r.get("SkillID", 0)) in five_star_skill_ids and r.get("AbilityName")
        }
        lc_docs = [
            (Path(f"EquipAbility:{name}"), g_loader._ability_by_name[name])
            for name in sorted(lc_ab_names)
            if name in g_loader._ability_by_name
        ]
        lc_stats = self._audit_ability_docs("5StarLightCone", lc_docs)

        # 5. Relic Sets
        relic_skill_cfg = json.loads((excel_root / "RelicSetSkillConfig.json").read_text(encoding="utf-8"))
        relic_ab_names = {
            str(r["AbilityName"]) for r in relic_skill_cfg if r.get("AbilityName")
        }
        relic_docs = [
            (Path(f"RelicAbility:{name}"), g_loader._ability_by_name[name])
            for name in sorted(relic_ab_names)
            if name in g_loader._ability_by_name
        ]
        relic_stats = self._audit_ability_docs("RelicSet", relic_docs)

        return CoverageAuditReport(
            tbgd_root=str(self.tbgd_root),
            executor_path=str(self.executor_path),
            supported_task_types=tuple(sorted(self.supported_tasks)),
            supported_predicate_types=tuple(sorted(self.supported_predicates)),
            prunable_types_count=len(self.prunable_types),
            domains={
                "BattleEvent": be_stats,
                "Monster": monster_stats,
                "5StarAvatar": avatar_stats,
                "5StarLightCone": lc_stats,
                "RelicSet": relic_stats,
            },
        )


def main() -> None:
    report = VMCoverageAuditor().audit_all()
    print(report.to_markdown())


if __name__ == "__main__":
    main()

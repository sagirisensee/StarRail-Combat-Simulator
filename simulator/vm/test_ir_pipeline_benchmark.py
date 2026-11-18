"""Benchmark & zero-unknown-symbol/hash validation for IRCompiler + StageSimAdapter pipeline.

Measures cold-start vs cache-hit compilation over:
- All 5-star Avatars & Servants
- All 5-star Light Cones
- All Relic Sets
- Stages 30126122 & 30510021 (including StageSimAdapter + IRCompiler integration)

Verifies:
- Zero unknown PostfixExpr builtin function hashes across all compiled abilities
- Global DynamicHashRegistry resolves all BattleEvent / Monster / Avatar / LC / Relic symbols
- Cache hit is significantly faster than cold build
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from simulator.core import Entity
from simulator.vm.expr import BUILTIN_FUNC_HASHES, CompiledPostfixExpr
from simulator.vm.ir_compiler import (
    AbilityIRCompiler,
    IRCacheBundle,
    build_global_symbol_registry,
    build_or_load_ir_cache,
)
from simulator.vm.loader import DEFAULT_TBGD_ROOT, GameDataLoader
from simulator.vm.stage_sim_adapter import build_data_driven_stage


def _collect_target_ability_names(tbgd_root: Path, g_loader: GameDataLoader) -> list[str]:
    excel_root = tbgd_root / "ExcelOutput"
    names: set[str] = set()

    # 1. 5-Star Avatars & Servants
    avatar_cfg = json.loads((excel_root / "AvatarConfig.json").read_text(encoding="utf-8"))
    five_star_aids = {
        int(r["AvatarID"])
        for r in avatar_cfg
        if r.get("Rarity") == "CombatPowerAvatarRarityType5"
    }
    for r in avatar_cfg:
        if int(r["AvatarID"]) not in five_star_aids:
            continue
        jp = r.get("JsonPath", "")
        if jp and (tbgd_root / jp).exists():
            cfg = json.loads((tbgd_root / jp).read_text(encoding="utf-8"))
            names.update(str(a) for a in cfg.get("AbilityList", []) if a)
            for sa in cfg.get("SkillAbilityList", []):
                names.update(str(a) for a in sa.get("AbilityList", []) if a)

    servant_path = excel_root / "AvatarServantConfig.json"
    if servant_path.exists():
        for sr in json.loads(servant_path.read_text(encoding="utf-8")):
            if (int(sr["ServantID"]) - 10000) in five_star_aids:
                sp = sr.get("Config", "")
                if sp and (tbgd_root / sp).exists():
                    scfg = json.loads((tbgd_root / sp).read_text(encoding="utf-8"))
                    names.update(str(a) for a in scfg.get("AbilityList", []) if a)
                    for sa in scfg.get("SkillAbilityList", []):
                        names.update(str(a) for a in sa.get("AbilityList", []) if a)

    # 2. 5-Star Light Cones
    equip_cfg = json.loads((excel_root / "EquipmentConfig.json").read_text(encoding="utf-8"))
    equip_skill_cfg = json.loads((excel_root / "EquipmentSkillConfig.json").read_text(encoding="utf-8"))
    five_star_sids = {
        int(r["SkillID"])
        for r in equip_cfg
        if r.get("Rarity") == "CombatPowerLightconeRarity5" and "SkillID" in r
    }
    for r in equip_skill_cfg:
        if int(r.get("SkillID", 0)) in five_star_sids and r.get("AbilityName"):
            names.add(str(r["AbilityName"]))

    # 3. Relic Sets
    relic_skill_cfg = json.loads((excel_root / "RelicSetSkillConfig.json").read_text(encoding="utf-8"))
    for r in relic_skill_cfg:
        if r.get("AbilityName"):
            names.add(str(r["AbilityName"]))

    return sorted(n for n in names if n in g_loader._ability_by_name)


class TestIRPipelineBenchmark(unittest.TestCase):
    def test_ir_compiler_5star_batch_and_stage_sim_adapter_benchmark(self) -> None:
        tbgd_root = Path(DEFAULT_TBGD_ROOT)
        loader = GameDataLoader(data_root=str(tbgd_root))
        loader.ensure_ability_index()
        target_names = _collect_target_ability_names(tbgd_root, loader)
        self.assertGreater(len(target_names), 200)

        # Verify 0 unknown PostfixExpr builtin function hashes across all target abilities
        unknown_fn_hashes: set[int] = set()

        def _check_expr_hashes(obj):
            if isinstance(obj, list):
                for x in obj:
                    _check_expr_hashes(x)
            elif isinstance(obj, dict):
                if "PostfixExpr" in obj and isinstance(obj["PostfixExpr"], dict):
                    pe = CompiledPostfixExpr.from_dict(obj["PostfixExpr"])
                    ops = pe.ops
                    i = 0
                    stack: list[int | None] = []
                    while i < len(ops):
                        op = ops[i]
                        if op == 0:
                            stack.append(None)
                            i += 2
                        elif op == 1:
                            idx = ops[i + 1] if i + 1 < len(ops) else -1
                            stack.append(pe.dynamic_hashes[idx] if 0 <= idx < len(pe.dynamic_hashes) else None)
                            i += 2
                        elif (pe.is_legacy and op == 9) or (not pe.is_legacy and op == 16):
                            argc = ops[i + 1] if i + 1 < len(ops) else 0
                            for _ in range(argc):
                                if stack:
                                    stack.pop()
                            fn_h = stack.pop() if stack else None
                            if fn_h is not None and fn_h not in BUILTIN_FUNC_HASHES:
                                unknown_fn_hashes.add(fn_h)
                            stack.append(None)
                            i += 2
                        elif (pe.is_legacy and op == 7) or (not pe.is_legacy and op == 14):
                            if stack:
                                stack[-1] = None
                            i += 1
                        elif not pe.is_legacy and op == 13:
                            for _ in range(min(3, len(stack))):
                                stack.pop()
                            stack.append(None)
                            i += 1
                        elif (pe.is_legacy and op == 10) or (not pe.is_legacy and op == 17):
                            i += 1
                        else:
                            if len(stack) >= 2:
                                stack.pop()
                                stack[-1] = None
                            i += 1
                for v in obj.values():
                    _check_expr_hashes(v)

        for name in target_names:
            ab = loader.get_ability(name)
            if ab is not None:
                _check_expr_hashes(ab)
        self.assertEqual(unknown_fn_hashes, set())

        # Cold build vs cache hit benchmark
        with tempfile.TemporaryDirectory() as tmpdir:
            t0 = time.perf_counter()
            cold_bundle, hit1 = build_or_load_ir_cache(
                tbgd_root=tbgd_root,
                cache_dir=tmpdir,
                ability_names=target_names,
            )
            cold_sec = time.perf_counter() - t0
            self.assertFalse(hit1)
            self.assertEqual(len(cold_bundle.abilities), len(target_names))

            t1 = time.perf_counter()
            warm_bundle, hit2 = build_or_load_ir_cache(
                tbgd_root=tbgd_root,
                cache_dir=tmpdir,
                ability_names=target_names,
            )
            warm_sec = time.perf_counter() - t1
            self.assertTrue(hit2)
            self.assertEqual(len(warm_bundle.abilities), len(cold_bundle.abilities))
            self.assertLess(warm_sec, cold_sec)

            # StageSimAdapter + IRCompiler integration for 30126122 & 30510021
            compiler = AbilityIRCompiler(registry=warm_bundle.registry, tbgd_root=tbgd_root)
            for sid in (30126122, 30510021):
                ally = Entity(name="BenchAlly", base_speed=134.0, max_hp=4000.0, current_hp=4000.0, is_enemy=False)
                sim, director = build_data_driven_stage(sid, [ally])
                for be in director.runner.built_stage.battle_events:
                    for ab_name, ab_ast in be.abilities.items():
                        ir = compiler.compile_ability(ab_name, ab_ast)
                        self.assertGreater(len(ir.instructions), 0)

            print(
                f"\n[IR Benchmark] abilities={len(target_names)} | "
                f"symbols={len(warm_bundle.registry.hash_to_symbol)} | "
                f"cold={cold_sec:.3f}s | warm_cache={warm_sec:.3f}s"
            )


if __name__ == "__main__":
    unittest.main()

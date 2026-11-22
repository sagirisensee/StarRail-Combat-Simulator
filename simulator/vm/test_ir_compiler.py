"""Unit tests for ``simulator.vm.ir_compiler``."""

from __future__ import annotations

import tempfile
import unittest

import pytest

from simulator.vm.expr import dotnet_hash
from simulator.vm.ir_compiler import (
    AbilityIRCompiler,
    AbilityRole,
    KNOWN_OBFUSCATED_OPS,
    build_global_symbol_registry,
    build_or_load_ir_cache,
    compute_tbgd_fingerprint,
)
from simulator.vm.loader import GameDataLoader


class TestIRCompiler(unittest.TestCase):
    @pytest.mark.slow
    def test_global_symbol_registry_and_obfuscated_ops(self) -> None:
        reg = build_global_symbol_registry()
        for dom in ("Builtin", "Avatar", "LightCone", "Relic", "Monster", "Stage", "ConfigAI"):
            self.assertGreater(reg.domain_counts.get(dom, 0), 0, f"Empty domain {dom}")

        # Verify critical runtime & official symbols reverse-resolve cleanly
        for sym in ("AIFlag", "BattleEventTurnLeftParam", "SummonID01", "min", "clamp01"):
            self.assertEqual(reg.resolve(dotnet_hash(sym)), sym)

        self.assertIn("RPG.GameCore.JDOLDFECMPL", KNOWN_OBFUSCATED_OPS)
        self.assertEqual(
            KNOWN_OBFUSCATED_OPS["RPG.GameCore.JDOLDFECMPL"].semantic_opcode,
            "AddElationPoint",
        )
        self.assertEqual(
            KNOWN_OBFUSCATED_OPS["RPG.GameCore.GFODFDCBFJF"].semantic_opcode,
            "ChangeActionDelayBit",
        )

    def test_compile_ability_ir_core(self) -> None:
        loader = GameDataLoader()
        loader.ensure_ability_index()
        compiler = AbilityIRCompiler()

        be49 = loader.get_ability("BattleEventAbility_Challenge_Month_49")
        self.assertIsNotNone(be49)
        assert be49 is not None
        ir49 = compiler.compile_ability("BattleEventAbility_Challenge_Month_49", be49)
        self.assertEqual(ir49.role, AbilityRole.BATTLE_EVENT)
        self.assertGreater(len(ir49.instructions), 0)

        # Synthetic obfuscated + ModifySPNew + PostfixExpr IR compilation check
        synth_ab = {
            "OnStart": [
                {"$type": "RPG.GameCore.JDOLDFECMPL", "Value": 5},
                {"$type": "RPG.GameCore.ModifySPNew", "TargetType": {"Alias": "Caster"}},
            ]
        }
        synth_ir = compiler.compile_ability("Test_Synth", synth_ab)
        self.assertEqual(
            [inst.opcode for inst in synth_ir.instructions],
            ["AddElationPoint", "ModifyEnergy"],
        )
        self.assertTrue(synth_ir.instructions[0].is_obfuscated)
        self.assertEqual(synth_ir.obfuscated_types, ("RPG.GameCore.JDOLDFECMPL",))

    @pytest.mark.slow
    def test_compile_ability_ir_and_fingerprint_cache(self) -> None:
        # Fingerprint cache hit & miss verification
        sample_names = [
            "BattleEventAbility_Challenge_Month_49",
            "BattleEventAbility_SummonMonsterInfinite",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle1, hit1 = build_or_load_ir_cache(
                cache_dir=tmpdir,
                ability_names=sample_names,
            )
            self.assertFalse(hit1)
            self.assertEqual(bundle1.fingerprint, compute_tbgd_fingerprint())
            self.assertIn("BattleEventAbility_Challenge_Month_49", bundle1.abilities)

            bundle2, hit2 = build_or_load_ir_cache(
                cache_dir=tmpdir,
                ability_names=sample_names,
            )
            self.assertTrue(hit2)
            self.assertEqual(bundle2.fingerprint, bundle1.fingerprint)
            self.assertEqual(
                len(bundle2.abilities["BattleEventAbility_Challenge_Month_49"].instructions),
                len(bundle1.abilities["BattleEventAbility_Challenge_Month_49"].instructions),
            )


if __name__ == "__main__":
    unittest.main()

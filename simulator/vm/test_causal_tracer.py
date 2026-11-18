"""Unit tests for ``simulator.vm.state_bridge`` and ``simulator.vm.causal_tracer``."""

from __future__ import annotations

import math
import unittest

from simulator.core import Entity
from simulator.events import (
    ActionEndEvent,
    ActionExecuteEvent,
    DamageAppliedEvent,
    HealAppliedEvent,
    TurnBeginEvent,
)
from simulator.vm.causal_tracer import VMCausalTracer
from simulator.vm.expr import dotnet_hash
from simulator.vm.ir_compiler import DynamicHashRegistry
from simulator.vm.runtime import ensure_vm_runtime
from simulator.vm.stage_sim_adapter import build_data_driven_stage
from simulator.vm.state_bridge import StateBridge


class TestStateBridgeAndCausalTracer(unittest.TestCase):
    def test_state_bridge_and_causal_tracer_with_vm_and_stage(self) -> None:
        ally = Entity(
            name="TestCaster",
            base_speed=140.0,
            base_atk=2000.0,
            max_hp=4000.0,
            current_hp=4000.0,
            base_def=1000.0,
            max_energy=120.0,
            energy=60.0,
            level=80,
            is_enemy=False,
        )
        memo = Entity(
            name="TestMemo",
            base_speed=160.0,
            base_atk=1000.0,
            max_hp=2000.0,
            current_hp=2000.0,
            level=80,
            is_enemy=False,
            is_memosprite=True,
            master_name="TestCaster",
            avatar_id=11409,
        )
        sim, director = build_data_driven_stage(30126122, [ally, memo])
        rt = ensure_vm_runtime(sim)

        reg = DynamicHashRegistry(
            hash_to_symbol={
                dotnet_hash("Memoria"): "Memoria",
                dotnet_hash("HealPool"): "HealPool",
            },
            symbol_to_hash={
                "Memoria": dotnet_hash("Memoria"),
                "HealPool": dotnet_hash("HealPool"),
            },
            domain_counts={"Test": 2},
            readinfo_labels={-1569959950: "SkillTreeParam:PointB1[0]"},
        )
        self.assertEqual(reg.resolve(-1569959950), "SkillTreeParam:PointB1[0]")
        bridge = StateBridge(sim, registry=reg)
        tracer = VMCausalTracer(sim, bridge=bridge, registry=reg)

        memos = bridge.get_memosprites(master_id="TestCaster")
        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0].name, "TestMemo")
        self.assertEqual(memos[0].servant_id, 11409)

        stage_snap = bridge.get_stage_snapshot()
        self.assertIsNotNone(stage_snap)
        assert stage_snap is not None
        self.assertEqual(stage_snap.stage_id, 30126122)
        self.assertEqual(stage_snap.wave_index, 0)

        sim.event_bus.publish(
            ActionExecuteEvent(
                av=10.0,
                cycle=0,
                actor_id="TestCaster",
                actor_name="TestCaster",
                action_type="Skill",
                description="Test Skill",
                action_id=1,
            )
        )
        rt.set_dynamic_value("TestCaster", dotnet_hash("Memoria"), 4.0)
        rt.modifier_engine.add_modifier(
            owner_id="TestCaster",
            caster_id="TestCaster",
            mod_name="TestBuffMod",
            count=2,
        )
        sim.event_bus.publish(
            HealAppliedEvent(
                av=10.0,
                cycle=0,
                source_name="TestCaster",
                target_name="TestCaster",
                amount=800.0,
            )
        )
        sim.event_bus.publish(
            DamageAppliedEvent(
                av=10.0,
                cycle=0,
                attacker_name="TestCaster",
                target_name="月夜天马",
                damage=12345.0,
                is_crit=True,
                breakdown=None,
                target_hp_left=3600000.0,
                damage_tag="skill",
            )
        )
        sim.event_bus.publish(
            ActionEndEvent(
                av=10.0,
                cycle=0,
                actor_id="TestCaster",
                actor_name="TestCaster",
                action_type="Skill",
                action_id=1,
            )
        )

        self.assertTrue(math.isclose(bridge.get_resource("TestCaster", "Memoria"), 4.0))
        self.assertTrue(math.isclose(bridge.get_resource("TestCaster", "TestBuffMod"), 2.0))
        self.assertTrue(math.isclose(bridge.get_resource("TestCaster", "sp"), float(sim.sp.current_sp)))

        self.assertEqual(len(tracer.history), 1)
        snap = tracer.history[0]
        self.assertEqual(len(snap.hits), 1)
        self.assertEqual(snap.hits[0].attacker_modifiers, (("TestBuffMod", 2),))
        self.assertIsNone(snap.hits[0].breakdown)
        self.assertEqual(len(snap.heals), 1)
        self.assertTrue(math.isclose(snap.heals[0].amount, 800.0))

        # Verify Modifier-local DynamicValue tracking + Out-of-action TurnBegin window + Breakdown
        mod = rt.modifier_engine.get_modifiers("TestCaster", "TestBuffMod")[0]
        mod.dynamic_values[dotnet_hash("HealPool")] = 550.0
        sim.event_bus.publish(
            HealAppliedEvent(
                av=12.0,
                cycle=0,
                source_name="TestCaster",
                target_name="TestCaster",
                amount=300.0,
            )
        )
        sim.event_bus.publish(
            DamageAppliedEvent(
                av=12.0,
                cycle=0,
                attacker_name="TestCaster",
                target_name="月夜天马",
                damage=999.0,
                is_crit=False,
                breakdown={"crit_mult": 1.0, "vuln_mult": 1.2},
                target_hp_left=3599000.0,
                damage_tag="additional",
            )
        )
        sim.event_bus.publish(
            TurnBeginEvent(av=12.0, cycle=0, actor_id="TestCaster", actor_name="TestCaster", speed=140.0)
        )
        self.assertEqual(len(tracer.history), 2)
        ooa_snap = tracer.history[1]
        self.assertEqual(ooa_snap.action_type, "TurnBegin")
        self.assertEqual(ooa_snap.hits[0].breakdown, {"crit_mult": 1.0, "vuln_mult": 1.2})
        self.assertTrue(
            any("mod:TestBuffMod" in dt.scope and dt.symbol_name == "HealPool" for dt in ooa_snap.dynamic_transitions)
        )

        dev = tracer.trace_deviation("TestCaster", "Memoria")
        self.assertEqual(len(dev), 1)
        self.assertTrue(math.isclose(dev[0][2].delta, 4.0))

        mod_hist = tracer.trace_modifier_history("TestCaster", "TestBuffMod")
        self.assertEqual(len(mod_hist), 1)
        self.assertEqual(mod_hist[0][2].change_type, "added")
        self.assertIn("TestCaster.Memoria", tracer.format_report())


if __name__ == "__main__":
    unittest.main()

"""Unit tests for ``simulator.vm.stage_sim_adapter``."""

from __future__ import annotations

import math
import unittest

from simulator.core import Entity
from simulator.stage_30126122 import (
    APOLI_PHASE1_HP,
    APOLI_PHASE2_HP,
    GRIFFIN_HP,
    PEGASUS_HP,
)
from simulator.vm.stage_sim_adapter import (
    DataDrivenEnemyKit,
    build_data_driven_stage,
)


def _make_dummy_ally(name: str = "TestTrailblazer", speed: float = 140.0) -> Entity:
    return Entity(
        name=name,
        base_speed=speed,
        base_atk=2000.0,
        max_hp=5000.0,
        current_hp=5000.0,
        base_def=1000.0,
        level=80,
        is_enemy=False,
    )


class TestStageSimAdapter(unittest.TestCase):
    def test_stage_30126122_moc_waves_ai_turns_and_phase_transition(self) -> None:
        ally = _make_dummy_ally()
        sim, director = build_data_driven_stage(30126122, [ally])

        self.assertEqual(director.wave, 1)
        wave1_enemies = [e for e in sim.entities if e.is_enemy]
        self.assertEqual([e.name for e in wave1_enemies], ["月夜天马", "正阳狮鹫"])
        self.assertTrue(math.isclose(wave1_enemies[0].max_hp, PEGASUS_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(wave1_enemies[1].max_hp, GRIFFIN_HP, rel_tol=1e-7))
        self.assertIsInstance(wave1_enemies[0].kit, DataDrivenEnemyKit)
        self.assertIsInstance(wave1_enemies[1].kit, DataDrivenEnemyKit)

        # Run several TurnSimulator steps so Griffin / Pegasus execute data-driven AI turns
        for _ in range(4):
            sim.step()
            director.after_step()

        griffin_kit = wave1_enemies[1].kit
        assert isinstance(griffin_kit, DataDrivenEnemyKit)
        self.assertGreater(len(griffin_kit.executed_skills), 0)

        # Clear Wave 1 -> MoC wave transition spawns Wave 2 (ApoliBoss) & resets ally runway
        for e in wave1_enemies:
            e.current_hp = 0.0
        ally.distance_remaining = 3210.0
        director.after_step()

        self.assertEqual(director.wave, 2)
        self.assertTrue(math.isclose(ally.distance_remaining, 10000.0, rel_tol=1e-9))
        wave2_enemies = [e for e in sim.entities if e.is_enemy]
        self.assertEqual([e.name for e in wave2_enemies], ["堕神之血•亚婆离"])
        apoli = wave2_enemies[0]
        self.assertTrue(math.isclose(apoli.max_hp, APOLI_PHASE1_HP, rel_tol=1e-7))

        # Trigger Phase 1 -> Phase 2 via DataDrivenStageDirector & verify AI phase sync
        new_phase = director.trigger_monster_phase_transition("堕神之血•亚婆离", mode="Inc")
        self.assertEqual(new_phase, 2)
        self.assertTrue(math.isclose(apoli.max_hp, APOLI_PHASE2_HP, rel_tol=1e-7))
        assert isinstance(apoli.kit, DataDrivenEnemyKit)
        self.assertEqual(apoli.kit.ai_executor.phase, 2)

    def test_stage_30510021_infinite_waves_and_cycle_boundary(self) -> None:
        ally = _make_dummy_ally(speed=120.0)
        sim, director = build_data_driven_stage(30510021, [ally])

        self.assertEqual(director.wave, 1)
        w1 = [e for e in sim.entities if e.is_enemy]
        self.assertEqual(len(w1), 2)

        # Defeat 1 enemy in infinite Wave 1 -> after_step refills back to MaxMonsterCount=2
        w1[0].current_hp = 0.0
        director.after_step()
        living_w1 = [e for e in sim.entities if e.is_enemy and e.current_hp > 0.0]
        self.assertEqual(len(living_w1), 2)

        # Advance past first cycle boundary (AV=160 -> cycle 1) -> BattleEvent 30503 turn countdown ticks
        sim.advance_clock(160.0)
        director.after_step()
        self.assertEqual(director.runner.state.current_cycle, 1)

        # Clear all Wave 1 enemies -> advance to Wave 2 (EliteGroup 374, Apoli Lv.100)
        for e in sim.entities:
            if e.is_enemy:
                e.current_hp = 0.0
        director.after_step()
        self.assertEqual(director.wave, 2)
        w2 = [e for e in sim.entities if e.is_enemy and e.current_hp > 0.0]
        self.assertEqual(len(w2), 1)
        self.assertTrue(math.isclose(w2[0].max_hp, 6389558.5, rel_tol=1e-5))


if __name__ == "__main__":
    unittest.main()

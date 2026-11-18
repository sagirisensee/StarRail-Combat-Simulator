"""Unit tests for ``simulator.vm.stage_factory``."""

from __future__ import annotations

import math
import unittest

from simulator.stage_30126122 import (
    APOLI_BASE_SPEED,
    APOLI_PHASE1_HP,
    APOLI_PHASE2_HP,
    APOLI_TOUGHNESS,
    EAGLE_HP,
    ENEMY_LV95_BASE_ATK,
    GRIFFIN_HP,
    GRIFFIN_INITIAL_DISTANCE,
    GRIFFIN_SPEED,
    PEGASUS_HP,
    SPROUT_HP,
)
from simulator.vm.stage_factory import StageFactory


class TestStageFactory(unittest.TestCase):
    factory: StageFactory

    @classmethod
    def setUpClass(cls) -> None:
        cls.factory = StageFactory()

    def test_build_stage_30126122_entities_and_summons(self) -> None:
        built = self.factory.build_stage(30126122)
        self.assertEqual(built.stage_id, 30126122)
        self.assertEqual(built.num_waves, 2)

        # Wave 1 entities
        w1_entities = built.build_wave_entities(0)
        self.assertEqual([e.name for e in w1_entities], ["月夜天马", "正阳狮鹫"])
        pegasus, griffin = w1_entities

        self.assertTrue(pegasus.is_enemy)
        self.assertFalse(pegasus.is_boss)
        self.assertEqual(pegasus.level, 95)
        self.assertTrue(math.isclose(pegasus.max_hp, PEGASUS_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(pegasus.base_atk, ENEMY_LV95_BASE_ATK, rel_tol=1e-7))
        # Thunder normalized to Lightning in damage_res
        self.assertIn("Lightning", pegasus.damage_res)
        self.assertNotIn("Thunder", pegasus.damage_res)
        self.assertTrue(math.isclose(pegasus.damage_res["Lightning"], 0.2, abs_tol=1e-9))

        self.assertFalse(griffin.is_boss)  # Rank="Elite"
        self.assertTrue(math.isclose(griffin.max_hp, GRIFFIN_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(griffin.base_speed, GRIFFIN_SPEED, rel_tol=1e-7))
        self.assertTrue(math.isclose(griffin.distance_remaining, GRIFFIN_INITIAL_DISTANCE, rel_tol=1e-9))

        # Wave 1 summoned MeteorEagle
        eagle = built.spawn_summon_entity(402201001, wave_index=0, name="流星铁鹰_1", initial_distance=5000.0)
        self.assertEqual(eagle.name, "流星铁鹰_1")
        self.assertTrue(math.isclose(eagle.max_hp, EAGLE_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(eagle.distance_remaining, 5000.0, rel_tol=1e-9))

        # Wave 2 ApoliBoss (LittleBoss -> is_boss=True, multi-phase HP)
        w2_entities = built.build_wave_entities(1)
        self.assertEqual(len(w2_entities), 1)
        apoli = w2_entities[0]
        self.assertEqual(apoli.name, "堕神之血•亚婆离")
        self.assertTrue(apoli.is_boss)
        self.assertTrue(math.isclose(apoli.max_hp, APOLI_PHASE1_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.base_speed, APOLI_BASE_SPEED, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.max_toughness, APOLI_TOUGHNESS, rel_tol=1e-9))
        self.assertTrue(math.isclose(apoli.phase_max_hps[1], APOLI_PHASE2_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.base_effect_res, 0.4, abs_tol=1e-9))

        # Wave 2 summoned BeastSprout
        sprout = built.spawn_summon_entity(503201002, wave_index=1, name="狂兽的胚芽1")
        self.assertTrue(math.isclose(sprout.max_hp, SPROUT_HP, rel_tol=1e-7))

    def test_build_stage_30126122_and_30510021_battle_event_abilities(self) -> None:
        built_122 = self.factory.build_stage(30126122)
        be_30149 = built_122.get_battle_event(30149)
        self.assertEqual(be_30149.unresolved_abilities, ())
        self.assertIn("BattleEventAbility_Challenge_Month_49", be_30149.abilities)
        self.assertEqual(be_30149.param_list, (5.0, 20.0))
        self.assertGreater(len(be_30149.referenced_task_types), 0)

        built_021 = self.factory.build_stage(30510021)
        be_30503 = built_021.get_battle_event(30503)
        self.assertEqual(be_30503.unresolved_abilities, ())
        self.assertIn("BattleEventAbility_SummonMonsterInfinite", be_30503.abilities)
        self.assertIn("BattleEventAbility_ChallengePeakBattle_CountDown", be_30503.abilities)
        self.assertEqual(be_30503.param_list, (0.5, 7.0, 4.0, 0.5))

        # Verify wave-scoped summons in 30510021 (Wave 0 has 8032040, Wave 1 has 503201002)
        self.assertIn(8032040, built_021.waves[0].summon_blueprints)
        self.assertNotIn(8032040, built_021.waves[1].summon_blueprints)
        self.assertIn(503201002, built_021.waves[1].summon_blueprints)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for ``simulator.vm.stage_ai``."""

from __future__ import annotations

import math
import unittest

from simulator.vm.stage_ai import MonsterAIExecutor, StageAILoader
from simulator.vm.stage_data_loader import StageDataLoader


class TestStageAI(unittest.TestCase):
    stage_loader: StageDataLoader
    ai_loader: StageAILoader

    @classmethod
    def setUpClass(cls) -> None:
        cls.stage_loader = StageDataLoader()
        cls.ai_loader = StageAILoader(stage_loader=cls.stage_loader)

    def test_stage_30126122_monster_ai_sequences_and_multipliers(self) -> None:
        stage = self.stage_loader.load_stage(30126122)

        # 1. 月夜天马 (402302001): Skill01 (3.0 Quantum) -> Skill02 (2.6 Quantum) -> ...
        pegasus_spec = stage.get_monster(402302001)
        pegasus_ai = self.ai_loader.compile_monster_ai(pegasus_spec)
        self.assertEqual(pegasus_ai.ai_path, "Config/ConfigAI/Monster_W4_Unicorn_00_AI.json")
        self.assertTrue(any("Skill01" in d.use_skills for d in pegasus_ai.decisions))
        self.assertTrue(any("Skill04" in d.use_skills for d in pegasus_ai.decisions))
        self.assertEqual(pegasus_ai.skill("Skill01").element, "Quantum")
        self.assertTrue(math.isclose(pegasus_ai.skill("Skill01").param(0), 3.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(pegasus_ai.skill("Skill04").param(0), 4.5, rel_tol=1e-9))
        self.assertTrue(any(h.hook_type == "StanceBreak" for h in pegasus_ai.reactive_hooks))

        # Step through AI flag cycle
        exec_pegasus = MonsterAIExecutor(pegasus_ai)
        turn1_actions = exec_pegasus.select_next_actions()
        self.assertEqual([a.skill_trigger_key for a in turn1_actions], ["Skill01"])

        # 2. 正阳狮鹫 (402301001): Skill01 (3.0 Fire) -> Skill02 (2.6 Fire) -> ...
        griffin_spec = stage.get_monster(402301001)
        griffin_ai = self.ai_loader.compile_monster_ai(griffin_spec)
        self.assertEqual(griffin_ai.skill("Skill01").element, "Fire")
        self.assertTrue(math.isclose(griffin_ai.skill("Skill01").param(0), 3.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin_ai.skill("Skill02").param(0), 2.6, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin_ai.skill("Skill04").param(0), 4.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(griffin_ai.skill("Skill04").param(1), 3.0, rel_tol=1e-9))

        # 3. 流星铁鹰 (402201001): Skill01 (2.0 Wind)
        eagle_spec = stage.get_monster(402201001)
        eagle_ai = self.ai_loader.compile_monster_ai(eagle_spec)
        self.assertEqual(eagle_ai.skill("Skill01").element, "Wind")
        self.assertTrue(math.isclose(eagle_ai.skill("Skill01").param(0), 2.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(eagle_ai.skill("Skill01").sp_hit_base, 5.0, rel_tol=1e-9))

        # 4. 堕神之血•亚婆离 (5034010): Phase 1 & Phase 2 decisions + PhaseTransition / TurnInsert hooks
        apoli_spec = stage.get_monster(5034010)
        apoli_ai = self.ai_loader.compile_monster_ai(apoli_spec)
        self.assertIn(1, apoli_ai.phase_sequences)
        self.assertIn(2, apoli_ai.phase_sequences)
        self.assertTrue(any(d.phase_condition == 1 and "Skill05" in d.use_skills for d in apoli_ai.decisions))
        self.assertTrue(any(d.phase_condition == 2 and "Skill04" in d.use_skills for d in apoli_ai.decisions))
        self.assertTrue(any(h.hook_type == "PhaseTransition" for h in apoli_ai.reactive_hooks))
        self.assertTrue(math.isclose(apoli_ai.skill("Skill01").param(0), 5.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(apoli_ai.skill("Skill02").param(0), 1.8, rel_tol=1e-9))

        # 5. 狂兽的胚芽 (503201002): OverrideSkillParams 2.2 -> 2.0 must be reflected in AI skill instance
        sprout_spec = stage.get_monster(503201002)
        sprout_ai = self.ai_loader.compile_monster_ai(sprout_spec)
        s01 = sprout_ai.skill("Skill01")
        self.assertEqual(s01.element, "Quantum")
        self.assertTrue(math.isclose(s01.base_params[0], 2.2, rel_tol=1e-9))
        self.assertTrue(math.isclose(s01.param(0), 2.0, rel_tol=1e-9))
        self.assertTrue(math.isclose(s01.sp_hit_base, 10.0, rel_tol=1e-9))

    def test_stage_30510021_monster_ai_and_stepper_groups(self) -> None:
        stage = self.stage_loader.load_stage(30510021)

        # 「灯塔」 (8033020) uses AIStepperDecisionGroupConfig
        beacon_spec = stage.get_monster(8033020)
        beacon_ai = self.ai_loader.compile_monster_ai(beacon_spec)
        self.assertTrue(any(d.group_name == "phase01" for d in beacon_ai.decisions))
        self.assertEqual(beacon_ai.skill("Skill01").element, "Physical")
        self.assertTrue(math.isclose(beacon_ai.skill("Skill04").param(0), 3.6, rel_tol=1e-9))

        # 千星戍卫 (8032040)
        guard_spec = stage.get_monster(8032040)
        guard_ai = self.ai_loader.compile_monster_ai(guard_spec)
        self.assertTrue(math.isclose(guard_ai.skill("Skill01").param(0), 1.5, rel_tol=1e-9))
        self.assertTrue(math.isclose(guard_ai.skill("Skill02").param(0), 2.0, rel_tol=1e-9))

        # 亚婆离 (503401002) Lv.100 barrier ratio override 0.95
        apoli_100 = stage.get_monster(503401002)
        apoli_100_ai = self.ai_loader.compile_monster_ai(apoli_100)
        self.assertTrue(math.isclose(apoli_100_ai.skill("PassiveSkill01").param(2), 0.95, rel_tol=1e-9))


if __name__ == "__main__":
    unittest.main()

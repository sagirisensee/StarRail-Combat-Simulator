# coding: utf-8
"""skill_config_id 打通测试: core 推导规则与实机导出中的官方技能 ID。"""
import unittest
from types import SimpleNamespace

from simulator.actions import ActionKind, AbilityDefinition, TargetMode
from simulator.core import resolve_skill_config_id
from simulator.golden_diff import build_default_sim, export_sim_sequence


class TestResolveSkillConfigId(unittest.TestCase):
    def setUp(self):
        self.ent = SimpleNamespace(avatar_id=1403)

    def test_slot_derivation_matches_official_ids(self):
        self.assertEqual(resolve_skill_config_id(self.ent, None, ActionKind.BASIC), 140301)
        self.assertEqual(resolve_skill_config_id(self.ent, None, ActionKind.SKILL), 140302)
        self.assertEqual(resolve_skill_config_id(self.ent, None, ActionKind.ULTIMATE), 140303)
        self.assertEqual(resolve_skill_config_id(self.ent, None, ActionKind.TECHNIQUE), 140307)

    def test_declared_id_wins(self):
        defn = AbilityDefinition(kind=ActionKind.MEMOSPRITE_SKILL, target_mode=TargetMode.ALL_ENEMIES, skill_id=1140901)
        spirit = SimpleNamespace(avatar_id=0)
        self.assertEqual(resolve_skill_config_id(spirit, defn, ActionKind.MEMOSPRITE_SKILL), 1140901)

    def test_unknown_returns_zero(self):
        no_avatar = SimpleNamespace(avatar_id=0)
        self.assertEqual(resolve_skill_config_id(no_avatar, None, ActionKind.BASIC), 0)
        self.assertEqual(resolve_skill_config_id(self.ent, None, ActionKind.FOLLOW_UP), 0)


class TestExportCarriesIds(unittest.TestCase):
    def test_sim_export_has_official_skill_ids(self):
        sim = build_default_sim(av_budget=200.0)
        seq = export_sim_sequence(sim, av_budget=200.0)
        ids = {s.config_id for t in seq.turns for s in t.skills if s.config_id}
        # 长夜忆灵技 1141301 与长夜月战技 141302 均应在导出序列中出现
        self.assertIn(1141301, ids)
        self.assertIn(141302, ids)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""缇宝 (Tribbie) 满命满精 11 个增益与 2 个其他效果全量真理源对账测试套件。"""
import unittest
from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulate_battle import STAGE_CONFIG, create_enemy_from_config


class TestTibaoFullStatusVerification(unittest.TestCase):
    def setUp(self):
        self.db = CharacterDB().load("data/character_db_export.json")
        self.team_members = ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]
        self.entities = [self.db.to_combat_entity(n) for n in self.team_members]
        for ent in self.entities:
            if ent.max_energy > 0 and ent.energy == 0.0:
                ent.energy = ent.max_energy * 0.5
        self.enemies = [create_enemy_from_config(c) for c in STAGE_CONFIG["waves"][0]["enemies"]]

    def test_tibao_11_buffs_and_2_other_effects_after_ultimate(self):
        sim = TurnSimulator(
            entities=self.entities + self.enemies,
            use_techniques=True,
            auto_ult=False,
            stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
        )
        tibao = sim.get_entity("缇宝")

        # 1. 验证开局 0.00 AV 满能
        self.assertEqual(tibao.energy, 120.0, "满命满精缇宝在开局应为 120/120 满能")

        # 2. 施放终结技 U1
        ult_success = sim.cast_ultimate("缇宝")
        self.assertTrue(ult_success, "终结技施放应成功")

        # 3. 验证回能：大招 5 点保底 + E6 追击触发 S5 专武回能 12 * 1.1944 = 19.33
        self.assertAlmostEqual(tibao.energy, 19.328, places=2)

        # 4. 获取真理源 status 快照
        snap = sim.query_status("缇宝")
        buff_names = [b["name"] for b in snap["buffs"]]
        other_names = [b["name"] for b in snap["other_effects"]]
        debuff_names = [b["name"] for b in snap.get("debuffs", [])]

        expected_buffs = [
            "城墙外的羊羔儿",
            "谕示",
            "偏离和弦",
            "长翅膀的玻璃球！",
            "我们自成旋律",
            "心意相契的安宁",
            "神启",
            "天气正好，万物可爱！",
            "烈阳惊雷的女武神",
            "星月漫天的明日",
            "哀歌覆国的诗人"
        ]

        expected_other = [
            "猜猜这里住着谁",
            "血噬"
        ]

        # 验证 11 个增益效果
        self.assertEqual(len(buff_names), 11, f"增益效果数量应为 11，实际为 {len(buff_names)}: {buff_names}")
        for expected in expected_buffs:
            self.assertIn(expected, buff_names, f"应包含增益效果: {expected}")

        # 验证 2 个其他效果
        self.assertEqual(len(other_names), 2, f"其他效果数量应为 2，实际为 {len(other_names)}: {other_names}")
        for expected in expected_other:
            self.assertIn(expected, other_names, f"应包含其他效果: {expected}")

        # 验证负面效果数量为 0
        self.assertEqual(len(debuff_names), 0, "开局我方应无负面效果")

        # 5. 动态属性数值校验
        self.assertAlmostEqual(snap["current_crit_dmg"], snap["base_crit_dmg"] + 0.96 + 0.55 + 0.15, places=2)
        self.assertAlmostEqual(snap["current_crit_rate"], snap["base_crit_rate"] + 0.32, places=2)
        self.assertAlmostEqual(snap["res_pen"], 0.264, places=3)
        self.assertAlmostEqual(snap["def_shred"], 0.18, places=2)
        # 生命上限 = 6505.1 * 1.20 + 2527 = 10333.1
        self.assertAlmostEqual(snap["max_hp"], snap["base_max_hp"] * 1.20 + 2527.0 if "base_max_hp" in snap else 10333.1, delta=1.0)


if __name__ == "__main__":
    unittest.main()

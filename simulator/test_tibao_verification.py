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

        # 3. 验证回能：大招 5 点 + E6 追击 5 点 + S5 专武追击 12 点 = 22 * 1.1944 = 26.27 (实机截断/显示为 26)
        self.assertAlmostEqual(tibao.energy, 26.268, places=2)
        self.assertEqual(round(tibao.energy), 26)

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

        # 5. 动态属性数值校验 (实机严格对齐)
        # 暴伤: 基础 324.2% + 拾骨地28% + 专武96% + 知更鸟59.5%(5怪命中达13点气氛值) + 女武神15% = 522.7%
        self.assertAlmostEqual(snap["current_crit_dmg"], 5.227, delta=0.02)
        # 暴击率: 基础 61.3% + 诗人32% = 93.3%
        self.assertAlmostEqual(snap["current_crit_rate"], 0.933, places=3)
        # 全抗穿: 26.4%
        self.assertAlmostEqual(snap["res_pen"], 0.264, places=3)
        # 防御无视: 18.0%
        self.assertAlmostEqual(snap["def_shred"], 0.18, places=2)
        # 通用属性增伤: 诗人10% + 知更鸟秘技30% + 羊羔儿72% = 112% (E6为必杀专属追加增伤，不污染通用增伤)
        self.assertAlmostEqual(snap["dmg_boost"], 1.12, places=2)
        # 生命上限 = 6505.1 + 基础白字生命2419.5 * 20% + 2527 = 9516.0
        self.assertEqual(round(snap["max_hp"]), 9516)

    def test_fengjin_full_status_verification(self):
        """验证风堇在进战且缇宝施放大招后的实机全量面板与增益效果对账。"""
        sim = TurnSimulator(
            entities=self.entities + self.enemies,
            use_techniques=True,
            auto_ult=False,
            stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
        )
        # 缇宝施放大招
        sim.cast_ultimate("缇宝")

        snap = sim.query_status("风堇")
        buff_names = [b["name"] for b in snap["buffs"]]
        other_names = [b["name"] for b in snap["other_effects"]]
        debuff_names = [b["name"] for b in snap.get("debuffs", [])]

        expected_buffs = [
            "谕示",
            "偏离和弦",
            "暴风停歇",
            "甘霖",
            "烈阳惊雷的女武神",
            "我们自成旋律",
            "天气正好，万物可爱！",
            "神启",
            "心意相契的安宁"
        ]

        expected_other = [
            "好忙好忙的缇宝",
            "血噬"
        ]

        # 1. 验证 9 个增益效果 (甘霖自身速度+6%，烈阳惊雷的女武神全队暴伤+15%)
        self.assertEqual(len(buff_names), 9, f"风堇增益效果应为 9，实际为 {len(buff_names)}: {buff_names}")
        for expected in expected_buffs:
            self.assertIn(expected, buff_names, f"风堇应包含增益: {expected}")

        # 2. 验证 2 个其他效果
        self.assertEqual(len(other_names), 2, f"风堇其他效果应为 2，实际为 {len(other_names)}: {other_names}")
        for expected in expected_other:
            self.assertIn(expected, other_names, f"风堇应包含其他效果: {expected}")

        # 3. 验证负面效果数量为 0
        self.assertEqual(len(debuff_names), 0)

        # 4. 动态属性数值与实机完全对账
        self.assertEqual(int(snap["max_hp"]), 6014)
        self.assertEqual(int(snap["current_energy"]), 70)
        self.assertEqual(int(snap["max_energy"]), 140)
        self.assertEqual(int(snap["current_atk"]), 1336)
        self.assertEqual(int(snap["current_def"]), 1527)
        self.assertEqual(round(snap["current_speed"]), 208)
        self.assertAlmostEqual(snap["current_crit_rate"], 1.05, places=2)
        self.assertAlmostEqual(snap["current_crit_dmg"], 2.426, places=3)
        self.assertAlmostEqual(snap["outgoing_healing"], 0.625, places=3)
        self.assertAlmostEqual(snap["effect_res"], 0.917, places=3)

    def test_tibao_trace_pebble_ally_hit_energy(self):
        """验证行迹【岔路旁的小石子？】：队友直接攻击每命中 1 目标回复 1.5 点固定能量，并免疫 DoT/反伤误判。"""
        from simulator.events import DamageAppliedEvent
        from simulator.damage import DamageBreakdown

        sim = TurnSimulator(
            entities=self.entities + self.enemies,
            use_techniques=True,
            auto_ult=False,
            stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
        )
        tibao = sim.get_entity("缇宝")
        sim.cast_ultimate("缇宝")
        energy_after_ult = tibao.energy
        self.assertAlmostEqual(energy_after_ult, 26.268, places=2)

        # 1. 模拟长夜直接攻击命中 2 个敌人 -> 回复 1.5 * 2 = 3.0 点固定能量
        breakdown_valid = DamageBreakdown(
            attacker_name="长夜",
            target_name="月夜天马 (Lv.100)",
            base_dmg=1000,
            crit_mult=2.0,
            is_crit=True,
            dmg_boost_mult=1.5,
            def_mult=0.5,
            res_mult=1.0,
            vuln_mult=1.0,
            reduction_mult=1.0,
            final_damage=1500.0
        )
        # 命中第 1 个敌人
        sim.event_bus.publish(DamageAppliedEvent(
            av=0.0, cycle=0, attacker_name="长夜", target_name="月夜天马 (Lv.100)",
            damage=1500.0, is_crit=True, breakdown=breakdown_valid, target_hp_left=500000.0
        ))
        self.assertAlmostEqual(tibao.energy, energy_after_ult + 1.5, places=2)

        # 命中第 2 个敌人 -> 累计 +3.0 点，能量达到 29.27 (显示 29 点)
        sim.event_bus.publish(DamageAppliedEvent(
            av=0.0, cycle=0, attacker_name="长夜", target_name="「灯塔」 (Lv.100)",
            damage=1500.0, is_crit=True, breakdown=breakdown_valid, target_hp_left=600000.0
        ))
        self.assertAlmostEqual(tibao.energy, energy_after_ult + 3.0, places=2)
        self.assertEqual(int(tibao.energy), 29)

        # 2. 机制边界验证：DoT 伤害跳伤不应触发回能
        breakdown_dot = DamageBreakdown(
            attacker_name="长夜月",
            target_name="月夜天马 (Lv.100)",
            base_dmg=500,
            crit_mult=1.0,
            is_crit=False,
            dmg_boost_mult=1.0,
            def_mult=0.5,
            res_mult=1.0,
            vuln_mult=1.0,
            reduction_mult=1.0,
            final_damage=250.0
        )
        sim.event_bus.publish(DamageAppliedEvent(
            av=0.0, cycle=0, attacker_name="长夜月", target_name="月夜天马 (Lv.100)",
            damage=250.0, is_crit=False, breakdown=breakdown_dot, target_hp_left=490000.0,
            damage_tag="dot"
        ))
        self.assertAlmostEqual(tibao.energy, energy_after_ult + 3.0, places=2, msg="DoT 伤害不应误触发行迹回能")

        # 3. 机制边界验证：反伤/友方目标受伤不应触发回能
        sim.event_bus.publish(DamageAppliedEvent(
            av=0.0, cycle=0, attacker_name="长夜月", target_name="长夜",
            damage=100.0, is_crit=False, breakdown=breakdown_valid, target_hp_left=3000.0
        ))
        self.assertAlmostEqual(tibao.energy, energy_after_ult + 3.0, places=2, msg="友方目标受击不应触发行迹回能")


if __name__ == "__main__":
    unittest.main()

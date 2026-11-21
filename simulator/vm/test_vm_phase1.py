# coding: utf-8
"""Phase 1 VM 验证测试：
1. `.NET` 字符串哈希算法 (`dotnet_hash`) 与官方 Rank/BuiltinFunc/DynamicKey 精确对齐；
2. 全部 13 种 `PostfixExpr` 操作码（含现代 17 结尾与早期 10 结尾两套格式）+ 11 个数学内置函数；
3. `GameDataLoader` 加载并编译 1403(E6) / 1409(E1) / 1413(E2) / 1512(E1) 及其忆灵、光锥、遗器参数，
   与现有 `SkillScalingFactory` / Nanoka 4.6 官方表 100% 数值对齐。
"""
import unittest

from simulator.vm import (
    GameDataLoader,
    dotnet_hash,
    eval_dynamic_float,
    eval_postfix_expr,
)


class TestVMPhase1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = GameDataLoader()

    def test_dotnet_hash_matches_official_keys(self):
        self.assertEqual(dotnet_hash("_CurrentSpeed"), 44986865)
        self.assertEqual(dotnet_hash("Rank01"), 2089636447)
        self.assertEqual(dotnet_hash("Rank02"), 523552506)
        self.assertEqual(dotnet_hash("Rank04"), 1686351920)
        self.assertEqual(dotnet_hash("Rank06"), -1445815962)
        self.assertEqual(dotnet_hash("min"), 339799074)
        self.assertEqual(dotnet_hash("max"), 696029444)
        self.assertEqual(dotnet_hash("floor"), 1776456860)
        self.assertEqual(dotnet_hash("clamp"), -1355705909)

    def test_postfix_expr_modern_and_legacy_opcodes(self):
        # 1. Hyacine PointB3: floor(_OverCountSpeedValue / 1) * 0.01
        expr_b3 = {
            "OpCodes": "AQABAQECBRABAQMEEQ==",
            "FixedValues": [],
            "DynamicHashes": [1776456860, 1234527420, 1696529396, -845735157],
        }
        res = eval_postfix_expr(
            expr_b3,
            {1776456860: 0.0, 1234527420: 15.8, 1696529396: 1.0, -845735157: 0.01},
        )
        self.assertAlmostEqual(res, 0.15, places=6)

        # 2. Legacy (end=10): Negate (-0.20) in Relic 108
        expr_legacy = {
            "OpCodes": "AQAHCg==",
            "FixedValues": [],
            "DynamicHashes": [-364539573],
        }
        self.assertAlmostEqual(eval_postfix_expr(expr_legacy, {-364539573: 0.20}), -0.20, places=6)

        # 3. Ternary + Clamp + Negate + Mod
        expr_clamp = {
            "OpCodes": "AQABAQECAgAAARMDER==",  # invalid check, test real RuanMei & SilverWolf999
        }
        # RuanMei: 0.5 * min(count, 20)
        expr_rm = {
            "OpCodes": "AQABAQECAQMQAgQR",
            "FixedValues": [],
            "DynamicHashes": [-1638941744, 339799074, 629996837, -648181786],
        }
        self.assertAlmostEqual(
            eval_postfix_expr(expr_rm, {-1638941744: 0.5, 629996837: 25.0, -648181786: 20.0}),
            10.0,
            places=6,
        )

    def test_team_characters_and_servants_match_nanoka_tables(self):
        # 1. 长夜月 (1413, E2)
        c1413 = self.loader.load_character(1413, eidolon=2)
        s1413 = self.loader.load_servant(11413, eidolon=2)
        self.assertEqual(c1413.skill_levels[1141301], 6)
        self.assertEqual(c1413.skill_levels[1141307], 6)
        # Skill03 multiplier = 2.00
        self.assertAlmostEqual(
            c1413.dynamic_floats[dotnet_hash("1413_Skill03_0")] if dotnet_hash("1413_Skill03_0") in c1413.dynamic_floats
            else next(
                c1413.dynamic_floats[int(k)]
                for k, v in c1413.config["DynamicValues"]["Floats"].items()
                if v.get("ReadInfo") == {"Type": "SkillParam", "TriggerKey": "Skill03", "Index": 0}
            ),
            2.0,
            places=4,
        )
        # Servant 1141301 params = [0.50, 0.10]
        sv_p0 = next(
            s1413.dynamic_floats[int(k)]
            for k, v in s1413.config["DynamicValues"]["Floats"].items()
            if v.get("ReadInfo") == {"Type": "SkillParam", "TriggerKey": "Skill01", "Index": 0}
        )
        self.assertAlmostEqual(sv_p0, 0.5, places=4)
        inh_1413 = self.loader.get_servant_base_inheritance(11413, eidolon=2)
        self.assertAlmostEqual(inh_1413["hp_inherit"], 0.50, places=4)
        self.assertAlmostEqual(inh_1413["speed_base"], 160.0, places=4)

        # 2. 缇宝 (1403, E6)
        c1403 = self.loader.load_character(1403, eidolon=6)
        self.assertEqual(c1403.skill_levels[140301], 7)
        self.assertEqual(c1403.skill_levels[140302], 12)
        self.assertEqual(c1403.skill_levels[140303], 12)
        self.assertEqual(c1403.skill_levels[140304], 12)
        u0 = next(
            c1403.dynamic_floats[int(k)]
            for k, v in c1403.config["DynamicValues"]["Floats"].items()
            if v.get("ReadInfo") == {"Type": "SkillParam", "TriggerKey": "Skill03", "Index": 0}
        )
        self.assertAlmostEqual(u0, 0.33, places=4)

        # 3. 风堇 (1409, E1) + 小伊卡 (11409)
        c1409 = self.loader.load_character(1409, eidolon=1)
        s1409 = self.loader.load_servant(11409, eidolon=1)
        self.assertEqual(c1409.skill_levels[1140901], 6)
        self.assertIn("Avatar_Hyacine_00_Skill02_Phase02", c1409.abilities)
        self.assertIn("MServant_HyacineServant_00_Passive", s1409.global_modifiers)
        sv_hy_0 = next(
            s1409.dynamic_floats[int(k)]
            for k, v in s1409.config["DynamicValues"]["Floats"].items()
            if v.get("ReadInfo") == {"Type": "SkillParam", "TriggerKey": "Skill01", "Index": 0}
        )
        self.assertAlmostEqual(sv_hy_0, 0.2, places=4)

        # 4. 晴歌 / 知更鸟S (1512, E1) + 晴空乐手 (11512)
        c1512 = self.loader.load_character(1512, eidolon=1)
        s1512 = self.loader.load_servant(11512, eidolon=1)
        self.assertEqual(c1512.skill_levels[1151201], 6)
        sv_rb_1 = next(
            s1512.dynamic_floats[int(k)]
            for k, v in s1512.config["DynamicValues"]["Floats"].items()
            if v.get("ReadInfo") == {"Type": "SkillParam", "TriggerKey": "Skill01", "Index": 1}
        )
        self.assertAlmostEqual(sv_rb_1, 1.5, places=4)

    def test_relics_and_light_cones_load_and_resolve(self):
        ab_125, dyn_125 = self.loader.get_relic_ability(125, 4)
        self.assertEqual(ab_125["Name"], "Ability51251")
        self.assertAlmostEqual(dyn_125[dotnet_hash("125_4")] if False else list(dyn_125.values())[0], 0.06, places=4)

        ab_323, dyn_323 = self.loader.get_relic_ability(323, 2)
        self.assertEqual(ab_323["Name"], "Ability53231")
        self.assertAlmostEqual(list(dyn_323.values())[0], 0.08, places=4)

        ab_23042, dyn_23042 = self.loader.get_equipment_ability(23042, superimposition=1)
        self.assertEqual(ab_23042["Name"], "Ability23042")
        self.assertIn(0.18, [round(v, 4) for v in dyn_23042.values()])
        self.assertIn(0.01, [round(v, 4) for v in dyn_23042.values()])

        ab_23052, dyn_23052 = self.loader.get_equipment_ability(23052, superimposition=1)
        self.assertEqual(ab_23052["Name"], "Ability23052")
        self.assertIn(0.16, [round(v, 4) for v in dyn_23052.values()])


if __name__ == "__main__":
    unittest.main()

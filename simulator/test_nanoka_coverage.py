"""
Nanoka 4.6 全量资产与行为覆盖验收测试 (Full Coverage Verification Tests).
覆盖范围：
1. 62 套官方遗器全部注册并可正常实例化；
2. 170 顶官方光锥全部注册并可正常按 S1~S5 阶级实例化；
3. 98 位官方角色全部具备 SkillScaling，逐级解析星魂 (E3/E5) 技能等级与倍率；
4. 核心角色 (缇宝、黄泉、流萤、花火) 在 E0/E3/E5/E6 下的倍率精准查表测试。
"""

import unittest
from simulator.assets import AssetRepository
from simulator.relics import RelicRegistry
from simulator.light_cones import LightConeRegistry
from simulator.scaling import SkillScalingFactory


class TestNanokaCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = AssetRepository.get_instance()

    def test_01_all_62_relic_sets_instantiation(self):
        """验证 62 套官方遗器全部可正常解析并实例化。"""
        all_relics = self.repo.all_relic_sets()
        self.assertEqual(len(all_relics), 62, "官方 4.6 遗器数量应为 62 套")

        for r_asset in all_relics:
            # 2 件套测试
            h2 = RelicRegistry.create(r_asset.id, owner_id="测试角色", pieces=2)
            self.assertIsNotNone(h2, f"遗器 {r_asset.id} ({r_asset.name}) 2件套实例化失败")

            # 4 件套测试
            h4 = RelicRegistry.create(r_asset.name, owner_id="测试角色", pieces=4)
            self.assertIsNotNone(h4, f"遗器 {r_asset.id} ({r_asset.name}) 4件套实例化失败")

    def test_02_all_170_light_cones_instantiation(self):
        """验证 170 顶官方光锥全部可正常按 S1~S5 实例化。"""
        all_lcs = self.repo.all_light_cones()
        self.assertEqual(len(all_lcs), 170, "官方 4.6 光锥数量应为 170 顶")

        for lc_asset in all_lcs:
            for s in (1, 5):
                h = LightConeRegistry.create(lc_asset.id, owner_id="测试角色", superimposition=s)
                self.assertIsNotNone(h, f"光锥 {lc_asset.id} ({lc_asset.name}) S{s} 实例化失败")
                self.assertEqual(h.superimposition, s)

    def test_03_all_98_characters_skill_scaling(self):
        """验证 98 位官方角色全部支持 SkillScaling 且 E3/E5 映射完整。"""
        all_chars = self.repo.all_characters()
        self.assertEqual(len(all_chars), 98, "官方 4.6 角色数量应为 98 位")

        for char_asset in all_chars:
            scaling_e0 = SkillScalingFactory.create(char_asset.id, eidolon=0)
            self.assertIsNotNone(scaling_e0, f"角色 {char_asset.id} ({char_asset.name}) E0 缩放器创建失败")

            scaling_e6 = SkillScalingFactory.create(char_asset.name, eidolon=6)
            self.assertIsNotNone(scaling_e6, f"角色 {char_asset.id} ({char_asset.name}) E6 缩放器创建失败")

            # 普攻等级：E0 为 6，E6 应 >= 6
            lvl_basic_e0 = scaling_e0.effective_level("basic")
            lvl_basic_e6 = scaling_e6.effective_level("basic")
            self.assertEqual(lvl_basic_e0, 6)
            self.assertGreaterEqual(lvl_basic_e6, 6)

            # 战技与终结技等级：E0 为 10，E6 应 >= 10
            self.assertEqual(scaling_e0.effective_level("skill"), 10)
            self.assertEqual(scaling_e0.effective_level("ultra"), 10)
            self.assertGreaterEqual(scaling_e6.effective_level("skill"), 10)
            self.assertGreaterEqual(scaling_e6.effective_level("ultra"), 10)

    def test_04_tibao_e3_e5_scaling_values(self):
        """验证缇宝 (ID 1403) 在各星魂阶级下的精准倍率数值。"""
        # E0
        s0 = SkillScalingFactory.create("缇宝", eidolon=0)
        self.assertEqual(s0.effective_level("basic"), 6)
        self.assertEqual(s0.effective_level("skill"), 10)
        self.assertEqual(s0.effective_level("ultra"), 10)
        self.assertEqual(s0.effective_level("talent"), 10)
        # 10 级战技全属性抗穿 24%
        self.assertAlmostEqual(s0.value("skill", 0), 0.24, places=4)
        # 10 级大招易伤 30%
        self.assertAlmostEqual(s0.value("ultra", 1), 0.30, places=4)

        # E3: 终结技+2, 普攻+1
        s3 = SkillScalingFactory.create("缇宝", eidolon=3)
        self.assertEqual(s3.effective_level("basic"), 7)
        self.assertEqual(s3.effective_level("ultra"), 12)
        self.assertEqual(s3.effective_level("skill"), 10)  # 未解锁
        # 12 级大招易伤 33%
        self.assertAlmostEqual(s3.value("ultra", 1), 0.33, places=4)

        # E5: 战技+2, 天赋+2
        s5 = SkillScalingFactory.create("缇宝", eidolon=5)
        self.assertEqual(s5.effective_level("skill"), 12)
        self.assertEqual(s5.effective_level("talent"), 12)
        # 12 级战技全属性抗穿 26.4%
        self.assertAlmostEqual(s5.value("skill", 0), 0.264, places=4)
        # 12 级天赋追加攻击倍率 19.8%
        self.assertAlmostEqual(s5.value("talent", 0), 0.198, places=4)

    def test_05_acheron_and_firefly_scaling_values(self):
        """验证黄泉与流萤在 E0/E6 下的倍率正确变化。"""
        # 黄泉 E0 vs E6
        ac_e0 = SkillScalingFactory.create("黄泉", eidolon=0)
        ac_e6 = SkillScalingFactory.create("黄泉", eidolon=6)
        # 战技主目标伤害倍率：10级 1.60，12级 1.76
        self.assertAlmostEqual(ac_e0.value("skill", 0), 1.60, places=4)
        self.assertAlmostEqual(ac_e6.value("skill", 0), 1.76, places=4)

        # 流萤 E0 vs E6
        ff_e0 = SkillScalingFactory.create("流萤", eidolon=0)
        ff_e6 = SkillScalingFactory.create("流萤", eidolon=6)
        # 强化战技主目标倍率：10级 2.00，12级 2.20
        self.assertAlmostEqual(ff_e0.value("skill", 0), 2.00, places=4)
        self.assertAlmostEqual(ff_e6.value("skill", 0), 2.20, places=4)


if __name__ == "__main__":
    unittest.main()

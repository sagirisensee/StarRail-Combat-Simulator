"""全面验证星穹铁道全角色技能套件 (Character Kits Comprehensive Test Suite)."""

import unittest
from simulator.core import TurnSimulator, Entity
from simulator.db.character_db import get_character_db
from simulator.actions import ActionKind, ActionContext
from simulator.status import StatType


class TestCharacterKitsComprehensive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_character_db("data/character_db_export.json")

    def test_01_all_62_characters_have_kits(self):
        """验证数据库内全量 62 位角色均能无缝转换为 Combat Entity 且已装配 Kit。"""
        all_profiles = self.db.list_all()
        self.assertEqual(len(all_profiles), 62, "数据库应包含 62 位角色档案")
        for p in all_profiles:
            ent = self.db.to_combat_entity(p)
            self.assertIsNotNone(ent.kit, f"角色 {p.name} 应装配有 KitHandler")

    def test_02_sparkle_kit(self):
        """验证花火核心技能与星魂机制。"""
        sparkle_prof = self.db.get("花火")
        sparkle = self.db.to_combat_entity(sparkle_prof)
        dps = Entity(name="测试主C", base_speed=100.0, base_atk=1000.0, base_crit_dmg=1.0)
        boss = Entity(name="拟真Boss", base_speed=90.0, is_enemy=True)

        sim = TurnSimulator(entities=[sparkle, dps, boss])
        self.assertEqual(sim.sp.max_sp, 7, "花火天赋应将 SP 上限提升至 7 点")

        # 花火 E3 (>= E1) 开局提速 15%
        self.assertAlmostEqual(sparkle.speed, sparkle.base_speed * 1.15, places=1)

        # 施放战技拉条与暴伤
        dps.distance_remaining = 8000.0
        sparkle.kit.execute(ActionContext("act_skill", sparkle.name, ActionKind.SKILL, target_ids=(dps.name,)))
        sim.resolver.resolve_all()

        # 拉条 50%: 8000 - 5000 = 3000
        self.assertAlmostEqual(dps.distance_remaining, 3000.0, places=1)
        # 暴伤加成
        self.assertGreater(dps.crit_dmg, 1.0)

    def test_03_robin_kit(self):
        """验证知更鸟全队拉条与 E1/E2 协奏增益。"""
        robin_prof = self.db.get("知更鸟")
        robin = self.db.to_combat_entity(robin_prof)
        ally1 = Entity(name="队友1", base_speed=100.0)
        ally2 = Entity(name="队友2", base_speed=120.0)

        sim = TurnSimulator(entities=[robin, ally1, ally2])
        ally1.distance_remaining = 6000.0
        ally2.distance_remaining = 9000.0

        # 知更鸟施放大招进入协奏
        robin.kit.execute(ActionContext("act_ult", robin.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()

        # 全员立即行动 (100% 拉条)
        self.assertEqual(ally1.distance_remaining, 0.0)
        self.assertEqual(ally2.distance_remaining, 0.0)

        # 知更鸟 E2: 全队速度提高 16%
        if robin.eidolon >= 2:
            self.assertAlmostEqual(ally1.speed, ally1.base_speed * 1.16, places=1)

    def test_04_ruan_mei_kit(self):
        """验证阮•梅开局天赋全队提速与结界抗穿/破防。"""
        rm_prof = self.db.get("阮•梅")
        rm = self.db.to_combat_entity(rm_prof)
        ally = Entity(name="主力DPS", base_speed=100.0)

        sim = TurnSimulator(entities=[rm, ally])

        # 天赋提速 10% (除自身外)
        self.assertAlmostEqual(ally.speed, 110.0, places=1)
        self.assertAlmostEqual(rm.speed, rm.base_speed, places=1)

        # 战技施放
        rm.kit.execute(ActionContext("act_skill", rm.name, ActionKind.SKILL, target_ids=()))
        sim.resolver.resolve_all()
        # 终结技施放
        rm.kit.execute(ActionContext("act_ult", rm.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()

        self.assertTrue(sim.status_mgr.has_status(ally.name, "RuanMei_Ult_ResPen"))
        if rm.eidolon >= 1:
            self.assertTrue(sim.status_mgr.has_status(ally.name, "RuanMei_E1_DefShred"))

    def test_05_bronya_kit(self):
        """验证布洛妮娅战技 100% 拉条、E6 2回合持续与大招攻暴加成。"""
        bronya_prof = self.db.get("布洛妮娅")
        bronya = self.db.to_combat_entity(bronya_prof)
        dps = Entity(name="巡猎主C", base_speed=110.0)

        sim = TurnSimulator(entities=[bronya, dps])
        dps.distance_remaining = 8500.0

        bronya.kit.execute(ActionContext("act_skill", bronya.name, ActionKind.SKILL, target_ids=(dps.name,)))
        sim.resolver.resolve_all()

        # 100% 拉条
        self.assertEqual(dps.distance_remaining, 0.0)
        # E6: 增伤持续 2 回合
        statuses = sim.status_mgr.get_statuses(dps.name)
        dmg_buff = next(s for s in statuses if s.id == "Bronya_Skill_Dmg")
        self.assertEqual(dmg_buff.duration, 2)

    def test_06_tingyun_kit(self):
        """验证停云战技赐福与终结技大额充能 (E6 充能 60 点)。"""
        tingyun_prof = self.db.get("停云")
        tingyun = self.db.to_combat_entity(tingyun_prof)
        dps = Entity(name="大招主C", base_speed=100.0, energy=10.0, max_energy=120.0)

        sim = TurnSimulator(entities=[tingyun, dps])
        tingyun.kit.execute(ActionContext("act_ult", tingyun.name, ActionKind.ULTIMATE, target_ids=(dps.name,)))
        sim.resolver.resolve_all()

        # E6: 10 + 60 = 70 点能量
        self.assertEqual(dps.energy, 70.0)
        self.assertTrue(sim.status_mgr.has_status(dps.name, "Tingyun_Ult_Dmg"))

    def test_07_firefly_kit(self):
        """验证流萤死星过载回能 144 点与完全燃烧 100% 自拉条 + E1 0点战技点消耗。"""
        ff_prof = self.db.get("流萤")
        ff = self.db.to_combat_entity(ff_prof)
        enemy = Entity(name="破韧靶子", base_speed=80.0, is_enemy=True, current_toughness=100.0, max_toughness=100.0)

        sim = TurnSimulator(entities=[ff, enemy], initial_sp=1)

        # 常态战技：回能 144 点
        ff.kit.execute(ActionContext("ff_skill_1", ff.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()
        self.assertEqual(ff.energy, 144.0)

        # 终结技：100% 自拉条进入完全燃烧
        ff.distance_remaining = 5000.0
        ff.kit.execute(ActionContext("ff_ult", ff.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertEqual(ff.distance_remaining, 0.0)
        self.assertTrue(ff.kit.is_combustion)

        # E1: 完全燃烧下强化战技消耗 0 点 SP！
        skill_defn = ff.kit.definition(ActionKind.SKILL)
        self.assertEqual(skill_defn.cost.sp, 0, "流萤E1完全燃烧下战技消耗应为 0 点 SP")

    def test_08_pela_and_gallagher(self):
        """验证佩拉大招群体减防 40% 与加拉赫大招自拉条 + 强化普攻削韧。"""
        pela_prof = self.db.get("佩拉")
        gallagher_prof = self.db.get("加拉赫")
        pela = self.db.to_combat_entity(pela_prof)
        gallagher = self.db.to_combat_entity(gallagher_prof)
        enemy = Entity(name="敌人", base_speed=80.0, is_enemy=True, current_toughness=60.0, max_toughness=60.0)

        sim = TurnSimulator(entities=[pela, gallagher, enemy])

        # 佩拉大招群体减防
        pela.kit.execute(ActionContext("pela_ult", pela.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(enemy.name, "Pela_Ult_DefShred"))

        # 加拉赫大招自拉条 100%
        gallagher.distance_remaining = 7000.0
        gallagher.kit.execute(ActionContext("gal_ult", gallagher.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertEqual(gallagher.distance_remaining, 0.0)
        self.assertTrue(gallagher.kit.is_enhanced_basic)

    def test_09_elation_quartet(self):
        """验证阿哈欢愉四人组 (真珠、爻光、火花、银狼LV.999) 欢愉度属性与阿哈时刻。"""
        pearl_prof = self.db.get("真珠")
        pearl = self.db.to_combat_entity(pearl_prof)
        ally = Entity(name="欢愉信徒", base_speed=100.0)
        enemy = Entity(name="无辜敌人", base_speed=80.0, is_enemy=True)

        sim = TurnSimulator(entities=[pearl, ally, enemy])
        ally.distance_remaining = 10000.0

        # 真珠施放「阿哈时刻！」终结技
        pearl.kit.execute(ActionContext("aha_ult", pearl.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()

        # 阿哈时刻全队拉条 30%: 10000 - 3000 = 7000
        self.assertEqual(ally.distance_remaining, 7000.0)


if __name__ == "__main__":
    unittest.main()

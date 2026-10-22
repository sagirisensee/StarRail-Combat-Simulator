"""独立解耦光锥模块单元测试与集成测试 (Light Cones Decoupled Tests)."""
import unittest
from simulator.core import TurnSimulator, Entity
from simulator.db.character_db import CharacterDB
from simulator.actions import ActionKind, ActionContext
from simulator.status import StatType
from simulator.light_cones import LightConeRegistry, LightConeEquipment
from simulator.light_cones.handlers.if_time_were_a_flower import IfTimeWereAFlowerHandler
from simulator.light_cones.handlers.make_farewells_more_beautiful import MakeFarewellsMoreBeautifulHandler
from simulator.light_cones.handlers.memory_never_fades import MemoryNeverFadesHandler
from simulator.light_cones.handlers.may_rainbows_remain_in_the_sky import MayRainbowsRemainInTheSkyHandler


class TestLightConesModular(unittest.TestCase):
    def setUp(self):
        self.db = CharacterDB().load("data/character_db_export.json")

    def test_01_registry_and_resolution(self):
        """验证光锥注册中心：按ID、标准名、别名双向解析与实例化。"""
        # 1. 查找如果时间是一朵花
        spec, handler_cls = LightConeRegistry.get("如果时间是一朵花")
        self.assertEqual(spec.cone_id, "23038")
        self.assertEqual(handler_cls, IfTimeWereAFlowerHandler)

        # 2. 别名查找
        spec2, _ = LightConeRegistry.get("tribbie_lc")
        self.assertEqual(spec2.cone_id, "23038")

        # 3. 实例化与非法叠影拦截
        inst = LightConeRegistry.create("23038", owner_id="测试角色", superimposition=5)
        self.assertIsNotNone(inst)
        self.assertEqual(inst.superimposition, 5)

        with self.assertRaises(ValueError):
            LightConeRegistry.create("23038", owner_id="测试角色", superimposition=6)

    def test_02_tibao_and_flower_lightcone_integrated(self):
        """验证缇宝与《如果时间是一朵花》(S5) 独立集成：开局回能、谕示暴伤与大招追击刷新。"""
        tibao = self.db.to_combat_entity("缇宝")
        self.assertIsNotNone(tibao.light_cone)
        self.assertIsInstance(tibao.light_cone, IfTimeWereAFlowerHandler)
        self.assertEqual(tibao.light_cone.superimposition, 5)

        # 进战初始 50% 能量 = 60
        tibao.energy = 60.0
        boss = Entity(name="测试首领", base_speed=90.0, is_enemy=True)

        sim = TurnSimulator(entities=[tibao, boss], auto_ult=False)

        # 缇宝开局能量：60 + (30行迹 + 21光锥) * 1.1944 = 120.9 -> 120 满能
        self.assertEqual(tibao.energy, 120.0, "满命满精缇宝开局应瞬间满能 120/120")
        self.assertTrue(sim.can_cast_ultimate("缇宝"))

        # 全体暴伤应享受到 S5 专武的 96% 暴伤提升
        snap = sim.query_status("缇宝")
        buff_names = [b["name"] for b in snap["buffs"]]
        self.assertTrue(any("谕示" in b for b in buff_names), "应挂载光锥【谕示】Buff")
        self.assertAlmostEqual(snap["current_crit_dmg"], snap["base_crit_dmg"] + 0.96, places=2)

    def test_03_changyeyue_make_farewells_lightcone(self):
        """验证长夜月与《让告别，更美一些》(S1) 独立集成：战技扣血激活【冥花】30%无视防御。"""
        changyeyue = self.db.to_combat_entity("长夜月")
        self.assertIsNotNone(changyeyue.light_cone)
        self.assertIsInstance(changyeyue.light_cone, MakeFarewellsMoreBeautifulHandler)
        self.assertEqual(changyeyue.light_cone.superimposition, 1)

        boss = Entity(name="测试首领", base_speed=90.0, is_enemy=True)
        sim = TurnSimulator(entities=[changyeyue, boss], auto_ult=False)

        # 开局尚未行动，不应有【冥花】
        snap_before = sim.query_status("长夜月")
        self.assertEqual(snap_before["def_shred"], 0.0)

        # 施放战技
        sim.execute_current_turn(action_override=ActionKind.SKILL)

        # 行动后光锥处理器应挂载【冥花】30% 减防/无视防御
        snap_after = sim.query_status("长夜月")
        self.assertAlmostEqual(snap_after["def_shred"], 0.30, places=2)

    def test_04_robin_memory_never_fades_lightcone(self):
        """验证知更鸟与《记忆永不落幕》(S5) 独立集成：战技后全体增伤 16%。"""
        robin = self.db.to_combat_entity("知更鸟•晴歌")
        self.assertIsNotNone(robin.light_cone)
        self.assertIsInstance(robin.light_cone, MemoryNeverFadesHandler)
        self.assertEqual(robin.light_cone.superimposition, 5)

        dps = Entity(name="测试主C", base_speed=100.0)
        boss = Entity(name="测试首领", base_speed=90.0, is_enemy=True)
        sim = TurnSimulator(entities=[robin, dps, boss], auto_ult=False)

        # 施放战技
        sim.execute_current_turn(action_override=ActionKind.SKILL)

        # 队友应享受知更鸟战技 50% 增伤 + 光锥 16% 增伤 = 66% 增伤
        snap_dps = sim.query_status("测试主C")
        self.assertAlmostEqual(snap_dps["dmg_boost"], 0.66, places=2)

    def test_05_fengjin_rainbow_lightcone(self):
        """验证风堇与《愿虹光永驻天空》(S1) 独立集成：施法为敌方施加 18% 易伤。"""
        fengjin = self.db.to_combat_entity("风堇")
        self.assertIsNotNone(fengjin.light_cone)
        self.assertIsInstance(fengjin.light_cone, MayRainbowsRemainInTheSkyHandler)
        self.assertEqual(fengjin.light_cone.superimposition, 1)

        boss = Entity(name="测试首领", base_speed=90.0, is_enemy=True)
        sim = TurnSimulator(entities=[fengjin, boss], auto_ult=False)

        # 开局敌方易伤为 0
        snap_boss_before = sim.query_status("测试首领")
        self.assertEqual(snap_boss_before["vulnerability"], 0.0)

        # 施放战技
        sim.execute_current_turn(action_override=ActionKind.SKILL)

        # 敌方应受到 18% 易伤加深
        snap_boss_after = sim.query_status("测试首领")
        self.assertAlmostEqual(snap_boss_after["vulnerability"], 0.18, places=2)

    def test_06_decoupled_swappable_cross_character(self):
        """验证真正的解耦与自由插拔：将《如果时间是一朵花》(S5) 跨职业装配给常规主C。"""
        custom_char = Entity(name="异世界旅人", base_speed=130.0, base_crit_dmg=1.0, max_energy=100.0, energy=50.0)
        # 自由装配光锥
        custom_char.light_cone = LightConeRegistry.create("如果时间是一朵花", owner_id=custom_char.name, superimposition=5)
        boss = Entity(name="测试首领", base_speed=90.0, is_enemy=True)

        sim = TurnSimulator(entities=[custom_char, boss], auto_ult=False)

        # 进战回能：50 + 21 = 71 点
        self.assertEqual(custom_char.energy, 71.0)
        # 全队享受到 96% 暴伤
        snap = sim.query_status("异世界旅人")
        self.assertAlmostEqual(snap["current_crit_dmg"], 1.96, places=2)


if __name__ == "__main__":
    unittest.main()

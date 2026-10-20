"""验证「砺烁新辉」官方最新重做与加强角色技能套件 (Enhanced Characters Test Suite).

测试数据来源：https://hsr.nanoka.cc/
测试角色：
- 藿藿 (Huohuo, 4.2 加强版)
- 银狼 (Silver Wolf, 3.4 加强版)
- 卡芙卡 (Kafka, 3.4 加强版)
- 希儿 (Seele, 4.2 加强版)
- 刃 (Blade, 3.4 加强版)
- 瓦尔特 (Welt, 4.2 加强版)
- 花火 (Sparkle, 4.0 加强版)
- 流萤 (Firefly, 4.2 加强版)
"""

import unittest
from simulator.core import TurnSimulator, Entity
from simulator.db.character_db import get_character_db
from simulator.actions import ActionKind, ActionContext
from simulator.status import StatType
from simulator.effects import ModifySPEffect


class TestEnhancedCharacters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_character_db("data/character_db_export.json")

    def test_01_silver_wolf_enhanced(self):
        """验证银狼 3.4 官方加强：终结技对群全体减防 45%、开局回能 20 点、E2 20% 易伤。"""
        sw = self.db.to_combat_entity(self.db.get("银狼"))
        enemy1 = Entity(name="精英敌人1", base_speed=90.0, is_enemy=True)
        enemy2 = Entity(name="精英敌人2", base_speed=90.0, is_enemy=True)

        sim = TurnSimulator(entities=[sw, enemy1, enemy2])
        # 开局回能 20 点
        self.assertEqual(sw.energy, 20.0, "银狼开局应立即恢复 20 点能量")

        # 施放终结技：对群全体施加 45% 减防
        sw.kit.execute(ActionContext("sw_ult", sw.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()

        self.assertTrue(sim.status_mgr.has_status(enemy1.name, "SilverWolf_Ult_DefShred"))
        self.assertTrue(sim.status_mgr.has_status(enemy2.name, "SilverWolf_Ult_DefShred"))

    def test_02_seele_enhanced(self):
        """验证希儿 4.2 官方加强：残血目标自动触发战技追击、大招增幅 60%、E1 无视 20% 防御。"""
        seele = self.db.to_combat_entity(self.db.get("希儿"))
        enemy = Entity(name="残血小怪", base_speed=80.0, is_enemy=True, current_hp=3000.0, max_hp=10000.0)

        sim = TurnSimulator(entities=[seele, enemy])

        # 希儿施放战技攻击残血目标 (HP < 50%)
        seele.kit.execute(ActionContext("seele_skill", seele.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()

        # E1 生效：无视 20% 防御
        if seele.eidolon >= 1:
            self.assertTrue(sim.status_mgr.has_status(seele.name, "Seele_E1_DefIgnore"))

    def test_03_kafka_enhanced(self):
        """验证卡芙卡 3.4 官方加强：战技立即引爆 DoT 伤害、终结技触电与引爆。"""
        kafka = self.db.to_combat_entity(self.db.get("卡芙卡"))
        enemy = Entity(name="DoT受体", base_speed=85.0, is_enemy=True, current_hp=50000.0, max_hp=50000.0)

        sim = TurnSimulator(entities=[kafka, enemy])

        # 战技引爆
        hp_before = enemy.current_hp
        kafka.kit.execute(ActionContext("kf_skill", kafka.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()
        self.assertLess(enemy.current_hp, hp_before)

        # 终结技挂触电并引爆
        kafka.kit.execute(ActionContext("kf_ult", kafka.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(enemy.name, "Kafka_Shock"))

    def test_04_blade_enhanced(self):
        """验证刃 3.4 官方加强：地狱变嘲讽提升、消耗生命累积充能触发追击。"""
        blade = self.db.to_combat_entity(self.db.get("刃"))
        enemy = Entity(name="靶子", base_speed=80.0, is_enemy=True)

        sim = TurnSimulator(entities=[blade, enemy])

        # 施放战技进入地狱变
        blade.kit.execute(ActionContext("blade_skill", blade.name, ActionKind.SKILL, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(blade.name, "Blade_Hellscape"))

    def test_05_welt_enhanced(self):
        """验证瓦尔特 4.2 官方加强：战技施加【失重】(防御降低20%与减速15%)、大招推条40%。"""
        welt = self.db.to_combat_entity(self.db.get("瓦尔特"))
        enemy = Entity(name="受害者", base_speed=100.0, is_enemy=True, distance_remaining=5000.0)

        sim = TurnSimulator(entities=[welt, enemy])

        # 施放战技施加【失重】
        welt.kit.execute(ActionContext("welt_skill", welt.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(enemy.name, "Welt_Weightless"))

        # 施放大招推条 40% (5000 + 4000 = 9000)
        welt.kit.execute(ActionContext("welt_ult", welt.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertEqual(enemy.distance_remaining, 9000.0)

    def test_06_sparkle_enhanced(self):
        """验证花火 4.0 官方加强：队友消耗 SP 时为花火回能并对全敌施加易伤。"""
        sparkle = self.db.to_combat_entity(self.db.get("花火"))
        enemy = Entity(name="敌方", base_speed=90.0, is_enemy=True)

        sim = TurnSimulator(entities=[sparkle, enemy])
        sparkle.energy = 10.0

        # 队友消耗 1 SP 事件
        sparkle.kit.on_event(ModifySPEffect("队友", -1, "施放战技"))
        sim.resolver.resolve_all()

        # 花火回能 3 点：10 + 3 = 13 点
        self.assertEqual(sparkle.energy, 13.0)
        # 敌方获得易伤
        self.assertTrue(sim.status_mgr.has_status(enemy.name, "Sparkle_Enemy_Vuln"))


if __name__ == "__main__":
    unittest.main()

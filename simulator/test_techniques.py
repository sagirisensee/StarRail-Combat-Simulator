"""秘技执行系统 (Technique Execution Engine) 单元测试。"""
import unittest
from simulator.core import TurnSimulator, Entity
from simulator.actions import ActionKind
from simulator.combat_port import CombatPort
from simulator.kits.characters.sparkle import SparkleKit
from simulator.kits.characters.ruan_mei import RuanMeiKit
from simulator.kits.characters.acheron import AcheronKit
from simulator.kits.characters.tingyun import TingyunKit
from simulator.kits.characters.fuxuan import FuXuanKit
from simulator.kits.characters.silver_wolf import SilverWolfKit
from simulator.kits.characters.pela import PelaKit
from simulator.kits.characters.aventurine import AventurineKit
from simulator.status import StatType


class TestTechniqueEngine(unittest.TestCase):
    def test_sparkle_technique_recovers_sp(self):
        """测试花火秘技【不可靠叙事者】：开战额外恢复 3 点 SP。"""
        sparkle = Entity(name="花火", base_speed=160.0)
        sparkle.kit = SparkleKit("花火", None, eidolon=0)

        # 初始 3 点 SP，未放秘技时为 3 点
        sim_no_tech = TurnSimulator(entities=[sparkle], initial_sp=3, use_techniques=False)
        self.assertEqual(sim_no_tech.sp.current_sp, 3)

        # 施放秘技后：3 + 3 = 6 点 SP (花火天赋将上限扩至 7 点)
        sparkle2 = Entity(name="花火", base_speed=160.0)
        sparkle2.kit = SparkleKit("花火", None, eidolon=0)
        sim_tech = TurnSimulator(entities=[sparkle2], initial_sp=3, use_techniques=True)
        self.assertEqual(sim_tech.sp.current_sp, 6)

    def test_ruan_mei_technique_auto_skill(self):
        """测试阮•梅秘技【拭琴抚罗袂】：开战自动展开战技结界。"""
        rm = Entity(name="阮•梅", base_speed=140.0)
        ally = Entity(name="主C", base_speed=120.0)
        rm.kit = RuanMeiKit("阮•梅", None, eidolon=1)

        sim = TurnSimulator(entities=[rm, ally], use_techniques=True, technique_users=["阮•梅"])
        # 阮•梅战技结界应该已生效于全队
        self.assertTrue(sim.port.has_status("主C", RuanMeiKit.SKILL_BUFF))

    def test_acheron_technique_slashed_dreams(self):
        """测试黄泉秘技【四相断我】：开战获得 2 点残梦，并对敌方造成削韧。"""
        acheron = Entity(name="黄泉", base_speed=101.0)
        acheron.kit = AcheronKit("黄泉", None, eidolon=0)

        enemy = Entity(name="精英怪", base_speed=100.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        enemy.max_toughness = 60.0
        enemy.current_toughness = 60.0

        sim = TurnSimulator(entities=[acheron, enemy], use_techniques=True, technique_users=["黄泉"])
        
        # 黄泉获得 2 点残梦
        self.assertEqual(acheron.kit.slashed_dream, 2)
        # 敌人韧性受到 20 点削减 (无视弱点削韧)
        self.assertEqual(enemy.current_toughness, 40.0)

    def test_tingyun_technique_energy(self):
        """测试停云秘技【惠风和畅】：开战立即回复 50 点能量。"""
        tingyun = Entity(name="停云", base_speed=150.0, max_energy=130.0)
        tingyun.energy = 0.0
        tingyun.kit = TingyunKit("停云", None, eidolon=6)

        sim = TurnSimulator(entities=[tingyun], use_techniques=True, technique_users=["停云"])
        self.assertAlmostEqual(tingyun.energy, 50.0, places=1)

    def test_fuxuan_technique_matrix(self):
        """测试符玄秘技【岁记否泰】：开战自动开启穷观阵。"""
        fuxuan = Entity(name="符玄", base_speed=140.0)
        fuxuan.kit = FuXuanKit("符玄", None, eidolon=1)

        sim = TurnSimulator(entities=[fuxuan], use_techniques=True, technique_users=["符玄"])
        self.assertTrue(sim.port.has_status("符玄", FuXuanKit.MATRIX_BUFF))

    def test_silver_wolf_and_pela_techniques(self):
        """测试银狼与佩拉削韧及减防秘技。"""
        sw = Entity(name="银狼", base_speed=150.0)
        sw.kit = SilverWolfKit("银狼", None, eidolon=2)

        pela = Entity(name="佩拉", base_speed=140.0)
        pela.kit = PelaKit("佩拉", None, eidolon=6)

        enemy = Entity(name="首领怪", base_speed=90.0, max_hp=200000.0, current_hp=200000.0, is_enemy=True)
        enemy.max_toughness = 100.0
        enemy.current_toughness = 100.0

        sim = TurnSimulator(
            entities=[sw, pela, enemy],
            use_techniques=True,
            technique_users=["银狼", "佩拉"]
        )

        # 银狼无视弱点削韧 20 点
        self.assertEqual(enemy.current_toughness, 80.0)
        # 佩拉全体减防 20%
        self.assertTrue(sim.port.has_status("首领怪", "Pela_Technique_DefShred"))


if __name__ == "__main__":
    unittest.main()

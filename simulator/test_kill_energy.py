# coding: utf-8
"""击杀回能测试: 击败敌方目标时击杀者恢复 10 点能量 (受 ERR 放大), 忆灵击杀归主人。"""
import unittest

from simulator.core import TurnSimulator, Entity
from simulator.status import StatType


def _make_sim():
    hero = Entity(name="测试主C", base_speed=120.0, base_atk=1500.0, max_hp=5000.0, current_hp=5000.0, max_energy=120.0)
    spirit = Entity(
        name="测试忆灵",
        base_speed=120.0,
        base_atk=1500.0,
        max_hp=3000.0,
        current_hp=3000.0,
        is_memosprite=True,
        master_name="测试主C",
    )
    enemy = Entity(name="残血敌人", base_speed=90.0, max_hp=100.0, current_hp=100.0, is_enemy=True)
    sim = TurnSimulator(entities=[hero, spirit, enemy], auto_ult=False)
    return sim


class TestKillEnergy(unittest.TestCase):
    def test_killer_gains_energy_on_kill(self):
        sim = _make_sim()
        hero = sim.get_entity("测试主C")
        hero.energy = 0.0
        err = sim.port.stat("测试主C", StatType.ERR) or 1.0
        sim.port.attack("测试主C", "残血敌人", element="Ice", atk_multiplier=50.0, toughness_damage=0.0)
        sim.resolver.resolve_all()
        self.assertEqual(sim.get_entity("残血敌人").current_hp, 0.0)
        self.assertAlmostEqual(hero.energy, 10.0 * err, delta=0.6)

    def test_no_energy_when_target_survives(self):
        sim = _make_sim()
        hero = sim.get_entity("测试主C")
        hero.energy = 0.0
        sim.port.attack("测试主C", "残血敌人", element="Ice", atk_multiplier=0.01, toughness_damage=0.0)
        sim.resolver.resolve_all()
        self.assertGreater(sim.get_entity("残血敌人").current_hp, 0.0)
        self.assertAlmostEqual(hero.energy, 0.0, delta=0.01)

    def test_memosprite_kill_grants_master(self):
        sim = _make_sim()
        hero = sim.get_entity("测试主C")
        hero.energy = 0.0
        err = sim.port.stat("测试主C", StatType.ERR) or 1.0
        sim.port.attack("测试忆灵", "残血敌人", element="Ice", atk_multiplier=50.0, toughness_damage=0.0, scaling_stat="hp")
        sim.resolver.resolve_all()
        self.assertEqual(sim.get_entity("残血敌人").current_hp, 0.0)
        self.assertAlmostEqual(hero.energy, 10.0 * err, delta=0.6)


if __name__ == "__main__":
    unittest.main()

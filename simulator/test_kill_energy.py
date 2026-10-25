# coding: utf-8
"""击杀回能测试: 击败敌方目标时击杀者恢复 10 点能量 (受 ERR 放大), 忆灵击杀归主人。"""
import unittest

from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.status import StatType


def _make_sim():
    db = CharacterDB().load("data/character_db_export.json")
    cyy = db.to_combat_entity("长夜月")
    enemy = Entity(name="残血敌人", base_speed=90.0, max_hp=100.0, current_hp=100.0, is_enemy=True)
    sim = TurnSimulator(entities=[cyy, enemy], auto_ult=False)
    return sim


class TestKillEnergy(unittest.TestCase):
    def test_killer_gains_energy_on_kill(self):
        sim = _make_sim()
        hero = sim.get_entity("长夜月")
        hero.energy = 0.0
        err = sim.port.stat("长夜月", StatType.ERR) or 1.0
        sim.port.attack("长夜月", "残血敌人", element="Ice", atk_multiplier=50.0, toughness_damage=0.0)
        sim.resolver.resolve_all()
        self.assertEqual(sim.get_entity("残血敌人").current_hp, 0.0)
        self.assertAlmostEqual(hero.energy, 10.0 * err, delta=0.6)

    def test_no_energy_when_target_survives(self):
        sim = _make_sim()
        hero = sim.get_entity("长夜月")
        hero.energy = 0.0
        sim.port.attack("长夜月", "残血敌人", element="Ice", atk_multiplier=0.01, toughness_damage=0.0)
        sim.resolver.resolve_all()
        self.assertGreater(sim.get_entity("残血敌人").current_hp, 0.0)
        self.assertAlmostEqual(hero.energy, 0.0, delta=0.01)

    def test_memosprite_kill_grants_master(self):
        sim = _make_sim()
        spirit = sim.get_entity("长夜")
        self.assertIsNotNone(spirit, "长夜月进战应召唤长夜")
        hero = sim.get_entity("长夜月")
        hero.energy = 0.0
        err = sim.port.stat("长夜月", StatType.ERR) or 1.0
        sim.port.attack("长夜", "残血敌人", element="Ice", atk_multiplier=50.0, toughness_damage=0.0, scaling_stat="hp")
        sim.resolver.resolve_all()
        self.assertEqual(sim.get_entity("残血敌人").current_hp, 0.0)
        self.assertAlmostEqual(hero.energy, 10.0 * err, delta=0.6)


if __name__ == "__main__":
    unittest.main()

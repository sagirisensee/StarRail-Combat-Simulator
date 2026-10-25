# coding: utf-8
"""DamageType 伤害分类枚举回归测试: 官方分类映射、管线传递与历史字符串收编。"""
import unittest
from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.actions import DamageType
from simulator.events import DamageAppliedEvent


class TestDamageTypeTaxonomy(unittest.TestCase):
    def test_from_tag_canonical_mapping(self):
        self.assertEqual(DamageType.from_tag("BasicAttack"), DamageType.BASIC)
        self.assertEqual(DamageType.from_tag("Skill"), DamageType.SKILL)
        self.assertEqual(DamageType.from_tag("Ultimate"), DamageType.ULTIMATE)
        self.assertEqual(DamageType.from_tag("AdditionalDamage"), DamageType.ADDITIONAL)
        self.assertEqual(DamageType.from_tag("FollowUpAttack"), DamageType.FOLLOW_UP)
        self.assertEqual(DamageType.from_tag("MemospriteSkill"), DamageType.SERVANT)
        self.assertEqual(DamageType.from_tag("dot"), DamageType.DOT)
        self.assertEqual(DamageType.from_tag("Technique"), DamageType.TECHNIQUE)

    def test_from_tag_legacy_character_flavored_labels(self):
        # 历史角色专属/同义标签一律收编到官方分类, 不再各行其是
        self.assertEqual(DamageType.from_tag("YanqingFollowUp"), DamageType.FOLLOW_UP)
        self.assertEqual(DamageType.from_tag("MoonlightUlt"), DamageType.ULTIMATE)
        self.assertEqual(DamageType.from_tag("MemospriteUltimate"), DamageType.SERVANT)
        self.assertEqual(DamageType.from_tag("SwordStance"), DamageType.ADDITIONAL)
        self.assertEqual(DamageType.from_tag("EnhancedBasic_Blast"), DamageType.BASIC)
        self.assertEqual(DamageType.from_tag("DoT_Detonation"), DamageType.DOT)

    def test_from_tag_fallback_and_passthrough(self):
        self.assertEqual(DamageType.from_tag("no_such_tag"), DamageType.DIRECT)
        self.assertEqual(DamageType.from_tag(""), DamageType.DIRECT)
        self.assertEqual(DamageType.from_tag(None), DamageType.DIRECT)
        self.assertEqual(DamageType.from_tag(DamageType.TRUE), DamageType.TRUE)

    def test_event_post_init_normalizes_type(self):
        ev = DamageAppliedEvent(
            av=0.0, cycle=0, attacker_name="A", target_name="B",
            damage=1.0, is_crit=False, breakdown=None, target_hp_left=0.0,
            damage_tag="dot",
        )
        self.assertEqual(ev.damage_type, DamageType.DOT)

    def test_port_attack_pipeline_carries_enum(self):
        db = CharacterDB().load("data/character_db_export.json")
        cyy = db.to_combat_entity("长夜月")
        enemy = Entity(name="木桩", base_speed=90.0, max_hp=10000000.0, current_hp=10000000.0, is_enemy=True)
        enemy.is_infinite_hp = True
        sim = TurnSimulator(entities=[cyy, enemy], auto_ult=False)

        seen = []
        sim.event_bus.subscribe(DamageAppliedEvent, lambda e: seen.append(e))

        sim.port.attack("长夜月", "木桩", element="Ice", atk_multiplier=1.0, toughness_damage=0.0, damage_type=DamageType.FOLLOW_UP)
        sim.port.attack("长夜月", "木桩", element="Ice", atk_multiplier=1.0, toughness_damage=0.0, damage_tag="YanqingFollowUp")
        sim.port.attack("长夜月", "木桩", element="Ice", atk_multiplier=1.0, toughness_damage=0.0)
        sim.resolver.resolve_all()

        types = [e.damage_type for e in seen]
        self.assertEqual(types, [DamageType.FOLLOW_UP, DamageType.FOLLOW_UP, DamageType.DIRECT])
        self.assertEqual(seen[0].damage_tag, "Follow-Up")


if __name__ == "__main__":
    unittest.main()

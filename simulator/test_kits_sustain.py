"""生存位 (Preservation & Abundance) 技能套件全面测试集 (Sustain Kits Test Suite)."""

import unittest
from simulator.core import TurnSimulator, Entity
from simulator.db.character_db import get_character_db
from simulator.actions import ActionKind, ActionContext
from simulator.status import StatType
from simulator.effects import ApplyDamageEffect, DamageRequest


class TestSustainKits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_character_db("data/character_db_export.json")

    def test_01_fuxuan_matrix_and_damage_share(self):
        """验证符玄穷观阵暴击暴伤加成、65%伤害分摊与半血生命逆转。"""
        fx_prof = self.db.get("符玄")
        fuxuan = self.db.to_combat_entity(fx_prof)
        ally = Entity(name="受保护队友", base_speed=100.0, current_hp=5000.0, max_hp=5000.0)
        boss = Entity(name="Boss", base_speed=90.0, is_enemy=True, base_atk=2000.0)

        sim = TurnSimulator(entities=[fuxuan, ally, boss])

        # 1. 战技开启穷观阵
        fuxuan.kit.execute(ActionContext("fx_skill", fuxuan.name, ActionKind.SKILL, target_ids=()))
        sim.resolver.resolve_all()

        # 验证暴击率 +12% 与 E1 暴伤 +30%
        self.assertAlmostEqual(ally.crit_rate, ally.base_crit_rate + 0.12, places=2)
        if fuxuan.eidolon >= 1:
            self.assertAlmostEqual(ally.crit_dmg, ally.base_crit_dmg + 0.30, places=2)

        # 2. Boss 攻击队友：验证 65% 伤害分摊给符玄
        fuxuan_orig_hp = fuxuan.current_hp
        ally_orig_hp = ally.current_hp

        # 入队 1000 点物理伤害
        req = DamageRequest(attacker=boss, target=ally, skill_multiplier=1.0)
        sim.resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
        sim.resolver.resolve_all()

        # 队友只承受约 35% 伤害，符玄承受约 65% 伤害
        self.assertLess(fuxuan.current_hp, fuxuan_orig_hp)
        self.assertLess(ally.current_hp, ally_orig_hp)

    def test_02_aventurine_shield_and_absorption(self):
        """验证砂金全队坚垣筹码护盾与优先抵扣伤害机制 (含未拥有角色实现)。"""
        from simulator.kits.registry import get_kit_class
        aventurine_cls = get_kit_class("砂金")
        self.assertIsNotNone(aventurine_cls)

        aventurine = Entity(name="砂金", base_speed=106.0, avatar_id=1304)
        aventurine.kit = aventurine_cls(owner_id=aventurine.name, port=None, eidolon=1)
        ally = Entity(name="队友", base_speed=100.0, current_hp=4000.0, max_hp=4000.0)
        boss = Entity(name="Boss", base_speed=90.0, is_enemy=True, base_atk=1000.0)

        sim = TurnSimulator(entities=[aventurine, ally, boss])

        # 施放战技上盾
        aventurine.kit.execute(ActionContext("av_skill", aventurine.name, ActionKind.SKILL, target_ids=()))
        sim.resolver.resolve_all()

        self.assertGreater(ally.shield, 1000.0)
        orig_shield = ally.shield

        # Boss 造成 500 点伤害 -> 护盾吸收，生命值丝毫不掉
        req = DamageRequest(attacker=boss, target=ally, skill_multiplier=0.5)
        sim.resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
        sim.resolver.resolve_all()

        self.assertEqual(ally.current_hp, 4000.0, "护盾吸收下生命值不应被扣减")
        self.assertLess(ally.shield, orig_shield)

    def test_03_huohuo_heal_and_recharge(self):
        """验证藿藿单体治疗、禳命 E1 提速 12% 与大招全队回能。"""
        hh_prof = self.db.get("藿藿")
        huohuo = self.db.to_combat_entity(hh_prof)
        ally = Entity(name="断能主C", base_speed=100.0, energy=0.0, max_energy=120.0, current_hp=2000.0, max_hp=5000.0)

        sim = TurnSimulator(entities=[huohuo, ally])

        # 战技治疗与禳命
        huohuo.kit.execute(ActionContext("hh_skill", huohuo.name, ActionKind.SKILL, target_ids=(ally.name,)))
        sim.resolver.resolve_all()

        self.assertGreater(ally.current_hp, 2000.0)
        # E1 禳命提速 12%
        if huohuo.eidolon >= 1:
            self.assertAlmostEqual(ally.speed, 112.0, places=1)

        # 终结技全队回能 20%
        huohuo.kit.execute(ActionContext("hh_ult", huohuo.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertGreater(ally.energy, 20.0)

    def test_04_luocha_field(self):
        """验证罗刹白花之刻与结界展开。"""
        luocha_prof = self.db.get("罗刹")
        luocha = self.db.to_combat_entity(luocha_prof)
        ally = Entity(name="残血队友", base_speed=100.0, current_hp=1000.0, max_hp=4000.0)

        sim = TurnSimulator(entities=[luocha, ally])

        # 施放战技
        luocha.kit.execute(ActionContext("lc_skill", luocha.name, ActionKind.SKILL, target_ids=(ally.name,)))
        sim.resolver.resolve_all()
        self.assertEqual(ally.current_hp, 4000.0)
        self.assertEqual(luocha.kit.abyss_flower, 1)

        # 施放大招触发结界
        luocha.kit.execute(ActionContext("lc_ult", luocha.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(ally.name, "Luocha_Cycle_Of_Life"))

    def test_05_gepard_and_bailu_and_lingsha(self):
        """验证杰帕德大招巨额护盾、白露群体治疗与生息、灵砂醇醉易伤。"""
        gepard = self.db.to_combat_entity(self.db.get("杰帕德"))
        bailu = self.db.to_combat_entity(self.db.get("白露"))
        lingsha = self.db.to_combat_entity(self.db.get("灵砂"))
        enemy = Entity(name="敌人", base_speed=80.0, is_enemy=True)

        sim = TurnSimulator(entities=[gepard, bailu, lingsha, enemy])

        # 杰帕德大招护盾
        gepard.kit.execute(ActionContext("gep_ult", gepard.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertGreater(gepard.shield, 2000.0)

        # 白露大招治疗与生息
        bailu.kit.execute(ActionContext("bl_ult", bailu.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(gepard.name, "Bailu_Invigoration"))

        # 灵砂大招醇醉易伤
        lingsha.kit.execute(ActionContext("ls_ult", lingsha.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(enemy.name, "Lingsha_Intoxicated"))


if __name__ == "__main__":
    unittest.main()

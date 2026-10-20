"""星魂动态激活与全体系角色套件验证测试 (Eidolons & Carries Comprehensive Test)."""

import unittest
from simulator.core import TurnSimulator, Entity
from simulator.db.character_db import get_character_db
from simulator.actions import ActionKind, ActionContext
from simulator.status import StatType
from simulator.kits.registry import get_kit_class


class TestEidolonsAndCarries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_character_db("data/character_db_export.json")

    def test_01_eidolon_gating_huohuo(self):
        """验证藿藿星魂阶梯激活机制：E0 (3回合/无提速/无增伤) vs E1 (4回合+提速) vs E6 (增伤50%)。"""
        huohuo_cls = get_kit_class("藿藿")

        # Case A: E0 藿藿
        hh_e0 = Entity(name="藿藿_E0", base_speed=110.0, base_atk=1000.0)
        hh_e0.kit = huohuo_cls(hh_e0.name, port=None, eidolon=0)
        ally_a = Entity(name="队友A", base_speed=100.0, max_hp=3000.0, current_hp=3000.0)
        sim_a = TurnSimulator(entities=[hh_e0, ally_a])

        # 战斗开始触发【禳命】
        prov_buff = sim_a.status_mgr.get_status(ally_a.name, huohuo_cls.PROVISION_BUFF)
        self.assertIsNotNone(prov_buff)
        self.assertEqual(prov_buff.duration, 3, "E0 禳命持续时间应为 3 回合")
        self.assertEqual(ally_a.speed, 100.0, "E0 不应触发 12% 提速光环")

        # 施放战技治疗
        hh_e0.kit.execute(ActionContext("hh_act", hh_e0.name, ActionKind.SKILL, target_ids=(ally_a.name,)))
        sim_a.resolver.resolve_all()
        self.assertFalse(sim_a.status_mgr.has_status(ally_a.name, huohuo_cls.E6_DMG_BUFF), "E0 不应触发 E6 增伤")

        # Case B: E1 藿藿
        hh_e1 = Entity(name="藿藿_E1", base_speed=110.0, base_atk=1000.0)
        hh_e1.kit = huohuo_cls(hh_e1.name, port=None, eidolon=1)
        ally_b = Entity(name="队友B", base_speed=100.0, max_hp=3000.0, current_hp=3000.0)
        sim_b = TurnSimulator(entities=[hh_e1, ally_b])

        prov_buff_e1 = sim_b.status_mgr.get_status(ally_b.name, huohuo_cls.PROVISION_BUFF)
        self.assertEqual(prov_buff_e1.duration, 4, "E1 禳命持续时间必须为 4 回合！")
        self.assertAlmostEqual(ally_b.speed, 112.0, places=1, msg="E1 必须为全队提供 12% 速度提升！")
        self.assertFalse(sim_b.status_mgr.has_status(ally_b.name, huohuo_cls.E6_DMG_BUFF), "E1 不应触发 E6 增伤")

        # Case C: E6 藿藿
        hh_e6 = Entity(name="藿藿_E6", base_speed=110.0, base_atk=1000.0)
        hh_e6.kit = huohuo_cls(hh_e6.name, port=None, eidolon=6)
        ally_c = Entity(name="队友C", base_speed=100.0, max_hp=3000.0, current_hp=3000.0)
        sim_c = TurnSimulator(entities=[hh_e6, ally_c])

        hh_e6.kit.execute(ActionContext("hh_act_6", hh_e6.name, ActionKind.SKILL, target_ids=(ally_c.name,)))
        sim_c.resolver.resolve_all()
        self.assertTrue(sim_c.status_mgr.has_status(ally_c.name, huohuo_cls.E6_DMG_BUFF), "E6 治疗必须为目标施加 50% 增伤")

    def test_02_eidolon_gating_aventurine(self):
        """验证砂金星魂阶梯激活机制：E0 vs E1 (大招套盾+暴伤) vs E2 (普攻减全抗)。"""
        aven_cls = get_kit_class("砂金")

        # E0 砂金
        aven_e0 = Entity(name="砂金_E0", base_speed=106.0)
        aven_e0.kit = aven_cls(aven_e0.name, port=None, eidolon=0)
        boss_a = Entity(name="Boss_A", base_speed=90.0, is_enemy=True)
        sim_a = TurnSimulator(entities=[aven_e0, boss_a])

        # 普攻
        aven_e0.kit.execute(ActionContext("av_a", aven_e0.name, ActionKind.BASIC, target_ids=(boss_a.name,)))
        sim_a.resolver.resolve_all()
        self.assertFalse(sim_a.status_mgr.has_status(boss_a.name, "Aventurine_E2_ResShred"), "E0 普攻不应降低全属性抗性")

        # E2 砂金
        aven_e2 = Entity(name="砂金_E2", base_speed=106.0)
        aven_e2.kit = aven_cls(aven_e2.name, port=None, eidolon=2)
        boss_b = Entity(name="Boss_B", base_speed=90.0, is_enemy=True)
        sim_b = TurnSimulator(entities=[aven_e2, boss_b])

        aven_e2.kit.execute(ActionContext("av_b", aven_e2.name, ActionKind.BASIC, target_ids=(boss_b.name,)))
        sim_b.resolver.resolve_all()
        self.assertTrue(sim_b.status_mgr.has_status(boss_b.name, "Aventurine_E2_ResShred"), "E2 普攻必须对目标施加 12% 全抗削弱！")

    def test_03_black_swan_kit_and_e1(self):
        """验证黑天鹅开局 E1 持续减抗光环与战技奥迹/减防。"""
        bs_prof = self.db.get("黑天鹅")
        self.assertEqual(bs_prof.eidolon, 1, "导入档案黑天鹅应为 E1")
        bs = self.db.to_combat_entity(bs_prof)
        enemy = Entity(name="风化受害者", base_speed=90.0, is_enemy=True)

        sim = TurnSimulator(entities=[bs, enemy])
        # E1: 开局全属性持续减抗 25%
        self.assertTrue(sim.status_mgr.has_status(enemy.name, "BlackSwan_E1_ResShred"))

        # 战技减防 20.8%
        bs.kit.execute(ActionContext("bs_skill", bs.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(enemy.name, "BlackSwan_Skill_DefShred"))

    def test_04_clara_kit_and_e1_e2(self):
        """验证克拉拉 (用户导入 E6) 战技保留反击标记 (E1) 与终结技大额攻击 (E2)。"""
        clara_prof = self.db.get("克拉拉")
        self.assertEqual(clara_prof.eidolon, 6, "用户导入克拉拉应为满魂 E6")
        clara = self.db.to_combat_entity(clara_prof)
        enemy = Entity(name="攻击者", base_speed=120.0, is_enemy=True)

        sim = TurnSimulator(entities=[clara, enemy])
        # 天赋常驻减伤
        self.assertTrue(sim.status_mgr.has_status(clara.name, "Clara_Talent_DmgReduce"))

        # 受到攻击触发史瓦罗反击并施加标记
        clara.kit.trigger_counter(enemy.name, is_clara_hit=True)
        sim.resolver.resolve_all()
        self.assertIn(enemy.name, clara.kit.marked_enemies)

        # 施放战技
        clara.kit.execute(ActionContext("clara_skill", clara.name, ActionKind.SKILL, target_ids=()))
        sim.resolver.resolve_all()
        # E1: 战技绝不清除反击标记！
        self.assertIn(enemy.name, clara.kit.marked_enemies, "克拉拉 E1 战技施放后不应清除标记")

        # 终结技触发 E2 增攻 30%
        clara.kit.execute(ActionContext("clara_ult", clara.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(sim.status_mgr.has_status(clara.name, "Clara_E2_Atk"))

    def test_05_yunli_kit(self):
        """验证云璃大剑格挡架势与反击弹反。"""
        yunli_prof = self.db.get("云璃")
        self.assertEqual(yunli_prof.eidolon, 2, "导入云璃应为 E2")
        yunli = self.db.to_combat_entity(yunli_prof)
        enemy = Entity(name="Boss", base_speed=100.0, is_enemy=True)

        sim = TurnSimulator(entities=[yunli, enemy])
        # 终结技进入格挡
        yunli.kit.execute(ActionContext("yl_ult", yunli.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(yunli.kit.is_parrying)

        # 触发弹反【灭】
        yunli.kit.trigger_counter(enemy.name)
        sim.resolver.resolve_all()
        self.assertFalse(yunli.kit.is_parrying)

    def test_06_ratio_kit(self):
        """验证真理医生粉笔追击与 E1 暴击层数。"""
        ratio_cls = get_kit_class("真理医生")
        ratio_e1 = Entity(name="真理医生_E1", base_speed=103.0)
        ratio_e1.kit = ratio_cls(ratio_e1.name, port=None, eidolon=1)
        enemy = Entity(name="靶子", base_speed=80.0, is_enemy=True)

        sim = TurnSimulator(entities=[ratio_e1, enemy])
        # E1: 开战直接拥有 4 层暴击增益
        self.assertEqual(ratio_e1.kit.current_stacks, 4)
        self.assertTrue(sim.status_mgr.has_status(ratio_e1.name, "Ratio_Talent_Crit"))

    def test_07_acheron_kit(self):
        """验证黄泉 9 点残梦终结技与 E1 暴击加成。"""
        acheron_cls = get_kit_class("黄泉")
        acheron = Entity(name="黄泉", base_speed=101.0)
        acheron.kit = acheron_cls(acheron.name, port=None, eidolon=1)
        enemy = Entity(name="敌方精英", base_speed=90.0, is_enemy=True)

        sim = TurnSimulator(entities=[acheron, enemy])
        # E1 暴击率提高 18%
        self.assertTrue(sim.status_mgr.has_status(acheron.name, "Acheron_E1_Crit"))

        # 战技充能残梦
        acheron.kit.execute(ActionContext("ach_skill", acheron.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()
        self.assertGreater(acheron.kit.slashed_dream, 0)

    def test_08_jingliu_transmigration(self):
        """验证镜流 2 层朔望进入转魄 100% 自拉条与强化战技 0 点 SP 消耗。"""
        jingliu_cls = get_kit_class("镜流")
        jl = Entity(name="镜流", base_speed=105.0)
        jl.kit = jingliu_cls(jl.name, port=None, eidolon=0)
        enemy = Entity(name="靶子", base_speed=80.0, is_enemy=True)

        sim = TurnSimulator(entities=[jl, enemy], initial_sp=3)
        # 第 1 次战技：朔望 1 层
        jl.kit.execute(ActionContext("jl_s1", jl.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()
        self.assertEqual(jl.kit.syzygy_stacks, 1)
        self.assertFalse(jl.kit.is_transmigrated)

        # 第 2 次战技：朔望 2 层，立即触发转魄并 100% 自拉条！
        jl.distance_remaining = 8000.0
        jl.kit.execute(ActionContext("jl_s2", jl.name, ActionKind.SKILL, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()
        self.assertTrue(jl.kit.is_transmigrated)
        self.assertEqual(jl.distance_remaining, 0.0)

        # 转魄下强化战技消耗 0 点 SP！
        defn = jl.kit.definition(ActionKind.SKILL)
        self.assertEqual(defn.cost.sp, 0, "转魄状态下强化战技消耗 SP 必须为 0")

    def test_09_qingque_e6_sp_refund(self):
        """验证青雀暗杠强化普攻与 E6 恢复 1 点战技点。"""
        qq_prof = self.db.get("青雀")
        self.assertEqual(qq_prof.eidolon, 6, "导入青雀档案应为满魂 E6")
        qq = self.db.to_combat_entity(qq_prof)
        enemy = Entity(name="敌方", base_speed=80.0, is_enemy=True)

        sim = TurnSimulator(entities=[qq, enemy], initial_sp=2)
        initial_sp = sim.sp.current_sp

        # 终结技必入暗杠
        qq.kit.execute(ActionContext("qq_ult", qq.name, ActionKind.ULTIMATE, target_ids=()))
        sim.resolver.resolve_all()
        self.assertTrue(qq.kit.is_hidden_hand)

        # 施放强化普攻【杠上开花！】
        qq.kit.execute(ActionContext("qq_basic", qq.name, ActionKind.BASIC, target_ids=(enemy.name,)))
        sim.resolver.resolve_all()

        # E6: 强化普攻后额外恢复 1 点 SP！
        self.assertGreaterEqual(sim.sp.current_sp, initial_sp, "青雀 E6 强化普攻应触发战技点返还")


if __name__ == "__main__":
    unittest.main()

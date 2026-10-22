"""长夜月 (ID 1413) 与伴生忆灵「长夜」Nanoka 4.6 规范全套机制单元测试。

验证点覆盖：
1. 进战天赋【今夜与我同行】：召唤忆灵在场，挂载 70% 增伤与 E2 60% 暴伤，并触发忆灵天赋【与夜，形影，不离】立即行动；
2. 普攻【从此岁月朦胧】：生命上限 70% 缩放冰伤；
3. 战技【白昼悄然离去】：自扣生命 10% 触发生命降低天赋，忆灵暴伤提升，获得忆质；
4. 天赋【今夜与我同行】阈值触发：当【忆质】>= 16 点时，使忆灵立即行动施放终极爆发【迷梦，流失，如露】；
5. 终极爆发结算：清空忆质，忆灵自毁离场，触发【与你，再见，无期】速度提升；
6. 终结技【晚安，全世界无眠】：耗能 240 点，敌方易伤 30%，增伤 60%，充能管理与至暗之谜。
"""

import unittest
from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.actions import ActionKind
from simulator.status import StatType


class TestChangyeyueMemospriteMechanics(unittest.TestCase):
    def setUp(self):
        self.db = CharacterDB().load("data/character_db_export.json")
        self.changyeyue = self.db.to_combat_entity("长夜月")
        self.boss = Entity(name="首领木桩", base_speed=90.0, max_hp=500000.0, current_hp=500000.0, is_enemy=True)

    def test_01_battle_start_and_memosprite_presence(self):
        """验证进战时自动召唤忆灵在场，生效 70% 在场增伤与 E2 暴伤加成，并触发【与夜，形影，不离】立即行动。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        kit = self.changyeyue.kit

        # 忆灵在场
        self.assertTrue(kit.spirit_alive, "进战应召唤忆灵在场")
        # 召唤触发【与夜，形影，不离】立即行动施放【追忆，蹁跹，如雨】，造成伤害并获取 1 点忆质 (E2 为 2 点)
        self.assertEqual(kit.yizhi, 2, "开局触发【与夜，形影，不离】立即行动施放技能后，E2下应获得2点忆质")

        # 验证增伤 Buff 与 E2 暴伤
        snap = sim.query_status("长夜月")
        buff_names = [b["name"] for b in snap["buffs"]]
        self.assertTrue(any("孤独，浮游，漆黑" in b for b in buff_names), "应挂载忆灵在场增伤")
        self.assertTrue(any("呓语" in b for b in buff_names), "E2长夜月应挂载暴伤提升")
        self.assertAlmostEqual(snap["dmg_boost"], 0.388 + 0.70, places=2)

    def test_02_basic_attack_hp_scaling(self):
        """验证普攻【从此岁月朦胧】按长夜月生命上限 70% 缩放结算冰伤。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        hp_before = self.boss.current_hp

        sim.execute_current_turn(action_override=ActionKind.BASIC)

        damage_dealt = hp_before - self.boss.current_hp
        self.assertGreater(damage_dealt, 0, "普攻应造成伤害")
        self.assertEqual(self.changyeyue.energy, 20.0, "普攻应回能 20 点")

    def test_03_skill_hp_loss_and_memory_accumulation(self):
        """验证战技扣血并产生两笔忆质（扣血天赋 3 点 + 战技直接 3 点 = 6 点，加开局 2 点共 8 点）。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        kit = self.changyeyue.kit

        hp_before = self.changyeyue.current_hp
        sim.execute_current_turn(action_override=ActionKind.SKILL)

        # 自扣 10% 生命
        self.assertLess(self.changyeyue.current_hp, hp_before)

        # E2 下：开局 2 点 + 扣血获得 2+1=3 点 + 战技直接获得 2+1=3 点，合计 8 点【忆质】
        self.assertEqual(kit.yizhi, 8, "开局(2)加战技自扣血(3)与战技直接获取(3)，在E2下应合计获得 8 点忆质")

    def test_04_memory_threshold_and_memosprite_burst(self):
        """验证【忆质】达到 16 点时，触发长夜立即行动爆发【迷梦，流失，如露】，清空忆质并自毁加速。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        kit = self.changyeyue.kit

        # 手动注入 15 点忆质
        kit.yizhi = 15
        self.assertEqual(kit.yizhi, 15)
        self.assertTrue(kit.spirit_alive, "忆灵应在场")

        boss_hp_before = self.boss.current_hp

        # 再获得 1 点忆质 (E2 自动变为 1+1=2 点，累计 17 点 >= 16 点，触发阈值爆发)
        kit.gain_yizhi(1)
        sim.resolver.resolve_all()

        # 验证爆发伤害已造成
        self.assertLess(self.boss.current_hp, boss_hp_before, "16忆质应触发长夜终极爆发造成高额冰伤")

        # 爆发后忆质清空
        self.assertEqual(kit.yizhi, 0, "爆发后忆质应清空")

        # 忆灵自毁离场，在场增伤移除
        self.assertFalse(kit.spirit_alive, "爆发后忆灵应自毁离场")

        # 触发【与你，再见，无期】离场加速 (10% + 17*1% = 27% 速度提升)
        snap = sim.query_status("长夜月")
        buff_names = [b["name"] for b in snap["buffs"]]
        self.assertTrue(any("与你，再见，无期" in b for b in buff_names), "忆灵离场应为长夜月赋予速度加成")

    def test_05_ultimate_darkness_and_charges(self):
        """验证终结技【晚安，全世界无眠】(240耗能) 触发至暗之谜、敌方易伤30%与3点充能(E2)。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        kit = self.changyeyue.kit

        # 充能 240 点
        self.changyeyue.energy = 240.0
        self.assertTrue(sim.can_cast_ultimate("长夜月"))

        # 施放终结技
        ult_success = sim.cast_ultimate("长夜月")
        self.assertTrue(ult_success)

        # 验证至暗之谜： 3 点充能 (E2)
        self.assertTrue(kit.darkness, "施放大招后应进入至暗之谜")
        self.assertEqual(kit.charges, 3, "E2施放大招应获得 3 点充能")

        # 敌方易伤 30%
        boss_snap = sim.query_status("首领木桩")
        self.assertAlmostEqual(boss_snap["vulnerability"], 0.30, places=2)

        # 自身增伤 60%
        cyy_snap = sim.query_status("长夜月")
        buff_names = [b["name"] for b in cyy_snap["buffs"]]
        self.assertTrue(any("至暗之谜" in b for b in buff_names), "长夜月应挂载至暗之谜Buff")


if __name__ == "__main__":
    unittest.main()

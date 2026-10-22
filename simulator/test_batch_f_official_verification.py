"""Batch F (Collab, Future & Specialized Characters: 联动、未来与欢愉全员) 官方标准规格验证测试套件。

涵盖角色：
- Archer (ID 1015, 巡猎 / 量子)
- 远坂凛 (Tohsaka Rin - ID 1508, 智识 / 量子)
- 大丽花 (Dahlia - ID 1321, 虚无 / 火)
- 刻律德菈 (Kelydra - ID 1412, 同谐 / 风)
- 遐蝶 (Xiadie - ID 1407, 记忆 / 量子)
- 昔涟 (Xilian - ID 1415, 记忆 / 冰)
- 欢愉星神阿哈体系 (Elation / Aha System: 火花 1501, 爻光 1502, 真珠 1503, 银狼LV.999 1506)
"""

import unittest
from typing import Any
from simulator.actions import ActionContext, ActionKind
from simulator.kits.characters.archer import ArcherKit
from simulator.kits.characters.tohsaka_rin import TohsakaRinKit
from simulator.kits.characters.dahlia import DahliaKit
from simulator.kits.characters.kelydra import KelydraKit
from simulator.kits.characters.xiadie import XiadieKit
from simulator.kits.characters.xilian import XilianKit
from simulator.kits.characters.elation import ElationKit


class MockCombatPort:
    def __init__(self):
        self.buffs = {}
        self.energy = {}
        self.sp_changes = []
        self.attacks = []
        self.heals = []
        self.shields = []
        self.advances = []
        self.delays = []
        self.lost_hp = []

    def enemies(self, owner_id):
        return ["enemy_1", "enemy_2"]

    def allies(self, owner_id):
        return ["ally_1", owner_id, "ally_2"]

    def stat(self, entity_id: str, stat_type: Any) -> float:
        return 150.0 if "speed" in str(stat_type).lower() else 2000.0

    def max_hp(self, entity_id):
        return 6000.0

    def hp_ratio(self, entity_id):
        return 0.80

    def attack(self, source_id, target_id, **kwargs):
        self.attacks.append((source_id, target_id, kwargs))

    def heal(self, source_id, target_id, amount):
        self.heals.append((source_id, target_id, amount))

    def add_shield(self, source_id, target_id, amount, **kwargs):
        self.shields.append((source_id, target_id, amount, kwargs))

    def advance(self, source_id, target_id, amount):
        self.advances.append((source_id, target_id, amount))

    def delay_action(self, target_id, amount):
        self.delays.append((target_id, amount))

    def gain_energy(self, entity_id, amount):
        self.energy[entity_id] = self.energy.get(entity_id, 0.0) + amount

    def lose_hp(self, entity_id, amount, cause=""):
        self.lost_hp.append((entity_id, amount, cause))

    def change_sp(self, entity_id, delta, reason=""):
        self.sp_changes.append((entity_id, delta, reason))

    def upsert_status(self, buff_spec):
        self.buffs[buff_spec.key] = buff_spec

    def remove_status(self, target_id, buff_key):
        if buff_key in self.buffs:
            del self.buffs[buff_key]

    def has_status(self, target_id, buff_key):
        return buff_key in self.buffs

    def has_buff(self, target_id, buff_key):
        return buff_key in self.buffs


class TestBatchFOfficialVerification(unittest.TestCase):
    def test_01_archer_official_kit(self):
        port = MockCombatPort()
        archer = ArcherKit("archer", port, eidolon=6)

        # 普攻【干将•莫邪】：130% 量子单体伤害，削韧 10，回能 20
        archer.execute(ActionContext("b", "archer", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.30)
        self.assertEqual(port.attacks[0][2]["toughness_damage"], 10.0)
        self.assertEqual(port.energy["archer"], 20.0)

        # 战技【伪•螺旋剑】：360% 量子单体伤害，削韧 20，回能 30
        archer.execute(ActionContext("s1", "archer", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[1][2]["atk_multiplier"], 3.60)
        self.assertEqual(port.attacks[1][2]["toughness_damage"], 20.0)
        self.assertEqual(port.energy["archer"], 50.0)

        # 终结技【无限剑制】：E4 伤害提高 150% (4.0 * 2.5 = 10.0)
        archer.execute(ActionContext("u", "archer", ActionKind.ULTIMATE, ()))
        ult_atks = [a for a in port.attacks if a[2]["damage_tag"] == "Ultimate"]
        self.assertTrue(len(ult_atks) >= 2)
        self.assertAlmostEqual(ult_atks[0][2]["atk_multiplier"], 10.00)

    def test_02_tohsaka_rin_official_kit(self):
        port = MockCombatPort()
        rin = TohsakaRinKit("rin", port, eidolon=6)

        # 开局获得 20 点宝石能量与 E6 20% 全属性穿透
        rin.on_battle_start()
        self.assertEqual(rin.gem_energy, 20)
        self.assertTrue(port.has_buff("rin", TohsakaRinKit.E6_PEN_BUFF))

        # 普攻【八极拳】：140% 量子单体伤害
        rin.execute(ActionContext("b", "rin", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 战技强化为【第二魔法实验】：消耗 10 宝石能量，造成群体 90% * 1.30 伤害
        rin.execute(ActionContext("s", "rin", ActionKind.SKILL, ()))
        self.assertEqual(rin.gem_energy, 10)

        # 终结技【山脉震撼•明星之薪】：主目标 600% / 其他目标 200%，E6 获得 24 点宝石能量并自拉条 100%
        rin.execute(ActionContext("u", "rin", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertEqual(rin.gem_energy, 34)
        self.assertTrue(len(port.advances) > 0)

    def test_03_dahlia_official_kit(self):
        port = MockCombatPort()
        dahlia = DahliaKit("dahlia", port, eidolon=6)

        # 开局天赋回能 35 点，绑定共舞者 ally_1，E2 全属性减抗 20%
        dahlia.on_battle_start()
        self.assertEqual(port.energy["dahlia"], 35.0)
        self.assertEqual(dahlia.co_dancer_id, "ally_1")
        self.assertTrue(port.has_buff("ally_1", DahliaKit.CO_DANCER_BUFF))
        self.assertTrue(port.has_buff("enemy_1", f"{DahliaKit.E2_RES_SHRED}_enemy_1"))

        # 普攻【拨弄…记忆绽开裂隙】：140% 火伤
        dahlia.execute(ActionContext("b", "dahlia", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 战技【舔舐…背叛伸出火舌】：160% 扩散伤害，开启 3 回合结界
        dahlia.execute(ActionContext("s", "dahlia", ActionKind.SKILL, ("enemy_1",)))
        self.assertEqual(dahlia.field_turns, 3)

        # 终结技【沉溺…飞灰邀入墓床】：敌方全体陷入【败谢】易伤 18%，300% 群体火伤
        dahlia.execute(ActionContext("u", "dahlia", ActionKind.ULTIMATE, ()))
        self.assertTrue(port.has_buff("enemy_1", f"{DahliaKit.BAIXIE_DEBUFF}_enemy_1"))

    def test_04_kelydra_official_kit(self):
        port = MockCombatPort()
        kelydra = KelydraKit("kelydra", port, eidolon=6)

        # 普攻【易位，兵贵神速】：140% 风伤
        kelydra.execute(ActionContext("b", "kelydra", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 战技【升变，士皆可帅】：赋予 ally_1 军功状态并增加 1 点充能
        kelydra.execute(ActionContext("s", "kelydra", ActionKind.SKILL, ("ally_1",)))
        self.assertEqual(kelydra.charges, 1)
        self.assertTrue(port.has_buff("ally_1", KelydraKit.MILITARY_MERIT_BUFF))

        # 终结技【世事如棋，四步堪杀】：充能+2，E4 480% 群体风伤
        kelydra.execute(ActionContext("u", "kelydra", ActionKind.ULTIMATE, ()))
        self.assertEqual(kelydra.charges, 3)
        ult_atks = [a for a in port.attacks if a[2]["damage_tag"] == "Ultimate"]
        self.assertAlmostEqual(ult_atks[0][2]["atk_multiplier"], 4.80)

    def test_05_xiadie_official_kit(self):
        port = MockCombatPort()
        xiadie = XiadieKit("xiadie", port, eidolon=6)

        # 开局 E6 20% 量子穿透
        xiadie.on_battle_start()
        self.assertTrue(port.has_buff("xiadie", XiadieKit.E6_PEN_BUFF))

        # 普攻【哀悼，死海之涟漪】：70% 生命上限量子伤害
        xiadie.execute(ActionContext("b", "xiadie", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 0.70)

        # 战技【缄默，幽蝶之轻抚】：消耗队友生命，50% 单体与 30% 扩散，天赋增伤 20%
        xiadie.execute(ActionContext("s", "xiadie", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(len(port.lost_hp) > 0)
        self.assertTrue(port.has_buff("xiadie", XiadieKit.TALENT_DMG_BUFF))

        # 终结技【亡喉怒哮，苏生之颂铃】：召唤死龙自拉条 100%，展开【遗世冥域】全抗降低 20%
        xiadie.execute(ActionContext("u", "xiadie", ActionKind.ULTIMATE, ()))
        self.assertTrue(xiadie.dragon_summoned)
        self.assertTrue(len(port.advances) > 0)
        self.assertTrue(port.has_buff("enemy_1", f"{XiadieKit.REALM_RES_DEBUFF}_enemy_1"))

    def test_06_xilian_official_kit(self):
        port = MockCombatPort()
        xilian = XilianKit("xilian", port, eidolon=6)

        # 开局 E2 额外获得 12 点追忆
        xilian.on_battle_start()
        self.assertEqual(xilian.remembrance_stacks, 12)

        # 普攻【看，希望的起始！】：70% 生命上限冰伤，追忆+1
        xilian.execute(ActionContext("b", "xilian", ActionKind.BASIC, ("enemy_1",)))
        self.assertEqual(xilian.remembrance_stacks, 13)

        # 战技【盛放吧，来世的乐土】：展开结界全队真实伤害加成，追忆+3
        xilian.execute(ActionContext("s", "xilian", ActionKind.SKILL, ()))
        self.assertEqual(xilian.remembrance_stacks, 16)
        self.assertTrue(port.has_buff("ally_1", f"{XilianKit.TERRITORY_BUFF}_ally_1"))

        # 终结技【诗的「◦」誓约的「∞」】：召唤德谬歌，暴击+50%，E6 首次大招全队 100% 自拉条
        xilian.execute(ActionContext("u", "xilian", ActionKind.ULTIMATE, ()))
        self.assertTrue(xilian.demiurge_summoned)
        self.assertTrue(xilian.is_enhanced)
        self.assertTrue(len(port.advances) >= 3)

    def test_07_elation_system_kit(self):
        port = MockCombatPort()
        elation = ElationKit("aha", port, eidolon=0)

        # 普攻【欢愉戏谑】：造成基础伤害
        elation.execute(ActionContext("b", "aha", ActionKind.BASIC, ("enemy_1",)))
        self.assertTrue(len(port.attacks) > 0)

        # 战技【阿哈的捉弄】：施加欢愉之愚
        elation.execute(ActionContext("s", "aha", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(port.has_buff("enemy_1", ElationKit.ELATION_DEBUFF))

        # 终结技【阿哈时刻！】：全队拉条 30%
        elation.execute(ActionContext("u", "aha", ActionKind.ULTIMATE, ()))
        self.assertTrue(len(port.advances) > 0)


if __name__ == "__main__":
    unittest.main()

"""Batch D (4-Star Supports, Sub-DPS & DoT: 4星辅助与持续伤害全员) 官方标准规格验证测试套件。

涵盖角色：
- 艾丝妲 (Asta - ID 1009)
- 寒鸦 (Hanya - ID 1215)
- 驭空 (Yukong - ID 1207)
- 桂乃芬 (Guinaifen - ID 1210)
- 桑博 (Sampo - ID 1108)
- 卢卡 (Luka - ID 1111)
- 希露瓦 (Serval - ID 1103)
- 雪衣 (Xueyi - ID 1214)
"""

import unittest
from typing import Any
from simulator.actions import ActionContext, ActionKind
from simulator.kits.characters.asta import AstaKit
from simulator.kits.characters.hanya import HanyaKit
from simulator.kits.characters.yukong import YukongKit
from simulator.kits.characters.guinaifen import GuinaifenKit
from simulator.kits.characters.sampo import SampoKit
from simulator.kits.characters.luka import LukaKit
from simulator.kits.characters.serval import ServalKit
from simulator.kits.characters.xueyi import XueyiKit


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

    def delay(self, source_id, target_id, amount):
        self.delays.append((source_id, target_id, amount))

    def gain_energy(self, entity_id, amount):
        self.energy[entity_id] = self.energy.get(entity_id, 0.0) + amount

    def lose_hp(self, entity_id, amount):
        self.lost_hp.append((entity_id, amount))

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


class TestBatchDOfficialVerification(unittest.TestCase):
    def test_01_asta_official_kit(self):
        port = MockCombatPort()
        asta = AstaKit("asta", port, eidolon=6)

        # 开局 3 层蓄能，全队攻击力提高 42% 与 E4 回能效率 15%
        asta.on_battle_start()
        self.assertTrue(port.has_buff("ally_1", AstaKit.CHARGING_BUFF))
        self.assertTrue(port.has_buff("asta", AstaKit.E4_ERR_BUFF))

        # 普攻【光谱射线】：140% 火伤，削韧 10，回能 20
        asta.execute(ActionContext("b", "asta", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertEqual(port.attacks[0][2]["toughness_damage"], 10.0)
        self.assertEqual(port.energy["asta"], 20.0)

        # 战技【流星群落】：E1 额外弹射 1 段 (总计 6 段各 50%)，回能 36 点
        asta.execute(ActionContext("s", "asta", ActionKind.SKILL, ("enemy_1",)))
        self.assertEqual(len([a for a in port.attacks if a[2]["damage_tag"] == "Skill"]), 6)
        self.assertEqual(port.energy["asta"], 56.0)

        # 终结技【星空祝言】：全队提速 50 点，E2 下回合不掉层
        asta.execute(ActionContext("u", "asta", ActionKind.ULTIMATE, ()))
        self.assertTrue(port.has_buff("ally_1", AstaKit.ULT_SPEED_BUFF))
        self.assertTrue(asta.prevent_decay)

    def test_02_hanya_official_kit(self):
        port = MockCombatPort()
        hanya = HanyaKit("hanya", port, eidolon=6)

        # 普攻【冥谶天笔】：140% 物理伤害
        hanya.execute(ActionContext("b", "hanya", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertEqual(port.energy["hanya"], 20.0)

        # 战技【生灭系缚】：240% 物理单体，施加【承负】(E6 为 40% 增伤)，E2 自身提速 20%
        hanya.execute(ActionContext("s", "hanya", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[1][2]["atk_multiplier"], 2.40)
        self.assertTrue(port.has_buff("enemy_1", HanyaKit.BURDEN_DEBUFF))
        self.assertTrue(port.has_buff("hanya", HanyaKit.E2_SPEED_BUFF))

        # 终结技【十王敕令，遍土遵行】：目标提速 20% (150*0.2=30) 与 60% 增攻，E4 延长至 3 回合
        hanya.execute(ActionContext("u", "hanya", ActionKind.ULTIMATE, ("ally_1",)))
        self.assertTrue(port.has_buff("ally_1", HanyaKit.ULT_BUFF))
        self.assertEqual(port.buffs[HanyaKit.ULT_BUFF].duration, 3)

    def test_03_yukong_official_kit(self):
        port = MockCombatPort()
        yukong = YukongKit("yukong", port, eidolon=6)

        # E1 开局全队提速 10%
        yukong.on_battle_start()
        self.assertTrue(port.has_buff("ally_1", YukongKit.E1_SPEED_BUFF))

        # 普攻【流镝】：天赋强化造成 220% 虚数伤害，削韧 20 点
        yukong.execute(ActionContext("b", "yukong", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 2.20)
        self.assertEqual(port.attacks[0][2]["toughness_damage"], 20.0)

        # 战技【天阙鸣弦】：全队攻击力提高 80% (获得 2 层号令)
        yukong.execute(ActionContext("s", "yukong", ActionKind.SKILL, ()))
        self.assertEqual(yukong.bowstring_stacks, 2)
        self.assertTrue(port.has_buff("ally_1", YukongKit.BOWSTRING_BUFF))

        # 终结技【贯云饮羽】：380% 虚数单体，削韧 30 点，全队暴击率 28% / 暴击伤害 65%
        yukong.execute(ActionContext("u", "yukong", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 3.80)
        self.assertEqual(port.attacks[-1][2]["toughness_damage"], 30.0)
        self.assertTrue(port.has_buff("ally_1", YukongKit.CRIT_BUFF))

    def test_04_guinaifen_official_kit(self):
        port = MockCombatPort()
        gnf = GuinaifenKit("guinaifen", port, eidolon=6)

        # 普攻【劈头满堂彩】：140% 火伤，施加【吞火】(E6 为 28% 易伤)
        gnf.execute(ActionContext("b", "guinaifen", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertTrue(port.has_buff("enemy_1", GuinaifenKit.FIREKISS_DEBUFF))

        # 战技【迎面开门红】：120% 主目标，40% 扩散，挂灼烧，E1 减抵抗 10%
        gnf.execute(ActionContext("s", "guinaifen", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[1][2]["atk_multiplier"], 1.20)
        self.assertTrue(port.has_buff("enemy_1", GuinaifenKit.BURN_DEBUFF))
        self.assertTrue(port.has_buff("enemy_1", GuinaifenKit.E1_RES_DOWN))

        # 终结技【给您来段看家戏】：120% 全体并引爆 92% 灼烧伤害
        gnf.execute(ActionContext("u", "guinaifen", ActionKind.ULTIMATE, ()))
        self.assertTrue(any(a[2].get("damage_tag") == "DoT_Detonation" and a[2].get("atk_multiplier") == 0.92 for a in port.attacks))

    def test_05_sampo_official_kit(self):
        port = MockCombatPort()
        sampo = SampoKit("sampo", port, eidolon=6)

        # 秘技【你最闪亮】：行动延后 25%
        sampo.execute(ActionContext("t", "sampo", ActionKind.TECHNIQUE, ()))
        self.assertEqual(len(port.delays), 2)

        # 普攻【酷炫的刀花】：140% 风伤，挂风化
        sampo.execute(ActionContext("b", "sampo", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertTrue(port.has_buff("enemy_1", SampoKit.WIND_SHEAR_DEBUFF))

        # 战技【反复横跳的爱】：E1 额外弹射 1 次 (总计 6 次各 56%)
        sampo.execute(ActionContext("s", "sampo", ActionKind.SKILL, ("enemy_1",)))
        skill_attacks = [a for a in port.attacks if a[2]["damage_tag"] == "Skill"]
        self.assertEqual(len(skill_attacks), 6)

        # 终结技【惊喜礼盒】：160% 全体，持续伤害易伤 30%
        sampo.execute(ActionContext("u", "sampo", ActionKind.ULTIMATE, ()))
        self.assertTrue(port.has_buff("enemy_1", SampoKit.ULT_DOT_VULN_DEBUFF))

    def test_06_luka_official_kit(self):
        port = MockCombatPort()
        luka = LukaKit("luka", port, eidolon=6)

        # 开局 1 层斗志，E4 增攻 5%
        luka.on_battle_start()
        self.assertEqual(luka.fighting_will, 1)
        self.assertTrue(port.has_buff("luka", LukaKit.E4_ATK_BUFF))

        # 普攻【直冲拳】：140% 物理伤害，斗志变为 2 层
        luka.execute(ActionContext("b", "luka", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertEqual(luka.fighting_will, 2)

        # 强化普攻【直冲碎天拳】：消耗 2 层斗志，196% 伤害并引爆裂伤 (E6 为 109%)
        defn = luka.definition(ActionKind.BASIC)
        self.assertEqual(defn.name, "直冲碎天拳")
        luka.execute(ActionContext("eb", "luka", ActionKind.BASIC, ("enemy_1",)))
        self.assertEqual(luka.fighting_will, 0)
        self.assertTrue(any(a[2].get("damage_tag") == "EnhancedBasic" and a[2].get("atk_multiplier") == 1.96 for a in port.attacks))
        self.assertTrue(any(a[2].get("damage_tag") == "DoT_Detonation" and a[2].get("atk_multiplier") == 1.09 for a in port.attacks))

        # 战技【裂伤拳】：120% 单体，挂裂伤，E2 额外产斗志，E1 增伤 15%
        luka.execute(ActionContext("s", "luka", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(port.has_buff("enemy_1", LukaKit.BLEED_DEBUFF))
        self.assertTrue(port.has_buff("luka", LukaKit.E1_DMG_BUFF))

        # 终结技【制胜一击】：易伤 20%，330% 爆发单体
        luka.execute(ActionContext("u", "luka", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertTrue(port.has_buff("enemy_1", LukaKit.ULT_VULN_DEBUFF))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 3.30)

    def test_07_serval_official_kit(self):
        port = MockCombatPort()
        serval = ServalKit("serval", port, eidolon=6)

        # 普攻【雷鸣音阶】：140% 雷伤，E1 扩散 60%
        serval.execute(ActionContext("b", "serval", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertTrue(any(a[2].get("damage_tag") == "Basic_Extra" for a in port.attacks))

        # 战技【电光石火间】：140% 主目标，60% 扩散，施加触电
        serval.execute(ActionContext("s", "serval", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(port.has_buff("enemy_1", ServalKit.SHOCK_DEBUFF))

        # 终结技【机械热潮登场！】：180% 全体雷伤，触电延长 2 回合
        serval.execute(ActionContext("u", "serval", ActionKind.ULTIMATE, ()))
        self.assertTrue(any(a[2].get("damage_tag") == "Ultimate" for a in port.attacks))

    def test_08_xueyi_official_kit(self):
        port = MockCombatPort()
        xueyi = XueyiKit("xueyi", port, eidolon=6)

        # 普攻【破魔锥】：140% 量子伤害，积攒 1 层恶报
        xueyi.execute(ActionContext("b", "xueyi", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertEqual(xueyi.karma_stacks, 1)

        # 战技【摄伏诸恶】：140% 主目标，70% 扩散，积攒 2 层恶报
        xueyi.execute(ActionContext("s", "xueyi", ActionKind.SKILL, ("enemy_1",)))
        self.assertEqual(xueyi.karma_stacks, 3)

        # 终结技【天罚贯身】：250% 量子单体，无视弱点削韧 40，E4 击破特攻 40%
        # 恶报由 3 + 4 = 7 >= 6，触发 E6 追击并回血 5% (E2)
        xueyi.execute(ActionContext("u", "xueyi", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertTrue(port.has_buff("xueyi", XueyiKit.E4_BREAK_BUFF))
        self.assertEqual(xueyi.karma_stacks, 0)
        self.assertTrue(any(a[2].get("damage_tag") == "KarmaFollowUp" and a[2].get("atk_multiplier") == 1.26 for a in port.attacks))
        self.assertEqual(len(port.heals), 1)


if __name__ == "__main__":
    unittest.main()

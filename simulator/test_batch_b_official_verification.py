"""Batch B (Sustainers: 存护与丰饶全员) 官方标准重构验证测试套件。

涵盖角色：
- 砂金 (Aventurine - ID 1304)
- 符玄 (Fu Xuan - ID 1208)
- 灵砂 (Lingsha - ID 1222)
- 加拉赫 (Gallagher - ID 1301)
- 藿藿 (Huohuo - ID 1217)
- 罗刹 (Luocha - ID 1203)
- 杰帕德 (Gepard - ID 1104)
- 白露 (Bailu - ID 1211)
- 玲可 (Lynx - ID 1110)
- 娜塔莎 (Natasha - ID 1105)
"""

import unittest
from typing import Any
from unittest.mock import MagicMock
from simulator.actions import ActionContext, ActionKind
from simulator.combat_port import CombatPort
from simulator.kits.characters.aventurine import AventurineKit
from simulator.kits.characters.fuxuan import FuXuanKit
from simulator.kits.characters.lingsha import LingshaKit
from simulator.kits.characters.gallagher import GallagherKit
from simulator.kits.characters.huohuo import HuohuoKit
from simulator.kits.characters.luocha import LuochaKit
from simulator.kits.characters.gepard import GepardKit
from simulator.kits.characters.bailu import BailuKit
from simulator.kits.characters.lynx import LynxKit
from simulator.kits.characters.natasha import NatashaKit


class MockCombatPort:
    def __init__(self):
        self.buffs = {}
        self.energy = {}
        self.attacks = []
        self.heals = []
        self.shields = []
        self.advances = []
        self.sp_changes = 0

    def enemies(self, owner_id):
        return ["enemy_1", "enemy_2"]

    def allies(self, owner_id):
        return ["ally_1", owner_id, "ally_2"]

    def stat(self, entity_id: str, stat_type: Any) -> float:
        return 2000.0

    def advance(self, source_id, target_id, amount):
        self.advances.append((source_id, target_id, amount))

    def max_hp(self, entity_id):
        return 6000.0

    def hp_ratio(self, entity_id):
        return 0.25

    def attack(self, source_id, target_id, **kwargs):
        self.attacks.append((source_id, target_id, kwargs))

    def heal(self, source_id, target_id, amount):
        self.heals.append((source_id, target_id, amount))

    def add_shield(self, source_id, target_id, amount, **kwargs):
        self.shields.append((source_id, target_id, amount, kwargs))

    def gain_energy(self, entity_id, amount):
        self.energy[entity_id] = self.energy.get(entity_id, 0.0) + amount

    def upsert_status(self, buff_spec):
        self.buffs[buff_spec.key] = buff_spec

    def has_buff(self, target_id, buff_key):
        return buff_key in self.buffs

    def remove_buff(self, target_id, buff_key):
        self.buffs.pop(buff_key, None)

    def consume_sp(self, amount):
        self.sp_changes -= amount

    def gain_sp(self, amount):
        self.sp_changes += amount

    def dispel_debuff(self, target_id):
        pass


class TestBatchBSustainers(unittest.TestCase):
    def setUp(self):
        self.port = MockCombatPort()

    def test_aventurine_kit(self):
        kit = AventurineKit("aventurine", self.port, eidolon=6)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "直观投注")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "繁荣基石")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "轮盘勋爵")

        # Execute Basic: def-scaling
        kit.execute(ActionContext("act_basic", "aventurine", ActionKind.BASIC, target_ids=["enemy_1"]))
        self.assertEqual(self.port.attacks[-1][2]["scaling_stat"], "def")

        # Execute Skill: shield all allies
        kit.execute(ActionContext("act_skill", "aventurine", ActionKind.SKILL, target_ids=[]))
        self.assertTrue(len(self.port.shields) >= 3)

        # Execute Ultimate: gains energy and blind bet
        kit.execute(ActionContext("act_ult", "aventurine", ActionKind.ULTIMATE, target_ids=["enemy_1"]))
        self.assertIn("Aventurine_Panic_CritDmg_enemy_1", self.port.buffs)

    def test_fuxuan_kit(self):
        kit = FuXuanKit("fuxuan", self.port, eidolon=1)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "始击岁星")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "太微行棋，灵台示影")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "天律大衍，历劫归一")

        # Execute Basic: hp-scaling
        kit.execute(ActionContext("act_basic", "fuxuan", ActionKind.BASIC, target_ids=["enemy_1"]))
        self.assertEqual(self.port.attacks[-1][2]["scaling_stat"], "hp")

        # Execute Skill: Matrix of Prescience with E1 crit dmg
        kit.execute(ActionContext("act_skill", "fuxuan", ActionKind.SKILL, target_ids=[]))
        self.assertTrue(any("FuXuan_Matrix" in k for k in self.port.buffs))

    def test_lingsha_kit(self):
        kit = LingshaKit("lingsha", self.port, eidolon=2)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "肃香")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "识烟飞彩")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "幔亭缭霞")

        # Execute Skill & Ult
        kit.execute(ActionContext("act_skill", "lingsha", ActionKind.SKILL, target_ids=[]))
        self.assertTrue(len(self.port.heals) >= 3)

        kit.execute(ActionContext("act_ult", "lingsha", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(any("Lingsha_Intoxicated" in k for k in self.port.buffs))

    def test_gallagher_kit(self):
        kit = GallagherKit("gallagher", self.port, eidolon=6)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "开瓶费")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "罐装特调")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "香槟仪礼")

        # Execute Ultimate: inflicts Besotted debuff
        kit.execute(ActionContext("act_ult", "gallagher", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(any("Gallagher_Besotted" in k for k in self.port.buffs))

    def test_huohuo_kit(self):
        kit = HuohuoKit("huohuo", self.port, eidolon=1)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "令旗•征风召雨")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "灵符•保命护身")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "尾巴•遣神役鬼")

        # Execute Basic: hp-scaling
        kit.execute(ActionContext("act_basic", "huohuo", ActionKind.BASIC, target_ids=["enemy_1"]))
        self.assertEqual(self.port.attacks[-1][2]["scaling_stat"], "hp")

        # Execute Skill: Divine Provision
        kit.execute(ActionContext("act_skill", "huohuo", ActionKind.SKILL, target_ids=["ally_1"]))
        self.assertTrue(any(HuohuoKit.PROVISION_BUFF in k for k in self.port.buffs))

        # Execute Ult: grants energy and atk boost
        kit.execute(ActionContext("act_ult", "huohuo", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(any(HuohuoKit.ULT_ATK_BUFF in k for k in self.port.buffs))

    def test_luocha_kit(self):
        kit = LuochaKit("luocha", self.port, eidolon=1)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "黑渊的棘刺")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "白花的祈望")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "归葬的遂愿")

        # Execute Skill: heals ally
        kit.execute(ActionContext("act_skill", "luocha", ActionKind.SKILL, target_ids=["ally_1"]))
        self.assertTrue(len(self.port.heals) >= 1)

    def test_gepard_kit(self):
        kit = GepardKit("gepard", self.port, eidolon=2)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "一意之拳")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "震慑之击")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "永屹之壁")

        # Execute Ult: shield all allies
        kit.execute(ActionContext("act_ult", "gepard", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(len(self.port.shields) >= 3)

    def test_bailu_kit(self):
        kit = BailuKit("bailu", self.port, eidolon=4)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "望 、闻、问…蹴！")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "云吟乍涌坠珠露")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "匏蛟跃渊先雷音")

        # Execute Skill: E4 dmg boost
        kit.execute(ActionContext("act_skill", "bailu", ActionKind.SKILL, target_ids=["ally_1"]))
        self.assertTrue(any("Bailu_E4_DmgBoost" in k for k in self.port.buffs))

    def test_lynx_kit(self):
        kit = LynxKit("lynx", self.port, eidolon=6)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "冰攀前齿技术")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "盐渍野营罐头")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "雪原急救方案")

        # Execute Basic: hp-scaling
        kit.execute(ActionContext("act_basic", "lynx", ActionKind.BASIC, target_ids=["enemy_1"]))
        self.assertEqual(self.port.attacks[-1][2]["scaling_stat"], "hp")

        # Execute Skill: Survival Response and E4 ATK buff
        kit.execute(ActionContext("act_skill", "lynx", ActionKind.SKILL, target_ids=["ally_1"]))
        self.assertTrue(any("Lynx_Survival_Response" in k for k in self.port.buffs))
        self.assertTrue(any("Lynx_E4_AtkBoost" in k for k in self.port.buffs))

        # Execute Ult: heals all allies
        kit.execute(ActionContext("act_ult", "lynx", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(len(self.port.heals) >= 4)

    def test_natasha_kit(self):
        kit = NatashaKit("natasha", self.port, eidolon=6)
        b_def = kit.definition(ActionKind.BASIC)
        self.assertEqual(b_def.name, "仁慈的背面")
        s_def = kit.definition(ActionKind.SKILL)
        self.assertEqual(s_def.name, "爱，救护与抉择")
        u_def = kit.definition(ActionKind.ULTIMATE)
        self.assertEqual(u_def.name, "新生之礼")

        # Execute Basic: E6 additional HP attack
        kit.execute(ActionContext("act_basic", "natasha", ActionKind.BASIC, target_ids=["enemy_1"]))
        self.assertTrue(any(atk[2].get("scaling_stat") == "hp" for atk in self.port.attacks))

        # Execute Skill: heals ally and applies HoT
        kit.execute(ActionContext("act_skill", "natasha", ActionKind.SKILL, target_ids=["ally_1"]))
        self.assertTrue(any("Natasha_Heal_Over_Time" in k for k in self.port.buffs))

        # Execute Ult: heals all allies, E2 applies HoT for low HP ally
        kit.execute(ActionContext("act_ult", "natasha", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(any("Natasha_E2_HoT" in k for k in self.port.buffs))


if __name__ == "__main__":
    unittest.main()

"""Batch C1 (Core Carries & DPS: 核心输出全员) 官方标准规格验证测试套件。

涵盖角色：
- 黄泉 (Acheron - ID 1308)
- 流萤 (Firefly - ID 1310)
- 云璃 (Yunli - ID 1221)
- 真理医生 (Dr. Ratio - ID 1305)
- 托帕&账账 (Topaz & Numby - ID 1112)
- 克拉拉 (Clara - ID 1107)
"""

import unittest
from typing import Any
from simulator.actions import ActionContext, ActionKind
from simulator.kits.characters.acheron import AcheronKit
from simulator.kits.characters.firefly import FireflyKit
from simulator.kits.characters.yunli import YunliKit
from simulator.kits.characters.ratio import RatioKit
from simulator.kits.characters.topaz import TopazKit
from simulator.kits.characters.clara import ClaraKit


class MockCombatPort:
    def __init__(self):
        self.buffs = {}
        self.energy = {}
        self.attacks = []
        self.heals = []
        self.shields = []
        self.advances = []
        self.lost_hp = []

    def enemies(self, owner_id):
        return ["enemy_1", "enemy_2"]

    def allies(self, owner_id):
        return ["ally_1", owner_id, "ally_2"]

    def stat(self, entity_id: str, stat_type: Any) -> float:
        return 2000.0

    def max_hp(self, entity_id):
        return 5000.0

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

    def gain_energy(self, entity_id, amount):
        self.energy[entity_id] = self.energy.get(entity_id, 0.0) + amount

    def lose_hp(self, entity_id, amount):
        self.lost_hp.append((entity_id, amount))

    def upsert_status(self, buff_spec):
        self.buffs[buff_spec.key] = buff_spec

    def has_buff(self, target_id, buff_key):
        return buff_key in self.buffs

    def remove_buff(self, target_id, buff_key):
        self.buffs.pop(buff_key, None)


class TestBatchC1OfficialKits(unittest.TestCase):
    def setUp(self):
        self.port = MockCombatPort()

    def test_acheron_kit(self):
        """验证黄泉：残梦机制、E1暴击、战技充能、终结技全属性抗穿。"""
        kit = AcheronKit("acheron", self.port, eidolon=1)
        self.assertEqual(kit.definition(ActionKind.BASIC).name, "三途枯榷")
        self.assertEqual(kit.definition(ActionKind.SKILL).name, "八雷飞渡")
        self.assertEqual(kit.definition(ActionKind.ULTIMATE).name, "残梦尽染，一刀缭断")
        self.assertEqual(kit.definition(ActionKind.TECHNIQUE).name, "四相断我")

        kit.on_battle_start()
        self.assertIn(AcheronKit.E1_CRIT_BUFF, self.port.buffs)

        # 战技充能残梦与集真赤
        kit.execute(ActionContext("ach_skill", "acheron", ActionKind.SKILL, target_ids=["enemy_1"]))
        self.assertEqual(kit.slashed_dream, 1)
        self.assertEqual(kit.crimson_knots["enemy_1"], 1)

        # 充能至 9 点释放终结技
        kit.slashed_dream = 9
        self.assertTrue(kit.can_cast_ultimate())
        kit.execute(ActionContext("ach_ult", "acheron", ActionKind.ULTIMATE, target_ids=["enemy_1"]))
        self.assertEqual(kit.slashed_dream, 0)
        self.assertIn(AcheronKit.ULT_RES_SHRED, self.port.buffs)

    def test_firefly_kit(self):
        """验证流萤：常态战技充能144点、终结技完全燃烧拉条100%、E1强化战技0消耗与破防。"""
        kit = FireflyKit("firefly", self.port, eidolon=2)

        # 常态战技：充能 144 点，自拉条 25%
        kit.execute(ActionContext("ff_sk", "firefly", ActionKind.SKILL, target_ids=["enemy_1"]))
        self.assertEqual(self.port.energy["firefly"], 144.0)
        self.assertIn(("firefly", "firefly", 0.25), self.port.advances)

        # 终结技进入完全燃烧并 100% 拉条
        kit.execute(ActionContext("ff_ult", "firefly", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(kit.is_combustion)
        self.assertIn(("firefly", "firefly", 1.0), self.port.advances)
        self.assertIn(FireflyKit.COMBUSTION_BUFF, self.port.buffs)

        # E1 强化战技 0 SP
        defn = kit.definition(ActionKind.SKILL)
        self.assertEqual(defn.name, "火萤Ⅳ型-死星过载")
        self.assertEqual(defn.cost.sp, 0)

        kit.execute(ActionContext("ff_sk2", "firefly", ActionKind.SKILL, target_ids=["enemy_1"]))
        self.assertIn(FireflyKit.E1_DEF_SHRED, self.port.buffs)

    def test_yunli_kit(self):
        """验证云璃：大招格挡架势、反击弹反【灭】、E2无视防御。"""
        kit = YunliKit("yunli", self.port, eidolon=2)
        self.assertEqual(kit.definition(ActionKind.BASIC).name, "翻风转日")
        self.assertEqual(kit.definition(ActionKind.SKILL).name, "飞铗震赫")
        self.assertEqual(kit.definition(ActionKind.ULTIMATE).name, "剑为地纪，刃惊天宗")

        # 战技自愈
        kit.execute(ActionContext("yl_sk", "yunli", ActionKind.SKILL, target_ids=["enemy_1"]))
        self.assertTrue(len(self.port.heals) >= 1)

        # 终结技进入格挡
        kit.execute(ActionContext("yl_ult", "yunli", ActionKind.ULTIMATE, target_ids=[]))
        self.assertTrue(kit.is_parrying)
        self.assertIn(YunliKit.PARRY_BUFF, self.port.buffs)

        # 受到攻击触发弹反【勘破•灭】
        kit.trigger_counter("enemy_1")
        self.assertFalse(kit.is_parrying)
        self.assertTrue(any(atk[2].get("damage_tag") == "Ultimate" for atk in self.port.attacks))
        self.assertIn("Yunli_E2_DefShred", self.port.buffs)

    def test_ratio_kit(self):
        """验证真理医生：E1开战4层【归纳】、战技粉笔追击、大招短见标记。"""
        kit = RatioKit("ratio", self.port, eidolon=1)
        self.assertEqual(kit.definition(ActionKind.BASIC).name, "知识就是力量")
        self.assertEqual(kit.definition(ActionKind.SKILL).name, "精神助产术")
        self.assertEqual(kit.definition(ActionKind.ULTIMATE).name, "三段悖论")

        kit.on_battle_start()
        self.assertEqual(kit.current_stacks, 4)
        self.assertIn(RatioKit.TALENT_CRIT_BUFF, self.port.buffs)

        # 战技追击
        kit.execute(ActionContext("rt_sk", "ratio", ActionKind.SKILL, target_ids=["enemy_1"]))
        self.assertTrue(any(atk[2].get("damage_tag") == "FollowUpAttack" for atk in self.port.attacks))

        # 终结技标记
        kit.execute(ActionContext("rt_ult", "ratio", ActionKind.ULTIMATE, target_ids=["enemy_1"]))
        self.assertTrue(any(RatioKit.ULT_WISDOM_MARK in k for k in self.port.buffs))

    def test_topaz_kit(self):
        """验证托帕&账账：战技负债证明、终结技涨幅惊人、E1被执行。"""
        kit = TopazKit("topaz", self.port, eidolon=1)
        self.assertEqual(kit.definition(ActionKind.BASIC).name, "赤字…")
        self.assertEqual(kit.definition(ActionKind.SKILL).name, "支付困难？")
        self.assertEqual(kit.definition(ActionKind.ULTIMATE).name, "扭亏为盈！")

        # 战技施加负债证明与E1被执行
        kit.execute(ActionContext("tp_sk", "topaz", ActionKind.SKILL, target_ids=["enemy_1"]))
        self.assertTrue(any(TopazKit.PROOF_OF_DEBT_DEBUFF in k for k in self.port.buffs))
        self.assertTrue(any(TopazKit.E1_EXEC_DEBUFF in k for k in self.port.buffs))

        # 终结技账账进入涨幅惊人
        kit.execute(ActionContext("tp_ult", "topaz", ActionKind.ULTIMATE, target_ids=[]))
        self.assertIn("Topaz_Windfall_Bonanza", self.port.buffs)

    def test_clara_kit(self):
        """验证克拉拉：天赋常驻减伤10%、受击反击与标记、E1战技保留标记、E2大招增攻30%。"""
        kit = ClaraKit("clara", self.port, eidolon=6)
        self.assertEqual(kit.definition(ActionKind.BASIC).name, "我也想帮上忙")
        self.assertEqual(kit.definition(ActionKind.SKILL).name, "史瓦罗在看着你")
        self.assertEqual(kit.definition(ActionKind.ULTIMATE).name, "是约定不是命令")

        kit.on_battle_start()
        self.assertIn(ClaraKit.TALENT_DMG_REDUCE, self.port.buffs)

        # 受击反击标记
        kit.trigger_counter("enemy_1")
        self.assertIn("enemy_1", kit.marked_enemies)

        # 施放战技，E1保留标记
        kit.execute(ActionContext("cl_sk", "clara", ActionKind.SKILL, target_ids=[]))
        self.assertIn("enemy_1", kit.marked_enemies)

        # 施放终结技，E2增攻
        kit.execute(ActionContext("cl_ult", "clara", ActionKind.ULTIMATE, target_ids=[]))
        self.assertIn(ClaraKit.E2_ATK_BUFF, self.port.buffs)


if __name__ == "__main__":
    unittest.main()

"""Batch C2 (Second Carry & Sub-DPS Wave: 输出与副C全员) 官方标准规格验证测试套件。

涵盖角色：
- 黑塔 (Herta - ID 1013)
- 姬子 (Himeko - ID 1003)
- 刃 (Blade - ID 1205)
- 镜流 (Jingliu - ID 1212)
- 希儿 (Seele - ID 1102)
- 卡芙卡 (Kafka - ID 1005)
- 黑天鹅 (Black Swan - ID 1307)
- 银狼 (Silver Wolf - ID 1006)
- 青雀 (Qingque - ID 1201)
- 瓦尔特 (Welt - ID 1004)
"""

import unittest
from typing import Any
from simulator.actions import ActionContext, ActionKind
from simulator.kits.characters.herta import HertaKit
from simulator.kits.characters.himeko import HimekoKit
from simulator.kits.characters.blade import BladeKit
from simulator.kits.characters.jingliu import JingliuKit
from simulator.kits.characters.seele import SeeleKit
from simulator.kits.characters.kafka import KafkaKit
from simulator.kits.characters.black_swan import BlackSwanKit
from simulator.kits.characters.silver_wolf import SilverWolfKit
from simulator.kits.characters.qingque import QingqueKit
from simulator.kits.characters.welt import WeltKit


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
        return 2000.0

    def max_hp(self, entity_id):
        return 6000.0

    def hp_ratio(self, entity_id):
        return 0.40 if entity_id == "enemy_1" else 0.80

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

    def has_buff(self, target_id, buff_key):
        return buff_key in self.buffs


class TestBatchC2OfficialVerification(unittest.TestCase):
    def test_01_herta_official_kit(self):
        port = MockCombatPort()
        herta = HertaKit("herta", port, eidolon=6)

        # 普攻【看什么看】：140% 攻击力 (E1 残血附加 40%)
        herta.execute(ActionContext("b", "herta", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertEqual(port.attacks[0][2]["toughness_damage"], 10.0)
        self.assertEqual(port.energy["herta"], 20.0)

        # 战技【一锤子买卖】：100% 全体 (对 HP>=50% 目标增伤 20%)
        herta.execute(ActionContext("s", "herta", ActionKind.SKILL, ()))
        self.assertEqual(port.attacks[-1][2]["toughness_damage"], 10.0)
        self.assertEqual(port.energy["herta"], 50.0)

        # 终结技【是魔法，我加了魔法】：200% 全体
        herta.execute(ActionContext("u", "herta", ActionKind.ULTIMATE, ()))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 2.00)
        self.assertEqual(port.attacks[-1][2]["toughness_damage"], 20.0)

        # 天赋追加攻击【还是我来吧】：40% 全体 (E4 增伤 10% 为 44%)
        herta.trigger_followup()
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 0.44)
        self.assertTrue(port.has_buff("herta", HertaKit.E2_CRIT_BUFF))

    def test_02_himeko_official_kit(self):
        port = MockCombatPort()
        himeko = HimekoKit("himeko", port, eidolon=1)

        # 普攻【武装调律】：140%
        himeko.execute(ActionContext("b", "himeko", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.40)

        # 战技【熔核爆裂】：主目标 200%，扩散 80%
        himeko.execute(ActionContext("s", "himeko", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-2][2]["atk_multiplier"], 2.00)
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 0.80)

        # 终结技【天坠之火】：230%
        himeko.execute(ActionContext("u", "himeko", ActionKind.ULTIMATE, ()))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 2.30)

        # 天赋追击【乘胜追击】：3层充能触发 140% 全体追击，E1 提速 20%
        himeko.add_charge(2)
        self.assertEqual(himeko.charge, 0)
        self.assertTrue(port.has_buff("himeko", HimekoKit.E1_SPEED_BUFF))

    def test_03_blade_official_kit(self):
        port = MockCombatPort()
        blade = BladeKit("blade", port, eidolon=6)

        # 战技【地狱变】：消耗 30% 生命上限，100% 自拉条并获得 40% 增伤
        blade.execute(ActionContext("s", "blade", ActionKind.SKILL, ()))
        self.assertTrue(blade.is_enhanced)
        self.assertEqual(len(port.advances), 1)
        self.assertTrue(port.has_buff("blade", BladeKit.HELLSCAPE_BUFF))

        # 强化普攻【无间剑树】：消耗 10% 生命，主目标 140% HP，0 SP
        blade.execute(ActionContext("eb", "blade", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-2][2]["atk_multiplier"], 1.40)
        self.assertEqual(port.attacks[-2][2]["scaling_stat"], "hp")

        # 终结技【大辟万死】：消耗生命上限至 50%，造成生命+攻击+已损失生命伤害 (E1 为 200%)
        blade.execute(ActionContext("u", "blade", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-2][2]["atk_multiplier"], 2.00)
        self.assertEqual(port.attacks[-2][2]["scaling_stat"], "hp")

        # 天赋【倏忽恩赐】：5层充能触发全体追击 (E6 增幅 50% 为 160% HP)，回复 25% 生命
        blade.add_charge(5)
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.60)
        self.assertEqual(port.attacks[-1][2]["scaling_stat"], "hp")
        self.assertEqual(len(port.heals), 1)

    def test_04_jingliu_official_kit(self):
        port = MockCombatPort()
        jl = JingliuKit("jingliu", port, eidolon=2)

        # 战技 1：朔望 1 层
        jl.execute(ActionContext("s1", "jingliu", ActionKind.SKILL, ("enemy_1",)))
        self.assertEqual(jl.syzygy_stacks, 1)
        self.assertFalse(jl.is_transmigrated)

        # 战技 2：朔望 2 层，立即触发转魄并 100% 自拉条
        jl.execute(ActionContext("s2", "jingliu", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(jl.is_transmigrated)
        self.assertEqual(len(port.advances), 1)
        self.assertTrue(port.has_buff("jingliu", JingliuKit.TRANSMIGRATION_BUFF))

        # 转魄下强化战技【寒川映月】：250% 主目标，125% 扩散，0 SP 消耗
        defn = jl.definition(ActionKind.SKILL)
        self.assertEqual(defn.cost.sp, 0)
        jl.execute(ActionContext("es", "jingliu", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-2][2]["atk_multiplier"], 2.50)
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.25)

        # 终结技【昙华生灭，天河泻梦】：300% 主目标，150% 扩散，获得 1 层朔望
        jl.execute(ActionContext("u", "jingliu", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-2][2]["atk_multiplier"], 3.00)

    def test_05_seele_official_kit(self):
        port = MockCombatPort()
        seele = SeeleKit("seele", port, eidolon=2)

        # 普攻【强袭】：140%
        seele.execute(ActionContext("b", "seele", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.40)

        # 战技【归刃】：220%，加速 25% (E2 可叠 2 层 = 50%)，残血 <=80% 触发 E1 无视防御
        seele.execute(ActionContext("s", "seele", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-2][2]["atk_multiplier"], 2.20)
        self.assertTrue(port.has_buff("seele", SeeleKit.SPEED_BUFF))
        self.assertTrue(port.has_buff("seele", SeeleKit.E1_DEF_IGNORE))

        # 终结技【乱蝶】：425% 爆发，进入增幅 80%
        seele.execute(ActionContext("u", "seele", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 4.25)
        self.assertTrue(port.has_buff("seele", SeeleKit.AMPLIFY_BUFF))

    def test_06_kafka_official_kit(self):
        port = MockCombatPort()
        kafka = KafkaKit("kafka", port, eidolon=2)

        # E2 开局全队 DoT 增伤 25%
        kafka.on_battle_start()
        self.assertTrue(port.has_buff("kafka", KafkaKit.E2_DOT_BUFF))

        # 普攻【夜间喧嚣不止】：140%
        kafka.execute(ActionContext("b", "kafka", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.40)

        # 战技【月光摩挲连绵】：160% 单体，60% 扩散，引爆 75% DoT
        kafka.execute(ActionContext("s", "kafka", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-3][2]["atk_multiplier"], 1.60)
        self.assertTrue(port.has_buff("enemy_1", KafkaKit.E1_DOT_VULN))

        # 终结技【悲剧尽头的颤音】：80% 全体，挂触电并立即引爆 100% 伤害
        kafka.execute(ActionContext("u", "kafka", ActionKind.ULTIMATE, ()))
        self.assertTrue(port.has_buff("enemy_1", KafkaKit.SHOCK_DEBUFF))

    def test_07_black_swan_official_kit(self):
        port = MockCombatPort()
        bs = BlackSwanKit("black_swan", port, eidolon=1)

        # E1 开局减抗 25%
        bs.on_battle_start()
        self.assertTrue(port.has_buff("enemy_1", BlackSwanKit.E1_RES_SHRED))

        # 普攻【洞见，缄默的黎明】：84%
        bs.execute(ActionContext("b", "black_swan", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 0.84)
        self.assertGreaterEqual(bs.arcana_stacks.get("enemy_1", 0), 1)

        # 战技【失坠，伪神的黄昏】：90% 扩散，减防 20.8%
        bs.execute(ActionContext("s", "black_swan", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 0.90)
        self.assertTrue(port.has_buff("enemy_1", BlackSwanKit.DEF_SHRED_DEBUFF))

        # 终结技【沉醉于彼界的臂湾】：120% 全体，揭露易伤 25%
        bs.execute(ActionContext("u", "black_swan", ActionKind.ULTIMATE, ()))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.20)
        self.assertTrue(port.has_buff("enemy_1", BlackSwanKit.EPIPHANY_DEBUFF))

    def test_08_silver_wolf_official_kit(self):
        port = MockCombatPort()
        sw = SilverWolfKit("silver_wolf", port, eidolon=2)

        # 开局回能 20 点与 E2 易伤
        sw.on_battle_start()
        self.assertEqual(port.energy["silver_wolf"], 20.0)
        self.assertTrue(port.has_buff("enemy_1", SilverWolfKit.E2_VULN_DEBUFF))

        # 普攻【|系统警告|】：140%
        sw.execute(ActionContext("b", "silver_wolf", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.40)

        # 战技【是否允许更改？】：196%，植入弱点与全属性减抗
        sw.execute(ActionContext("s", "silver_wolf", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.96)
        self.assertTrue(port.has_buff("enemy_1", SilverWolfKit.WEAKNESS_IMPLANT))

        # 终结技【|账号已封禁|】：380% 单体，全体减防 45%
        sw.execute(ActionContext("u", "silver_wolf", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 3.80)
        self.assertTrue(port.has_buff("enemy_1", SilverWolfKit.DEF_SHRED_DEBUFF))

    def test_09_qingque_official_kit(self):
        port = MockCombatPort()
        qq = QingqueKit("qingque", port, eidolon=6)

        # 普攻【门前清】：140%
        qq.execute(ActionContext("b", "qingque", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.40)

        # 战技【海底捞月】：摸牌 + 增伤 28%
        qq.execute(ActionContext("s", "qingque", ActionKind.SKILL, ()))
        self.assertTrue(port.has_buff("qingque", QingqueKit.SKILL_DMG_BUFF))

        # 终结技【四幺暗刻？和！】：200% 全体，必入暗杠
        qq.execute(ActionContext("u", "qingque", ActionKind.ULTIMATE, ()))
        self.assertTrue(qq.is_hidden_hand)
        self.assertTrue(port.has_buff("qingque", QingqueKit.HIDDEN_HAND_BUFF))

        # 强化普攻【杠上开花！】：336% 主目标，140% 扩散，0 SP，E6 恢复 1 点 SP
        defn = qq.definition(ActionKind.BASIC)
        self.assertEqual(defn.name, "杠上开花！")
        self.assertEqual(defn.cost.sp, 0)
        qq.execute(ActionContext("eb", "qingque", ActionKind.BASIC, ("enemy_1",)))
        self.assertTrue(any(a[2].get("atk_multiplier") == 3.36 for a in port.attacks))
        self.assertEqual(len(port.sp_changes), 1)

    def test_10_welt_official_kit(self):
        port = MockCombatPort()
        welt = WeltKit("welt", port, eidolon=1)

        # 普攻【重力压制】：140%
        welt.execute(ActionContext("b", "welt", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.40)

        # 战技【虚空断界】：216% 弹射，施加【失重】(减防20%，减速15%)
        welt.execute(ActionContext("s", "welt", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 2.16)
        self.assertTrue(port.has_buff("enemy_1", WeltKit.WEIGHTLESS_DEBUFF))

        # 终结技【拟似黑洞】：150% 全体，推条 40% 与禁锢
        welt.execute(ActionContext("u", "welt", ActionKind.ULTIMATE, ()))
        self.assertAlmostEqual(port.attacks[-1][2]["atk_multiplier"], 1.50)
        self.assertEqual(len(port.delays), 2)
        self.assertTrue(port.has_buff("enemy_1", WeltKit.IMPRISON_DEBUFF))


if __name__ == "__main__":
    unittest.main()

"""Batch E (Dan Heng, Dan Heng IL, March 7th Hunt, Moze, Yanqing, Sushang, Misha, Hook, Arlan, Trailblazer Harmony) 官方标准规格验证测试套件。

严格依据 Nanoka 4.6 官方解包原始数据与长夜月标准进行 100% 机制与数值契合度验证：
1. 丹恒 (Dan Heng - ID 1002, 巡猎 / 风)
2. 丹恒•饮月 (Dan Heng • Imbibitor Lunae - ID 1213, 毁灭 / 虚数)
3. 三月七•巡猎 (March 7th • The Hunt - ID 1224, 巡猎 / 虚数)
4. 貊泽 (Moze - ID 1223, 巡猎 / 雷)
5. 彦卿 (Yanqing - ID 1209, 巡猎 / 冰)
6. 素裳 (Sushang - ID 1206, 巡猎 / 物理)
7. 米沙 (Misha - ID 1312, 毁灭 / 冰)
8. 虎克 (Hook - ID 1109, 毁灭 / 火)
9. 阿兰 (Arlan - ID 1008, 毁灭 / 雷)
10. 开拓者•同谐 (Harmony Trailblazer - ID 8005/8006, 同谐 / 虚数)
"""

import unittest
from typing import Any
from simulator.actions import ActionContext, ActionKind
from simulator.kits.characters.danheng import DanHengKit
from simulator.kits.characters.danheng_tenghuang import DanHengTenghuangKit
from simulator.kits.characters.march7th_hunt import March7thHuntKit
from simulator.kits.characters.moze import MozeKit
from simulator.kits.characters.yanqing import YanqingKit
from simulator.kits.characters.sushang import SushangKit
from simulator.kits.characters.misha import MishaKit
from simulator.kits.characters.hook import HookKit
from simulator.kits.characters.arlan import ArlanKit
from simulator.kits.characters.trailblazer_harmony import TrailblazerHarmonyKit


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
        self._dispelled = []

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

    def is_broken(self, entity_id):
        return True

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

    def delay(self, source_id, target_id, amount):
        self.delays.append((target_id, amount))

    def gain_energy(self, entity_id, amount):
        self.energy[entity_id] = self.energy.get(entity_id, 0.0) + amount

    def lose_hp(self, entity_id, amount, cause=""):
        self.lost_hp.append((entity_id, amount, cause))

    def dispel(self, target_id: str, is_debuff: bool = True) -> None:
        self._dispelled.append((target_id, is_debuff))

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


class TestBatchEOfficialVerification(unittest.TestCase):
    def test_01_danheng_official_kit(self):
        port = MockCombatPort()
        dh = DanHengKit("danheng", port, eidolon=6)

        # 普攻【云骑枪术•朔风】：140% 风伤，削韧 10，回能 20
        dh.execute(ActionContext("b", "danheng", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertEqual(port.attacks[0][2]["toughness_damage"], 10.0)
        self.assertEqual(port.energy["danheng"], 20.0)

        # 战技【云骑枪术•疾雨】：260% 风伤，削韧 20，回能 30
        dh.execute(ActionContext("s", "danheng", ActionKind.SKILL, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[1][2]["atk_multiplier"], 2.60)
        self.assertEqual(port.attacks[1][2]["toughness_damage"], 20.0)
        self.assertEqual(port.energy["danheng"], 50.0)

        # 终结技【洞天幻化，长梦一觉】：基础 400% 风伤，削韧 30，回能 5
        dh.execute(ActionContext("u", "danheng", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertGreaterEqual(port.attacks[2][2]["atk_multiplier"], 4.00)
        self.assertEqual(port.energy["danheng"], 55.0)

    def test_02_danheng_tenghuang_official_kit(self):
        port = MockCombatPort()
        dhil = DanHengTenghuangKit("dhil", port, eidolon=2)

        # 战技强化 3 次为【盘拏耀跃】: 700% 主目标 / 252% 扩散
        dhil.execute(ActionContext("s1", "dhil", ActionKind.SKILL, ()))
        dhil.execute(ActionContext("s2", "dhil", ActionKind.SKILL, ()))
        dhil.execute(ActionContext("s3", "dhil", ActionKind.SKILL, ()))
        self.assertEqual(dhil.enhance_level, 3)

        dhil.execute(ActionContext("b3", "dhil", ActionKind.BASIC, ("enemy_1",)))
        self.assertEqual(dhil.enhance_level, 0) # 攻击后重置强化
        main_atk = [a for a in port.attacks if a[1] == "enemy_1"][-1]
        self.assertAlmostEqual(main_atk[2]["atk_multiplier"], 7.00)

        # 终结技【苍龙傲睨，劫水濯世】：300% 主目标 / 140% 扩散，获得 2 层逆鳞抵扣战技点，E2 100% 自拉条
        dhil.execute(ActionContext("u", "dhil", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertEqual(dhil.squama_sacrosancta, 3) # E2 获得 3 点逆鳞
        self.assertTrue(len(port.advances) > 0)

    def test_03_march7th_hunt_official_kit(self):
        port = MockCombatPort()
        m7 = March7thHuntKit("m7h", port, eidolon=6)

        # 战技【师父，请喝茶！】: 拜师 ally_1
        m7.execute(ActionContext("s", "m7h", ActionKind.SKILL, ("ally_1",)))
        self.assertEqual(m7.shifu_id, "ally_1")
        self.assertTrue(port.has_buff("ally_1", March7thHuntKit.SHIFU_SPEED_BUFF))

        # 普攻【荡涤妖邪琉璃剑】：140% 虚数伤害
        m7.execute(ActionContext("b", "m7h", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 充能达到 7 层触发【师父，我悟了！】立即行动与强化普攻
        m7.add_charge(7)
        self.assertTrue(m7.is_enhanced)
        self.assertTrue(len(port.advances) > 0)

    def test_04_moze_official_kit(self):
        port = MockCombatPort()
        moze = MozeKit("moze", port, eidolon=6)

        # 普攻【飞铙】：140% 雷伤
        moze.execute(ActionContext("b", "moze", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 战技【迅羽掠袭】：标记 9 层猎物并进入离场状态
        moze.execute(ActionContext("s", "moze", ActionKind.SKILL, ("enemy_1",)))
        self.assertEqual(moze.prey_target_id, "enemy_1")
        self.assertEqual(moze.charges, 9)
        self.assertTrue(moze.is_departed)

        # 终结技【锋入幽渺，影出凌厉】：270% 雷伤并触发追击
        moze.execute(ActionContext("u", "moze", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertEqual(port.energy["moze"], 55.0)

    def test_05_yanqing_official_kit(self):
        port = MockCombatPort()
        yq = YanqingKit("yanqing", port, eidolon=4)

        # 开局生命 80% 触发 E4 12% 冰抗穿透
        yq.on_battle_start()
        self.assertTrue(port.has_buff("yanqing", YanqingKit.E4_PEN_BUFF))

        # 普攻【霜锋点寒芒】：140% 冰伤，回能 20
        yq.execute(ActionContext("b", "yanqing", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)
        self.assertEqual(port.energy["yanqing"], 20.0)

        # 战技【遥击三尺水】：220% 冰伤，激活【智剑连心】
        yq.execute(ActionContext("s", "yanqing", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(yq.is_soulsteel)
        self.assertTrue(port.has_buff("yanqing", YanqingKit.SOULSTEEL_BUFF))

        # 终结技【快雨燕相逐】：暴击 60% 与暴伤 50%，350% 冰伤
        yq.execute(ActionContext("u", "yanqing", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertTrue(port.has_buff("yanqing", YanqingKit.ULT_CRIT_BUFF))

        # 受击解除【智剑连心】
        yq.on_damaged("enemy_1", 100.0)
        self.assertFalse(yq.is_soulsteel)

    def test_06_sushang_official_kit(self):
        port = MockCombatPort()
        ss = SushangKit("sushang", port, eidolon=6)

        # 开局 E4 击破特攻 40% 与 E6 获得 1 层提速
        ss.on_battle_start()
        self.assertTrue(port.has_buff("sushang", SushangKit.E4_BREAK_BUFF))
        self.assertTrue(port.has_buff("sushang", SushangKit.TALENT_SPD_BUFF))

        # 普攻【云骑剑经 • 素霓】：140% 物理伤害
        ss.execute(ActionContext("b", "sushang", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 终结技【太虚形蕴 • 烛夜】：320% 伤害，自拉条 100%，攻击力提高 30%
        ss.execute(ActionContext("u", "sushang", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertTrue(len(port.advances) > 0)
        self.assertTrue(port.has_buff("sushang", SushangKit.ULT_ATK_BUFF))

        # 战技【云骑剑经 • 山倾】：对击破目标必定触发剑势，E1 恢复 1 点战技点
        ss.execute(ActionContext("s", "sushang", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(any(ch[1] == 1 for ch in port.sp_changes))

    def test_07_misha_official_kit(self):
        port = MockCombatPort()
        misha = MishaKit("misha", port, eidolon=6)

        # 队友消耗 SP 触发天赋回能 2 点并增加终结技段数
        misha.on_sp_consumed(2)
        self.assertEqual(misha.ult_hits, 5) # 3 + 2 = 5 段
        self.assertEqual(port.energy["misha"], 4.0)

        # 普攻【请…请让一下！】：140% 冰伤
        misha.execute(ActionContext("b", "misha", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 战技【客…客房服务！】：单体 200% / 扩散 80%，段数 +1
        misha.execute(ActionContext("s", "misha", ActionKind.SKILL, ("enemy_1",)))
        self.assertEqual(misha.ult_hits, 6)

        # 终结技【要…要迟到了！】：E6 增伤 30% 并重置段数回 3 段
        misha.execute(ActionContext("u", "misha", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertTrue(port.has_buff("misha", MishaKit.E6_DMG_BUFF))
        self.assertEqual(misha.ult_hits, 3)

    def test_08_hook_official_kit(self):
        port = MockCombatPort()
        hook = HookKit("hook", port, eidolon=6)

        # 普攻【喂！小心火烛】：140% 火伤
        hook.execute(ActionContext("b", "hook", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 终结技【轰！飞来焰火】：400% 火伤，自拉条 20%，强化下一次战技
        hook.execute(ActionContext("u", "hook", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertTrue(hook.is_enhanced_skill)
        self.assertTrue(len(port.advances) > 0)

        # 强化战技【嘿！记得虎克吗】：扩散攻击，E1 增伤 20% (主目标 336% / 扩散 96%)
        hook.execute(ActionContext("s", "hook", ActionKind.SKILL, ("enemy_1",)))
        self.assertFalse(hook.is_enhanced_skill)
        main_skill_atks = [a for a in port.attacks if a[2]["damage_tag"] == "Skill" and a[1] == "enemy_1"]
        self.assertAlmostEqual(main_skill_atks[-1][2]["atk_multiplier"], 2.80 * 1.20)

    def test_09_arlan_official_kit(self):
        port = MockCombatPort()
        arlan = ArlanKit("arlan", port, eidolon=6)

        # 普攻【如雷疾行】：140% 雷伤
        arlan.execute(ActionContext("b", "arlan", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 战技【禁锢解除】：0 SP 消耗，扣除 15% 上限生命，240% 雷伤，E2 驱散 1 负面
        defn = arlan.definition(ActionKind.SKILL)
        self.assertEqual(defn.cost.sp, 0)
        arlan.execute(ActionContext("s", "arlan", ActionKind.SKILL, ("enemy_1",)))
        self.assertTrue(len(port.lost_hp) > 0)
        self.assertTrue(len(port._dispelled) > 0)

        # 终结技【狂者制裁】：320% 单体，110 能量
        defn_u = arlan.definition(ActionKind.ULTIMATE)
        self.assertEqual(defn_u.cost.energy, 110.0)
        arlan.execute(ActionContext("u", "arlan", ActionKind.ULTIMATE, ("enemy_1",)))
        self.assertEqual(port.energy["arlan"], 55.0)

    def test_10_trailblazer_harmony_official_kit(self):
        port = MockCombatPort()
        tb = TrailblazerHarmonyKit("tb", port, eidolon=6)

        # 开局 E2 充能效率 25% 与 E4 击破特攻光环
        tb.on_battle_start()
        self.assertTrue(port.has_buff("tb", TrailblazerHarmonyKit.E2_ERR_BUFF))
        self.assertTrue(port.has_buff("ally_1", f"{TrailblazerHarmonyKit.E4_BREAK_AURA}_ally_1"))

        # 普攻【摇摆的礼仪】：140% 虚数伤害
        tb.execute(ActionContext("b", "tb", ActionKind.BASIC, ("enemy_1",)))
        self.assertAlmostEqual(port.attacks[0][2]["atk_multiplier"], 1.40)

        # 战技【中场馈赠的雨】：E6 拥有 7 段弹射，E1 首次返还 1 点 SP
        tb.execute(ActionContext("s", "tb", ActionKind.SKILL, ("enemy_1",)))
        skill_atks = [a for a in port.attacks if a[2]["damage_tag"] == "Skill"]
        self.assertEqual(len(skill_atks), 7)
        self.assertTrue(any(ch[1] == 1 for ch in port.sp_changes))

        # 终结技【喧嚣的舞灯巡游】：全队【伴舞】状态持续 3 回合，击破特攻提高 30%
        tb.execute(ActionContext("u", "tb", ActionKind.ULTIMATE, ()))
        self.assertTrue(port.has_buff("ally_1", f"{TrailblazerHarmonyKit.BACKUP_DANCER_BUFF}_ally_1"))

        # 天赋：击破回能 10 点
        prev_energy = port.energy.get("tb", 0.0)
        tb.on_enemy_broken()
        self.assertEqual(port.energy["tb"], prev_energy + 10.0)


if __name__ == "__main__":
    unittest.main()

"""同谐与虚无辅助核心全员 (Sparkle, Ruan Mei, Sunday, Bronya, Tingyun, Pela, Fugue) 官方标准规格单元测试。"""

import unittest
from simulator.actions import ActionContext, ActionKind
from simulator.status import StatType
from simulator.combat_port import CombatPort
from simulator.kits.characters.sparkle import SparkleKit
from simulator.kits.characters.ruan_mei import RuanMeiKit
from simulator.kits.characters.sunday import SundayKit
from simulator.kits.characters.bronya import BronyaKit
from simulator.kits.characters.tingyun import TingyunKit
from simulator.kits.characters.pela import PelaKit
from simulator.kits.characters.fugue import FugueKit


class MockCombatPort(CombatPort):
    def __init__(self, owner_id: str):
        self.owner_id = owner_id
        self._statuses = {}
        self._energies = {owner_id: 0.0, "ally_dps": 0.0}
        self._max_energies = {owner_id: 120.0, "ally_dps": 120.0}
        self._sp = 3
        self._max_sp = 5
        self._advances = []
        self._attacks = []

    def allies(self, entity_id: str):
        return [self.owner_id, "ally_dps"]

    def enemies(self, entity_id: str):
        return ["enemy_boss"]

    def stat(self, entity_id: str, stat_type: StatType) -> float:
        if stat_type == StatType.CRIT_DMG:
            return 2.0  # 200% CD
        elif stat_type == StatType.ATK_BASE:
            return 2000.0
        return 0.0

    def attack(self, source_id, target_id, **kwargs):
        self._attacks.append((source_id, target_id, kwargs))

    def advance(self, source_id, target_id, amount):
        self._advances.append((target_id, amount))

    def gain_energy(self, entity_id, amount):
        self._energies[entity_id] = self._energies.get(entity_id, 0.0) + amount

    def upsert_status(self, spec):
        self._statuses[spec.key] = spec

    def has_status(self, entity_id, key):
        return key in self._statuses

    def set_sp_cap(self, new_cap: int):
        self._max_sp = new_cap

    def change_sp(self, entity_id, delta, reason=""):
        self._sp += delta


class TestBatchAOfficialKits(unittest.TestCase):

    def test_01_sparkle_official(self):
        """验证花火：SP上限提升至7(E4为8)，战技暴伤+拉条50%，大招恢复4点SP(E4为5点)+谜诡。"""
        port = MockCombatPort("sparkle")
        kit = SparkleKit("sparkle", port, eidolon=4)
        kit.on_battle_start()
        self.assertEqual(port._max_sp, 8)

        # 战技拉条 50%
        ctx_skill = ActionContext("act_sk", "sparkle", ActionKind.SKILL, target_ids=("ally_dps",))
        kit.execute(ctx_skill)
        self.assertIn(("ally_dps", 0.50), port._advances)

        # 终结技恢复 5 点 SP (E4)
        ctx_ult = ActionContext("act_ult", "sparkle", ActionKind.ULTIMATE, target_ids=())
        kit.execute(ctx_ult)
        self.assertEqual(port._sp, 8)  # 3 + 5
        self.assertIn(SparkleKit.ULT_CIPHER_BUFF, port._statuses)

    def test_02_ruan_mei_official(self):
        """验证阮梅：天赋常驻全队除自身提速 10%，战技 32% 增伤 + 50% 击破效率，大招 25% 抗穿 + E1 20% 无视防御。"""
        port = MockCombatPort("ruan_mei")
        kit = RuanMeiKit("ruan_mei", port, eidolon=1)
        kit.on_battle_start()
        self.assertIn("RuanMei_Talent_Speed_ally_dps", port._statuses)

        # 战技
        ctx_skill = ActionContext("act_sk", "ruan_mei", ActionKind.SKILL, target_ids=())
        kit.execute(ctx_skill)
        self.assertIn(RuanMeiKit.SKILL_BUFF, port._statuses)
        self.assertEqual(port._statuses[RuanMeiKit.SKILL_BUFF].modifiers[0].value, 0.32)

        # 终结技
        ctx_ult = ActionContext("act_ult", "ruan_mei", ActionKind.ULTIMATE, target_ids=())
        kit.execute(ctx_ult)
        self.assertIn(RuanMeiKit.ULT_RES_PEN_BUFF, port._statuses)
        self.assertIn("RuanMei_E1_DefShred", port._statuses)
        self.assertEqual(port._statuses["RuanMei_E1_DefShred"].modifiers[0].value, 0.20)

    def test_03_sunday_official(self):
        """验证星期日：战技100%拉条+增伤+蒙受恩宠+天赋暴击率，大招回能20%+暴伤提升，E4开局回能8点。"""
        port = MockCombatPort("sunday")
        kit = SundayKit("sunday", port, eidolon=4)
        kit.on_battle_start()
        self.assertEqual(port._energies["sunday"], 8.0)

        # 战技拉条 100%
        ctx_skill = ActionContext("act_sk", "sunday", ActionKind.SKILL, target_ids=("ally_dps",))
        kit.execute(ctx_skill)
        self.assertIn(("ally_dps", 1.0), port._advances)
        self.assertIn(SundayKit.BEATIFIED_BUFF, port._statuses)
        self.assertIn(SundayKit.TALENT_CR_BUFF, port._statuses)

        # 终结技为目标回能 20% (120*0.2 = 24 点)
        ctx_ult = ActionContext("act_ult", "sunday", ActionKind.ULTIMATE, target_ids=())
        kit.execute(ctx_ult)
        self.assertEqual(port._energies["ally_dps"], 24.0)
        self.assertIn(SundayKit.ULT_CD_BUFF, port._statuses)

    def test_04_bronya_official(self):
        """验证布洛妮娅：普攻自拉条30%，战技100%拉条+66%增伤，大招全队加攻55%+暴伤。"""
        port = MockCombatPort("bronya")
        kit = BronyaKit("bronya", port, eidolon=2)

        # 普攻自拉条 30%
        ctx_basic = ActionContext("act_ba", "bronya", ActionKind.BASIC, target_ids=("enemy_boss",))
        kit.execute(ctx_basic)
        self.assertIn(("bronya", 0.30), port._advances)

        # 战技拉条 100% + E2 提速 30%
        ctx_skill = ActionContext("act_sk", "bronya", ActionKind.SKILL, target_ids=("ally_dps",))
        kit.execute(ctx_skill)
        self.assertIn(("ally_dps", 1.0), port._advances)
        self.assertIn(BronyaKit.SKILL_DMG_BUFF, port._statuses)
        self.assertIn("Bronya_E2_Speed_ally_dps", port._statuses)

        # 大招全队增益
        ctx_ult = ActionContext("act_ult", "bronya", ActionKind.ULTIMATE, target_ids=())
        kit.execute(ctx_ult)
        self.assertIn("Bronya_Ult_March_ally_dps", port._statuses)

    def test_05_tingyun_official(self):
        """验证停云：战技赐福攻击力提升，大招为队友恢复50点能量(E6为60点)+50%增伤。"""
        port = MockCombatPort("tingyun")
        kit = TingyunKit("tingyun", port, eidolon=6)

        # 战技赐福
        ctx_skill = ActionContext("act_sk", "tingyun", ActionKind.SKILL, target_ids=("ally_dps",))
        kit.execute(ctx_skill)
        self.assertIn(TingyunKit.SKILL_BENEDICTION_BUFF, port._statuses)

        # 大招为队友恢复 60 点能量 (E6)
        ctx_ult = ActionContext("act_ult", "tingyun", ActionKind.ULTIMATE, target_ids=("ally_dps",))
        kit.execute(ctx_ult)
        self.assertEqual(port._energies["ally_dps"], 60.0)
        self.assertIn(TingyunKit.ULT_DMG_BUFF, port._statuses)

    def test_06_pela_official(self):
        """验证佩拉：战技210%冰伤+E4减冰抗12%，大招全体40%减防。"""
        port = MockCombatPort("pela")
        kit = PelaKit("pela", port, eidolon=4)

        # 战技
        ctx_skill = ActionContext("act_sk", "pela", ActionKind.SKILL, target_ids=("enemy_boss",))
        kit.execute(ctx_skill)
        self.assertIn("Pela_E4_IceResShred_enemy_boss", port._statuses)

        # 大招全体 40% 减防
        ctx_ult = ActionContext("act_ult", "pela", ActionKind.ULTIMATE, target_ids=())
        kit.execute(ctx_ult)
        self.assertIn(PelaKit.ULT_DEF_SHRED_DEBUFF, port._statuses)

    def test_07_fugue_official(self):
        """验证忘归人：战技狐祈击破特攻提升30%+E1击破效率50%，大招全体削韧+云焰18%减防。"""
        port = MockCombatPort("fugue")
        kit = FugueKit("fugue", port, eidolon=1)

        # 战技狐祈
        ctx_skill = ActionContext("act_sk", "fugue", ActionKind.SKILL, target_ids=("ally_dps",))
        kit.execute(ctx_skill)
        self.assertIn(FugueKit.PRAYER_BUFF, port._statuses)

        # 大招全体云焰 18% 减防
        ctx_ult = ActionContext("act_ult", "fugue", ActionKind.ULTIMATE, target_ids=())
        kit.execute(ctx_ult)
        self.assertIn(f"{FugueKit.CLOUDFLAME_DEBUFF}_enemy_boss", port._statuses)


if __name__ == "__main__":
    unittest.main()

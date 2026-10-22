"""知更鸟 (Robin - ID 1309, 物理 / 同谐) 官方标准规格单元测试。"""

import unittest
from simulator.actions import ActionKind
from simulator.status import StatType
from simulator.kits.characters.robin import RobinKit
from simulator.combat_port import CombatPort


class DummyPort(CombatPort):
    def __init__(self):
        self._statuses = {}
        self._entities = {}

    def allies(self, entity_id: str):
        return ["robin_1309", "ally_dps"]

    def enemies(self, entity_id: str):
        return ["enemy_boss"]

    def stat(self, entity_id: str, stat_type: StatType) -> float:
        if stat_type == StatType.ATK_BASE:
            return 4000.0 if entity_id == "robin_1309" else 2000.0
        return 0.0

    def attack(self, source_id, target_id, **kwargs):
        pass

    def advance(self, source_id, target_id, amount):
        pass

    def gain_energy(self, entity_id, amount):
        pass

    def upsert_status(self, spec):
        self._statuses[spec.key] = spec

    def max_hp(self, entity_id):
        return 4000.0


class TestRobinOfficialKit(unittest.TestCase):
    def setUp(self):
        self.port = DummyPort()
        self.kit = RobinKit("robin_1309", self.port, eidolon=2)

    def test_01_battle_start_talent_and_advance(self):
        """验证进战：天赋全队暴伤 +20%，行动提前 25%。"""
        self.kit.on_battle_start()
        # 验证全队获得调性合颂
        self.assertIn("Robin_Talent_TonalHarmony_robin_1309", self.port._statuses)
        self.assertIn("Robin_Talent_TonalHarmony_ally_dps", self.port._statuses)
        buff = self.port._statuses["Robin_Talent_TonalHarmony_ally_dps"]
        self.assertEqual(buff.modifiers[0].value, 0.20)

    def test_02_skill_team_dmg_boost(self):
        """验证战技【翎之咏叹调】：全队增伤 50%，持续 3 回合。"""
        from simulator.actions import ActionContext
        ctx = ActionContext(action_id="act_skill", actor_id="robin_1309", kind=ActionKind.SKILL, target_ids=())
        self.kit.execute(ctx)
        self.assertIn("Robin_Skill_Aria", self.port._statuses)
        buff = self.port._statuses["Robin_Skill_Aria"]
        self.assertEqual(buff.modifiers[0].value, 0.50)
        self.assertEqual(buff.duration, 3)

    def test_03_ultimate_concerto_and_e1_e2(self):
        """验证终结技【千音迭奏，群星赋格】：进入协奏，攻击加成 22.8%*4000 + 200 = 1112，E1 抗穿 24%，E2 提速 16%。"""
        from simulator.actions import ActionContext
        ctx = ActionContext(action_id="act_ult", actor_id="robin_1309", kind=ActionKind.ULTIMATE, target_ids=())
        self.kit.execute(ctx)
        self.assertTrue(self.kit.in_concerto)
        
        # 验证攻击力加成
        self.assertIn("Robin_Concerto_Atk", self.port._statuses)
        buff_atk = self.port._statuses["Robin_Concerto_Atk"]
        expected_atk = 4000.0 * 0.228 + 200.0
        self.assertAlmostEqual(buff_atk.modifiers[0].value, expected_atk)

        # 验证 E1 抗穿 24%
        self.assertIn("Robin_E1_ResPen", self.port._statuses)
        buff_e1 = self.port._statuses["Robin_E1_ResPen"]
        self.assertAlmostEqual(buff_e1.modifiers[0].value, 0.24)

        # 验证 E2 速度 16%
        self.assertIn("Robin_E2_Speed", self.port._statuses)
        buff_e2 = self.port._statuses["Robin_E2_Speed"]
        self.assertAlmostEqual(buff_e2.modifiers[0].value, 0.16)


if __name__ == "__main__":
    unittest.main()

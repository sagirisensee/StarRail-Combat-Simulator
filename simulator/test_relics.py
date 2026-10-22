#!/usr/bin/env python3
"""遗器系统解耦与运行时处理器单元测试套件 (Relics System Tests)."""
import unittest
from simulator.core import TurnSimulator, Entity
from simulator.relics import RelicRegistry, RelicSetHandler
from simulator.kits.characters.fengjin import FengjinKit
from simulator.kits.characters.tibao import TibaoKit
from simulator.kits.characters.acheron import AcheronKit
from simulator.status import StatType


class TestRelicRegistryAndDecoupling(unittest.TestCase):
    def test_relic_registry_lookup(self):
        # 1. 按 ID 查询
        spec_125, cls_125 = RelicRegistry.get(125)
        self.assertEqual(spec_125.name, "烈阳惊雷的女武神")

        spec_124, cls_124 = RelicRegistry.get(124)
        self.assertEqual(spec_124.name, "哀歌覆国的诗人")

        # 2. 按别名与规范名查询
        _, cls_valk_alias = RelicRegistry.get("valkyrie_of_sun_and_thunder")
        self.assertIs(cls_125, cls_valk_alias)

        _, cls_poet_alias = RelicRegistry.get("沉醉于狂欢的诗人")
        self.assertIs(cls_124, cls_poet_alias)

    def test_valkyrie_decoupled_from_fengjin(self):
        # 风堇裸体 (无遗器) 进战：不应挂载【烈阳惊雷的女武神】
        fengjin_naked = Entity(name="风堇", base_speed=130.0, base_atk=1000.0, kit=FengjinKit("风堇", None))
        ally = Entity(name="队友", base_speed=100.0, base_atk=1000.0)
        sim1 = TurnSimulator(entities=[fengjin_naked, ally], use_techniques=False)

        snap_ally1 = sim1.query_status("队友")
        buff_names1 = [b["name"] for b in snap_ally1["buffs"]]
        self.assertNotIn("甘霖", buff_names1, "裸体风堇绝不应附带女武神遗器效果")

        # 任意其他角色 (如队友) 穿戴女武神 4 件套进战：应正常为全队提供暴伤 +15%
        valk_handler = RelicRegistry.create("烈阳惊雷的女武神", owner_id="队友", pieces=4)
        self.assertIsNotNone(valk_handler)
        ally_with_valk = Entity(
            name="队友", 
            base_speed=100.0, 
            base_atk=1000.0,
            relic_handlers=[valk_handler]
        )
        sim2 = TurnSimulator(entities=[fengjin_naked, ally_with_valk], use_techniques=False)

        snap_fengjin = sim2.query_status("风堇")
        buff_names2 = [b["name"] for b in snap_fengjin["buffs"]]
        self.assertIn("甘霖", buff_names2, "其他角色装备女武神应正常为全队赋予暴伤增益")
        self.assertAlmostEqual(snap_fengjin["current_crit_dmg"], snap_fengjin["base_crit_dmg"] + 0.15, places=2)

    def test_poet_decoupled_from_tibao(self):
        # 缇宝裸体 (无遗器) 进战：不应挂载【哀歌覆国的诗人】
        tibao_naked = Entity(name="缇宝", base_speed=90.0, base_atk=1000.0, kit=TibaoKit("缇宝", None))
        sim1 = TurnSimulator(entities=[tibao_naked], use_techniques=False)

        snap_naked = sim1.query_status("缇宝")
        buff_names1 = [b["name"] for b in snap_naked["buffs"]]
        self.assertNotIn("哀歌覆国的诗人", buff_names1, "裸体缇宝绝不应附带诗人遗器效果")

        # 其他低速角色 (<95 速度) 穿戴诗人 4 件套：获得 32% 暴击率
        poet_handler = RelicRegistry.create(124, owner_id="其他角色", pieces=4)
        slow_char = Entity(name="其他角色", base_speed=80.0, base_atk=1000.0, relic_handlers=[poet_handler])
        sim2 = TurnSimulator(entities=[slow_char], use_techniques=False)

        snap_slow = sim2.query_status("其他角色")
        buff_names2 = [b["name"] for b in snap_slow["buffs"]]
        self.assertIn("哀歌覆国的诗人", buff_names2)
        self.assertAlmostEqual(snap_slow["current_crit_rate"], snap_slow["base_crit_rate"] + 0.32, places=2)

        # 中速角色 (100 速度，在 95~110 之间)：获得 20% 暴击率
        poet_handler_mid = RelicRegistry.create(124, owner_id="中速角色", pieces=4)
        mid_char = Entity(name="中速角色", base_speed=100.0, base_atk=1000.0, relic_handlers=[poet_handler_mid])
        sim3 = TurnSimulator(entities=[mid_char], use_techniques=False)

        snap_mid = sim3.query_status("中速角色")
        self.assertAlmostEqual(snap_mid["current_crit_rate"], snap_mid["base_crit_rate"] + 0.20, places=2)

    def test_acheron_ultimate_protocol_decoupling(self):
        # 验证黄泉通过 Kit 协议与核心调度器解耦
        acheron = Entity(name="黄泉", base_speed=101.0, base_atk=1000.0, kit=AcheronKit("黄泉", None))
        sim = TurnSimulator(entities=[acheron], use_techniques=False)

        # 初始 0 残梦，不可开大
        self.assertFalse(sim.can_cast_ultimate("黄泉"))
        self.assertEqual(acheron.kit.get_energy_display(acheron), "残梦: 0/9")

        # 充满 9 点残梦
        acheron.kit.slashed_dream = 9
        self.assertTrue(sim.can_cast_ultimate("黄泉"))
        self.assertEqual(acheron.kit.get_energy_display(acheron), "残梦: 9/9")

        # 施放终结技，残梦清空
        success = sim.cast_ultimate("黄泉")
        self.assertTrue(success)
        self.assertEqual(acheron.kit.slashed_dream, 0)
        self.assertFalse(sim.can_cast_ultimate("黄泉"))


if __name__ == "__main__":
    unittest.main()

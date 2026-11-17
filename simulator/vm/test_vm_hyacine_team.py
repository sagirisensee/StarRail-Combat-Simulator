# coding: utf-8
"""Phase 2/3/4 官方 ConfigAbility VM 实装对账测试（风堇 + 长夜月 + 缇宝 + 晴歌）。"""
import unittest

from simulator.core import TurnSimulator
from simulator.entity import Entity
from simulator.events import HealAppliedEvent
from simulator.vm import (
    ConfigAbilityKitAdapter,
    ConfigAbilityLightConeAdapter,
    ConfigAbilityRelicAdapter,
    GameDataLoader,
)


class TestVMHyacineTeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = GameDataLoader()

    def _make_hyacine_evernight_sim(self, use_techniques: bool = True):
        evernight = Entity(
            name="长夜月",
            base_speed=115.0,
            base_atk=1443.0,
            base_crit_rate=0.50,
            base_crit_dmg=2.00,
            max_hp=8108.1,
            current_hp=8108.1,
            base_white_hp=2467.0,
            base_white_speed=99.0,
            element="Ice",
            path="Memory",
            avatar_id=1413,
            eidolon=2,
            kit=ConfigAbilityKitAdapter("长夜月", 1413, eidolon=2, loader=self.loader),
            light_cone=ConfigAbilityLightConeAdapter("长夜月", 23049, superimposition=1),
            relic_handlers=[
                ConfigAbilityRelicAdapter("长夜月", 127, pieces=4),
                ConfigAbilityRelicAdapter("长夜月", 319, pieces=2),
            ],
        )
        hyacine = Entity(
            name="风堇",
            base_speed=213.8,
            base_atk=1336.0,
            base_crit_rate=0.05,
            base_crit_dmg=0.901,
            max_hp=5563.65,
            current_hp=5563.65,
            base_white_hp=2250.0,
            base_white_speed=110.0,
            base_outgoing_healing=0.545,
            element="Wind",
            path="Memory",
            avatar_id=1409,
            eidolon=1,
            kit=ConfigAbilityKitAdapter("风堇", 1409, eidolon=1, loader=self.loader),
            light_cone=ConfigAbilityLightConeAdapter("风堇", 23042, superimposition=1),
            relic_handlers=[
                ConfigAbilityRelicAdapter("风堇", 125, pieces=4),
                ConfigAbilityRelicAdapter("风堇", 320, pieces=2),
            ],
        )
        enemy = Entity(
            name="木桩首领",
            base_speed=100.0,
            base_atk=1000.0,
            max_hp=1_000_000.0,
            current_hp=1_000_000.0,
            is_enemy=True,
            is_boss=True,
            weaknesses=["Wind", "Ice", "Quantum"],
        )
        heals = []
        sim = TurnSimulator(
            entities=[evernight, hyacine, enemy],
            use_techniques=use_techniques,
            auto_ult=False,
        )
        sim.event_bus.subscribe(HealAppliedEvent, lambda e: heals.append(e))
        return sim, heals

    def test_enter_battle_priority_summons_evernight_before_hyacine_technique(self):
        sim, _ = self._make_hyacine_evernight_sim(use_techniques=True)
        # 1. 长夜月被动 Priority=-92 应在 AV=0 召唤「长夜」
        self.assertIsNotNone(sim.get_entity("长夜"))
        # 2. 风堇暴风停歇 (Speed > 200) 应在进场后立即生效 (+20% MaxHP)
        hy_max_hp = sim.port.max_hp("风堇")
        self.assertGreater(hy_max_hp, 6000.0)
        # 3. 风堇秘技 (+20% MaxHP) 应在 AV=0 挂载于全队
        self.assertTrue(sim.vm_runtime.modifier_engine.has_modifier("风堇", "MAvatar_Hyacine_00_Maze_AddMaxHp"))
        self.assertTrue(sim.vm_runtime.modifier_engine.has_modifier("长夜月", "MAvatar_Hyacine_00_Maze_AddMaxHp"))

    def test_hyacine_skill_and_ultimate_summon_ika_and_heal(self):
        sim, heals = self._make_hyacine_evernight_sim(use_techniques=True)
        from simulator.actions import ActionKind
        actor = sim.advance_to_next_turn()
        self.assertIsNotNone(actor)
        # 推进到风堇回合并施放战技
        while actor.name != "风堇":
            sim.execute_current_turn()
            actor = sim.advance_to_next_turn()
        sim.execute_current_turn(action_override=ActionKind.SKILL, target_ids=("风堇",))
        self.assertIsNotNone(sim.get_entity("小伊卡"))
        self.assertGreater(len(heals), 0)
        # 女武神 4pc 触发后应同时挂上 MRelic_125_Buff (+6% 速度) 与全队光环 MRelic_125_Buff2 (+15% 暴伤)
        self.assertTrue(sim.vm_runtime.modifier_engine.has_modifier("风堇", "MRelic_125_Buff"))
        self.assertTrue(sim.vm_runtime.modifier_engine.has_modifier("长夜月", "MRelic_125_Buff2"))
        self.assertTrue(sim.vm_runtime.modifier_engine.has_modifier("小伊卡", "MRelic_125_Buff2"))


if __name__ == "__main__":
    unittest.main()

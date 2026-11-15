# coding: utf-8
"""关卡 30126122 与月夜天马/正阳狮鹫/流星铁鹰 Kit 单元测试与时间轴对账。"""

import unittest

from simulator.actions import ActionKind
from simulator.core import Entity, TurnSimulator
from simulator.events import ActionEndEvent, EnemyDefeatedEvent, TurnBeginEvent
from simulator.kits.enemies import (
    AQUILA_MARK_KEY,
    EnemyActionContext,
    MeteorEagleKit,
    MoonlitPegasusKit,
    ORONYX_MARK_KEY,
    STANDARD_ACTION_DISTANCE,
    SunlitGriffinKit,
)
from simulator.stage_30126122 import (
    EAGLE_HP,
    EAGLE_SPEED,
    EAGLE_TOUGHNESS,
    EAGLE_WEAKNESSES,
    GRIFFIN_HP,
    GRIFFIN_INITIAL_DISTANCE,
    GRIFFIN_SPEED,
    GRIFFIN_TOUGHNESS,
    GRIFFIN_WEAKNESSES,
    PEGASUS_HP,
    PEGASUS_SPEED,
    PEGASUS_TOUGHNESS,
    PEGASUS_WEAKNESSES,
    build_stage_30126122,
)


def _dummy_ally(name: str = "测试角色", speed: float = 100.0) -> Entity:
    ent = Entity(
        name=name,
        base_speed=speed,
        base_atk=1000.0,
        max_hp=10000.0,
        current_hp=10000.0,
        max_toughness=0.0,
        current_toughness=0.0,
        weaknesses=[],
        is_enemy=False,
    )
    ent.base_def = 1000.0
    ent.def_val = 1000.0
    ent.level = 80
    return ent


class TestEnemyKitsUnit(unittest.TestCase):
    def test_meteor_eagle_windwalk_resets_distance_to_zero(self) -> None:
        ally = _dummy_ally("风堇", speed=50.0)
        eagle = Entity(
            name="流星铁鹰_test",
            base_speed=EAGLE_SPEED,
            base_atk=950.0,
            max_hp=EAGLE_HP,
            current_hp=EAGLE_HP,
            max_toughness=EAGLE_TOUGHNESS,
            current_toughness=EAGLE_TOUGHNESS,
            weaknesses=list(EAGLE_WEAKNESSES),
            is_enemy=True,
        )
        eagle.distance_remaining = 5000.0
        sim = TurnSimulator(entities=[ally, eagle], use_techniques=False, auto_ult=False)

        from simulator.stage_30126122 import Stage30126122CombatPort

        port = Stage30126122CombatPort(sim)
        kit = MeteorEagleKit(owner_id=eagle.name, port=port, windwalk_ready=True)
        eagle.kit = kit

        res1 = kit.execute_turn(EnemyActionContext(action_id="a1", actor_id=eagle.name))
        self.assertEqual(res1.reset_distance, 0.0)
        self.assertFalse(kit.windwalk_ready)

        res2 = kit.execute_turn(EnemyActionContext(action_id="a2", actor_id=eagle.name))
        self.assertEqual(res2.reset_distance, STANDARD_ACTION_DISTANCE)

    def test_pegasus_oronyx_mark_cycle_and_ult_clear(self) -> None:
        ally = _dummy_ally("风堇", speed=50.0)
        pegasus = Entity(
            name="月夜天马",
            base_speed=PEGASUS_SPEED,
            base_atk=1400.0,
            max_hp=PEGASUS_HP,
            current_hp=PEGASUS_HP,
            max_toughness=PEGASUS_TOUGHNESS,
            current_toughness=PEGASUS_TOUGHNESS,
            weaknesses=list(PEGASUS_WEAKNESSES),
            is_enemy=True,
        )
        sim = TurnSimulator(entities=[ally, pegasus], use_techniques=False, auto_ult=False)
        from simulator.stage_30126122 import Stage30126122CombatPort

        port = Stage30126122CombatPort(sim)
        kit = MoonlitPegasusKit(owner_id=pegasus.name, port=port)

        # Turn 1: 施加欧洛尼斯印记
        kit.execute_turn(EnemyActionContext(action_id="p1", actor_id=pegasus.name))
        self.assertTrue(port.has_mark_status(target_id=ally.name, mark_key=ORONYX_MARK_KEY))

        # 我方施放终结技 -> 清除印记
        kit.on_event(
            ActionEndEvent(
                av=10.0,
                cycle=0,
                actor_id=ally.name,
                actor_name=ally.name,
                action_type="终结技",
                action_kind=ActionKind.ULTIMATE,
                skill_config_id=0,
                action_id=1,
            )
        )
        self.assertFalse(port.has_mark_status(target_id=ally.name, mark_key=ORONYX_MARK_KEY))

        # 重新挂上印记并在 Turn 3 引爆清除
        kit.execute_turn(EnemyActionContext(action_id="p2", actor_id=pegasus.name))
        port.apply_mark_status(
            owner_id=pegasus.name,
            target_id=ally.name,
            mark_key=ORONYX_MARK_KEY,
            mark_name="欧洛尼斯印记",
        )
        hp_before = ally.current_hp
        kit.execute_turn(EnemyActionContext(action_id="p3", actor_id=pegasus.name))
        self.assertLess(ally.current_hp, hp_before)
        self.assertFalse(port.has_mark_status(target_id=ally.name, mark_key=ORONYX_MARK_KEY))

    def test_griffin_summon_resummon_and_mark_clear_on_eagle_death(self) -> None:
        ally = _dummy_ally("长夜月", speed=50.0)
        sim, director = build_stage_30126122([ally])
        griffin = sim.get_entity("正阳狮鹫")
        self.assertIsNotNone(griffin)
        self.assertEqual(griffin.distance_remaining, GRIFFIN_INITIAL_DISTANCE)

        # 手动触发正阳狮鹫首动召唤
        res = griffin.kit.execute_turn(EnemyActionContext(action_id="g1", actor_id=griffin.name))
        self.assertEqual(res.reset_distance, STANDARD_ACTION_DISTANCE)
        self.assertEqual(griffin.kit.generation, 1)
        self.assertEqual(len(griffin.kit.summon_ids), 3)

        from simulator.stage_30126122 import Stage30126122CombatPort

        port = Stage30126122CombatPort(sim)
        self.assertTrue(port.has_mark_status(target_id=ally.name, mark_key=AQUILA_MARK_KEY))

        # 击杀第 1 只流星铁鹰 -> 解除艾格勒印记
        e1 = sim.get_entity(griffin.kit.summon_ids[0])
        e1.current_hp = 0.0
        griffin.kit.on_event(
            EnemyDefeatedEvent(av=50.0, cycle=0, attacker_name=ally.name, target_name=e1.name)
        )
        self.assertFalse(port.has_mark_status(target_id=ally.name, mark_key=AQUILA_MARK_KEY))

        # 其余 2 只仍存活时，正阳狮鹫常规攻击不重召 (第1次常规全体)
        griffin.kit.execute_turn(EnemyActionContext(action_id="g2", actor_id=griffin.name))
        self.assertEqual(griffin.kit.generation, 1)

        # 全部铁鹰阵亡后，召唤后第2次常规攻击 (4段单体) 仍不重召，第3次行动才重召第 2 代
        for eid in griffin.kit.summon_ids:
            sim.get_entity(eid).current_hp = 0.0
        griffin.kit.execute_turn(EnemyActionContext(action_id="g3", actor_id=griffin.name))
        self.assertEqual(griffin.kit.generation, 1)

        griffin.kit.execute_turn(EnemyActionContext(action_id="g4", actor_id=griffin.name))
        self.assertEqual(griffin.kit.generation, 2)
        self.assertEqual(len(griffin.kit.summon_ids), 3)


class TestStage30126122Timeline(unittest.TestCase):
    def test_stage_stats_and_enemy_turn_timeline_match_log(self) -> None:
        # 构造慢速木桩我方，避免干扰敌方行动轴，仅验证敌方 AV 节拍与流星铁鹰 114.90 双连动
        ally = _dummy_ally("测试桩", speed=10.0)
        ally.max_hp = 1000000.0
        ally.current_hp = 1000000.0
        sim, director = build_stage_30126122([ally])

        pegasus = sim.get_entity("月夜天马")
        griffin = sim.get_entity("正阳狮鹫")
        self.assertAlmostEqual(pegasus.max_hp, PEGASUS_HP, places=2)
        self.assertEqual(pegasus.base_speed, PEGASUS_SPEED)
        self.assertEqual(pegasus.max_toughness, PEGASUS_TOUGHNESS)
        self.assertEqual(pegasus.weaknesses, PEGASUS_WEAKNESSES)

        self.assertAlmostEqual(griffin.max_hp, GRIFFIN_HP, places=2)
        self.assertEqual(griffin.base_speed, GRIFFIN_SPEED)
        self.assertEqual(griffin.max_toughness, GRIFFIN_TOUGHNESS)
        self.assertEqual(griffin.weaknesses, GRIFFIN_WEAKNESSES)

        enemy_turns = []

        def _on_turn(ev: TurnBeginEvent) -> None:
            ent = sim.get_entity(ev.actor_id)
            if ent is not None and ent.is_enemy:
                enemy_turns.append((round(ev.av, 2), ev.actor_name))

        sim.event_bus.subscribe(TurnBeginEvent, _on_turn)

        # 推进至 230 AV
        for _ in range(40):
            if sim.current_av >= 230.0:
                break
            sim.step()
            director.after_step()
            # 在 150 AV 模拟击杀第一批 3 只流星铁鹰，验证 220.96 AV 正阳狮鹫重召
            if sim.current_av >= 150.0:
                for eid in griffin.kit.summon_ids:
                    if eid.startswith("流星铁鹰_g1_"):
                        e = sim.get_entity(eid)
                        if e is not None and e.current_hp > 0:
                            e.current_hp = 0.0
                director.after_step()

        expected_turns = [
            (31.57, "正阳狮鹫"),
            (69.44, "流星铁鹰_g1_1"),
            (75.76, "月夜天马"),
            (92.17, "流星铁鹰_g1_2"),
            (94.70, "正阳狮鹫"),
            (114.90, "流星铁鹰_g1_3"),
            (114.90, "流星铁鹰_g1_3"),
            (151.52, "月夜天马"),
            (157.83, "正阳狮鹫"),
            (220.96, "正阳狮鹫"),
            (227.27, "月夜天马"),
        ]
        for exp in expected_turns:
            self.assertIn(exp, enemy_turns, f"Missing expected enemy turn {exp} in {enemy_turns}")
        self.assertEqual(griffin.kit.generation, 2)


if __name__ == "__main__":
    unittest.main()

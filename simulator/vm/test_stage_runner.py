"""Unit tests for ``simulator.vm.stage_prunable_types`` and ``simulator.vm.stage_runner``.

Verifies pure data-driven stage execution on official configs for:
- Stage 30126122 (MoC: Wave 1 Pegasus + Griffin -> SummonMonster Eagle -> Wave 2 Apoli
  LockHP / SetMonsterPhase Phase 1->2 / SummonMonster Sprout / ExitBreakState / ResetStance /
  BattleEvent 30149)
- Stage 30510021 (Pure Fiction / Challenge Peak: InfiniteEliteGroup 368->374 wave
  transition, infinite slot refill, BattleEvent 30503 CountDown & SummonMonsterInfinite)
"""

from __future__ import annotations

import math
import unittest

from simulator.stage_30126122 import (
    APOLI_PHASE1_HP,
    APOLI_PHASE2_HP,
    EAGLE_HP,
    GRIFFIN_HP,
    PEGASUS_HP,
    SPROUT_HP,
)
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_prunable_types import (
    ALL_SAFE_PRUNABLE_TYPES,
    STAGE_MECHANICAL_PREDICATE_TYPES,
    STAGE_MECHANICAL_TASK_TYPES,
    STAGE_PRUNABLE_PRESENTATION_TYPES,
    classify_node_type,
    is_safe_prunable_type,
    prune_stage_task_list,
)
from simulator.vm.stage_runner import StageRunner


class TestStagePrunableTypes(unittest.TestCase):
    def test_classification_and_disjointness(self) -> None:
        # Prunable presentation/meta nodes must never overlap with mechanical nodes
        self.assertEqual(ALL_SAFE_PRUNABLE_TYPES & STAGE_MECHANICAL_TASK_TYPES, set())
        self.assertEqual(ALL_SAFE_PRUNABLE_TYPES & STAGE_MECHANICAL_PREDICATE_TYPES, set())

        self.assertEqual(classify_node_type("RPG.GameCore.AnimSetParameter"), "prunable_presentation")
        self.assertEqual(classify_node_type("RPG.GameCore.ShowBossInfoBar"), "prunable_presentation")
        self.assertEqual(classify_node_type("RPG.GameCore.SetBattleAchievement"), "prunable_meta_scoring")
        self.assertEqual(classify_node_type("RPG.GameCore.SetBattleScoringItem"), "prunable_meta_scoring")
        self.assertEqual(classify_node_type("RPG.GameCore.SummonMonster"), "mechanical_task")
        self.assertEqual(classify_node_type("RPG.GameCore.ByCompareMonsterPhase"), "mechanical_predicate")
        self.assertTrue(is_safe_prunable_type("RPG.GameCore.SkillExecutionStart"))
        self.assertFalse(is_safe_prunable_type("RPG.GameCore.LockHP"))

    def test_prune_stage_task_list_keeps_mechanical_nodes(self) -> None:
        raw = [
            {"$type": "RPG.GameCore.ShowBossInfoBar", "IsShow": True},
            {"$type": "RPG.GameCore.SetBattleAchievement", "AchievementID": 1},
            {
                "$type": "RPG.GameCore.PredicateTaskList",
                "Predicate": {"$type": "RPG.GameCore.ByCompareMonsterPhase"},
                "SuccessTaskList": [
                    {"$type": "RPG.GameCore.AnimSetParameter"},
                    {"$type": "RPG.GameCore.SetMonsterPhase", "SetMode": "Inc"},
                ],
            },
        ]
        pruned = prune_stage_task_list(raw)
        self.assertEqual(len(pruned), 1)
        self.assertEqual(pruned[0]["$type"], "RPG.GameCore.PredicateTaskList")
        self.assertEqual(
            [t["$type"] for t in pruned[0]["SuccessTaskList"]],
            ["RPG.GameCore.SetMonsterPhase"],
        )


class TestStageRunner(unittest.TestCase):
    game_loader: GameDataLoader

    @classmethod
    def setUpClass(cls) -> None:
        cls.game_loader = GameDataLoader()
        cls.game_loader.ensure_ability_index()

    def test_stage_30126122_full_data_driven_lifecycle(self) -> None:
        runner = StageRunner(30126122)
        w1 = runner.start_stage()
        self.assertEqual([e.name for e in w1], ["月夜天马", "正阳狮鹫"])
        self.assertTrue(math.isclose(w1[0].max_hp, PEGASUS_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(w1[1].max_hp, GRIFFIN_HP, rel_tol=1e-7))
        self.assertIn(30149, runner.state.battle_events)

        # Stage predicates evaluated purely from CompiledStageSpec
        self.assertTrue(
            runner.eval_stage_predicate(
                {
                    "$type": "RPG.GameCore.ByCompareStageID",
                    "CompareType": "Equal",
                    "StageID": {"IsDynamic": False, "FixedValue": {"Value": 30126122}},
                }
            )
        )
        self.assertTrue(
            runner.eval_stage_predicate(
                {"$type": "RPG.GameCore.ByCompareStageType", "CurrentStageType": "Challenge"}
            )
        )
        self.assertTrue(
            runner.eval_stage_predicate(
                {
                    "$type": "RPG.GameCore.ByCompareBattleEventID",
                    "TargetBattleEventID": {"IsDynamic": False, "FixedValue": {"Value": 30149}},
                }
            )
        )

        # Griffin summons MeteorEagle via official SummonMonster task format
        from simulator.vm.expr import dotnet_hash

        summon_task = {
            "$type": "RPG.GameCore.SummonMonster",
            "SummonMonsterDataList": [
                {
                    "MonsterID": {
                        "IsDynamic": True,
                        "PostfixExpr": {
                            "OpCodes": "AQAR",
                            "FixedValues": [],
                            "DynamicHashes": [dotnet_hash("SummonID01")],
                        },
                    },
                    "LocationType": "KeepOnEdge",
                }
            ],
            "DelayRatio": {"IsDynamic": False, "FixedValue": {"Value": 0.5}},
        }
        spawned_eagles = runner.execute_summon_monster("正阳狮鹫", summon_task)
        self.assertEqual(len(spawned_eagles), 1)
        self.assertTrue(math.isclose(spawned_eagles[0].max_hp, EAGLE_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(spawned_eagles[0].distance_remaining, 5000.0, rel_tol=1e-9))

        # Defeat Wave 1 -> Advance to Wave 2 (ApoliBoss)
        for ent in runner.living_enemies():
            ent.current_hp = 0.0
        w2 = runner.advance_wave_if_cleared()
        self.assertIsNotNone(w2)
        assert w2 is not None
        self.assertEqual([e.name for e in w2], ["堕神之血•亚婆离"])
        apoli = w2[0]
        self.assertTrue(math.isclose(apoli.max_hp, APOLI_PHASE1_HP, rel_tol=1e-7))

        # Verify Apoli Phase 1 -> LockHP -> SetMonsterPhase -> Phase 2
        self.assertTrue(
            runner.eval_stage_predicate(
                {
                    "$type": "RPG.GameCore.ByCompareMonsterPhase",
                    "CompareType": "Equal",
                    "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 1}},
                },
                caster_name="堕神之血•亚婆离",
            )
        )
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.LockHP", "Threshold": {"IsDynamic": False, "FixedValue": {"Value": 0.3}}},
            caster_name="堕神之血•亚婆离",
        )
        apoli.current_hp = 1.0
        clamped = runner.enforce_lock_hp("堕神之血•亚婆离")
        self.assertTrue(math.isclose(clamped, APOLI_PHASE1_HP * 0.3, rel_tol=1e-7))

        # Break & reset stance via ExitBreakState / ResetStance
        apoli.current_toughness = 0.0
        apoli.is_broken = True
        runner.execute_stage_task({"$type": "RPG.GameCore.ExitBreakState"}, caster_name="堕神之血•亚婆离")
        self.assertFalse(apoli.is_broken)
        runner.execute_stage_task({"$type": "RPG.GameCore.ResetStance"}, caster_name="堕神之血•亚婆离")
        self.assertTrue(math.isclose(apoli.current_toughness, apoli.max_toughness, rel_tol=1e-9))

        # Phase transition via official SetMonsterPhase task
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.SetMonsterPhase", "SetMode": "Inc"},
            caster_name="堕神之血•亚婆离",
        )
        self.assertEqual(runner.get_enemy_state("堕神之血•亚婆离").phase, 2)
        self.assertTrue(math.isclose(apoli.max_hp, APOLI_PHASE2_HP, rel_tol=1e-7))
        self.assertTrue(math.isclose(apoli.current_hp, APOLI_PHASE2_HP, rel_tol=1e-7))

        # Apoli summons BeastSprout using real Monster_W5_Fallen_00_Ability SummonMonster task
        fallen_ab = self.game_loader.get_ability("BattleEventAbility_Monster_W5_Fallen_00_SummonMonster")
        self.assertIsNotNone(fallen_ab)
        # Extract the first SummonMonster task from Phase 2 branch
        summon_tasks: list[dict] = []

        def _find_summons(obj):
            if isinstance(obj, list):
                for x in obj:
                    _find_summons(x)
            elif isinstance(obj, dict):
                if obj.get("$type") == "RPG.GameCore.SummonMonster":
                    summon_tasks.append(obj)
                for v in obj.values():
                    _find_summons(v)

        _find_summons(fallen_ab)
        self.assertGreater(len(summon_tasks), 0)
        sprouts = runner.execute_summon_monster("堕神之血•亚婆离", summon_tasks[0])
        self.assertEqual(len(sprouts), 1)
        self.assertTrue(math.isclose(sprouts[0].max_hp, SPROUT_HP, rel_tol=1e-7))

    def test_stage_30510021_infinite_waves_and_battle_event(self) -> None:
        runner = StageRunner(30510021)
        w1 = runner.start_stage()
        self.assertEqual(len(w1), 2)
        self.assertIn(30503, runner.state.battle_events)

        # Wave 0 has 1 wave left -> ByInfiniteMonsterWaveLeft > 0 is True
        self.assertTrue(
            runner.eval_stage_predicate(
                {
                    "$type": "RPG.GameCore.ByInfiniteMonsterWaveLeft",
                    "CompareType": "Greater",
                    "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 0}},
                }
            )
        )

        # Execute official BattleEventAbility_SummonMonsterInfinite OnStack tasks
        be_inf = self.game_loader.get_ability("BattleEventAbility_SummonMonsterInfinite")
        self.assertIsNotNone(be_inf)
        assert be_inf is not None
        on_stack = be_inf["Modifiers"]["BattleEventAbility_SummonMonsterInfinite_Modifier"]["_CallbackList"][0]["CallbackConfig"]
        for task in on_stack:
            if task.get("$type") in ("RPG.GameCore.OwnerEntityAddAbility",) or is_safe_prunable_type(task.get("$type", "")):
                handled = runner.execute_stage_task(task)
                self.assertTrue(handled)
        self.assertIn("BattleEventAbility_SummonMonsterInfinite_Insert", runner.state.stage_abilities)

        # Infinite slot refill in Wave 0 (MaxMonsterCount=2 -> kill 1, refill 1)
        w1[0].current_hp = 0.0
        refilled = runner.refill_infinite_wave_slot()
        self.assertEqual(len(refilled), 1)
        self.assertEqual(len(runner.living_enemies()), 2)

        # Clear Wave 0 -> advance to Wave 1 (InfiniteEliteGroup 374, Apoli Lv.100)
        for ent in runner.living_enemies():
            ent.current_hp = 0.0
        w2 = runner.advance_wave_if_cleared()
        self.assertIsNotNone(w2)
        assert w2 is not None
        self.assertEqual(len(w2), 1)
        self.assertTrue(math.isclose(w2[0].max_hp, 6389558.5, rel_tol=1e-5))
        self.assertFalse(
            runner.eval_stage_predicate(
                {
                    "$type": "RPG.GameCore.ByInfiniteMonsterWaveLeft",
                    "CompareType": "Greater",
                    "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 0}},
                }
            )
        )

    def test_custom_event_bus_boundaries_weakness_and_predicates(self) -> None:
        # 1. TriggerCustomString event bus & Level_SpecialWin / Level_ManualLose
        runner = StageRunner(30126122)
        w1 = runner.start_stage()
        received: list[str] = []
        runner.subscribe_custom_event("PhaseTrigger", lambda name, _st: received.append(name))
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.TriggerCustomString", "CustomString": "PhaseTrigger"}
        )
        self.assertEqual(received, ["PhaseTrigger"])
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.TriggerCustomString", "CustomString": "Level_SpecialWin"}
        )
        self.assertEqual(runner.state.special_outcome, "win")

        # 2. Unique name registration & TargetFetchUniqueNameEntity + AddStageAbilityByName
        pegasus = w1[0]
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.SetTargetUniqueName", "UniqueName": "BossMain"},
            caster_name=pegasus.name,
        )
        self.assertTrue(
            runner.execute_stage_task(
                {"$type": "RPG.GameCore.TargetFetchUniqueNameEntity", "UniqueName": "BossMain"}
            )
        )
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.AddStageAbilityByName", "AbilityName": "TestFetchedAbility"}
        )
        self.assertIn("TestFetchedAbility", runner.state.stage_abilities)
        self.assertEqual([e.name for e in runner.resolve_unique_name_entities("BossMain")], [pegasus.name])

        # 3. StackWeakness (Add / Remove Thunder -> Lightning)
        self.assertNotIn("Lightning", pegasus.weaknesses)
        base_lightning_res = pegasus.damage_res.get("Lightning", 0.2)
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.StackWeakness", "OPType": "Add", "WeakList": ["Thunder"]},
            caster_name=pegasus.name,
        )
        self.assertIn("Lightning", pegasus.weaknesses)
        self.assertTrue(math.isclose(pegasus.damage_res["Lightning"], 0.0, abs_tol=1e-9))
        runner.execute_stage_task(
            {"$type": "RPG.GameCore.StackWeakness", "OPType": "Remove", "WeakList": ["Thunder"]},
            caster_name=pegasus.name,
        )
        self.assertNotIn("Lightning", pegasus.weaknesses)
        self.assertTrue(math.isclose(pegasus.damage_res["Lightning"], base_lightning_res, abs_tol=1e-9))

        # 4. High-frequency predicates: ByIsTurnActionEntity, ByIsTargetAbleToAction,
        # ByIsDamageType, ByCompareHP, ByCurrentSkillName
        runner.on_turn_begin(pegasus.name, current_av=100.0)
        self.assertTrue(
            runner.eval_stage_predicate(
                {"$type": "RPG.GameCore.ByIsTurnActionEntity"},
                caster_name=pegasus.name,
            )
        )
        self.assertTrue(
            runner.eval_stage_predicate(
                {"$type": "RPG.GameCore.ByIsTargetAbleToAction"},
                caster_name=pegasus.name,
            )
        )
        pegasus.is_broken = True
        self.assertFalse(
            runner.eval_stage_predicate(
                {"$type": "RPG.GameCore.ByIsTargetAbleToAction"},
                caster_name=pegasus.name,
            )
        )
        self.assertTrue(
            runner.eval_stage_predicate(
                {"$type": "RPG.GameCore.ByIsTargetAbleToAction", "Inverse": True},
                caster_name=pegasus.name,
            )
        )
        self.assertTrue(
            runner.eval_stage_predicate(
                {"$type": "RPG.GameCore.ByIsDamageType", "DamageTypeList": ["Fire", "Ice"]},
                damage_type="Fire",
            )
        )
        self.assertTrue(
            runner.eval_stage_predicate(
                {"$type": "RPG.GameCore.ByCurrentSkillName", "SkillName": "Skill03"},
                skill_name="Skill03",
            )
        )
        pegasus.current_hp = 50000.0
        self.assertTrue(
            runner.eval_stage_predicate(
                {
                    "$type": "RPG.GameCore.ByCompareHP",
                    "CompareType": "LessEqual",
                    "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 60000.0}},
                },
                caster_name=pegasus.name,
            )
        )

        # 5. Pure Fiction cycle boundary & wave AV preservation (30510021)
        pf_runner = StageRunner(30510021)
        pf_runner.start_stage()
        cycles_seen: list[int] = []
        pf_runner.subscribe_cycle_boundary(lambda c, _av, _st: cycles_seen.append(c))
        pf_runner.on_cycle_boundary(1, current_av=150.0)
        self.assertEqual(cycles_seen, [1])
        self.assertEqual(pf_runner.state.current_cycle, 1)


if __name__ == "__main__":
    unittest.main()

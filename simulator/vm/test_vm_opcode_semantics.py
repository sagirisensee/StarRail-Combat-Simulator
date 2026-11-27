# coding: utf-8
"""VM 引擎通用原语与语义单测（合成 ConfigAbility JSON，零角色耦合，不随新增角色膨胀）。"""

import base64
import unittest

from simulator.core import TurnSimulator
from simulator.entity import Entity
from simulator.events import HealAppliedEvent
from simulator.vm.executor import (
    ExecutionContext,
    IGNORED_MECHANICAL_TASK_STUBS,
    IGNORED_OBFUSCATED_TASK_STUBS,
    TaskExecutor,
)
from simulator.vm.expr import dotnet_hash
from simulator.vm.loader import CompiledCharacterSpec, prune_task_list
from simulator.vm.runtime import ConfigAbilityKitAdapter, VMRuntime
from simulator.vm.stage_prunable_types import ALL_SAFE_PRUNABLE_TYPES


def _make_sim_with_vm() -> tuple[TurnSimulator, VMRuntime, Entity, Entity]:
    ally = Entity(
        name="测试角色",
        base_speed=100.0,
        base_atk=1200.0,
        max_hp=5000.0,
        current_hp=3000.0,
        max_energy=100.0,
        energy=20.0,
        base_crit_rate=0.50,
        base_crit_dmg=1.50,
    )
    enemy = Entity(
        name="测试木桩",
        base_speed=90.0,
        base_atk=800.0,
        max_hp=100_000.0,
        current_hp=100_000.0,
        is_enemy=True,
        weaknesses=["Ice", "Quantum"],
    )
    sim = TurnSimulator(entities=[ally, enemy], use_techniques=False, auto_ult=False)
    rt = VMRuntime(sim)
    sim.vm_runtime = rt
    return sim, rt, ally, enemy


class TestVMOpcodeSemantics(unittest.TestCase):
    def test_add_remove_modifier_and_dynamic_value_predicate(self) -> None:
        """验证 AddModifier / RemoveModifier / DynamicValue 读写与 ByCompareDynamicValue 谓词分支。"""
        _, rt, _, _ = _make_sim_with_vm()
        rt.loader._global_mod_by_name["MSynth_TestBuff"] = {
            "BehaviorFlagList": ["TestFlagA"],
            "MaxLayer": 3,
            "Stacking": "Multiple",
        }
        try:
            ctx = ExecutionContext(
                runtime=rt,
                caster_id="测试角色",
                ability_name="TestSynth",
                ability_target_ids=("测试木桩",),
            )

            # 添加 2 层并设置 DynamicValue = 5
            rt.execute_tasks(
                [
                    {
                        "$type": "RPG.GameCore.AddModifier",
                        "TargetType": {"Alias": "Caster"},
                        "ModifierName": "MSynth_TestBuff",
                        "Count": {"IsDynamic": False, "FixedValue": {"Value": 2}},
                    },
                    {
                        "$type": "RPG.GameCore.DefineDynamicValue",
                        "TargetType": {"Alias": "Caster"},
                        "DynamicKey": "SynthStack",
                        "ResetValue": {"IsDynamic": False, "FixedValue": {"Value": 5}},
                    },
                ],
                ctx,
            )
            self.assertTrue(rt.modifier_engine.has_modifier("测试角色", "MSynth_TestBuff"))
            self.assertTrue(rt.modifier_engine.has_behavior_flag("测试角色", "TestFlagA"))
            self.assertAlmostEqual(
                rt.get_dynamic_value("测试角色", dotnet_hash("SynthStack"), ability_name="TestSynth", local_ctx=ctx),
                5.0,
            )

            # PredicateTaskList: SynthStack >= 5 -> 移除 Modifier
            rt.execute_tasks(
                [
                    {
                        "$type": "RPG.GameCore.PredicateTaskList",
                        "Predicate": {
                            "$type": "RPG.GameCore.ByCompareDynamicValue",
                            "TargetType": {"Alias": "Caster"},
                            "DynamicKey": "SynthStack",
                            "CompareType": "GreaterEqual",
                            "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 5}},
                        },
                        "SuccessTaskList": [
                            {
                                "$type": "RPG.GameCore.RemoveModifier",
                                "TargetType": {"Alias": "Caster"},
                                "ModifierName": "MSynth_TestBuff",
                            }
                        ],
                    }
                ],
                ctx,
            )
            self.assertFalse(rt.modifier_engine.has_modifier("测试角色", "MSynth_TestBuff"))
        finally:
            rt.loader._global_mod_by_name.pop("MSynth_TestBuff", None)

    def test_set_control_skill_mapping_remaps_and_clears(self) -> None:
        """验证 RPG.GameCore.SetControlSkillMapping 原生改写与清空控制技能映射。"""
        _, rt, _, _ = _make_sim_with_vm()
        ctx = ExecutionContext(
            runtime=rt,
            caster_id="测试角色",
            ability_name="TestSynth",
            ability_target_ids=("测试角色",),
        )

        rt.execute_tasks(
            [
                {
                    "$type": "RPG.GameCore.SetControlSkillMapping",
                    "TargetType": {"Alias": "Caster"},
                    "ControlSkillType": "ControlSkill01",
                    "SkillTriggerKey": "Skill03",
                }
            ],
            ctx,
        )
        self.assertEqual(rt.control_skill_mapping.get(("测试角色", "ControlSkill01")), "Skill03")

        rt.execute_tasks(
            [
                {
                    "$type": "RPG.GameCore.SetControlSkillMapping",
                    "TargetType": {"Alias": "Caster"},
                    "ControlSkillType": "ControlSkill01",
                    "SkillTriggerKey": "",
                }
            ],
            ctx,
        )
        self.assertNotIn(("测试角色", "ControlSkill01"), rt.control_skill_mapping)

    def test_modify_sp_heal_and_action_delay_opcodes(self) -> None:
        """验证 ModifySPNew（回能）、HealHP（治疗）与 ModifyActionDelay（拉条/推条）通用原语。"""
        sim, rt, ally, _ = _make_sim_with_vm()
        heals = []
        sim.event_bus.subscribe(HealAppliedEvent, lambda e: heals.append(e))
        ctx = ExecutionContext(
            runtime=rt,
            caster_id="测试角色",
            ability_name="TestSynth",
            ability_target_ids=("测试角色",),
        )

        energy_before = ally.energy
        hp_before = ally.current_hp
        av_before = ally.remaining_av

        rt.execute_tasks(
            [
                {
                    "$type": "RPG.GameCore.ModifySPNew",
                    "TargetType": {"Alias": "Caster"},
                    "AddRatio": {"IsDynamic": False, "FixedValue": {"Value": 0}},
                    "AddValue": {"IsDynamic": False, "FixedValue": {"Value": 25}},
                },
                {
                    "$type": "RPG.GameCore.HealHP",
                    "TargetType": {"Alias": "Caster"},
                    "HealPercentage": {"IsDynamic": False, "FixedValue": {"Value": 0.10}},
                    "ModifyValue": {"IsDynamic": False, "FixedValue": {"Value": 200}},
                },
                {
                    "$type": "RPG.GameCore.ModifyActionDelay",
                    "TargetType": {"Alias": "Caster"},
                    "AddNormalizedValue": {"IsDynamic": False, "FixedValue": {"Value": -0.25}},
                },
            ],
            ctx,
        )

        self.assertGreater(ally.energy, energy_before)
        self.assertGreater(ally.current_hp, hp_before)
        self.assertGreater(len(heals), 0)
        self.assertLess(ally.remaining_av, av_before)

    def test_task_dispatch_table_integrity_and_disjointness(self) -> None:
        """校验 TaskExecutor._TASK_DISPATCH 覆盖与忽略注册表互斥，且未知节点保持 strict 报错。"""
        dispatch = TaskExecutor._TASK_DISPATCH
        self.assertGreaterEqual(len(dispatch), 100)
        self.assertTrue(all(callable(fn) for fn in dispatch.values()))

        dispatch_keys = set(dispatch.keys())
        self.assertEqual(dispatch_keys & ALL_SAFE_PRUNABLE_TYPES, set())
        self.assertEqual(dispatch_keys & IGNORED_MECHANICAL_TASK_STUBS, set())
        self.assertEqual(dispatch_keys & IGNORED_OBFUSCATED_TASK_STUBS, set())
        self.assertEqual(IGNORED_MECHANICAL_TASK_STUBS & IGNORED_OBFUSCATED_TASK_STUBS, set())

        _, rt, _, _ = _make_sim_with_vm()
        ctx = ExecutionContext(runtime=rt, caster_id="测试角色", ability_name="TestSynth")
        with self.assertRaises(NotImplementedError):
            rt.execute_tasks([{"$type": "RPG.GameCore.NonExistentTestTask"}], ctx)

    def test_use_technique_triggers_only_entry_ability(self) -> None:
        """验证 ConfigAbilityKitAdapter.use_technique 仅触发 SkillMaze 的 EntryAbility，不抢跑派生 Insert。"""
        sim, rt, _, _ = _make_sim_with_vm()
        rt.loader.ensure_ability_index()
        spec = CompiledCharacterSpec(
            unit_id=999999,
            is_servant=False,
            config={
                "SkillList": [
                    {
                        "Name": "SkillMaze",
                        "SkillType": "Maze",
                        "EntryAbility": "Synth_Maze_Entry",
                    }
                ],
                "SkillAbilityList": [
                    {
                        "Skill": "SkillMaze",
                        "AbilityList": ["Synth_Maze_Entry", "Synth_Maze_Insert"],
                    }
                ],
            },
            abilities={},
            global_modifiers={},
            global_templates={},
            dynamic_floats={},
            skill_levels={},
        )

        class _SynthCharLoader:
            def load_character(self, *_args, **_kwargs) -> CompiledCharacterSpec:
                return spec

        rt.loader._ability_by_name["Synth_Maze_Entry"] = {
            "Name": "Synth_Maze_Entry",
            "OnStart": [
                {
                    "$type": "RPG.GameCore.SetDynamicValue",
                    "DynamicKey": "SynthEntryRan",
                    "Value": {"IsDynamic": False, "FixedValue": {"Value": 1}},
                }
            ],
        }
        rt.loader._ability_by_name["Synth_Maze_Insert"] = {
            "Name": "Synth_Maze_Insert",
            "OnStart": [
                {
                    "$type": "RPG.GameCore.SetDynamicValue",
                    "DynamicKey": "SynthInsertRan",
                    "Value": {"IsDynamic": False, "FixedValue": {"Value": 1}},
                }
            ],
        }
        try:
            adapter = ConfigAbilityKitAdapter(
                owner_id="测试角色",
                avatar_or_servant_id=999999,
                port=sim.port,
                runtime=rt,
                loader=_SynthCharLoader(),  # type: ignore[arg-type]
            )
            adapter.use_technique()
            self.assertAlmostEqual(rt.get_dynamic_value("测试角色", dotnet_hash("SynthEntryRan")), 1.0)
            self.assertAlmostEqual(rt.get_dynamic_value("测试角色", dotnet_hash("SynthInsertRan")), 0.0)
        finally:
            rt.loader._ability_by_name.pop("Synth_Maze_Entry", None)
            rt.loader._ability_by_name.pop("Synth_Maze_Insert", None)

    def test_add_modifier_success_and_fail_task_lists_with_chance(self) -> None:
        """验证 AddModifier 支持 SuccessTaskList / FailTaskList 与含效果命中抵抗的 Chance 循环终止。"""
        ally = Entity(
            name="测试角色",
            base_speed=100.0,
            base_atk=1200.0,
            max_hp=5000.0,
            current_hp=5000.0,
            base_effect_hit_rate=1.2,
        )
        enemy = Entity(
            name="测试木桩",
            base_speed=90.0,
            base_atk=800.0,
            max_hp=100_000.0,
            current_hp=100_000.0,
            is_enemy=True,
            base_effect_res=0.4,
        )
        sim = TurnSimulator(entities=[ally, enemy], use_techniques=False, auto_ult=False)
        rt = VMRuntime(sim)
        sim.vm_runtime = rt
        rt.loader._global_mod_by_name["MSynth_LoopDot"] = {
            "MaxLayer": 10,
            "LayerAddWhenStack": 1,
            "Stacking": "ReplaceByCaster",
        }
        rt.loader._global_mod_by_name["MSynth_StopFlag"] = {}

        def _b64(ops: list[int]) -> str:
            return base64.b64encode(bytes(ops)).decode("ascii")

        chance_hash = dotnet_hash("_current_chance")
        loop_cnt_hash = dotnet_hash("_loop_count")
        raw_tasks = [
            {
                "$type": "RPG.GameCore.SetDynamicValue",
                "DynamicKey": "_can_continue",
                "Value": {"IsDynamic": False, "FixedValue": {"Value": 1}},
            },
            {
                "$type": "RPG.GameCore.SetDynamicValue",
                "DynamicKey": "_loop_count",
                "Value": {"IsDynamic": False, "FixedValue": {"Value": 0}},
            },
            {
                "$type": "RPG.GameCore.SetDynamicValue",
                "DynamicKey": "_current_chance",
                "Value": {"IsDynamic": False, "FixedValue": {"Value": 1.5}},
            },
            {
                "$type": "RPG.GameCore.ConditionLoopExecuteTaskListWithInterval",
                "Predicate": {
                    "$type": "RPG.GameCore.ByCompareDynamicValue",
                    "DynamicKey": "_can_continue",
                    "CompareType": "GreaterEqual",
                    "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 1}},
                },
                "TaskList": [
                    {
                        "$type": "RPG.GameCore.SetDynamicValue",
                        "DynamicKey": "_loop_count",
                        "Value": {
                            "IsDynamic": True,
                            "PostfixExpr": {
                                "OpCodes": _b64([1, 0, 0, 0, 2, 17]),
                                "FixedValues": [{"Value": 1}],
                                "DynamicHashes": [loop_cnt_hash],
                            },
                        },
                    },
                    {
                        "$type": "RPG.GameCore.SetDynamicValue",
                        "DynamicKey": "_can_continue",
                        "Value": {"IsDynamic": False, "FixedValue": {"Value": 0}},
                    },
                    {
                        "$type": "RPG.GameCore.AddModifier",
                        "TargetType": {"Alias": "AbilityTargetEntity"},
                        "ModifierName": "MSynth_LoopDot",
                        "MaxLayer": {"IsDynamic": False, "FixedValue": {"Value": 10}},
                        "LayerAddWhenStack": {"IsDynamic": False, "FixedValue": {"Value": 1}},
                        "Chance": {
                            "IsDynamic": True,
                            "PostfixExpr": {
                                "OpCodes": _b64([1, 0, 17]),
                                "FixedValues": [],
                                "DynamicHashes": [chance_hash],
                            },
                        },
                        "SuccessTaskList": [
                            {
                                "$type": "RPG.GameCore.SetDynamicValue",
                                "DynamicKey": "_can_continue",
                                "Value": {"IsDynamic": False, "FixedValue": {"Value": 1}},
                            }
                        ],
                        "FailTaskList": [
                            {
                                "$type": "RPG.GameCore.TriggerAnimState",
                                "TargetType": {"Alias": "ParamEntity"},
                                "AnimStateName": "Hit",
                            },
                            {
                                "$type": "RPG.GameCore.AddModifier",
                                "TargetType": {"Alias": "ParamEntity"},
                                "ModifierName": "MSynth_StopFlag",
                            },
                        ],
                    },
                    {
                        "$type": "RPG.GameCore.SetDynamicValue",
                        "DynamicKey": "_current_chance",
                        "Value": {
                            "IsDynamic": True,
                            "PostfixExpr": {
                                "OpCodes": _b64([1, 0, 0, 0, 4, 17]),
                                "FixedValues": [{"Value": 0.5}],
                                "DynamicHashes": [chance_hash],
                            },
                        },
                    },
                ],
            },
        ]
        pruned_tasks = prune_task_list(raw_tasks)
        loop_add_mod = pruned_tasks[3]["TaskList"][2]
        self.assertEqual([t["$type"] for t in loop_add_mod["FailTaskList"]], ["RPG.GameCore.AddModifier"])

        try:
            ctx = ExecutionContext(
                runtime=rt,
                caster_id="测试角色",
                ability_name="TestSynth",
                ability_target_ids=("测试木桩",),
            )
            rt.execute_tasks(pruned_tasks, ctx)

            dot_mods = rt.modifier_engine.get_modifiers("测试木桩", "MSynth_LoopDot")
            self.assertEqual(len(dot_mods), 1)
            self.assertEqual(dot_mods[0].layer, 2)
            self.assertTrue(rt.modifier_engine.has_modifier("测试木桩", "MSynth_StopFlag"))
            self.assertAlmostEqual(rt.get_dynamic_value("测试角色", loop_cnt_hash), 3.0)
        finally:
            rt.loader._global_mod_by_name.pop("MSynth_LoopDot", None)
            rt.loader._global_mod_by_name.pop("MSynth_StopFlag", None)


if __name__ == "__main__":
    unittest.main()

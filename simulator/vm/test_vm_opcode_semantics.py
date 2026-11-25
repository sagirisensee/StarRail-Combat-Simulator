# coding: utf-8
"""VM 引擎通用原语与语义单测（合成 ConfigAbility JSON，零角色耦合，不随新增角色膨胀）。"""

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
from simulator.vm.runtime import VMRuntime
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


if __name__ == "__main__":
    unittest.main()

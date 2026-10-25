# coding: utf-8
import unittest
from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.actions import ActionKind
from simulator.tracer import ActionCausalTracer

class TestActionCausalTracer(unittest.TestCase):
    def test_tracer_records_variable_and_plugin_causality(self):
        db = CharacterDB().load('data/character_db_export.json')
        team = [
            db.to_combat_entity('长夜月'),
            db.to_combat_entity('缇宝'),
            db.to_combat_entity('知更鸟•晴歌'),
            db.to_combat_entity('风堇')
        ]
        enemies = [
            Entity(name='月夜天马 (Lv.100)', base_speed=132.0, max_hp=1000000.0, current_hp=1000000.0, weaknesses=['Fire'], is_enemy=True),
        ]
        sim = TurnSimulator(entities=team + enemies, stage_mechanics=['血噬'])
        self.assertIsNotNone(sim.tracer)
        self.assertIsInstance(sim.tracer, ActionCausalTracer)

        cy = sim.get_entity('长夜月')
        init_yizhi = cy.kit.yizhi

        # 模拟扣血派发
        sim.tracer.start_action("长夜月", "测试扣血流转", av=10.0, cycle=0)
        sim.port.lose_hp("长夜月", 100.0, cause="LC_MayRainbows_HP_Drain")

        # 验证长夜月天赋响应并写入 tracer
        self.assertEqual(cy.kit.yizhi, init_yizhi + 4)
        self.assertEqual(len(sim.tracer.current_trace.deltas), 1)
        delta = sim.tracer.current_trace.deltas[0]
        self.assertEqual(delta.entity, "长夜月")
        self.assertEqual(delta.var_name, "忆质")
        self.assertEqual(delta.delta, 4)
        self.assertIn("《愿虹光永驻天空》", delta.cause_desc)

        # 验证插件记录
        plugin_names = [p.plugin_name for p in sim.tracer.current_trace.plugins]
        self.assertIn("《愿虹光永驻天空》 (风堇 S1)", plugin_names)
        self.assertIn("《今夜与我同行》 (长夜月 E2)", plugin_names)

        sim.tracer.end_action()
        self.assertEqual(len(sim.tracer.history), 1)

    def test_tracer_records_energy_flow(self):
        db = CharacterDB().load('data/character_db_export.json')
        team = [db.to_combat_entity('长夜月'), db.to_combat_entity('风堇')]
        sim = TurnSimulator(entities=team)

        sim.tracer.start_action("风堇", "战技与受击", av=48.0, cycle=0)
        sim.port.gain_energy("风堇", 30.0, cause="战技回能", source_plugin="风堇战技")
        sim.port.gain_hit_energy("长夜月", 5.0)

        self.assertEqual(len(sim.tracer.current_trace.energy_deltas), 2)
        ed1 = sim.tracer.current_trace.energy_deltas[0]
        self.assertEqual(ed1.entity, "风堇")
        self.assertEqual(ed1.delta, 30.0)
        self.assertEqual(ed1.source_plugin, "风堇战技")

        ed2 = sim.tracer.current_trace.energy_deltas[1]
        self.assertEqual(ed2.entity, "长夜月")
        self.assertEqual(ed2.delta, 5.0)
        self.assertEqual(ed2.source_plugin, "受击机制")

        sim.tracer.end_action()
        self.assertEqual(len(sim.tracer.history), 1)

    def test_tracer_generic_variable_and_cause_registration(self):
        """验证追踪器通用性: 新变量只需插件自申报即可渲染, 扣血来源描述由来源插件自注册。"""
        import io
        from contextlib import redirect_stdout
        from simulator.tracer import TraceVariableSpec

        # 1. 扣血来源描述由来源插件自注册 (来源模块加载后即可查到, 追踪器源码不写死)
        import simulator.light_cones.catalog  # noqa: F401  (触发光锥插件自注册)
        import simulator.stage_mechanics  # noqa: F401  (触发关卡插件自注册)
        self.assertIsNotNone(ActionCausalTracer.describe_cause("LC_MayRainbows_HP_Drain"))
        self.assertIsNotNone(ActionCausalTracer.describe_cause("stage_mechanic_bleed_turn_begin"))
        self.assertIsNone(ActionCausalTracer.describe_cause("nonexistent_cause"))

        # 2. 任意插件自申报一个全新变量 (如【怒气值】), 追踪器零改动即可渲染其流转与维持值
        class _FakeKit:
            def trace_variables(self):
                return [TraceVariableSpec(var_name="怒气值", unit="点", current_value=lambda: 42.0)]

        class _FakeEnt:
            name = "假想新角色"
            kit = _FakeKit()

        class _FakeSim:
            entities = [_FakeEnt()]

        tracer = ActionCausalTracer(_FakeSim())
        tracer.start_action("假想新角色", "测试行动", av=1.0, cycle=0)
        buf = io.StringIO()
        with redirect_stdout(buf):
            tracer.render_audit_panel()
        out = buf.getvalue()
        self.assertIn("假想新角色 · 怒气值变化流转", out)
        self.assertIn("维持 42 点", out)


if __name__ == '__main__':
    unittest.main()

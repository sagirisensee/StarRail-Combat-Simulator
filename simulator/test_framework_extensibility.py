"""战斗模拟器微内核架构与协议拓展性验证测试套件 (Framework & Extensibility Verification)。"""
import unittest
from simulator import (
    TurnSimulator, Entity, BuffSpec,
    ActionKind, ActionContext, AbilityDefinition, TargetMode, ResourceCost,
    KitHandler, LightConeHandler, RelicSetHandler,
    StageMechanicPlugin, register_stage_mechanic,
    StatType, Modifier, ModifierOp, DurationTiming,
    HPLostEvent,
)


class TestFrameworkExtensibility(unittest.TestCase):
    def test_01_protocol_handler_attachment_and_execution(self):
        """验证 KitHandler / LightConeHandler / RelicSetHandler 协议多态挂载与事件驱动结算。"""
        class TestHeroKit(KitHandler):
            def get_initial_sp_cap(self):
                return 6

            def definition(self, kind: ActionKind) -> AbilityDefinition:
                if kind == ActionKind.BASIC:
                    return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="测试普攻")
                return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1), name="测试战技", tag="专属战技")

            def execute(self, ctx: ActionContext) -> None:
                enemies = self.port.enemies(self.owner_id)
                if enemies:
                    self.port.lose_hp(self.owner_id, 100.0, cause="skill_self_burn")
                    self.port.attack(self.owner_id, enemies[0], element="Ice", atk_multiplier=1.5, toughness_damage=10.0)

        class TestSigLightCone(LightConeHandler):
            DEF_IGNORE = (0.20, 0.25, 0.30, 0.35, 0.40)

            def on_event(self, event):
                if isinstance(event, HPLostEvent) and event.entity_name == self.owner_id:
                    self.port.upsert_status(BuffSpec(
                        key="Test_LC_DefIgnore",
                        name="测试光锥无视防御",
                        source_id=self.owner_id,
                        target_id=self.owner_id,
                        modifiers=[Modifier(StatType.DEF_SHRED, ModifierOp.ADD, self.scale(self.DEF_IGNORE))],
                        duration=2,
                    ))

        class TestCritRelic(RelicSetHandler):
            def on_battle_start(self):
                if self.pieces >= 4:
                    self.port.upsert_status(BuffSpec(
                        key="Test_Relic_CR",
                        name="测试遗器暴击加成",
                        source_id=self.owner_id,
                        target_id=self.owner_id,
                        modifiers=[Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15)],
                        duration=99,
                    ))

        @register_stage_mechanic("test_energy_field")
        class TestStageField(StageMechanicPlugin):
            def on_battle_start(self, sim):
                for ent in sim.entities:
                    if not ent.is_enemy:
                        ent.energy += 15.0

        hero = Entity(
            name="测试新角色",
            base_speed=134.0,
            base_atk=2500.0,
            base_crit_rate=0.05,
            max_hp=3000.0,
            current_hp=3000.0,
            kit=TestHeroKit(owner_id="测试新角色", port=None),
            light_cone=TestSigLightCone(owner_id="测试新角色", superimposition=5),
            relic_handlers=[TestCritRelic(owner_id="测试新角色", pieces=4)],
        )
        enemy = Entity(name="测试木桩", base_speed=100.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(
            entities=[hero, enemy],
            auto_ult=False,
            stage_mechanics=["test_energy_field"],
        )

        self.assertEqual(sim.sp.max_sp, 6)
        self.assertEqual(hero.energy, 15.0)
        self.assertAlmostEqual(sim.port.stat("测试新角色", StatType.CRIT_RATE), 0.20, places=3)

        turn_info = sim.get_turn_action_info()
        skill_action = next(a for a in turn_info["actions"] if a["kind"] == "SKILL")
        self.assertEqual(skill_action["tag"], "专属战技")

        sim.step()
        self.assertTrue(sim.port.has_status("测试新角色", "Test_LC_DefIgnore"))
        self.assertAlmostEqual(sim.port.stat("测试新角色", StatType.DEF_SHRED), 0.40, places=3)

    def test_03_action_advance_ready_queue_lifo_order(self):
        """验证行动就绪队列 (Ready Queue) 与 100% 拉条的 LIFO 插队机制。"""
        e_a = Entity(name="角色A", base_speed=150.0, max_hp=5000.0, current_hp=5000.0)
        e_b = Entity(name="角色B", base_speed=120.0, max_hp=5000.0, current_hp=5000.0)
        e_c = Entity(name="角色C", base_speed=100.0, max_hp=5000.0, current_hp=5000.0)
        enemy = Entity(name="木桩", base_speed=80.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)

        sim = TurnSimulator(entities=[e_a, e_b, e_c, enemy], auto_ult=False)

        actor = sim.advance_to_next_turn()
        self.assertEqual(actor.name, "角色A")

        sim.port.advance("角色A", "角色B", 1.0)
        self.assertEqual(sim._ready_queue, ["角色B"])

        sim.port.advance("角色A", "角色C", 1.0)
        self.assertEqual(sim._ready_queue, ["角色C", "角色B"])

        order_names = [e.name for e in sim.get_action_order()]
        self.assertEqual(order_names[:3], ["角色A", "角色C", "角色B"])

        sim.execute_current_turn()

        next_actor = sim.advance_to_next_turn()
        self.assertEqual(next_actor.name, "角色C")
        sim.execute_current_turn()

        next_actor = sim.advance_to_next_turn()
        self.assertEqual(next_actor.name, "角色B")
        sim.execute_current_turn()


if __name__ == "__main__":
    unittest.main()

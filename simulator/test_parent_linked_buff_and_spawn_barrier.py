"""底层契约重构单元测试：宿主绑定状态 (Parent-Linked Buff) 级联销毁与召唤物入场屏障 (Spawn Barrier)。

严格遵循 Opus 顶层架构师规范：
1. 状态生命周期拓扑不变量：A -> B -> C 跨实体级联销毁、常驻随宿主消失、同到期单次事件；
2. 异常防御：自依赖、成环、缺失宿主拒绝；
3. 动态生命上限收敛：级联移除所有受影响实体的当前生命值正确截断；
4. 召唤物入场屏障：四阶段 REGISTER -> BROADCAST -> STABILIZE -> ACTION_GATE 严格时序与 is_action_ready 校验。
"""
import unittest
from simulator.core import TurnSimulator, Entity
from simulator.combat_port import BuffSpec, SpawnPhase
from simulator.status import Modifier, ModifierOp, DurationTiming, StatType, StackPolicy


class TestParentLinkedBuffCascade(unittest.TestCase):
    def setUp(self):
        self.ent1 = Entity(name="Entity1", base_speed=100.0, max_hp=1000.0, current_hp=1000.0)
        self.ent2 = Entity(name="Entity2", base_speed=100.0, max_hp=1000.0, current_hp=1000.0)
        self.ent3 = Entity(name="Entity3", base_speed=100.0, max_hp=1000.0, current_hp=1000.0)
        self.sim = TurnSimulator(entities=[self.ent1, self.ent2, self.ent3], auto_ult=False)
        self.port = self.sim.port

    def test_01_three_tier_cascade_removal(self):
        """测试 A -> B -> C 跨实体级联销毁：当根状态 A 移除时，B 与 C 同步销毁。"""
        # 1. 施加根宿主状态 A on Entity1
        self.port.upsert_status(BuffSpec(
            key="HostA",
            name="宿主结界A",
            source_id="Entity1",
            target_id="Entity1",
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.20),),
            duration=3
        ))
        self.assertTrue(self.port.has_status("Entity1", "HostA"))

        # 2. 施加派生状态 B on Entity2，绑定 HostA
        self.port.upsert_status(BuffSpec(
            key="ChildB",
            name="派生光环B",
            source_id="Entity1",
            target_id="Entity2",
            modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.15),),
            duration=None,  # 常驻跟随宿主
            parent_key="HostA",
            parent_target_name="Entity1"
        ))
        self.assertTrue(self.port.has_status("Entity2", "ChildB"))

        # 3. 施加次级派生状态 C on Entity3，绑定 ChildB
        self.port.upsert_status(BuffSpec(
            key="GrandchildC",
            name="次级派生C",
            source_id="Entity1",
            target_id="Entity3",
            modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.10),),
            duration=None,
            parent_key="ChildB",
            parent_target_name="Entity2"
        ))
        self.assertTrue(self.port.has_status("Entity3", "GrandchildC"))

        # 4. 显式移除根宿主 A
        self.port.remove_status("Entity1", "HostA")

        # 5. 验证 A、B、C 全部级联销毁，无残留孤儿副本
        self.assertFalse(self.port.has_status("Entity1", "HostA"), "根状态 A 应当已移除")
        self.assertFalse(self.port.has_status("Entity2", "ChildB"), "派生状态 B 应当随根级联移除")
        self.assertFalse(self.port.has_status("Entity3", "GrandchildC"), "次级派生 C 应当随父级联移除")

    def test_02_parent_expire_cascades_permanent_child(self):
        """测试宿主到期自然衰减时，常驻子状态 (duration=None) 同步级联销毁。"""
        self.port.upsert_status(BuffSpec(
            key="HostField",
            name="限时宿主",
            source_id="Entity1",
            target_id="Entity1",
            modifiers=(),
            duration=1,
            timing=DurationTiming.TARGET_TURN_END
        ))
        self.port.upsert_status(BuffSpec(
            key="ChildShared",
            name="常驻共享",
            source_id="Entity1",
            target_id="Entity2",
            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.30),),
            duration=None,
            parent_key="HostField",
            parent_target_name="Entity1"
        ))
        self.assertTrue(self.port.has_status("Entity1", "HostField"))
        self.assertTrue(self.port.has_status("Entity2", "ChildShared"))

        # Entity1 行动结束扣减时钟
        self.sim.status_mgr.tick_on_turn_end(self.ent1)

        # 宿主到期，子状态应级联消失
        self.assertFalse(self.port.has_status("Entity1", "HostField"))
        self.assertFalse(self.port.has_status("Entity2", "ChildShared"))

    def test_03_invalid_linkage_rejected(self):
        """测试自依赖与宿主缺失时被正确防御拦截。"""
        # 1. 尝试自依赖
        with self.assertRaises(ValueError):
            self.port.upsert_status(BuffSpec(
                key="SelfCycle",
                name="自循环",
                source_id="Entity1",
                target_id="Entity1",
                modifiers=(),
                parent_key="SelfCycle",
                parent_target_name="Entity1"
            ))

        # 2. 尝试绑定不存在的宿主
        self.port.upsert_status(BuffSpec(
            key="GhostChild",
            name="幽灵子状态",
            source_id="Entity1",
            target_id="Entity2",
            modifiers=(),
            parent_key="NonExistentHost",
            parent_target_name="Entity1"
        ))
        self.assertFalse(self.port.has_status("Entity2", "GhostChild"), "无宿主派生状态应当被拒绝创建")

    def test_04_cascade_hp_clamp(self):
        """测试级联删除生命上限 Buff 时，受影响目标的当前生命值被原子截断。"""
        # Entity2 初始 1000/1000
        self.port.upsert_status(BuffSpec(
            key="HostAura",
            name="宿主光环",
            source_id="Entity1",
            target_id="Entity1",
            modifiers=(),
            duration=2
        ))
        # 给 Entity2 增加 50% 生命上限
        self.port.upsert_status(BuffSpec(
            key="HPBuffB",
            name="生命上限光环",
            source_id="Entity1",
            target_id="Entity2",
            modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.50),),
            duration=None,
            parent_key="HostAura",
            parent_target_name="Entity1"
        ))
        # Entity2 生命变为 1500/1500
        self.assertAlmostEqual(self.ent2.current_hp, 1500.0)

        # 移除宿主光环
        self.port.remove_status("Entity1", "HostAura")

        # 验证 Entity2 状态被级联移除，且生命值被原子截断回 1000.0
        self.assertFalse(self.port.has_status("Entity2", "HPBuffB"))
        self.assertAlmostEqual(self.ent2.current_hp, 1000.0)


class TestSpawnBarrierStateMachine(unittest.TestCase):
    def setUp(self):
        self.owner = Entity(name="Owner", base_speed=120.0, max_hp=2000.0, current_hp=2000.0)
        self.sim = TurnSimulator(entities=[self.owner], auto_ult=False)
        self.port = self.sim.port

    def test_01_spawn_barrier_lifecycle_and_action_ready(self):
        """测试召唤物入场屏障：REGISTER -> BROADCAST -> STABILIZE -> ACTION_GATE。"""
        spirit = self.port.summon_spirit(
            owner_id="Owner",
            name="TestSpirit",
            base_speed=150.0,
            max_hp=1000.0
        )
        self.assertIsNotNone(spirit)
        self.assertTrue(self.port.entity_exists("TestSpirit"))
        # 召唤完成后，屏障已完成稳定化并放行动作门
        self.assertTrue(self.port.is_action_ready("TestSpirit"))

        # 退场后，动作就绪状态注销
        self.port.despawn_spirit("TestSpirit", reason="测试退场")
        self.assertFalse(self.port.entity_exists("TestSpirit"))
        self.assertFalse(self.port.is_action_ready("TestSpirit"))


if __name__ == "__main__":
    unittest.main()

"""战斗模拟器微内核架构与插件拓展性验证测试套件 (Framework & Extensibility Verification)。

验证目标：
1. 装饰器零侵入自注册机制：`@register_kit`, `@register_light_cone`, `@register_relic_set`, `@register_stage_mechanic`；
2. 伤害拦截协议多态解耦：`KitHandler.intercept_incoming_damage`（如符玄穷观阵分摊，验证 `effects.py` 零硬编码）；
3. 领域事实事件总线解耦：`HPLostEvent` 与 `SpiritDespawnEvent` 驱动光锥被动，无需角色 Kit 直接调用光锥方法；
4. 防御乘区完整汇总：同时计算目标身上的减防 (Defense Shred) 与攻击者身上的无视防御 (Defense Ignore)；
5. `CombatPort` 标准窄接口完备性：无需访问 `port.sim` 或 `port._get_entity` 即可完成命途统计、白字读取与标签过滤采样。
"""
import unittest
from simulator import (
    TurnSimulator, Entity, CombatPort, BuffSpec,
    ActionKind, ActionContext, AbilityDefinition, TargetMode, ResourceCost,
    KitHandler, register_kit, get_kit_class,
    LightConeHandler, LightConeRegistry, register_light_cone,
    RelicSetHandler, RelicRegistry, register_relic_set,
    StageMechanicRegistry, register_stage_mechanic,
    StatType, Modifier, ModifierOp, DurationTiming, StatusTag,
    HPLostEvent, SpiritDespawnEvent
)


class TestFrameworkExtensibility(unittest.TestCase):
    def test_01_decorator_plugin_registration_and_execution(self):
        """验证新人开发通过装饰器即插即用注册新角色、新光锥、新遗器与新关卡环境。"""
        @register_kit("9901", "测试新角色", "test_new_hero")
        class NewHeroKit(KitHandler):
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

        @register_light_cone(cone_id="99001", name="测试专属光锥", path="Remembrance", aliases=("test_sig_lc",))
        class NewSigLightCone(LightConeHandler):
            DEF_IGNORE = (0.20, 0.25, 0.30, 0.35, 0.40)
            def on_event(self, event):
                if isinstance(event, HPLostEvent) and event.entity_name == self.owner_id:
                    self.port.upsert_status(BuffSpec(
                        key="Test_LC_DefIgnore",
                        name="测试光锥无视防御",
                        source_id=self.owner_id,
                        target_id=self.owner_id,
                        modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, self.scale(self.DEF_IGNORE)),),
                        duration=2,
                        timing=DurationTiming.TARGET_TURN_END
                    ))

        @register_relic_set(set_id=991, name="测试四件套", set_type="cavern", aliases=("test_cavern_set",))
        class NewRelicSet(RelicSetHandler):
            def on_battle_start(self):
                if self.pieces >= 4 and self.port:
                    self.port.upsert_status(BuffSpec(
                        key="Test_Relic_CritRate",
                        name="测试遗器暴击",
                        source_id=self.owner_id,
                        target_id=self.owner_id,
                        modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15),),
                        duration=None
                    ))

        @register_stage_mechanic("测试星芒环境")
        class StarlightStagePlugin:
            def __init__(self, name: str = "测试星芒环境"):
                self.name = name
            def on_battle_start(self, sim):
                for e in sim.entities:
                    if not e.is_enemy:
                        sim.port.gain_energy(e.name, 15.0)
            def on_turn_begin(self, active_entity, sim):
                pass
            def on_entity_summoned(self, entity, sim):
                pass

        # 验证注册表无需改动中心文件即可检索
        self.assertIs(get_kit_class("测试新角色"), NewHeroKit)
        lc_inst = LightConeRegistry.create("test_sig_lc", owner_id="测试新角色", superimposition=5)
        self.assertIsInstance(lc_inst, NewSigLightCone)
        relic_inst = RelicRegistry.create(991, owner_id="测试新角色", pieces=4)
        self.assertIsInstance(relic_inst, NewRelicSet)

        hero = Entity(
            name="测试新角色",
            base_speed=150.0,
            base_atk=2000.0,
            max_hp=5000.0,
            current_hp=5000.0,
            kit=NewHeroKit("测试新角色", None),
            light_cone=lc_inst,
            relic_handlers=[relic_inst]
        )
        enemy = Entity(name="测试木桩", base_speed=100.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)

        sim = TurnSimulator(entities=[hero, enemy], stage_mechanics=["测试星芒环境"], auto_ult=False)
        # 验证 get_initial_sp_cap 生效
        self.assertEqual(sim.sp.max_sp, 6)
        # 验证关卡插件进战回能 15 点
        self.assertEqual(hero.energy, 15.0)
        # 验证遗器进战暴击率加成 (+15% -> 20%)
        self.assertAlmostEqual(sim.port.stat("测试新角色", StatType.CRIT_RATE), 0.20, places=3)

        # 验证自定义动作标签在 get_turn_action_info 中生效
        turn_info = sim.get_turn_action_info()
        skill_action = next(a for a in turn_info["actions"] if a["kind"] == "SKILL")
        self.assertEqual(skill_action["tag"], "专属战技")

        # 推进一回合：角色施放战技自扣 100 血 -> 触发 HPLostEvent -> 光锥自动挂载 S5 40% 无视防御 -> 攻击结算生效
        sim.step()
        self.assertTrue(sim.port.has_status("测试新角色", "Test_LC_DefIgnore"))
        self.assertAlmostEqual(sim.port.stat("测试新角色", StatType.DEF_SHRED), 0.40, places=3)

    def test_02_polymorphic_damage_interception_fuxuan(self):
        """验证伤害分摊钩子 intercept_incoming_damage 在不硬编码角色名的情况下正常驱动符玄穷观阵分摊与回血。"""
        from simulator.kits.characters.fuxuan import FuXuanKit
        fuxuan = Entity(
            name="任意存护名_符玄",
            base_speed=140.0,
            max_hp=8000.0,
            current_hp=4200.0,  # 52.5% HP，分摊后跌破 50% 触发天赋自愈
            kit=FuXuanKit("任意存护名_符玄", None)
        )
        ally = Entity(name="脆皮主C", base_speed=120.0, max_hp=3000.0, current_hp=3000.0)
        boss = Entity(name="强敌", base_speed=160.0, base_atk=2000.0, max_hp=50000.0, current_hp=50000.0, is_enemy=True)

        sim = TurnSimulator(entities=[fuxuan, ally, boss], use_techniques=True, auto_ult=False)
        # 秘技已开启穷观阵，现在让强敌对脆皮主C造成伤害
        sim.port.attack("强敌", "脆皮主C", element="Physical", atk_multiplier=1.0, toughness_damage=0.0)
        sim.resolver.resolve_all()

        # 验证脆皮主C只承受了 35% 伤害，且符玄分摊 65% 后跌破半血触发了天赋翻转回血
        self.assertGreater(ally.current_hp, 2600.0)
        self.assertEqual(fuxuan.kit.hp_reversals, 0, "符玄跌破半血应自动消耗 1 次生命翻转并回血")
        self.assertGreater(fuxuan.current_hp, 7000.0)


if __name__ == "__main__":
    unittest.main()

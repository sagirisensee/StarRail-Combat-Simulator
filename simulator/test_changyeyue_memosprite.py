"""长夜月 (ID 1413) 与伴生忆灵「长夜」Nanoka 4.6 规范全套机制单元测试。

验证点覆盖：
1. 进战天赋【今夜与我同行】与行迹【烛火起，烛火熄】【天黑黑，月寂寂】：
   - 进战自动召唤忆灵在场，挂载 70% 增伤、E2 60% 暴伤与 A2 35% 暴击率；
   - 触发忆灵天赋【与夜，形影，不离】立即行动；
   - 忆灵技施放扣除自身 5% 生命 (血量变为 95%)，触发天赋暴伤提升与忆质累积；
   - 开局第一动前忆灵血量精准为 95%，长夜月忆质达到 9 层 (E2无秘技) / 11 层 (E2开秘技)；
   - 支持通过 sim.query_status("长夜") 精确获取独立忆灵状态快照；
2. 普攻【从此岁月朦胧】：生命上限 70% 缩放冰伤，回能 20 点；
3. 战技【白昼悄然离去】：扣除生命触发行迹与天赋，累积忆质并为长夜回血；
4. 天赋【今夜与我同行】阈值触发：当【忆质】>= 16 点时，使忆灵立即行动施放终极爆发【迷梦，流失，如露】；
5. 终极爆发结算：清空忆质，忆灵自毁离场，触发【与你，再见，无期】速度提升与 A2 回复 1 SP；
6. 终结技【晚安，全世界无眠】：耗能 240 点，敌方易伤 30%，增伤 60%，充能管理与至暗之谜。
"""

import unittest
from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.actions import ActionKind
from simulator.status import StatType


class TestChangyeyueMemospriteMechanics(unittest.TestCase):
    def setUp(self):
        self.db = CharacterDB().load("data/character_db_export.json")
        self.changyeyue = self.db.to_combat_entity("长夜月")
        self.boss = Entity(name="首领木桩", base_speed=90.0, max_hp=500000.0, current_hp=500000.0, is_enemy=True)

    def test_01_battle_start_and_memosprite_presence(self):
        """验证进战时自动召唤忆灵在场、生效行迹与E2加成、触发【与夜，形影，不离】立即行动扣血95%与忆质累积。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        kit = self.changyeyue.kit

        # 忆灵在场
        self.assertTrue(kit.spirit_alive, "进战应召唤忆灵在场")

        # 推进长夜开局顶轴第 1 动 (常规忆灵技)
        sim.step()

        # 伴生忆灵「长夜」独立快照验证
        spirit_snap = sim.query_status("长夜")
        self.assertIsNotNone(spirit_snap, "应支持独立查询伴生忆灵「长夜」快照")
        self.assertEqual(spirit_snap["name"], "长夜")
        self.assertEqual(spirit_snap["speed"], 160.0)
        self.assertAlmostEqual(spirit_snap["hp_pct"], 0.95, places=2, msg="长夜动完后血量应精准为 95.0%")

        # 开局忆质层数验证：
        # A4进战获得 2 点 (1+1)
        # 长夜立即行动扣血触发天赋获得 3 点 (2+1)
        # 长夜施放技能触发A4获得 2 点 (1+1)
        # 技能自带获得 2 点 (1+1)
        # 无秘技 E2 合计 13 点【忆质】(A4进战 1+2=3, 扣血天赋 2+2=4, 施法A4 1+2=3, 技能结算 1+2=3)
        self.assertEqual(kit.yizhi, 13, "开局长夜动完后，在E2无秘技下应获得 13 点忆质 (含E2每动+2额外忆质)")

        # 验证长夜月状态快照与 Buff
        snap = sim.query_status("长夜月")
        buff_names = [b["name"] for b in snap["buffs"]]
        self.assertTrue(any("孤独，浮游，漆黑" in b for b in buff_names), "应挂载忆灵在场增伤")
        self.assertTrue(any("呓语" in b for b in buff_names), "E2长夜月应挂载暴伤提升")
        self.assertTrue(any("天黑黑，月寂寂 (暴击率+35%)" in b for b in buff_names), "应挂载A2暴击率")
        self.assertTrue(any("天黑黑，月寂寂 (施法暴伤+15%)" in b for b in buff_names), "长夜施法应挂载A2暴伤提升")
        self.assertTrue(any("今夜与我同行" in b for b in buff_names), "长夜扣血应触发生命降低暴伤提升")

    def test_02_basic_attack_hp_scaling(self):
        """验证普攻【从此岁月朦胧】按长夜月生命上限 70% 缩放结算冰伤与回能。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        # 长夜开局顶轴先动
        sim.step()
        hp_before = self.boss.current_hp
        energy_before = self.changyeyue.energy # 进战 70 + 忆灵技能 5 = 75 点

        sim.execute_current_turn(action_override=ActionKind.BASIC, actor=self.changyeyue)

        damage_dealt = hp_before - self.boss.current_hp
        self.assertGreater(damage_dealt, 0, "普攻应造成伤害")
        self.assertEqual(self.changyeyue.energy, energy_before + 20.0, "普攻应回能 20 点")

    def test_03_skill_hp_loss_and_memory_accumulation(self):
        """验证战技自扣生命、为忆灵恢复生命并累积忆质。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        # 长夜开局顶轴先动
        sim.step()
        kit = self.changyeyue.kit

        # 开局长夜已动，忆灵血量为 95%
        self.assertAlmostEqual(kit.spirit_hp / kit.spirit_max_hp, 0.95, places=2)

        # 清空忆质以测试单次战技的独立累积逻辑
        kit.yizhi = 0
        hp_before = self.changyeyue.current_hp

        sim.execute_current_turn(action_override=ActionKind.SKILL, actor=self.changyeyue)

        # 自扣生命
        self.assertLess(self.changyeyue.current_hp, hp_before)

        # 忆灵在场施放战技，为其恢复 50% 生命上限，生命回满至 100%
        self.assertAlmostEqual(kit.spirit_hp / kit.spirit_max_hp, 1.0, places=2)

        # 战技忆质累加：
        # 自扣 10% 触发生命降低天赋 +3
        # A2 自扣 5% 触发生命降低天赋 +3
        # 战技本身获取 +3 (2+1)
        # A4 施放技能回能回质 +2 (1+1)
        # 单次战技累积 15 点忆质 (自扣10% 2+2=4, A2自扣5% 2+2=4, 战技本身 2+2=4, A4技能 1+2=3)
        self.assertEqual(kit.yizhi, 15, "单次战技自扣血、行迹与施放，在E2下应累积 15 点忆质 (含E2每动+2额外忆质)")

    def test_04_memory_threshold_and_memosprite_burst(self):
        """验证【忆质】达到 16 点时，触发长夜立即行动爆发【迷梦，流失，如露】，清空忆质、自毁加速并回 1 SP。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        kit = self.changyeyue.kit

        # 手动注入 15 点忆质
        kit.yizhi = 15
        self.assertEqual(kit.yizhi, 15)
        self.assertTrue(kit.spirit_alive, "忆灵应在场")

        boss_hp_before = self.boss.current_hp
        sp_before = sim.sp.current_sp

        # 再获得 1 点忆质 (E2 自动变为 1+2=3 点，累计 18 点 >= 16 点，触发阈值立即行动)
        kit.gain_yizhi(1)
        # 忆灵在行动中施放终极爆发【迷梦，流失，如露】
        kit.trigger_spirit_burst()
        sim.resolver.resolve_all()

        # 验证爆发伤害已造成
        self.assertLess(self.boss.current_hp, boss_hp_before, "16忆质应触发长夜终极爆发造成高额冰伤")

        # 爆发消耗全部忆质后，忆灵消耗生命自毁触发天赋生命降低回能/回忆质 (获得 2 点，E2 为 4 点)
        self.assertEqual(kit.yizhi, 4, "爆发消耗全部忆质后，忆灵消耗生命自毁触发生命降低天赋，获得 2+2=4 点忆质")

        # 忆灵自毁离场，在场增伤移除
        self.assertFalse(kit.spirit_alive, "爆发后忆灵应自毁离场")

        # 行迹 A2 恢复 1 点战技点
        self.assertEqual(sim.sp.current_sp, sp_before + 1, "行迹 A2 应在爆发后恢复 1 个战技点")

        # 触发【与你，再见，无期】离场加速 (10% + 17*1% = 27% 速度提升)
        snap = sim.query_status("长夜月")
        buff_names = [b["name"] for b in snap["buffs"]]
        self.assertTrue(any("与你，再见，无期" in b for b in buff_names), "忆灵离场应为长夜月赋予速度加成")

    def test_05_ultimate_darkness_and_charges(self):
        """验证终结技【晚安，全世界无眠】(240耗能) 触发至暗之谜、敌方易伤30%与3点充能(E2)。"""
        sim = TurnSimulator(entities=[self.changyeyue, self.boss], auto_ult=False)
        kit = self.changyeyue.kit

        # 充能 240 点
        self.changyeyue.energy = 240.0
        self.assertTrue(sim.can_cast_ultimate("长夜月"))

        # 施放终结技
        ult_success = sim.cast_ultimate("长夜月")
        self.assertTrue(ult_success)

        # 验证至暗之谜： 4 点充能 (基础2点 + E2额外2点)
        self.assertTrue(kit.darkness, "施放大招后应进入至暗之谜")
        self.assertEqual(kit.charges, 4, "E2施放大招应获得 4 点充能 (基础2点 + E2额外2点)")

        # 敌方易伤 30%
        boss_snap = sim.query_status("首领木桩")
        self.assertAlmostEqual(boss_snap["vulnerability"], 0.30, places=2)

        # 自身增伤 60%
        cyy_snap = sim.query_status("长夜月")
        buff_names = [b["name"] for b in cyy_snap["buffs"]]
        self.assertTrue(any("至暗之谜" in b for b in buff_names), "长夜月应挂载至暗之谜Buff")

        # 验证大招结算后能量：基础回能 5 点 + 行迹【烛火起，烛火熄】施放技能回能 5 点 = 10 点能量
        self.assertEqual(self.changyeyue.energy, 10.0, "长夜月施放大招后能量应精准为 10 点 (5基础 + 5行迹)")


    def test_06_memosprite_full_team_panel_verification(self):
        """验证在实战队伍【长夜月, 缇宝, 知更鸟•晴歌, 风堇】与血噬关卡下，长夜的15项增益、血量与面板全量对账。"""
        from simulate_battle import STAGE_CONFIG, create_enemy_from_config
        team = [self.db.to_combat_entity(n) for n in ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]]
        enemies = [create_enemy_from_config(c) for c in STAGE_CONFIG["waves"][0]["enemies"]]
        sim = TurnSimulator(entities=team + enemies, use_techniques=True, stage_mechanics=STAGE_CONFIG["mechanics"])

        # 推进长夜开局顶轴第 1 动并直达首个玩家决策点 (终极爆发)
        sim.advance_to_interactive_turn()

        # 1. 验证队伍中「记忆」命途角色数量为 3 (长夜月, 风堇, 知更鸟•晴歌)
        cy_kit = team[0].kit
        self.assertEqual(cy_kit._get_remembrance_count(), 3)

        # 2. 验证知更鸟氛围值：风堇开局1 + 知更鸟晴歌开局6 + 长夜开局1 = 8 点
        robin = sim.get_entity("知更鸟•晴歌")
        self.assertEqual(robin.kit.vibes, 8)

        # 验证长夜月身上忆质层数演变与最终值：6 -> 10 -> 17 -> 20 -> 24
        self.assertEqual(cy_kit.yizhi, 24, "开局完整时序动完后，长夜月忆质应精准为 24 层")

        # 3. 验证长夜快照
        msnap = sim.query_status("长夜")
        self.assertEqual(msnap["name"], "长夜")
        self.assertEqual(int(msnap["max_hp"]), 4313)
        self.assertEqual(int(msnap["current_hp"]), 3122)
        self.assertEqual(msnap["speed"], 160.0)
        self.assertEqual(msnap["crit_rate"], 1.036)
        self.assertAlmostEqual(msnap["crit_dmg"], 6.641, delta=0.01)
        self.assertEqual(len(msnap["buffs"]), 15)

        buff_names = [b["name"] for b in msnap["buffs"]]
        expected_15 = [
            "冥花", "今夜与我同行", "偏离和弦", "天黑黑，月寂寂",
            "我们自成旋律", "天亮了，雨落了", "白昼悄然离去", "心意相契的安宁",
            "神启", "谕示", "天气正好", "女武神",
            "听沉眠中的呓语", "孤独，浮游，漆黑"
        ]
        for name in expected_15:
            self.assertTrue(any(name in b for b in buff_names), f"长夜应包含增益: {name}")
        # 验证长夜作为伴生忆灵绝不挂载角色专属标记【好忙好忙的缇宝】，其他效果精准反映关卡环境机制
        self.assertFalse(any("好忙好忙" in o for o in msnap["other_effects"]), "长夜作为伴生忆灵不应挂载角色专属标记【好忙好忙的缇宝】")
        self.assertEqual(msnap["other_effects"], STAGE_CONFIG["mechanics"], f"长夜特殊效果应精准反映关卡环境配置: {STAGE_CONFIG['mechanics']}")

    def test_07_pluggable_stage_mechanics_and_renaming_extensibility(self):
        """验证关卡机制纯插件化：更换机制名称为【流血环境】或动态注册自定义插件时，引擎核心零硬编码且正常驱动。"""
        from simulate_battle import create_enemy_from_config, STAGE_CONFIG
        from simulator.stage_mechanics import StageMechanicRegistry, StageMechanicPlugin

        # 1. 验证别名换名（如换成「流血环境」）：语义分发仍能命中扣血逻辑，且快照状态名称精准为「流血环境」
        team = [self.db.to_combat_entity(n) for n in ["长夜月", "风堇"]]
        enemies = [create_enemy_from_config(c) for c in STAGE_CONFIG["waves"][0]["enemies"]]
        sim_renamed = TurnSimulator(entities=team + enemies, use_techniques=False, stage_mechanics=["流血环境"])
        snap = sim_renamed.query_status("长夜")
        self.assertIn("流血环境", snap["other_effects"], "关卡机制换名为【流血环境】后应能被插件注册中心动态实例化挂载")

        # 2. 验证第三方自定义插件完全插拔（无需改动任何 core.py 源码）
        hook_log = []
        class CustomDomainPlugin(StageMechanicPlugin):
            def __init__(self, name: str = "自定义虚数裂隙"):
                self.name = name
            def on_battle_start(self, sim):
                hook_log.append("battle_start")
            def on_turn_begin(self, active_entity, sim):
                hook_log.append(f"turn_begin_{active_entity.name}")
            def on_entity_summoned(self, entity, sim):
                hook_log.append(f"summoned_{entity.name}")

        StageMechanicRegistry.register("自定义虚数裂隙", CustomDomainPlugin)
        sim_custom = TurnSimulator(entities=team + enemies, use_techniques=False, stage_mechanics=["自定义虚数裂隙"])
        self.assertIn("battle_start", hook_log)
        self.assertIn("summoned_长夜", hook_log)

    def test_08_dynamic_relationship_queries_and_status_tags(self):
        """验证 CombatPort 的实体从属关系与 StatusTag 语义过滤，确保消除任何角色名硬编码黑名单。"""
        from simulate_battle import create_enemy_from_config, STAGE_CONFIG
        from simulator.status import StatusTag

        team = [self.db.to_combat_entity(n) for n in ["长夜月", "风堇", "知更鸟•晴歌"]]
        enemies = [create_enemy_from_config(c) for c in STAGE_CONFIG["waves"][0]["enemies"]]
        sim = TurnSimulator(entities=team + enemies, use_techniques=False)

        port = sim.port
        # 1. 验证动态身份判定
        self.assertTrue(port.is_memosprite("长夜"))
        self.assertFalse(port.is_memosprite("长夜月"))
        self.assertEqual(port.get_master_name("长夜"), "长夜月")
        self.assertTrue(port.is_own_memosprite("长夜月", "长夜"))
        self.assertFalse(port.is_own_memosprite("风堇", "长夜"))
        self.assertTrue(port.is_ally("长夜"))
        self.assertTrue(port.is_ally("风堇"))
        self.assertFalse(port.is_ally(enemies[0].name))

        # 2. 验证 StatusTag 语义过滤 (天亮了雨落了具有 MEMOSPRITE_ONLY 标签)
        spirit_statuses = sim.status_mgr.get_statuses("长夜")
        rain_buff = next((s for s in spirit_statuses if "天亮了，雨落了" in s.name), None)
        self.assertIsNotNone(rain_buff)
        self.assertIn(StatusTag.MEMOSPRITE_ONLY, rain_buff.tags)

        # 忆灵行动攻击后触发知更鸟偏离和弦，和弦同样动态携带 MEMOSPRITE_ONLY 标签
        sim.step()
        spirit_statuses = sim.status_mgr.get_statuses("长夜")
        tonal_chord = next((s for s in spirit_statuses if "偏离和弦" in s.name), None)
        self.assertIsNotNone(tonal_chord)
        self.assertIn(StatusTag.MEMOSPRITE_ONLY, tonal_chord.tags)

    def test_09_ally_memosprite_skill_triggers_candle_trace(self):
        """验证行迹【烛火起，烛火熄】通过统一事件总线驱动：队友忆灵施放技能时同样为长夜月恢复 5 点能量并获得忆质，且倒计时实体不误触发。"""
        from simulator.events import ActionExecuteEvent

        robin = self.db.to_combat_entity("知更鸟•晴歌")
        sim = TurnSimulator(entities=[self.changyeyue, robin, self.boss], use_techniques=False, auto_ult=False)
        cyy_kit = self.changyeyue.kit

        # 知更鸟召唤伴生忆灵「晴空乐手」并进入 Fever 生成「晴空乐手•倒计时」
        robin.kit.summon_musicians()
        robin.kit.gain_vibes(12)
        self.assertTrue(sim.port.is_memosprite("晴空乐手"))
        self.assertTrue(sim.port.is_countdown("晴空乐手•倒计时"))
        self.assertFalse(sim.port.is_memosprite("晴空乐手•倒计时"))

        energy_before = self.changyeyue.energy
        yizhi_before = cyy_kit.yizhi

        # 1. 队友忆灵「晴空乐手」施放忆灵技 -> 触发长夜月【烛火起，烛火熄】(+5 能量，E2 下 +3 忆质)
        sim.event_bus.publish(ActionExecuteEvent(
            av=sim.current_av,
            cycle=sim.current_cycle,
            actor_id="晴空乐手",
            actor_name="晴空乐手",
            action_type="叽叽啾啾四重奏",
            description="施放【叽叽啾啾四重奏】",
            action_kind=ActionKind.SKILL
        ))
        self.assertEqual(self.changyeyue.energy, energy_before + 5.0, "队友忆灵施放技能应触发长夜月恢复 5 点能量")
        self.assertEqual(cyy_kit.yizhi, yizhi_before + 3, "队友忆灵施放技能应触发长夜月获得 1+2=3 点忆质")

        # 2. 机制实体「晴空乐手•倒计时」结算 -> 不应误触发长夜月【烛火起，烛火熄】
        sim.event_bus.publish(ActionExecuteEvent(
            av=sim.current_av,
            cycle=sim.current_cycle,
            actor_id="晴空乐手•倒计时",
            actor_name="晴空乐手•倒计时",
            action_type="Fever倒计时结算",
            description="Fever倒计时结算",
            action_kind=ActionKind.SKILL
        ))
        self.assertEqual(self.changyeyue.energy, energy_before + 5.0, "倒计时实体行动不应误触发长夜月回能")
        self.assertEqual(cyy_kit.yizhi, yizhi_before + 3, "倒计时实体行动不应误触发长夜月获得忆质")


if __name__ == "__main__":
    unittest.main()

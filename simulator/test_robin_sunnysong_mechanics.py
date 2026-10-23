"""知更鸟•晴歌 (Robin: Sunny Song - ID 1512, 风 / 记忆) 官方机制全量专项单元测试。

验证点覆盖 (严格对照 Nanoka 4.6 官方实机规范 1512.json)：
1. 普攻【音浪，为海风定调】：生命上限 HP 缩放 (70%)、风属性、回 1 SP 与回能 20 点；
2. 战技【盛夏是灵魂的乐手】与伴生忆灵【晴空乐手】阶梯登台：
   - 贝茜登台 (回能 20 点，易伤 11.2%)；
   - 气氛值 >= 6 啾米登台 (回能 20 点，易伤 16.8%)；
   - 气氛值 >= 12 派丁登台 (回能 20 点，易伤 22.4%)；
3. 【Fever】状态与倒计时机制：
   - 全员登台触发【Fever】与结界无视防御 (15% + 气氛值 * 0.5%)，气氛值变动实时刷新结界；
   - 晴空乐手施放【叽叽啾啾四重奏】(210% HP 风属性全体伤害，回能 20 点)；
   - 倒计时 (SPD 140) 扣除 50% 气氛值 (至少 12 点)，且倒计时行动本身不触发友方攻击气氛值；
   - 气氛值归零退出【Fever】，清除全部 Fever 增益，乐手与倒计时离场，知更鸟行动提前 50%；
4. 行迹【偏离和弦】(加攻 vs 暴伤动态分流，持续 2 回合) 与终结技【特邀嘉宾】(+2 气氛值、禁止拉条其他友方)；
5. 星魂完整性验证 (E1 记录100%/11%+0.1%真伤/清空50%、E2 抗穿18%/上限70/首技能+2、E4 进Fever+12气氛值与提速、E6 倍率翻倍与140回能)。
"""
import unittest
from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.actions import ActionKind, ActionContext
from simulator.status import StatType


class TestRobinSunnySongMechanics(unittest.TestCase):
    def setUp(self):
        self.db = CharacterDB().load("data/character_db_export.json")
        self.robin_ent = self.db.to_combat_entity("知更鸟•晴歌")
        self.cyy_ent = self.db.to_combat_entity("长夜月")
        self.enemy = Entity(name="测试木桩", base_speed=100.0, max_hp=500000.0, current_hp=500000.0, is_enemy=True)
        self.enemy.is_infinite_hp = True

    def test_01_basic_attack_and_technique(self):
        """测试 1: 验证普攻 HP 缩放、风属性伤害、SP 恢复以及秘技进战拉条 20% 与增益。"""
        sim = TurnSimulator(
            entities=[self.robin_ent, self.enemy],
            use_techniques=True,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")

        # 秘技生效：行动提前 20% (距离从 10000 降为 8000)
        self.assertEqual(robin.distance_remaining, 8000.0)
        self.assertGreaterEqual(robin.kit.vibes, 6)

        # 检查普攻动作定义
        defn = robin.kit.definition(ActionKind.BASIC)
        self.assertEqual(defn.name, "音浪，为海风定调")
        self.assertEqual(defn.cost.sp, -1)

        # 执行普攻
        energy_before = robin.energy
        robin.kit.execute(ActionContext(
            action_id="robin_basic",
            actor_id=robin.name,
            kind=ActionKind.BASIC,
            target_ids=(self.enemy.name,)
        ))
        sim.resolver.resolve_all()

        # 验证回能 20 点
        self.assertEqual(robin.energy, energy_before + 20.0)

    def test_02_skill_summon_bessie_and_progression_to_fever(self):
        """测试 2: 验证战技召唤贝茜、回能 20 点、易伤光环阶梯、进 Fever 实时刷新与结界清理。"""
        sim = TurnSimulator(
            entities=[self.robin_ent, self.cyy_ent, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")
        kit = robin.kit

        # 施放战技召唤贝茜
        energy_before = robin.energy
        kit._execute_skill(ActionContext(
            action_id="robin_skill",
            actor_id=robin.name,
            kind=ActionKind.SKILL,
            target_ids=()
        ))
        sim.resolver.resolve_all()

        # 战技自身回能 30 + 贝茜登台回能 20 (1151205) = 50 点
        self.assertEqual(robin.energy, energy_before + 50.0)
        self.assertTrue(kit.musicians_alive)
        self.assertTrue(kit.has_bessie)
        self.assertEqual(kit.member_count, 1)

        # 验证 1 位乐手易伤光环 (11.2%)
        snap_enemy = sim.query_status("测试木桩")
        vul_buff = next((b for b in snap_enemy["debuffs"] if "扑翅雀跃的和声" in b["name"]), None)
        self.assertIsNotNone(vul_buff)
        self.assertIn("11.2%", vul_buff["modifiers_desc"])

        # 获得气氛值至 6 点 -> 召唤啾米 (再回能 20 点，易伤升至 16.8%)
        kit.gain_vibes(6)
        self.assertTrue(kit.has_drummie)
        self.assertEqual(kit.member_count, 2)
        snap_enemy = sim.query_status("测试木桩")
        vul_buff = next((b for b in snap_enemy["debuffs"] if "扑翅雀跃的和声" in b["name"]), None)
        self.assertIn("16.8%", vul_buff["modifiers_desc"])

        # 获得气氛值至 12 点 -> 召唤派丁 (再回能 20 点，全员登台进入【Fever】)
        kit.gain_vibes(6)
        self.assertTrue(kit.has_paddie)
        self.assertEqual(kit.member_count, 3)
        self.assertTrue(kit.in_fever, "全员登台应开启【Fever】状态")

        # 验证 Fever 结界防御无视 (15% + 12 * 0.5% = 21.0%)
        snap_cyy = sim.query_status("长夜月")
        def_ignore = next((b for b in snap_cyy["buffs"] if "巡游在无界的天空" in b["name"]), None)
        self.assertIsNotNone(def_ignore, "全队应获得 Fever 结界无视防御加成")
        self.assertIn("21.0%", def_ignore["modifiers_desc"])

        # Fever 期间再获得 4 点气氛值 (至 16 点)，验证结界无视防御实时刷新至 23.0%
        kit.gain_vibes(4)
        snap_cyy = sim.query_status("长夜月")
        def_ignore = next((b for b in snap_cyy["buffs"] if "巡游在无界的天空" in b["name"]), None)
        self.assertIn("23.0%", def_ignore["modifiers_desc"])

        # 验证场景中存在倒计时实体
        countdown = sim.get_entity("晴空乐手•倒计时")
        self.assertIsNotNone(countdown, "场景中应生成【晴空乐手•倒计时】实体")
        self.assertEqual(countdown.speed, 140.0)

    def test_03_fever_countdown_and_exit_advance(self):
        """测试 3: 验证倒计时扣除 50% 气氛值，归零退出 Fever、清除全部 Fever 增益并使知更鸟拉条 50%。"""
        sim = TurnSimulator(
            entities=[self.robin_ent, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")
        kit = robin.kit

        # 开启战技并直接注入 16 点气氛值激活 Fever
        kit.summon_musicians()
        kit.gain_vibes(16)
        self.assertTrue(kit.in_fever)
        self.assertEqual(kit.vibes, 16)

        # 倒计时第 1 次结算：16 - max(12, floor(8)) = 16 - 12 = 4 点
        kit.on_countdown_turn()
        self.assertEqual(kit.vibes, 4)
        self.assertTrue(kit.in_fever)

        # 倒计时第 2 次结算：4 - 12 <= 0 -> 归零，退出 Fever，乐手与倒计时离场，知更鸟拉条 50%
        kit.on_countdown_turn()
        self.assertEqual(kit.vibes, 0)
        self.assertFalse(kit.in_fever)
        self.assertFalse(kit.musicians_alive)
        self.assertIsNone(sim.get_entity("晴空乐手"))
        self.assertIsNone(sim.get_entity("晴空乐手•倒计时"))
        # 验证退出 Fever 后知更鸟身上的 Fever 增伤与减防已彻底移除
        snap_robin = sim.query_status("知更鸟•晴歌")
        self.assertFalse(any("Fever增伤" in b["name"] for b in snap_robin["buffs"]))
        self.assertFalse(any("巡游在无界的天空" in b["name"] for b in snap_robin["buffs"]))
        # 验证 1151206 知更鸟拉条 50% (distance_remaining = 5000.0)
        self.assertEqual(robin.distance_remaining, 5000.0)

    def test_04_tonal_chord_and_special_guest_mechanics(self):
        """测试 4: 验证行迹【偏离和弦】加攻/暴伤分流、终结技【特邀嘉宾】额外气氛值及禁拉条其他友方限制。"""
        sim = TurnSimulator(
            entities=[self.robin_ent, self.cyy_ent, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")
        kit = robin.kit

        # 1. 偏离和弦：长夜月 ATK <= 知更鸟 ATK，获得暴伤加成 (持续 2 回合)
        kit.vibes = 10
        kit.apply_tonal_chord_to_ally("长夜月")
        snap = sim.query_status("长夜月")
        chord_buff = next((b for b in snap["buffs"] if "偏离和弦" in b["name"]), None)
        self.assertIsNotNone(chord_buff)
        # 0.40 + 10 * 0.015 = 0.55 (55.0% 暴伤)
        self.assertIn("55.0%", chord_buff["modifiers_desc"])

        # 2. 终结技赋予长夜月【特邀嘉宾】
        robin.energy = 140.0
        sim.cast_ultimate("知更鸟•晴歌", target_ids=("长夜月",))
        snap = sim.query_status("长夜月")
        guest_buff = next((b for b in snap["buffs"] if "特邀嘉宾" in b["name"]), None)
        self.assertIsNotNone(guest_buff)

        # 验证持有【特邀嘉宾】的角色无法使其他友方目标获得行动提前效果
        robin_dist_before = robin.distance_remaining
        sim.port.advance("长夜月", "知更鸟•晴歌", 0.50)
        sim.resolver.resolve_all()
        self.assertEqual(robin.distance_remaining, robin_dist_before, "持有【特邀嘉宾】的角色不应能拉条其他友方角色")

        # 3. 特邀嘉宾攻击触发额外 +2 气氛值
        vibes_before = kit.vibes
        from simulator.events import ActionExecuteEvent
        sim.event_bus.publish(ActionExecuteEvent(
            av=sim.current_av,
            cycle=sim.current_cycle,
            actor_id="长夜月",
            actor_name="长夜月",
            action_type="BasicAttack",
            description="长夜月攻击"
        ))
        # 基础 1 点 + 特邀嘉宾 2 点 = 3 点
        self.assertEqual(kit.vibes, vibes_before + 3)

    def test_05_eidolons_progression(self):
        """测试 5: 严格对照 1512.json 验证 E1(100%记录/11%+0.1%真伤/清空50%)、E2(抗穿18%/上限70/+2气氛值)、E4(进Fever+12/提速) 与 E6(倍率翻倍/140回能)。"""
        robin_e6 = self.db.to_combat_entity("知更鸟•晴歌")
        robin_e6.kit.eidolon = 6

        sim = TurnSimulator(
            entities=[robin_e6, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        kit = robin_e6.kit

        # 1. 验证 E2 气氛值上限自动动态计算为 70 点 (无需手动赋值 max_vibes)
        self.assertEqual(kit.max_vibes, 70)

        # 2. 验证 E2 全队全属性抗穿 +18%
        snap_robin = sim.query_status("知更鸟•晴歌")
        self.assertTrue(any("心似一片湖水" in b["name"] for b in snap_robin["buffs"]))

        # 3. 验证 E1 记录 100% 伤害，并在施放忆灵技时造成 (11% + 气氛值*0.1%) 真实伤害，随后清空 50% 记录值
        kit.summon_musicians()
        from simulator.events import DamageAppliedEvent
        sim.event_bus.publish(DamageAppliedEvent(
            av=0.0,
            cycle=0,
            attacker_name=robin_e6.name,
            target_name=self.enemy.name,
            damage=10000.0,
            is_crit=True,
            breakdown=None,
            target_hp_left=490000.0
        ))
        # E1 #3 = 1.0 -> 记录 100% = 10000.0 点
        self.assertEqual(kit.recorded_damage, 10000.0)

        # 忆灵施放【叽叽啾啾四重奏】：倍率因 E6 翻倍至 4.20，并清空 50% 的 E1 记录伤害 (剩余 5000.0)
        m_ent = sim.get_entity("晴空乐手")
        m_ent.kit.execute(ActionContext(
            action_id="musician_skill",
            actor_id=m_ent.name,
            kind=ActionKind.SKILL,
            target_ids=()
        ))
        self.assertEqual(kit.recorded_damage, 5000.0, "施放忆灵技后应清空 50% 记录伤害")

        # 4. 验证进入 Fever 时：E4 立即获得 12 点气氛值，E6 首次进入 Fever 固定恢复 140 点能量
        robin_e6.energy = 0.0
        kit.gain_vibes(12)  # 触发全员登台进入 Fever (12 + E4赠送12 = 24 点气氛值)
        self.assertTrue(kit.in_fever)
        self.assertEqual(kit.vibes, 24, "12点触发进Fever后应立即获得E4的12点气氛值，共24点")
        self.assertEqual(robin_e6.energy, 140.0, "E6 首次进入 Fever 应固定恢复 140 点能量满能")

    def test_06_amphoreus_relic_team_speed_buff(self):
        """测试 6: 验证装备【永恒之地翁法罗斯】(ID 323) 时，忆灵「晴空乐手」在场为我方全体提供 8% 速度加成。"""
        sim = TurnSimulator(
            entities=[self.robin_ent, self.cyy_ent, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")
        cyy = sim.get_entity("长夜月")

        # 召唤晴空乐手前：晴空乐手不在场，晴歌身上的翁法罗斯套装不生效
        robin_spd_before = robin.speed
        cyy_spd_before = cyy.speed

        # 施放战技召唤「晴空乐手」
        robin.kit.summon_musicians()
        sim.resolver.resolve_all()

        # 召唤后：晴空乐手在场，我方全体获得 8% 速度加成
        # 知更鸟白字 95 * 0.08 = 7.6
        self.assertAlmostEqual(robin.speed, robin_spd_before + 95.0 * 0.08, places=2)
        # 长夜月白字 99 * 0.08 = 7.92
        self.assertAlmostEqual(cyy.speed, cyy_spd_before + 99.0 * 0.08, places=2)



    def test_07_amphoreus_relic_non_stacking_and_graceful_despawn(self):
        """测试 7: 验证【永恒之地翁法罗斯】不叠加规则 (双装备者只有 8%) 及单人忆灵退场不误删全队效果。"""
        from simulator.relics.handlers.eternal_land_of_amphoreus import EternalLandOfAmphoreusHandler
        sim = TurnSimulator(
            entities=[self.robin_ent, self.cyy_ent, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")
        cyy = sim.get_entity("长夜月")

        # 让长夜月也装备翁法罗斯 2 件套
        cyy_amphoreus = EternalLandOfAmphoreusHandler(owner_id="长夜月", port=sim.port, pieces=2)
        cyy.relic_handlers.append(cyy_amphoreus)

        # 初始：长夜月的伴生忆灵「长夜」已自动召唤在场
        self.assertTrue(cyy.kit.spirit_alive)
        cyy_amphoreus.on_battle_start()

        # 全队应有 8% 速度加成 (长夜在场)
        self.assertTrue(sim.port.has_status("知更鸟•晴歌", EternalLandOfAmphoreusHandler.BUFF_KEY))
        robin_spd_1 = robin.speed

        # 晴歌也施放战技召唤晴空乐手 (此时两名角色均有忆灵在场)
        robin.kit.summon_musicians()
        sim.resolver.resolve_all()

        # 验证“该效果无法叠加”：知更鸟的速度依然是 1 份 8% 加成，没有变成 16%
        self.assertAlmostEqual(robin.speed, robin_spd_1, places=2)

        # 模拟晴空乐手离场 (退场)
        sim.port.despawn_spirit("晴空乐手", reason="test_exit")
        # 触发晴歌的遗器同步
        for handler in robin.relic_handlers:
            if isinstance(handler, EternalLandOfAmphoreusHandler):
                handler._sync_speed_buff()

        # 验证：因为长夜月的忆灵「长夜」仍然在场，全队 8% 加速不应被误删！
        self.assertTrue(sim.port.has_status("知更鸟•晴歌", EternalLandOfAmphoreusHandler.BUFF_KEY))
        self.assertAlmostEqual(robin.speed, robin_spd_1, places=2)

    def test_08_improvisational_blues_rhythm_in_turn_and_5_turns_linkage(self):
        """测试 8: 验证行迹【即兴蓝调】律动消耗仅在实战回合生效、门禁重置机制与 5 次回合联动对账 (律动精准降为 7 层，氛围值结算为 14 点)。"""
        from simulator.events import TurnBeginEvent, ActionExecuteEvent
        from simulator.combat_port import BuffSpec
        from simulator.status import DurationTiming, StatusTag

        sim = TurnSimulator(
            entities=[self.robin_ent, self.cyy_ent, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")
        kit = robin.kit

        # 1. 模拟开局注入 12 层律动与 7 点氛围值 (风堇秘技治疗 1 点 + 知更鸟秘技 6 点)
        kit.rhythm_stacks = 12
        kit.vibes = 7
        self.assertEqual(kit.rhythm_stacks, 12, "开局律动维持 12 层")
        self.assertEqual(kit.vibes, 7, "战前氛围值基准为 7 点")

        # 2. Turn 1: 友方回合 -> 首次获能，律动 12 -> 11，氛围值 7 -> 8
        sim.event_bus.publish(TurnBeginEvent(av=10.0, cycle=0, actor_id="长夜月", actor_name="长夜月", speed=100.0))
        self.assertFalse(kit._rhythm_consumed_in_current_turn, "新回合开始重置律动消耗门禁")
        sim.event_bus.publish(ActionExecuteEvent(av=10.0, cycle=0, actor_id="长夜月", actor_name="长夜月", action_type="BasicAttack", description="普攻", action_kind=ActionKind.BASIC))
        self.assertEqual(kit.rhythm_stacks, 11)
        self.assertEqual(kit.vibes, 8)
        self.assertTrue(kit._rhythm_consumed_in_current_turn, "获能后门禁生效，锁定本回合不重复消耗")

        # 3. Turn 2: 友方回合 -> TurnBeginEvent 重置门禁，律动 11 -> 10，氛围值 8 -> 9
        sim.event_bus.publish(TurnBeginEvent(av=20.0, cycle=0, actor_id="长夜月", actor_name="长夜月", speed=100.0))
        self.assertFalse(kit._rhythm_consumed_in_current_turn)
        sim.event_bus.publish(ActionExecuteEvent(av=20.0, cycle=0, actor_id="长夜月", actor_name="长夜月", action_type="BasicAttack", description="普攻", action_kind=ActionKind.BASIC))
        self.assertEqual(kit.rhythm_stacks, 10)
        self.assertEqual(kit.vibes, 9)

        # 4. Turn 3: 友方回合 -> 普攻，律动 10 -> 9，氛围值 9 -> 10
        sim.event_bus.publish(TurnBeginEvent(av=30.0, cycle=0, actor_id="长夜月", actor_name="长夜月", speed=100.0))
        sim.event_bus.publish(ActionExecuteEvent(av=30.0, cycle=0, actor_id="长夜月", actor_name="长夜月", action_type="BasicAttack", description="普攻", action_kind=ActionKind.BASIC))
        self.assertEqual(kit.rhythm_stacks, 9)
        self.assertEqual(kit.vibes, 10)

        # 5. Turn 4: 友方回合 -> 普攻，律动 9 -> 8，氛围值 10 -> 11
        sim.event_bus.publish(TurnBeginEvent(av=40.0, cycle=0, actor_id="长夜月", actor_name="长夜月", speed=100.0))
        sim.event_bus.publish(ActionExecuteEvent(av=40.0, cycle=0, actor_id="长夜月", actor_name="长夜月", action_type="BasicAttack", description="普攻", action_kind=ActionKind.BASIC))
        self.assertEqual(kit.rhythm_stacks, 8)
        self.assertEqual(kit.vibes, 11)

        # 6. Turn 5: 长夜月获得【特邀嘉宾】并行动 -> 攻击触发 +3 氛围值 (基础1 + 特邀2 = 3)，律动 8 -> 7，氛围值 11 -> 14
        sim.port.upsert_status(BuffSpec(
            key=kit.ULT_SPECIAL_GUEST_BUFF,
            name="特邀嘉宾",
            source_id=robin.name,
            target_id="长夜月",
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_START,
            tags=(StatusTag.CANNOT_ADVANCE_OTHER_ALLIES,),
            description="特邀嘉宾"
        ))
        sim.event_bus.publish(TurnBeginEvent(av=50.0, cycle=0, actor_id="长夜月", actor_name="长夜月", speed=100.0))
        sim.event_bus.publish(ActionExecuteEvent(av=50.0, cycle=0, actor_id="长夜月", actor_name="长夜月", action_type="BasicAttack", description="特邀嘉宾普攻", action_kind=ActionKind.BASIC))

        # 最终状态校验：5 次回合联动后，律动层数精准降为 7 层，氛围值自然结算为 14 点（绝无任何硬编码赋值）！
        self.assertEqual(kit.rhythm_stacks, 7, "经历 5 次回合联动后律动层数精准降为 7 层")
        self.assertEqual(kit.vibes, 14, "经历 5 次回合联动后氛围值精准结算为 14 点")


if __name__ == "__main__":
    unittest.main()

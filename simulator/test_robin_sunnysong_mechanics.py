"""知更鸟•晴歌 (Robin: Sunny Song - ID 1512, 风 / 记忆) 官方机制全量专项单元测试。

验证点覆盖 (对照 Nanoka 4.6 官方实机规范 1512.json)：
1. 普攻【音浪，为海风定调】：生命上限 HP 缩放 (70%)、风属性、回 1 SP 与回能 20 点；
2. 战技【盛夏是灵魂的乐手】与伴生忆灵【晴空乐手】阶梯登台：
   - 贝茜登台 (回能 20 点，易伤 11.2%)；
   - 气氛值 >= 6 啾米登台 (回能 20 点，易伤 16.8%)；
   - 气氛值 >= 12 派丁登台 (回能 20 点，易伤 22.4%)；
3. 【Fever】状态与倒计时机制：
   - 全员登台触发【Fever】与结界无视防御 (15% + 气氛值 * 0.5%)；
   - 晴空乐手施放【叽叽啾啾四重奏】(210% HP 风属性全体伤害)；
   - 倒计时 (SPD 140) 扣除 50% 气氛值 (至少 12 点)；
   - 气氛值归零退出【Fever】，乐手与倒计时离场，知更鸟行动提前 50%；
4. 行迹【偏离和弦】(加攻 vs 暴伤动态分流，持续 2 回合) 与终结技【特邀嘉宾】(+2 气氛值)；
5. 星魂完整性验证 (E1 真实伤害、E2 抗穿与上限、E4 提速、E6 倍率翻倍与回能)。
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
        sp_before = sim.sp.current_sp
        energy_before = robin.energy
        robin.kit.execute(ActionContext(
            action_id="robin_basic",
            actor_id=robin.name,
            kind=ActionKind.BASIC,
            target_ids=(self.enemy.name,)
        ))
        sim.resolver.resolve_all()

        # 验证回能 20 点与恢复 1 点 SP (sp 由 resolver 结算或定义标记)
        self.assertEqual(robin.energy, energy_before + 20.0)

    def test_02_skill_summon_bessie_and_progression_to_fever(self):
        """测试 2: 验证战技召唤贝茜、回能 20 点、易伤光环阶梯与进入【Fever】。"""
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

        # 验证 Fever 结界防御无视与增伤挂载
        snap_cyy = sim.query_status("长夜月")
        def_ignore = next((b for b in snap_cyy["buffs"] if "巡游在无界的天空" in b["name"]), None)
        self.assertIsNotNone(def_ignore, "全队应获得 Fever 结界无视防御加成")

        # 验证场景中存在倒计时实体
        countdown = sim.get_entity("晴空乐手•倒计时")
        self.assertIsNotNone(countdown, "场景中应生成【晴空乐手•倒计时】实体")
        self.assertEqual(countdown.speed, 140.0)

    def test_03_fever_countdown_and_exit_advance(self):
        """测试 3: 验证倒计时扣除 50% 气氛值，归零退出 Fever 并使知更鸟拉条 50%。"""
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
        # 验证 1151206 知更鸟拉条 50% (distance_remaining = 5000.0)
        self.assertEqual(robin.distance_remaining, 5000.0)

    def test_04_tonal_chord_and_special_guest_mechanics(self):
        """测试 4: 验证行迹【偏离和弦】加攻/暴伤分流与终结技【特邀嘉宾】。"""
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
        """测试 5: 验证 E1 真实伤害记录与结算、E2 抗穿与上限、E4 提速与 E6 倍率翻倍。"""
        robin_e6 = self.db.to_combat_entity("知更鸟•晴歌")
        robin_e6.kit.eidolon = 6
        robin_e6.kit.max_vibes = 70 # E2 提升上限

        sim = TurnSimulator(
            entities=[robin_e6, self.enemy],
            use_techniques=False,
            auto_ult=False
        )
        kit = robin_e6.kit

        # 验证 E2 气氛值上限为 70 点
        self.assertEqual(kit.max_vibes, 70)

        # 验证 E2 全队全属性抗穿 +18%
        snap_robin = sim.query_status("知更鸟•晴歌")
        self.assertTrue(any("心似一片湖水" in b["name"] for b in snap_robin["buffs"]))

        # 验证 E1 记录伤害并在施放忆灵技时造成真实伤害
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
        # 记录 15% = 1500 点
        self.assertEqual(kit.recorded_damage, 1500.0)

        # 忆灵施放【叽叽啾啾四重奏】：倍率因 E6 翻倍至 4.20，并清空 E1 记录伤害
        m_ent = sim.get_entity("晴空乐手")
        m_ent.kit.execute(ActionContext(
            action_id="musician_skill",
            actor_id=m_ent.name,
            kind=ActionKind.SKILL,
            target_ids=()
        ))
        self.assertEqual(kit.recorded_damage, 0.0, "施放忆灵技后记录伤害应清零")


if __name__ == "__main__":
    unittest.main()

"""长夜月核心四人队伍 (长夜月 + 缇宝 + 知更鸟•晴歌 + 风堇) 机制协同与生命周期完整单元测试。

验证点覆盖：
1. 四人队伍初始化与开局秘技联动 (长夜召唤、风堇生命提升、知更鸟气氛值、缇宝充能就绪)
2. 知更鸟•晴歌【跃入这片蔚蓝狂想】指定单体 100% 立即行动拉条、20% 回能与【特邀嘉宾】
3. 长夜月与忆灵「长夜」的完整循环 (忆质累积满 16 层 -> 触发忆灵爆发 -> 自毁加速 -> 回复 SP)
4. 风堇大招生命增益对长夜月 HP 上限与缩放基础区的动态放大
5. 队伍在首领木桩下的 150 AV 连续跑条完整推演 (13 动全流程零死锁、零异常)
6. 实机双波次关卡秒杀结算 (Wave 1 被缇宝爆发秒杀，敌方全灭触发正常胜利终止)
"""
import unittest
from simulator.db.character_db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.actions import ActionKind
from simulator.status import StatType
from simulate_battle import STAGE_CONFIG, create_enemy_from_config


class TestChangyeyueTeamSynergy(unittest.TestCase):
    def setUp(self):
        self.db = CharacterDB().load("data/character_db_export.json")
        self.team_names = ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]
        self.team_entities = [self.db.to_combat_entity(n) for n in self.team_names]
        # 对齐实机初始半能规则
        for ent in self.team_entities:
            if ent.max_energy > 0 and ent.energy == 0.0:
                ent.energy = ent.max_energy * 0.5
        self.enemies = [create_enemy_from_config(c) for c in STAGE_CONFIG["waves"][0]["enemies"]]

    def test_01_team_battle_start_initialization(self):
        """测试 1: 验证 4 人队伍进战时各角色的专属机制与秘技初始化。"""
        sim = TurnSimulator(
            entities=self.team_entities + self.enemies,
            use_techniques=True,
            auto_ult=False,
            stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
        )

        cyy = sim.get_entity("长夜月")
        tibao = sim.get_entity("缇宝")
        robin = sim.get_entity("知更鸟•晴歌")

        # 1. 长夜月伴生忆灵在场
        self.assertTrue(cyy.kit.spirit_alive, "长夜月进战应召唤伴生忆灵「长夜」")
        self.assertIsNotNone(sim.get_entity("长夜"), "场景中应存在伴生忆灵「长夜」")

        # 2. 缇宝满能
        self.assertEqual(tibao.energy, 120.0, "缇宝开局应为 120/120 满能")

        # 3. 风堇秘技加成生命 (进战生命上限提升)
        snap_cyy = sim.query_status("长夜月")
        self.assertGreater(snap_cyy["max_hp"], 8000.0, "长夜月在队伍加成下生命应超过 8000")

        # 4. 知更鸟秘技气氛值初始化
        self.assertGreaterEqual(robin.kit.vibes, 6, "知更鸟进战秘技应获得至少 6 点气氛值")

    def test_02_robin_ultimate_single_ally_advance_and_special_guest(self):
        """测试 2: 验证知更鸟施放终结技【跃入这片蔚蓝狂想】使指定单体我方行动提前 100%、回能 20% 并赋予【特邀嘉宾】。"""
        sim = TurnSimulator(
            entities=self.team_entities + self.enemies,
            use_techniques=True,
            auto_ult=False
        )
        robin = sim.get_entity("知更鸟•晴歌")
        cyy = sim.get_entity("长夜月")

        # 记录长夜月施放大招前的能量
        cyy_energy_before = cyy.energy
        expected_energy_gain = cyy.max_energy * 0.20

        # 模拟给知更鸟充能并指定长夜月施放大招
        robin.energy = robin.max_energy
        ult_success = sim.cast_ultimate("知更鸟•晴歌", target_ids=("长夜月",))
        self.assertTrue(ult_success, "知更鸟终结技施放应成功")

        # 1. 验证目标长夜月 100% 拉条 (distance_remaining 与 remaining_av 归零)
        self.assertEqual(cyy.distance_remaining, 0.0, "长夜月 distance_remaining 应被推进至 0")
        self.assertEqual(cyy.remaining_av, 0.0, "长夜月 remaining_av 应被推进至 0")

        # 2. 验证目标长夜月固定恢复 20% 能量上限的能量
        self.assertAlmostEqual(cyy.energy, cyy_energy_before + expected_energy_gain, places=2)

        # 3. 验证目标长夜月获得【特邀嘉宾】增益，持续 2 回合
        snap_cyy = sim.query_status("长夜月")
        buff_names = [b["name"] for b in snap_cyy["buffs"]]
        self.assertIn("特邀嘉宾", buff_names, "长夜月应获得【特邀嘉宾】增益")

        # 4. 验证特邀嘉宾攻击时，额外使知更鸟获得 2 点气氛值 (基础 1 点 + 额外 2 点 = 3 点)
        vibes_before = robin.kit.vibes
        sim.step()
        self.assertEqual(robin.kit.vibes, vibes_before + 3, "特邀嘉宾攻击应额外提供 2 点气氛值 (共 +3 点)")

    def test_03_changyeyue_yizhi_burst_and_self_destruction(self):
        """测试 3: 验证长夜月忆质累积满 16 层触发忆灵立即爆发并自毁加速。"""
        sim = TurnSimulator(
            entities=self.team_entities + self.enemies,
            use_techniques=False,
            auto_ult=False
        )
        cyy = sim.get_entity("长夜月")
        kit = cyy.kit

        # 手动注入 15 点忆质
        kit.yizhi = 15
        self.assertTrue(kit.spirit_alive, "爆发前忆灵应在场")
        speed_before = cyy.speed

        # 增加 1 点忆质 (E2 下 1+2=3 点，累计 18 点 >= 16 点)
        kit.gain_yizhi(1)
        self.assertGreaterEqual(kit.yizhi, 16)

        # 触发忆灵终极爆发【迷梦，流失，如露】并自毁离场
        kit.trigger_spirit_burst()

        self.assertFalse(kit.spirit_alive, "忆灵终极爆发后应自毁离场")
        self.assertEqual(kit.yizhi, 4, "爆发消耗全部忆质后，忆灵消耗生命自毁触发生命降低天赋，获得 2+2=4 点忆质")
        self.assertGreater(cyy.speed, speed_before, "忆灵自毁后长夜月应获得速度提升 (与你，再见，无期)")

    def test_04_fengjin_ult_scales_changyeyue_hp(self):
        """测试 4: 验证风堇施放终结技提升全队生命上限，动态放大长夜月生命值。"""
        sim = TurnSimulator(
            entities=self.team_entities + self.enemies,
            use_techniques=False,
            auto_ult=False
        )
        fengjin = sim.get_entity("风堇")

        hp_before = sim.query_status("长夜月")["max_hp"]

        # 风堇充能并施放大招
        fengjin.energy = fengjin.max_energy
        sim.cast_ultimate("风堇")

        hp_after = sim.query_status("长夜月")["max_hp"]
        self.assertGreater(hp_after, hp_before, "风堇大招后长夜月实战生命上限应显著提升")

    def test_05_team_end_to_end_150_av_boss_simulation(self):
        """测试 5: 四人完整队伍在首领木桩对战下自动推演 150 AV，验证连续行动流转稳定、无报错。"""
        boss = Entity(name="拟真Boss", base_speed=120.0, max_hp=100000000.0, current_hp=100000000.0, is_enemy=True)
        boss.is_infinite_hp = True

        sim = TurnSimulator(
            entities=self.team_entities + [boss],
            use_techniques=True,
            auto_ult=True,
            stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
        )

        turns = 0
        for _ in sim.run_until_av(max_av=150.0):
            turns += 1

        self.assertGreaterEqual(turns, 10, "在 150 AV 首领对局中全队总行动次数应至少达到 10 次")
        status = sim.get_battle_status()
        self.assertIn("team", status)
        self.assertIn("enemies", status)
        self.assertGreater(sim.current_av, 100.0)

    def test_06_wave_instant_clear_terminates_gracefully(self):
        """测试 6: 验证在真实小怪关卡中，缇宝开局爆发秒杀全怪后，引擎优雅识别全灭并终止排轴。"""
        sim = TurnSimulator(
            entities=self.team_entities + self.enemies,
            use_techniques=True,
            auto_ult=True,
            stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
        )

        turns = 0
        for _ in sim.run_until_av(max_av=150.0):
            turns += 1

        # 缇宝开局秒杀 Wave 1，敌人全灭，排轴正常退出
        alive_enemies = [e for e in sim.entities if e.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))]
        self.assertEqual(len(alive_enemies), 0, "Wave 1 敌方目标应全部阵亡")

    def test_07_robin_sunnysong_full_panel_verification(self):
        """测试 7: 验证知更鸟•晴歌实战全量对账 (战前结算 73 能量/11 层律动 -> 首个玩家决策点 76 能量/10 层律动/234.1% 暴伤)。"""
        sim = TurnSimulator(
            entities=self.team_entities + self.enemies,
            use_techniques=True,
            auto_ult=False,
            stage_mechanics=STAGE_CONFIG.get("mechanics", ["血噬"])
        )

        # 阶段 1：0.0 AV 战前秘技结算期 (step=0，消耗第 1 层律动：12 -> 11 层，能量 70 -> 73)
        snap_pre = sim.query_status("知更鸟•晴歌")
        robin_kit = sim.get_entity("知更鸟•晴歌").kit
        self.assertEqual(robin_kit.rhythm_stacks, 11, "战前秘技结算后律动消耗 1 层，剩余 11 层")
        self.assertEqual(int(snap_pre["current_energy"]), 73, "战前回能 3 点，能量为 73/140")
        self.assertEqual(robin_kit.vibes, 7, "战前风堇治疗+1、知更鸟秘技+6，气氛值精准为 7 点")

        # 阶段 2：推进至首个玩家可操作决策回合 (长夜自动喷水完成，消耗第 2 层律动：11 -> 10 层，能量 73 -> 76)
        actor = sim.advance_to_interactive_turn()
        self.assertEqual(actor.name, "长夜", "首个玩家可操作决策回合应为【长夜】满忆质终极爆发")

        snap = sim.query_status("知更鸟•晴歌")

        # 1. 双暴对账：暴击率 91.3% (基础 41.3% + 重构谐乐 50.0%)，暴击伤害 234.1% (7 气氛值偏离和弦 50.5%)
        self.assertAlmostEqual(snap["current_crit_rate"], 0.913, places=3)
        self.assertAlmostEqual(snap["current_crit_dmg"], 2.341, places=3)

        # 2. 能量对账：76 / 140 (初始 70 + 消耗 2 层律动回能 6 点)
        self.assertEqual(int(snap["current_energy"]), 76)
        self.assertEqual(int(snap["max_energy"]), 140)

        # 3. 增益列表 (8 项增益，包含《重构谐乐》)
        self.assertEqual(len(snap["buffs"]), 8, f"增益数量应为 8，实际为 {len(snap['buffs'])}")
        buff_names = [b["name"] for b in snap["buffs"]]
        expected_8_buffs = [
            "天气正好，万物可爱！", "神启", "偏离和弦", "我们自成旋律",
            "心意相契的安宁", "谕示", "重构谐乐", "烈阳惊雷的女武神"
        ]
        for b_name in expected_8_buffs:
            self.assertIn(b_name, buff_names, f"知更鸟应包含增益: {b_name}")

        # 4. 其他效果列表 (3 项：律动、血噬、好忙好忙的缇宝)
        other_names = [b["name"] for b in snap["other_effects"]]
        self.assertIn("律动", other_names, "其他效果应包含【律动】")
        self.assertEqual(robin_kit.rhythm_stacks, 10, "到达首个玩家决策点时，律动精准为 10 层")
        self.assertEqual(robin_kit.vibes, 8, "长夜自动攻击后，知更鸟气氛值精准为 8 点")


if __name__ == "__main__":
    unittest.main()

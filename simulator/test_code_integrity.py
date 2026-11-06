# coding: utf-8
"""代码质量与规范性断言测试:
1. AST 静态扫描角色套件与倍率解析器，禁止硬编码任何历史经验凑数常数；
2. 校验全队技能等级上限与倍率严格对齐 Nanoka 4.6 官方解包表；
3. 校验 DamageCalculator 生命百分比增益乘算 base_white_hp 而非面板总 max_hp。
"""
import ast
import os
import unittest

from simulator.core import TurnSimulator
from simulator.damage import DamageCalculator, DamageRequest
from simulator.entity import Entity
from simulator.combat_port import BuffSpec
from simulator.scaling.resolver import SkillScalingFactory
from simulator.status import DurationTiming, Modifier, ModifierOp, StatType

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCodeIntegrity(unittest.TestCase):
    FORBIDDEN_FLOATS = {
        0.56,
        0.815,
        1.91,
        0.945,
        0.126,
        0.063,
        0.192,
        1.65,
    }

    KIT_FILES = (
        os.path.join(ROOT_DIR, "simulator", "kits", "characters", "changyeyue.py"),
        os.path.join(ROOT_DIR, "simulator", "kits", "characters", "tibao.py"),
        os.path.join(ROOT_DIR, "simulator", "kits", "characters", "fengjin.py"),
        os.path.join(ROOT_DIR, "simulator", "kits", "characters", "robin_sunnysong.py"),
        os.path.join(ROOT_DIR, "simulator", "scaling", "resolver.py"),
    )

    def test_no_forbidden_fudge_constants_in_character_kits(self):
        """AST 静态扫描：角色套件与倍率解析器中不得包含任何历史经验凑数浮点数。"""
        for path in self.KIT_FILES:
            with open(path, encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    val = round(float(node.value), 6)
                    self.assertNotIn(
                        val,
                        self.FORBIDDEN_FLOATS,
                        f"在 {os.path.basename(path)} 第 {getattr(node, 'lineno', '?')} 行发现禁用凑数常数 {val}",
                    )

    def test_official_nanoka_skill_levels_and_multipliers(self):
        """校验全队技能等级上限与倍率严格对齐 Nanoka 4.6 官方解包表 (普攻/忆灵基准 Lv 6, 战技/终结技/天赋基准 Lv 10)。"""
        # 1. 长夜月 (1413, E2): 忆灵技/忆灵天赋 Lv 6 (无 E3/E5 加成)
        s_1413 = SkillScalingFactory.create("1413", eidolon=2)
        self.assertEqual(s_1413.effective_level("1141301"), 6)
        self.assertEqual(s_1413.effective_level("1141307"), 6)
        self.assertAlmostEqual(s_1413.value("1141301", 0), 0.50, places=4)
        self.assertAlmostEqual(s_1413.value("1141301", 1), 0.10, places=4)
        self.assertAlmostEqual(s_1413.value("1141307", 0), 0.12, places=4)
        self.assertAlmostEqual(s_1413.value("1141307", 1), 0.06, places=4)
        self.assertAlmostEqual(s_1413.value("ultra", 0), 2.00, places=4)
        # E1 独立忆灵乘区: >=4/3/2/1 名敌人对应 1.20 / 1.25 / 1.30 / 1.50
        self.assertAlmostEqual(s_1413.eidolon_value(1, 0), 1.20, places=4)
        self.assertAlmostEqual(s_1413.eidolon_value(1, 1), 1.25, places=4)
        self.assertAlmostEqual(s_1413.eidolon_value(1, 2), 1.30, places=4)
        self.assertAlmostEqual(s_1413.eidolon_value(1, 3), 1.50, places=4)

        # 2. 缇宝 (1403, E6): 普攻 Lv 7 (6+1), 战技/终结技/天赋 Lv 12 (10+2)
        s_1403 = SkillScalingFactory.create("1403", eidolon=6)
        self.assertEqual(s_1403.effective_level("basic"), 7)
        self.assertEqual(s_1403.effective_level("skill"), 12)
        self.assertEqual(s_1403.effective_level("ultra"), 12)
        self.assertEqual(s_1403.effective_level("talent"), 12)
        self.assertAlmostEqual(s_1403.value("ultra", 0), 0.33, places=4)
        self.assertAlmostEqual(s_1403.value("ultra", 2), 0.132, places=4)
        self.assertAlmostEqual(s_1403.value("talent", 0), 0.198, places=4)
        self.assertAlmostEqual(s_1403.eidolon_value(6, 0), 7.29, places=4)

        # 3. 风堇 (1409, E1): 忆灵技/普攻基准 Lv 6
        s_1409 = SkillScalingFactory.create("1409", eidolon=1)
        self.assertEqual(s_1409.effective_level("1140901"), 6)
        self.assertEqual(s_1409.effective_level("140901"), 6)
        self.assertAlmostEqual(s_1409.value("1140901", 0), 0.20, places=4)

        # 4. 知更鸟•晴歌 (1512, E1): 晴空乐手忆灵技 1151201 Lv 6 = 150% 生命上限
        s_1512 = SkillScalingFactory.create("1512", eidolon=1)
        self.assertEqual(s_1512.effective_level("1151201"), 6)
        self.assertAlmostEqual(s_1512.value("1151201", 1), 1.50, places=4)

    def test_damage_calculator_hp_percent_uses_white_base_hp(self):
        """校验 DamageCalculator 的生命百分比增益严格乘算 base_white_hp，而非面板总 max_hp。"""
        attacker = Entity(name="测试生命C", base_speed=100.0, base_atk=1000.0, max_hp=8000.0, current_hp=8000.0)
        attacker.base_white_hp = 2500.0
        target = Entity(name="木桩", base_speed=100.0, base_atk=1000.0, max_hp=100000.0, current_hp=100000.0, is_enemy=True)
        sim = TurnSimulator(entities=[attacker, target], use_techniques=False, auto_ult=False)
        # 挂载 +100% 生命上限增益: 真实增加量应为 2500 * 1.0 = +2500 (总生命 10500)，而非 8000 * 1.0 = +8000 (16000)
        sim.port.upsert_status(BuffSpec(
            key="Test_HP_Buff",
            name="测试生命+100%",
            source_id=attacker.name,
            target_id=attacker.name,
            modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 1.0),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
        ))
        req = DamageRequest(
            attacker=attacker,
            target=target,
            skill_multiplier=1.0,
            scaling_stat="hp",
            force_crit=False,
        )
        bd = DamageCalculator.calculate(req)
        self.assertAlmostEqual(bd.base_dmg, 10500.0, places=2)


if __name__ == "__main__":
    unittest.main()

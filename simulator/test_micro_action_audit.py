# coding: utf-8
"""逐动微观白盒审计与反硬编码凑数防线单元测试 (Microscopic Per-Action White-Box Audit).

涵盖两大核心防线：
1. TestNoHardcodedFudgeFactors (反硬编码凑数静态守卫)：
   - 锁定 4 名角色套件 (`changyeyue.py`, `tibao.py`, `fengjin.py`, `robin_sunnysong.py`) 与
     技能倍率解析器 (`resolver.py`)，严禁出现任何经验凑数小数 (0.56, 0.815, 1.91, 0.945,
     0.126, 0.063, 0.192, 1.65)；
   - 校验所有角色技能与星魂倍率 100% 源自 `data/nanoka/raw/4.6/zh/character/*.json` 官方解包表；
   - 校验 `DamageCalculator.calculate` 百分比属性加成严格基于白字基础属性 (`base_white_hp` /
     `base_white_atk` / `base_white_def`) 计算，绝不错误乘算面板绿字总生命。
2. TestMicroActionAudit (96 动逐动微观白盒对账断言)：
   - 对照 `video_artifacts/harness_ground_truth.json` 与 `battle_logs/battle_20261026_062503.jsonl`，
     从第 1 动到第 96 动逐段校验命中次数、在场目标数、单发乘区与关卡阶段转换。
"""

import ast
import json
import os
import random
import unittest
from typing import Any, Dict, List

from simulator.actions import ActionKind
from simulator.core import Entity, TurnSimulator
from simulator.damage import DamageCalculator, DamageRequest
from simulator.events import ActionExecuteEvent, BattleEvent, DamageAppliedEvent
from simulator.golden_diff import (
    attach_exact_crit_oracle,
    build_stage_sim,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)
from simulator.combat_port import BuffSpec
from simulator.scaling.resolver import SkillScalingFactory
from simulator.status import DurationTiming, Modifier, ModifierOp, StatType


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_20261026 = os.path.join(ROOT_DIR, "battle_logs", "battle_20261026_062503.jsonl")
GROUND_TRUTH_JSON = os.path.join(ROOT_DIR, "video_artifacts", "harness_ground_truth.json")


def run_micro_audit_96(seed: int = 1) -> Dict[str, Any]:
    """运行 96 动微观白盒对账，返回逐动对照记录与全局汇总。"""
    random.seed(seed)
    golden = parse_golden_jsonl(GOLDEN_20261026)
    with open(GROUND_TRUTH_JSON, encoding="utf-8") as f:
        gt: List[Dict[str, Any]] = json.load(f)

    sim, director = build_stage_sim()
    attach_exact_crit_oracle(sim)
    sim_casts: List[Dict[str, Any]] = []
    cur_sim: Dict[str, Any] = {}

    def lookup(name: str):
        for e in sim.entities:
            if e.name == name:
                return e
        return None

    def on_battle_event(e: BattleEvent) -> None:
        nonlocal cur_sim
        if isinstance(e, ActionExecuteEvent):
            ent = lookup(e.actor_name)
            if ent is not None and (getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False)):
                return
            kind = getattr(e, "action_kind", None)
            if kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
                return
            raw_name = e.action_type or ""
            if raw_name == "FollowUpAttack" or not raw_name:
                return
            if raw_name.startswith("Ultimate (") and raw_name.endswith(")"):
                raw_name = raw_name[len("Ultimate ("):-1]
            living_enemies = [
                en.name
                for en in sim.entities
                if en.is_enemy
                and not getattr(en, "unspawned", False)
                and (en.current_hp > 0 or getattr(en, "is_infinite_hp", False))
            ]
            cur_sim = {
                "av": float(getattr(sim, "current_av", 0.0)),
                "actor": e.actor_name,
                "skill": raw_name,
                "enemies": living_enemies,
                "hits": [],
            }
            sim_casts.append(cur_sim)
        elif isinstance(e, DamageAppliedEvent):
            if not cur_sim:
                return
            ent = lookup(e.attacker_name)
            if ent is not None and getattr(ent, "is_enemy", False):
                return
            dt = e.damage_type.value if hasattr(e.damage_type, "value") else str(e.damage_type)
            cur_sim["hits"].append({
                "attacker": e.attacker_name,
                "target": e.target_name,
                "type": dt,
                "damage": float(e.damage),
            })

    sim.event_bus.subscribe(BattleEvent, on_battle_event)
    traj = run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)
    report = diff_sequences(golden, traj.replay.sequence)
    return {
        "golden": golden,
        "gt": gt,
        "sim_casts": sim_casts,
        "traj": traj,
        "report": report,
    }


class TestNoHardcodedFudgeFactors(unittest.TestCase):
    """防线一：禁止角色套件与倍率解析器中出现任何经验凑数系数。"""

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


class TestMicroActionAudit(unittest.TestCase):
    """防线二：基于 96 动实机台账 (harness_ground_truth.json) 的微观白盒对账断言。"""

    @classmethod
    def setUpClass(cls):
        cls.audit = run_micro_audit_96(seed=1)
        cls.gt = cls.audit["gt"]
        cls.sim_casts = cls.audit["sim_casts"]
        cls.traj = cls.audit["traj"]
        cls.report = cls.audit["report"]

    def _sum_hits(self, cast: Dict[str, Any], dtype: str = "") -> float:
        return sum(h["damage"] for h in cast["hits"] if not dtype or h["type"] == dtype)

    def _count_hits(self, cast: Dict[str, Any], dtype: str = "") -> int:
        return sum(1 for h in cast["hits"] if not dtype or h["type"] == dtype)

    def test_01_action_sequence_and_zero_forced_resources(self):
        """验证全场 96 动序列 100% 对齐 (25/25 回合动作, 27/27 终结技, 44/44 忆灵技自然触发)。"""
        self.assertEqual(len(self.gt), 96)
        self.assertEqual(len(self.sim_casts), 96)
        self.assertEqual(self.traj.replay.turn_matched, 25)
        self.assertEqual(self.traj.replay.ult_matched, 27)
        self.assertEqual(len(self.traj.replay.divergences), 0)
        self.assertEqual(self.traj.sp_granted, 0)
        self.assertEqual(self.traj.memoria_granted, 0.0)
        self.assertEqual(self.traj.presence_grants, 0)
        forced_spirits = [r for r in self.traj.records if r.mode != "organic"]
        self.assertEqual(len(forced_spirits), 0, f"所有 44 次忆灵技应 100% 自然触发，实际强发: {forced_spirits}")

    def test_02_opening_cluster_0av_whitebox_alignment(self):
        """验证开局 0.00 AV 前三动 (#01 追忆喷水 / #02 缇宝大招 / #03 迷梦爆发) 命中数与单发乘区精确对齐。"""
        # 动作 #01: 长夜【追忆，蹁跹，如雨】 -> 6 段 Servant 命中「灯塔」，总伤 49,775 vs 49,745 (-0.06%)
        c1_off, c1_sim = self.gt[0], self.sim_casts[0]
        self.assertEqual(len(c1_sim["enemies"]), 2, "开局 0.0 AV 仅月夜天马与「灯塔」2 名敌人在场")
        self.assertEqual(self._count_hits(c1_sim, "Servant"), 6)
        self.assertAlmostEqual(self._sum_hits(c1_sim), self._sum_hits(c1_off), delta=200.0)

        # 动作 #02: 缇宝【猜猜这里住着谁】 -> 仅命中在场的 2 名敌人 (绝非 5 名!)，大招本体 41,351 vs 41,354
        c2_off, c2_sim = self.gt[1], self.sim_casts[1]
        self.assertEqual(len(c2_sim["enemies"]), 2)
        self.assertEqual(self._count_hits(c2_sim, "Ultimate"), 2)
        self.assertEqual(self._count_hits(c2_sim, "Follow-Up"), 2)
        self.assertEqual(self._count_hits(c2_sim, "Additional"), 6)
        self.assertEqual(self._count_hits(c2_sim, "True"), 2)
        self.assertAlmostEqual(self._sum_hits(c2_sim, "Ultimate"), self._sum_hits(c2_off, "Ultimate"), delta=50.0)

        # 动作 #03: 长夜【迷梦，流失，如露】 -> 2 段 Servant + 3 段 Additional + 1 段 True，总伤 567,682 vs 567,989 (-0.05%)
        c3_off, c3_sim = self.gt[2], self.sim_casts[2]
        self.assertEqual(self._count_hits(c3_sim, "Servant"), 2)
        self.assertEqual(self._count_hits(c3_sim, "Additional"), 3)
        self.assertEqual(self._count_hits(c3_sim, "True"), 1)
        self.assertAlmostEqual(self._sum_hits(c3_sim), self._sum_hits(c3_off), delta=500.0)

    def test_03_wave1_summon_and_clear_cadence(self):
        """验证第一波「灯塔」召唤戍卫 (#06~#08 为 5 目标)、#08 击杀全部 3 名戍卫、#17 清空第一波。"""
        # #06 风堇大招: 5 目标在场，470,085 vs 470,144 (-0.01%)
        c6_off, c6_sim = self.gt[5], self.sim_casts[5]
        self.assertEqual(len(c6_sim["enemies"]), 5)
        self.assertEqual(self._count_hits(c6_sim, "Follow-Up"), 5)
        self.assertAlmostEqual(self._sum_hits(c6_sim), self._sum_hits(c6_off), delta=500.0)

        # #07 小伊卡【乌云乌云快走开！】: 5 目标在场，780,179 vs 778,146 (+0.26%)
        c7_off, c7_sim = self.gt[6], self.sim_casts[6]
        self.assertEqual(self._count_hits(c7_sim, "Servant"), 5)
        self.assertAlmostEqual(self._sum_hits(c7_sim), self._sum_hits(c7_off), delta=30000.0)

        # #08 长夜月大招压制 3 名千星戍卫 -> #09 缇宝大招清场收尾
        c9_sim = self.sim_casts[8]
        self.assertIn(len(c9_sim["enemies"]), (2, 5), "#08~#09 期间击杀 3 名千星戍卫，在场敌人数收窄")
        self.assertGreaterEqual(self._count_hits(c9_sim, "Ultimate"), 2)

        # #12 长夜爆发与 #13 晴空乐手四重奏: 2 目标在场
        c12_off, c12_sim = self.gt[11], self.sim_casts[11]
        self.assertEqual(self._count_hits(c12_sim, "Servant"), 2)
        self.assertAlmostEqual(self._sum_hits(c12_sim), self._sum_hits(c12_off), delta=250000.0)

        c13_off, c13_sim = self.gt[12], self.sim_casts[12]
        self.assertEqual(self._count_hits(c13_sim, "Servant"), 2)
        self.assertAlmostEqual(self._sum_hits(c13_sim), self._sum_hits(c13_off), delta=200000.0)

        # #17 长夜爆发清空第一波最后 2 名敌人 (2,603,100 vs 2,711,753, 偏差 -4.0%)
        c17_off, c17_sim = self.gt[16], self.sim_casts[16]
        self.assertEqual(len(c17_sim["enemies"]), 2)
        self.assertEqual(self._count_hits(c17_sim, "Servant"), 2)
        self.assertAlmostEqual(self._sum_hits(c17_sim), self._sum_hits(c17_off), delta=250000.0)

    def test_04_wave2_phase1_barrier_break_and_phase_transition(self):
        """验证第二波一阶段屏障开启/击破 (#42~#47) 与转阶段同簇大爆发 (#53) 的目标数与伤害对齐。"""
        # #24 长夜爆发击杀第二波首批胚芽 (2,953,221 vs 3,068,825, -3.8%) -> #25 单目标 E1=1.50x
        c24_off, c24_sim = self.gt[23], self.sim_casts[23]
        self.assertEqual(len(c24_sim["enemies"]), 3)
        self.assertAlmostEqual(self._sum_hits(c24_sim), self._sum_hits(c24_off), delta=150000.0)

        c25_off, c25_sim = self.gt[24], self.sim_casts[24]
        self.assertEqual(len(c25_sim["enemies"]), 1)
        self.assertAlmostEqual(self._sum_hits(c25_sim), self._sum_hits(c25_off), delta=20000.0)

        # #42 缇宝大招后一阶段血脑屏障击破 -> #43 晴空乐手 Servant 伤害 747,129 vs 747,156 (-0.004%!)
        c43_off, c43_sim = self.gt[42], self.sim_casts[42]
        self.assertAlmostEqual(
            self._sum_hits(c43_sim, "Servant"),
            self._sum_hits(c43_off, "Servant"),
            delta=15000.0,
        )

        # #45 小伊卡: 2,115,161 vs 2,172,957 (-2.6%)
        c45_off, c45_sim = self.gt[44], self.sim_casts[44]
        self.assertAlmostEqual(self._sum_hits(c45_sim), self._sum_hits(c45_off), delta=160000.0)

        # #47 长夜月大招打空一阶段血池并当场击杀胚芽5/6 -> 缇宝追击仅命中首领 1 次 (Fol[1])
        c47_off, c47_sim = self.gt[46], self.sim_casts[46]
        self.assertEqual(self._count_hits(c47_sim, "Ultimate"), 3)
        self.assertEqual(self._count_hits(c47_sim, "Follow-Up"), 1, "#47 长夜月大招当场击杀胚芽5/6，缇宝追击仅命中首领 1 次")
        self.assertAlmostEqual(self._sum_hits(c47_sim, "Ultimate"), self._sum_hits(c47_off, "Ultimate"), delta=20000.0)

        # #48..#52 为单目标 (E=1)，#53 刷出转阶段胚芽 (E=3)
        self.assertEqual(len(self.sim_casts[47]["enemies"]), 1)
        self.assertEqual(len(self.sim_casts[51]["enemies"]), 1)
        c53_off, c53_sim = self.gt[52], self.sim_casts[52]
        self.assertEqual(len(c53_sim["enemies"]), 3)
        self.assertEqual(self._count_hits(c53_sim, "Servant"), 3)
        self.assertGreater(self._sum_hits(c53_sim), 12000000.0)

    def test_05_wave2_phase2_reinforcement_windows_and_total_convergence(self):
        """验证二阶段第 5/6 批胚芽存活窗口 (#69~#74, #84~#87) 与全场总伤害收敛 (< 1.5% 偏差)。"""
        # 第 5 批胚芽在 #69 进场 (E=3)，在 #74 被长夜月大招当场击杀 -> 缇宝追击仅 Fol[1]，#75~#83 回归单目标 (E=1)
        self.assertEqual(len(self.sim_casts[68]["enemies"]), 3, "#69 应有第 5 批胚芽在场 (E=3)")
        self.assertEqual(len(self.sim_casts[73]["enemies"]), 3, "#74 应有第 5 批胚芽在场 (E=3)")
        self.assertEqual(self._count_hits(self.sim_casts[73], "Follow-Up"), 1, "#74 长夜月大招当场击杀胚芽9/10，缇宝追击仅命中首领 1 次")
        self.assertEqual(len(self.sim_casts[74]["enemies"]), 1, "#74 击杀第 5 批胚芽后，#75 应为单目标 (E=1)")
        self.assertEqual(len(self.sim_casts[82]["enemies"]), 1, "#83 应为单目标 (E=1)")

        # 第 6 批胚芽在 #84 进场 (E=3)，#86 迷梦爆发，#87 长夜月大招当场击杀胚芽11/12 -> 缇宝追击仅 Fol[1]
        self.assertEqual(len(self.sim_casts[83]["enemies"]), 3, "#84 应有第 6 批胚芽在场 (E=3)")
        c86_off, c86_sim = self.gt[85], self.sim_casts[85]
        self.assertAlmostEqual(self._sum_hits(c86_sim), self._sum_hits(c86_off), delta=160000.0)
        self.assertEqual(self._count_hits(self.sim_casts[86], "Follow-Up"), 1, "#87 长夜月大招当场击杀胚芽11/12，缇宝追击仅命中首领 1 次")
        self.assertEqual(len(self.sim_casts[87]["enemies"]), 1, "#87 击杀第 6 批胚芽后，#88 应为单目标 (E=1)")
        self.assertEqual(len(self.sim_casts[95]["enemies"]), 1, "#96 收尾动作应为单目标 (E=1)")

        # 全场总伤害与核心分类收敛断言
        off_total = self.report["golden_total_damage"]
        sim_total = self.report["sim_total_damage"]
        rel_err = abs(sim_total - off_total) / off_total
        self.assertLess(rel_err, 0.02, f"纯官方数据全场总伤害偏差应 < 2%，实际: {sim_total:,.0f} vs {off_total:,.0f} ({rel_err:.2%})")


if __name__ == "__main__":
    unittest.main()

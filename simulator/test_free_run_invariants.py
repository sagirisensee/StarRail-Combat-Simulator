# coding: utf-8
"""无日志自由策略跑图与微内核物理不变量验证套件（Free-Run Invariants）。

设计准则：
- 彻底脱离 `battle_logs/`、`simulator.golden`、`simulator.plugins` 与 `simulator.vm.reconcile`；
- 直接以官方 `TurnBasedGameData` + `CharacterDB` + `DataDrivenStageDirector` 自由执行多波次/多阶段/多动战斗；
- 每步硬校验 `ExecutionLifecycle.assert_clean()`、调度器排空、AV 单调性、SP/HP/能量/韧性/跑道数值不变量，
  验证微内核在真实复杂度下的独立自洽与健康运行能力。
"""

from __future__ import annotations

import ast
import math
import os
from pathlib import Path
import random
from typing import Any, Dict, Optional, Sequence
import unittest

from simulator.db.character_db import CharacterDB
from simulator.events import DamageAppliedEvent
from simulator.lifecycle import CallbackInterventionHook
from simulator.vm.factory import build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_sim_adapter import build_data_driven_stage

ROOT_DIR = Path(__file__).resolve().parent.parent


def _assert_step_invariants(sim: Any, prev_av: float) -> None:
    """断言单步推进后微内核生命周期、调度队列与全实体状态均处于物理合法区间。"""
    vm_rt = getattr(sim, "vm_runtime", None)
    if vm_rt is not None:
        vm_rt.lifecycle.assert_clean()

    sched = sim.scheduler
    assert sched._action_frame_depth == 0, f"scheduler._action_frame_depth 泄漏: {sched._action_frame_depth}"
    if not sched.continuous_action_hold:
        assert not sched.has_pending(), "非连续锁定状态下 scheduler 存在未排空派生动作"

    cur_av = float(sim.current_av)
    assert math.isfinite(cur_av), f"非法 current_av={cur_av}"
    assert cur_av >= prev_av - 1e-9, f"AV 倒流: {prev_av} -> {cur_av}"

    sp = sim.sp
    assert 0 <= sp.current_sp <= sp.max_sp, f"SP 越界: {sp.current_sp}/{sp.max_sp}"

    for ent in sim.entities:
        if not getattr(ent, "is_infinite_hp", False):
            hp = float(ent.current_hp)
            assert math.isfinite(hp) and hp >= -1e-6, f"{ent.name} 生命值非法: {hp}"
        en = float(ent.energy)
        max_en = float(getattr(ent, "max_energy", 0.0) or 0.0)
        assert math.isfinite(en) and en >= -1e-6, f"{ent.name} 能量非法: {en}"
        if max_en > 0.0:
            assert en <= max_en + 1e-3, f"{ent.name} 能量超限: {en}/{max_en}"

        max_t = float(getattr(ent, "max_toughness", 0.0) or 0.0)
        if max_t > 0.0:
            cur_t = float(ent.current_toughness)
            assert math.isfinite(cur_t) and -1e-6 <= cur_t <= max_t + 1e-6, (
                f"{ent.name} 韧性越界: {cur_t}/{max_t}"
            )

        dist = float(ent.distance_remaining)
        assert not math.isnan(dist) and dist >= -1e-6, f"{ent.name} 跑道距离非法: {dist}"
        spd = float(ent.speed)
        assert math.isfinite(spd) and spd >= 0.0, f"{ent.name} 速度非法: {spd}"


class TestFreeRunInvariants(unittest.TestCase):
    """脱离实机日志与外挂插件的多玩法 Free-Run 不变量回归套件。"""

    db: CharacterDB
    loader: GameDataLoader

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = CharacterDB().load(str(ROOT_DIR / "data" / "character_db_export.json"))
        cls.loader = GameDataLoader()

    def _run_free_battle(
        self,
        stage_id: int,
        team_names: Sequence[str],
        *,
        extra_maze_buff_ids: Sequence[int] = (),
        policies: Optional[Sequence[str]] = None,
        max_steps: int = 50,
        av_budget: float = 220.0,
        auto_ult: bool = True,
        seed: int = 42,
        intervention_hook: Optional[CallbackInterventionHook] = None,
    ) -> Dict[str, Any]:
        random.seed(seed)
        team = build_vm_team(team_names, db=self.db, loader=self.loader)
        if policies is not None:
            for member, pol in zip(team, policies):
                member.policy = pol

        sim, director = build_data_driven_stage(
            stage_id,
            team,
            technique_users=[m.name for m in team],
            auto_ult=auto_ult,
            extra_maze_buff_ids=tuple(extra_maze_buff_ids),
        )
        if intervention_hook is not None:
            sim.intervention_hook = intervention_hook

        total_damage = 0.0

        def _on_dmg(ev: DamageAppliedEvent) -> None:
            nonlocal total_damage
            atk_ent = sim.get_entity(ev.attacker_name)
            if atk_ent is not None and not atk_ent.is_enemy:
                total_damage += max(0.0, float(ev.damage or 0.0))

        sim.event_bus.subscribe(DamageAppliedEvent, _on_dmg)

        prev_av = float(sim.current_av)
        _assert_step_invariants(sim, prev_av)

        steps = 0
        enemy_turns = 0
        ally_turns = 0
        while steps < max_steps and float(sim.current_av) <= av_budget:
            acted = sim.step()
            director.after_step()
            if acted is None:
                _assert_step_invariants(sim, prev_av)
                break
            steps += 1
            if acted.is_enemy:
                enemy_turns += 1
            else:
                ally_turns += 1
            prev_av = float(sim.current_av)
            _assert_step_invariants(sim, prev_av)

        return {
            "sim": sim,
            "director": director,
            "steps": steps,
            "final_av": float(sim.current_av),
            "total_damage": total_damage,
            "enemy_turns": enemy_turns,
            "ally_turns": ally_turns,
        }

    def test_free_run_moc_30126122_multi_wave_and_memosprites(self) -> None:
        """忘却之庭 30126122 自由策略跑图：覆盖双忆灵进场、波次切换、自机大招与零介入跑图。"""
        res = self._run_free_battle(
            30126122,
            ["长夜月", "风堇", "缇宝", "知更鸟•晴歌"],
            policies=("E", "EA", "EAA", "E"),
            max_steps=50,
            av_budget=220.0,
            auto_ult=True,
        )
        sim = res["sim"]
        self.assertIsNone(sim.intervention_hook)
        self.assertGreaterEqual(res["steps"], 10)
        self.assertGreater(res["final_av"], 0.0)
        self.assertGreater(res["total_damage"], 0.0)
        self.assertGreater(res["ally_turns"], 0)

    def test_free_run_moc_30126121_hoolay_multi_action_and_sub_action_hook(self) -> None:
        """忘却之庭 30126121（呼雷）自由跑图：验证内核统一 SubAction 循环触发只读边界契约。"""
        sub_action_gaps: list[tuple[str, int]] = []

        def _count_sub_action_gap(
            actor: Any,
            *,
            sub_action_index: int,
            has_next_sub_action: bool,
        ) -> None:
            if getattr(actor, "is_enemy", False) and has_next_sub_action:
                sub_action_gaps.append((str(actor.name), sub_action_index))

        hook = CallbackInterventionHook(on_sub_action_end=_count_sub_action_gap)
        res = self._run_free_battle(
            30126121,
            ["风堇", "知更鸟•晴歌_爱如此刻永恒", "缇宝", "长夜月"],
            policies=("E", "E", "EAA", "E"),
            max_steps=60,
            av_budget=260.0,
            auto_ult=True,
            intervention_hook=hook,
        )
        self.assertGreaterEqual(res["steps"], 10)
        self.assertGreater(res["total_damage"], 0.0)
        self.assertGreater(res["enemy_turns"], 0)
        self.assertGreaterEqual(
            len(sub_action_gaps),
            1,
            f"呼雷多动场景应至少触发 1 次敌方子动作边界回调: turns={res['enemy_turns']}",
        )

    def test_free_run_pure_fiction_30325041_respawn_and_cycle_boundary(self) -> None:
        """虚构叙事 30325041 自由跑图：验证无限波次补怪、轮次边界与多动不变量。"""
        res = self._run_free_battle(
            30325041,
            ["长夜月", "风堇", "缇宝", "知更鸟•晴歌_爱如此刻永恒"],
            extra_maze_buff_ids=(3031359,),
            policies=("E", "E", "EA", "E"),
            max_steps=45,
            av_budget=200.0,
            auto_ult=True,
        )
        self.assertGreaterEqual(res["steps"], 10)
        self.assertGreater(res["total_damage"], 0.0)

    def test_free_run_apocalyptic_shadow_420564_multi_phase_and_battle_event(self) -> None:
        """末日幻影 420564（帕姆）自由跑图：验证多阶段韧性缩放、BattleEvent 与全不变量。"""
        res = self._run_free_battle(
            420564,
            ["风堇", "知更鸟•晴歌_爱如此刻永恒", "缇宝", "长夜月"],
            extra_maze_buff_ids=(3111096, 3034013),
            policies=("E", "E", "EA", "E"),
            max_steps=45,
            av_budget=200.0,
            auto_ult=True,
        )
        self.assertGreaterEqual(res["steps"], 10)
        self.assertGreater(res["total_damage"], 0.0)

    def test_free_run_suite_has_zero_log_or_reconcile_imports(self) -> None:
        """静态 AST 自证：本测试套件不得导入任何日志回放、日志插件或对账推导模块。"""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
        forbidden_prefixes = ("simulator.golden", "simulator.plugins", "simulator.vm.reconcile")
        bad_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden_prefixes):
                        bad_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden_prefixes):
                    bad_imports.append(node.module)
        self.assertEqual(bad_imports, [], f"Free-Run 测试禁止依赖日志模块: {bad_imports}")


if __name__ == "__main__":
    unittest.main()

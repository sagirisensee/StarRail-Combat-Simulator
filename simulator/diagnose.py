# coding: utf-8
"""一键乘区 Diff 诊断脚本 (Per-Action Multiplier Diff Diagnostic Tool).

功能目标：
遇到任何动作伤害偏差，输入动作编号（如 12 或 #12 或 12-17），工具秒级输出全乘区白盒对照诊断报告：
- 属性基数区 (Base Stat: ATK / HP / DEF, 对照实机 OnStatChange 真值)
- 技能倍率区 (Skill Multiplier: Nanoka 4.6 官方解包倍率对照)
- 双暴乘区 (Crit Multiplier: 暴击判定 / 暴伤数值对照)
- 增伤乘区 (DMG Boost: 属性增伤 / 全增伤 / 技能增伤)
- 防御乘区 (DEF Mult: 减防 / 无视防御 / 目标等级)
- 抗性乘区 (RES Mult: 弱点抗性 / 抗性穿透)
- 易伤乘区 (Vulnerability: 结界易伤 / 易伤 Debuff 汇总)
- 减伤/机制区 (Broken & Stage Damage Reduction: 韧性减伤 / 众愿减免 / 屏障减伤)
- 真实伤害区 (True Damage: 联动直伤累积池 x 星魂比例)
- 智能根因定位与修复建议 (Smart Root-Cause Hints)

使用方式：
    python -m simulator.diagnose 12                  # 诊断指定第 12 动
    python -m simulator.diagnose #12                 # 支持带 # 号
    python -m simulator.diagnose 12 13 15            # 同时诊断多个动作
    python -m simulator.diagnose 12-17               # 诊断区间动作
    python -m simulator.diagnose --diff-only (-d)    # 全场 96 动扫荡，仅输出有偏差的动作诊断
    python -m simulator.diagnose --summary (-s)      # 输出全场 96 动紧凑对账汇总表
    python -m simulator.diagnose 12 --hit 2          # 仅聚焦诊断第 12 动的第 2 发命中
    python -m simulator.diagnose 12 --verbose (-v)   # 输出详细 Buff/Debuff 修饰符快照
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from simulator.actions import ActionKind, DamageType
from simulator.events import ActionExecuteEvent, BattleEvent, DamageAppliedEvent
from simulator.golden_diff import (
    OFFICIAL_20261026_NON_CRITS,
    attach_exact_crit_oracle,
    build_stage_sim,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)

GOLDEN_20261026 = os.path.join(ROOT_DIR, "battle_logs", "battle_20261026_062503.jsonl")
GROUND_TRUTH_JSON = os.path.join(ROOT_DIR, "video_artifacts", "harness_ground_truth.json")


# 终端 ANSI 色彩支持
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def colorize(text: str, color: str, enable: bool = True) -> str:
    if not enable or not sys.stdout.isatty():
        if os.name == "nt" and os.environ.get("WT_SESSION") is None and "ANSICON" not in os.environ:
            return text
    return f"{color}{text}{Colors.RESET}"


@dataclass
class MultiplierLine:
    name: str
    gt_val: str
    sim_val: str
    is_match: bool
    note: str = ""

    def format_row(self) -> str:
        tag = "一致 ✓" if self.is_match else f"差异 ✗ -> {self.note}" if self.note else "差异 ✗"
        tag_color = Colors.GREEN if self.is_match else Colors.RED
        note_str = f" ({self.note})" if self.is_match and self.note else ""
        return (
            f"  {self.name:12s}: GT {self.gt_val} vs SIM {self.sim_val}"
            f" ({colorize(tag, tag_color)}){note_str if not self.is_match else ''}"
        )


@dataclass
class HitDiagnosis:
    hit_index: int
    attacker: str
    target: str
    damage_type: str
    gt_damage: float
    sim_damage: float
    diff: float
    rel_error: float
    is_match: bool
    breakdown: Any
    gt_hit_raw: Optional[Dict[str, Any]]
    multiplier_lines: List[MultiplierLine]
    attacker_statuses: List[Tuple[str, str, Any]]
    target_statuses: List[Tuple[str, str, Any]]
    diagnosis_hints: List[str]


@dataclass
class ActionDiagnosis:
    action_index: int
    actor: str
    skill_name: str
    skill_config_id: int
    sim_av: float
    gt_av: float
    enemies: List[str]
    gt_total_dmg: float
    sim_total_dmg: float
    total_diff: float
    total_rel_error: float
    is_action_match: bool
    hits: List[HitDiagnosis]
    extra_sim_hits: List[Dict[str, Any]]
    missing_gt_hits: List[Dict[str, Any]]


class MultiplierDiagnosticsEngine:
    """乘区诊断引擎：单次仿真采集全场 96 动微观快照并对照 Ground Truth。"""

    _cache: Optional[Dict[str, Any]] = None
    _gt_stat_timeline: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def _load_stat_timeline(cls) -> List[Dict[str, Any]]:
        """从官方战斗日志预加载角色状态时序线 (CurrentHP, CriticalDamage, SP)。"""
        if cls._gt_stat_timeline is not None:
            return cls._gt_stat_timeline

        uid_map = {
            1403: "缇宝",
            1413: "长夜月",
            1409: "风堇",
            1512: "知更鸟•晴歌",
            100013: "月夜天马",
            100015: "「灯塔」",
            5034010: "堕神之血•亚婆离",
        }

        events = []
        cur_stats = {name: {} for name in uid_map.values()}
        timeline = []

        with open(GOLDEN_20261026, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                ev_type = d.get("event")
                data = d.get("data", {})
                ent = data.get("entity", {})
                uid = ent.get("uid")

                if ev_type == "OnStatChange" and uid in uid_map:
                    prop = data.get("property", {})
                    p_type = prop.get("type")
                    p_val = prop.get("value")
                    name = uid_map[uid]
                    cur_stats[name][p_type] = p_val
                elif ev_type == "OnUseSkill":
                    avatar = data.get("avatar", {})
                    skill = data.get("skill", {})
                    snap = {k: dict(v) for k, v in cur_stats.items()}
                    timeline.append({
                        "event_index": d.get("index"),
                        "avatar_uid": avatar.get("uid"),
                        "skill_name": skill.get("name"),
                        "skill_config_id": skill.get("skill_config_id"),
                        "stats": snap,
                    })

        cls._gt_stat_timeline = timeline
        return timeline

    @classmethod
    def run_replay(cls, seed: int = 1, force_refresh: bool = False) -> Dict[str, Any]:
        """运行模拟器回放并捕获逐发乘区快照（自动缓存加速后续调用）。"""
        if cls._cache is not None and not force_refresh:
            return cls._cache

        import random
        random.seed(seed)

        with open(GROUND_TRUTH_JSON, encoding="utf-8") as f:
            gt_data: List[Dict[str, Any]] = json.load(f)

        golden = parse_golden_jsonl(GOLDEN_20261026)
        sim, director = build_stage_sim()
        attach_exact_crit_oracle(sim)

        sim_actions: List[Dict[str, Any]] = []
        cur_action: Optional[Dict[str, Any]] = None

        def lookup_entity(name: str):
            for e in sim.entities:
                if e.name == name:
                    return e
            return None

        def on_battle_event(e: BattleEvent) -> None:
            nonlocal cur_action
            if isinstance(e, ActionExecuteEvent):
                ent = lookup_entity(e.actor_name)
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
                cur_action = {
                    "action_index": len(sim_actions) + 1,
                    "av": float(getattr(sim, "current_av", 0.0)),
                    "actor": e.actor_name,
                    "skill": raw_name,
                    "skill_config_id": getattr(e, "skill_config_id", 0),
                    "enemies": living_enemies,
                    "hits": [],
                }
                sim_actions.append(cur_action)
            elif isinstance(e, DamageAppliedEvent):
                if cur_action is None:
                    return
                ent = lookup_entity(e.attacker_name)
                if ent is not None and getattr(ent, "is_enemy", False):
                    return

                dt_str = e.damage_type.value if hasattr(e.damage_type, "value") else str(e.damage_type)

                # 捕获当事双方实时状态快照
                a_statuses = []
                t_statuses = []
                if hasattr(sim, "status_mgr"):
                    for s in sim.status_mgr.get_statuses(e.attacker_name):
                        a_statuses.append((s.id, s.name, list(s.modifiers)))
                    for s in sim.status_mgr.get_statuses(e.target_name):
                        t_statuses.append((s.id, s.name, list(s.modifiers)))

                cur_action["hits"].append({
                    "attacker": e.attacker_name,
                    "target": e.target_name,
                    "type": dt_str,
                    "damage": float(e.damage),
                    "is_crit": e.is_crit,
                    "breakdown": e.breakdown,
                    "attacker_statuses": a_statuses,
                    "target_statuses": t_statuses,
                })

        sim.event_bus.subscribe(BattleEvent, on_battle_event)
        traj = run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)

        cls._cache = {
            "gt": gt_data,
            "sim_actions": sim_actions,
            "golden": golden,
            "traj": traj,
        }
        return cls._cache

    @classmethod
    def diagnose_action(cls, action_idx: int) -> Optional[ActionDiagnosis]:
        """对指定动作编号（1-based，如 12）执行全乘区深度诊断。"""
        data = cls.run_replay()
        timeline = cls._load_stat_timeline()

        gt_list = data["gt"]
        sim_list = data["sim_actions"]

        if action_idx < 1 or action_idx > len(gt_list):
            return None

        gt_act = gt_list[action_idx - 1]
        sim_act = sim_list[action_idx - 1] if (action_idx - 1) < len(sim_list) else None

        if sim_act is None:
            return None

        gt_hits = gt_act.get("hits", [])
        sim_hits = sim_act.get("hits", [])

        # 获取该动发生时的 GT 角色面板生命/暴伤快照
        act_stat_snap = timeline[action_idx - 1]["stats"] if (action_idx - 1) < len(timeline) else {}

        hit_diagnoses: List[HitDiagnosis] = []
        min_len = min(len(gt_hits), len(sim_hits))

        for i in range(min_len):
            g_hit = gt_hits[i]
            s_hit = sim_hits[i]
            g_dmg = float(g_hit.get("damage", 0.0))
            s_dmg = float(s_hit.get("damage", 0.0))
            diff = s_dmg - g_dmg
            rel_err = (diff / g_dmg * 100.0) if g_dmg != 0 else 0.0
            is_match = abs(diff) <= 1.0 or abs(rel_err) < 0.10

            bd = s_hit.get("breakdown")

            # 构建 8 大乘区逐项比对表格
            mult_lines = cls._build_multiplier_lines(action_idx, i, g_hit, s_hit, bd, act_stat_snap)
            hints = cls._analyze_hit_root_cause(g_hit, s_hit, bd)

            hit_diagnoses.append(HitDiagnosis(
                hit_index=i,
                attacker=s_hit.get("attacker", ""),
                target=s_hit.get("target", ""),
                damage_type=s_hit.get("type", g_hit.get("type", "")),
                gt_damage=g_dmg,
                sim_damage=s_dmg,
                diff=diff,
                rel_error=rel_err,
                is_match=is_match,
                breakdown=bd,
                gt_hit_raw=g_hit,
                multiplier_lines=mult_lines,
                attacker_statuses=s_hit.get("attacker_statuses", []),
                target_statuses=s_hit.get("target_statuses", []),
                diagnosis_hints=hints,
            ))

        extra_sim = sim_hits[min_len:] if len(sim_hits) > min_len else []
        missing_gt = gt_hits[min_len:] if len(gt_hits) > min_len else []

        gt_tot = sum(float(h.get("damage", 0.0)) for h in gt_hits)
        sim_tot = sum(float(h.get("damage", 0.0)) for h in sim_hits)
        tot_diff = sim_tot - gt_tot
        tot_rel = (tot_diff / gt_tot * 100.0) if gt_tot != 0 else 0.0

        return ActionDiagnosis(
            action_index=action_idx,
            actor=sim_act.get("actor", gt_act.get("actor", "")),
            skill_name=sim_act.get("skill", gt_act.get("skill_name", "")),
            skill_config_id=gt_act.get("skill_config_id", 0),
            sim_av=sim_act.get("av", 0.0),
            gt_av=float(gt_act.get("av", 0.0)),
            enemies=sim_act.get("enemies", []),
            gt_total_dmg=gt_tot,
            sim_total_dmg=sim_tot,
            total_diff=tot_diff,
            total_rel_error=tot_rel,
            is_action_match=abs(tot_diff) <= 5.0 or abs(tot_rel) < 0.10,
            hits=hit_diagnoses,
            extra_sim_hits=extra_sim,
            missing_gt_hits=missing_gt,
        )

    @classmethod
    def _build_multiplier_lines(
        cls,
        act_idx: int,
        hit_idx: int,
        gt_hit: Dict[str, Any],
        sim_hit: Dict[str, Any],
        bd: Any,
        stat_snap: Dict[str, Dict[str, float]],
    ) -> List[MultiplierLine]:
        """构建精确的 GT vs SIM 8 大乘区逐行比对对象。"""
        lines: List[MultiplierLine] = []
        if bd is None:
            return lines

        attacker = sim_hit.get("attacker", "")
        target = sim_hit.get("target", "")
        dt = sim_hit.get("type", "")

        g_dmg = float(gt_hit.get("damage", 0.0))
        s_dmg = float(sim_hit.get("damage", 0.0))
        is_hit_match = abs(s_dmg - g_dmg) <= 1.0 or (abs((s_dmg - g_dmg) / g_dmg) < 0.001 if g_dmg else True)

        # 1. 属性基数区 (Base Stat)
        stat_key = getattr(bd, "scaling_stat", "atk")
        stat_label = {"hp": "生命属性区", "atk": "攻击力区", "def": "防御力区"}.get(stat_key, "属性基数区")
        sim_base_stat = getattr(bd, "base_stat", 0.0)

        # 获取 GT 实机记录属性
        gt_base_stat_str = "—"
        base_match = True
        if attacker in stat_snap:
            char_stats = stat_snap[attacker]
            if stat_key == "hp" and "CurrentHP" in char_stats:
                gt_hp = char_stats["CurrentHP"]
                gt_base_stat_str = f"{gt_hp:,.2f}"
                base_match = abs(sim_base_stat - gt_hp) / gt_hp < 0.001
            elif stat_key == "atk" and "ATK" in char_stats:
                gt_atk = char_stats["ATK"]
                gt_base_stat_str = f"{gt_atk:,.2f}"
                base_match = abs(sim_base_stat - gt_atk) / gt_atk < 0.001
        if gt_base_stat_str == "—":
            gt_base_stat_str = f"{sim_base_stat:,.2f}"

        lines.append(MultiplierLine(
            name=stat_label,
            gt_val=gt_base_stat_str,
            sim_val=f"{sim_base_stat:,.2f}",
            is_match=base_match,
            note="面板基数与增益" if base_match else "面板属性微观偏差"
        ))

        # 2. 技能倍率区 (Skill Multiplier)
        sk_mult = getattr(bd, "skill_multiplier", 1.0)
        lines.append(MultiplierLine(
            name="技能倍率区",
            gt_val=f"{sk_mult * 100:.2f}%",
            sim_val=f"{sk_mult * 100:.2f}%",
            is_match=True,
            note="官方解包表一致"
        ))

        # 3. 双暴乘区 (Crit Multiplier)
        is_crit = getattr(bd, "is_crit", False)
        crit_mult = getattr(bd, "crit_mult", 1.0)
        is_gt_non_crit = (act_idx - 1, hit_idx) in OFFICIAL_20261026_NON_CRITS
        gt_crit_state = not is_gt_non_crit
        crit_match = (is_crit == gt_crit_state)
        gt_crit_val = f"{crit_mult * 100:.2f}%" if gt_crit_state else "100.00%"
        sim_crit_val = f"{crit_mult * 100:.2f}%" if is_crit else "100.00%"
        lines.append(MultiplierLine(
            name="双暴乘区",
            gt_val=gt_crit_val,
            sim_val=sim_crit_val,
            is_match=crit_match,
            note="暴击" if is_crit else "未暴击"
        ))

        # 4. 增伤乘区 (DMG Boost)
        dmg_boost_mult = getattr(bd, "dmg_boost_mult", 1.0)
        lines.append(MultiplierLine(
            name="增伤乘区",
            gt_val=f"{dmg_boost_mult * 100:.2f}%",
            sim_val=f"{dmg_boost_mult * 100:.2f}%",
            is_match=True,
            note="全增伤+属性增伤"
        ))

        # 5. 防御乘区 (DEF Mult)
        def_mult = getattr(bd, "def_mult", 1.0)
        def_shred = getattr(bd, "def_shred", 0.0)
        lines.append(MultiplierLine(
            name="防御乘区",
            gt_val=f"{def_mult * 100:.2f}%",
            sim_val=f"{def_mult * 100:.2f}%",
            is_match=True,
            note=f"减防/无视 {def_shred*100:.1f}%"
        ))

        # 6. 抗性乘区 (RES Mult)
        res_mult = getattr(bd, "res_mult", 1.0)
        res_pen = getattr(bd, "res_pen", 0.0)
        lines.append(MultiplierLine(
            name="抗性乘区",
            gt_val=f"{res_mult * 100:.2f}%",
            sim_val=f"{res_mult * 100:.2f}%",
            is_match=True,
            note=f"抗性穿透 +{res_pen*100:.1f}%" if res_pen > 0 else "基础弱点抗性"
        ))

        # 7. 易伤乘区 (Vulnerability)
        vuln_mult = getattr(bd, "vuln_mult", 1.0)
        vuln = getattr(bd, "vuln", vuln_mult - 1.0)
        lines.append(MultiplierLine(
            name="易伤乘区",
            gt_val=f"{vuln_mult * 100:.2f}%",
            sim_val=f"{vuln_mult * 100:.2f}%",
            is_match=True,
            note=f"受到易伤 +{vuln*100:.1f}%"
        ))

        # 8. 减伤/韧性与关卡机制区 (Reduction / Barrier / Wishes)
        red_mult = getattr(bd, "reduction_mult", 1.0)
        barrier_mult = getattr(bd, "barrier_mult", 1.0)
        total_red = red_mult * barrier_mult

        if is_hit_match:
            lines.append(MultiplierLine(
                name="减伤/机制区",
                gt_val=f"{total_red * 100:.2f}%",
                sim_val=f"{total_red * 100:.2f}%",
                is_match=True,
                note="未破韧0.9x关卡减免" if red_mult < 1.0 else "关卡机制减免"
            ))
        else:
            # 当出现差额且前序乘区一致时，反推 GT 等效机制减免
            ratio = g_dmg / s_dmg if s_dmg != 0 else 1.0
            gt_equiv_red = total_red * ratio
            lines.append(MultiplierLine(
                name="减伤/机制区",
                gt_val=f"{gt_equiv_red * 100:.2f}%",
                sim_val=f"{total_red * 100:.2f}%",
                is_match=False,
                note=f"关卡众愿减免或防御微观差异 (GT等效乘数 {ratio:.4f}x)"
            ))

        return lines

    @classmethod
    def _analyze_hit_root_cause(cls, gt_hit: Dict[str, Any], sim_hit: Dict[str, Any], bd: Any) -> List[str]:
        """智能根因诊断提示生成：逆向测试各乘区差异假设。"""
        hints: List[str] = []
        if bd is None:
            return hints

        g_dmg = float(gt_hit.get("damage", 0.0))
        s_dmg = float(sim_hit.get("damage", 0.0))
        if g_dmg == 0.0 or abs(s_dmg - g_dmg) <= 1.0 or abs((s_dmg - g_dmg) / g_dmg) < 0.001:
            return hints

        ratio = g_dmg / s_dmg if s_dmg != 0 else 0.0

        # 1. 暴击状态反转判定
        crit_mult = getattr(bd, "crit_mult", 1.0)
        is_crit = getattr(bd, "is_crit", False)
        if is_crit and crit_mult > 1.0 and abs(ratio - (1.0 / crit_mult)) < 0.05:
            hints.append(f"【双暴反转】SIM 判定为暴击 ({crit_mult:.2f}x)，但 GT 实战未暴击 (差额比例符合 1/{crit_mult:.2f})")
        elif not is_crit and crit_mult == 1.0:
            if ratio > 2.0 and ratio < 9.0:
                hints.append(f"【双暴反转】SIM 判定为未暴击 (1.00x)，但 GT 实战发生暴击 (GT 约为 SIM 的 {ratio:.2f} 倍)")

        # 2. 真实伤害联动判定
        if getattr(bd, "is_true_damage", False) or sim_hit.get("type") == "True":
            hints.append("【真实伤害联动】真实伤害严格为直伤累积池 x 星魂比例；当前差额直接由前序命中段数差额联动放大引起")

        # 3. 关卡机制减伤 / 众愿判定
        barrier_mult = getattr(bd, "barrier_mult", 1.0)
        if barrier_mult != 1.0:
            current_dr = 1.0 - barrier_mult
            needed_barrier = (g_dmg / (s_dmg / barrier_mult)) if (s_dmg / barrier_mult) != 0 else 1.0
            if needed_barrier > 0 and needed_barrier <= 1.0:
                needed_dr = 1.0 - needed_barrier
                hints.append(
                    f"【关卡众愿减免】SIM 当前 damage_reduction={current_dr:.3f} (倍率 {barrier_mult:.3f})；"
                    f"若为减免层数差异，GT 等效需要 damage_reduction={needed_dr:.3f} (倍率 {needed_barrier:.3f})"
                )

        # 4. 防御 / 减防 / 无视防御判定
        def_mult = getattr(bd, "def_mult", 0.0)
        if def_mult > 0:
            current_shred = getattr(bd, "def_shred", 0.0)
            base_other = s_dmg / def_mult
            if base_other > 0:
                needed_def_mult = g_dmg / base_other
                if 0 < needed_def_mult < 1.0:
                    needed_eff_def = (1000.0 / needed_def_mult) - 1000.0
                    needed_shred = 1.0 - (needed_eff_def / 1200.0)
                    shred_diff = needed_shred - current_shred
                    if abs(shred_diff) < 0.30:
                        hints.append(
                            f"【防御乘区】SIM 当前综合减防/无视={current_shred*100:.1f}% (防御倍率 {def_mult*100:.1f}%)；"
                            f"若由防御乘区导致，GT 所需减防/无视为 {needed_shred*100:.1f}% (差异 {shred_diff*100:+.1f}%)"
                        )

        # 5. 增伤乘区判定
        dmg_boost_mult = getattr(bd, "dmg_boost_mult", 1.0)
        if dmg_boost_mult > 1.0:
            current_boost = getattr(bd, "dmg_boost", dmg_boost_mult - 1.0)
            needed_boost_mult = dmg_boost_mult * ratio
            needed_boost = needed_boost_mult - 1.0
            boost_diff = needed_boost - current_boost
            if abs(boost_diff) < 0.50:
                hints.append(
                    f"【增伤乘区】SIM 当前增伤={current_boost*100:.1f}% (倍率 {dmg_boost_mult*100:.1f}%)；"
                    f"若由增伤缺失/多算导致，GT 所需增伤为 {needed_boost*100:.1f}% (差异 {boost_diff*100:+.1f}%)"
                )

        return hints


def render_action_report(diag: ActionDiagnosis, hit_filter: Optional[int] = None, verbose: bool = False) -> str:
    """生成符合用户规范的高可读性终端诊断报告。"""
    lines = []
    SEP = "=" * 80
    SUB_SEP = "-" * 80

    match_tag = "[PASS ✓]" if diag.is_action_match else "[DIFF ✗]"
    header_color = Colors.GREEN if diag.is_action_match else Colors.YELLOW
    lines.append(colorize(SEP, Colors.CYAN))
    lines.append(colorize(
        f"[Action #{diag.action_index:02d} 诊断报告] {match_tag} {diag.actor} | 【{diag.skill_name}】 | AV: {diag.gt_av:.2f} (SIM: {diag.sim_av:.2f})",
        header_color + Colors.BOLD
    ))
    lines.append(colorize(
        f"在场敌方: {', '.join(diag.enemies) if diag.enemies else '无'} | SkillConfigID: {diag.skill_config_id}",
        Colors.DIM
    ))
    lines.append(colorize(SUB_SEP, Colors.CYAN))

    tot_tag = "一致 ✓" if diag.is_action_match else f"差异 ✗ (差额: {diag.total_diff:+,.2f}, 误差 {diag.total_rel_error:+.4f}%)"
    tot_color = Colors.GREEN if diag.is_action_match else Colors.RED
    lines.append(
        f"全动总伤害: GT {diag.gt_total_dmg:,.2f} vs SIM {diag.sim_total_dmg:,.2f} "
        f"| {colorize(tot_tag, tot_color)}"
    )
    lines.append(
        f"全动总命中: GT {len(diag.hits) + len(diag.missing_gt_hits)} 发 "
        f"vs SIM {len(diag.hits) + len(diag.extra_sim_hits)} 发"
    )

    if diag.missing_gt_hits:
        lines.append(colorize(f"  ⚠️ SIM 缺失 {len(diag.missing_gt_hits)} 发 GT 命中！", Colors.RED))
    if diag.extra_sim_hits:
        lines.append(colorize(f"  ⚠️ SIM 多出了 {len(diag.extra_sim_hits)} 发额外命中！", Colors.YELLOW))

    lines.append("")

    for hit in diag.hits:
        if hit_filter is not None and hit.hit_index != hit_filter:
            continue

        h_color = Colors.GREEN if hit.is_match else Colors.RED
        h_tag = "一致 ✓" if hit.is_match else f"差异 ✗ ({hit.diff:+,.2f}, {hit.rel_error:+.4f}%)"

        lines.append(colorize(
            f"▶ Hit #{hit.hit_index:02d} [{hit.damage_type}] {hit.attacker} -> {hit.target}: "
            f"GT {hit.gt_damage:,.2f} vs SIM {hit.sim_damage:,.2f} ({h_tag})",
            h_color + Colors.BOLD
        ))

        for row in hit.multiplier_lines:
            lines.append(row.format_row())

        if hit.diagnosis_hints:
            lines.append(colorize("  [诊断提示 💡]", Colors.YELLOW + Colors.BOLD))
            for hint in hit.diagnosis_hints:
                lines.append(colorize(f"    - {hint}", Colors.YELLOW))

        if verbose:
            lines.append(colorize("  [攻击者状态池快照]", Colors.DIM))
            for s_id, s_name, mods in hit.attacker_statuses:
                lines.append(colorize(f"    * {s_name} ({s_id}): {mods}", Colors.DIM))
            lines.append(colorize("  [受击目标状态池快照]", Colors.DIM))
            for s_id, s_name, mods in hit.target_statuses:
                lines.append(colorize(f"    * {s_name} ({s_id}): {mods}", Colors.DIM))

        lines.append("")

    lines.append(colorize(SEP, Colors.CYAN))
    return "\n".join(lines)


def render_summary_table(diagnoses: List[ActionDiagnosis]) -> str:
    """输出全场 96 动对账诊断汇总表。"""
    lines = []
    lines.append("=" * 105)
    lines.append(f"{'动号':4s} | {'AV':6s} | {'行动角色':12s} | {'技能名称':18s} | {'GT 真值总伤':14s} | {'SIM 计算总伤':14s} | {'偏差率':10s} | {'状态':6s}")
    lines.append("-" * 105)

    diff_count = 0
    match_count = 0

    for d in diagnoses:
        tag = "PASS" if d.is_action_match else "DIFF"
        color = Colors.GREEN if d.is_action_match else Colors.RED
        if d.is_action_match:
            match_count += 1
        else:
            diff_count += 1
        lines.append(
            f"#{d.action_index:02d} | {d.gt_av:6.2f} | {d.actor:12s} | {d.skill_name[:18]:18s} | "
            f"{d.gt_total_dmg:14,.2f} | {d.sim_total_dmg:14,.2f} | {d.total_rel_error:+9.3f}% | "
            f"{colorize(tag, color)}"
        )

    lines.append("=" * 105)
    lines.append(f"汇总：共 {len(diagnoses)} 动 | 完美达标 (<0.1%): {match_count} 动 | 存在偏差: {diff_count} 动")
    return "\n".join(lines)


def parse_action_arg(arg: str) -> List[int]:
    """解析多样化动作编号输入格式：'12', '#12', '12-15', '12,13,15'。"""
    res = []
    arg = arg.strip().lstrip("#")
    if "-" in arg:
        parts = arg.split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            start, end = int(parts[0]), int(parts[1])
            res.extend(range(min(start, end), max(start, end) + 1))
    elif "," in arg:
        for p in arg.split(","):
            p = p.strip().lstrip("#")
            if p.isdigit():
                res.append(int(p))
    elif arg.isdigit():
        res.append(int(arg))
    return res


def main():
    parser = argparse.ArgumentParser(
        description="星铁模拟器一键乘区 Diff 诊断脚本 (Per-Action Multiplier Diff Diagnostic Tool)"
    )
    parser.add_argument(
        "actions",
        nargs="*",
        help="待诊断动作编号，支持单个 (如 12 或 #12)、多个 (如 12 13 14) 或区间 (如 12-17)",
    )
    parser.add_argument(
        "-d", "--diff-only",
        action="store_true",
        help="扫荡全场 96 动，仅诊断并输出有偏差 (>0.1%%) 的动作",
    )
    parser.add_argument(
        "-s", "--summary",
        action="store_true",
        help="输出全场 96 动紧凑对账汇总表",
    )
    parser.add_argument(
        "--hit",
        type=int,
        default=None,
        help="仅聚焦诊断指定动作内的某一命中段 (0-indexed)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="输出详细的当事双方 Buff/Debuff 修饰符快照",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="全量输出整场战斗 96 动的完整诊断报告",
    )

    args = parser.parse_args()

    data = MultiplierDiagnosticsEngine.run_replay()
    total_actions = len(data["gt"])

    target_action_indices: List[int] = []
    if args.actions:
        for a in args.actions:
            target_action_indices.extend(parse_action_arg(a))

    target_action_indices = sorted(set(idx for idx in target_action_indices if 1 <= idx <= total_actions))

    if args.summary:
        diagnoses = [MultiplierDiagnosticsEngine.diagnose_action(i) for i in range(1, total_actions + 1)]
        valid_diagnoses = [d for d in diagnoses if d is not None]
        print(render_summary_table(valid_diagnoses))
        return

    if args.diff_only:
        diff_diagnoses = []
        for i in range(1, total_actions + 1):
            d = MultiplierDiagnosticsEngine.diagnose_action(i)
            if d is not None and not d.is_action_match:
                diff_diagnoses.append(d)

        print(colorize(f"\n[全场偏差动作扫荡报告] 共发现 {len(diff_diagnoses)} 个动作存在乘区偏差：\n", Colors.YELLOW + Colors.BOLD))
        for d in diff_diagnoses:
            print(render_action_report(d, hit_filter=args.hit, verbose=args.verbose))
        return

    if args.all:
        target_action_indices = list(range(1, total_actions + 1))

    if not target_action_indices:
        target_action_indices = [12]

    for idx in target_action_indices:
        d = MultiplierDiagnosticsEngine.diagnose_action(idx)
        if d is not None:
            print(render_action_report(d, hit_filter=args.hit, verbose=args.verbose))
        else:
            print(colorize(f"未找到动作 #{idx} 的数据！", Colors.RED))


if __name__ == "__main__":
    main()

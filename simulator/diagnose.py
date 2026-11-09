# coding: utf-8
"""一键乘区 Diff 与全链路白盒对账诊断引擎 (Per-Action Multiplier & White-Box Audit Tool).

功能目标：
遇到任何动作伤害偏差，输入动作编号（如 12 或 #12 或 12-17）或使用 `--audit` 全场体检，工具秒级输出：
1. 【日志真值 1:1 绑定】：
   - 从 `battle_20261026_062503.jsonl` 的 `OnStatChange` 实时提取全部 534 发命中的真实受击目标 (`gt_target`)、
     战前/战后敌方 HP (`CurrentHP`)、实时韧性条 (`CurrentStance` 破韧状态)；
   - 实时提取我方 4 名角色 (`长夜月`/`缇宝`/`风堇`/`知更鸟•晴歌`) 在每一动出手瞬间的真实 `MaxHP` 与 `CriticalDamage`
     (直接透视实机【偏离和弦】、【雨过天晴】、【创世套】、【女武神】等 Buff 的生灭时点)。
2. 【三大动态机制蓄水池真值反推】：
   - 长夜《迷梦，流失，如露》：对比 `SIM 出手忆质` vs `GT 反推忆质点数`；
   - 小伊卡《乌云乌云快走开！》/ 风堇《飞入晨昏的我们》：对比 `SIM 累计治疗池 (accumulated_healing)` vs `GT 反推治疗池`；
   - 晴空乐手《叽叽啾啾四重奏》：对比 `SIM 出手气氛值 (vibes)` 与增伤/无视防御折算。
3. 【消除假打勾 & 智能乘区归因】：
   - 独立校验【受击目标】、【属性基数】、【双暴面板】、【破韧乘区】、【屏障/众愿减伤】；
   - 对复合乘区（倍率/增伤/防御/抗性/易伤）计算扣除已知偏差后的净残差比，自动匹配具体 Buff/机制根因。

使用方式：
    python -m simulator.diagnose --audit (-a)        # 全场 96 动四大维度白盒体检 (面板/动态池/首领HP/目标对齐)
    python -m simulator.diagnose --summary (-s)      # 输出全场 96 动紧凑对账汇总表
    python -m simulator.diagnose 12                  # 诊断指定第 12 动
    python -m simulator.diagnose 12 24 41 42 59      # 同时诊断多个动作
    python -m simulator.diagnose 59-66               # 诊断区间动作
    python -m simulator.diagnose --diff-only (-d)    # 全场 96 动扫荡，仅输出有偏差的动作诊断
    python -m simulator.diagnose 12 --hit 0 -v       # 仅聚焦诊断第 12 动的第 0 发命中并打印完整状态池
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from simulator.actions import ActionKind
from simulator.events import ActionExecuteEvent, BattleEvent, DamageAppliedEvent
from simulator.golden_diff import (
    OFFICIAL_20261026_NON_CRITS,
    attach_exact_crit_oracle,
    build_stage_sim,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)
from simulator.status import StatType

GOLDEN_20261026 = os.path.join(ROOT_DIR, "battle_logs", "battle_20261026_062503.jsonl")
GROUND_TRUTH_JSON = os.path.join(ROOT_DIR, "video_artifacts", "harness_ground_truth.json")


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
    status: str  # "MATCH", "DIFF", "INFO"
    note: str = ""

    def format_row(self) -> str:
        if self.status == "MATCH":
            tag = "一致 ✓"
            tag_color = Colors.GREEN
            note_str = f" ({self.note})" if self.note else ""
            return f"  {self.name:12s}: GT {self.gt_val} vs SIM {self.sim_val} ({colorize(tag, tag_color)}){note_str}"
        elif self.status == "DIFF":
            tag = f"差异 ✗ -> {self.note}" if self.note else "差异 ✗"
            return f"  {self.name:12s}: GT {self.gt_val} vs SIM {self.sim_val} ({colorize(tag, Colors.RED)})"
        else:
            note_str = f" [{self.note}]" if self.note else ""
            return f"  {self.name:12s}: SIM {self.sim_val}{colorize(note_str, Colors.CYAN)}"


@dataclass
class HitDiagnosis:
    hit_index: int
    attacker: str
    gt_target: str
    sim_target: str
    damage_type: str
    gt_damage: float
    sim_damage: float
    diff: float
    rel_error: float
    is_match: bool
    gt_target_hp_before: Optional[float]
    gt_target_hp_after: Optional[float]
    sim_target_hp_before: Optional[float]
    sim_target_hp_after: Optional[float]
    gt_target_stance: Optional[float]
    sim_target_toughness: Optional[float]
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
    wave: int
    gt_enemies: List[str]
    sim_enemies: List[str]
    gt_boss_hp: float
    sim_boss_hp: float
    gt_total_dmg: float
    sim_total_dmg: float
    total_diff: float
    total_rel_error: float
    is_action_match: bool
    gt_party_stats: Dict[str, Dict[str, float]]
    sim_party_stats: Dict[str, Dict[str, float]]
    pool_info: Dict[str, Any]
    hits: List[HitDiagnosis]
    extra_sim_hits: List[Dict[str, Any]]
    missing_gt_hits: List[Dict[str, Any]]


class MultiplierDiagnosticsEngine:
    """乘区与全链路白盒诊断引擎：单次仿真采集全场 96 动微观快照并对照官方 JSONL 真值。"""

    _cache: Optional[Dict[str, Any]] = None
    _gt_rich_actions: Optional[List[Dict[str, Any]]] = None

    PLAYER_UID_MAP = {
        1403: "缇宝",
        1409: "风堇",
        1413: "长夜月",
        1512: "知更鸟•晴歌",
    }

    @classmethod
    def _load_gt_rich_actions(cls) -> List[Dict[str, Any]]:
        """从官方 battle_20261026_062503.jsonl 提取 96 动完整真值 (含每击精确受击怪、HP、韧性及四角色实时面板)。"""
        if cls._gt_rich_actions is not None:
            return cls._gt_rich_actions

        with open(GROUND_TRUTH_JSON, encoding="utf-8") as f:
            base_gt: List[Dict[str, Any]] = json.load(f)

        with open(GOLDEN_20261026, encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]

        enemy_name: Dict[int, str] = {100013: "月夜天马", 100015: "「灯塔」"}
        enemy_hp: Dict[int, float] = {100013: 4904294.49, 100015: 4286281.55}
        enemy_max_hp: Dict[int, float] = {100013: 4904294.49, 100015: 4286281.55}
        enemy_stance: Dict[int, float] = {100013: 390.0, 100015: 390.0}
        current_wave = 1
        current_av = 0.0

        # 我方 4 名本体角色的实时 OnStatChange 面板
        party_stats: Dict[str, Dict[str, float]] = {
            "缇宝": {"MaxHP": 9516.348, "CurrentHP": 9516.348, "CriticalDamage": 4.63204, "CurrentSP": 121.79},
            "风堇": {"MaxHP": 5564.373, "CurrentHP": 5564.373, "CriticalDamage": 1.46680, "HealRatio": 0.545, "CurrentSP": 0.0},
            "长夜月": {"MaxHP": 8108.804, "CurrentHP": 8056.434, "CriticalDamage": 4.53380, "CurrentSP": 195.0},
            "知更鸟•晴歌": {"MaxHP": 7236.158, "CurrentHP": 6193.410, "CriticalDamage": 1.38180, "CurrentSP": 76.0},
        }
        # 记录每个角色最近出现过的暴伤峰值 (过滤先删后加的瞬时闪烁，并捕获长夜/长夜月双轨暴伤)
        recent_cd_window: Dict[str, List[float]] = {k: [v["CriticalDamage"]] for k, v in party_stats.items()}
        current_gt_vibes: int = 8
        last_tonal_vibes: Dict[int, int] = {}

        rich_actions: List[Dict[str, Any]] = []
        cur_act: Optional[Dict[str, Any]] = None
        pending_enemy_changes: List[Tuple[int, str, float, float, float]] = []

        def _try_update_gt_vibes(uid: int, val: float) -> None:
            nonlocal current_gt_vibes
            v_est = None
            if uid == 1403 and val > 5.0:
                v_est = (val - 5.032040042616427) / 0.015
            elif uid == 1409 and val > 2.40:
                v_est = (val - 2.411760017422065) / 0.015
            elif uid == 1413 and val > 5.0:
                v_est = (val - 4.933800025470555) / 0.015
            if v_est is not None and abs(v_est - round(v_est)) < 0.05:
                v_int = int(round(v_est))
                if 0 <= v_int <= 70 and last_tonal_vibes.get(uid) != v_int:
                    last_tonal_vibes[uid] = v_int
                    current_gt_vibes = v_int

        def _update_stat(e_data: Dict[str, Any]) -> None:
            ent = e_data.get("entity", {})
            prop = e_data.get("property", {})
            team = ent.get("team")
            uid = ent.get("uid")
            ptype = prop.get("type")
            val = float(prop.get("value", 0.0) or 0.0)
            if team == "Player" and uid in cls.PLAYER_UID_MAP:
                cname = cls.PLAYER_UID_MAP[uid]
                if ptype in ("MaxHP", "CurrentHP", "CriticalDamage", "HealRatio", "Speed", "CurrentSP"):
                    party_stats[cname][ptype] = val
                if ptype == "CriticalDamage":
                    win = recent_cd_window[cname]
                    win.append(val)
                    if len(win) > 4:
                        win.pop(0)
                    _try_update_gt_vibes(uid, val)
            elif team == "Enemy" and uid is not None:
                prev_hp = enemy_hp.get(uid, 0.0)
                prev_st = enemy_stance.get(uid, 0.0)
                if ptype == "CurrentHP":
                    enemy_hp[uid] = val
                    pending_enemy_changes.append((uid, "HP", prev_hp, val, prev_st))
                elif ptype == "MaxHP":
                    enemy_max_hp[uid] = val
                elif ptype == "CurrentStance":
                    enemy_stance[uid] = val
                    pending_enemy_changes.append((uid, "Stance", prev_hp, enemy_hp.get(uid, 0.0), prev_st))
                elif ptype == "CurrentSP":
                    pending_enemy_changes.append((uid, "SP", prev_hp, enemy_hp.get(uid, 0.0), prev_st))

        idx = 0
        while idx < len(events):
            e = events[idx]
            ev = e.get("event")
            d = e.get("data", {})

            if ev == "OnUpdateWave":
                current_wave = int(d.get("wave", current_wave))
                if current_wave == 2:
                    # 清理第一波残余怪记录
                    for old_uid in (100013, 100015, 100021, 100024, 100026):
                        enemy_hp[old_uid] = 0.0
            elif ev == "OnTurnBegin":
                current_av = float(d.get("action_value", current_av))
                if cur_act is not None:
                    cur_act = None
            elif ev == "OnInitializeEnemy":
                en = d.get("enemy", {})
                uid = en.get("uid")
                name = en.get("name", f"Enemy#{uid}")
                props = en.get("base_stats", {}).get("properties", {})
                hp_val = float(props.get("CurrentHP", 0.0))
                enemy_name[uid] = name
                enemy_hp[uid] = hp_val
                enemy_max_hp[uid] = float(props.get("MaxHP", hp_val))
                if name == "堕神之血•亚婆离":
                    enemy_stance[uid] = 1080.0
                elif name == "狂兽的胚芽":
                    enemy_stance[uid] = 120.0
                else:
                    enemy_stance[uid] = 90.0
            elif ev == "OnStatChange":
                _update_stat(d)
            elif ev == "OnUseSkill":
                sk = d.get("skill", {})
                stype = sk.get("type")
                av_info = d.get("avatar", {})
                if stype in ("Normal", "BPSkill", "Ultra", "Servant", "EnemySkill"):
                    pending_enemy_changes.clear()
                    if av_info.get("team") == "Player" and stype in ("Normal", "BPSkill", "Ultra", "Servant"):
                        # 捕获施放瞬间的在场敌方与首领血量
                        alive_uids = [
                            u for u, hp in enemy_hp.items()
                            if hp > 0 and ((current_wave == 1 and u < 100030) or (current_wave == 2 and u >= 100030))
                        ]
                        alive_names = [enemy_name.get(u, f"#{u}") for u in alive_uids]
                        boss_uid = 100015 if current_wave == 1 else 100037
                        boss_hp_now = enemy_hp.get(boss_uid, 0.0)

                        # 向前预读该技能第一发 OnDamage 之前的自身 Buff OnStatChange (如 A2 扣血加暴伤、雨过天晴加生命、气氛暴伤)
                        look_idx = idx + 1
                        temp_party = {k: dict(v) for k, v in party_stats.items()}
                        temp_vibes = current_gt_vibes
                        while look_idx < len(events):
                            ne = events[look_idx]
                            nev = ne.get("event")
                            if nev in ("OnDamage", "OnTurnBegin"):
                                break
                            if nev == "OnUseSkill":
                                nst = ne.get("data", {}).get("skill", {}).get("type")
                                if nst in ("Normal", "BPSkill", "Ultra", "Servant", "EnemySkill"):
                                    break
                            if nev == "OnStatChange":
                                ent = ne.get("data", {}).get("entity", {})
                                prop = ne.get("data", {}).get("property", {})
                                uid = ent.get("uid")
                                if ent.get("team") == "Player" and uid in cls.PLAYER_UID_MAP:
                                    cname = cls.PLAYER_UID_MAP[uid]
                                    ptype = prop.get("type")
                                    val = float(prop.get("value", 0.0) or 0.0)
                                    if ptype in ("MaxHP", "CurrentHP", "CriticalDamage", "HealRatio", "Speed", "CurrentSP"):
                                        temp_party[cname][ptype] = val
                                    if ptype == "CriticalDamage":
                                        v_est = None
                                        if uid == 1403 and val > 5.0:
                                            v_est = (val - 5.032040042616427) / 0.015
                                        elif uid == 1409 and val > 2.40:
                                            v_est = (val - 2.411760017422065) / 0.015
                                        elif uid == 1413 and val > 5.0:
                                            v_est = (val - 4.933800025470555) / 0.015
                                        if v_est is not None and abs(v_est - round(v_est)) < 0.05:
                                            v_int = int(round(v_est))
                                            if 0 <= v_int <= 70:
                                                temp_vibes = v_int
                            look_idx += 1

                        act_i = len(rich_actions)
                        base_item = base_gt[act_i] if act_i < len(base_gt) else {}
                        cur_act = {
                            "action_index": act_i + 1,
                            "av": round(current_av, 2),
                            "wave": current_wave,
                            "actor": base_item.get("actor", cls.PLAYER_UID_MAP.get(av_info.get("uid"), "")),
                            "skill_type": stype,
                            "skill_name": sk.get("name", ""),
                            "skill_config_id": sk.get("skill_config_id", 0),
                            "gt_enemies": alive_names,
                            "gt_boss_hp": boss_hp_now,
                            "gt_party_stats": temp_party,
                            "gt_vibes": temp_vibes,
                            "hits": [],
                        }
                        rich_actions.append(cur_act)
                    else:
                        cur_act = None
            elif ev == "OnDamage":
                att = d.get("attacker", {})
                if att.get("team") == "Player" and cur_act is not None:
                    t_uid = None
                    hp_before, hp_after, st_before = None, None, None
                    for u, kind, hb, ha, stb in reversed(pending_enemy_changes):
                        if kind == "HP":
                            t_uid, hp_before, hp_after, st_before = u, hb, ha, stb
                            break
                    if t_uid is None and pending_enemy_changes:
                        t_uid, _, hb, ha, stb = pending_enemy_changes[-1]
                        hp_before, hp_after, st_before = hb, ha, stb
                    pending_enemy_changes.clear()

                    t_name = enemy_name.get(t_uid, f"Enemy#{t_uid}") if t_uid is not None else "未知目标"
                    cur_act["hits"].append({
                        "type": d.get("type", ""),
                        "damage": float(d.get("damage", 0.0)),
                        "overkill_damage": float(d.get("overkill_damage", 0.0)),
                        "target_uid": t_uid,
                        "target": t_name,
                        "target_hp_before": hp_before,
                        "target_hp_after": hp_after,
                        "target_stance_before": st_before,
                        "target_stance_after": enemy_stance.get(t_uid) if t_uid is not None else None,
                        "party_stats_at_hit": {k: dict(v) for k, v in party_stats.items()},
                        "gt_vibes_at_hit": current_gt_vibes,
                    })
            idx += 1

        cls._gt_rich_actions = rich_actions
        return rich_actions

    @classmethod
    def run_replay(cls, seed: int = 1, force_refresh: bool = False) -> Dict[str, Any]:
        """运行模拟器回放并捕获逐动动态蓄水池、全队面板与逐发乘区快照。"""
        if cls._cache is not None and not force_refresh:
            return cls._cache

        import random
        random.seed(seed)

        gt_data = cls._load_gt_rich_actions()
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

        def snapshot_sim_party() -> Dict[str, Dict[str, float]]:
            snap: Dict[str, Dict[str, float]] = {}
            for cname in ("长夜月", "缇宝", "风堇", "知更鸟•晴歌", "长夜", "小伊卡", "晴空乐手"):
                ent = lookup_entity(cname)
                if ent is not None:
                    cd = sim.status_mgr.calculate_stat(cname, ent.base_crit_dmg, StatType.CRIT_DMG)
                    hr = sim.status_mgr.calculate_stat(cname, getattr(ent, "base_outgoing_healing", 0.0), StatType.OUTGOING_HEALING)
                    snap[cname] = {
                        "MaxHP": float(ent.max_hp),
                        "CurrentHP": float(ent.current_hp),
                        "CriticalDamage": float(cd),
                        "HealRatio": float(hr),
                        "CurrentSP": float(getattr(ent, "energy", 0.0)),
                    }
            return snap

        def snapshot_pools_and_boss() -> Dict[str, Any]:
            cyy = lookup_entity("长夜月")
            fj = lookup_entity("风堇")
            rb = lookup_entity("知更鸟•晴歌")
            lh = lookup_entity("「灯塔」")
            ypl = lookup_entity("堕神之血•亚婆离")

            cyy_kit = getattr(cyy, "kit", None) if cyy else None
            fj_kit = getattr(fj, "kit", None) if fj else None
            rb_kit = getattr(rb, "kit", None) if rb else None
            lh_kit = getattr(lh, "kit", None) if lh else None

            boss_ent = ypl if (ypl is not None and ypl.current_hp > 0) else lh
            boss_hp = float(boss_ent.current_hp) if boss_ent is not None else 0.0
            boss_dr = float(getattr(boss_ent, "damage_reduction", 0.0)) if boss_ent is not None else 0.0
            wishes = getattr(lh_kit, "wishes", None) if lh_kit is not None else None

            return {
                "yizhi": getattr(cyy_kit, "yizhi", 0) if cyy_kit else 0,
                "darkness": getattr(cyy_kit, "darkness", False) if cyy_kit else False,
                "accumulated_healing": float(getattr(fj_kit, "accumulated_healing", 0.0)) if fj_kit else 0.0,
                "vibes": getattr(rb_kit, "vibes", 0) if rb_kit else 0,
                "max_vibes": getattr(rb_kit, "max_vibes", 60) if rb_kit else 60,
                "has_drummie": getattr(rb_kit, "has_drummie", False) if rb_kit else False,
                "has_paddie": getattr(rb_kit, "has_paddie", False) if rb_kit else False,
                "boss_name": boss_ent.name if boss_ent is not None else "",
                "boss_hp": boss_hp,
                "boss_dr": boss_dr,
                "wishes": wishes,
            }

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
                    "party_stats_pre": snapshot_sim_party(),
                    "party_stats_at_hit": None,
                    "pools_pre": snapshot_pools_and_boss(),
                    "hits": [],
                }
                sim_actions.append(cur_action)
            elif isinstance(e, DamageAppliedEvent):
                if cur_action is None:
                    return
                ent = lookup_entity(e.attacker_name)
                if ent is not None and getattr(ent, "is_enemy", False):
                    return

                if cur_action["party_stats_at_hit"] is None:
                    cur_action["party_stats_at_hit"] = snapshot_sim_party()
                    # 若是小伊卡或长夜出手，首击瞬间的池子可能已在 execute 开头快照，同时记录首击时状态
                    cur_action["pools_at_first_hit"] = snapshot_pools_and_boss()

                dt_str = e.damage_type.value if hasattr(e.damage_type, "value") else str(e.damage_type)

                a_statuses = []
                t_statuses = []
                if hasattr(sim, "status_mgr"):
                    for s in sim.status_mgr.get_statuses(e.attacker_name):
                        a_statuses.append((s.id, s.name, list(s.modifiers)))
                    for s in sim.status_mgr.get_statuses(e.target_name):
                        t_statuses.append((s.id, s.name, list(s.modifiers)))

                t_ent = lookup_entity(e.target_name)
                t_hp_after = float(t_ent.current_hp) if t_ent is not None else None
                t_hp_before = (t_hp_after + float(e.damage)) if t_hp_after is not None else None
                t_tough = float(t_ent.current_toughness) if t_ent is not None else None

                cur_action["hits"].append({
                    "attacker": e.attacker_name,
                    "target": e.target_name,
                    "type": dt_str,
                    "damage": float(e.damage),
                    "is_crit": e.is_crit,
                    "target_hp_before": t_hp_before,
                    "target_hp_after": t_hp_after,
                    "target_toughness": t_tough,
                    "breakdown": e.breakdown,
                    "attacker_statuses": a_statuses,
                    "target_statuses": t_statuses,
                })

        sim.event_bus.subscribe(BattleEvent, on_battle_event)
        traj = run_trajectory_replay(sim, director, extract_timeline(GOLDEN_20261026), av_budget=golden.final_av)

        # 对无伤害技能 (如白昼悄然离去 / 爱在虹光洒落时) 补齐施放后的面板快照
        for act in sim_actions:
            if act["party_stats_at_hit"] is None:
                act["party_stats_at_hit"] = act["party_stats_pre"]

        cls._cache = {
            "gt": gt_data,
            "sim_actions": sim_actions,
            "golden": golden,
            "traj": traj,
        }
        return cls._cache

    @classmethod
    def _compute_pool_comparison(cls, gt_act: Dict[str, Any], sim_act: Dict[str, Any]) -> Dict[str, Any]:
        """针对三大动态机制技能，从 GT 首段主伤害反推实机真实池子数值 (忆质 / 累计治疗池 / 气氛值)。"""
        pools = dict(sim_act.get("pools_pre", {}))
        pools["gt_vibes"] = gt_act.get("gt_vibes", pools.get("vibes", 0))
        skill_name = sim_act.get("skill", gt_act.get("skill_name", ""))
        gt_hits = gt_act.get("hits", [])
        sim_hits = sim_act.get("hits", [])

        # 1. 长夜《迷梦，流失，如露》: 主目标倍率 = 0.288 * yizhi * e1_mult
        if skill_name == "迷梦，流失，如露" and gt_hits and sim_hits:
            sim_yizhi = pools.get("yizhi", 0)
            # 找第一发 Servant 命中
            g_serv = next((h for h in gt_hits if h.get("type") == "Servant"), None)
            s_serv = next((h for h in sim_hits if h.get("type") == "Servant"), None)
            if g_serv and s_serv and s_serv["damage"] > 0 and sim_yizhi > 0:
                ratio = g_serv["damage"] / s_serv["damage"]
                pools["gt_inferred_yizhi"] = sim_yizhi * ratio
                pools["yizhi_diff"] = sim_yizhi - (sim_yizhi * ratio)

        # 2. 小伊卡《乌云乌云快走开！》: 伤害线性正比于 accumulated_healing
        elif skill_name == "乌云乌云快走开！" and gt_hits and sim_hits:
            # 注意: 风堇大招后自动触发的小伊卡，其治疗池在 ActionExecuteEvent 前已累加完雨过天晴
            sim_pool = pools.get("accumulated_healing", 0.0)
            g_servs = [h["damage"] for h in gt_hits if h.get("type") == "Servant"]
            s_servs = [h["damage"] for h in sim_hits if h.get("type") == "Servant"]
            if g_servs and s_servs and sum(s_servs) > 0 and sim_pool > 0:
                ratio = sum(g_servs) / sum(s_servs)
                pools["gt_inferred_healing_pool"] = sim_pool * ratio
                pools["healing_pool_err_pct"] = (1.0 - ratio) * 100.0

        return pools

    @classmethod
    def diagnose_action(cls, action_idx: int) -> Optional[ActionDiagnosis]:
        """对指定动作编号（1-based，如 12）执行全乘区与全链路深度诊断。"""
        data = cls.run_replay()
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
        gt_party = gt_act.get("gt_party_stats", {})
        sim_party = sim_act.get("party_stats_at_hit") or sim_act.get("party_stats_pre", {})
        pool_info = cls._compute_pool_comparison(gt_act, sim_act)

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
            hit_gt_party = g_hit.get("party_stats_at_hit", gt_party)

            mult_lines, hints = cls._build_multiplier_lines_and_hints(
                action_idx, i, g_hit, s_hit, bd, hit_gt_party, sim_party, pool_info
            )

            hit_diagnoses.append(HitDiagnosis(
                hit_index=i,
                attacker=s_hit.get("attacker", ""),
                gt_target=g_hit.get("target", "未知"),
                sim_target=s_hit.get("target", "未知"),
                damage_type=s_hit.get("type", g_hit.get("type", "")),
                gt_damage=g_dmg,
                sim_damage=s_dmg,
                diff=diff,
                rel_error=rel_err,
                is_match=is_match,
                gt_target_hp_before=g_hit.get("target_hp_before"),
                gt_target_hp_after=g_hit.get("target_hp_after"),
                sim_target_hp_before=s_hit.get("target_hp_before"),
                sim_target_hp_after=s_hit.get("target_hp_after"),
                gt_target_stance=g_hit.get("target_stance_before"),
                sim_target_toughness=s_hit.get("target_toughness"),
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
            wave=gt_act.get("wave", 1),
            gt_enemies=gt_act.get("gt_enemies", []),
            sim_enemies=sim_act.get("enemies", []),
            gt_boss_hp=float(gt_act.get("gt_boss_hp", 0.0)),
            sim_boss_hp=float(pool_info.get("boss_hp", 0.0)),
            gt_total_dmg=gt_tot,
            sim_total_dmg=sim_tot,
            total_diff=tot_diff,
            total_rel_error=tot_rel,
            is_action_match=abs(tot_diff) <= 5.0 or abs(tot_rel) < 0.10,
            gt_party_stats=gt_party,
            sim_party_stats=sim_party,
            pool_info=pool_info,
            hits=hit_diagnoses,
            extra_sim_hits=extra_sim,
            missing_gt_hits=missing_gt,
        )

    @classmethod
    def _build_multiplier_lines_and_hints(
        cls,
        act_idx: int,
        hit_idx: int,
        gt_hit: Dict[str, Any],
        sim_hit: Dict[str, Any],
        bd: Any,
        gt_party: Dict[str, Dict[str, float]],
        sim_party: Dict[str, Dict[str, float]],
        pool_info: Dict[str, Any],
    ) -> Tuple[List[MultiplierLine], List[str]]:
        """构建真实独立校验的乘区对比表与精准根因归因提示（彻底杜绝左手比左手假打勾）。"""
        lines: List[MultiplierLine] = []
        hints: List[str] = []
        if bd is None:
            return lines, hints

        attacker = sim_hit.get("attacker", "")
        sim_target = sim_hit.get("target", "")
        gt_target = gt_hit.get("target", "")
        dt = sim_hit.get("type", "")

        g_dmg = float(gt_hit.get("damage", 0.0))
        s_dmg = float(sim_hit.get("damage", 0.0))
        is_hit_match = abs(s_dmg - g_dmg) <= 1.0 or (abs((s_dmg - g_dmg) / g_dmg) < 0.001 if g_dmg else True)
        is_true_dmg = bool(getattr(bd, "is_true_damage", False) or dt == "True")

        # 累积已解释的误差比例 (SIM / GT)，用于剥离已知偏差后定位未知乘区残差
        explained_sim_over_gt = 1.0

        # 0. 受击目标与敌方战后 HP 校验
        target_same = (gt_target == sim_target) or (gt_target.startswith("千星戍卫") and sim_target.startswith("千星戍卫")) or (gt_target.startswith("狂兽的胚芽") and sim_target.startswith("狂兽的胚芽"))
        gt_hp_after = gt_hit.get("target_hp_after")
        sim_hp_after = sim_hit.get("target_hp_after")
        gt_hp_str = f"{gt_target} (战后HP {gt_hp_after:,.0f})" if gt_hp_after is not None else gt_target
        sim_hp_str = f"{sim_target} (战后HP {sim_hp_after:,.0f})" if sim_hp_after is not None else sim_target
        lines.append(MultiplierLine(
            name="受击目标区",
            gt_val=gt_hp_str,
            sim_val=sim_hp_str,
            status="MATCH" if target_same else "DIFF",
            note="目标吻合" if target_same else f"索敌目标错位: GT打{gt_target} vs SIM打{sim_target}"
        ))
        if not target_same:
            hints.append(f"【索敌错位】GT 实际命中 [{gt_target}]，而 SIM 命中了 [{sim_target}]（可能因小怪提前/延后死亡或主目标偏差）")

        # 1. 属性基数区 (Base Stat: 独立对照 OnStatChange MaxHP)
        stat_key = getattr(bd, "scaling_stat", "atk")
        stat_label = {"hp": "生命属性区", "atk": "攻击力区", "def": "防御力区"}.get(stat_key, "属性基数区")
        sim_base_stat = float(getattr(bd, "base_stat", 0.0))

        gt_base_stat: Optional[float] = None
        if stat_key == "hp":
            if attacker in gt_party and "MaxHP" in gt_party[attacker]:
                gt_base_stat = float(gt_party[attacker]["MaxHP"])
            elif attacker == "长夜" and "长夜月" in gt_party and "MaxHP" in gt_party["长夜月"]:
                # 长夜 MaxHP: 本体常驻 MaxHP * 50% + 动态增益 (通过本体 GT vs SIM 差值映射)
                sim_master_hp = sim_party.get("长夜月", {}).get("MaxHP", 0.0)
                gt_master_hp = float(gt_party["长夜月"]["MaxHP"])
                if sim_master_hp > 0:
                    gt_base_stat = sim_base_stat + (gt_master_hp - sim_master_hp)

        if gt_base_stat is not None and gt_base_stat > 0 and not is_true_dmg:
            base_match = abs(sim_base_stat - gt_base_stat) / gt_base_stat < 0.001
            if not base_match:
                explained_sim_over_gt *= (sim_base_stat / gt_base_stat)
                hints.append(
                    f"【属性基数偏差】{attacker} 实时 MaxHP: GT={gt_base_stat:,.2f} vs SIM={sim_base_stat:,.2f} "
                    f"(差额 {sim_base_stat - gt_base_stat:+,.2f}, 造成伤害偏移 {(sim_base_stat/gt_base_stat - 1)*100:+.2f}%)"
                )
            lines.append(MultiplierLine(
                name=stat_label,
                gt_val=f"{gt_base_stat:,.2f}",
                sim_val=f"{sim_base_stat:,.2f}",
                status="MATCH" if base_match else "DIFF",
                note="OnStatChange真值吻合" if base_match else f"差额 {sim_base_stat - gt_base_stat:+,.2f}"
            ))
        else:
            lines.append(MultiplierLine(
                name=stat_label,
                gt_val="—",
                sim_val=f"{sim_base_stat:,.2f}",
                status="MATCH" if (is_hit_match or is_true_dmg) else "INFO",
                note="真伤基数来自原击" if is_true_dmg else "固定攻击白值+增益"
            ))

        # 2. 双暴乘区 (独立对照 OnStatChange CriticalDamage 与暴击真值表)
        is_crit = getattr(bd, "is_crit", False)
        sim_crit_mult = float(getattr(bd, "crit_mult", 1.0))
        is_gt_non_crit = (act_idx - 1, hit_idx) in OFFICIAL_20261026_NON_CRITS
        gt_crit_state = False if is_true_dmg else (not is_gt_non_crit)

        # 从 OnStatChange 提取 GT 实时暴伤乘数 (1 + CriticalDamage)
        gt_crit_mult: Optional[float] = None
        if not is_true_dmg and gt_crit_state:
            if attacker in gt_party and "CriticalDamage" in gt_party[attacker]:
                gt_cd = float(gt_party[attacker]["CriticalDamage"])
                if attacker == "长夜月" and abs((sim_crit_mult - 1.0) - (gt_cd + 0.50)) < 0.002:
                    gt_crit_mult = 1.0 + gt_cd + 0.50
                else:
                    gt_crit_mult = 1.0 + gt_cd
            elif attacker == "长夜" and "长夜月" in gt_party:
                gt_m_cd = float(gt_party["长夜月"]["CriticalDamage"])
                sim_m_cd = float(sim_party.get("长夜月", {}).get("CriticalDamage", gt_m_cd))
                cd_diff = sim_m_cd - gt_m_cd
                if abs(cd_diff) > 0.01:
                    gt_crit_mult = sim_crit_mult - cd_diff

        if is_true_dmg:
            lines.append(MultiplierLine("双暴乘区", "100.00%", "100.00%", "MATCH", "真实伤害不暴击"))
        elif not gt_crit_state and not is_crit:
            lines.append(MultiplierLine("双暴乘区", "100.00%", "100.00%", "MATCH", "未暴击一致"))
        elif gt_crit_mult is not None and is_crit:
            cd_match = abs(sim_crit_mult - gt_crit_mult) / gt_crit_mult < 0.002
            if not cd_match:
                explained_sim_over_gt *= (sim_crit_mult / gt_crit_mult)
                cd_delta = (sim_crit_mult - gt_crit_mult) * 100.0
                hints.append(
                    f"【暴伤面板偏差】{attacker} OnStatChange 暴伤乘区: GT={gt_crit_mult*100:.2f}% vs SIM={sim_crit_mult*100:.2f}% "
                    f"(SIM 差额 {cd_delta:+.2f}% 暴伤，常见于【偏离和弦】快照或持续回合差异，造成伤害偏移 {(sim_crit_mult/gt_crit_mult - 1)*100:+.2f}%)"
                )
            lines.append(MultiplierLine(
                name="双暴乘区",
                gt_val=f"{gt_crit_mult * 100:.2f}%",
                sim_val=f"{sim_crit_mult * 100:.2f}%",
                status="MATCH" if cd_match else "DIFF",
                note="OnStatChange暴伤吻合" if cd_match else f"暴伤差 {(sim_crit_mult - gt_crit_mult)*100:+.2f}%"
            ))
        else:
            crit_state_match = (is_crit == gt_crit_state)
            lines.append(MultiplierLine(
                name="双暴乘区",
                gt_val="暴击" if gt_crit_state else "100.00%",
                sim_val=f"{sim_crit_mult * 100:.2f}%" if is_crit else "100.00%",
                status="MATCH" if (crit_state_match and is_hit_match) else ("DIFF" if not crit_state_match else "INFO"),
                note=f"暴击 (暴伤 {(sim_crit_mult-1)*100:.2f}%)" if is_crit else "未暴击"
            ))

        # 3. 韧性破韧乘区 (独立对照 OnStatChange Enemy CurrentStance: >0 为 0.90x, ==0 为 1.00x)
        sim_red_mult = float(getattr(bd, "reduction_mult", 1.0))
        gt_stance = gt_hit.get("target_stance_before")
        if is_true_dmg:
            lines.append(MultiplierLine("韧性乘区", "100.00%", "100.00%", "MATCH", "真实伤害无视韧性"))
        elif gt_stance is not None:
            # 官方机制：敌方未破韧常规承伤 0.90x；若实体形态覆盖韧性减免为 0% (如二阶段亚婆离) 或已破韧，则承伤 1.00x
            if gt_stance == 0.0 or (gt_target == "堕神之血•亚婆离" and abs(sim_red_mult - 1.0) < 0.01):
                gt_tough_mult = 1.00
            else:
                gt_tough_mult = 0.90
            tough_match = abs(sim_red_mult - gt_tough_mult) < 0.01
            if not tough_match:
                explained_sim_over_gt *= (sim_red_mult / gt_tough_mult)
                hints.append(
                    f"【破韧状态错位】GT 敌方韧性={gt_stance:.0f} (乘数 {gt_tough_mult:.2f}x)，"
                    f"SIM 敌方韧性={sim_hit.get('target_toughness') or 0:.0f} (乘数 {sim_red_mult:.2f}x)"
                )
            lines.append(MultiplierLine(
                name="韧性乘区",
                gt_val=f"{gt_tough_mult * 100:.1f}% (韧性 {gt_stance:.0f})",
                sim_val=f"{sim_red_mult * 100:.1f}% (韧性 {sim_hit.get('target_toughness') or 0:.0f})",
                status="MATCH" if tough_match else "DIFF",
                note="破韧状态吻合" if tough_match else "破韧时点偏差!"
            ))
        else:
            lines.append(MultiplierLine("韧性乘区", "—", f"{sim_red_mult * 100:.1f}%", "INFO", ""))

        # 4. 关卡机制减伤区 (灯塔【众愿】 / 亚婆离【血脑屏障】)
        sim_barrier_mult = float(getattr(bd, "barrier_mult", 1.0))
        # 判断 GT 中亚婆离是否处于血脑屏障状态:
        # 一阶段冻结地板为 4,540,782.5 (在 Act #42 破盾扣 35% 至 1,750,860)；二阶段地板为 3,833,735.1
        gt_hp_b = gt_hit.get("target_hp_before")
        gt_hp_a = gt_hit.get("target_hp_after")
        gt_expected_barrier: Optional[float] = None
        if not is_true_dmg:
            if gt_target == "堕神之血•亚婆离" and gt_hp_b is not None and gt_hp_a is not None:
                # 若命中首领且首领扣血为 0 (冻结在 454万 或 383万 地板)，或处于屏障吸收期，则 GT 必有 75% 屏障减伤 (0.25x)
                if abs(gt_hp_b - gt_hp_a) < 1.0 and gt_hp_a > 3000000.0:
                    gt_expected_barrier = 0.25
                elif s_dmg > 0 and abs((g_dmg / s_dmg) - (0.25 / sim_barrier_mult)) < 0.08 and sim_barrier_mult == 1.0:
                    gt_expected_barrier = 0.25
                elif s_dmg > 0 and abs((g_dmg / s_dmg) - (1.0 / sim_barrier_mult)) < 0.08 and sim_barrier_mult == 0.25:
                    gt_expected_barrier = 1.00
            elif gt_target in ("月夜天马", "千星戍卫", "狂兽的胚芽"):
                gt_expected_barrier = 1.00

        if gt_expected_barrier is not None:
            bar_match = abs(sim_barrier_mult - gt_expected_barrier) < 0.01
            if not bar_match:
                explained_sim_over_gt *= (sim_barrier_mult / gt_expected_barrier)
                hints.append(
                    f"【血脑屏障错位】GT 首领处于 {'屏障激活 (0.25x)' if gt_expected_barrier == 0.25 else '屏障已破 (1.00x)'}，"
                    f"但 SIM 为 {sim_barrier_mult:.2f}x！(首领屏障吸收池累计伤害存在偏差)"
                )
            lines.append(MultiplierLine(
                name="屏障/众愿区",
                gt_val=f"{gt_expected_barrier * 100:.2f}%",
                sim_val=f"{sim_barrier_mult * 100:.2f}%",
                status="MATCH" if bar_match else "DIFF",
                note="屏障状态吻合" if bar_match else "破盾临界点错位!"
            ))
        else:
            wishes_note = f"承伤 {sim_barrier_mult*100:.1f}% (减伤 {(1-sim_barrier_mult)*100:.1f}%)"
            lines.append(MultiplierLine(
                name="屏障/众愿区",
                gt_val=f"{sim_barrier_mult * 100:.2f}%" if is_hit_match else "待核",
                sim_val=f"{sim_barrier_mult * 100:.2f}%",
                status="MATCH" if is_hit_match else "INFO",
                note=wishes_note
            ))

        # 5. 复合乘区展示 (技能倍率 / 增伤 / 防御 / 抗性 / 易伤) + 净残差精算归因
        sk_mult = float(getattr(bd, "skill_multiplier", 1.0))
        dmg_boost_mult = float(getattr(bd, "dmg_boost_mult", 1.0))
        def_mult = float(getattr(bd, "def_mult", 1.0))
        def_shred = float(getattr(bd, "def_shred", 0.0))
        res_mult = float(getattr(bd, "res_mult", 1.0))
        res_pen = float(getattr(bd, "res_pen", 0.0))
        vuln_mult = float(getattr(bd, "vuln_mult", 1.0))

        comp_status = "MATCH" if is_hit_match else "INFO"
        lines.append(MultiplierLine("技能倍率区", f"{sk_mult*100:.2f}%" if is_hit_match else "—", f"{sk_mult*100:.2f}%", comp_status, "含动态池/星魂独立乘区"))
        lines.append(MultiplierLine("增伤乘区", f"{dmg_boost_mult*100:.2f}%" if is_hit_match else "—", f"{dmg_boost_mult*100:.2f}%", comp_status, f"增伤 +{(dmg_boost_mult-1)*100:.1f}%"))
        lines.append(MultiplierLine("防御乘区", f"{def_mult*100:.2f}%" if is_hit_match else "—", f"{def_mult*100:.2f}%", comp_status, f"减防/无视 {def_shred*100:.1f}%"))
        lines.append(MultiplierLine("抗性乘区", f"{res_mult*100:.2f}%" if is_hit_match else "—", f"{res_mult*100:.2f}%", comp_status, f"抗穿 +{res_pen*100:.1f}%"))
        lines.append(MultiplierLine("易伤乘区", f"{vuln_mult*100:.2f}%" if is_hit_match else "—", f"{vuln_mult*100:.2f}%", comp_status, f"易伤 +{(vuln_mult-1)*100:.1f}%"))

        # 6. 扣除已知面板/韧性/屏障偏差后的【净未解释残差归因】
        if not is_hit_match and g_dmg > 0 and s_dmg > 0:
            raw_sim_over_gt = s_dmg / g_dmg
            residual_sim_over_gt = raw_sim_over_gt / explained_sim_over_gt if explained_sim_over_gt > 0 else raw_sim_over_gt
            residual_gt_over_sim = 1.0 / residual_sim_over_gt if residual_sim_over_gt > 0 else 1.0

            if getattr(bd, "is_true_damage", False) or dt == "True":
                hints.append("【真实伤害联动】真实伤害 = 本动直伤池 × 24% (或晴空乐手气氛比例)，差额直接源自前序直伤命中")
            elif abs(residual_sim_over_gt - 1.0) > 0.0015:
                # 6a. 检查是否由动态蓄水池引起 (小伊卡治疗池 / 风堇大招 / 长夜忆质)
                if attacker in ("小伊卡", "依卡") and "gt_inferred_healing_pool" in pool_info:
                    sim_p = pool_info["accumulated_healing"]
                    gt_p = pool_info["gt_inferred_healing_pool"]
                    hints.append(
                        f"【治疗蓄水池偏差】小伊卡伤害 100% 取决于累计治疗量：SIM 池={sim_p:,.1f} vs GT 等效池={gt_p:,.1f} "
                        f"(池子差额 {sim_p - gt_p:+,.1f}, 占比 {(sim_p/gt_p - 1)*100:+.2f}%)"
                    )
                if attacker == "长夜" and "gt_inferred_yizhi" in pool_info:
                    sim_yz = pool_info["yizhi"]
                    gt_yz = pool_info["gt_inferred_yizhi"]
                    if abs(sim_yz - gt_yz) >= 0.8:
                        hints.append(
                            f"【忆质点数或增伤偏差】SIM 出手忆质={sim_yz} 点；若乘区一致，GT 等效忆质={gt_yz:.2f} 点 "
                            f"(差值 {sim_yz - gt_yz:+.2f} 点)"
                        )

                # 6b. 检验是否精确吻合增伤区差额 (如创世套 +15%、秘技 +30%、专武 +16%)
                if dmg_boost_mult > 1.0:
                    needed_boost_mult = dmg_boost_mult * residual_gt_over_sim
                    boost_delta = (dmg_boost_mult - needed_boost_mult) * 100.0
                    if abs(boost_delta) < 65.0:
                        matched_buff = ""
                        if abs(abs(boost_delta) - 15.0) < 2.5:
                            matched_buff = " -> 高度吻合【再创天地的救世主 4件套 15% 增伤】叠加层数差异!"
                        elif abs(abs(boost_delta) - 16.0) < 2.5:
                            matched_buff = " -> 高度吻合【记忆永不落幕 S5 16% 增伤】覆盖差异!"
                        elif abs(abs(boost_delta) - 30.0) < 3.0:
                            matched_buff = " -> 高度吻合【知更鸟秘技 30% 增伤】或【2层创世套 30% 增伤】差异!"
                        elif abs(abs(boost_delta) - 60.0) < 4.0:
                            matched_buff = " -> 高度吻合【长夜月至暗之谜 60% 增伤】覆盖差异!"
                        hints.append(
                            f"【净残差 -> 增伤假设】扣除已知面板偏差后净残差 {(residual_sim_over_gt-1)*100:+.2f}%："
                            f"若归因于增伤区，SIM 增伤 ({(dmg_boost_mult-1)*100:.1f}%) 比 GT 多算了 {boost_delta:+.2f}%{matched_buff}"
                        )

                # 6c. 检验是否吻合易伤区差额 (如专武虹光 18% 易伤、至暗之谜 30% 易伤、扑翅雀跃 16% 易伤)
                if vuln_mult > 1.0:
                    needed_vuln_mult = vuln_mult * residual_gt_over_sim
                    vuln_delta = (vuln_mult - needed_vuln_mult) * 100.0
                    if abs(vuln_delta) < 45.0:
                        matched_vuln = ""
                        if abs(abs(vuln_delta) - 18.0) < 2.5:
                            matched_vuln = " -> 高度吻合【愿虹光永驻天空 18% 易伤】过期/挂载时序差异!"
                        elif abs(abs(vuln_delta) - 16.0) < 2.5:
                            matched_vuln = " -> 高度吻合【晴空乐手 16% 易伤】覆盖差异!"
                        elif abs(abs(vuln_delta) - 30.0) < 3.0:
                            matched_vuln = " -> 高度吻合【至暗之谜 30% 易伤】覆盖差异!"
                        hints.append(
                            f"【净残差 -> 易伤假设】若归因于易伤区，SIM 易伤 (+{(vuln_mult-1)*100:.1f}%) 比 GT 多算了 {vuln_delta:+.2f}%{matched_vuln}"
                        )

                # 6d. 检验是否吻合减防/无视防御差额
                if def_mult > 0:
                    needed_def_mult = def_mult * residual_gt_over_sim
                    if 0 < needed_def_mult < 1.0:
                        needed_eff_def = (1000.0 / needed_def_mult) - 1000.0
                        needed_shred = 1.0 - (needed_eff_def / 1200.0)
                        shred_delta = (def_shred - needed_shred) * 100.0
                        if abs(shred_delta) < 35.0:
                            matched_def = ""
                            if abs(abs(shred_delta) - 18.0) < 2.5:
                                matched_def = " -> 高度吻合【缇宝 E4 结界 18% 无视防御】!"
                            elif abs(abs(shred_delta) - 30.0) < 3.0:
                                matched_def = " -> 高度吻合【长夜月专武冥花 30% 无视防御】或【知更鸟热潮无视防御】!"
                            hints.append(
                                f"【净残差 -> 防御假设】若归因于减防/无视防御，SIM ({def_shred*100:.1f}%) 比 GT 多算了 {shred_delta:+.2f}%{matched_def}"
                            )

                # 6e. 第一波「灯塔」众愿层数检验
                if gt_target == "「灯塔」" and sim_barrier_mult < 1.0:
                    needed_bar = sim_barrier_mult * residual_gt_over_sim
                    if 0.35 <= needed_bar <= 1.0:
                        sim_wishes = round((1.0 - sim_barrier_mult) / 0.05)
                        gt_wishes = (1.0 - needed_bar) / 0.05
                        if abs(sim_wishes - gt_wishes) <= 3.0:
                            hints.append(
                                f"【灯塔众愿假设】SIM 当前众愿={sim_wishes} 层 (承伤 {sim_barrier_mult*100:.0f}%)，"
                                f"GT 等效众愿={gt_wishes:.2f} 层 (承伤 {needed_bar*100:.1f}%)"
                            )

        return lines, hints


def render_action_report(diag: ActionDiagnosis, hit_filter: Optional[int] = None, verbose: bool = False) -> str:
    """生成高可读性的单动全链路白盒诊断报告。"""
    lines = []
    SEP = "=" * 96
    SUB_SEP = "-" * 96

    match_tag = "[PASS ✓]" if diag.is_action_match else "[DIFF ✗]"
    header_color = Colors.GREEN if diag.is_action_match else Colors.YELLOW
    lines.append(colorize(SEP, Colors.CYAN))
    lines.append(colorize(
        f"[Action #{diag.action_index:02d} 诊断报告] {match_tag} {diag.actor} | 【{diag.skill_name}】 "
        f"| Wave {diag.wave} | AV: {diag.gt_av:.2f} (SIM: {diag.sim_av:.2f})",
        header_color + Colors.BOLD
    ))
    gt_e_str = f"{len(diag.gt_enemies)}怪 ({', '.join(diag.gt_enemies)})"
    sim_e_str = f"{len(diag.sim_enemies)}怪 ({', '.join(diag.sim_enemies)})"
    e_match = len(diag.gt_enemies) == len(diag.sim_enemies)
    lines.append(
        f"在场敌方: GT {gt_e_str} vs SIM {sim_e_str} "
        f"| 首领战前HP: GT {diag.gt_boss_hp:,.0f} vs SIM {diag.sim_boss_hp:,.0f}"
        + ("" if e_match else colorize("  ⚠️ [在场敌人数不一致!]", Colors.RED + Colors.BOLD))
    )

    # 输出动态蓄水池状态
    p = diag.pool_info
    vibes_str = f"晴歌气氛={p.get('vibes', 0)}/{p.get('max_vibes', 60)} (GT气氛={p.get('gt_vibes', 0)})"
    pool_parts = [
        f"长夜忆质={p.get('yizhi', 0)}点({'至暗' if p.get('darkness') else '常态'})",
        f"风堇治疗池={p.get('accumulated_healing', 0.0):,.1f}",
        vibes_str,
    ]
    if "gt_inferred_yizhi" in p:
        pool_parts.append(colorize(f"GT反推忆质≈{p['gt_inferred_yizhi']:.2f}点", Colors.MAGENTA + Colors.BOLD))
    if "gt_inferred_healing_pool" in p:
        pool_parts.append(colorize(
            f"GT反推治疗池≈{p['gt_inferred_healing_pool']:,.1f} (SIM偏差 {p['healing_pool_err_pct']:+.2f}%)",
            Colors.MAGENTA + Colors.BOLD
        ))
    lines.append("动态机制池: " + " | ".join(pool_parts))

    # 输出我方 4 角色实时面板真值对照 (OnStatChange vs SIM)
    party_diffs = []
    for cname in ("长夜月", "缇宝", "风堇", "知更鸟•晴歌"):
        g_st = diag.gt_party_stats.get(cname, {})
        s_st = diag.sim_party_stats.get(cname, {})
        if not g_st or not s_st:
            continue
        g_hp, s_hp = g_st.get("MaxHP", 0.0), s_st.get("MaxHP", 0.0)
        g_cd, s_cd = g_st.get("CriticalDamage", 0.0), s_st.get("CriticalDamage", 0.0)
        # 长夜月 SIM 包含常驻 A6 +0.50 (若已激活)，对照时展示原始值与差值
        hp_ok = abs(s_hp - g_hp) <= 5.0
        cd_ok = abs(s_cd - g_cd) <= 0.015
        if not hp_ok or not cd_ok:
            party_diffs.append(
                f"{cname}[HP: GT {g_hp:,.1f} vs SIM {s_hp:,.1f} ({s_hp-g_hp:+.1f}) | "
                f"暴伤: GT {g_cd*100:.2f}% vs SIM {s_cd*100:.2f}% ({(s_cd-g_cd)*100:+.2f}%)]"
            )
    if party_diffs:
        lines.append(colorize("面板真值差异: " + " ; ".join(party_diffs), Colors.YELLOW))
    else:
        lines.append(colorize("面板真值对照: 四角色 MaxHP 与 CriticalDamage 与实机 OnStatChange 完全吻合 ✓", Colors.GREEN))

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
        t_disp = hit.sim_target if hit.sim_target == hit.gt_target else f"GT:{hit.gt_target} / SIM:{hit.sim_target}"

        lines.append(colorize(
            f"▶ Hit #{hit.hit_index:02d} [{hit.damage_type}] {hit.attacker} -> {t_disp}: "
            f"GT {hit.gt_damage:,.2f} vs SIM {hit.sim_damage:,.2f} ({h_tag})",
            h_color + Colors.BOLD
        ))

        for row in hit.multiplier_lines:
            lines.append(row.format_row())

        if hit.diagnosis_hints:
            lines.append(colorize("  [根因归因定位 💡]", Colors.YELLOW + Colors.BOLD))
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
    lines.append("=" * 118)
    lines.append(
        f"{'动号':4s} | {'AV':6s} | {'行动角色':10s} | {'技能名称':16s} | {'怪数(G/S)':9s} | "
        f"{'GT 真值总伤':14s} | {'SIM 计算总伤':14s} | {'偏差率':9s} | {'核心池状态':16s} | {'状态':4s}"
    )
    lines.append("-" * 118)

    diff_count = 0
    match_count = 0

    for d in diagnoses:
        tag = "PASS" if d.is_action_match else "DIFF"
        color = Colors.GREEN if d.is_action_match else Colors.RED
        if d.is_action_match:
            match_count += 1
        else:
            diff_count += 1
        e_cnt = f"{len(d.gt_enemies)}/{len(d.sim_enemies)}"
        p = d.pool_info
        if d.skill_name == "迷梦，流失，如露":
            pool_str = f"忆质:{p.get('yizhi',0)} (GT≈{p.get('gt_inferred_yizhi', 0):.1f})"
        elif d.skill_name == "乌云乌云快走开！":
            pool_str = f"疗池:{p.get('accumulated_healing',0)/1000:.0f}k({p.get('healing_pool_err_pct',0):+.1f}%)"
        elif d.skill_name == "叽叽啾啾四重奏":
            pool_str = f"气氛:{p.get('vibes',0)}/{p.get('max_vibes',60)}"
        else:
            pool_str = f"首领HP:{d.sim_boss_hp/1e6:.2f}M"

        lines.append(
            f"#{d.action_index:02d} | {d.gt_av:6.2f} | {d.actor:10s} | {d.skill_name[:16]:16s} | {e_cnt:9s} | "
            f"{d.gt_total_dmg:14,.2f} | {d.sim_total_dmg:14,.2f} | {d.total_rel_error:+8.3f}% | "
            f"{pool_str:16s} | {colorize(tag, color)}"
        )

    lines.append("=" * 118)
    lines.append(f"汇总：共 {len(diagnoses)} 动 | 完美达标 (<0.1%): {match_count} 动 | 存在偏差: {diff_count} 动")
    return "\n".join(lines)


def render_full_audit_report(diagnoses: List[ActionDiagnosis]) -> str:
    """输出全场 96 动四大维度白盒聚类体检报告 (--audit)。"""
    out: List[str] = []
    SEP = "=" * 115

    # 1. 三大动态机制蓄水池全场轨迹对账表
    out.append(colorize(SEP, Colors.CYAN))
    out.append(colorize("【一、 三大动态蓄水池全场轨迹对账 (长夜忆质 / 小伊卡累计治疗池 / 晴空乐手气氛值)】", Colors.BOLD + Colors.CYAN))
    out.append("-" * 115)

    out.append(colorize("▸ 1A. 长夜《迷梦，流失，如露》(共 12 次爆发) — 忆质点数与增伤/暴伤对账：", Colors.YELLOW + Colors.BOLD))
    out.append(f"  {'动号':4s} | {'AV':6s} | {'在场怪(G/S)':10s} | {'SIM忆质':8s} | {'GT反推忆质':10s} | {'GT总伤':13s} | {'SIM总伤':13s} | {'伤害偏差':9s} | {'长夜月暴伤(GT / SIM)'}")
    for d in diagnoses:
        if d.skill_name == "迷梦，流失，如露":
            p = d.pool_info
            g_cd = d.gt_party_stats.get("长夜月", {}).get("CriticalDamage", 0.0) * 100
            s_cd = d.sim_party_stats.get("长夜月", {}).get("CriticalDamage", 0.0) * 100
            sp_cd = d.sim_party_stats.get("长夜", {}).get("CriticalDamage", 0.0) * 100
            out.append(
                f"  #{d.action_index:02d} | {d.gt_av:6.2f} | {len(d.gt_enemies):4d}/{len(d.sim_enemies):<5d} | "
                f"{p.get('yizhi', 0):6d}点 | {p.get('gt_inferred_yizhi', 0.0):8.2f}点 | "
                f"{d.gt_total_dmg:13,.1f} | {d.sim_total_dmg:13,.1f} | {d.total_rel_error:+8.2f}% | "
                f"本体 {g_cd:.1f}%/{s_cd:.1f}% (长夜 {sp_cd:.1f}%)"
            )

    out.append("")
    out.append(colorize("▸ 1B. 小伊卡《乌云乌云快走开！》(共 9 次出手) — 累计治疗蓄水池 (accumulated_healing) 对账：", Colors.YELLOW + Colors.BOLD))
    out.append(f"  {'动号':4s} | {'AV':6s} | {'在场怪(G/S)':10s} | {'SIM治疗池':13s} | {'GT等效治疗池':13s} | {'池偏差%':9s} | {'GT总伤':13s} | {'SIM总伤':13s} | {'伤害偏差':9s} | {'风堇暴伤(GT / SIM)'}")
    for d in diagnoses:
        if d.skill_name == "乌云乌云快走开！":
            p = d.pool_info
            g_cd = d.gt_party_stats.get("风堇", {}).get("CriticalDamage", 0.0) * 100
            s_cd = d.sim_party_stats.get("风堇", {}).get("CriticalDamage", 0.0) * 100
            out.append(
                f"  #{d.action_index:02d} | {d.gt_av:6.2f} | {len(d.gt_enemies):4d}/{len(d.sim_enemies):<5d} | "
                f"{p.get('accumulated_healing', 0.0):13,.1f} | {p.get('gt_inferred_healing_pool', 0.0):13,.1f} | "
                f"{p.get('healing_pool_err_pct', 0.0):+8.2f}% | "
                f"{d.gt_total_dmg:13,.1f} | {d.sim_total_dmg:13,.1f} | {d.total_rel_error:+8.2f}% | "
                f"{g_cd:.1f}% / {s_cd:.1f}%"
            )

    out.append("")
    out.append(colorize("▸ 1C. 晴空乐手《叽叽啾啾四重奏》(共 9 次出手) — 气氛值 (vibes) 与面板对账：", Colors.YELLOW + Colors.BOLD))
    out.append(f"  {'动号':4s} | {'AV':6s} | {'在场怪(G/S)':10s} | {'SIM气氛值':10s} | {'咚咚/啪啪':9s} | {'GT总伤':13s} | {'SIM总伤':13s} | {'伤害偏差':9s} | {'晴歌暴伤(GT / SIM)'}")
    for d in diagnoses:
        if d.skill_name == "叽叽啾啾四重奏":
            p = d.pool_info
            g_cd = d.gt_party_stats.get("知更鸟•晴歌", {}).get("CriticalDamage", 0.0) * 100
            s_cd = d.sim_party_stats.get("知更鸟•晴歌", {}).get("CriticalDamage", 0.0) * 100
            dp = f"{'Y' if p.get('has_drummie') else 'N'}/{'Y' if p.get('has_paddie') else 'N'}"
            out.append(
                f"  #{d.action_index:02d} | {d.gt_av:6.2f} | {len(d.gt_enemies):4d}/{len(d.sim_enemies):<5d} | "
                f"{p.get('vibes', 0):4d}/{p.get('max_vibes', 60):<4d} | {dp:9s} | "
                f"{d.gt_total_dmg:13,.1f} | {d.sim_total_dmg:13,.1f} | {d.total_rel_error:+8.2f}% | "
                f"{g_cd:.1f}% / {s_cd:.1f}%"
            )

    # 2. 首领血量与屏障关键节点对账表
    out.append("")
    out.append(colorize(SEP, Colors.CYAN))
    out.append(colorize("【二、 首领血量轨迹与血脑屏障/众愿关键节点对账 (GT vs SIM)】", Colors.BOLD + Colors.CYAN))
    out.append("-" * 115)
    out.append(f"  {'动号':4s} | {'AV':6s} | {'行动角色':10s} | {'技能名称':16s} | {'GT首领战前HP':14s} | {'SIM首领战前HP':14s} | {'首领HP差额':13s} | {'SIM首领减伤':10s} | {'本动伤害偏差'}")
    key_acts = [1, 3, 6, 8, 12, 17, 18, 24, 25, 35, 40, 41, 42, 43, 45, 47, 48, 53, 54, 59, 60, 61, 66, 69, 71, 74, 83, 86, 87, 96]
    for idx in key_acts:
        if 1 <= idx <= len(diagnoses):
            d = diagnoses[idx - 1]
            p = d.pool_info
            hp_diff = d.sim_boss_hp - d.gt_boss_hp
            out.append(
                f"  #{d.action_index:02d} | {d.gt_av:6.2f} | {d.actor:10s} | {d.skill_name[:16]:16s} | "
                f"{d.gt_boss_hp:14,.0f} | {d.sim_boss_hp:14,.0f} | {hp_diff:+13,.0f} | "
                f"{p.get('boss_dr', 0.0)*100:8.1f}% | {d.total_rel_error:+8.2f}%"
            )

    # 3. 我方 4 角色 OnStatChange 面板 (MaxHP & CriticalDamage) 异常监控表
    out.append("")
    out.append(colorize(SEP, Colors.CYAN))
    out.append(colorize("【三、 全队 4 角色实时面板 (OnStatChange MaxHP & 暴伤) 偏差监控表】", Colors.BOLD + Colors.CYAN))
    out.append("-" * 115)
    panel_mismatch_rows = []
    for d in diagnoses:
        row_items = []
        for cname in ("长夜月", "缇宝", "风堇", "知更鸟•晴歌"):
            g_st = d.gt_party_stats.get(cname, {})
            s_st = d.sim_party_stats.get(cname, {})
            if not g_st or not s_st:
                continue
            g_hp, s_hp = g_st.get("MaxHP", 0.0), s_st.get("MaxHP", 0.0)
            g_cd, s_cd = g_st.get("CriticalDamage", 0.0), s_st.get("CriticalDamage", 0.0)
            hp_diff = s_hp - g_hp
            cd_diff = (s_cd - g_cd) * 100.0
            if abs(hp_diff) > 5.0 or abs(cd_diff) > 1.5:
                parts = []
                if abs(hp_diff) > 5.0:
                    parts.append(f"HP:{g_hp:.0f}->{s_hp:.0f}({hp_diff:+.0f})")
                if abs(cd_diff) > 1.5:
                    parts.append(f"CD:{g_cd*100:.1f}%->{s_cd*100:.1f}%({cd_diff:+.1f}%)")
                row_items.append(f"{cname}[{', '.join(parts)}]")
        if row_items:
            panel_mismatch_rows.append(f"  #{d.action_index:02d} (AV {d.gt_av:6.2f} {d.actor:8s} {d.skill_name[:12]:12s}): " + " | ".join(row_items))

    if panel_mismatch_rows:
        out.extend(panel_mismatch_rows[:35])
        if len(panel_mismatch_rows) > 35:
            out.append(f"  ... 其余 {len(panel_mismatch_rows) - 35} 动面板差异已折叠")
    else:
        out.append(colorize("  全队 4 角色在全部 96 动中的实时 MaxHP 与 CriticalDamage 与实机 100% 吻合！", Colors.GREEN))

    # 4. 534 发命中目标与破韧状态一致性统计
    out.append("")
    out.append(colorize(SEP, Colors.CYAN))
    out.append(colorize("【四、 全场 534 发命中索敌目标与破韧状态一致性统计】", Colors.BOLD + Colors.CYAN))
    out.append("-" * 115)
    total_hits = 0
    target_matches = 0
    tough_matches = 0
    mismatched_examples = []
    for d in diagnoses:
        for h in d.hits:
            total_hits += 1
            t_ok = (h.gt_target == h.sim_target) or (h.gt_target.startswith("千星戍卫") and h.sim_target.startswith("千星戍卫")) or (h.gt_target.startswith("狂兽的胚芽") and h.sim_target.startswith("狂兽的胚芽"))
            if t_ok:
                target_matches += 1
            else:
                mismatched_examples.append(f"  Act #{d.action_index:02d} Hit #{h.hit_index:02d} [{h.damage_type}]: GT->{h.gt_target} vs SIM->{h.sim_target}")

            if h.gt_target_stance is not None and h.breakdown is not None:
                if getattr(h.breakdown, "is_true_damage", False):
                    tough_matches += 1
                else:
                    gt_tm = 0.90 if h.gt_target_stance > 0 else 1.00
                    if abs(getattr(h.breakdown, "reduction_mult", 1.0) - gt_tm) < 0.01:
                        tough_matches += 1

    out.append(f"  命中段数对齐: {total_hits} / 534 发")
    out.append(f"  索敌目标一致: {target_matches} / {total_hits} 发 ({target_matches/max(1,total_hits)*100:.2f}%)")
    out.append(f"  破韧乘数一致: {tough_matches} / {total_hits} 发 ({tough_matches/max(1,total_hits)*100:.2f}%)")
    if mismatched_examples:
        out.append(colorize("  索敌错位明细 (前 10 项):", Colors.YELLOW))
        out.extend(mismatched_examples[:10])
    out.append(colorize(SEP, Colors.CYAN))
    return "\n".join(out)


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
        description="星铁模拟器一键乘区 Diff 与全链路白盒诊断工具 (Per-Action Multiplier & White-Box Audit Tool)"
    )
    parser.add_argument(
        "actions",
        nargs="*",
        help="待诊断动作编号，支持单个 (如 12 或 #12)、多个 (如 12 13 14) 或区间 (如 12-17)",
    )
    parser.add_argument(
        "-a", "--audit",
        action="store_true",
        help="输出全场 96 动四大维度白盒聚类体检报告 (动态蓄水池/首领HP与屏障/四角色实时面板/索敌对齐)",
    )
    parser.add_argument(
        "-d", "--diff-only",
        action="store_true",
        help="扫荡全场 96 动，仅诊断并输出有偏差 (>0.1%%) 的动作",
    )
    parser.add_argument(
        "-s", "--summary",
        action="store_true",
        help="输出全场 96 动紧凑对账汇总表 (含动态池与首领HP监控列)",
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

    if args.audit:
        diagnoses = [MultiplierDiagnosticsEngine.diagnose_action(i) for i in range(1, total_actions + 1)]
        valid_diagnoses = [d for d in diagnoses if d is not None]
        print(render_full_audit_report(valid_diagnoses))
        return

    if args.summary:
        diagnoses = [MultiplierDiagnosticsEngine.diagnose_action(i) for i in range(1, total_actions + 1)]
        valid_diagnoses = [d for d in diagnoses if d is not None]
        print(render_summary_table(valid_diagnoses))
        return

    target_action_indices: List[int] = []
    if args.actions:
        for a in args.actions:
            target_action_indices.extend(parse_action_arg(a))

    target_action_indices = sorted(set(idx for idx in target_action_indices if 1 <= idx <= total_actions))

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

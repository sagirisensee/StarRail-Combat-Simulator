# coding: utf-8
"""通用官方日志 → ConfigAbility VM 对账运行器与测试生成器。

给定任意 ``battle_logs/battle_*.jsonl``：
1. 自动解析 ``OnBattleBegin`` 获取 ``stage_id``；
2. 自动扫描参战我方角色 UID，从 ``CharacterDB`` 装配官方 VM 队伍；
3. 自动从实机日志抽取：
   - 敌方 UID 映射（``enemy_uid_map``）
   - 我方辅助单点技能目标（如知更鸟•晴歌终结技拉条目标）
   - 敌方风行再动判定（同 AV 同敌方 UID 连续行动）
   - 阿哈随机弹射回合（``turn_owner=None`` 且无技能施放时的敌方扣血与我方伴生扣血）
   - 敌方回合受击目标与扩散目标，并结合「差额反推 + 被动奶 O(1) 判别 + 有界二次确认（含 Buff/跳过回合 vs 命中忆灵）」自动补全忆灵受击；
   （若存在同名 ``simulator/plugins/log_<tag>.py`` 且未指定 ``--no-plugin``，可优先复用）
4. 依据 ``stage_id`` 自动路由至对应关卡构建器或纯数据驱动 ``build_data_driven_stage(stage_id)``；
5. 输出逐动误差诊断报告（拆分 Servant / LC_Additional / Other 偏差），并可选生成标准 ``unittest`` 对账脚本。
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from simulator.db.character_db import CharacterDB
from simulator.golden_diff import (
    attach_exact_crit_oracle,
    diff_sequences,
    extract_timeline,
    parse_golden_jsonl,
    run_trajectory_replay,
)
from simulator.stage_30126122 import build_stage_30126122
from simulator.vm.factory import DEFAULT_CHAR_DB_PATH, UID_TO_NAME, build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_sim_adapter import build_data_driven_stage

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_SENTINEL = "__SKIP__"


@dataclass
class EnemyHitRecord:
    """从实机日志敌方回合自动提取的我方受击目标记录。"""

    av: float
    enemy_uid: int
    hit_allies: List[str] = field(default_factory=list)
    hit_counts: Dict[str, int] = field(default_factory=dict)
    had_hp_drop: bool = False
    had_passive_heal: bool = False


@dataclass
class AhaTurnRecord:
    """从实机日志自动提取的阿哈回合（敌方弹射扣血 + 我方伴生微伤）。"""

    av: float
    enemy_damages: List[Tuple[int, float]] = field(default_factory=list)  # (enemy_uid, dmg)
    ally_chip_hits: List[str] = field(default_factory=list)


@dataclass
class AmbiguousMemospriteSlot:
    """敌方回合内存在差额 (missing_hits > 0) 且有多种分配候选的待确认位点。"""

    key: Tuple[float, int, str]  # (av, enemy_uid, kind: "primary" | "blast" | "bounce")
    av: float
    enemy_uid: int
    kind: str
    candidates: List[Tuple[str, ...]]  # 每个候选为目标元组（空元组=无额外扩散；(SKIP_SENTINEL,)=敌方非攻击回合）
    default_choice: Tuple[str, ...]


@dataclass
class InferredMemospriteHit:
    """差额反推或二次确认锁定的忆灵受击/敌方跳过记录。"""

    av: float
    enemy_uid: int
    kind: str
    targets: Tuple[str, ...]
    source: str  # "passive_heal_o1" | "deficit_single" | "blast_adjacent" | "second_pass_confirmed"


@dataclass
class LogMetadata:
    """从实机战斗日志提取的通用元信息。"""

    log_path: str
    tag: str
    stage_id: int
    team_uids: List[int]
    team_names: List[str]
    enemy_hits: List[EnemyHitRecord]
    final_av: float
    enemy_uid_map: Dict[int, str] = field(default_factory=dict)
    ally_ult_targets: Dict[str, List[str]] = field(default_factory=dict)  # caster_name -> [target_name, ...]
    player_enemy_targets: Dict[Tuple[float, str], List[str]] = field(default_factory=dict)  # (av, caster_name) -> [enemy_name, ...]
    aha_turns: List[AhaTurnRecord] = field(default_factory=list)
    windwalk_enemy_uids: Set[int] = field(default_factory=set)
    slow_hits: Set[Tuple[float, str]] = field(default_factory=set)  # (av, target_name) 敌方回合内发生减速的命中记录


@dataclass
class TurnDiffEntry:
    """单动伤害对比条目。"""

    av: float
    gt_total: float
    sim_total: float
    err: float
    attackers: List[str]
    breakdown: Dict[str, Tuple[float, float]]


@dataclass
class ReconcileReport:
    """通用对账运行结果。"""

    meta: LogMetadata
    stage_mode: str
    plugin_mode: str
    turn_matched: int
    turn_total: int
    ult_matched: int
    ult_total: int
    sp_granted: int
    memoria_granted: float
    presence_grants: int
    forced_or_failed: int
    golden_total_damage: float
    sim_total_damage: float
    total_err: float
    max_turn_err: float
    turn_diffs: List[TurnDiffEntry]
    inferred_memosprite_hits: List[InferredMemospriteHit] = field(default_factory=list)
    unresolved_ambiguous_slots: int = 0


def _extract_tag(log_path: str) -> str:
    base = os.path.basename(log_path)
    m = re.search(r"battle_(\d{8}_\d{6})", base)
    if m:
        return m.group(1)
    return os.path.splitext(base)[0]


def _resolve_uid_name(uid: int, db: CharacterDB) -> str:
    if uid in UID_TO_NAME:
        return UID_TO_NAME[uid]
    rp = db.get(uid)
    if rp is not None:
        return rp.name
    return f"UID_{uid}"


def extract_log_metadata(
    log_path: str,
    *,
    db: Optional[CharacterDB] = None,
    team_override: Optional[Sequence[str]] = None,
) -> LogMetadata:
    """扫描实机 JSONL，自动提取 stage_id、参战阵容、敌方 UID 映射、受击/阿哈/拉条目标与风行再动。"""
    char_db = db if db is not None else CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    stage_id = 0
    seen_uids: List[int] = []
    seen_uid_set: Set[int] = set()

    # 敌方 UID 映射追踪
    initial_enemy_uids: List[int] = []
    seen_init_enemy_uids: Set[int] = set()
    enemy_uid_map: Dict[int, str] = {}
    eagle_spawn_count = 0
    sprout_spawn_count = 0
    saw_first_init_enemy = False

    # 回合态追踪
    cur_av = 0.0
    cur_turn_owner_team: Optional[str] = None
    cur_enemy_uid: Optional[int] = None
    prev_enemy_turn: Optional[Tuple[float, int]] = None
    windwalk_enemy_uids: Set[int] = set()

    cur_hit_order: List[str] = []
    cur_hit_set: Set[str] = set()
    cur_hit_counts: Dict[str, int] = {}
    cur_small_heal_uids: Set[int] = set()

    # 无归属回合（阿哈回合）追踪
    cur_none_had_skill = False
    cur_none_enemy_dmgs: List[Tuple[int, float]] = []
    cur_none_ally_chips: List[str] = []

    # 辅助单点终结技（如 151203 知更鸟•晴歌）目标追踪 & 我方单体/扩散攻击敌方主目标追踪
    pending_ally_ult_caster: Optional[str] = None
    ally_ult_targets: Dict[str, List[str]] = {}
    pending_player_atk: Optional[Tuple[float, str]] = None
    pending_player_hit_euids: List[int] = []
    pending_player_primary_dmg_hits = 0
    player_enemy_targets_raw: Dict[Tuple[float, str], List[int]] = {}

    def _flush_pending_player_atk() -> None:
        nonlocal pending_player_atk, pending_player_hit_euids, pending_player_primary_dmg_hits
        if pending_player_atk is not None:
            # 仅对纯单体技能（主技能 OnDamage 命中数 == 1，如风堇普攻）记录首个扣血敌方为主目标；
            # 扩散/群攻（主技能 OnDamage 命中数 > 1，如缇宝普攻）由默认居中逻辑处理
            if pending_player_primary_dmg_hits == 1 and pending_player_hit_euids:
                player_enemy_targets_raw.setdefault(pending_player_atk, []).append(pending_player_hit_euids[0])
        pending_player_atk = None
        pending_player_hit_euids = []
        pending_player_primary_dmg_hits = 0

    last_player_hp: Dict[int, float] = {}
    last_player_spd: Dict[int, float] = {}
    slow_hits: Set[Tuple[float, str]] = set()
    last_enemy_hp: Dict[int, float] = {}
    enemy_hits: List[EnemyHitRecord] = []
    aha_turns: List[AhaTurnRecord] = []

    def _flush_turn() -> None:
        nonlocal cur_enemy_uid, cur_hit_order, cur_hit_set, cur_hit_counts, cur_small_heal_uids
        nonlocal cur_turn_owner_team, cur_none_had_skill, cur_none_enemy_dmgs, cur_none_ally_chips
        if cur_enemy_uid is not None:
            enemy_hits.append(
                EnemyHitRecord(
                    av=round(cur_av, 2),
                    enemy_uid=cur_enemy_uid,
                    hit_allies=list(cur_hit_order),
                    hit_counts=dict(cur_hit_counts),
                    had_hp_drop=bool(cur_hit_order),
                    had_passive_heal=len(cur_small_heal_uids) >= 2,
                )
            )
        elif cur_turn_owner_team is None and not cur_none_had_skill and cur_none_ally_chips:
            # 真实阿哈回合必含我方伴生微伤（过滤无我方微伤的 Boss 紫色球体/破盾扣血等系统回合）
            filtered_dmgs = [(u, d) for u, d in cur_none_enemy_dmgs if d < 500_000.0]
            aha_turns.append(
                AhaTurnRecord(
                    av=round(cur_av, 2),
                    enemy_damages=filtered_dmgs,
                    ally_chip_hits=list(cur_none_ally_chips),
                )
            )
        cur_enemy_uid = None
        cur_hit_order = []
        cur_hit_set = set()
        cur_hit_counts = {}
        cur_small_heal_uids = set()
        cur_none_had_skill = False
        cur_none_enemy_dmgs = []
        cur_none_ally_chips = []

    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            ev = obj.get("event")
            data = obj.get("data") or {}

            if ev == "OnBattleBegin":
                stage_id = int(data.get("stage_id") or 0)
            elif ev == "OnInitializeEnemy":
                saw_first_init_enemy = True
                enemy = data.get("enemy") or {}
                euid = int(enemy.get("uid") or 0)
                ename = str(enemy.get("name") or "")
                props = (enemy.get("base_stats") or {}).get("properties") or {}
                if euid and "CurrentHP" in props:
                    last_enemy_hp[euid] = float(props["CurrentHP"])
                if euid:
                    if ename == "流星铁鹰":
                        eagle_spawn_count += 1
                        gen = (eagle_spawn_count - 1) // 3 + 1
                        idx = (eagle_spawn_count - 1) % 3 + 1
                        enemy_uid_map[euid] = f"流星铁鹰_g{gen}_{idx}"
                    elif ename == "狂兽的胚芽":
                        sprout_spawn_count += 1
                        enemy_uid_map[euid] = f"狂兽的胚芽{sprout_spawn_count}"
                    elif ename:
                        enemy_uid_map[euid] = ename
            elif ev == "OnTurnBegin":
                _flush_pending_player_atk()
                _flush_turn()
                cur_av = float(data.get("action_value", cur_av))
                owner = data.get("turn_owner")
                if isinstance(owner, dict):
                    cur_turn_owner_team = owner.get("team")
                    if cur_turn_owner_team == "Enemy":
                        euid = int(owner.get("uid") or 0)
                        cur_enemy_uid = euid
                        if prev_enemy_turn is not None and abs(prev_enemy_turn[0] - cur_av) < 0.05 and prev_enemy_turn[1] == euid:
                            windwalk_enemy_uids.add(euid)
                        prev_enemy_turn = (cur_av, euid)
                    else:
                        prev_enemy_turn = None
                else:
                    cur_turn_owner_team = None
                    prev_enemy_turn = None
                pending_ally_ult_caster = None
                _flush_pending_player_atk()
            elif ev == "OnUseSkill":
                _flush_pending_player_atk()
                if cur_turn_owner_team is None:
                    cur_none_had_skill = True
                av_ent = data.get("avatar") or {}
                if av_ent.get("team") == "Player":
                    uid = int(av_ent.get("uid") or 0)
                    if uid and uid not in seen_uid_set:
                        seen_uid_set.add(uid)
                        seen_uids.append(uid)
                    skill = data.get("skill") or {}
                    sk_id = int(skill.get("skill_config_id") or 0)
                    sk_type = str(skill.get("type") or "")
                    cname = _resolve_uid_name(uid, char_db)
                    if sk_id == 151203:
                        pending_ally_ult_caster = cname
                    elif sk_type in ("Normal", "BPSkill", "Ultra"):
                        pending_player_atk = (round(cur_av, 2), cname)
            elif ev == "OnDamage":
                if pending_player_atk is not None:
                    dtype = str(data.get("type") or "")
                    if dtype in ("Basic", "Normal", "Skill", "BPSkill", "Ultimate", "Ultra"):
                        pending_player_primary_dmg_hits += 1
            elif ev == "OnStatChange":
                ent = data.get("entity") or {}
                team_tag = ent.get("team")
                uid = int(ent.get("uid") or 0)
                prop = data.get("property") or {}
                ptype = prop.get("type")
                val = float(prop.get("value", 0.0))

                if team_tag == "Enemy" and uid:
                    if not saw_first_init_enemy and uid not in seen_init_enemy_uids:
                        seen_init_enemy_uids.add(uid)
                        initial_enemy_uids.append(uid)
                    if ptype == "CurrentHP":
                        prev = last_enemy_hp.get(uid)
                        if cur_turn_owner_team is None and not cur_none_had_skill and prev is not None and val < prev - 1.0:
                            cur_none_enemy_dmgs.append((uid, prev - val))
                        elif pending_player_atk is not None and (prev is None or val < prev - 1.0):
                            pending_player_hit_euids.append(uid)
                        last_enemy_hp[uid] = val
                elif team_tag == "Player" and uid:
                    if uid not in seen_uid_set:
                        seen_uid_set.add(uid)
                        seen_uids.append(uid)
                    if pending_ally_ult_caster is not None and ptype == "ActionDelay" and val < -1.0:
                        tgt_name = _resolve_uid_name(uid, char_db)
                        ally_ult_targets.setdefault(pending_ally_ult_caster, []).append(tgt_name)
                        pending_ally_ult_caster = None
                    if ptype == "MaxHP":
                        if uid not in last_player_hp:
                            last_player_hp[uid] = val
                    elif ptype == "Speed":
                        prev_spd = last_player_spd.get(uid)
                        if cur_enemy_uid is not None and prev_spd is not None and val < prev_spd - 1.0:
                            slow_hits.add((round(cur_av, 2), _resolve_uid_name(uid, char_db)))
                        last_player_spd[uid] = val
                    elif ptype == "CurrentHP":
                        prev = last_player_hp.get(uid)
                        if cur_enemy_uid is not None and prev is not None:
                            if 120.0 <= val <= 550.0 and val < prev * 0.35:
                                cur_small_heal_uids.add(uid)
                            elif val < prev - 1e-3 and (prev - val) < prev * 0.60:
                                name = _resolve_uid_name(uid, char_db)
                                if name not in cur_hit_set:
                                    cur_hit_set.add(name)
                                    cur_hit_order.append(name)
                                cur_hit_counts[name] = cur_hit_counts.get(name, 0) + 1
                        elif cur_turn_owner_team is None and not cur_none_had_skill and prev is not None:
                            # 阿哈回合我方伴生微伤（通常 0.1~5.0 点 HP）
                            delta = prev - val
                            if 0.05 <= delta <= 10.0:
                                cur_none_ally_chips.append(_resolve_uid_name(uid, char_db))
                        if prev is None or val >= prev * 0.40:
                            last_player_hp[uid] = val

    _flush_pending_player_atk()
    _flush_turn()

    # 为 stage 30126122 的 Wave 1 初始双怪自动补全 UID 映射（较小 UID=月夜天马，较大 UID=正阳狮鹫）
    if stage_id == 30126122 and len(initial_enemy_uids) >= 2:
        sorted_init = sorted(initial_enemy_uids)[:2]
        enemy_uid_map.setdefault(sorted_init[0], "月夜天马")
        enemy_uid_map.setdefault(sorted_init[1], "正阳狮鹫")

    player_enemy_targets: Dict[Tuple[float, str], List[str]] = {}
    for k_pt, euids in player_enemy_targets_raw.items():
        names = [enemy_uid_map[u] for u in euids if u in enemy_uid_map]
        if names:
            player_enemy_targets[k_pt] = names

    if team_override:
        team_names = list(team_override)
        team_uids = []
        for n in team_names:
            rp = char_db.get_by_name(n)
            if rp is not None:
                team_uids.append(int(rp.avatar_id))
            else:
                matched = [u for u, nm in UID_TO_NAME.items() if nm == n]
                team_uids.append(matched[0] if matched else 0)
    else:
        valid_uids = [u for u in seen_uids if u in UID_TO_NAME or char_db.get(u) is not None]
        if 1409 in valid_uids:
            valid_uids = [1409] + [u for u in valid_uids if u != 1409]
        team_uids = valid_uids
        team_names = [_resolve_uid_name(u, char_db) for u in valid_uids]

    return LogMetadata(
        log_path=os.path.abspath(log_path),
        tag=_extract_tag(log_path),
        stage_id=stage_id,
        team_uids=team_uids,
        team_names=team_names,
        enemy_hits=enemy_hits,
        final_av=cur_av,
        enemy_uid_map=enemy_uid_map,
        ally_ult_targets=ally_ult_targets,
        player_enemy_targets=player_enemy_targets,
        aha_turns=aha_turns,
        windwalk_enemy_uids=windwalk_enemy_uids,
        slow_hits=slow_hits,
    )


def _is_memosprite(ent: Any) -> bool:
    return bool(getattr(ent, "is_memosprite", False))


def attach_auto_rng_plugin(
    sim: Any,
    meta: LogMetadata,
    *,
    memosprite_overrides: Optional[Dict[Tuple[float, int, str], Tuple[str, ...]]] = None,
    ambiguous_out: Optional[List[AmbiguousMemospriteSlot]] = None,
    inferred_out: Optional[List[InferredMemospriteHit]] = None,
) -> None:
    """挂载全自动 RNG 先知（敌方 UID 映射、辅助拉条、风行再动、阿哈弹射、差额忆灵反推与跳过回合判别）。"""
    overrides = memosprite_overrides or {}

    # 1. 自动设置 enemy_uid_map
    if meta.enemy_uid_map:
        sim.enemy_uid_map = dict(meta.enemy_uid_map)

    # 2. 自动风行再动判定（流星铁鹰）
    windwalk_names: Set[str] = {meta.enemy_uid_map[u] for u in meta.windwalk_enemy_uids if u in meta.enemy_uid_map}

    def _enemy_windwalk_provider(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in windwalk_names

    sim.enemy_windwalk_provider = _enemy_windwalk_provider

    # 3. 敌方非攻击/跳过回合判定（来自二次确认锁定的 SKIP_SENTINEL）
    skip_av_names: Set[Tuple[float, str]] = set()
    for (ov_av, ov_uid, ov_kind), ov_val in overrides.items():
        if ov_kind == "primary" and ov_val == (SKIP_SENTINEL,):
            ename = meta.enemy_uid_map.get(ov_uid, "")
            skip_av_names.add((ov_av, ename))

    def _enemy_attack_skip_provider(attacker: Any, av: float) -> bool:
        aname = str(getattr(attacker, "name", "") or "")
        for s_av, s_name in skip_av_names:
            if abs(av - s_av) < 0.05 and (not s_name or s_name == aname):
                return True
        return False

    sim.enemy_attack_skip_provider = _enemy_attack_skip_provider

    # 3.5. 自动减速 Debuff 命中判定（狂兽的胚芽等，依据敌方回合内 Speed 下降直接还原）
    def _debuff_hit_provider(attacker: Any, target: Any, key: str, av: float) -> bool:
        if key == "BeastSprout_Slow":
            tname = str(getattr(target, "name", "") or "")
            return any(abs(av - s_av) < 0.25 and s_name == tname for s_av, s_name in meta.slow_hits)
        return True

    sim.debuff_hit_provider = _debuff_hit_provider

    # 4. 自动阿哈回合处理器（直接回放日志中的敌方弹射扣血与我方伴生微伤）
    if meta.aha_turns:
        triggered_aha: Set[int] = set()

        def _auto_aha_handler(director: Any) -> None:
            director.suppress_aha_sprout_advance = True
            av = float(getattr(sim, "current_av", 0.0))
            for idx, rec in enumerate(meta.aha_turns):
                if idx in triggered_aha:
                    continue
                if av >= rec.av - 1e-6:
                    triggered_aha.add(idx)
                    if hasattr(sim, "_action_seq"):
                        sim._action_seq += 1
                    # 合并同敌方目标的多段伤害或逐段施加
                    for euid, dmg in rec.enemy_damages:
                        ename = meta.enemy_uid_map.get(euid)
                        if ename and hasattr(director, "apply_aha_hp_damage"):
                            director.apply_aha_hp_damage(ename, dmg)
                    for aname in rec.ally_chip_hits:
                        if hasattr(director, "apply_aha_ally_chip_hit"):
                            director.apply_aha_ally_chip_hit(aname)
                    if hasattr(director, "flush_ally_talent_heals"):
                        director.flush_ally_talent_heals()

        sim.aha_special_handler = _auto_aha_handler

    # 5. 受击目标 & 扩散目标（含差额反推 + 被动奶 O(1) + 辅助单点目标）
    recs_by_av: Dict[float, List[EnemyHitRecord]] = {}
    for rec in meta.enemy_hits:
        recs_by_av.setdefault(rec.av, []).append(rec)

    cursor_by_av: Dict[float, int] = {}
    active_rec_by_av: Dict[float, EnemyHitRecord] = {}
    ally_ult_cursor: Dict[str, int] = {}
    recorded_ambig_keys: Set[Tuple[float, int, str]] = set()
    recorded_inf_keys: Set[Tuple[float, int, str]] = set()

    def _find_ally(living: List[Any], name: str) -> Optional[Any]:
        for ent in living:
            if getattr(ent, "name", None) == name:
                return ent
        return None

    def _living_memosprites(living: List[Any]) -> List[Any]:
        return [e for e in living if _is_memosprite(e)]

    def _match_av_key(av: float) -> Optional[float]:
        key = round(av, 2)
        for cand_av in recs_by_av:
            if abs(cand_av - key) <= 0.05:
                return cand_av
        return None

    def _record_inf(av: float, uid: int, kind: str, targets: Tuple[str, ...], source: str) -> None:
        if inferred_out is None:
            return
        k = (av, uid, kind)
        if k not in recorded_inf_keys:
            recorded_inf_keys.add(k)
            inferred_out.append(InferredMemospriteHit(av=av, enemy_uid=uid, kind=kind, targets=targets, source=source))

    def _record_ambig(
        av: float,
        uid: int,
        kind: str,
        candidates: List[Tuple[str, ...]],
        default_choice: Tuple[str, ...],
    ) -> None:
        if ambiguous_out is None or len(candidates) <= 1:
            return
        k = (av, uid, kind)
        if k not in recorded_ambig_keys:
            recorded_ambig_keys.add(k)
            ambiguous_out.append(
                AmbiguousMemospriteSlot(
                    key=k,
                    av=av,
                    enemy_uid=uid,
                    kind=kind,
                    candidates=candidates,
                    default_choice=default_choice,
                )
            )

    def _pick_memosprite_by_passive_signal(
        rec: EnemyHitRecord,
        memos: List[Any],
        kind: str,
    ) -> Optional[Any]:
        if not memos:
            return None
        ov_key = (rec.av, rec.enemy_uid, kind)
        if ov_key in overrides:
            chosen_names = overrides[ov_key]
            if chosen_names and chosen_names != (SKIP_SENTINEL,):
                ent = _find_ally(memos, chosen_names[0])
                if ent is not None:
                    _record_inf(rec.av, rec.enemy_uid, kind, (ent.name,), "second_pass_confirmed")
                    return ent

        non_ica = [m for m in memos if m.name != "小伊卡"]
        ica = _find_ally(memos, "小伊卡")

        if rec.had_passive_heal and non_ica:
            chosen = non_ica[0]
            _record_inf(rec.av, rec.enemy_uid, kind, (chosen.name,), "passive_heal_o1")
            if len(non_ica) > 1:
                _record_ambig(rec.av, rec.enemy_uid, kind, [(m.name,) for m in non_ica], (chosen.name,))
            return chosen

        if not rec.had_passive_heal and ica is not None:
            _record_inf(rec.av, rec.enemy_uid, kind, (ica.name,), "passive_heal_o1")
            # 0 角色掉血 + 0 被动奶：可能是“打中小伊卡”，也可能是“敌方非攻击/增益回合(SKIP)”
            cands: List[Tuple[str, ...]] = [(ica.name,)]
            if kind == "primary":
                cands.append((SKIP_SENTINEL,))
            for m in non_ica:
                cands.append((m.name,))
            _record_ambig(rec.av, rec.enemy_uid, kind, cands, (ica.name,))
            return ica

        chosen = memos[0]
        _record_inf(rec.av, rec.enemy_uid, kind, (chosen.name,), "deficit_single")
        cands = [(m.name,) for m in memos]
        if kind == "primary" and not rec.had_passive_heal:
            cands.append((SKIP_SENTINEL,))
        if len(cands) > 1:
            _record_ambig(rec.av, rec.enemy_uid, kind, cands, (chosen.name,))
        return chosen

    def _target_provider(attacker: Any, living: List[Any], hit_idx: int) -> Optional[Any]:
        att_name = str(getattr(attacker, "name", "") or "")
        av = float(getattr(sim, "current_av", 0.0))
        # 我方攻击敌方时的单体/主目标选择（如风堇普攻点狂兽的胚芽而非亚婆离）
        if not getattr(attacker, "is_enemy", False) and living and all(getattr(e, "is_enemy", False) for e in living):
            key_av = round(av, 2)
            for (p_av, p_name), enames in meta.player_enemy_targets.items():
                if p_name == att_name and abs(p_av - key_av) <= 0.05 and enames:
                    target_ename = enames[min(hit_idx, len(enames) - 1)]
                    found = _find_ally(living, target_ename)
                    if found is not None:
                        return found
            return None

        # 我方辅助单点技能目标（如知更鸟•晴歌终结技）
        if att_name in meta.ally_ult_targets:
            targets = meta.ally_ult_targets[att_name]
            idx = min(ally_ult_cursor.get(att_name, 0), len(targets) - 1)
            ally_ult_cursor[att_name] = ally_ult_cursor.get(att_name, 0) + 1
            return _find_ally(living, targets[idx])
        av_key = _match_av_key(av)
        if av_key is None:
            return None
        recs = recs_by_av[av_key]
        if hit_idx == 0:
            idx = min(cursor_by_av.get(av_key, 0), len(recs) - 1)
            rec = recs[idx]
            cursor_by_av[av_key] = cursor_by_av.get(av_key, 0) + 1
            active_rec_by_av[av_key] = rec
        else:
            rec = active_rec_by_av.get(av_key) or recs[min(max(0, cursor_by_av.get(av_key, 1) - 1), len(recs) - 1)]

        hit_seq: List[str] = []
        for nm in rec.hit_allies:
            hit_seq.extend([nm] * max(1, rec.hit_counts.get(nm, 1)))

        if hit_idx < len(hit_seq):
            return _find_ally(living, hit_seq[hit_idx])

        memos = _living_memosprites(living)
        if memos:
            kind = "primary" if hit_idx == 0 else "bounce"
            return _pick_memosprite_by_passive_signal(rec, memos, kind)

        if rec.hit_allies:
            return _find_ally(living, rec.hit_allies[0])
        return None

    def _blast_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        av_key = _match_av_key(av)
        if av_key is None:
            return []
        recs = recs_by_av[av_key]
        rec = active_rec_by_av.get(av_key) or recs[min(max(0, cursor_by_av.get(av_key, 1) - 1), len(recs) - 1)]

        primary_name = getattr(primary, "name", None)
        known_blasts: List[Any] = []
        for nm in rec.hit_allies:
            if nm != primary_name:
                ent = _find_ally(living, nm)
                if ent is not None:
                    known_blasts.append(ent)

        if len(known_blasts) >= 2:
            return known_blasts

        memos = _living_memosprites(living)
        if not memos:
            return known_blasts

        ov_key = (rec.av, rec.enemy_uid, "blast")
        if ov_key in overrides:
            extra_names = overrides[ov_key]
            out = list(known_blasts)
            for mname in extra_names:
                ment = _find_ally(memos, mname)
                if ment is not None and ment not in out and ment is not primary:
                    out.append(ment)
            if extra_names:
                _record_inf(rec.av, rec.enemy_uid, "blast", extra_names, "second_pass_confirmed")
            return out

        adj_memos: List[Any] = []
        try:
            pidx = living.index(primary)
            for nb in (pidx - 1, pidx + 1):
                if 0 <= nb < len(living) and _is_memosprite(living[nb]):
                    adj_memos.append(living[nb])
        except ValueError:
            pass

        cand_memos = [m for m in memos if m is not primary and m not in known_blasts]
        if cand_memos:
            candidates: List[Tuple[str, ...]] = [()]
            for m in cand_memos:
                candidates.append((m.name,))
            default_extra = (adj_memos[0].name,) if adj_memos else ()
            _record_ambig(rec.av, rec.enemy_uid, "blast", candidates, default_extra)
            if default_extra:
                _record_inf(rec.av, rec.enemy_uid, "blast", default_extra, "blast_adjacent")
                return known_blasts + [adj_memos[0]]

        return known_blasts

    sim.target_provider = _target_provider
    sim.blast_target_provider = _blast_provider


def _try_load_existing_plugin(tag: str) -> Tuple[Optional[Callable[[Any], None]], Set[Any]]:
    """尝试加载已存在的 simulator/plugins/log_<tag>.py 及对应非暴击账本。"""
    plugin_fn: Optional[Callable[[Any], None]] = None
    non_crits: Set[Any] = set()
    mod_name = f"simulator.plugins.log_{tag}"
    fn_name = f"attach_log_{tag}_plugin"
    try:
        mod = importlib.import_module(mod_name)
        plugin_fn = getattr(mod, fn_name, None)
    except ModuleNotFoundError:
        plugin_fn = None

    try:
        nc_mod = importlib.import_module("simulator.plugins.non_crit_ledgers")
        nc_attr = f"OFFICIAL_{tag}_NON_CRITS"
        if hasattr(nc_mod, nc_attr):
            non_crits = set(getattr(nc_mod, nc_attr))
    except Exception:
        pass
    return plugin_fn, non_crits


def build_stage_for_id(
    stage_id: int,
    team: List[Any],
    *,
    technique_users: Sequence[str],
    force_data_driven: bool = False,
) -> Tuple[Any, Any, str]:
    """按 stage_id 路由至官方已验证关卡构建器或纯数据驱动 StageFactory 底座。"""
    if stage_id == 30126122 and not force_data_driven:
        sim, director = build_stage_30126122(team, technique_users=list(technique_users))
        return sim, director, "stage_30126122"
    sim, director = build_data_driven_stage(
        stage_id,
        team,
        technique_users=list(technique_users),
    )
    return sim, director, f"data_driven({stage_id})"


def _attach_crit_hit_recorder(sim: Any) -> List[Tuple[float, int, int, str, float, float, float]]:
    """包装 sim.crit_oracle 并订阅 DamageAppliedEvent，记录每次玩家暴击的 (av, act_idx, hit_idx, dtype, eff_cr, crit_mult, dmg)。"""
    from simulator.actions import ActionKind
    from simulator.events import ActionExecuteEvent, BattleEvent, DamageAppliedEvent
    from simulator.status import StatType

    records: List[Tuple[float, int, int, str, float, float, float]] = []
    state = {"act_idx": -1, "hit_idx": 0}
    pending: List[Tuple[int, int, float]] = []

    def _on_ev(e: BattleEvent) -> None:
        if isinstance(e, ActionExecuteEvent):
            ent = sim.get_entity(e.actor_name)
            if ent is not None and (getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False)):
                return
            kind = getattr(e, "action_kind", None)
            if kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
                return
            raw_name = e.action_type or ""
            if raw_name == "FollowUpAttack" or not raw_name:
                return
            state["act_idx"] += 1
            state["hit_idx"] = 0
        elif isinstance(e, DamageAppliedEvent):
            if not pending:
                return
            act_i, hit_i, eff_cr = pending.pop(0)
            bd = getattr(e, "breakdown", None)
            if e.is_crit and bd is not None and getattr(bd, "crit_mult", 1.0) > 1.05:
                dtype = getattr(e.damage_type, "value", str(e.damage_type)) if e.damage_type is not None else ""
                records.append(
                    (
                        round(float(getattr(sim, "current_av", 0.0)), 2),
                        act_i,
                        hit_i,
                        dtype,
                        eff_cr,
                        float(bd.crit_mult),
                        float(e.damage),
                    )
                )

    sim.event_bus.subscribe(BattleEvent, _on_ev)

    orig_oracle = sim.crit_oracle

    def _wrapped_oracle(req: Any) -> bool:
        res = orig_oracle(req)
        if not (getattr(req.attacker, "is_enemy", False) or getattr(req.attacker, "is_countdown", False)):
            h_i = state["hit_idx"]
            state["hit_idx"] += 1
            try:
                eff_cr = float(sim.port.stat(req.attacker.name, StatType.CRIT_RATE)) + float(
                    getattr(req, "extra_crit_rate", 0.0) or 0.0
                )
            except Exception:
                eff_cr = 0.5
            pending.append((state["act_idx"], h_i, eff_cr))
        return res

    sim.crit_oracle = _wrapped_oracle
    return records


def _detect_non_crits_from_trace(
    g: Any,
    crit_records: Sequence[Tuple[float, int, int, str, float, float, float]],
) -> Set[Tuple[int, int]]:
    """将 SIM 暴击命中与 GT 同 AV 同类型伤害逐段比对，精确识别实机未暴击的 (act_idx, hit_idx)。

    严格防呆：
    - 仅检查有效暴击率 < 99.9% 的角色命中；
    - 仅当 sim_dmg / gt_dmg 与该次命中的 1 + CritDMG (crit_mult) 偏差 < 6% 时才判定为未暴击。
    """
    gt_hits: Dict[Tuple[float, str], List[float]] = {}
    for t in g.turns:
        av = round(t.av, 2)
        for d in t.damages:
            if d.damage_type == "DoT":
                continue
            gt_hits.setdefault((av, d.damage_type), []).append(float(d.damage))

    sim_grouped: Dict[Tuple[float, str], List[Tuple[int, int, float, float, float]]] = {}
    for av, act_i, hit_i, dtype, eff_cr, crit_mult, dmg in crit_records:
        sim_grouped.setdefault((av, dtype), []).append((act_i, hit_i, eff_cr, crit_mult, dmg))

    detected: Set[Tuple[int, int]] = set()
    for key, s_list in sim_grouped.items():
        g_list = gt_hits.get(key)
        if not g_list or len(g_list) != len(s_list):
            continue
        for (act_i, hit_i, eff_cr, crit_mult, s_dmg), g_dmg in zip(s_list, g_list):
            if eff_cr >= 0.999 or g_dmg <= 0.0:
                continue
            ratio = s_dmg / g_dmg
            if abs(ratio - crit_mult) / crit_mult < 0.06:
                detected.add((act_i, hit_i))
    return detected


def _run_single_pass(
    log_path: str,
    meta: LogMetadata,
    g: Any,
    tl: List[Any],
    *,
    char_db: CharacterDB,
    vm_loader: GameDataLoader,
    force_data_driven: bool,
    plugin_fn: Optional[Callable[[Any], None]],
    non_crits: Set[Any],
    av_budget: Optional[float],
    memosprite_overrides: Optional[Dict[Tuple[float, int, str], Tuple[str, ...]]] = None,
    record_crits: bool = False,
) -> Tuple[ReconcileReport, List[AmbiguousMemospriteSlot], List[Tuple[float, int, int, str, float, float, float]]]:
    team = build_vm_team(meta.team_names, db=char_db, loader=vm_loader)
    sim, director, stage_mode = build_stage_for_id(
        meta.stage_id,
        team,
        technique_users=meta.team_names,
        force_data_driven=force_data_driven,
    )

    ambiguous_slots: List[AmbiguousMemospriteSlot] = []
    inferred_hits: List[InferredMemospriteHit] = []

    attach_exact_crit_oracle(sim, log_path=log_path, non_crits=non_crits)
    crit_records = _attach_crit_hit_recorder(sim) if record_crits else []
    if not getattr(sim, "enemy_uid_map", None) and meta.enemy_uid_map:
        if force_data_driven:
            dd_map: Dict[int, str] = {}
            for uid, ename in meta.enemy_uid_map.items():
                m_eg = re.match(r"^(.+)_g(\d+)_(\d+)$", ename)
                if m_eg:
                    base, gen, idx = m_eg.group(1), int(m_eg.group(2)), int(m_eg.group(3))
                    dd_map[uid] = f"{base}_{(gen - 1) * 3 + idx}"
                else:
                    dd_map[uid] = ename
            sim.enemy_uid_map = dd_map
        else:
            sim.enemy_uid_map = dict(meta.enemy_uid_map)
    if plugin_fn is not None:
        plugin_fn(sim)
        plugin_mode = f"plugin:log_{meta.tag}"
    else:
        attach_auto_rng_plugin(
            sim,
            meta,
            memosprite_overrides=memosprite_overrides,
            ambiguous_out=ambiguous_slots,
            inferred_out=inferred_hits,
        )
        plugin_mode = ""

    traj = run_trajectory_replay(
        sim,
        director,
        tl,
        av_budget=av_budget if av_budget is not None else g.final_av,
        log_path=log_path,
    )
    rep = diff_sequences(g, traj.replay.sequence)

    if plugin_fn is None:
        plugin_mode = (
            f"auto_rng({len([h for h in meta.enemy_hits if h.hit_allies])} avatar hits, "
            f"{len(inferred_hits)} memo/skip inferred, {len(meta.aha_turns)} aha, {len(non_crits)} non_crits)"
        )

    gt_by_av: Dict[float, float] = {}
    gt_atks: Dict[float, Set[str]] = {}
    gt_cat: Dict[float, Dict[str, float]] = {}
    for t in g.turns:
        av = round(t.av, 2)
        for d in t.damages:
            if d.damage_type == "DoT":
                continue
            gt_by_av[av] = gt_by_av.get(av, 0.0) + d.damage
            gt_atks.setdefault(av, set()).add(d.attacker)
            cat = f"{d.attacker}:{d.damage_type}"
            gt_cat.setdefault(av, {})[cat] = gt_cat.setdefault(av, {}).get(cat, 0.0) + d.damage

    sim_by_av: Dict[float, float] = {}
    sim_cat: Dict[float, Dict[str, float]] = {}
    for t in traj.replay.sequence.turns:
        av = round(t.av, 2)
        for d in t.damages:
            if d.damage_type == "DoT":
                continue
            sim_by_av[av] = sim_by_av.get(av, 0.0) + d.damage
            cat = f"{d.attacker}:{d.damage_type}"
            sim_cat.setdefault(av, {})[cat] = sim_cat.setdefault(av, {}).get(cat, 0.0) + d.damage

    all_avs = sorted(set(gt_by_av.keys()) | set(sim_by_av.keys()))
    turn_diffs: List[TurnDiffEntry] = []
    max_turn_err = 0.0
    for av in all_avs:
        gd = gt_by_av.get(av, 0.0)
        sd = sim_by_av.get(av, 0.0)
        if gd > 0.0:
            err = abs(sd - gd) / gd
        else:
            err = 1.0 if sd > 0.0 else 0.0
        max_turn_err = max(max_turn_err, err)
        cats = sorted(set(gt_cat.get(av, {}).keys()) | set(sim_cat.get(av, {}).keys()))
        breakdown = {c: (gt_cat.get(av, {}).get(c, 0.0), sim_cat.get(av, {}).get(c, 0.0)) for c in cats}
        turn_diffs.append(
            TurnDiffEntry(
                av=av,
                gt_total=gd,
                sim_total=sd,
                err=err,
                attackers=sorted(gt_atks.get(av, set())),
                breakdown=breakdown,
            )
        )

    gold_tot = float(rep["golden_total_damage"])
    sim_tot = float(rep["sim_total_damage"])
    tot_err = abs(sim_tot - gold_tot) / gold_tot if gold_tot > 0 else 0.0
    forced_or_failed = sum(1 for r in traj.records if r.mode in ("forced", "failed"))

    report = ReconcileReport(
        meta=meta,
        stage_mode=stage_mode,
        plugin_mode=plugin_mode,
        turn_matched=traj.replay.turn_matched,
        turn_total=traj.replay.turn_total,
        ult_matched=traj.replay.ult_matched,
        ult_total=traj.replay.ult_total,
        sp_granted=traj.sp_granted,
        memoria_granted=traj.memoria_granted,
        presence_grants=traj.presence_grants,
        forced_or_failed=forced_or_failed,
        golden_total_damage=gold_tot,
        sim_total_damage=sim_tot,
        total_err=tot_err,
        max_turn_err=max_turn_err,
        turn_diffs=turn_diffs,
        inferred_memosprite_hits=inferred_hits,
        unresolved_ambiguous_slots=len(ambiguous_slots),
    )
    return report, ambiguous_slots, crit_records


def reconcile_log(
    log_path: str,
    *,
    db: Optional[CharacterDB] = None,
    loader: Optional[GameDataLoader] = None,
    team_override: Optional[Sequence[str]] = None,
    force_data_driven: bool = False,
    use_existing_plugin: bool = True,
    resolve_memosprites: bool = True,
    av_budget: Optional[float] = None,
    max_tl_av: Optional[float] = None,
    threshold: float = 0.002,
) -> ReconcileReport:
    """对任意官方战斗日志执行端到端 VM 对账并返回逐动诊断报告。"""
    char_db = db if db is not None else CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    vm_loader = loader if loader is not None else GameDataLoader()

    meta = extract_log_metadata(log_path, db=char_db, team_override=team_override)
    g = parse_golden_jsonl(log_path)
    tl = extract_timeline(log_path)
    if max_tl_av is not None:
        tl = [item for item in tl if item.av < max_tl_av]

    plugin_fn: Optional[Callable[[Any], None]] = None
    non_crits: Set[Any] = set()
    if use_existing_plugin:
        plugin_fn, non_crits = _try_load_existing_plugin(meta.tag)

    overrides: Dict[Tuple[float, int, str], Tuple[str, ...]] = {}
    report, ambiguous_slots, crit_records = _run_single_pass(
        log_path,
        meta,
        g,
        tl,
        char_db=char_db,
        vm_loader=vm_loader,
        force_data_driven=force_data_driven,
        plugin_fn=plugin_fn,
        non_crits=non_crits,
        av_budget=av_budget,
        memosprite_overrides=overrides,
        record_crits=(plugin_fn is None),
    )

    # 纯自动模式下：最多 2 轮自动检测未暴击 (act_idx, hit_idx) 并收敛
    if plugin_fn is None:
        for _nc_round in range(2):
            newly_detected = _detect_non_crits_from_trace(g, crit_records) - non_crits
            if not newly_detected:
                break
            non_crits = set(non_crits) | newly_detected
            report, ambiguous_slots, crit_records = _run_single_pass(
                log_path,
                meta,
                g,
                tl,
                char_db=char_db,
                vm_loader=vm_loader,
                force_data_driven=force_data_driven,
                plugin_fn=None,
                non_crits=non_crits,
                av_budget=av_budget,
                memosprite_overrides=overrides,
                record_crits=True,
            )

    if plugin_fn is None and resolve_memosprites and ambiguous_slots:
        resolved_keys: Set[Tuple[float, int, str]] = set()
        for _round in range(min(len(ambiguous_slots), 8)):
            bad_turns = [td for td in report.turn_diffs if td.err >= threshold]
            if not bad_turns:
                break
            first_bad = bad_turns[0]
            preceding = [
                slot
                for slot in ambiguous_slots
                if slot.av <= first_bad.av + 0.05 and slot.key not in resolved_keys
            ]
            if not preceding:
                break
            improved_any = False
            for slot in reversed(preceding[-3:]):
                resolved_keys.add(slot.key)
                best_choice = slot.default_choice
                best_err = first_bad.err
                best_report = report
                best_slots = ambiguous_slots
                for cand in slot.candidates:
                    if cand == slot.default_choice:
                        continue
                    trial_ov = dict(overrides)
                    trial_ov[slot.key] = cand
                    trial_rep, trial_slots, _ = _run_single_pass(
                        log_path,
                        meta,
                        g,
                        tl,
                        char_db=char_db,
                        vm_loader=vm_loader,
                        force_data_driven=force_data_driven,
                        plugin_fn=None,
                        non_crits=non_crits,
                        av_budget=av_budget,
                        memosprite_overrides=trial_ov,
                        record_crits=False,
                    )
                    trial_td = next((td for td in trial_rep.turn_diffs if abs(td.av - first_bad.av) < 0.05), None)
                    trial_err = trial_td.err if trial_td is not None else 1.0
                    if trial_err + 1e-4 < best_err:
                        best_err = trial_err
                        best_choice = cand
                        best_report = trial_rep
                        best_slots = trial_slots
                if best_choice != slot.default_choice:
                    overrides[slot.key] = best_choice
                    report = best_report
                    ambiguous_slots = best_slots
                    improved_any = True
                    break
            if not improved_any:
                break

    return report


def format_report(report: ReconcileReport, *, threshold: float = 0.002, verbose: bool = False) -> str:
    """将 ReconcileReport 格式化为可读的终端诊断报告。"""
    over = [td for td in report.turn_diffs if td.err >= threshold]
    lines = [
        f"=== VM Reconcile Report: {os.path.basename(report.meta.log_path)} ===",
        f"Stage      : {report.meta.stage_id} ({report.stage_mode})",
        f"Team       : {report.meta.team_names} (UIDs={report.meta.team_uids})",
        f"RNG Plugin : {report.plugin_mode}",
        f"Trajectory : turns={report.turn_matched}/{report.turn_total} ults={report.ult_matched}/{report.ult_total} "
        f"sp_grant={report.sp_granted} mem_grant={report.memoria_granted:.1f} forced/failed={report.forced_or_failed}",
        f"Damage     : GT={report.golden_total_damage:,.2f}  SIM={report.sim_total_damage:,.2f}  "
        f"total_err={report.total_err:.4%}  max_turn_err={report.max_turn_err:.4%}  over_{threshold:.1%}={len(over)}/{len(report.turn_diffs)}",
    ]
    if report.inferred_memosprite_hits:
        lines.append("Memosprite / skip inferences:")
        for hit in report.inferred_memosprite_hits:
            lines.append(
                f"  AV={hit.av:6.2f} enemy={hit.enemy_uid} kind={hit.kind:7s} -> {list(hit.targets)} [{hit.source}]"
            )
    rows = report.turn_diffs if verbose else over
    if rows:
        lines.append("")
        lines.append(f"Per-turn breakdown ({'ALL' if verbose else f'>= {threshold:.1%}'}):")
        for td in rows:
            lines.append(
                f"  AV={td.av:6.2f}  err={td.err:7.3%}  GT={td.gt_total:11.2f}  SIM={td.sim_total:11.2f}  "
                f"diff={td.sim_total - td.gt_total:+10.2f}  atks={td.attackers}"
            )
            for cat, (gv, sv) in td.breakdown.items():
                if abs(sv - gv) > 1.0:
                    ce = (sv - gv) / gv if gv > 0 else 1.0
                    lines.append(f"      {cat:28s} GT={gv:10.2f} SIM={sv:10.2f} ({ce:+.3%})")
    return "\n".join(lines)


def emit_alignment_test(
    report: ReconcileReport,
    *,
    output_path: Optional[str] = None,
    force_data_driven: bool = False,
) -> str:
    """根据对账报告生成标准 unittest 对账脚本并返回写入路径。"""
    meta = report.meta
    if output_path is None:
        fname = f"test_vm_{meta.stage_id}_{meta.tag}_alignment.py"
        output_path = os.path.join(ROOT_DIR, "simulator", "vm", fname)

    team_literal = repr(meta.team_names)
    rel_log = os.path.basename(meta.log_path)
    code = f'''# coding: utf-8
"""自动生成的 VM 对账测试：stage={meta.stage_id}, log={rel_log}。"""

import os
import unittest

from simulator.vm.reconcile_generator import reconcile_log

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVMStage{meta.stage_id}_{meta.tag}Alignment(unittest.TestCase):
    def test_alignment(self) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", {rel_log!r})
        rep = reconcile_log(
            log_path,
            team_override={team_literal},
            force_data_driven={force_data_driven!r},
        )
        self.assertEqual(rep.turn_matched, rep.turn_total)
        self.assertEqual(rep.ult_matched, rep.ult_total)
        self.assertEqual(rep.sp_granted, 0)
        self.assertEqual(rep.memoria_granted, 0.0)
        self.assertEqual(rep.forced_or_failed, 0)
        self.assertLess(rep.total_err, 0.002, f"总伤偏差过大: {{rep.total_err:.3%}}")
        for td in rep.turn_diffs:
            self.assertLess(
                td.err,
                0.002,
                f"AV={{td.av:.2f}} 单动偏差过大: {{td.err:.3%}} (GT={{td.gt_total:.2f}}, SIM={{td.sim_total:.2f}})",
            )


if __name__ == "__main__":
    unittest.main()
'''
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(code)
    return output_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="通用官方日志 → ConfigAbility VM 对账工具与测试生成器")
    parser.add_argument("log_path", help="battle_logs/battle_*.jsonl 路径")
    parser.add_argument("--team", nargs="+", default=None, help="手动指定队伍站位顺序（默认自动识别）")
    parser.add_argument("--data-driven", action="store_true", help="强制走通用 build_data_driven_stage(stage_id)")
    parser.add_argument("--no-plugin", action="store_true", help="忽略已有 log_<tag>.py，强制走自动提取受击目标")
    parser.add_argument("--no-resolve-memosprites", action="store_true", help="关闭多忆灵差额二次试跑确认")
    parser.add_argument("--av-budget", type=float, default=None, help="截断复现的最大 AV")
    parser.add_argument("--threshold", type=float, default=0.002, help="单动误差高亮阈值（默认 0.002 = 0.2%%）")
    parser.add_argument("--verbose", action="store_true", help="输出所有回合的逐动对比")
    parser.add_argument("--emit-test", nargs="?", const="", default=None, help="生成 unittest 对账脚本（可选指定输出路径）")
    args = parser.parse_args(argv)

    rep = reconcile_log(
        args.log_path,
        team_override=args.team,
        force_data_driven=args.data_driven,
        use_existing_plugin=not args.no_plugin,
        resolve_memosprites=not args.no_resolve_memosprites,
        av_budget=args.av_budget,
        threshold=args.threshold,
    )
    print(format_report(rep, threshold=args.threshold, verbose=args.verbose))
    if args.emit_test is not None:
        out = emit_alignment_test(
            rep,
            output_path=args.emit_test or None,
            force_data_driven=args.data_driven,
        )
        print(f"\n[Generated test] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

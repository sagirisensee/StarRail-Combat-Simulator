# coding: utf-8
"""从官方战斗 JSONL 日志提取 LogMetadata（阵容、敌方 UID、受击/阿哈/拉条目标等）。"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from simulator.db.character_db import CharacterDB
from simulator.vm.reconcile.models import (
    DEFAULT_CHAR_DB_PATH,
    AhaTurnRecord,
    EnemyHitRecord,
    LogMetadata,
    _extract_tag,
    _get_avatar_damage_types,
    _get_avatar_skill_effects,
    _get_avatar_skill_stance_pairs,
    _get_avatar_skill_stances,
    _get_servant_skill_effects,
    _resolve_uid_name,
)
from simulator.vm.stage_data_loader import StageDataLoader


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

    # 敌方 UID 映射追踪（通用：不写死任何怪物名称）
    initial_enemy_uids: List[int] = []
    seen_init_enemy_uids: Set[int] = set()
    enemy_uid_map: Dict[int, str] = {}
    spawn_events_raw: List[Tuple[int, str]] = []
    enemy_spawns: List[Tuple[float, int, str]] = []
    gluttony_locked_euids: Set[int] = set()
    gluttony_revived_euids: Set[int] = set()
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
    cur_hit_dmgs: Dict[str, float] = {}
    cur_clamped_hp_names: Set[str] = set()
    cur_small_hp_drops: Dict[str, List[float]] = {}
    cur_sub_hits: List[str] = []
    cur_sub_actions: List[List[str]] = []
    cur_sub_sp_gains: Dict[str, int] = {}
    cur_sub_first_memo: Optional[str] = None
    cur_sub_pending_sp_owner: Optional[str] = None
    cur_sub_action_details: List[Tuple[List[str], Dict[str, int], Optional[str]]] = []
    cur_small_heal_uids: Set[int] = set()
    cur_sp_gain_counts: Dict[str, int] = {}
    cur_first_memo_owner: Optional[str] = None
    pending_first_sp_owner: Optional[str] = None
    last_enemy_hit_sp: float = 0.0
    paused_enemy_ctx: Optional[Dict[str, Any]] = None

    # 无归属回合（阿哈回合）追踪
    cur_none_had_skill = False
    cur_none_enemy_dmgs: List[Tuple[int, float]] = []
    cur_none_last_drop_euid: Optional[int] = None
    cur_none_lethal_euids: Set[int] = set()
    cur_none_ally_chips: List[str] = []
    cur_none_ally_sp_counts: Dict[str, int] = {}
    cur_none_pending_hp_chip_uid: Optional[int] = None
    last_player_sp: Dict[int, float] = {}

    # 辅助单点拉条终结技目标追踪（通用：检测任意 Ultra 后伴随单名队友负 ActionDelay）
    pending_ally_ult_caster: Optional[str] = None
    pending_ally_ult_sid: int = 0
    pending_ally_ult_uid: int = 0
    pending_ally_ult_sp_fallback: Optional[str] = None
    ally_ult_targets: Dict[str, List[str]] = {}
    enemy_retarget_picks: List[Tuple[float, int, int]] = []
    pending_player_atk: Optional[Tuple[float, str]] = None
    pending_player_hit_euids: List[int] = []
    pending_player_dmg_confirmed_euids: List[int] = []
    pending_player_sp_euids: List[int] = []
    pending_player_hit_dmgs: Dict[int, float] = {}
    pending_hit_hp_euids: List[int] = []
    pending_hit_direct_euid: Optional[int] = None
    pending_hit_sp_euid: Optional[int] = None
    last_player_hit_euid: Optional[int] = None
    pending_player_primary_dmg_hits = 0
    pending_player_is_servant = False
    pending_player_skill_id = 0
    pending_player_skill_type = ""
    player_enemy_targets_raw: Dict[Tuple[float, str], List[int]] = {}
    servant_targets_raw: Dict[Tuple[float, str], List[Optional[int]]] = {}
    pending_player_atk_records: List[
        Tuple[Tuple[float, str], bool, int, str, int, List[int], List[int], Dict[int, float], List[int]]
    ] = []
    servant_skill_effects = _get_servant_skill_effects()
    avatar_skill_effects = _get_avatar_skill_effects()
    in_aoe_heal_window = False
    aoe_heal_slot_uids: List[int] = []
    inferred_slot_uids: List[int] = []
    robin_s_init_ad: float = 0.0
    first_skill_info: Optional[Tuple[int, int]] = None
    first_skill_done: bool = False
    first_skill_stance_obs: Dict[int, float] = {}
    cur_player_sk_info: Optional[Tuple[int, int, int]] = None
    cur_player_atk_seq = 0
    init_enemy_first_stance: Dict[int, Tuple[int, int, float, int]] = {}
    init_stance_seen_euids: Set[int] = set()
    skill_atk_dmgs: Dict[int, Dict[int, float]] = {}

    def _servant_primary_euid(hit_euids: Sequence[int]) -> Optional[int]:
        """单体忆灵技主目标：仅在官方技能表为 SingleAttack 且全段命中同一个敌方时提取。"""
        ordered: List[int] = []
        for u in hit_euids:
            if u not in ordered:
                ordered.append(u)
        if len(ordered) == 1:
            return ordered[0]
        return None

    def _flush_pending_player_atk() -> None:
        nonlocal pending_player_atk, pending_player_hit_euids, pending_player_dmg_confirmed_euids, pending_player_sp_euids, pending_player_hit_dmgs, pending_player_primary_dmg_hits, last_player_hit_euid, pending_hit_direct_euid, pending_hit_sp_euid
        nonlocal pending_player_is_servant, pending_player_skill_id, pending_player_skill_type
        if cur_player_sk_info is not None and pending_player_hit_dmgs:
            skill_atk_dmgs.setdefault(cur_player_sk_info[2], {}).update(pending_player_hit_dmgs)
        if pending_player_atk is not None:
            pending_player_atk_records.append(
                (
                    pending_player_atk,
                    pending_player_is_servant,
                    pending_player_skill_id,
                    pending_player_skill_type,
                    pending_player_primary_dmg_hits,
                    list(pending_player_hit_euids),
                    list(pending_player_dmg_confirmed_euids),
                    dict(pending_player_hit_dmgs),
                    list(pending_player_sp_euids),
                )
            )
        pending_player_atk = None
        pending_player_hit_euids = []
        pending_player_dmg_confirmed_euids = []
        pending_player_sp_euids = []
        pending_player_hit_dmgs = {}
        pending_hit_hp_euids.clear()
        pending_hit_direct_euid = None
        pending_hit_sp_euid = None
        last_player_hit_euid = None
        pending_player_primary_dmg_hits = 0
        pending_player_is_servant = False
        pending_player_skill_id = 0
        pending_player_skill_type = ""

    last_player_hp: Dict[int, float] = {}
    last_player_spd: Dict[int, float] = {}
    slow_hits: Set[Tuple[float, str]] = set()
    av_elems_map = _get_avatar_damage_types()
    last_stance_zero_euid: Optional[int] = None
    pending_q_break: Optional[Tuple[float, int, int]] = None
    quantum_entangle_resists_raw: Set[Tuple[float, int]] = set()

    def _flush_pending_q_break() -> None:
        nonlocal pending_q_break
        if pending_q_break is not None:
            q_av, q_euid, q_cnt = pending_q_break
            if q_cnt == 1:
                quantum_entangle_resists_raw.add((q_av, q_euid))
            pending_q_break = None
    last_enemy_hp: Dict[int, float] = {}
    enemy_hp_at_turn_end_raw: Dict[Tuple[float, int], float] = {}
    pending_tie_highest_hp_euid: Optional[int] = None
    enemy_hits: List[EnemyHitRecord] = []
    aha_turns: List[AhaTurnRecord] = []

    def _flush_sub_action() -> None:
        nonlocal cur_sub_hits, cur_sub_sp_gains, cur_sub_first_memo, cur_sub_pending_sp_owner, cur_small_hp_drops
        if cur_sub_hits or cur_sub_sp_gains:
            if cur_sub_pending_sp_owner is not None and not cur_sub_hits and cur_sub_first_memo is None:
                cur_sub_first_memo = cur_sub_pending_sp_owner
            if cur_sub_hits:
                cur_sub_actions.append(list(cur_sub_hits))
            cur_sub_action_details.append((
                list(cur_sub_hits),
                dict(cur_sub_sp_gains),
                cur_sub_first_memo,
            ))
        cur_sub_hits = []
        cur_sub_sp_gains = {}
        cur_sub_first_memo = None
        cur_sub_pending_sp_owner = None
        cur_small_hp_drops = {}

    def _flush_turn() -> None:
        nonlocal cur_enemy_uid, cur_hit_order, cur_hit_set, cur_hit_counts, cur_hit_dmgs, cur_clamped_hp_names, cur_small_hp_drops, cur_sub_hits, cur_sub_actions, cur_sub_sp_gains, cur_sub_first_memo, cur_sub_pending_sp_owner, cur_sub_action_details, cur_small_heal_uids, cur_sp_gain_counts, cur_first_memo_owner, pending_first_sp_owner, last_enemy_hit_sp
        nonlocal cur_turn_owner_team, cur_none_had_skill, cur_none_enemy_dmgs, cur_none_last_drop_euid, cur_none_lethal_euids, cur_none_ally_chips, cur_none_ally_sp_counts, cur_none_pending_hp_chip_uid
        if cur_enemy_uid is not None:
            if pending_first_sp_owner is not None and not cur_hit_order and cur_first_memo_owner is None:
                cur_first_memo_owner = pending_first_sp_owner
            pending_first_sp_owner = None
            _flush_sub_action()
            eff_hit_order = list(cur_hit_order)
            # 敌方多动中若先放全体 AoE 再放单体点名（如 Skill02 + Skill01 [+ Skill04]），将单体目标放在首位供 target_provider 精准锁定
            if len(cur_sub_actions) >= 2 and len(set(cur_sub_actions[0])) >= 2:
                st_subs = [sub[0] for sub in cur_sub_actions[1:] if len(set(sub)) == 1]
                if st_subs:
                    st_tgt = st_subs[0]
                    if st_tgt in eff_hit_order:
                        eff_hit_order.remove(st_tgt)
                    eff_hit_order.insert(0, st_tgt)
            elif len(cur_sub_actions) == 1 and len(cur_hit_dmgs) >= 2 and not cur_clamped_hp_names:
                # 全体主/副双倍率技能（如锁定单人高倍率重击 + 其余低倍率波及）：将承伤显著最高者置首作为主目标
                sorted_dmgs = sorted(cur_hit_dmgs.items(), key=lambda kv: kv[1], reverse=True)
                if sorted_dmgs[1][1] > 0.0 and sorted_dmgs[0][1] > sorted_dmgs[1][1] * 1.8:
                    prim = sorted_dmgs[0][0]
                    if prim in eff_hit_order:
                        eff_hit_order.remove(prim)
                    eff_hit_order.insert(0, prim)
            sub_recs: List[EnemyHitRecord] = []
            if len(cur_sub_action_details) >= 2:
                had_pheal = len(cur_small_heal_uids) >= 2
                for sub_hits, sub_sp, sub_fm in cur_sub_action_details:
                    sub_order: List[str] = []
                    sub_seen: Set[str] = set()
                    sub_counts: Dict[str, int] = {}
                    for nm in sub_hits:
                        if nm not in sub_seen:
                            sub_seen.add(nm)
                            sub_order.append(nm)
                        sub_counts[nm] = sub_counts.get(nm, 0) + 1
                    sub_recs.append(
                        EnemyHitRecord(
                            av=round(cur_av, 2),
                            enemy_uid=cur_enemy_uid,
                            hit_allies=sub_order,
                            hit_counts=sub_counts,
                            had_hp_drop=bool(sub_hits),
                            had_passive_heal=had_pheal,
                            sp_gain_counts=dict(sub_sp),
                            first_memo_owner=sub_fm,
                        )
                    )
            enemy_hits.append(
                EnemyHitRecord(
                    av=round(cur_av, 2),
                    enemy_uid=cur_enemy_uid,
                    hit_allies=eff_hit_order,
                    hit_counts=dict(cur_hit_counts),
                    had_hp_drop=bool(cur_hit_order),
                    had_passive_heal=len(cur_small_heal_uids) >= 2,
                    sp_gain_counts=dict(cur_sp_gain_counts),
                    first_memo_owner=cur_first_memo_owner,
                    sub_records=sub_recs,
                )
            )
        elif cur_turn_owner_team is None and not cur_none_had_skill and cur_none_ally_chips:
            # 真实阿哈回合必含我方伴生微伤（过滤无我方微伤的 Boss 紫色球体/破盾扣血等系统回合）
            filtered_dmgs = [(u, d) for u, d in cur_none_enemy_dmgs if d < 500_000.0]
            aha_turns.append(
                AhaTurnRecord(
                    av=round(cur_av, 6),
                    enemy_damages=filtered_dmgs,
                    ally_chip_hits=list(cur_none_ally_chips),
                    ally_sp_gain_counts=dict(cur_none_ally_sp_counts),
                    lethal_enemy_uids=set(cur_none_lethal_euids),
                )
            )
        if cur_turn_owner_team == "Player" and last_enemy_hp:
            av_k = round(cur_av, 2)
            for eu, ehp in last_enemy_hp.items():
                if ehp > 0.0:
                    enemy_hp_at_turn_end_raw[(av_k, eu)] = ehp
        cur_enemy_uid = None
        cur_hit_order = []
        cur_hit_set = set()
        cur_hit_counts = {}
        cur_hit_dmgs = {}
        cur_clamped_hp_names = set()
        cur_small_hp_drops = {}
        cur_sub_hits = []
        cur_sub_actions = []
        cur_sub_sp_gains = {}
        cur_sub_first_memo = None
        cur_sub_pending_sp_owner = None
        cur_sub_action_details = []
        cur_small_heal_uids = set()
        cur_sp_gain_counts = {}
        cur_first_memo_owner = None
        pending_first_sp_owner = None
        last_enemy_hit_sp = 0.0
        cur_none_had_skill = False
        cur_none_enemy_dmgs = []
        cur_none_last_drop_euid = None
        cur_none_lethal_euids = set()
        cur_none_ally_chips = []
        cur_none_ally_sp_counts = {}
        cur_none_pending_hp_chip_uid = None

    def _pause_enemy_turn_if_active() -> None:
        nonlocal paused_enemy_ctx
        if cur_enemy_uid is not None:
            _paused_sub_actions = list(cur_sub_actions)
            _paused_sub_details = list(cur_sub_action_details)
            if cur_sub_hits or cur_sub_sp_gains:
                _sub_fm = (
                    cur_sub_pending_sp_owner
                    if (cur_sub_pending_sp_owner is not None and not cur_sub_hits and cur_sub_first_memo is None)
                    else cur_sub_first_memo
                )
                if cur_sub_hits:
                    _paused_sub_actions.append(list(cur_sub_hits))
                _paused_sub_details.append((list(cur_sub_hits), dict(cur_sub_sp_gains), _sub_fm))
            _snap = {
                "av": round(cur_av, 2),
                "euid": cur_enemy_uid,
                "hit_order": list(cur_hit_order),
                "hit_set": set(cur_hit_set),
                "hit_counts": dict(cur_hit_counts),
                "hit_dmgs": dict(cur_hit_dmgs),
                "clamped_hp_names": set(cur_clamped_hp_names),
                "sub_actions": _paused_sub_actions,
                "sub_details": _paused_sub_details,
                "small_heal": set(cur_small_heal_uids),
                "sp_gains": dict(cur_sp_gain_counts),
                "first_memo": cur_first_memo_owner,
                "last_sp": last_enemy_hit_sp,
            }
            _flush_turn()
            _snap["rec_idx"] = len(enemy_hits) - 1
            paused_enemy_ctx = _snap

    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            ev = obj.get("event")
            data = obj.get("data") or {}
            if not (
                ev == "OnStatChange"
                and (data.get("entity") or {}).get("team") == "Enemy"
                and (data.get("property") or {}).get("type") == "CurrentHP"
            ):
                cur_none_last_drop_euid = None

            if ev == "OnBattleBegin":
                stage_id = int(data.get("stage_id") or 0)
            elif ev == "OnInitializeEnemy":
                saw_first_init_enemy = True
                enemy = data.get("enemy") or {}
                euid = int(enemy.get("uid") or 0)
                eid = int(enemy.get("id") or 0)
                ename = str(enemy.get("name") or "")
                props = (enemy.get("base_stats") or {}).get("properties") or {}
                if euid and "CurrentHP" in props:
                    last_enemy_hp[euid] = float(props["CurrentHP"])
                if euid and ename:
                    spawn_events_raw.append((euid, ename))
                if eid and ename:
                    enemy_spawns.append((round(cur_av, 2), eid, ename))
            elif ev == "OnTurnBegin":
                if in_aoe_heal_window and len(aoe_heal_slot_uids) >= 2 and not inferred_slot_uids:
                    inferred_slot_uids = list(aoe_heal_slot_uids)
                in_aoe_heal_window = False
                paused_enemy_ctx = None
                _flush_pending_player_atk()
                _flush_turn()
                _flush_pending_q_break()
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
                if pending_ally_ult_caster is not None and pending_ally_ult_sp_fallback is not None:
                    ally_ult_targets.setdefault(pending_ally_ult_caster, []).append(pending_ally_ult_sp_fallback)
                pending_ally_ult_caster = None
                pending_ally_ult_sid = 0
                pending_ally_ult_uid = 0
                pending_ally_ult_sp_fallback = None
                if first_skill_info is not None and not first_skill_done:
                    first_skill_done = True
                _flush_pending_player_atk()
            elif ev == "OnUseSkill":
                _flush_pending_q_break()
                _flush_pending_player_atk()
                if cur_turn_owner_team is None:
                    if cur_none_ally_chips:
                        _flush_turn()
                    cur_none_had_skill = True
                av_ent = data.get("avatar") or {}
                if av_ent.get("team") == "Player":
                    _pause_enemy_turn_if_active()
                    uid = int(av_ent.get("uid") or 0)
                    if uid and uid not in seen_uid_set:
                        seen_uid_set.add(uid)
                        seen_uids.append(uid)
                    skill = data.get("skill") or {}
                    sk_type = str(skill.get("type") or "")
                    sk_id = int(skill.get("skill_config_id") or 0)
                    if sk_id > 0 and uid > 0 and sk_type in ("Normal", "BPSkill", "Ultra", "Servant"):
                        cur_player_atk_seq += 1
                        cur_player_sk_info = (sk_id, uid, cur_player_atk_seq)
                    if not first_skill_done:
                        if first_skill_info is None and sk_id > 0:
                            first_skill_info = (sk_id, uid)
                        elif first_skill_info is not None:
                            first_skill_done = True
                    cname = (
                        f"BattleEvent_{sk_id // 100}"
                        if (uid == 0 and sk_id >= 1000000)
                        else _resolve_uid_name(uid, char_db)
                    )
                    if not inferred_slot_uids and sk_id in (140902, 140903):
                        in_aoe_heal_window = True
                        aoe_heal_slot_uids = []
                    else:
                        in_aoe_heal_window = False
                    if sk_type == "Ultra":
                        pending_ally_ult_caster = cname
                        pending_ally_ult_sid = sk_id
                        pending_ally_ult_uid = uid
                        pending_ally_ult_sp_fallback = None
                    if sk_type in ("Normal", "BPSkill", "Ultra", "Servant"):
                        # 忆灵技（Servant）的施法者 UID 是召唤师本体，主目标仍需按官方日志锁定
                        pending_player_atk = (round(cur_av, 2), cname)
                        pending_player_is_servant = sk_type == "Servant"
                        pending_player_skill_id = sk_id
                        pending_player_skill_type = sk_type
            elif ev == "OnDamage":
                dtype = str(data.get("type") or "")
                if dtype in ("Ultimate", "Ultra") and pending_ally_ult_caster is not None:
                    pending_ally_ult_caster = None
                    pending_ally_ult_sid = 0
                    pending_ally_ult_uid = 0
                    pending_ally_ult_sp_fallback = None
                if pending_player_atk is not None:
                    if dtype in ("Basic", "Normal", "Skill", "BPSkill", "Ultimate", "Ultra"):
                        pending_player_primary_dmg_hits += 1
                    confirmed_euid = (
                        pending_hit_direct_euid
                        if pending_hit_direct_euid is not None
                        else (pending_hit_hp_euids[0] if len(pending_hit_hp_euids) == 1 else None)
                    )
                    if confirmed_euid is not None and dtype not in ("Break", "Additional", "True"):
                        pending_player_dmg_confirmed_euids.append(confirmed_euid)
                        if (
                            pending_hit_sp_euid is not None
                            and dtype != "Follow-Up"
                            and pending_hit_sp_euid not in pending_player_sp_euids
                        ):
                            pending_player_sp_euids.append(pending_hit_sp_euid)
                        dmg_val = float(data.get("damage") or 0.0)
                        if dmg_val > pending_player_hit_dmgs.get(confirmed_euid, 0.0):
                            pending_player_hit_dmgs[confirmed_euid] = dmg_val
                    if dtype != "Break":
                        pending_hit_hp_euids.clear()
                        pending_hit_direct_euid = None
                        pending_hit_sp_euid = None
                        last_player_hit_euid = None
                atk_ent = data.get("attacker") or {}
                if dtype in ("Additional", "True"):
                    _flush_pending_q_break()
                elif dtype == "Break" and atk_ent.get("team") == "Player":
                    _flush_pending_q_break()
                    atk_uid = int(atk_ent.get("uid") or 0)
                    if av_elems_map.get(atk_uid) == "Quantum" and last_stance_zero_euid is not None:
                        pending_q_break = (round(cur_av, 2), last_stance_zero_euid, 0)
                        last_stance_zero_euid = None
                if (
                    atk_ent.get("team") == "Player"
                    and int(atk_ent.get("uid") or 0) == 1403
                    and dtype == "Additional"
                    and pending_tie_highest_hp_euid is not None
                ):
                    pick_item = (round(cur_av, 2), 1403, pending_tie_highest_hp_euid)
                    if pick_item not in enemy_retarget_picks:
                        enemy_retarget_picks.append(pick_item)
                    pending_tie_highest_hp_euid = None
            elif ev == "OnStatChange":
                ent = data.get("entity") or {}
                team_tag = ent.get("team")
                uid = int(ent.get("uid") or 0)
                prop = data.get("property") or {}
                ptype = prop.get("type")
                val = float(prop.get("value", 0.0))

                if ptype == "ActionDelay" and abs(val) <= 1e-6:
                    _flush_pending_q_break()

                if team_tag == "Enemy" and uid:
                    if ptype == "CurrentStance" and val <= 1e-6:
                        _flush_pending_q_break()
                        last_stance_zero_euid = uid
                    elif (
                        ptype == "ActionDelay"
                        and pending_q_break is not None
                        and uid == pending_q_break[1]
                        and 0.0 < val < 100.0
                    ):
                        pending_q_break = (pending_q_break[0], pending_q_break[1], pending_q_break[2] + 1)
                    if not saw_first_init_enemy and uid not in seen_init_enemy_uids:
                        seen_init_enemy_uids.add(uid)
                        initial_enemy_uids.append(uid)
                    if ptype == "CurrentStance" and pending_player_atk is not None and pending_hit_hp_euids:
                        pending_hit_direct_euid = uid
                    if (
                        ptype == "CurrentStance"
                        and first_skill_info is not None
                        and not first_skill_done
                        and val > 0.0
                        and uid not in first_skill_stance_obs
                    ):
                        first_skill_stance_obs[uid] = val
                    if (
                        ptype == "CurrentStance"
                        and cur_player_sk_info is not None
                        and not spawn_events_raw
                        and uid not in init_stance_seen_euids
                    ):
                        init_stance_seen_euids.add(uid)
                        init_enemy_first_stance[uid] = (
                            cur_player_sk_info[0],
                            cur_player_sk_info[1],
                            val,
                            cur_player_sk_info[2],
                        )
                    if ptype == "CurrentSP":
                        if pending_player_atk is not None and pending_hit_hp_euids and val > 0.0:
                            pending_hit_direct_euid = uid
                            pending_hit_sp_euid = uid
                        if (
                            cur_enemy_uid is None
                            and paused_enemy_ctx is not None
                            and paused_enemy_ctx["euid"] == uid
                            and val <= 1e-6
                            and abs(round(cur_av, 2) - paused_enemy_ctx["av"]) < 0.05
                            and paused_enemy_ctx["rec_idx"] == len(enemy_hits) - 1
                        ):
                            enemy_hits.pop()
                            cur_enemy_uid = paused_enemy_ctx["euid"]
                            cur_hit_order = list(paused_enemy_ctx["hit_order"])
                            cur_hit_set = set(paused_enemy_ctx["hit_set"])
                            cur_hit_counts = dict(paused_enemy_ctx["hit_counts"])
                            cur_hit_dmgs = dict(paused_enemy_ctx.get("hit_dmgs") or {})
                            cur_clamped_hp_names = set(paused_enemy_ctx.get("clamped_hp_names") or ())
                            cur_sub_actions = list(paused_enemy_ctx["sub_actions"])
                            cur_sub_action_details = list(paused_enemy_ctx.get("sub_details") or [])
                            cur_sub_hits = []
                            cur_sub_sp_gains = {}
                            cur_sub_first_memo = None
                            cur_sub_pending_sp_owner = None
                            cur_small_hp_drops = {}
                            cur_small_heal_uids = set(paused_enemy_ctx["small_heal"])
                            cur_sp_gain_counts = dict(paused_enemy_ctx["sp_gains"])
                            cur_first_memo_owner = paused_enemy_ctx["first_memo"]
                            last_enemy_hit_sp = float(paused_enemy_ctx["last_sp"])
                            paused_enemy_ctx = None
                        if cur_enemy_uid is not None and uid == cur_enemy_uid:
                            if pending_first_sp_owner is not None and not cur_hit_order and cur_first_memo_owner is None:
                                cur_first_memo_owner = pending_first_sp_owner
                            pending_first_sp_owner = None
                            if val <= 1e-6:
                                _flush_sub_action()
                        last_enemy_hit_sp = val if val > 0.0 else 0.0
                    elif ptype == "MaxHP" and uid in gluttony_locked_euids:
                        gluttony_revived_euids.add(uid)
                    elif ptype == "CurrentHP":
                        if abs(val - 1.0) < 0.01:
                            gluttony_locked_euids.add(uid)
                        prev = last_enemy_hp.get(uid)
                        if prev is not None and val < prev - 1.0 and last_enemy_hp:
                            max_cur = max(last_enemy_hp.values())
                            if prev >= max_cur - 1.0 and sum(1 for v in last_enemy_hp.values() if abs(v - prev) < 1.0) >= 2:
                                pending_tie_highest_hp_euid = uid
                            else:
                                pending_tie_highest_hp_euid = None
                        if cur_turn_owner_team is None and not cur_none_had_skill and prev is not None:
                            if val < prev - 1.0:
                                cur_none_enemy_dmgs.append((uid, prev - val))
                                cur_none_last_drop_euid = uid
                                if val <= 1e-3:
                                    cur_none_lethal_euids.add(uid)
                            elif abs(val - prev) <= 1.0 and val > 1e-3:
                                if cur_none_last_drop_euid == uid and abs(val - prev) <= 1e-3:
                                    # 紧随扣血之后同 UID 相同数值的 CurrentHP 广播是贪饕 DirtyHPRatio 同步回声，非护盾吸收命中
                                    cur_none_last_drop_euid = None
                                else:
                                    cur_none_enemy_dmgs.append((uid, 0.0))
                                    cur_none_last_drop_euid = None
                            else:
                                cur_none_last_drop_euid = None
                        elif pending_player_atk is not None and (
                            prev is None
                            or val < prev - 1.0
                            or (
                                (
                                    pending_player_atk[1].startswith("UID_")
                                    or pending_player_atk[1].startswith("BattleEvent_")
                                )
                                and abs(val - prev) <= 1.0
                                and val > 1e-3
                            )
                        ):
                            pending_player_hit_euids.append(uid)
                            if prev is not None and val < prev - 1.0:
                                if uid not in pending_hit_hp_euids:
                                    pending_hit_hp_euids.append(uid)
                                last_player_hit_euid = uid
                                if len(pending_hit_hp_euids) == 1 and uid not in pending_player_hit_dmgs:
                                    pending_player_hit_dmgs[uid] = prev - val
                        elif cur_enemy_uid is not None and uid != cur_enemy_uid and prev is not None and prev > 0.0 and val <= 0.0:
                            enemy_retarget_picks.append((round(cur_av, 2), cur_enemy_uid, uid))
                        last_enemy_hp[uid] = val
                elif team_tag == "Player" and uid:
                    if uid == 1512 and ptype == "ActionDelay" and robin_s_init_ad <= 0.0 and val > 0.0:
                        robin_s_init_ad = val
                    if uid not in seen_uid_set:
                        seen_uid_set.add(uid)
                        seen_uids.append(uid)
                    if pending_ally_ult_caster is not None:
                        if ptype == "ActionDelay" and val < -1.0:
                            tgt_name = _resolve_uid_name(uid, char_db)
                            ally_ult_targets.setdefault(pending_ally_ult_caster, []).append(tgt_name)
                            pending_ally_ult_caster = None
                            pending_ally_ult_sid = 0
                            pending_ally_ult_uid = 0
                            pending_ally_ult_sp_fallback = None
                        elif (
                            pending_ally_ult_sid == 151203
                            and pending_ally_ult_sp_fallback is None
                            and ptype == "CurrentSP"
                            and uid != pending_ally_ult_uid
                            and val > 0.0
                        ):
                            pending_ally_ult_sp_fallback = _resolve_uid_name(uid, char_db)
                    if ptype == "MaxHP":
                        if uid not in last_player_hp:
                            last_player_hp[uid] = val
                    elif ptype == "CurrentSP":
                        if val < -1.0:
                            _pause_enemy_turn_if_active()
                        cname = (
                        f"BattleEvent_{sk_id // 100}"
                        if (uid == 0 and sk_id >= 1000000)
                        else _resolve_uid_name(uid, char_db)
                    )
                        prev_sp = last_player_sp.get(uid)
                        is_enemy_hit_sp = (
                            cur_enemy_uid is not None
                            and 0.2 < val < 35.0
                            and last_enemy_hit_sp > 0.0
                            and 0.99 <= (val / last_enemy_hit_sp) <= 1.60
                            and not (prev_sp is not None and abs((val - prev_sp) - 3.0) < 1e-3)
                        )
                        if is_enemy_hit_sp:
                            small_drops = cur_small_hp_drops.get(cname)
                            if small_drops:
                                drop_delta = small_drops.pop(0)
                                if pending_first_sp_owner is not None:
                                    if pending_first_sp_owner != cname and cur_first_memo_owner is None:
                                        cur_first_memo_owner = pending_first_sp_owner
                                    pending_first_sp_owner = None
                                if cur_sub_pending_sp_owner is not None:
                                    if cur_sub_pending_sp_owner != cname and cur_sub_first_memo is None:
                                        cur_sub_first_memo = cur_sub_pending_sp_owner
                                    cur_sub_pending_sp_owner = None
                                if cname not in cur_hit_set:
                                    cur_hit_set.add(cname)
                                    cur_hit_order.append(cname)
                                cur_sub_hits.append(cname)
                                cur_hit_counts[cname] = cur_hit_counts.get(cname, 0) + 1
                                cur_hit_dmgs[cname] = cur_hit_dmgs.get(cname, 0.0) + drop_delta
                            else:
                                if not cur_hit_order and cur_first_memo_owner is None and pending_first_sp_owner is None:
                                    pending_first_sp_owner = cname
                                if not cur_sub_hits and cur_sub_first_memo is None and cur_sub_pending_sp_owner is None:
                                    cur_sub_pending_sp_owner = cname
                            cur_sp_gain_counts[cname] = cur_sp_gain_counts.get(cname, 0) + 1
                            cur_sub_sp_gains[cname] = cur_sub_sp_gains.get(cname, 0) + 1
                        elif cur_turn_owner_team is None and not cur_none_had_skill:
                            sp_delta = (val - prev_sp) if prev_sp is not None else val
                            if cur_none_pending_hp_chip_uid == uid:
                                cur_none_ally_sp_counts[cname] = cur_none_ally_sp_counts.get(cname, 0) + 1
                                cur_none_pending_hp_chip_uid = None
                            elif (1.8 <= sp_delta <= 2.9) or (prev_sp is not None and val >= 100.0 and abs(val - prev_sp) < 1e-4 and val > 0.0):
                                cur_none_ally_sp_counts[cname] = cur_none_ally_sp_counts.get(cname, 0) + 1
                        if val <= 0.0:
                            last_player_sp[uid] = 0.0
                        elif prev_sp is not None and (
                            is_enemy_hit_sp
                            or (val <= 35.0 and val <= prev_sp + 1e-4)
                        ):
                            last_player_sp[uid] = prev_sp + val
                        else:
                            last_player_sp[uid] = val
                    elif ptype == "Speed":
                        prev_spd = last_player_spd.get(uid)
                        if cur_enemy_uid is not None and prev_spd is not None and val < prev_spd - 1.0:
                            slow_hits.add((round(cur_av, 2), _resolve_uid_name(uid, char_db)))
                        last_player_spd[uid] = val
                    elif ptype == "CurrentHP":
                        if (
                            in_aoe_heal_window
                            and not inferred_slot_uids
                            and char_db.get(uid) is not None
                        ):
                            if uid not in aoe_heal_slot_uids:
                                aoe_heal_slot_uids.append(uid)
                        prev = last_player_hp.get(uid)
                        if cur_enemy_uid is not None:
                            if prev is None:
                                if val > 550.0:
                                    name = _resolve_uid_name(uid, char_db)
                                    if name not in cur_hit_set:
                                        cur_hit_set.add(name)
                                        cur_hit_order.append(name)
                                    cur_sub_hits.append(name)
                                    cur_hit_counts[name] = cur_hit_counts.get(name, 0) + 1
                            elif 120.0 <= val <= 550.0 and val < prev * 0.35:
                                cur_small_heal_uids.add(uid)
                                _flush_sub_action()
                            elif val < prev - 1e-3 and (prev - val) < prev * 0.60:
                                delta = prev - val
                                # 过滤敌方回合结束时的 1% 伴生微伤/DoT，避免误将未受直接攻击的队友计入受击/扩散目标
                                if delta >= 200.0 or delta >= prev * 0.02:
                                    name = _resolve_uid_name(uid, char_db)
                                    if pending_first_sp_owner is not None:
                                        if pending_first_sp_owner != name and cur_first_memo_owner is None:
                                            cur_first_memo_owner = pending_first_sp_owner
                                        pending_first_sp_owner = None
                                    if cur_sub_pending_sp_owner is not None:
                                        if cur_sub_pending_sp_owner != name and cur_sub_first_memo is None:
                                            cur_sub_first_memo = cur_sub_pending_sp_owner
                                        cur_sub_pending_sp_owner = None
                                    if name not in cur_hit_set:
                                        cur_hit_set.add(name)
                                        cur_hit_order.append(name)
                                    cur_sub_hits.append(name)
                                    cur_hit_counts[name] = cur_hit_counts.get(name, 0) + 1
                                    cur_hit_dmgs[name] = cur_hit_dmgs.get(name, 0.0) + delta
                                elif delta >= 10.0:
                                    name = _resolve_uid_name(uid, char_db)
                                    cur_small_hp_drops.setdefault(name, []).append(delta)
                            elif abs(val - 1.0) <= 1e-2:
                                name = _resolve_uid_name(uid, char_db)
                                cur_clamped_hp_names.add(name)
                                cur_small_hp_drops.setdefault(name, []).append(max(1.0, prev - val))
                            elif val < prev - 1e-3:
                                name = _resolve_uid_name(uid, char_db)
                                cur_small_hp_drops.setdefault(name, []).append(prev - val)
                        elif cur_turn_owner_team is None and not cur_none_had_skill and prev is not None:
                            # 阿哈回合我方伴生微伤（通常 0.1~5.0 点 HP）
                            delta = prev - val
                            if 0.05 <= delta <= 10.0:
                                cur_none_ally_chips.append(_resolve_uid_name(uid, char_db))
                                cur_none_pending_hp_chip_uid = uid
                        if prev is None or val >= prev * 0.40 or val <= 1.0 + 1e-2:
                            last_player_hp[uid] = val

    _flush_pending_player_atk()
    _flush_turn()
    _flush_pending_q_break()

    # 排除已在 OnInitializeEnemy 登记的后续生成怪（其属性初始化 OnStatChange 可能早于 OnInitializeEnemy 发出）
    spawn_euids = {u for u, _ in spawn_events_raw}
    initial_enemy_uids = [u for u in initial_enemy_uids if u not in spawn_euids]

    # 基于官方 StageDataLoader 通用映射任意关卡的初始敌方与召唤物 UID（零关卡硬编码）
    summon_monster_names: Set[str] = set()
    wave0_names: List[str] = []
    stage_spec = None
    if stage_id > 0:
        try:
            stage_spec = StageDataLoader().load_stage(stage_id)
            if stage_spec.waves:
                wave0_names = [m.name for m in stage_spec.waves[0].monsters]
            summon_monster_names = {m.name for m in stage_spec.summon_monsters.values()}
        except Exception:
            pass

    is_infinite_stage = bool(stage_spec is not None and stage_spec.stage_infinite_group_id is not None)
    if is_infinite_stage and stage_spec is not None and stage_spec.waves and initial_enemy_uids:
        w0_monsters = stage_spec.waves[0].monsters
        sorted_init = sorted(initial_enemy_uids)
        max_field = stage_spec.waves[0].max_teammate_count or 5
        if w0_monsters and w0_monsters[0].monster_id == 8003060:
            if len(sorted_init) > max_field:
                enemy_uid_map.setdefault(sorted_init[0], w0_monsters[0].name)
                formation_init_uids = sorted_init[1:]
            else:
                enemy_uid_map.setdefault(sorted_init[0] - 2, w0_monsters[0].name)
                formation_init_uids = sorted_init
        else:
            formation_init_uids = sorted_init
        init_names = [m.name for m in w0_monsters if m.monster_id != 8003060][:len(formation_init_uids)]
        inf_seen_cnt: Dict[str, int] = {}
        for euid, nm in zip(formation_init_uids, init_names):
            inf_seen_cnt[nm] = inf_seen_cnt.get(nm, 0) + 1
            cnt = inf_seen_cnt[nm]
            enemy_uid_map.setdefault(euid, nm if cnt == 1 else f"{nm}_{cnt}")
        all_wave_monster_names = {m.name for w in stage_spec.waves for m in w.monsters}
        only_summon_names = summon_monster_names - all_wave_monster_names
        for euid, ename in spawn_events_raw:
            inf_seen_cnt[ename] = inf_seen_cnt.get(ename, 0) + 1
            cnt = inf_seen_cnt[ename]
            if ename in only_summon_names:
                enemy_uid_map[euid] = f"{ename}_{cnt}"
            else:
                enemy_uid_map[euid] = ename if cnt == 1 else f"{ename}_{cnt}"
    else:
        spawn_seq_by_name: Dict[str, int] = {}
        if wave0_names and initial_enemy_uids:
            sorted_init = sorted(initial_enemy_uids)
            name_totals: Dict[str, int] = {}
            for nm in wave0_names:
                name_totals[nm] = name_totals.get(nm, 0) + 1
            seen_init_name_cnt: Dict[str, int] = {}
            for euid, nm in zip(sorted_init, wave0_names):
                if name_totals[nm] > 1:
                    seen_init_name_cnt[nm] = seen_init_name_cnt.get(nm, 0) + 1
                    enemy_uid_map.setdefault(euid, f"{nm}_{seen_init_name_cnt[nm]}")
                else:
                    enemy_uid_map.setdefault(euid, nm)
            if len(sorted_init) > len(wave0_names) and stage_spec is not None and stage_spec.waves:
                w0_summon_names: List[str] = []
                w0_smap = stage_spec.waves[0].summon_monsters
                for m in stage_spec.waves[0].monsters:
                    for sid in getattr(m, "summon_ids", ()):
                        sm = w0_smap.get(sid) or stage_spec.summon_monsters.get(sid)
                        if sm is not None:
                            w0_summon_names.append(sm.name)
                for euid, nm in zip(sorted_init[len(wave0_names):], w0_summon_names):
                    spawn_seq_by_name[nm] = spawn_seq_by_name.get(nm, 0) + 1
                    enemy_uid_map.setdefault(euid, f"{nm}_{spawn_seq_by_name[nm]}")

        raw_name_totals: Dict[str, int] = {}
        for _, ename in spawn_events_raw:
            raw_name_totals[ename] = raw_name_totals.get(ename, 0) + 1
        for euid, ename in spawn_events_raw:
            if ename in summon_monster_names or raw_name_totals[ename] > 1:
                spawn_seq_by_name[ename] = spawn_seq_by_name.get(ename, 0) + 1
                enemy_uid_map[euid] = f"{ename}_{spawn_seq_by_name[ename]}"
            else:
                enemy_uid_map[euid] = ename

    # 对阿哈回合被特殊护盾全额吸收（delta_hp <= 1.0）的命中段：
    # 1) 同回合有其他未带盾敌方扣血时，按同日志实测同回合双目标基础伤害比（抗性比）缩放置换；
    # 2) 全段均被护盾吸收时，回退至该怪物（或同场前次未带盾）单段观测伤害。
    def _base_enemy_name(u: int) -> str:
        nm = enemy_uid_map.get(u, "")
        if "_" in nm and nm.rsplit("_", 1)[1].isdigit():
            return nm.rsplit("_", 1)[0]
        return nm

    pairwise_ratios: Dict[Tuple[str, str], List[float]] = {}
    for a in aha_turns:
        by_base: Dict[str, List[float]] = {}
        for u, d in a.enemy_damages:
            if d > 1.0:
                bn = _base_enemy_name(u)
                if bn:
                    by_base.setdefault(bn, []).append(d)
        base_med = {bn: sorted(ds)[len(ds) // 2] for bn, ds in by_base.items()}
        for b_t, d_t in base_med.items():
            for b_r, d_r in base_med.items():
                if b_t != b_r and d_r > 1.0:
                    pairwise_ratios.setdefault((b_t, b_r), []).append(d_t / d_r)
    med_ratio = {k: sorted(vs)[len(vs) // 2] for k, vs in pairwise_ratios.items()}

    global_unshielded_by_base: Dict[str, List[float]] = {}
    all_unshielded_hits: List[float] = []
    for a in aha_turns:
        for u, d in a.enemy_damages:
            if d > 1.0:
                bn = _base_enemy_name(u)
                if bn:
                    global_unshielded_by_base.setdefault(bn, []).append(d)
                all_unshielded_hits.append(d)
    global_med_by_base = {bn: sorted(ds)[len(ds) // 2] for bn, ds in global_unshielded_by_base.items()}
    global_any_med = sorted(all_unshielded_hits)[len(all_unshielded_hits) // 2] if all_unshielded_hits else 0.0

    last_unshielded_by_base: Dict[str, float] = {}
    last_any_unshielded: float = 0.0
    for a in aha_turns:
        pos_items = [(u, d) for u, d in a.enemy_damages if d > 1.0]
        new_dmgs: List[Tuple[int, float]] = []
        for u, d in a.enemy_damages:
            if d <= 1.0:
                a.shielded_enemy_uids.add(u)
            if d > 1.0:
                new_dmgs.append((u, d))
                bn = _base_enemy_name(u)
                if bn:
                    last_unshielded_by_base[bn] = d
                last_any_unshielded = d
            elif pos_items:
                bn = _base_enemy_name(u)
                est_list: List[float] = []
                for u_ref, d_ref in pos_items:
                    b_ref = _base_enemy_name(u_ref)
                    r = med_ratio.get((bn, b_ref))
                    if r is not None:
                        est_list.append(d_ref * r)
                if est_list:
                    est = sorted(est_list)[len(est_list) // 2]
                else:
                    est = max(dr for _, dr in pos_items)
                new_dmgs.append((u, est))
                if bn:
                    last_unshielded_by_base[bn] = est
                last_any_unshielded = est
            else:
                bn = _base_enemy_name(u)
                est = last_unshielded_by_base.get(bn, 0.0)
                if est <= 1.0:
                    g_est = global_med_by_base.get(bn, global_any_med)
                    est = g_est if g_est > 1.0 else 0.0
                new_dmgs.append((u, est))
        a.enemy_damages = new_dmgs

    non_formation_euids: Set[int] = set()
    if stage_spec is not None and stage_spec.waves:
        nf_names = {m.name for w in stage_spec.waves for m in w.monsters if m.monster_id == 8003060}
        if nf_names:
            non_formation_euids = {u for u, nm in enemy_uid_map.items() if nm in nf_names}

    for (
        p_atk,
        p_is_servant,
        p_skill_id,
        p_skill_type,
        p_primary_hits,
        p_hit_euids_raw,
        p_dmg_confirmed_raw,
        p_hit_dmgs_raw,
        p_sp_euids_raw,
    ) in pending_player_atk_records:
        p_hit_euids = [u for u in p_hit_euids_raw if u not in non_formation_euids] if non_formation_euids else p_hit_euids_raw
        p_dmg_confirmed = [u for u in p_dmg_confirmed_raw if u not in non_formation_euids] if non_formation_euids else p_dmg_confirmed_raw
        p_hit_dmgs = {u: d for u, d in p_hit_dmgs_raw.items() if u not in non_formation_euids} if non_formation_euids else p_hit_dmgs_raw
        p_sp_euids = [u for u in p_sp_euids_raw if u not in non_formation_euids] if non_formation_euids else p_sp_euids_raw
        if p_is_servant:
            sk_eff = servant_skill_effects.get(p_skill_id, "")
            if sk_eff == "SingleAttack":
                servant_targets_raw.setdefault(p_atk, []).append(
                    _servant_primary_euid(p_dmg_confirmed if p_dmg_confirmed else p_hit_euids)
                )
            elif sk_eff in ("AoEAttack", "Blast", "Bounce"):
                inferred_primary: Optional[int] = None
                if sk_eff in ("AoEAttack", "Blast"):
                    if len(p_sp_euids) == 1:
                        inferred_primary = p_sp_euids[0]
                    elif len(p_hit_dmgs) >= 2:
                        sorted_dmgs = sorted(p_hit_dmgs.items(), key=lambda kv: kv[1], reverse=True)
                        if sorted_dmgs[1][1] > 0.0 and sorted_dmgs[0][1] > sorted_dmgs[1][1] * 1.4:
                            inferred_primary = sorted_dmgs[0][0]
                servant_targets_raw.setdefault(p_atk, []).append(inferred_primary)
            elif not sk_eff:
                _servant_euid = _servant_primary_euid(p_dmg_confirmed if p_dmg_confirmed else p_hit_euids)
                if _servant_euid is not None:
                    servant_targets_raw.setdefault(p_atk, []).append(_servant_euid)
        elif (
            p_primary_hits == 1
            or (
                (p_atk[1].startswith("UID_") or p_atk[1].startswith("BattleEvent_"))
                and p_primary_hits == 0
                and len(set(p_hit_euids)) == 1
            )
        ) and (p_dmg_confirmed or p_hit_euids):
            av_eff = avatar_skill_effects.get(p_skill_id, "")
            if av_eff in ("SingleAttack", "") and p_skill_type != "Ultra":
                pri_euid = p_dmg_confirmed[0] if p_dmg_confirmed else p_hit_euids[0]
                player_enemy_targets_raw.setdefault(p_atk, []).append(pri_euid)

    player_enemy_targets: Dict[Tuple[float, str], List[str]] = {}
    for k_pt, euids in player_enemy_targets_raw.items():
        names = [enemy_uid_map[u] for u in euids if u in enemy_uid_map]
        if names:
            player_enemy_targets[k_pt] = names

    servant_targets: Dict[Tuple[float, str], List[Optional[str]]] = {}
    for k_pt, euids in servant_targets_raw.items():
        seq: List[Optional[str]] = [
            (enemy_uid_map.get(u) if u is not None else None) for u in euids
        ]
        while seq and seq[-1] is None:
            seq.pop()
        if any(x is not None for x in seq):
            servant_targets[k_pt] = seq

    if team_override:
        team_names = list(team_override)
        team_uids = []
        for n in team_names:
            rp = char_db.get_by_name(n)
            if rp is None and "_" in n:
                rp = char_db.get_by_name(n.split("_", 1)[0])
            team_uids.append(int(rp.avatar_id) if rp is not None else 0)
    else:
        valid_uids = [u for u in seen_uids if char_db.get(u) is not None]
        if len(aoe_heal_slot_uids) >= 2 and not inferred_slot_uids:
            inferred_slot_uids = list(aoe_heal_slot_uids)
        if inferred_slot_uids:
            ordered = [u for u in inferred_slot_uids if u in valid_uids]
            ordered.extend(u for u in valid_uids if u not in ordered)
            valid_uids = ordered
        elif 1409 in valid_uids:
            valid_uids = [1409] + [u for u in valid_uids if u != 1409]
        team_uids = valid_uids
        team_names = []
        for u in valid_uids:
            nm = _resolve_uid_name(u, char_db)
            if (
                u == 1512
                and 0.0 < robin_s_init_ad < 44.3
                and char_db.get_by_name("知更鸟•晴歌_爱如此刻永恒") is not None
            ):
                nm = "知更鸟•晴歌_爱如此刻永恒"
            team_names.append(nm)

    entry_element: Optional[str] = None
    entry_toughness: float = 10.0
    if stage_spec is not None and stage_spec.waves:
        w0_by_name: Dict[str, List[Any]] = {}

        def _add_w0_spec(mspec: Any) -> None:
            lst = w0_by_name.setdefault(mspec.name, [])
            if all(existing.monster_id != mspec.monster_id for existing in lst):
                lst.append(mspec)

        for m in stage_spec.waves[0].monsters:
            _add_w0_spec(m)
        for sm in stage_spec.waves[0].summon_monsters.values():
            _add_w0_spec(sm)
        for sm in stage_spec.summon_monsters.values():
            _add_w0_spec(sm)
        av_elems = _get_avatar_damage_types()
        if first_skill_info is not None and first_skill_stance_obs:
            sk_id, sk_caster_uid = first_skill_info
            sk_stance = _get_avatar_skill_stances().get(sk_id, 0.0)
            if sk_stance > 0.0:
                for euid, new_stance in first_skill_stance_obs.items():
                    base_nm = _base_enemy_name(euid)
                    for m_spec in w0_by_name.get(base_nm, ()):
                        if m_spec.toughness > 0.0:
                            missing = float(m_spec.toughness) - float(sk_stance) - float(new_stance)
                            if missing >= 15.0:
                                entry_toughness = round(missing, 1)
                                entry_element = av_elems.get(sk_caster_uid)
                                break
                    if entry_element is not None:
                        break
        if entry_element is None and init_enemy_first_stance:
            stance_pairs = _get_avatar_skill_stance_pairs()
            init_euid_set = set(initial_enemy_uids)
            for euid, (sk_id, sk_uid, new_stance, atk_seq) in init_enemy_first_stance.items():
                if euid not in init_euid_set:
                    continue
                pair = stance_pairs.get(sk_id)
                elem = av_elems.get(sk_uid)
                if not pair or not elem:
                    continue
                base_nm = _base_enemy_name(euid)
                pri_st, sub_st = pair
                dmgs = skill_atk_dmgs.get(atk_seq, {})
                is_primary = True
                if pri_st != sub_st and len(dmgs) >= 2:
                    max_d = max(dmgs.values())
                    e_d = dmgs.get(euid, 0.0)
                    if max_d > 0.0 and e_d < max_d * 0.8:
                        is_primary = False
                sk_stance = pri_st if is_primary else sub_st
                for m_spec in w0_by_name.get(base_nm, ()):
                    if m_spec.toughness <= 0.0:
                        continue
                    norm_weak = {"Lightning" if w == "Thunder" else w for w in getattr(m_spec, "weaknesses", ())}
                    if elem not in norm_weak:
                        continue
                    missing = float(m_spec.toughness) - float(sk_stance) - float(new_stance)
                    if missing >= 15.0:
                        entry_toughness = round(missing, 1)
                        entry_element = elem
                        break
                if entry_element is not None:
                    break

    enemy_hp_at_turn_end: Dict[Tuple[float, str], float] = {
        (av_k, enemy_uid_map[eu]): ehp
        for (av_k, eu), ehp in enemy_hp_at_turn_end_raw.items()
        if eu in enemy_uid_map
    }

    quantum_entangle_resists: Set[Tuple[float, str]] = {
        (q_av, enemy_uid_map[eu])
        for q_av, eu in quantum_entangle_resists_raw
        if eu in enemy_uid_map
    }

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
        enemy_retarget_picks=enemy_retarget_picks,
        player_enemy_targets=player_enemy_targets,
        servant_targets=servant_targets,
        aha_turns=aha_turns,
        windwalk_enemy_uids=windwalk_enemy_uids,
        slow_hits=slow_hits,
        quantum_entangle_resists=quantum_entangle_resists,
        enemy_hp_at_turn_end=enemy_hp_at_turn_end,
        enemy_spawns=enemy_spawns,
        gluttony_enemy_names={enemy_uid_map[u] for u in gluttony_revived_euids if u in enemy_uid_map},
        entry_element=entry_element,
        entry_toughness=entry_toughness,
    )

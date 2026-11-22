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
    _get_avatar_skill_effects,
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
    cur_sub_hits: List[str] = []
    cur_sub_actions: List[List[str]] = []
    cur_small_heal_uids: Set[int] = set()
    cur_sp_gain_counts: Dict[str, int] = {}
    cur_first_memo_owner: Optional[str] = None
    pending_first_sp_owner: Optional[str] = None
    last_enemy_hit_sp: float = 0.0
    paused_enemy_ctx: Optional[Dict[str, Any]] = None

    # 无归属回合（阿哈回合）追踪
    cur_none_had_skill = False
    cur_none_enemy_dmgs: List[Tuple[int, float]] = []
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
    pending_player_hit_dmgs: Dict[int, float] = {}
    pending_player_primary_dmg_hits = 0
    pending_player_is_servant = False
    pending_player_skill_id = 0
    pending_player_skill_type = ""
    player_enemy_targets_raw: Dict[Tuple[float, str], List[int]] = {}
    servant_targets_raw: Dict[Tuple[float, str], List[Optional[int]]] = {}
    servant_skill_effects = _get_servant_skill_effects()
    avatar_skill_effects = _get_avatar_skill_effects()
    in_aoe_heal_window = False
    aoe_heal_slot_uids: List[int] = []
    inferred_slot_uids: List[int] = []

    def _servant_primary_euid() -> Optional[int]:
        """单体忆灵技主目标：仅在官方技能表为 SingleAttack 且全段命中同一个敌方时提取。"""
        ordered: List[int] = []
        for u in pending_player_hit_euids:
            if u not in ordered:
                ordered.append(u)
        if len(ordered) == 1:
            return ordered[0]
        return None

    def _flush_pending_player_atk() -> None:
        nonlocal pending_player_atk, pending_player_hit_euids, pending_player_hit_dmgs, pending_player_primary_dmg_hits
        nonlocal pending_player_is_servant, pending_player_skill_id, pending_player_skill_type
        if pending_player_atk is not None:
            if pending_player_is_servant:
                # 依据官方 AvatarServantSkillConfig.SkillEffect 区分单体技与群攻/扩散/弹射技：
                # - SingleAttack：登记唯一扣血敌方为主目标（避免锁血/残血场景把群攻误判为单体）
                # - AoEAttack/Blast：若某目标首次扣血量显著高于次高目标（>1.4x，如主副倍率群攻/扩散），锁定为主目标；否则 None 占位
                # - Bounce：写入 None 占位，保证同 AV 混排时游标不串号
                sk_eff = servant_skill_effects.get(pending_player_skill_id, "")
                if sk_eff == "SingleAttack":
                    servant_targets_raw.setdefault(pending_player_atk, []).append(_servant_primary_euid())
                elif sk_eff in ("AoEAttack", "Blast", "Bounce"):
                    inferred_primary: Optional[int] = None
                    if sk_eff in ("AoEAttack", "Blast") and len(pending_player_hit_dmgs) >= 2:
                        sorted_dmgs = sorted(pending_player_hit_dmgs.items(), key=lambda kv: kv[1], reverse=True)
                        if sorted_dmgs[1][1] > 0.0 and sorted_dmgs[0][1] > sorted_dmgs[1][1] * 1.4:
                            inferred_primary = sorted_dmgs[0][0]
                    servant_targets_raw.setdefault(pending_player_atk, []).append(inferred_primary)
                elif not sk_eff:
                    # 未知忆灵技兜底：仅在无歧义单目标时登记
                    _servant_euid = _servant_primary_euid()
                    if _servant_euid is not None:
                        servant_targets_raw.setdefault(pending_player_atk, []).append(_servant_euid)
            # 仅对纯单体技能（主技能 OnDamage 命中数 == 1，如风堇普攻）记录首个扣血敌方为主目标；
            # 扩散/群攻（主技能 OnDamage 命中数 > 1，如缇宝普攻）由默认居中逻辑处理
            elif (
                pending_player_primary_dmg_hits == 1
                or (
                    pending_player_atk[1].startswith("UID_")
                    and pending_player_primary_dmg_hits == 0
                    and len(pending_player_hit_euids) == 1
                )
            ) and pending_player_hit_euids:
                av_eff = avatar_skill_effects.get(pending_player_skill_id, "")
                if av_eff in ("SingleAttack", "") and pending_player_skill_type != "Ultra":
                    player_enemy_targets_raw.setdefault(pending_player_atk, []).append(pending_player_hit_euids[0])
        pending_player_atk = None
        pending_player_hit_euids = []
        pending_player_hit_dmgs = {}
        pending_player_primary_dmg_hits = 0
        pending_player_is_servant = False
        pending_player_skill_id = 0
        pending_player_skill_type = ""

    last_player_hp: Dict[int, float] = {}
    last_player_spd: Dict[int, float] = {}
    slow_hits: Set[Tuple[float, str]] = set()
    last_enemy_hp: Dict[int, float] = {}
    enemy_hp_at_turn_end_raw: Dict[Tuple[float, int], float] = {}
    pending_tie_highest_hp_euid: Optional[int] = None
    enemy_hits: List[EnemyHitRecord] = []
    aha_turns: List[AhaTurnRecord] = []

    def _flush_turn() -> None:
        nonlocal cur_enemy_uid, cur_hit_order, cur_hit_set, cur_hit_counts, cur_hit_dmgs, cur_sub_hits, cur_sub_actions, cur_small_heal_uids, cur_sp_gain_counts, cur_first_memo_owner, pending_first_sp_owner, last_enemy_hit_sp
        nonlocal cur_turn_owner_team, cur_none_had_skill, cur_none_enemy_dmgs, cur_none_lethal_euids, cur_none_ally_chips, cur_none_ally_sp_counts, cur_none_pending_hp_chip_uid
        if cur_enemy_uid is not None:
            if pending_first_sp_owner is not None and not cur_hit_order and cur_first_memo_owner is None:
                cur_first_memo_owner = pending_first_sp_owner
            pending_first_sp_owner = None
            if cur_sub_hits:
                cur_sub_actions.append(list(cur_sub_hits))
            eff_hit_order = list(cur_hit_order)
            # 敌方多动中若先放全体 AoE 再放单体点名（如 Skill02 + Skill01 [+ Skill04]），将单体目标放在首位供 target_provider 精准锁定
            if len(cur_sub_actions) >= 2 and len(set(cur_sub_actions[0])) >= 2:
                st_subs = [sub[0] for sub in cur_sub_actions[1:] if len(set(sub)) == 1]
                if st_subs:
                    st_tgt = st_subs[0]
                    if st_tgt in eff_hit_order:
                        eff_hit_order.remove(st_tgt)
                    eff_hit_order.insert(0, st_tgt)
            elif len(cur_sub_actions) == 1 and len(cur_hit_dmgs) >= 2:
                # 全体主/副双倍率技能（如锁定单人高倍率重击 + 其余低倍率波及）：将承伤显著最高者置首作为主目标
                sorted_dmgs = sorted(cur_hit_dmgs.items(), key=lambda kv: kv[1], reverse=True)
                if sorted_dmgs[1][1] > 0.0 and sorted_dmgs[0][1] > sorted_dmgs[1][1] * 1.8:
                    prim = sorted_dmgs[0][0]
                    if prim in eff_hit_order:
                        eff_hit_order.remove(prim)
                    eff_hit_order.insert(0, prim)
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
        cur_sub_hits = []
        cur_sub_actions = []
        cur_small_heal_uids = set()
        cur_sp_gain_counts = {}
        cur_first_memo_owner = None
        pending_first_sp_owner = None
        last_enemy_hit_sp = 0.0
        cur_none_had_skill = False
        cur_none_enemy_dmgs = []
        cur_none_lethal_euids = set()
        cur_none_ally_chips = []
        cur_none_ally_sp_counts = {}
        cur_none_pending_hp_chip_uid = None

    def _pause_enemy_turn_if_active() -> None:
        nonlocal paused_enemy_ctx
        if cur_enemy_uid is not None:
            _paused_sub_actions = list(cur_sub_actions)
            if cur_sub_hits:
                _paused_sub_actions.append(list(cur_sub_hits))
            _snap = {
                "av": round(cur_av, 2),
                "euid": cur_enemy_uid,
                "hit_order": list(cur_hit_order),
                "hit_set": set(cur_hit_set),
                "hit_counts": dict(cur_hit_counts),
                "hit_dmgs": dict(cur_hit_dmgs),
                "sub_actions": _paused_sub_actions,
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
                _flush_pending_player_atk()
            elif ev == "OnUseSkill":
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
                    cname = _resolve_uid_name(uid, char_db)
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
                atk_ent = data.get("attacker") or {}
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

                if team_tag == "Enemy" and uid:
                    if not saw_first_init_enemy and uid not in seen_init_enemy_uids:
                        seen_init_enemy_uids.add(uid)
                        initial_enemy_uids.append(uid)
                    if ptype == "CurrentSP":
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
                            cur_sub_actions = list(paused_enemy_ctx["sub_actions"])
                            cur_sub_hits = []
                            cur_small_heal_uids = set(paused_enemy_ctx["small_heal"])
                            cur_sp_gain_counts = dict(paused_enemy_ctx["sp_gains"])
                            cur_first_memo_owner = paused_enemy_ctx["first_memo"]
                            last_enemy_hit_sp = float(paused_enemy_ctx["last_sp"])
                            paused_enemy_ctx = None
                        if cur_enemy_uid is not None and uid == cur_enemy_uid:
                            if pending_first_sp_owner is not None and not cur_hit_order and cur_first_memo_owner is None:
                                cur_first_memo_owner = pending_first_sp_owner
                            pending_first_sp_owner = None
                        if cur_enemy_uid is not None and uid == cur_enemy_uid and val <= 1e-6 and cur_sub_hits:
                            cur_sub_actions.append(list(cur_sub_hits))
                            cur_sub_hits = []
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
                                if val <= 1e-3:
                                    cur_none_lethal_euids.add(uid)
                            elif abs(val - prev) <= 1.0 and val > 1e-3:
                                cur_none_enemy_dmgs.append((uid, 0.0))
                        elif pending_player_atk is not None and (
                            prev is None
                            or val < prev - 1.0
                            or (pending_player_atk[1].startswith("UID_") and abs(val - prev) <= 1.0 and val > 1e-3)
                        ):
                            pending_player_hit_euids.append(uid)
                            if prev is not None and val < prev - 1.0 and uid not in pending_player_hit_dmgs:
                                pending_player_hit_dmgs[uid] = prev - val
                        elif cur_enemy_uid is not None and uid != cur_enemy_uid and prev is not None and prev > 0.0 and val <= 0.0:
                            enemy_retarget_picks.append((round(cur_av, 2), cur_enemy_uid, uid))
                        last_enemy_hp[uid] = val
                elif team_tag == "Player" and uid:
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
                        cname = _resolve_uid_name(uid, char_db)
                        prev_sp = last_player_sp.get(uid)
                        is_enemy_hit_sp = (
                            cur_enemy_uid is not None
                            and 1.0 < val < 35.0
                            and last_enemy_hit_sp > 0.0
                            and 0.99 <= (val / last_enemy_hit_sp) <= 1.60
                            and not (prev_sp is not None and abs((val - prev_sp) - 3.0) < 1e-3)
                        )
                        if is_enemy_hit_sp:
                            if not cur_hit_order and cur_first_memo_owner is None and pending_first_sp_owner is None:
                                pending_first_sp_owner = cname
                            cur_sp_gain_counts[cname] = cur_sp_gain_counts.get(cname, 0) + 1
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
                                if cur_sub_hits:
                                    cur_sub_actions.append(list(cur_sub_hits))
                                    cur_sub_hits = []
                            elif val < prev - 1e-3 and (prev - val) < prev * 0.60:
                                delta = prev - val
                                # 过滤敌方回合结束时的 1% 伴生微伤/DoT，避免误将未受直接攻击的队友计入受击/扩散目标
                                if delta >= 200.0 or delta >= prev * 0.02:
                                    name = _resolve_uid_name(uid, char_db)
                                    if pending_first_sp_owner is not None:
                                        if pending_first_sp_owner != name and cur_first_memo_owner is None:
                                            cur_first_memo_owner = pending_first_sp_owner
                                        pending_first_sp_owner = None
                                    if name not in cur_hit_set:
                                        cur_hit_set.add(name)
                                        cur_hit_order.append(name)
                                    cur_sub_hits.append(name)
                                    cur_hit_counts[name] = cur_hit_counts.get(name, 0) + 1
                                    cur_hit_dmgs[name] = cur_hit_dmgs.get(name, 0.0) + delta
                        elif cur_turn_owner_team is None and not cur_none_had_skill and prev is not None:
                            # 阿哈回合我方伴生微伤（通常 0.1~5.0 点 HP）
                            delta = prev - val
                            if 0.05 <= delta <= 10.0:
                                cur_none_ally_chips.append(_resolve_uid_name(uid, char_db))
                                cur_none_pending_hp_chip_uid = uid
                        if prev is None or val >= prev * 0.40:
                            last_player_hp[uid] = val

    _flush_pending_player_atk()
    _flush_turn()

    # 基于官方 StageDataLoader 通用映射任意关卡的初始敌方与召唤物 UID（零关卡硬编码）
    summon_monster_names: Set[str] = set()
    wave0_names: List[str] = []
    if stage_id > 0:
        try:
            stage_spec = StageDataLoader().load_stage(stage_id)
            if stage_spec.waves:
                wave0_names = [m.name for m in stage_spec.waves[0].monsters]
            summon_monster_names = {m.name for m in stage_spec.summon_monsters.values()}
        except Exception:
            pass

    if wave0_names and initial_enemy_uids:
        name_totals: Dict[str, int] = {}
        for nm in wave0_names:
            name_totals[nm] = name_totals.get(nm, 0) + 1
        seen_init_name_cnt: Dict[str, int] = {}
        for euid, nm in zip(sorted(initial_enemy_uids), wave0_names):
            if name_totals[nm] > 1:
                seen_init_name_cnt[nm] = seen_init_name_cnt.get(nm, 0) + 1
                enemy_uid_map.setdefault(euid, f"{nm}_{seen_init_name_cnt[nm]}")
            else:
                enemy_uid_map.setdefault(euid, nm)

    raw_name_totals: Dict[str, int] = {}
    for _, ename in spawn_events_raw:
        raw_name_totals[ename] = raw_name_totals.get(ename, 0) + 1
    spawn_seq_by_name: Dict[str, int] = {}
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
        team_names = [_resolve_uid_name(u, char_db) for u in valid_uids]

    enemy_hp_at_turn_end: Dict[Tuple[float, str], float] = {
        (av_k, enemy_uid_map[eu]): ehp
        for (av_k, eu), ehp in enemy_hp_at_turn_end_raw.items()
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
        enemy_hp_at_turn_end=enemy_hp_at_turn_end,
        enemy_spawns=enemy_spawns,
        gluttony_enemy_names={enemy_uid_map[u] for u in gluttony_revived_euids if u in enemy_uid_map},
    )

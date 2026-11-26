# coding: utf-8
"""从官方战斗 JSONL 日志提取 LogMetadata（阵容、敌方 UID、受击/阿哈/拉条目标等）。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Set, Tuple

from simulator.db.character_db import CharacterDB
from simulator.vm.reconcile.metadata_post import (
    build_enemy_uid_map,
    infer_entry_technique_stance,
    reconstruct_shielded_aha_damages,
    resolve_player_and_servant_targets,
    resolve_team_roster,
)
from simulator.vm.reconcile.metadata_trackers import (
    AhaTurnTracker,
    EnemyTurnTracker,
    PlayerTargetTracker,
    RosterAndSpawnTracker,
    StreamContext,
)
from simulator.vm.reconcile.models import (
    DEFAULT_CHAR_DB_PATH,
    LogMetadata,
    _extract_tag,
    _resolve_uid_name,
)


def _parse_log_time_ms(ts: Any) -> Optional[float]:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts).timestamp() * 1000.0
    except ValueError:
        return None


def extract_log_metadata(
    log_path: str,
    *,
    db: Optional[CharacterDB] = None,
    team_override: Optional[Sequence[str]] = None,
) -> LogMetadata:
    """扫描实机 JSONL，自动提取 stage_id、参战阵容、敌方 UID 映射、受击/阿哈/拉条目标与风行再动。"""
    char_db = db if db is not None else CharacterDB().load(DEFAULT_CHAR_DB_PATH)
    sctx = StreamContext(char_db=char_db)
    roster_tracker = RosterAndSpawnTracker()
    enemy_tracker = EnemyTurnTracker()
    aha_tracker = AhaTurnTracker()
    player_tracker = PlayerTargetTracker()
    active_bomb_uid: int = 0
    bomb_ad_streak: list = []
    enemy_debuff_hits_list: list = []

    def _flush_bomb_ad_streak() -> None:
        if len(bomb_ad_streak) == 1 and bomb_ad_streak[0][0] == "Player":
            _, b_uid, b_av = bomb_ad_streak[0]
            if active_bomb_uid and b_uid == active_bomb_uid:
                enemy_debuff_hits_list.append((b_av, b_uid, "MMonster_W5_AsatPramad_00_Shake"))
        bomb_ad_streak.clear()

    def _flush_turn() -> None:
        if not enemy_tracker.flush_turn(sctx.cur_av):
            aha_tracker.flush_turn(sctx.cur_av, sctx.cur_turn_owner_team)
        else:
            aha_tracker.reset_turn_state()
        if sctx.cur_turn_owner_team == "Player" and sctx.last_enemy_hp:
            av_k = round(sctx.cur_av, 2)
            for eu, ehp in sctx.last_enemy_hp.items():
                if ehp > 0.0:
                    sctx.enemy_hp_at_turn_end_raw[(av_k, eu)] = ehp

    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            ev = obj.get("event")
            data = obj.get("data") or {}
            aha_tracker.on_event_header(ev, data)
            if ev != "OnStatChange" or ((data.get("property") or {}).get("type") != "ActionDelay"):
                _flush_bomb_ad_streak()

            if ev == "OnBattleBegin":
                roster_tracker.on_battle_begin(data)
            elif ev == "OnUpdateWave":
                player_tracker.on_update_wave()
            elif ev == "OnInitializeEnemy":
                roster_tracker.on_initialize_enemy(data, sctx)
            elif ev == "OnTurnBegin":
                roster_tracker.on_turn_begin_before_flush()
                active_bomb_uid = 0
                enemy_tracker.clear_paused()
                player_tracker.flush_pending_player_atk()
                _flush_turn()
                player_tracker.flush_pending_q_break()
                sctx.cur_av = float(data.get("action_value", sctx.cur_av))
                sctx.cur_turn_owner_team = enemy_tracker.on_turn_begin_owner(data.get("turn_owner"), sctx.cur_av)
                player_tracker.on_turn_begin_after_owner()
                roster_tracker.on_turn_begin_after_flush(data.get("turn_owner"))
                player_tracker.flush_pending_player_atk()
            elif ev == "OnUseSkill":
                player_tracker.flush_pending_q_break()
                player_tracker.flush_pending_player_atk()
                if sctx.cur_turn_owner_team is None:
                    if aha_tracker.cur_none_ally_chips:
                        _flush_turn()
                    aha_tracker.cur_none_had_skill = True
                av_ent = data.get("avatar") or {}
                if av_ent.get("team") == "Player":
                    enemy_tracker.pause_if_active(sctx.cur_av)
                    uid = int(av_ent.get("uid") or 0)
                    skill = data.get("skill") or {}
                    sk_type = str(skill.get("type") or "")
                    sk_id = int(skill.get("skill_config_id") or 0)
                    active_bomb_uid = uid if sk_id == 700005 else 0
                    roster_tracker.on_player_use_skill(uid, sk_id)
                    cname = (
                        f"BattleEvent_{sk_id // 100}"
                        if (uid == 0 and sk_id >= 1000000)
                        else _resolve_uid_name(uid, char_db)
                    )
                    player_tracker.on_player_use_skill(sctx.cur_av, uid, cname, sk_type, sk_id)
            elif ev == "OnDamage":
                roster_tracker.on_damage_for_init_hp(data)
                player_tracker.on_damage(data, sctx.cur_av, _parse_log_time_ms(obj.get("time")), sctx.last_enemy_hp)
            elif ev == "OnStatChange":
                ent = data.get("entity") or {}
                team_tag = ent.get("team")
                uid = int(ent.get("uid") or 0)
                prop = data.get("property") or {}
                ptype = prop.get("type")
                val = float(prop.get("value", 0.0))

                player_tracker.on_action_delay_zero(ptype, val)
                if ptype == "ActionDelay":
                    bomb_ad_streak.append((team_tag, uid, sctx.cur_av))

                if team_tag == "Enemy" and uid:
                    player_tracker.on_enemy_stance_and_delay(uid, ptype, val)
                    roster_tracker.on_enemy_stat_change(uid, ptype, val, player_tracker.cur_player_sk_info)
                    if ptype == "CurrentSP":
                        player_tracker.on_enemy_sp_hit(uid, val)
                        enemy_tracker.on_enemy_sp_change(uid, val, sctx.cur_av)
                    elif ptype == "CurrentHP":
                        prev = sctx.last_enemy_hp.get(uid)
                        player_tracker.update_tie_highest_hp(uid, val, prev, sctx.last_enemy_hp)
                        if aha_tracker.is_active(sctx.cur_turn_owner_team) and prev is not None:
                            aha_tracker.on_enemy_hp_change(uid, val, prev)
                        elif player_tracker.try_record_enemy_hp_hit(uid, val, prev):
                            pass
                        elif (
                            enemy_tracker.cur_enemy_uid is not None
                            and uid != enemy_tracker.cur_enemy_uid
                            and prev is not None
                            and prev > 0.0
                            and val <= 0.0
                        ):
                            player_tracker.record_enemy_retarget_pick(sctx.cur_av, enemy_tracker.cur_enemy_uid, uid)
                        sctx.last_enemy_hp[uid] = val
                elif team_tag == "Player" and uid:
                    roster_tracker.on_player_stat_change(uid, ptype, val, char_db)
                    player_tracker.on_player_stat_change_ult(uid, ptype, val, char_db)
                    player_tracker.on_player_special_sp_change(
                        uid,
                        ptype,
                        val,
                        sctx.cur_av,
                        _parse_log_time_ms(obj.get("time")),
                    )
                    if ptype == "MaxHP":
                        if uid not in sctx.last_player_hp:
                            sctx.last_player_hp[uid] = val
                    elif ptype == "CurrentSP":
                        prof = char_db.get(uid)
                        max_sp = float(getattr(prof, "max_sp", 0) or 0) if prof is not None else 0.0
                        min_ult_spend = (max_sp * 0.8) if max_sp > 0.0 else 50.0
                        if val < -max(1.0, min_ult_spend):
                            enemy_tracker.pause_if_active(sctx.cur_av)
                        cname = _resolve_uid_name(uid, char_db)
                        prev_sp = sctx.last_player_sp.get(uid)
                        is_enemy_hit_sp = enemy_tracker.on_player_sp_change(val, prev_sp, cname)
                        if not is_enemy_hit_sp and aha_tracker.is_active(sctx.cur_turn_owner_team):
                            aha_tracker.on_player_sp_change(uid, val, prev_sp, cname)
                        if val <= 0.0:
                            sctx.last_player_sp[uid] = 0.0
                        elif prev_sp is not None and (
                            is_enemy_hit_sp or (val <= 35.0 and val <= prev_sp + 1e-4)
                        ):
                            sctx.last_player_sp[uid] = prev_sp + val
                        else:
                            sctx.last_player_sp[uid] = val
                    elif ptype == "Speed":
                        prev_spd = sctx.last_player_spd.get(uid)
                        enemy_tracker.on_player_speed_change(uid, val, prev_spd, sctx.cur_av, char_db)
                        sctx.last_player_spd[uid] = val
                    elif ptype == "CurrentHP":
                        prev = sctx.last_player_hp.get(uid)
                        if enemy_tracker.cur_enemy_uid is not None:
                            enemy_tracker.on_player_hp_change(uid, val, prev, char_db)
                        elif aha_tracker.is_active(sctx.cur_turn_owner_team) and prev is not None:
                            aha_tracker.on_player_hp_change(uid, val, prev, char_db)
                        if prev is None or val >= prev * 0.40 or val <= 1.0 + 1e-2:
                            sctx.last_player_hp[uid] = val

    player_tracker.flush_pending_player_atk()
    player_tracker.flush_bp_draw_carry()
    player_tracker.flush_active_elation_insert()
    _flush_turn()
    player_tracker.flush_pending_q_break()

    enemy_uid_map, stage_spec, initial_enemy_uids = build_enemy_uid_map(
        roster_tracker.stage_id,
        roster_tracker.initial_enemy_uids,
        roster_tracker.spawn_events_raw,
    )
    reconstruct_shielded_aha_damages(aha_tracker.aha_turns, enemy_uid_map)
    player_enemy_targets, servant_targets = resolve_player_and_servant_targets(
        player_tracker.pending_player_atk_records,
        enemy_uid_map,
        stage_spec,
    )
    team_uids, team_names = resolve_team_roster(
        char_db,
        roster_tracker.seen_uids,
        roster_tracker.inferred_slot_uids,
        roster_tracker.aoe_heal_slot_uids,
        roster_tracker.robin_s_init_ad,
        team_override,
    )
    from simulator.vm.loader import GameDataLoader

    enh_skill_map = GameDataLoader().get_enhanced_skill_ids()
    enhanced_avatars = {
        int(uid)
        for uid, sks in roster_tracker.observed_skill_ids.items()
        if sks & enh_skill_map.get(int(uid), set())
    }
    entry_element, entry_toughness = infer_entry_technique_stance(
        stage_spec,
        enemy_uid_map,
        initial_enemy_uids,
        roster_tracker.first_skill_info,
        roster_tracker.first_skill_stance_obs,
        roster_tracker.init_enemy_first_stance,
        player_tracker.skill_atk_dmgs,
        team_uids=team_uids,
        init_enemy_first_hp=roster_tracker.init_enemy_first_hp,
        init_enemy_first_dmg=roster_tracker.init_enemy_first_dmg,
        enhanced_avatars=enhanced_avatars,
    )

    enemy_hp_at_turn_end: Dict[Tuple[float, str], float] = {
        (av_k, enemy_uid_map[eu]): ehp
        for (av_k, eu), ehp in sctx.enemy_hp_at_turn_end_raw.items()
        if eu in enemy_uid_map
    }
    quantum_entangle_resists: Set[Tuple[float, str]] = {
        (q_av, enemy_uid_map[eu])
        for q_av, eu in player_tracker.quantum_entangle_resists_raw
        if eu in enemy_uid_map
    }

    return LogMetadata(
        log_path=os.path.abspath(log_path),
        tag=_extract_tag(log_path),
        stage_id=roster_tracker.stage_id,
        team_uids=team_uids,
        team_names=team_names,
        enemy_hits=enemy_tracker.enemy_hits,
        final_av=sctx.cur_av,
        enemy_uid_map=enemy_uid_map,
        ally_ult_targets=player_tracker.ally_ult_targets,
        enemy_retarget_picks=player_tracker.enemy_retarget_picks,
        random_config_draws=player_tracker.random_config_draws,
        player_enemy_targets=player_enemy_targets,
        servant_targets=servant_targets,
        aha_turns=aha_tracker.aha_turns,
        windwalk_enemy_uids=enemy_tracker.windwalk_enemy_uids,
        windwalk_events=enemy_tracker.windwalk_events,
        slow_hits=enemy_tracker.slow_hits,
        quantum_entangle_resists=quantum_entangle_resists,
        enemy_hp_at_turn_end=enemy_hp_at_turn_end,
        enemy_spawns=roster_tracker.enemy_spawns,
        gluttony_enemy_names={
            enemy_uid_map[u] for u in roster_tracker.gluttony_revived_euids if u in enemy_uid_map
        },
        entry_element=entry_element,
        entry_toughness=entry_toughness,
        player_obs_speeds=roster_tracker.player_obs_speeds,
        random_chance_triggers=player_tracker.random_chance_triggers,
        enhanced_avatars=enhanced_avatars,
        enemy_debuff_hits=tuple(enemy_debuff_hits_list),
    )

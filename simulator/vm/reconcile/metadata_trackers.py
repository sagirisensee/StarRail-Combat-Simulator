# coding: utf-8
"""从战斗 JSONL 单遍扫描过程中按机制隔离的状态追踪器（Tracker）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from simulator.db.character_db import CharacterDB
from simulator.vm.reconcile.metadata_post import PlayerAttackRecord
from simulator.vm.reconcile.models import (
    AhaTurnRecord,
    EnemyHitRecord,
    _get_avatar_damage_types,
    _get_avatar_skill_trigger_keys,
    _resolve_uid_name,
)


@dataclass
class StreamContext:
    """流式扫描期间各 Tracker 共享的时间与属性快照上下文。"""

    char_db: CharacterDB
    cur_av: float = 0.0
    cur_turn_owner_team: Optional[str] = None
    last_enemy_hp: Dict[int, float] = field(default_factory=dict)
    last_player_hp: Dict[int, float] = field(default_factory=dict)
    last_player_sp: Dict[int, float] = field(default_factory=dict)
    last_player_spd: Dict[int, float] = field(default_factory=dict)
    enemy_hp_at_turn_end_raw: Dict[Tuple[float, int], float] = field(default_factory=dict)


class RosterAndSpawnTracker:
    """追踪关卡号、站位顺序、初始敌方、波次召唤与开局秘技削韧采样。"""

    def __init__(self) -> None:
        self.stage_id: int = 0
        self.seen_uids: List[int] = []
        self.seen_uid_set: Set[int] = set()
        self.initial_enemy_uids: List[int] = []
        self.seen_init_enemy_uids: Set[int] = set()
        self.spawn_events_raw: List[Tuple[int, str]] = []
        self.enemy_spawns: List[Tuple[float, int, str]] = []
        self.gluttony_locked_euids: Set[int] = set()
        self.gluttony_revived_euids: Set[int] = set()
        self.saw_first_init_enemy: bool = False
        self.in_aoe_heal_window: bool = False
        self.aoe_heal_slot_uids: List[int] = []
        self.inferred_slot_uids: List[int] = []
        self.robin_s_init_ad: float = 0.0
        self.first_skill_info: Optional[Tuple[int, int]] = None
        self.first_skill_done: bool = False
        self.first_skill_stance_obs: Dict[int, float] = {}
        self.init_enemy_first_stance: Dict[int, Tuple[int, int, float, int]] = {}
        self.init_stance_seen_euids: Set[int] = set()
        self.init_enemy_first_hp: Dict[int, float] = {}
        self.init_enemy_first_dmg: Dict[int, float] = {}
        self._pending_first_hp_euid: Optional[int] = None

    def _record_seen_uid(self, uid: int) -> None:
        if uid and uid not in self.seen_uid_set:
            self.seen_uid_set.add(uid)
            self.seen_uids.append(uid)

    def on_battle_begin(self, data: Mapping[str, Any]) -> None:
        self.stage_id = int(data.get("stage_id") or 0)

    def on_initialize_enemy(self, data: Mapping[str, Any], sctx: StreamContext) -> None:
        self.saw_first_init_enemy = True
        enemy = data.get("enemy") or {}
        euid = int(enemy.get("uid") or 0)
        eid = int(enemy.get("id") or 0)
        ename = str(enemy.get("name") or "")
        props = (enemy.get("base_stats") or {}).get("properties") or {}
        if euid and "CurrentHP" in props:
            sctx.last_enemy_hp[euid] = float(props["CurrentHP"])
        if euid and ename:
            self.spawn_events_raw.append((euid, ename))
        if eid and ename:
            self.enemy_spawns.append((round(sctx.cur_av, 2), eid, ename))

    def on_turn_begin_before_flush(self) -> None:
        if self.in_aoe_heal_window and len(self.aoe_heal_slot_uids) >= 2 and not self.inferred_slot_uids:
            self.inferred_slot_uids = list(self.aoe_heal_slot_uids)
        self.in_aoe_heal_window = False

    def on_turn_begin_after_flush(self) -> None:
        if self.first_skill_info is not None and not self.first_skill_done:
            self.first_skill_done = True

    def on_player_use_skill(self, uid: int, sk_id: int) -> None:
        self._record_seen_uid(uid)
        if not self.first_skill_done:
            if self.first_skill_info is None and sk_id > 0:
                self.first_skill_info = (sk_id, uid)
            elif self.first_skill_info is not None:
                self.first_skill_done = True
        if not self.inferred_slot_uids and sk_id in (140902, 140903):
            self.in_aoe_heal_window = True
            self.aoe_heal_slot_uids = []
        else:
            self.in_aoe_heal_window = False

    def on_enemy_stat_change(
        self,
        uid: int,
        ptype: Any,
        val: float,
        cur_player_sk_info: Optional[Tuple[int, int, int]],
    ) -> None:
        if not self.saw_first_init_enemy and uid not in self.seen_init_enemy_uids:
            self.seen_init_enemy_uids.add(uid)
            self.initial_enemy_uids.append(uid)
        if (
            ptype == "CurrentStance"
            and self.first_skill_info is not None
            and not self.first_skill_done
            and val > 0.0
            and uid not in self.first_skill_stance_obs
        ):
            self.first_skill_stance_obs[uid] = val
        if (
            ptype == "CurrentStance"
            and not self.spawn_events_raw
            and uid not in self.init_stance_seen_euids
        ):
            self.init_stance_seen_euids.add(uid)
            if cur_player_sk_info is not None:
                self.init_enemy_first_stance[uid] = (
                    cur_player_sk_info[0],
                    cur_player_sk_info[1],
                    val,
                    cur_player_sk_info[2],
                )
        if (
            ptype == "CurrentHP"
            and not self.spawn_events_raw
            and not self.saw_first_init_enemy
            and uid not in self.init_enemy_first_hp
            and val > 0.0
        ):
            self.init_enemy_first_hp[uid] = val
            self._pending_first_hp_euid = uid
        if ptype == "MaxHP" and uid in self.gluttony_locked_euids:
            self.gluttony_revived_euids.add(uid)
        elif ptype == "CurrentHP" and abs(val - 1.0) < 0.01:
            self.gluttony_locked_euids.add(uid)

    def on_damage_for_init_hp(self, data: Mapping[str, Any]) -> None:
        if self._pending_first_hp_euid is None:
            return
        atk = data.get("attacker") or {}
        if atk.get("team") != "Player":
            return
        euid = self._pending_first_hp_euid
        self._pending_first_hp_euid = None
        if euid not in self.init_enemy_first_dmg:
            self.init_enemy_first_dmg[euid] = float(data.get("damage") or 0.0)

    def on_player_stat_change(self, uid: int, ptype: Any, val: float, char_db: CharacterDB) -> None:
        if uid == 1512 and ptype == "ActionDelay" and self.robin_s_init_ad <= 0.0 and val > 0.0:
            self.robin_s_init_ad = val
        self._record_seen_uid(uid)
        if (
            ptype == "CurrentHP"
            and self.in_aoe_heal_window
            and not self.inferred_slot_uids
            and char_db.get(uid) is not None
            and uid not in self.aoe_heal_slot_uids
        ):
            self.aoe_heal_slot_uids.append(uid)


class EnemyTurnTracker:
    """追踪敌方回合内的多动拆段、我方受击、插队暂停恢复与风行/减速标记。"""

    def __init__(self) -> None:
        self.cur_enemy_uid: Optional[int] = None
        self.prev_enemy_turn: Optional[Tuple[float, int]] = None
        self.windwalk_enemy_uids: Set[int] = set()
        self.windwalk_events: List[Tuple[float, int]] = []
        self.cur_hit_order: List[str] = []
        self.cur_hit_set: Set[str] = set()
        self.cur_hit_counts: Dict[str, int] = {}
        self.cur_hit_dmgs: Dict[str, float] = {}
        self.cur_clamped_hp_names: Set[str] = set()
        self.cur_small_hp_drops: Dict[str, List[float]] = {}
        self.cur_sub_hits: List[str] = []
        self.cur_sub_actions: List[List[str]] = []
        self.cur_sub_sp_gains: Dict[str, int] = {}
        self.cur_sub_first_memo: Optional[str] = None
        self.cur_sub_pending_sp_owner: Optional[str] = None
        self.cur_sub_action_details: List[Tuple[List[str], Dict[str, int], Optional[str]]] = []
        self.cur_small_heal_uids: Set[int] = set()
        self.cur_sp_gain_counts: Dict[str, int] = {}
        self.cur_first_memo_owner: Optional[str] = None
        self.pending_first_sp_owner: Optional[str] = None
        self.last_enemy_hit_sp: float = 0.0
        self.paused_enemy_ctx: Optional[Dict[str, Any]] = None
        self.slow_hits: Set[Tuple[float, str]] = set()
        self.enemy_hits: List[EnemyHitRecord] = []

    def clear_paused(self) -> None:
        self.paused_enemy_ctx = None

    def reset_turn_state(self) -> None:
        self.cur_enemy_uid = None
        self.cur_hit_order = []
        self.cur_hit_set = set()
        self.cur_hit_counts = {}
        self.cur_hit_dmgs = {}
        self.cur_clamped_hp_names = set()
        self.cur_small_hp_drops = {}
        self.cur_sub_hits = []
        self.cur_sub_actions = []
        self.cur_sub_sp_gains = {}
        self.cur_sub_first_memo = None
        self.cur_sub_pending_sp_owner = None
        self.cur_sub_action_details = []
        self.cur_small_heal_uids = set()
        self.cur_sp_gain_counts = {}
        self.cur_first_memo_owner = None
        self.pending_first_sp_owner = None
        self.last_enemy_hit_sp = 0.0

    def _record_confirmed_hit(self, name: str, dmg_delta: float) -> None:
        if self.pending_first_sp_owner is not None:
            if self.pending_first_sp_owner != name and self.cur_first_memo_owner is None:
                self.cur_first_memo_owner = self.pending_first_sp_owner
            self.pending_first_sp_owner = None
        if self.cur_sub_pending_sp_owner is not None:
            if self.cur_sub_pending_sp_owner != name and self.cur_sub_first_memo is None:
                self.cur_sub_first_memo = self.cur_sub_pending_sp_owner
            self.cur_sub_pending_sp_owner = None
        if name not in self.cur_hit_set:
            self.cur_hit_set.add(name)
            self.cur_hit_order.append(name)
        self.cur_sub_hits.append(name)
        self.cur_hit_counts[name] = self.cur_hit_counts.get(name, 0) + 1
        self.cur_hit_dmgs[name] = self.cur_hit_dmgs.get(name, 0.0) + dmg_delta

    def flush_sub_action(self) -> None:
        if self.cur_sub_hits or self.cur_sub_sp_gains:
            if self.cur_sub_pending_sp_owner is not None and not self.cur_sub_hits and self.cur_sub_first_memo is None:
                self.cur_sub_first_memo = self.cur_sub_pending_sp_owner
            if self.cur_sub_hits:
                self.cur_sub_actions.append(list(self.cur_sub_hits))
            self.cur_sub_action_details.append((
                list(self.cur_sub_hits),
                dict(self.cur_sub_sp_gains),
                self.cur_sub_first_memo,
            ))
        self.cur_sub_hits = []
        self.cur_sub_sp_gains = {}
        self.cur_sub_first_memo = None
        self.cur_sub_pending_sp_owner = None
        self.cur_small_hp_drops = {}

    def flush_turn(self, cur_av: float) -> bool:
        """若存在活跃敌方回合则结算并记录 EnemyHitRecord；返回是否为敌方回合。"""
        had_enemy = self.cur_enemy_uid is not None
        if self.cur_enemy_uid is not None:
            if self.pending_first_sp_owner is not None and not self.cur_hit_order and self.cur_first_memo_owner is None:
                self.cur_first_memo_owner = self.pending_first_sp_owner
            self.pending_first_sp_owner = None
            self.flush_sub_action()
            eff_hit_order = list(self.cur_hit_order)
            # 敌方多动中若先放全体 AoE 再放单体点名（如 Skill02 + Skill01 [+ Skill04]），将单体目标放在首位供 target_provider 精准锁定
            if len(self.cur_sub_actions) >= 2 and len(set(self.cur_sub_actions[0])) >= 2:
                st_subs = [sub[0] for sub in self.cur_sub_actions[1:] if len(set(sub)) == 1]
                if st_subs:
                    st_tgt = st_subs[0]
                    if st_tgt in eff_hit_order:
                        eff_hit_order.remove(st_tgt)
                    eff_hit_order.insert(0, st_tgt)
            elif len(self.cur_sub_actions) == 1 and len(self.cur_hit_dmgs) >= 2 and not self.cur_clamped_hp_names:
                # 全体主/副双倍率技能（如锁定单人高倍率重击 + 其余低倍率波及）：将承伤显著最高者置首作为主目标
                sorted_dmgs = sorted(self.cur_hit_dmgs.items(), key=lambda kv: kv[1], reverse=True)
                if sorted_dmgs[1][1] > 0.0 and sorted_dmgs[0][1] > sorted_dmgs[1][1] * 1.8:
                    prim = sorted_dmgs[0][0]
                    if prim in eff_hit_order:
                        eff_hit_order.remove(prim)
                    eff_hit_order.insert(0, prim)
            sub_recs: List[EnemyHitRecord] = []
            if len(self.cur_sub_action_details) >= 2:
                had_pheal = len(self.cur_small_heal_uids) >= 2
                for sub_hits, sub_sp, sub_fm in self.cur_sub_action_details:
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
                            enemy_uid=self.cur_enemy_uid,
                            hit_allies=sub_order,
                            hit_counts=sub_counts,
                            had_hp_drop=bool(sub_hits),
                            had_passive_heal=had_pheal,
                            sp_gain_counts=dict(sub_sp),
                            first_memo_owner=sub_fm,
                        )
                    )
            self.enemy_hits.append(
                EnemyHitRecord(
                    av=round(cur_av, 2),
                    enemy_uid=self.cur_enemy_uid,
                    hit_allies=eff_hit_order,
                    hit_counts=dict(self.cur_hit_counts),
                    had_hp_drop=bool(self.cur_hit_order),
                    had_passive_heal=len(self.cur_small_heal_uids) >= 2,
                    sp_gain_counts=dict(self.cur_sp_gain_counts),
                    first_memo_owner=self.cur_first_memo_owner,
                    sub_records=sub_recs,
                )
            )
        self.reset_turn_state()
        return had_enemy

    def pause_if_active(self, cur_av: float) -> None:
        if self.cur_enemy_uid is not None:
            paused_sub_actions = list(self.cur_sub_actions)
            paused_sub_details = list(self.cur_sub_action_details)
            if self.cur_sub_hits or self.cur_sub_sp_gains:
                sub_fm = (
                    self.cur_sub_pending_sp_owner
                    if (self.cur_sub_pending_sp_owner is not None and not self.cur_sub_hits and self.cur_sub_first_memo is None)
                    else self.cur_sub_first_memo
                )
                if self.cur_sub_hits:
                    paused_sub_actions.append(list(self.cur_sub_hits))
                paused_sub_details.append((list(self.cur_sub_hits), dict(self.cur_sub_sp_gains), sub_fm))
            snap: Dict[str, Any] = {
                "av": round(cur_av, 2),
                "euid": self.cur_enemy_uid,
                "hit_order": list(self.cur_hit_order),
                "hit_set": set(self.cur_hit_set),
                "hit_counts": dict(self.cur_hit_counts),
                "hit_dmgs": dict(self.cur_hit_dmgs),
                "clamped_hp_names": set(self.cur_clamped_hp_names),
                "sub_actions": paused_sub_actions,
                "sub_details": paused_sub_details,
                "small_heal": set(self.cur_small_heal_uids),
                "sp_gains": dict(self.cur_sp_gain_counts),
                "first_memo": self.cur_first_memo_owner,
                "last_sp": self.last_enemy_hit_sp,
            }
            self.flush_turn(cur_av)
            snap["rec_idx"] = len(self.enemy_hits) - 1
            self.paused_enemy_ctx = snap

    def on_turn_begin_owner(self, owner: Any, cur_av: float) -> Optional[str]:
        if isinstance(owner, dict):
            team = owner.get("team")
            if team == "Enemy":
                euid = int(owner.get("uid") or 0)
                self.cur_enemy_uid = euid
                if (
                    self.prev_enemy_turn is not None
                    and abs(self.prev_enemy_turn[0] - cur_av) < 0.05
                    and self.prev_enemy_turn[1] == euid
                ):
                    self.windwalk_enemy_uids.add(euid)
                    self.windwalk_events.append((round(cur_av, 2), euid))
                self.prev_enemy_turn = (cur_av, euid)
            else:
                self.prev_enemy_turn = None
            return team
        self.prev_enemy_turn = None
        return None

    def on_enemy_sp_change(self, uid: int, val: float, cur_av: float) -> None:
        if (
            self.cur_enemy_uid is None
            and self.paused_enemy_ctx is not None
            and self.paused_enemy_ctx["euid"] == uid
            and val <= 1e-6
            and abs(round(cur_av, 2) - self.paused_enemy_ctx["av"]) < 0.05
            and self.paused_enemy_ctx["rec_idx"] == len(self.enemy_hits) - 1
        ):
            self.enemy_hits.pop()
            ctx = self.paused_enemy_ctx
            self.cur_enemy_uid = ctx["euid"]
            self.cur_hit_order = list(ctx["hit_order"])
            self.cur_hit_set = set(ctx["hit_set"])
            self.cur_hit_counts = dict(ctx["hit_counts"])
            self.cur_hit_dmgs = dict(ctx.get("hit_dmgs") or {})
            self.cur_clamped_hp_names = set(ctx.get("clamped_hp_names") or ())
            self.cur_sub_actions = list(ctx["sub_actions"])
            self.cur_sub_action_details = list(ctx.get("sub_details") or [])
            self.cur_sub_hits = []
            self.cur_sub_sp_gains = {}
            self.cur_sub_first_memo = None
            self.cur_sub_pending_sp_owner = None
            self.cur_small_hp_drops = {}
            self.cur_small_heal_uids = set(ctx["small_heal"])
            self.cur_sp_gain_counts = dict(ctx["sp_gains"])
            self.cur_first_memo_owner = ctx["first_memo"]
            self.last_enemy_hit_sp = float(ctx["last_sp"])
            self.paused_enemy_ctx = None
        if self.cur_enemy_uid is not None and uid == self.cur_enemy_uid:
            if self.pending_first_sp_owner is not None and not self.cur_hit_order and self.cur_first_memo_owner is None:
                self.cur_first_memo_owner = self.pending_first_sp_owner
            self.pending_first_sp_owner = None
            if val <= 1e-6:
                self.flush_sub_action()
        self.last_enemy_hit_sp = val if val > 0.0 else 0.0

    def on_player_sp_change(self, val: float, prev_sp: Optional[float], cname: str) -> bool:
        is_enemy_hit_sp = (
            self.cur_enemy_uid is not None
            and 0.2 < val < 35.0
            and self.last_enemy_hit_sp > 0.0
            and 0.99 <= (val / self.last_enemy_hit_sp) <= 1.60
            and not (prev_sp is not None and abs((val - prev_sp) - 3.0) < 1e-3)
        )
        if is_enemy_hit_sp:
            small_drops = self.cur_small_hp_drops.get(cname)
            if small_drops:
                drop_delta = small_drops.pop(0)
                self._record_confirmed_hit(cname, drop_delta)
            else:
                if not self.cur_hit_order and self.cur_first_memo_owner is None and self.pending_first_sp_owner is None:
                    self.pending_first_sp_owner = cname
                if not self.cur_sub_hits and self.cur_sub_first_memo is None and self.cur_sub_pending_sp_owner is None:
                    self.cur_sub_pending_sp_owner = cname
            self.cur_sp_gain_counts[cname] = self.cur_sp_gain_counts.get(cname, 0) + 1
            self.cur_sub_sp_gains[cname] = self.cur_sub_sp_gains.get(cname, 0) + 1
        return is_enemy_hit_sp

    def on_player_speed_change(
        self,
        uid: int,
        val: float,
        prev_spd: Optional[float],
        cur_av: float,
        char_db: CharacterDB,
    ) -> None:
        if self.cur_enemy_uid is not None and prev_spd is not None and val < prev_spd - 1.0:
            self.slow_hits.add((round(cur_av, 2), _resolve_uid_name(uid, char_db)))

    def on_player_hp_change(
        self,
        uid: int,
        val: float,
        prev: Optional[float],
        char_db: CharacterDB,
    ) -> None:
        if prev is None:
            if val > 550.0:
                name = _resolve_uid_name(uid, char_db)
                if name not in self.cur_hit_set:
                    self.cur_hit_set.add(name)
                    self.cur_hit_order.append(name)
                self.cur_sub_hits.append(name)
                self.cur_hit_counts[name] = self.cur_hit_counts.get(name, 0) + 1
        elif 120.0 <= val <= 550.0 and val < prev * 0.35:
            self.cur_small_heal_uids.add(uid)
            self.flush_sub_action()
        elif val < prev - 1e-3 and (prev - val) < prev * 0.60:
            delta = prev - val
            # 过滤敌方回合结束时的 1% 伴生微伤/DoT，避免误将未受直接攻击的队友计入受击/扩散目标
            if delta >= 200.0 or delta >= prev * 0.02:
                name = _resolve_uid_name(uid, char_db)
                self._record_confirmed_hit(name, delta)
            elif delta >= 10.0:
                name = _resolve_uid_name(uid, char_db)
                self.cur_small_hp_drops.setdefault(name, []).append(delta)
        elif abs(val - 1.0) <= 1e-2:
            name = _resolve_uid_name(uid, char_db)
            self.cur_clamped_hp_names.add(name)
            self.cur_small_hp_drops.setdefault(name, []).append(max(1.0, prev - val))
        elif val < prev - 1e-3:
            name = _resolve_uid_name(uid, char_db)
            self.cur_small_hp_drops.setdefault(name, []).append(prev - val)


class AhaTurnTracker:
    """追踪无归属回合（阿哈回合）内我方微伤、受击回能与敌方扣血/致命标志。"""

    def __init__(self) -> None:
        self.cur_none_had_skill: bool = False
        self.cur_none_enemy_dmgs: List[Tuple[int, float]] = []
        self.cur_none_last_drop_euid: Optional[int] = None
        self.cur_none_lethal_euids: Set[int] = set()
        self.cur_none_ally_chips: List[str] = []
        self.cur_none_ally_sp_counts: Dict[str, int] = {}
        self.cur_none_pending_hp_chip_uid: Optional[int] = None
        self.aha_turns: List[AhaTurnRecord] = []

    def reset_turn_state(self) -> None:
        self.cur_none_had_skill = False
        self.cur_none_enemy_dmgs = []
        self.cur_none_last_drop_euid = None
        self.cur_none_lethal_euids = set()
        self.cur_none_ally_chips = []
        self.cur_none_ally_sp_counts = {}
        self.cur_none_pending_hp_chip_uid = None

    def is_active(self, cur_turn_owner_team: Optional[str]) -> bool:
        return cur_turn_owner_team is None and not self.cur_none_had_skill

    def on_event_header(self, ev: Any, data: Mapping[str, Any]) -> None:
        if not (
            ev == "OnStatChange"
            and (data.get("entity") or {}).get("team") == "Enemy"
            and (data.get("property") or {}).get("type") == "CurrentHP"
        ):
            self.cur_none_last_drop_euid = None

    def flush_turn(self, cur_av: float, cur_turn_owner_team: Optional[str]) -> None:
        if cur_turn_owner_team is None and not self.cur_none_had_skill and self.cur_none_ally_chips:
            # 真实阿哈回合必含我方伴生微伤（过滤无我方微伤的 Boss 紫色球体/破盾扣血等系统回合）
            filtered_dmgs = [(u, d) for u, d in self.cur_none_enemy_dmgs if d < 500_000.0]
            self.aha_turns.append(
                AhaTurnRecord(
                    av=round(cur_av, 6),
                    enemy_damages=filtered_dmgs,
                    ally_chip_hits=list(self.cur_none_ally_chips),
                    ally_sp_gain_counts=dict(self.cur_none_ally_sp_counts),
                    lethal_enemy_uids=set(self.cur_none_lethal_euids),
                )
            )
        self.reset_turn_state()

    def on_enemy_hp_change(self, uid: int, val: float, prev: float) -> None:
        if val < prev - 1.0:
            self.cur_none_enemy_dmgs.append((uid, prev - val))
            self.cur_none_last_drop_euid = uid
            if val <= 1e-3:
                self.cur_none_lethal_euids.add(uid)
        elif abs(val - prev) <= 1.0 and val > 1e-3:
            if self.cur_none_last_drop_euid == uid and abs(val - prev) <= 1e-3:
                # 紧随扣血之后同 UID 相同数值的 CurrentHP 广播是贪饕 DirtyHPRatio 同步回声，非护盾吸收命中
                self.cur_none_last_drop_euid = None
            else:
                self.cur_none_enemy_dmgs.append((uid, 0.0))
                self.cur_none_last_drop_euid = None
        else:
            self.cur_none_last_drop_euid = None

    def on_player_sp_change(self, uid: int, val: float, prev_sp: Optional[float], cname: str) -> None:
        sp_delta = (val - prev_sp) if prev_sp is not None else val
        if self.cur_none_pending_hp_chip_uid == uid:
            self.cur_none_ally_sp_counts[cname] = self.cur_none_ally_sp_counts.get(cname, 0) + 1
            self.cur_none_pending_hp_chip_uid = None
        elif (1.8 <= sp_delta <= 2.9) or (prev_sp is not None and val >= 100.0 and abs(val - prev_sp) < 1e-4 and val > 0.0):
            self.cur_none_ally_sp_counts[cname] = self.cur_none_ally_sp_counts.get(cname, 0) + 1

    def on_player_hp_change(self, uid: int, val: float, prev: float, char_db: CharacterDB) -> None:
        # 阿哈回合我方伴生微伤（通常 0.1~5.0 点 HP）
        delta = prev - val
        if 0.05 <= delta <= 10.0:
            self.cur_none_ally_chips.append(_resolve_uid_name(uid, char_db))
            self.cur_none_pending_hp_chip_uid = uid


class PlayerTargetTracker:
    """追踪玩家/忆灵目标选择、队友单点大招目标、高血量并列选择与量子纠缠抵抗。"""

    def __init__(self) -> None:
        self.pending_ally_ult_caster: Optional[str] = None
        self.pending_ally_ult_sid: int = 0
        self.pending_ally_ult_uid: int = 0
        self.pending_ally_ult_sp_fallback: Optional[str] = None
        self.ally_ult_targets: Dict[str, List[str]] = {}
        self.enemy_retarget_picks: List[Tuple[float, int, int]] = []
        self.random_config_draws: List[Tuple[float, int, int]] = []
        self._last_special_sp: Optional[float] = None
        self._bp_draw_caster_uid: int = 0
        self._bp_draw_av: float = 0.0
        self._bp_draw_cap_carry: int = 0
        self.pending_tie_highest_hp_euid: Optional[int] = None

        self.pending_player_atk: Optional[Tuple[float, str]] = None
        self.pending_player_hit_euids: List[int] = []
        self.pending_player_dmg_confirmed_euids: List[int] = []
        self.pending_player_sp_euids: List[int] = []
        self.pending_player_hit_dmgs: Dict[int, float] = {}
        self.pending_hit_hp_euids: List[int] = []
        self.pending_hit_direct_euid: Optional[int] = None
        self.pending_hit_sp_euid: Optional[int] = None
        self.last_player_hit_euid: Optional[int] = None
        self.pending_player_primary_dmg_hits: int = 0
        self.pending_player_is_servant: bool = False
        self.pending_player_skill_id: int = 0
        self.pending_player_skill_type: str = ""
        self.pending_player_primary_euids: List[int] = []
        self.pending_player_elation_hits: List[Tuple[int, int]] = []
        self.pending_player_atk_records: List[PlayerAttackRecord] = []

        self.cur_player_sk_info: Optional[Tuple[int, int, int]] = None
        self.cur_player_atk_seq: int = 0
        self.skill_atk_dmgs: Dict[int, Dict[int, float]] = {}

        self.av_elems_map = _get_avatar_damage_types()
        self.last_stance_zero_euid: Optional[int] = None
        self.pending_q_break: Optional[Tuple[float, int, int]] = None
        self.quantum_entangle_resists_raw: Set[Tuple[float, int]] = set()

    def _clear_pending_ally_ult(self) -> None:
        self.pending_ally_ult_caster = None
        self.pending_ally_ult_sid = 0
        self.pending_ally_ult_uid = 0
        self.pending_ally_ult_sp_fallback = None

    def flush_pending_player_atk(self) -> None:
        if self.cur_player_sk_info is not None and self.pending_player_hit_dmgs:
            self.skill_atk_dmgs.setdefault(self.cur_player_sk_info[2], {}).update(self.pending_player_hit_dmgs)
        if self.pending_player_atk is not None:
            if self.pending_player_elation_hits:
                av_key = self.pending_player_atk[0]
                pri = self.pending_player_primary_euids
                hits = self.pending_player_elation_hits
                i = 0
                while i < len(hits):
                    if (
                        len(pri) >= 2
                        and i + len(pri) <= len(hits)
                        and [e for _, e in hits[i:i + len(pri)]] == pri
                        and len({a for a, _ in hits[i:i + len(pri)]}) == 1
                    ):
                        i += len(pri)
                    else:
                        a_uid, e_uid = hits[i]
                        self.enemy_retarget_picks.append((av_key, a_uid, e_uid))
                        i += 1
            self.pending_player_atk_records.append(
                PlayerAttackRecord(
                    atk_key=self.pending_player_atk,
                    is_servant=self.pending_player_is_servant,
                    skill_id=self.pending_player_skill_id,
                    skill_type=self.pending_player_skill_type,
                    primary_dmg_hits=self.pending_player_primary_dmg_hits,
                    hit_euids=list(self.pending_player_hit_euids),
                    dmg_confirmed_euids=list(self.pending_player_dmg_confirmed_euids),
                    hit_dmgs=dict(self.pending_player_hit_dmgs),
                    sp_euids=list(self.pending_player_sp_euids),
                )
            )
        self.pending_player_atk = None
        self.pending_player_hit_euids = []
        self.pending_player_dmg_confirmed_euids = []
        self.pending_player_sp_euids = []
        self.pending_player_hit_dmgs = {}
        self.pending_hit_hp_euids.clear()
        self.pending_hit_direct_euid = None
        self.pending_hit_sp_euid = None
        self.last_player_hit_euid = None
        self.pending_player_primary_dmg_hits = 0
        self.pending_player_is_servant = False
        self.pending_player_skill_id = 0
        self.pending_player_skill_type = ""
        self.pending_player_primary_euids = []
        self.pending_player_elation_hits = []

    def flush_pending_q_break(self) -> None:
        if self.pending_q_break is not None:
            q_av, q_euid, q_cnt = self.pending_q_break
            if q_cnt == 1:
                self.quantum_entangle_resists_raw.add((q_av, q_euid))
            self.pending_q_break = None

    def flush_bp_draw_carry(self) -> None:
        if self._bp_draw_caster_uid and self._bp_draw_cap_carry in (1, 2):
            self.random_config_draws.append(
                (self._bp_draw_av, self._bp_draw_caster_uid, 0 if self._bp_draw_cap_carry >= 2 else 1)
            )
        self._bp_draw_cap_carry = 0

    def on_player_special_sp_change(self, uid: int, ptype: Any, val: float, cur_av: float) -> None:
        if ptype == "CurrentSpecialSP":
            delta = round(val - self._last_special_sp) if self._last_special_sp is not None else 0
            self._last_special_sp = val
            if self._bp_draw_caster_uid and delta > 0:
                if val < 59.999:
                    if delta in (1, 2):
                        self.random_config_draws.append(
                            (round(cur_av, 2), self._bp_draw_caster_uid, 0 if delta >= 2 else 1)
                        )
                else:
                    self._bp_draw_cap_carry += delta
                    self._bp_draw_av = round(cur_av, 2)
        elif ptype == "CurExtraSpecialSP":
            extra = round(val)
            if self._bp_draw_caster_uid and extra > 0:
                tot = self._bp_draw_cap_carry + extra
                self._bp_draw_cap_carry = 0
                if tot in (1, 2):
                    self.random_config_draws.append(
                        (round(cur_av, 2), self._bp_draw_caster_uid, 0 if tot >= 2 else 1)
                    )
        elif ptype == "CurrentSP" and uid == self._bp_draw_caster_uid and val <= 1e-6:
            self.flush_bp_draw_carry()

    def on_turn_begin_after_owner(self) -> None:
        self.flush_bp_draw_carry()
        self._bp_draw_caster_uid = 0
        if self.pending_ally_ult_caster is not None and self.pending_ally_ult_sp_fallback is not None:
            self.ally_ult_targets.setdefault(self.pending_ally_ult_caster, []).append(
                self.pending_ally_ult_sp_fallback
            )
        self._clear_pending_ally_ult()

    def on_player_use_skill(self, cur_av: float, uid: int, cname: str, sk_type: str, sk_id: int) -> None:
        self.flush_bp_draw_carry()
        if sk_type == "BPSkill":
            self._bp_draw_caster_uid = uid
            self._bp_draw_av = round(cur_av, 2)
        else:
            self._bp_draw_caster_uid = 0
        if sk_id > 0 and uid > 0 and sk_type in ("Normal", "BPSkill", "Ultra", "Servant"):
            sk_key = _get_avatar_skill_trigger_keys().get(sk_id, "")
            if sk_key in ("Skill12", "Skill13", "Skill14"):
                self.random_config_draws.append(
                    (round(cur_av, 2), uid, {"Skill12": 0, "Skill13": 1, "Skill14": 2}[sk_key])
                )
            self.cur_player_atk_seq += 1
            self.cur_player_sk_info = (sk_id, uid, self.cur_player_atk_seq)
        if sk_type == "Ultra":
            self.pending_ally_ult_caster = cname
            self.pending_ally_ult_sid = sk_id
            self.pending_ally_ult_uid = uid
            self.pending_ally_ult_sp_fallback = None
        if sk_type in ("Normal", "BPSkill", "Ultra", "Servant"):
            # 忆灵技（Servant）的施法者 UID 是召唤师本体，主目标仍需按官方日志锁定
            self.pending_player_atk = (round(cur_av, 2), cname)
            self.pending_player_is_servant = sk_type == "Servant"
            self.pending_player_skill_id = sk_id
            self.pending_player_skill_type = sk_type

    def on_damage(self, data: Mapping[str, Any], cur_av: float) -> None:
        dtype = str(data.get("type") or "")
        if dtype in ("Ultimate", "Ultra") and self.pending_ally_ult_caster is not None:
            self._clear_pending_ally_ult()
        atk_ent = data.get("attacker") or {}
        if self.pending_player_atk is not None:
            if dtype in ("Basic", "Normal", "Skill", "BPSkill", "Ultimate", "Ultra"):
                self.pending_player_primary_dmg_hits += 1
        if dtype in ("Basic", "Normal", "Skill", "BPSkill", "Ultimate", "Ultra"):
            self.flush_bp_draw_carry()
            self._bp_draw_caster_uid = 0
        if self.pending_player_atk is not None:
            confirmed_euid = (
                self.pending_hit_direct_euid
                if self.pending_hit_direct_euid is not None
                else (self.pending_hit_hp_euids[0] if len(self.pending_hit_hp_euids) == 1 else None)
            )
            if confirmed_euid is not None:
                if (
                    dtype in ("Basic", "Normal", "Skill", "BPSkill", "Ultimate", "Ultra")
                    and confirmed_euid not in self.pending_player_primary_euids
                ):
                    self.pending_player_primary_euids.append(confirmed_euid)
                if dtype == "Elation" and atk_ent.get("team") == "Player":
                    self.pending_player_elation_hits.append((int(atk_ent.get("uid") or 0), confirmed_euid))
            if confirmed_euid is not None and dtype not in ("Break", "Additional", "True"):
                self.pending_player_dmg_confirmed_euids.append(confirmed_euid)
                if (
                    self.pending_hit_sp_euid is not None
                    and dtype != "Follow-Up"
                    and self.pending_hit_sp_euid not in self.pending_player_sp_euids
                ):
                    self.pending_player_sp_euids.append(self.pending_hit_sp_euid)
                dmg_val = float(data.get("damage") or 0.0)
                if dmg_val > self.pending_player_hit_dmgs.get(confirmed_euid, 0.0):
                    self.pending_player_hit_dmgs[confirmed_euid] = dmg_val
            if dtype != "Break":
                self.pending_hit_hp_euids.clear()
                self.pending_hit_direct_euid = None
                self.pending_hit_sp_euid = None
                self.last_player_hit_euid = None
        if dtype in ("Additional", "True"):
            self.flush_pending_q_break()
        elif dtype == "Break" and atk_ent.get("team") == "Player":
            self.flush_pending_q_break()
            atk_uid = int(atk_ent.get("uid") or 0)
            if self.av_elems_map.get(atk_uid) == "Quantum" and self.last_stance_zero_euid is not None:
                self.pending_q_break = (round(cur_av, 2), self.last_stance_zero_euid, 0)
                self.last_stance_zero_euid = None
        if (
            atk_ent.get("team") == "Player"
            and int(atk_ent.get("uid") or 0) == 1403
            and dtype == "Additional"
            and self.pending_tie_highest_hp_euid is not None
        ):
            pick_item = (round(cur_av, 2), 1403, self.pending_tie_highest_hp_euid)
            if pick_item not in self.enemy_retarget_picks:
                self.enemy_retarget_picks.append(pick_item)
            self.pending_tie_highest_hp_euid = None

    def on_action_delay_zero(self, ptype: Any, val: float) -> None:
        if ptype == "ActionDelay" and abs(val) <= 1e-6:
            self.flush_pending_q_break()

    def on_enemy_stance_and_delay(self, uid: int, ptype: Any, val: float) -> None:
        if ptype == "CurrentStance" and val <= 1e-6:
            self.flush_pending_q_break()
            self.last_stance_zero_euid = uid
        elif (
            ptype == "ActionDelay"
            and self.pending_q_break is not None
            and uid == self.pending_q_break[1]
            and 0.0 < val < 100.0
        ):
            self.pending_q_break = (self.pending_q_break[0], self.pending_q_break[1], self.pending_q_break[2] + 1)
        if ptype == "CurrentStance" and self.pending_player_atk is not None and self.pending_hit_hp_euids:
            self.pending_hit_direct_euid = uid

    def on_enemy_sp_hit(self, uid: int, val: float) -> None:
        if self.pending_player_atk is not None and self.pending_hit_hp_euids and val > 0.0:
            self.pending_hit_direct_euid = uid
            self.pending_hit_sp_euid = uid

    def update_tie_highest_hp(
        self,
        uid: int,
        val: float,
        prev: Optional[float],
        last_enemy_hp: Mapping[int, float],
    ) -> None:
        if prev is not None and val < prev - 1.0 and last_enemy_hp:
            max_cur = max(last_enemy_hp.values())
            if prev >= max_cur - 1.0 and sum(1 for v in last_enemy_hp.values() if abs(v - prev) < 1.0) >= 2:
                self.pending_tie_highest_hp_euid = uid
            else:
                self.pending_tie_highest_hp_euid = None

    def try_record_enemy_hp_hit(self, uid: int, val: float, prev: Optional[float]) -> bool:
        if self.pending_player_atk is not None and (
            prev is None
            or val < prev - 1.0
            or (
                (
                    self.pending_player_atk[1].startswith("UID_")
                    or self.pending_player_atk[1].startswith("BattleEvent_")
                )
                and abs(val - prev) <= 1.0
                and val > 1e-3
            )
        ):
            self.pending_player_hit_euids.append(uid)
            if prev is not None and val < prev - 1.0:
                if uid not in self.pending_hit_hp_euids:
                    self.pending_hit_hp_euids.append(uid)
                self.last_player_hit_euid = uid
                if len(self.pending_hit_hp_euids) == 1 and uid not in self.pending_player_hit_dmgs:
                    self.pending_player_hit_dmgs[uid] = prev - val
            return True
        return False

    def record_enemy_retarget_pick(self, cur_av: float, cur_enemy_uid: int, dead_uid: int) -> None:
        self.enemy_retarget_picks.append((round(cur_av, 2), cur_enemy_uid, dead_uid))

    def on_player_stat_change_ult(self, uid: int, ptype: Any, val: float, char_db: CharacterDB) -> None:
        if self.pending_ally_ult_caster is not None:
            if ptype == "ActionDelay" and val < -1.0:
                tgt_name = _resolve_uid_name(uid, char_db)
                self.ally_ult_targets.setdefault(self.pending_ally_ult_caster, []).append(tgt_name)
                self._clear_pending_ally_ult()
            elif (
                self.pending_ally_ult_sid == 151203
                and self.pending_ally_ult_sp_fallback is None
                and ptype == "CurrentSP"
                and uid != self.pending_ally_ult_uid
                and val > 0.0
            ):
                self.pending_ally_ult_sp_fallback = _resolve_uid_name(uid, char_db)

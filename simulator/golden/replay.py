# coding: utf-8
"""Golden Trace 回放对齐与轨迹回放引擎（从 golden_diff.py 拆分）。"""

from __future__ import annotations

import importlib
import os
import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from simulator.actions import ActionKind
from simulator.events import ActionExecuteEvent, BattleEvent
from simulator.lifecycle import CallbackInterventionHook
from simulator.golden.models import (
    SPIRIT_TRAJECTORY_SKILLS,
    Decision,
    Divergence,
    Grant,
    MasterRecord,
    ReplayResult,
    TimelineItem,
    TrajectoryCast,
    TrajectoryRecord,
    TrajectoryResult,
    _sim_player_actors,
)
from simulator.golden.parser import SequenceRecorder, extract_enemy_target_plan


def resolve_non_crits(log_path: Optional[str] = None) -> Set[Tuple[int, int]]:
    """从对应实机日志插件 simulator/plugins/log_<tag>.py 加载 NON_CRITS 台账。"""
    if log_path is not None:
        m = re.search(r"battle_(\d{8}_\d{6})", str(log_path))
        if m:
            try:
                mod = importlib.import_module(f"simulator.plugins.log_{m.group(1)}")
                if hasattr(mod, "NON_CRITS"):
                    return set(getattr(mod, "NON_CRITS"))
            except Exception:
                pass
    return set()


def attach_exact_crit_oracle(
    sim: Any,
    log_path: Optional[str] = None,
    non_crits: Optional[Set[Tuple[int, int]]] = None,
) -> None:
    """挂载精准暴击真值映射器：优先使用插件传入的未暴击台账 non_crits，未传入时按兼容解析器回退。"""
    if non_crits is None:
        non_crits = resolve_non_crits(log_path)

    state = {"act_idx": -1, "hit_idx": 0}

    def _on_battle_ev(e: BattleEvent):
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

    sim.event_bus.subscribe(BattleEvent, _on_battle_ev)

    def _crit_oracle(req: Any) -> bool:
        if getattr(req.attacker, "is_enemy", False) or getattr(req.attacker, "is_countdown", False):
            return False
        h_idx = state["hit_idx"]
        state["hit_idx"] += 1
        if (state["act_idx"], h_idx) in non_crits:
            return False
        return True

    sim.crit_oracle = _crit_oracle


def run_replay(
    sim: Any,
    director: Any,
    decisions: List[Decision],
    av_budget: float,
    force: bool = False,
    on_step: Any = None,
    pre_step: Any = None,
) -> ReplayResult:
    """按官方决策脚本驱动模拟 (回放对齐模式)。"""
    recorder = SequenceRecorder(sim)
    result = ReplayResult(
        decisions_total=len(decisions),
        turn_matched=0,
        turn_total=sum(1 for d in decisions if d.kind != "ult"),
        ult_matched=0,
        ult_total=sum(1 for d in decisions if d.kind == "ult"),
        forced=force,
    )
    prev_auto_ult = getattr(sim, "auto_ult", None)
    if prev_auto_ult is not None:
        sim.auto_ult = False
    ptr = 0
    steps = 0
    idle_steps = 0

    def note(kind: str, detail: str) -> None:
        result.divergences.append(Divergence(av=float(getattr(sim, "current_av", 0.0)), kind=kind, detail=detail))

    def mark_ult_blocked(d: Decision) -> None:
        ent = sim.get_entity(d.actor)
        have = float(getattr(ent, "energy", 0.0)) if ent else 0.0
        need = float(getattr(ent, "max_energy", 0.0)) if ent else 0.0
        note("ult_blocked", f"{d.actor} 终结技【{d.name}】未能按脚本施放 (能量 {have:.0f}/{need:.0f})")

    def force_cast_ult(d: Decision) -> None:
        ent = sim.get_entity(d.actor)
        if ent is None:
            note("ult_failed", f"{d.actor} 终结技【{d.name}】施放失败 (实体不存在)")
            return
        deficit = float(ent.max_energy) - float(ent.energy)
        if deficit > 1e-4:
            ent.energy = float(ent.max_energy)
            result.grants.append(Grant(av=float(getattr(sim, "current_av", 0.0)), actor=d.actor, kind="energy", amount=deficit))
        if sim.cast_ultimate(d.actor):
            result.ult_matched += 1
            if director is not None:
                director.after_step()
        else:
            note("ult_failed", f"{d.actor} 终结技【{d.name}】能量补足后仍施放失败")

    def force_sp_for_skill(d: Decision) -> None:
        sp = getattr(sim, "sp", None)
        if sp is not None and not sp.can_consume(1):
            deficit = 1 - int(sp.current_sp)
            if deficit > 0:
                sp.generate(deficit, d.actor, "回放强制补足", float(getattr(sim, "current_av", 0.0)))
                result.grants.append(Grant(av=float(getattr(sim, "current_av", 0.0)), actor=d.actor, kind="sp", amount=float(deficit)))

    while steps < 1600 and float(getattr(sim, "current_av", 0.0)) <= av_budget:
        steps += 1
        if pre_step is not None and pre_step(sim):
            continue
        while ptr < len(decisions) and decisions[ptr].kind == "ult":
            d = decisions[ptr]
            if force:
                force_cast_ult(d)
                ptr += 1
                continue
            ent = sim.get_entity(d.actor)
            if ent is not None and float(getattr(ent, "energy", 0.0)) >= float(getattr(ent, "max_energy", 0.0)) - 1e-4:
                if sim.cast_ultimate(d.actor):
                    result.ult_matched += 1
                    ptr += 1
                    if director is not None:
                        director.after_step()
                    continue
            break
        actor_ent = sim.advance_to_next_turn()
        if actor_ent is None:
            if director is not None:
                director.after_step()
            idle_steps += 1
            if idle_steps > 100:
                break
            continue
        idle_steps = 0
        override = None
        scripted: Optional[Decision] = None
        if actor_ent.name in _sim_player_actors(sim):
            j = ptr
            while j < len(decisions) and decisions[j].kind == "ult":
                j += 1
            if j < len(decisions):
                d = decisions[j]
                if d.actor == actor_ent.name:
                    for k in range(ptr, j):
                        if force:
                            force_cast_ult(decisions[k])
                        else:
                            mark_ult_blocked(decisions[k])
                    ptr = j + 1
                    scripted = d
                    if force and d.kind == "skill":
                        force_sp_for_skill(d)
                    override = ActionKind.SKILL if d.kind == "skill" else ActionKind.BASIC
                    result.turn_matched += 1
                else:
                    note("turn_order", f"回合顺序偏离: 脚本期待 {d.actor} 行动, 实际为 {actor_ent.name}")
            else:
                note("script_exhausted", f"脚本决策已耗尽, {actor_ent.name} 改由默认策略行动")
        actions_before = len(recorder.raw_actions)
        sim.step(action_override=override)
        if director is not None:
            director.after_step()
        if on_step is not None:
            on_step(sim)
        if scripted is not None and scripted.kind == "skill":
            executed = [a for a in recorder.raw_actions[actions_before:] if a.actor_name == scripted.actor]
            if executed and not any((getattr(a, "skill_config_id", 0) or 0) == scripted.skill_id for a in executed):
                note("sp_downgrade", f"{scripted.actor} 战技【{scripted.name}】未按脚本执行 (实际: {executed[0].action_type})")

    for k in range(ptr, len(decisions)):
        if decisions[k].kind == "ult":
            if force:
                force_cast_ult(decisions[k])
            else:
                mark_ult_blocked(decisions[k])

    if prev_auto_ult is not None:
        sim.auto_ult = prev_auto_ult
    result.sequence = recorder.finish()
    return result


_LOG_PLAN_CACHE: Dict[Tuple[str, float, int], Tuple[List[Dict[str, Any]], bool]] = {}


def run_trajectory_replay(
    sim: Any,
    director: Any,
    timeline: List[TimelineItem],
    av_budget: float,
    log_path: Optional[str] = None,
) -> TrajectoryResult:
    """轨迹回放 v2: 全施放轨迹按官方 AV 钉死, 缺口补足逐项记账。"""
    result = TrajectoryResult(replay=None)
    if log_path is not None:
        lp_str = str(log_path)
        cache_key: Optional[Tuple[str, float, int]] = None
        if os.path.exists(lp_str):
            st = os.stat(lp_str)
            cache_key = (os.path.abspath(lp_str), st.st_mtime, st.st_size)
        cached_plan = _LOG_PLAN_CACHE.get(cache_key) if cache_key is not None else None
        if cached_plan is not None:
            target_plan, has_break_in_log = cached_plan
        else:
            target_plan = extract_enemy_target_plan(log_path)
            has_break_in_log = False
            if os.path.exists(lp_str):
                with open(lp_str, "r", encoding="utf-8") as _bf:
                    has_break_in_log = '"type": "Break"' in _bf.read()
            if cache_key is not None:
                _LOG_PLAN_CACHE[cache_key] = (target_plan, has_break_in_log)

        def _attacker_matches_uid(attacker: Any, uid: Any) -> bool:
            name = getattr(attacker, "name", "") or ""
            uid_map = getattr(sim, "enemy_uid_map", None) or {}
            if uid in uid_map:
                return uid_map[uid] == name
            return True

        def _find_turn(now_av: float, attacker: Any = None) -> Optional[Dict[str, Any]]:
            fallback = None
            for p in target_plan:
                if abs(p["av"] - now_av) < 1.0:
                    if attacker is not None and not _attacker_matches_uid(attacker, p.get("enemy_uid")):
                        continue
                    if p["targets"] or p["sub_targets"]:
                        return p
                    if fallback is None:
                        fallback = p
            return fallback

        existing_target_provider = getattr(sim, "target_provider", None)

        def _trace_target_provider(attacker: Any, candidates: List[Any], sub_idx: int = 0) -> Any:
            if existing_target_provider is not None:
                chosen = existing_target_provider(attacker, candidates, sub_idx)
                if chosen is not None:
                    return chosen
            if attacker is not None and not getattr(attacker, "is_enemy", False):
                return None
            now_av = float(getattr(sim, "current_av", 0.0))
            best_turn = _find_turn(now_av, attacker)
            if best_turn:
                subs = best_turn.get("sub_targets") or []
                sub_hps = best_turn.get("sub_hp_targets") or []
                if subs:
                    if sub_idx < len(subs):
                        hp_list = sub_hps[sub_idx] if sub_idx < len(sub_hps) else subs[sub_idx]
                        if getattr(attacker, "is_enemy", False) and not hp_list:
                            memo = next((c for c in candidates if getattr(c, "is_memosprite", False)), None)
                            if memo is not None:
                                return memo
                        if subs[sub_idx]:
                            tname = subs[sub_idx][0]
                            matched = next((c for c in candidates if c.name == tname), None)
                            if matched:
                                return matched
                    return None
                elif sub_idx == 0:
                    tlist = best_turn.get("targets", [])
                    if tlist:
                        tname = tlist[0]
                        matched = next((c for c in candidates if c.name == tname), None)
                        if matched:
                            return matched
                    elif getattr(attacker, "is_enemy", False):
                        memo = next((c for c in candidates if getattr(c, "is_memosprite", False)), None)
                        if memo is not None:
                            return memo
            return candidates[0] if candidates and sub_idx == 0 else None

        sim.target_provider = _trace_target_provider
        sim.record_break_damage = has_break_in_log

    turn_items = [i for i in timeline if i.kind in ("basic", "skill")]
    ult_queue = deque([(idx, i) for idx, i in enumerate(timeline) if i.kind == "ult"])
    spirit_queues: Dict[int, deque] = {}
    for idx, i in enumerate(timeline):
        if i.kind == "spirit":
            spirit_queues.setdefault(i.skill_id, deque()).append(
                TrajectoryCast(av=i.av, actor=i.actor, skill_id=i.skill_id, name=i.name, order=idx)
            )
    turn_indices = [idx for idx, i in enumerate(timeline) if i.kind in ("basic", "skill")]
    fired_master: Set[int] = set()
    organic: List[Tuple[int, float]] = []
    organic_used: Set[int] = set()
    master_fired: List[Tuple[str, int, float]] = []

    def _on_action(e: Any) -> None:
        sid = int(getattr(e, "skill_config_id", 0) or 0)
        if sid in SPIRIT_TRAJECTORY_SKILLS:
            organic.append((sid, float(getattr(e, "av", 0.0))))
        actor = getattr(e, "actor_name", "")
        kind = getattr(e, "action_kind", None)
        if actor in _sim_player_actors(sim) and kind in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE):
            master_fired.append((actor, sid, float(getattr(e, "av", 0.0))))

    sim.event_bus.subscribe(ActionExecuteEvent, _on_action)

    def _spirit_due(cast: TrajectoryCast) -> bool:
        ent = sim.get_entity(cast.actor)
        if ent is None or not getattr(ent, "is_memosprite", False):
            return False
        kit = getattr(ent, "kit", None)
        if kit is not None and hasattr(kit, "definition"):
            try:
                adef = kit.definition(ActionKind.MEMOSPRITE_SKILL)
                if adef is not None and getattr(adef, "skill_id", 0) and int(adef.skill_id) != int(cast.skill_id):
                    return False
            except Exception:
                pass
        if ent.name in getattr(sim, "_ready_queue", ()):
            return True
        if float(getattr(ent, "distance_remaining", 1e9)) <= 5.0:
            return True
        peek = sim.peek_next_actor() if hasattr(sim, "peek_next_actor") else None
        return peek is ent

    def _match_organic_spirits() -> None:
        for sid, q in spirit_queues.items():
            while q:
                head = q[0]
                match_idx = None
                for idx, (s2, av2) in enumerate(organic):
                    if idx in organic_used or s2 != sid:
                        continue
                    if av2 >= head.av - 2.0:
                        match_idx = idx
                        break
                    organic_used.add(idx)
                if match_idx is None:
                    break
                organic_used.add(match_idx)
                result.records.append(TrajectoryRecord(sid, head.name, head.av, organic[match_idx][1], "organic", ()))
                q.popleft()

    def _resolve_turn_owner(raw_owner: str) -> str:
        for pfx in ("UID_", "敌人#"):
            if raw_owner.startswith(pfx) and raw_owner[len(pfx):].isdigit():
                uid_map = getattr(sim, "enemy_uid_map", None)
                if isinstance(uid_map, dict):
                    mapped = uid_map.get(int(raw_owner[len(pfx):]))
                    if mapped:
                        return str(mapped)
        return raw_owner

    def _ult_blocked(u_idx: int, u_item: Any, now_av: float, *, allow_cur_enemy: bool = False) -> bool:
        if now_av > u_item.av + 15.0:
            return False
        cur_turn = getattr(sim, "current_turn_entity", None)
        u_owner = _resolve_turn_owner(getattr(u_item, "turn_owner", ""))
        if (
            cur_turn is not None
            and getattr(cur_turn, "is_enemy", False)
            and u_owner in _sim_player_actors(sim)
            and abs(now_av - u_item.av) <= 0.5
        ):
            return True
        if (
            not allow_cur_enemy
            and cur_turn is not None
            and getattr(cur_turn, "is_enemy", False)
            and u_owner
            and u_owner not in _sim_player_actors(sim)
            and abs(now_av - u_item.av) <= 0.5
            and now_av <= u_item.av + 1e-4
            and (
                getattr(cur_turn, "name", "").replace("_", "") == u_owner.replace("_", "")
                if u_owner[-1:].isdigit()
                else getattr(cur_turn, "name", "").startswith(u_owner)
            )
        ):
            return True
        _cur_matches_owner = (
            allow_cur_enemy
            and cur_turn is not None
            and getattr(cur_turn, "is_enemy", False)
            and bool(u_owner)
            and (
                getattr(cur_turn, "name", "").replace("_", "") == u_owner.replace("_", "")
                if u_owner[-1:].isdigit()
                else getattr(cur_turn, "name", "").startswith(u_owner)
            )
        )
        _u_actor_ent = sim.get_entity(u_item.actor) if getattr(u_item, "actor", None) else None
        _u_actor_full = (
            _u_actor_ent is not None
            and float(getattr(_u_actor_ent, "energy", 0.0)) >= float(getattr(_u_actor_ent, "max_energy", 1e9)) - 1e-6
        )
        if (
            u_owner
            and u_owner not in _sim_player_actors(sim)
            and abs(now_av - u_item.av) <= 0.5
            and not (_cur_matches_owner and _u_actor_full)
        ):
            if any(
                e is not cur_turn
                and getattr(e, "is_enemy", False)
                and float(getattr(e, "current_hp", 0.0)) > 0.0
                and (
                    getattr(e, "name", "").replace("_", "") == u_owner.replace("_", "")
                    if u_owner[-1:].isdigit()
                    else getattr(e, "name", "").startswith(u_owner)
                )
                and float(getattr(e, "speed", 0.0)) > 0.0
                and now_av + float(getattr(e, "distance_remaining", 0.0)) / float(e.speed) <= u_item.av + 1e-4
                for e in getattr(sim, "entities", ())
            ):
                return True
        if u_owner.startswith("UID_") and now_av < u_item.av - 1e-4:
            return True
        actor_ent = sim.get_entity(u_item.actor) if getattr(u_item, "actor", None) else None
        if actor_ent is not None and getattr(actor_ent, "_avatar_change_target_id", None) is not None:
            return True
        u_turn_seq = getattr(u_item, "turn_seq", 0)
        if (
            u_owner in _sim_player_actors(sim)
            and abs(now_av - u_item.av) <= 0.5
            and (cur_turn is None or getattr(cur_turn, "name", "") != u_owner)
        ):
            if any(
                t_idx not in fired_master
                and getattr(timeline[t_idx], "turn_seq", -1) == u_turn_seq
                for t_idx in turn_indices
            ):
                return True
        for t_idx in turn_indices:
            if t_idx >= u_idx:
                break
            if t_idx not in fired_master and abs(timeline[t_idx].av - u_item.av) <= 0.5:
                return True
        for sq in spirit_queues.values():
            if not sq:
                continue
            sp_head = sq[0]
            if sp_head.order < u_idx and abs(sp_head.av - u_item.av) <= 0.5 and _spirit_due(sp_head):
                return True
            if (
                u_owner == "环境/插队"
                and u_item.av > 1e-4
                and getattr(timeline[sp_head.order], "turn_seq", -1) == u_turn_seq
                and abs(sp_head.av - u_item.av) <= 0.5
                and (cur_turn is None or getattr(cur_turn, "name", "") != sp_head.actor)
                and _spirit_due(sp_head)
            ):
                return True
        return False

    def _fire_due_ults(*, allow_cur_enemy: bool = False) -> None:
        now_av = float(getattr(sim, "current_av", 0.0))
        while ult_queue and ult_queue[0][1].av <= now_av + 1e-4 and not _ult_blocked(ult_queue[0][0], ult_queue[0][1], now_av, allow_cur_enemy=allow_cur_enemy):
            if allow_cur_enemy and not getattr(ult_queue[0][1], "between_enemy_sub_actions", False):
                _cand_ent = sim.get_entity(ult_queue[0][1].actor)
                if _cand_ent is None or float(_cand_ent.energy) < float(_cand_ent.max_energy) - 1e-6:
                    break
            _idx, item = ult_queue.popleft()
            fired_master.add(_idx)
            ent = sim.get_entity(item.actor)
            if ent is None:
                result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))
                continue
            deficit = float(ent.max_energy) - float(ent.energy)
            if deficit > 1e-4:
                ent.energy = float(ent.max_energy)
                result.ult_energy_granted += deficit
                diag_cb = getattr(sim, "timeline_diag_cb", None)
                if callable(diag_cb):
                    diag_cb("ULT_EN", f"{item.actor} +{deficit:.2f} (need={item.av:.2f}, now={now_av:.2f})")
            ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
            if director is not None:
                director.after_step()
            result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, now_av if ok else None))

    def _peek_next() -> Any:
        return sim.peek_next_actor()

    recorder = SequenceRecorder(sim)
    replay = ReplayResult(decisions_total=len(turn_items) + len(ult_queue), turn_matched=0, turn_total=len(turn_items), ult_matched=0, ult_total=len(ult_queue), forced=True)
    prev_auto_ult = getattr(sim, "auto_ult", None)
    if prev_auto_ult is not None:
        sim.auto_ult = False

    def _on_turn_action_completed(actor_ent: Any, *, pre_turn_end: bool = False) -> None:
        now_av = float(getattr(sim, "current_av", 0.0))
        act_name = getattr(actor_ent, "name", "")
        while (
            ult_queue
            and ult_queue[0][1].av <= now_av + 1e-4
            and (
                (
                    pre_turn_end
                    and not getattr(actor_ent, "is_enemy", False)
                    and getattr(ult_queue[0][1], "turn_owner", "") == act_name
                )
                or (
                    not pre_turn_end
                    and ult_queue[0][1].actor == act_name
                    and getattr(ult_queue[0][1], "turn_owner", "") == act_name
                )
                or (
                    getattr(actor_ent, "is_enemy", False)
                    and bool(_resolve_turn_owner(getattr(ult_queue[0][1], "turn_owner", "")))
                    and (
                        act_name.replace("_", "") == _resolve_turn_owner(getattr(ult_queue[0][1], "turn_owner", "")).replace("_", "")
                        if _resolve_turn_owner(getattr(ult_queue[0][1], "turn_owner", ""))[-1:].isdigit()
                        else act_name.startswith(_resolve_turn_owner(getattr(ult_queue[0][1], "turn_owner", "")))
                    )
                )
            )
            and not _ult_blocked(ult_queue[0][0], ult_queue[0][1], now_av, allow_cur_enemy=pre_turn_end)
        ):
            _idx, item = ult_queue.popleft()
            fired_master.add(_idx)
            ent = sim.get_entity(item.actor)
            if ent is not None:
                deficit = float(ent.max_energy) - float(ent.energy)
                if deficit > 1e-4:
                    ent.energy = float(ent.max_energy)
                    result.ult_energy_granted += deficit
                    diag_cb = getattr(sim, "timeline_diag_cb", None)
                    if callable(diag_cb):
                        diag_cb("ULT_EN", f"{item.actor} +{deficit:.2f} (post, need={item.av:.2f}, now={now_av:.2f})")
                ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
                if director is not None:
                    director.after_step()
                result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, now_av if ok else None))
            else:
                result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))

    def _pre_turn_end_hook(actor_ent: Any) -> None:
        if getattr(actor_ent, "is_enemy", False) and float(getattr(actor_ent, "current_hp", 0.0)) > 0.0:
            _pending_d = getattr(sim, "_pending_turn_reset_distance", None)
            _base_d = 10000.0 if _pending_d is None else float(_pending_d)
            actor_ent.distance_remaining = _base_d
            _on_turn_action_completed(actor_ent, pre_turn_end=True)
            _delta_d = float(getattr(actor_ent, "distance_remaining", _base_d)) - _base_d
            if abs(_delta_d) > 1e-6:
                sim._pending_turn_reset_distance = max(0.0, _base_d + _delta_d)
            return
        _on_turn_action_completed(actor_ent, pre_turn_end=True)

    def _on_sub_action_end(
        actor_ent: Any,
        *,
        sub_action_index: int,
        has_next_sub_action: bool,
    ) -> None:
        if not (getattr(actor_ent, "is_enemy", False) and has_next_sub_action):
            return
        if not ult_queue:
            return
        u_item = ult_queue[0][1]
        cur_t = getattr(sim, "current_turn_entity", None)
        now_sub_av = float(getattr(sim, "current_av", 0.0))
        u_ent_d = sim.get_entity(u_item.actor)
        diag_cb = getattr(sim, "timeline_diag_cb", None)
        if callable(diag_cb):
            e_cur = float(getattr(u_ent_d, "energy", 0.0)) if u_ent_d is not None else -1.0
            e_max = float(getattr(u_ent_d, "max_energy", 0.0)) if u_ent_d is not None else -1.0
            diag_cb(
                "SUB_END",
                f"turn={getattr(cur_t, 'name', None)} head={u_item.actor}@{u_item.av:.4f} "
                f"now={now_sub_av:.4f} betw={getattr(u_item, 'between_enemy_sub_actions', False)} "
                f"ow={getattr(u_item, 'turn_owner', '')} E={e_cur:.2f}/{e_max:.2f}",
            )
        if not getattr(u_item, "between_enemy_sub_actions", False):
            return
        if u_item.av > now_sub_av + 1e-4:
            return
        if u_ent_d is not None and float(u_ent_d.energy) >= float(u_ent_d.max_energy) - 1e-6:
            _fire_due_ults(allow_cur_enemy=True)

    actor_queues = defaultdict(deque)
    for idx, i in enumerate(timeline):
        if i.kind in ("basic", "skill"):
            actor_queues[i.actor].append((idx, i))

    def _pop_actor_decision(actor_name: str, *, require_due: bool = False) -> Tuple[Optional[ActionKind], Optional[Tuple[str, ...]]]:
        q = actor_queues.get(actor_name)
        if not q:
            return None, None
        now_av = float(getattr(sim, "current_av", 0.0))
        if require_due and abs(float(q[0][1].av) - now_av) > 0.25:
            return None, None
        _idx, head = q.popleft()
        fired_master.add(_idx)
        if head.kind == "skill":
            sp = getattr(sim, "sp", None)
            vm_rt = getattr(sim, "vm_runtime", None)
            extra_bp = int(vm_rt.entity_boost_points.get(head.actor, 0.0)) if vm_rt is not None else 0
            if sp is not None and (int(sp.current_sp) + extra_bp) < 1:
                deficit = 1 - (int(sp.current_sp) + extra_bp)
                if deficit > 0:
                    sp.generate(deficit, head.actor, "轨迹回放强制补足", float(getattr(sim, "current_av", 0.0)))
                    result.sp_granted += deficit
                    diag_cb = getattr(sim, "timeline_diag_cb", None)
                    if callable(diag_cb):
                        diag_cb("SP", f"FORCED {head.actor} +{deficit} team_sp={sp.current_sp} extra_bp={extra_bp}")
        dec_kind = ActionKind.SKILL if head.kind == "skill" else ActionKind.BASIC
        dec_tgts: Optional[Tuple[str, ...]] = None
        uid_override_map = getattr(sim, "enemy_uid_map", None)
        h_uids = getattr(head, "target_uids", None)
        if uid_override_map and h_uids:
            mapped_list = []
            for u in h_uids:
                if u not in uid_override_map:
                    continue
                ename = uid_override_map[u]
                ent = sim.get_entity(ename)
                mapped_list.append(ent.name if ent is not None else ename)
            if mapped_list:
                dec_tgts = tuple(mapped_list)
        if dec_tgts is None:
            raw_tids = getattr(head, "target_ids", None)
            if raw_tids:
                mapped_raw = [
                    ent.name
                    for tid in raw_tids
                    if (ent := sim.get_entity(tid)) is not None
                ]
                if len(mapped_raw) == len(raw_tids):
                    dec_tgts = tuple(mapped_raw)
        replay.turn_matched += 1
        return dec_kind, dec_tgts

    def _on_auto_chained_skill(actor_name: str, sid: int) -> None:
        q = actor_queues.get(actor_name)
        if not q:
            return
        now_av = float(getattr(sim, "current_av", 0.0))
        if (
            abs(float(q[0][1].av) - now_av) <= 0.25
            and (int(q[0][1].skill_id) == int(sid) or int(sid) == 0)
        ):
            _idx, _ = q.popleft()
            fired_master.add(_idx)
            replay.turn_matched += 1

    sim.intervention_hook = CallbackInterventionHook(
        on_sub_action_end=_on_sub_action_end,
        on_pre_turn_end=_pre_turn_end_hook,
        on_turn_action_completed=_on_turn_action_completed,
        on_auto_chained_skill=_on_auto_chained_skill,
        decide_insert_action=lambda actor_name: _pop_actor_decision(actor_name, require_due=True),
    )
    if director is not None and hasattr(director, "drain_opening_actions"):
        before_master_len = len(master_fired)
        director.drain_opening_actions()
        for m_actor, m_sid, m_av in master_fired[before_master_len:]:
            q = actor_queues.get(m_actor)
            if (
                q
                and q[0][1].turn_owner == "环境/插队"
                and abs(float(q[0][1].av) - float(m_av)) <= 0.05
                and (int(q[0][1].skill_id) == int(m_sid) or int(m_sid) == 0)
            ):
                _idx, _ = q.popleft()
                fired_master.add(_idx)
                replay.turn_matched += 1
    steps = 0
    delays = 0
    idle_steps = 0
    if ult_queue and ult_queue[0][1].av <= 1e-4 and getattr(ult_queue[0][1], "turn_owner", "") == "环境/插队":
        _fire_due_ults()
    while steps < 1600 and (
        float(getattr(sim, "current_av", 0.0)) <= av_budget
        or (
            float(getattr(sim, "current_av", 0.0)) <= av_budget + 1e-4
            and (
                any(q and q[0][1].av <= av_budget for q in actor_queues.values())
                or (ult_queue and ult_queue[0][1].av <= av_budget)
                or any(q and q[0].av <= av_budget for q in spirit_queues.values())
            )
        )
    ):
        steps += 1
        if getattr(sim, "_current_turn_entity", None) is None and delays < 800:
            nxt = _peek_next()
            if nxt is not None and nxt.name in _sim_player_actors(sim) and not getattr(nxt, "_is_avatar_change_target", False):
                land_av = float(getattr(sim, "current_av", 0.0)) + float(nxt.remaining_av)
                q = actor_queues.get(nxt.name)
                if q:
                    head = q[0][1]
                    if head.av > land_av + 1e-4:
                        nxt.distance_remaining += float(nxt.speed) * (head.av - land_av)
                        if nxt.name in getattr(sim, "_ready_queue", ()):
                            sim._ready_queue.remove(nxt.name)
                        delays += 1
                        continue
                    elif head.av < land_av and (land_av - head.av) <= 0.5:
                        nxt.distance_remaining = max(0.0, nxt.distance_remaining - float(nxt.speed) * (land_av - head.av))
                elif not any(
                    getattr(u, "turn_owner", "") == nxt.name and abs(float(u.av) - land_av) <= 0.5
                    for _, u in ult_queue
                ):
                    nxt.distance_remaining += float(nxt.speed) * (av_budget - land_av + 1000.0)
                    if nxt.name in getattr(sim, "_ready_queue", ()):
                        sim._ready_queue.remove(nxt.name)
                    result.sunk_turns += 1
                    delays += 1
                    continue
        if getattr(sim, "_current_turn_entity", None) is None:
            while True:
                now0 = float(getattr(sim, "current_av", 0.0))
                landing_av = sim.peek_landing_av()
                ult_av: Optional[float] = None
                if ult_queue:
                    cand_ult = ult_queue[0][1].av
                    if now0 < cand_ult <= landing_av:
                        next_actor = getattr(sim, "peek_next_actor", lambda: None)()
                        blocked_enemy = (
                            cand_ult >= landing_av - 0.25
                            and (
                                (
                                    next_actor is not None
                                    and (getattr(next_actor, "is_enemy", False) or getattr(next_actor, "is_countdown", False))
                                )
                                or any(
                                    (getattr(e, "is_enemy", False) or getattr(e, "is_countdown", False))
                                    and float(getattr(e, "current_hp", 0.0)) > 0.0
                                    and abs(now0 + float(getattr(e, "remaining_av", 1e9)) - landing_av) < 1e-3
                                    for e in getattr(sim, "entities", ())
                                )
                            )
                        )
                        if not blocked_enemy and not (cand_ult >= landing_av - 0.25 and _ult_blocked(ult_queue[0][0], ult_queue[0][1], cand_ult)):
                            ult_av = cand_ult
                dir_av: Optional[float] = None
                if director is not None and hasattr(director, "peek_next_interrupt_av"):
                    dir_av = director.peek_next_interrupt_av(now0, landing_av)
                if ult_av is None and dir_av is None:
                    break
                if dir_av is not None and (ult_av is None or dir_av <= ult_av + 1e-6):
                    sim.advance_clock(dir_av - now0)
                    if hasattr(director, "mark_interrupt_av_checked"):
                        director.mark_interrupt_av_checked(dir_av)
                    director.after_step()
                    _fire_due_ults()
                else:
                    assert ult_av is not None
                    sim.advance_clock(ult_av - now0)
                    if director is not None:
                        director.after_step()
                    _fire_due_ults()
        next_actor = getattr(sim, "peek_next_actor", lambda: None)()
        now_b = float(getattr(sim, "current_av", 0.0))
        if not (
            ult_queue
            and abs(ult_queue[0][1].av - now_b) < 0.25
            and getattr(ult_queue[0][1], "turn_owner", "") != "环境/插队"
            and (
                (
                    next_actor is not None
                    and (getattr(next_actor, "is_enemy", False) or getattr(next_actor, "is_countdown", False))
                )
                or any(
                    (getattr(e, "is_enemy", False) or getattr(e, "is_countdown", False))
                    and float(getattr(e, "current_hp", 0.0)) > 0.0
                    and float(getattr(e, "remaining_av", 1e9)) <= 1e-3
                    for e in getattr(sim, "entities", ())
                )
            )
        ):
            _fire_due_ults()
        actor_ent = sim.advance_to_next_turn()
        if director is not None:
            director.after_step()
        if (
            float(getattr(sim, "current_av", 0.0)) < 1e-4
            or (
                actor_ent is not None
                and not getattr(actor_ent, "is_enemy", False)
                and ult_queue
                and (
                    getattr(ult_queue[0][1], "turn_owner", "") == actor_ent.name
                    or (
                        getattr(actor_ent, "is_memosprite", False)
                        and getattr(ult_queue[0][1], "turn_owner", "") == "环境/插队"
                        and any(
                            sq
                            and sq[0].actor == actor_ent.name
                            and getattr(timeline[sq[0].order], "turn_seq", -1)
                            == getattr(ult_queue[0][1], "turn_seq", -2)
                            for sq in spirit_queues.values()
                        )
                    )
                )
            )
        ):
            _fire_due_ults()
        if actor_ent is None or getattr(actor_ent, "current_hp", 0.0) <= 0.0:
            if actor_ent is not None and getattr(sim, "_current_turn_entity", None) is actor_ent:
                sim._current_turn_entity = None
            if director is not None:
                director.after_step()
            idle_steps += 1
            if idle_steps > 100:
                break
            continue
        idle_steps = 0
        override = None
        target_ids = None
        if actor_ent.name in _sim_player_actors(sim):
            override, target_ids = _pop_actor_decision(actor_ent.name, require_due=False)
        sim.step(action_override=override, target_ids=target_ids)
        if director is not None:
            director.after_step()
        _match_organic_spirits()
        _fire_due_ults()
        _match_organic_spirits()

    while ult_queue and ult_queue[0][1].av <= av_budget:
        _idx, item = ult_queue.popleft()
        fired_master.add(_idx)
        ent = sim.get_entity(item.actor)
        if ent is not None:
            ent.energy = float(ent.max_energy)
            ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
            if director is not None:
                director.after_step()
            result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, float(getattr(sim, "current_av", 0.0)) if ok else None))
        else:
            result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))
    while ult_queue:
        _idx, item = ult_queue.popleft()
        result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))
    _match_organic_spirits()
    for sid, q in spirit_queues.items():
        while q:
            cast = q.popleft()
            result.records.append(TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ()))
    if prev_auto_ult is not None:
        sim.auto_ult = prev_auto_ult
    replay.sequence = recorder.finish()
    replay.ult_matched = sum(1 for r in result.ult_records if r.fired_av is not None)
    result.replay = replay
    fired_by_key = defaultdict(list)
    for actor, sid, av in master_fired:
        fired_by_key[(actor, sid)].append(av)
    for item in turn_items:
        candidates = fired_by_key.get((item.actor, item.skill_id), [])
        fired_av = None
        if candidates:
            best = min(range(len(candidates)), key=lambda i: abs(candidates[i] - item.av))
            fired_av = candidates.pop(best)
        result.master_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, fired_av))
    result.records.sort(key=lambda r: r.official_av)
    return result

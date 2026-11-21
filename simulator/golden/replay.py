# coding: utf-8
"""Golden Trace 回放对齐与轨迹回放引擎（从 golden_diff.py 拆分）。"""

from __future__ import annotations

import importlib
import os
import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from simulator.actions import ActionContext, ActionKind
from simulator.events import ActionExecuteEvent, BattleEvent, TurnBeginEvent
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
        target_plan = extract_enemy_target_plan(log_path)

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

        def _trace_bounce_provider(attacker: Any, candidates: List[Any], count: int = 10, sub_idx: int = 0) -> List[Any]:
            now_av = float(getattr(sim, "current_av", 0.0))
            best_turn = _find_turn(now_av, attacker)
            if best_turn:
                subs = best_turn.get("sub_targets") or []
                if subs:
                    tlist = subs[sub_idx] if sub_idx < len(subs) and subs[sub_idx] else []
                else:
                    tlist = best_turn.get("targets", []) if sub_idx == 0 else []
                if count <= 0:
                    c_map = {c.name: c for c in candidates}
                    return [c_map[t] for t in dict.fromkeys(tlist) if t in c_map]
                if tlist:
                    res = []
                    c_map = {c.name: c for c in candidates}
                    for tname in tlist:
                        if tname in c_map:
                            res.append(c_map[tname])
                        if len(res) >= count:
                            break
                    while len(res) < count and res:
                        res.append(res[-1])
                    return res
            if count <= 0:
                return list(candidates[:1]) if sub_idx == 0 else []
            return [candidates[i % len(candidates)] for i in range(count)] if sub_idx == 0 else []

        sim.target_provider = _trace_target_provider
        sim.bounce_target_provider = _trace_bounce_provider

        has_break_in_log = False
        if log_path and os.path.exists(str(log_path)):
            with open(str(log_path), "r", encoding="utf-8") as _bf:
                has_break_in_log = '"type": "Break"' in _bf.read()
        sim.record_break_damage = has_break_in_log

    turn_items = [i for i in timeline if i.kind in ("basic", "skill")]
    ult_queue = deque([(idx, i) for idx, i in enumerate(timeline) if i.kind == "ult"])
    spirit_queues: Dict[int, deque] = {}
    for idx, i in enumerate(timeline):
        if i.kind == "spirit":
            spirit_queues.setdefault(i.skill_id, deque()).append(
                TrajectoryCast(av=i.av, actor=i.actor, skill_id=i.skill_id, name=i.name, order=idx)
            )
    master_indices = [idx for idx, i in enumerate(timeline) if i.kind in ("basic", "skill", "ult")]
    turn_indices = [idx for idx, i in enumerate(timeline) if i.kind in ("basic", "skill")]
    fired_master: Set[int] = set()
    organic: List[Tuple[int, float]] = []
    organic_used: Set[int] = set()
    stash = {"amount": 0.0}
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

    def _kit_of(entity_name: str) -> Any:
        ent = sim.get_entity(entity_name)
        return getattr(ent, "kit", None) if ent is not None else None

    def _changye_kit() -> Any:
        moon = sim.get_entity("长夜月")
        return getattr(moon, "kit", None) if moon is not None else None

    def _get_vm_memoria() -> float:
        rt = getattr(sim, "vm_runtime", None)
        if rt is None:
            return 0.0
        from simulator.vm.expr import dotnet_hash

        if sim.get_entity("长夜") is not None and "长夜" in rt.entity_dynamics:
            return float(rt.get_dynamic_value("长夜", dotnet_hash("_Partner_Count")))
        if "长夜月" in rt.entity_dynamics:
            return float(rt.get_dynamic_value("长夜月", dotnet_hash("_Partner_Count_Show")))
        return 0.0

    def _set_vm_memoria(val: float) -> None:
        rt = getattr(sim, "vm_runtime", None)
        if rt is None:
            return
        from simulator.vm.expr import dotnet_hash

        v = float(val)
        if "长夜月" in rt.entity_dynamics:
            rt.set_dynamic_value("长夜月", dotnet_hash("_Partner_Count_Show"), v)
        if "长夜" in rt.entity_dynamics:
            rt.set_dynamic_value("长夜", dotnet_hash("_Partner_Count"), v)

    def _force_spirit(cast: TrajectoryCast, now_av: float) -> TrajectoryRecord:
        patches: List[str] = []
        sid = cast.skill_id
        organic_before = len(organic)
        rt = getattr(sim, "vm_runtime", None)
        try:
            if rt is not None:
                enemies = tuple(
                    e.name for e in sim.entities
                    if getattr(e, "is_enemy", False) and float(getattr(e, "current_hp", 0.0)) > 0.0
                )
                if sid in (1141301, 1141307):
                    if sim.get_entity("长夜月") is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ())
                    changye_ent = sim.get_entity("长夜")
                    if changye_ent is None or float(getattr(changye_ent, "current_hp", 0.0)) <= 0.0:
                        changye_ent = rt.summon_servant("长夜月", 11413)
                        patches.append("presence")
                        result.presence_grants += 1
                    sim.cancel_immediate_action("长夜")
                    if changye_ent is not None:
                        sim._turn_id += 1
                        sim.event_bus.publish(TurnBeginEvent(
                            av=round(sim.current_av, 2),
                            cycle=sim.current_cycle,
                            actor_id=changye_ent.name,
                            actor_name=changye_ent.name,
                            speed=round(changye_ent.speed, 1),
                            turn_id=sim._turn_id,
                        ))
                        sim.run_stage_turn_begin(changye_ent)
                    if sid == 1141307:
                        if stash["amount"] > 0:
                            cur_mem = _get_vm_memoria()
                            _set_vm_memoria(cur_mem + stash["amount"])
                            patches.append(f"stash+{stash['amount']:.0f}")
                            stash["amount"] = 0.0
                        cur_mem = _get_vm_memoria()
                        if cur_mem < 16:
                            deficit = 16 - cur_mem
                            _set_vm_memoria(16.0)
                            patches.append(f"memoria+{deficit:.0f}")
                            result.memoria_granted += deficit
                        rt.trigger_ability(
                            caster_id="长夜",
                            ability_name="Servant_EvernightServant_00_Skill11_Phase01",
                            target_ids=enemies,
                            skill_target_ids=enemies,
                            current_skill_type="Servant",
                            current_attack_type="Servant",
                        )
                        rt.modifier_engine.dispatch_event(
                            "OnListenAfterSkillUse",
                            param_entity_id="长夜",
                            current_skill_type="Servant",
                        )
                        if sim.port.entity_exists("长夜"):
                            sim.port.despawn_spirit("长夜", reason="1141307 自毁离场")
                    else:
                        if changye_ent is None or getattr(changye_ent, "kit", None) is None:
                            return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
                        ctx = ActionContext(action_id="trajectory", actor_id="长夜", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=enemies, skill_id=1141301)
                        changye_ent.kit.execute(ctx)
                elif sid == 1140901:
                    if sim.get_entity("风堇") is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ())
                    ika_ent = sim.get_entity("小伊卡")
                    if ika_ent is None or float(getattr(ika_ent, "current_hp", 0.0)) <= 0.0:
                        ika_ent = rt.summon_servant("风堇", 11409)
                        patches.append("presence")
                        result.presence_grants += 1
                    if ika_ent is None or getattr(ika_ent, "kit", None) is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
                    ctx = ActionContext(action_id="trajectory", actor_id="小伊卡", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=enemies)
                    ika_ent.kit.execute(ctx)
                elif sid == 1151201:
                    ent = sim.get_entity("晴空乐手")
                    if ent is None or getattr(ent, "kit", None) is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "unforceable", ())
                    ctx = ActionContext(action_id="trajectory", actor_id="晴空乐手", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=enemies)
                    ent.kit.execute(ctx)
                else:
                    ent = sim.get_entity(cast.actor)
                    if ent is None or getattr(ent, "kit", None) is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "unforceable", ())
                    ctx = ActionContext(action_id="trajectory", actor_id=cast.actor, kind=ActionKind.MEMOSPRITE_SKILL, target_ids=enemies, skill_id=sid)
                    ent.kit.execute(ctx)
            elif sid in (1141301, 1141307):
                kit = _changye_kit()
                if kit is None:
                    return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ())
                if sim.get_entity("长夜") is None or not getattr(kit, "spirit_alive", False):
                    kit.summon_spirit()
                    patches.append("presence")
                    result.presence_grants += 1
                sim.cancel_immediate_action("长夜")
                changye_ent = sim.get_entity("长夜")
                if changye_ent is not None:
                    sim._turn_id += 1
                    sim.event_bus.publish(TurnBeginEvent(
                        av=round(sim.current_av, 2),
                        cycle=sim.current_cycle,
                        actor_id=changye_ent.name,
                        actor_name=changye_ent.name,
                        speed=round(changye_ent.speed, 1),
                        turn_id=sim._turn_id,
                    ))
                    sim.run_stage_turn_begin(changye_ent)
                if sid == 1141307:
                    if stash["amount"] > 0:
                        kit.yizhi = float(kit.yizhi) + stash["amount"]
                        patches.append(f"stash+{stash['amount']:.0f}")
                        stash["amount"] = 0.0
                    if float(getattr(kit, "yizhi", 0)) < 16:
                        deficit = 16 - float(kit.yizhi)
                        kit.yizhi = 16
                        patches.append(f"memoria+{deficit:.0f}")
                        result.memoria_granted += deficit
                    kit.trigger_spirit_burst()
                else:
                    kit._execute_memosprite_skill()
            elif sid == 1140901:
                fkit = _kit_of("风堇")
                if sim.get_entity("小伊卡") is None and fkit is not None:
                    fkit.summon_yika()
                    patches.append("presence")
                    result.presence_grants += 1
                ika_kit = _kit_of("小伊卡")
                if ika_kit is None:
                    return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
                ika_kit.cast_scatter()
            elif sid == 1151201:
                ent = sim.get_entity("晴空乐手")
                if ent is None or getattr(ent, "kit", None) is None:
                    return TrajectoryRecord(sid, cast.name, cast.av, None, "unforceable", ())
                ctx = ActionContext(action_id="trajectory", actor_id="晴空乐手", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(e.name for e in sim.entities if getattr(e, "is_enemy", False)))
                ent.kit.execute(ctx)
        except Exception:
            return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
        resolver = getattr(sim, "resolver", None)
        if resolver is not None:
            resolver.resolve_all()
        sim.port.publish_action(cast.actor, cast.name, ActionKind.MEMOSPRITE_SKILL, skill_id=sid)
        for idx in range(organic_before, len(organic)):
            if organic[idx][0] == sid:
                organic_used.add(idx)
        if director is not None:
            director.after_step()
        return TrajectoryRecord(sid, cast.name, cast.av, now_av, "forced", tuple(patches))

    def _clamp_memoria(now_av: float) -> None:
        q = spirit_queues.get(1141307)
        if not q:
            return
        if getattr(sim, "vm_runtime", None) is not None:
            if sim.get_entity("长夜月") is None:
                return
            cur_mem = _get_vm_memoria()
            if q[0].av - now_av > 10.0 and cur_mem > 15:
                excess = cur_mem - 15
                _set_vm_memoria(15.0)
                stash["amount"] += excess
            elif q[0].av - now_av <= 10.0 and stash["amount"] > 0:
                _set_vm_memoria(int(cur_mem + stash["amount"]))
                stash["amount"] = 0.0
            return
        kit = _changye_kit()
        if kit is None:
            return
        if q[0].av - now_av > 10.0 and float(getattr(kit, "yizhi", 0)) > 15:
            excess = float(kit.yizhi) - 15
            kit.yizhi = 15
            stash["amount"] += excess
        elif q[0].av - now_av <= 10.0 and stash["amount"] > 0:
            kit.yizhi = int(float(kit.yizhi) + stash["amount"])
            stash["amount"] = 0.0
            if hasattr(kit, "_check_threshold"):
                kit._check_threshold()

    def _master_blocked(cast: TrajectoryCast, now_av: float) -> bool:
        if cast.order < 0 or now_av > cast.av + 15.0:
            return False
        for j in master_indices:
            if j >= cast.order:
                break
            if j not in fired_master and timeline[j].av <= cast.av + 0.5:
                return True
        for other_q in spirit_queues.values():
            if other_q and other_q[0].order < cast.order and abs(other_q[0].av - cast.av) <= 0.5:
                return True
        if cast.skill_id in (1141301, 1141307) and getattr(director, "_pending_transition_sprouts", False):
            return True
        return False

    defer_counts: Dict[Tuple[str, int, float, int], int] = {}

    def _has_zero_av_pending() -> bool:
        if getattr(sim, "_ready_queue", ()):
            return True
        peek = sim.peek_next_actor() if hasattr(sim, "peek_next_actor") else None
        return peek is not None and float(getattr(peek, "distance_remaining", 1e9)) <= 1e-6

    def _musician_due() -> bool:
        ent = sim.get_entity("晴空乐手")
        if ent is None:
            return False
        if ent.name in getattr(sim, "_ready_queue", ()):
            return True
        if float(getattr(ent, "distance_remaining", 1e9)) <= 5.0:
            return True
        peek = sim.peek_next_actor() if hasattr(sim, "peek_next_actor") else None
        return peek is ent

    def _changye_due(sid: int = 1141307) -> bool:
        ent = sim.get_entity("长夜")
        if ent is None:
            return False
        if sid == 1141307:
            if getattr(sim, "vm_runtime", None) is not None:
                if _get_vm_memoria() + 4 < 16:
                    return False
            else:
                kit = _changye_kit()
                if kit is None or float(getattr(kit, "yizhi", 0)) + 4 < 16:
                    return False
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

    def _enforce_spirits() -> None:
        now_av = float(getattr(sim, "current_av", 0.0))
        _clamp_memoria(now_av)
        _match_organic_spirits()
        for sid, q in spirit_queues.items():
            while q and q[0].av <= now_av and not _master_blocked(q[0], now_av):
                zero_key = ("zero_av", sid, q[0].av, q[0].order)
                if _has_zero_av_pending() and defer_counts.get(zero_key, 0) < 16:
                    defer_counts[zero_key] = defer_counts.get(zero_key, 0) + 1
                    break
                due_key = ("due", sid, q[0].av, q[0].order)
                if (
                    (sid == 1151201 and _musician_due())
                    or (sid in (1141301, 1141307) and _changye_due(sid))
                ) and defer_counts.get(due_key, 0) < 1:
                    defer_counts[due_key] = defer_counts.get(due_key, 0) + 1
                    break
                cast = q.popleft()
                result.records.append(_force_spirit(cast, now_av))

    def _ult_blocked(u_idx: int, u_item: Any, now_av: float, *, allow_cur_enemy: bool = False) -> bool:
        if now_av > u_item.av + 15.0:
            return False
        cur_turn = getattr(sim, "current_turn_entity", None)
        u_owner = getattr(u_item, "turn_owner", "")
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
        if u_owner and u_owner not in _sim_player_actors(sim) and abs(now_av - u_item.av) <= 0.5:
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
        mq = spirit_queues.get(1151201)
        if mq and mq[0].order < u_idx and abs(mq[0].av - u_item.av) <= 0.5 and _musician_due():
            return True
        for sid in (1141301, 1141307):
            cq = spirit_queues.get(sid)
            if cq and cq[0].order < u_idx and abs(cq[0].av - u_item.av) <= 0.5 and _changye_due(sid):
                return True
        return False

    def _fire_due_ults(*, allow_cur_enemy: bool = False) -> None:
        now_av = float(getattr(sim, "current_av", 0.0))
        while ult_queue and ult_queue[0][1].av <= now_av + 1e-4 and not _ult_blocked(ult_queue[0][0], ult_queue[0][1], now_av, allow_cur_enemy=allow_cur_enemy):
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
            ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
            for e in list(getattr(sim, "entities", ())):
                kit = getattr(e, "kit", None)
                if kit is not None and getattr(kit, "_pending_volley", False) and hasattr(kit, "_flush_zone_window"):
                    kit._flush_zone_window()
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
                    and act_name == "缇宝"
                )
                or (
                    getattr(actor_ent, "is_enemy", False)
                    and bool(getattr(ult_queue[0][1], "turn_owner", ""))
                    and (
                        act_name.replace("_", "") == getattr(ult_queue[0][1], "turn_owner", "").replace("_", "")
                        if getattr(ult_queue[0][1], "turn_owner", "")[-1:].isdigit()
                        else act_name.startswith(getattr(ult_queue[0][1], "turn_owner", ""))
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
                ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
                for e in list(getattr(sim, "entities", ())):
                    kit = getattr(e, "kit", None)
                    if kit is not None and getattr(kit, "_pending_volley", False) and hasattr(kit, "_flush_zone_window"):
                        kit._flush_zone_window()
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

    sim.pre_turn_end_hook = _pre_turn_end_hook
    sim.turn_action_completed_hook = _on_turn_action_completed

    actor_queues = defaultdict(deque)
    for idx, i in enumerate(timeline):
        if i.kind in ("basic", "skill"):
            actor_queues[i.actor].append((idx, i))
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
        if actor_ent is not None and actor_ent.name == "长夜" and getattr(director, "_pending_transition_sprouts", False):
            boss_ent = sim.get_entity("堕神之血•亚婆离")
            if boss_ent is not None:
                if "堕神之血•亚婆离" in getattr(sim, "_ready_queue", ()):
                    sim._ready_queue.remove("堕神之血•亚婆离")
                sim._ready_queue.insert(0, "长夜")
                sim._current_turn_entity = boss_ent
                actor_ent = boss_ent
        if director is not None:
            director.after_step()

        def _ult_ready_before_enemy_step() -> bool:
            if (
                actor_ent is None
                or not getattr(actor_ent, "is_enemy", False)
                or not getattr(actor_ent, "is_boss", False)
                or not ult_queue
            ):
                return False
            u_item = ult_queue[0][1]
            if u_item.av > float(getattr(sim, "current_av", 0.0)) + 1e-4:
                return False
            u_ent = sim.get_entity(u_item.actor)
            return u_ent is not None and float(u_ent.energy) >= float(u_ent.max_energy) - 1e-6

        def _on_sub_action_end() -> None:
            if not ult_queue:
                return
            u_item = ult_queue[0][1]
            if not getattr(u_item, "between_enemy_sub_actions", False):
                cur_t = getattr(sim, "current_turn_entity", None)
                u_ow = getattr(u_item, "turn_owner", "")
                if not (
                    cur_t is not None
                    and getattr(cur_t, "is_enemy", False)
                    and u_ow
                    and (
                        getattr(cur_t, "name", "").replace("_", "") == u_ow.replace("_", "")
                        if u_ow[-1:].isdigit()
                        else getattr(cur_t, "name", "").startswith(u_ow)
                    )
                ):
                    return
            if u_item.av > float(getattr(sim, "current_av", 0.0)) + 1e-4:
                return
            u_ent = sim.get_entity(u_item.actor)
            if u_ent is not None and float(u_ent.energy) >= float(u_ent.max_energy) - 1e-6:
                _fire_due_ults(allow_cur_enemy=True)

        sim.on_enemy_sub_action_end = _on_sub_action_end
        _pre_boss_ult = _ult_ready_before_enemy_step()
        if (
            float(getattr(sim, "current_av", 0.0)) < 1e-4
            or (
                actor_ent is not None
                and not getattr(actor_ent, "is_enemy", False)
                and ult_queue
                and getattr(ult_queue[0][1], "turn_owner", "") == actor_ent.name
            )
            or _pre_boss_ult
        ):
            _fire_due_ults(allow_cur_enemy=_pre_boss_ult)
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
            q = actor_queues.get(actor_ent.name)
            if q:
                _idx, head = q.popleft()
                fired_master.add(_idx)
                if head.kind == "skill":
                    sp = getattr(sim, "sp", None)
                    if sp is not None and not sp.can_consume(1):
                        deficit = 1 - int(sp.current_sp)
                        if deficit > 0:
                            sp.generate(deficit, head.actor, "轨迹回放强制补足", float(getattr(sim, "current_av", 0.0)))
                            result.sp_granted += deficit
                override = ActionKind.SKILL if head.kind == "skill" else ActionKind.BASIC
                uid_override_map = getattr(sim, "enemy_uid_map", None)
                h_uids = getattr(head, "target_uids", None)
                if uid_override_map and h_uids:
                    mapped_list = []
                    for u in h_uids:
                        if u not in uid_override_map:
                            continue
                        ename = uid_override_map[u]
                        ent = sim.get_entity(ename)
                        if ent is not None:
                            ename = ent.name
                        else:
                            m_eg = re.match(r"^(.+)_g(\d+)_(\d+)$", ename)
                            if m_eg:
                                alt = f"{m_eg.group(1)}_{(int(m_eg.group(2)) - 1) * 3 + int(m_eg.group(3))}"
                                ent_alt = sim.get_entity(alt)
                                if ent_alt is not None:
                                    ename = ent_alt.name
                        mapped_list.append(ename)
                    if mapped_list:
                        target_ids = tuple(mapped_list)
                if target_ids is None:
                    raw_tids = getattr(head, "target_ids", None)
                    if raw_tids:
                        mapped_raw = []
                        for tid in raw_tids:
                            ent = sim.get_entity(tid)
                            if ent is not None:
                                mapped_raw.append(ent.name)
                            else:
                                m_eg = re.match(r"^(.+)_g(\d+)_(\d+)$", tid)
                                if m_eg:
                                    alt = f"{m_eg.group(1)}_{(int(m_eg.group(2)) - 1) * 3 + int(m_eg.group(3))}"
                                    ent_alt = sim.get_entity(alt)
                                    if ent_alt is not None:
                                        mapped_raw.append(ent_alt.name)
                        if len(mapped_raw) == len(raw_tids):
                            target_ids = tuple(mapped_raw)
                replay.turn_matched += 1
        if actor_ent.name == "长夜":
            q01 = spirit_queues.get(1141301)
            q07 = spirit_queues.get(1141307)
            cur_av_now = float(getattr(sim, "current_av", 0.0))
            if q01 and q01[0].av <= cur_av_now + 0.05 and (not q07 or (q01[0].av, q01[0].order) < (q07[0].av, q07[0].order)):
                actor_ent._trajectory_skill_id = 1141301
        sim.step(action_override=override, target_ids=target_ids)
        if director is not None:
            director.after_step()
        _match_organic_spirits()
        _fire_due_ults()
        _enforce_spirits()

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
    now_av = float(getattr(sim, "current_av", 0.0))
    for sid, q in spirit_queues.items():
        while q and q[0].av <= av_budget:
            cast = q.popleft()
            result.records.append(_force_spirit(cast, now_av))
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

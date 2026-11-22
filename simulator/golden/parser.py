# coding: utf-8
"""Golden Trace 日志解析器、模拟器事件记录器与时间线/目标提取器。"""

from __future__ import annotations

import bisect
import collections
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from simulator.actions import ActionKind
from simulator.golden.models import (
    KNOWN_AVATAR_NAMES,
    SKILL_TYPE_BY_KIND,
    SPIRIT_TRAJECTORY_SKILLS,
    BattleSequence,
    DamageHit,
    Decision,
    SkillCast,
    TimelineItem,
    TrajectoryCast,
    TurnRecord,
    _DECISION_KIND_BY_TYPE,
    _golden_actor_display,
)


def parse_golden_jsonl(path: str) -> BattleSequence:
    """解析 Veritas 官方 JSONL, 归纳为标准时序。"""
    seq = BattleSequence(source=path)
    enemy_names: Dict[int, str] = {}
    sprout_cnt = 0
    current: Optional[TurnRecord] = None

    def open_turn(av: float, owner: str) -> TurnRecord:
        nonlocal current
        current = TurnRecord(index=len(seq.turns) + 1, av=av, owner=owner)
        seq.turns.append(current)
        return current

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            ev = entry.get("event")
            data = entry.get("data") or {}

            if ev == "OnInitializeEnemy":
                e = data.get("enemy") or {}
                uid = e.get("uid")
                if uid is not None:
                    ename = e.get("name", f"敌人#{uid}")
                    if ename == "狂兽的胚芽" and uid not in enemy_names:
                        sprout_cnt += 1
                        enemy_names[uid] = f"狂兽的胚芽{sprout_cnt}"
                    else:
                        enemy_names[uid] = ename
            elif ev == "OnTurnBegin":
                owner_ref = data.get("turn_owner")
                if owner_ref:
                    owner = _golden_actor_display(owner_ref.get("uid"), owner_ref.get("team", ""), enemy_names)
                else:
                    owner = "环境/插队"
                open_turn(float(data.get("action_value", 0.0)), owner)
            elif ev == "OnUseSkill":
                if current is None:
                    open_turn(0.0, "环境/插队")
                avatar = data.get("avatar") or {}
                skill = data.get("skill") or {}
                actor = _golden_actor_display(avatar.get("uid"), avatar.get("team", ""), enemy_names)
                current.skills.append(SkillCast(
                    actor=actor,
                    name=skill.get("name", ""),
                    skill_type=skill.get("type", "Unknown"),
                    config_id=skill.get("skill_config_id"),
                ))
            elif ev == "OnDamage":
                if current is None:
                    open_turn(0.0, "环境/插队")
                attacker = data.get("attacker") or {}
                actor = _golden_actor_display(attacker.get("uid"), attacker.get("team", ""), enemy_names)
                dmg_type = data.get("type", "")
                if attacker.get("team") == "Player" and dmg_type == "Servant":
                    actor = f"{actor} (忆灵)"
                current.damages.append(DamageHit(
                    attacker=actor,
                    damage_type=dmg_type,
                    damage=float(data.get("damage", 0.0)),
                ))
            elif ev == "OnBattleEnd":
                seq.final_av = float(data.get("action_value", 0.0))

    if not seq.final_av and seq.turns:
        seq.final_av = seq.turns[-1].av
    if seq.final_av:
        seq.turns = [t for t in seq.turns if t.av <= seq.final_av]
    seq.total_damage = sum(t.total_damage for t in seq.turns)
    seq.enemy_names = enemy_names
    return seq


class SequenceRecorder:
    """将一场模拟的事件流记录为与官方日志同构的标准时序 (自由运行与回放共用)。"""

    def __init__(self, sim: Any):
        from simulator.events import ActionExecuteEvent, DamageAppliedEvent, TurnBeginEvent, WeaknessBreakEvent

        self.sim = sim
        self.seq = BattleSequence(source="simulator")
        self.current: Optional[TurnRecord] = None
        self.raw_actions: List[Any] = []
        self._ent_cache: Dict[str, Any] = {}
        sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        sim.event_bus.subscribe(ActionExecuteEvent, self._on_action)
        sim.event_bus.subscribe(DamageAppliedEvent, self._on_damage)
        if getattr(sim, "record_break_damage", False):
            sim.event_bus.subscribe(WeaknessBreakEvent, self._on_break)

    def _lookup_entity(self, name: str):
        if name not in self._ent_cache:
            for ent in getattr(self.sim, "entities", []):
                self._ent_cache[ent.name] = ent
        return self._ent_cache.get(name)

    def _skill_actor(self, name: str) -> str:
        ent = self._lookup_entity(name)
        if ent is not None and getattr(ent, "is_memosprite", False):
            return getattr(ent, "master_name", None) or name
        return name

    def _damage_actor(self, name: str, dtype_value: str) -> str:
        ent = self._lookup_entity(name)
        if ent is not None and getattr(ent, "is_memosprite", False):
            master = getattr(ent, "master_name", None) or name
            return f"{master} (忆灵)"
        if dtype_value == "Servant":
            return f"{name} (忆灵)"
        return name

    def _open_turn(self, av: float, owner: str) -> TurnRecord:
        self.current = TurnRecord(index=len(self.seq.turns) + 1, av=av, owner=owner)
        self.seq.turns.append(self.current)
        return self.current

    def _on_turn_begin(self, e: Any) -> None:
        self._open_turn(float(getattr(e, "av", 0.0)), e.actor_name)

    def _ensure_turn(self, av: float, owner: str) -> TurnRecord:
        if self.current is None or abs(av - self.current.av) > 0.02:
            return self._open_turn(av, owner)
        return self.current

    def _on_action(self, e: Any) -> None:
        self.raw_actions.append(e)
        self._ensure_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        actor_ent = self._lookup_entity(e.actor_name)
        if actor_ent is not None and getattr(actor_ent, "is_countdown", False):
            return
        kind = getattr(e, "action_kind", None)
        raw_name = e.action_type or ""
        if raw_name == "FollowUpAttack" or kind == ActionKind.FOLLOW_UP:
            raw_name = ""
        elif raw_name.startswith("Ultimate (") and raw_name.endswith(")"):
            raw_name = raw_name[len("Ultimate ("):-1]
        self.current.skills.append(SkillCast(
            actor=self._skill_actor(e.actor_name),
            name=raw_name,
            skill_type=SKILL_TYPE_BY_KIND.get(kind, "Unknown"),
            config_id=(getattr(e, "skill_config_id", 0) or None),
        ))

    def _is_enemy_actor(self, name: str) -> bool:
        ent = self._lookup_entity(name)
        return bool(ent is not None and getattr(ent, "is_enemy", False))

    def _on_damage(self, e: Any) -> None:
        if self._is_enemy_actor(e.attacker_name):
            return
        self._ensure_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        dtype = getattr(e, "damage_type", None)
        dtype_value = getattr(dtype, "value", "Direct")
        self.current.damages.append(DamageHit(
            attacker=self._damage_actor(e.attacker_name, dtype_value),
            damage_type=dtype_value,
            damage=float(e.damage),
        ))

    def _on_break(self, e: Any) -> None:
        if self._is_enemy_actor(e.breaker_name):
            return
        self._ensure_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        self.current.damages.append(DamageHit(
            attacker=self._skill_actor(e.breaker_name),
            damage_type="Break",
            damage=float(e.break_damage),
        ))

    def finish(self) -> BattleSequence:
        self.seq.total_damage = sum(t.total_damage for t in self.seq.turns)
        self.seq.final_av = float(getattr(self.sim, "current_av", 0.0))
        return self.seq


def export_sim_sequence(sim: Any, av_budget: float, max_turns: int = 400, director: Any = None) -> BattleSequence:
    """自由运行一场模拟战斗并导出标准时序 (sim 须为已构造完毕的 TurnSimulator)。"""
    recorder = SequenceRecorder(sim)
    seq = recorder.seq
    steps = 0
    idle_steps = 0
    while steps < max_turns * 4 and len(seq.turns) <= max_turns:
        actor = sim.step()
        if director is not None:
            director.after_step()
        steps += 1
        if actor is None:
            idle_steps += 1
            if idle_steps > 100:
                break
        else:
            idle_steps = 0
        if float(getattr(sim, "current_av", 0.0)) > av_budget:
            break
    return recorder.finish()


def extract_decisions(path: str) -> List[Decision]:
    """从官方 JSONL 提取玩家决策脚本 (按日志顺序)。"""
    decisions: List[Decision] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("event") != "OnUseSkill":
                continue
            data = entry.get("data") or {}
            avatar = data.get("avatar") or {}
            skill = data.get("skill") or {}
            if avatar.get("team") != "Player":
                continue
            actor = KNOWN_AVATAR_NAMES.get(avatar.get("uid"))
            kind = _DECISION_KIND_BY_TYPE.get(skill.get("type"))
            if actor and kind:
                decisions.append(Decision(
                    actor=actor,
                    kind=kind,
                    skill_id=int(skill.get("skill_config_id") or 0),
                    name=skill.get("name", ""),
                ))
    return decisions


def extract_enemy_activity(path: str) -> Dict[str, Any]:
    """从 OnStatChange 提取敌方行动与受击回能 (签名法)。"""
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    owner_at = []
    turn_starts = []
    cur = (None, None)
    for i, e in enumerate(events):
        if e.get("event") == "OnTurnBegin":
            o = e.get("data", {}).get("turn_owner") or {}
            cur = (o.get("team"), o.get("uid"))
            turn_starts.append(i)
        owner_at.append(cur)

    enemy_turns = collections.Counter()
    for i, e in enumerate(events):
        if e.get("event") == "OnTurnBegin":
            o = e.get("data", {}).get("turn_owner") or {}
            if o.get("team") == "Enemy":
                enemy_turns[o.get("uid")] += 1

    sp_series = collections.defaultdict(list)
    for i, e in enumerate(events):
        if e.get("event") == "OnStatChange":
            ent = e.get("data", {}).get("entity") or {}
            prop = e.get("data", {}).get("property") or {}
            if ent.get("team") == "Player" and prop.get("type") == "CurrentSP":
                sp_series[ent.get("uid")].append((i, float(prop.get("value") or 0.0)))

    hit_energy = {}
    targets_per_turn = collections.defaultdict(set)
    for uid, series in sp_series.items():
        prev = 0.0
        count = 0
        total = 0.0
        for i, v in series:
            d = v - prev
            prev = v
            if 3.5 <= d <= 17.0 and i < len(owner_at) and owner_at[i][0] == "Enemy":
                count += 1
                total += d
                t = bisect.bisect_right(turn_starts, i) - 1
                targets_per_turn[t].add(uid)
        if count:
            hit_energy[uid] = {"count": count, "total": round(total, 1)}

    wide_actions = sum(1 for s in targets_per_turn.values() if len(s) >= 3)
    return {
        "enemy_turns": dict(enemy_turns),
        "enemy_turn_total": sum(enemy_turns.values()),
        "hit_energy": hit_energy,
        "hit_energy_total_count": sum(v["count"] for v in hit_energy.values()),
        "hit_energy_total": round(sum(v["total"] for v in hit_energy.values()), 1),
        "wide_actions": wide_actions,
    }


def extract_trajectory(path: str) -> List[TrajectoryCast]:
    """从官方日志提取忆灵技施放轨迹 (AV 来自回合记录, 按 AV 排序)。"""
    seq = parse_golden_jsonl(path)
    out: List[TrajectoryCast] = []
    for t in seq.turns:
        for s in t.skills:
            if s.config_id in SPIRIT_TRAJECTORY_SKILLS:
                out.append(TrajectoryCast(av=float(t.av), actor=SPIRIT_TRAJECTORY_SKILLS[s.config_id], skill_id=s.config_id, name=s.name))
    out.sort(key=lambda c: c.av)
    return out


def extract_player_target_plan(path: str) -> List[Tuple[int, Tuple[str, ...], Tuple[int, ...]]]:
    """从官方日志提取玩家本体技能目标序列 (按 Normal/BPSkill/Ultra 出现顺序)。"""
    with open(path, "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]

    stage_id = 0
    initial_enemy_uids: List[int] = []
    seen_init_uids: Set[int] = set()
    saw_first_init_enemy = False
    spawn_events_raw: List[Tuple[int, str]] = []
    for e in events:
        ev = e.get("event")
        data = e.get("data") or {}
        if ev == "OnBattleBegin":
            stage_id = int(data.get("stage_id") or 0)
        elif ev == "OnInitializeEnemy":
            saw_first_init_enemy = True
            en = data.get("enemy") or {}
            uid = int(en.get("uid") or 0)
            name = str(en.get("name") or "")
            if uid and name:
                spawn_events_raw.append((uid, name))
        elif ev == "OnStatChange" and not saw_first_init_enemy:
            ent = data.get("entity") or {}
            if ent.get("team") == "Enemy":
                uid = int(ent.get("uid") or 0)
                if uid and uid not in seen_init_uids:
                    seen_init_uids.add(uid)
                    initial_enemy_uids.append(uid)

    uid_map: Dict[int, str] = {}
    wave0_names: List[str] = []
    summon_names: Set[str] = set()
    if stage_id > 0:
        try:
            from simulator.vm.stage_data_loader import StageDataLoader

            stage_spec = StageDataLoader().load_stage(stage_id)
            if stage_spec.waves:
                wave0_names = [m.name for m in stage_spec.waves[0].monsters]
            summon_names = {m.name for m in stage_spec.summon_monsters.values()}
        except Exception:
            pass

    if wave0_names and initial_enemy_uids:
        name_totals: Dict[str, int] = {}
        for nm in wave0_names:
            name_totals[nm] = name_totals.get(nm, 0) + 1
        seen_init_cnt: Dict[str, int] = {}
        for euid, nm in zip(sorted(initial_enemy_uids), wave0_names):
            if name_totals[nm] > 1:
                seen_init_cnt[nm] = seen_init_cnt.get(nm, 0) + 1
                uid_map[euid] = f"{nm}_{seen_init_cnt[nm]}"
            else:
                uid_map[euid] = nm

    raw_totals: Dict[str, int] = {}
    for _, ename in spawn_events_raw:
        raw_totals[ename] = raw_totals.get(ename, 0) + 1
    spawn_seq: Dict[str, int] = {}
    for euid, ename in spawn_events_raw:
        if ename in summon_names or raw_totals[ename] > 1:
            spawn_seq[ename] = spawn_seq.get(ename, 0) + 1
            uid_map[euid] = f"{ename}_{spawn_seq[ename]}"
        else:
            uid_map[euid] = ename

    def uid_to_name(uid):
        return uid_map.get(uid)

    player_skill_targets = []
    for i, e in enumerate(events):
        if e.get("event") == "OnUseSkill":
            d = e.get("data", {})
            av = d.get("avatar", {})
            s = d.get("skill", {})
            stype = s.get("type")
            if av.get("team") == "Player" and stype in ("Normal", "BPSkill", "Ultra"):
                sid = s.get("skill_config_id")
                if sid in SPIRIT_TRAJECTORY_SKILLS:
                    continue
                hit_uids = []
                if stype == "Ultra" and sid == 151203:
                    caster_uid = av.get("uid")
                    sp_fallback_uid = None
                    for j in range(i + 1, min(i + 25, len(events))):
                        ev2 = events[j]
                        if ev2.get("event") in ("OnUseSkill", "OnTurnBegin"):
                            break
                        if ev2.get("event") == "OnStatChange":
                            d2 = ev2.get("data", {})
                            ent = d2.get("entity", {})
                            prop = d2.get("property", {})
                            if ent.get("team") == "Player":
                                u = ent.get("uid")
                                if prop.get("type") == "ActionDelay" and u is not None:
                                    hit_uids.append(u)
                                    break
                                if (
                                    sp_fallback_uid is None
                                    and prop.get("type") == "CurrentSP"
                                    and u is not None
                                    and u != caster_uid
                                    and float(prop.get("value", 0.0)) > 0.0
                                ):
                                    sp_fallback_uid = u
                    if not hit_uids and sp_fallback_uid is not None:
                        hit_uids.append(sp_fallback_uid)
                    named_targets = tuple(KNOWN_AVATAR_NAMES[u] for u in hit_uids if u in KNOWN_AVATAR_NAMES)
                    player_skill_targets.append((sid, named_targets, tuple(hit_uids)))
                    continue
                for j in range(i + 1, min(i + 100, len(events))):
                    ev2 = events[j]
                    if ev2.get("event") in ("OnUseSkill", "OnTurnBegin"):
                        break
                    if ev2.get("event") == "OnStatChange":
                        d2 = ev2.get("data", {})
                        ent = d2.get("entity", {})
                        prop = d2.get("property", {})
                        if ent.get("team") == "Enemy" and prop.get("type") == "CurrentHP":
                            u = ent.get("uid")
                            if u not in hit_uids:
                                hit_uids.append(u)
                named_targets = tuple(uid_to_name(u) for u in hit_uids if uid_to_name(u) is not None)
                player_skill_targets.append((sid, named_targets, tuple(hit_uids)))
    return player_skill_targets


def extract_timeline(path: str) -> List[TimelineItem]:
    """从官方日志提取完整施放时间线 (本体决策 + 忆灵技, 含 AV, 按 AV 排序)。"""
    seq = parse_golden_jsonl(path)
    target_plan = extract_player_target_plan(path)
    # 通用检测：识别实机中插在敌方两动之间的抢断终结技
    between_sub_ults: Set[Tuple[float, int]] = set()
    try:
        with open(path, "r", encoding="utf-8") as _f:
            _cur_av = 0.0
            _cur_enemy_uid: Optional[int] = None
            _pending_ults: List[Tuple[float, int]] = []
            for _line in _f:
                if not _line.strip():
                    continue
                _ev = json.loads(_line)
                _et = _ev.get("event")
                _d = _ev.get("data") or {}
                if _et == "OnTurnBegin":
                    _cur_av = float(_d.get("action_value", _cur_av))
                    _ow = _d.get("turn_owner")
                    _cur_enemy_uid = int(_ow.get("uid")) if isinstance(_ow, dict) and _ow.get("team") == "Enemy" and _ow.get("uid") else None
                    _pending_ults = []
                elif _cur_enemy_uid is not None:
                    if _et == "OnUseSkill":
                        _av_ent = _d.get("avatar") or {}
                        _sk = _d.get("skill") or {}
                        if _av_ent.get("team") == "Player" and _sk.get("type") == "Ultra":
                            _pending_ults.append((round(_cur_av, 2), int(_sk.get("skill_config_id") or 0)))
                    elif _pending_ults and _et == "OnInitializeEnemy":
                        between_sub_ults.update(_pending_ults)
                        _pending_ults = []
                    elif _pending_ults and _et == "OnStatChange":
                        _ent = _d.get("entity") or {}
                        _prop = _d.get("property") or {}
                        if _ent.get("team") == "Enemy" and _ent.get("uid") == _cur_enemy_uid and _prop.get("type") == "CurrentSP" and float(_prop.get("value", -1.0)) == 0.0:
                            between_sub_ults.update(_pending_ults)
                            _pending_ults = []
    except Exception:
        pass
    target_idx = 0
    items: List[TimelineItem] = []
    for turn_seq, t in enumerate(seq.turns):
        for s in t.skills:
            if s.config_id in SPIRIT_TRAJECTORY_SKILLS:
                items.append(TimelineItem(float(t.av), "spirit", SPIRIT_TRAJECTORY_SKILLS[s.config_id], s.config_id, s.name, turn_owner=t.owner, turn_seq=turn_seq))
            elif s.actor in KNOWN_AVATAR_NAMES.values():
                kind = _DECISION_KIND_BY_TYPE.get(s.skill_type)
                if kind:
                    t_ids = None
                    t_uids = None
                    if target_idx < len(target_plan):
                        match_idx = target_idx
                        if target_plan[match_idx][0] != s.config_id:
                            for k in range(target_idx + 1, min(target_idx + 6, len(target_plan))):
                                if target_plan[k][0] == s.config_id:
                                    match_idx = k
                                    break
                        p_sid, p_targets, p_uids = target_plan[match_idx]
                        if p_sid == s.config_id:
                            if kind == "basic" or (kind == "ult" and s.config_id == 151203):
                                if p_targets:
                                    t_ids = p_targets
                                if p_uids:
                                    t_uids = p_uids
                            target_idx = match_idx + 1
                    is_between = (kind == "ult" and (round(float(t.av), 2), int(s.config_id)) in between_sub_ults)
                    items.append(TimelineItem(float(t.av), kind, s.actor, s.config_id, s.name, target_ids=t_ids, turn_owner=t.owner, turn_seq=turn_seq, target_uids=t_uids, between_enemy_sub_actions=is_between))
    items.sort(key=lambda x: x.av)
    return items


def extract_enemy_target_plan(path: str) -> List[Dict[str, Any]]:
    """从官方日志提取确定性敌方行动目标序列 (供轨迹对账 TraceTargetProvider 使用)。"""
    with open(path, "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]

    uid_to_name = KNOWN_AVATAR_NAMES
    plan = []
    cur_turn = None
    last_hp: Dict[int, float] = {}
    current_sp: Dict[int, float] = {}
    sp_at_turn_start: Dict[int, float] = {}
    turn_hp_lost: Set[int] = set()
    for e in events:
        ev = e.get("event")
        data = e.get("data", {})
        if ev == "OnTurnBegin":
            owner = data.get("turn_owner")
            if isinstance(owner, dict) and owner.get("team") == "Enemy":
                cur_turn = {
                    "av": float(data.get("action_value", 0.0)),
                    "enemy_uid": owner.get("uid"),
                    "targets": [],
                    "sub_targets": [],
                    "sub_hp_targets": [],
                    "closed": False,
                }
                plan.append(cur_turn)
                sp_at_turn_start = dict(current_sp)
                turn_hp_lost = set()
            else:
                cur_turn = None
        elif cur_turn is not None and not cur_turn["closed"] and ev == "OnUseSkill":
            avatar = data.get("avatar") or {}
            if avatar.get("team") == "Player":
                cur_turn["closed"] = True
        elif ev == "OnStatChange":
            ent = data.get("entity", {})
            prop = data.get("property", {})
            ptype = prop.get("type")
            val = float(prop.get("value", 0.0) or 0.0)
            uid = ent.get("uid")
            if ent.get("team") == "Player" and ptype == "CurrentHP":
                prev_hp = last_hp.get(uid, val)
                if val > 400.0:
                    last_hp[uid] = val
                if (
                    cur_turn is not None
                    and not cur_turn["closed"]
                    and val > 400.0
                    and val < prev_hp - 100.0
                ):
                    pname = uid_to_name.get(uid)
                    if pname:
                        turn_hp_lost.add(uid)
                        if not cur_turn["sub_hp_targets"]:
                            cur_turn["sub_hp_targets"].append([])
                        cur_turn["sub_hp_targets"][-1].append(pname)
            elif (
                cur_turn is not None
                and not cur_turn["closed"]
                and ent.get("team") == "Enemy"
                and uid == cur_turn["enemy_uid"]
                and ptype == "CurrentSP"
                and val == 0.0
            ):
                cur_turn["sub_targets"].append([])
                cur_turn["sub_hp_targets"].append([])
            elif ent.get("team") == "Player" and ptype == "CurrentSP":
                current_sp[uid] = val
                pname = uid_to_name.get(uid)
                sp_start = sp_at_turn_start.get(uid)
                is_static_residual = (sp_start is not None and abs(val - sp_start) < 1e-4)

                if cur_turn is not None and not cur_turn["closed"] and pname and 0 < val <= 30.0:
                    if is_static_residual and uid not in turn_hp_lost:
                        if cur_turn["av"] < 100.0:
                            actual_target = "小伊卡"
                        else:
                            actual_target = pname
                    else:
                        actual_target = pname

                    cur_turn["targets"].append(actual_target)
                    if not cur_turn["sub_targets"]:
                        cur_turn["sub_targets"].append([])
                    if actual_target not in cur_turn["sub_targets"][-1] or cur_turn["enemy_uid"] in (100009, 100013):
                        cur_turn["sub_targets"][-1].append(actual_target)
    for p in plan:
        if not p["targets"] and p["sub_hp_targets"]:
            for sub in p["sub_hp_targets"]:
                for t in sub:
                    if t not in p["targets"]:
                        p["targets"].append(t)
        for i in range(len(p["sub_targets"])):
            if not p["sub_targets"][i] and i < len(p["sub_hp_targets"]):
                p["sub_targets"][i] = list(dict.fromkeys(p["sub_hp_targets"][i]))
    return plan

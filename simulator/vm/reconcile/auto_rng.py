# coding: utf-8
"""全自动 RNG 先知插件挂载器（敌方受击/扩散目标、忆灵差额反推、阿哈弹射、风行再动）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from simulator.vm.reconcile.models import (
    AmbiguousMemospriteSlot,
    EnemyHitRecord,
    InferredMemospriteHit,
    LogMetadata,
    SKIP_SENTINEL,
)


def _is_memosprite(ent: Any) -> bool:
    return bool(getattr(ent, "is_memosprite", False))


def attach_auto_rng_plugin(
    sim: Any,
    meta: LogMetadata,
    *,
    memosprite_overrides: Optional[Dict[Tuple[float, int, str], Tuple[str, ...]]] = None,
    aha_dmg_overrides: Optional[Dict[Tuple[int, str], float]] = None,
    ambiguous_out: Optional[List[AmbiguousMemospriteSlot]] = None,
    inferred_out: Optional[List[InferredMemospriteHit]] = None,
) -> None:
    """挂载全自动 RNG 先知（敌方 UID 映射、辅助拉条、风行再动、阿哈弹射、差额忆灵反推与跳过回合判别）。"""
    overrides = memosprite_overrides or {}
    aha_overrides = aha_dmg_overrides or {}

    # 1. 自动设置 enemy_uid_map
    if meta.enemy_uid_map:
        sim.enemy_uid_map = dict(meta.enemy_uid_map)

    # 2. 自动风行再动判定（流星铁鹰）
    windwalk_names: Set[str] = {meta.enemy_uid_map[u] for u in meta.windwalk_enemy_uids if u in meta.enemy_uid_map}

    def _enemy_windwalk_provider(eagle_name: str, generation: int, idx: int) -> bool:
        return eagle_name in windwalk_names

    sim.enemy_windwalk_provider = _enemy_windwalk_provider

    # 3. 敌方非攻击/跳过回合判定（自动从无掉血/无回能/无被动奶的敌方回合提取 + 二次确认锁定的 SKIP_SENTINEL）
    skip_av_names: Set[Tuple[float, str]] = set()
    for h in meta.enemy_hits:
        ename = meta.enemy_uid_map.get(h.enemy_uid, "")
        if ename and not h.had_hp_drop and not h.sp_gain_counts and not h.had_passive_heal:
            skip_av_names.add((h.av, ename))
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
                    # 直接按实机日志记录的敌方扣血总量施加（与 emit_plugin 保持完全一致，零硬编码单段值）
                    dmg_by_enemy: Dict[str, float] = {}
                    lethal_names: Set[str] = {
                        meta.enemy_uid_map.get(u, str(u)) for u in rec.lethal_enemy_uids
                    }
                    for euid, dmg in rec.enemy_damages:
                        ename = meta.enemy_uid_map.get(euid)
                        if not ename:
                            continue
                        dmg_by_enemy[ename] = dmg_by_enemy.get(ename, 0.0) + float(dmg)

                    for ename, tot_d in dmg_by_enemy.items():
                        if (idx, ename) in aha_overrides:
                            tot_d = aha_overrides[(idx, ename)]
                        eff_d = (tot_d + 10000.0) if ename in lethal_names else tot_d
                        if hasattr(director, "apply_aha_hp_damage"):
                            director.apply_aha_hp_damage(ename, eff_d)
                    for owner, sp_cnt in rec.ally_sp_gain_counts.items():
                        hp_cnt = rec.ally_chip_hits.count(owner)
                        extra_memo_chips = max(0, sp_cnt - hp_cnt)
                        for _ in range(extra_memo_chips):
                            living_memos = [
                                e for e in getattr(sim, "entities", ())
                                if getattr(e, "is_memosprite", False)
                                and getattr(e, "current_hp", 0.0) > 0
                            ]
                            m_ent = next(
                                (
                                    e for e in living_memos
                                    if owner in (
                                        getattr(e, "master_name", None),
                                        getattr(e, "summoner_name", None),
                                        getattr(e, "owner_name", None),
                                    )
                                ),
                                living_memos[0] if len(living_memos) == 1 else None,
                            )
                            if m_ent is not None and hasattr(director, "apply_aha_ally_chip_hit"):
                                director.apply_aha_ally_chip_hit(m_ent.name)
                    for aname in rec.ally_chip_hits:
                        if hasattr(director, "apply_aha_ally_chip_hit"):
                            director.apply_aha_ally_chip_hit(aname)
                    if hasattr(director, "flush_ally_talent_heals"):
                        director.flush_ally_talent_heals()

        sim.aha_special_handler = _auto_aha_handler
        sim.aha_interrupt_avs = [a.av for a in meta.aha_turns]

    # 5. 受击目标 & 扩散目标（含差额反推 + 被动奶 O(1) + 辅助单点目标）
    recs_by_av: Dict[float, List[EnemyHitRecord]] = {}
    for rec in meta.enemy_hits:
        recs_by_av.setdefault(rec.av, []).append(rec)

    cursor_by_av: Dict[Any, int] = {}
    active_rec_by_av: Dict[Any, EnemyHitRecord] = {}
    active_turn_seq_by_key: Dict[Any, int] = {}
    sub_hit_offset_by_key: Dict[Any, int] = {}
    turn_seq = [0]
    from simulator.events import BattleEvent as _BE, TurnBeginEvent as _TBE

    def _on_turn_begin_seq(ev: _BE) -> None:
        if isinstance(ev, _TBE):
            turn_seq[0] += 1

    sim.event_bus.subscribe(_BE, _on_turn_begin_seq)
    ally_ult_cursor: Dict[str, int] = {}
    servant_cursor: Dict[Tuple[float, str], int] = {}
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

        if rec.first_memo_owner:
            for m in memos:
                if rec.first_memo_owner in (
                    getattr(m, "master_name", None),
                    getattr(m, "summoner_name", None),
                    getattr(m, "owner_name", None),
                ):
                    _record_inf(rec.av, rec.enemy_uid, kind, (m.name,), "passive_heal_o1")
                    return m

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
            # 忆灵技：日志里施法者 UID 是召唤师本体，需按 master_name 归属并沿施放顺序消费游标
            if getattr(attacker, "is_memosprite", False):
                master_name = str(getattr(attacker, "master_name", "") or "")
                for (p_av, p_name), seq in meta.servant_targets.items():
                    if p_name == master_name and abs(p_av - key_av) <= 0.05 and seq:
                        idx = servant_cursor.get((p_av, p_name), 0)
                        servant_cursor[(p_av, p_name)] = idx + 1
                        if idx >= len(seq) or seq[idx] is None:
                            return None
                        target_ename = seq[idx]
                        found = _find_ally(living, target_ename)
                        if found is not None:
                            return found
                return None
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
        name_matched = [r for r in recs if meta.enemy_uid_map.get(r.enemy_uid, "") == att_name]
        pool = name_matched if name_matched else recs
        cursor_key = (av_key, att_name) if name_matched else av_key
        if hit_idx == 0:
            if (
                active_turn_seq_by_key.get(cursor_key) == turn_seq[0]
                and cursor_key in active_rec_by_av
            ):
                # 同一敌方回合内的第 2 动（OneMorePerTurn）：复用本回合 EnemyHitRecord，推进子目标偏移
                rec = active_rec_by_av[cursor_key]
                sub_hit_offset_by_key[cursor_key] = sub_hit_offset_by_key.get(cursor_key, 0) + 1
            else:
                idx = min(cursor_by_av.get(cursor_key, 0), len(pool) - 1)
                rec = pool[idx]
                cursor_by_av[cursor_key] = cursor_by_av.get(cursor_key, 0) + 1
                active_rec_by_av[cursor_key] = rec
                active_rec_by_av[av_key] = rec
                active_turn_seq_by_key[cursor_key] = turn_seq[0]
                sub_hit_offset_by_key[cursor_key] = 0
        else:
            rec = active_rec_by_av.get(cursor_key) or active_rec_by_av.get(av_key) or pool[min(max(0, cursor_by_av.get(cursor_key, 1) - 1), len(pool) - 1)]

        eff_hit_idx = hit_idx + sub_hit_offset_by_key.get(cursor_key, 0)
        if eff_hit_idx == 0 and rec.first_memo_owner:
            m_first = next(
                (
                    e for e in living
                    if _is_memosprite(e)
                    and rec.first_memo_owner in (
                        getattr(e, "master_name", None),
                        getattr(e, "summoner_name", None),
                        getattr(e, "owner_name", None),
                    )
                ),
                None,
            )
            if m_first is not None:
                _record_inf(rec.av, rec.enemy_uid, "primary", (m_first.name,), "passive_heal_o1")
                return m_first

        hit_seq: List[str] = []
        for nm in rec.hit_allies:
            hit_seq.extend([nm] * max(1, rec.hit_counts.get(nm, 1)))

        seq_idx = eff_hit_idx - 1 if (rec.first_memo_owner and eff_hit_idx > 0) else eff_hit_idx
        if 0 <= seq_idx < len(hit_seq):
            return _find_ally(living, hit_seq[seq_idx])

        if hit_idx == 0 and not rec.had_hp_drop and rec.sp_gain_counts:
            memo_owner = next(iter(rec.sp_gain_counts.keys()))
            m_sp = next(
                (
                    e for e in living
                    if _is_memosprite(e)
                    and memo_owner in (
                        getattr(e, "master_name", None),
                        getattr(e, "summoner_name", None),
                        getattr(e, "owner_name", None),
                    )
                ),
                None,
            )
            if m_sp is not None:
                _record_inf(rec.av, rec.enemy_uid, "primary", (m_sp.name,), "sp_gain_o1")
                return m_sp

        memos = _living_memosprites(living)
        if memos:
            kind = "primary" if hit_idx == 0 else "bounce"
            return _pick_memosprite_by_passive_signal(rec, memos, kind)

        if rec.hit_allies:
            return _find_ally(living, rec.hit_allies[0])
        return None

    def _blast_provider(attacker: Any, primary: Any, living: List[Any]) -> List[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        att_name = str(getattr(attacker, "name", "") or "")
        av_key = _match_av_key(av)
        if av_key is None:
            return []
        recs = recs_by_av[av_key]
        name_matched = [r for r in recs if meta.enemy_uid_map.get(r.enemy_uid, "") == att_name]
        cursor_key = (av_key, att_name) if name_matched else av_key
        pool = name_matched if name_matched else recs
        rec = active_rec_by_av.get(cursor_key) or active_rec_by_av.get(av_key) or pool[min(max(0, cursor_by_av.get(cursor_key, 1) - 1), len(pool) - 1)]

        extra_chars = (
            list(rec.hit_allies)
            if rec.first_memo_owner
            else (rec.hit_allies[1:] if len(rec.hit_allies) > 1 else [])
        )
        known_blasts: List[Any] = []
        for nm in extra_chars:
            ent = _find_ally(living, nm)
            if ent is not None and ent is not primary and ent not in known_blasts:
                known_blasts.append(ent)

        memos = _living_memosprites(living)
        if not memos:
            return known_blasts

        ov_key = (rec.av, rec.enemy_uid, "blast")
        if ov_key in overrides:
            extra_names = overrides[ov_key]
            out = list(known_blasts)
            matched_any = False
            for mname in extra_names:
                ment = _find_ally(memos, mname)
                if ment is not None and ment not in out and ment is not primary:
                    out.append(ment)
                    matched_any = True
            if not extra_names or matched_any:
                if extra_names:
                    _record_inf(rec.av, rec.enemy_uid, "blast", extra_names, "second_pass_confirmed")
                return out

        if rec.sp_gain_counts:
            if rec.first_memo_owner:
                sp_memo_owners = [
                    ow for ow, sp_c in rec.sp_gain_counts.items()
                    if ow != rec.first_memo_owner and (
                        (ow in rec.hit_allies and sp_c >= 2 * rec.hit_counts.get(ow, 0) > 0)
                        or (ow not in rec.hit_allies and sp_c > 0)
                    )
                ]
            else:
                sp_memo_owners = [
                    ow for ow, sp_c in rec.sp_gain_counts.items()
                    if (ow in rec.hit_allies and sp_c >= 2 * rec.hit_counts.get(ow, 0) > 0)
                    or (rec.had_hp_drop and rec.hit_allies and ow not in rec.hit_allies and sp_c > 0)
                ]
            if sp_memo_owners:
                sp_extra: List[Any] = []
                for ow in sp_memo_owners:
                    for m in memos:
                        if (
                            ow in (
                                getattr(m, "master_name", None),
                                getattr(m, "summoner_name", None),
                                getattr(m, "owner_name", None),
                            )
                            and m is not primary
                            and m not in known_blasts
                            and m not in sp_extra
                        ):
                            sp_extra.append(m)
                if sp_extra:
                    _record_inf(rec.av, rec.enemy_uid, "blast", tuple(m.name for m in sp_extra), "blast_adjacent")
                    return known_blasts + sp_extra
            if rec.first_memo_owner:
                return known_blasts

        if len(known_blasts) >= 2:
            return known_blasts

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

    team_uid_map: Dict[int, str] = {
        uid: name.split("_", 1)[0]
        for uid, name in zip(meta.team_uids, meta.team_names)
    }

    def _enemy_retarget_provider(caster: Any, candidates: List[Any]) -> Optional[Any]:
        av = float(getattr(sim, "current_av", 0.0))
        cname = getattr(caster, "name", "")
        for p_av, c_uid, v_uid in meta.enemy_retarget_picks:
            expected_cname = meta.enemy_uid_map.get(c_uid) or team_uid_map.get(c_uid, "")
            if abs(av - p_av) < 0.05 and expected_cname == cname:
                vname = meta.enemy_uid_map.get(v_uid, "")
                for ent in candidates:
                    if getattr(ent, "name", "") == vname:
                        return ent
        return None

    used_spawn_indices: Set[int] = set()

    def _summon_id_provider(av: float, default_mid: int, candidate_ids: Sequence[int]) -> Optional[int]:
        if not meta.enemy_spawns or not candidate_ids:
            return None
        for idx, (sp_av, sp_id, _sp_name) in enumerate(meta.enemy_spawns):
            if idx in used_spawn_indices:
                continue
            if abs(sp_av - av) <= 0.15:
                # 匹配候选召唤池中的 monster_id 或 template_id
                if sp_id in candidate_ids:
                    used_spawn_indices.add(idx)
                    return sp_id
                for cid in candidate_ids:
                    if str(cid).startswith(str(sp_id)):
                        used_spawn_indices.add(idx)
                        return cid
        return None

    sim.target_provider = _target_provider
    sim.blast_target_provider = _blast_provider
    sim.enemy_retarget_provider = _enemy_retarget_provider
    sim.summon_id_provider = _summon_id_provider

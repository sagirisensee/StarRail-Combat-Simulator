# coding: utf-8
"""从战斗日志提取元数据的无状态后处理纯函数与数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from simulator.db.character_db import CharacterDB
from simulator.vm.reconcile.models import (
    AhaTurnRecord,
    _get_avatar_damage_types,
    _get_avatar_skill_effects,
    _get_avatar_skill_stance_pairs,
    _get_avatar_skill_stances,
    _get_servant_skill_effects,
    _resolve_uid_name,
)
from simulator.vm.stage_data_loader import StageDataLoader


@dataclass
class PlayerAttackRecord:
    """流式阶段采集的单次玩家/忆灵技能命中明细。"""

    atk_key: Tuple[float, str]
    is_servant: bool
    skill_id: int
    skill_type: str
    primary_dmg_hits: int
    hit_euids: List[int]
    dmg_confirmed_euids: List[int]
    hit_dmgs: Dict[int, float]
    sp_euids: List[int]


def base_enemy_name(uid: int, enemy_uid_map: Mapping[int, str]) -> str:
    """从 UID 映射表中去掉 `_2`/`_3` 同名编号后缀，返回怪物基础名称。"""
    nm = enemy_uid_map.get(uid, "")
    if "_" in nm and nm.rsplit("_", 1)[1].isdigit():
        return nm.rsplit("_", 1)[0]
    return nm


def _servant_primary_euid(hit_euids: Sequence[int]) -> Optional[int]:
    """单体忆灵技主目标：仅在官方技能表为 SingleAttack 且全段命中同一个敌方时提取。"""
    ordered: List[int] = []
    for u in hit_euids:
        if u not in ordered:
            ordered.append(u)
    if len(ordered) == 1:
        return ordered[0]
    return None


def build_enemy_uid_map(
    stage_id: int,
    initial_enemy_uids: Sequence[int],
    spawn_events_raw: Sequence[Tuple[int, str]],
) -> Tuple[Dict[int, str], Optional[Any], List[int]]:
    """基于官方 StageDataLoader 通用映射任意关卡的初始敌方与召唤物 UID（零关卡硬编码）。"""
    spawn_euids = {u for u, _ in spawn_events_raw}
    filtered_init_uids = [u for u in initial_enemy_uids if u not in spawn_euids]

    enemy_uid_map: Dict[int, str] = {}
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
    if is_infinite_stage and stage_spec is not None and stage_spec.waves and filtered_init_uids:
        w0_monsters = stage_spec.waves[0].monsters
        sorted_init = sorted(filtered_init_uids)
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
        init_names = [m.name for m in w0_monsters if m.monster_id != 8003060][: len(formation_init_uids)]
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
        if wave0_names and filtered_init_uids:
            sorted_init = sorted(filtered_init_uids)
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
                for euid, nm in zip(sorted_init[len(wave0_names) :], w0_summon_names):
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

    return enemy_uid_map, stage_spec, filtered_init_uids


def reconstruct_shielded_aha_damages(
    aha_turns: Sequence[AhaTurnRecord],
    enemy_uid_map: Mapping[int, str],
) -> None:
    """对阿哈回合被特殊护盾全额吸收（delta_hp <= 1.0）的命中段按同回合比例或历史观测值插值修复。"""
    pairwise_ratios: Dict[Tuple[str, str], List[float]] = {}
    for a in aha_turns:
        by_base: Dict[str, List[float]] = {}
        for u, d in a.enemy_damages:
            if d > 1.0:
                bn = base_enemy_name(u, enemy_uid_map)
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
                bn = base_enemy_name(u, enemy_uid_map)
                if bn:
                    global_unshielded_by_base.setdefault(bn, []).append(d)
                all_unshielded_hits.append(d)
    global_med_by_base = {bn: sorted(ds)[len(ds) // 2] for bn, ds in global_unshielded_by_base.items()}
    global_any_med = sorted(all_unshielded_hits)[len(all_unshielded_hits) // 2] if all_unshielded_hits else 0.0

    last_unshielded_by_base: Dict[str, float] = {}
    for a in aha_turns:
        pos_items = [(u, d) for u, d in a.enemy_damages if d > 1.0]
        new_dmgs: List[Tuple[int, float]] = []
        for u, d in a.enemy_damages:
            if d <= 1.0:
                a.shielded_enemy_uids.add(u)
            if d > 1.0:
                new_dmgs.append((u, d))
                bn = base_enemy_name(u, enemy_uid_map)
                if bn:
                    last_unshielded_by_base[bn] = d
            elif pos_items:
                bn = base_enemy_name(u, enemy_uid_map)
                est_list: List[float] = []
                for u_ref, d_ref in pos_items:
                    b_ref = base_enemy_name(u_ref, enemy_uid_map)
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
            else:
                bn = base_enemy_name(u, enemy_uid_map)
                est = last_unshielded_by_base.get(bn, 0.0)
                if est <= 1.0:
                    g_est = global_med_by_base.get(bn, global_any_med)
                    est = g_est if g_est > 1.0 else 0.0
                new_dmgs.append((u, est))
        a.enemy_damages = new_dmgs


def resolve_player_and_servant_targets(
    pending_records: Sequence[PlayerAttackRecord],
    enemy_uid_map: Mapping[int, str],
    stage_spec: Optional[Any],
) -> Tuple[Dict[Tuple[float, str], List[str]], Dict[Tuple[float, str], List[Optional[str]]]]:
    """根据技能受击记录与官方技能表解析玩家与忆灵的主目标序列。"""
    servant_skill_effects = _get_servant_skill_effects()
    avatar_skill_effects = _get_avatar_skill_effects()

    non_formation_euids: Set[int] = set()
    if stage_spec is not None and stage_spec.waves:
        nf_names = {m.name for w in stage_spec.waves for m in w.monsters if m.monster_id == 8003060}
        if nf_names:
            non_formation_euids = {u for u, nm in enemy_uid_map.items() if nm in nf_names}

    player_enemy_targets_raw: Dict[Tuple[float, str], List[int]] = {}
    servant_targets_raw: Dict[Tuple[float, str], List[Optional[int]]] = {}
    for rec in pending_records:
        p_atk = rec.atk_key
        p_hit_euids = [u for u in rec.hit_euids if u not in non_formation_euids] if non_formation_euids else rec.hit_euids
        p_dmg_confirmed = (
            [u for u in rec.dmg_confirmed_euids if u not in non_formation_euids]
            if non_formation_euids
            else rec.dmg_confirmed_euids
        )
        p_hit_dmgs = (
            {u: d for u, d in rec.hit_dmgs.items() if u not in non_formation_euids}
            if non_formation_euids
            else rec.hit_dmgs
        )
        p_sp_euids = [u for u in rec.sp_euids if u not in non_formation_euids] if non_formation_euids else rec.sp_euids

        if rec.is_servant:
            sk_eff = servant_skill_effects.get(rec.skill_id, "")
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
                servant_euid = _servant_primary_euid(p_dmg_confirmed if p_dmg_confirmed else p_hit_euids)
                if servant_euid is not None:
                    servant_targets_raw.setdefault(p_atk, []).append(servant_euid)
        elif p_dmg_confirmed or p_hit_euids:
            av_eff = avatar_skill_effects.get(rec.skill_id, "")
            if rec.skill_type not in ("Ultra", "ElationDamage"):
                if av_eff in ("SingleAttack", "") and (
                    rec.primary_dmg_hits == 1
                    or (
                        (p_atk[1].startswith("UID_") or p_atk[1].startswith("BattleEvent_"))
                        and rec.primary_dmg_hits == 0
                        and len(set(p_hit_euids)) == 1
                    )
                ):
                    pri_euid = p_dmg_confirmed[0] if p_dmg_confirmed else p_hit_euids[0]
                    player_enemy_targets_raw.setdefault(p_atk, []).append(pri_euid)
                elif av_eff == "Blast":
                    inferred_pri: Optional[int] = None
                    if len(p_sp_euids) == 1:
                        inferred_pri = p_sp_euids[0]
                    elif len(p_dmg_confirmed) == 1:
                        inferred_pri = p_dmg_confirmed[0]
                    elif len(p_hit_dmgs) >= 2:
                        sorted_dmgs = sorted(p_hit_dmgs.items(), key=lambda kv: kv[1], reverse=True)
                        if sorted_dmgs[1][1] > 0.0 and sorted_dmgs[0][1] > sorted_dmgs[1][1] * 1.4:
                            inferred_pri = sorted_dmgs[0][0]
                    elif len(set(p_hit_euids)) == 1:
                        inferred_pri = p_hit_euids[0]
                    if inferred_pri is not None:
                        player_enemy_targets_raw.setdefault(p_atk, []).append(inferred_pri)

    player_enemy_targets: Dict[Tuple[float, str], List[str]] = {}
    for k_pt, euids in player_enemy_targets_raw.items():
        names = [enemy_uid_map[u] for u in euids if u in enemy_uid_map]
        if names:
            player_enemy_targets[k_pt] = names

    servant_targets: Dict[Tuple[float, str], List[Optional[str]]] = {}
    for k_pt, euids in servant_targets_raw.items():
        seq: List[Optional[str]] = [(enemy_uid_map.get(u) if u is not None else None) for u in euids]
        while seq and seq[-1] is None:
            seq.pop()
        if any(x is not None for x in seq):
            servant_targets[k_pt] = seq

    return player_enemy_targets, servant_targets


def resolve_team_roster(
    char_db: CharacterDB,
    seen_uids: Sequence[int],
    inferred_slot_uids: Sequence[int],
    aoe_heal_slot_uids: Sequence[int],
    robin_s_init_ad: float,
    team_override: Optional[Sequence[str]],
) -> Tuple[List[int], List[str]]:
    """按站位规则或 team_override 解析参战队伍 UID 与角色名称列表。"""
    if team_override:
        team_names = list(team_override)
        team_uids: List[int] = []
        for n in team_names:
            rp = char_db.get_by_name(n)
            if rp is None and "_" in n:
                rp = char_db.get_by_name(n.split("_", 1)[0])
            team_uids.append(int(rp.avatar_id) if rp is not None else 0)
        return team_uids, team_names

    valid_uids = [u for u in seen_uids if char_db.get(u) is not None]
    eff_slot_uids = list(inferred_slot_uids)
    if len(aoe_heal_slot_uids) >= 2 and not eff_slot_uids:
        eff_slot_uids = list(aoe_heal_slot_uids)
    if eff_slot_uids:
        ordered = [u for u in eff_slot_uids if u in valid_uids]
        ordered.extend(u for u in valid_uids if u not in ordered)
        valid_uids = ordered

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
    return team_uids, team_names


def _has_prebattle_non_stance_damage_maze(ldr: Any, uid: int, *, enhanced: bool = False) -> bool:
    """检查指定角色的 SkillMaze 是否含 ByIsMazeSkillAffectCurrentWave 且无削韧直接造成 DamageByAttackProperty。"""
    av = ldr.get_avatar_config(int(uid), enhanced=enhanced)
    if not av or not av.get("JsonPath"):
        return False
    cfg = ldr._read_json(av["JsonPath"])
    maze_abs: List[str] = []
    for item in cfg.get("SkillAbilityList") or ():
        if isinstance(item, Mapping) and item.get("Skill") == "SkillMaze":
            maze_abs.extend(str(a) for a in (item.get("AbilityList") or ()) if a)
    if not maze_abs:
        return False
    ldr.ensure_ability_index()
    has_wave_pred = False
    has_non_stance_dmg = False

    def _walk(node: Any) -> None:
        nonlocal has_wave_pred, has_non_stance_dmg
        if isinstance(node, Mapping):
            nt = node.get("$type")
            if nt == "RPG.GameCore.ByIsMazeSkillAffectCurrentWave":
                has_wave_pred = True
            elif nt == "RPG.GameCore.DamageByAttackProperty":
                ap = node.get("AttackProperty") or {}
                sv = ap.get("StanceValue") if isinstance(ap, Mapping) else None
                if sv is None or (
                    isinstance(sv, Mapping)
                    and not sv.get("IsDynamic")
                    and float((sv.get("FixedValue") or {}).get("Value", 0.0) or 0.0) == 0.0
                ):
                    has_non_stance_dmg = True
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for ab_name in maze_abs:
        ab = ldr.get_ability(ab_name)
        if ab:
            _walk(ab)
    return has_wave_pred and has_non_stance_dmg


def infer_entry_technique_stance(
    stage_spec: Optional[Any],
    enemy_uid_map: Mapping[int, str],
    initial_enemy_uids: Sequence[int],
    first_skill_info: Optional[Tuple[int, int]],
    first_skill_stance_obs: Mapping[int, float],
    init_enemy_first_stance: Mapping[int, Tuple[int, int, float, int]],
    skill_atk_dmgs: Mapping[int, Mapping[int, float]],
    *,
    team_uids: Sequence[int] = (),
    init_enemy_first_hp: Mapping[int, float] = (),
    init_enemy_first_dmg: Mapping[int, float] = (),
    enhanced_avatars: Optional[Set[int]] = None,
) -> Tuple[Optional[str], float]:
    """根据开局首轮削韧差值自动反推入战秘技属性与削韧量。"""
    entry_element: Optional[str] = None
    entry_toughness: float = 10.0
    if stage_spec is None or not stage_spec.waves:
        return entry_element, entry_toughness

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
                base_nm = base_enemy_name(euid, enemy_uid_map)
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
            base_nm = base_enemy_name(euid, enemy_uid_map)
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

    if entry_element is None and init_enemy_first_hp and team_uids:
        init_euid_set = set(initial_enemy_uids)
        has_prebattle_hp_drop = False
        for euid, first_hp in init_enemy_first_hp.items():
            if init_euid_set and euid not in init_euid_set:
                continue
            base_nm = base_enemy_name(euid, enemy_uid_map)
            total_before_first = float(first_hp) + float(init_enemy_first_dmg.get(euid, 0.0))
            for m_spec in w0_by_name.get(base_nm, ()):
                if float(getattr(m_spec, "hp", 0.0) or 0.0) > 0.0 and total_before_first < float(m_spec.hp) - 10.0:
                    has_prebattle_hp_drop = True
                    break
            if has_prebattle_hp_drop:
                break
        if has_prebattle_hp_drop:
            from simulator.vm.loader import GameDataLoader

            ldr = GameDataLoader()
            for uid in team_uids:
                if _has_prebattle_non_stance_damage_maze(
                    ldr,
                    int(uid),
                    enhanced=bool(enhanced_avatars and int(uid) in enhanced_avatars),
                ):
                    elem = av_elems.get(int(uid))
                    if elem:
                        entry_element = elem
                        entry_toughness = 0.0
                        break

    return entry_element, entry_toughness

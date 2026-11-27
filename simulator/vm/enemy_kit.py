# coding: utf-8
"""纯数据驱动敌方技能组适配器（DataDrivenEnemyKit，从 stage_sim_adapter.py 拆分）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.core import Entity, TurnSimulator
from simulator.lifecycle import AbilityFrameSpec
from simulator.vm.enemy_port import (
    BaseEnemyCombatPortImpl,
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    EnemySubActionOutcome,
    STANDARD_ACTION_DISTANCE,
)
from simulator.vm.stage_ai import (
    AISkillActionSpec,
    CompiledMonsterAISpec,
    MonsterAIExecutor,
)
from simulator.vm.stage_runner import StageRunner


@dataclass
class _EnemyTurnSession:
    """敌方单个自然回合的分步子动作会话（由 TurnSimulator.TurnFrame 驱动）。"""

    sim: TurnSimulator
    attacker: Optional[Entity]
    rt: Any
    can_one_more: bool
    next_turn_one_more: bool
    action_idx: int = 0
    last_rt_om: bool = False
    pending_skills: List[AISkillActionSpec] = field(default_factory=list)


class DataDrivenEnemyKit(EnemyKit):
    """Pure data-driven ``EnemyKit`` backed by ``CompiledMonsterAISpec`` & ``StageRunner``."""

    supports_staged_sub_actions: bool = True

    def __init__(
        self,
        owner_id: str,
        port: BaseEnemyCombatPortImpl,
        ai_spec: CompiledMonsterAISpec,
        runner: StageRunner,
    ) -> None:
        super().__init__(owner_id=owner_id, port=port)
        self.enemy_port = port
        self.ai_spec = ai_spec
        self.ai_executor = MonsterAIExecutor(ai_spec)
        self.runner = runner
        self.executed_skills: List[str] = []
        self._turn_count: int = 0
        self._skill_usage_turn: Dict[str, int] = {}
        self._ai_selected_targets: Dict[str, Tuple[str, ...]] = {}
        mrs = self.runner.get_enemy_state(owner_id)
        self.has_one_more: bool = self._detect_one_more_per_turn(mrs)
        self._fast_action_provider_synced: bool = False
        self._pending_fast_action_target: Optional[str] = None
        self._monster_dyn_initialized: bool = False
        self._marked_target: Optional[str] = None

    def _detect_one_more_per_turn(self, mrs: Any) -> bool:
        """从内存加载的官方 ConfigAbility AST 检测怪物是否具备 OneMorePerTurn 机制。"""
        rank = str(getattr(mrs.blueprint, "rank", "") or "")
        if rank not in ("Elite", "LittleBoss", "Boss", "BigBoss"):
            return False
        _json_cfg = str(getattr(mrs.blueprint, "json_config_path", "") or "")
        game_loader = getattr(self.runner.factory, "game_loader", None)
        stage_loader = getattr(self.runner.factory, "stage_loader", None)
        if _json_cfg and game_loader is not None and stage_loader is not None:
            char_cfg = stage_loader._load_char_config(_json_cfg) or {}
            queue: List[str] = []
            for ab in getattr(mrs.blueprint, "ability_list", ()) or ():
                if ab:
                    queue.append(str(ab))
            for ab in char_cfg.get("AbilityList") or ():
                if ab:
                    queue.append(str(ab))
            for sk in char_cfg.get("SkillList") or ():
                if isinstance(sk, Mapping) and sk.get("EntryAbility"):
                    queue.append(str(sk["EntryAbility"]))
            for sb in char_cfg.get("SkillAbilityList") or ():
                if isinstance(sb, Mapping):
                    for ab in sb.get("AbilityList") or ():
                        if ab:
                            queue.append(str(ab))
            visited: set[str] = set()
            resolved_any = False

            def _scan_node(node: Any) -> bool:
                if node == "OneMorePerTurn":
                    return True
                if isinstance(node, Mapping):
                    nt = node.get("$type", "")
                    if nt == "RPG.GameCore.TriggerAbility":
                        an = node.get("AbilityName")
                        aval = an.get("Value") if isinstance(an, Mapping) else an
                        if aval and str(aval) not in visited:
                            queue.append(str(aval))
                    elif nt == "RPG.GameCore.TriggerParallelAbility":
                        for ent in node.get("ParallelAbilityList") or ():
                            if isinstance(ent, Mapping):
                                an = ent.get("AbilityName")
                                aval = an.get("Value") if isinstance(an, Mapping) else an
                                if aval and str(aval) not in visited:
                                    queue.append(str(aval))
                    return any(_scan_node(v) for v in node.values())
                if isinstance(node, list):
                    return any(_scan_node(item) for item in node)
                return False

            while queue:
                ab_name = queue.pop(0)
                if not ab_name or ab_name in visited:
                    continue
                visited.add(ab_name)
                ab_doc = game_loader.get_ability(ab_name)
                if not ab_doc:
                    continue
                resolved_any = True
                if _scan_node(ab_doc):
                    return True
            if resolved_any:
                return False
        if _json_cfg:
            return rank in ("Elite", "Boss", "BigBoss")
        return rank in ("Boss", "BigBoss")

    def _record_skill_usage(self, sim: TurnSimulator, sk_key: str) -> None:
        """记录本实体与全局同 SkillID 的技能冷却基准回合（对应官方 ByCompareSkillUsageLimit / _GlobalDelay）。"""
        if not sk_key:
            return
        self._skill_usage_turn[sk_key] = self._turn_count
        sk = self.ai_spec.skills_by_key.get(sk_key)
        sk_id = int(getattr(sk, "skill_id", 0) or 0) if sk is not None else 0
        usage_key: Any = sk_id if sk_id > 0 else (int(self.ai_spec.monster_template_id or 0), sk_key)
        global_usage = getattr(sim, "_global_skill_usage_turn", None)
        if not isinstance(global_usage, dict):
            global_usage = {}
            setattr(sim, "_global_skill_usage_turn", global_usage)
        global_usage[usage_key] = int(getattr(sim, "_turn_id", 0) or 0)

    def _grant_fast_action(self, rt: Any, target_name: str) -> None:
        """通过官方 MCommon_FastAction 状态授予目标单位立刻再动能力。"""
        if rt is not None and target_name and not rt.modifier_engine.has_modifier(target_name, "MCommon_FastAction"):
            rt.modifier_engine.add_modifier(
                owner_id=target_name,
                caster_id=self.owner_id,
                mod_name="MCommon_FastAction",
            )

    def _sync_external_fast_action_provider(self, sim: TurnSimulator, rt: Any) -> None:
        """消费回放插件注入的外部再动判定契约，并转换为官方 MCommon_FastAction。"""
        if self._fast_action_provider_synced:
            return
        self._fast_action_provider_synced = True
        wp = getattr(sim, "enemy_windwalk_provider", None)
        if not callable(wp):
            return
        gen, idx = 1, 0
        parts = self.owner_id.split("_")
        base_name = parts[0] if parts else self.owner_id
        if len(parts) >= 3 and parts[-2].startswith("g") and parts[-2][1:].isdigit() and parts[-1].isdigit():
            gen = int(parts[-2][1:])
            idx = int(parts[-1])
        elif len(parts) >= 2 and parts[-1].isdigit():
            idx = int(parts[-1])
        val = wp(self.owner_id, gen, idx)
        if not val and idx > 0:
            val = wp(f"{base_name}_g{gen}_{idx}", gen, idx)
        if val is True:
            self._grant_fast_action(rt, self.owner_id)
        elif isinstance(val, str) and val:
            self._pending_fast_action_target = val

    def sync_phase(self, phase: int) -> None:
        if self.ai_executor.phase != phase:
            self.ai_executor.set_phase(phase, reset_ai_flag=1)

    def intercept_incoming_damage(self, target_id: str, raw_damage: float, *, allow_overflow: bool = True) -> float:
        if target_id != self.owner_id or raw_damage <= 0.0:
            return raw_damage
        sim = getattr(self.enemy_port, "sim", None)
        rt = getattr(sim, "vm_runtime", None) if sim is not None else None
        if rt is not None:
            for mod in list(rt.modifier_engine.get_modifiers(self.owner_id)):
                if "SingleBlock" in mod.behavior_flags and float(getattr(mod, "single_block_cur", 0.0)) > 0.0:
                    cur_shld = float(getattr(mod, "single_block_cur", 0.0))
                    absorbed = min(cur_shld, raw_damage)
                    new_shld = max(0.0, cur_shld - raw_damage)
                    setattr(mod, "single_block_cur", new_shld)
                    mod.dynamic_values[-276442507] = new_shld
                    rt.modifier_engine.dispatch_event(
                        "OnSingleBlockChange",
                        owner_id=self.owner_id,
                        param_entity_id=self.owner_id,
                    )
                    overflow = (raw_damage - absorbed) if allow_overflow else 0.0
                    if new_shld <= 0.0:
                        owner_ent = sim.get_entity(self.owner_id) if sim is not None else None
                        if owner_ent is not None and overflow > 0.0:
                            try:
                                mrs_ov = self.runner.get_enemy_state(self.owner_id)
                                cur_hp_ov = float(mrs_ov.entity.current_hp)
                                max_hp_ov = float(mrs_ov.entity.max_hp)
                                if mrs_ov.lock_hp_ratio is not None and mrs_ov.lock_hp_ratio > 0.0:
                                    fl_ov = max_hp_ov * float(mrs_ov.lock_hp_ratio)
                                    if cur_hp_ov >= fl_ov - 1e-6 and cur_hp_ov - overflow < fl_ov:
                                        overflow = max(0.0, cur_hp_ov - fl_ov)
                                if mrs_ov.phase < mrs_ov.max_phase and cur_hp_ov - overflow <= 0.0:
                                    setattr(mrs_ov, "_limbo_pending", True)
                                    setattr(mrs_ov.entity, "_vm_limbo_pending", True)
                                    overflow = max(0.0, cur_hp_ov - 1.0)
                            except KeyError:
                                pass
                            owner_ent.current_hp = max(0.0, float(owner_ent.current_hp) - overflow)
                            setattr(owner_ent, "_single_block_break_overflow", overflow)
                        rt.modifier_engine.destroy_modifier(mod)
                        return 0.0
                    return overflow

        try:
            mrs = self.runner.get_enemy_state(self.owner_id)
        except KeyError:
            return raw_damage

        shared_map = getattr(rt, "hp_shared_groups", None) if rt is not None else None
        if shared_map and self.owner_id in shared_map and sim is not None:
            main_ent_sh = sim.get_entity(shared_map[self.owner_id])
            if main_ent_sh is not None and main_ent_sh is not mrs.entity and main_ent_sh.current_hp > 0.0:
                return raw_damage

        if getattr(mrs.entity, "_vm_phase_change_pending", False):
            return 0.0

        cur_hp = float(mrs.entity.current_hp)
        max_hp = float(mrs.entity.max_hp)
        if mrs.lock_hp_ratio is not None and mrs.lock_hp_ratio > 0.0:
            floor_hp = max_hp * float(mrs.lock_hp_ratio)
            if cur_hp >= floor_hp - 1e-6 and cur_hp - raw_damage < floor_hp:
                raw_damage = max(0.0, cur_hp - floor_hp)

        if mrs.phase < mrs.max_phase and cur_hp - raw_damage <= 0.0:
            setattr(mrs, "_limbo_pending", True)
            setattr(mrs.entity, "_vm_limbo_pending", True)
            raw_damage = max(0.0, cur_hp - 1.0)
        elif cur_hp - raw_damage <= 0.0 and rt is not None:
            rt.modifier_engine.dispatch_event(
                "OnBeforeMortallyWonded",
                owner_id=self.owner_id,
                param_entity_id=self.owner_id,
                change_value=float(raw_damage),
                param_flags=("IsHPChangeByDamage",),
            )

        locks = getattr(mrs.entity, "_locked_hp_thresholds", None)
        if isinstance(locks, dict) and locks:
            floor_hp = max(float(v) for v in locks.values())
            if cur_hp >= floor_hp - 1e-6 and cur_hp - raw_damage < floor_hp:
                raw_damage = max(0.0, cur_hp - floor_hp)
                if rt is not None:
                    rt.modifier_engine.dispatch_event(
                        "OnLockHPThresholdReached",
                        owner_id=self.owner_id,
                        param_entity_id=self.owner_id,
                    )

        return raw_damage

    def _select_targets(self, sim: TurnSimulator, selector: str) -> List[Entity]:
        allies = [
            e
            for e in sim.entities
            if not e.is_enemy
            and not getattr(e, "is_countdown", False)
            and not getattr(e, "is_unselectable", False)
            and e.current_hp > 0.0
        ]
        if not allies:
            return []
        if "All" in selector or "Team" in selector:
            return allies
        return [allies[0]]

    def _get_entry_ability_name(self, skill_key: str) -> Optional[str]:
        mrs = self.runner.get_enemy_state(self.owner_id)
        tpl_id = mrs.blueprint.monster_template_id
        trow = self.runner.factory.stage_loader.monster_templates.get(tpl_id, {})
        json_path = trow.get("JsonConfig", "")
        if not json_path:
            return None
        char_cfg = self.runner.factory.stage_loader._load_char_config(json_path)
        for sk_entry in char_cfg.get("SkillList", []):
            if sk_entry.get("Name") == skill_key:
                return sk_entry.get("EntryAbility")
        return None

    def _execute_ability_tasks(
        self, ability_name: str, visited: Optional[set[str]] = None
    ) -> None:
        if visited is None:
            visited = set()
        if ability_name in visited:
            return
        visited.add(ability_name)

        game_loader = getattr(self.runner.factory, "game_loader", None)
        if game_loader is None:
            from simulator.vm.loader import GameDataLoader

            game_loader = GameDataLoader()
            setattr(self.runner.factory, "game_loader", game_loader)
        ab = game_loader.get_ability(ability_name)
        if not ab:
            return
        sim = getattr(self.enemy_port, "sim", None)
        rt = getattr(sim, "vm_runtime", None) if sim is not None else None
        if rt is not None:
            self._ensure_monster_dynamic_values(rt)
            dyn_resolver = lambda h: rt.resolve_hash(self.owner_id, h, ability_name=ability_name)
        else:
            dyn_resolver = None
        def _run_stage_tasks(tasks: Sequence[Any]) -> None:
            for t in tasks:
                if not isinstance(t, Mapping):
                    continue
                tt = t.get("$type", "")
                if tt == "RPG.GameCore.TriggerAbility":
                    child_name = t.get("AbilityName", {}).get("Value")
                    if child_name and "Camera" not in child_name:
                        self._execute_ability_tasks(child_name, visited=visited)
                elif tt == "RPG.GameCore.PredicateTaskList":
                    pred = t.get("Predicate")
                    ok = True
                    if pred:
                        try:
                            ok = self.runner.eval_stage_predicate(
                                pred, caster_name=self.owner_id, dynamic_resolver=dyn_resolver
                            )
                        except NotImplementedError:
                            if rt is not None:
                                from simulator.vm.executor import ExecutionContext

                                p_ctx = ExecutionContext(
                                    runtime=rt,
                                    caster_id=self.owner_id,
                                    ability_name=ability_name,
                                    ability_target_ids=(self.owner_id,),
                                    modifier_owner_id=self.owner_id,
                                )
                                try:
                                    ok = rt.executor.eval_predicate(pred, p_ctx)
                                except NotImplementedError:
                                    ok = False
                            else:
                                ok = False
                    branch = t.get("SuccessTaskList", []) if ok else t.get("FailedTaskList", [])
                    _run_stage_tasks(branch or [])
                else:
                    self.runner.execute_stage_task(
                        t, caster_name=self.owner_id, dynamic_resolver=dyn_resolver
                    )

        _run_stage_tasks(ab.get("OnStart", []))

    def _ensure_monster_dynamic_values(self, rt: Any) -> None:
        """将官方怪物 CharacterConfig 中的 SkillParam DynamicValues 与 CustomValues 注入 VM 运行时，供敌方 AST 表达式求值。"""
        if self._monster_dyn_initialized:
            return
        self._monster_dyn_initialized = True
        mrs = self.runner.get_enemy_state(self.owner_id)
        for h_key, c_val in mrs.custom_values.items():
            if isinstance(c_val, (int, float)):
                rt.set_dynamic_value(self.owner_id, int(h_key), float(c_val))
        tpl_id = mrs.blueprint.monster_template_id
        trow = self.runner.factory.stage_loader.monster_templates.get(tpl_id, {})
        json_path = trow.get("JsonConfig", "")
        if not json_path:
            return
        char_cfg = self.runner.factory.stage_loader._load_char_config(json_path)
        custom_vals = char_cfg.get("CustomValues", {})
        if isinstance(custom_vals, Mapping):
            from simulator.vm.expr import dotnet_hash

            for ck, cv in custom_vals.items():
                if ck == "AIFlag" or not isinstance(cv, (int, float)):
                    continue
                h_ck = dotnet_hash(str(ck))
                if h_ck not in mrs.custom_values and str(ck) not in mrs.custom_values:
                    if rt.get_dynamic_value(self.owner_id, h_ck) == 0.0:
                        rt.set_dynamic_value(self.owner_id, h_ck, float(cv))
        floats = char_cfg.get("DynamicValues", {}).get("Floats", {})
        if not isinstance(floats, Mapping):
            return
        from simulator.vm.expr import dotnet_hash

        h_cp = dotnet_hash("ChangePhase")
        if mrs.max_phase > 1 and str(h_cp) in floats and rt.get_dynamic_value(self.owner_id, h_cp) == 0.0:
            rt.set_dynamic_value(self.owner_id, h_cp, 1.0)
        h_ic = dotnet_hash("InsertCheck")
        if (
            mrs.max_phase > 1
            and str(h_ic) in floats
            and "InsertCheck" not in custom_vals
            and h_ic not in mrs.custom_values
            and "InsertCheck" not in mrs.custom_values
            and rt.get_dynamic_value(self.owner_id, h_ic) == 0.0
        ):
            rt.set_dynamic_value(self.owner_id, h_ic, 1.0)
        for h_str, entry in floats.items():
            if not isinstance(entry, Mapping):
                continue
            ri = entry.get("ReadInfo") or {}
            if ri.get("Type") != "SkillParam":
                continue
            tkey = str(ri.get("TriggerKey", ""))
            idx = int(ri.get("Index", 0))
            sk_spec = mrs.blueprint.skills_by_key.get(tkey)
            if sk_spec is not None and 0 <= idx < len(sk_spec.effective_params):
                rt.set_dynamic_value(self.owner_id, int(h_str), float(sk_spec.effective_params[idx]))

    def _execute_vm_skill(
        self,
        entry_ab: str,
        sim: TurnSimulator,
        sk: Any,
        attacker: Any,
    ) -> Tuple[str, ...]:
        """统一通过官方 ConfigAbility VM 执行所有敌方技能（伤害/支援/扩散/群攻/动态倍率/吞噬），并统一上报三方命中审计。"""
        rt = getattr(sim, "vm_runtime", None)
        if rt is None or not entry_ab:
            return ()
        self._ensure_monster_dynamic_values(rt)
        ab = rt.loader.get_ability(entry_ab)
        if not ab:
            return ()

        def _living_allies_ordered() -> List[Any]:
            allies = [
                e
                for e in sim.entities
                if not e.is_enemy
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
                and e.current_hp > 0.0
            ]
            avatars = [e for e in allies if not getattr(e, "is_memosprite", False)]
            avatar_rank = {e.name: idx for idx, e in enumerate(avatars)}
            memos = [e for e in allies if getattr(e, "is_memosprite", False)]
            memos.sort(key=lambda m: avatar_rank.get(getattr(m, "master_name", "") or "", 99))
            return avatars + memos

        def _ab_uses_target(ab_doc: Mapping[str, Any], seen: set[str]) -> bool:
            import json as _json

            txt = _json.dumps(ab_doc, ensure_ascii=False)
            if "RPG.GameCore.DamageByAttackProperty" in txt:
                return True

            def _iter_triggered(node: Any) -> List[str]:
                out: List[str] = []
                if isinstance(node, Mapping):
                    if node.get("$type") == "RPG.GameCore.TriggerAbility":
                        cn = (node.get("AbilityName") or {}).get("Value", "")
                        if cn and "Camera" not in cn:
                            out.append(str(cn))
                    for v in node.values():
                        out.extend(_iter_triggered(v))
                elif isinstance(node, list):
                    for it in node:
                        out.extend(_iter_triggered(it))
                return out

            for cn in _iter_triggered(ab_doc.get("OnStart", [])):
                if cn not in seen:
                    seen.add(cn)
                    child = rt.loader.get_ability(cn)
                    if child and _ab_uses_target(child, seen):
                        return True
            return False

        tinfo = str((ab.get("TargetInfo") or {}).get("TargetType", ""))
        sk_key = str(getattr(sk, "skill_trigger_key", "") or "")
        ai_picked = self._ai_selected_targets.pop(sk_key, ())
        target_ids: Tuple[str, ...] = (self.owner_id,)
        living_allies = _living_allies_ordered()
        has_dmg = _ab_uses_target(ab, {entry_ab})
        ai_picked_alive = tuple(
            tid
            for tid in ai_picked
            if (ent := sim.get_entity(tid)) is not None and ent.current_hp > 0.0
        )

        if tinfo in ("Caster", "Self"):
            target_ids = (self.owner_id,)
        elif tinfo == "AllEnemy":
            if living_allies:
                target_ids = tuple(e.name for e in living_allies)
        elif tinfo == "FriendSelect":
            if ai_picked_alive:
                target_ids = (ai_picked_alive[0],)
            else:
                other_enemies = [
                    e
                    for e in sim.entities
                    if e.is_enemy
                    and not getattr(e, "is_countdown", False)
                    and e.current_hp > 0.0
                    and e.name != self.owner_id
                ]
                if other_enemies:
                    target_ids = (other_enemies[0].name,)
        elif tinfo == "SkillPointEntity":
            other_enemies = [
                e
                for e in sim.entities
                if e.is_enemy
                and not getattr(e, "is_countdown", False)
                and e.current_hp > 0.0
                and e.name != self.owner_id
            ]
            if other_enemies:
                other_enemies.sort(
                    key=lambda e: (1 if getattr(e, "is_boss", False) else 0, float(getattr(e, "max_hp", 0.0))),
                    reverse=True,
                )
                target_ids = (other_enemies[0].name,)
        elif tinfo in ("SkillTargetEntityList", "EnemySelect", ""):
            if (not has_dmg) and ai_picked_alive:
                target_ids = (ai_picked_alive[0],)
            elif has_dmg and living_allies:
                cand_allies = [e for e in living_allies if e.name in ai_picked_alive] if ai_picked_alive else []
                picked = (
                    [cand_allies[0]]
                    if cand_allies
                    else self._select_targets(sim, getattr(sk, "target_selector", "single"))
                )
                target_provider = getattr(sim, "target_provider", None)
                if callable(target_provider):
                    prev_is_blast = getattr(sim, "_current_enemy_skill_is_blast", False)
                    sim._current_enemy_skill_is_blast = bool(getattr(sk, "is_blast", False))
                    try:
                        chosen = target_provider(attacker, cand_allies or living_allies, 0)
                    finally:
                        sim._current_enemy_skill_is_blast = prev_is_blast
                    if chosen is not None and (not cand_allies or chosen in cand_allies):
                        picked = [chosen]
                diag_cb_t = getattr(sim, "timeline_diag_cb", None)
                if callable(diag_cb_t):
                    diag_cb_t(
                        "ETARG",
                        f"{self.owner_id} sk={sk.skill_trigger_key} picked={[p.name for p in picked]}",
                    )
                if picked:
                    target_ids = (picked[0].name,)

        sim._action_seq += 1
        sp_base = float(
            sk.sp_hit_base
            if float(getattr(sk, "sp_hit_base", 0.0) or 0.0) > 0.0
            else (getattr(attacker, "hit_energy", 5.0) or 5.0)
        )
        prev_sp_base = getattr(rt, "_current_enemy_sp_hit_base", 0.0)
        prev_has_dmg = getattr(rt, "_current_enemy_skill_has_damage", True)
        rt._current_enemy_sp_hit_base = sp_base
        rt._current_enemy_skill_has_damage = has_dmg

        hit_targets: List[str] = []
        hit_avatars: List[str] = []
        hit_sp_owners: List[str] = []
        hit_snaps: List[Any] = []
        try:
            with rt.lifecycle.capture_damage_targets(self.owner_id) as hit_snaps:
                rt.lifecycle.run_ability_frame(
                    AbilityFrameSpec(
                        caster_id=self.owner_id,
                        ability_name=entry_ab,
                        target_ids=target_ids,
                        skill_target_ids=target_ids,
                        skill_name=str(getattr(sk, "skill_trigger_key", "") or ""),
                        emit_before_skill=True,
                        before_skill_targets_as_attack=True,
                        end_being_attacked_on_exit=True,
                        emit_after_skill=True,
                        emit_settle_callback=True,
                    )
                )
        finally:
            rt._current_enemy_sp_hit_base = prev_sp_base
            rt._current_enemy_skill_has_damage = prev_has_dmg

        for snap in hit_snaps:
            if not snap.is_enemy and not snap.is_countdown:
                if snap.target_name not in hit_targets:
                    hit_targets.append(snap.target_name)
                if not snap.is_memosprite and snap.target_name not in hit_avatars:
                    hit_avatars.append(snap.target_name)
                sp_owner = (
                    (snap.master_name or snap.target_name)
                    if snap.is_memosprite
                    else snap.target_name
                )
                if sp_owner not in hit_sp_owners:
                    hit_sp_owners.append(sp_owner)

        skill_audit_cb = getattr(sim, "on_enemy_skill_resolved", None)
        if callable(skill_audit_cb) and (hit_avatars or hit_sp_owners):
            is_aoe = bool(getattr(sk, "is_aoe", False)) or tinfo == "AllEnemy"
            is_blast = (not is_aoe) and bool(getattr(sk, "is_blast", False))
            scope = "AllEnemy" if is_aoe else ("Blast" if is_blast else "Single")
            skill_audit_cb(
                av=round(float(getattr(sim, "current_av", 0.0)), 2),
                enemy_name=self.owner_id,
                skill_id=int(getattr(sk, "skill_id", 0) or 0),
                skill_key=str(getattr(sk, "skill_trigger_key", "") or ""),
                expected_scope=scope,
                expected_hits=tuple(sorted(hit_avatars)),
                sim_hits=tuple(sorted(hit_avatars)),
                sim_sp_owners=tuple(sorted(hit_sp_owners)),
            )

        return tuple(hit_targets)

    def begin_turn_session(self, ctx: EnemyActionContext) -> Optional[_EnemyTurnSession]:
        sim: TurnSimulator = self.port.sim
        self.runner.on_turn_begin(self.owner_id, current_av=sim.current_av)

        # Keep AI phase synchronized with StageRunner's MonsterRuntimeState
        mrs = self.runner.get_enemy_state(self.owner_id)
        if self.ai_executor.phase != mrs.phase:
            self.ai_executor.set_phase(mrs.phase, reset_ai_flag=1)

        self._turn_count += 1
        attacker = sim.get_entity(self.owner_id)
        rt = getattr(sim, "vm_runtime", None)
        self._sync_external_fast_action_provider(sim, rt)

        # 非攻击辅助回合（如赋予友方 MCommon_FastAction）：
        # 对具有 AIFlag 自切换能力或无任何伤害技能的纯辅助怪物，优先走官方 ConfigAI + ConfigAbility 分支
        has_dynamic_ai_flag = any(
            d.next_ai_flag is not None
            or (
                isinstance(d.root_task, Mapping)
                and any(
                    isinstance(t, Mapping)
                    and t.get("$type") == "RPG.GameCore.SetDynamicValueByAddValue"
                    for t in (d.root_task.get("TaskList") or ())
                )
            )
            for d in self.ai_executor.spec.decisions
        )
        has_any_damage_skill = any(
            (not sk.is_passive) and sk.damage_type is not None
            for sk in self.ai_executor.spec.skills_by_key.values()
        )
        skip_prov = getattr(sim, "enemy_attack_skip_provider", None)
        if (
            skip_prov is not None
            and attacker is not None
            and has_any_damage_skill
            and not has_dynamic_ai_flag
            and skip_prov(attacker, sim.current_av)
        ):
            if self._pending_fast_action_target:
                director = getattr(sim, "_stage_director", None)
                t_ent = (
                    director._resolve_enemy_target(self._pending_fast_action_target)
                    if director is not None and hasattr(director, "_resolve_enemy_target")
                    else sim.get_entity(self._pending_fast_action_target)
                )
                if t_ent is not None and t_ent.current_hp > 0.0:
                    self._grant_fast_action(rt, t_ent.name)
                self._pending_fast_action_target = None
            else:
                wp = getattr(sim, "enemy_windwalk_provider", None)
                if callable(wp):
                    for ally_e in sim.entities:
                        if not ally_e.is_enemy or ally_e.current_hp <= 0.0:
                            continue
                        if getattr(ally_e, "kit", None) is None:
                            continue
                        if wp(ally_e.name, 1, 0) is True:
                            self._grant_fast_action(rt, ally_e.name)
            for sup_sk in self.ai_executor.spec.skills_by_key.values():
                if (not sup_sk.is_passive) and sup_sk.damage_type is None and sup_sk.skill_trigger_key:
                    self._record_skill_usage(sim, sup_sk.skill_trigger_key)
            self.runner.on_turn_end(self.owner_id, current_av=sim.current_av)
            return None

        # 优先同步 VM 中的动态 AIFlag (如 Monster_W5_Fallen_00_AttackOrder 将 AIFlag 设为 2)
        if rt is not None:
            from simulator.vm.expr import dotnet_hash

            vm_flag = rt.get_dynamic_value(self.owner_id, dotnet_hash("AIFlag"))
            if vm_flag > 0:
                self.ai_executor.ai_flag = int(round(vm_flag))
            if rt.modifier_engine.has_modifier(self.owner_id, "OneMorePerTurn"):
                self.has_one_more = True

        # 官方 OneMorePerTurn 驱动机制:
        # 1. 怪物每回合基础 1 动；
        # 2. 若拥有 OneMorePerTurn 状态，则在该行动后可获得 1 次额外行动机会；
        # 3. 若技能执行中执行了 RemoveModifier("OneMorePerTurn")（如蓄力 Skill03），则失去额外行动机会；
        # 4. 若技能执行中执行了 AddModifier("OneMorePerTurn")（如终极技 Skill04），则为下次回合赋予额外行动额度。
        can_one_more = getattr(self, "has_one_more", False)
        return _EnemyTurnSession(
            sim=sim,
            attacker=attacker,
            rt=rt,
            can_one_more=can_one_more,
            next_turn_one_more=can_one_more,
        )

    def _resolve_select_ai_skill_target(
        self,
        task: Mapping[str, Any],
        ai_ctx: Any,
        rt: Any,
    ) -> None:
        sk_name = str(task.get("SkillName") or "")
        if not sk_name:
            return
        sim = rt.sim
        skill_tinfo = ""
        try:
            mrs = self.runner.get_enemy_state(self.owner_id)
            _json_cfg = str(getattr(mrs.blueprint, "json_config_path", "") or "")
            stage_loader = getattr(self.runner.factory, "stage_loader", None)
            if _json_cfg and stage_loader is not None:
                char_cfg = stage_loader._load_char_config(_json_cfg) or {}
                for sk_cfg in char_cfg.get("SkillList") or ():
                    if isinstance(sk_cfg, Mapping) and str(sk_cfg.get("Name") or "") == sk_name:
                        skill_tinfo = str(((sk_cfg.get("TargetInfo") or {}).get("TargetType")) or "")
                        break
        except KeyError:
            pass
        if "Friend" in skill_tinfo:
            candidates = [
                e.name
                for e in sim.entities
                if e.is_enemy
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
                and e.current_hp > 0.0
            ]
        else:
            candidates = [
                e.name
                for e in sim.entities
                if not e.is_enemy
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
                and e.current_hp > 0.0
            ]

        def _match_selector(cand_id: str, sel: Any) -> bool:
            if not isinstance(sel, Mapping):
                return True
            st = str(sel.get("$type") or "")
            inv = bool(sel.get("InverseResultFlag", False))
            matched = True
            if st == "RPG.GameCore.AIComposeSelector":
                subs = sel.get("SelectorList") or ()
                matched = all(_match_selector(cand_id, sub) for sub in subs)
            elif st == "RPG.GameCore.AITaskTargetTypeSelector":
                t_ids = rt.executor._resolve_targets(sel.get("TargetType"), ai_ctx)
                matched = cand_id in t_ids
            elif st == "RPG.GameCore.AIModifierNameSelector":
                mn = sel.get("ModifierName")
                mname = str(mn.get("Value") if isinstance(mn, Mapping) else (mn or ""))
                matched = bool(mname and rt.modifier_engine.has_modifier(cand_id, mname))
            return (not matched) if inv else matched

        selector = task.get("Selector")
        filtered = [cid for cid in candidates if _match_selector(cid, selector)]
        if filtered:
            self._ai_selected_targets[sk_name] = tuple(filtered)

    def execute_next_sub_action(
        self,
        session: _EnemyTurnSession,
        sub_action_index: int,
    ) -> Optional[EnemySubActionOutcome]:
        sim = session.sim
        attacker = session.attacker
        rt = session.rt

        while True:
            if not session.pending_skills:
                if session.action_idx >= 8:
                    return None
                has_runtime_one_more = (
                    rt is not None and rt.modifier_engine.has_modifier(self.owner_id, "OneMore")
                )
                if session.action_idx == 1 and not session.can_one_more and not has_runtime_one_more:
                    return None
                if session.action_idx >= 2 and not has_runtime_one_more:
                    return None
                session.action_idx += 1
                session.last_rt_om = has_runtime_one_more
                if (
                    session.action_idx >= 2
                    and rt is not None
                    and rt.modifier_engine.has_modifier(self.owner_id, "OneMore")
                ):
                    om_mods = rt.modifier_engine.get_modifiers(self.owner_id, "OneMore")
                    if (
                        session.action_idx == 2
                        and om_mods
                        and getattr(om_mods[0], "life_time", None) is not None
                        and om_mods[0].life_time >= 2
                    ):
                        om_mods[0].life_time -= 1
                    else:
                        rt.modifier_engine.remove_modifier(self.owner_id, "OneMore")

                if rt is not None:
                    from simulator.vm.expr import dotnet_hash
                    from simulator.vm.executor import ExecutionContext

                    vm_flag = rt.get_dynamic_value(self.owner_id, dotnet_hash("AIFlag"))
                    if vm_flag > 0:
                        self.ai_executor.ai_flag = int(round(vm_flag))
                    else:
                        rt.set_dynamic_value(self.owner_id, dotnet_hash("AIFlag"), float(self.ai_executor.ai_flag))
                    prev_ai_flag = self.ai_executor.ai_flag
                    eval_ctx = ExecutionContext(
                        runtime=rt,
                        caster_id=self.owner_id,
                        ability_name="",
                        ability_target_ids=(self.owner_id,),
                        modifier_owner_id=self.owner_id,
                    )
                    actions: Tuple[AISkillActionSpec, ...] = self.ai_executor.select_next_actions(
                        predicate_evaluator=lambda p: rt.executor.eval_predicate(p, eval_ctx)
                    )
                else:
                    actions = self.ai_executor.select_next_actions()
                if not actions:
                    return None
                if rt is not None:
                    from simulator.vm.expr import dotnet_hash

                    matched_dec = getattr(self.ai_executor, "last_matched_decision", None)
                    if matched_dec is not None and isinstance(matched_dec.root_task, Mapping):
                        from simulator.vm.executor import ExecutionContext

                        ai_ctx = ExecutionContext(
                            runtime=rt,
                            caster_id=self.owner_id,
                            ability_name="",
                            ability_target_ids=(self.owner_id,),
                            modifier_owner_id=self.owner_id,
                        )
                        root_type = str(matched_dec.root_task.get("$type", "") or "")
                        if root_type and root_type != "RPG.GameCore.SequenceConfig":
                            root_tasks = [matched_dec.root_task]
                        else:
                            root_tasks = matched_dec.root_task.get("TaskList", [])
                        has_dynamic_root = any(
                            isinstance(t, Mapping)
                            and t.get("$type")
                            in (
                                "RPG.GameCore.PredicateTaskList",
                                "RPG.GameCore.Retarget",
                                "RPG.GameCore.SetDynamicValueByAddValue",
                                "RPG.GameCore.SequenceConfig",
                            )
                            for t in root_tasks
                        )
                        if not has_dynamic_root:
                            rt.set_dynamic_value(self.owner_id, dotnet_hash("AIFlag"), float(self.ai_executor.ai_flag))
                            ai_tasks = [
                                t for t in root_tasks
                                if isinstance(t, Mapping)
                                and (
                                    t.get("$type") in ("RPG.GameCore.AddModifier", "RPG.GameCore.RemoveModifier")
                                    or (
                                        t.get("$type") in ("RPG.GameCore.DefineDynamicValue", "RPG.GameCore.SetDynamicValue")
                                        and (t.get("DynamicKey") or {}).get("Value") != "AIFlag"
                                    )
                                )
                            ]
                            if ai_tasks:
                                rt.executor.execute_tasks(ai_tasks, ai_ctx)
                            for t in root_tasks:
                                if isinstance(t, Mapping) and t.get("$type") == "RPG.GameCore.SelectAISkillTarget":
                                    self._resolve_select_ai_skill_target(t, ai_ctx, rt)
                        # 动态求值 ConfigAI RootTask 中的条件/目标重选与 AIFlag 自增，精确还原官方分支技能选择
                        if has_dynamic_root:
                            self.ai_executor.ai_flag = prev_ai_flag
                            rt.set_dynamic_value(self.owner_id, dotnet_hash("AIFlag"), float(prev_ai_flag))
                            resolved_skill_names: List[str] = []

                            def _resolve_ai_skills(nodes: Any) -> None:
                                if isinstance(nodes, list):
                                    for item in nodes:
                                        _resolve_ai_skills(item)
                                    return
                                if not isinstance(nodes, Mapping):
                                    return
                                nt = nodes.get("$type", "")
                                if nt == "RPG.GameCore.UseSkill" and nodes.get("SkillName"):
                                    resolved_skill_names.append(str(nodes["SkillName"]))
                                elif nt in ("RPG.GameCore.AddModifier", "RPG.GameCore.RemoveModifier"):
                                    rt.executor.execute_task(nodes, ai_ctx)
                                    mn = nodes.get("ModifierName")
                                    mval = mn.get("Value") if isinstance(mn, Mapping) else mn
                                    if mval == "OneMorePerTurn":
                                        if nt == "RPG.GameCore.RemoveModifier":
                                            session.can_one_more = False
                                            session.next_turn_one_more = False
                                        elif nt == "RPG.GameCore.AddModifier":
                                            session.next_turn_one_more = True
                                elif nt in ("RPG.GameCore.DefineDynamicValue", "RPG.GameCore.SetDynamicValue"):
                                    rt.executor.execute_task(nodes, ai_ctx)
                                    dk = nodes.get("DynamicKey")
                                    dk_name = dk.get("Value") if isinstance(dk, Mapping) else str(dk or "")
                                    if dk_name == "AIFlag":
                                        new_flag = rt.get_dynamic_value(self.owner_id, dotnet_hash("AIFlag"))
                                        if new_flag > 0:
                                            self.ai_executor.ai_flag = int(round(new_flag))
                                elif nt == "RPG.GameCore.SetDynamicValueByAddValue":
                                    rt.executor.execute_task(nodes, ai_ctx)
                                    dk = nodes.get("Key") or nodes.get("DynamicKey")
                                    dk_name = dk.get("Value") if isinstance(dk, Mapping) else str(dk or "")
                                    if dk_name == "AIFlag":
                                        new_flag = rt.get_dynamic_value(self.owner_id, dotnet_hash("AIFlag"))
                                        if new_flag > 0:
                                            self.ai_executor.ai_flag = int(round(new_flag))
                                elif nt == "RPG.GameCore.Retarget":
                                    cands = rt.executor._resolve_targets(nodes.get("TargetType"), ai_ctx)
                                    pred = nodes.get("Predicate")
                                    matched_tgts: List[str] = []
                                    for tid in cands:
                                        if pred:
                                            t_ctx = ai_ctx.clone(param_entity_id=tid)
                                            try:
                                                ok = rt.executor.eval_predicate(pred, t_ctx)
                                            except NotImplementedError:
                                                ok = False
                                            if not ok:
                                                continue
                                        matched_tgts.append(tid)
                                    if matched_tgts:
                                        _resolve_ai_skills(nodes.get("TaskList", []))
                                    else:
                                        _resolve_ai_skills(nodes.get("FailedTaskList", []))
                                elif nt == "RPG.GameCore.PredicateTaskList":
                                    pred = nodes.get("Predicate")
                                    try:
                                        ok = rt.executor.eval_predicate(pred, ai_ctx) if pred else True
                                    except NotImplementedError:
                                        ok = False
                                    _resolve_ai_skills(
                                        nodes.get("SuccessTaskList", []) if ok else nodes.get("FailedTaskList", [])
                                    )
                                elif nt == "RPG.GameCore.SelectAISkillTarget":
                                    self._resolve_select_ai_skill_target(nodes, ai_ctx, rt)
                                elif nt == "RPG.GameCore.SequenceConfig":
                                    _resolve_ai_skills(nodes.get("TaskList", []))

                            _resolve_ai_skills(root_tasks)
                            if resolved_skill_names:
                                dyn_actions = tuple(
                                    self.ai_spec.skills_by_key[sk_name]
                                    for sk_name in resolved_skill_names
                                    if sk_name in self.ai_spec.skills_by_key
                                )
                                if dyn_actions:
                                    actions = dyn_actions
                session.pending_skills.extend(actions)

            if not session.pending_skills:
                return None

            sk = session.pending_skills.pop(0)
            self.executed_skills.append(sk.skill_trigger_key)

            # 1. Execute official ConfigAbility AST tasks (e.g. SummonMonster)
            entry_ab = self._get_entry_ability_name(sk.skill_trigger_key)
            if entry_ab:
                if rt is None:
                    self._execute_ability_tasks(entry_ab)
                game_loader = getattr(self.runner.factory, "game_loader", None)
                if game_loader:
                    ab_cands = [entry_ab]
                    if "_Phase01" in entry_ab:
                        ab_cands.append(entry_ab.replace("_Phase01", "_Phase02"))
                    for cand_ab in ab_cands:
                        ab_doc = game_loader.get_ability(cand_ab)
                        if not ab_doc:
                            continue

                        def _scan_one_more(node: Any) -> Tuple[bool, bool]:
                            rem = add = False
                            if isinstance(node, dict):
                                t_nd = node.get("$type", "")
                                mn = node.get("ModifierName")
                                mval = mn.get("Value") if isinstance(mn, dict) else mn
                                if mval == "OneMorePerTurn":
                                    if t_nd == "RPG.GameCore.RemoveModifier":
                                        rem = True
                                    elif t_nd == "RPG.GameCore.AddModifier":
                                        add = True
                                for v in node.values():
                                    r2, a2 = _scan_one_more(v)
                                    rem = rem or r2
                                    add = add or a2
                            elif isinstance(node, list):
                                for it in node:
                                    r2, a2 = _scan_one_more(it)
                                    rem = rem or r2
                                    add = add or a2
                            return rem, add

                        has_rem, has_add = _scan_one_more(ab_doc)
                        if has_rem:
                            session.can_one_more = False
                            session.next_turn_one_more = False
                            if rt is not None:
                                rt.modifier_engine.remove_modifier(self.owner_id, "OneMorePerTurn")
                        if has_add:
                            session.next_turn_one_more = True

            # 2. Sync any newly spawned monsters to TurnSimulator
            director = getattr(sim, "_stage_director", None)
            if director and hasattr(director, "sync_spawned_entities"):
                director.sync_spawned_entities()

            # 3. 统一通过官方 ConfigAbility VM 执行技能（废除伤害/非伤害双轨分流）
            if sk.is_passive or attacker is None:
                continue
            if sk.skill_trigger_key:
                self._record_skill_usage(sim, sk.skill_trigger_key)
            sim._pending_turn_reset_distance = STANDARD_ACTION_DISTANCE * float(getattr(sk, "delay_ratio", 1.0) or 1.0)
            diag_cb = getattr(sim, "timeline_diag_cb", None)
            if callable(diag_cb):
                diag_cb(
                    "ESKILL",
                    f"{self.owner_id} idx={session.action_idx} key={sk.skill_trigger_key} "
                    f"can_om={session.can_one_more} rt_om={session.last_rt_om}",
                )
            resolved: Tuple[str, ...] = ()
            if entry_ab and rt is not None:
                resolved = self._execute_vm_skill(entry_ab, sim, sk, attacker)
            else:
                # 仅无 VM / 无 ConfigAbility 的极简单元测试回退
                mult = sk.param(0, default=0.0)
                if mult > 0.0 and sk.damage_type is not None:
                    targets = self._select_targets(sim, sk.target_selector)
                    resolved = self.enemy_port.apply_enemy_attack(
                        owner_id=self.owner_id,
                        target_ids=tuple(t.name for t in targets),
                        multiplier=mult,
                        element=sk.element or "Physical",
                        hit_energy=float(sk.sp_hit_base or getattr(attacker, "hit_energy", 5.0) or 5.0),
                        hits=max(1, int(getattr(sk, "hit_count", 1) or 1)),
                        blast=bool(getattr(sk, "is_blast", False)),
                        increment_action_seq=True,
                    )
            if resolved and sk.skill_trigger_key in ("Skill01", "Skill03"):
                self._marked_target = resolved[0]

            has_om_after = rt is not None and rt.modifier_engine.has_modifier(self.owner_id, "OneMore")
            has_next_sub_action = bool(
                attacker is not None
                and attacker.current_hp > 0.0
                and (
                    (session.action_idx == 1 and (session.can_one_more or has_om_after))
                    or (session.action_idx >= 2 and has_om_after)
                )
            )
            if attacker is None or attacker.current_hp <= 0.0:
                session.pending_skills.clear()
            return EnemySubActionOutcome(executed=True, has_next_sub_action=has_next_sub_action)

    def finish_turn_session(self, session: _EnemyTurnSession) -> EnemyActionResult:
        sim = session.sim
        attacker = session.attacker
        self.has_one_more = session.next_turn_one_more
        rt = getattr(sim, "vm_runtime", None)
        if rt is not None and attacker is not None and attacker.current_hp > 0.0:
            rt.end_being_attacked()
        self.runner.on_turn_end(self.owner_id, current_av=sim.current_av)

        # 官方 MCommon_FastAction (风行/如流星闪耀): 行动结束后跑道归零，立刻获得一次额外再动
        has_fast_action_mod = (
            rt is not None
            and rt.modifier_engine.has_modifier(self.owner_id, "MCommon_FastAction")
        )
        if attacker is not None and attacker.current_hp > 0.0 and has_fast_action_mod and rt is not None:
            rt.modifier_engine.remove_modifier(self.owner_id, "MCommon_FastAction")
            return EnemyActionResult(reset_distance=0.0)

        pending_reset = getattr(sim, "_pending_turn_reset_distance", None)
        if pending_reset is not None:
            return EnemyActionResult(reset_distance=float(pending_reset))

        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        session = self.begin_turn_session(ctx)
        if session is None:
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)
        boundary = getattr(session.sim, "_on_turn_sub_action_boundary", None)
        for sub_idx in range(1, 33):
            outcome = self.execute_next_sub_action(session, sub_idx)
            if outcome is None:
                break
            if outcome.executed and callable(boundary) and session.attacker is not None:
                boundary(
                    session.attacker,
                    sub_action_index=sub_idx,
                    has_next_sub_action=outcome.has_next_sub_action,
                )
            if session.attacker is None or session.attacker.current_hp <= 0.0:
                break
        return self.finish_turn_session(session)

    def get_kit_state(self) -> Dict[str, Any]:
        return {
            "monster_id": self.ai_spec.monster_id,
            "phase": self.ai_executor.phase,
            "ai_flag": self.ai_executor.ai_flag,
            "executed_skills": list(self.executed_skills),
        }

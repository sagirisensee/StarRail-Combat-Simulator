# coding: utf-8
"""纯数据驱动敌方技能组适配器（DataDrivenEnemyKit，从 stage_sim_adapter.py 拆分）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.core import Entity, TurnSimulator
from simulator.vm.enemy_port import (
    BaseEnemyCombatPortImpl,
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from simulator.vm.stage_ai import (
    AISkillActionSpec,
    CompiledMonsterAISpec,
    MonsterAIExecutor,
)
from simulator.vm.stage_runner import StageRunner


class DataDrivenEnemyKit(EnemyKit):
    """Pure data-driven ``EnemyKit`` backed by ``CompiledMonsterAISpec`` & ``StageRunner``."""

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
        mrs = self.runner.get_enemy_state(owner_id)
        rank = getattr(mrs.blueprint, "rank", "")
        # 官方 OneMorePerTurn 机制: 精英怪与首领初始具备额外行动特权（排除狂兽的胚芽等 MinionLv2 召唤物）
        self.has_one_more: bool = rank in ("Elite", "Boss", "BigBoss")
        # 官方 MCommon_FastAction (风行/如流星闪耀) 立即再动状态
        self.windwalk_ready: bool = False
        self.windwalk_target: Optional[str] = None
        self._windwalk_initialized: bool = False
        self._monster_dyn_initialized: bool = False
        self._marked_target: Optional[str] = None

    def _ensure_windwalk_init(self, sim: TurnSimulator) -> None:
        if self._windwalk_initialized:
            return
        self._windwalk_initialized = True
        mid = int(self.ai_spec.monster_template_id or 0)
        if mid != 4022010:
            return
        # 解析代次与序号 (支持 <name>_3 / <name>_g1_3)
        gen, idx = 1, 0
        parts = self.owner_id.split("_")
        base_name = parts[0] if parts else self.owner_id
        if len(parts) >= 3 and parts[-2].startswith("g") and parts[-2][1:].isdigit() and parts[-1].isdigit():
            gen = int(parts[-2][1:])
            idx = int(parts[-1])
        elif len(parts) >= 2 and parts[-1].isdigit():
            idx = int(parts[-1])
        wp = getattr(sim, "enemy_windwalk_provider", None)
        if wp is not None:
            val = wp(self.owner_id, gen, idx)
            if not val and idx > 0:
                val = wp(f"{base_name}_g{gen}_{idx}", gen, idx)
            if val is True:
                self.windwalk_ready = True
            elif isinstance(val, str) and val:
                self.windwalk_target = val
        elif gen == 1 and idx == 3:
            self.windwalk_ready = True

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
                    try:
                        ok = (
                            self.runner.eval_stage_predicate(
                                pred, caster_name=self.owner_id, dynamic_resolver=dyn_resolver
                            )
                            if pred
                            else True
                        )
                    except NotImplementedError:
                        ok = True
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

    def _apply_enemy_skill_modifiers(
        self,
        entry_ab: str,
        hit_targets: Sequence[str],
        sim: TurnSimulator,
    ) -> None:
        """通用执行敌方技能 AST 中施加给我方受击目标的 AddModifier（如印记叠加真伤、Debuff 等）。"""
        rt = getattr(sim, "vm_runtime", None)
        if rt is None or not hit_targets:
            return
        game_loader = getattr(self.runner.factory, "game_loader", None) or getattr(rt, "loader", None)
        if game_loader is None:
            return
        game_loader.ensure_ability_index()
        self._ensure_monster_dynamic_values(rt)

        from simulator.vm.target_alias import ExecutionContext

        visited: set[str] = set()
        mod_tasks: List[Tuple[Mapping[str, Any], str, bool]] = []
        dyn_tasks: List[Mapping[str, Any]] = []
        saw_dmg = False
        saw_finish = False

        def _walk_ab(ab_doc: Mapping[str, Any], scope_alias: str) -> None:
            _walk(ab_doc.get("OnStart", []), scope_alias)
            for tpl in ab_doc.get("TaskListTemplate", []) or []:
                if isinstance(tpl, Mapping):
                    _walk(tpl.get("TaskList", []), scope_alias)

        def _walk(tasks: Sequence[Any], scope_alias: str) -> None:
            nonlocal saw_dmg, saw_finish
            for t in tasks:
                if not isinstance(t, Mapping):
                    continue
                tt = t.get("$type", "")
                if tt == "RPG.GameCore.DamageByAttackProperty":
                    saw_dmg = True
                elif tt == "RPG.GameCore.DamagePerformFinish":
                    if saw_dmg:
                        saw_finish = True
                elif tt == "RPG.GameCore.SetDynamicValue":
                    dk = t.get("DynamicKey")
                    dk_name = dk.get("Value") if isinstance(dk, Mapping) else str(dk or "")
                    if dk_name and dk_name != "AIFlag":
                        dyn_tasks.append(t)
                elif tt == "RPG.GameCore.TriggerAbility":
                    cname = (t.get("AbilityName") or {}).get("Value", "")
                    if cname and "Camera" not in cname and cname not in visited:
                        visited.add(cname)
                        child = game_loader.get_ability(cname)
                        if child:
                            _walk_ab(child, scope_alias)
                elif tt == "RPG.GameCore.Retarget":
                    ttype = t.get("TargetType") or {}
                    alias = str(ttype.get("Alias", "")) if isinstance(ttype, Mapping) else ""
                    _walk(t.get("TaskList", []), alias or scope_alias)
                elif tt == "RPG.GameCore.PredicateTaskList":
                    pred = t.get("Predicate") or {}
                    # 仅在自定义开关为假（默认常规路径）时走 FailedTaskList，否则走 SuccessTaskList
                    if pred.get("$type") == "RPG.GameCore.ByCheckCustomValueBool":
                        _walk(t.get("FailedTaskList", []), scope_alias)
                    else:
                        _walk(t.get("SuccessTaskList", []), scope_alias)
                elif tt == "RPG.GameCore.AddModifier":
                    mname = str((t.get("ModifierName") or {}).get("Value", ""))
                    if not mname or (
                        "Debuff_Mark" not in mname
                        and "Corrosion" not in mname
                        and "BlackBlood" not in mname
                    ):
                        continue
                    ttype = t.get("TargetType") or {}
                    alias = str(ttype.get("Alias", "")) if isinstance(ttype, Mapping) else ""
                    tt_kind = str(ttype.get("$type", "")) if isinstance(ttype, Mapping) else ""
                    if (
                        alias in (
                            "ParamEntity",
                            "AbilityTargetEntity",
                            "AbilityTargetAndAdjoinEntity",
                            "AbilityTargetAdjoinEntity",
                            "AllEnemy",
                        )
                        or tt_kind == "RPG.GameCore.TargetSequence"
                    ):
                        if not any(str((mt.get("ModifierName") or {}).get("Value", "")) == mname for mt, _, _ in mod_tasks):
                            mod_tasks.append((t, scope_alias or alias, saw_finish))

        visited.add(entry_ab)
        root_ab = game_loader.get_ability(entry_ab)
        if root_ab:
            _walk_ab(root_ab, "")

        if not mod_tasks and not dyn_tasks:
            return

        ctx = ExecutionContext(
            runtime=rt,
            caster_id=self.owner_id,
            ability_name=entry_ab,
            ability_target_ids=(self.owner_id,),
            modifier_owner_id=self.owner_id,
        )
        if dyn_tasks:
            rt.executor.execute_tasks(dyn_tasks, ctx)

        def _apply_mod_batch(batch: Sequence[Tuple[Mapping[str, Any], str, bool]]) -> None:
            for task, scope_alias, _ in batch:
                mname = str((task.get("ModifierName") or {}).get("Value", ""))
                life = rt.executor._eval_num(task["LifeTime"], ctx) if "LifeTime" in task else None
                cnt_spec = task.get("LayerAddWhenStack") if "LayerAddWhenStack" in task else task.get("Count")
                cnt = int(round(rt.executor._eval_num(cnt_spec, ctx, 1.0))) if cnt_spec is not None else 1
                max_l = int(round(rt.executor._eval_num(task["MaxLayer"], ctx, 1.0))) if "MaxLayer" in task else None
                inherit = str(task.get("InheritCaster", ""))
                apply_tgts = list(hit_targets)
                for tid in apply_tgts:
                    eff_caster = tid if inherit == "TargetSelf" else self.owner_id
                    rt.modifier_engine.add_modifier(
                        owner_id=tid,
                        caster_id=eff_caster,
                        mod_name=mname,
                        ability_name=entry_ab,
                        dynamic_values=task.get("DynamicValues"),
                        life_time=life,
                        count=cnt,
                        max_layer=max_l,
                        ctx=ctx.clone(ability_target_ids=(tid,)),
                    )

        pre_mods = [m for m in mod_tasks if not m[2]]
        post_mods = [m for m in mod_tasks if m[2]]
        if pre_mods:
            _apply_mod_batch(pre_mods)
        if post_mods:
            rt.end_being_attacked()
            _apply_mod_batch(post_mods)

    def _execute_vm_non_damage_skill(self, entry_ab: str, sim: TurnSimulator, *, sp_hit_base: float = 0.0) -> None:
        """通用执行敌方非直伤/支援/吞噬技能 AST (如 HealHP、Retarget+ForceKill、AddModifier)。"""
        rt = getattr(sim, "vm_runtime", None)
        if rt is None or not entry_ab:
            return
        self._ensure_monster_dynamic_values(rt)
        ab = rt.loader.get_ability(entry_ab)
        if not ab:
            return
        tinfo = str((ab.get("TargetInfo") or {}).get("TargetType", ""))
        target_ids: Tuple[str, ...] = (self.owner_id,)
        if tinfo in ("AllEnemy", "EnemySelect", "SkillTargetEntityList"):
            living_allies = [
                e.name
                for e in sim.entities
                if not e.is_enemy
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
                and e.current_hp > 0.0
            ]
            if living_allies:
                target_ids = tuple(living_allies)
        elif tinfo == "SkillPointEntity":
            other_enemies = [
                e for e in sim.entities
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
        prev_sp_base = getattr(rt, "_current_enemy_sp_hit_base", 0.0)
        rt._current_enemy_sp_hit_base = float(sp_hit_base)
        try:
            rt.trigger_ability(
                caster_id=self.owner_id,
                ability_name=entry_ab,
                target_ids=target_ids,
                skill_target_ids=target_ids,
            )
        finally:
            rt._current_enemy_sp_hit_base = prev_sp_base

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        sim: TurnSimulator = self.port.sim
        self.runner.on_turn_begin(self.owner_id, current_av=sim.current_av)

        # Keep AI phase synchronized with StageRunner's MonsterRuntimeState
        mrs = self.runner.get_enemy_state(self.owner_id)
        if self.ai_executor.phase != mrs.phase:
            self.ai_executor.set_phase(mrs.phase, reset_ai_flag=1)

        self._turn_count += 1
        attacker = sim.get_entity(self.owner_id)
        self._ensure_windwalk_init(sim)

        # 非攻击辅助回合（如流星铁鹰 Skill02【如流星闪耀】赋予友方风行）：
        # 对具有 AIFlag 自切换能力的数据驱动怪物，优先走官方 ConfigAI + ConfigAbility 分支
        has_dynamic_ai_flag = any(d.next_ai_flag is not None for d in self.ai_executor.spec.decisions)
        skip_prov = getattr(sim, "enemy_attack_skip_provider", None)
        if (
            skip_prov is not None
            and attacker is not None
            and not has_dynamic_ai_flag
            and skip_prov(attacker, sim.current_av)
        ):
            if self.windwalk_target:
                director = getattr(sim, "_stage_director", None)
                t_ent = (
                    director._resolve_enemy_target(self.windwalk_target)
                    if director is not None and hasattr(director, "_resolve_enemy_target")
                    else sim.get_entity(self.windwalk_target)
                )
                t_kit = getattr(t_ent, "kit", None) if t_ent is not None else None
                if t_kit is not None and hasattr(t_kit, "windwalk_ready"):
                    t_kit.windwalk_ready = True
                self.windwalk_target = None
            else:
                wp = getattr(sim, "enemy_windwalk_provider", None)
                if callable(wp):
                    for ally_e in sim.entities:
                        if not ally_e.is_enemy or ally_e.current_hp <= 0.0:
                            continue
                        t_kit = getattr(ally_e, "kit", None)
                        if t_kit is None or not hasattr(t_kit, "windwalk_ready"):
                            continue
                        if wp(ally_e.name, 1, 0) is True:
                            t_kit.windwalk_ready = True
            self.runner.on_turn_end(self.owner_id, current_av=sim.current_av)
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

        # 优先同步 VM 中的动态 AIFlag (如 Monster_W5_Fallen_00_AttackOrder 将 AIFlag 设为 2)
        rt = getattr(sim, "vm_runtime", None)
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
        next_turn_one_more = can_one_more

        action_idx = 0
        while action_idx < 2:
            if action_idx == 1 and not can_one_more:
                break
            action_idx += 1
            if action_idx == 2 and rt is not None and rt.modifier_engine.has_modifier(self.owner_id, "OneMore"):
                rt.modifier_engine.remove_modifier(self.owner_id, "OneMore")

            if rt is not None:
                from simulator.vm.expr import dotnet_hash

                vm_flag = rt.get_dynamic_value(self.owner_id, dotnet_hash("AIFlag"))
                if vm_flag > 0:
                    self.ai_executor.ai_flag = int(round(vm_flag))

            actions: Tuple[AISkillActionSpec, ...] = self.ai_executor.select_next_actions()
            if not actions:
                break
            if rt is not None:
                from simulator.vm.expr import dotnet_hash

                rt.set_dynamic_value(self.owner_id, dotnet_hash("AIFlag"), float(self.ai_executor.ai_flag))
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
                    root_tasks = matched_dec.root_task.get("TaskList", [])
                    ai_tasks = [
                        t for t in root_tasks
                        if isinstance(t, Mapping)
                        and t.get("$type") in ("RPG.GameCore.AddModifier", "RPG.GameCore.RemoveModifier")
                    ]
                    if ai_tasks:
                        rt.executor.execute_tasks(ai_tasks, ai_ctx)
                    # 动态求值 ConfigAI RootTask 中的 PredicateTaskList，精确还原官方分支技能选择
                    if any(
                        isinstance(t, Mapping) and t.get("$type") == "RPG.GameCore.PredicateTaskList"
                        for t in root_tasks
                    ):
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
                            elif nt == "RPG.GameCore.PredicateTaskList":
                                pred = nodes.get("Predicate")
                                try:
                                    ok = rt.executor.eval_predicate(pred, ai_ctx) if pred else True
                                except NotImplementedError:
                                    ok = False
                                _resolve_ai_skills(
                                    nodes.get("SuccessTaskList", []) if ok else nodes.get("FailedTaskList", [])
                                )
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

            for sk in actions:
                self.executed_skills.append(sk.skill_trigger_key)

                # 1. Execute official ConfigAbility AST tasks (e.g. SummonMonster)
                entry_ab = self._get_entry_ability_name(sk.skill_trigger_key)
                if entry_ab:
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
                                can_one_more = False
                                next_turn_one_more = False
                            if has_add:
                                next_turn_one_more = True

                # 2. Sync any newly spawned monsters to TurnSimulator
                director = getattr(sim, "_stage_director", None)
                if director and hasattr(director, "sync_spawned_entities"):
                    director.sync_spawned_entities()

                # 3. Apply skill damage (or execute VM support/devour AST if non-damaging)
                mult = sk.param(0, default=0.0)
                if sk.is_passive or attacker is None:
                    continue
                if mult <= 0.0 or sk.damage_type is None:
                    if entry_ab:
                        self._execute_vm_non_damage_skill(entry_ab, sim, sp_hit_base=float(getattr(sk, "sp_hit_base", 0.0) or 0.0))
                    sched_pre = getattr(sim, "scheduler", None)
                    if (action_idx == 1 and can_one_more) or (sched_pre is not None and sched_pre.has_pending()):
                        rt_sub = getattr(sim, "vm_runtime", None)
                        if rt_sub is not None:
                            rt_sub.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=self.owner_id)
                    sub_cb = getattr(sim, "on_enemy_sub_action_end", None)
                    if callable(sub_cb) and action_idx == 1 and can_one_more and attacker is not None and attacker.current_hp > 0.0:
                        sched = getattr(sim, "scheduler", None)
                        prev_depth = getattr(sched, "_action_frame_depth", 0) if sched is not None else 0
                        if sched is not None and prev_depth > 0:
                            sched._action_frame_depth = 0
                        try:
                            sub_cb()
                            if sched is not None and sched.has_pending():
                                sched.drain()
                        finally:
                            if sched is not None and prev_depth > 0:
                                sched._action_frame_depth = prev_depth
                    continue

                # 索敌: 若技能在 Ability 中声明了 AllEnemy 或为全体横扫，则命中全体
                targets = self._select_targets(sim, sk.target_selector)
                if sk.skill_trigger_key == "Skill02":
                    allies = [
                        e
                        for e in sim.entities
                        if not e.is_enemy
                        and not getattr(e, "is_countdown", False)
                        and not getattr(e, "is_unselectable", False)
                        and e.current_hp > 0.0
                    ]
                    # 按官方编队站位排序（本体按进场站位序，忆灵按其召唤者站位序排在本体之后）
                    avatars = [e for e in allies if not getattr(e, "is_memosprite", False)]
                    avatar_rank = {e.name: idx for idx, e in enumerate(avatars)}
                    memos = [e for e in allies if getattr(e, "is_memosprite", False)]
                    memos.sort(key=lambda m: avatar_rank.get(getattr(m, "master_name", "") or "", 99))
                    targets = avatars + memos
                    # 通用解析官方 GlobalTargetAlias 中定义的 Skill02_Target (如 TargetTake Count=3)
                    gl = getattr(self.runner.factory, "game_loader", None)
                    if gl is not None and entry_ab and "_Skill02" in entry_ab:
                        prefix = entry_ab.split("_Skill02", 1)[0]
                        alias_def = gl.get_global_target_alias(f"{prefix}_Skill02_Target")
                        if isinstance(alias_def, Mapping) and alias_def.get("$type") == "RPG.GameCore.TargetSequence":
                            seq = alias_def.get("Sequence") or []
                            is_l2r = any(
                                isinstance(s, Mapping) and "LeftToRightLightTeamTarget" in str(s.get("Alias", ""))
                                for s in seq
                            )
                            take_cnt = 0
                            for s in seq:
                                if isinstance(s, Mapping) and s.get("$type") == "RPG.GameCore.TargetTake":
                                    cnt_obj = s.get("Count") or {}
                                    fv = cnt_obj.get("FixedValue") or {}
                                    take_cnt = int(fv.get("Value", 0) or 0)
                            if is_l2r:
                                targets = list(reversed(targets))
                            if take_cnt > 0:
                                targets = targets[:take_cnt]
                elif sk.skill_trigger_key == "Skill04":
                    # Skill04 (六倍满月 / 赞美艾格勒) 优先锁定带标记的目标
                    marked = [
                        e
                        for e in sim.entities
                        if not e.is_enemy
                        and e.current_hp > 0.0
                        and getattr(e, "is_memosprite", False)
                    ]
                    if not marked:
                        marked = [
                            e
                            for e in sim.entities
                            if not e.is_enemy and e.current_hp > 0.0
                        ]
                    if marked:
                        targets = [marked[0]]

                elem = sk.element or "Physical"
                # 受击回能: 优先采用技能原生 SPHitBase
                base_energy = (
                    sk.sp_hit_base
                    if sk.sp_hit_base > 0.0
                    else getattr(attacker, "hit_energy", 5.0) or 5.0
                )
                hits = 1
                adj_ratio = 1.0
                is_blast = (sk.target_selector == "adjacent")
                blast_prov = getattr(sim, "blast_target_provider", None)
                if not is_blast and sk.skill_trigger_key != "Skill01" and blast_prov is not None and targets:
                    living_allies = [
                        e
                        for e in sim.entities
                        if not e.is_enemy
                        and e.current_hp > 0.0
                        and not getattr(e, "is_countdown", False)
                    ]
                    if bool(blast_prov(attacker, targets[0], living_allies)):
                        is_blast = True

                if sk.skill_trigger_key == "Skill04":
                    mid = int(self.ai_spec.monster_template_id or 0)
                    if mid == 4023020:
                        # 4023020 Skill04: 3 段扩散攻击，总倍率 4.5
                        hits = 3
                        mult = mult / 3.0
                        is_blast = True
                    elif mid == 4023010:
                        # 4023010 Skill04: 4 段扩散扑击，总倍率 4.0，扩散系数 0.75
                        hits = 4
                        mult = mult / 4.0
                        is_blast = True
                        adj_ratio = 0.75

                hit_energy = base_energy / hits
                target_ids = tuple(t.name for t in targets)
                resolved = self.enemy_port.apply_enemy_attack(
                    owner_id=self.owner_id,
                    target_ids=target_ids,
                    multiplier=mult,
                    element=elem,
                    hit_energy=hit_energy,
                    hits=hits,
                    blast=is_blast,
                    adjacent_multiplier_ratio=adj_ratio,
                    increment_action_seq=True,
                )
                if resolved and sk.skill_trigger_key in ("Skill01", "Skill03"):
                    self._marked_target = resolved[0]
                if entry_ab and resolved:
                    self._apply_enemy_skill_modifiers(entry_ab, resolved, sim)
                rt_after_hit = getattr(sim, "vm_runtime", None)
                if rt_after_hit is not None:
                    rt_after_hit.end_being_attacked()
                    if resolved:
                        rt_after_hit.modifier_engine.dispatch_event(
                            "OnAfterAttack",
                            owner_id=self.owner_id,
                            attack_target_ids=tuple(resolved),
                        )
                        rt_after_hit.modifier_engine.dispatch_event(
                            "OnListenAfterAttack",
                            param_entity_id=self.owner_id,
                            attack_target_ids=tuple(resolved),
                        )

                sched_pre = getattr(sim, "scheduler", None)
                if (action_idx == 1 and can_one_more) or (sched_pre is not None and sched_pre.has_pending()):
                    rt_sub = getattr(sim, "vm_runtime", None)
                    if rt_sub is not None:
                        rt_sub.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=self.owner_id)

                sub_cb = getattr(sim, "on_enemy_sub_action_end", None)
                if callable(sub_cb) and action_idx == 1 and can_one_more and attacker is not None and attacker.current_hp > 0.0:
                    sched = getattr(sim, "scheduler", None)
                    prev_depth = getattr(sched, "_action_frame_depth", 0) if sched is not None else 0
                    if sched is not None and prev_depth > 0:
                        sched._action_frame_depth = 0
                    try:
                        sub_cb()
                        if sched is not None and sched.has_pending():
                            sched.drain()
                    finally:
                        if sched is not None and prev_depth > 0:
                            sched._action_frame_depth = prev_depth

                if attacker is None or attacker.current_hp <= 0.0:
                    break
            if attacker is None or attacker.current_hp <= 0.0:
                break

        self.has_one_more = next_turn_one_more
        rt = getattr(sim, "vm_runtime", None)
        if rt is not None and attacker is not None and attacker.current_hp > 0.0:
            rt.end_being_attacked()
        self.runner.on_turn_end(self.owner_id, current_av=sim.current_av)

        # 官方 MCommon_FastAction (风行/如流星闪耀): 行动结束后跑道归零，立刻获得一次额外再动
        has_fast_action_mod = (
            rt is not None
            and rt.modifier_engine.has_modifier(self.owner_id, "MCommon_FastAction")
        )
        if attacker is not None and attacker.current_hp > 0.0 and (self.windwalk_ready or has_fast_action_mod):
            self.windwalk_ready = False
            if has_fast_action_mod and rt is not None:
                rt.modifier_engine.remove_modifier(self.owner_id, "MCommon_FastAction")
            return EnemyActionResult(reset_distance=0.0)

        pending_reset = getattr(sim, "_pending_turn_reset_distance", None)
        if pending_reset is not None:
            return EnemyActionResult(reset_distance=float(pending_reset))

        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def get_kit_state(self) -> Dict[str, Any]:
        return {
            "monster_id": self.ai_spec.monster_id,
            "phase": self.ai_executor.phase,
            "ai_flag": self.ai_executor.ai_flag,
            "executed_skills": list(self.executed_skills),
        }

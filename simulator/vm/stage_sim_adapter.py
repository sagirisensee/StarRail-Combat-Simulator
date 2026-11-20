"""Read-only adapter bridging StageFactory / StageRunner / StageAILoader to TurnSimulator.

Provides a pure data-driven ``EnemyKit`` (``DataDrivenEnemyKit``) and
``StageDirector`` (``DataDrivenStageDirector``) + ``build_data_driven_stage()``
without modifying ``core.py``, ``stage_30126122.py``, or ``kits/enemies/*``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.core import Entity, TurnSimulator
from simulator.damage import DamageRequest
from simulator.effects import ApplyDamageEffect
from simulator.events import (
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    HPLostEvent,
    TurnBeginEvent,
    WeaknessBreakEvent,
)
from simulator.kits.enemies.base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from simulator.kits.enemies.sim_port import BaseEnemyCombatPortImpl
from simulator.stage_director import AnomalyWaveMode, BreakStatusHelper, MoCWaveMode
from simulator.status import StatType
from simulator.vm.stage_ai import (
    AISkillActionSpec,
    CompiledMonsterAISpec,
    MonsterAIExecutor,
    StageAILoader,
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
        if mid != 4022010 and "流星铁鹰" not in self.owner_id:
            return
        # 解析代次与序号 (支持 流星铁鹰_3 / 流星铁鹰_g1_3)
        gen, idx = 1, 0
        parts = self.owner_id.split("_")
        if len(parts) >= 3 and parts[-2].startswith("g") and parts[-2][1:].isdigit() and parts[-1].isdigit():
            gen = int(parts[-2][1:])
            idx = int(parts[-1])
        elif len(parts) >= 2 and parts[-1].isdigit():
            idx = int(parts[-1])
        wp = getattr(sim, "enemy_windwalk_provider", None)
        if wp is not None:
            val = wp(self.owner_id, gen, idx)
            if not val and idx > 0:
                val = wp(f"流星铁鹰_g{gen}_{idx}", gen, idx)
            if val is True:
                self.windwalk_ready = True
            elif isinstance(val, str) and val:
                self.windwalk_target = val
        elif gen == 1 and idx == 3:
            self.windwalk_ready = True

    def sync_phase(self, phase: int) -> None:
        if self.ai_executor.phase != phase:
            self.ai_executor.set_phase(phase, reset_ai_flag=1)

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
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
                    overflow = raw_damage - absorbed
                    if new_shld <= 0.0:
                        rt.modifier_engine.destroy_modifier(mod)
                    return overflow

        try:
            mrs = self.runner.get_enemy_state(self.owner_id)
        except KeyError:
            return raw_damage

        cur_hp = float(mrs.entity.current_hp)
        max_hp = float(mrs.entity.max_hp)
        if mrs.lock_hp_ratio is not None and mrs.lock_hp_ratio > 0.0:
            floor_hp = max_hp * float(mrs.lock_hp_ratio)
            if cur_hp > floor_hp and cur_hp - raw_damage < floor_hp:
                raw_damage = max(0.0, cur_hp - floor_hp)

        if mrs.phase < mrs.max_phase and cur_hp - raw_damage <= 0.0:
            setattr(mrs, "_limbo_pending", True)
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
        for t in ab.get("OnStart", []):
            tt = t.get("$type", "")
            if tt == "RPG.GameCore.TriggerAbility":
                child_name = t.get("AbilityName", {}).get("Value")
                if child_name and "Camera" not in child_name:
                    self._execute_ability_tasks(child_name, visited=visited)
            elif tt == "RPG.GameCore.PredicateTaskList":
                for st in t.get("SuccessTaskList", []):
                    self.runner.execute_stage_task(st, caster_name=self.owner_id)
            else:
                self.runner.execute_stage_task(t, caster_name=self.owner_id)

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

        from simulator.vm.expr import dotnet_hash
        from simulator.vm.target_alias import ExecutionContext

        visited: set[str] = set()
        mod_tasks: List[Tuple[Mapping[str, Any], str]] = []

        def _walk_ab(ab_doc: Mapping[str, Any], scope_alias: str) -> None:
            _walk(ab_doc.get("OnStart", []), scope_alias)
            for tpl in ab_doc.get("TaskListTemplate", []) or []:
                if isinstance(tpl, Mapping):
                    _walk(tpl.get("TaskList", []), scope_alias)

        def _walk(tasks: Sequence[Any], scope_alias: str) -> None:
            for t in tasks:
                if not isinstance(t, Mapping):
                    continue
                tt = t.get("$type", "")
                if tt == "RPG.GameCore.TriggerAbility":
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
                        if not any(str((mt.get("ModifierName") or {}).get("Value", "")) == mname for mt, _ in mod_tasks):
                            mod_tasks.append((t, scope_alias or alias))

        visited.add(entry_ab)
        root_ab = game_loader.get_ability(entry_ab)
        if root_ab:
            _walk_ab(root_ab, "")

        if not mod_tasks:
            return

        ctx = ExecutionContext(
            runtime=rt,
            caster_id=self.owner_id,
            ability_name=entry_ab,
        )
        for task, scope_alias in mod_tasks:
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

    def _execute_vm_non_damage_skill(self, entry_ab: str, sim: TurnSimulator) -> None:
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
            bosses = rt.executor._resolve_targets(
                {"Alias": "Monster_W5_Fallen_00_Self"},
                rt.executor._make_ctx(self.owner_id, entry_ab)
                if hasattr(rt.executor, "_make_ctx")
                else None,
            ) if hasattr(rt.executor, "_make_ctx") else []
            if not bosses:
                from simulator.vm.target_alias import ExecutionContext
                tmp_ctx = ExecutionContext(runtime=rt, caster_id=self.owner_id, ability_name=entry_ab)
                bosses = rt.executor._resolve_targets({"Alias": "Monster_W5_Fallen_00_Self"}, tmp_ctx)
            if bosses:
                target_ids = tuple(bosses)
        rt.trigger_ability(
            caster_id=self.owner_id,
            ability_name=entry_ab,
            target_ids=target_ids,
            skill_target_ids=target_ids,
        )

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
        # 对具有 AIFlag 自切换能力的数据驱动怪物（如狂兽的胚芽），优先走官方 ConfigAI + ConfigAbility 分支
        skip_prov = getattr(sim, "enemy_attack_skip_provider", None)
        if (
            skip_prov is not None
            and attacker is not None
            and "胚芽" not in self.owner_id
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
                        ab_doc = game_loader.get_ability(entry_ab)
                        if ab_doc:
                            s_doc = str(ab_doc)
                            if "OneMorePerTurn" in s_doc:
                                if "RemoveModifier" in s_doc and "OneMorePerTurn" in s_doc:
                                    can_one_more = False
                                    next_turn_one_more = False
                                if "AddModifier" in s_doc and "OneMorePerTurn" in s_doc:
                                    next_turn_one_more = True

                # 蓄力移除 OneMorePerTurn，终极技释放恢复 OneMorePerTurn (官方语义保底)
                if sk.skill_trigger_key == "Skill03" and "Monster_W5_Fallen_00" not in str(entry_ab or ""):
                    can_one_more = False
                    next_turn_one_more = False
                elif sk.skill_trigger_key == "Skill04" and "Monster_W5_Fallen_00" not in str(entry_ab or ""):
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
                        self._execute_vm_non_damage_skill(entry_ab, sim)
                    continue

                # 索敌: 若技能在 Ability 中声明了 AllEnemy 或为全体横扫，则命中全体
                targets = self._select_targets(sim, sk.target_selector)
                if sk.skill_trigger_key == "Skill02":
                    allies = [
                        e
                        for e in sim.entities
                        if not e.is_enemy
                        and not getattr(e, "is_countdown", False)
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
                    # Skill04 (六倍满月 / 赞美艾格勒) 优先锁定带标记的目标 (小伊卡或风堇)
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
                    if "天马" in self.owner_id or mid == 4023020:
                        # 月夜天马【六倍满月】: 3 段扩散攻击，总倍率 4.5
                        hits = 3
                        mult = mult / 3.0
                        is_blast = True
                    elif "狮鹫" in self.owner_id or mid == 4023010:
                        # 正阳狮鹫【赞美艾格勒】: 4 段扩散扑击，总倍率 4.0，扩散系数 0.75
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

                sched_pre = getattr(sim, "scheduler", None)
                if (action_idx == 1 and can_one_more) or (sched_pre is not None and sched_pre.has_pending()):
                    rt_sub = getattr(sim, "vm_runtime", None)
                    if rt_sub is not None:
                        rt_sub.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=self.owner_id)

                sub_cb = getattr(sim, "on_enemy_sub_action_end", None)
                if callable(sub_cb) and attacker is not None and attacker.current_hp > 0.0:
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
        self.runner.on_turn_end(self.owner_id, current_av=sim.current_av)

        # 官方 MCommon_FastAction (风行/如流星闪耀): 行动结束后跑道归零，立刻获得一次额外再动
        rt = getattr(sim, "vm_runtime", None)
        has_fast_action_mod = (
            rt is not None
            and rt.modifier_engine.has_modifier(self.owner_id, "MCommon_FastAction")
        )
        if attacker is not None and attacker.current_hp > 0.0 and (self.windwalk_ready or has_fast_action_mod):
            self.windwalk_ready = False
            if has_fast_action_mod and rt is not None:
                rt.modifier_engine.remove_modifier(self.owner_id, "MCommon_FastAction")
            return EnemyActionResult(reset_distance=0.0)

        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def get_kit_state(self) -> Dict[str, Any]:
        return {
            "monster_id": self.ai_spec.monster_id,
            "phase": self.ai_executor.phase,
            "ai_flag": self.ai_executor.ai_flag,
            "executed_skills": list(self.executed_skills),
        }


class DataDrivenStageDirector:
    """Pure data-driven ``StageDirector`` bridging ``StageRunner`` & ``StageAILoader`` to ``TurnSimulator``."""

    def __init__(
        self,
        sim: TurnSimulator,
        runner: StageRunner,
        ai_loader: StageAILoader,
        *,
        ai_by_monster_id: Optional[Mapping[int, CompiledMonsterAISpec]] = None,
    ) -> None:
        self.sim = sim
        self.runner = runner
        self.ai_loader = ai_loader
        self.port = BaseEnemyCombatPortImpl(sim)
        self.stage_id = runner.built_stage.stage_id
        self.max_waves = runner.built_stage.num_waves
        self._is_moc = (
            runner.built_stage.source_spec.stage_infinite_group_id is None
            and runner.built_stage.stage_type == "Challenge"
        )
        self._wave_mode = (
            MoCWaveMode(max_waves=self.max_waves)
            if self._is_moc
            else AnomalyWaveMode(max_waves=self.max_waves)
        )
        self._break_helper = BreakStatusHelper(sim)
        self._ai_cache: Dict[int, CompiledMonsterAISpec] = dict(ai_by_monster_id or {})
        self._last_cycle: int = sim.current_cycle
        self.aha_special_damage: float = 0.0
        self._pending_aha_turn: bool = False
        self._published_aha_turn_avs: set[float] = set()
        self._wave_start_av: float = 0.0
        self._triggered_aha_cycles: set[tuple[int, int]] = set()
        self.aha_extra_turns: list[dict[str, Any]] = []
        self.laugh_points: int = 0
        self._fired_aha_interrupts: set[int] = set()
        self._battle_event_timers: Dict[str, Tuple[str, str]] = {}
        self._triggered_aha_137: bool = False
        self._triggered_aha_150: bool = False

        self.sim.event_bus.subscribe(WeaknessBreakEvent, self._break_helper.on_weakness_break)
        self.sim.event_bus.subscribe(DamageAppliedEvent, self._break_helper.on_damage_applied)
        self.sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        setattr(self.sim, "_stage_director", self)

    def _current_wave_cycle(self) -> int:
        return self._wave_mode.current_wave_cycle(self.sim)

    def _check_cycle_aha_extra_turn(self) -> None:
        cur_cycle = self._current_wave_cycle()
        key = (self.wave, cur_cycle)
        if key not in self._triggered_aha_cycles:
            self._triggered_aha_cycles.add(key)
            record = {
                "cycle": cur_cycle,
                "av": round(self.sim.current_av, 2),
                "fixed_laugh_points": 20,
                "consumed_laugh_points": 0,
                "remaining_laugh_points": getattr(self, "laugh_points", 0),
            }
            self.aha_extra_turns.append(record)
            if cur_cycle >= 1:
                self.sim._turn_seq = getattr(self.sim, "_turn_seq", 0) + 1
                self._published_aha_turn_avs.add(round(float(self.sim.current_av), 2))
                self.sim.event_bus.publish(
                    TurnBeginEvent(
                        av=round(self.sim.current_av, 2),
                        cycle=cur_cycle,
                        actor_id="阿哈",
                        actor_name="阿哈",
                        speed=0.0,
                        turn_id=self.sim._turn_seq,
                    )
                )
            from simulator.events import AhaExtraTurnEvent

            self.sim.event_bus.publish(
                AhaExtraTurnEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=cur_cycle,
                    fixed_laugh_points=20,
                    consumed_laugh_points=0,
                    remaining_laugh_points=getattr(self, "laugh_points", 0),
                    description=f"[AhaExtraTurn] 第 {cur_cycle} 轮开始：阿哈获得 1 个固定计入 20 笑点的额外回合（不消耗笑点）",
                )
            )

    def peek_next_interrupt_av(self, now0: float, landing_av: float) -> Optional[float]:
        """返回 (now0, landing_av) 区间内最早的关卡轮次边界或待触发阿哈事件 AV。"""
        best: Optional[float] = None
        c = 1
        wave_start = getattr(self, "_wave_start_av", 0.0)
        while True:
            if (self.wave, c) not in self._triggered_aha_cycles:
                cyc_av = wave_start + 150.0 + 100.0 * (c - 1)
                if now0 + 1e-6 < cyc_av < landing_av - 1e-6:
                    best = cyc_av
                break
            c += 1
        for idx, cand in enumerate(getattr(self.sim, "aha_interrupt_avs", ())):
            if idx in self._fired_aha_interrupts:
                continue
            cand_f = float(cand)
            if now0 + 1e-6 < cand_f < landing_av - 1e-6:
                if best is None or cand_f < best:
                    best = cand_f
        return best

    def mark_interrupt_av_checked(self, av: float) -> None:
        for idx, cand in enumerate(getattr(self.sim, "aha_interrupt_avs", ())):
            if abs(float(cand) - av) <= 1e-5:
                self._fired_aha_interrupts.add(idx)

    def flush_ally_talent_heals(self) -> None:
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is not None:
            hit_enemies = list(getattr(self, "_aha_hit_enemies", ()))
            if hit_enemies:
                self._aha_hit_enemies.clear()
                for ename in hit_enemies:
                    e_obj = self.sim.get_entity(ename)
                    if e_obj is not None and e_obj.current_hp > 0.0:
                        rt.modifier_engine.dispatch_event(
                            "OnAfterBeingAttacked",
                            owner_id=ename,
                            param_entity_id="阿哈",
                        )
            rt.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id="__LEVEL__")
            rt.end_being_attacked("阿哈")
            if getattr(self, "_pending_aha_turn", False):
                self._pending_aha_turn = False
                if not getattr(self, "_suppress_aha_turn_reset", False):
                    rt.modifier_engine.dispatch_event("OnListenTurnEnd", param_entity_id="阿哈")
                    cur_owner = getattr(getattr(self.sim, "_current_turn_entity", None), "name", "__LEVEL__")
                    rt.modifier_engine.dispatch_event("OnListenTurnBegin", param_entity_id=cur_owner)
            return
        for ent in self.sim.entities:
            if not ent.is_enemy and ent.current_hp > 0:
                kit = getattr(ent, "kit", None)
                if kit is not None and hasattr(kit, "_resolve_talent_heal"):
                    kit._resolve_talent_heal()

    def _check_aha_special_damage_events(self) -> None:
        handler = getattr(self.sim, "aha_special_handler", None)
        if handler is not None:
            handler(self)

    def _init_wave_monster_battle_events(self, entities: Sequence[Entity], wave_index: int) -> None:
        """通用初始化当前波次怪物的 DynamicValues、触发 *PassiveSkillInitiate，并结算入场立即就绪的 BattleEvent（如 20041 进场召唤胚芽）。"""
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is None:
            return
        for ent in entities:
            kit = getattr(ent, "kit", None)
            if kit is not None and hasattr(kit, "_ensure_monster_dynamic_values"):
                kit._ensure_monster_dynamic_values(rt)
            try:
                mrs = self.runner.get_enemy_state(ent.name)
            except KeyError:
                continue
            for ab_name in getattr(mrs.blueprint, "ability_list", ()):
                if "PassiveSkillInitiate" in str(ab_name):
                    rt.trigger_ability(
                        caster_id=ent.name,
                        ability_name=str(ab_name),
                        target_ids=(ent.name,),
                    )

        # 若怪物 PassiveSkillInitiate 创建了 OnAdd 立即置零跑道 (distance_remaining == 0) 的 BattleEvent (如 20041)，
        # 按官方波次进场时序立即触发其 OnPhase1 + drain 并将距离重置为 10000.0
        for be_name in list(rt.named_targets.get("BattleEventEntityList", ())):
            be_ent = self.sim.get_entity(be_name)
            if (
                be_ent is not None
                and getattr(be_ent, "is_countdown", False)
                and be_ent.distance_remaining <= 1e-6
            ):
                if hasattr(self.sim, "_ready_queue") and be_name in self.sim._ready_queue:
                    self.sim._ready_queue.remove(be_name)
                if hasattr(self.sim, "_natural_due_names"):
                    self.sim._natural_due_names.discard(be_name)
                rt.modifier_engine.dispatch_event("OnPhase1", owner_id=be_name)
                sched = getattr(self.sim, "scheduler", None)
                if sched is not None and sched.has_pending():
                    prev_d = getattr(sched, "_action_frame_depth", 0)
                    sched._action_frame_depth = 0
                    try:
                        sched.drain()
                    finally:
                        sched._action_frame_depth = prev_d
                be_ent.distance_remaining = 10000.0
        self.sync_spawned_entities()

    def _on_turn_begin(self, event: TurnBeginEvent) -> None:
        self._check_aha_special_damage_events()
        self._break_helper.on_turn_begin(event)
        actor_ent = self.sim.get_entity(event.actor_name)
        if actor_ent is not None and getattr(actor_ent, "is_countdown", False):
            sched = getattr(self.sim, "scheduler", None)
            if sched is not None and sched.has_pending():
                prev_d = getattr(sched, "_action_frame_depth", 0)
                sched._action_frame_depth = 0
                try:
                    sched.drain()
                finally:
                    sched._action_frame_depth = prev_d
                self.sync_spawned_entities()

    @property
    def wave(self) -> int:
        return self.runner.state.wave_index + 1

    def _get_ai_spec(self, monster_id: int, wave_index: int) -> CompiledMonsterAISpec:
        if monster_id in self._ai_cache:
            return self._ai_cache[monster_id]
        src_wave = self.runner.built_stage.source_spec.waves[wave_index]
        for m in src_wave.monsters:
            if m.monster_id == monster_id:
                spec = self.ai_loader.compile_monster_ai(m)
                self._ai_cache[monster_id] = spec
                return spec
        if monster_id in src_wave.summon_monsters:
            spec = self.ai_loader.compile_monster_ai(src_wave.summon_monsters[monster_id])
            self._ai_cache[monster_id] = spec
            return spec
        try:
            m_spec = self.runner.factory.stage_loader.compile_monster(
                monster_id, level=src_wave.monster_level
            )
            spec = self.ai_loader.compile_monster_ai(m_spec)
            self._ai_cache[monster_id] = spec
            return spec
        except Exception:
            pass
        raise KeyError(f"Monster {monster_id} not found in wave {wave_index} of stage {self.stage_id}")

    def _sync_enemy_order(self) -> None:
        living_runner_enemies = [m.entity for m in self.runner.state.enemies if m.entity.current_hp > 0.0]
        runner_enemy_names = {e.name for e in living_runner_enemies}
        allies = [e for e in self.sim.entities if not getattr(e, "is_enemy", False)]
        other_enemies = [e for e in self.sim.entities if getattr(e, "is_enemy", False) and e.name not in runner_enemy_names]
        self.sim.entities[:] = allies + living_runner_enemies + other_enemies
        if hasattr(self.sim, "_rebuild_entity_cache"):
            self.sim._rebuild_entity_cache()

    def sync_spawned_entities(self) -> List[Entity]:
        sim_names = {e.name for e in self.sim.entities}
        new_entities = [
            mrs.entity
            for mrs in self.runner.state.enemies
            if mrs.entity.name not in sim_names and mrs.entity.current_hp > 0.0
        ]
        if new_entities:
            self.attach_kits_to_entities(new_entities, self.runner.state.wave_index)
            rt = getattr(self.sim, "vm_runtime", None)
            for ent in new_entities:
                self.sim.add_entity(ent, trigger_battle_start=True)
                if getattr(ent, "kit", None) is not None:
                    ent.kit.port = self.port
                    if rt is not None and hasattr(ent.kit, "_ensure_monster_dynamic_values"):
                        ent.kit._ensure_monster_dynamic_values(rt)
                if rt is not None:
                    try:
                        mrs = self.runner.get_enemy_state(ent.name)
                    except KeyError:
                        mrs = None
                    if mrs is not None:
                        for ab_name in getattr(mrs.blueprint, "ability_list", ()):
                            if "PassiveSkillInitiate" in str(ab_name):
                                rt.trigger_ability(
                                    caster_id=ent.name,
                                    ability_name=str(ab_name),
                                    target_ids=(ent.name,),
                                )
            self._sync_enemy_order()
        return new_entities

    def attach_kits_to_entities(self, entities: Sequence[Entity], wave_index: int) -> None:
        for ent in entities:
            mid = int(getattr(ent, "monster_id", 0))
            if mid <= 0:
                continue
            ai_spec = self._get_ai_spec(mid, wave_index)
            ent.kit = DataDrivenEnemyKit(
                owner_id=ent.name,
                port=self.port,
                ai_spec=ai_spec,
                runner=self.runner,
            )

    def summon_enemy(
        self,
        caster_name: str,
        summon_task: Mapping[str, Any],
        *,
        dynamic_resolver: Optional[Any] = None,
    ) -> List[Entity]:
        spawned = self.runner.execute_summon_monster(
            caster_name,
            summon_task,
            dynamic_resolver=dynamic_resolver,
        )
        widx = self.runner.state.wave_index
        self.attach_kits_to_entities(spawned, widx)
        rt = getattr(self.sim, "vm_runtime", None)
        for ent in spawned:
            self.sim.add_entity(ent, trigger_battle_start=True)
            if rt is not None and getattr(ent, "kit", None) is not None and hasattr(ent.kit, "_ensure_monster_dynamic_values"):
                ent.kit._ensure_monster_dynamic_values(rt)
            if rt is not None:
                try:
                    mrs = self.runner.get_enemy_state(ent.name)
                except KeyError:
                    mrs = None
                if mrs is not None:
                    for ab_name in getattr(mrs.blueprint, "ability_list", ()):
                        if "PassiveSkillInitiate" in str(ab_name):
                            rt.trigger_ability(
                                caster_id=ent.name,
                                ability_name=str(ab_name),
                                target_ids=(ent.name,),
                            )
        self._sync_enemy_order()
        return spawned

    def _resolve_enemy_target(self, target_name: str) -> Optional[Entity]:
        ent = self.sim.get_entity(target_name)
        if ent is not None and ent.current_hp > 0:
            return ent
        # Check alias (e.g. 流星铁鹰_g1_2 -> 流星铁鹰_2)
        if "_g1_" in target_name:
            alt = target_name.replace("_g1_", "_")
            ent = self.sim.get_entity(alt)
            if ent is not None and ent.current_hp > 0:
                return ent
        elif "_g2_" in target_name:
            alt = target_name.replace("_g2_", "_")
            ent = self.sim.get_entity(alt)
            if ent is not None and ent.current_hp > 0:
                return ent
        for e in self.sim.entities:
            if e.is_enemy and e.current_hp > 0 and e.name == target_name:
                return e
        return None

    def apply_aha_hp_damage(self, target_name: str, dmg: float) -> float:
        self._pending_aha_turn = True
        av_key = round(float(self.sim.current_av), 2)
        if av_key not in self._published_aha_turn_avs:
            self._published_aha_turn_avs.add(av_key)
            self.sim._turn_seq = getattr(self.sim, "_turn_seq", 0) + 1
            self.sim.event_bus.publish(
                TurnBeginEvent(
                    av=av_key,
                    cycle=int(self.sim.current_cycle),
                    actor_id="阿哈",
                    actor_name="阿哈",
                    speed=0.0,
                    turn_id=self.sim._turn_seq,
                )
            )
        ent = self._resolve_enemy_target(target_name)
        if ent is None or ent.current_hp <= 0:
            return 0.0
        if not hasattr(self, "_aha_hit_enemies"):
            self._aha_hit_enemies: set[str] = set()
        self._aha_hit_enemies.add(ent.name)
        if dmg <= 0.0:
            return 0.0
        kit = getattr(ent, "kit", None)
        effective_dmg = dmg
        if kit is not None and hasattr(kit, "intercept_incoming_damage"):
            effective_dmg = kit.intercept_incoming_damage(ent.name, dmg)
        actual = min(ent.current_hp, effective_dmg)
        ent.current_hp = max(0.0, ent.current_hp - effective_dmg)
        self.aha_special_damage += dmg
        if actual > 0.0:
            self._break_helper.add_quantum_stack(ent.name)
            vm_rt = getattr(self.sim, "vm_runtime", None)
            if vm_rt is not None:
                vm_rt.modifier_engine.dispatch_event("OnHPChange", owner_id=ent.name, param_entity_id="阿哈")
                try:
                    mrs = self.runner.get_enemy_state(ent.name)
                    if getattr(mrs, "_limbo_pending", False):
                        setattr(mrs, "_limbo_pending", False)
                        vm_rt.modifier_engine.dispatch_event("OnLimboWaitHeal", owner_id=ent.name, param_entity_id="阿哈")
                except KeyError:
                    pass
        if ent.current_hp <= 0.0:
            vm_rt = getattr(self.sim, "vm_runtime", None)
            if vm_rt is not None:
                vm_rt.modifier_engine.dispatch_event("OnBeforeDying", owner_id=ent.name, param_entity_id="阿哈")
                vm_rt.modifier_engine.destroy_all_for_entity(ent.name)
            self.sim.event_bus.publish(
                EnemyDefeatedEvent(
                    av=float(self.sim.current_av),
                    cycle=int(self.sim.current_cycle),
                    attacker_name="阿哈",
                    target_name=ent.name,
                )
            )
            self.runner.state.enemies = [
                m for m in self.runner.state.enemies if m.entity.name != ent.name
            ]
            self.sim.entities[:] = [
                e for e in self.sim.entities if e is not ent
            ]
        return actual

    def apply_aha_ally_chip_hit(self, target_name: str) -> None:
        """阿哈回合伴生 1.0 基础伤害 (Lv.95 DEF 减免) 与 +2.0 基础受击回能。"""
        self._pending_aha_turn = True
        ent = self.sim.get_entity(target_name)
        if ent is None or ent.current_hp <= 0:
            return
        sm = getattr(self.sim, "status_mgr", None)
        def_val = (
            sm.calculate_stat(ent.name, getattr(ent, "base_def", 1000.0), StatType.DEF)
            if sm is not None
            else getattr(ent, "base_def", 1000.0)
        )
        atk_lvl_coeff = 95 * 10 + 200
        dmg = 1.0 * atk_lvl_coeff / (atk_lvl_coeff + max(0.0, def_val))
        actual = min(max(0.0, ent.current_hp - 1.0), dmg) if ent.current_hp > 1.0 else 0.0
        ent.current_hp = max(1.0, ent.current_hp - dmg) if ent.current_hp > 0.0 else 0.0
        if actual > 0.0:
            vm_rt = getattr(self.sim, "vm_runtime", None)
            if vm_rt is not None:
                vm_rt._open_enemy_attack = "阿哈"
                vm_rt.modifier_engine.dispatch_event("OnBeforeBeingHitAll", owner_id=ent.name, param_entity_id="阿哈")
                self.sim.event_bus.publish(HPLostEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=self.sim.current_cycle,
                    entity_name=ent.name,
                    amount=actual,
                    hp_left=ent.current_hp,
                    cause="attack_damage",
                ))
                vm_rt.modifier_engine.dispatch_event("OnAfterBeingHitAll", owner_id=ent.name, param_entity_id="阿哈")
            else:
                for ally in self.sim.entities:
                    kit = getattr(ally, "kit", None)
                    if kit is not None and hasattr(kit, "on_hp_lost"):
                        kit.on_hp_lost(ent.name, actual, cause="attack_damage")
        energy_target = ent
        if getattr(ent, "is_memosprite", False) and getattr(ent, "max_energy", 0.0) <= 0.0:
            master_name = getattr(ent, "master_name", None)
            if master_name:
                m_ent = self.sim.get_entity(master_name)
                if m_ent is not None:
                    energy_target = m_ent
        if hasattr(energy_target, "gain_sp"):
            energy_target.gain_sp(2.0)
        elif hasattr(energy_target, "energy") and hasattr(energy_target, "max_energy"):
            err = (
                sm.calculate_stat(energy_target.name, getattr(energy_target, "base_err", 1.0), StatType.ERR)
                if sm is not None
                else getattr(energy_target, "base_err", 1.0)
            )
            energy_target.energy = min(energy_target.max_energy, energy_target.energy + 2.0 * err)

    def trigger_monster_phase_transition(
        self,
        monster_name: str,
        *,
        mode: str = "Inc",
        value: Optional[int] = None,
    ) -> int:
        new_phase = self.runner.set_monster_phase(monster_name, mode=mode, value=value)
        ent = self.sim.get_entity(monster_name)
        if ent is not None and isinstance(getattr(ent, "kit", None), DataDrivenEnemyKit):
            ent.kit.sync_phase(new_phase)
        return new_phase

    def after_step(self) -> None:
        # 0. Aha cycle check & special damage check
        self._check_cycle_aha_extra_turn()
        self._check_aha_special_damage_events()

        # 1. Cycle boundary check
        cur_cycle = self.sim.current_cycle
        if cur_cycle > self._last_cycle:
            self._last_cycle = cur_cycle
            self.runner.on_cycle_boundary(cur_cycle, current_av=self.sim.current_av)

        # 2. Enforce LockHP on active enemies
        for mrs in list(self.runner.state.enemies):
            if mrs.lock_hp_ratio is not None and mrs.entity.current_hp > 0.0:
                self.runner.enforce_lock_hp(mrs.entity.name)

        # 3. Infinite wave slot refill if wave not yet cleared
        src_wave = self.runner.built_stage.source_spec.waves[self.runner.state.wave_index]
        if (
            self.runner.built_stage.source_spec.stage_infinite_group_id is not None
            and src_wave.max_monster_count > 0
            and 0 < len(self.runner.living_enemies()) < src_wave.max_monster_count
        ):
            refilled = self.runner.refill_infinite_wave_slot()
            self.attach_kits_to_entities(refilled, self.runner.state.wave_index)
            for ent in refilled:
                self.sim.add_entity(ent, trigger_battle_start=True)

        # 4. Wave clearance & transition
        if not self.runner.living_enemies():
            # Remove defeated enemies from TurnSimulator's active entities before spawning next wave
            next_wave_entities = self.runner.advance_wave_if_cleared(current_av=self.sim.current_av)
            if next_wave_entities is not None:
                self._wave_start_av = float(self.sim.current_av)
                self.sim.entities[:] = [
                    e for e in self.sim.entities if not e.is_enemy or e.current_hp > 0.0
                ]
                if self._is_moc:
                    for ent in self.sim.entities:
                        if (
                            not ent.is_enemy
                            and ent.current_hp > 0.0
                            and ent.speed > 0.0
                            and ent.distance_remaining < 1e5
                        ):
                            ent.distance_remaining = 10000.0
                    if hasattr(self.sim, "_ready_queue"):
                        self.sim._ready_queue.clear()
                self.attach_kits_to_entities(next_wave_entities, self.runner.state.wave_index)
                for ent in next_wave_entities:
                    self.sim.add_entity(ent, trigger_battle_start=True)
                    if getattr(ent, "kit", None) is not None:
                        ent.kit.port = self.port
                self._init_wave_monster_battle_events(next_wave_entities, self.runner.state.wave_index)


def build_data_driven_stage(
    stage_id: int,
    team: List[Entity],
    *,
    technique_users: Optional[Sequence[str]] = None,
    auto_ult: bool = True,
) -> Tuple[TurnSimulator, DataDrivenStageDirector]:
    """Build a ``(TurnSimulator, DataDrivenStageDirector)`` purely from official stage tables."""
    for member in team:
        if (
            not getattr(member, "is_enemy", False)
            and getattr(member, "max_energy", 0.0) > 0
            and getattr(member, "energy", 0.0) == 0.0
        ):
            member.energy = member.max_energy * 0.5

    runner = StageRunner(stage_id)
    ai_loader = StageAILoader(stage_loader=runner.factory.stage_loader)
    wave0_enemies = runner.start_stage()

    if team:
        raw_elem = getattr(team[0], "element", None)
        entry_elem = str(raw_elem).capitalize() if raw_elem else None
        if entry_elem:
            for e in wave0_enemies:
                if entry_elem in getattr(e, "weaknesses", ()):
                    e.current_toughness = max(0.0, e.current_toughness - 10.0)

    sim = TurnSimulator(
        entities=list(team) + list(wave0_enemies),
        use_techniques=bool(technique_users),
        technique_users=list(technique_users) if technique_users is not None else None,
        auto_ult=auto_ult,
    )
    sim.enemy_uid_map = {100009: "月夜天马", 100011: "正阳狮鹫"}
    director = DataDrivenStageDirector(sim, runner, ai_loader)
    director.attach_kits_to_entities(wave0_enemies, wave_index=0)
    return sim, director

# coding: utf-8
"""纯数据驱动关卡导演（DataDrivenStageDirector）与构建入口（从 stage_sim_adapter.py 拆分）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from simulator.core import Entity, TurnSimulator
from simulator.events import (
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    HPLostEvent,
    TurnBeginEvent,
    WeaknessBreakEvent,
)
from simulator.lifecycle import emit_sim_event
from simulator.vm.enemy_port import BaseEnemyCombatPortImpl
from simulator.vm.wave_modes import AnomalyWaveMode, BreakStatusHelper, MoCWaveMode
from simulator.status import StatType
from simulator.vm.enemy_kit import DataDrivenEnemyKit
from simulator.vm.stage_ai import CompiledMonsterAISpec, StageAILoader
from simulator.vm.stage_runner import StageRunner


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
        source_spec = runner.built_stage.source_spec
        self.challenge_mode: str = getattr(source_spec, "challenge_mode", "Other")
        self._is_moc = (
            self.challenge_mode == "MoC"
            if self.challenge_mode != "Other"
            else (
                source_spec.stage_infinite_group_id is None
                and runner.built_stage.stage_type == "Challenge"
            )
        )
        self._has_cycle_aha_extra_turn: bool = bool(
            getattr(source_spec, "has_cycle_aha_extra_turn", False)
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

        setattr(self.sim, "_stage_director", self)
        self._active_wave_ability: Optional[str] = None
        self._init_stage_affix_abilities()
        self._init_stage_battle_events()
        self._apply_wave_ability(self.runner.state.wave_index)

    def _init_stage_affix_abilities(
        self, extra_maze_buff_ids: Sequence[int] = ()
    ) -> None:
        """挂载官方 ChallengePeakConfig -> MazeBuff 及可选额外 MazeBuff（如贪饕临时增益）。"""
        affixes = list(getattr(self.runner.built_stage.source_spec, "stage_affix_abilities", ()))
        stage_loader = getattr(self.runner.factory, "stage_loader", None)
        if stage_loader is not None and hasattr(stage_loader, "resolve_stage_invasion"):
            stage_id = int(getattr(self.runner.built_stage.source_spec, "stage_id", 0) or 0)
            if stage_id:
                self._stage_invasion_info = stage_loader.resolve_stage_invasion(stage_id)
                if isinstance(self._stage_invasion_info, Mapping):
                    inv_mb_id = int(self._stage_invasion_info.get("maze_buff_id") or 0)
                    if inv_mb_id and hasattr(stage_loader, "resolve_maze_buff_abilities"):
                        seen_abs = {ab for ab, _ in affixes}
                        for inv_ab, inv_params in stage_loader.resolve_maze_buff_abilities((inv_mb_id,)):
                            if inv_ab not in seen_abs:
                                affixes.append((inv_ab, inv_params))
                                seen_abs.add(inv_ab)
        if extra_maze_buff_ids:
            if stage_loader is not None and hasattr(stage_loader, "resolve_maze_buff_abilities"):
                affixes.extend(stage_loader.resolve_maze_buff_abilities(extra_maze_buff_ids))
        if not affixes:
            return
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is None:
            return
        maze_buff_param_hashes = (462955996, 59671469, 1625755410, 866240523, -1862642832)
        rt.loader.ensure_ability_index()
        before_uids = {m.uid for m in rt.modifier_engine.get_modifiers("__LEVEL__")}
        mounted_level_abs = {
            m.ability_name for m in rt.modifier_engine.get_modifiers("__LEVEL__")
        }
        for ab_name, params in affixes:
            if ab_name in mounted_level_abs:
                continue
            ab = rt.loader.get_ability(ab_name)
            if not ab:
                continue
            mounted_level_abs.add(ab_name)
            init_dyn = {}
            for idx, val in enumerate(params):
                if idx < len(maze_buff_param_hashes):
                    h = maze_buff_param_hashes[idx]
                    init_dyn[h] = float(val)
                    rt.set_dynamic_value("__LEVEL__", h, float(val), ability_name=ab_name)
            on_add = ab.get("OnAdd") or []
            if on_add:
                from simulator.vm.target_alias import ExecutionContext

                ctx = ExecutionContext(
                    runtime=rt,
                    caster_id="__LEVEL__",
                    ability_name=ab_name,
                    ability_target_ids=("__LEVEL__",),
                    modifier_owner_id="__LEVEL__",
                    local_dynamics=dict(init_dyn),
                )
                rt.executor.execute_tasks(on_add, ctx)
            # 将每个 MazeBuff 专属的 ParamList 写入其对应的 Modifier 实例 dynamic_values，避免多个关卡词条共用 __LEVEL__[462955996] 互相覆盖
            for mod in rt.modifier_engine.get_modifiers("__LEVEL__"):
                if mod.ability_name == ab_name:
                    for idx, val in enumerate(params):
                        if idx < len(maze_buff_param_hashes):
                            mod.dynamic_values[maze_buff_param_hashes[idx]] = float(val)
        new_level_mods = [m for m in rt.modifier_engine.get_modifiers("__LEVEL__") if m.uid not in before_uids]
        # 对已入场实体补发一次 OnListenCharacterCreate，使所有环境词条挂到全部现有角色与敌方
        for ent in list(self.sim.entities):
            if getattr(ent, "is_countdown", False):
                continue
            prev_max = float(self.sim.port.max_hp(ent.name)) if hasattr(self.sim, "port") else float(ent.max_hp)
            was_full = abs(float(ent.current_hp) - prev_max) <= 1.0
            if new_level_mods:
                rt.modifier_engine.dispatch_event_to_modifiers(
                    new_level_mods,
                    "OnListenCharacterCreate",
                    param_entity_id=ent.name,
                )
            if was_full and hasattr(self.sim, "port"):
                new_max = float(self.sim.port.max_hp(ent.name))
                if new_max > ent.current_hp:
                    ent.current_hp = new_max
                    ent.max_hp = new_max
        if new_level_mods and getattr(rt, "_battle_entered", False):
            rt.modifier_engine.dispatch_event_to_modifiers(new_level_mods, "OnEnterBattle")

    def _init_stage_battle_events(self) -> None:
        """挂载关卡级 BattleEvent（如虚构叙事 31001 无限波次补怪与击杀回能修正）。"""
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is None:
            return
        battle_events = list(getattr(self.runner.built_stage, "battle_events", ()))
        if not battle_events:
            return
        rt.loader.ensure_ability_index()
        from simulator.vm.target_alias import ExecutionContext

        before_uids = {m.uid for m in rt.modifier_engine.get_modifiers("__LEVEL__")}
        for be in battle_events:
            if getattr(be, "team", "") not in ("", "TeamNeutral") or getattr(be, "event_sub_type", "") in (
                "AssistEvent",
                "DummyCharacter",
            ):
                continue
            param_list = [float(p) for p in getattr(be, "param_list", ())]
            for ab_name in getattr(be, "ability_names", ()):
                ab = rt.loader.get_ability(ab_name)
                if not ab:
                    continue
                for check_ab_name in (ab_name, f"{ab_name}_Insert"):
                    chk_doc = rt.loader.get_ability(check_ab_name)
                    if not isinstance(chk_doc, dict):
                        continue
                    floats = (chk_doc.get("DynamicValues") or {}).get("Floats") or {}
                    if isinstance(floats, Mapping):
                        for h_str, entry in floats.items():
                            if not isinstance(entry, Mapping):
                                continue
                            ri = entry.get("ReadInfo") or {}
                            if ri.get("Type") == "BattleEvent":
                                idx = int(ri.get("Index", 0) or 0)
                                if 0 <= idx < len(param_list):
                                    rt.set_dynamic_value("__LEVEL__", int(h_str), param_list[idx], ability_name=check_ab_name)
                on_add = ab.get("OnAdd") or []
                if on_add:
                    ctx = ExecutionContext(
                        runtime=rt,
                        caster_id="__LEVEL__",
                        ability_name=ab_name,
                        ability_target_ids=("__LEVEL__",),
                        modifier_owner_id="__LEVEL__",
                    )
                    rt.executor.execute_tasks(on_add, ctx)
        new_level_mods = [m for m in rt.modifier_engine.get_modifiers("__LEVEL__") if m.uid not in before_uids]
        for ent in list(self.sim.entities):
            if getattr(ent, "is_countdown", False):
                continue
            prev_max = float(self.sim.port.max_hp(ent.name)) if hasattr(self.sim, "port") else float(ent.max_hp)
            was_full = abs(float(ent.current_hp) - prev_max) <= 1.0
            if new_level_mods:
                rt.modifier_engine.dispatch_event_to_modifiers(
                    new_level_mods,
                    "OnListenCharacterCreate",
                    param_entity_id=ent.name,
                )
            if was_full and hasattr(self.sim, "port"):
                new_max = float(self.sim.port.max_hp(ent.name))
                if new_max > ent.current_hp:
                    ent.current_hp = new_max
                    ent.max_hp = new_max
        if new_level_mods and getattr(rt, "_battle_entered", False):
            rt.modifier_engine.dispatch_event_to_modifiers(new_level_mods, "OnEnterBattle")

    def _apply_wave_ability(self, wave_index: int) -> None:
        """挂载当前波次配置的 Wave Ability（如 FantasticStory_Wave_Ability_0001）。"""
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is None:
            return
        waves = getattr(self.runner.built_stage.source_spec, "waves", ())
        if not (0 <= wave_index < len(waves)):
            return
        src_wave = waves[wave_index]
        if getattr(src_wave, "clear_previous_ability", False) and self._active_wave_ability:
            prev_ab = self._active_wave_ability
            for m in list(rt.modifier_engine.get_modifiers("__LEVEL__")):
                if m.ability_name == prev_ab:
                    rt.modifier_engine.destroy_modifier(m)
            for ent in list(self.sim.entities):
                for m in list(rt.modifier_engine.get_modifiers(ent.name)):
                    if m.ability_name == prev_ab:
                        rt.modifier_engine.destroy_modifier(m)
            self._active_wave_ability = None

        ab_name = getattr(src_wave, "wave_ability", None)
        if not ab_name:
            return
        rt.loader.ensure_ability_index()
        ab = rt.loader.get_ability(ab_name)
        if not ab:
            return
        self._active_wave_ability = ab_name
        params = getattr(src_wave, "wave_ability_params", ()) or ()
        maze_buff_param_hashes = (462955996, 59671469, 1625755410, 866240523, -1862642832)
        init_dyn = {}
        for idx, val in enumerate(params):
            if idx < len(maze_buff_param_hashes):
                h = maze_buff_param_hashes[idx]
                init_dyn[h] = float(val)
                rt.set_dynamic_value("__LEVEL__", h, float(val), ability_name=ab_name)
        before_uids = {m.uid for m in rt.modifier_engine.get_modifiers("__LEVEL__")}
        on_add = ab.get("OnAdd") or []
        if on_add:
            from simulator.vm.target_alias import ExecutionContext

            ctx = ExecutionContext(
                runtime=rt,
                caster_id="__LEVEL__",
                ability_name=ab_name,
                ability_target_ids=("__LEVEL__",),
                modifier_owner_id="__LEVEL__",
                local_dynamics=dict(init_dyn),
            )
            rt.executor.execute_tasks(on_add, ctx)
        for mod in rt.modifier_engine.get_modifiers("__LEVEL__"):
            if mod.ability_name == ab_name:
                for idx, val in enumerate(params):
                    if idx < len(maze_buff_param_hashes):
                        mod.dynamic_values[maze_buff_param_hashes[idx]] = float(val)
        new_level_mods = [m for m in rt.modifier_engine.get_modifiers("__LEVEL__") if m.uid not in before_uids]
        for ent in list(self.sim.entities):
            if getattr(ent, "is_countdown", False):
                continue
            prev_max = float(self.sim.port.max_hp(ent.name)) if hasattr(self.sim, "port") else float(ent.max_hp)
            was_full = abs(float(ent.current_hp) - prev_max) <= 1.0
            if new_level_mods:
                rt.modifier_engine.dispatch_event_to_modifiers(
                    new_level_mods,
                    "OnListenCharacterCreate",
                    param_entity_id=ent.name,
                )
            if was_full and hasattr(self.sim, "port"):
                new_max = float(self.sim.port.max_hp(ent.name))
                if new_max > ent.current_hp:
                    ent.current_hp = new_max
                    ent.max_hp = new_max

    def _current_wave_cycle(self) -> int:
        return self._wave_mode.current_wave_cycle(self.sim)

    def _check_cycle_aha_extra_turn(self) -> None:
        if not self._has_cycle_aha_extra_turn:
            return
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
                emit_sim_event(
                    self.sim,
                    TurnBeginEvent(
                        av=round(self.sim.current_av, 2),
                        cycle=cur_cycle,
                        actor_id="阿哈",
                        actor_name="阿哈",
                        speed=0.0,
                        turn_id=self.sim._turn_seq,
                    ),
                )
            from simulator.events import AhaExtraTurnEvent

            emit_sim_event(
                self.sim,
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
        if self._has_cycle_aha_extra_turn:
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
                    e_obj = self.sim.get_entity(ename)
                    if e_obj is not None and e_obj.current_hp > 0.0:
                        rt.modifier_engine.dispatch_event(
                            "OnAfterBeingAttackedEnd",
                            owner_id=ename,
                            param_entity_id="阿哈",
                        )
            rt.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id="__LEVEL__")
            rt.end_being_attacked("阿哈")
            if getattr(self, "_pending_aha_turn", False):
                self._pending_aha_turn = False
                if not getattr(self, "_suppress_aha_turn_reset", False):
                    rt.modifier_engine.dispatch_event("OnListenTurnEnd", param_entity_id="阿哈")
                    cur_ent = getattr(self.sim, "_current_turn_entity", None)
                    if cur_ent is not None:
                        rt.modifier_engine.dispatch_event("OnListenTurnBegin", param_entity_id=cur_ent.name)

    def _check_aha_special_damage_events(self) -> None:
        handler = getattr(self.sim, "aha_special_handler", None)
        if handler is not None:
            handler(self)

    def _trigger_monster_passive_abilities(self, ent: Entity, rt: Any) -> None:
        """触发怪物的入场被动能力：AbilityList 中的 *PassiveSkillInitiate 与 SkillList 中的 Passive 技能入口。"""
        try:
            mrs = self.runner.get_enemy_state(ent.name)
        except KeyError:
            return
        rt.loader.ensure_ability_index()
        from simulator.vm.target_alias import ExecutionContext

        triggered: set[str] = set()
        abilities_cfg = tuple(getattr(mrs.blueprint, "ability_list", ()) or ())
        # Pass 1: 执行 AbilityList 中所有挂载体即触发的 OnAdd（如 Boss SkillEX* / TeamFormation）
        for ab_name in abilities_cfg:
            s_ab = str(ab_name)
            if (
                not s_ab
                or s_ab.endswith("_Camera")
                or "_Camera_" in s_ab
                or "BGM" in s_ab
                or "MuteHitFly" in s_ab
                or "StanceBreak_Action" in s_ab
            ):
                continue
            ab = rt.loader.get_ability(s_ab)
            if not isinstance(ab, dict) or not ab.get("OnAdd"):
                continue
            add_key = (ent.name, s_ab)
            if add_key in rt._added_abilities:
                continue
            rt._added_abilities.add(add_key)
            ctx = ExecutionContext(
                runtime=rt,
                caster_id=ent.name,
                ability_name=s_ab,
                ability_target_ids=(ent.name,),
                modifier_owner_id=ent.name,
            )
            rt.executor.execute_tasks(ab.get("OnAdd", []), ctx)

        # Pass 2: 触发 PassiveSkillInitiate（若仅有 OnAdd 且上面已触发则会跳过重复）
        for ab_name in abilities_cfg:
            s_ab = str(ab_name)
            if "PassiveSkillInitiate" in s_ab and s_ab not in triggered:
                triggered.add(s_ab)
                rt.trigger_ability(caster_id=ent.name, ability_name=s_ab, target_ids=(ent.name,))
        sl = self.ai_loader.stage_loader
        tmpl = sl.monster_templates.get(
            int(getattr(mrs.blueprint, "monster_template_id", 0)), {}
        )
        cfg_path = str(tmpl.get("JsonConfig") or "")
        if cfg_path:
            char_cfg = sl._load_char_config(cfg_path)
            for sk_item in char_cfg.get("SkillList", ()) or ():
                if not isinstance(sk_item, dict):
                    continue
                if (
                    sk_item.get("SkillType") != "Passive"
                    and sk_item.get("UseType") != "Passive"
                    and not str(sk_item.get("Name", "")).startswith("PassiveSkill")
                ):
                    continue
                entry_ab = str(sk_item.get("EntryAbility") or "")
                if (
                    entry_ab
                    and entry_ab not in triggered
                    and "BGM" not in entry_ab
                    and "MuteHitFly" not in entry_ab
                    and "StanceBreak_Action" not in entry_ab
                ):
                    triggered.add(entry_ab)
                    rt.trigger_ability(caster_id=ent.name, ability_name=entry_ab, target_ids=(ent.name,))

    def _init_wave_monster_battle_events(self, entities: Sequence[Entity], wave_index: int) -> None:
        """通用初始化当前波次怪物的 DynamicValues、触发入场被动，并结算入场立即就绪的 BattleEvent（如 20041 进场召唤胚芽）。"""
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is None:
            return
        for ent in entities:
            kit = getattr(ent, "kit", None)
            if kit is not None and hasattr(kit, "_ensure_monster_dynamic_values"):
                kit._ensure_monster_dynamic_values(rt)
            self._trigger_monster_passive_abilities(ent, rt)

        # 若怪物 PassiveSkillInitiate 创建了 OnAdd 立即置零跑道 (distance_remaining == 0) 的 BattleEvent (如 20041)，
        # 按官方波次进场时序立即触发其 OnPhase1 + drain 并将距离重置为 10000.0
        for be_name in list(rt.named_targets.get("BattleEventEntityList", ())):
            be_ent = self.sim.get_entity(be_name)
            if (
                be_ent is not None
                and getattr(be_ent, "is_countdown", False)
                and not getattr(be_ent, "is_dummy", False)
                and be_ent.distance_remaining <= 1e-6
            ):
                if hasattr(self.sim, "_ready_queue") and be_name in self.sim._ready_queue:
                    self.sim._ready_queue.remove(be_name)
                if hasattr(self.sim, "_natural_due_names"):
                    self.sim._natural_due_names.discard(be_name)
                rt.modifier_engine.dispatch_event("OnPhase1", owner_id=be_name)
                sched = getattr(self.sim, "scheduler", None)
                if sched is not None:
                    sched.drain_at_boundary()
                be_ent.distance_remaining = 10000.0
        self.sync_spawned_entities()
        pending_entry = getattr(self, "_entry_weakness_break", None) if wave_index == 0 else None
        if pending_entry is not None:
            entry_elem, entry_toughness, applied_names = pending_entry
            if entry_elem and entry_toughness > 0.0:
                for ent in self.sim.entities:
                    if getattr(ent, "is_enemy", False) and ent.name not in applied_names:
                        applied_names.add(ent.name)
                        if entry_elem in getattr(ent, "weaknesses", ()):
                            ent.current_toughness = max(0.0, ent.current_toughness - float(entry_toughness))
            self._entry_weakness_break = None

    def on_damage_applied(self, event: DamageAppliedEvent) -> None:
        self._break_helper.on_damage_applied(event)

    def on_weakness_break(self, event: WeaknessBreakEvent) -> None:
        self._break_helper.on_weakness_break(event)

    def on_turn_begin(self, event: TurnBeginEvent) -> None:
        self._check_aha_special_damage_events()
        self._break_helper.on_turn_begin(event)
        actor_ent = self.sim.get_entity(event.actor_name)
        if actor_ent is not None and getattr(actor_ent, "is_countdown", False):
            sched = getattr(self.sim, "scheduler", None)
            if sched is not None and sched.has_pending():
                sched.drain_at_boundary()
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
            new_entities.sort(key=lambda e: getattr(e, "_runner_spawn_order", 0))
            self.attach_kits_to_entities(new_entities, self.runner.state.wave_index)
            rt = getattr(self.sim, "vm_runtime", None)
            for ent in new_entities:
                self.sim.add_entity(ent, trigger_battle_start=True)
                if getattr(ent, "kit", None) is not None:
                    ent.kit.port = self.port
                    if rt is not None and hasattr(ent.kit, "_ensure_monster_dynamic_values"):
                        ent.kit._ensure_monster_dynamic_values(rt)
                if rt is not None:
                    if not getattr(self.sim, "battle_started", False):
                        rt.modifier_engine.dispatch_event(
                            "OnListenCharacterCreate",
                            owner_id="__LEVEL__",
                            param_entity_id=ent.name,
                        )
                    if getattr(ent, "is_enemy", False) and hasattr(self.sim, "port"):
                        new_max = float(self.sim.port.max_hp(ent.name))
                        if new_max > ent.current_hp:
                            ent.current_hp = new_max
                            ent.max_hp = new_max
                    self._trigger_monster_passive_abilities(ent, rt)
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
            summon_id_provider=getattr(self.sim, "summon_id_provider", None),
            current_av=float(getattr(self.sim, "current_av", 0.0)),
        )
        widx = self.runner.state.wave_index
        self.attach_kits_to_entities(spawned, widx)
        rt = getattr(self.sim, "vm_runtime", None)
        for ent in spawned:
            self.sim.add_entity(ent, trigger_battle_start=True)
            if rt is not None and getattr(ent, "kit", None) is not None and hasattr(ent.kit, "_ensure_monster_dynamic_values"):
                ent.kit._ensure_monster_dynamic_values(rt)
            if rt is not None:
                self._trigger_monster_passive_abilities(ent, rt)
        self._sync_enemy_order()
        return spawned

    def _resolve_enemy_target(self, target_name: str) -> Optional[Entity]:
        ent = self.sim.get_entity(target_name)
        if ent is not None and ent.current_hp > 0:
            return ent
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
            emit_sim_event(
                self.sim,
                TurnBeginEvent(
                    av=av_key,
                    cycle=int(self.sim.current_cycle),
                    actor_id="阿哈",
                    actor_name="阿哈",
                    speed=0.0,
                    turn_id=self.sim._turn_seq,
                ),
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
        vm_rt = getattr(self.sim, "vm_runtime", None)
        gluttony_div = 1.0
        if vm_rt is not None:
            from simulator.vm.expr import dotnet_hash

            h_ft = dotnet_hash("MDF_FirstTriggered")
            h_p4 = dotnet_hash("MDF_Param4")
            for mod in vm_rt.modifier_engine.get_modifiers(ent.name):
                if "Gluttony" in mod.name and float(mod.dynamic_values.get(h_ft, 0.0)) == 1.0:
                    p4 = float(mod.dynamic_values.get(h_p4, 0.0))
                    if p4 > 0.0:
                        gluttony_div = 1.0 + p4
                        break
        raw_aha_dmg = effective_dmg / gluttony_div
        if kit is not None and hasattr(kit, "intercept_incoming_damage"):
            raw_aha_dmg = kit.intercept_incoming_damage(ent.name, raw_aha_dmg)
        actual = min(ent.current_hp, raw_aha_dmg)
        ent.current_hp = max(0.0, ent.current_hp - raw_aha_dmg)
        self.aha_special_damage += dmg
        if actual > 0.0:
            self._break_helper.add_quantum_stack(ent.name)
            if vm_rt is not None:
                vm_rt.modifier_engine.dispatch_event(
                    "OnHPChange",
                    owner_id=ent.name,
                    param_entity_id="阿哈",
                    change_value=-float(actual),
                    current_attack_type="ElationDamage",
                    param_flags=("IsHPChangeByDamage",),
                )
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
            emit_sim_event(
                self.sim,
                EnemyDefeatedEvent(
                    av=float(self.sim.current_av),
                    cycle=int(self.sim.current_cycle),
                    attacker_name="阿哈",
                    target_name=ent.name,
                ),
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
                vm_rt.lifecycle.open_enemy_attack = "阿哈"
                vm_rt.modifier_engine.dispatch_event("OnBeforeBeingHitAll", owner_id=ent.name, param_entity_id="阿哈")
                emit_sim_event(self.sim, HPLostEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=self.sim.current_cycle,
                    entity_name=ent.name,
                    amount=actual,
                    hp_left=ent.current_hp,
                    cause="attack_damage",
                ))
                vm_rt.modifier_engine.dispatch_event("OnAfterBeingHitAll", owner_id=ent.name, param_entity_id="阿哈")
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
        old_phase: Optional[int] = None
        old_hp: Optional[float] = None
        was_broken_before = False
        was_limbo_before = False
        try:
            mrs_before = self.runner.get_enemy_state(monster_name)
            old_phase = mrs_before.phase
            old_hp = float(mrs_before.entity.current_hp)
            was_broken_before = bool(mrs_before.entity.is_broken)
            was_limbo_before = bool(getattr(mrs_before.entity, "_vm_limbo_pending", False))
        except KeyError:
            pass
        new_phase = self.runner.set_monster_phase(monster_name, mode=mode, value=value)
        if old_phase is not None and new_phase == old_phase:
            return new_phase
        ent = self.sim.get_entity(monster_name)
        if ent is not None and isinstance(getattr(ent, "kit", None), DataDrivenEnemyKit):
            ent.kit.sync_phase(new_phase)
        rt = getattr(self.sim, "vm_runtime", None)
        if rt is not None:
            if was_broken_before and ent is not None and not getattr(ent, "is_broken", False):
                # Official Monster_ChangePhase triggers ExitBreakState while the entity is still
                # in pre-heal limbo, so AliveOnly=True modifiers added in OnListenEndBreak skip it.
                restore_limbo = was_limbo_before and old_hp is not None
                if restore_limbo:
                    saved_hp_after_phase = float(ent.current_hp)
                    saved_limbo_after_phase = bool(getattr(ent, "_vm_limbo_pending", False))
                    ent.current_hp = float(old_hp)
                    ent._vm_limbo_pending = True
                try:
                    rt.modifier_engine.dispatch_event(
                        "OnEndBreak",
                        owner_id=monster_name,
                        param_entity_id=monster_name,
                    )
                    rt.modifier_engine.dispatch_event(
                        "OnListenEndBreak",
                        param_entity_id=monster_name,
                    )
                finally:
                    if restore_limbo:
                        ent.current_hp = saved_hp_after_phase
                        ent._vm_limbo_pending = saved_limbo_after_phase
            if ent is not None:
                from simulator.effects import sync_hp_shared_subtargets

                sync_hp_shared_subtargets(self.sim, ent)
                if old_hp is not None and float(ent.current_hp) > old_hp + 1e-6:
                    delta_hp = float(ent.current_hp) - old_hp
                    rt.modifier_engine.dispatch_event(
                        "OnHPChange",
                        owner_id=monster_name,
                        param_entity_id=monster_name,
                        change_value=delta_hp,
                    )
                    rt.modifier_engine.dispatch_event(
                        "OnListenHPChange",
                        param_entity_id=monster_name,
                        change_value=delta_hp,
                    )
            rt.modifier_engine.dispatch_event(
                "OnMonsterPhaseChanged",
                owner_id=monster_name,
                param_entity_id=monster_name,
            )
            if rt.modifier_engine.has_behavior_flag(monster_name, "CustomEvent_MonsterChangePhaseTrigger"):
                rt.modifier_engine.dispatch_event(
                    "OnCustomEvent",
                    owner_id=monster_name,
                    param_entity_id=monster_name,
                )
        return new_phase

    def after_step(self) -> None:
        # -1. 将回合内通过 SetActionDelay(0)/100% 拉条触发自身立即再动的实体提至 _ready_queue 最前（优先于自然到点实体）
        ready_q = getattr(self.sim, "_ready_queue", None)
        if isinstance(ready_q, list) and len(ready_q) > 1:
            jumped: List[str] = []
            for nm in list(ready_q):
                ent = self.sim.get_entity(nm)
                if ent is not None and getattr(ent, "_vm_immediate_jump", False):
                    setattr(ent, "_vm_immediate_jump", False)
                    jumped.append(nm)
            if jumped:
                rest = [nm for nm in ready_q if nm not in jumped]
                ready_q[:] = jumped + rest

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

        # 3. Infinite wave slot refill if wave not yet cleared (legacy fallback when VM SummonMonsterInfinite is not active)
        src_wave = self.runner.built_stage.source_spec.waves[self.runner.state.wave_index]
        rt_inf = getattr(self.sim, "vm_runtime", None)
        has_vm_infinite_summon = bool(
            rt_inf is not None
            and rt_inf.modifier_engine.has_modifier(
                "__LEVEL__", "BattleEventAbility_SummonMonsterInfinite_Modifier"
            )
        )
        if (
            self.runner.built_stage.source_spec.stage_infinite_group_id is not None
            and not has_vm_infinite_summon
            and src_wave.max_monster_count > 0
            and 0 < len(self.runner.living_enemies()) < src_wave.max_monster_count
        ):
            refilled = self.runner.refill_infinite_wave_slot()
            self.attach_kits_to_entities(refilled, self.runner.state.wave_index)
            for ent in refilled:
                self.sim.add_entity(ent, trigger_battle_start=True)

        # 4. Wave clearance & transition
        living_formation_enemies = [
            e for e in self.runner.living_enemies() if not getattr(e, "_not_in_formation", False)
        ]
        if not living_formation_enemies:
            # 清理非参战控制器实体（如 8003060 虚构集合体）
            rt_clr = getattr(self.sim, "vm_runtime", None)
            for mrs in list(self.runner.state.enemies):
                if getattr(mrs.entity, "_not_in_formation", False):
                    mrs.entity.current_hp = 0.0
                    if rt_clr is not None:
                        rt_clr.modifier_engine.destroy_all_for_entity(mrs.entity.name)
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
                self._apply_wave_ability(self.runner.state.wave_index)
                rt = getattr(self.sim, "vm_runtime", None)
                if rt is not None:
                    # 官方 AST 规范（如 Tribbie OnWaveMonster 监听）：波次怪物入场时派发 OnWaveMonster，
                    # 激活跨波次挂起的追击/插入行动（如 OnInsertAbort_Flg 追击），并在召唤辅助实体前优先结算
                    rt.modifier_engine.dispatch_event("OnWaveMonster")
                    sched = getattr(self.sim, "scheduler", None)
                    if sched is not None and sched.can_auto_drain():
                        sched.drain()
                self._init_wave_monster_battle_events(next_wave_entities, self.runner.state.wave_index)
                if rt is not None and getattr(rt, "_battle_entered", False) and next_wave_entities:
                    rt.modifier_engine.dispatch_event(
                        "OnEnterBattle",
                        owner_ids=[e.name for e in next_wave_entities],
                    )
                    sched = getattr(self.sim, "scheduler", None)
                    if sched is not None and sched.has_pending():
                        sched.drain_at_boundary()
                        self.sync_spawned_entities()
                if rt is not None:
                    # 官方日志实证（220255 L1336、221208 L1461）：新波次入场会触发一次 turn_owner=null 的 OnTurnBegin，
                    # 用于重置各角色每回合限制标记（如知更鸟 MAvatar_RobinS_00_Passive_HyperCharge_TurnFlag）。
                    rt.modifier_engine.dispatch_event("OnListenTurnBegin", param_entity_id="__LEVEL__")

    def drain_opening_actions(self) -> None:
        """排空开战进场（OnEnterBattle）入队的插队/自动技，并同步新召唤实体。"""
        sched = getattr(self.sim, "scheduler", None)
        if sched is None or not sched.has_pending():
            return
        sched.drain_at_boundary(auto_ult=False)
        self.sync_spawned_entities()


def build_data_driven_stage(
    stage_id: int,
    team: List[Entity],
    *,
    technique_users: Optional[Sequence[str]] = None,
    auto_ult: bool = True,
    extra_maze_buff_ids: Sequence[int] = (),
    entry_element: Optional[str] = None,
    entry_toughness: float = 10.0,
    defer_opening_drain: bool = False,
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

    entry_elem: Optional[str] = None
    if team:
        raw_elem = entry_element if entry_element else getattr(team[0], "element", None)
        entry_elem = str(raw_elem).capitalize() if raw_elem else None
        if entry_elem and entry_toughness > 0.0:
            for e in wave0_enemies:
                if entry_elem in getattr(e, "weaknesses", ()):
                    e.current_toughness = max(0.0, e.current_toughness - float(entry_toughness))

    norm_tech_users = (
        [u[:-2] if isinstance(u, str) and u.endswith("_旧") else u for u in technique_users]
        if technique_users is not None
        else None
    )
    def _apply_pre_tech_stage_setup(sim_inst: TurnSimulator) -> None:
        from simulator.vm.runtime import ensure_vm_runtime
        from simulator.vm.target_alias import ExecutionContext

        sim_inst._entry_element = entry_elem
        allies_pre = [
            e for e in sim_inst.entities
            if not getattr(e, "is_enemy", False) and not getattr(e, "is_countdown", False)
        ]
        has_vm_ally = any(hasattr(getattr(e, "kit", None), "_ensure_registered") for e in allies_pre)
        if not has_vm_ally and not extra_maze_buff_ids:
            return
        rt = ensure_vm_runtime(sim_inst, loader=runner.factory.game_loader)
        rt.loader.ensure_ability_index()
        if (
            has_vm_ally
            and allies_pre
            and rt.loader.get_global_modifier("StageAbility_MazeCommon_EnterBattle_MarkTeamLeader") is not None
        ):
            rt.modifier_engine.add_modifier(
                owner_id=allies_pre[0].name,
                caster_id="__LEVEL__",
                mod_name="StageAbility_MazeCommon_EnterBattle_MarkTeamLeader",
                ability_name="StageAbility_MazeCommon_EnterBattle_CheckTeamLeader",
            )
        has_elation_ally = any(
            str(getattr(e, "path", "") or "").upper() in ("ELATION", "欢愉")
            for e in allies_pre
        )
        if (
            getattr(runner.built_stage, "stage_type", "") != "FateRin"
            and has_elation_ally
            and rt.loader.get_ability("StageAbility_Elation") is not None
        ):
            rt.trigger_ability(caster_id="__LEVEL__", ability_name="StageAbility_Elation", target_ids=("__LEVEL__",))

        if not extra_maze_buff_ids:
            return
        stage_loader = getattr(runner.factory, "stage_loader", None)
        if stage_loader is None or not hasattr(stage_loader, "resolve_maze_buff_abilities"):
            return
        affixes = stage_loader.resolve_maze_buff_abilities(extra_maze_buff_ids)
        if not affixes:
            return
        maze_buff_param_hashes = (462955996, 59671469, 1625755410, 866240523, -1862642832)

        for ab_name, params in affixes:
            ab = rt.loader.get_ability(ab_name)
            if not ab:
                continue
            init_dyn = {}
            for idx, val in enumerate(params):
                if idx < len(maze_buff_param_hashes):
                    h = maze_buff_param_hashes[idx]
                    init_dyn[h] = float(val)
                    rt.set_dynamic_value("__LEVEL__", h, float(val), ability_name=ab_name)
            on_add = ab.get("OnAdd") or []
            if on_add:
                ctx = ExecutionContext(
                    runtime=rt,
                    caster_id="__LEVEL__",
                    ability_name=ab_name,
                    ability_target_ids=("__LEVEL__",),
                    modifier_owner_id="__LEVEL__",
                    local_dynamics=dict(init_dyn),
                )
                rt.executor.execute_tasks(on_add, ctx)
            for mod in rt.modifier_engine.get_modifiers("__LEVEL__"):
                if mod.ability_name == ab_name:
                    for idx, val in enumerate(params):
                        if idx < len(maze_buff_param_hashes):
                            mod.dynamic_values[maze_buff_param_hashes[idx]] = float(val)
        for ent in list(sim_inst.entities):
            if getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False):
                continue
            rt.modifier_engine.dispatch_event("OnListenCharacterCreate", param_entity_id=ent.name)
            new_mhp = float(ent.max_hp)
            if new_mhp > ent.current_hp:
                ent.current_hp = new_mhp

    sim = TurnSimulator(
        entities=list(team) + list(wave0_enemies),
        use_techniques=bool(norm_tech_users),
        technique_users=norm_tech_users,
        auto_ult=auto_ult,
        pre_technique_hook=_apply_pre_tech_stage_setup,
        defer_opening_drain=defer_opening_drain,
    )
    director = DataDrivenStageDirector(sim, runner, ai_loader)
    if entry_elem and entry_toughness > 0.0:
        director._entry_weakness_break = (
            entry_elem,
            float(entry_toughness),
            {e.name for e in wave0_enemies},
        )
    prev_auto_ult = getattr(sim, "auto_ult", False)
    sim.auto_ult = False
    try:
        director.attach_kits_to_entities(wave0_enemies, wave_index=0)
        director._init_wave_monster_battle_events(wave0_enemies, wave_index=0)
        rt_post = getattr(sim, "vm_runtime", None)
        if extra_maze_buff_ids and rt_post is not None:
            for e in wave0_enemies:
                rt_post.modifier_engine.dispatch_event("OnListenCharacterCreate", param_entity_id=e.name)
        if rt_post is not None and getattr(rt_post, "_battle_entered", False):
            w0_all_enemies = [
                e.name
                for e in sim.entities
                if getattr(e, "is_enemy", False) and not getattr(e, "is_countdown", False)
            ]
            if w0_all_enemies:
                rt_post.modifier_engine.dispatch_event("OnEnterBattle", owner_ids=w0_all_enemies)
                if not defer_opening_drain:
                    director.drain_opening_actions()
    finally:
        sim.auto_ult = prev_auto_ult
    return sim, director

"""官方 ConfigAbility 运行时协调器与 Kit/Relic/LightCone 适配器 (Phase 3/4)。

提供：
- `VMRuntime`：挂载于 `TurnSimulator` 的官方配置运行时，统一托管所有 VM 实体的 DynamicValues、
  ModifierEngine、TaskExecutor 与统一升序 `OnEnterBattle` 进场流水线；
- `ConfigAbilityKitAdapter`：完全实现 `KitHandler` 协议，令任意角色无缝接入 `TurnSimulator`；
- `ConfigAbilityEquipmentAdapter` / `ConfigAbilityRelicAdapter`：用官方配置替代手写光锥与遗器处理器。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..actions import AbilityDefinition, ActionContext, ActionKind, ResourceCost, TargetMode
from ..entity import Entity
from ..events import (
    ActionEndEvent,
    ActionExecuteEvent,
    EnemyDefeatedEvent,
    HealAppliedEvent,
    HPLostEvent,
    SpiritDespawnEvent,
    SpiritSummonedEvent,
    TurnBeginEvent,
    TurnEndEvent,
)
from ..protocols import KitHandler, LightConeHandler, RelicSetHandler
from ..status import StatType
from .executor import TaskExecutor
from .loader import CompiledCharacterSpec, GameDataLoader
from .modifier_engine import ModifierEngine, VMModifierInstance
from .target_alias import ExecutionContext


class VMRuntime:
    """挂载在 TurnSimulator 上的官方 ConfigAbility 统一运行时。"""

    def __init__(self, sim: Any, loader: Optional[GameDataLoader] = None, *, strict: bool = True) -> None:
        self.sim = sim
        self.loader = loader or GameDataLoader()
        self.modifier_engine = ModifierEngine(self)
        self.executor = TaskExecutor(self, strict=strict)
        self.entity_specs: Dict[str, CompiledCharacterSpec] = {}
        # entity_name -> {hash_int: float}
        self.entity_dynamics: Dict[str, Dict[int, float]] = {}
        # 动态注册目标名 (如 RobinS_Partner02 -> [entity_name])
        self.named_targets: Dict[str, List[str]] = {}
        # 已激活的装备 / 遗器能力上下文：(owner_id, ability_name) -> {hash_int: float}
        self.equip_dynamics: Dict[Tuple[str, str], Dict[int, float]] = {}
        self.global_target_aliases: Dict[str, Any] = {}
        self._global_aliases_loaded: bool = False
        self._battle_entered: bool = False
        self._in_turn_phase1_end: bool = False
        self._attack_scope_depth: int = 0
        self._attack_targets_by_key: Dict[Tuple[int, str], List[str]] = {}
        self._pending_after_attack: Optional[Tuple[int, str, Dict[str, Any], str]] = None
        self._open_enemy_attack: Optional[str] = None
        self._active_skill_sp_base: float = 0.0
        self._skill_sp_ratio_granted: bool = False
        self._added_abilities: Set[Tuple[str, str]] = set()
        self.elation_points: float = 0.0
        self._attack_blocked_targets: Set[str] = set()
        self._entity_is_enemy: Dict[str, bool] = {
            e.name: bool(getattr(e, "is_enemy", False))
            for e in getattr(sim, "entities", ())
            if getattr(e, "name", None)
        }

        # 订阅 TurnSimulator 核心事实事件，转发给官方 Modifier 引擎
        self.control_skill_mapping: Dict[Tuple[str, str], str] = {}
        self.turn_control_skill_snapshot: Dict[str, str] = {}
        self.dynamic_entity_params: Dict[Tuple[str, str], List[str]] = {}
        self.sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        self.sim.event_bus.subscribe(TurnEndEvent, self._on_turn_end)
        self.sim.event_bus.subscribe(ActionExecuteEvent, self._on_action_execute)
        self.sim.event_bus.subscribe(ActionEndEvent, self._on_action_end)
        self.sim.event_bus.subscribe(HPLostEvent, self._on_hp_lost)
        self.sim.event_bus.subscribe(HealAppliedEvent, self._on_heal_applied)
        self.sim.event_bus.subscribe(SpiritDespawnEvent, self._on_spirit_despawn)
        self.sim.event_bus.subscribe(EnemyDefeatedEvent, self._on_enemy_defeated)

    def resolve_global_target_alias(self, alias_name: str) -> Optional[Dict[str, Any]]:
        if not self._global_aliases_loaded:
            self.loader.ensure_ability_index()
            for data in self.loader._file_cache.values():
                if isinstance(data, dict) and isinstance(data.get("GlobalTargetAlias"), dict):
                    self.global_target_aliases.update(data["GlobalTargetAlias"])
            self._global_aliases_loaded = True
        return self.global_target_aliases.get(alias_name)

    def begin_attack_scope(self) -> None:
        self._attack_scope_depth += 1

    def trigger_or_defer_limbo(self, owner_id: str, param_entity_id: Optional[str]) -> bool:
        """若当前处于攻击作用域或死亡批处理（OnBeforeDying）中，将转阶段回血延后至结算完成后触发，防止附加/真伤或自伤误扣新阶段 HP。"""
        if getattr(self, "_in_dying_batch", False) or getattr(self, "_attack_scope_depth", 0) > 0:
            q = getattr(self, "_pending_limbo_after_dying", None)
            if q is None:
                q = []
                self._pending_limbo_after_dying = q
            if not any(tid == owner_id for tid, _ in q):
                q.append((owner_id, param_entity_id))
            return True
        return False

    def flush_pending_after_attack(self) -> None:
        after_end_payload: Optional[Tuple[Tuple[str, ...], str, Dict[str, Any], str]] = None
        if self._pending_after_attack is not None:
            pending = self._pending_after_attack
            atk_seq, caster_id, dmg_data, atk_type = pending[:4]
            skill_type = pending[4] if len(pending) > 4 else atk_type
            self._pending_after_attack = None
            all_targets = tuple(self._attack_targets_by_key.get((atk_seq, caster_id), ()))
            after_set = getattr(self, "_after_attack_fired", None)
            if after_set is None:
                after_set = set()
                self._after_attack_fired = after_set
            after_key = (atk_seq, caster_id)
            if after_key not in after_set:
                after_set.add(after_key)
                after_end_payload = (all_targets, caster_id, dmg_data, atk_type)
                self._in_after_attack = True
                try:
                    self.modifier_engine.dispatch_event(
                        "OnAfterAttack",
                        owner_id=caster_id,
                        attack_target_ids=all_targets,
                        damage_data=dmg_data,
                        current_skill_type=skill_type,
                        current_attack_type=atk_type,
                    )
                    self.modifier_engine.dispatch_event(
                        "OnListenAfterAttack",
                        param_entity_id=caster_id,
                        attack_target_ids=all_targets,
                        damage_data=dmg_data,
                        current_skill_type=skill_type,
                        current_attack_type=atk_type,
                    )
                    for tid in all_targets:
                        self.modifier_engine.dispatch_event(
                            "OnAfterBeingAttacked",
                            owner_id=tid,
                            param_entity_id=caster_id,
                            damage_data=dmg_data,
                            current_attack_type=atk_type,
                        )
                finally:
                    self._in_after_attack = False
        pending_dying = getattr(self, "_pending_dying_enemies", None)
        if pending_dying:
            dying_batch = list(pending_dying)
            pending_dying.clear()
            prev_in_dying = getattr(self, "_in_dying_batch", False)
            self._in_dying_batch = True
            try:
                for dead_tid, killer_id in dying_batch:
                    dead_ent = self.sim.get_entity(dead_tid)
                    if dead_ent is not None:
                        self.record_entity_team(dead_ent)
                    self.modifier_engine.dispatch_event("OnBeforeDying", owner_id=dead_tid, param_entity_id=killer_id)
                    self.modifier_engine.dispatch_event("OnBeingLimbo", owner_id=dead_tid, param_entity_id=killer_id)
                    dead_ent = self.sim.get_entity(dead_tid)
                    if dead_ent is not None and getattr(dead_ent, "_in_deathrattle_limbo", False):
                        self.modifier_engine.strip_for_deathrattle(dead_tid)
                    active_dr = getattr(self, "_active_deathrattle_entities", None)
                    if active_dr is None:
                        active_dr = set()
                        self._active_deathrattle_entities = active_dr
                    active_dr.add(dead_tid)
                    try:
                        self.modifier_engine.dispatch_event("OnDeathrattle", owner_id=dead_tid, param_entity_id=killer_id)
                    finally:
                        active_dr.discard(dead_tid)
                    self.finalize_inline_deathrattle(dead_tid)
            finally:
                self._in_dying_batch = prev_in_dying
        pending_listen = getattr(self, "_pending_listen_die", None)
        if pending_listen:
            self._flushing_listen_die = True
            try:
                while pending_listen:
                    listen_batch = list(pending_listen)
                    pending_listen.clear()
                    for dead_id in listen_batch:
                        self.modifier_engine.dispatch_event("OnListenCharacterDie", param_entity_id=dead_id)
            finally:
                self._flushing_listen_die = False
        if not getattr(self, "_in_dying_batch", False):
            pending_limbo = getattr(self, "_pending_limbo_after_dying", None)
            if pending_limbo:
                limbo_batch = list(pending_limbo)
                pending_limbo.clear()
                for limbo_tid, limbo_killer in limbo_batch:
                    ent = self.sim.get_entity(limbo_tid)
                    kit = getattr(ent, "kit", None) if ent is not None else None
                    runner = getattr(kit, "runner", None) if kit is not None else None
                    if runner is not None:
                        try:
                            mrs = runner.get_enemy_state(limbo_tid)
                            setattr(mrs, "_limbo_pending", False)
                        except KeyError:
                            pass
                    self.modifier_engine.dispatch_event(
                        "OnLimboWaitHeal",
                        owner_id=limbo_tid,
                        param_entity_id=limbo_killer,
                    )
        pending_lvl = getattr(self, "_pending_level_kills", None)
        while pending_lvl:
            lvl_batch = list(pending_lvl)
            pending_lvl.clear()
            for dead_tid, eff_killer in lvl_batch:
                ent = self.sim.get_entity(dead_tid)
                if ent is None:
                    continue
                self.modifier_engine.dispatch_event("OnBeforeDying", owner_id=dead_tid, param_entity_id=eff_killer)
                self.sim.event_bus.publish(
                    EnemyDefeatedEvent(
                        av=float(self.sim.current_av),
                        cycle=int(self.sim.current_cycle),
                        attacker_name=eff_killer,
                        target_name=dead_tid,
                    )
                )
                self.modifier_engine.destroy_all_for_entity(dead_tid)
                self.sim.entities[:] = [e for e in self.sim.entities if e.name != dead_tid]
        if after_end_payload is not None:
            end_targets, end_caster, end_dmg_data, end_atk_type = after_end_payload
            self._in_after_attack = True
            try:
                for tid in end_targets:
                    self.modifier_engine.dispatch_event(
                        "OnAfterBeingAttackedEnd",
                        owner_id=tid,
                        param_entity_id=end_caster,
                        damage_data=end_dmg_data,
                        current_attack_type=end_atk_type,
                    )
            finally:
                self._in_after_attack = False
        if self._attack_blocked_targets:
            self._attack_blocked_targets.clear()
        pending_dead = getattr(self, "_pending_dead_enemies", None)
        if pending_dead:
            remaining_dead = []
            for dead_tid in list(pending_dead):
                dead_ent = self.sim.get_entity(dead_tid)
                if dead_ent is not None and getattr(dead_ent, "_in_deathrattle_limbo", False):
                    remaining_dead.append(dead_tid)
                else:
                    self.modifier_engine.destroy_all_for_entity(dead_tid)
            pending_dead[:] = remaining_dead

    def end_attack_scope(self) -> None:
        self._attack_scope_depth = max(0, self._attack_scope_depth - 1)
        if self._attack_scope_depth == 0:
            self.flush_pending_after_attack()

    def begin_being_attacked(self, attacker_name: str, target_ids: Sequence[str]) -> None:
        if self._open_enemy_attack is not None:
            self.end_being_attacked(self._open_enemy_attack)
        self._open_enemy_attack = attacker_name
        for tid in target_ids:
            self.modifier_engine.dispatch_event(
                "OnBeforeBeingAttacked",
                owner_id=tid,
                param_entity_id=attacker_name,
            )

    def end_being_attacked(self, attacker_name: Optional[str] = None) -> None:
        atk = attacker_name or self._open_enemy_attack
        if atk is None:
            return
        if self._open_enemy_attack == atk or attacker_name is None:
            self._open_enemy_attack = None
        self.modifier_engine.dispatch_event("OnListenAfterAttack", param_entity_id=atk)

    def record_entity_team(self, entity: Any) -> None:
        if entity is not None and getattr(entity, "name", None):
            self._entity_is_enemy[entity.name] = bool(getattr(entity, "is_enemy", False))

    def finalize_inline_deathrattle(self, entity_id: str) -> None:
        """若实体无异步亡语插入动作且 HP<=0，则立即结束亡语悬停态并销毁 Modifier。"""
        ent = self.sim.get_entity(entity_id)
        if (
            ent is not None
            and getattr(ent, "_in_deathrattle_limbo", False)
            and int(getattr(ent, "_pending_deathrattle_actions", 0) or 0) == 0
            and float(getattr(ent, "current_hp", 0.0)) <= 0.0
        ):
            setattr(ent, "_die_immediately_after_deathrattle", False)
            setattr(ent, "_in_deathrattle_limbo", False)
            ent.current_hp = 0.0
            self.modifier_engine.destroy_all_for_entity(entity_id)

    def is_enemy_entity_id(self, entity_id: Optional[str]) -> bool:
        if not entity_id or entity_id == "__LEVEL__":
            return False
        ent = self.sim.get_entity(entity_id)
        if ent is not None:
            is_en = bool(getattr(ent, "is_enemy", False))
            self._entity_is_enemy[entity_id] = is_en
            return is_en
        return self._entity_is_enemy.get(entity_id, False)

    def register_character(self, entity_name: str, spec: CompiledCharacterSpec) -> None:
        self.entity_specs[entity_name] = spec
        self.entity_dynamics[entity_name] = dict(spec.dynamic_floats)
        self.record_entity_team(self.sim.get_entity(entity_name))

    def register_equip_ability(self, owner_id: str, ability_name: str, dyn_floats: Dict[int, float]) -> None:
        self.equip_dynamics[(owner_id, ability_name)] = dict(dyn_floats)

    def resolve_hash(
        self,
        caster_id: str,
        hash_val: int,
        *,
        ability_name: str = "",
        local_ctx: Optional[ExecutionContext] = None,
    ) -> float:
        if local_ctx is not None:
            if hash_val in local_ctx.local_dynamics:
                return local_ctx.local_dynamics[hash_val]
            if local_ctx.modifier_instance is not None and hash_val in local_ctx.modifier_instance.dynamic_values:
                return local_ctx.modifier_instance.dynamic_values[hash_val]
        if ability_name:
            if (caster_id, ability_name) in self.equip_dynamics:
                eq_map = self.equip_dynamics[(caster_id, ability_name)]
                if hash_val in eq_map:
                    return eq_map[hash_val]
            ent = self.sim.get_entity(caster_id)
            if ent is not None and getattr(ent, "master_name", None):
                m_eq = self.equip_dynamics.get((ent.master_name, ability_name))
                if m_eq and hash_val in m_eq:
                    return m_eq[hash_val]
        dyn = self.entity_dynamics.get(caster_id)
        if dyn and hash_val in dyn:
            return dyn[hash_val]
        # 若为忆灵且未找到（可能引用主人参数），尝试回溯主人上下文
        ent = self.sim.get_entity(caster_id)
        if ent is not None and getattr(ent, "master_name", None):
            m_dyn = self.entity_dynamics.get(ent.master_name)
            if m_dyn and hash_val in m_dyn:
                return m_dyn[hash_val]
        # 若为由其他实体（如 __LEVEL__）挂载光环/Modifier 产生的子状态，回溯至 modifier caster_id
        if local_ctx is not None and local_ctx.modifier_instance is not None:
            mod_caster = getattr(local_ctx.modifier_instance, "caster_id", None)
            if mod_caster:
                mc_dyn = self.entity_dynamics.get(mod_caster)
                if mc_dyn and hash_val in mc_dyn:
                    return mc_dyn[hash_val]
        return 0.0

    def get_dynamic_value(
        self,
        entity_id: str,
        key_hash: int,
        *,
        ability_name: str = "",
        local_ctx: Optional[ExecutionContext] = None,
    ) -> float:
        return self.resolve_hash(entity_id, key_hash, ability_name=ability_name, local_ctx=local_ctx)

    def set_dynamic_value(
        self,
        entity_id: str,
        key_hash: int,
        value: float,
        *,
        modifier: Optional[VMModifierInstance] = None,
        ability_name: str = "",
    ) -> None:
        if modifier is not None:
            old_val = modifier.dynamic_values.get(key_hash, 0.0)
            modifier.dynamic_values[key_hash] = float(value)
        else:
            dyn = self.entity_dynamics.setdefault(entity_id, {})
            old_val = dyn.get(key_hash, 0.0)
            dyn[key_hash] = float(value)
            if ability_name and (entity_id, ability_name) in self.equip_dynamics:
                eq = self.equip_dynamics[(entity_id, ability_name)]
                if key_hash in eq:
                    eq[key_hash] = float(value)
        self.modifier_engine.check_dynamic_value_changes(entity_id, key_hash, old_val, float(value))

    def modify_elation_points(self, value: float, *, mode: str = "add") -> None:
        old_val = float(self.elation_points)
        if mode == "set":
            new_val = max(0.0, float(value))
        else:
            new_val = max(0.0, old_val + float(value))
        actual_delta = new_val - old_val
        self.elation_points = new_val
        self.modifier_engine.check_elation_point_changes(old_val, new_val, actual_delta)

    def find_template(self, tpl_name: str, ability_name: str = "") -> Optional[List[Dict[str, Any]]]:
        if ability_name:
            ab = self.loader.get_ability(ability_name)
            if ab:
                for tpl in ab.get("TaskListTemplate", []):
                    if tpl.get("Name") == tpl_name:
                        return tpl.get("TaskList", [])
        for spec in self.entity_specs.values():
            for ab in spec.abilities.values():
                for tpl in ab.get("TaskListTemplate", []):
                    if tpl.get("Name") == tpl_name:
                        return tpl.get("TaskList", [])
        return self.loader.get_global_template(tpl_name)

    def execute_tasks(self, tasks: Sequence[Mapping[str, Any]], ctx: ExecutionContext) -> None:
        self.executor.execute_tasks(tasks, ctx)

    def trigger_ability(
        self,
        *,
        caster_id: str,
        ability_name: str,
        target_ids: Tuple[str, ...] = (),
        skill_target_ids: Tuple[str, ...] = (),
        current_skill_type: str = "",
        current_attack_type: str = "",
    ) -> None:
        ab = self.loader.get_ability(ability_name)
        if ab is None:
            return
        tgt_info = (ab.get("TargetInfo") or {}).get("TargetType", "")
        eff_targets = skill_target_ids if (tgt_info == "SkillTargetEntityList" and skill_target_ids) else target_ids
        ctx = ExecutionContext(
            runtime=self,
            caster_id=caster_id,
            ability_name=ability_name,
            ability_target_ids=eff_targets,
            skill_target_ids=skill_target_ids or eff_targets,
            current_skill_type=current_skill_type,
            current_attack_type=current_attack_type,
        )
        has_add = bool(ab.get("OnAdd"))
        has_start = "OnStart" in ab
        if has_add and has_start:
            add_key = (caster_id, ability_name)
            if add_key not in self._added_abilities:
                self._added_abilities.add(add_key)
                self.executor.execute_tasks(ab.get("OnAdd", []), ctx)
        tasks = ab.get("OnStart") if has_start else ab.get("OnAdd", [])
        self.executor.execute_tasks(tasks, ctx)

    def collect_hit_modifiers(
        self,
        attacker_id: str,
        target_ids: Tuple[str, ...],
        *,
        attack_type: str = "ElementDamage",
    ) -> Dict[str, Any]:
        """收集非 TaskExecutor._execute_damage 发起的命中（如弱点击破 / 量子纠缠）在 VM 中的 OnBeforeHitAll 修饰。"""
        dmg_data: Dict[str, Any] = {}
        self.modifier_engine.dispatch_event(
            "OnBeforeHitAll",
            owner_id=attacker_id,
            attack_target_ids=target_ids,
            damage_data=dmg_data,
            current_attack_type=attack_type,
        )
        self.modifier_engine.dispatch_event(
            "OnListenBeforeHitAll",
            param_entity_id=attacker_id,
            attack_target_ids=target_ids,
            damage_data=dmg_data,
            current_attack_type=attack_type,
        )
        return dmg_data

    def enter_battle(self) -> None:
        """统一执行所有 VM 实体的进场被动、装备/遗器初始化，并按官方 Priority 升序触发 OnEnterBattle。"""
        if self._battle_entered:
            return
        self._battle_entered = True
        # 1. 进场前先刷新一次常驻属性区间监听（如风堇行迹 PointB3 速度转治疗加成），确保秘技/进场技能生效时享受足额面板
        for e in list(self.sim.entities):
            self.modifier_engine.check_property_changes(e.name)
        # 2. 触发 OnEnterBattle
        self.modifier_engine.dispatch_event("OnEnterBattle")
        # 3. 进场结算完成后再次刷新所有实体的属性区间监听（如风堇速度 > 200 暴风停歇）
        for e in list(self.sim.entities):
            self.modifier_engine.check_property_changes(e.name)

    def summon_servant(
        self,
        master_id: str,
        servant_id: int,
        *,
        init_dynamics: Optional[Dict[int, float]] = None,
    ) -> Optional[Entity]:
        """由官方 CreateServant 任务调用：按 AvatarServantConfig 继承公式生成并挂载伴生忆灵。"""
        master = self.sim.get_entity(master_id)
        if master is None:
            return None
        spec_master = self.entity_specs.get(master_id)
        eidolon = spec_master.eidolon if spec_master else int(getattr(master, "eidolon", 0))
        inh = self.loader.get_servant_base_inheritance(servant_id, eidolon=eidolon)
        sv_spec = self.loader.load_servant(servant_id, owner_avatar_id=spec_master.unit_id if spec_master else None, eidolon=eidolon)

        from ..golden.models import SERVANT_NAMES
        sv_name = SERVANT_NAMES.get(servant_id, f"Servant_{servant_id}")

        master_base_hp = float(getattr(master, "base_max_hp", 0.0) or self.sim.port.max_hp(master_id))
        master_white_hp = float(getattr(master, "base_white_hp", 0.0) or master_base_hp)
        sv_max_hp = inh["hp_base"] + master_base_hp * inh["hp_inherit"]
        sv_white_hp = master_white_hp * inh["hp_inherit"]
        sv_speed = inh["speed_base"] + float(master.base_speed) * inh["speed_inherit"]
        sv_white_speed = float(inh["speed_base"]) + float(getattr(master, "base_white_speed", 0.0) or 0.0) * float(inh["speed_inherit"])

        sv_entity = self.sim.get_entity(sv_name)
        if sv_entity is None:
            sv_entity = Entity(
                name=sv_name,
                base_speed=max(1.0, sv_speed) if sv_speed > 0 else 1.0,
                base_atk=master.base_atk,
                base_crit_rate=master.base_crit_rate,
                base_crit_dmg=master.base_crit_dmg,
                base_outgoing_healing=getattr(master, "base_outgoing_healing", 0.0),
                max_hp=sv_max_hp,
                current_hp=sv_max_hp,
                base_white_hp=sv_white_hp,
                base_white_speed=sv_white_speed,
                base_white_atk=getattr(master, "base_white_atk", 0.0),
                base_white_def=getattr(master, "base_white_def", 0.0),
                base_def=master.base_def,
                base_effect_res=getattr(master, "base_effect_res", 0.10),
                base_effect_hit_rate=getattr(master, "base_effect_hit_rate", 0.0),
                base_break_effect=getattr(master, "base_break_effect", 0.0),
                base_err=getattr(master, "base_err", 1.0),
                base_dmg_boost=getattr(master, "base_dmg_boost", 0.0),
                element=master.element,
                path=master.path,
                is_memosprite=True,
                master_name=master_id,
                avatar_id=servant_id,
                eidolon=eidolon,
                kit=ConfigAbilityKitAdapter(sv_name, servant_id, eidolon=eidolon, runtime=self, is_servant=True),
            )
            self.sim.add_entity(sv_entity, trigger_battle_start=False)
        else:
            sv_entity.base_max_hp = sv_max_hp
            sv_entity.base_white_hp = sv_white_hp
            sv_entity.base_white_speed = sv_white_speed
            sv_entity.base_dmg_boost = getattr(master, "base_dmg_boost", 0.0)
            sv_entity.current_hp = sv_max_hp
            sv_entity.master_name = master_id

        self.register_character(sv_name, sv_spec)
        if getattr(sv_entity, "kit", None) is not None:
            if hasattr(sv_entity.kit, "_registered"):
                sv_entity.kit._registered = True
            if hasattr(sv_entity.kit, "_passives_triggered"):
                sv_entity.kit._passives_triggered = True
        if init_dynamics:
            self.entity_dynamics[sv_name].update(init_dynamics)

        # 清理旧的技能槽映射，再触发忆灵自身被动与入场能力（SkillP* 仅触发 EntryAbility / 被动，禁止误触 _Resummon/_Insert）
        for k in [k for k in self.control_skill_mapping if k[0] == sv_name]:
            self.control_skill_mapping.pop(k, None)
        self.turn_control_skill_snapshot.pop(sv_name, None)
        seen_init: set[str] = set()
        for ab_name in sv_spec.config.get("AbilityList", []):
            if "PassiveSkill" in ab_name and ab_name not in seen_init:
                seen_init.add(ab_name)
                self.trigger_ability(caster_id=sv_name, ability_name=ab_name, target_ids=(sv_name,))
        sv_entry_map = {
            s.get("Name", ""): s.get("EntryAbility", "")
            for s in sv_spec.config.get("SkillList", [])
            if isinstance(s, dict)
        }
        for item in sv_spec.config.get("SkillAbilityList", []):
            sk = item.get("Skill", "")
            if sk.startswith("SkillP"):
                entry_ab = sv_entry_map.get(sk, "")
                candidates = [entry_ab] if entry_ab else [
                    a for a in item.get("AbilityList", [])
                    if ("Passive" in a or "BattleCry" in a or "DeathRattle" in a)
                    and not any(bad in a for bad in ("Insert", "Resummon", "Camera"))
                ]
                for ab_name in candidates:
                    if ab_name and ab_name not in seen_init:
                        seen_init.add(ab_name)
                        self.trigger_ability(caster_id=sv_name, ability_name=ab_name, target_ids=(sv_name,))

        # 基础速度为 0 的忆灵不进入自然跑道（由官方 AvatarServantConfig.SpeedBase=0 / SpeedOverride 决定）
        if float(getattr(sv_entity, "base_speed", 0.0)) <= 0.0:
            sv_entity.distance_remaining = 1e12

        # 通知全队光环 / OnListenCharacterCreate，并按最新光环刷新满血上限
        self.modifier_engine.on_entity_created(sv_name)
        full_hp = float(self.sim.port.max_hp(sv_name))
        if full_hp > 0:
            sv_entity.current_hp = full_hp

        # 发布官方 SpiritSummonedEvent 并通知关卡机制插件 (如血噬)
        self.sim.event_bus.publish(SpiritSummonedEvent(
            av=round(getattr(self.sim, "current_av", 0.0), 2),
            cycle=getattr(self.sim, "current_cycle", 0),
            owner_name=master_id,
            spirit_name=sv_name,
        ))
        for plugin in getattr(self.sim, "stage_plugins", []):
            if hasattr(plugin, "on_entity_summoned"):
                plugin.on_entity_summoned(sv_entity, self.sim)
        return sv_entity

    # ------------------------------------------------------------------
    # EventBus 桥接回调
    # ------------------------------------------------------------------
    def _on_turn_begin(self, evt: TurnBeginEvent) -> None:
        # 实机日志已证实 (184845 [961..966], 204943 [637..640], 155925 [304..305])：
        # TurnPhase1 顺序：OnPhase1 -> OnListenTurnBegin -> OnListenTurnPhase1Begin
        # -> OnListenBeforeTurnPhase1End (血嗜等回合开始扣血 & 伴生小伊卡回血，此时 Phase1End 到期光环仍在！)
        # -> ModifierPhase1End (回合开始到期光环结算) -> OnActionPhaseBegin；
        # 终结技/追击等额外行动不经过 TurnBegin，不触发 OnPhase1。
        self.modifier_engine.dispatch_event("OnPhase1", owner_id=evt.actor_name)
        self.modifier_engine.dispatch_event("OnListenTurnBegin", param_entity_id=evt.actor_name)
        self.modifier_engine.dispatch_event("OnListenTurnPhase1Begin", param_entity_id=evt.actor_name)
        self.turn_control_skill_snapshot[evt.actor_name] = self.control_skill_mapping.get((evt.actor_name, "ControlSkill01"), "Skill01")
        self._in_turn_phase1_end = True
        try:
            self.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=evt.actor_name)
        finally:
            self._in_turn_phase1_end = False
        actor_ent = self.sim.get_entity(evt.actor_name)
        if actor_ent is not None and not getattr(actor_ent, "is_enemy", False):
            sched = getattr(self.sim, "scheduler", None)
            if sched is not None and sched.has_pending():
                sched.drain()
                director = getattr(self.sim, "_stage_director", None)
                if director is not None and hasattr(director, "sync_spawned_entities"):
                    director.sync_spawned_entities()
        self.modifier_engine.tick_life_step("ModifierPhase1End", evt.actor_name)
        self.modifier_engine.dispatch_event("OnActionPhaseBegin", owner_id=evt.actor_name)
        if actor_ent is not None and not getattr(actor_ent, "is_enemy", False):
            sched = getattr(self.sim, "scheduler", None)
            if sched is not None and sched.has_pending():
                sched.drain()
                director = getattr(self.sim, "_stage_director", None)
                if director is not None and hasattr(director, "sync_spawned_entities"):
                    director.sync_spawned_entities()

    def _on_turn_end(self, evt: TurnEndEvent) -> None:
        self.turn_control_skill_snapshot.pop(evt.actor_name, None)
        self.end_being_attacked()
        self._in_turn_phase1_end = True
        try:
            self.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=evt.actor_name)
            self.modifier_engine.dispatch_event("OnListenTurnEnd", param_entity_id=evt.actor_name)
            self.modifier_engine.tick_life_step("TurnEnd", evt.actor_name)
        finally:
            self._in_turn_phase1_end = False
        ent = self.sim.get_entity(evt.actor_name)
        if ent is not None and getattr(ent, "is_enemy", False) and getattr(ent, "current_hp", 0.0) > 0.0:
            self.modifier_engine.dispatch_event("OnPhase2", owner_id=evt.actor_name, param_entity_id=evt.actor_name)
            sched_p2 = getattr(self.sim, "scheduler", None)
            if sched_p2 is not None and sched_p2.has_pending():
                prev_d2 = getattr(sched_p2, "_action_frame_depth", 0)
                sched_p2._action_frame_depth = 0
                try:
                    sched_p2.drain()
                finally:
                    sched_p2._action_frame_depth = prev_d2
            self.end_being_attacked()

    @staticmethod
    def _normalize_skill_type(evt: Any) -> str:
        kind = getattr(evt, "action_kind", None)
        if kind == ActionKind.BASIC:
            return "Normal"
        if kind == ActionKind.SKILL:
            return "Skill"
        if kind == ActionKind.ULTIMATE:
            return "Ultra"
        if kind == ActionKind.MEMOSPRITE_SKILL:
            return "Servant"
        if kind == ActionKind.FOLLOW_UP:
            return "Pursued"
        if kind == ActionKind.TECHNIQUE:
            return "Maze"
        at = str(getattr(evt, "action_type", ""))
        if "Basic" in at or at == "普攻":
            return "Normal"
        if "Skill" in at or at == "战技":
            return "Skill"
        if "Ult" in at or at == "终结技":
            return "Ultra"
        if "Memo" in at or "Servant" in at or at == "忆灵技":
            return "Servant"
        return at

    def _on_action_execute(self, evt: ActionExecuteEvent) -> None:
        sk_type = self._normalize_skill_type(evt)
        if evt.actor_name in self.entity_specs:
            self.modifier_engine.dispatch_event(
                "OnBeforeSkillUse",
                owner_id=evt.actor_name,
                current_skill_type=sk_type,
            )
        else:
            self.modifier_engine.dispatch_event(
                "OnListenBeforeSkillUse",
                param_entity_id=evt.actor_name,
                current_skill_type=sk_type,
            )

    def _on_action_end(self, evt: ActionEndEvent) -> None:
        self.end_being_attacked()
        sk_type = self._normalize_skill_type(evt)
        if evt.actor_name in self.entity_specs:
            self.modifier_engine.dispatch_event(
                "OnAfterSkillUse",
                owner_id=evt.actor_name,
                current_skill_type=sk_type,
            )
            self.modifier_engine.dispatch_event("OnActionEnd", owner_id=evt.actor_name)
        self.modifier_engine.dispatch_event(
            "OnListenAfterSkillUse",
            param_entity_id=evt.actor_name,
            current_skill_type=sk_type,
        )
        self.modifier_engine.dispatch_event("OnListenActionEnd", param_entity_id=evt.actor_name)
        if evt.actor_name in self.entity_specs:
            self.modifier_engine.dispatch_event("OnAfterAction", owner_id=evt.actor_name)
        self.modifier_engine.dispatch_event("OnListenAfterAction", param_entity_id=evt.actor_name)
        self.modifier_engine.dispatch_event(
            "CheckParamFlagCallBack",
            param_entity_id=evt.actor_name,
            param_flags=("CallBack_SettleSkillOrInsertAbility",),
        )

    def _on_hp_lost(self, evt: HPLostEvent) -> None:
        self.modifier_engine.dispatch_event("OnHPChange", owner_id=evt.entity_name, change_value=-evt.amount)
        self.modifier_engine.dispatch_event("OnListenHPChange", param_entity_id=evt.entity_name, change_value=-evt.amount)

    def _on_heal_applied(self, evt: HealAppliedEvent) -> None:
        if evt.amount > 0.0:
            self.modifier_engine.dispatch_event("OnHPChange", owner_id=evt.target_name, change_value=float(evt.amount))
            self.modifier_engine.dispatch_event("OnListenHPChange", param_entity_id=evt.target_name, change_value=float(evt.amount))

    def _on_spirit_despawn(self, evt: SpiritDespawnEvent) -> None:
        if self.modifier_engine.has_modifier(evt.spirit_name, "MMonster_W4_Griffin_00_Debuff_Avatar_Status"):
            self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=evt.spirit_name, param_entity_id=evt.spirit_name)
        elif evt.owner_name and self.modifier_engine.has_modifier(evt.owner_name, "MMonster_W4_Griffin_00_Debuff_Avatar_Status"):
            self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=evt.owner_name, param_entity_id=evt.spirit_name)
        self.modifier_engine.destroy_all_for_entity(evt.spirit_name)

    def _on_enemy_defeated(self, evt: EnemyDefeatedEvent) -> None:
        killer_id = str(getattr(evt, "attacker_name", ""))
        dead_id = str(getattr(evt, "target_name", ""))
        if dead_id:
            self._entity_is_enemy.setdefault(dead_id, True)
        killer_ent = self.sim.get_entity(killer_id) if killer_id else None
        if killer_ent is not None:
            self.record_entity_team(killer_ent)
        if (
            killer_ent is not None
            and self.modifier_engine.has_modifier(killer_id, "MMonster_W4_Griffin_00_Debuff_Avatar_Status")
        ):
            self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=killer_id, param_entity_id=dead_id)
        elif killer_ent is not None and getattr(killer_ent, "is_enemy", False):
            self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=killer_id, param_entity_id=dead_id)
        else:
            if killer_ent is not None:
                self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=killer_id, param_entity_id=dead_id)
            owner_prov = getattr(self.sim, "on_trigger_death_owner_provider", None)
            picked_owner = owner_prov(killer_id, dead_id) if callable(owner_prov) else None
            if picked_owner and self.modifier_engine.has_modifier(picked_owner, "MMonster_W4_Griffin_00_Debuff_Avatar_Status"):
                self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=picked_owner, param_entity_id=dead_id)
            else:
                for e in getattr(self.sim, "entities", ()):
                    if not getattr(e, "is_enemy", False) and getattr(e, "current_hp", 0.0) > 0.0:
                        if self.modifier_engine.has_modifier(e.name, "MMonster_W4_Griffin_00_Debuff_Avatar_Status"):
                            self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=e.name, param_entity_id=dead_id)
                            break
        if (
            getattr(self, "_attack_scope_depth", 0) > 0
            and not getattr(self, "_in_after_attack", False)
            and not getattr(self, "_flushing_listen_die", False)
        ):
            q = getattr(self, "_pending_listen_die", None)
            if q is None:
                q = []
                self._pending_listen_die = q
            if dead_id and dead_id not in q:
                q.append(dead_id)
        else:
            self.modifier_engine.dispatch_event("OnListenCharacterDie", param_entity_id=dead_id)


def ensure_vm_runtime(sim: Any, *, loader: Optional[GameDataLoader] = None, strict: bool = True) -> VMRuntime:
    rt = getattr(sim, "vm_runtime", None)
    if rt is None:
        rt = VMRuntime(sim, loader=loader, strict=strict)
        sim.vm_runtime = rt
    return rt


class ConfigAbilityKitAdapter(KitHandler):
    """基于官方 ConfigAbility VM 的通用角色/忆灵 KitHandler 适配器。"""

    def __init__(
        self,
        owner_id: str,
        avatar_or_servant_id: int,
        port: Any = None,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None,
        runtime: Optional[VMRuntime] = None,
        loader: Optional[GameDataLoader] = None,
        is_servant: bool = False,
    ) -> None:
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.unit_id = int(avatar_or_servant_id)
        self.is_servant = is_servant
        self._runtime = runtime
        self._loader = loader or (runtime.loader if runtime else GameDataLoader())
        if is_servant:
            self.spec = self._loader.load_servant(self.unit_id, eidolon=eidolon, trained_levels=skill_levels)
        else:
            self.spec = self._loader.load_character(self.unit_id, eidolon=eidolon, trained_levels=skill_levels)
        self._skill_abilities: Dict[str, List[str]] = {
            item.get("Skill", ""): list(item.get("AbilityList", []))
            for item in self.spec.config.get("SkillAbilityList", [])
        }
        self._skill_entries: Dict[str, str] = {
            item.get("Name", ""): item.get("EntryAbility", "")
            for item in self.spec.config.get("SkillList", [])
            if isinstance(item, dict) and item.get("Name")
        }
        self._skill_target_infos: Dict[str, Dict[str, Any]] = {
            item.get("Name", ""): dict(item.get("TargetInfo") or {})
            for item in self.spec.config.get("SkillList", [])
            if isinstance(item, dict) and item.get("Name")
        }
        self._registered = False
        self._passives_triggered = False

    def _rt(self) -> VMRuntime:
        if self._runtime is not None:
            return self._runtime
        sim = getattr(self.port, "sim", None)
        if sim is None:
            raise RuntimeError("ConfigAbilityKitAdapter 需要绑定到 TurnSimulator")
        self._runtime = ensure_vm_runtime(sim, loader=self._loader)
        return self._runtime

    def _ensure_registered(self, *, trigger_passives: bool = True) -> VMRuntime:
        rt = self._rt()
        if not self._registered:
            self._registered = True
            rt.register_character(self.owner_id, self.spec)
        if trigger_passives and not self._passives_triggered:
            self._passives_triggered = True
            seen_init: set[str] = set()
            for ab_name in self.spec.config.get("AbilityList", []):
                if "PassiveSkill" in ab_name and ab_name not in seen_init:
                    seen_init.add(ab_name)
                    rt.trigger_ability(caster_id=self.owner_id, ability_name=ab_name, target_ids=(self.owner_id,))
            for sk, ab_list in self._skill_abilities.items():
                if sk.startswith("SkillP"):
                    entry_ab = self._skill_entries.get(sk, "")
                    candidates = [entry_ab] if entry_ab else [
                        a for a in ab_list
                        if ("Passive" in a or "BattleCry" in a or "DeathRattle" in a)
                        and not any(bad in a for bad in ("Insert", "Resummon", "Camera"))
                    ]
                    for ab_name in candidates:
                        if ab_name and ab_name not in seen_init:
                            seen_init.add(ab_name)
                            rt.trigger_ability(caster_id=self.owner_id, ability_name=ab_name, target_ids=(self.owner_id,))
        return rt

    def _has_runtime_modifier(self, mod_name: str) -> bool:
        rt = self._runtime
        if rt is None and self.port and getattr(self.port, "sim", None) is not None:
            rt = getattr(self.port.sim, "vm_runtime", None)
        return bool(rt is not None and rt.modifier_engine.has_modifier(self.owner_id, mod_name))

    def _resolve_control_skill_key(self, ctrl_type: str, default_key: str) -> str:
        rt = self._runtime or (getattr(self.port.sim, "vm_runtime", None) if (self.port and getattr(self.port, "sim", None)) else None)
        if rt is not None:
            if self.is_servant and ctrl_type == "ControlSkill01":
                cur_turn = getattr(rt.sim, "_current_turn_entity", None)
                if cur_turn is not None and getattr(cur_turn, "name", None) == self.owner_id:
                    snap = rt.turn_control_skill_snapshot.get(self.owner_id)
                    if snap and snap in self._skill_abilities:
                        return snap
            mapped = rt.control_skill_mapping.get((self.owner_id, ctrl_type))
            if mapped and mapped in self._skill_abilities:
                return mapped
        return default_key

    def _resolve_skill_row(self, sk_key: str) -> Optional[Dict[str, Any]]:
        if self.is_servant:
            self._loader._ensure_servants()
            self._loader._ensure_servant_skills()
            sv = self._loader._servants.get(self.unit_id, {})
            for sid in sv.get("SkillIDList", []):
                row = self._loader._servant_skills.get((int(sid), 1))
                if row and row.get("SkillTriggerKey") == sk_key:
                    return row
            return None
        self._loader._ensure_avatars()
        self._loader._ensure_avatar_skills()
        av = self._loader._avatars.get(self.unit_id, {})
        for sid in av.get("SkillList", []):
            row = self._loader._avatar_skills.get((int(sid), 1))
            if row and row.get("SkillTriggerKey") == sk_key:
                return row
        return None

    def _resolve_skill_id(self, sk_key: str, fallback_slot: int) -> int:
        row = self._resolve_skill_row(sk_key)
        if row and row.get("SkillID"):
            return int(row["SkillID"])
        return self.unit_id * 100 + fallback_slot

    def _resolve_target_mode(self, sk_key: str, default: TargetMode) -> TargetMode:
        info = self._skill_target_infos.get(sk_key) or {}
        tt = str(info.get("TargetType", ""))
        sub = str(info.get("SubTargetType", ""))
        if tt == "EnemySelect":
            return TargetMode.BLAST if sub == "TargetAdjoinEntity" else TargetMode.SINGLE_ENEMY
        if tt == "AllEnemy":
            return TargetMode.ALL_ENEMIES
        if tt == "Caster":
            return TargetMode.SELF
        if tt == "AllTeamMember":
            return TargetMode.ALL_ALLIES
        if tt == "FriendSelect":
            return TargetMode.SINGLE_ALLY
        return default

    def _resolve_sp_cost(self, sk_key: str, default_sp: int = 0) -> ResourceCost:
        if self.is_servant:
            if self.unit_id == 11512 and sk_key == "Skill01":
                return ResourceCost(sp=-1)
            return ResourceCost(sp=0)
        row = self._resolve_skill_row(sk_key)
        if row is not None:
            bp_need = row.get("BPNeed")
            bp_add = row.get("BPAdd")
            if isinstance(bp_need, dict) and float(bp_need.get("Value", 0.0)) > 0:
                return ResourceCost(sp=int(round(float(bp_need["Value"]))))
            if isinstance(bp_add, dict) and float(bp_add.get("Value", 0.0)) > 0:
                return ResourceCost(sp=-int(round(float(bp_add["Value"]))))
            return ResourceCost(sp=0)
        return ResourceCost(sp=default_sp)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if self.is_servant:
            if kind in (ActionKind.SKILL, ActionKind.MEMOSPRITE_SKILL):
                sk_key = self._resolve_control_skill_key("ControlSkill01", "Skill01")
                sk_id = self._resolve_skill_id(sk_key, 7 if sk_key == "Skill11" else 1)
                cost = self._resolve_sp_cost(sk_key, 0)
                name = "忆灵爆发" if sk_key == "Skill11" else "忆灵技"
                return AbilityDefinition(kind=kind, name=name, target_mode=TargetMode.ALL_ENEMIES, cost=cost, is_auto=True, skill_id=sk_id)
            return AbilityDefinition(kind=kind, name=str(kind.name), target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=0), is_auto=True)

        if kind == ActionKind.BASIC:
            sk_key = self._resolve_control_skill_key("ControlSkill01", "Skill01")
            sk_id = self._resolve_skill_id(sk_key, 1)
            return AbilityDefinition(
                kind=kind,
                name="普攻",
                target_mode=self._resolve_target_mode(sk_key, TargetMode.SINGLE_ENEMY),
                cost=self._resolve_sp_cost(sk_key, -1),
                skill_id=sk_id,
            )
        if kind == ActionKind.SKILL:
            sk_key = self._resolve_control_skill_key("ControlSkill02", "Skill02")
            sk_id = self._resolve_skill_id(sk_key, 9 if sk_key == "Skill21" else 2)
            return AbilityDefinition(
                kind=kind,
                name="战技",
                target_mode=self._resolve_target_mode(sk_key, TargetMode.ALL_ALLIES),
                cost=self._resolve_sp_cost(sk_key, 1),
                skill_id=sk_id,
            )
        if kind == ActionKind.ULTIMATE:
            sk_key = self._resolve_control_skill_key("ControlSkill03", "Skill03")
            sk_id = self._resolve_skill_id(sk_key, 3)
            return AbilityDefinition(
                kind=kind,
                name="终结技",
                target_mode=self._resolve_target_mode(sk_key, TargetMode.ALL_ALLIES),
                cost=ResourceCost(),
                skill_id=sk_id,
            )
        if kind == ActionKind.TECHNIQUE:
            sk_id = self._resolve_skill_id("SkillMaze", 7)
            return AbilityDefinition(kind=kind, name="秘技", target_mode=TargetMode.SELF, priority=1, skill_id=sk_id)
        if kind == ActionKind.FOLLOW_UP:
            if any("Insert" in a for a in self._skill_abilities.get("SkillP01", [])):
                sk_id = self._resolve_skill_id("SkillP01", 4)
                return AbilityDefinition(kind=kind, name="追击", target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(), skill_id=sk_id)
            return None  # type: ignore[return-value]
        if kind == ActionKind.MEMOSPRITE_SKILL:
            return AbilityDefinition(kind=kind, name="忆灵技", target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost())
        return AbilityDefinition(kind=kind, name=str(kind.name), target_mode=TargetMode.SINGLE_ENEMY)

    def use_technique(self) -> None:
        rt = self._ensure_registered(trigger_passives=False)
        for ab_name in self._skill_abilities.get("SkillMaze", []):
            rt.trigger_ability(caster_id=self.owner_id, ability_name=ab_name, target_ids=(self.owner_id,), current_skill_type="Maze")

    def on_battle_start(self) -> None:
        self._ensure_registered()

    def execute(self, ctx: ActionContext) -> None:
        rt = self._ensure_registered()
        if self.is_servant:
            if ctx.kind in (ActionKind.SKILL, ActionKind.MEMOSPRITE_SKILL):
                sk_key = self._resolve_control_skill_key("ControlSkill01", "Skill01")
                sk_type = "Servant"
            else:
                sk_key, sk_type = ("Skill01", "Servant")
        else:
            sk_map = {
                ActionKind.BASIC: ("ControlSkill01", "Skill01", "Normal"),
                ActionKind.SKILL: ("ControlSkill02", "Skill02", "BPSkill"),
                ActionKind.ULTIMATE: ("ControlSkill03", "Skill03", "Ultra"),
                ActionKind.MEMOSPRITE_SKILL: ("ControlSkill01", "Skill01", "Servant"),
            }
            ctrl_t, def_key, sk_type = sk_map.get(ctx.kind, ("ControlSkill01", "Skill01", "Normal"))
            sk_key = self._resolve_control_skill_key(ctrl_t, def_key)

        ab_list = self._skill_abilities.get(sk_key, [])
        t_info = self._skill_target_infos.get(sk_key) or {}
        t_type = str(t_info.get("TargetType", ""))
        if t_type == "EnemySelect":
            picked_ents = [
                e for e in rt.sim.entities
                if getattr(e, "is_enemy", False)
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
                and float(getattr(e, "current_hp", 0.0)) > 0.0
            ]
            chosen_ent = None
            tp = getattr(rt.sim, "target_provider", None)
            if tp is not None and picked_ents:
                actor_ent = rt.sim.get_entity(self.owner_id)
                if actor_ent is not None:
                    chosen_ent = tp(actor_ent, picked_ents, 0)
            if chosen_ent is not None and chosen_ent in picked_ents:
                eff_targets = (chosen_ent.name,)
            elif ctx.target_ids:
                norm_ctx_tids = tuple(
                    getattr(rt.sim.get_entity(tid), "name", tid) for tid in ctx.target_ids
                )
                if str(t_info.get("SubTargetType", "")) == "TargetAdjoinEntity" and len(norm_ctx_tids) >= 2:
                    pos_map = {e.name: idx for idx, e in enumerate(picked_ents)}
                    valid_tids = [tid for tid in norm_ctx_tids if tid in pos_map]
                    valid_tids.sort(key=lambda tid: pos_map[tid])
                    if len(valid_tids) == 3:
                        eff_targets = (valid_tids[1],)
                    elif len(valid_tids) == 2:
                        if pos_map[valid_tids[0]] == 0:
                            eff_targets = (valid_tids[0],)
                        elif pos_map[valid_tids[1]] == len(picked_ents) - 1:
                            eff_targets = (valid_tids[1],)
                        else:
                            eff_targets = (norm_ctx_tids[0],)
                    else:
                        eff_targets = norm_ctx_tids[:1]
                else:
                    eff_targets = norm_ctx_tids[:1]
            else:
                chosen_ent = max(
                    picked_ents,
                    key=lambda e: (
                        bool(getattr(e, "is_boss", False)),
                        float(getattr(e, "max_hp", 0.0)),
                        float(getattr(e, "current_hp", 0.0)),
                    ),
                ) if picked_ents else None
                eff_targets = (chosen_ent.name,) if chosen_ent is not None else ()
        elif t_type == "FriendSelect" and ctx.target_ids:
            eff_targets = ctx.target_ids[:1]
        elif t_type == "FriendSelect" and not ctx.target_ids:
            avoid_self = bool(t_info.get("AvoidSelf", False))
            forbid_sv = str(t_info.get("AllowFriendServant", "")) == "Forbidden"
            picked = [
                e.name for e in rt.sim.entities
                if not getattr(e, "is_enemy", False)
                and not getattr(e, "is_countdown", False)
                and float(getattr(e, "current_hp", 0.0)) > 0.0
                and (not avoid_self or e.name != self.owner_id)
                and (not forbid_sv or not getattr(e, "is_memosprite", False))
            ]
            eff_targets = (picked[0],) if picked else ((self.owner_id,) if not avoid_self else ())
        elif t_type == "AllEnemy":
            eff_targets = tuple(
                e.name
                for e in sorted(
                    (
                        e
                        for e in rt.sim.entities
                        if getattr(e, "is_enemy", False)
                        and not getattr(e, "is_countdown", False)
                        and not getattr(e, "is_unselectable", False)
                        and float(getattr(e, "current_hp", 0.0)) > 0.0
                    ),
                    key=lambda x: getattr(x, "_spawn_seq", 0),
                )
            )
        elif t_type == "AllTeamMember" and not ctx.target_ids:
            eff_targets = tuple(
                e.name for e in rt.sim.entities
                if not getattr(e, "is_enemy", False)
                and not getattr(e, "is_countdown", False)
                and not getattr(e, "is_unselectable", False)
                and float(getattr(e, "current_hp", 0.0)) > 0.0
            )
        elif t_type == "Caster" and not ctx.target_ids:
            eff_targets = (self.owner_id,)
        else:
            eff_targets = ctx.target_ids

        # 在执行 Ability 前以当前 SkillTargetEntityList 分发 OnListenBeforeSkillUse（支撑光锥 23052 等读取 ParamEntitySkillTargetEntityList）
        rt.modifier_engine.dispatch_event(
            "OnListenBeforeSkillUse",
            param_entity_id=self.owner_id,
            skill_target_ids=eff_targets,
            param_skill_targets=eff_targets,
            current_skill_type=sk_type,
        )

        # 读取官方 ExcelOutput SPBase 能量基数
        row = self._resolve_skill_row(sk_key)
        sp_obj = (row.get("SPBase") or {}) if row else {}
        base_en = float(sp_obj.get("Value", 0.0)) if isinstance(sp_obj, dict) else 0.0

        prev_sp_base = rt._active_skill_sp_base
        prev_sp_granted = rt._skill_sp_ratio_granted
        rt._active_skill_sp_base = base_en
        rt._skill_sp_ratio_granted = False
        rt.begin_attack_scope()
        try:
            # 只执行 Phase01/Phase02（跳过 _Camera）
            entry_ab = self._skill_entries.get(sk_key, "")
            entry = [entry_ab] if (entry_ab and not entry_ab.endswith("_Camera")) else (
                [a for a in ab_list if a.endswith("_Phase01")] or [a for a in ab_list if not a.endswith("_Camera")]
            )
            for ab_name in entry[:1]:
                rt.trigger_ability(
                    caster_id=self.owner_id,
                    ability_name=ab_name,
                    target_ids=eff_targets,
                    skill_target_ids=eff_targets,
                    current_skill_type=sk_type,
                    current_attack_type=sk_type,
                )
        finally:
            rt.end_attack_scope()
            sp_granted_by_task = rt._skill_sp_ratio_granted
            rt._active_skill_sp_base = prev_sp_base
            rt._skill_sp_ratio_granted = prev_sp_granted

        # 若 Ability 内未通过 ModifySPNew(AddRatio) 结算技能基础回能，则在此统一按 SPBase * ERR 结算
        if base_en > 0 and not sp_granted_by_task and self.port:
            ep_recipient = self.owner_id
            if self.is_servant:
                ent = rt.sim.get_entity(self.owner_id)
                master_id = getattr(ent, "master_name", None) if ent is not None else None
                if not master_id:
                    return
                ep_recipient = master_id
            err = self.port.stat(ep_recipient, StatType.ERR) or 1.0
            self.port.gain_energy(ep_recipient, base_en * err, cause=f"技能回能 {sk_key}")


class ConfigAbilityRelicAdapter(RelicSetHandler):
    """基于官方 ConfigAbility VM 的遗器处理器。"""

    def __init__(self, owner_id: str, set_id: int, port: Any = None, *, pieces: int = 4, spec: Any = None) -> None:
        super().__init__(owner_id, port, pieces=pieces, spec=spec)
        self.set_id = int(set_id)

    def on_battle_start(self) -> None:
        if not self.port or not hasattr(self.port, "sim"):
            return
        rt = ensure_vm_runtime(self.port.sim)
        res = rt.loader.get_relic_ability(self.set_id, self.pieces)
        if res is None:
            return
        ab, dyn = res
        rt.register_equip_ability(self.owner_id, ab["Name"], dyn)
        rt.trigger_ability(caster_id=self.owner_id, ability_name=ab["Name"], target_ids=(self.owner_id,))


class ConfigAbilityLightConeAdapter(LightConeHandler):
    """基于官方 ConfigAbility VM 的光锥处理器。"""

    def __init__(self, owner_id: str, equip_id: int, port: Any = None, *, superimposition: int = 1, spec: Any = None) -> None:
        super().__init__(owner_id, port, superimposition=superimposition, spec=spec)
        self.equip_id = int(equip_id)

    def on_battle_start(self) -> None:
        if not self.port or not hasattr(self.port, "sim"):
            return
        rt = ensure_vm_runtime(self.port.sim)
        res = rt.loader.get_equipment_ability(self.equip_id, self.superimposition)
        if res is None:
            return
        ab, dyn = res
        rt.register_equip_ability(self.owner_id, ab["Name"], dyn)
        rt.trigger_ability(caster_id=self.owner_id, ability_name=ab["Name"], target_ids=(self.owner_id,))

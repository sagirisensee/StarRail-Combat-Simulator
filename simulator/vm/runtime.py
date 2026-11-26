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
    SPChangeEvent,
    SpiritDespawnEvent,
    SpiritSummonedEvent,
    TurnBeginEvent,
    TurnEndEvent,
)
from ..lifecycle import AbilityFrameSpec, AfterAttackPayload, ExecutionLifecycle, emit_sim_event
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
        self.lifecycle = ExecutionLifecycle(self)
        self._battle_entered: bool = False
        self._active_skill_sp_base: float = 0.0
        self._skill_sp_ratio_granted: bool = False
        self._added_abilities: Set[Tuple[str, str]] = set()
        self.elation_points: float = 0.0
        self._entity_is_enemy: Dict[str, bool] = {
            e.name: bool(getattr(e, "is_enemy", False))
            for e in getattr(sim, "entities", ())
            if getattr(e, "name", None)
        }

        # 订阅 TurnSimulator 核心事实事件，转发给官方 Modifier 引擎
        self.control_skill_mapping: Dict[Tuple[str, str], str] = {}
        self.turn_control_skill_snapshot: Dict[str, str] = {}
        self.dynamic_entity_params: Dict[Tuple[str, str], List[str]] = {}
        self.hp_shared_groups: Dict[str, str] = {}
        self.skill_property_overrides: Dict[str, List[Dict[str, Any]]] = {}
        self.entity_boost_points: Dict[str, float] = {}
        self.entity_skill_tags: Dict[str, Dict[str, Set[Tuple[int, int]]]] = {}
        self.entity_removed_skill_tags: Dict[str, Dict[str, Set[Tuple[int, int]]]] = {}
        self._pending_use_skill_one_more: Dict[str, List[str]] = {}
        self.in_elation_time: bool = False
        self.elation_time_override_points: float = 0.0
        self.elation_time_custom_tag: str = ""
        self.elation_time_units: List[str] = []
        self.has_paused_elation_time: bool = False
        self.entity_dynamic_strings: Dict[str, Dict[str, str]] = {}
        self.common_skills: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.auto_use_bound_ultra_skills: Dict[str, Set[str]] = {}
        self.auto_use_entity_ultra_skills: Dict[str, Any] = {}
        self.global_action_delay: float = 0.0
        self._skill_targets_by_action_id: Dict[int, Tuple[str, ...]] = {}
        if getattr(sim, "vm_runtime", None) is None:
            sim.vm_runtime = self

    @property
    def _attack_scope_depth(self) -> int:
        return self.lifecycle.attack_scope_depth

    @_attack_scope_depth.setter
    def _attack_scope_depth(self, value: int) -> None:
        self.lifecycle.attack_scope_depth = int(value)

    @property
    def _in_turn_phase1_end(self) -> bool:
        return self.lifecycle.in_turn_phase1_end

    @_in_turn_phase1_end.setter
    def _in_turn_phase1_end(self, value: bool) -> None:
        self.lifecycle.in_turn_phase1_end = bool(value)

    @property
    def _in_after_attack(self) -> bool:
        return self.lifecycle.in_after_attack

    @_in_after_attack.setter
    def _in_after_attack(self, value: bool) -> None:
        self.lifecycle.in_after_attack = bool(value)

    @property
    def _in_dying_batch(self) -> bool:
        return self.lifecycle.in_dying_batch

    @_in_dying_batch.setter
    def _in_dying_batch(self, value: bool) -> None:
        self.lifecycle.in_dying_batch = bool(value)

    @property
    def _flushing_listen_die(self) -> bool:
        return self.lifecycle.flushing_listen_die

    @_flushing_listen_die.setter
    def _flushing_listen_die(self, value: bool) -> None:
        self.lifecycle.flushing_listen_die = bool(value)

    @property
    def _pending_after_attack(self) -> Optional[AfterAttackPayload]:
        return self.lifecycle.pending_after_attack

    @_pending_after_attack.setter
    def _pending_after_attack(self, value: Any) -> None:
        if value is None or isinstance(value, AfterAttackPayload):
            self.lifecycle.pending_after_attack = value
        elif isinstance(value, tuple):
            atk_seq, caster_id, dmg_data, atk_type = value[:4]
            skill_type = value[4] if len(value) > 4 else atk_type
            self.lifecycle.pending_after_attack = AfterAttackPayload(
                atk_seq=int(atk_seq),
                caster_id=str(caster_id),
                dmg_data=dmg_data,
                atk_type=str(atk_type),
                skill_type=str(skill_type),
            )
        else:
            raise TypeError(f"Unsupported pending_after_attack payload: {type(value)!r}")

    @property
    def _after_attack_fired(self) -> Set[Tuple[int, str]]:
        return self.lifecycle.after_attack_fired

    @_after_attack_fired.setter
    def _after_attack_fired(self, value: Set[Tuple[int, str]]) -> None:
        self.lifecycle.after_attack_fired = value

    @property
    def _attack_targets_by_key(self) -> Dict[Tuple[int, str], List[str]]:
        return self.lifecycle.attack_targets_by_key

    @_attack_targets_by_key.setter
    def _attack_targets_by_key(self, value: Dict[Tuple[int, str], List[str]]) -> None:
        self.lifecycle.attack_targets_by_key = value

    @property
    def _attack_blocked_targets(self) -> Set[str]:
        return self.lifecycle.attack_blocked_targets

    @_attack_blocked_targets.setter
    def _attack_blocked_targets(self, value: Set[str]) -> None:
        self.lifecycle.attack_blocked_targets = value

    @property
    def _open_enemy_attack(self) -> Optional[str]:
        return self.lifecycle.open_enemy_attack

    @_open_enemy_attack.setter
    def _open_enemy_attack(self, value: Optional[str]) -> None:
        self.lifecycle.open_enemy_attack = value

    @property
    def _pending_dying_enemies(self) -> List[Tuple[str, str]]:
        return self.lifecycle.pending_dying_enemies

    @_pending_dying_enemies.setter
    def _pending_dying_enemies(self, value: List[Tuple[str, str]]) -> None:
        self.lifecycle.pending_dying_enemies = value

    @property
    def _pending_limbo_after_dying(self) -> List[Tuple[str, Optional[str]]]:
        return self.lifecycle.pending_limbo_after_dying

    @_pending_limbo_after_dying.setter
    def _pending_limbo_after_dying(self, value: List[Tuple[str, Optional[str]]]) -> None:
        self.lifecycle.pending_limbo_after_dying = value

    @property
    def _pending_level_kills(self) -> List[Tuple[str, str]]:
        return self.lifecycle.pending_level_kills

    @_pending_level_kills.setter
    def _pending_level_kills(self, value: List[Tuple[str, str]]) -> None:
        self.lifecycle.pending_level_kills = value

    @property
    def _pending_dead_enemies(self) -> List[str]:
        return self.lifecycle.pending_dead_enemies

    @_pending_dead_enemies.setter
    def _pending_dead_enemies(self, value: List[str]) -> None:
        self.lifecycle.pending_dead_enemies = value

    @property
    def _pending_listen_die(self) -> List[Tuple[str, str]]:
        return self.lifecycle.pending_listen_die

    @_pending_listen_die.setter
    def _pending_listen_die(self, value: List[Tuple[str, str]]) -> None:
        self.lifecycle.pending_listen_die = value

    @property
    def _active_deathrattle_entities(self) -> Set[str]:
        return self.lifecycle.active_deathrattle_entities

    @_active_deathrattle_entities.setter
    def _active_deathrattle_entities(self, value: Set[str]) -> None:
        self.lifecycle.active_deathrattle_entities = value

    def resolve_global_target_alias(self, alias_name: str) -> Optional[Dict[str, Any]]:
        return self.loader.get_global_target_alias(alias_name)

    def begin_attack_scope(self) -> None:
        self.lifecycle.begin_attack_scope()

    def trigger_or_defer_limbo(self, owner_id: str, param_entity_id: Optional[str]) -> bool:
        """若当前处于攻击作用域或死亡批处理（OnBeforeDying）中，将转阶段回血延后至结算完成后触发，防止附加/真伤或自伤误扣新阶段 HP。"""
        return self.lifecycle.trigger_or_defer_limbo(owner_id, param_entity_id)

    def flush_pending_after_attack(self) -> None:
        self.lifecycle.settle_attack_boundary()

    def flush_pending_listen_die(self) -> None:
        """Flush deferred OnListenCharacterDie callbacks after attack/after-attack hooks settle."""
        self.lifecycle.flush_listen_die()

    def drain_pending_dying_enemies(self) -> None:
        """Drain deferred dying enemies (OnBeforeDying / OnDeathrattle) after attack hooks settle."""
        self.lifecycle.drain_dying_batch()

    def finalize_dead_enemy(self, dead_tid: str) -> None:
        """Finalize a defeated enemy entity and cascade-cleanup any HP-shared subtargets."""
        self.lifecycle.finalize_dead_enemy(dead_tid)

    def end_attack_scope(self) -> None:
        self.lifecycle.end_attack_scope()

    def begin_being_attacked(self, attacker_name: str, target_ids: Sequence[str]) -> None:
        self.lifecycle.begin_being_attacked(attacker_name, target_ids)

    def end_being_attacked(self, attacker_name: Optional[str] = None) -> None:
        self.lifecycle.end_being_attacked(attacker_name)

    def record_entity_team(self, entity: Any) -> None:
        if entity is not None and getattr(entity, "name", None):
            self._entity_is_enemy[entity.name] = bool(getattr(entity, "is_enemy", False))

    def finalize_inline_deathrattle(self, entity_id: str) -> None:
        """若实体无异步亡语插入动作且 HP<=0，则立即结束亡语悬停态并销毁 Modifier。"""
        self.lifecycle.finalize_inline_deathrattle(entity_id)

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
        ent = self.sim.get_entity(entity_name)
        if ent is not None and getattr(spec, "uses_special_sp", False):
            ent.uses_special_sp = True
        self.record_entity_team(ent)

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
            if local_ctx.template_dynamics is not None and hash_val in local_ctx.template_dynamics:
                return local_ctx.template_dynamics[hash_val]
            if hash_val in local_ctx.local_dynamics:
                return local_ctx.local_dynamics[hash_val]
            if local_ctx.modifier_instance is not None:
                bound = local_ctx.modifier_instance.resolve_bound_value(hash_val)
                if bound is not None:
                    return bound
                if hash_val in local_ctx.modifier_instance.dynamic_values:
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
        self.modifier_engine.check_dynamic_value_changes(
            entity_id, key_hash, old_val, float(value), modifier=modifier
        )

    def modify_elation_points(self, value: float, *, mode: str = "add", source: str = "") -> None:
        old_val = float(self.elation_points)
        if mode == "set":
            new_val = max(0.0, float(value))
        else:
            new_val = max(0.0, old_val + float(value))
        actual_delta = new_val - old_val
        self.elation_points = new_val
        diag_cb = getattr(self.sim, "timeline_diag_cb", None)
        if callable(diag_cb):
            src_s = f" ab={source}" if source else ""
            diag_cb("EP", f"mode={mode} val={float(value):g} {old_val:g}->{new_val:g}{src_s}")
        self.modifier_engine.check_elation_point_changes(old_val, new_val, actual_delta)

    def get_elation_points_for_query(self, owner_id: str, query_type: Optional[str] = None) -> float:
        if str(query_type or "") == "KGCEIIJFCKE":
            return float(self.elation_points or 0.0)
        if getattr(self, "in_elation_time", False):
            ov_pt = float(getattr(self, "elation_time_override_points", 0.0) or 0.0)
            if ov_pt > 0.0:
                return ov_pt
        if not getattr(self, "in_elation_time", False) and owner_id and owner_id != "__LEVEL__":
            echo_pt = float(self.modifier_engine.get_entity_property(owner_id, "ElationEchoPoint") or 0.0)
            if echo_pt > 0.0:
                return echo_pt
        return float(self.elation_points or 0.0)

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
        local_dynamics: Optional[Dict[int, float]] = None,
        custom_strings: Optional[Dict[str, str]] = None,
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
            local_dynamics=dict(local_dynamics) if local_dynamics else {},
            custom_strings=dict(custom_strings) if custom_strings else {},
        )
        has_add = bool(ab.get("OnAdd"))
        has_start = "OnStart" in ab
        if has_add:
            add_key = (caster_id, ability_name)
            if add_key not in self._added_abilities:
                self._added_abilities.add(add_key)
                self.executor.execute_tasks(ab.get("OnAdd", []), ctx)
        if has_start:
            self.executor.execute_tasks(ab.get("OnStart", []), ctx)

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
                base_elem_dmg_boost=getattr(master, "base_elem_dmg_boost", 0.0),
                base_elation=getattr(master, "base_elation", 0.0),
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
            sv_entity.base_elem_dmg_boost = getattr(master, "base_elem_dmg_boost", 0.0)
            sv_entity.base_elation = getattr(master, "base_elation", 0.0)
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
        emit_sim_event(self.sim, SpiritSummonedEvent(
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
    # 微内核事实路由入口（由 TurnSimulator.emit_event 显式顺序调用）
    # ------------------------------------------------------------------
    def on_turn_begin(self, evt: TurnBeginEvent) -> None:
        # 实机日志已证实 (184845 [961..966], 204943 [637..640], 155925 [304..305])：
        # TurnPhase1 顺序：OnPhase1 -> OnListenTurnBegin -> OnListenTurnPhase1Begin
        # -> OnListenBeforeTurnPhase1End (血嗜等回合开始扣血 & 伴生小伊卡回血，此时 Phase1End 到期光环仍在！)
        # -> ModifierPhase1End (回合开始到期光环结算) -> OnActionPhaseBegin；
        # 终结技/追击等额外行动不经过 TurnBegin，不触发 OnPhase1。
        self.modifier_engine.dispatch_event("OnListenTurnBegin", param_entity_id=evt.actor_name)
        self.modifier_engine.dispatch_event("OnPhase1", owner_id=evt.actor_name)
        self.modifier_engine.dispatch_event("OnListenTurnPhase1Begin", param_entity_id=evt.actor_name)
        self.turn_control_skill_snapshot[evt.actor_name] = self.control_skill_mapping.get((evt.actor_name, "ControlSkill01"), "Skill01")
        with self.lifecycle.turn_phase1_end_scope():
            self.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=evt.actor_name)
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
        self.modifier_engine.dispatch_event(
            "OnBeforeAction",
            owner_id=evt.actor_name,
            param_entity_id=evt.actor_name,
        )
        if actor_ent is not None and not getattr(actor_ent, "is_enemy", False):
            sched = getattr(self.sim, "scheduler", None)
            if sched is not None and sched.has_pending():
                sched.drain()
                director = getattr(self.sim, "_stage_director", None)
                if director is not None and hasattr(director, "sync_spawned_entities"):
                    director.sync_spawned_entities()
        self.modifier_engine.dispatch_event("OnListenAllowAction", param_entity_id=evt.actor_name)

    def on_turn_end(self, evt: TurnEndEvent) -> None:
        self.turn_control_skill_snapshot.pop(evt.actor_name, None)
        self.end_being_attacked()
        with self.lifecycle.turn_phase1_end_scope():
            self.modifier_engine.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=evt.actor_name)
            self.modifier_engine.dispatch_event("OnListenTurnEnd", param_entity_id=evt.actor_name)
            self.modifier_engine.tick_life_step("TurnEnd", evt.actor_name)
        ent = self.sim.get_entity(evt.actor_name)
        if (
            ent is not None
            and (not getattr(ent, "is_countdown", False) or getattr(ent, "is_battle_event", False))
            and getattr(ent, "current_hp", 0.0) > 0.0
        ):
            self.modifier_engine.dispatch_event("OnPhase2", owner_id=evt.actor_name, param_entity_id=evt.actor_name)
            sched_p2 = getattr(self.sim, "scheduler", None)
            if sched_p2 is not None:
                sched_p2.drain_at_boundary()
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

    def on_action_execute(self, evt: ActionExecuteEvent) -> None:
        sk_type = self._normalize_skill_type(evt)
        if evt.actor_name in self.entity_specs:
            ent = self.sim.get_entity(evt.actor_name)
            if isinstance(getattr(ent, "kit", None), ConfigAbilityKitAdapter):
                return
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

    def on_action_end(self, evt: ActionEndEvent) -> None:
        self.end_being_attacked()
        sk_type = self._normalize_skill_type(evt)
        sk_tgts = self._skill_targets_by_action_id.pop(int(getattr(evt, "action_id", 0) or 0), ())
        if not sk_tgts:
            sk_tgts = tuple(getattr(evt, "target_ids", ()) or ())
        in_hold = bool(getattr(getattr(self.sim, "scheduler", None), "continuous_action_hold", False))
        if evt.actor_name in self.entity_specs:
            self.modifier_engine.dispatch_event(
                "OnAfterSkillUse",
                owner_id=evt.actor_name,
                current_skill_type=sk_type,
                skill_target_ids=sk_tgts,
                param_skill_targets=sk_tgts,
            )
            if not in_hold:
                self.modifier_engine.dispatch_event("OnActionEnd", owner_id=evt.actor_name)
        self.modifier_engine.dispatch_event(
            "OnListenAfterSkillUse",
            param_entity_id=evt.actor_name,
            current_skill_type=sk_type,
            skill_target_ids=sk_tgts,
            param_skill_targets=sk_tgts,
        )
        if not in_hold:
            self.modifier_engine.dispatch_event("OnListenActionEnd", param_entity_id=evt.actor_name)
            self.modifier_engine.dispatch_event(
                "CheckParamFlagCallBack",
                param_entity_id=evt.actor_name,
                param_flags=("CallBack_SettleSkillOrInsertAbility",),
            )
            if evt.actor_name in self.entity_specs:
                self.modifier_engine.dispatch_event("OnAfterAction", owner_id=evt.actor_name)
            self.modifier_engine.dispatch_event("OnListenAfterAction", param_entity_id=evt.actor_name)

    def on_hp_lost(self, evt: HPLostEvent) -> None:
        self.modifier_engine.dispatch_event("OnHPChange", owner_id=evt.entity_name, change_value=-evt.amount)
        self.modifier_engine.dispatch_event("OnListenHPChange", param_entity_id=evt.entity_name, change_value=-evt.amount)

    def on_heal_applied(self, evt: HealAppliedEvent) -> None:
        if evt.amount > 0.0:
            self.modifier_engine.dispatch_event("OnHPChange", owner_id=evt.target_name, change_value=float(evt.amount))
            self.modifier_engine.dispatch_event("OnListenHPChange", param_entity_id=evt.target_name, change_value=float(evt.amount))

    def on_sp_change(self, evt: SPChangeEvent) -> None:
        if evt.delta != 0:
            self.modifier_engine.dispatch_event(
                "OnListenBpChange",
                param_entity_id=evt.actor_name,
                change_value=float(evt.delta),
            )

    def on_spirit_despawn(self, evt: SpiritDespawnEvent) -> None:
        done_set = getattr(self, "_pre_despawn_trigger_death_done", None)
        if done_set and evt.spirit_name in done_set:
            done_set.discard(evt.spirit_name)
        elif self.modifier_engine.has_modifier(evt.spirit_name, "MMonster_W4_Griffin_00_Debuff_Avatar_Status"):
            self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=evt.spirit_name, param_entity_id=evt.spirit_name)
        elif evt.owner_name and self.modifier_engine.has_modifier(evt.owner_name, "MMonster_W4_Griffin_00_Debuff_Avatar_Status"):
            self.modifier_engine.dispatch_event("OnTriggerDeath", owner_id=evt.owner_name, param_entity_id=evt.spirit_name)
        self.modifier_engine.destroy_all_for_entity(evt.spirit_name)

    def on_enemy_defeated(self, evt: EnemyDefeatedEvent) -> None:
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
        self.lifecycle.defer_or_dispatch_listen_die(dead_id, killer_id=killer_id, defer_in_after_attack=True)

    def on_global_action_delay_changed(self, delta_av: float, delay_add: float) -> None:
        if delta_av <= 0.0 and delay_add <= 0.0:
            return
        self.global_action_delay += float(delay_add)
        self.modifier_engine.dispatch_event(
            "OnListenGlobalActionDelayChanged",
            change_value=float(delay_add),
            change_value2=float(self.global_action_delay),
        )
        diag_cb = getattr(self.sim, "timeline_diag_cb", None)
        if callable(diag_cb) and self.auto_use_entity_ultra_skills:
            ep_str = ", ".join(
                f"{tid}={float(getattr(self.sim.get_entity(tid), 'energy', 0.0)):.4f}/{float(getattr(self.sim.get_entity(tid), 'max_energy', 0.0)):.1f}"
                for tid in self.auto_use_entity_ultra_skills
                if self.sim.get_entity(tid) is not None
            )
            diag_cb("BE_EP", f"delay_add={delay_add:.4f} global={self.global_action_delay:.4f} {ep_str}")

    def trigger_auto_use_ultra_skills(self) -> None:
        if not self.auto_use_entity_ultra_skills:
            return
        from ..actions import ActionKind
        from ..events import ActionExecuteEvent
        from ..lifecycle import AbilityFrameSpec, emit_sim_event
        from .target_alias import ExecutionContext

        sim = self.sim
        me = self.modifier_engine
        diag_cb = getattr(sim, "timeline_diag_cb", None)
        for tid, tgt_spec in list(self.auto_use_entity_ultra_skills.items()):
            ent = sim.get_entity(tid)
            if ent is None or getattr(ent, "_in_auto_ultra", False):
                continue
            if not getattr(ent, "is_countdown", False) and float(getattr(ent, "current_hp", 0.0)) <= 0.0:
                continue
            max_ep = float(getattr(ent, "max_energy", 0.0) or 0.0)
            cur_ep = float(getattr(ent, "energy", 0.0) or 0.0)
            if callable(diag_cb):
                dis = me.is_skill_type_disabled(tid, "Ultra")
                ctrl = me.has_behavior_flag(tid, "STAT_CTRL")
                diag_cb("AUTO_U", f"{tid} ep={cur_ep:.4f}/{max_ep:.1f} dis_ultra={dis} ctrl={ctrl}")
            if max_ep <= 0.0 or cur_ep < max_ep - 1e-6:
                continue
            if me.is_skill_type_disabled(tid, "Ultra") or me.has_behavior_flag(tid, "STAT_CTRL"):
                continue
            spec = self.entity_specs.get(tid)
            if spec is None:
                continue
            ultra_sk = None
            for sk in spec.config.get("SkillList") or ():
                if isinstance(sk, Mapping) and str(sk.get("SkillType") or "") == "Ultra":
                    ultra_sk = sk
                    break
            if ultra_sk is None:
                continue
            entry_ab = str(ultra_sk.get("EntryAbility") or "")
            if not entry_ab:
                continue
            sk_name = str(ultra_sk.get("Name") or "Skill03")
            setattr(ent, "_in_auto_ultra", True)
            try:
                ent.energy = 0.0
                me.dispatch_event("OnUltraSkillPrepare", owner_id=tid, param_entity_id=tid)
                eff_spec = tgt_spec if tgt_spec is not None else (ultra_sk.get("TargetInfo") or {"Alias": "AllEnemy"})
                exec_ctx = ExecutionContext(
                    runtime=self,
                    caster_id=tid,
                    ability_name=entry_ab,
                    modifier_owner_id=tid,
                )
                eff_tgts = tuple(self.executor._resolve_targets(eff_spec, exec_ctx))
                if not eff_tgts:
                    eff_tgts = tuple(
                        e.name for e in sim.entities
                        if getattr(e, "is_enemy", False)
                        and not getattr(e, "is_countdown", False)
                        and not getattr(e, "is_unselectable", False)
                        and float(getattr(e, "current_hp", 0.0)) > 0.0
                    )
                sim._action_seq += 1
                sim._av_batch_seq += 1
                sk_id = int(getattr(ent, "avatar_id", 0) or 0) * 100 + 1
                emit_sim_event(
                    sim,
                    ActionExecuteEvent(
                        av=round(sim.current_av, 2),
                        cycle=sim.current_cycle,
                        actor_id=tid,
                        actor_name=tid,
                        action_type=sk_name,
                        description=f"自动施放战意/支援超必杀【{sk_name}】",
                        action_kind=ActionKind.ULTIMATE,
                        skill_config_id=sk_id,
                        action_id=sim._action_seq,
                    ),
                )
                self.lifecycle.run_ability_frame(
                    AbilityFrameSpec(
                        caster_id=tid,
                        ability_name=entry_ab,
                        target_ids=eff_tgts,
                        skill_target_ids=eff_tgts,
                        skill_type="Ultra",
                        attack_type="Ultra",
                        skill_name=sk_name,
                        sp_base=0.0,
                        energy_cause="",
                        emit_before_skill=True,
                        emit_listen_before_skill=True,
                        pass_skill_targets_to_before_hooks=True,
                        emit_after_skill=True,
                        emit_action_end_hooks=True,
                        emit_settle_callback=True,
                    )
                )
                director = getattr(sim, "_stage_director", None)
                if director is not None and hasattr(director, "sync_spawned_entities"):
                    director.sync_spawned_entities()
            finally:
                setattr(ent, "_in_auto_ultra", False)


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
        enhanced: bool = False,
    ) -> None:
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.unit_id = int(avatar_or_servant_id)
        self.is_servant = is_servant
        self.enhanced = bool(enhanced)
        self._runtime = runtime
        self._loader = loader or (runtime.loader if runtime else GameDataLoader())
        if is_servant:
            self.spec = self._loader.load_servant(self.unit_id, eidolon=eidolon, trained_levels=skill_levels)
        else:
            self.spec = self._loader.load_character(
                self.unit_id,
                eidolon=eidolon,
                trained_levels=skill_levels,
                enhanced=self.enhanced,
            )
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
        self._hold_turn_skills: set[str] = {
            item.get("Name", "")
            for item in self.spec.config.get("SkillList", [])
            if isinstance(item, dict)
            and item.get("Name")
            and (item.get("AutoStandbyOnSkillFinish") is False or "FakeSkillConfig" in item)
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
            for ab_name in getattr(self.spec, "extra_passive_abilities", ()):
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
        self._loader._ensure_avatar_skills()
        av = self._loader.get_avatar_config(self.unit_id, enhanced=self.enhanced)
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
        sp_val = default_sp
        row = self._resolve_skill_row(sk_key)
        if row is not None:
            bp_need = row.get("BPNeed")
            bp_add = row.get("BPAdd")
            if isinstance(bp_need, dict) and float(bp_need.get("Value", 0.0)) > 0:
                sp_val = int(round(float(bp_need["Value"])))
            elif isinstance(bp_add, dict) and float(bp_add.get("Value", 0.0)) > 0:
                sp_val = -int(round(float(bp_add["Value"])))
            else:
                sp_val = 0
        rt = self._runtime or (
            getattr(self.port.sim, "vm_runtime", None)
            if (self.port and getattr(self.port, "sim", None))
            else None
        )
        if rt is not None and sp_val > 0:
            for ov in rt.skill_property_overrides.get(self.owner_id, ()):
                if ov.get("PropertyType") == "BPNeed" and (
                    not ov.get("SkillName") or ov.get("SkillName") == sk_key
                ):
                    op = str(ov.get("OperatorType", "Set"))
                    if op == "Unset":
                        continue
                    val = float(ov.get("Value", 0.0))
                    if op == "Mul":
                        sp_val = int(round(sp_val * val))
                    elif op == "Add":
                        sp_val = int(round(sp_val + val))
                    else:
                        sp_val = int(round(val))
        return ResourceCost(sp=sp_val)

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
            if ctx.kind in (ActionKind.BASIC, ActionKind.SKILL):
                rt.sim.scheduler.continuous_action_hold = (sk_key in self._hold_turn_skills)

        ab_list = self._skill_abilities.get(sk_key, [])
        if self.owner_id in rt.skill_property_overrides:
            rt.skill_property_overrides[self.owner_id] = [
                ov
                for ov in rt.skill_property_overrides[self.owner_id]
                if ov.get("SkillName") and ov.get("SkillName") != sk_key
            ]
            if not rt.skill_property_overrides[self.owner_id]:
                rt.skill_property_overrides.pop(self.owner_id, None)
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

        # 读取官方 ExcelOutput SPBase 能量基数
        row = self._resolve_skill_row(sk_key)
        sp_obj = (row.get("SPBase") or {}) if row else {}
        base_en = float(sp_obj.get("Value", 0.0)) if isinstance(sp_obj, dict) else 0.0

        # 只执行 Phase01/Phase02（跳过 _Camera）
        entry_ab = self._skill_entries.get(sk_key, "")
        entry = [entry_ab] if (entry_ab and not entry_ab.endswith("_Camera")) else (
            [a for a in ab_list if a.endswith("_Phase01")] or [a for a in ab_list if not a.endswith("_Camera")]
        )
        rt.lifecycle.run_ability_frame(
            AbilityFrameSpec(
                caster_id=self.owner_id,
                ability_name=(entry[0] if entry else ""),
                target_ids=eff_targets,
                skill_target_ids=eff_targets,
                skill_type=sk_type,
                attack_type=sk_type,
                skill_name=sk_key,
                sp_base=base_en,
                energy_cause=f"技能回能 {sk_key}",
                emit_ultra_prepare=(ctx.kind == ActionKind.ULTIMATE),
                emit_before_skill=True,
                emit_listen_before_skill=True,
                pass_skill_targets_to_before_hooks=True,
            )
        )


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

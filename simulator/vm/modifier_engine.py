"""官方 ConfigAbility Modifier 宿主引擎与优先级事件调度器 (Phase 2)。

核心职责：
1. 托管官方 `VMModifierInstance`（包含 `DynamicValues` 作用域、`Layer`/`MaxLayer`、`LifeTime`/`LifeStepMoment`、
   `AdditionConfig.SubModifierList` + `IsHaloStatus`、`BehaviorFlagList`、`Stacking` 策略）；
2. 将 `StackProperty` 实时同步到 `TurnSimulator.status_mgr`，无缝兼容 `DamageCalculator` 与 `Entity`；
   并追踪 `*Convert` 转化属性（如 `SpeedConvert` / `CriticalDamageConvert` / `HPConvert` / `HealRatioConvert`），
   彻底避免二次属性转化自循环；
3. 按整数 `Priority` 升序分发官方 `_CallbackList` 事件（如 `-92` 先于 `-80` 先于 `0`）；
4. 监听 `OnAbilityPropertyChange` 与 `OnDynamicValueChange` 范围阈值回调（`OnEnterRange` / `OnChange` / `OnExitRange`）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

from ..combat_port import BuffSpec
from ..status import DurationTiming, Modifier, ModifierOp, StatType, StatusTag
from .expr import dotnet_hash, eval_dynamic_float
from .target_alias import ExecutionContext, resolve_target_type

# 官方 Property 名 -> (StatType, ModifierOp, is_convert)
PROPERTY_TO_STAT: Dict[str, Tuple[StatType, ModifierOp, bool]] = {
    "MaxHP": (StatType.MAX_HP_PERCENT, ModifierOp.ADD, False),
    "HPDelta": (StatType.MAX_HP_PERCENT, ModifierOp.ADD, False),
    "HPAddedRatio": (StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, False),
    "HPConvert": (StatType.MAX_HP_PERCENT, ModifierOp.ADD, True),
    "Speed": (StatType.SPEED, ModifierOp.ADD, False),
    "SpeedDelta": (StatType.SPEED, ModifierOp.ADD, False),
    "SpeedAddedRatio": (StatType.SPEED, ModifierOp.PERCENT, False),
    "SpeedConvert": (StatType.SPEED, ModifierOp.ADD, True),
    "CriticalChanceBase": (StatType.CRIT_RATE, ModifierOp.ADD, False),
    "CriticalDamageBase": (StatType.CRIT_DMG, ModifierOp.ADD, False),
    "CriticalDamageConvert": (StatType.CRIT_DMG, ModifierOp.ADD, True),
    "AllDamageTypeAddedRatio": (StatType.DMG_BOOST, ModifierOp.ADD, False),
    "AllDamageTypeTakenRatio": (StatType.VULNERABILITY, ModifierOp.ADD, False),
    "AllDamageTypePenetrate": (StatType.RES_PEN, ModifierOp.ADD, False),
    "HealRatioBase": (StatType.OUTGOING_HEALING, ModifierOp.ADD, False),
    "HealRatioConvert": (StatType.OUTGOING_HEALING, ModifierOp.ADD, True),
    "StatusResistanceBase": (StatType.EFFECT_RES, ModifierOp.ADD, False),
    "AttackAddedRatio": (StatType.ATK_PERCENT, ModifierOp.PERCENT, False),
    "AttackDelta": (StatType.ATK_BASE, ModifierOp.ADD, False),
    "DefenceAddedRatio": (StatType.DEF_PERCENT, ModifierOp.PERCENT, False),
    "BreakDamageAddedRatioBase": (StatType.BREAK_EFFECT, ModifierOp.ADD, False),
    "SPRatioBase": (StatType.ERR, ModifierOp.ADD, False),
    "AggroAddedRatio": (StatType.AGGRO, ModifierOp.PERCENT, False),
}

CONVERT_PROPERTY_PAIR: Dict[str, str] = {
    "SpeedConvert": "Speed",
    "CriticalDamageConvert": "CriticalDamageBase",
    "HPConvert": "MaxHP",
    "HealRatioConvert": "HealRatioBase",
}


@dataclass
class VMModifierInstance:
    """运行中的官方 Modifier 实例。"""
    uid: int
    name: str
    caster_id: str
    owner_id: str
    ability_name: str
    config: Dict[str, Any]
    dynamic_values: Dict[int, float] = field(default_factory=dict)
    properties: Dict[str, float] = field(default_factory=dict)
    convert_properties: Dict[str, float] = field(default_factory=dict)
    layer: int = 1
    max_layer: int = 1
    life_time: Optional[float] = None
    life_step_moment: str = ""
    stacking: str = "ReplaceByCaster"
    behavior_flags: Set[str] = field(default_factory=set)
    sub_modifier_links: List[Tuple[str, str, int]] = field(default_factory=list)  # (target_id, mod_name, uid)
    is_halo: bool = False
    halo_parent_uid: Optional[int] = None
    range_states: Dict[Tuple[str, int, int], bool] = field(default_factory=dict)
    _spawn_order: int = 0
    _destroyed: bool = False

    @property
    def status_key(self) -> str:
        return f"VMMod::{self.name}::{self.uid}"


class ModifierEngine:
    """官方 Modifier 宿主、属性同步与优先级事件调度引擎。"""

    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self._next_uid = 1
        self._next_order = 1
        # owner_id -> list[VMModifierInstance]
        self.by_owner: Dict[str, List[VMModifierInstance]] = {}
        self.by_uid: Dict[int, VMModifierInstance] = {}
        # 追踪实体上一次属性采样值（用于 OnAbilityPropertyChange）
        self._last_props: Dict[Tuple[str, str], float] = {}
        self._last_apc_val: Dict[Tuple[int, int], float] = {}
        self._checking_apc: Set[Tuple[int, int]] = set()
        self._apc_defer_depth: int = 0
        self._dirty_apc_entities: Set[str] = set()

    def all_modifiers(self) -> List[VMModifierInstance]:
        return list(self.by_uid.values())

    def get_modifiers(self, owner_id: str, name: Optional[str] = None) -> List[VMModifierInstance]:
        mods = self.by_owner.get(owner_id, [])
        if name is None:
            return [m for m in mods if not m._destroyed]
        return [m for m in mods if not m._destroyed and m.name == name]

    def has_modifier(self, owner_id: str, name: str, caster_id: Optional[str] = None) -> bool:
        for m in self.get_modifiers(owner_id, name):
            if caster_id is None or m.caster_id == caster_id:
                return True
        return False

    def has_behavior_flag(self, owner_id: str, flag: str) -> bool:
        if flag in ("STAT_CTRL", "DisableAction"):
            sim = getattr(self.rt, "sim", None)
            port = getattr(sim, "port", None)
            if port is not None and port.is_action_suppressed(owner_id):
                return True
        for m in self.get_modifiers(owner_id):
            if flag in m.behavior_flags:
                return True
        return False

    def _lookup_modifier_config(self, mod_name: str, ability_name: str = "") -> Dict[str, Any]:
        # 1. 先查来源 Ability 的本地 Modifiers
        if ability_name:
            ab = self.rt.loader.get_ability(ability_name)
            if ab and mod_name in ab.get("Modifiers", {}):
                return ab["Modifiers"][mod_name]
        # 2. 查该实体的全部已加载 Abilities
        for spec in self.rt.entity_specs.values():
            for ab in spec.abilities.values():
                if mod_name in ab.get("Modifiers", {}):
                    return ab["Modifiers"][mod_name]
        # 3. 查 GlobalModifiers
        gm = self.rt.loader.get_global_modifier(mod_name)
        if gm is not None:
            return gm
        return {}

    def _resolve_mod_hash(self, mod: VMModifierInstance, hash_val: int) -> float:
        if hash_val in mod.dynamic_values:
            return mod.dynamic_values[hash_val]
        return self.rt.resolve_hash(mod.caster_id, hash_val, ability_name=mod.ability_name)

    def add_modifier(
        self,
        *,
        owner_id: str,
        caster_id: str,
        mod_name: str,
        ability_name: str = "",
        dynamic_values: Optional[Mapping[str, Any]] = None,
        life_time: Optional[float] = None,
        count: int = 1,
        max_layer: Optional[int] = None,
        ctx: Optional[ExecutionContext] = None,
        halo_parent_uid: Optional[int] = None,
        resolved_dynamics: Optional[Dict[int, float]] = None,
    ) -> Optional[VMModifierInstance]:
        """按官方 Stacking 语义挂载/刷新/叠加 Modifier，并触发 OnCreate / OnStack / SubModifierList / OnModifierAdd。"""
        if owner_id != "__LEVEL__" and self.rt.sim.get_entity(owner_id) is None:
            return None

        cfg = self._lookup_modifier_config(mod_name, ability_name)
        stacking = str(cfg.get("Stacking", "Unique"))

        # 确定 MaxLayer / LifeTime
        cfg_max_layer = cfg.get("MaxLayer")
        eff_max_layer = max_layer
        if eff_max_layer is None and cfg_max_layer is not None:
            eff_max_layer = int(round(eval_dynamic_float(
                cfg_max_layer,
                lambda h: self.rt.resolve_hash(caster_id, h, ability_name=ability_name, local_ctx=ctx),
                1.0,
            )))
        if eff_max_layer is None:
            if stacking == "Stack" or count > 1:
                eff_max_layer = 99
            else:
                eff_max_layer = 1

        eff_life = life_time
        if eff_life is None and "LifeTime" in cfg:
            eff_life = eval_dynamic_float(
                cfg["LifeTime"],
                lambda h: self.rt.resolve_hash(caster_id, h, ability_name=ability_name, local_ctx=ctx),
                1.0,
            )

        # 解析传入 DynamicValues
        parsed_dyn: Dict[int, float] = dict(resolved_dynamics) if resolved_dynamics else {}
        if dynamic_values and not resolved_dynamics:
            eval_caster = ctx.caster_id if ctx is not None else caster_id
            for k, v in dynamic_values.items():
                val = eval_dynamic_float(
                    v,
                    lambda h: self.rt.resolve_hash(eval_caster, h, ability_name=ability_name, local_ctx=ctx),
                    0.0,
                )
                parsed_dyn[dotnet_hash(k)] = val

        # 检查 Stacking 碰撞
        existing_list = self.get_modifiers(owner_id, mod_name)
        target_existing: Optional[VMModifierInstance] = None
        if stacking == "ReplaceByCaster":
            for m in existing_list:
                if m.caster_id == caster_id:
                    target_existing = m
                    break
        elif stacking == "Unique":
            if existing_list:
                return existing_list[0]
        elif stacking in ("Replace", "Refresh"):
            if existing_list:
                target_existing = existing_list[0]
        elif stacking == "Stack":
            for m in existing_list:
                if m.caster_id == caster_id:
                    target_existing = m
                    break

        is_new = target_existing is None
        if target_existing is not None:
            mod = target_existing
            if count < 0:
                mod.layer = max(0, mod.layer + count)
            elif eff_max_layer > 1:
                mod.layer = min(eff_max_layer, mod.layer + max(1, count))
            else:
                mod.layer = max(1, count)
            mod.max_layer = eff_max_layer
            if eff_life is not None:
                mod.life_time = eff_life
            mod.dynamic_values.update(parsed_dyn)
            if ability_name:
                mod.ability_name = ability_name
        else:
            uid = self._next_uid
            self._next_uid += 1
            order = self._next_order
            self._next_order += 1
            mod = VMModifierInstance(
                uid=uid,
                name=mod_name,
                caster_id=caster_id,
                owner_id=owner_id,
                ability_name=ability_name,
                config=cfg,
                dynamic_values=parsed_dyn,
                layer=min(eff_max_layer, max(1, count)),
                max_layer=eff_max_layer,
                life_time=eff_life,
                life_step_moment=str(cfg.get("LifeStepMoment") or "TurnEnd"),
                stacking=stacking,
                behavior_flags=set(cfg.get("BehaviorFlagList", [])),
                halo_parent_uid=halo_parent_uid,
                _spawn_order=order,
            )
            self.by_owner.setdefault(owner_id, []).append(mod)
            self.by_uid[uid] = mod

        # 执行静态 Properties（若配置有直接写 Property 字段）
        self._apply_static_modifier_props(mod)

        if mod.life_time is not None and mod.life_step_moment == "TurnEnd":
            sim = getattr(self.rt, "sim", None)
            cur = getattr(sim, "_current_turn_entity", None)
            if cur is not None and getattr(cur, "name", None) == owner_id:
                skip_set = getattr(self, "_skip_turn_end_uids", None)
                if skip_set is None:
                    skip_set = set()
                    self._skip_turn_end_uids = skip_set
                skip_set.add(mod.uid)

        # 触发 OnCreate (仅首次) 与 OnStack (每次)
        mod_ctx = ExecutionContext(
            runtime=self.rt,
            caster_id=caster_id,
            ability_name=mod.ability_name,
            modifier_owner_id=owner_id,
            modifier_instance=mod,
        )
        if is_new:
            self.dispatch_modifier_callbacks(mod, "OnCreate", mod_ctx)

        # OnStack 前清空动态 StackProperty（允许同窗内多层乘算/覆盖重算）
        self._apc_defer_depth += 1
        try:
            mod.properties.clear()
            mod.convert_properties.clear()
            self._apply_static_modifier_props(mod)
            self.dispatch_modifier_callbacks(mod, "OnStack", mod_ctx)
            self._sync_modifier_to_status_mgr(mod)

            # 处理 AdditionConfig.SubModifierList (如光环下发/刷新)
            self._attach_sub_modifiers(mod, mod_ctx)

            # 触发全局 OnModifierAdd / OnListenModifierAdd
            if is_new:
                self.dispatch_event(
                    "OnModifierAdd",
                    owner_id=owner_id,
                    param_entity_id=owner_id,
                    callback_modifier_name=mod_name,
                    callback_behavior_flags=tuple(mod.behavior_flags),
                )
                self.dispatch_event(
                    "OnListenModifierAdd",
                    param_entity_id=owner_id,
                    callback_modifier_name=mod_name,
                    callback_behavior_flags=tuple(mod.behavior_flags),
                )
            self._dirty_apc_entities.add(owner_id)
        finally:
            self._apc_defer_depth -= 1

        if self._apc_defer_depth == 0:
            self._flush_dirty_apc()
        if is_new:
            self._init_dynamic_value_ranges(mod, mod_ctx)
        return mod

    def _flush_dirty_apc(self) -> None:
        while self._dirty_apc_entities:
            batch = list(self._dirty_apc_entities)
            self._dirty_apc_entities.clear()
            for eid in batch:
                self.check_property_changes(eid)

    def _apply_static_modifier_props(self, mod: VMModifierInstance) -> None:
        props_cfg = mod.config.get("Properties")
        if isinstance(props_cfg, dict):
            for prop_name, val_spec in props_cfg.items():
                val = eval_dynamic_float(val_spec, lambda h: self._resolve_mod_hash(mod, h), 0.0)
                if val:
                    mod.properties[prop_name] = mod.properties.get(prop_name, 0.0) + val

    def _attach_sub_modifiers(self, mod: VMModifierInstance, mod_ctx: ExecutionContext) -> None:
        add_cfg = mod.config.get("AdditionConfig")
        if not isinstance(add_cfg, dict):
            return
        for sub in add_cfg.get("SubModifierList", []):
            if not isinstance(sub, dict):
                continue
            sub_name = sub.get("Name")
            if not sub_name:
                continue
            targets = resolve_target_type(sub.get("TargetType"), mod_ctx)
            is_halo = bool(sub.get("IsHaloStatus", False))
            existing_links = {(t, n, u) for (t, n, u) in mod.sub_modifier_links}
            for tid in targets:
                child = self.add_modifier(
                    owner_id=tid,
                    caster_id=mod.caster_id,
                    mod_name=sub_name,
                    ability_name=mod.ability_name,
                    dynamic_values=sub.get("DynamicValues"),
                    life_time=None,
                    ctx=mod_ctx,
                    halo_parent_uid=mod.uid,
                )
                if child is not None:
                    child.is_halo = is_halo
                    link = (tid, sub_name, child.uid)
                    if link not in existing_links:
                        existing_links.add(link)
                        mod.sub_modifier_links.append(link)

    def attach_halos_to_new_entity(self, new_entity_id: str) -> None:
        """仅向新入场实体补发带有 IsHaloStatus 的 SubModifierList（不触发 OnListenCharacterCreate）。"""
        for mod in list(self.by_uid.values()):
            if mod._destroyed:
                continue
            add_cfg = mod.config.get("AdditionConfig")
            if not isinstance(add_cfg, dict):
                continue
            mod_ctx = ExecutionContext(
                runtime=self.rt,
                caster_id=mod.caster_id,
                ability_name=mod.ability_name,
                modifier_owner_id=mod.owner_id,
                modifier_instance=mod,
            )
            for sub in add_cfg.get("SubModifierList", []):
                if not isinstance(sub, dict) or not sub.get("IsHaloStatus"):
                    continue
                sub_name = sub.get("Name")
                if not sub_name:
                    continue
                targets = resolve_target_type(sub.get("TargetType"), mod_ctx)
                if new_entity_id in targets and not self.has_modifier(new_entity_id, sub_name, mod.caster_id):
                    child = self.add_modifier(
                        owner_id=new_entity_id,
                        caster_id=mod.caster_id,
                        mod_name=sub_name,
                        ability_name=mod.ability_name,
                        dynamic_values=sub.get("DynamicValues"),
                        ctx=mod_ctx,
                        halo_parent_uid=mod.uid,
                    )
                    if child is not None:
                        child.is_halo = True
                        mod.sub_modifier_links.append((new_entity_id, sub_name, child.uid))

    def on_entity_created(self, new_entity_id: str) -> None:
        """新实体（如忆灵）入场时：
        1. 对带有 IsHaloStatus 的 SubModifierList 自动向新实体补发；
        2. 分发 OnListenCharacterCreate(ParamEntity=new_entity_id)。
        """
        self.attach_halos_to_new_entity(new_entity_id)
        self.dispatch_event("OnListenCharacterCreate", param_entity_id=new_entity_id)

    def remove_modifier(
        self,
        owner_id: str,
        mod_name: str,
        *,
        caster_id: Optional[str] = None,
        only_remove_caster_added: bool = False,
    ) -> int:
        targets = [
            m
            for m in self.get_modifiers(owner_id, mod_name)
            if (not only_remove_caster_added or caster_id is None or m.caster_id == caster_id)
        ]
        for m in targets:
            self.destroy_modifier(m)
        return len(targets)

    def destroy_modifier(self, mod: VMModifierInstance, *, reason: str = "EXPLICIT") -> None:
        if mod._destroyed:
            return
        mod._destroyed = True

        # 触发 OnDestroy
        mod_ctx = ExecutionContext(
            runtime=self.rt,
            caster_id=mod.caster_id,
            ability_name=mod.ability_name,
            modifier_owner_id=mod.owner_id,
            modifier_instance=mod,
        )
        self.dispatch_modifier_callbacks(mod, "OnDestroy", mod_ctx)

        # 级联拆除 SubModifierList 派生副本
        for _, _, child_uid in list(mod.sub_modifier_links):
            child = self.by_uid.get(child_uid)
            if child is not None and not child._destroyed:
                self.destroy_modifier(child, reason=reason)

        # 从索引和 StatusManager 摘除
        self.by_uid.pop(mod.uid, None)
        if mod.owner_id in self.by_owner:
            self.by_owner[mod.owner_id] = [m for m in self.by_owner[mod.owner_id] if m.uid != mod.uid]
        if mod.owner_id != "__LEVEL__" and self.rt.sim.get_entity(mod.owner_id) is not None:
            self.rt.sim.status_mgr.remove_status(mod.owner_id, mod.status_key, reason=reason)

        # 通知 OnModifierRemove / OnListenModifierRemove
        self.dispatch_event(
            "OnModifierRemove",
            owner_id=mod.owner_id,
            param_entity_id=mod.owner_id,
            callback_modifier_name=mod.name,
            callback_behavior_flags=tuple(mod.behavior_flags),
        )
        self.dispatch_event(
            "OnListenModifierRemove",
            param_entity_id=mod.owner_id,
            callback_modifier_name=mod.name,
            callback_behavior_flags=tuple(mod.behavior_flags),
        )
        if mod.owner_id != "__LEVEL__":
            self.check_property_changes(mod.owner_id)

    def destroy_all_for_entity(self, owner_id: str) -> None:
        """销毁实体自身挂载及由其施放的 RemoveWhenCasterDead Modifier。"""
        for m in list(self.get_modifiers(owner_id)):
            self.destroy_modifier(m)
        for m in list(self.by_uid.values()):
            if not m._destroyed and m.caster_id == owner_id and "RemoveWhenCasterDead" in m.behavior_flags:
                self.destroy_modifier(m)

    def stack_property(
        self,
        mod: VMModifierInstance,
        prop_name: str,
        value: float,
        *,
        is_convert: bool = False,
        is_refresh: bool = False,
    ) -> None:
        if prop_name in CONVERT_PROPERTY_PAIR or is_convert:
            base_prop = CONVERT_PROPERTY_PAIR.get(prop_name, prop_name)
            if is_refresh:
                mod.convert_properties[base_prop] = value
                mod.properties[prop_name] = value
            else:
                mod.convert_properties[base_prop] = mod.convert_properties.get(base_prop, 0.0) + value
                mod.properties[prop_name] = mod.properties.get(prop_name, 0.0) + value
        else:
            if is_refresh:
                mod.properties[prop_name] = value
            else:
                mod.properties[prop_name] = mod.properties.get(prop_name, 0.0) + value
        self._sync_modifier_to_status_mgr(mod)
        if mod.owner_id != "__LEVEL__":
            if self._apc_defer_depth > 0:
                self._dirty_apc_entities.add(mod.owner_id)
            else:
                self.check_property_changes(mod.owner_id)

    def _sync_modifier_to_status_mgr(self, mod: VMModifierInstance) -> None:
        if mod.owner_id == "__LEVEL__" or self.rt.sim.get_entity(mod.owner_id) is None:
            return
        mods: List[Modifier] = []
        tags = [StatusTag.SUPPRESS_STATUS_APPLY_EVENT]
        has_convert = False
        for prop_name, val in mod.properties.items():
            if abs(val) < 1e-12:
                continue
            # SpeedOverride 单独处理：覆盖基础速度（为 0 时冻结自然跑条）
            if prop_name == "SpeedOverride":
                ent = self.rt.sim.get_entity(mod.owner_id)
                if ent is not None:
                    ent.base_speed = float(val)
                    if float(val) <= 0.0:
                        ent.distance_remaining = 1e12
                continue
            if prop_name == "BaseSpeed":
                ent = self.rt.sim.get_entity(mod.owner_id)
                if ent is not None and getattr(ent, "is_countdown", False):
                    ent.base_speed = max(1.0, float(val))
                continue
            mapping = PROPERTY_TO_STAT.get(prop_name)
            if mapping is None:
                continue
            stat_type, op, is_conv = mapping
            if is_conv:
                has_convert = True
            mods.append(Modifier(stat=stat_type, op=op, value=float(val)))

        if not mods:
            self.rt.sim.status_mgr.remove_status(mod.owner_id, mod.status_key)
            return

        if has_convert:
            tags.append(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS)
        category = "debuff" if "STAT_DEBUFF" in mod.behavior_flags or any(
            m.stat == StatType.VULNERABILITY and m.value > 0 for m in mods
        ) else "buff"

        self.rt.sim.port.upsert_status(BuffSpec(
            key=mod.status_key,
            name=mod.name,
            source_id=mod.caster_id if self.rt.sim.get_entity(mod.caster_id) else mod.owner_id,
            target_id=mod.owner_id,
            modifiers=tuple(mods),
            duration=None,  # 生命周期由 VMModifierInstance.life_time 精确托管
            timing=DurationTiming.TARGET_TURN_END,
            category=category,
            tags=tuple(tags),
        ))

    def get_entity_property(self, entity_id: str, prop_name: str) -> float:
        """读取实体在官方引擎口径下的实时属性值（含 SpeedConvert / CriticalDamageConvert 等转化部分）。"""
        if entity_id == "__LEVEL__":
            return 0.0
        ent = self.rt.sim.get_entity(entity_id)
        if ent is None:
            return 0.0
        port = self.rt.sim.port
        if prop_name == "Speed":
            return float(ent.speed)
        if prop_name == "SpeedConvert":
            return sum(m.convert_properties.get("Speed", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "MaxHP":
            return float(port.max_hp(entity_id))
        if prop_name == "HPConvert":
            return sum(m.convert_properties.get("MaxHP", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "CurrentHP":
            return float(ent.current_hp)
        if prop_name == "HPRatio":
            m = float(port.max_hp(entity_id))
            return float(ent.current_hp / m) if m > 0 else 1.0
        if prop_name == "CriticalChanceBase":
            return float(ent.crit_rate)
        if prop_name == "CriticalDamageBase":
            return float(ent.crit_dmg)
        if prop_name == "CriticalDamageConvert":
            return sum(m.convert_properties.get("CriticalDamageBase", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "HealRatioBase":
            return float(port.stat(entity_id, StatType.OUTGOING_HEALING))
        if prop_name == "HealRatioConvert":
            return sum(m.convert_properties.get("HealRatioBase", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "BaseSpeed":
            return float(ent.base_speed)
        if prop_name == "AllDamageTypeAddedRatio":
            return float(port.stat(entity_id, StatType.DMG_BOOST))
        mapping = PROPERTY_TO_STAT.get(prop_name)
        if mapping is not None:
            return float(port.stat(entity_id, mapping[0]))
        return 0.0

    def check_property_changes(self, entity_id: str) -> None:
        """检查该实体上订阅了 OnAbilityPropertyChange 的 Modifier 是否发生区间进入/变化/离开。"""
        if entity_id == "__LEVEL__" or self.rt.sim.get_entity(entity_id) is None:
            return
        for mod in list(self.get_modifiers(entity_id)):
            if mod._destroyed:
                continue
            apcs = mod.config.get("OnAbilityPropertyChange")
            if not isinstance(apcs, list):
                continue
            mod_ctx = ExecutionContext(
                runtime=self.rt,
                caster_id=mod.caster_id,
                ability_name=mod.ability_name,
                modifier_owner_id=mod.owner_id,
                modifier_instance=mod,
            )
            for idx_apc, apc in enumerate(apcs):
                prop_name = apc.get("Property", "")
                if not prop_name:
                    continue
                apc_key = (mod.uid, idx_apc)
                if apc_key in self._checking_apc:
                    continue
                cur_val = self.get_entity_property(entity_id, prop_name)
                prev_val = self._last_apc_val.get(apc_key)
                changed = prev_val is None or abs(cur_val - prev_val) > 1e-6
                self._last_apc_val[apc_key] = cur_val

                self._checking_apc.add(apc_key)
                try:
                    for idx_rng, rng in enumerate(apc.get("Ranges", [])):
                        lo = eval_dynamic_float(rng.get("Min"), lambda h: self._resolve_mod_hash(mod, h), -1e18)
                        hi = eval_dynamic_float(rng.get("Max"), lambda h: self._resolve_mod_hash(mod, h), 1e18)
                        in_range = (lo <= cur_val <= hi)
                        key = (prop_name, idx_apc, idx_rng)
                        was_in = mod.range_states.get(key, False)
                        mod.range_states[key] = in_range
                        if in_range and not was_in:
                            self.rt.execute_tasks(rng.get("OnEnterRange", []), mod_ctx)
                            self.rt.execute_tasks(rng.get("OnChange", []), mod_ctx)
                        elif in_range and was_in and changed:
                            self.rt.execute_tasks(rng.get("OnChange", []), mod_ctx)
                        elif not in_range and was_in:
                            self.rt.execute_tasks(rng.get("OnExitRange", []), mod_ctx)
                finally:
                    self._checking_apc.discard(apc_key)

    def _init_dynamic_value_ranges(self, mod: VMModifierInstance, mod_ctx: ExecutionContext) -> None:
        """初始化新建 Modifier 上的 OnDynamicValueChange 范围状态并触发初始入域回调。"""
        if mod._destroyed:
            return
        dvcs = mod.config.get("OnDynamicValueChange")
        if not isinstance(dvcs, list):
            return
        for idx_dvc, dvc in enumerate(dvcs):
            if mod._destroyed:
                return
            k = dvc.get("Key", {})
            target_h = int(k.get("Hash", 0)) if isinstance(k, dict) else 0
            if not target_h:
                continue
            scope = dvc.get("ContextScope", "")
            scope_eid = mod.caster_id if scope == "ContextCaster" else mod.owner_id
            cur_val = self.rt.resolve_hash(scope_eid, target_h, ability_name=mod.ability_name, local_ctx=mod_ctx)
            for idx_rng, rng in enumerate(dvc.get("Ranges", [])):
                lo = eval_dynamic_float(rng.get("Min"), lambda h: self._resolve_mod_hash(mod, h), -1e18)
                hi = eval_dynamic_float(rng.get("Max"), lambda h: self._resolve_mod_hash(mod, h), 1e18)
                now_in = (lo <= cur_val <= hi)
                state_key = ("dvc", idx_dvc, idx_rng)
                mod.range_states[state_key] = now_in
                if now_in:
                    self.rt.execute_tasks(rng.get("OnEnterRange", []), mod_ctx)

    def check_dynamic_value_changes(self, owner_id: str, key_hash: int, old_val: float, new_val: float) -> None:
        """触发订阅了 OnDynamicValueChange 的监听（如晴歌 HyperValue 同步）。"""
        for mod in list(self.by_uid.values()):
            if mod._destroyed:
                continue
            dvcs = mod.config.get("OnDynamicValueChange")
            if not isinstance(dvcs, list):
                continue
            mod_ctx = ExecutionContext(
                runtime=self.rt,
                caster_id=mod.caster_id,
                ability_name=mod.ability_name,
                modifier_owner_id=mod.owner_id,
                modifier_instance=mod,
            )
            for idx_dvc, dvc in enumerate(dvcs):
                k = dvc.get("Key", {})
                target_h = int(k.get("Hash", 0)) if isinstance(k, dict) else 0
                if target_h != key_hash:
                    continue
                scope = dvc.get("ContextScope", "")
                if scope == "ContextCaster" and mod.caster_id != owner_id:
                    continue
                if scope != "ContextCaster" and mod.owner_id != owner_id:
                    continue
                for idx_rng, rng in enumerate(dvc.get("Ranges", [])):
                    lo = eval_dynamic_float(rng.get("Min"), lambda h: self._resolve_mod_hash(mod, h), -1e18)
                    hi = eval_dynamic_float(rng.get("Max"), lambda h: self._resolve_mod_hash(mod, h), 1e18)
                    state_key = ("dvc", idx_dvc, idx_rng)
                    was_in = mod.range_states.get(state_key, (lo <= old_val <= hi))
                    now_in = (lo <= new_val <= hi)
                    mod.range_states[state_key] = now_in
                    if now_in and not was_in:
                        self.rt.execute_tasks(rng.get("OnEnterRange", []), mod_ctx)
                    if now_in:
                        self.rt.execute_tasks(rng.get("OnChange", []), mod_ctx)
                    if not now_in and was_in:
                        self.rt.execute_tasks(rng.get("OnExitRange", []), mod_ctx)

    def tick_life_step(self, moment: str, actor_id: str) -> None:
        """按官方 LifeStepMoment 衰减 Modifier 剩余回合数（如 ModifierPhase1End / TurnEnd）。"""
        skip_set = getattr(self, "_skip_turn_end_uids", None) if moment == "TurnEnd" else None
        for mod in list(self.by_uid.values()):
            if mod._destroyed or mod.life_time is None:
                continue
            # ModifierPhase1End 与 TurnEnd 都在 Caster 或 Owner 对应时机扣减
            # 注：风堇雨过天晴 LifeStepMoment=ModifierPhase1End 挂在风堇自身 (Caster==Owner==风堇)
            if mod.life_step_moment and mod.life_step_moment != moment:
                continue
            if mod.owner_id != actor_id and mod.caster_id != actor_id:
                continue
            # 常规在场期间风堇等自身回合结束扣减：若 owner==actor 扣减（在自身回合内新挂/刷新的 TurnEnd 效果跳过本回合末扣减）
            if mod.owner_id == actor_id:
                if skip_set is not None and mod.uid in skip_set:
                    skip_set.discard(mod.uid)
                    continue
                mod.life_time -= 1.0
                if mod.life_time <= 0.0:
                    self.destroy_modifier(mod, reason="EXPIRED")

    def dispatch_modifier_callbacks(self, mod: VMModifierInstance, event_name: str, ctx: ExecutionContext) -> None:
        for cb in mod.config.get("_CallbackList", []):
            if cb.get("Event") == event_name:
                self.rt.execute_tasks(cb.get("CallbackConfig", []), ctx)

    def dispatch_event(
        self,
        event_name: str,
        *,
        owner_id: Optional[str] = None,
        param_entity_id: Optional[str] = None,
        param_entity2_id: Optional[str] = None,
        ability_target_ids: Tuple[str, ...] = (),
        skill_target_ids: Tuple[str, ...] = (),
        param_skill_targets: Tuple[str, ...] = (),
        attack_target_ids: Tuple[str, ...] = (),
        damage_data: Optional[Dict[str, Any]] = None,
        heal_data: Optional[Dict[str, Any]] = None,
        callback_modifier_name: str = "",
        callback_behavior_flags: Tuple[str, ...] = (),
        change_value: float = 0.0,
        current_skill_type: str = "",
        current_attack_type: str = "",
        param_flags: Tuple[str, ...] = (),
    ) -> None:
        """收集所有订阅该事件的 Modifier 回调，严格按 Priority 升序 (-92 -> -80 -> 0 -> +N) 执行。"""
        entries: List[Tuple[int, int, VMModifierInstance, List[Dict[str, Any]]]] = []
        is_owner_scoped = owner_id is not None and not event_name.startswith("OnListen")

        for mod in list(self.by_uid.values()):
            if mod._destroyed:
                continue
            if is_owner_scoped and mod.owner_id != owner_id:
                continue
            for cb in mod.config.get("_CallbackList", []):
                if cb.get("Event") == event_name:
                    prio = int(cb.get("Priority", 0))
                    entries.append((prio, mod._spawn_order, mod, cb.get("CallbackConfig", [])))

        entries.sort(key=lambda item: (item[0], item[1]))
        for _, _, mod, tasks in entries:
            if mod._destroyed:
                continue
            ctx = ExecutionContext(
                runtime=self.rt,
                caster_id=mod.caster_id,
                ability_name=mod.ability_name,
                modifier_owner_id=mod.owner_id,
                modifier_instance=mod,
                ability_target_ids=ability_target_ids,
                skill_target_ids=skill_target_ids,
                param_skill_targets=param_skill_targets or skill_target_ids,
                attack_target_ids=attack_target_ids,
                param_entity_id=param_entity_id,
                param_entity2_id=param_entity2_id,
                damage_data=damage_data,
                heal_data=heal_data,
                callback_modifier_name=callback_modifier_name,
                callback_behavior_flags=callback_behavior_flags,
                change_value=change_value,
                current_skill_type=current_skill_type,
                current_attack_type=current_attack_type,
                param_flags=param_flags,
            )
            self.rt.execute_tasks(tasks, ctx)

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
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..lifecycle import emit_sim_event
from ..status import ModifierOp, StatType, StatusTag
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
    "DefenceDelta": (StatType.DEF, ModifierOp.ADD, False),
    "BreakDamageAddedRatioBase": (StatType.BREAK_EFFECT, ModifierOp.ADD, False),
    "StanceBreakAddedRatio": (StatType.BREAK_EFFICIENCY, ModifierOp.ADD, False),
    "SPRatioBase": (StatType.ERR, ModifierOp.ADD, False),
    "AggroAddedRatio": (StatType.AGGRO, ModifierOp.PERCENT, False),
    "FatigueRatio": (StatType.FATIGUE, ModifierOp.ADD, False),
    "ElationDamageAddedRatio": (StatType.ELATION, ModifierOp.ADD, False),
    "ElationDamageAddedRatioBase": (StatType.ELATION, ModifierOp.ADD, False),
    "ElationDamageAddedRatioConvert": (StatType.ELATION, ModifierOp.ADD, True),
    "ElationDamageExtraAddedRatio": (StatType.ELATION_EXTRA, ModifierOp.ADD, False),
    "AttackConvert": (StatType.ATK_BASE, ModifierOp.ADD, True),
}

CONVERT_PROPERTY_PAIR: Dict[str, str] = {
    "SpeedConvert": "Speed",
    "CriticalDamageConvert": "CriticalDamageBase",
    "HPConvert": "MaxHP",
    "HealRatioConvert": "HealRatioBase",
    "ElationDamageAddedRatioConvert": "ElationDamageAddedRatioBase",
    "AttackConvert": "Attack",
}

ELEMENT_RESISTANCE_DELTA_PROPS: Dict[str, str] = {
    "PhysicalResistanceDelta": "Physical",
    "FireResistanceDelta": "Fire",
    "IceResistanceDelta": "Ice",
    "ThunderResistanceDelta": "Lightning",
    "WindResistanceDelta": "Wind",
    "QuantumResistanceDelta": "Quantum",
    "ImaginaryResistanceDelta": "Imaginary",
}

MAX_HP_AFFECTING_PROPS = frozenset({"MaxHP", "HPDelta", "HPAddedRatio", "HPConvert"})


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
    caster_snapshot_entity: Optional[Any] = None
    caster_snapshot_props: Dict[str, float] = field(default_factory=dict)
    _spawn_order: int = 0
    _destroyed: bool = False
    _stats_detached: bool = False
    shield_value: float = 0.0
    shield_max: float = 0.0
    stacked_weaknesses: Dict[str, List[Tuple[str, Tuple[str, ...]]]] = field(default_factory=dict)
    weak_resistance_deltas: Dict[str, List[Tuple[str, str, float]]] = field(default_factory=dict)
    custom_strings: Dict[str, str] = field(default_factory=dict)

    def resolve_bound_value(self, hash_val: int) -> Optional[float]:
        add_cfg = self.config.get("AdditionConfig")
        if not isinstance(add_cfg, Mapping):
            return None
        vbinds = add_cfg.get("ValueBindList")
        if not isinstance(vbinds, list):
            return None
        for entry in vbinds:
            if not isinstance(entry, Mapping):
                continue
            dk = entry.get("DynamicKey")
            if not isinstance(dk, Mapping):
                continue
            h = int(dk["Hash"]) if "Hash" in dk else (dotnet_hash(str(dk["Value"])) if "Value" in dk else None)
            if h == hash_val:
                btype = str(entry.get("BindType") or "Layer")
                if btype in ("Layer", "Count"):
                    return float(self.layer)
                if btype == "MaxLayer":
                    return float(self.max_layer)
                if btype == "LifeTime":
                    return float(self.life_time or 0.0)
        return None


class ModifierEngine:
    """官方 Modifier 宿主、属性与优先级事件调度引擎。"""

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
        self._deferred_prev_props_by_uid: Dict[int, Dict[str, float]] = {}

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

    def notify_entangle_being_attacked(
        self,
        owner_id: str,
        attacker_id: str,
        *,
        attack_type: Optional[str] = None,
    ) -> None:
        """向受击敌方目标上的 MCommon_Element_Entangle 派发 OnBeforeBeingAttacked。"""
        ent = self.rt.sim.get_entity(owner_id)
        if ent is None or not getattr(ent, "is_enemy", False):
            return
        for m_entg in list(self.get_modifiers(owner_id, "MCommon_Element_Entangle")):
            entg_ctx = ExecutionContext(
                runtime=self.rt,
                caster_id=m_entg.caster_id,
                ability_name=m_entg.ability_name,
                param_entity_id=attacker_id,
                modifier_owner_id=owner_id,
                modifier_instance=m_entg,
                current_attack_type=attack_type,
                custom_strings=dict(m_entg.custom_strings),
            )
            self.dispatch_modifier_callbacks(m_entg, "OnBeforeBeingAttacked", entg_ctx)

    def has_behavior_flag(self, owner_id: str, flag: str) -> bool:
        if flag in ("STAT_CTRL", "DisableAction"):
            sim = getattr(self.rt, "sim", None)
            port = getattr(sim, "port", None)
            if port is not None and port.is_action_suppressed(owner_id):
                return True
        if flag == "Break":
            sim = getattr(self.rt, "sim", None)
            ent = sim.get_entity(owner_id) if sim is not None else None
            if ent is not None and getattr(ent, "is_broken", False):
                return True
        for m in self.get_modifiers(owner_id):
            if flag in m.behavior_flags:
                return True
        return False

    def iter_stat_modifiers(
        self,
        entity_name: str,
        *,
        exclude_tags: Tuple[str, ...] = (),
        category: Optional[str] = None,
    ):
        """产出实体当前生效的 VM Modifier 属性项 `(StatType, ModifierOp, float)`，消除双账本镜像。"""
        exclude_transfers = StatusTag.EXCLUDE_FROM_STAT_TRANSFERS in exclude_tags
        for mod in self.by_owner.get(entity_name, ()):
            if mod._stats_detached:
                continue
            props = self._deferred_prev_props_by_uid.get(mod.uid)
            if props is None:
                props = mod.properties
            if not props:
                continue
            mapped: List[Tuple[StatType, ModifierOp, float]] = []
            has_convert = False
            has_vuln = False
            for prop_name, val in props.items():
                fval = float(val)
                if abs(fval) < 1e-12:
                    continue
                mapping = PROPERTY_TO_STAT.get(prop_name)
                if mapping is None:
                    continue
                stat_type, op, is_conv = mapping
                if is_conv:
                    has_convert = True
                if stat_type == StatType.VULNERABILITY and fval > 0:
                    has_vuln = True
                mapped.append((stat_type, op, fval))
            if not mapped:
                continue
            if has_convert and exclude_transfers:
                continue
            if category is not None:
                mod_cat = "debuff" if ("STAT_DEBUFF" in mod.behavior_flags or has_vuln) else "buff"
                if mod_cat != category:
                    continue
            for item in mapped:
                yield item

    def iter_snapshot_buffs(self, entity_name: str) -> List[Dict[str, Any]]:
        """生成面向 `StatusManager.get_detailed_snapshot()` 的只读 VM 状态快照列表。"""
        out: List[Dict[str, Any]] = []
        sim = getattr(self.rt, "sim", None)
        for mod in self.by_owner.get(entity_name, ()):
            if mod._destroyed or mod._stats_detached:
                continue
            mod_strs: List[str] = []
            has_vuln = False
            for prop_name, val in mod.properties.items():
                fval = float(val)
                if abs(fval) < 1e-12:
                    continue
                mapping = PROPERTY_TO_STAT.get(prop_name)
                if mapping is None:
                    continue
                m_stat, m_op, _ = mapping
                if m_stat == StatType.VULNERABILITY and fval > 0:
                    has_vuln = True
                if m_stat == StatType.MAX_HP_PERCENT:
                    if m_op == ModifierOp.PERCENT:
                        mod_strs.append(f"生命上限 +{fval * 100:.1f}%")
                    else:
                        mod_strs.append(f"生命上限 +{fval:.0f}")
                else:
                    is_pct = (
                        m_op == ModifierOp.PERCENT
                        or m_stat in (
                            StatType.ATK_PERCENT, StatType.SPEED, StatType.CRIT_RATE,
                            StatType.CRIT_DMG, StatType.RES_PEN, StatType.DMG_BOOST,
                            StatType.VULNERABILITY, StatType.DEF_SHRED, StatType.BREAK_EFFECT,
                            StatType.EFFECT_RES,
                        )
                    )
                    op_str = "%" if is_pct else ""
                    val_disp = fval * 100.0 if is_pct else fval
                    mod_strs.append(f"{m_stat.name} +{val_disp:.1f}{op_str}")
            st_type = self.get_modifier_status_type(mod)
            if st_type == "Debuff" or "STAT_DEBUFF" in mod.behavior_flags or has_vuln:
                category = "debuff"
            elif st_type == "Buff" or mod_strs:
                category = "buff"
            else:
                category = "other"
            src_ent = sim.get_entity(mod.caster_id) if sim is not None else None
            src_name = getattr(src_ent, "name", mod.caster_id) if src_ent is not None else mod.caster_id
            out.append({
                "id": f"{mod.name}#{mod.uid}",
                "name": mod.name,
                "source": src_name,
                "duration": mod.life_time,
                "timing": mod.life_step_moment,
                "stacks": mod.layer,
                "category": category,
                "modifiers_desc": ", ".join(mod_strs) if mod_strs else "特殊效果 / 机制生效中",
            })
        return out

    def get_modifier_status_type(self, mod: VMModifierInstance) -> str:
        """返回 Modifier 的官方 StatusType（先读自身/合成配置，再查官方 StatusConfig 系列表）。"""
        return str(mod.config.get("StatusType") or "") or self.rt.loader.get_modifier_status_type(mod.name)

    def can_dispel_modifier(self, mod: VMModifierInstance) -> bool:
        """校验 Modifier 是否允许被驱散（优先遵循 UnDispellable 标记与官方 StatusConfig.CanDispel）。"""
        if "UnDispellable" in mod.behavior_flags:
            return False
        official = self.rt.loader.get_modifier_can_dispel(mod.name)
        if official is not None:
            return bool(official)
        return bool(mod.config.get("CanDispel", True))

    def sync_entity_shield(self, entity_id: str) -> None:
        """将实体挂载的所有活性护盾 Modifier 最大有效盾量同步到 Entity.shield。"""
        if not entity_id or entity_id == "__LEVEL__":
            return
        ent = self.rt.sim.get_entity(entity_id)
        if ent is not None:
            ent.shield = max((m.shield_value for m in self.get_modifiers(entity_id) if m.shield_value > 0.0), default=0.0)

    def recompute_entity_weaknesses(self, entity_id: str, *, unlock_if_unprotected: bool = False) -> None:
        """根据实体初始弱点与当前全部活跃 Modifier 的 StackWeakness / ClearWeakness 声明重算有效弱点列表。"""
        if not entity_id or entity_id == "__LEVEL__":
            return
        ent = self.rt.sim.get_entity(entity_id)
        if ent is None:
            return
        if not hasattr(ent, "_base_weaknesses"):
            setattr(ent, "_base_weaknesses", list(getattr(ent, "weaknesses", [])))
        cur: List[str] = list(getattr(ent, "_base_weaknesses", []))

        director = getattr(self.rt.sim, "_stage_director", None)
        runner = getattr(director, "runner", None) if director is not None else None
        if runner is not None:
            try:
                mrs = runner.get_enemy_state(entity_id)
                for elem in getattr(mrs, "stacked_weaknesses", ()):
                    if elem not in cur:
                        cur.append(elem)
            except KeyError:
                pass

        has_protected: Optional[bool] = None
        protected_elems: Set[str] = set()
        for m in sorted(self.by_uid.values(), key=lambda x: x._spawn_order):
            if m._destroyed:
                continue
            ops = m.stacked_weaknesses.get(entity_id)
            if not ops:
                continue
            for op, elems in ops:
                if op == "Override":
                    cur = list(elems)
                elif op in ("Attach", "Add"):
                    for el in elems:
                        if el not in cur:
                            cur.append(el)
                elif op in ("Remove", "Clear", "ClearAttach"):
                    cur = [el for el in cur if el not in elems]
                elif op == "Protected":
                    has_protected = True
                    protected_elems.update(elems)
                elif op == "ClearProtected":
                    has_protected = False
                    if elems:
                        protected_elems.difference_update(elems)
                    else:
                        protected_elems.clear()

        ent.weaknesses[:] = cur
        setattr(ent, "_protected_weaknesses", set(protected_elems))
        if has_protected is True:
            ent.toughness_locked = True
        elif has_protected is False or unlock_if_unprotected:
            has_flag_lock = any(
                not m._destroyed and ("MuteBreak" in m.behavior_flags or "SingleBlock" in m.behavior_flags)
                for m in self.get_modifiers(entity_id)
            )
            if not has_flag_lock:
                ent.toughness_locked = False

    def recompute_entity_damage_res(self, entity_id: str) -> None:
        """根据实体初始属性抗性与当前全部活跃 Modifier 的 StackWeakResistance 声明重算 damage_res。"""
        if not entity_id or entity_id == "__LEVEL__":
            return
        ent = self.rt.sim.get_entity(entity_id)
        if ent is None:
            return
        if not hasattr(ent, "_base_damage_res"):
            setattr(ent, "_base_damage_res", dict(getattr(ent, "damage_res", {}) or {}))
        res: Dict[str, float] = dict(getattr(ent, "_base_damage_res", {}))
        for m in sorted(self.by_uid.values(), key=lambda x: x._spawn_order):
            if m._destroyed:
                continue
            deltas = m.weak_resistance_deltas.get(entity_id)
            if deltas:
                for stype, elem, val in deltas:
                    if stype == "Delta":
                        res[elem] = float(res.get(elem, 0.0)) + float(val)
                    else:
                        res[elem] = float(val)
            if m.owner_id == entity_id:
                for prop_name, elem in ELEMENT_RESISTANCE_DELTA_PROPS.items():
                    if prop_name in m.properties:
                        res[elem] = float(res.get(elem, 0.0)) + float(m.properties[prop_name])
        ent.damage_res = res

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
        bound = mod.resolve_bound_value(hash_val)
        if bound is not None:
            return bound
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
        count: Optional[int] = None,
        max_layer: Optional[int] = None,
        ctx: Optional[ExecutionContext] = None,
        halo_parent_uid: Optional[int] = None,
        resolved_dynamics: Optional[Dict[int, float]] = None,
        reference_mod_name: str = "",
        dynamic_strings: Optional[Mapping[str, Any]] = None,
    ) -> Optional[VMModifierInstance]:
        """按官方 Stacking 语义挂载/刷新/叠加 Modifier，并触发 OnCreate / OnStack / SubModifierList / OnModifierAdd。"""
        if owner_id != "__LEVEL__" and self.rt.sim.get_entity(owner_id) is None:
            return None

        eff_mod_name = mod_name or reference_mod_name
        if not eff_mod_name:
            return None
        cfg = self._lookup_modifier_config(eff_mod_name, ability_name)
        if not cfg and reference_mod_name and reference_mod_name != eff_mod_name:
            cfg = self._lookup_modifier_config(reference_mod_name, ability_name)
        mod_name = eff_mod_name
        add_cfg_check = cfg.get("AdditionConfig")
        if isinstance(add_cfg_check, dict):
            dep_add = add_cfg_check.get("DependencyOnAdd")
            if isinstance(dep_add, dict):
                dep_name = str(dep_add.get("DependentModifier") or "")
                if dep_name and not self.has_modifier(owner_id, dep_name):
                    return None
        stacking = str(cfg.get("Stacking", "Unique"))

        # 确定 MaxLayer / LifeTime
        # 官方免控机制：拥有 EnduranceLogicOnly / Endurance 标记时免疫控制类 Debuff (STAT_CTRL / DisableAction)
        incoming_flags = set(cfg.get("BehaviorFlagList", []))
        if (
            ("STAT_CTRL" in incoming_flags or "DisableAction" in incoming_flags or mod_name == "MCommon_Entangle")
            and (self.has_behavior_flag(owner_id, "EnduranceLogicOnly") or self.has_behavior_flag(owner_id, "Endurance"))
        ):
            return None

        cfg_count: Optional[int] = None
        if count is None and "Count" in cfg:
            cfg_count = int(round(eval_dynamic_float(
                cfg["Count"],
                lambda h: self.rt.resolve_hash(caster_id, h, ability_name=ability_name, local_ctx=ctx),
                1.0,
            )))
        init_count_val = count if count is not None else cfg_count

        cfg_max_layer = cfg.get("MaxLayer")
        eff_max_layer = max_layer
        if eff_max_layer is None and cfg_max_layer is not None:
            eff_max_layer = int(round(eval_dynamic_float(
                cfg_max_layer,
                lambda h: self.rt.resolve_hash(caster_id, h, ability_name=ability_name, local_ctx=ctx),
                1.0,
            )))
        if eff_max_layer is None:
            if stacking == "Stack" or (init_count_val is not None and init_count_val > 1) or cfg.get("LayerAddWhenStack") is not None:
                eff_max_layer = max(99, init_count_val or 1)
            else:
                eff_max_layer = 1

        eff_life = life_time
        if eff_life is None and "LifeTime" in cfg:
            eff_life = eval_dynamic_float(
                cfg["LifeTime"],
                lambda h: self.rt.resolve_hash(caster_id, h, ability_name=ability_name, local_ctx=ctx),
                1.0,
            )
        if eff_life is not None and eff_life < 0:
            eff_life = None

        # 解析传入 DynamicValues 与 DynamicStrings
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

        parsed_strs: Dict[str, str] = {}
        cfg_strs = cfg.get("DynamicStrings")
        if isinstance(cfg_strs, Mapping):
            for k, v in cfg_strs.items():
                if isinstance(v, Mapping):
                    parsed_strs[str(k)] = str(v.get("Value") or v.get("RawString") or "")
                elif v is not None:
                    parsed_strs[str(k)] = str(v)
        if isinstance(dynamic_strings, Mapping):
            for k, v in dynamic_strings.items():
                if isinstance(v, Mapping) and v.get("Custom"):
                    ck = str(v.get("Key") or "")
                    cval = ctx.custom_strings.get(ck) if ctx is not None else None
                    if cval is None:
                        cval = getattr(self.rt, "entity_dynamic_strings", {}).get(caster_id, {}).get(ck, "")
                    parsed_strs[str(k)] = str(cval)
                elif isinstance(v, Mapping):
                    raw_v = v.get("Value") if "Value" in v else v.get("RawString", "")
                    raw_s = str(raw_v or "")
                    if ctx is not None and raw_s in ctx.custom_strings:
                        parsed_strs[str(k)] = ctx.custom_strings[raw_s]
                    else:
                        parsed_strs[str(k)] = raw_s
                elif v is not None:
                    parsed_strs[str(k)] = str(v)

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
                add_cfg = cfg.get("AdditionConfig")
                if isinstance(add_cfg, dict) and add_cfg.get("SubModifierList") and "Stacking" not in cfg:
                    # 实机中未显式声明 Stacking 的光环父 Modifier（如 MRelic_127_Sub1）重复挂载会先卸载旧实例（含子光环并按比例缩放 HP / 刷新 APC）再重建
                    self.destroy_modifier(existing_list[0], reason="EXPIRED")
                else:
                    return existing_list[0]
        elif stacking in ("Replace", "Refresh", "Merge"):
            if existing_list:
                target_existing = existing_list[0]
        elif stacking == "Stack":
            for m in existing_list:
                if m.caster_id == caster_id:
                    target_existing = m
                    break

        is_new = target_existing is None
        prev_props = {} if is_new else dict(target_existing.properties)
        caster_snap = self.rt.sim.get_entity(caster_id) if caster_id != "__LEVEL__" else None
        caster_snap_props = (
            self._snapshot_entity_props(caster_id)
            if (caster_snap is not None and bool(cfg.get("UseSnapshotEntity", False)))
            else {}
        )
        if target_existing is not None:
            mod = target_existing
            if caster_snap is not None:
                mod.caster_snapshot_entity = caster_snap
            if caster_snap_props:
                mod.caster_snapshot_props = caster_snap_props
            if max_layer is None and cfg_max_layer is None and mod.max_layer > 1:
                eff_max_layer = mod.max_layer
            if count is not None:
                eff_count = count
            elif cfg.get("LayerAddWhenStack") is not None:
                eff_count = int(round(eval_dynamic_float(
                    cfg["LayerAddWhenStack"],
                    lambda h: self.rt.resolve_hash(caster_id, h, ability_name=ability_name, local_ctx=ctx),
                    1.0,
                )))
            elif cfg_count is not None and stacking in ("Replace", "ReplaceByCaster", "Refresh"):
                eff_count = cfg_count
            else:
                eff_count = 1
            if eff_count < 0:
                mod.layer = max(0, mod.layer + eff_count)
            elif cfg_count is not None and count is None and stacking in ("Replace", "ReplaceByCaster", "Refresh"):
                mod.layer = min(eff_max_layer, max(1, eff_count))
            elif eff_max_layer > 1:
                mod.layer = min(eff_max_layer, mod.layer + max(1, eff_count))
            else:
                mod.layer = max(1, eff_count)
            mod.max_layer = eff_max_layer
            if eff_life is not None:
                mod.life_time = eff_life
            mod.dynamic_values.update(parsed_dyn)
            if parsed_strs:
                mod.custom_strings.update(parsed_strs)
            if ability_name:
                mod.ability_name = ability_name
            if "HPAddedRatio" in mod.properties or "HPDelta" in mod.properties:
                for m_a in self.get_modifiers(owner_id):
                    apcs = m_a.config.get("OnAbilityPropertyChange")
                    if isinstance(apcs, list):
                        for idx_apc, apc in enumerate(apcs):
                            if apc.get("Property") in ("HPAddedRatio", "HPDelta"):
                                self._last_apc_val.pop((m_a.uid, idx_apc), None)
        else:
            uid = self._next_uid
            self._next_uid += 1
            order = self._next_order
            self._next_order += 1
            init_layer = min(eff_max_layer, max(1, init_count_val if init_count_val is not None else 1))
            mod = VMModifierInstance(
                uid=uid,
                name=mod_name,
                caster_id=caster_id,
                owner_id=owner_id,
                ability_name=ability_name,
                caster_snapshot_entity=caster_snap,
                caster_snapshot_props=caster_snap_props,
                config=cfg,
                dynamic_values=parsed_dyn,
                layer=init_layer,
                max_layer=eff_max_layer,
                life_time=eff_life,
                life_step_moment=str(cfg.get("LifeStepMoment") or "TurnEnd"),
                stacking=stacking,
                behavior_flags=set(cfg.get("BehaviorFlagList", [])),
                halo_parent_uid=halo_parent_uid,
                _spawn_order=order,
                custom_strings=parsed_strs,
            )
            self.by_owner.setdefault(owner_id, []).append(mod)
            self.by_uid[uid] = mod

        had_defer_entry = mod.uid in self._deferred_prev_props_by_uid
        prev_defer_entry = self._deferred_prev_props_by_uid.get(mod.uid)
        self._deferred_prev_props_by_uid[mod.uid] = prev_props
        try:
            # 执行静态 Properties（若配置有直接写 Property 字段）
            self._apply_static_modifier_props(mod)
            if "MuteBreak" in mod.behavior_flags and owner_id != "__LEVEL__":
                owner_ent = self.rt.sim.get_entity(owner_id)
                if owner_ent is not None:
                    owner_ent.toughness_locked = True

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
                custom_strings=dict(mod.custom_strings),
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
                owner_ent_hp = self.rt.sim.get_entity(owner_id) if owner_id != "__LEVEL__" else None
                sm_add = getattr(self.rt.sim, "status_mgr", None) if owner_ent_hp is not None else None
                need_hp_sync = (
                    owner_ent_hp is not None
                    and sm_add is not None
                    and (
                        any(p in MAX_HP_AFFECTING_PROPS for p in mod.properties)
                        or any(p in MAX_HP_AFFECTING_PROPS for p in prev_props)
                    )
                )
                old_max_hp_add: Optional[float] = (
                    sm_add._calc_entity_max_hp(owner_ent_hp) if need_hp_sync else None
                )
                if had_defer_entry and prev_defer_entry is not None:
                    self._deferred_prev_props_by_uid[mod.uid] = prev_defer_entry
                else:
                    self._deferred_prev_props_by_uid.pop(mod.uid, None)
                self._apply_modifier_side_effects(mod, old_max_hp=old_max_hp_add)

                # 触发全局 OnModifierAdd / OnListenModifierAdd / OnModifierOnStack / OnListenModifierOnStack
                mod_status_type = self.get_modifier_status_type(mod)
                if is_new:
                    self.dispatch_event(
                        "OnModifierAdd",
                        owner_id=owner_id,
                        param_entity_id=owner_id,
                        param_entity2_id=caster_id,
                        callback_modifier_name=mod_name,
                        callback_behavior_flags=tuple(mod.behavior_flags),
                        callback_status_type=mod_status_type,
                        callback_modifier_instance=mod,
                    )
                    self.dispatch_event(
                        "OnListenModifierAdd",
                        param_entity_id=owner_id,
                        param_entity2_id=caster_id,
                        callback_modifier_name=mod_name,
                        callback_behavior_flags=tuple(mod.behavior_flags),
                        callback_status_type=mod_status_type,
                        callback_modifier_instance=mod,
                    )
                self.dispatch_event(
                    "OnModifierOnStack",
                    owner_id=owner_id,
                    param_entity_id=owner_id,
                    param_entity2_id=caster_id,
                    callback_modifier_name=mod_name,
                    callback_behavior_flags=tuple(mod.behavior_flags),
                    callback_status_type=mod_status_type,
                    callback_modifier_instance=mod,
                    exclude_modifier_uid=mod.uid,
                )
                self.dispatch_event(
                    "OnListenModifierOnStack",
                    param_entity_id=owner_id,
                    param_entity2_id=caster_id,
                    callback_modifier_name=mod_name,
                    callback_behavior_flags=tuple(mod.behavior_flags),
                    callback_status_type=mod_status_type,
                    callback_modifier_instance=mod,
                    exclude_modifier_uid=mod.uid,
                )
                self._dirty_apc_entities.add(owner_id)
            finally:
                self._apc_defer_depth -= 1
        finally:
            if mod.uid in self._deferred_prev_props_by_uid:
                if had_defer_entry and prev_defer_entry is not None:
                    self._deferred_prev_props_by_uid[mod.uid] = prev_defer_entry
                else:
                    self._deferred_prev_props_by_uid.pop(mod.uid, None)

        if self._apc_defer_depth == 0:
            self._flush_dirty_apc()
        # 处理 AdditionConfig.SubModifierList (如光环下发/刷新): 在本体 APC 刷新后逐目标按站位序结算，与实机 L2745-2767 一致
        self._attach_sub_modifiers(mod, mod_ctx)
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
            sub_pred = sub.get("Predicate")
            if isinstance(sub_pred, dict) and not self.rt.executor.eval_predicate(sub_pred, mod_ctx):
                continue
            ref_name = str(sub.get("ReferenceModifierName") or "")
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
                    reference_mod_name=ref_name,
                )
                if child is not None:
                    child.is_halo = is_halo
                    link = (tid, sub_name, child.uid)
                    if link not in existing_links:
                        existing_links.add(link)
                        mod.sub_modifier_links.append(link)

    def attach_halos_to_new_entity(self, new_entity_id: str) -> None:
        """仅向新入场实体补发带有 IsHaloStatus 的 SubModifierList（关卡 __LEVEL__ 光环先于角色光环，确保关卡监听先挂）。"""
        ordered_mods = sorted(
            self.by_uid.values(),
            key=lambda m: (0 if m.owner_id == "__LEVEL__" else 1, m._spawn_order),
        )
        for mod in ordered_mods:
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
                custom_strings=dict(mod.custom_strings),
            )
            for sub in add_cfg.get("SubModifierList", []):
                if not isinstance(sub, dict) or not sub.get("IsHaloStatus"):
                    continue
                sub_name = sub.get("Name")
                if not sub_name:
                    continue
                sub_pred = sub.get("Predicate")
                if isinstance(sub_pred, dict) and not self.rt.executor.eval_predicate(sub_pred, mod_ctx):
                    continue
                ref_name = str(sub.get("ReferenceModifierName") or "")
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
                        reference_mod_name=ref_name,
                    )
                    if child is not None:
                        child.is_halo = True
                        mod.sub_modifier_links.append((new_entity_id, sub_name, child.uid))

    def on_entity_created(self, new_entity_id: str) -> None:
        """新实体（如忆灵或波次补员）入场时：
        1. 先分发 OnListenCharacterCreate(ParamEntity=new_entity_id)，挂好关卡监听型 Modifier（如 Grit / ResDown Track）；
        2. 再对带有 IsHaloStatus 的 SubModifierList 自动向新实体补发，确保 Debuff 入场同步触发上述监听。
        """
        self.dispatch_event("OnListenCharacterCreate", param_entity_id=new_entity_id)
        self.attach_halos_to_new_entity(new_entity_id)

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

        owner_ent = self.rt.sim.get_entity(mod.owner_id) if mod.owner_id != "__LEVEL__" else None
        if owner_ent is not None and "SingleBlock" in mod.behavior_flags:
            owner_ent.barrier_guarded = False
            has_other_lock = any(
                not m._destroyed
                and m.uid != mod.uid
                and ("MuteBreak" in m.behavior_flags or "SingleBlock" in m.behavior_flags)
                for m in self.get_modifiers(mod.owner_id)
            )
            if not has_other_lock:
                owner_ent.toughness_locked = False
            if hasattr(mod, "_saved_toughness_dmg_reduction"):
                owner_ent.toughness_dmg_reduction = float(getattr(mod, "_saved_toughness_dmg_reduction"))
        if owner_ent is not None and "MuteBreak" in mod.behavior_flags:
            has_other_lock = any(
                not m._destroyed
                and m.uid != mod.uid
                and ("MuteBreak" in m.behavior_flags or "SingleBlock" in m.behavior_flags)
                for m in self.get_modifiers(mod.owner_id)
            )
            if not has_other_lock:
                owner_ent.toughness_locked = False
        if getattr(mod, "_applied_lock_hp", False):
            director = getattr(self.rt.sim, "_stage_director", None)
            runner = getattr(director, "runner", None) if director is not None else None
            if runner is not None:
                try:
                    runner.get_enemy_state(mod.owner_id).lock_hp_ratio = None
                except KeyError:
                    pass
        if owner_ent is not None and getattr(mod, "_enabled_negative_hp", False):
            has_other_neg = any(
                not m._destroyed
                and m.uid != mod.uid
                and getattr(m, "_enabled_negative_hp", False)
                for m in self.get_modifiers(mod.owner_id)
            )
            if not has_other_neg:
                setattr(owner_ent, "_negative_hp_enabled", False)

        # 触发 OnDestroy
        mod_ctx = ExecutionContext(
            runtime=self.rt,
            caster_id=mod.caster_id,
            ability_name=mod.ability_name,
            modifier_owner_id=mod.owner_id,
            modifier_instance=mod,
            custom_strings=dict(mod.custom_strings),
        )
        self.dispatch_modifier_callbacks(mod, "OnDestroy", mod_ctx)

        # 级联拆除 SubModifierList 派生副本
        for _, _, child_uid in list(mod.sub_modifier_links):
            child = self.by_uid.get(child_uid)
            if child is not None and not child._destroyed:
                self.destroy_modifier(child, reason=reason)

        # 级联拆除 AdditionConfig.DependencyOnRemove 依赖该 Modifier 的同实体状态
        if not self.has_modifier(mod.owner_id, mod.name):
            for dep_mod in list(self.get_modifiers(mod.owner_id)):
                if dep_mod._destroyed:
                    continue
                d_add = dep_mod.config.get("AdditionConfig")
                d_rem = d_add.get("DependencyOnRemove") if isinstance(d_add, dict) else None
                if isinstance(d_rem, dict) and str(d_rem.get("DependentModifier") or "") == mod.name:
                    self.destroy_modifier(dep_mod, reason=reason)

        # 从索引摘除并同步受影响实体的生命上限/特殊副作用
        owner_alive = mod.owner_id != "__LEVEL__" and owner_ent is not None
        sm_rem = getattr(self.rt.sim, "status_mgr", None) if owner_alive else None
        had_max_hp = any(p in MAX_HP_AFFECTING_PROPS for p in mod.properties)
        old_max_hp_rem: Optional[float] = (
            sm_rem._calc_entity_max_hp(owner_ent) if (had_max_hp and sm_rem is not None) else None
        )
        mod._stats_detached = True
        self.by_uid.pop(mod.uid, None)
        if mod.owner_id in self.by_owner:
            self.by_owner[mod.owner_id] = [m for m in self.by_owner[mod.owner_id] if m.uid != mod.uid]
        if owner_alive:
            if had_max_hp and sm_rem is not None and old_max_hp_rem is not None:
                sm_rem.sync_entity_hp_after_max_hp_change(
                    owner_ent,
                    old_max_hp_rem,
                    is_removal=True,
                    reason=reason,
                )
            if "DirtyHPRatio" in mod.properties:
                self._recompute_dirty_hp_ratio(mod.owner_id)
            if any(p in mod.properties for p in ELEMENT_RESISTANCE_DELTA_PROPS):
                self.recompute_entity_damage_res(mod.owner_id)
        if mod.stacked_weaknesses:
            for tid, ops in list(mod.stacked_weaknesses.items()):
                had_prot = any(op == "Protected" for op, _ in ops)
                self.recompute_entity_weaknesses(tid, unlock_if_unprotected=had_prot)
        if mod.weak_resistance_deltas:
            for tid in list(mod.weak_resistance_deltas.keys()):
                self.recompute_entity_damage_res(tid)

        # 通知 OnModifierRemove / OnListenModifierRemove
        mod_status_type = self.get_modifier_status_type(mod)
        self.dispatch_event(
            "OnModifierRemove",
            owner_id=mod.owner_id,
            param_entity_id=mod.owner_id,
            param_entity2_id=mod.caster_id,
            callback_modifier_name=mod.name,
            callback_behavior_flags=tuple(mod.behavior_flags),
            callback_status_type=mod_status_type,
            callback_modifier_instance=mod,
        )
        self.dispatch_event(
            "OnListenModifierRemove",
            param_entity_id=mod.owner_id,
            param_entity2_id=mod.caster_id,
            callback_modifier_name=mod.name,
            callback_behavior_flags=tuple(mod.behavior_flags),
            callback_status_type=mod_status_type,
            callback_modifier_instance=mod,
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
        added = getattr(self.rt, "_added_abilities", None)
        if added:
            for k in [item for item in added if item[0] == owner_id]:
                added.discard(k)

    def strip_for_deathrattle(self, owner_id: str) -> None:
        """亡语阶段清理非 KeepOnDeathrattle 的状态与光环子修饰符。"""
        if self.has_behavior_flag(owner_id, "KeepAllModifierOnDeathRattle"):
            return
        for m in list(self.get_modifiers(owner_id)):
            if "KeepOnDeathrattle" not in m.behavior_flags and "Deathrattle" not in m.behavior_flags:
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
        is_deferred = mod.uid in self._deferred_prev_props_by_uid
        old_max_hp_sp: Optional[float] = None
        if not is_deferred and prop_name in MAX_HP_AFFECTING_PROPS and mod.owner_id != "__LEVEL__":
            owner_ent = self.rt.sim.get_entity(mod.owner_id)
            sm = getattr(self.rt.sim, "status_mgr", None) if owner_ent is not None else None
            if owner_ent is not None and sm is not None:
                old_max_hp_sp = sm._calc_entity_max_hp(owner_ent)
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
        if not is_deferred:
            self._apply_modifier_side_effects(mod, old_max_hp=old_max_hp_sp)
        if mod.owner_id != "__LEVEL__":
            if self._apc_defer_depth > 0:
                self._dirty_apc_entities.add(mod.owner_id)
            else:
                self.check_property_changes(mod.owner_id)

    def _apply_modifier_side_effects(
        self,
        mod: VMModifierInstance,
        *,
        old_max_hp: Optional[float] = None,
    ) -> None:
        """同步非纯属性累加类副作用：SpeedOverride / BaseSpeed / DirtyHPRatio / 元素抗性 / MaxHP 缩放。"""
        if mod.owner_id == "__LEVEL__":
            return
        ent = self.rt.sim.get_entity(mod.owner_id)
        if ent is None:
            return
        for prop_name, val in mod.properties.items():
            if abs(val) < 1e-12:
                continue
            if prop_name == "SpeedOverride":
                ent.base_speed = float(val)
                if float(val) <= 0.0:
                    ent.distance_remaining = 1e12
            elif prop_name == "BaseSpeed":
                if getattr(ent, "is_countdown", False):
                    ent.base_speed = max(1.0, float(val))
            elif prop_name == "DirtyHPRatio":
                self._recompute_dirty_hp_ratio(mod.owner_id)

        if any(p in mod.properties for p in ELEMENT_RESISTANCE_DELTA_PROPS):
            self.recompute_entity_damage_res(mod.owner_id)

        if old_max_hp is not None and getattr(self.rt.sim, "status_mgr", None) is not None:
            self.rt.sim.status_mgr.sync_entity_hp_after_max_hp_change(
                ent,
                old_max_hp,
                is_removal=False,
            )

    def _recompute_dirty_hp_ratio(self, owner_id: str) -> None:
        ent = self.rt.sim.get_entity(owner_id)
        if ent is None:
            return
        is_enemy = bool(getattr(ent, "is_enemy", False))
        if not is_enemy and self.has_behavior_flag(owner_id, "ImmuneDebuff"):
            return
        total_dirty = sum(
            float(m.properties.get("DirtyHPRatio", 0.0))
            for m in self.get_modifiers(owner_id)
            if not m._destroyed
        )
        old_hp = float(getattr(ent, "current_hp", 0.0))
        cap_ratio = 1.0 if is_enemy else 0.50
        ent.hp_lock_ratio = max(0.0, min(cap_ratio, total_dirty))
        self._dirty_apc_entities.add(owner_id)
        if not is_enemy:
            ent.clamp_hp()
            lost = old_hp - float(getattr(ent, "current_hp", 0.0))
            if lost > 1e-6:
                from simulator.events import HPLostEvent
                emit_sim_event(self.rt.sim, HPLostEvent(
                    av=self.rt.sim.current_av,
                    cycle=self.rt.sim.current_cycle,
                    entity_name=ent.name,
                    amount=lost,
                    hp_left=float(ent.current_hp),
                    cause="DirtyHPRatio",
                ))

    def _snapshot_entity_props(self, entity_id: str) -> Dict[str, float]:
        """在 UseSnapshotEntity 挂载/叠层瞬间快照施法者的面板属性（施法者阵亡离场后仍可读）。"""
        if not entity_id or entity_id == "__LEVEL__":
            return {}
        ent = self.rt.sim.get_entity(entity_id)
        if ent is None:
            return {}
        port = self.rt.sim.port
        be_val = float(port.stat(entity_id, StatType.BREAK_EFFECT))
        if getattr(ent, "is_memosprite", False) and getattr(ent, "master_name", None):
            be_val = max(be_val, float(port.stat(ent.master_name, StatType.BREAK_EFFECT)))
        return {
            "Attack": float(ent.atk),
            "BaseAttack": float(ent.base_atk),
            "MaxHP": float(port.max_hp(entity_id)),
            "BaseHP": float(ent.base_max_hp),
            "CurrentHP": float(ent.current_hp),
            "Defence": float(ent.defense),
            "BaseDefence": float(ent.base_def),
            "Speed": float(ent.speed),
            "BaseSpeed": float(ent.base_speed),
            "CriticalChanceBase": float(ent.crit_rate),
            "CriticalDamageBase": float(ent.crit_dmg),
            "BreakDamageAddedRatio": be_val,
            "BreakDamageAddedRatioBase": be_val,
            "AllDamageTypeAddedRatio": float(port.stat(entity_id, StatType.DMG_BOOST)),
            "ElationDamageAddedRatio": float(port.stat(entity_id, StatType.ELATION)),
            "ElationDamageAddedRatioBase": float(
                port.stat(entity_id, StatType.ELATION, exclude_tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS,))
            ),
            "ElationDamageExtraAddedRatio": float(port.stat(entity_id, StatType.ELATION_EXTRA)),
        }

    def get_entity_property(
        self,
        entity_id: str,
        prop_name: str,
        *,
        entity_override: Optional[Any] = None,
    ) -> float:
        """读取实体在官方引擎口径下的实时属性值（含 SpeedConvert / CriticalDamageConvert 等转化部分）。"""
        if entity_id == "__LEVEL__":
            return 0.0
        ent = self.rt.sim.get_entity(entity_id)
        used_override = False
        if ent is None and entity_override is not None:
            ent = entity_override
            used_override = True
        if ent is None:
            return 0.0
        port = self.rt.sim.port
        if prop_name == "Attack":
            return float(ent.atk)
        if prop_name == "BaseAttack":
            return float(ent.base_atk)
        if prop_name == "Defence":
            return float(ent.defense)
        if prop_name == "BaseDefence":
            return float(ent.base_def)
        if prop_name == "Speed":
            return float(ent.speed)
        if prop_name == "SpeedConvert":
            return sum(m.convert_properties.get("Speed", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "MaxHP":
            return float(ent.max_hp) if used_override else float(port.max_hp(entity_id))
        if prop_name == "BaseHP":
            return float(ent.base_max_hp)
        if prop_name == "DirtyHPRatio":
            return sum(
                float(m.properties.get("DirtyHPRatio", 0.0))
                for m in self.get_modifiers(entity_id)
                if not m._destroyed
            )
        if prop_name == "DirtyHPDelta":
            return sum(
                float(m.properties.get("DirtyHPDelta", 0.0))
                for m in self.get_modifiers(entity_id)
                if not m._destroyed
            )
        if prop_name == "HPDelta":
            return sum(m.properties.get("HPDelta", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "RallyHP":
            return sum(m.properties.get("RallyHP", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "HPConvert":
            return sum(m.convert_properties.get("MaxHP", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "CurrentHP":
            return float(ent.current_hp)
        if prop_name == "NegativeHP":
            return float(getattr(ent, "_negative_hp", 0.0) or 0.0)
        if prop_name == "HPRatio":
            m = float(ent.max_hp) if used_override else float(port.max_hp(entity_id))
            return float(ent.current_hp / m) if m > 0 else 1.0
        if prop_name in ("CriticalChanceBase", "CriticalChance"):
            return float(ent.crit_rate)
        if prop_name in ("CriticalDamageBase", "CriticalDamage"):
            return float(ent.crit_dmg)
        if prop_name == "CriticalDamageConvert":
            return sum(m.convert_properties.get("CriticalDamageBase", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "AttackConvert":
            return sum(m.convert_properties.get("Attack", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name in ("SpeedAddedRatio", "SpeedDelta"):
            return sum(float(m.properties.get(prop_name, 0.0)) for m in self.get_modifiers(entity_id))
        if prop_name == "ElationDamageAddedRatio":
            return float(port.stat(entity_id, StatType.ELATION))
        if prop_name == "ElationDamageAddedRatioBase":
            return float(
                port.stat(entity_id, StatType.ELATION, exclude_tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS,))
            )
        if prop_name == "ElationDamageAddedRatioConvert":
            return sum(
                m.convert_properties.get("ElationDamageAddedRatioBase", 0.0)
                for m in self.get_modifiers(entity_id)
            )
        if prop_name == "ElationDamageExtraAddedRatio":
            return float(port.stat(entity_id, StatType.ELATION_EXTRA))
        if prop_name == "ElationEchoPoint":
            return sum(float(m.properties.get("ElationEchoPoint", 0.0)) for m in self.get_modifiers(entity_id))
        if prop_name == "AdditionalBP":
            return float(self.rt.entity_boost_points.get(entity_id, 0.0))
        if prop_name in ("CurrentSpecialSP", "CurrentSP"):
            return float(getattr(ent, "energy", 0.0))
        if prop_name in ("MaxSpecialSP", "MaxSP"):
            return float(getattr(ent, "max_energy", 0.0))
        if prop_name == "CurExtraSpecialSP":
            return float(getattr(ent, "extra_special_sp", 0.0))
        if prop_name == "MaxExtraSpecialSP":
            return sum(float(m.properties.get("MaxExtraSpecialSP", 0.0)) for m in self.get_modifiers(entity_id))
        if prop_name == "Level":
            return float(getattr(ent, "level", 80) or 80)
        if prop_name == "HealRatioBase":
            return float(port.stat(entity_id, StatType.OUTGOING_HEALING))
        if prop_name == "HealRatioConvert":
            return sum(m.convert_properties.get("HealRatioBase", 0.0) for m in self.get_modifiers(entity_id))
        if prop_name == "BaseSpeed":
            return float(ent.base_speed)
        if prop_name == "Shield":
            return float(getattr(ent, "shield", 0.0))
        if prop_name == "CurrentStance":
            return float(getattr(ent, "current_toughness", 0.0))
        if prop_name == "MaxStance":
            return float(getattr(ent, "max_toughness", 0.0))
        if prop_name == "ActionDelay":
            return float(getattr(ent, "remaining_av", 0.0)) / 10.0
        if prop_name == "AllDamageTypeAddedRatio":
            return float(port.stat(entity_id, StatType.DMG_BOOST))
        if prop_name in ("BreakDamageAddedRatio", "BreakDamageAddedRatioBase"):
            be_val = float(port.stat(entity_id, StatType.BREAK_EFFECT))
            if getattr(ent, "is_memosprite", False) and getattr(ent, "master_name", None):
                be_val = max(be_val, float(port.stat(ent.master_name, StatType.BREAK_EFFECT)))
            return be_val
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
                mod_ctx = ExecutionContext(
                    runtime=self.rt,
                    caster_id=mod.caster_id,
                    ability_name=mod.ability_name,
                    modifier_owner_id=mod.owner_id,
                    modifier_instance=mod,
                    change_value=float(cur_val - prev_val) if prev_val is not None else 0.0,
                    custom_strings=dict(mod.custom_strings),
                )

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

    def check_dynamic_value_changes(
        self,
        owner_id: str,
        key_hash: int,
        old_val: float,
        new_val: float,
        *,
        modifier: Optional[VMModifierInstance] = None,
    ) -> None:
        """触发订阅了 OnDynamicValueChange 的监听（如晴歌 HyperValue 同步、Modifier 局部动态值监听）。"""
        mods_to_scan = [modifier] if modifier is not None else list(self.by_uid.values())
        for mod in mods_to_scan:
            if mod is None or mod._destroyed:
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
                change_value=float(new_val - old_val),
                custom_strings=dict(mod.custom_strings),
            )
            for idx_dvc, dvc in enumerate(dvcs):
                k = dvc.get("Key", {})
                target_h = int(k.get("Hash", 0)) if isinstance(k, dict) else 0
                if target_h != key_hash:
                    continue
                if modifier is None:
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

    def check_elation_point_changes(self, old_val: float, new_val: float, delta: float) -> None:
        """触发订阅了 OnElationPointChange 的 Modifier 监听（如 BattleEvent 20049 蓄能同步）。"""
        for mod in list(self.by_uid.values()):
            if mod._destroyed:
                continue
            epcs = mod.config.get("OnElationPointChange")
            if not isinstance(epcs, list):
                continue
            mod_ctx = ExecutionContext(
                runtime=self.rt,
                caster_id=mod.caster_id,
                ability_name=mod.ability_name,
                modifier_owner_id=mod.owner_id,
                modifier_instance=mod,
                change_value=delta,
                custom_strings=dict(mod.custom_strings),
            )
            for idx_rng, rng in enumerate(epcs):
                if not isinstance(rng, dict):
                    continue
                lo = eval_dynamic_float(rng.get("Min"), lambda h: self._resolve_mod_hash(mod, h), -1e18)
                hi = eval_dynamic_float(rng.get("Max"), lambda h: self._resolve_mod_hash(mod, h), 1e18)
                state_key = ("epc", 0, idx_rng)
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
            if mod._destroyed or mod.life_time is None or mod.life_time < 0.0:
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

    def dispatch_event_to_modifiers(
        self,
        modifiers: Sequence[VMModifierInstance],
        event_name: str,
        *,
        param_entity_id: Optional[str] = None,
        param_entity2_id: Optional[str] = None,
    ) -> None:
        """仅向指定 Modifier 列表派发事件（避免 OnListen* 广播误触已挂载角色监听）。"""
        entries: List[Tuple[int, int, VMModifierInstance, List[Dict[str, Any]]]] = []
        for mod in modifiers:
            if mod._destroyed:
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
                param_entity_id=param_entity_id,
                param_entity2_id=param_entity2_id,
                custom_strings=dict(mod.custom_strings),
            )
            self.rt.execute_tasks(tasks, ctx)

    def dispatch_event(
        self,
        event_name: str,
        *,
        owner_id: Optional[str] = None,
        owner_ids: Optional[Sequence[str]] = None,
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
        callback_status_type: str = "",
        callback_modifier_instance: Optional[VMModifierInstance] = None,
        exclude_modifier_uid: Optional[int] = None,
        change_value: float = 0.0,
        current_skill_type: str = "",
        current_attack_type: str = "",
        param_flags: Tuple[str, ...] = (),
        param_strings: Tuple[str, ...] = (),
    ) -> None:
        """收集所有订阅该事件的 Modifier 回调，严格按 Priority 升序 (-92 -> -80 -> 0 -> +N) 执行。"""
        entries: List[Tuple[int, int, VMModifierInstance, List[Dict[str, Any]]]] = []
        is_owner_scoped = owner_id is not None and not event_name.startswith("OnListen")
        owner_set = set(owner_ids) if (owner_ids is not None and not event_name.startswith("OnListen")) else None

        for mod in list(self.by_uid.values()):
            if mod._destroyed or mod.uid == exclude_modifier_uid:
                continue
            if is_owner_scoped and mod.owner_id != owner_id:
                continue
            if owner_set is not None and mod.owner_id not in owner_set:
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
                callback_status_type=callback_status_type,
                callback_modifier_instance=callback_modifier_instance,
                change_value=change_value,
                current_skill_type=current_skill_type,
                current_attack_type=current_attack_type,
                param_flags=param_flags,
                param_strings=param_strings,
                custom_strings=dict(mod.custom_strings),
            )
            self.rt.execute_tasks(tasks, ctx)

    def intercept_team_block_damage(self, target_id: str, raw_dmg: float) -> float:
        """拦截 TeamBlock 类型 Modifier 对我方受击伤害的抵消（消耗 MDF_TeamBlockValue 并触发回调）。"""
        if raw_dmg <= 0.0:
            return raw_dmg
        for m in list(self.by_uid.values()):
            if m._destroyed or "TeamBlock" not in m.behavior_flags:
                continue
            cur = float(getattr(m, "team_block_cur", 0.0))
            if cur <= 0.0:
                continue
            pred = getattr(m, "team_block_predicate", None)
            if pred is not None:
                p_ctx = ExecutionContext(
                    runtime=self.rt,
                    caster_id=m.caster_id,
                    ability_name=m.ability_name,
                    modifier_owner_id=m.owner_id,
                    modifier_instance=m,
                    param_entity_id=target_id,
                )
                if not self.rt.executor.eval_predicate(pred, p_ctx):
                    continue
            rate = max(0.0, min(1.0, float(getattr(m, "team_block_rate", 1.0))))
            absorbed = min(cur, raw_dmg * rate)
            if absorbed > 0.0:
                new_val = max(0.0, cur - absorbed)
                setattr(m, "team_block_cur", new_val)
                raw_dmg -= absorbed
                diag_cb = getattr(self.rt.sim, "timeline_diag_cb", None)
                if callable(diag_cb):
                    diag_cb(
                        "TBLK",
                        f"absorb target={target_id} abs={absorbed:.2f} {cur:.2f}->{new_val:.2f} mod={m.name}",
                    )
                self.rt.set_dynamic_value(m.owner_id, dotnet_hash("MDF_TeamBlockValue"), new_val, modifier=m)
                cb_ctx = ExecutionContext(
                    runtime=self.rt,
                    caster_id=m.caster_id,
                    ability_name=m.ability_name,
                    modifier_owner_id=m.owner_id,
                    modifier_instance=m,
                    param_entity_id=target_id,
                    change_value=-absorbed,
                )
                self.dispatch_modifier_callbacks(m, "OnModifierTeamBlockChange", cb_ctx)
                if raw_dmg <= 0.0:
                    break
        return max(0.0, raw_dmg)

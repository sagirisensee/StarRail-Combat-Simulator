"""Kit 与底层战斗引擎基础设施之间的窄接口契约及标准适配器实现 (Combat Port & Adapter).

设计原则：
- 所有业务插件（角色 Kit、光锥 LightCone、遗器 RelicSet）仅通过 CombatPort 与引擎交互；
- 严禁插件直接访问 `self.port.sim` 或 `self.port._get_entity` 内部私有结构；
- `SimulatorCombatPort` 将插件的窄接口请求桥接为 `EffectResolver` 队列事务、`StatusManager` 状态更新与 `EventBus` 事实事件。
"""
from dataclasses import dataclass
from typing import Protocol, Tuple, Optional, Any, TYPE_CHECKING
from .actions import ActionKind, TargetMode
from .effects import (
    AdvanceActionEffect, DelayActionEffect, ModifySPEffect, ApplyDamageEffect, DamageRequest
)
from .events import (
    ActionExecuteEvent, HealAppliedEvent, ShieldAppliedEvent, HPLostEvent,
    SpiritSummonedEvent, SpiritDespawnEvent
)
from .status import Modifier, ModifierOp, DurationTiming, StatType, StackPolicy, StatusInstance, StatusTag

if TYPE_CHECKING:
    from .core import TurnSimulator
    from .entity import Entity


@dataclass(frozen=True)
class BuffSpec:
    key: str
    name: str
    source_id: str
    target_id: str
    modifiers: Tuple[Modifier, ...]
    duration: Optional[int] = 1
    timing: DurationTiming = DurationTiming.TARGET_TURN_END
    stack_policy: StackPolicy = StackPolicy.REPLACE
    skip_current_clock: bool = False
    category: str = "buff"
    description: Optional[str] = None
    tags: Tuple[str, ...] = ()
    stacks: int = 1
    max_stacks: int = 1


class CombatPort(Protocol):
    """技能/光锥/遗器处理器调用的安全基础设施端口契约。"""
    # --- 1. 阵营与从属关系查询 ---
    def entity_exists(self, entity_id: str) -> bool: ...
    def is_ally(self, actor_id: str) -> bool: ...
    def is_memosprite(self, entity_id: str) -> bool: ...
    def get_master_name(self, entity_id: str) -> Optional[str]: ...
    def is_own_memosprite(self, master_id: str, entity_id: str) -> bool: ...
    def is_attack_action(self, actor_id: str, action_kind: Any = None, action_type: str = "") -> bool: ...
    def allies(self, actor_id: str) -> Tuple[str, ...]: ...
    def enemies(self, actor_id: str) -> Tuple[str, ...]: ...
    def count_allies_by_path(self, actor_id: str, path_name: str) -> int: ...

    # --- 2. 实时属性与白字基准查询 ---
    def stat(
        self,
        entity_id: str,
        stat: StatType,
        *,
        exclude_tags: Tuple[str, ...] = (),
        exclude_ids: Tuple[str, ...] = ()
    ) -> float: ...
    def white_stat(self, entity_id: str, stat: StatType) -> float: ...
    def max_energy(self, entity_id: str) -> float: ...
    def current_hp(self, entity_id: str) -> float: ...
    def max_hp(self, entity_id: str) -> float: ...
    def hp_ratio(self, entity_id: str) -> float: ...

    # --- 3. 状态管理与语义检索 ---
    def has_status(self, target_id: str, key: str) -> bool: ...
    def statuses(
        self,
        target_id: str,
        *,
        category: Optional[str] = None,
        include_tags: Tuple[str, ...] = (),
        exclude_tags: Tuple[str, ...] = ()
    ) -> Tuple[StatusInstance, ...]: ...
    def upsert_status(self, spec: BuffSpec) -> None: ...
    def remove_status(self, target_id: str, key: str) -> None: ...
    def dispel(self, target_id: str, is_debuff: bool = True) -> None: ...

    # --- 4. 战斗动作与资源指令 ---
    def advance(self, source_id: str, target_id: str, ratio: float) -> None: ...
    def delay(self, source_id: str, target_id: str, ratio: float) -> None: ...
    def set_distance(self, entity_id: str, distance: float) -> None: ...
    def set_base_speed(self, entity_id: str, speed: float) -> None: ...
    def change_sp(self, source_id: str, amount: int, reason: str) -> None: ...
    def set_sp_cap(self, new_cap: int) -> None: ...
    def gain_energy(self, entity_id: str, amount: float) -> None: ...
    def gain_hit_energy(self, entity_id: str, base_amount: float = 5.0) -> float: ...
    def heal(self, source_id: str, target_id: str, amount: float) -> None: ...
    def add_shield(self, source_id: str, target_id: str, amount: float, duration: int = 3) -> None: ...
    def attack(
        self,
        source_id: str,
        target_id: str,
        *,
        element: str,
        atk_multiplier: float,
        toughness_damage: float,
        damage_tag: str = "direct",
        ignore_weakness: bool = False,
        scaling_stat: str = "atk",
        force_crit: Optional[bool] = None,
        fixed_crit_dmg: Optional[float] = None
    ) -> None: ...
    def lose_hp(self, entity_id: str, amount: float, cause: str = "") -> None: ...
    def is_countdown(self, entity_id: str) -> bool: ...
    def summon_spirit(
        self,
        owner_id: str,
        name: str,
        base_speed: float,
        max_hp: float,
        kit_class: Any = None,
        kit_args: Optional[dict] = None,
        *,
        is_memosprite: bool = True,
        is_countdown: bool = False
    ) -> Any: ...
    def despawn_spirit(self, name: str, reason: str = "") -> None: ...


class SimulatorCombatPort:
    """TurnSimulator 与业务插件（KitHandler / LightConeHandler / RelicSetHandler）之间的标准窄接口实现。"""
    def __init__(self, simulator: "TurnSimulator"):
        self.sim = simulator

    def _get_entity(self, name_or_id: str) -> Optional["Entity"]:
        for e in self.sim.entities:
            if e.name == name_or_id or str(getattr(e, "avatar_id", "")) == str(name_or_id):
                return e
        return None

    def entity_exists(self, entity_id: str) -> bool:
        return self._get_entity(entity_id) is not None

    def is_memosprite(self, entity_id: str) -> bool:
        ent = self._get_entity(entity_id)
        return bool(ent and getattr(ent, "is_memosprite", False))

    def is_ally(self, actor_id: str) -> bool:
        ent = self._get_entity(actor_id)
        if ent:
            return not ent.is_enemy
        enemies = [e.name for e in self.sim.entities if e.is_enemy]
        return bool(actor_id) and actor_id not in enemies

    def get_master_name(self, entity_id: str) -> Optional[str]:
        ent = self._get_entity(entity_id)
        return getattr(ent, "master_name", None) if ent else None

    def is_own_memosprite(self, master_id: str, entity_id: str) -> bool:
        ent = self._get_entity(entity_id)
        return bool(ent and getattr(ent, "is_memosprite", False) and getattr(ent, "master_name", None) == master_id)

    def is_countdown(self, entity_id: str) -> bool:
        ent = self._get_entity(entity_id)
        return bool(ent and getattr(ent, "is_countdown", False))

    def is_attack_action(self, actor_id: str, action_kind: Any = None, action_type: str = "") -> bool:
        """判定指定实体的某次动作是否属于【攻击】行为（排除纯辅助技能与倒计时实体）。"""
        actor_ent = self._get_entity(actor_id)
        if actor_ent and getattr(actor_ent, "is_countdown", False):
            return False
        if "Countdown" in str(action_type):
            return False
        if action_kind in (ActionKind.BASIC, ActionKind.FOLLOW_UP) or action_type in ("BasicAttack", "FollowUpAttack"):
            return True
        ent = self._get_entity(actor_id)
        if ent and getattr(ent, "kit", None) is not None and action_kind is not None:
            try:
                defn = ent.kit.definition(action_kind)
                if defn and getattr(defn, "target_mode", None) is not None:
                    return defn.target_mode in (
                        TargetMode.SINGLE_ENEMY,
                        TargetMode.ALL_ENEMIES,
                        TargetMode.BLAST,
                        TargetMode.BOUNCE,
                    )
            except Exception:
                pass
        return True

    def allies(self, actor_id: str) -> Tuple[str, ...]:
        actor = self._get_entity(actor_id)
        if not actor:
            return ()
        return tuple(
            e.name for e in self.sim.entities
            if e.is_enemy == actor.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))
        )

    def enemies(self, actor_id: str) -> Tuple[str, ...]:
        actor = self._get_entity(actor_id)
        if not actor:
            return ()
        return tuple(
            e.name for e in self.sim.entities
            if e.is_enemy != actor.is_enemy and (e.current_hp > 0 or getattr(e, "is_infinite_hp", False))
        )

    def count_allies_by_path(self, actor_id: str, path_name: str) -> int:
        """统计我方阵营中指定命途（如 'Remembrance' / '记忆'）的角色数量（不含伴生忆灵）。"""
        target = path_name.strip().upper()
        path_aliases = {
            "REMEMBRANCE": {"REMEMBRANCE", "8", "记忆"},
            "记忆": {"REMEMBRANCE", "8", "记忆"},
            "HARMONY": {"HARMONY", "同谐"},
            "同谐": {"HARMONY", "同谐"},
            "NIHILITY": {"NIHILITY", "虚无"},
            "虚无": {"NIHILITY", "虚无"},
            "PRESERVATION": {"PRESERVATION", "存护"},
            "存护": {"PRESERVATION", "存护"},
            "ABUNDANCE": {"ABUNDANCE", "丰饶"},
            "丰饶": {"ABUNDANCE", "丰饶"},
            "DESTRUCTION": {"DESTRUCTION", "WARRIOR", "毁灭"},
            "毁灭": {"DESTRUCTION", "WARRIOR", "毁灭"},
            "THE HUNT": {"THE HUNT", "HUNT", "ROGUE", "巡猎"},
            "HUNT": {"THE HUNT", "HUNT", "ROGUE", "巡猎"},
            "巡猎": {"THE HUNT", "HUNT", "ROGUE", "巡猎"},
            "ERUDITION": {"ERUDITION", "MAGE", "智识"},
            "智识": {"ERUDITION", "MAGE", "智识"},
            "ELATION": {"ELATION", "欢愉"},
            "欢愉": {"ELATION", "欢愉"},
        }
        accepted = path_aliases.get(target, {target})
        count = 0
        for ally_name in self.allies(actor_id):
            ent = self._get_entity(ally_name)
            if not ent or getattr(ent, "is_memosprite", False):
                continue
            p = getattr(ent, "path", "")
            p_str = str(getattr(p, "value", p)).strip().upper()
            if p_str in accepted or any(a in p_str for a in accepted):
                count += 1
        return count

    def white_stat(self, entity_id: str, stat: StatType) -> float:
        """获取实体的基础白字属性（角色白字 + 光锥白字）。"""
        ent = self._get_entity(entity_id)
        if not ent:
            return 0.0
        if stat in (StatType.ATK_BASE, StatType.ATK_PERCENT, StatType.ATK):
            return getattr(ent, "base_white_atk", 0.0) or getattr(ent, "base_atk", 0.0)
        elif stat in (StatType.DEF, StatType.DEF_PERCENT, StatType.DEF_BASE):
            return getattr(ent, "base_white_def", 0.0) or getattr(ent, "base_def", 0.0)
        elif stat == StatType.MAX_HP_PERCENT:
            return getattr(ent, "base_white_hp", 0.0) or getattr(ent, "max_hp", 0.0)
        elif stat == StatType.SPEED:
            return getattr(ent, "base_white_speed", 0.0) or getattr(ent, "base_speed", 0.0)
        elif stat == StatType.DMG_BOOST:
            return getattr(ent, "base_dmg_boost", 0.0)
        return 0.0

    def stat(
        self,
        entity_id: str,
        stat: StatType,
        *,
        exclude_tags: Tuple[str, ...] = (),
        exclude_ids: Tuple[str, ...] = ()
    ) -> float:
        """动态查询实体当前实时属性，支持全量 StatType 与语义标签排除过滤。"""
        ent = self._get_entity(entity_id)
        if not ent:
            return 0.0
        base_val = 0.0
        if stat == StatType.CRIT_DMG:
            base_val = ent.base_crit_dmg
        elif stat == StatType.CRIT_RATE:
            base_val = ent.base_crit_rate
        elif stat == StatType.SPEED:
            base_val = ent.base_speed
        elif stat in (StatType.ATK_BASE, StatType.ATK_PERCENT, StatType.ATK):
            base_val = ent.base_atk
        elif stat in (StatType.DEF, StatType.DEF_PERCENT, StatType.DEF_BASE):
            base_val = getattr(ent, "base_def", 0.0)
        elif stat == StatType.MAX_HP_PERCENT:
            base_val = getattr(ent, "max_hp", 0.0)
        elif stat == StatType.ERR:
            base_val = getattr(ent, "base_err", 1.0)
        elif stat == StatType.BREAK_EFFECT:
            base_val = getattr(ent, "base_break_effect", 0.0)
        elif stat == StatType.EFFECT_RES:
            base_val = getattr(ent, "base_effect_res", 0.10)
        elif stat == StatType.EHR:
            base_val = getattr(ent, "base_effect_hit_rate", 0.0)
        elif stat == StatType.OUTGOING_HEALING:
            base_val = getattr(ent, "base_outgoing_healing", 0.0)
        elif stat == StatType.DMG_BOOST:
            base_val = getattr(ent, "base_dmg_boost", 0.0)
        return self.sim.status_mgr.calculate_stat(
            ent.name,
            base_val,
            stat,
            exclude_tags=exclude_tags,
            exclude_ids=exclude_ids
        )

    def has_status(self, target_id: str, key: str) -> bool:
        ent = self._get_entity(target_id)
        return self.sim.status_mgr.has_status(ent.name, key) if ent else False

    def statuses(
        self,
        target_id: str,
        *,
        category: Optional[str] = None,
        include_tags: Tuple[str, ...] = (),
        exclude_tags: Tuple[str, ...] = ()
    ) -> Tuple[StatusInstance, ...]:
        """获取指定实体身上满足条件的状态实例元组。"""
        ent = self._get_entity(target_id)
        if not ent:
            return ()
        return tuple(
            self.sim.status_mgr.get_statuses(
                ent.name,
                category=category,
                include_tags=include_tags,
                exclude_tags=exclude_tags
            )
        )

    def upsert_status(self, spec: BuffSpec) -> None:
        src = self._get_entity(spec.source_id)
        tgt = self._get_entity(spec.target_id)
        if not src or not tgt:
            return
        status = StatusInstance(
            id=spec.key,
            name=spec.name,
            source=src,
            target=tgt,
            duration=spec.duration,
            timing=spec.timing,
            modifiers=list(spec.modifiers),
            stack_policy=spec.stack_policy,
            skip_current_clock=spec.skip_current_clock,
            category=getattr(spec, "category", "buff"),
            description=getattr(spec, "description", None),
            tags=list(getattr(spec, "tags", ())),
            stacks=getattr(spec, "stacks", 1),
            max_stacks=getattr(spec, "max_stacks", 1)
        )
        self.sim.status_mgr.add_status(status)

    def remove_status(self, target_id: str, key: str) -> None:
        ent = self._get_entity(target_id)
        if ent:
            self.sim.status_mgr.remove_status(ent.name, key)

    def advance(self, source_id: str, target_id: str, ratio: float) -> None:
        tgt = self._get_entity(target_id)
        if tgt:
            if (
                source_id
                and source_id != target_id
                and not self.is_own_memosprite(source_id, target_id)
                and self.statuses(source_id, include_tags=(StatusTag.CANNOT_ADVANCE_OTHER_ALLIES,))
            ):
                return
            if ratio >= 1.0 and (self.sim.current_turn_entity == tgt or getattr(tgt, "extra_immediate_action", False)):
                tgt.extra_immediate_action = True
            self.sim.resolver.enqueue(AdvanceActionEffect(source_id, tgt, ratio))

    def delay(self, source_id: str, target_id: str, ratio: float) -> None:
        tgt = self._get_entity(target_id)
        if tgt:
            self.sim.resolver.enqueue(DelayActionEffect(source_id, tgt, ratio))

    def set_distance(self, entity_id: str, distance: float) -> None:
        ent = self._get_entity(entity_id)
        if ent:
            ent.distance_remaining = max(0.0, float(distance))

    def set_base_speed(self, entity_id: str, speed: float) -> None:
        ent = self._get_entity(entity_id)
        if ent:
            ent.base_speed = float(speed)

    def change_sp(self, source_id: str, amount: int, reason: str) -> None:
        self.sim.resolver.enqueue(ModifySPEffect(source_id, amount, reason))

    def set_sp_cap(self, new_cap: Optional[int]) -> None:
        if new_cap is not None and new_cap > 0:
            self.sim.sp.set_max_sp(new_cap)

    def gain_energy(self, entity_id: str, amount: float) -> None:
        ent = self._get_entity(entity_id)
        if ent:
            ent.energy = min(ent.max_energy, ent.energy + amount)

    def gain_hit_energy(self, entity_id: str, base_amount: float = 5.0) -> float:
        """受击回能标准接口：严格按角色【能量恢复效率 (ERR)】进行放大。"""
        ent = self._get_entity(entity_id)
        if not ent:
            return 0.0
        err = self.stat(entity_id, StatType.ERR) or getattr(ent, "base_err", 1.0) or 1.0
        actual = base_amount * err
        self.gain_energy(entity_id, actual)
        return actual

    def heal(self, source_id: str, target_id: str, amount: float) -> None:
        tgt = self._get_entity(target_id)
        if tgt and hasattr(tgt, "current_hp"):
            cur_max = self.max_hp(target_id) or tgt.max_hp
            tgt.current_hp = min(cur_max, tgt.current_hp + amount)
            self.sim.event_bus.publish(HealAppliedEvent(
                av=getattr(self.sim, "current_av", 0.0),
                cycle=getattr(self.sim, "current_cycle", 0),
                source_name=source_id,
                target_name=tgt.name,
                amount=amount
            ))

    def add_shield(self, source_id: str, target_id: str, amount: float, duration: int = 3) -> None:
        tgt = self._get_entity(target_id)
        if tgt and hasattr(tgt, "shield"):
            tgt.shield = max(tgt.shield, amount)
            self.sim.event_bus.publish(ShieldAppliedEvent(
                av=getattr(self.sim, "current_av", 0.0),
                cycle=getattr(self.sim, "current_cycle", 0),
                source_name=source_id,
                target_name=tgt.name,
                amount=amount
            ))

    def dispel(self, target_id: str, is_debuff: bool = True) -> None:
        ent = self._get_entity(target_id)
        if not ent:
            return
        cat = "debuff" if is_debuff else "buff"
        statuses = self.sim.status_mgr.get_statuses(ent.name, category=cat)
        if statuses:
            self.sim.status_mgr.remove_status(ent.name, statuses[0].id)

    def max_energy(self, entity_id: str) -> float:
        ent = self._get_entity(entity_id)
        return ent.max_energy if ent else 120.0

    def current_hp(self, entity_id: str) -> float:
        ent = self._get_entity(entity_id)
        return getattr(ent, "current_hp", 0.0) if ent else 0.0

    def hp_ratio(self, entity_id: str) -> float:
        ent = self._get_entity(entity_id)
        cur_max = self.max_hp(entity_id)
        if ent and cur_max > 0:
            return ent.current_hp / cur_max
        return 1.0

    def attack(
        self,
        source_id: str,
        target_id: str,
        *,
        element: str,
        atk_multiplier: float,
        toughness_damage: float,
        damage_tag: str = "direct",
        ignore_weakness: bool = False,
        scaling_stat: str = "atk",
        force_crit: Optional[bool] = None,
        fixed_crit_dmg: Optional[float] = None
    ) -> None:
        tgt = self._get_entity(target_id)
        src = self._get_entity(source_id)
        if not tgt or not src:
            return
        base_res = 0.20
        if hasattr(tgt, "damage_res") and isinstance(tgt.damage_res, dict) and element in tgt.damage_res:
            base_res = tgt.damage_res[element]
        elif hasattr(tgt, "weaknesses") and element in tgt.weaknesses:
            base_res = 0.0
        req = DamageRequest(
            attacker=src,
            target=tgt,
            skill_multiplier=atk_multiplier,
            target_base_res=base_res,
            target_is_broken=tgt.is_broken,
            force_crit=force_crit,
            fixed_crit_dmg=fixed_crit_dmg,
            scaling_stat=scaling_stat
        )
        if damage_tag == "FollowUpAttack":
            self.sim.event_bus.publish(ActionExecuteEvent(
                av=round(self.sim.current_av, 2),
                cycle=self.sim.current_cycle,
                actor_id=source_id,
                actor_name=source_id,
                action_type="FollowUpAttack",
                description=f"【{source_id}】触发追加攻击",
                action_kind=ActionKind.FOLLOW_UP
            ))
        self.sim.resolver.enqueue(ApplyDamageEffect(
            request=req,
            toughness_reduction=toughness_damage,
            element=element,
            ignore_weakness=ignore_weakness,
            damage_tag=damage_tag
        ))

    def max_hp(self, entity_id: str) -> float:
        ent = self._get_entity(entity_id)
        if ent:
            base_max_hp = getattr(ent, "max_hp", 0.0)
            if hasattr(self.sim, "status_mgr") and base_max_hp > 0 and base_max_hp != float("inf"):
                white_hp = getattr(ent, "base_white_hp", 0.0) or base_max_hp
                return self.sim.status_mgr.calculate_stat(ent.name, base_max_hp, StatType.MAX_HP_PERCENT, white_base=white_hp)
            return base_max_hp
        return 0.0

    def lose_hp(self, entity_id: str, amount: float, cause: str = "") -> None:
        ent = self._get_entity(entity_id)
        if ent:
            if cause == "fuxuan_matrix_share" and getattr(ent, "shield", 0.0) > 0:
                absorbed = min(ent.shield, amount)
                ent.shield -= absorbed
                amount -= absorbed
            actual = min(ent.current_hp, amount)
            ent.current_hp = max(1.0, ent.current_hp - actual)
            if actual > 0:
                self.sim.event_bus.publish(HPLostEvent(
                    av=round(getattr(self.sim, "current_av", 0.0), 2),
                    cycle=getattr(self.sim, "current_cycle", 0),
                    entity_name=ent.name,
                    amount=actual,
                    hp_left=ent.current_hp,
                    cause=cause
                ))
            for e in list(self.sim.entities):
                if getattr(e, "kit", None) and hasattr(e.kit, "on_hp_lost"):
                    e.kit.on_hp_lost(entity_id, actual, cause)

    def summon_spirit(
        self,
        owner_id: str,
        name: str,
        base_speed: float,
        max_hp: float,
        kit_class: Any = None,
        kit_args: Optional[dict] = None,
        *,
        is_memosprite: bool = True,
        is_countdown: bool = False
    ) -> Any:
        from .entity import Entity
        existing = self.sim.get_entity(name)
        if existing:
            return existing
        owner = self._get_entity(owner_id)
        spirit = Entity(
            name=name,
            base_speed=base_speed,
            base_atk=0.0,
            max_hp=max_hp,
            current_hp=max_hp,
            base_crit_rate=owner.base_crit_rate if owner else 0.05,
            base_crit_dmg=owner.base_crit_dmg if owner else 0.50,
            is_enemy=False,
            is_memosprite=is_memosprite,
            is_countdown=is_countdown,
            master_name=owner_id,
            policy="A"
        )
        if kit_class:
            spirit.kit = kit_class(name, self, **(kit_args or {}))
        self.sim.add_entity(spirit, trigger_battle_start=False)
        self.sim.event_bus.publish(SpiritSummonedEvent(
            av=round(getattr(self.sim, "current_av", 0.0), 2),
            cycle=getattr(self.sim, "current_cycle", 0),
            owner_name=owner_id,
            spirit_name=name
        ))
        for plugin in getattr(self.sim, "stage_plugins", []):
            plugin.on_entity_summoned(spirit, self.sim)
        return spirit

    def despawn_spirit(self, name: str, reason: str = "") -> None:
        ent = self.sim.get_entity(name)
        if ent and ent in self.sim.entities:
            owner_name = getattr(ent, "master_name", "") or ""
            self.sim.entities.remove(ent)
            if self.sim._current_turn_entity == ent:
                self.sim._current_turn_entity = None
            self.sim.event_bus.publish(SpiritDespawnEvent(
                av=round(getattr(self.sim, "current_av", 0.0), 2),
                cycle=getattr(self.sim, "current_cycle", 0),
                owner_name=owner_name,
                spirit_name=name,
                reason=reason
            ))

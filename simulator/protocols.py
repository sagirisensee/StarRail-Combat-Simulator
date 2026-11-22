# coding: utf-8
"""战斗实体行为处理器抽象协议（Kit / LightCone / RelicSet 统一接口层）。

由 ConfigAbility VM 适配器（``simulator/vm/runtime.py``）实现，并由微内核
（``simulator/core.py``）通过多态协议调度。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import math
from typing import Any, Optional, Sequence, TypeVar

from .actions import AbilityDefinition, ActionContext, ActionKind, FollowUpPhase
from .combat_port import CombatPort

T = TypeVar("T")


class KitHandler(ABC):
    """所有角色/忆灵技能行为处理器的抽象基类。"""

    follow_up_phase: Optional[FollowUpPhase] = None

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None,
    ):
        if not 0 <= eidolon <= 6:
            raise ValueError(f"星魂等阶必须在 0 到 6 之间，当前为: {eidolon}")
        self.owner_id = owner_id
        self.port = port
        self.eidolon = eidolon
        self.skill_levels = skill_levels or {}

    @abstractmethod
    def definition(self, kind: ActionKind) -> AbilityDefinition:
        """声明指定动作类型的目标模式与资源消耗。"""

    @abstractmethod
    def execute(self, ctx: ActionContext) -> None:
        """执行指定动作的具体战斗逻辑。"""

    def apply_trace_passives(self, entity: Any) -> None:
        pass

    def get_initial_sp_cap(self) -> Optional[int]:
        return None

    def use_technique(self) -> None:
        try:
            defn = self.definition(ActionKind.TECHNIQUE)
            if not defn:
                return
            ctx = ActionContext(
                action_id=f"{self.owner_id}_technique",
                actor_id=self.owner_id,
                kind=ActionKind.TECHNIQUE,
                target_ids=(),
            )
            self.execute(ctx)
        except (ValueError, KeyError, NotImplementedError):
            pass

    def on_battle_start(self) -> None:
        pass

    def on_battle_end(self) -> None:
        pass

    def on_event(self, event: Any) -> None:
        pass

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
        return raw_damage

    def can_cast_ultimate(self, entity: Any) -> bool:
        max_energy = getattr(entity, "max_energy", 120.0)
        energy = getattr(entity, "energy", 0.0)
        return max_energy > 0 and energy >= (max_energy - 1e-4)

    def consume_ultimate_cost(self, entity: Any) -> bool:
        if not self.can_cast_ultimate(entity):
            return False
        entity.energy = 0.0
        return True

    def get_energy_display(self, entity: Any) -> str:
        energy = getattr(entity, "energy", 0.0)
        max_energy = getattr(entity, "max_energy", 120.0)
        return f"能量: {math.floor(energy)}/{math.floor(max_energy)}"

    def get_memosprite_snapshot(self) -> Optional[dict]:
        return None

    def trace_variables(self) -> list:
        return []

    def get_trace_panel_section(self) -> Optional[tuple]:
        return None

    def get_kit_state(self) -> dict:
        excluded = {"owner_id", "port", "skill_levels", "scaling"}
        state = {}
        for k, v in self.__dict__.items():
            if k not in excluded and not k.startswith("_"):
                if isinstance(v, (int, float, bool, str, list, dict)):
                    state[k] = v
        return state


class GenericKit(KitHandler):
    """通用保底 Kit（仅用于脱离 VM 单独构造 Entity 时的单测占位）。"""

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        from .actions import ResourceCost, TargetMode

        if kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1), name="战技")
        if kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(energy=120.0), name="终结技")
        return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="普攻")

    def execute(self, ctx: ActionContext) -> None:
        from .actions import DamageType

        target = ctx.target_ids[0] if ctx.target_ids else (
            self.port.enemies(self.owner_id)[0] if self.port.enemies(self.owner_id) else self.owner_id
        )
        if ctx.kind == ActionKind.SKILL:
            self.port.attack(self.owner_id, target, element="Physical", atk_multiplier=2.0, toughness_damage=20.0, damage_type=DamageType.SKILL)
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            self.port.attack(self.owner_id, target, element="Physical", atk_multiplier=3.0, toughness_damage=30.0, damage_type=DamageType.ULTIMATE)
            self.port.gain_energy(self.owner_id, 5.0)
        else:
            self.port.attack(self.owner_id, target, element="Physical", atk_multiplier=1.0, toughness_damage=10.0, damage_type=DamageType.BASIC)
            self.port.gain_energy(self.owner_id, 20.0)


class LightConeHandler(ABC):
    """光锥运行时处理器抽象基类。"""

    def __init__(
        self,
        owner_id: str,
        port: Optional[CombatPort] = None,
        *,
        superimposition: int = 1,
        spec: Optional[Any] = None,
    ) -> None:
        if not isinstance(superimposition, int) or not 1 <= superimposition <= 5:
            raise ValueError(f"光锥叠影阶数必须是 1~5 之间的整数，当前为: {superimposition}")
        self.owner_id = owner_id
        self.port = port
        self.superimposition = superimposition
        self.spec = spec

    def scale(self, values: Sequence[T]) -> T:
        if len(values) != 5:
            raise ValueError(f"叠影数值序列必须包含 5 个元素 (S1~S5)，当前长度: {len(values)}")
        return values[self.superimposition - 1]

    def on_attach(self) -> None:
        pass

    def on_battle_start(self) -> None:
        pass

    def on_action_before(self, ctx: ActionContext) -> None:
        pass

    def on_action_after(self, ctx: ActionContext) -> None:
        pass

    def on_turn_start(self) -> None:
        pass

    def on_turn_end(self) -> None:
        pass

    def on_event(self, event: Any) -> None:
        pass


class RelicSetHandler(ABC):
    """遗器套装运行时处理器抽象基类。"""

    def __init__(
        self,
        owner_id: str,
        port: Optional[CombatPort] = None,
        *,
        pieces: int = 4,
        spec: Optional[Any] = None,
    ) -> None:
        if pieces not in (2, 4):
            raise ValueError(f"遗器套装件数必须为 2 或 4，当前为: {pieces}")
        self.owner_id = owner_id
        self.port = port
        self.pieces = pieces
        self.spec = spec

    def apply_panel_passives(self, entity: Any) -> None:
        pass

    def on_attach(self) -> None:
        pass

    def on_battle_start(self) -> None:
        pass

    def on_action_before(self, ctx: ActionContext) -> None:
        pass

    def on_action_after(self, ctx: ActionContext) -> None:
        pass

    def on_turn_start(self) -> None:
        pass

    def on_turn_end(self) -> None:
        pass

    def on_event(self, event: Any) -> None:
        pass


def apply_equipped_relics_affixes(relics: Any, entity: Any) -> None:
    """从装备的具体遗器部件中解析主词条属性并注入实体基础属性 (如治疗衣)。"""
    if not relics:
        return
    for r in relics:
        main_affix = getattr(r, "main_affix_name", "")
        if "治疗量" in main_affix:
            # 5 星治疗衣 +15 主词条精确值 (RelicMainAffixConfig GroupID=53 AffixID=6: 0.345606)
            entity.base_outgoing_healing += 0.345606

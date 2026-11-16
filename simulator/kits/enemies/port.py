from typing import Optional, Protocol, Tuple


class EnemyCombatPort(Protocol):
    def is_alive(self, entity_id: str) -> bool:
        """实体是否存在且存活。"""
        ...

    def summon_lighthouse_guards(
        self,
        *,
        owner_id: str,
        generation: int,
        count: int,
    ) -> Tuple[str, ...]:
        """创建完整一组千星戍卫，返回唯一实体 ID。"""
        ...

    def execute_lighthouse_regular_action(
        self,
        *,
        owner_id: str,
        action_id: str,
    ) -> None:
        """执行灯塔常规行动效果。"""
        ...


class BaseEnemyCombatPort(Protocol):
    """通用敌方 Kit 战斗端口协议。"""

    def is_alive(self, entity_id: str) -> bool:
        """实体是否存在且存活。"""
        ...

    def get_living_allies(self) -> Tuple[str, ...]:
        """获取当前存活的我方目标实体 ID 列表。"""
        ...

    def apply_enemy_attack(
        self,
        *,
        owner_id: str,
        target_ids: Tuple[str, ...],
        multiplier: float,
        element: str = "Physical",
        hit_energy: float = 5.0,
        hits: int = 1,
        blast: bool = False,
    ) -> Tuple[str, ...]:
        """对指定目标执行敌方攻击伤害结算。"""
        ...

    def apply_mark_status(
        self,
        *,
        owner_id: str,
        target_id: str,
        mark_key: str,
        mark_name: str,
        description: str = "",
    ) -> None:
        """为我方目标附加敌方机制印记。"""
        ...

    def remove_mark_status(
        self,
        *,
        target_id: str,
        mark_key: str,
    ) -> bool:
        """移除我方目标身上的指定印记，返回是否实际存在并被移除。"""
        ...

    def has_mark_status(
        self,
        *,
        target_id: str,
        mark_key: str,
    ) -> bool:
        """检查目标是否持有指定印记。"""
        ...

    def apply_hp_lock(
        self,
        *,
        target_id: str,
        delta_ratio: float = 0.10,
        max_ratio: float = 0.50,
    ) -> None:
        """对目标叠加【噬命】生命上限锁定比例（仅限制 current_hp 上限）。"""
        ...


class PegasusCombatPort(BaseEnemyCombatPort, Protocol):
    """月夜天马专用端口协议。"""

    def trigger_oronyx_detonation(
        self,
        *,
        owner_id: str,
        target_id: str,
        multiplier: float,
        element: str = "Quantum",
    ) -> None:
        """引爆【欧洛尼斯印记】造成额外结算伤害。"""
        ...


class GriffinCombatPort(BaseEnemyCombatPort, Protocol):
    """正阳狮鹫专用端口协议。"""

    def summon_meteor_eagles(
        self,
        *,
        owner_id: str,
        generation: int,
        count: int = 3,
        initial_distances: Optional[Tuple[float, ...]] = None,
    ) -> Tuple[str, ...]:
        """召唤一组流星铁鹰，返回唯一实体 ID 元组。"""
        ...


class EagleCombatPort(BaseEnemyCombatPort, Protocol):
    """流星铁鹰专用端口协议。"""
    pass


class ApoliCombatPort(BaseEnemyCombatPort, Protocol):
    """堕神之血•亚婆离专用端口协议。"""

    def get_current_av(self) -> float:
        """获取当前全局行动值 AV。"""
        ...

    def get_entity_hp_and_max(self, entity_id: str) -> Tuple[float, float]:
        """获取实体 (current_hp, max_hp)。"""
        ...

    def set_entity_phase_stats(
        self,
        entity_id: str,
        *,
        max_hp: float,
        current_hp: float,
        speed: float,
        toughness: float,
        reset_distance: Optional[float] = None,
        toughness_dmg_reduction: Optional[float] = None,
    ) -> None:
        """更新 Boss 阶段属性（MaxHP / HP / Speed / Toughness / 可选跑道与韧性减伤）。"""
        ...

    def set_entity_speed(self, entity_id: str, speed: float) -> None:
        """更新实体速度并同步重算行动条。"""
        ...

    def set_barrier_state(
        self,
        entity_id: str,
        *,
        active: bool,
        damage_reduction: float = 0.75,
        toughness_dmg_reduction: Optional[float] = None,
    ) -> None:
        """同步【血脑屏障】的受击护盾锁韧、减伤与韧性减伤状态。"""
        ...

    def break_entity_toughness_and_deduct_hp(
        self,
        entity_id: str,
        *,
        hp_deduct: float,
    ) -> None:
        """击破韧性至 0 并扣除指定生命值。"""
        ...

    def set_continuous_action_hold(self, hold: bool) -> None:
        """控制多段子动间的回合挂起（开放终结技插队窗口）。"""
        ...

    def summon_transition_sprouts(self, *, owner_id: str) -> Tuple[str, ...]:
        """转阶段时召唤狂兽的胚芽并重锚增援节拍。"""
        ...

    def absorb_sprout_and_heal(self, *, owner_id: str, heal_ratio: float = 0.04) -> bool:
        """吸收场上 1 个存活的胚芽（不触发亡语反伤）并为 Boss 回复指定比例 MaxHP。"""
        ...

    def execute_channel_pulse(
        self,
        *,
        owner_id: str,
        allies: Tuple[str, ...],
    ) -> None:
        """执行 8 段小 AoE 脉冲 + 1 段终结 AoE 结算。"""
        ...


class SproutCombatPort(BaseEnemyCombatPort, Protocol):
    """狂兽的胚芽专用端口协议。"""

    def heal_boss_by_ratio(self, *, boss_id: str, ratio: float) -> float:
        """按 Boss 当前阶段 MaxHP 比例治疗 Boss，返回实际治疗量。"""
        ...

    def is_boss_barrier_active(self, boss_id: str) -> bool:
        """查询 Boss【血脑屏障】当前是否开启。"""
        ...

    def apply_boss_backlash(self, *, boss_id: str, damage: float) -> None:
        """胚芽阵亡时对 Boss 造成固定反噬扣血。"""
        ...

    def apply_speed_debuff(
        self,
        *,
        owner_id: str,
        target_id: str,
        key: str,
        name: str,
        pct_per_stack: float = -0.10,
        max_stacks: int = 5,
        duration: int = 3,
        base_chance: float = 1.0,
    ) -> bool:
        """对目标施加可叠加的速度降低负面状态。"""
        ...

from __future__ import annotations

from .base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from .port import SproutCombatPort


class BeastSproutKit(EnemyKit):
    """狂兽的胚芽 (5032010) 专属机制 Kit。

    核心机制:
    - 奇偶交替行动:
      - 奇数号（首动攻击）: 攻击 -> 治疗 Boss 2% 当前阶段 MaxHP -> 攻击 ...
      - 偶数号（首动治疗）: 治疗 Boss 2% 当前阶段 MaxHP -> 攻击 -> 治疗 ...
    - 死亡反噬:
      - 当 Boss【血脑屏障】未开启时，胚芽阵亡会反噬 Boss 扣除固定生命值
        (102,128.65688 = Phase 1 MaxHP 的 2% / Phase 2 MaxHP 的 1%)。
    """

    ENEMY_ID = 5032010
    BACKLASH_DAMAGE = 102128.65688196554

    def __init__(
        self,
        owner_id: str,
        port: SproutCombatPort,
        *,
        boss_id: str = "堕神之血•亚婆离",
        initial_action: str = "attack",
        backlash_damage: float = BACKLASH_DAMAGE,
    ) -> None:
        super().__init__(owner_id, port)
        self._boss_id = boss_id
        self._next_action = initial_action if initial_action in ("attack", "heal") else "attack"
        self._backlash_damage = backlash_damage
        self._death_handled = False

    @property
    def next_action(self) -> str:
        return self._next_action

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        action = self._next_action
        self._next_action = "heal" if action == "attack" else "attack"

        if action == "heal":
            if self.port.is_alive(self._boss_id):
                self.port.heal_boss_by_ratio(boss_id=self._boss_id, ratio=0.02)
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

        allies = self.port.get_living_allies()
        if allies:
            hit_targets = self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=(allies[0],),
                multiplier=1.2,
                element="Physical",
                hit_energy=10.0,
                hits=1,
                blast=False,
            )
            for tgt in hit_targets:
                self.port.apply_speed_debuff(
                    owner_id=self.owner_id,
                    target_id=tgt,
                    key="BeastSprout_Slow",
                    name="狂兽减速",
                    pct_per_stack=-0.10,
                    max_stacks=5,
                    duration=3,
                    base_chance=1.0,
                )
                self.port.apply_hp_lock(target_id=tgt, delta_ratio=0.10, max_ratio=0.50)
        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

    def notify_death(self) -> None:
        if self._death_handled:
            return
        self._death_handled = True
        if not self.port.is_alive(self._boss_id):
            return
        self.port.apply_boss_backlash(
            boss_id=self._boss_id,
            damage=self._backlash_damage,
        )

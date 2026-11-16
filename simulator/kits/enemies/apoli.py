from __future__ import annotations

from typing import Tuple

from .base import (
    EnemyActionContext,
    EnemyActionResult,
    EnemyKit,
    STANDARD_ACTION_DISTANCE,
)
from .port import ApoliCombatPort


PHASE2_SUBACTION_PLAN = {
    1: ("HEAVY_ST", "PARTY_AOE", "SUMMON_SPROUTS"),
}


def _phase2_plan_for_turn(combat_turn: int) -> Tuple[str, ...]:
    """返回 Phase 2 第 combat_turn 动（1-based）的子动序列。"""
    if combat_turn in PHASE2_SUBACTION_PLAN:
        return PHASE2_SUBACTION_PLAN[combat_turn]
    phase_idx = (combat_turn - 2) % 3
    if phase_idx == 0:
        return ("ABSORB_AND_HEAVY_ST", "PARTY_AOE")
    if phase_idx == 1:
        return ("PARTY_AOE", "ABSORB_AND_CHANNEL_PULSE")
    return ("HEAVY_ST", "PARTY_AOE")


class ApoliBossKit(EnemyKit):
    """堕神之血•亚婆离 (5034010) 专属机制 Kit。

    核心机制 (参数化支持 Lv.95 关卡 30126122 与 Lv.100 关卡 30510021):
    - Phase 1: 进场速度置 0（不执行常规行动）。当生命首次跌破 trigger_ratio (默认 70%) Phase 1 MaxHP，
      或单次伤害直接打穿 30% 血线时开启【血脑屏障】，期间护盾吸收伤害、本体锁血锁韧；
      护盾击破时直接击破韧性并扣除 35% Phase 1 MaxHP。Phase 1 生命归零时立即转入 Phase 2。
    - Phase 2: MaxHP 翻倍，韧性重置为 1080.0，速度恢复为 237.60 并立即行动。
      按多子动模组循环（HEAVY_ST / PARTY_AOE / SUMMON_SPROUTS / CHANNEL_PULSE），子动间开放插队窗口。
      当 Phase 2 生命首次跌破 trigger_ratio (默认 70%) MaxHP，或单次伤害直接打穿 30% 血线时进入狂暴加速
      （Speed 237.60 -> 356.40）并开启二阶段屏障，持续 250.00 AV 后解除加速、击破韧性并扣除相应百分比 MaxHP。
    """

    ENEMY_ID = 5034010
    PHASE1_MAX_HP = 5106432.844098277
    PHASE2_MAX_HP = 10212865.688196555
    PHASE1_BARRIER_SHIELD = PHASE1_MAX_HP * 0.65
    PHASE2_BARRIER_SHIELD = PHASE2_MAX_HP * 0.65
    PHASE1_SPHERE_INTERVAL_AV = 10000.0 / 66.0
    PHASE2_SPHERE_INTERVAL_AV = 10000.0 / 40.0
    PHASE2_BASE_SPEED = 237.60000005364418
    PHASE2_BERSERK_SPEED = 356.4000001910608
    PHASE2_TOUGHNESS = 1080.0

    def __init__(
        self,
        owner_id: str,
        port: ApoliCombatPort,
        *,
        phase1_max_hp: float = PHASE1_MAX_HP,
        phase2_max_hp: float = PHASE2_MAX_HP,
        phase1_barrier_shield: float | None = None,
        phase2_barrier_shield: float | None = None,
        phase1_barrier_shield_ratio: float = 0.65,
        phase2_barrier_shield_ratio: float = 0.65,
        phase1_barrier_trigger_ratio: float = 0.70,
        phase2_barrier_trigger_ratio: float = 0.70,
        phase2_toughness_dmg_reduction: float = 0.10,
        apply_hp_lock_on_st: bool = False,
        apply_hp_lock_on_aoe: bool = False,
        apply_hp_lock_on_pulse: bool = True,
        transition_pulse_multipliers: Tuple[float, ...] | None = None,
        transition_pulse_hit_energy: Tuple[float, float] = (12.0, 12.0),
        aoe_include_memosprites: bool = False,
        party_aoe_multiplier: float = 1.2,
        heavy_st_multiplier: float = 2.4,
        phase2_berserk_duration_av: float = 250.0,
        phase2_plan: dict[int, Tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__(owner_id, port)
        self._phase = 1
        self._barrier_active = False
        self._phase1_barrier_triggered = False
        self._phase1_max_hp = float(phase1_max_hp)
        self._phase2_max_hp = float(phase2_max_hp)
        self._phase1_barrier_shield_ratio = float(phase1_barrier_shield_ratio)
        self._phase2_barrier_shield_ratio = float(phase2_barrier_shield_ratio)
        self._phase1_barrier_shield = (
            float(phase1_barrier_shield)
            if phase1_barrier_shield is not None
            else self._phase1_max_hp * self._phase1_barrier_shield_ratio
        )
        self._phase2_barrier_shield = (
            float(phase2_barrier_shield)
            if phase2_barrier_shield is not None
            else self._phase2_max_hp * self._phase2_barrier_shield_ratio
        )
        self._phase1_barrier_trigger_ratio = float(phase1_barrier_trigger_ratio)
        self._phase2_barrier_trigger_ratio = float(phase2_barrier_trigger_ratio)
        self._phase2_toughness_dmg_reduction = float(phase2_toughness_dmg_reduction)
        self._apply_hp_lock_on_st = bool(apply_hp_lock_on_st)
        self._apply_hp_lock_on_aoe = bool(apply_hp_lock_on_aoe)
        self._apply_hp_lock_on_pulse = bool(apply_hp_lock_on_pulse)
        self._transition_pulse_multipliers = transition_pulse_multipliers
        self._transition_pulse_hit_energy = transition_pulse_hit_energy
        self._aoe_include_memosprites = bool(aoe_include_memosprites)
        self._party_aoe_multiplier = float(party_aoe_multiplier)
        self._heavy_st_multiplier = float(heavy_st_multiplier)
        self._barrier_initial_shield = 0.0
        self._barrier_hp = 0.0
        self._barrier_sprout_stacks = 0
        self._barrier_sphere_removed = 0.0
        self._barrier_sphere_next_av: float | None = None

        self._phase2_berserk_triggered = False
        self._phase2_berserk_end_av: float | None = None
        self._phase2_berserk_duration_av = phase2_berserk_duration_av
        self._phase2_plan = phase2_plan

        self._combat_turns = 0
        self._subaction_idx = 0

    @property
    def phase(self) -> int:
        return self._phase

    @property
    def barrier_active(self) -> bool:
        return self._barrier_active

    @property
    def phase2_berserk_end_av(self) -> float | None:
        return self._phase2_berserk_end_av

    def on_battle_start(self) -> EnemyActionResult:
        # Phase 1 休眠，不参与常规跑条行动
        return EnemyActionResult(reset_distance=1e12)

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
        if target_id != self.owner_id or raw_damage <= 0.0:
            return raw_damage
        if self._barrier_active:
            absorbed = min(self._barrier_hp, raw_damage)
            self._barrier_hp = max(0.0, self._barrier_hp - raw_damage)
            overflow = raw_damage - absorbed
            if self._barrier_hp <= 0.0:
                self._break_barrier()
            return overflow

        # 单次伤害直接打穿 30% 血线时，锁血在 30% 并强制开启当前阶段屏障吸收溢出伤害
        cur_hp, _ = self.port.get_entity_hp_and_max(self.owner_id)
        av = self.port.get_current_av()
        if self._phase == 1 and not self._phase1_barrier_triggered:
            floor_hp = self._phase1_max_hp * 0.30
            if cur_hp > 0.0 and cur_hp - raw_damage <= floor_hp:
                self._phase1_barrier_triggered = True
                effective = max(0.0, cur_hp - floor_hp)
                overflow = raw_damage - effective
                self._activate_barrier(
                    av,
                    shield=self._phase1_barrier_shield,
                    sphere_interval_av=self.PHASE1_SPHERE_INTERVAL_AV,
                )
                if overflow > 0.0 and self._barrier_active:
                    absorbed = min(self._barrier_hp, overflow)
                    self._barrier_hp = max(0.0, self._barrier_hp - overflow)
                    extra_overflow = overflow - absorbed
                    if self._barrier_hp <= 0.0:
                        self._break_barrier()
                    return effective + extra_overflow
                return effective
        elif self._phase == 2 and not self._phase2_berserk_triggered:
            floor_hp = self._phase2_max_hp * 0.30
            if cur_hp > 0.0 and cur_hp - raw_damage <= floor_hp:
                self._phase2_berserk_triggered = True
                effective = max(0.0, cur_hp - floor_hp)
                overflow = raw_damage - effective
                self._activate_barrier(
                    av,
                    shield=self._phase2_barrier_shield,
                    sphere_interval_av=self.PHASE2_SPHERE_INTERVAL_AV,
                )
                self._phase2_berserk_end_av = av + self._phase2_berserk_duration_av
                self.port.set_entity_speed(self.owner_id, self.PHASE2_BERSERK_SPEED)
                if overflow > 0.0 and self._barrier_active:
                    absorbed = min(self._barrier_hp, overflow)
                    self._barrier_hp = max(0.0, self._barrier_hp - overflow)
                    extra_overflow = overflow - absorbed
                    if self._barrier_hp <= 0.0:
                        self._break_barrier()
                    return effective + extra_overflow
                return effective
        return raw_damage

    def notify_sprout_killed_on_barrier(self, damage: float) -> None:
        """屏障激活期间，我方击杀胚芽时同步削减屏障盾量并叠加紫色球体层数。"""
        if not self._barrier_active:
            return
        self._barrier_hp = max(0.0, self._barrier_hp - max(0.0, damage))
        self._barrier_sprout_stacks += 1

    def _activate_barrier(self, av: float, *, shield: float, sphere_interval_av: float) -> None:
        self._barrier_active = True
        self._barrier_initial_shield = shield
        self._barrier_hp = shield
        self._barrier_sprout_stacks = 0
        self._barrier_sphere_removed = 0.0
        self._barrier_sphere_next_av = av + sphere_interval_av
        if hasattr(self.port, "set_barrier_state"):
            self.port.set_barrier_state(
                self.owner_id,
                active=True,
                damage_reduction=0.75,
                toughness_dmg_reduction=(0.0 if self._phase == 2 else None),
            )

    def _break_barrier(self) -> None:
        self._barrier_active = False
        self._barrier_sphere_next_av = None
        self._phase2_berserk_end_av = None
        if hasattr(self.port, "set_barrier_state"):
            self.port.set_barrier_state(
                self.owner_id,
                active=False,
                damage_reduction=0.0,
                toughness_dmg_reduction=(self._phase2_toughness_dmg_reduction if self._phase == 2 else None),
            )
        if self._barrier_initial_shield > 0.0:
            ratio = max(0.0, 1.0 - self._barrier_sphere_removed / self._barrier_initial_shield)
        else:
            ratio = 1.0
        phase_max_hp = self._phase1_max_hp if self._phase == 1 else self._phase2_max_hp
        if self._phase == 2:
            self.port.set_entity_speed(self.owner_id, self.PHASE2_BASE_SPEED)
        self.port.break_entity_toughness_and_deduct_hp(
            self.owner_id,
            hp_deduct=phase_max_hp * 0.35 * ratio,
        )

    def _tick_purple_sphere(self, av: float) -> None:
        if not self._barrier_active or self._barrier_sphere_next_av is None:
            return
        interval = (
            self.PHASE1_SPHERE_INTERVAL_AV if self._phase == 1 else self.PHASE2_SPHERE_INTERVAL_AV
        )
        while self._barrier_active and self._barrier_sphere_next_av is not None and av >= self._barrier_sphere_next_av - 1e-6:
            sphere_dmg = (0.05 + 0.10 * self._barrier_sprout_stacks) * self._barrier_initial_shield
            removed = min(self._barrier_hp, sphere_dmg)
            self._barrier_sphere_removed += removed
            self._barrier_hp = max(0.0, self._barrier_hp - removed)
            self._barrier_sprout_stacks = 0
            if self._barrier_hp <= 0.0:
                self._barrier_sphere_next_av = None
                break
            self._barrier_sphere_next_av += interval

    def check_state_transitions(self) -> None:
        """在每次行动/结算后检查屏障激活、紫色球体结算、破盾与转阶段。"""
        cur_hp, max_hp = self.port.get_entity_hp_and_max(self.owner_id)
        if self._phase == 2 and cur_hp <= 0.0:
            return
        av = self.port.get_current_av()

        if self._phase == 1:
            if not self._phase1_barrier_triggered and 0.0 < cur_hp <= max_hp * self._phase1_barrier_trigger_ratio:
                self._phase1_barrier_triggered = True
                self._activate_barrier(
                    av,
                    shield=self._phase1_barrier_shield,
                    sphere_interval_av=self.PHASE1_SPHERE_INTERVAL_AV,
                )
                return

            self._tick_purple_sphere(av)
            if self._barrier_active and self._barrier_hp <= 0.0:
                self._break_barrier()
                return

            # Phase 1 生命归零 -> 转入 Phase 2
            cur_hp, _ = self.port.get_entity_hp_and_max(self.owner_id)
            if cur_hp <= 0.0:
                self._enter_phase2()
            return

        # Phase 2: 检查 70% HP 狂暴加速与二阶段屏障激活
        if not self._phase2_berserk_triggered and 0.0 < cur_hp <= self._phase2_max_hp * self._phase2_barrier_trigger_ratio:
            self._phase2_berserk_triggered = True
            self._activate_barrier(
                av,
                shield=self._phase2_barrier_shield,
                sphere_interval_av=self.PHASE2_SPHERE_INTERVAL_AV,
            )
            self._phase2_berserk_end_av = av + self._phase2_berserk_duration_av
            self.port.set_entity_speed(self.owner_id, self.PHASE2_BERSERK_SPEED)
            return

        self._tick_purple_sphere(av)
        if self._barrier_active and (
            self._barrier_hp <= 0.0
            or (
                self._phase2_berserk_end_av is not None
                and av >= self._phase2_berserk_end_av - 1e-6
            )
        ):
            self._break_barrier()

    def _enter_phase2(self) -> None:
        self._phase = 2
        self._barrier_active = False
        self._barrier_sphere_next_av = None
        self._combat_turns = 0
        self._subaction_idx = 0
        self.port.set_entity_phase_stats(
            self.owner_id,
            max_hp=self._phase2_max_hp,
            current_hp=self._phase2_max_hp,
            speed=self.PHASE2_BASE_SPEED,
            toughness=self.PHASE2_TOUGHNESS,
            reset_distance=0.0,
            toughness_dmg_reduction=self._phase2_toughness_dmg_reduction,
        )
        allies = self._get_aoe_allies()
        if allies:
            self._execute_pulse_with_config(allies)
            if self._apply_hp_lock_on_pulse:
                for tgt in allies:
                    if hasattr(self.port, "apply_hp_lock"):
                        self.port.apply_hp_lock(target_id=tgt, delta_ratio=0.10, max_ratio=0.50)

    def _get_aoe_allies(self) -> Tuple[str, ...]:
        if self._aoe_include_memosprites:
            try:
                return self.port.get_living_allies(include_memosprites=True)
            except TypeError:
                pass
        return self.port.get_living_allies()

    def _execute_pulse_with_config(self, allies: Tuple[str, ...]) -> None:
        try:
            self.port.execute_channel_pulse(
                owner_id=self.owner_id,
                allies=allies,
                multipliers=self._transition_pulse_multipliers,
                tick_hit_energy=self._transition_pulse_hit_energy[0],
                final_hit_energy=self._transition_pulse_hit_energy[1],
            )
        except TypeError:
            self.port.execute_channel_pulse(owner_id=self.owner_id, allies=allies)

    def execute_turn(self, ctx: EnemyActionContext) -> EnemyActionResult:
        if self._phase == 1:
            return EnemyActionResult(reset_distance=1e12)

        if getattr(self.port, "is_broken", lambda _: False)(self.owner_id):
            self._subaction_idx = 0
            self.port.set_continuous_action_hold(False)
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

        allies = self.port.get_living_allies()
        if not allies:
            self._subaction_idx = 0
            self.port.set_continuous_action_hold(False)
            return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

        if self._subaction_idx == 0:
            self._combat_turns += 1

        if getattr(self, "_phase2_plan", None) and self._combat_turns in self._phase2_plan:
            plan = self._phase2_plan[self._combat_turns]
        else:
            plan = _phase2_plan_for_turn(self._combat_turns)
        subaction = plan[self._subaction_idx]

        if subaction in ("HEAVY_ST", "ABSORB_AND_HEAVY_ST"):
            if subaction == "ABSORB_AND_HEAVY_ST":
                self.port.absorb_sprout_and_heal(owner_id=self.owner_id, heal_ratio=0.04)
            hits = self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=(allies[0],),
                multiplier=self._heavy_st_multiplier,
                element="Physical",
                hit_energy=10.0,
                hits=1,
                blast=False,
            )
            if self._apply_hp_lock_on_st:
                for tgt in hits:
                    if hasattr(self.port, "apply_hp_lock"):
                        self.port.apply_hp_lock(target_id=tgt, delta_ratio=0.10, max_ratio=0.50)
        elif subaction == "PARTY_AOE":
            aoe_allies = self._get_aoe_allies()
            hits = self.port.apply_enemy_attack(
                owner_id=self.owner_id,
                target_ids=aoe_allies,
                multiplier=self._party_aoe_multiplier,
                element="Physical",
                hit_energy=10.0,
                hits=1,
                blast=False,
            )
            if self._apply_hp_lock_on_aoe:
                for tgt in hits:
                    if hasattr(self.port, "apply_hp_lock"):
                        self.port.apply_hp_lock(target_id=tgt, delta_ratio=0.10, max_ratio=0.50)
        elif subaction == "SUMMON_SPROUTS":
            self.port.summon_transition_sprouts(owner_id=self.owner_id)
        elif subaction in ("CHANNEL_PULSE", "ABSORB_AND_CHANNEL_PULSE"):
            if subaction == "ABSORB_AND_CHANNEL_PULSE":
                self.port.absorb_sprout_and_heal(owner_id=self.owner_id, heal_ratio=0.04)
            aoe_allies = self._get_aoe_allies()
            self._execute_pulse_with_config(aoe_allies)
            if self._apply_hp_lock_on_pulse:
                for tgt in aoe_allies:
                    if hasattr(self.port, "apply_hp_lock"):
                        self.port.apply_hp_lock(target_id=tgt, delta_ratio=0.10, max_ratio=0.50)

        self._subaction_idx += 1
        if self._subaction_idx < len(plan):
            self.port.set_continuous_action_hold(True)
            return EnemyActionResult(reset_distance=0.0)

        self._subaction_idx = 0
        self.port.set_continuous_action_hold(False)
        return EnemyActionResult(reset_distance=STANDARD_ACTION_DISTANCE)

# coding: utf-8
"""关卡 30126122 场景建模 (参考实机日志 battle_20261114_155925.jsonl 与 Nanoka 数据库)。

敌方实测与数据库参数 (Lv.95):
- 月夜天马 (id=4023020, uid=100009):
  - MaxHP: 3,631,241.13 (= 680857.7125462855 * 16 / 3, 日志首轮伤害+当前血量反推)
  - Speed: 132.0 (ActionDelay = 75.757576)
  - Toughness: 160.0, 弱点: Fire / Quantum / Imaginary
- 正阳狮鹫 (uid=100011):
  - MaxHP: 4,085,146.28 (= 680857.7125462855 * 6, 日志首轮伤害+当前血量反推)
  - Speed: 158.4 (ActionDelay = 63.131313, 开场 50% 拉条后首动 ActionDelay = 31.565657)
  - Toughness: 160.0, 弱点: Physical / Quantum / Imaginary
- 流星铁鹰 (id=4022010, uid=100017/100019/100021 & 100037/100039/100041):
  - MaxHP: 680,857.7125462855 (日志 OnInitializeEnemy 精确值)
  - Speed: 132.0 (ActionDelay = 75.757576)
  - Toughness: 90.0, 弱点: Wind / Quantum / Imaginary (其余属性抗性 0.2 经日志实测)
  - 由正阳狮鹫在 31.57 AV 与 220.96 AV 召唤 3 只，初始 ActionDelay 分别为
    37.88 (5000/132) / 60.61 (8000/132) / 83.33 (11000/132)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from .actions import ActionKind
from .combat_port import BuffSpec
from .core import Entity, TurnSimulator
from .damage import DamageRequest, DamageType
from .effects import ApplyDamageEffect
from .events import ActionEndEvent, BattleEvent, DamageAppliedEvent, EnemyDefeatedEvent, EnemySpawnedEvent, TurnBeginEvent
from .kits.enemies import (
    ApoliBossKit,
    BeastSproutKit,
    MeteorEagleKit,
    MoonlitPegasusKit,
    SunlitGriffinKit,
)
from .status import DurationTiming, Modifier, ModifierOp, StatType

STAGE_ID = 30126122
MAX_CYCLES = 45
MAX_WAVES = 2

_ELEMENTS = ("Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary")

# 实机日志 Lv.95 数值
EAGLE_HP = 680857.7125462855
EAGLE_SPEED = 132.0
EAGLE_TOUGHNESS = 90.0
EAGLE_WEAKNESSES = ["Wind", "Quantum", "Imaginary"]
EAGLE_INITIAL_DISTANCES: Tuple[float, ...] = (5000.0, 8000.0, 11000.0)

PEGASUS_HP = EAGLE_HP * 16.0 / 3.0  # 3,631,241.1335801893
PEGASUS_SPEED = 132.0
PEGASUS_TOUGHNESS = 480.0
PEGASUS_WEAKNESSES = ["Fire", "Quantum", "Imaginary"]

GRIFFIN_HP = EAGLE_HP * 6.0  # 4,085,146.275277713
GRIFFIN_SPEED = 158.4
GRIFFIN_INITIAL_DISTANCE = 5000.0
GRIFFIN_TOUGHNESS = 480.0
GRIFFIN_WEAKNESSES = ["Physical", "Quantum", "Imaginary"]

# 第二波 Lv.95 敌方实测数值
APOLI_PHASE1_HP = 5106432.844098277
APOLI_PHASE2_HP = 10212865.688196555
APOLI_BASE_SPEED = 237.60000005364418
APOLI_TOUGHNESS = 1080.0
APOLI_WEAKNESSES = ["Ice", "Quantum", "Imaginary"]

SPROUT_HP = EAGLE_HP * 2.0  # 1,361,715.425092571
SPROUT_SPEED = 186.24000003933907
SPROUT_TOUGHNESS = 120.0
SPROUT_WEAKNESSES = ["Fire", "Wind", "Imaginary"]
SPROUT_INTERVAL_SPEED = 132.0  # 10000 / 132.0 = 75.757576 AV 增援节拍


def _build_enemy_entity(
    *,
    name: str,
    hp: float,
    speed: float,
    weaknesses: List[str],
    max_toughness: float,
    initial_distance: float = 10000.0,
    is_boss: bool = False,
    base_atk: float = 1200.0,
) -> Entity:
    ent = Entity(
        name=name,
        base_speed=speed,
        base_atk=base_atk,
        max_hp=hp,
        current_hp=hp,
        max_toughness=max_toughness,
        current_toughness=max_toughness,
        weaknesses=list(weaknesses),
        is_enemy=True,
        is_boss=is_boss,
    )
    ent.level = 95
    ent.distance_remaining = initial_distance
    ent.hit_energy = 5.0
    ent.damage_res = {el: (0.0 if el in weaknesses else 0.2) for el in _ELEMENTS}
    return ent


def create_moonlit_pegasus(name: str = "月夜天马") -> Entity:
    """构建月夜天马 (4023020, Lv.95) 实体。"""
    return _build_enemy_entity(
        name=name,
        hp=PEGASUS_HP,
        speed=PEGASUS_SPEED,
        weaknesses=PEGASUS_WEAKNESSES,
        max_toughness=PEGASUS_TOUGHNESS,
        initial_distance=10000.0,
        is_boss=False,
        base_atk=1400.0,
    )


def create_sunlit_griffin(name: str = "正阳狮鹫") -> Entity:
    """构建正阳狮鹫 (Lv.95) 实体。"""
    return _build_enemy_entity(
        name=name,
        hp=GRIFFIN_HP,
        speed=GRIFFIN_SPEED,
        weaknesses=GRIFFIN_WEAKNESSES,
        max_toughness=GRIFFIN_TOUGHNESS,
        initial_distance=GRIFFIN_INITIAL_DISTANCE,
        is_boss=True,
        base_atk=1711.0,
    )


def create_meteor_eagle(
    name: str = "流星铁鹰",
    initial_distance: float = 10000.0,
) -> Entity:
    """构建流星铁鹰 (4022010, Lv.95) 实体。"""
    return _build_enemy_entity(
        name=name,
        hp=EAGLE_HP,
        speed=EAGLE_SPEED,
        weaknesses=EAGLE_WEAKNESSES,
        max_toughness=EAGLE_TOUGHNESS,
        initial_distance=initial_distance,
        is_boss=False,
        base_atk=1476.0,
    )


def create_apoli_boss(name: str = "堕神之血•亚婆离") -> Entity:
    return _build_enemy_entity(
        name=name,
        hp=APOLI_PHASE1_HP,
        speed=APOLI_BASE_SPEED,
        max_toughness=APOLI_TOUGHNESS,
        weaknesses=APOLI_WEAKNESSES,
        is_boss=True,
        base_atk=1476.0,
    )


def create_beast_sprout(name: str) -> Entity:
    return _build_enemy_entity(
        name=name,
        hp=SPROUT_HP,
        speed=SPROUT_SPEED,
        max_toughness=SPROUT_TOUGHNESS,
        weaknesses=SPROUT_WEAKNESSES,
        base_atk=1476.0,
    )


class Stage30126122CombatPort:
    """关卡 30126122 敌方 Kit 战斗端口适配器，连接敌方 Kit 与 TurnSimulator。"""

    def __init__(self, sim: TurnSimulator) -> None:
        self.sim = sim

    def is_alive(self, entity_id: str) -> bool:
        ent = self.sim.get_entity(entity_id)
        return ent is not None and getattr(ent, "current_hp", 0.0) > 0

    def get_living_allies(self) -> Tuple[str, ...]:
        allies = [
            e.name
            for e in self.sim.entities
            if not e.is_enemy
            and getattr(e, "current_hp", 0.0) > 0
            and not getattr(e, "is_countdown", False)
            and not getattr(e, "is_memosprite", False)
        ]
        return tuple(allies)

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
        attacker = self.sim.get_entity(owner_id)
        if attacker is None or attacker.current_hp <= 0:
            return ()
        skip_provider = getattr(self.sim, "enemy_attack_skip_provider", None)
        if skip_provider is not None and skip_provider(attacker, float(getattr(self.sim, "current_av", 0.0))):
            return ()
        attacker.hit_energy = hit_energy

        resolved_targets: List[Entity] = []
        for tid in target_ids:
            tgt = self.sim.get_entity(tid)
            if tgt is not None and tgt.current_hp > 0:
                resolved_targets.append(tgt)
        if not resolved_targets:
            return ()

        # 若外部挂载了 target_provider 且本次为单体点名，则优先遵循对账引导
        target_provider = getattr(self.sim, "target_provider", None)
        if target_provider is not None and len(resolved_targets) == 1:
            living = [
                e
                for e in self.sim.entities
                if not e.is_enemy
                and e.current_hp > 0
                and not getattr(e, "is_countdown", False)
            ]
            if living:
                chosen = target_provider(attacker, living, 0)
                if chosen is not None:
                    resolved_targets = [chosen]

        if blast and len(resolved_targets) == 1:
            primary = resolved_targets[0]
            living_allies = [
                e
                for e in self.sim.entities
                if not e.is_enemy
                and e.current_hp > 0
                and not getattr(e, "is_countdown", False)
            ]
            blast_provider = getattr(self.sim, "blast_target_provider", None)
            if blast_provider is not None:
                extra = blast_provider(attacker, primary, living_allies)
                for adj in extra or ():
                    if adj is not None and adj.current_hp > 0 and adj not in resolved_targets:
                        resolved_targets.append(adj)
            else:
                # 通用扩散邻位: 优先匹配存在绑定关系的忆灵/召唤者, 否则按站位邻格扩散
                port = getattr(self.sim, "port", None)
                paired = [
                    e
                    for e in living_allies
                    if e is not primary
                    and port is not None
                    and (
                        port.is_own_memosprite(primary.name, e.name)
                        or port.is_own_memosprite(e.name, primary.name)
                    )
                ]
                if paired:
                    resolved_targets.extend(paired)
                elif primary in living_allies:
                    idx = living_allies.index(primary)
                    for adj_idx in (idx - 1, idx + 1):
                        if 0 <= adj_idx < len(living_allies):
                            resolved_targets.append(living_allies[adj_idx])

        for _ in range(max(1, hits)):
            for tgt in resolved_targets:
                if tgt.current_hp <= 0:
                    continue
                req = DamageRequest(
                    attacker=attacker,
                    target=tgt,
                    skill_multiplier=multiplier,
                )
                self.sim.resolver.enqueue(
                    ApplyDamageEffect(
                        request=req,
                        toughness_reduction=0.0,
                        element=element,
                    )
                )
            self.sim.resolver.resolve_all()
        self.sim._action_seq += 1
        return tuple(t.name for t in resolved_targets)

    def apply_hp_lock(
        self,
        *,
        target_id: str,
        delta_ratio: float = 0.10,
        max_ratio: float = 0.50,
    ) -> None:
        tgt = self.sim.get_entity(target_id)
        if tgt is None or tgt.is_enemy or tgt.current_hp <= 0.0:
            return
        cur = float(getattr(tgt, "hp_lock_ratio", 0.0))
        tgt.hp_lock_ratio = min(max_ratio, cur + delta_ratio)
        tgt.clamp_hp()

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
        attacker = self.sim.get_entity(owner_id)
        target = self.sim.get_entity(target_id)
        if attacker is None or target is None or target.current_hp <= 0:
            return False
        provider = getattr(self.sim, "debuff_hit_provider", None)
        if provider is not None:
            landed = bool(provider(attacker, target, key, float(getattr(self.sim, "current_av", 0.0))))
        else:
            eff_hit = float(getattr(attacker, "effect_hit_rate", getattr(attacker, "base_effect_hit_rate", 0.36)))
            eff_res = float(self.sim.port.stat(target_id, StatType.EFFECT_RES))
            chance = base_chance * (1.0 + eff_hit) * max(0.0, 1.0 - eff_res)
            rng = getattr(self.sim, "rng", None)
            roll = rng.random() if rng is not None else 0.0
            landed = roll < chance
        if not landed:
            return False

        full_key = f"{key}_{target_id}"
        existing = next(
            (s for s in self.sim.status_mgr.get_statuses(target_id) if s.id == full_key),
            None,
        )
        prev_stacks = int(getattr(existing, "stacks", 0)) if existing is not None else 0
        stacks = min(max_stacks, prev_stacks + 1)
        if existing is not None:
            self.sim.port.remove_status(target_id, full_key)
        self.sim.port.upsert_status(
            BuffSpec(
                key=full_key,
                name=name,
                source_id=owner_id,
                target_id=target_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, pct_per_stack),),
                duration=duration,
                timing=DurationTiming.TARGET_TURN_END,
                category="debuff",
                stacks=stacks,
                max_stacks=max_stacks,
                description=f"速度降低 {abs(pct_per_stack) * stacks * 100:.0f}% ({stacks}层)",
            )
        )
        return True

    def apply_mark_status(
        self,
        *,
        owner_id: str,
        target_id: str,
        mark_key: str,
        mark_name: str,
        description: str = "",
    ) -> None:
        self.sim.port.upsert_status(
            BuffSpec(
                key=mark_key,
                name=mark_name,
                source_id=owner_id,
                target_id=target_id,
                modifiers=(),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="debuff",
                description=description,
            )
        )

    def remove_mark_status(
        self,
        *,
        target_id: str,
        mark_key: str,
    ) -> bool:
        if not self.has_mark_status(target_id=target_id, mark_key=mark_key):
            return False
        self.sim.status_mgr.remove_status(target_id, mark_key)
        return True

    def has_mark_status(
        self,
        *,
        target_id: str,
        mark_key: str,
    ) -> bool:
        return any(
            st.id == mark_key for st in self.sim.status_mgr.get_statuses(target_id)
        )

    def trigger_oronyx_detonation(
        self,
        *,
        owner_id: str,
        target_id: str,
        multiplier: float,
        element: str = "Quantum",
    ) -> None:
        self.apply_enemy_attack(
            owner_id=owner_id,
            target_ids=(target_id,),
            multiplier=multiplier,
            element=element,
            hit_energy=0.0,
            hits=1,
        )

    def summon_meteor_eagles(
        self,
        *,
        owner_id: str,
        generation: int,
        count: int = 3,
        initial_distances: Optional[Tuple[float, ...]] = None,
    ) -> Tuple[str, ...]:
        # 回收上一代残留的流星铁鹰 (实机 220.96 AV: 正阳狮鹫重召时直接清除场上残存铁鹰)
        old_eagles = [e for e in self.sim.entities if e.is_enemy and e.name.startswith("流星铁鹰_")]
        for old in old_eagles:
            old.current_hp = 0.0
            self.sim.entities.remove(old)

        distances = initial_distances or EAGLE_INITIAL_DISTANCES
        spawned_ids: List[str] = []
        spawned_entities: List[Entity] = []
        for idx in range(1, count + 1):
            dist = distances[idx - 1] if idx - 1 < len(distances) else 10000.0
            eagle_name = f"流星铁鹰_g{generation}_{idx}"
            eagle = create_meteor_eagle(name=eagle_name, initial_distance=dist)
            windwalk_provider = getattr(self.sim, "enemy_windwalk_provider", None)
            windwalk_ready = (
                bool(windwalk_provider(eagle_name, generation, idx))
                if windwalk_provider is not None
                else (generation == 1 and idx == 3)
            )
            eagle.kit = MeteorEagleKit(
                owner_id=eagle_name,
                port=self,
                windwalk_ready=windwalk_ready,
            )
            self.sim.add_entity(eagle, trigger_battle_start=False)
            eagle.kit.port = self
            eagle.distance_remaining = dist
            self.sim.event_bus.publish(
                EnemySpawnedEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=self.sim.current_cycle,
                    enemy_name=eagle_name,
                )
            )
            spawned_ids.append(eagle_name)
            spawned_entities.append(eagle)

        # 实机站位排序: [g_1, 月夜天马, g_3, 正阳狮鹫, g_2]，确保月夜天马与正阳狮鹫各左右相邻两只铁鹰
        if len(spawned_entities) == 3:
            pegasus = self.sim.get_entity("月夜天马")
            griffin = self.sim.get_entity("正阳狮鹫")
            if pegasus is not None and griffin is not None:
                non_targets = [
                    e for e in self.sim.entities
                    if e not in spawned_entities and e is not pegasus and e is not griffin
                ]
                self.sim.entities[:] = non_targets + [
                    spawned_entities[0],
                    pegasus,
                    spawned_entities[2],
                    griffin,
                    spawned_entities[1],
                ]
                if hasattr(self.sim, "_rebuild_entity_cache"):
                    self.sim._rebuild_entity_cache()
        return tuple(spawned_ids)

    # ---- ApoliCombatPort & SproutCombatPort ----

    def get_current_av(self) -> float:
        return float(getattr(self.sim, "current_av", 0.0))

    def get_entity_hp_and_max(self, entity_id: str) -> Tuple[float, float]:
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            return (0.0, 0.0)
        return (float(ent.current_hp), float(ent.max_hp))

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
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            return
        ent.max_hp = max_hp
        ent.current_hp = current_hp
        ent.base_speed = speed
        ent.max_toughness = toughness
        ent.current_toughness = toughness
        ent.is_broken = False
        if reset_distance is not None:
            ent.distance_remaining = reset_distance
        if toughness_dmg_reduction is not None:
            ent.toughness_dmg_reduction = float(toughness_dmg_reduction)

    def set_entity_speed(self, entity_id: str, speed: float) -> None:
        ent = self.sim.get_entity(entity_id)
        if ent is None:
            return
        old_speed = float(getattr(ent, "speed", speed))
        ent.base_speed = speed
        if old_speed > 0.0 and speed > 0.0 and ent.distance_remaining < 1e9:
            # 保持当前剩余 AV 比例（或由行动条自然重算）
            pass

    def break_entity_toughness_and_deduct_hp(
        self,
        entity_id: str,
        *,
        hp_deduct: float,
    ) -> None:
        ent = self.sim.get_entity(entity_id)
        if ent is None or ent.current_hp <= 0.0:
            return
        ent.current_toughness = 0.0
        ent.is_broken = True
        ent.current_hp = max(0.0, float(ent.current_hp) - hp_deduct)
        if ent.distance_remaining < 1e9:
            ent.distance_remaining += 2500.0

    def is_broken(self, entity_id: str) -> bool:
        ent = self.sim.get_entity(entity_id)
        return bool(ent is not None and getattr(ent, "is_broken", False))

    def set_continuous_action_hold(self, hold: bool) -> None:
        if hasattr(self.sim, "scheduler"):
            self.sim.scheduler.continuous_action_hold = hold

    def summon_transition_sprouts(self, *, owner_id: str) -> Tuple[str, ...]:
        director = getattr(self.sim, "_stage_director", None)
        if director is not None and hasattr(director, "spawn_wave2_sprouts"):
            return director.spawn_wave2_sprouts(
                count=2,
                reanchor_timer=True,
                initial_distance=5000.0,
            )
        return ()

    def absorb_sprout_and_heal(
        self,
        *,
        owner_id: str,
        heal_ratio: float = 0.04,
    ) -> bool:
        boss = self.sim.get_entity(owner_id)
        if boss is None or boss.current_hp <= 0.0:
            return False
        director = getattr(self.sim, "_stage_director", None)
        target_sprout = None
        for ent in self.sim.entities:
            if (
                ent.is_enemy
                and ent.current_hp > 0.0
                and ent.name.startswith("狂兽的胚芽")
            ):
                target_sprout = ent
                break
        if target_sprout is None:
            return False
        if director is not None and hasattr(director, "_notified_dead_sprouts"):
            director._notified_dead_sprouts.add(target_sprout.name)
        target_sprout.current_hp = 0.0
        target_sprout.distance_remaining = 1e12
        heal_amt = boss.max_hp * max(0.0, heal_ratio)
        if heal_amt > 0.0:
            boss.current_hp = min(boss.max_hp, boss.current_hp + heal_amt)
        return True

    def execute_channel_pulse(
        self,
        *,
        owner_id: str,
        allies: Tuple[str, ...],
    ) -> None:
        attacker = self.sim.get_entity(owner_id)
        if attacker is None or attacker.current_hp <= 0.0:
            return
        setattr(self.sim, "_in_channel_pulse", True)
        try:
            for _ in range(8):
                if hasattr(self.sim, "_action_seq"):
                    self.sim._action_seq += 1
                self.apply_enemy_attack(
                    owner_id=owner_id,
                    target_ids=allies,
                    multiplier=0.1,
                    element="Physical",
                    hit_energy=1.0,
                    hits=1,
                    blast=False,
                )
            if hasattr(self.sim, "_action_seq"):
                self.sim._action_seq += 1
            self.apply_enemy_attack(
                owner_id=owner_id,
                target_ids=allies,
                multiplier=0.8,
                element="Physical",
                hit_energy=12.0,
                hits=1,
                blast=False,
            )
        finally:
            setattr(self.sim, "_in_channel_pulse", False)

    def heal_boss_by_ratio(self, *, boss_id: str, ratio: float) -> float:
        boss = self.sim.get_entity(boss_id)
        if boss is None or boss.current_hp <= 0.0:
            return 0.0
        heal_amt = float(boss.max_hp) * ratio
        before = float(boss.current_hp)
        boss.current_hp = min(float(boss.max_hp), before + heal_amt)
        return boss.current_hp - before

    def is_boss_barrier_active(self, boss_id: str) -> bool:
        boss = self.sim.get_entity(boss_id)
        kit = getattr(boss, "kit", None) if boss is not None else None
        return bool(getattr(kit, "barrier_active", False))

    def apply_boss_backlash(self, *, boss_id: str, damage: float) -> None:
        resolver = getattr(self.sim, "resolver", None)
        if resolver is not None and (getattr(resolver, "_resolving", False) or getattr(resolver, "_aoe_depth", 0) > 0):
            resolver.defer_post_resolve(
                lambda: self._apply_boss_backlash_now(boss_id=boss_id, damage=damage)
            )
            return
        self._apply_boss_backlash_now(boss_id=boss_id, damage=damage)

    def _apply_boss_backlash_now(self, *, boss_id: str, damage: float) -> None:
        boss = self.sim.get_entity(boss_id)
        if boss is None or boss.current_hp <= 0.0:
            return
        kit = getattr(boss, "kit", None)
        if kit is not None and getattr(kit, "barrier_active", False):
            if hasattr(kit, "notify_sprout_killed_on_barrier"):
                kit.notify_sprout_killed_on_barrier(float(boss.max_hp) * 0.02)
            return
        boss.current_hp = max(0.0, float(boss.current_hp) - float(boss.max_hp) * 0.02)


@dataclass(frozen=True)
class ElationLaughGainEvent(BattleEvent):
    """特殊增益事件：我方施放终结技获得笑点。"""

    actor_name: str = ""
    gained: int = 5
    total_laugh_points: int = 0
    description: str = ""


@dataclass(frozen=True)
class AhaExtraTurnEvent(BattleEvent):
    """特殊增益事件：每轮开始时阿哈获得固定计入 20 笑点的额外回合（不消耗笑点）。"""

    fixed_laugh_points: int = 20
    consumed_laugh_points: int = 0
    remaining_laugh_points: int = 0
    description: str = ""


class Stage30126122Director:
    """关卡 30126122 导演：负责机制事件转发、欢愉笑点/阿哈特殊事件与波次切换推进。"""

    def __init__(
        self,
        sim: TurnSimulator,
        *,
        pegasus_kit: MoonlitPegasusKit,
        griffin_kit: SunlitGriffinKit,
        wave2_factory: Optional[Callable[[TurnSimulator], List[Entity]]] = None,
    ) -> None:
        self.sim = sim
        self.stage_id = STAGE_ID
        self.max_cycles = MAX_CYCLES
        self.max_waves = MAX_WAVES
        self.wave = 1
        self.pegasus_kit = pegasus_kit
        self.griffin_kit = griffin_kit
        self._wave2_factory = wave2_factory
        self._notified_dead_eagles: set[str] = set()
        self.apoli_kit: Optional[ApoliBossKit] = None
        self._apoli_locked_toughness: float = APOLI_TOUGHNESS
        self._sprout_count: int = 0
        self._notified_dead_sprouts: set[str] = set()
        self._sprout_advance_seq: dict[str, int] = {}
        self._sprout_timer_name: str = "胚芽增援倒计时"
        setattr(self.sim, "_stage_director", self)

        # 关卡特殊增益: 我方施放终结技获得 5 个笑点；每轮开始时阿哈立即获得 1 个固定计入 20 笑点的额外回合(不消耗笑点)
        self.laugh_points: int = 0
        self.aha_extra_turns: List[dict[str, Any]] = []
        self.aha_special_damage: float = 0.0
        self._triggered_aha_cycles: set[tuple[int, int]] = set()
        self._wave_start_av: float = 0.0
        self._triggered_aha_137: bool = False
        self._triggered_aha_150: bool = False

        self.sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        self.sim.event_bus.subscribe(ActionEndEvent, self._on_action_end)
        self.sim.event_bus.subscribe(EnemyDefeatedEvent, self._on_entity_defeated)
        self.sim.event_bus.subscribe(DamageAppliedEvent, self._on_damage_applied)

    def _on_turn_begin(self, event: TurnBeginEvent) -> None:
        self._check_aha_special_damage_events()
        if event.actor_name == self._sprout_timer_name and self.wave >= 2:
            boss = self.sim.get_entity("堕神之血•亚婆离")
            if boss is not None and boss.current_hp > 0.0:
                self.spawn_wave2_sprouts(count=2, reanchor_timer=False)

    def _on_damage_applied(self, event: DamageAppliedEvent) -> None:
        target_name = str(getattr(event, "target_name", ""))
        if not target_name.startswith("狂兽的胚芽"):
            return
        if getattr(event, "damage", 0.0) <= 0.0:
            return
        ent = self.sim.get_entity(target_name)
        if ent is None or not ent.is_enemy or ent.current_hp <= 0.0 or ent.distance_remaining >= 1e9:
            return
        action_seq = int(getattr(self.sim, "_action_seq", 0))
        if self._sprout_advance_seq.get(target_name) == action_seq:
            return
        self._sprout_advance_seq[target_name] = action_seq
        # 受到攻击伤害时，存活胚芽行动提前 8% (800 / 10000 跑道)，每次行动至多触发一次
        ent.distance_remaining = max(0.0, ent.distance_remaining - 800.0)

    def _on_action_end(self, event: ActionEndEvent) -> None:
        self.pegasus_kit.on_event(event)
        ent = self.sim.get_entity(event.actor_id)
        is_ally = ent is not None and not ent.is_enemy
        is_ult = (
            event.action_kind == ActionKind.ULTIMATE
            or "终结技" in str(event.action_type)
        )
        if is_ally and is_ult:
            self.laugh_points += 5
            self.sim.event_bus.publish(
                ElationLaughGainEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=self.sim.current_cycle,
                    actor_name=event.actor_name,
                    gained=5,
                    total_laugh_points=self.laugh_points,
                    description=f"[ElationLaughGain] {event.actor_name} 施放终结技，获得 5 个笑点（当前 {self.laugh_points}）",
                )
            )

    def _on_entity_defeated(self, event: EnemyDefeatedEvent) -> None:
        self.griffin_kit.on_event(event)

    def _current_wave_cycle(self) -> int:
        elapsed = max(0.0, float(self.sim.current_av) - self._wave_start_av)
        if elapsed < 150.0 - 1e-9:
            return 0
        return 1 + int((elapsed - 150.0 + 1e-9) // 100.0)

    def _check_cycle_aha_extra_turn(self) -> None:
        cur_cycle = self._current_wave_cycle()
        key = (self.wave, cur_cycle)
        if key not in self._triggered_aha_cycles:
            self._triggered_aha_cycles.add(key)
            record = {
                "cycle": cur_cycle,
                "av": round(self.sim.current_av, 2),
                "fixed_laugh_points": 20,
                "consumed_laugh_points": 0,
                "remaining_laugh_points": self.laugh_points,
            }
            self.aha_extra_turns.append(record)
            self.sim.event_bus.publish(
                AhaExtraTurnEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=cur_cycle,
                    fixed_laugh_points=20,
                    consumed_laugh_points=0,
                    remaining_laugh_points=self.laugh_points,
                    description=f"[AhaExtraTurn] 第 {cur_cycle} 轮开始：阿哈获得 1 个固定计入 20 笑点的额外回合（不消耗笑点，当前笑点 {self.laugh_points}）",
                )
            )

    def apply_aha_hp_damage(self, target_name: str, dmg: float) -> float:
        ent = self.sim.get_entity(target_name)
        if ent is None or ent.current_hp <= 0:
            return 0.0
        kit = getattr(ent, "kit", None)
        effective_dmg = dmg
        if kit is not None and hasattr(kit, "intercept_incoming_damage"):
            effective_dmg = kit.intercept_incoming_damage(ent.name, dmg)
        actual = min(ent.current_hp, effective_dmg)
        ent.current_hp = max(0.0, ent.current_hp - effective_dmg)
        self.aha_special_damage += dmg
        return actual

    def apply_aha_ally_chip_hit(self, target_name: str) -> None:
        """阿哈回合伴生 1.0 基础伤害 (Lv.95 DEF 减免 -> 长夜月 0.528 / 风堇 0.429) 与 +2.0 基础受击回能。"""
        ent = self.sim.get_entity(target_name)
        if ent is None or ent.current_hp <= 0:
            return
        sm = getattr(self.sim, "status_mgr", None)
        def_val = (
            sm.calculate_stat(ent.name, getattr(ent, "base_def", 1000.0), StatType.DEF)
            if sm is not None
            else getattr(ent, "base_def", 1000.0)
        )
        # Lv.95 敌方防御乘区: (95 * 10 + 200) / (95 * 10 + 200 + DEF)
        atk_lvl_coeff = 95 * 10 + 200
        dmg = 1.0 * atk_lvl_coeff / (atk_lvl_coeff + max(0.0, def_val))
        actual = min(max(0.0, ent.current_hp - 1.0), dmg) if ent.current_hp > 1.0 else 0.0
        ent.current_hp = max(1.0, ent.current_hp - dmg) if ent.current_hp > 0.0 else 0.0
        if actual > 0.0:
            for ally in self.sim.entities:
                kit = getattr(ally, "kit", None)
                if kit is not None and hasattr(kit, "on_hp_lost"):
                    kit.on_hp_lost(ent.name, actual, cause="attack_damage")
        # 受击 +2.0 基础回能 (若目标为忆灵且无独立能量槽, 则由主人风堇记录回能)
        energy_target = ent
        if getattr(ent, "is_memosprite", False) and getattr(ent, "max_energy", 0.0) <= 0.0:
            master_name = getattr(ent, "master_name", None)
            if master_name:
                m_ent = self.sim.get_entity(master_name)
                if m_ent is not None:
                    energy_target = m_ent
        if getattr(energy_target, "max_energy", 0.0) > 0.0:
            err = (
                sm.calculate_stat(energy_target.name, getattr(energy_target, "base_err", 1.0), StatType.ERR)
                if sm is not None
                else getattr(energy_target, "base_err", 1.0)
            )
            energy_target.energy = min(energy_target.max_energy, energy_target.energy + 2.0 * err)

    def flush_ally_talent_heals(self) -> None:
        for ent in getattr(self.sim, "entities", ()):
            if not ent.is_enemy and ent.current_hp > 0:
                kit = getattr(ent, "kit", None)
                if kit is not None and hasattr(kit, "_resolve_talent_heal"):
                    kit._resolve_talent_heal()

    def _check_aha_special_damage_events(self) -> None:
        handler = getattr(self.sim, "aha_special_handler", None)
        if handler is not None:
            handler(self)

    def spawn_wave2_sprouts(
        self,
        *,
        count: int = 2,
        reanchor_timer: bool = False,
        initial_distance: float = 10000.0,
    ) -> Tuple[str, ...]:
        port = Stage30126122CombatPort(self.sim)
        spawned: List[str] = []
        for _ in range(count):
            self._sprout_count += 1
            idx = self._sprout_count
            name = f"狂兽的胚芽{idx}"
            sprout = create_beast_sprout(name)
            sprout.kit = BeastSproutKit(
                owner_id=name,
                port=port,
                boss_id="堕神之血•亚婆离",
                initial_action="attack" if idx % 2 == 1 else "heal",
            )
            self.sim.add_entity(sprout, trigger_battle_start=False)
            sprout.kit.port = port
            sprout.distance_remaining = float(initial_distance)
            self.sim.event_bus.publish(
                EnemySpawnedEvent(
                    av=round(self.sim.current_av, 2),
                    cycle=self.sim.current_cycle,
                    enemy_name=name,
                )
            )
            spawned.append(name)
        if reanchor_timer:
            timer_ent = self.sim.get_entity(self._sprout_timer_name)
            if timer_ent is not None:
                timer_ent.distance_remaining = 10000.0
        return tuple(spawned)

    def _spawn_default_wave2(self) -> None:
        port = Stage30126122CombatPort(self.sim)
        boss = create_apoli_boss("堕神之血•亚婆离")
        apoli_kit = ApoliBossKit(owner_id=boss.name, port=port)
        boss.kit = apoli_kit
        self.apoli_kit = apoli_kit
        self._apoli_locked_toughness = APOLI_TOUGHNESS
        self.sim.add_entity(boss, trigger_battle_start=True)
        boss.kit.port = port
        boss.distance_remaining = 1e12

        timer_ent = Entity(
            name=self._sprout_timer_name,
            max_hp=1.0,
            current_hp=1.0,
            base_speed=SPROUT_INTERVAL_SPEED,
            is_enemy=False,
            is_countdown=True,
        )
        self.sim.add_entity(timer_ent, trigger_battle_start=False)
        timer_ent.distance_remaining = 10000.0

        self.spawn_wave2_sprouts(count=2, reanchor_timer=False)

    def after_step(self) -> None:
        self._check_cycle_aha_extra_turn()
        self._check_aha_special_damage_events()

        # 兜底检测: 若流星铁鹰在结算中被击杀，确保触发正阳狮鹫清除【艾格勒印记】
        for eid in self.griffin_kit.summon_ids:
            if eid not in self._notified_dead_eagles:
                ent = self.sim.get_entity(eid)
                if ent is not None and ent.current_hp <= 0:
                    self._notified_dead_eagles.add(eid)
                    self.griffin_kit.clear_aquila_marks()

        # Wave 2 胚芽阵亡反噬与亚婆离状态机推进
        if self.wave >= 2:
            for ent in list(self.sim.entities):
                if (
                    ent.is_enemy
                    and ent.name.startswith("狂兽的胚芽")
                    and ent.current_hp <= 0
                    and ent.name not in self._notified_dead_sprouts
                ):
                    self._notified_dead_sprouts.add(ent.name)
                    kit = getattr(ent, "kit", None)
                    if kit is not None and hasattr(kit, "notify_death"):
                        kit.notify_death()

            if self.apoli_kit is not None:
                boss = self.sim.get_entity("堕神之血•亚婆离")
                if boss is not None:
                    if boss.current_hp > 0:
                        if self.apoli_kit.barrier_active:
                            boss.current_toughness = self._apoli_locked_toughness
                            boss.barrier_guarded = True
                            boss.damage_reduction = 0.75
                            boss.toughness_dmg_reduction = 0.0
                        else:
                            self._apoli_locked_toughness = float(boss.current_toughness)
                            boss.barrier_guarded = False
                            boss.damage_reduction = 0.0
                            boss.toughness_dmg_reduction = 0.10
                    self.apoli_kit.check_state_transitions()
                    berserk_end_av = self.apoli_kit.phase2_berserk_end_av
                    b_timer = self.sim.get_entity("血脑屏障狂暴倒计时")
                    if berserk_end_av is not None and boss.current_hp > 0:
                        rem_av = max(0.0, berserk_end_av - float(self.sim.current_av))
                        if b_timer is None:
                            b_timer = Entity(
                                name="血脑屏障狂暴倒计时",
                                max_hp=1.0,
                                current_hp=1.0,
                                base_speed=40.0,
                                is_enemy=False,
                                is_countdown=True,
                            )
                            self.sim.add_entity(b_timer, trigger_battle_start=False)
                        b_timer.base_speed = 40.0
                        b_timer.distance_remaining = rem_av * 40.0
                    elif b_timer is not None:
                        b_timer.distance_remaining = 1e12
                    if boss.current_hp > 0:
                        boss.barrier_guarded = self.apoli_kit.barrier_active
                        boss.damage_reduction = 0.75 if self.apoli_kit.barrier_active else 0.0
                        boss.toughness_dmg_reduction = 0.0 if self.apoli_kit.barrier_active else 0.10

        # 波次切换判定 (Wave 1 -> Wave 2)
        if self.wave < self.max_waves:
            living_enemies = [
                e for e in self.sim.entities if e.is_enemy and e.current_hp > 0
            ]
            if not living_enemies:
                self.wave += 1
                self._wave_start_av = float(self.sim.current_av)
                self._triggered_aha_cycles.add((self.wave, 0))
                # 换波瞬间重置在场可跑条我方实体跑道，清空就绪队列，保留能量/笑点/全局 AV
                for ent in self.sim.entities:
                    if (
                        not ent.is_enemy
                        and ent.current_hp > 0
                        and getattr(ent, "speed", 0.0) > 0.0
                        and ent.distance_remaining < 1e5
                    ):
                        ent.distance_remaining = 10000.0
                if hasattr(self.sim, "_ready_queue"):
                    self.sim._ready_queue.clear()

                if self._wave2_factory is not None:
                    for ent in self._wave2_factory(self.sim):
                        self.sim.add_entity(ent, trigger_battle_start=True)
                else:
                    self._spawn_default_wave2()


def build_stage_30126122(
    team: List[Entity],
    technique_users: Optional[Sequence[str]] = None,
    wave2_factory: Optional[Callable[[TurnSimulator], List[Entity]]] = None,
) -> Tuple[TurnSimulator, Stage30126122Director]:
    """组装关卡 30126122 场景: 返回 (sim, director)。"""
    for member in team:
        if (
            not getattr(member, "is_enemy", False)
            and getattr(member, "max_energy", 0.0) > 0
            and getattr(member, "energy", 0.0) == 0.0
        ):
            member.energy = member.max_energy * 0.5

    pegasus = create_moonlit_pegasus("月夜天马")
    griffin = create_sunlit_griffin("正阳狮鹫")

    # 进战削韧: 编队首位角色攻击进战时削减弱点匹配的初始敌方 10 点韧性
    if team:
        raw_elem = getattr(team[0], "element", None)
        entry_elem = str(raw_elem).capitalize() if raw_elem else None
        if entry_elem:
            for e in (pegasus, griffin):
                if entry_elem in e.weaknesses:
                    e.current_toughness = max(0.0, e.current_toughness - 10.0)

    tech_list = list(technique_users) if technique_users is not None else None
    sim = TurnSimulator(
        entities=list(team) + [pegasus, griffin],
        use_techniques=True,
        technique_users=tech_list,
        auto_ult=True,
    )

    port = Stage30126122CombatPort(sim)
    pegasus_kit = MoonlitPegasusKit(owner_id=pegasus.name, port=port)
    griffin_kit = SunlitGriffinKit(owner_id=griffin.name, port=port)
    pegasus.kit = pegasus_kit
    griffin.kit = griffin_kit

    sim.enemy_uid_map = {100009: "月夜天马", 100011: "正阳狮鹫"}
    director = Stage30126122Director(
        sim,
        pegasus_kit=pegasus_kit,
        griffin_kit=griffin_kit,
        wave2_factory=wave2_factory,
    )
    return sim, director

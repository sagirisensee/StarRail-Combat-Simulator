# coding: utf-8
"""关卡 30126122 场景建模 (混沌回忆式换波 + 欢愉/阿哈机制 + 关卡数值覆盖)。

敌方实测与数据库参数 (Lv.95):
- 月夜天马 (id=4023020, uid=100009):
  - MaxHP: 3,631,241.13 (= 680857.7125462855 * 16 / 3)
  - Speed: 132.0 (ActionDelay = 75.757576), Toughness: 480.0, 弱点: Fire / Quantum / Imaginary
- 正阳狮鹫 (uid=100011):
  - MaxHP: 4,085,146.28 (= 680857.7125462855 * 6)
  - Speed: 158.4 (开场 50% 拉条后首动 31.57 AV), Toughness: 480.0, 弱点: Physical / Quantum / Imaginary
- 流星铁鹰 (id=4022010):
  - MaxHP: 680,857.7125462855, Speed: 132.0, Toughness: 90.0, 弱点: Wind / Quantum / Imaginary
  - 由正阳狮鹫在 31.57 AV 与 220.96 AV 召唤 3 只，初始距离 5000 / 8000 / 11000。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from .actions import ActionKind
from .core import Entity, TurnSimulator
from .events import (
    ActionEndEvent,
    BattleEvent,
    DamageAppliedEvent,
    EnemyDefeatedEvent,
    EnemySpawnedEvent,
    TurnBeginEvent,
    WeaknessBreakEvent,
)
from .kits.enemies import (
    ApoliBossKit,
    BaseEnemyCombatPortImpl,
    BeastSproutKit,
    MeteorEagleKit,
    MoonlitPegasusKit,
    SunlitGriffinKit,
)
from .stage_director import BreakStatusHelper, MoCWaveMode
from .status import StatType

STAGE_ID = 30126122
MAX_CYCLES = 45
MAX_WAVES = 2

_ELEMENTS = ("Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary")

# 实机日志 Lv.95 关卡专属数值覆盖
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

# 第二波 Lv.95 敌方实测数值覆盖
APOLI_PHASE1_HP = 5106432.844098277
APOLI_PHASE2_HP = 10212865.688196555
APOLI_PHASE1_BARRIER_RATIO = 0.65
APOLI_PHASE2_BARRIER_RATIO = 0.65
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


class Stage30126122CombatPort(BaseEnemyCombatPortImpl):
    """关卡 30126122 敌方战斗端口：继承通用端口，仅覆写本关召唤与站位编排。"""

    def summon_meteor_eagles(
        self,
        *,
        owner_id: str,
        generation: int,
        count: int = 3,
        initial_distances: Optional[Tuple[float, ...]] = None,
    ) -> Tuple[str, ...]:
        director = getattr(self.sim, "_stage_director", None)
        if director is not None and hasattr(director, "flush_ally_talent_heals"):
            director.flush_ally_talent_heals()
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
            windwalk_val = (
                windwalk_provider(eagle_name, generation, idx)
                if windwalk_provider is not None
                else (generation == 1 and idx == 3)
            )
            eagle.kit = MeteorEagleKit(
                owner_id=eagle_name,
                port=self,
                windwalk_ready=(windwalk_val is True),
                windwalk_target=(windwalk_val if isinstance(windwalk_val, str) else None),
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
        target_sprout = next(
            (
                ent for ent in self.sim.entities
                if ent.is_enemy and ent.current_hp > 0.0 and ent.name.startswith("狂兽的胚芽")
            ),
            None,
        )
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
    """关卡 30126122 导演：组合混沌回忆换波模式 + 本关专属欢愉/阿哈紊流 + 敌方波次调度。"""

    def __init__(
        self,
        sim: TurnSimulator,
        *,
        pegasus_kit: MoonlitPegasusKit,
        griffin_kit: SunlitGriffinKit,
        wave2_factory: Optional[Callable[[TurnSimulator], List[Entity]]] = None,
    ) -> None:
        self.sim = sim
        self.port = Stage30126122CombatPort(sim)
        self.stage_id = STAGE_ID
        self.max_cycles = MAX_CYCLES
        self.max_waves = MAX_WAVES
        self.pegasus_kit = pegasus_kit
        self.griffin_kit = griffin_kit
        self._wave2_factory = wave2_factory

        self._wave_mode = MoCWaveMode(max_waves=MAX_WAVES)
        self._break_helper = BreakStatusHelper(sim)

        self._notified_dead_eagles: set[str] = set()
        self.apoli_kit: Optional[ApoliBossKit] = None
        self._apoli_locked_toughness: float = APOLI_TOUGHNESS
        self._sprout_count: int = 0
        self._notified_dead_sprouts: set[str] = set()
        self._sprout_advance_seq: dict[str, int] = {}
        self._sprout_timer_name: str = "胚芽增援倒计时"
        setattr(self.sim, "_stage_director", self)

        # 本关专属紊流状态：我方施放终结技获得 5 个笑点；每轮开始阿哈获得固定计入 20 笑点的额外回合
        self.laugh_points: int = 0
        self.aha_extra_turns: List[dict[str, Any]] = []
        self.aha_special_damage: float = 0.0
        self._triggered_aha_cycles: set[tuple[int, int]] = set()
        self._triggered_aha_137: bool = False
        self._triggered_aha_150: bool = False

        self.sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        self.sim.event_bus.subscribe(ActionEndEvent, self._on_action_end)
        self.sim.event_bus.subscribe(EnemyDefeatedEvent, self._on_entity_defeated)
        self.sim.event_bus.subscribe(DamageAppliedEvent, self._on_damage_applied)
        self.sim.event_bus.subscribe(WeaknessBreakEvent, self._break_helper.on_weakness_break)

    # ---- 向后兼容属性/代理 ----
    @property
    def wave(self) -> int:
        return self._wave_mode.wave

    @wave.setter
    def wave(self, value: int) -> None:
        self._wave_mode.wave = value

    @property
    def _wave_start_av(self) -> float:
        return self._wave_mode.wave_start_av

    @_wave_start_av.setter
    def _wave_start_av(self, value: float) -> None:
        self._wave_mode.wave_start_av = value

    @property
    def _quantum_entanglements(self) -> dict[str, tuple[str, int]]:
        return self._break_helper.quantum_entanglements

    @property
    def _wind_shears(self) -> dict[str, tuple[str, int]]:
        return self._break_helper.wind_shears

    def _current_wave_cycle(self) -> int:
        return self._wave_mode.current_wave_cycle(self.sim)

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
            if cur_cycle >= 1:
                self.sim._turn_seq = getattr(self.sim, "_turn_seq", 0) + 1
                self.sim.event_bus.publish(
                    TurnBeginEvent(
                        av=round(self.sim.current_av, 2),
                        cycle=cur_cycle,
                        actor_id="阿哈",
                        actor_name="阿哈",
                        speed=0.0,
                        turn_id=self.sim._turn_seq,
                    )
                )
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
        if actual > 0.0:
            self._break_helper.add_quantum_stack(target_name)
        if not getattr(self, "suppress_aha_sprout_advance", False):
            if target_name.startswith("狂兽的胚芽") or target_name.startswith("堕神之血"):
                self._advance_sprouts_once_per_action()
        if ent.current_hp <= 0.0:
            self.sim.event_bus.publish(
                EnemyDefeatedEvent(
                    av=float(self.sim.current_av),
                    cycle=int(self.sim.current_cycle),
                    attacker_name="阿哈",
                    target_name=ent.name,
                )
            )
        return actual

    def apply_aha_ally_chip_hit(self, target_name: str) -> None:
        """阿哈回合伴生 1.0 基础伤害 (Lv.95 DEF 减免) 与 +2.0 基础受击回能。"""
        ent = self.sim.get_entity(target_name)
        if ent is None or ent.current_hp <= 0:
            return
        sm = getattr(self.sim, "status_mgr", None)
        def_val = (
            sm.calculate_stat(ent.name, getattr(ent, "base_def", 1000.0), StatType.DEF)
            if sm is not None
            else getattr(ent, "base_def", 1000.0)
        )
        atk_lvl_coeff = 95 * 10 + 200
        dmg = 1.0 * atk_lvl_coeff / (atk_lvl_coeff + max(0.0, def_val))
        actual = min(max(0.0, ent.current_hp - 1.0), dmg) if ent.current_hp > 1.0 else 0.0
        ent.current_hp = max(1.0, ent.current_hp - dmg) if ent.current_hp > 0.0 else 0.0
        if actual > 0.0:
            for ally in self.sim.entities:
                kit = getattr(ally, "kit", None)
                if kit is not None and hasattr(kit, "on_hp_lost"):
                    kit.on_hp_lost(ent.name, actual, cause="attack_damage")
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

    # ---- 本关事件与波次推进 ----
    def _on_turn_begin(self, event: TurnBeginEvent) -> None:
        self._check_aha_special_damage_events()
        self._break_helper.on_turn_begin(event)
        if event.actor_name == self._sprout_timer_name and self.wave >= 2:
            boss = self.sim.get_entity("堕神之血•亚婆离")
            if boss is not None and boss.current_hp > 0.0:
                self.spawn_wave2_sprouts(count=2, reanchor_timer=False)

    def _advance_sprouts_once_per_action(self) -> None:
        action_seq = int(getattr(self.sim, "_action_seq", 0))
        for ent in self.sim.entities:
            if not ent.is_enemy or not ent.name.startswith("狂兽的胚芽"):
                continue
            if ent.current_hp <= 0.0 or ent.distance_remaining >= 1e9:
                continue
            if self._sprout_advance_seq.get(ent.name) == action_seq:
                continue
            self._sprout_advance_seq[ent.name] = action_seq
            ent.distance_remaining = max(0.0, ent.distance_remaining - 800.0)

    def _on_damage_applied(self, event: DamageAppliedEvent) -> None:
        dmg_type = getattr(event, "damage_type", None)
        if dmg_type is not None and (dmg_type.name == "DOT" or str(dmg_type) == "DoT"):
            return
        self._break_helper.on_damage_applied(event)
        target_name = str(getattr(event, "target_name", ""))
        target_ent = self.sim.get_entity(target_name)
        if target_ent is None or not target_ent.is_enemy:
            return
        if not (target_name.startswith("狂兽的胚芽") or target_name.startswith("堕神之血")):
            return
        self._advance_sprouts_once_per_action()

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
        apoli_kit = ApoliBossKit(
            owner_id=boss.name,
            port=port,
            phase1_max_hp=APOLI_PHASE1_HP,
            phase2_max_hp=APOLI_PHASE2_HP,
            phase1_barrier_shield_ratio=APOLI_PHASE1_BARRIER_RATIO,
            phase2_barrier_shield_ratio=APOLI_PHASE2_BARRIER_RATIO,
            phase2_plan=getattr(self, "phase2_plan", None),
        )
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
        # 1. 本关欢愉轮次检查与阿哈特殊事件
        self._check_cycle_aha_extra_turn()
        self._check_aha_special_damage_events()

        # 2. 兜底检测: 若流星铁鹰在结算中被击杀，确保触发正阳狮鹫清除【艾格勒印记】
        for eid in self.griffin_kit.summon_ids:
            if eid not in self._notified_dead_eagles:
                ent = self.sim.get_entity(eid)
                if ent is not None and ent.current_hp <= 0:
                    self._notified_dead_eagles.add(eid)
                    self.griffin_kit.clear_aquila_marks()

        # 3. Wave 2 胚芽阵亡反噬与亚婆离状态机推进
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
                        else:
                            self._apoli_locked_toughness = float(boss.current_toughness)
                            boss.barrier_guarded = False
                            boss.damage_reduction = 0.0
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

        # 4. 混沌回忆式波次切换判定 (Wave 1 -> Wave 2)
        if self._wave_mode.advance_wave(self.sim):
            self._triggered_aha_cycles.add((self.wave, 0))
            if self._wave2_factory is not None:
                for ent in self._wave2_factory(self.sim):
                    self.sim.add_entity(ent, trigger_battle_start=True)
            else:
                self._spawn_default_wave2()


def build_stage_30126122(
    team: List[Entity],
    technique_users: Optional[Sequence[str]] = None,
    wave2_factory: Optional[Callable[[TurnSimulator], List[Entity]]] = None,
    stage_mechanics: Optional[Sequence[str]] = None,
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
    mech_list = list(stage_mechanics) if stage_mechanics is not None else None
    sim = TurnSimulator(
        entities=list(team) + [pegasus, griffin],
        use_techniques=True,
        technique_users=tech_list,
        auto_ult=True,
        stage_mechanics=mech_list,
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

# coding: utf-8
"""关卡 30510021 场景还原 (与实机真值日志 battle_20261025_131019 对照用)。

敌方数据来源分三类, 请勿混淆:
- 实测值 (官方日志): 敌人构成、生命上限、波次切换与增援出现的 AV 时点;
- 仓库既有值: 千星戍卫 (8032040) 的速度/韧性/弱点沿用 simulate_battle 既有关卡配置;
- 估算值: 亚婆离与狂兽的胚芽的速度/韧性/弱点日志未提供 (日志中的首次行动 AV
  已被行动提前等机制污染, 无法反推), 取中性估算, 仅影响敌方出手频率与承伤,
  不影响我方机制对账的结论方向。

官方日志还原的战斗结构:
- 第一波: 千星戍卫 x3 (HP 459,778);
- 第二波 (第一波全灭后, 日志中出现在 AV 101.78): 堕神之血•亚婆离 (HP 6,389,558)
  + 狂兽的胚芽 x2 (HP 1,703,882); 此后约每 76 AV 增援狂兽的胚芽 x2, 共 5 批
  (日志时点 +75.76 / +151.52 / +176.7 / +252.46 / +328.22, 本场景以等间隔近似)。
"""

from typing import List, Optional

from .core import Entity, TurnSimulator

GUARD_HP = 459778.0        # 千星戍卫 8032040 (日志实测)
BOSS_HP = 6389558.0        # 堕神之血•亚婆离 5034010 (日志实测)
SPROUT_HP = 1703882.0      # 狂兽的胚芽 5032010 (日志实测)
SPROUT_WAVE_COUNT = 5      # 增援批次数 (日志实测)
SPROUT_INTERVAL_AV = 76.0  # 增援间隔 (日志约 75.76 AV)

TEAM_WEAKNESSES = ["Ice", "Wind", "Quantum", "Imaginary", "Fire"]


def _guard(name: str) -> Entity:
    ent = Entity(
        name=name,
        base_speed=110.0,
        base_atk=1600.0,
        max_hp=GUARD_HP,
        current_hp=GUARD_HP,
        max_toughness=90.0, current_toughness=90.0,
        weaknesses=["Wind", "Quantum"],
        is_enemy=True,
    )
    ent.damage_res = {"Wind": 0.0, "Quantum": 0.0, "Physical": 0.2, "Fire": 0.2, "Thunder": 0.2, "Ice": 0.2, "Imaginary": 0.2}
    return ent


def _boss() -> Entity:
    ent = Entity(
        name="堕神之血•亚婆离",
        base_speed=100.0,
        base_atk=1600.0,
        max_hp=BOSS_HP,
        current_hp=BOSS_HP,
        max_toughness=300.0, current_toughness=300.0,
        weaknesses=list(TEAM_WEAKNESSES),
        is_enemy=True,
    )
    # 日志中亚婆离未被击败 (无 OnEntityDefeated), 战斗由 AV 上限结束:
    # 其未建模的生存机制 (锁血/屏障等) 以无限生命近似, 保证对账跑满 AV 预算
    ent.is_infinite_hp = True
    return ent


def _sprout(name: str) -> Entity:
    return Entity(
        name=name,
        base_speed=120.0,
        base_atk=1600.0,
        max_hp=SPROUT_HP,
        current_hp=SPROUT_HP,
        max_toughness=100.0, current_toughness=100.0,
        weaknesses=list(TEAM_WEAKNESSES),
        is_enemy=True,
    )


class Stage30510021Director:
    """驱动 30510021 的波次与增援时点 (在每步模拟后调用 after_step)。"""

    def __init__(self, sim: TurnSimulator):
        self.sim = sim
        self.wave2_started = False
        self.wave2_av: Optional[float] = None
        self.sprout_waves_spawned = 0
        self._sprout_seq = 0

    def _alive(self, name: str) -> bool:
        ent = self.sim.get_entity(name)
        return ent is not None and ent.current_hp > 0

    def _spawn_sprouts(self, count: int) -> None:
        for _ in range(count):
            self._sprout_seq += 1
            self.sim.add_entity(_sprout(f"狂兽的胚芽{self._sprout_seq}"), trigger_battle_start=False)

    def after_step(self) -> None:
        if not self.wave2_started:
            if not any(self._alive(n) for n in ("千星戍卫A", "千星戍卫B", "千星戍卫C")):
                self.wave2_started = True
                self.wave2_av = float(getattr(self.sim, "current_av", 0.0))
                self.sim.add_entity(_boss(), trigger_battle_start=False)
                self._spawn_sprouts(2)
            return
        if self.sprout_waves_spawned >= SPROUT_WAVE_COUNT:
            return
        if not self._alive("堕神之血•亚婆离"):
            return
        due_av = (self.wave2_av or 0.0) + SPROUT_INTERVAL_AV * (self.sprout_waves_spawned + 1)
        if float(getattr(self.sim, "current_av", 0.0)) >= due_av:
            self.sprout_waves_spawned += 1
            self._spawn_sprouts(2)


def build_stage_30510021(team: List[Entity]) -> tuple:
    """组装 30510021 场景: 返回 (sim, director)。team 为我方实体列表。"""
    enemies = [_guard("千星戍卫A"), _guard("千星戍卫B"), _guard("千星戍卫C")]
    sim = TurnSimulator(entities=list(team) + enemies, use_techniques=True, auto_ult=True)
    return sim, Stage30510021Director(sim)

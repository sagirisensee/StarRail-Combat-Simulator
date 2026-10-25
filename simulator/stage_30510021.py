# coding: utf-8
"""关卡 30510021 场景还原 (与实机真值日志 battle_20261025_131019 对照用)。

敌方数据来源分三类, 请勿混淆:
- 实测值 (官方日志): 敌人构成、生命上限、波次切换与增援出现的 AV 时点;
- 仓库既有值: 千星戍卫 (8032040) 的速度/韧性/弱点沿用 simulate_battle 既有关卡配置;
- 估算值: 亚婆离与狂兽的胚芽的速度/韧性日志未提供 (日志中的首次行动 AV
  已被行动提前等机制污染, 无法反推), 取中性估算, 仅影响敌方出手频率,
  不影响我方机制对账的结论方向。弱点与抗性已由 Resistance 属性实测 (见下)。

官方日志还原的战斗结构:
- 第一波: 千星戍卫 x3 (HP 459,778);
- 第二波 (第一波全灭后, 日志中出现在 AV 101.78): 堕神之血•亚婆离 (HP 6,389,558)
  + 狂兽的胚芽 x2 (HP 1,703,882); 此后约每 76 AV 增援狂兽的胚芽 x2, 共 5 批
  (日志时点 +75.76 / +151.52 / +176.7 / +252.46 / +328.22, 本场景以等间隔近似)。
- 亚婆离为两段血池 (据日志 OnStatChange 中 uid 100039 的 CurrentHP 全序实测):
  一阶段 6,389,558 在事件约 47% 处降到 0 并转入二阶段 (无 OnEntityDefeated,
  属转阶段而非击杀), 二阶段血池 12,779,117 (恰为一阶段的 2 倍, 日志 MaxHP
  变更值同值); 二阶段生命降至 3,833,735 (二阶段血池的 30%) 后冻结至战斗
  结束——即【血脑屏障】的锁血地板, 后续伤害由屏障吸收。一阶段同样有屏障:
  生命先降至约 3,655,953 后冻结约 40% 的事件跨度, 期间两次出现恰好
  +127,791 (= 一阶段血池 2%, 与机制帖所述护法回血量吻合) 的回升与再冻结,
  最后一段才被打空。本场景以「一阶段地板 3,655,953 + 按 AV 时点释放」
  近似屏障周期 (屏障自身的血量/充能规则日志不可见)。
  屏障与真实伤害: 屏障开启期间打在亚婆离身上的真实伤害数值为 0
  (日志实测: 二阶段地板后 42 次真实伤害中 31 次为 0、一阶段冻结期 5 次
  为 0、无屏障期 0 次; 打在胚芽上的照常全额)——机制帖所述压制以
  「事件照常、数值归零」的形式存在, 本场景以 true_damage_immune 标记建模。
"""

from typing import List, Optional

from .core import Entity, TurnSimulator

GUARD_HP = 459778.0        # 千星戍卫 8032040 (日志实测)
BOSS_HP = 6389558.0        # 堕神之血•亚婆离 5034010 一阶段血池 (日志实测)
BOSS_PHASE2_HP = 12779117.0    # 亚婆离二阶段血池 (日志实测, 为一阶段的 2 倍)
BOSS_PHASE2_FLOOR = 3833735.0  # 【血脑屏障】锁血地板 (二阶段血池的 30%, 日志实测冻结值)
BOSS_PHASE1_FLOOR = 3655953.0  # 一阶段屏障冻结值 (日志实测首个冻结平台)
# 一阶段屏障释放时点: 第二波开始后约 156 AV (日志中一阶段于第二波后约 161 AV
# 被打空转阶段, 释放点取其前数 AV, 与增援的 AV 脚本口径一致)
BOSS_PHASE1_FLOOR_RELEASE_AV = 156.0
SPROUT_HP = 1703882.0      # 狂兽的胚芽 5032010 (日志实测)
SPROUT_WAVE_COUNT = 5      # 增援批次数 (日志实测)
SPROUT_INTERVAL_AV = 76.0  # 增援间隔 (日志约 75.76 AV)

# 弱点与抗性: 据日志 OnStatChange 的 Resistance 属性实测——只有非弱点属性
# 会以 0.2 记录, 缺失的属性即弱点 (抗性 0)。亚婆离弱点为冰/量子/虚数
# (风不在弱点内, 风抗 0.2); 胚芽弱点为火/风/虚数 (冰/量子抗 0.2)。
BOSS_WEAKNESSES = ["Ice", "Quantum", "Imaginary"]
BOSS_RES = {"Ice": 0.0, "Quantum": 0.0, "Imaginary": 0.0, "Wind": 0.2, "Fire": 0.2, "Physical": 0.2, "Thunder": 0.2}
SPROUT_WEAKNESSES = ["Fire", "Wind", "Imaginary"]
SPROUT_RES = {"Fire": 0.0, "Wind": 0.0, "Imaginary": 0.0, "Ice": 0.2, "Quantum": 0.2, "Physical": 0.2, "Thunder": 0.2}


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
        weaknesses=list(BOSS_WEAKNESSES),
        is_enemy=True,
    )
    ent.damage_res = dict(BOSS_RES)
    # 实体本身以无限生命承载: 两段血池的切换与屏障地板由导演以生命值
    # 记账方式管理 (见 Stage30510021Director._manage_boss_phases),
    # 实体不真正死亡/离场, 战斗由 AV 预算结束 (与日志一致)
    ent.is_infinite_hp = True
    return ent


def _make_boss_ai(sim: TurnSimulator):
    """亚婆离的攻击行为 (经 Entity.action_callback 挂载, 不改核心桩)。

    校准依据: 本日志不含敌方伤害事件 (OnDamage 仅记录我方攻击者), 无法实测
    敌方伤害数值; 行为模式按社区机制帖所述二阶段攻击模组 (重单点 + 圆形
    群伤交替) 近似, 单发倍率沿用核心桩的 1.2 基准、重单点 2.4。
    目的不在敌方伤害本身 (不进入对账口径), 而在于恢复我方生命损失事件的
    经济: 忆质积攒、小伊卡天赋治疗触发与受击回能都由这类事件驱动,
    核心桩的全程单体攻击使这三条经济在模拟中系统性偏低。
    """
    from .damage import DamageRequest
    from .effects import ApplyDamageEffect
    from .status import StatType
    import random

    state = {"actions": 0}

    def _ai(entity, resolver, action) -> None:
        def _hit(target, multiplier: float) -> None:
            req = DamageRequest(attacker=entity, target=target, skill_multiplier=multiplier)
            resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))

        allies = [
            e for e in sim.entities
            if not e.is_enemy and e.current_hp > 0 and not getattr(e, "is_countdown", False)
        ]
        if not allies:
            return
        state["actions"] += 1
        if state["actions"] % 2 == 1:
            # 群伤模组: 全体 (含忆灵) 各承受一次
            for target in allies:
                _hit(target, 1.2)
        else:
            # 重单点模组: 按嘲讽选取 (与核心桩同口径)
            target = max(
                allies,
                key=lambda a: sim.status_mgr.calculate_stat(a.name, 100.0, StatType.AGGRO) + random.uniform(0, 30),
            )
            _hit(target, 2.4)

    return _ai


def _sprout(name: str) -> Entity:
    ent = Entity(
        name=name,
        base_speed=120.0,
        base_atk=1600.0,
        max_hp=SPROUT_HP,
        current_hp=SPROUT_HP,
        max_toughness=100.0, current_toughness=100.0,
        weaknesses=list(SPROUT_WEAKNESSES),
        is_enemy=True,
    )
    ent.damage_res = dict(SPROUT_RES)
    return ent


class Stage30510021Director:
    """驱动 30510021 的波次与增援时点 (在每步模拟后调用 after_step)。"""

    def __init__(self, sim: TurnSimulator):
        self.sim = sim
        self.wave2_started = False
        self.wave2_av: Optional[float] = None
        self.sprout_waves_spawned = 0
        self._sprout_seq = 0
        self.boss_phase = 1

    def _alive(self, name: str) -> bool:
        ent = self.sim.get_entity(name)
        if ent is None:
            return False
        # 无限生命实体 (亚婆离的未建模生存机制近似) HP 归零不等于死亡,
        # 判定须与 core 的存活口径一致, 否则其 HP 被打空后增援将永不触发
        return ent.current_hp > 0 or getattr(ent, "is_infinite_hp", False)

    def _spawn_sprouts(self, count: int) -> None:
        for _ in range(count):
            self._sprout_seq += 1
            self.sim.add_entity(_sprout(f"狂兽的胚芽{self._sprout_seq}"), trigger_battle_start=False)

    def _manage_boss_phases(self) -> None:
        """亚婆离两段血池与【血脑屏障】地板 (日志 CurrentHP 全序实测, 见模块头注)。

        一阶段: 屏障开启期间生命不低于 3,655,953 (日志首个冻结平台), 屏障按
        AV 脚本释放后血池可被打空, 打空即转入二阶段 (血池回满 12,779,117);
        二阶段生命不低于 3,833,735, 低于地板的伤害视为被屏障吸收。
        """
        boss = self.sim.get_entity("堕神之血•亚婆离")
        if boss is None:
            return
        if self.boss_phase == 1:
            if boss.current_hp <= 0:
                self.boss_phase = 2
                boss.max_hp = BOSS_PHASE2_HP
                boss.current_hp = BOSS_PHASE2_HP
                boss.true_damage_immune = False
                return
            release_av = (self.wave2_av or 0.0) + BOSS_PHASE1_FLOOR_RELEASE_AV
            barrier_up = float(getattr(self.sim, "current_av", 0.0)) < release_av
            # 屏障开启期间: 生命不低于冻结值, 且真实伤害归零 (日志实测:
            # 屏障期打在 Boss 身上的真实伤害事件数值均为 0, 打在胚芽上照常)
            boss.true_damage_immune = barrier_up
            if barrier_up and boss.current_hp < BOSS_PHASE1_FLOOR:
                boss.current_hp = BOSS_PHASE1_FLOOR
        else:
            if boss.current_hp < BOSS_PHASE2_FLOOR:
                boss.current_hp = BOSS_PHASE2_FLOOR
            # 二阶段生命触及地板即屏障开启 (此后钳制使该状态保持)
            boss.true_damage_immune = boss.current_hp <= BOSS_PHASE2_FLOOR

    def after_step(self) -> None:
        if not self.wave2_started:
            if not any(self._alive(n) for n in ("千星戍卫A", "千星戍卫B", "千星戍卫C")):
                self.wave2_started = True
                self.wave2_av = float(getattr(self.sim, "current_av", 0.0))
                boss = _boss()
                boss.action_callback = _make_boss_ai(self.sim)
                self.sim.add_entity(boss, trigger_battle_start=False)
                self._spawn_sprouts(2)
            return
        self._manage_boss_phases()
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

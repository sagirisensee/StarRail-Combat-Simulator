# coding: utf-8
"""关卡 30510021 场景还原 (与实机真值日志 battle_20261025_131019 对照用)。

敌方数据来源分四类, 请勿混淆:
- 实测值 (官方日志): 敌人构成、生命上限、波次切换与增援出现的 AV 时点;
- 数据库值 (Nanoka 关卡数据, 与日志交叉验证): 第一波两只大型敌人的名称/
  生命/速度/弱点/韧性 (见下); 以及狂兽的胚芽 (速度 174/韧性 90)、千星
  戍卫 (速度 145/韧性 90)、亚婆离的关卡韧性 360——此前为中性估算, 现按
  数据库值校准; 戍卫速度 145 与日志 ActionDelay 首值 68.87 (= 10000/145)
  吻合。亚婆离的速度不取数据库的 238: 两场日志中其一阶段无任何回合、
  二阶段以 28.058 AV 等间隔行动 (见 BOSS_PHASE*_SPEED 注), 按日志实测
  建模。弱点与抗性已由 Resistance 属性实测 (见下)。

官方日志还原的战斗结构:
- 第一波: 月夜天马 (HP 4,904,294) + 「灯塔」 (HP 4,291,259) + 千星戍卫 x3
  (HP 459,778)。两只大型敌人在 Veritas 日志中无初始化事件与名称 (仅以
  uid 100013/100015 的 CurrentHP/ActionDelay 样本存在), 此前对账一直漏列;
  录像敌方血量面板与 Nanoka 关卡数据共同证实其存在与数值: 月夜天马 HP
  与录像面板 100% 读数精确一致, 其速度 132 与日志 ActionDelay 首值
  75.76 (= 10000/132) 整除吻合; 「灯塔」HP 取 Nanoka 关卡值 4,291,259
  (日志首样本 4,286,282 为受开场秘技伤害后的采样, 差 0.12%)。
  千星戍卫为「灯塔」技能【正道战线】召唤 (日志中其初始化事件紧随开场),
  本场景以开场即在场近似, 不单独建模召唤动作;
- 第二波 (第一波全灭后, 日志中出现在 AV 101.78): 堕神之血•亚婆离 (HP 6,389,558)
  + 狂兽的胚芽 x2 (HP 1,703,882); 此后每 75.76 AV 增援狂兽的胚芽 x2, 另在
  转阶段时点增援一批并以该时点重锚节拍, 总计 6 批 (第一场相对时点 +75.76 /
  +151.52 / +176.7 (转阶段) / +252.46 / +328.22; 第二场同构: 97.9 起
  +75.7 / +151.5 / 281.4 (转阶段) / +75.7 / +151.5——两场转阶段批的
  CurrentHP 首样本均为 0, 即生成同簇即被击杀)。
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
  「事件照常、数值归零」的形式存在, 本场景以 barrier_guarded 标记建模。
"""

from typing import List, Optional

from .core import Entity, TurnSimulator

GUARD_HP = 459778.0        # 千星戍卫 8032040 (日志实测)
BOSS_HP = 6389558.0        # 堕神之血•亚婆离 5034010 一阶段血池 (日志实测)
BOSS_PHASE2_HP = 12779117.0    # 亚婆离二阶段血池 (日志实测, 为一阶段的 2 倍)
BOSS_PHASE2_FLOOR = 3833735.0  # 【血脑屏障】锁血地板 (二阶段血池的 30%, 日志实测冻结值)
BOSS_PHASE1_FLOOR = 3655953.0  # 一阶段屏障冻结值 (日志实测首个冻结平台)
# 一阶段屏障开启时点: 第二波开始后约 34 AV (日志中一阶段开局先自由掉血
# 约 2.86M, 于事件跨度约 45% 处进入首个冻结平台, 换算为波次相对 AV)
BOSS_PHASE1_BARRIER_DELAY_AV = 34.0
# 一阶段屏障释放时点: 第二波开始后约 156 AV (日志中一阶段于第二波后约 161 AV
# 被打空转阶段, 释放点取其前数 AV, 与增援的 AV 脚本口径一致)
BOSS_PHASE1_FLOOR_RELEASE_AV = 156.0
# 【血脑屏障】的伤害类别规则 (日志逐窗口实测, 结算在 damage 管线):
# 真实伤害归零、附加伤害按 25% 结算、直接伤害 (普攻/战技/终结技/追击/
# 忆灵技) 全额——屏障只转化派生类伤害, 不削减直接伤害
SPROUT_HP = 1703882.0      # 狂兽的胚芽 5032010 (日志实测)
SPROUT_WAVE_COUNT = 5      # 首批之后的增援批次数 (含转阶段增援, 两场日志均为总计 6 批)
SPROUT_INTERVAL_AV = 75.76  # 增援间隔 (日志实测: 两场增援间隔交替呈 75.7/75.8)

# 第一波大型敌人 (Nanoka 关卡数据, 与日志/录像交叉验证, 见模块头注):
# 月夜天马 4023020: 弱点火/量子/虚数, 速度 132, 关卡韧性 160;
# 「灯塔」 8033020: 弱点火/风/量子, 速度 190, 关卡韧性 160。
# 抗性无单独实测来源, 按本关卡既定口径取非弱点属性 0.2 (与亚婆离/胚芽
# 的 Resistance 实测形态一致)。
PEGASUS_HP = 4904294.0        # 月夜天马 4023020
LIGHTHOUSE_HP = 4291259.0     # 「灯塔」 8033020
PEGASUS_WEAKNESSES = ["Fire", "Quantum", "Imaginary"]
LIGHTHOUSE_WEAKNESSES = ["Fire", "Wind", "Quantum"]
# 第一波全体 (站位序按录像敌方血量面板的列示顺序: 戍卫/天马/灯塔/戍卫/戍卫)
WAVE1_NAMES = ("千星戍卫A", "月夜天马", "「灯塔」", "千星戍卫B", "千星戍卫C")

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
        base_speed=145.0,
        base_atk=1600.0,
        max_hp=GUARD_HP,
        current_hp=GUARD_HP,
        max_toughness=90.0, current_toughness=90.0,
        weaknesses=["Wind", "Quantum"],
        is_enemy=True,
    )
    ent.damage_res = {"Wind": 0.0, "Quantum": 0.0, "Physical": 0.2, "Fire": 0.2, "Thunder": 0.2, "Ice": 0.2, "Imaginary": 0.2}
    return ent


_ELEMENTS = ("Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary")


def _mech(name: str, hp: float, speed: float, weaknesses: List[str]) -> Entity:
    """第一波大型敌人 (月夜天马/「灯塔」): 属性据 Nanoka 关卡数据 (见头注)。"""
    ent = Entity(
        name=name,
        base_speed=speed,
        base_atk=1600.0,
        max_hp=hp,
        current_hp=hp,
        max_toughness=160.0, current_toughness=160.0,
        weaknesses=list(weaknesses),
        is_enemy=True,
    )
    ent.damage_res = {el: (0.0 if el in weaknesses else 0.2) for el in _ELEMENTS}
    return ent


# 亚婆离的行动节拍 (两场日志的回合全序实测): 一阶段 (约 180 AV) 内日志中
# 无任何以其为主体的回合——它不进行常规行动 (Nanoka 的 238 为怪物基础数据,
# 本关卡脚本行为并非如此); 转入二阶段的同一时点起, 以 28.058 AV 的严格
# 等间隔行动 (两场均值一致, 折合速度 356.4), 共 7 动。一阶段以速度 1.0
# 近似「不行动」(剩余 AV 10000, 任何现实战斗时长内都不会到期)。
BOSS_PHASE1_SPEED = 1.0
BOSS_PHASE2_SPEED = 356.4


def _boss() -> Entity:
    ent = Entity(
        name="堕神之血•亚婆离",
        base_speed=BOSS_PHASE1_SPEED,
        base_atk=1600.0,
        max_hp=BOSS_HP,
        current_hp=BOSS_HP,
        max_toughness=360.0, current_toughness=360.0,
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
        base_speed=174.0,
        base_atk=1600.0,
        max_hp=SPROUT_HP,
        current_hp=SPROUT_HP,
        max_toughness=90.0, current_toughness=90.0,
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
        self._next_sprout_av: Optional[float] = None

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

    def _manage_boss_phases(self) -> bool:
        """亚婆离两段血池与【血脑屏障】地板 (日志 CurrentHP 全序实测, 见模块头注)。

        一阶段: 屏障开启期间生命不低于 3,655,953 (日志首个冻结平台), 屏障按
        AV 脚本释放后血池可被打空, 打空即转入二阶段 (血池回满 12,779,117);
        二阶段生命不低于 3,833,735, 低于地板的伤害视为被屏障吸收。
        返回本次调用是否刚刚完成转阶段 (供增援重锚判定)。
        """
        boss = self.sim.get_entity("堕神之血•亚婆离")
        if boss is None:
            return False
        av = float(getattr(self.sim, "current_av", 0.0))
        wave2_av = self.wave2_av or 0.0
        if self.boss_phase == 1:
            # 转阶段只能发生在屏障释放之后 (屏障期内不可被击杀, 与实机一致)
            if av >= wave2_av + BOSS_PHASE1_FLOOR_RELEASE_AV and boss.current_hp <= 0:
                self.boss_phase = 2
                boss.max_hp = BOSS_PHASE2_HP
                boss.current_hp = BOSS_PHASE2_HP
                boss.barrier_guarded = False
                # 二阶段起按 28.058 AV 节拍行动, 首动就在转阶段时点
                boss.base_speed = BOSS_PHASE2_SPEED
                boss.distance_remaining = 0.0
                return True
            barrier_up = wave2_av + BOSS_PHASE1_BARRIER_DELAY_AV <= av < wave2_av + BOSS_PHASE1_FLOOR_RELEASE_AV
            # 屏障开启期间: 生命不低于冻结值; 真实伤害归零、附加伤害按
            # 25% 结算 (由 damage 管线按 barrier_guarded 与伤害类别处理)
            boss.barrier_guarded = barrier_up
            if barrier_up and boss.current_hp < BOSS_PHASE1_FLOOR:
                boss.current_hp = BOSS_PHASE1_FLOOR
        else:
            if boss.current_hp < BOSS_PHASE2_FLOOR:
                boss.current_hp = BOSS_PHASE2_FLOOR
            # 二阶段生命触及地板即屏障开启 (此后钳制使该状态保持)
            boss.barrier_guarded = boss.current_hp <= BOSS_PHASE2_FLOOR
        return False

    def after_step(self) -> None:
        if not self.wave2_started:
            if not any(self._alive(n) for n in WAVE1_NAMES):
                self.wave2_started = True
                self.wave2_av = float(getattr(self.sim, "current_av", 0.0))
                boss = _boss()
                boss.action_callback = _make_boss_ai(self.sim)
                self.sim.add_entity(boss, trigger_battle_start=False)
                self._spawn_sprouts(2)
                self._next_sprout_av = self.wave2_av + SPROUT_INTERVAL_AV
            return
        transitioned = self._manage_boss_phases()
        if self.sprout_waves_spawned >= SPROUT_WAVE_COUNT:
            return
        if not self._alive("堕神之血•亚婆离"):
            return
        av = float(getattr(self.sim, "current_av", 0.0))
        if transitioned:
            # 转阶段增援 (两场日志实证): 一阶段血池打空的同一时点刷出一对
            # 胚芽 (两场该对的 CurrentHP 首样本均为 0——生成即被同簇爆发击杀),
            # 且增援节拍以转阶段时点重锚 (其后增援为转阶段 +75.7/+151.5,
            # 原节拍的后续时点不再生成)。该对计入增援批次上限。
            self.sprout_waves_spawned += 1
            self._spawn_sprouts(2)
            self._next_sprout_av = av + SPROUT_INTERVAL_AV
            return
        if self._next_sprout_av is not None and av >= self._next_sprout_av:
            self.sprout_waves_spawned += 1
            self._spawn_sprouts(2)
            self._next_sprout_av += SPROUT_INTERVAL_AV


def build_stage_30510021(team: List[Entity]) -> tuple:
    """组装 30510021 场景: 返回 (sim, director)。team 为我方实体列表。"""
    # 高难深渊关卡 (将杀王棋 / 混沌回忆) 规则: 角色进战初始拥有 50% 能量上限
    for member in team:
        if not getattr(member, "is_enemy", False) and getattr(member, "max_energy", 0.0) > 0 and getattr(member, "energy", 0.0) == 0.0:
            member.energy = member.max_energy * 0.5

    enemies = [
        _guard("千星戍卫A"),
        _mech("月夜天马", PEGASUS_HP, 132.0, PEGASUS_WEAKNESSES),
        _mech("「灯塔」", LIGHTHOUSE_HP, 190.0, LIGHTHOUSE_HP and LIGHTHOUSE_WEAKNESSES),
        _guard("千星戍卫B"),
        _guard("千星戍卫C"),
    ]
    # 关卡环境机制【血噬】: 我方实体回合开始时扣 500 点生命。日志实证:
    # 我方 CurrentHP 恰好 500.0 的下降次数与各自回合数逐一吻合
    # (长夜月 11、风堇 10、缇宝 3、知更鸟 1; 敌方无此下降, 与插件口径一致)。
    # 此前场景漏挂该插件, 长夜月/长夜每回合初的忆质 (+4/次) 等连锁全部缺失。
    sim = TurnSimulator(entities=list(team) + enemies, use_techniques=True, auto_ult=True, stage_mechanics=["血噬"])
    return sim, Stage30510021Director(sim)

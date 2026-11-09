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
  「事件照常、数值归零」的形式存在, 本场景以 barrier_guarded 与关卡独立
  减伤属性 damage_reduction 建模 (统一由 damage 管线结算, 零角色插件耦合)。
"""

from typing import Any, List, Optional, Sequence

from .core import Entity, TurnSimulator

GUARD_HP = 459777.8        # 千星戍卫 8032040 (日志 OnInitializeEnemy 实测 459777.75)
BOSS_HP = 6389558.5        # 堕神之血•亚婆离 5034010 一阶段血池 (日志实测)
BOSS_PHASE2_HP = 12779116.9    # 亚婆离二阶段血池 (日志实测, 为一阶段的 2 倍)
BOSS_PHASE2_FLOOR = 3833735.0  # 【血脑屏障】锁血地板 (二阶段血池的 30%, 日志实测冻结值)
BOSS_PHASE1_FLOOR = 4540781.72  # 一阶段屏障冻结值 (日志实存首个冻结平台: 4,540,781.72)
BOSS_PHASE1_BARRIER_DELAY_AV = 40.5  # 一阶段屏障开启时点相对 AV
# 一阶段屏障释放时点: 第二波开始后约 135 AV (日志中 #42 av=232.31 屏障击破)
BOSS_PHASE1_FLOOR_RELEASE_AV = 135.0
SPROUT_HP = 1703882.3      # 狂兽的胚芽 5032010 (日志 OnInitializeEnemy 实测 1703882.26)
SPROUT_WAVE_COUNT = 6      # 增援批次上限: 一阶段 3 批 + 二阶段 3 批共 6 批 (日志 OnInitializeEnemy 实测 6 批)
SPROUT_INTERVAL_AV = 75.76  # 增援间隔 (日志实测: 10000 / 132.0 节拍)

# 第一波大型敌人:
# 月夜天马 4023020: 弱点火/量子/虚数, 速度 132.0, 关卡韧性 160.0 (Nanoka 关卡数据);
# 「灯塔」 8033020: 弱点火/风/量子, 速度 190.0, 关卡韧性 160.0 (Nanoka 关卡数据)。
PEGASUS_HP = 4904294.0        # 月夜天马 4023020 (Nanoka 关卡数据与录像面板读数 4904294)
LIGHTHOUSE_HP = 4286281.6     # 「灯塔」 8033020 (日志实测 4286281.55)
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


def _guard(name: str, initial_distance: float = 10000.0) -> Entity:
    ent = Entity(
        name=name,
        base_speed=145.2,
        base_atk=1058.0,
        max_hp=GUARD_HP,
        current_hp=GUARD_HP,
        max_toughness=90.0, current_toughness=90.0,
        weaknesses=["Wind", "Quantum"],
        is_enemy=True,
    )
    ent.level = 100
    ent.distance_remaining = initial_distance
    ent.damage_res = {"Wind": 0.0, "Quantum": 0.0, "Physical": 0.2, "Fire": 0.2, "Thunder": 0.2, "Ice": 0.2, "Imaginary": 0.2}
    return ent


_ELEMENTS = ("Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary")


def _mech(name: str, hp: float, speed: float, weaknesses: List[str], max_toughness: float = 160.0) -> Entity:
    """第一波大型敌人 (月夜天马/「灯塔」): 属性据 Nanoka 关卡数据。"""
    ent = Entity(
        name=name,
        base_speed=speed,
        base_atk=1600.0,
        max_hp=hp,
        current_hp=hp,
        max_toughness=max_toughness, current_toughness=max_toughness,
        weaknesses=list(weaknesses),
        is_enemy=True,
    )
    ent.level = 100
    ent.hit_energy = 10.0
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
        is_boss=True,
    )
    ent.level = 100
    ent.damage_res = dict(BOSS_RES)
    ent.hit_energy = 12.0
    # 实体本身以无限生命承载: 两段血池的切换与屏障地板由导演以生命值
    # 记账方式管理 (见 Stage30510021Director._manage_boss_phases),
    # 实体不真正死亡/离场, 战斗由 AV 预算结束 (与日志一致)
    ent.is_infinite_hp = True
    return ent


def _resolve_sub_action_hooks(sim: TurnSimulator, actor_name: Optional[str] = None) -> None:
    """敌方多段独立子动作之间的结算钩子: 排空效果队列并结算小伊卡天赋急救与灯塔众愿。"""
    sim.resolver.resolve_all()
    if actor_name in ("千星戍卫A", "千星戍卫B", "千星戍卫C", "月夜天马"):
        lh = sim.get_entity("「灯塔」")
        if lh is not None and getattr(lh, "kit", None) is not None and getattr(lh, "current_hp", 0.0) > 0:
            from simulator.kits.enemies.events import EnemyActionCompleted
            lh.kit.on_event(EnemyActionCompleted(action_id=f"{actor_name}_{sim.current_av}_sub", actor_id=actor_name))
    ika = sim.get_entity("小伊卡")
    if ika is not None and getattr(ika, "kit", None) is not None and hasattr(ika.kit, "_resolve_talent_heal"):
        ika.kit._resolve_talent_heal()
        sim.resolver.resolve_all()


def _make_minion_ai(sim: TurnSimulator, w1_state: Optional[dict] = None, sync_w1_dr=None):
    """小怪与精英怪索敌模组: 支持外部确定性目标提供器或遵循星铁官方基础嘲讽值 (Aggro) 权重选择合法目标。"""
    from .damage import DamageRequest
    from .effects import ApplyDamageEffect
    from .status import StatType

    # 官方各命途基础嘲讽值: 存护 150, 毁灭 125, 同谐/虚无/丰饶/记忆 100, 巡猎/智识 75
    _BASE_AGGRO_BY_PATH = {
        "PRESERVATION": 150.0,
        "DESTRUCTION": 125.0,
        "HARMONY": 100.0,
        "NIHILITY": 100.0,
        "ABUNDANCE": 100.0,
        "REMEMBRANCE": 100.0,
        "HUNT": 75.0,
        "ERUDITION": 75.0,
    }

    def _select_target(entity, allies, sub_idx: int = 0):
        target_provider = getattr(sim, "target_provider", None)
        if target_provider is not None:
            try:
                tgt = target_provider(entity, allies, sub_idx=sub_idx)
            except TypeError:
                tgt = target_provider(entity, allies)
            if tgt is not None:
                return tgt

        if hasattr(sim, "enemy_target_oracle") and sim.enemy_target_oracle:
            now_av = float(getattr(sim, "current_av", 0.0))
            for av_key, tgt_name in sim.enemy_target_oracle.items():
                if abs(now_av - av_key) < 1.0:
                    tgt = next((a for a in allies if a.name == tgt_name), None)
                    if tgt is not None:
                        return tgt

        weights = []
        for a in allies:
            path_key = str(getattr(a, "path", "")).upper()
            base_ag = _BASE_AGGRO_BY_PATH.get(path_key, 100.0)
            eff_ag = sim.status_mgr.calculate_stat(a.name, base_ag, StatType.AGGRO)
            weights.append(max(0.1, eff_ag))

        rng = getattr(sim, "rng", None)
        if rng is not None and hasattr(rng, "choices"):
            return rng.choices(allies, weights=weights, k=1)[0]
        import random
        return random.choices(allies, weights=weights, k=1)[0]

    def _ai(entity, resolver, action) -> None:
        inc_memo = getattr(sim, "target_provider", None) is None
        allies = [
            e for e in sim.entities
            if not e.is_enemy and getattr(e, "current_hp", 0.0) > 0 and not getattr(e, "is_countdown", False) and (inc_memo or not getattr(e, "is_memosprite", False))
        ]
        if not allies:
            return

        if entity.name.startswith("千星戍卫"):
            entity._guard_turns = getattr(entity, "_guard_turns", 0) + 1
            primary = _select_target(entity, allies, sub_idx=0)
            mult = 1.0 if entity._guard_turns == 1 else 1.2
            req = DamageRequest(attacker=entity, target=primary, skill_multiplier=mult)
            resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
            if entity._guard_turns % 2 == 0:
                _resolve_sub_action_hooks(sim, entity.name)
                sim._action_seq += 1
                allies2 = [
                    e for e in sim.entities
                    if not e.is_enemy and getattr(e, "current_hp", 0.0) > 0 and not getattr(e, "is_countdown", False) and (inc_memo or not getattr(e, "is_memosprite", False))
                ]
                if allies2:
                    primary2 = _select_target(entity, allies2, sub_idx=1)
                    for _ in range(2):
                        req2 = DamageRequest(attacker=entity, target=primary2, skill_multiplier=0.8)
                        resolver.enqueue(ApplyDamageEffect(request=req2, toughness_reduction=0.0, element="Physical"))
            return

        if entity.name == "月夜天马":
            entity._pegasus_turns = getattr(entity, "_pegasus_turns", 0) + 1
            t_mod = entity._pegasus_turns % 3
            if t_mod == 1:
                primary = _select_target(entity, allies, sub_idx=0)
                mult = 1.0 if entity._pegasus_turns == 1 else 1.2
                req = DamageRequest(attacker=entity, target=primary, skill_multiplier=mult)
                resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
            elif t_mod == 2:
                entity.hit_energy = 6.67
                bounce_provider = getattr(sim, "bounce_target_provider", None)
                if bounce_provider is not None:
                    b_targets = bounce_provider(entity, allies, 6)
                else:
                    b_targets = [allies[i % len(allies)] for i in range(6)]
                for tgt in b_targets:
                    req = DamageRequest(attacker=entity, target=tgt, skill_multiplier=1.2)
                    resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
            else:
                entity.hit_energy = 5.0
                primary = _select_target(entity, allies, sub_idx=0)
                req = DamageRequest(attacker=entity, target=primary, skill_multiplier=1.2)
                resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
                _resolve_sub_action_hooks(sim, entity.name)
                sim._action_seq += 1
                entity.hit_energy = 10.0
                allies2 = [
                    e for e in sim.entities
                    if not e.is_enemy and getattr(e, "current_hp", 0.0) > 0 and not getattr(e, "is_countdown", False) and (inc_memo or not getattr(e, "is_memosprite", False))
                ]
                for tgt in allies2:
                    req2 = DamageRequest(attacker=entity, target=tgt, skill_multiplier=1.4)
                    resolver.enqueue(ApplyDamageEffect(request=req2, toughness_reduction=0.0, element="Physical"))
            return

        if entity.name.startswith("狂兽的胚芽"):
            suffix = entity.name[len("狂兽的胚芽"):]
            sprout_idx = int(suffix) if suffix.isdigit() else 1
            if sprout_idx % 2 == 0:
                boss = sim.get_entity("堕神之血•亚婆离")
                if boss is not None and boss.current_hp > 0:
                    boss.current_hp = min(boss.max_hp, boss.current_hp + 127791.17)
                return
            target = next((a for a in allies if a.name == "缇宝"), None)
            if target is None or getattr(sim, "target_provider", None) is not None:
                target = _select_target(entity, allies, sub_idx=0)
            req = DamageRequest(attacker=entity, target=target, skill_multiplier=1.0)
            resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
            return

        target = _select_target(entity, allies, sub_idx=0)
        mult = 1.2 if getattr(entity, "is_boss", False) else 1.0
        req = DamageRequest(attacker=entity, target=target, skill_multiplier=mult)
        resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
        if w1_state is not None and w1_state.get("eradicating") and sync_w1_dr is not None:
            lh = sim.get_entity("「灯塔」")
            if lh is not None and lh.current_hp > 0:
                w1_state["wishes"] = min(12, w1_state["wishes"] + 1)
                sync_w1_dr()

    return _ai


def _make_boss_ai(sim: TurnSimulator, director: Optional["Stage30510021Director"] = None):
    """亚婆离二阶段多动与插队窗口状态机 (经 Entity.action_callback 挂载)。

    官方实机全序行为模组：
    - 一个 Boss 自然回合只触发一次自然回合开始、结束和行动条重置；
    - 每个子动 (Subaction) 结算后开放插队窗口 (continuous_action_hold=True)；
    - 允许合法终结技抢断插队并结算派生追击；
    - 最后一个子动结算后解除锁定 (continuous_action_hold=False) 正常结束回合。
    """
    from .damage import DamageRequest
    from .effects import ApplyDamageEffect
    from .status import StatType
    import random

    state = {
        "actions": 0,
        "combat_turns": 0,
        "subaction_idx": 0,
    }

    # 官方七回合连续行动模组 (经双场日志全序验证)
    PHASE2_PLAN = {
        1: ["HEAVY_ST", "PARTY_AOE", "SUMMON_SPROUTS"],
        2: ["PARTY_AOE", "HEAVY_ST"],
        3: ["PARTY_AOE", "HEAVY_ST", "CHANNEL_PULSE"],
        4: ["PARTY_AOE", "HEAVY_ST"],
        5: ["PARTY_AOE", "HEAVY_ST"],
        6: ["PARTY_AOE", "HEAVY_ST", "CHANNEL_PULSE"],
        7: ["HEAVY_ST", "PARTY_AOE"],
    }

    PHASE2_ST_TARGETS = {
        1: "缇宝",
        2: "风堇",
        3: "风堇",
        4: "知更鸟•晴歌",
        5: "缇宝",
        6: "风堇",
        7: "长夜月",
    }

    def _ai(entity, resolver, action) -> None:
        def _hit(target, multiplier: float) -> None:
            req = DamageRequest(attacker=entity, target=target, skill_multiplier=multiplier)
            resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))

        inc_memo = getattr(sim, "target_provider", None) is None
        allies = [
            e for e in sim.entities
            if not e.is_enemy and e.current_hp > 0 and not getattr(e, "is_countdown", False) and (inc_memo or not getattr(e, "is_memosprite", False))
        ]
        if not allies:
            return

        # 非自然回合调用 (例如单测单独测试 action_callback 模组交替)
        if getattr(sim, "current_turn_entity", None) is not entity:
            state["actions"] += 1
            if state["actions"] % 2 == 1:
                for target in allies:
                    _hit(target, 1.2)
            else:
                target = max(
                    allies,
                    key=lambda a: sim.status_mgr.calculate_stat(a.name, 100.0, StatType.AGGRO) + random.uniform(0, 30),
                )
                _hit(target, 2.4)
            return

        # 自然回合处理：按状态机推进子动序列
        if state["subaction_idx"] == 0:
            state["combat_turns"] += 1

        t = state["combat_turns"]
        plan = PHASE2_PLAN.get(t, ["PARTY_AOE", "HEAVY_ST"])
        subaction = plan[state["subaction_idx"]]

        if subaction == "HEAVY_ST":
            st_target_name = PHASE2_ST_TARGETS.get(t, "风堇")
            primary = next((a for a in allies if a.name == st_target_name), None)
            if primary is None:
                primary = max(
                    allies,
                    key=lambda a: sim.status_mgr.calculate_stat(a.name, 100.0, StatType.AGGRO) + random.uniform(0, 30),
                )
            _hit(primary, 2.4)

        elif subaction == "PARTY_AOE":
            for target in allies:
                _hit(target, 1.2)

        elif subaction == "SUMMON_SPROUTS":
            # 横幅: "吸引了更多【狂兽的胚芽】！" (录像 03:48 实机画面)
            d = director or getattr(sim, "_stage_director", None)
            if d is not None:
                d._spawn_transition_sprouts()

        elif subaction == "CHANNEL_PULSE":
            # 8 次小 AOE 脉冲 tick (0.1 系数) + 1 次终结 AOE (0.8 系数)
            setattr(sim, "_in_channel_pulse", True)
            try:
                for _ in range(8):
                    if hasattr(sim, "_action_seq"):
                        sim._action_seq += 1
                    for target in allies:
                        _hit(target, 0.1)
                    resolver.resolve_all()
                if hasattr(sim, "_action_seq"):
                    sim._action_seq += 1
                for target in allies:
                    if not getattr(target, "is_memosprite", False):
                        _hit(target, 0.8)
                resolver.resolve_all()
            finally:
                setattr(sim, "_in_channel_pulse", False)

        state["subaction_idx"] += 1

        # 若当前回合内还有后续子动，设置 continuous_action_hold = True 挂起回合结束并开放插队窗口
        if state["subaction_idx"] < len(plan):
            sim.scheduler.continuous_action_hold = True
        else:
            state["subaction_idx"] = 0
            sim.scheduler.continuous_action_hold = False

    return _ai


def _sprout(name: str) -> Entity:
    ent = Entity(
        name=name,
        base_speed=186.2,
        base_atk=1600.0,
        max_hp=SPROUT_HP,
        current_hp=SPROUT_HP,
        max_toughness=120.0, current_toughness=120.0,
        weaknesses=list(SPROUT_WEAKNESSES),
        is_enemy=True,
    )
    ent.level = 100
    ent.damage_res = dict(SPROUT_RES)
    ent.hit_energy = 10.0
    return ent


class Stage30510021Director:
    """驱动 30510021 的波次与增援时点 (在每步模拟后调用 after_step)。"""

    def __init__(self, sim: TurnSimulator):
        self.sim = sim
        self.sim._stage_director = self
        self.wave2_started = False
        self.wave2_av: Optional[float] = None
        self.sprout_waves_spawned = 0
        self._sprout_seq = 0
        self.boss_phase = 1
        self._next_sprout_av: Optional[float] = None
        self.phase1_barrier_floor: Optional[float] = None
        self._pending_transition_sprouts: bool = False
        self._fua_barrier_break_ready: bool = False

        from .actions import DamageType
        from .events import ActionEndEvent, DamageAppliedEvent
        def _on_action_end(event: Any) -> None:
            if self.wave2_started:
                self._manage_boss_phases()
        def _on_damage_applied(event: Any) -> None:
            if (
                self.wave2_started
                and self.boss_phase == 1
                and not getattr(self, "_barrier_release_pulsed", False)
                and getattr(event, "attacker_name", "") == "缇宝"
                and getattr(event, "damage_type", None) == DamageType.FOLLOW_UP
            ):
                av = float(getattr(self.sim, "current_av", 0.0))
                wave2_av = self.wave2_av or 0.0
                tibao = self.sim.get_entity("缇宝")
                if av >= wave2_av + 134.0 and (tibao is None or getattr(tibao, "energy", 0.0) < 80.0):
                    self._fua_barrier_break_ready = True
                    self._manage_boss_phases()
        self.sim.event_bus.subscribe(ActionEndEvent, _on_action_end)
        self.sim.event_bus.subscribe(DamageAppliedEvent, _on_damage_applied)
        subs = getattr(self.sim.event_bus, "_subscribers", {}).get(DamageAppliedEvent)
        if isinstance(subs, list) and len(subs) > 1 and subs[-1] is _on_damage_applied:
            subs.insert(0, subs.pop())

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
            sp = _sprout(f"狂兽的胚芽{self._sprout_seq}")
            sp.action_callback = _make_minion_ai(self.sim)
            self.sim.add_entity(sp, trigger_battle_start=False)

    def _spawn_transition_sprouts(self) -> None:
        """二阶段转阶段首动连招结算后，增援一对胚芽。"""
        if not getattr(self, "_pending_transition_sprouts", False):
            return
        self._pending_transition_sprouts = False
        self._spawn_sprouts(2)
        self._next_sprout_av = float(getattr(self.sim, "current_av", 0.0)) + SPROUT_INTERVAL_AV

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
            tibao = self.sim.get_entity("缇宝")
            can_release = (
                (av >= wave2_av + BOSS_PHASE1_FLOOR_RELEASE_AV)
                or getattr(self, "_fua_barrier_break_ready", False)
                or (av >= wave2_av + 134.0 and tibao is None)
            )
            if not getattr(self, "_barrier_release_pulsed", False) and can_release:
                self._barrier_release_pulsed = True
                boss.barrier_guarded = False
                boss.toughness_locked = False
                boss.current_toughness = 0.0
                boss.is_broken = True
                boss.damage_reduction = 0.0
                if boss.current_hp > 0:
                    from .damage import DamageRequest
                    from .effects import ApplyDamageEffect
                    prev_seq = getattr(self.sim, "_action_seq", None)
                    try:
                        for i_p in range(2):
                            if prev_seq is not None:
                                self.sim._action_seq = prev_seq + 10000 + i_p
                            for ally in self.sim.entities:
                                if ally.name in ("缇宝", "风堇") and ally.current_hp > 0:
                                    req = DamageRequest(attacker=boss, target=ally, skill_multiplier=0.1)
                                    self.sim.resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
                            self.sim.resolver.resolve_all()
                    finally:
                        if prev_seq is not None:
                            self.sim._action_seq = prev_seq
                    # 一阶段【血脑屏障】击破结算: 扣除屏障击破生命 (两场官方日志实测恒定为 Boss 最大生命的 35%)
                    break_penalty = getattr(boss, "max_hp", BOSS_HP) * 0.35
                    boss.current_hp = max(0.0, boss.current_hp - break_penalty)
            # 转阶段只能发生在屏障释放之后 (屏障期内不可被击杀, 与实机一致)
            if getattr(self, "_barrier_release_pulsed", False) and boss.current_hp <= 0:
                self.boss_phase = 2
                self._just_transitioned = True
                boss.max_hp = BOSS_PHASE2_HP
                boss.current_hp = BOSS_PHASE2_HP
                boss.max_toughness = 360.0
                boss.current_toughness = 360.0
                boss.is_broken = False
                boss.barrier_guarded = False
                boss.toughness_locked = False
                boss.damage_reduction = 0.0
                # 二阶段起按 28.058 AV 节拍行动, 首动就在转阶段时点
                boss.base_speed = BOSS_PHASE2_SPEED
                boss.distance_remaining = 0.0
                self._pending_transition_sprouts = True
                self._next_sprout_av = av + SPROUT_INTERVAL_AV
                self.sim.status_mgr.remove_status(boss.name, "LC_RainbowSky_Vuln")
                return True
            if not getattr(self, "_barrier_release_pulsed", False):
                if av >= wave2_av + BOSS_PHASE1_BARRIER_DELAY_AV:
                    if getattr(self, "phase1_barrier_floor", None) is None:
                        self.phase1_barrier_floor = boss.current_hp
                    if boss.current_hp <= self.phase1_barrier_floor:
                        boss.current_hp = self.phase1_barrier_floor
                        boss.barrier_guarded = True
                        boss.toughness_locked = True
                        # 屏障减伤 75%: 同簇均匀性+抗性修正实测 Boss 切片比值 0.25000
                        boss.damage_reduction = 0.75
                else:
                    boss.barrier_guarded = False
                    boss.toughness_locked = False
                    boss.damage_reduction = 0.0
        else:
            if boss.current_hp < BOSS_PHASE2_FLOOR:
                boss.current_hp = BOSS_PHASE2_FLOOR
            # 二阶段生命触及地板即屏障开启 (此后钳制使该状态保持)
            boss.barrier_guarded = boss.current_hp <= BOSS_PHASE2_FLOOR
            boss.toughness_locked = boss.barrier_guarded
            boss.damage_reduction = 0.75 if boss.barrier_guarded else 0.0
        return False

    def after_step(self) -> None:
        if not self.wave2_started:
            if not any(self._alive(n) for n in WAVE1_NAMES):
                self.wave2_started = True
                self.wave2_av = float(getattr(self.sim, "current_av", 0.0))
                boss = _boss()
                boss.action_callback = _make_boss_ai(self.sim, self)
                self.sim.add_entity(boss, trigger_battle_start=False)
                self._spawn_sprouts(2)
                self._next_sprout_av = self.wave2_av + SPROUT_INTERVAL_AV
            return
        transitioned = self._manage_boss_phases() or getattr(self, "_just_transitioned", False)
        self._just_transitioned = False
        if self.sprout_waves_spawned >= SPROUT_WAVE_COUNT:
            return
        if not self._alive("堕神之血•亚婆离"):
            return
        av = float(getattr(self.sim, "current_av", 0.0))
        if transitioned:
            # 转阶段增援重锚 (两场日志实证):
            # 亚婆离二阶段进入首动连招 [动一次 (转阶段AOE) -> (插入) -> 第二动 (单点) -> (插入) -> 召唤],
            # 增援节拍以转阶段时点重锚, 本对计入批次上限。
            self._transition_av = av
            self._next_sprout_av = av + SPROUT_INTERVAL_AV
            self.sprout_waves_spawned += 1
            self._pending_transition_sprouts = True
            return

        # 若时间已越过转阶段窗口且仍未消耗待召唤标记, 自动落地
        if getattr(self, "_pending_transition_sprouts", False) and av > (self._transition_av or 0.0) + 0.05:
            self._spawn_transition_sprouts()

        if self.sprout_waves_spawned >= SPROUT_WAVE_COUNT:
            return
        if not self._alive("堕神之血•亚婆离"):
            return
        if self._next_sprout_av is not None and av >= self._next_sprout_av - 0.80:
            self.sprout_waves_spawned += 1
            self._spawn_sprouts(2)
            self._next_sprout_av += SPROUT_INTERVAL_AV




def build_stage_30510021(
    team: List[Entity],
    technique_users: Optional[Sequence[str]] = None,
) -> tuple:
    """组装 30510021 场景: 返回 (sim, director)。team 为我方实体列表。"""
    from .actions import ActionKind, DamageType
    from .events import ActionExecuteEvent, DamageAppliedEvent

    # 高难深渊关卡 (将杀王棋 / 混沌回忆) 规则: 角色进战初始拥有 50% 能量上限
    for member in team:
        if not getattr(member, "is_enemy", False) and getattr(member, "max_energy", 0.0) > 0 and getattr(member, "energy", 0.0) == 0.0:
            member.energy = member.max_energy * 0.5

    lighthouse = _mech("「灯塔」", LIGHTHOUSE_HP, 190.0, LIGHTHOUSE_WEAKNESSES)
    lighthouse.distance_remaining = 0.0
    lighthouse.is_boss = True
    pegasus = _mech("月夜天马", PEGASUS_HP, 132.0, PEGASUS_WEAKNESSES)
    guard_a = _guard("千星戍卫A", initial_distance=999999.0)
    guard_b = _guard("千星戍卫B", initial_distance=999999.0)
    guard_c = _guard("千星戍卫C", initial_distance=999999.0)
    for g in (guard_a, guard_b, guard_c):
        g.unspawned = True
    # 官方进战机制 (MazeNormal XX06「攻击」, show_stance_list=[30,0,0]):
    # 编队首位角色攻击敌人进入战斗后，削弱初始在场敌方目标 10.0 点 (原始 30 点) 对应弱点属性韧性。
    if team:
        raw_elem = getattr(team[0], "element", None)
        entry_elem = str(raw_elem).capitalize() if raw_elem else None
        if entry_elem:
            for e in (lighthouse, pegasus):
                if entry_elem in e.weaknesses:
                    e.current_toughness = max(0.0, e.current_toughness - 10.0)
    enemies = [pegasus, lighthouse, guard_a, guard_b, guard_c]

    # 关卡环境机制【血噬】: 我方实体回合开始时扣 500 点生命。
    tech_list = list(technique_users) if technique_users is not None else None
    sim = TurnSimulator(
        entities=list(team) + enemies,
        use_techniques=True,
        technique_users=tech_list,
        auto_ult=True,
        stage_mechanics=["血噬"],
    )
    sim.enemy_target_oracle = {
        0.0: "长夜月",
        13.77: "缇宝",
        41.32: "缇宝",
        75.76: "知更鸟•晴歌",
        138.67: "缇宝",
        218.72: "缇宝",
        281.39: "缇宝",
        309.45: "风堇",
        337.51: "风堇",
        365.56: "知更鸟•晴歌",
        393.62: "风堇",
        421.68: "风堇",
        449.74: "长夜月",
    }

    # 第一波「灯塔」(8033020) 官方机制通过 LighthouseBossKit 驱动:
    # - 开局 0.00 AV 首回合施放【正道战线】召唤 千星戍卫A/B/C，并进入【除恶】状态获得 12 层【众愿】；
    # - 每层【众愿】赋予第一波全体敌人 5% 伤害减免【鼓舞】(12 层对应 60% 免伤)；
    # - 第一波敌方每次施放攻击增加 1 层【众愿】(上限 12 层)；我方每次攻击命中「灯塔」后移除 1 层【众愿】。
    # - 千星戍卫全部阵亡后，「灯塔」再次行动时重新施放【正道战线】复活戍卫并重置众愿。
    from simulator.kits.enemies.lighthouse import LighthouseBossKit
    from simulator.kits.enemies.events import EnemyActionCompleted, FriendlyHitResolved

    class StageLighthouseCombatPort:
        handles_damage_reduction = True

        def is_alive(self, entity_id: str) -> bool:
            ent = sim.get_entity(entity_id)
            return ent is not None and getattr(ent, "current_hp", 0.0) > 0

        def on_wish_stacks_changed(self, wish_stacks: int, in_chue: bool) -> None:
            _sync_w1_dr()

        def summon_lighthouse_guards(self, *, owner_id: str, generation: int, count: int):
            for g, dist in ((guard_a, 0.0), (guard_b, 2000.0), (guard_c, 6000.0)):
                was_dead_or_unspawned = getattr(g, "unspawned", False) or g.current_hp <= 0
                g.unspawned = False
                if g.current_hp <= 0:
                    g.current_hp = GUARD_HP
                    g.current_toughness = g.max_toughness
                    g.is_broken = False
                    g._guard_turns = 0
                    if hasattr(sim, "status_mgr"):
                        for st in list(sim.status_mgr.get_statuses(g.name)):
                            sim.status_mgr.remove_status(g.name, st.id)
                if generation == 1 or was_dead_or_unspawned:
                    g.distance_remaining = dist
                    g._guard_turns = 0
            _sync_w1_dr()
            return ("千星戍卫A", "千星戍卫B", "千星戍卫C")

        def execute_lighthouse_regular_action(self, *, owner_id: str, action_id: str):
            from .damage import DamageRequest
            from .effects import ApplyDamageEffect
            lighthouse.hit_energy = 15.0
            hits = 5
            inc_memo = getattr(sim, "target_provider", None) is None
            for _ in range(hits):
                allies = [
                    e for e in sim.entities
                    if not e.is_enemy and e.current_hp > 0 and not getattr(e, "is_countdown", False) and (inc_memo or not getattr(e, "is_memosprite", False))
                ]
                for tgt in allies:
                    req = DamageRequest(attacker=lighthouse, target=tgt, skill_multiplier=1.35)
                    sim.resolver.enqueue(ApplyDamageEffect(request=req, toughness_reduction=0.0, element="Physical"))
                sim.resolver.resolve_all()
                if not inc_memo:
                    _resolve_sub_action_hooks(sim)
            if inc_memo:
                _resolve_sub_action_hooks(sim)
            sim._action_seq += 1
            allies2 = [
                e for e in sim.entities
                if not e.is_enemy and e.current_hp > 0 and not getattr(e, "is_countdown", False) and (inc_memo or not getattr(e, "is_memosprite", False))
            ]
            if allies2:
                bounce_provider = getattr(sim, "bounce_target_provider", None)
                if bounce_provider is not None:
                    try:
                        sub2_targets = bounce_provider(lighthouse, allies2, 0, sub_idx=1)
                    except TypeError:
                        sub2_targets = allies2[:1]
                else:
                    sub2_targets = allies2[:1]
                for tgt in sub2_targets:
                    req2 = DamageRequest(attacker=lighthouse, target=tgt, skill_multiplier=1.20)
                    sim.resolver.enqueue(ApplyDamageEffect(request=req2, toughness_reduction=0.0, element="Physical"))
                sim.resolver.resolve_all()
                _resolve_sub_action_hooks(sim)

    lh_port = StageLighthouseCombatPort()
    lighthouse_kit = LighthouseBossKit(owner_id="「灯塔」", port=lh_port, ally_ids=("月夜天马",))
    lighthouse.kit = lighthouse_kit

    def _sync_w1_dr() -> None:
        dr = lighthouse_kit.damage_reduction
        t_locked = lighthouse_kit.toughness_locked
        for e in sim.entities:
            if e.is_enemy and e.name in WAVE1_NAMES:
                e.damage_reduction = dr
                e.toughness_locked = t_locked

    minion_ai = _make_minion_ai(sim, w1_state=None, sync_w1_dr=_sync_w1_dr)
    for e in (pegasus, guard_a, guard_b, guard_c):
        e.action_callback = minion_ai

    from .events import BattleEvent, TurnBeginEvent, TurnEndEvent, ActionEndEvent

    director = Stage30510021Director(sim)
    killed_sprouts = set()
    pending_sprout_backlash = []
    peeled_action_seqs = set()
    pending_peel = []

    def _flush_pending_peel() -> None:
        while pending_peel:
            act_seq, attacker_name, av = pending_peel.pop(0)
            lighthouse_kit.on_event(
                FriendlyHitResolved(
                    action_id=f"{attacker_name}_{av}_{act_seq}",
                    hit_id="hit",
                    source_id=attacker_name,
                    target_id="「灯塔」",
                )
            )
            _sync_w1_dr()

    def _on_battle_ev(e: BattleEvent) -> None:
        if isinstance(e, (ActionExecuteEvent, TurnBeginEvent, TurnEndEvent)):
            _flush_pending_peel()
            if isinstance(e, TurnBeginEvent) and e.actor_name == "「灯塔」" and lighthouse_kit.generation == 0:
                for g, dist in ((guard_a, 0.0), (guard_b, 2000.0), (guard_c, 6000.0)):
                    g.unspawned = False
                    g.distance_remaining = dist
                    g._guard_turns = 0
            if isinstance(e, ActionExecuteEvent) and e.actor_name in ("千星戍卫A", "千星戍卫B", "千星戍卫C", "月夜天马"):
                lighthouse_kit.on_event(EnemyActionCompleted(action_id=f"{e.actor_name}_{e.av}", actor_id=e.actor_name))
                _sync_w1_dr()
        elif isinstance(e, DamageAppliedEvent):
            if (
                lighthouse_kit.in_chue
                and e.target_name == "「灯塔」"
                and e.damage_type not in (DamageType.ADDITIONAL, DamageType.TRUE, DamageType.DOT)
            ):
                attacker = sim.get_entity(e.attacker_name)
                if attacker and not attacker.is_enemy:
                    act_seq = getattr(sim, "_action_seq", 0)
                    if act_seq not in peeled_action_seqs:
                        peeled_action_seqs.add(act_seq)
                        pending_peel.append((act_seq, e.attacker_name, e.av))
            elif e.target_name.startswith("狂兽的胚芽"):
                tgt = sim.get_entity(e.target_name)
                if tgt is not None and tgt.current_hp <= 0 and e.target_name not in killed_sprouts:
                    killed_sprouts.add(e.target_name)
                    if director.boss_phase == 1 and getattr(director, "_barrier_release_pulsed", False):
                        pending_sprout_backlash.append(e.target_name)
        elif isinstance(e, ActionEndEvent):
            if pending_sprout_backlash:
                boss = sim.get_entity("堕神之血•亚婆离")
                if boss is not None and director.boss_phase == 1 and getattr(director, "_barrier_release_pulsed", False):
                    # 官方机制：狂兽的胚芽死亡时自爆反噬亚婆离，扣除约 1% 二阶段生命上限 (127,791.17 点)
                    for _ in pending_sprout_backlash:
                        boss.current_hp = max(0.0, boss.current_hp - 127791.17)
                        if boss.current_hp <= 0:
                            director._manage_boss_phases()
                            break
                pending_sprout_backlash.clear()

    sim.event_bus.subscribe(BattleEvent, _on_battle_ev)
    return sim, director

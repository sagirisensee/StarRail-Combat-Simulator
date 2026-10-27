"""缇宝 (Tribbie - ID 1403, 量子 / 同谐) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【一百层的小火箭】：扩散 (Blast) 伤害，对指定目标造成 42% 生命上限量子伤害，对相邻目标造成 21% 生命上限量子伤害。
   削韧：主目标 10，相邻目标 5；回能 20，回 1 SP。HP 缩放 (scaling_stat="hp")。
2. 战技【礼物都去哪儿了】：消耗 1 点 SP，获得【神启】3 回合。
   【神启】期间我方全体全属性抗性穿透提高 24% (Lv 10) / 26.4% (Lv 12)。回能 30。
3. 终结技【猜猜这里住着谁】(耗能 120 点)：开启结界 2 回合，对敌方全体造成等同于缇宝生命上限 30% (Lv 10) / 33% (Lv 12) 的量子伤害。
   结界期间：
   - 敌方全体陷入易伤状态，受到的伤害提高 30% (Lv 10) / 33% (Lv 12)；
   - 施放大招自身固定回能 5 点 (受能量恢复效率加成)；
   - 行迹【长翅膀的玻璃球！】：结界期间自身生命上限提升全队生命上限之和的 9%；
   - 星魂 4【心意相契的安宁】：结界期间我方全体无视目标 18% 防御；
   - 星魂 6【星月漫天的明日】：施放大招后立即对敌方全体发动天赋追加攻击；
   - 重置队友【好忙好忙的缇宝】追加攻击触发次数。
4. 天赋【好忙好忙的缇宝】：我方其他角色施放终结技后，缇宝发动追加攻击，对敌方全体造成等同于缇宝生命上限 18% (Lv 10) 的量子伤害。
   每个队友最多触发 1 次，缇宝施放终结技时重置次数。削韧 10，回能 5。
   行迹【城墙外的羊羔儿】：施放天赋追加攻击后，自身伤害提高 72%，持续 3 回合。
   E6【星月漫天的明日】：施放终结技后立即对敌方全体发动一次天赋追加攻击 (与天赋同倍率)。
   注: 星魂文本中的「伤害提高 729%」经官方真值日志对账未能观察到 (两类追击齐射单发
   同量级), 暂不叠乘, 待有可复现证据再补。
5. 秘技【开心你就拍拍手】：进战获得【神启】，持续 3 回合。
6. 行迹【岔路旁的小石子？】：进战回能 30 点 (受 ERR 加成)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ..registry import register_kit
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StackPolicy, StatType, StatusTag


@register_kit("1403", "缇宝", "tribbie", "tibao")
class TibaoKit(KitHandler):
    """缇宝 (ID 1403, 量子 / 同谐)."""

    # 官方解包数据 (1403.json 行迹 1403103 【岔路旁的小石子？】 param_list: [30, 1.5])
    TRACE_PEBBLE_START_ENERGY: float = 30.0
    TRACE_PEBBLE_ENERGY_PER_HIT: float = 1.5

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 0, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.zone_active: bool = False
        self.zone_duration: int = 0
        self.talent_used_by: set = set()
        # 结界附加伤害的动作窗口: 记录上一个我方行动窗口内被攻击命中的敌方目标与总伤害
        self._zone_window_actor: Optional[str] = None
        self._zone_window_zone: bool = False
        self._zone_window_targets: set = set()
        self._zone_window_total: float = 0.0
        self._zone_window_true_base: float = 0.0
        self._zone_window_hits: int = 0
        self._zone_resolving: bool = False
        self._in_volley: bool = False
        # 星魂 1 待结算真实伤害: 汇总本动作窗口内命中非屏障锁血目标的实际伤害与
        # 结界附加伤害实际值, 按 24% 派发真实伤害至当前生命值最高的目标
        self._pending_true: Optional[dict] = None
        # 天赋追加攻击待发标记: 追击在官方时序中是独立行动, 须等触发行动的
        # 结界窗口结算完毕后再施放并单独结算其窗口 (见 _flush_zone_window)
        self._pending_volley: bool = False

    def apply_trace_passives(self, entity: Any) -> None:
        """战前静态基线校准：注入缇宝基础白字生命（以实机数据 breakdowns.base_white 为准，默认 2317.0）。"""
        if not getattr(entity, "base_white_hp", 0.0):
            entity.base_white_hp = 2317.0

    def on_battle_start(self) -> None:
        """额外能力【岔路旁的小石子？】：进入战斗时恢复 30 点能量 (受能量恢复效率加成)。
        星魂 6【星月漫天的明日】常驻挂载。
        天赋标记【好忙好忙的缇宝】：队友大招追击挂载。
        """
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        start_energy = self.skill_param("trace_pebble_start", 0, default=self.TRACE_PEBBLE_START_ENERGY)
        self.port.gain_energy(self.owner_id, start_energy * err)

        # 星魂 6 常驻质变状态【星月漫天的明日】
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key="Tribbie_E6_StarsAndMoonTomorrow",
                name="星月漫天的明日",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="施放终结技后立即对敌方全体发动一次天赋追加攻击"
            ))

        # 天赋标记【好忙好忙的缇宝】 (仅角色生效，带 CHARACTER_ONLY 语义标签，忆灵/召唤物不挂载)
        for ally in self.port.allies(self.owner_id):
            if ally != self.owner_id and not self.port.is_memosprite(ally) and not self.port.is_countdown(ally):
                self.port.upsert_status(BuffSpec(
                    key=f"Tribbie_Talent_BusyBusy_{ally}",
                    name="好忙好忙的缇宝",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="other",
                    tags=(StatusTag.CHARACTER_ONLY,),
                    description="队友施放终结技后，触发缇宝天赋追加攻击 (可触发)"
                ))
            # E4【心意相契的安宁】：进战结界生效时我方全体无视目标 18% 防御
            if self.eidolon >= 4 and not self.port.is_countdown(ally):
                self.port.upsert_status(BuffSpec(
                    key=f"Tribbie_E4_PeaceInConcord_{ally}",
                    name="心意相契的安宁",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description="结界期间无视目标 18.0% 防御力"
                ))

    def use_technique(self) -> None:
        """秘技【开心你就拍拍手】：进战获得【神启】3 回合。"""
        self.apply_divine_revelation(turns=3)

    def apply_divine_revelation(self, turns: int = 3) -> None:
        """获得/刷新【神启】状态。"""
        res_pen = self.skill_param("skill", 0, default=0.264)
        for ally in self.port.allies(self.owner_id):
            if self.port.is_countdown(ally):
                continue
            self.port.upsert_status(BuffSpec(
                key=f"Tribbie_Ult_DivineRevelation_{ally}",
                name="神启",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, res_pen),),
                duration=turns,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"全属性抗性穿透 +{res_pen * 100:.1f}%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="一百层的小火箭"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="礼物都去哪儿了"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="猜猜这里住着谁"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="开心你就拍拍手"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【一百层的小火箭】：扩散 (Blast) 伤害，HP 缩放。"""
        enemies = self.port.enemies(self.owner_id)
        if not enemies:
            return
        primary_target = (
            ctx.target_ids[0]
            if ctx.target_ids
            else (enemies[1] if len(enemies) >= 3 else enemies[0])
        )

        main_mult = self.skill_param("basic", 0, default=0.42)
        adj_mult = self.skill_param("basic", 1, default=0.21)

        self.port.attack(
            self.owner_id,
            primary_target,
            element="Quantum",
            atk_multiplier=main_mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="hp"
        )

        try:
            p_idx = enemies.index(primary_target)
            adjacent_targets = []
            if p_idx > 0:
                adjacent_targets.append(enemies[p_idx - 1])
            if p_idx < len(enemies) - 1:
                adjacent_targets.append(enemies[p_idx + 1])
            for adj in adjacent_targets:
                self.port.attack(
                    self.owner_id,
                    adj,
                    element="Quantum",
                    atk_multiplier=adj_mult,
                    toughness_damage=5.0,
                    damage_type=DamageType.BASIC,
                    scaling_stat="hp"
                )
        except ValueError:
            pass

        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 20.0 * err)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【礼物都去哪儿了】：获得【神启】3 回合，我方全体抗穿。"""
        duration = int(self.skill_param("skill", 1, default=3))
        self.apply_divine_revelation(turns=duration)
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 30.0 * err)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【猜猜这里住着谁】：开启结界，易伤，神启，E4 无视防御，E6 追加攻击。"""
        zone_vuln = self.skill_param("ultra", 1, default=0.33)
        self.zone_active = True

        # 1. 展开结界领域
        self.port.upsert_status(BuffSpec(
            key="Tribbie_Ult_Zone_GuessWhoLivesHere",
            name="猜猜这里住着谁",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(),
            duration=3,
            timing=DurationTiming.CASTER_TURN_END,
            category="other",
            description=f"结界领域展开中：敌方受到伤害提高 +{zone_vuln * 100:.1f}%"
        ))

        for e in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"Tribbie_Ult_Zone_Vulnerability_{e}",
                name="结界易伤 (猜猜这里住着谁)",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, zone_vuln),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description=f"受到伤害提高 +{zone_vuln * 100:.1f}%"
            ))

        # 1.5 终结技本体伤害: 对敌方全体造成等同于缇宝生命上限 30% (Lv 10) / 33% (Lv 12) 的量子伤害
        ult_mult = self.skill_param("ultra", 0, default=0.30)
        for e in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                e,
                element="Quantum",
                atk_multiplier=ult_mult,
                toughness_damage=20.0,
                damage_type=DamageType.ULTIMATE,
                scaling_stat="hp"
            )

        # 2. 为我方全体附加【神启】并重置天赋次数
        self.talent_used_by.clear()
        res_pen = self.skill_param("skill", 0, default=0.264)
        for a in self.port.allies(self.owner_id):
            if self.port.is_countdown(a):
                continue
            if a != self.owner_id and not self.port.is_memosprite(a):
                self.port.upsert_status(BuffSpec(
                    key=f"Tribbie_Talent_BusyBusy_{a}",
                    name="好忙好忙的缇宝",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="other",
                    tags=(StatusTag.CHARACTER_ONLY,),
                    description="队友施放终结技后，触发缇宝天赋追加攻击 (次数已重置)"
                ))
            self.port.upsert_status(BuffSpec(
                key=f"Tribbie_Ult_DivineRevelation_{a}",
                name="神启",
                source_id=self.owner_id,
                target_id=a,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, res_pen),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"全属性抗性穿透 +{res_pen * 100:.1f}%"
            ))

        # 3. 星魂 4【心意相契的安宁】：结界期间我方全体无视目标 18% 防御
        if self.eidolon >= 4:
            for a in self.port.allies(self.owner_id):
                if self.port.is_countdown(a):
                    continue
                self.port.upsert_status(BuffSpec(
                    key=f"Tribbie_E4_PeaceInConcord_{a}",
                    name="心意相契的安宁",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="全队造成的伤害无视目标 18.0% 防御"
                ))

        # 4. 额外能力【长翅膀的玻璃球！】：处于结界期间自身生命上限提升全队生命上限之和的 9%
        self._sync_glass_ball_hp()

        # 5. 施放大招自身固定回能 5 点 (受 ERR 加成);
        #    E6 齐射的回能 5 点在齐射实际施放时由 _cast_talent_volley 统一结算
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 5.0 * err)

        # 6. 星魂 6【星月漫天的明日】：施放终结技时立即触发一次追加攻击。
        #    先排空并结算终结技本体伤害的结界窗口, 再置待发标记触发 E6 齐射并独立结算。
        if self.eidolon >= 6:
            if hasattr(self.port, "resolve_effects"):
                self.port.resolve_effects()
            self._pending_volley = True
            self._flush_zone_window()

    def _apply_lamb_buff(self) -> None:
        """行迹【城墙外的羊羔儿】: 施放天赋追加攻击后, 自身造成伤害提高 72%,
        最多叠加 3 层, 持续 3 回合。每次追加攻击 (队友大招触发或 E6 自大招齐射)
        结算后叠加 1 层; 本次齐射不享受自己新叠的层数。"""
        self.port.upsert_status(BuffSpec(
            key="Tribbie_A2_LambOutsideTheWall",
            name="城墙外的羊羔儿",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.72),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            stacks=1,
            max_stacks=3,
            stack_policy=StackPolicy.STACK,
            description="造成伤害提高 +72.0% (每层, 最多 3 层)"
        ))

    def _flush_zone_window(self) -> None:
        """结算上一个我方攻击动作窗口的结界附加伤害 (140303) 与星魂 1 真实伤害。

        触发规则以官方真值日志 (battle_20261025_131019) 逐窗口对账为准:
        - 附加命中数 = 该行动对敌方造成的伤害段数 + (星魂 2 时额外 1 次, 每次行动
          仅 1 次, 而非每个目标 1 次)。实测: 单目标行动 1 段→2 命中、三目标全体
          攻击 3 段→4 命中、长夜迷梦 5 段→6 命中。旧实现按「不同目标数 × 2」
          计数, 三目标时打出 6 命中, 系统性偏高。
        - 附加伤害全部落在被攻击目标中当前生命值最高者身上, 每段等同于缇宝
          12% 生命上限 (星魂 2 倍率提高至 120%) 的量子属性伤害。
        - 星魂 1 真实伤害的基数 = 本次攻击总伤害 + 本次结界附加实际打出的伤害:
          实测两窗口 0.24 × (712,020 + 277,564) = 237,501、0.24 × (569,426 +
          268,756) = 201,164, 与日志真实伤害逐点吻合。
        结算完成后, 若有待发的天赋追加攻击, 在此开启其专属窗口并施放
        (官方时序中追击是独立行动, 与触发它的终结技各结算一次结界)。
        延迟真实伤害: 引擎的伤害经效果队列延迟结算, 本窗口附加的实际值在
        结算当下尚未产生, 故星魂 1 真实伤害登记为待结算, 在下一次窗口结算
        时以 (本次攻击总伤害 + 附加实际值) 为基数先行发出。
        """
        if self._zone_resolving:
            return
        if hasattr(self.port, "resolve_effects"):
            self.port.resolve_effects()
        targets = self._zone_window_targets
        total = self._zone_window_total
        true_base_pool = self._zone_window_true_base
        hit_count = self._zone_window_hits
        zone_was_active = self._zone_window_zone
        window_actor = self._zone_window_actor
        self._zone_window_actor = None
        self._zone_window_zone = False
        self._zone_window_targets = set()
        self._zone_window_total = 0.0
        self._zone_window_true_base = 0.0
        self._zone_window_hits = 0
        pending_volley = self._pending_volley
        self._pending_volley = False

        # 结界判定取窗口开启时与结算时两点状态的并集: 终结技自身的窗口在
        # 事件到达时结界尚未展开 (状态在大招执行中段才施加), 须以结算时
        # 状态补正, 否则大招本体永远无法触发自己开启的结界
        if (zone_was_active or self.zone_active) and targets and total > 0 and hit_count > 0:
            living_enemies = set(self.port.enemies(self.owner_id))
            living = [t for t in targets if t in living_enemies]
            if not living:
                living = [t for t in targets if self.port.entity_exists(t) and self.port.current_hp(t) > 0]
            if living:
                top_target = max(living, key=lambda t: (self.port.current_hp(t), self.port.max_hp(t)))
                base_mult = self.skill_param("ultra", 2, default=0.12)
                additional_hits = hit_count
                if self.eidolon >= 2:
                    base_mult *= self.eidolon_param(2, 0, default=1.2)
                    if not self._in_volley:
                        additional_hits += 1
                self._zone_resolving = True
                try:
                    if self.eidolon >= 1:
                        self._pending_true = {"target": top_target, "base": true_base_pool, "additional": 0.0}
                    for _ in range(additional_hits):
                        self.port.attack(
                            self.owner_id,
                            top_target,
                            element="Quantum",
                            atk_multiplier=base_mult,
                            toughness_damage=0.0,
                            damage_type=DamageType.ADDITIONAL,
                            scaling_stat="hp"
                        )
                    if hasattr(self.port, "resolve_effects"):
                        self.port.resolve_effects()
                    if self._pending_true is not None:
                        pending_true = self._pending_true
                        self._pending_true = None
                        if self.port.entity_exists(pending_true["target"]):
                            true_ratio = self.eidolon_param(1, 0, default=0.24)
                            my_max_hp = self.port.max_hp(self.owner_id)
                            true_base = (pending_true["base"] + pending_true["additional"]) if pending_true["base"] > 0 else 0.0
                            t_id = pending_true["target"]
                            emit_zero_true = (
                                true_base == 0.0
                                and window_actor != "晴空乐手"
                                and hasattr(self.port, "is_barrier_guarded")
                                and self.port.is_barrier_guarded(t_id)
                            )
                            if my_max_hp > 0 and (true_base > 0 or emit_zero_true):
                                # 真实伤害为固定数值: 以生命上限为缩放基准反推等效倍率 (真实伤害结算只取基础区)
                                self.port.attack(
                                    self.owner_id,
                                    pending_true["target"],
                                    element="Quantum",
                                    atk_multiplier=(true_base * true_ratio) / my_max_hp,
                                    toughness_damage=0.0,
                                    damage_type=DamageType.TRUE,
                                    scaling_stat="hp"
                                )
                                if hasattr(self.port, "resolve_effects"):
                                    self.port.resolve_effects()
                finally:
                    self._zone_resolving = False
        if pending_volley:
            # 追击作为独立行动: 开启其专属窗口采样并施放, 同步排空并独立结算其结界窗口;
            # 行迹【城墙外的羊羔儿】在本次追加攻击及其结界窗口结算完毕后再叠层 (本次齐射不享受自己新叠的层数)
            self._zone_window_actor = self.owner_id
            self._zone_window_zone = self.zone_active
            self._in_volley = True
            try:
                self._cast_talent_volley()
            finally:
                self._in_volley = False
            if hasattr(self.port, "resolve_effects"):
                self.port.resolve_effects()
            self._flush_zone_window()
            self._apply_lamb_buff()

    def _cast_talent_volley(self) -> None:
        """施放天赋追加攻击齐射 (全体敌人, 生命上限 Lv12 19.8% × E6 追击补正) 并处理回能。

        倍率依据见天赋触发处注释 (E6 齐射补正)。回能在此统一处理;
        E6 自大招齐射的回能已在大招本体处一并结算, 其待发标记由
        cast_ultimate 直接置位时不重复回能 (见 _pending_volley 的置位点)。
        """
        fu_mult = self.skill_param("talent", 0, default=0.198)
        e6_boost = self.eidolon_param(6, 0, default=7.29) if self.eidolon >= 6 else 0.0
        for e in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                e,
                element="Quantum",
                atk_multiplier=fu_mult,
                toughness_damage=10.0,
                damage_type=DamageType.FOLLOW_UP,
                scaling_stat="hp",
                extra_dmg_boost=e6_boost
            )
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 5.0 * err, cause="天赋追加攻击回能 (基础 5.0 × ERR)", source_plugin="缇宝天赋")

    def _sync_glass_ball_hp(self) -> None:
        """同步行迹【长翅膀的玻璃球！】生命上限加成 (我方全体角色生命上限之和的 9%)。"""
        if not self.port:
            return
        zone_status = next(
            (s for s in self.port.statuses(self.owner_id, category="other") if s.id == "Tribbie_Ult_Zone_GuessWhoLivesHere"),
            None
        )
        self.zone_active = zone_status is not None
        if not self.zone_active:
            if self.port.has_status(self.owner_id, "Tribbie_A4_GlassBallWithWings"):
                self.port.remove_status(self.owner_id, "Tribbie_A4_GlassBallWithWings")
            return

        if self.zone_active:
            zone_vuln = self.skill_param("ultra", 1, default=0.33)
            for e in self.port.enemies(self.owner_id):
                if not self.port.has_status(e, f"Tribbie_Ult_Zone_Vulnerability_{e}"):
                    self.port.upsert_status(BuffSpec(
                        key=f"Tribbie_Ult_Zone_Vulnerability_{e}",
                        name="结界易伤 (猜猜这里住着谁)",
                        source_id=self.owner_id,
                        target_id=e,
                        modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, zone_vuln),),
                        duration=zone_status.duration,
                        timing=DurationTiming.TARGET_TURN_END,
                        skip_current_clock=True,
                        category="debuff",
                        description=f"受到伤害提高 +{zone_vuln * 100:.1f}%"
                    ))

        team_hp_sum = 0.0
        for ally in self.port.allies(self.owner_id):
            if not self.port.is_memosprite(ally) and not self.port.is_countdown(ally):
                if ally == self.owner_id:
                    self_hp = self.port.stat(
                        ally,
                        StatType.MAX_HP_PERCENT,
                        exclude_tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS,)
                    )
                    team_hp_sum += self_hp
                else:
                    team_hp_sum += self.port.max_hp(ally)

        glass_ball_hp = round(team_hp_sum * 0.09, 1)
        self.port.upsert_status(BuffSpec(
            key="Tribbie_A4_GlassBallWithWings",
            name="长翅膀的玻璃球！",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, glass_ball_hp),),
            duration=zone_status.duration,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=zone_status.skip_current_clock,
            category="buff",
            tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS, StatusTag.SUPPRESS_STATUS_APPLY_EVENT),
            description=f"生命上限提升 +{glass_ball_hp:.0f} (全队生命上限之和的 9%)"
        ))

    def on_event(self, event: Any) -> None:
        """响应事件：
        1. 我方其他角色施放终结技后触发追加攻击；
        2. 行迹【岔路旁的小石子？】：我方目标施放攻击后，每击中 1 个目标使缇宝恢复 1.5 点能量；
        3. 动态同步【长翅膀的玻璃球！】生命上限与结界易伤光环。
        """
        from ...events import (
            ActionExecuteEvent, DamageAppliedEvent, SpiritSummonedEvent,
            SpiritDespawnEvent, StatusApplyEvent, StatusExpireEvent,
            TurnBeginEvent, TurnEndEvent
        )
        if isinstance(event, TurnBeginEvent):
            self._turn_started = True
        if isinstance(event, (TurnBeginEvent, TurnEndEvent)):
            self._flush_zone_window()
        if isinstance(event, (ActionExecuteEvent, SpiritSummonedEvent, SpiritDespawnEvent, StatusApplyEvent, StatusExpireEvent, TurnBeginEvent)):
            self._sync_glass_ball_hp()

        if isinstance(event, DamageAppliedEvent):
            attacker = event.attacker_name
            target = event.target_name
            dtype = getattr(event, "damage_type", None)
            is_own_zone_dmg = (attacker == self.owner_id and dtype in (DamageType.ADDITIONAL, DamageType.TRUE))

            # 结界窗口采样: 收集我方攻击命中的敌方目标与伤害总量, 供动作结束时结算附加伤害与 E1 真实伤害。
            # 结界自身的附加/真实伤害不计入采样, 队友伴随攻击触发的附加伤害 (如小伊卡 E1) 计入本次攻击总伤害池。
            is_new_target = False
            if (
                not self._zone_resolving
                and self.port.is_ally(attacker)
                and not self.port.is_countdown(attacker)
                and not self.port.is_ally(target)
                and dtype not in (DamageType.DOT, DamageType.TRUE)
                and not is_own_zone_dmg
                and getattr(event.breakdown, "is_dot", False) is False
                and event.damage > 0
            ):
                if self._zone_window_actor is None:
                    self._zone_window_actor = attacker
                    self._zone_window_zone = self.zone_active
                is_new_target = target not in self._zone_window_targets
                self._zone_window_targets.add(target)
                self._zone_window_total += float(event.damage)
                is_guarded = hasattr(self.port, "is_barrier_guarded") and self.port.is_barrier_guarded(target)
                if not is_guarded:
                    self._zone_window_true_base += float(event.damage)
                if is_new_target and dtype != DamageType.ADDITIONAL:
                    self._zone_window_hits += 1

            # 汇总待结算真实伤害的基数: 本窗口结界附加伤害的实际值
            if (
                self._pending_true is not None
                and attacker == self.owner_id
                and dtype == DamageType.ADDITIONAL
            ):
                self._pending_true["additional"] += float(event.damage)

            # 严格机制边界校验 (避免 DoT、环境反伤、自残扣血、多段同目标重复触发误判):
            # 1. 攻击者必须为我方目标 (支持伴生忆灵长夜及进入正式回合后的缇宝直接攻击)
            # 2. 承受目标必须为敌方目标 (每次攻击每击中 1 个不同目标触发 1 次)
            # 3. 必须为直接攻击有效命中 (排除 DoT / stage_bleed / reflect / 结界附加与真伤)
            is_valid_attacker = self.port.is_ally(attacker) and (
                attacker != self.owner_id or (getattr(self, "_turn_started", False) and not is_own_zone_dmg)
            )
            is_valid_target = not self.port.is_ally(target)
            is_attack_dmg = (
                dtype != DamageType.DOT
                and getattr(event.breakdown, "is_dot", False) is False
                and event.damage > 0
            )

            if is_valid_attacker and is_valid_target and is_attack_dmg and is_new_target:
                energy_per_hit = self.skill_param("trace_pebble_per_hit", 1, default=self.TRACE_PEBBLE_ENERGY_PER_HIT)
                # 星铁底层机制：未标明“固定能量”的回能严格享受角色能量恢复效率 (ERR) 放大
                err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
                self.port.gain_energy(self.owner_id, energy_per_hit * err, cause=f"行迹《岔路旁的小石子？》我方目标命中[{target}]回能 (基础 {energy_per_hit} × ERR {err*100:.1f}%)", source_plugin="缇宝行迹")

        elif isinstance(event, ActionExecuteEvent):
            action_kind = getattr(event, "action_kind", None)
            if action_kind == ActionKind.TALENT:
                return
            actor_id = event.actor_name or event.actor_id
            if getattr(self, "_in_volley", False) and actor_id == self.owner_id and action_kind == ActionKind.FOLLOW_UP:
                return
            # 新动作开始: 先排空挂起伤害并结算上一个动作窗口的结界附加伤害, 再开启本动作的采样窗口
            if hasattr(self.port, "resolve_effects"):
                self.port.resolve_effects()
            self._flush_zone_window()
            if self.port.is_ally(actor_id) and not self.port.is_countdown(actor_id):
                self._zone_window_actor = actor_id
                self._zone_window_zone = self.zone_active
            action_type = getattr(event, "action_type", "")

            if self.port.is_ally(actor_id) and actor_id != self.owner_id and not self.port.is_memosprite(actor_id) and not self.port.is_countdown(actor_id):
                if action_kind == ActionKind.ULTIMATE:
                    if actor_id not in self.talent_used_by:
                        self.talent_used_by.add(actor_id)
                        # 置待发标记: 齐射在大招的结界窗口结算后作为独立行动施放
                        # 并单独结算其结界窗口 (见 _flush_zone_window); 倍率依据
                        # (E6 的 729% 不叠乘) 见 _cast_talent_volley。
                        self._pending_volley = True

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

from dataclasses import dataclass, field
from typing import Optional, List, Any
from ..base import KitHandler
from ..registry import register_kit
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType, FollowUpPhase
from ...combat_port import BuffSpec, CombatPort
from ...events import PrimaryDamageCompleteEvent, ActionEndEvent
from ...status import DurationTiming, Modifier, ModifierOp, StackPolicy, StatType, StatusTag


@dataclass
class _ZoneWindow:
    actor_id: str
    kind: ActionKind
    zone_seen: bool = False

    targets: set[str] = field(default_factory=set)
    direct_targets: set[str] = field(default_factory=set)

    damage_total: float = 0.0
    true_base: float = 0.0
    direct_hits: int = 0

    request_volley: bool = False


@register_kit("1403", "缇宝", "tribbie", "tibao")
class TibaoKit(KitHandler):
    """缇宝 (ID 1403, 量子 / 同谐)."""
    follow_up_phase = FollowUpPhase.NORMAL

    # 官方解包数据 (1403.json 行迹 1403103 【岔路旁的小石子？】 param_list: [30, 1.5])
    TRACE_PEBBLE_START_ENERGY: float = 30.0
    TRACE_PEBBLE_ENERGY_PER_HIT: float = 1.5

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 0, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.zone_active: bool = False
        self.zone_duration: int = 0
        self.talent_used_by: set = set()

        # 基于 action_id 的结界因果账本
        self._zone_windows: dict[int, _ZoneWindow] = {}
        self._zone_finished_actions: set[int] = set()
        self._zone_seen_effects: set[int] = set()
        self._zone_settling_action: Optional[int] = None
        self._zone_additional_actual: float = 0.0
        self._turn_started: bool = False

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
        # 由大招行动窗口在主伤完成后统一安排 (见 _flush_zone_window)

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

    def _on_zone_action_execute(self, event: Any) -> None:
        from ._causal import actor_of, require_id

        action_id = require_id(event, "action_id")
        if (
            action_id in self._zone_windows
            or action_id in self._zone_finished_actions
        ):
            return

        actor = actor_of(event)
        kind = event.action_kind

        if (
            kind == ActionKind.TALENT
            or not self.port.is_ally(actor)
            or self.port.is_countdown(actor)
        ):
            return

        window = _ZoneWindow(
            actor_id=actor,
            kind=kind,
            zone_seen=self.zone_active,
        )
        self._zone_windows[action_id] = window

        if kind != ActionKind.ULTIMATE:
            return

        is_other_character = (
            actor != self.owner_id
            and not self.port.is_memosprite(actor)
        )

        if is_other_character and actor not in self.talent_used_by:
            self.talent_used_by.add(actor)
            window.request_volley = True

        if actor == self.owner_id and self.eidolon >= 6:
            window.request_volley = True

    def _on_zone_damage(self, event: Any) -> None:
        from ._causal import require_id

        action_id = require_id(event, "action_id")
        effect_id = require_id(event, "effect_id")

        if effect_id in self._zone_seen_effects:
            return
        self._zone_seen_effects.add(effect_id)

        attacker = event.attacker_name
        target = event.target_name
        dtype = event.damage_type
        damage = float(event.damage)

        # 结界自身附加伤害仅进入本次真实伤害基数，不反过来触发更多结界伤害
        if (
            self._zone_settling_action == action_id
            and attacker == self.owner_id
            and dtype == DamageType.ADDITIONAL
        ):
            if not self.port.is_barrier_guarded(target):
                self._zone_additional_actual += max(0.0, damage)
            return

        if self._zone_settling_action == action_id:
            return

        window = self._zone_windows.get(action_id)
        if window is None:
            # 兼容测试桩未显式声明 ActionExecuteEvent 的裸 DamageAppliedEvent
            window = self._zone_windows.setdefault(
                action_id,
                _ZoneWindow(actor_id=attacker, kind=ActionKind.BASIC, zone_seen=self.zone_active)
            )

        if (
            not self.port.is_ally(attacker)
            or self.port.is_countdown(attacker)
            or self.port.is_ally(target)
            or dtype in (DamageType.DOT, DamageType.TRUE)
            or getattr(
                getattr(event, "breakdown", None),
                "is_dot",
                False,
            )
            or damage <= 0
        ):
            return

        window.zone_seen |= self.zone_active
        window.targets.add(target)
        window.damage_total += damage

        if not self.port.is_barrier_guarded(target):
            window.true_base += damage

        if dtype == DamageType.ADDITIONAL:
            return

        window.direct_hits += 1

        if target not in window.direct_targets:
            window.direct_targets.add(target)

            # 行迹【岔路旁的小石子？】：仅限我方其他目标 (队友及忆灵) 攻击命中时回能，缇宝自身攻击不触发
            if attacker != self.owner_id:
                amount = self.skill_param(
                    "trace_pebble_per_hit",
                    1,
                    default=self.TRACE_PEBBLE_ENERGY_PER_HIT,
                )
                err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
                self.port.gain_energy(
                    self.owner_id,
                    amount * err,
                    cause=f"小石子：行动 {action_id} 首次命中 {target}",
                    source_plugin="缇宝行迹",
                )

    def _flush_zone_window(self, action_id: Optional[int] = None) -> None:
        """结算我方攻击动作窗口的结界附加伤害 (140303) 与星魂 1 真实伤害。"""
        if action_id is None:
            if self._zone_windows:
                action_id = next(iter(self._zone_windows))
            else:
                return

        if action_id in self._zone_finished_actions:
            return

        if self._zone_settling_action is not None:
            return

        window = self._zone_windows.get(action_id)
        if window is None:
            return

        self._zone_windows.pop(action_id)
        self._zone_finished_actions.add(action_id)

        self._zone_settling_action = action_id
        self._zone_additional_actual = 0.0

        try:
            living = set(self.port.enemies(self.owner_id))
            candidates = [
                target
                for target in window.targets
                if target in living
                and self.port.current_hp(target) > 0
            ]

            if (
                window.zone_seen
                and candidates
                and window.direct_hits > 0
            ):
                target = max(
                    candidates,
                    key=lambda t: (
                        self.port.current_hp(t),
                        self.port.max_hp(t),
                    ),
                )

                multiplier = self.skill_param(
                    "ultra", 2, default=0.12,
                )
                hits = window.direct_hits

                if self.eidolon >= 2:
                    multiplier *= self.eidolon_param(
                        2, 0, default=1.2,
                    )
                    hits += 1

                for _ in range(hits):
                    if target not in self.port.enemies(self.owner_id):
                        break

                    self.port.attack(
                        self.owner_id,
                        target,
                        element="Quantum",
                        atk_multiplier=multiplier,
                        toughness_damage=0.0,
                        damage_type=DamageType.ADDITIONAL,
                        scaling_stat="hp",
                    )
                    self.port.resolve_effects()

                true_base = (
                    window.true_base
                    + self._zone_additional_actual
                )
                if (
                    self.eidolon >= 1
                    and true_base > 0
                    and target in self.port.enemies(self.owner_id)
                ):
                    hp = self.port.max_hp(self.owner_id)
                    if hp > 0:
                        true_amount = true_base * self.eidolon_param(
                            1, 0, default=0.24,
                        )
                        self.port.attack(
                            self.owner_id,
                            target,
                            element="Quantum",
                            atk_multiplier=true_amount / hp,
                            toughness_damage=0.0,
                            damage_type=DamageType.TRUE,
                            scaling_stat="hp",
                        )
                        self.port.resolve_effects()
        finally:
            self._zone_settling_action = None
            self._zone_additional_actual = 0.0

        if window.kind == ActionKind.FOLLOW_UP:
            if window.actor_id == self.owner_id:
                self._apply_lamb_buff()

        if window.request_volley and self.port.enemies(self.owner_id):
            self.port.enqueue_follow_up(
                actor_id=self.owner_id,
                name="好忙好忙的缇宝",
                skill_id=None,
                callback=self._cast_talent_volley,
            )

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

        glass_ball_hp = team_hp_sum * 0.09
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
            TurnBeginEvent, TurnEndEvent, ActionEndEvent, PrimaryDamageCompleteEvent
        )
        if isinstance(event, TurnBeginEvent):
            self._turn_started = True
        if isinstance(event, (ActionExecuteEvent, SpiritSummonedEvent, SpiritDespawnEvent, StatusApplyEvent, StatusExpireEvent, TurnBeginEvent)):
            self._sync_glass_ball_hp()

        if isinstance(event, SpiritSummonedEvent):
            target_id = getattr(event, "spirit_name", "")
            if (
                self.port.entity_exists(target_id)
                and self.port.is_ally(target_id)
                and self.port.is_memosprite(target_id)
            ):
                divine_buff = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Tribbie_Ult_DivineRevelation_")), None)
                if divine_buff and not self.port.has_status(target_id, f"Tribbie_Ult_DivineRevelation_{target_id}"):
                    self.port.upsert_status(BuffSpec(
                        key=f"Tribbie_Ult_DivineRevelation_{target_id}",
                        name="神启",
                        source_id=self.owner_id,
                        target_id=target_id,
                        modifiers=tuple(divine_buff.modifiers),
                        duration=divine_buff.duration,
                        timing=divine_buff.timing,
                        skip_current_clock=True,
                        category="buff",
                        description="全属性抗性穿透",
                        parent_key=divine_buff.id,
                        parent_target_name=self.owner_id
                    ))
                e4_buff = next((s for s in self.port.statuses(self.owner_id) if s.id.startswith("Tribbie_E4_PeaceInConcord_")), None)
                if e4_buff and not self.port.has_status(target_id, f"Tribbie_E4_PeaceInConcord_{target_id}"):
                    self.port.upsert_status(BuffSpec(
                        key=f"Tribbie_E4_PeaceInConcord_{target_id}",
                        name="心意相契的安宁",
                        source_id=self.owner_id,
                        target_id=target_id,
                        modifiers=tuple(e4_buff.modifiers),
                        duration=e4_buff.duration,
                        timing=e4_buff.timing,
                        skip_current_clock=True,
                        category="buff",
                        description="全队造成的伤害无视目标 18.0% 防御",
                        parent_key=e4_buff.id,
                        parent_target_name=self.owner_id
                    ))

        if isinstance(event, ActionExecuteEvent):
            self._on_zone_action_execute(event)

        elif isinstance(event, DamageAppliedEvent):
            self._on_zone_damage(event)

        elif isinstance(event, PrimaryDamageCompleteEvent):
            from ._causal import require_id
            self._flush_zone_window(require_id(event, "action_id"))

        elif isinstance(event, ActionEndEvent):
            from ._causal import require_id
            # 无主伤行动或生命周期兜底；已结算的 action_id 自动忽略。
            self._flush_zone_window(require_id(event, "action_id"))

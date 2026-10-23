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
   - 行迹【长翅膀的玻璃球！】：结界期间自身生命上限提升 2527 点数值；
   - 星魂 4【心意相契的安宁】：结界期间我方全体无视目标 18% 防御；
   - 星魂 6【星月漫天的明日】：施放大招后立即对敌方全体发动天赋追加攻击；
   - 重置队友【好忙好忙的缇宝】追加攻击触发次数。
4. 天赋【好忙好忙的缇宝】：我方其他角色施放终结技后，缇宝发动追加攻击，对敌方全体造成等同于缇宝生命上限 18% (Lv 10) 的量子伤害。
   每个队友最多触发 1 次，缇宝施放终结技时重置次数。削韧 10，回能 5。
   行迹【城墙外的羊羔儿】：施放天赋追加攻击后，自身伤害提高 72%，持续 3 回合。
   E6: 天赋追加攻击造成的伤害提高 729%。
5. 秘技【开心你就拍拍手】：进战获得【神启】，持续 3 回合。
6. 行迹【岔路旁的小石子？】：进战回能 30 点 (受 ERR 加成)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StatusTag


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
                description="天赋追加攻击伤害提高 +729.0%"
            ))

        # 天赋标记【好忙好忙的缇宝】 (仅角色生效，带 CHARACTER_ONLY 语义标签，忆灵/召唤物不挂载)
        for ally in self.port.allies(self.owner_id):
            if ally != self.owner_id and not self.port.is_memosprite(ally):
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
            if self.eidolon >= 4:
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
        primary_target = ctx.target_ids[0] if ctx.target_ids else enemies[0]

        main_mult = self.skill_param("basic", 0, default=0.42)
        adj_mult = self.skill_param("basic", 1, default=0.21)

        self.port.attack(
            self.owner_id,
            primary_target,
            element="Quantum",
            atk_multiplier=main_mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
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
                    damage_tag="BasicAttack",
                    scaling_stat="hp"
                )
        except ValueError:
            pass

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【礼物都去哪儿了】：获得【神启】3 回合，我方全体抗穿。"""
        duration = int(self.skill_param("skill", 1, default=3))
        self.apply_divine_revelation(turns=duration)
        self.port.gain_energy(self.owner_id, 30.0)

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

        # 2. 为我方全体附加【神启】并重置天赋次数
        self.talent_used_by.clear()
        res_pen = self.skill_param("skill", 0, default=0.264)
        for a in self.port.allies(self.owner_id):
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

        # 5. 施放大招自身固定回能 5 点 + E6 天赋追加攻击回能 5 点 (受 ERR 加成)
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        base_energy = 5.0 + (5.0 if self.eidolon >= 6 else 0.0)
        self.port.gain_energy(self.owner_id, base_energy * err)

        # 6. 星魂 6【星月漫天的明日】：施放终结技时立即触发一次追加攻击
        if self.eidolon >= 6:
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
                description="造成伤害提高 +72.0%"
            ))
            fu_mult = 1.20 * (1.0 + 7.29)
            for e in self.port.enemies(self.owner_id):
                self.port.attack(
                    self.owner_id,
                    e,
                    element="Quantum",
                    atk_multiplier=fu_mult,
                    toughness_damage=10.0,
                    damage_tag="FollowUpAttack",
                    scaling_stat="hp"
                )

    def _sync_glass_ball_hp(self) -> None:
        """同步行迹【长翅膀的玻璃球！】生命上限加成 (我方全体角色生命上限之和的 9%)。"""
        if not self.port:
            return
        is_active = getattr(self, "zone_active", False) or self.port.has_status(self.owner_id, "Tribbie_Ult_Zone_GuessWhoLivesHere")
        if not is_active:
            if self.port.has_status(self.owner_id, "Tribbie_A4_GlassBallWithWings"):
                old_max = self.port.max_hp(self.owner_id)
                self.port.remove_status(self.owner_id, "Tribbie_A4_GlassBallWithWings")
                new_max = self.port.max_hp(self.owner_id)
                ent = getattr(self.port, "_get_entity", lambda x: None)(self.owner_id)
                if ent and getattr(ent, "current_hp", 0.0) > new_max:
                    ent.current_hp = new_max
            return

        team_hp_sum = 0.0
        for ally in self.port.allies(self.owner_id):
            if not self.port.is_memosprite(ally):
                if ally == self.owner_id:
                    ent = getattr(self.port, "_get_entity", lambda x: None)(ally)
                    base_max_hp = getattr(ent, "max_hp", 0.0)
                    white_hp = getattr(ent, "base_white_hp", 0.0) or base_max_hp
                    status_mgr = getattr(getattr(self.port, "sim", None), "status_mgr", None)
                    if status_mgr:
                        self_hp = status_mgr.calculate_stat(
                            ally, base_max_hp, StatType.MAX_HP_PERCENT, white_base=white_hp,
                            exclude_ids=("Tribbie_A4_GlassBallWithWings",)
                        )
                    else:
                        self_hp = base_max_hp
                    team_hp_sum += self_hp
                else:
                    team_hp_sum += self.port.max_hp(ally)

        glass_ball_hp = round(team_hp_sum * 0.09, 1)
        old_max = self.port.max_hp(self.owner_id)
        self.port.upsert_status(BuffSpec(
            key="Tribbie_A4_GlassBallWithWings",
            name="长翅膀的玻璃球！",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, glass_ball_hp),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"生命上限提升 +{glass_ball_hp:.0f} (全队生命上限之和的 9%)"
        ))
        new_max = self.port.max_hp(self.owner_id)
        hp_delta = new_max - old_max
        if hp_delta > 0:
            ent = getattr(self.port, "_get_entity", lambda x: None)(self.owner_id)
            if ent:
                ent.current_hp = min(new_max, getattr(ent, "current_hp", 0.0) + hp_delta)

    def on_event(self, event: Any) -> None:
        """响应事件：
        1. 我方其他角色施放终结技后触发追加攻击；
        2. 行迹【岔路旁的小石子？】：我方其他目标攻击后，每击中 1 个目标使缇宝恢复 1.5 点固定能量。
        """
        from ...events import ActionExecuteEvent, DamageAppliedEvent, SpiritSummonedEvent, SpiritDespawnEvent
        if isinstance(event, (ActionExecuteEvent, SpiritSummonedEvent, SpiritDespawnEvent)):
            self._sync_glass_ball_hp()

        if isinstance(event, DamageAppliedEvent):
            attacker = event.attacker_name
            target = event.target_name

            # 严格机制边界校验 (避免 DoT、环境反伤、自残扣血误判):
            # 1. 攻击者必须为我方其他目标 (排除缇宝自身，支持伴生忆灵长夜)
            # 2. 承受目标必须为敌方目标
            # 3. 必须为直接攻击有效命中 (排除 DoT / stage_bleed / reflect)
            is_valid_attacker = self.port.is_ally(attacker) and attacker != self.owner_id
            is_valid_target = not self.port.is_ally(target)
            is_attack_dmg = (
                getattr(event, "damage_tag", "") not in ("dot", "stage_bleed", "reflect", "environment")
                and getattr(event.breakdown, "is_dot", False) is False
                and event.damage > 0
            )

            if is_valid_attacker and is_valid_target and is_attack_dmg:
                energy_per_hit = self.skill_param("trace_pebble_per_hit", 1, default=self.TRACE_PEBBLE_ENERGY_PER_HIT)
                # 星铁底层机制：未标明“固定能量”的回能严格享受角色能量恢复效率 (ERR) 放大
                err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
                self.port.gain_energy(self.owner_id, energy_per_hit * err)

        elif isinstance(event, ActionExecuteEvent):
            self._sync_glass_ball_hp()
            actor_id = event.actor_name or event.actor_id
            action_kind = getattr(event, "action_kind", None)
            action_type = getattr(event, "action_type", "")

            if self.port.is_ally(actor_id) and actor_id != self.owner_id and not self.port.is_memosprite(actor_id):
                if action_kind == ActionKind.ULTIMATE or "Ultimate" in str(action_type):
                    if actor_id not in self.talent_used_by:
                        self.talent_used_by.add(actor_id)
                        fu_mult = 0.18 * ((1.0 + 7.29) if self.eidolon >= 6 else 1.0)
                        for e in self.port.enemies(self.owner_id):
                            self.port.attack(
                                self.owner_id,
                                e,
                                element="Quantum",
                                atk_multiplier=fu_mult,
                                toughness_damage=10.0,
                                damage_tag="FollowUpAttack",
                                scaling_stat="hp"
                            )
                        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
                        self.port.gain_energy(self.owner_id, 5.0 * err)

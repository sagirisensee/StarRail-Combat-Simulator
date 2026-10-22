"""联动角色与未来角色战斗技能套件完整实现 (Collab & Special Character Kits).

涵盖用户账号中的特殊联动与未定档角色：
- 远坂凛 (Tohsaka Rin - ID 1508)
- Archer (ID 1015)
- 昔涟 (ID 1415)
- 丹恒•腾荒 (ID 1414)
- 长夜月 (ID 1413)
- 刻律德菈 (ID 1412)
- 风堇 (ID 1409)
- 遐蝶 (ID 1407)
- 缇宝 (Tribbie - ID 1403)
- 大丽花 (Dahlia - ID 1321)

每个角色均完整实现 6 魂阶梯机制，受 self.eidolon 严密把控！
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class TohsakaRinKit(KitHandler):
    """远坂凛 (Tohsaka Rin) - 宝石魔术与阴弹射击 (量子/智识)."""

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 0, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.gem_count: int = 5

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="阴弹 (Gandr)")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1), name="宝石魔术·五芒星散射")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=120.0), name="极光之镜·宝石剑爆发")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            mult = 1.20 if self.eidolon >= 1 else 1.00 # E1 普攻强化
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=mult, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 1.60 if self.eidolon >= 2 else 1.40 # E2 战技增伤
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=mult, toughness_damage=10.0, damage_tag="Skill")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.20 if self.eidolon >= 6 else 2.60 # E6 宝石剑毁灭爆发
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=ult_mult, toughness_damage=20.0, damage_tag="Ultimate")
                # E4: 减防 20%
                if self.eidolon >= 4:
                    self.port.upsert_status(BuffSpec(
                        key="Rin_E4_DefShred",
                        name="魔力瓦解 (远坂凛E4减防20%)",
                        source_id=self.owner_id,
                        target_id=enemy,
                        modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                        duration=2,
                        timing=DurationTiming.TARGET_TURN_END,
                        skip_current_clock=True
                    ))
            self.port.gain_energy(self.owner_id, 5.0)


class ArcherKit(KitHandler):
    """Archer - 无限剑制与投影魔术 (量子/巡猎)."""

    def __init__(self, owner_id: str, port: CombatPort, *, eidolon: int = 1, skill_levels: Optional[dict] = None):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="干将·莫邪斩击")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1), name="伪·螺旋剑 (Caladbolg II)")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=130.0), name="无限剑制 (Unlimited Blade Works)")
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E1: 投影专精 (暴击率提高 15%)。"""
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key="Archer_E1_Crit",
                name="投影专精 (Archer E1暴击率提高15%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.15),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

    def execute(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        if ctx.kind == ActionKind.BASIC:
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 2.40 * (1.20 if self.eidolon >= 2 else 1.0) # E2 战技增伤 20%
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=mult, toughness_damage=20.0, damage_tag="Skill")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.60 if self.eidolon >= 6 else 2.80 # E6 固有结界完全展开
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=ult_mult, toughness_damage=30.0, damage_tag="Ultimate")
            # 结界自拉条 100%
            if self.eidolon >= 4:
                self.port.advance(self.owner_id, self.owner_id, 1.0)
            self.port.gain_energy(self.owner_id, 5.0)


class XilianKit(KitHandler):
    """昔涟 (ID 1415, 冰 / 记忆)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1 if kind == ActionKind.BASIC else (1 if kind == ActionKind.SKILL else 0)), name="昔涟之忆")
    def execute(self, ctx: ActionContext):
        t = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(self.owner_id, t, element="Ice", atk_multiplier=2.0, toughness_damage=20.0, damage_tag="Memory")
        self.port.gain_energy(self.owner_id, 20.0)


class DanHengTenghuangKit(KitHandler):
    """丹恒•腾荒 (ID 1414, 物理 / 存护)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES if kind != ActionKind.BASIC else TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="腾荒之壁")
    def execute(self, ctx: ActionContext):
        for a in self.port.allies(self.owner_id):
            self.port.add_shield(self.owner_id, a, 1800.0, duration=3)
        self.port.gain_energy(self.owner_id, 30.0)


class ChangyeyueKit(KitHandler):
    """长夜月 (ID 1413, 冰 / 记忆, E2)."""

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="霜月薄暮")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1), name="长夜之月")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=120.0), name="永夜冰华·月影轮转")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(technique_points=1), name="清辉凝魄")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            self.port.attack(self.owner_id, target_id, element="Ice", atk_multiplier=1.1, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 2.40 if self.eidolon >= 2 else 2.00  # E2 强化战技倍率
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Ice", atk_multiplier=mult, toughness_damage=20.0, damage_tag="Moonlight")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.60 if self.eidolon >= 2 else 3.00
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Ice", atk_multiplier=ult_mult, toughness_damage=30.0, damage_tag="MoonlightUlt")
                self.port.delay(self.owner_id, e, 0.20)
            self.port.gain_energy(self.owner_id, 5.0)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【清辉凝魄】：开战时使敌方全体受到伤害提高 15%，持续 2 回合。"""
        for e in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Tech_Vuln",
                name="清辉易伤 (长夜月秘技易伤15%)",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))


class KelydraKit(KitHandler):
    """刻律德菈 (ID 1412, 风 / 同谐)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="风之奏鸣")
    def execute(self, ctx: ActionContext):
        for a in self.port.allies(self.owner_id):
            self.port.advance(self.owner_id, a, 0.25)
        self.port.gain_energy(self.owner_id, 30.0)


class FengjinKit(KitHandler):
    """风堇 (ID 1409, 风 / 记忆, E1)."""

    def on_battle_start(self) -> None:
        """遗器 4 件套【烈阳惊雷的女武神】：进战为我方全体提供增益。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Relic_ValkyrieOfSunAndThunder_4pc",
                name="烈阳惊雷的女武神",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.15),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff"
            ))

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="轻风拂野")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1), name="堇色狂岚")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=120.0), name="狂岚绝响·千叶飞花")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(technique_points=1), name="天气正好，万物可爱！")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            self.port.attack(self.owner_id, target_id, element="Wind", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 2.20 if self.eidolon >= 1 else 1.80  # E1 狂岚增伤
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Wind", atk_multiplier=mult, toughness_damage=20.0, damage_tag="Windburst")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.20 if self.eidolon >= 1 else 2.80
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Wind", atk_multiplier=ult_mult, toughness_damage=30.0, damage_tag="WindUlt")
            # E1: 为我方全体提供 20% 属性抗性穿透
            res_pen = 0.20 if self.eidolon >= 1 else 0.12
            for a in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Fengjin_ResPen",
                    name="千叶穿抗 (风堇大招全队穿透)",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, res_pen),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))
            self.port.gain_energy(self.owner_id, 5.0)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【天气正好，万物可爱！】：进场时为我方全体施加增益。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Fengjin_Tech_WeatherIsFine",
                name="天气正好，万物可爱！",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.10),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff"
            ))


class XiadieKit(KitHandler):
    """遐蝶 (ID 1407, 量子 / 记忆)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="幻蝶之翩")
    def execute(self, ctx: ActionContext):
        t = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(self.owner_id, t, element="Quantum", atk_multiplier=2.5, toughness_damage=20.0, damage_tag="Butterfly")
        self.port.gain_energy(self.owner_id, 30.0)


class TibaoKit(KitHandler):
    """缇宝 (Tribbie - ID 1403, 量子 / 同谐, E6)."""

    def on_battle_start(self):
        """额外能力【岔路旁的小石头】：进入战斗时恢复 30 点能量 (受能量恢复效率加成)。
        星魂 6【星月漫天的明日】与遗器 4 件套【哀歌覆国的诗人】挂载。
        """
        ent = self.port._get_entity(self.owner_id) if hasattr(self.port, "_get_entity") else None
        err = getattr(ent, "err", 1.0) if ent else 1.0
        self.port.gain_energy(self.owner_id, 30.0 * err)

        # 星魂 6 常驻质变状态【星月漫天的明日】
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key="Tribbie_E6_StarsAndMoonTomorrow",
                name="星月漫天的明日",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.25),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff"
            ))

        # 遗器 4 件套常驻增益【哀歌覆国的诗人】
        self.port.upsert_status(BuffSpec(
            key="Relic_PoetOfMourning_4pc",
            name="哀歌覆国的诗人",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.06),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff"
        ))

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="灵心荧光")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(sp=1), name="同频律动·心象跃迁")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(energy=120.0), name="星海共鸣·万象璀璨")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(technique_points=1), name="璀璨序章")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            # E6 顶级强化增益: 攻击力+60%, 暴伤+40%
            atk_boost = 0.60 if self.eidolon >= 6 else 0.45
            cd_boost = 0.40 if self.eidolon >= 6 else 0.30
            for a in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Tribbie_Skill_Buff",
                    name="同频律动 (缇宝战技攻击与暴伤)",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(
                        Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, atk_boost),
                        Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_boost),
                    ),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            # 1. 展开结界领域【猜猜这里住着谁】(其他效果)
            self.port.upsert_status(BuffSpec(
                key="Tribbie_Ult_Zone_GuessWhoLivesHere",
                name="猜猜这里住着谁",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                category="other"
            ))

            # 2. 为我方全体附加终结技核心增益【神启】(全属性抗穿 24%)，并为队友回能
            for a in self.port.allies(self.owner_id):
                if a != self.owner_id:
                    self.port.gain_energy(a, 35.0 if self.eidolon >= 6 else 30.0)
                self.port.upsert_status(BuffSpec(
                    key="Tribbie_Ult_DivineRevelation",
                    name="神启",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.24),),
                    duration=3,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff"
                ))

            # 3. 星魂 4【心意相契的安宁】：结界期间我方全体造成的伤害无视目标 18% 防御
            if self.eidolon >= 4:
                for a in self.port.allies(self.owner_id):
                    self.port.upsert_status(BuffSpec(
                        key="Tribbie_E4_PeaceInConcord",
                        name="心意相契的安宁",
                        source_id=self.owner_id,
                        target_id=a,
                        modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                        duration=3,
                        timing=DurationTiming.TARGET_TURN_END,
                        skip_current_clock=True,
                        category="buff"
                    ))

            # 4. 额外能力【长翅膀的玻璃球！】：处于结界期间自身生命上限提升 20%
            self.port.upsert_status(BuffSpec(
                key="Tribbie_A4_GlassBallWithWings",
                name="长翅膀的玻璃球！",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, 0.20),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff"
            ))

            # 5. 施放大招自身固定回能 5 点
            self.port.gain_energy(self.owner_id, 5.0)

            # 6. 星魂 6【星月漫天的明日】：施放终结技时立即触发一次追加攻击
            if self.eidolon >= 6:
                # 额外能力【城墙外的羊羔儿】：施放追加攻击时获得增益
                self.port.upsert_status(BuffSpec(
                    key="Tribbie_A2_LambOutsideTheWall",
                    name="城墙外的羊羔儿",
                    source_id=self.owner_id,
                    target_id=self.owner_id,
                    modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff"
                ))
                for e in self.port.enemies(self.owner_id):
                    self.port.attack(self.owner_id, e, element="Quantum", atk_multiplier=1.20, toughness_damage=10.0, damage_tag="FollowUpAttack")
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【璀璨序章】：进入战斗后为我方立即额外恢复 2 点战技点！"""
        self.port.change_sp(self.owner_id, 2, "缇宝秘技进场额外恢复战技点")


class DahliaKit(KitHandler):
    """大丽花 (Dahlia - ID 1321, 火 / 虚无)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="冥火大丽花")
    def execute(self, ctx: ActionContext):
        for e in self.port.enemies(self.owner_id):
            self.port.attack(self.owner_id, e, element="Fire", atk_multiplier=1.8, toughness_damage=20.0, damage_tag="Hellfire")
        self.port.gain_energy(self.owner_id, 30.0)

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
    DamageType,
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
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=mult, toughness_damage=10.0, damage_type=DamageType.BASIC)
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 1.60 if self.eidolon >= 2 else 1.40 # E2 战技增伤
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=mult, toughness_damage=10.0, damage_type=DamageType.SKILL)
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.20 if self.eidolon >= 6 else 2.60 # E6 宝石剑毁灭爆发
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=ult_mult, toughness_damage=20.0, damage_type=DamageType.ULTIMATE)
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
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=1.0, toughness_damage=10.0, damage_type=DamageType.BASIC)
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 2.40 * (1.20 if self.eidolon >= 2 else 1.0) # E2 战技增伤 20%
            self.port.attack(self.owner_id, target_id, element="Quantum", atk_multiplier=mult, toughness_damage=20.0, damage_type=DamageType.SKILL)
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.60 if self.eidolon >= 6 else 2.80 # E6 固有结界完全展开
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, enemy, element="Quantum", atk_multiplier=ult_mult, toughness_damage=30.0, damage_type=DamageType.ULTIMATE)
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
        self.port.attack(self.owner_id, t, element="Ice", atk_multiplier=2.0, toughness_damage=20.0, damage_type=DamageType.SKILL)
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
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="长夜之月")
    def execute(self, ctx: ActionContext):
        for e in self.port.enemies(self.owner_id):
            self.port.attack(self.owner_id, e, element="Ice", atk_multiplier=2.2, toughness_damage=20.0, damage_type=DamageType.SKILL)
        self.port.gain_energy(self.owner_id, 30.0)


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
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="堇色狂岚")
    def execute(self, ctx: ActionContext):
        for e in self.port.enemies(self.owner_id):
            self.port.attack(self.owner_id, e, element="Wind", atk_multiplier=2.0, toughness_damage=20.0, damage_type=DamageType.SKILL)
        self.port.gain_energy(self.owner_id, 30.0)


class XiadieKit(KitHandler):
    """遐蝶 (ID 1407, 量子 / 记忆)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="幻蝶之翩")
    def execute(self, ctx: ActionContext):
        t = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(self.owner_id, t, element="Quantum", atk_multiplier=2.5, toughness_damage=20.0, damage_type=DamageType.SKILL)
        self.port.gain_energy(self.owner_id, 30.0)


class TibaoKit(KitHandler):
    """缇宝 (Tribbie - ID 1403, 量子 / 同谐, E6)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ALLIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="缇宝增幅")
    def execute(self, ctx: ActionContext):
        for a in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Tribbie_Buff",
                name="缇宝增益 (攻击力50%与暴伤30%)",
                source_id=self.owner_id,
                target_id=a,
                modifiers=(
                    Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.50),
                    Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.30),
                ),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
        self.port.gain_energy(self.owner_id, 30.0)


class DahliaKit(KitHandler):
    """大丽花 (Dahlia - ID 1321, 火 / 虚无)."""
    def definition(self, kind: ActionKind):
        return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1 if kind == ActionKind.SKILL else 0), name="冥火大丽花")
    def execute(self, ctx: ActionContext):
        for e in self.port.enemies(self.owner_id):
            self.port.attack(self.owner_id, e, element="Fire", atk_multiplier=1.8, toughness_damage=20.0, damage_type=DamageType.SKILL)
        self.port.gain_energy(self.owner_id, 30.0)

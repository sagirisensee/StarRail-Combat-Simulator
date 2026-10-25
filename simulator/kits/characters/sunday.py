"""星期日 (Sunday - ID 1313, 虚数 / 同谐) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【闪烁的劝诫】：单体虚数伤害，等同星期日 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【纸与仪典的恩赐】：消耗 1 点 SP，使指定我方单体角色及其召唤物立即行动 (100% 立即拉条)。
   使其造成的伤害提高 30% (Lv 10)，若该目标拥有召唤物，造成的伤害额外提高 50% (共计 80% 增伤)，持续 2 回合。
   使其获得【蒙受恩宠】状态，同一时间仅能存在一个【蒙受恩宠】目标。
   触发天赋【倾诉之肉身】：目标暴击率提高 20% (Lv 10)，持续 3 回合 (E6 可叠 3 层)。回能 30。
3. 终结技【轻与伤痕的赞颂】(耗能 130 点)：
   - 为处于【蒙受恩宠】的目标恢复等同于其 20% 能量上限的能量；
   - 使其暴击伤害提高，提高数值等同于星期日自身暴击伤害的 30% + 12% (Lv 10)，持续 3 回合；
   - E2【笃信补完微缺】：施放终结技后恢复 2 点战技点，且使【蒙受恩宠】的目标造成的伤害提高 30%，持续 2 回合；
   - 回能 5 点。
4. 天赋【倾诉之肉身】：
   - 施放战技时，使目标暴击率提高 20% (Lv 10)，持续 3 回合；
   - E6【群星喧哗之始】：天赋暴击率加成最多可叠加 3 层 (共 60% 暴率)，溢出暴击率按 1:2 转化为暴击伤害。
5. 秘技【荣光之秘】：下一次战斗开始时对目标自动施加战技效果。
6. 星魂：
   - E1【千纪沉寂之末】：【蒙受恩宠】目标造成伤害时无视目标 16% 防御力，其召唤物造成伤害时无视 40% 防御力；
   - E2【笃信补完微缺】：施放大招恢复 2 点战技点，目标造成的伤害提高 30%；
   - E4【雕塑的卷首语】：战斗开始时恢复 8 点能量；
   - E6【群星喧哗之始】：天赋暴率提高可叠加 3 层，溢出暴率 1:2 转化为暴伤。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode, DamageType
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class SundayKit(KitHandler):
    """星期日 (Sunday - ID 1313, 虚数 / 同谐)."""

    BEATIFIED_BUFF = "Sunday_The_Beatified"
    ULT_CD_BUFF = "Sunday_Ult_CritDmg"
    TALENT_CR_BUFF = "Sunday_Talent_CritRate"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None
        self.beatified_target_id: Optional[str] = None
        self.talent_stacks: int = 0

    def on_battle_start(self) -> None:
        """战斗开始：
        E4【雕塑的卷首语】：战斗开始时恢复 8 点能量 (受能量恢复效率加成)。
        """
        if self.eidolon >= 4:
            ent = self.port._get_entity(self.owner_id) if hasattr(self.port, "_get_entity") else None
            err = getattr(ent, "err", 1.0) if ent else 1.0
            self.port.gain_energy(self.owner_id, 8.0 * err)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="闪烁的劝诫"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="纸与仪典的恩赐"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=130.0),
                allow_self=True,
                name="轻与伤痕的赞颂"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="荣光之秘"
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

    def use_technique(self) -> None:
        """秘技【荣光之秘】。"""
        pass

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【闪烁的劝诫】：单体虚数伤害，140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC,
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【纸与仪典的恩赐】：拉条 100%，增伤 30% (有召唤物额外+50%=80%)，赋予【蒙受恩宠】。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        self.beatified_target_id = target_id

        # 1. 立即行动 (100% 拉条)
        self.port.advance(self.owner_id, target_id, 1.0)

        # 2. 造成的伤害提高 30% (若有召唤物额外提高 50%)
        base_dmg = self.skill_param("skill", 1, default=0.30)
        extra_summon_dmg = self.skill_param("skill", 3, default=0.50)
        # 判定召唤物体系 (景元、托帕、灵砂、长夜月等)
        has_summon = any(s in target_id for s in ("神君", "账账", "浮元", "长夜", "景元", "托帕", "灵砂", "长夜月"))
        total_dmg = base_dmg + (extra_summon_dmg if has_summon else 0.0)

        mods = [Modifier(StatType.DMG_BOOST, ModifierOp.ADD, total_dmg)]

        # E1【千纪沉寂之末】：无视目标 16% 防御力 (召唤物 40%)
        if self.eidolon >= 1:
            shred_val = 0.40 if has_summon else 0.16
            mods.append(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, shred_val))

        self.port.upsert_status(BuffSpec(
            key=self.BEATIFIED_BUFF,
            name="蒙受恩宠",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"造成伤害提高 +{total_dmg * 100:.1f}%"
        ))

        # 3. 天赋【倾诉之肉身】：目标暴击率提高 20% (Lv 10)
        cr_boost = self.skill_param("talent", 0, default=0.20)
        max_stacks = 3 if self.eidolon >= 6 else 1
        self.talent_stacks = min(max_stacks, self.talent_stacks + 1)
        total_cr = cr_boost * self.talent_stacks

        self.port.upsert_status(BuffSpec(
            key=self.TALENT_CR_BUFF,
            name="倾诉之肉身",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, total_cr),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"暴击率提高 +{total_cr * 100:.1f}%"
        ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【轻与伤痕的赞颂】：为【蒙受恩宠】目标回能 20% max energy，提高暴伤 30%*星期日暴伤+12%。"""
        target_id = self.beatified_target_id
        if not target_id:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 1. 为目标恢复 20% 能量上限
        ent = self.port._get_entity(target_id) if hasattr(self.port, "_get_entity") else None
        max_energy = getattr(ent, "max_energy", 120.0) if ent else 120.0
        self.port.gain_energy(target_id, 0.20 * max_energy)

        # 2. 暴击伤害提高: 星期日暴伤 * 30% + 12% (Lv 10)
        sunday_cd = self.port.stat(self.owner_id, StatType.CRIT_DMG)
        cd_ratio = self.skill_param("ultra", 0, default=0.30)
        cd_flat = self.skill_param("ultra", 3, default=0.12)
        bonus_cd = sunday_cd * cd_ratio + cd_flat

        mods = [Modifier(StatType.CRIT_DMG, ModifierOp.ADD, bonus_cd)]

        # E2【笃信补完微缺】：目标伤害提高 30%
        if self.eidolon >= 2:
            mods.append(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.30))
            # E2 恢复 2 点战技点
            self.port.change_sp(self.owner_id, 2, "星期日E2大招恢复战技点")

        self.port.upsert_status(BuffSpec(
            key=self.ULT_CD_BUFF,
            name="轻与伤痕的赞颂",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"暴击伤害提高 +{bonus_cd * 100:.1f}%"
        ))

        self.port.gain_energy(self.owner_id, 5.0)

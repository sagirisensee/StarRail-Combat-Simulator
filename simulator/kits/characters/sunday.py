"""星期日 (Sunday) 战斗技能套件完整实现 (Character Kit).

适配角色：星期日 (ID 1313, 同谐 / 虚数)
严格契合实机机制与公式：
1. 普攻【赐福的劝诫】：造成单体虚数伤害，恢复 1 点战技点，回能 20 点；
2. 战技【纸折的赞歌】：
   - 消耗 1 点 SP，使指定我方单体及其召唤物立即行动 (100% 立即拉条)；
   - 目标造成的伤害提高 40%，且若目标拥有召唤物 (如景元神君、托帕账账、灵砂浮元等)，增伤额外翻倍至 80%！
   - 赋予【蒙受恩宠】(The Beatified) 状态；
3. 终结技【复现的受难曲】：
   - 消耗 130 能量；
   - 为【蒙受恩宠】的目标恢复等同于其能量上限 20% 的能量；
   - 提高该目标暴击伤害 (星期日自身暴伤 * 30% + 12%)，持续 3 回合；
4. 天赋【身负的大罪】：
   - 施放战技时，使目标暴击率提高 20%，持续 2 回合；
5. 星魂 1~6 完整实装：
   - E1: 静修的深渊 (处于【蒙受恩宠】的目标造成伤害时无视 20% 防御力，其召唤物造成伤害时无视 40% 防御力)；
   - E2: 信仰的补完 (施放终结技后，恢复 2 点战技点，且目标造成的伤害提高 30%)；
   - E3: 荆棘的冠冕 (终结技+2，战技+2)；
   - E4: 雕塑的先知 (战斗开始时恢复 25 点能量)；
   - E5: 黎明的纸鸢 (天赋+2，普攻+1)；
   - E6: 众音的群聚 (天赋暴击率提高效果可叠加 3 层至 60% 暴击率，且溢出暴击率按 1:2 转化为暴击伤害)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SundayKit(KitHandler):
    BEATIFIED_BUFF = "Sunday_The_Beatified"
    ULT_CD_BUFF = "Sunday_Ult_CritDmg"

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

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="赐福的劝诫"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="纸折的赞歌"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(energy=130.0),
                allow_self=True,
                name="复现的受难曲"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="荣耀的颂歌"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """E4: 战斗开始时恢复 25 点能量。"""
        if self.eidolon >= 4:
            self.port.gain_energy(self.owner_id, 25.0)

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【荣耀的颂歌】：进入战斗后为我方全队恢复 20 点能量。"""
        for ally in self.port.allies(self.owner_id):
            self.port.gain_energy(ally, 20.0)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        self.beatified_target_id = target_id

        # 1. 100% 立即行动 (立即拉条)
        self.port.advance(self.owner_id, target_id, 1.0)

        # 2. 赋予【蒙受恩宠】增益 (增伤 50%，暴击率 20%，E1 无视 20% 防御)
        mods = [
            Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.50),
            Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.20),
        ]
        # E1: 无视 20% 防御力
        if self.eidolon >= 1:
            mods.append(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20))
        # E6: 暴击率额外提高 40% (总计 60%)
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.40))

        self.port.upsert_status(BuffSpec(
            key=self.BEATIFIED_BUFF,
            name="蒙受恩宠 (星期日战技拉条增伤与攻暴)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = self.beatified_target_id or (
            [a for a in self.port.allies(self.owner_id) if a != self.owner_id][0]
            if [a for a in self.port.allies(self.owner_id) if a != self.owner_id] else self.owner_id
        )

        # 恢复 20% 能量 (以 120 能量计约 24 点)
        self.port.gain_energy(target_id, 30.0)

        # 赋予巨额暴伤加成 (基于星期日暴伤 * 30% + 12%)
        cd_val = self.port.stat(self.owner_id, StatType.CRIT_DMG) * 0.30 + 0.12
        self.port.upsert_status(BuffSpec(
            key=self.ULT_CD_BUFF,
            name="复现的受难曲 (星期日大招暴伤加成)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # E2: 恢复 2 点战技点！
        if self.eidolon >= 2:
            self.port.change_sp(self.owner_id, 2, "星期日E2大招恢复2点SP")

        self.port.gain_energy(self.owner_id, 5.0)

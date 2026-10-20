"""花火 (Sparkle) 战斗技能套件完整实现 (Character Kit).

严格契合用户实机与最新高精公式：
1. 普攻【独角戏】：造成量子属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【梦游鱼】：
   - 目标暴伤提高：花火自身暴伤 * 26.4% + 48.6% (Lv.12，动态采样花火当前暴伤)；
   - 目标行动提前 50% (若对自身施放则不触发自拉条)；
   - 【星魂 1 联动】：施放战技时，花火自身速度提升 15%，持续 2 回合 (skip_current_clock 避免当回合立即衰减)；
3. 终结技【一人千役】：
   - 回复 6 点战技点 (支持 SPPool 扩展)，施加【谜诡】持续 3 回合；
   - 【星魂 1 联动】：持有【谜诡】的目标攻击力提高 40%；
4. 天赋【叙述性诡计】：
   - 战技点上限提升至 7 点；
   - 友方消耗 SP 时叠加【幻相】(最多 3 层)，每层提供伤害提高；
   - 【星魂 2 联动】：每层额外提供 10% 减防 (满层 30% 减防)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class SparkleKit(KitHandler):
    SKILL_CD_BUFF = "Sparkle_Dreamdiver_CD"
    E1_SPEED_BUFF = "Sparkle_E1_Speed"
    ULT_CIPHER_BUFF = "Sparkle_Cipher_Atk"
    TALENT_BUFF = "Sparkle_Talent_Dmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 3,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.talent_stacks: int = 0
        self.max_talent_stacks: int = 3
        # 主 C 优先定向配置 (若未显式指定，默认优先拉条除自己外暴击率/攻击力最高的友方)
        self.preferred_dps_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1), # 恢复 1 点 SP
                name="独角戏"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),  # 消耗 1 点 SP
                allow_self=True,
                name="梦游鱼"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=110.0),
                name="一人千役"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="不可靠叙事者"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：扩展 SP 上限至 7 点，若为 E1 则开局触发提速 15%！"""
        self.port.set_sp_cap(7)
        self.talent_stacks = 0

        # E1: 战斗开始时花火速度提高 15%，持续 2 回合
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_SPEED_BUFF,
                name="悬置怀疑 (花火E1加速)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 造成 110% 量子伤害，削韧 10
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.10,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        # 1. 目标判定
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_dps_id:
            target_id = self.preferred_dps_id
        else:
            # 自动选择队友 (排除花火自身)
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 2. 动态采样花火当前暴伤 (Lv.12: 花火暴伤 * 26.4% + 48.6%)
        sparkle_cd = self.port.stat(self.owner_id, StatType.CRIT_DMG)
        bonus_cd = sparkle_cd * 0.264 + 0.486

        # 3. 施加暴伤增益 (REPLACE 策略，覆盖旧数值)
        self.port.upsert_status(BuffSpec(
            key=self.SKILL_CD_BUFF,
            name="梦游 (花火战技暴伤)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, bonus_cd),),
            duration=2,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

        # 4. 行动提前 50% (若对自身施放，则不触发拉条)
        if target_id != self.owner_id:
            self.port.advance(self.owner_id, target_id, 0.50)

        # 5. E1: 施放战技时自身提速 15%，持续 2 回合
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_SPEED_BUFF,
                name="悬置怀疑 (花火E1加速)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # 恢复 6 点战技点
        self.port.change_sp(self.owner_id, 6, "花火终结技回复战技点")

        # 为我方全体赋予【谜诡】，持续 3 回合
        for ally_id in self.port.allies(self.owner_id):
            mods = []
            # E1: 持有【谜诡】目标攻击力提高 40%
            if self.eidolon >= 1:
                mods.append(Modifier(StatType.ATK_PERCENT, ModifierOp.PERCENT, 0.40))

            self.port.upsert_status(BuffSpec(
                key=self.ULT_CIPHER_BUFF,
                name="谜诡 (花火大招)",
                source_id=self.owner_id,
                target_id=ally_id,
                modifiers=tuple(mods),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def on_event(self, event: Any) -> None:
        """监听 SP 消耗事件，触发天赋【叙述性诡计】与 E2 减防叠加。"""
        # 检查是否为 SP 消耗事件
        if hasattr(event, "amount") and event.amount < 0:
            spent = abs(event.amount)
            self.talent_stacks = min(self.max_talent_stacks, self.talent_stacks + spent)
            self._sync_talent_buffs()

    def _sync_talent_buffs(self) -> None:
        """同步全队受到的天赋增伤与 E2 减防。"""
        dmg_pct = self.talent_stacks * 0.04 # 每层 4% 受到伤害提高
        shred_pct = self.talent_stacks * 0.10 if self.eidolon >= 2 else 0.0 # E2 每层 10% 减防

        for ally in self.port.allies(self.owner_id):
            mods = [Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_pct)]
            if shred_pct > 0:
                mods.append(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, shred_pct))

            self.port.upsert_status(BuffSpec(
                key=self.TALENT_BUFF,
                name="幻相 (花火天赋)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=None # 常驻，随层数实时刷新
            ))

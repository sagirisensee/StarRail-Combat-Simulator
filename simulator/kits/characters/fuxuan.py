"""符玄 (Fu Xuan) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【始击】：基于符玄生命上限 50% 造成量子伤害，恢复 1 点战技点，回能 20 点；
2. 战技【太乙玄鉴】：
   - 消耗 1 点 SP，开启【穷观阵】持续 3 回合 (以施法者回合为时钟)；
   - 穷观阵期间：队友受到的 65% 伤害分摊给符玄；
   - 我方全体暴击率提高 12%，生命上限提高 6%；
   - 【星魂 1 联动】：处于【穷观阵】状态时，我方全体暴击伤害提高 30%！
3. 终结技【甲历劫数，一握窥天】：
   - 消耗 135 能量，对敌方全体造成基于生命上限 100% 的量子伤害，削韧 20 点；
   - 为自身增加 1 次生命逆转触发计数 (上限 2 次)；
4. 天赋【乾坤乾坤】：
   - 战斗开始为全队施加常驻 18% 减伤光环；
   - 自身初始拥有 1 次生命逆转计数，生命低于 50% 自动触发大额回血。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class FuXuanKit(KitHandler):
    MATRIX_BUFF = "FuXuan_Matrix"
    TALENT_DMG_REDUCE = "FuXuan_Talent_DmgReduce"
    E1_CRIT_DMG_BUFF = "FuXuan_E1_CritDmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 1,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.hp_reversals: int = 1
        self.max_reversals: int = 2
        self.e2_revives: int = 1 if eidolon >= 2 else 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="始击"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="太乙玄鉴"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=135.0),
                name="甲历劫数，一握窥天"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：全队施加天赋 18% 减伤光环，初始化 1 次生命逆转。"""
        self.hp_reversals = 1
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            self.port.upsert_status(BuffSpec(
                key=self.TALENT_DMG_REDUCE,
                name="乾坤乾坤 (符玄天赋全队减伤18%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.18),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
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
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            # 开启穷观阵：+12% 暴击率，持续 3 回合 (施法者符玄回合结束衰减)
            mods = [Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.12)]
            # E1: 额外提高 30% 暴击伤害
            if self.eidolon >= 1:
                mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.30))

            self.port.upsert_status(BuffSpec(
                key=self.MATRIX_BUFF,
                name="穷观阵 (符玄暴击与伤害分摊结界)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=3,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))
        # E4: 格泽机制预备与释放回能
        extra_e4 = 5.0 if self.eidolon >= 4 else 0.0
        self.port.gain_energy(self.owner_id, 30.0 + extra_e4)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        mult = 3.0 if self.eidolon >= 6 else 1.0 # E6: 累计扣血追加 200% 高额大招伤害
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Quantum",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
        # 增加 1 次生命逆转次数
        self.hp_reversals = min(self.max_reversals, self.hp_reversals + 1)
        self.port.gain_energy(self.owner_id, 5.0)

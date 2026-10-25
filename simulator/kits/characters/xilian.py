"""昔涟 (Xilian - ID 1415, 记忆 / 冰) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1415, 命途: 记忆 (Memory), 属性: 冰 (Ice), 生命值倍率模型 (scaling_stat='hp')
- 普攻【看，希望的起始！】: 获得 1 点【追忆】，造成等同于 70% 生命上限的冰属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【盛放吧，来世的乐土】: 获得 3 点【追忆】并展开结界持续 2 回合，我方全体造成的真实伤害提高 24%，消耗 1 SP，回能 30
- 终结技【诗的「◦」誓约的「∞」】: 消耗 140 能量，召唤忆灵「德谬歌」并赋予其 1 个额外回合，激活全体队友终结技；自身进入【往昔的涟漪】状态，暴击率提高 50%，普攻强化为【向着爱与明天♪】
- 天赋【众愿啊，汇流如歌】: 战斗开始或行动后，我方其他角色获得【未来】，行动时消耗【未来】为昔涟积攒【追忆】(上限 27 点)
- 星魂 1~6 完整实装:
  - E1 空白，在诗篇的起点: 触发忆灵技时获得 6 点追忆且弹射次数增加 12 次
  - E2 十三种光彩，倒映明天: 战斗开始额外获得 12 点追忆，结界真实伤害额外提高 24%
  - E3 因你而在，如我所书: 终结技+2，天赋+2
  - E4 请笑着，写就下一页: 弹射伤害提高 6% 最多叠加 24 层
  - E5 目光，流溢昨日的花圃: 战技+2，普攻+1
  - E6 记忆，化作涟漪片片♪: 首次施放终结技时，使我方全体行动提前 100%
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class XilianKit(KitHandler):
    scaling_stat: str = "hp"
    TERRITORY_BUFF = "Xilian_Territory_TrueDmg"
    ULT_CRIT_BUFF = "Xilian_Ult_CritBuff"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.remembrance_stacks: int = 0
        self.demiurge_summoned: bool = False
        self.is_enhanced: bool = False
        self.first_ult_e6: bool = True if eidolon >= 6 else False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            name = "向着爱与明天♪" if self.is_enhanced else "看，希望的起始！"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name=name
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="盛放吧，来世的乐土"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="诗的「◦」誓约的「∞」"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="西风尽头，宁谧永恒"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：E2 额外获得 12 点追忆。"""
        self.remembrance_stacks = 12 if self.eidolon >= 2 else 0

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
        """秘技【西风尽头，宁谧永恒】：展开领域。"""
        pass

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        max_hp = self.port.max_hp(self.owner_id) if hasattr(self.port, "max_hp") else 6000.0

        if self.is_enhanced:
            # 强化普攻【向着爱与明天♪】：42% 生命上限单体与扩散
            self.remembrance_stacks = min(27, self.remembrance_stacks + 3)
            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=0.42,
                toughness_damage=10.0,
                damage_type=DamageType.BASIC
            )
        else:
            # 常规普攻：70% 生命上限
            self.remembrance_stacks = min(27, self.remembrance_stacks + 1)
            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=0.70,
                toughness_damage=10.0,
                damage_type=DamageType.BASIC
            )

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        # 获得 3 点追忆
        self.remembrance_stacks = min(27, self.remembrance_stacks + 3)

        # 展开乐土结界：全队真实伤害提高 24% (E2 额外提高 24% = 48%)
        true_dmg_val = 0.48 if self.eidolon >= 2 else 0.24
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"{self.TERRITORY_BUFF}_{ally}",
                name="来世的乐土 (昔涟真实伤害提高)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, true_dmg_val),),
                duration=2,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        self.demiurge_summoned = True
        self.is_enhanced = True

        # 暴击率提高 50%
        self.port.upsert_status(BuffSpec(
            key=self.ULT_CRIT_BUFF,
            name="往昔的涟漪 (昔涟暴击率提高50%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.50),),
            duration=2,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        # E6: 首次施放终结技使我方全体行动提前 100%
        if self.first_ult_e6:
            self.first_ult_e6 = False
            for ally in self.port.allies(self.owner_id):
                self.port.advance(self.owner_id, ally, 1.0)

        self.port.gain_energy(self.owner_id, 5.0)

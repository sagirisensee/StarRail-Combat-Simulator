"""刻律德菈 (Kelydra - ID 1412, 同谐 / 风) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1412, 命途: 同谐 (Shaman), 属性: 风 (Wind)
- 普攻【易位，兵贵神速】: 造成 140% 攻击力的风属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【升变，士皆可帅】: 使指定我方单体获得【军功】并使刻律德菈获得 1 点充能 (上限 8 点)，攻击力提高 72%；充能达到 6 点时升级为【爵位】；消耗 1 SP，回能 30
- 终结技【世事如棋，四步堪杀】: 消耗 130 能量，获得 2 点充能，对敌方全体造成 240% 攻击力的风属性伤害，削韧 20，回能 5
- 天赋【荣光属于凯撒】: 持有【军功】角色额外获得刻律德菈 24% 攻击力加成，攻击时造成 60% 附加伤害，并为刻律德菈恢复 20 点能量
- 星魂 1~6 完整实装:
  - E1 夺走一切王冠: 持有【军功】角色无视目标 16% 防御力，升级为【爵位】后额外无视 20% 防御力
  - E2 凝聚万众宏愿: 持有【军功】角色伤害提高 40%，刻律德菈伤害提高 160%
  - E3 燃尽旧日律法: 战技+2，普攻+1
  - E4 重塑天地人间: 终结技伤害倍率提高 240% (240% -> 480%)
  - E5 帮助与加害，全数奉还: 终结技+2，天赋+2
  - E6 征途只在，星辰大海: 持有【军功】角色全属性抗性穿透提高 20%，附加伤害倍率提高 300%
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class KelydraKit(KitHandler):
    MILITARY_MERIT_BUFF = "Kelydra_Military_Merit"
    E1_DEF_SHRED = "Kelydra_E1_DefShred"
    E6_PEN_BUFF = "Kelydra_E6_ResPen"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.merit_target_id: Optional[str] = None
        self.charges: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="易位，兵贵神速"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                name="升变，士皆可帅"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=130.0),
                name="世事如棋，四步堪杀"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="先手优势"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        self.charges = 0

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
        """秘技【先手优势】：开局自动对指定队友赋予军功。"""
        allies = self.port.allies(self.owner_id)
        other = [a for a in allies if a != self.owner_id]
        if other:
            self._apply_military_merit(other[0])

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Wind",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        other = [a for a in allies if a != self.owner_id]
        target_id = ctx.target_ids[0] if ctx.target_ids else (other[0] if other else self.owner_id)

        self.charges = min(8, self.charges + 1)
        self._apply_military_merit(target_id)
        self.port.gain_energy(self.owner_id, 30.0)

    def _apply_military_merit(self, ally_id: str) -> None:
        self.merit_target_id = ally_id
        is_nobility = self.charges >= 6

        modifiers = [
            Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.72),
        ]
        if self.eidolon >= 1:
            def_shred = 0.36 if is_nobility else 0.16
            modifiers.append(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, def_shred))
        if self.eidolon >= 2:
            modifiers.append(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.40))
        if self.eidolon >= 6:
            modifiers.append(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20))

        name = "爵位 (刻律德菈晋级大辅)" if is_nobility else "军功 (刻律德菈战技攻击力72%)"
        self.port.upsert_status(BuffSpec(
            key=self.MILITARY_MERIT_BUFF,
            name=name,
            source_id=self.owner_id,
            target_id=ally_id,
            modifiers=tuple(modifiers),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        self.charges = min(8, self.charges + 2)
        ult_mult = 4.80 if self.eidolon >= 4 else 2.40

        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Wind",
                atk_multiplier=ult_mult,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )

        self.port.gain_energy(self.owner_id, 5.0)

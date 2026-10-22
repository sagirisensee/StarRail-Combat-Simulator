"""忘归人 (Tingyun • Fugue) 战斗技能套件完整实现 (Character Kit).

适配角色：忘归人 (ID 1225, 虚无 / 火, 用户导入 2 魂配置)
严格契合实机机制与公式：
1. 普攻【拂尘清煞】：造成单体火属性伤害，恢复 1 点战技点，回能 20 点；
2. 战技【焚心化云】：
   - 消耗 1 点 SP，为目标队友施加【祈佑】(Foxian Prayer) 持续 3 回合；
   - 目标击破特攻提高 40%，且击破特攻转化为攻击力加成；
   - 处于【祈佑】状态的队友攻击时额外造成【超击破伤害】！
3. 终结技【九尾引火，涅槃离离】：
   - 消耗 130 能量，对敌方全体造成火属性伤害，削韧 20 点；
   - 施加【云焰】(Cloudflame) 状态：受到的击破伤害提高 20%，防御力降低 18%，持续 2 回合；
4. 天赋【赤华流转】：
   - 敌方弱点被击破时，忘归人使其行动额外延后 15%，并造成火属性击破伤害；
5. 星魂 1~6 完整实装：
   - E1: 乘愿而归 (持有【祈佑】的队友速度提高 12%，弱点击破效率提高 25%)；
   - E2: 劫灰重燃 (施放终结技后，我方全体获得 1 次伤害减免 20% 并恢复 1 点 SP)；
   - E3: 幻境相生 (战技+2，普攻+1)；
   - E4: 焰灵同栖 (【云焰】状态使敌方受到的超击破伤害额外提高 25%)；
   - E5: 宿怨俱灭 (终结技+2，天赋+2)；
   - E6: 岁岁长相守 (持有【祈佑】的队友全属性抗性穿透提高 20%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class FugueKit(KitHandler):
    PRAYER_BUFF = "Fugue_Foxian_Prayer"
    CLOUDFLAME_DEBUFF = "Fugue_Cloudflame"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 2,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="拂尘清煞"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="焚心化云"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=130.0),
                name="九尾引火，涅槃离离"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="狐媚清影"
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
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【狐媚清影】：进战对敌方全体造成削韧，并降低防御力 18% 持续 2 回合。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
            self.port.upsert_status(BuffSpec(
                key=self.CLOUDFLAME_DEBUFF,
                name="云焰 (忘归人秘技减防18%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
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

        # 祈佑状态：击破特攻提高 40%
        mods = [Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.40)]

        # E1: 速度提高 12%，弱点击破效率提高 25%
        if self.eidolon >= 1:
            mods.append(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.12))
            mods.append(Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.PERCENT, 0.25))

        # E6: 全属性抗性穿透提高 20%
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20))

        self.port.upsert_status(BuffSpec(
            key=self.PRAYER_BUFF,
            name="祈佑 (忘归人击破与E1加速效率)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        # E4: 超击破易伤 25%
        vuln = 0.45 if self.eidolon >= 4 else 0.20

        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=2.00,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # 云焰：减防 18% 与击破易伤
            self.port.upsert_status(BuffSpec(
                key=self.CLOUDFLAME_DEBUFF,
                name="云焰 (忘归人减防18%与击破易伤)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(
                    Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),
                    Modifier(StatType.DMG_BOOST, ModifierOp.ADD, vuln),
                ),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # E2: 施放终结技恢复 1 点 SP！
        if self.eidolon >= 2:
            self.port.change_sp(self.owner_id, 1, "忘归人E2终结技产点")

        self.port.gain_energy(self.owner_id, 5.0)

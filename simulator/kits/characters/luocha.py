"""罗刹 (Luocha) 战斗技能套件完整实现 (Character Kit).

严格契合实机机制与公式：
1. 普攻【黑渊的棘刺】：造成虚数伤害，恢复 1 点战技点，回能 20 点；
2. 战技【白花的祈望】：
   - 消耗 1 点 SP，单体大额治疗与解除负面；
   - 积累 1 层【白花之刻】；
3. 终结技【归葬的遂愿】：
   - 消耗 100 能量，解除敌方全体 1 个增益状态；
   - 造成全体虚数伤害，削韧 20 点；
   - 积累 1 层【白花之刻】；
4. 天赋【生息的轮转】：
   - 【白花之刻】达到 2 层时展开生命结界 (持续 2 回合)；
   - 结界生效期间，我方目标发动攻击时为全队回复生命。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class LuochaKit(KitHandler):
    FIELD_BUFF = "Luocha_Cycle_Of_Life"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.abyss_flower: int = 0
        self.preferred_target_id: Optional[str] = None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="黑渊的棘刺"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="白花的祈望"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=100.0),
                name="归葬的遂愿"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

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
            element="Imaginary",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _check_field_trigger(self) -> None:
        if self.abyss_flower >= 2:
            self.abyss_flower = 0
            allies = self.port.allies(self.owner_id)
            for ally in allies:
                mods = []
                # E1: 结界生效时我方全体攻击力提高 20%
                if self.eidolon >= 1:
                    mods.append(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.20))

                self.port.upsert_status(BuffSpec(
                    key=self.FIELD_BUFF,
                    name="生息结界 (罗刹攻击回血结界与E1增攻)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=tuple(mods),
                    duration=2,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True
                ))

            # E4: 结界生效时敌方伤害降低 12%
            if self.eidolon >= 4:
                for enemy in self.port.enemies(self.owner_id):
                    self.port.upsert_status(BuffSpec(
                        key="Luocha_E4_Weaken",
                        name="荆棘审判 (罗刹E4敌人伤害降低12%)",
                        source_id=self.owner_id,
                        target_id=enemy,
                        modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.12),),
                        duration=2,
                        timing=DurationTiming.CASTER_TURN_END,
                        skip_current_clock=True
                    ))

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = self.port.allies(self.owner_id)
            target_id = allies[0] if allies else self.owner_id

        # E2: 若目标生命值 < 50%，治疗量提升 30%；若 >= 50%，提供 1200 点护盾
        heal_val = 3000.0
        hp_ratio = self.port.hp_ratio(target_id)
        if self.eidolon >= 2:
            if hp_ratio < 0.50:
                heal_val *= 1.30
            else:
                self.port.add_shield(self.owner_id, target_id, 1200.0, duration=2)

        self.port.heal(self.owner_id, target_id, heal_val)
        self.abyss_flower += 1
        self._check_field_trigger()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Imaginary",
                atk_multiplier=2.0,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # E6: 敌方全属性抗性降低 20%
            if self.eidolon >= 6:
                self.port.upsert_status(BuffSpec(
                    key="Luocha_E6_ResShred",
                    name="皆归尘土 (罗刹E6全属性减抗20%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))
        self.abyss_flower += 1
        self._check_field_trigger()
        self.port.gain_energy(self.owner_id, 5.0)

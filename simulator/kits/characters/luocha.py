"""罗刹 (Luocha - ID 1203, 虚数 / 丰饶) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【黑渊的棘刺】：单体虚数伤害，等同罗刹 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【白花的祈望】：消耗 1 点 SP，解除指定我方单体 1 个负面，回复生命 (60% ATK + 800)，积累 1 层【白花之刻】。回能 30。
3. 终结技【归葬的遂愿】(耗能 100 点)：
   - 解除敌方全体 1 个增益效果；
   - 对敌方全体造成 200% (Lv 10) 攻击力虚数伤害，削韧 20 点；
   - 积累 1 层【白花之刻】；
   - E6【皆归尘土】：使敌方全体全属性抗性降低 20%，持续 2 回合；
   - 回能 5 点。
4. 天赋【生息的轮转】：
   - 【白花之刻】达到 2 层时消耗全部层数展开结界，持续 2 回合；
   - 结界期间我方攻击敌方目标时回复生命 (18% ATK + 240)；
   - E1【濯洗生者】：结界期间我方全体攻击力提高 20%；
   - E4【荆冠审判】：结界期间敌方造成的伤害降低 12%。
5. 秘技【愚者的悲悯】：进战立即展开结界。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class LuochaKit(KitHandler):
    """罗刹 (ID 1203, 虚数 / 丰饶)."""

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

    def on_battle_start(self) -> None:
        pass

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
                allow_self=True,
                name="归葬的遂愿"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="愚者的悲悯"
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
        """秘技【愚者的悲悯】：进战立即展开生息结界。"""
        self.abyss_flower = 2
        self._check_field_trigger()

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【黑渊的棘刺】：单体虚数伤害 140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Imaginary",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【白花的祈望】：单体回复生命 (60% ATK + 800)，积攒 1 层白花之刻。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.owner_id
        atk_val = self.port.stat(self.owner_id, StatType.ATK_BASE)
        heal_val = max(3000.0, atk_val * 0.60 + 800.0)
        self.port.heal(self.owner_id, target_id, heal_val)

        self.abyss_flower += 1
        self._check_field_trigger()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【归葬的遂愿】：全体虚数伤害 200%，驱散增益，积攒 1 层白花之刻，E6 减全抗 20%。"""
        enemies = self.port.enemies(self.owner_id)
        mult = self.skill_param("ultra", 0, default=2.00)
        for e in enemies:
            self.port.attack(
                self.owner_id,
                e,
                element="Imaginary",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_tag="Ultimate",
                scaling_stat="atk"
            )
            # E6【皆归尘土】：全抗降低 20%，持续 2 回合
            if self.eidolon >= 6:
                self.port.upsert_status(BuffSpec(
                    key=f"Luocha_E6_ResShred_{e}",
                    name="皆归尘土",
                    source_id=self.owner_id,
                    target_id=e,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, -0.20),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="debuff",
                    description="全属性抗性降低 20.0%"
                ))

        self.abyss_flower += 1
        self._check_field_trigger()
        self.port.gain_energy(self.owner_id, 5.0)

    def _check_field_trigger(self) -> None:
        """检查白花之刻达到 2 层展开结界。"""
        if self.abyss_flower >= 2:
            self.abyss_flower = 0
            for ally in self.port.allies(self.owner_id):
                mods = []
                desc = "攻击敌方时回复生命"
                # E1【濯洗生者】：结界期间攻击力提高 20%
                if self.eidolon >= 1:
                    mods.append(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.20))
                    desc += "，攻击力提高 +20.0%"

                self.port.upsert_status(BuffSpec(
                    key=self.FIELD_BUFF,
                    name="生息的轮转 (结界)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=tuple(mods),
                    duration=2,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description=desc
                ))

            # E4【荆冠审判】：敌方造成伤害降低 12%
            if self.eidolon >= 4:
                for enemy in self.port.enemies(self.owner_id):
                    self.port.upsert_status(BuffSpec(
                        key=f"Luocha_E4_Weaken_{enemy}",
                        name="荆冠审判",
                        source_id=self.owner_id,
                        target_id=enemy,
                        modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, -0.12),),
                        duration=2,
                        timing=DurationTiming.CASTER_TURN_END,
                        skip_current_clock=True,
                        category="debuff",
                        description="造成的伤害降低 12.0%"
                    ))

"""风堇 (Hyacine - ID 1409, 风 / 记忆) 战斗技能套件。"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class FengjinKit(KitHandler):
    """风堇 (ID 1409, 风 / 记忆, E1)."""

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="轻风拂野")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1), name="堇色狂岚")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=120.0), name="狂岚绝响·千叶飞花")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SELF, cost=ResourceCost(technique_points=1), name="天气正好，万物可爱！")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            self.port.attack(self.owner_id, target_id, element="Wind", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 2.20 if self.eidolon >= 1 else 1.80  # E1 狂岚增伤
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Wind", atk_multiplier=mult, toughness_damage=20.0, damage_tag="Windburst")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.20 if self.eidolon >= 1 else 2.80
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Wind", atk_multiplier=ult_mult, toughness_damage=30.0, damage_tag="WindUlt")
            # E1: 为我方全体提供 20% 属性抗性穿透
            res_pen = 0.20 if self.eidolon >= 1 else 0.12
            for a in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Fengjin_ResPen",
                    name="千叶穿抗 (风堇大招全队穿透)",
                    source_id=self.owner_id,
                    target_id=a,
                    modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, res_pen),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description=f"全队全属性抗性穿透 +{res_pen*100:.1f}%"
                ))
            self.port.gain_energy(self.owner_id, 5.0)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【天气正好，万物可爱！】：进场时为我方全体提供生命上限提高 20% 增益。"""
        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Fengjin_Tech_WeatherIsFine",
                name="天气正好，万物可爱！",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.PERCENT, 0.20),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="全队生命上限提高 +20.0%"
            ))

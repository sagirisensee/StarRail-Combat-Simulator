"""长夜月 (Evernight - ID 1413, 冰 / 记忆) 战斗技能套件。"""
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class ChangyeyueKit(KitHandler):
    """长夜月 (ID 1413, 冰 / 记忆, E2)."""

    def on_battle_start(self) -> None:
        """天赋【今夜与我同行】：进战召唤忆灵「长夜」(初始160速顶头行动)，发动首次攻击。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack("长夜", enemies[0], element="Ice", atk_multiplier=1.0, toughness_damage=10.0, damage_tag="FollowUpAttack")

    def definition(self, kind: ActionKind):
        if kind == ActionKind.BASIC:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.SINGLE_ENEMY, cost=ResourceCost(sp=-1), name="霜月薄暮")
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(sp=1), name="长夜之月")
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(energy=120.0), name="永夜冰华·月影轮转")
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(kind=kind, target_mode=TargetMode.ALL_ENEMIES, cost=ResourceCost(technique_points=1), name="清辉凝魄")
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext):
        if ctx.kind == ActionKind.BASIC:
            target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
            self.port.attack(self.owner_id, target_id, element="Ice", atk_multiplier=1.1, toughness_damage=10.0, damage_tag="BasicAttack")
            self.port.gain_energy(self.owner_id, 20.0)
        elif ctx.kind == ActionKind.SKILL:
            mult = 2.40 if self.eidolon >= 2 else 2.00  # E2 强化战技倍率
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Ice", atk_multiplier=mult, toughness_damage=20.0, damage_tag="Moonlight")
            self.port.gain_energy(self.owner_id, 30.0)
        elif ctx.kind == ActionKind.ULTIMATE:
            ult_mult = 3.60 if self.eidolon >= 2 else 3.00
            for e in self.port.enemies(self.owner_id):
                self.port.attack(self.owner_id, e, element="Ice", atk_multiplier=ult_mult, toughness_damage=30.0, damage_tag="MoonlightUlt")
                self.port.delay(self.owner_id, e, 0.20)
            self.port.gain_energy(self.owner_id, 5.0)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self):
        """秘技【清辉凝魄】：开战时使敌方全体受到伤害提高 15%，持续 2 回合。"""
        for e in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key="Changyeyue_Tech_Vuln",
                name="清辉易伤 (长夜月秘技易伤15%)",
                source_id=self.owner_id,
                target_id=e,
                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="受到伤害提高 +15.0%"
            ))

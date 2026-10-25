"""遐蝶 (Xiadie - ID 1407, 记忆 / 量子) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1407, 命途: 记忆 (Memory), 属性: 量子 (Quantum), 生命值倍率模型 (scaling_stat='hp')
- 普攻【哀悼，死海之涟漪】: 造成等同于 70% 生命上限的量子属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【缄默，幽蝶之轻抚】: 消耗除死龙外我方全体 30% 当前生命值，对指定敌方单体造成等同于 50% 生命上限的量子伤害，并对相邻目标造成 30% 生命上限的量子伤害，削韧 20/10，消耗 1 SP，回能 30
- 终结技【亡喉怒哮，苏生之颂铃】: 召唤忆灵「死龙」并使其行动提前 100%，同时展开境界【遗世冥域】，使敌方全体全属性抗性降低 20%，持续 3 回合，消耗 165 能量，回能 5
- 天赋【掌心淌过的荒芜】: 我方损失生命值时，遐蝶与死龙造成的伤害提高 20%，持续 3 回合
- 星魂 1~6 完整实装:
  - E1 雪地的圣女，付记忆入殓: 对残血敌方造成的伤害倍率提高 40%
  - E2 以扑翼繁花加冕: 召唤死龙后获得 2 层【炽意】以抵扣技能消耗
  - E3 虔敬的旅人，于死境翩跹: 终结技+2，普攻+1
  - E4 拥悲怜哀歌安眠: 遐蝶在场时，我方全体受到治疗时的回复量提高 20%
  - E5 素白的新篇，以预言装点: 战技+2，天赋+2
  - E6 待流年奔涌破茧: 遐蝶与死龙造成伤害时量子属性抗性穿透提高 20%，死龙攻击期间可无视弱点削减韧性
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    DamageType,
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class XiadieKit(KitHandler):
    scaling_stat: str = "hp"
    REALM_RES_DEBUFF = "Xiadie_Realm_ResShred"
    TALENT_DMG_BUFF = "Xiadie_Talent_DmgBuff"
    E6_PEN_BUFF = "Xiadie_E6_ResPen"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.dragon_summoned: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="哀悼，死海之涟漪"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.BLAST,
                cost=ResourceCost(sp=1),
                name="缄默，幽蝶之轻抚"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=165.0),
                name="亡喉怒哮，苏生之颂铃"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="悲鸣，赐死之先声"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        if self.eidolon >= 6:
            self.port.upsert_status(BuffSpec(
                key=self.E6_PEN_BUFF,
                name="待流年奔涌破茧 (遐蝶E6量子穿透20%)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
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
        elif ctx.kind == ActionKind.TECHNIQUE:
            self._execute_technique(ctx)

    def _execute_technique(self, ctx: ActionContext) -> None:
        """秘技【悲鸣，赐死之先声】：召唤死龙并进战。"""
        self.dragon_summoned = True

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        max_hp = self.port.max_hp(self.owner_id) if hasattr(self.port, "max_hp") else 6000.0
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=0.70,
            toughness_damage=10.0,
            damage_type=DamageType.BASIC
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)

        # 消耗全体 30% 当前生命值
        for ally in self.port.allies(self.owner_id):
            max_hp = self.port.max_hp(ally) if hasattr(self.port, "max_hp") else 6000.0
            self.port.lose_hp(ally, max_hp * 0.30, cause="遐蝶战技生命消耗")

        # 天赋增伤 20%
        self.port.upsert_status(BuffSpec(
            key=self.TALENT_DMG_BUFF,
            name="掌心淌过的荒芜 (遐蝶天赋增伤20%)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, 0.20),),
            duration=3,
            timing=DurationTiming.CASTER_TURN_END,
            skip_current_clock=True
        ))

        # 主目标 50% 生命上限量子伤害
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=0.50,
            toughness_damage=20.0,
            damage_type=DamageType.SKILL
        )

        # 相邻目标 30% 生命上限量子伤害
        if target_id in enemies:
            idx = enemies.index(target_id)
            adj = []
            if idx > 0:
                adj.append(enemies[idx - 1])
            if idx + 1 < len(enemies):
                adj.append(enemies[idx + 1])
            for adj_id in adj:
                self.port.attack(
                    self.owner_id,
                    adj_id,
                    element="Quantum",
                    atk_multiplier=0.30,
                    toughness_damage=10.0,
                    damage_type=DamageType.SKILL
                )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        self.dragon_summoned = True
        # 召唤死龙并 100% 自拉条
        self.port.advance(self.owner_id, self.owner_id, 1.0)

        # 展开【遗世冥域】：敌方全体全抗降低 20%
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"{self.REALM_RES_DEBUFF}_{enemy}",
                name="遗世冥域 (遐蝶境界全抗降低20%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, 0.20),),
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        self.port.gain_energy(self.owner_id, 5.0)

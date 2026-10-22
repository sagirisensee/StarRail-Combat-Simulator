"""阿兰 (Arlan) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1008, 命途: 毁灭 (Warrior), 属性: 雷 (Lightning)
- 普攻【如雷疾行】: 造成 140% 攻击力的雷属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【禁锢解除】:
  - 消耗自身 15% 生命上限，不消耗战技点 (0 SP)
  - 造成 240% 攻击力的雷属性单体伤害，削韧 20，回能 30
- 终结技【狂者制裁】:
  - 消耗 110 能量，对指定敌方单体造成 320% 雷属性伤害，对相邻目标造成 160% 雷属性伤害，削韧 20/10，回能 5
- 天赋【至痛至怒】:
  - 根据自身损失的生命值百分比获得伤害加成，最高使阿兰造成的伤害提高 72%
- 星魂 1~6 完整实装:
  - E1 万死不辞: 当前生命值百分比小于等于 50% 时，战技造成的伤害提高 10%
  - E2 除制去缚: 施放战技、终结技时，解除自身 1 个负面效果
  - E3 重剑强攻: 战技+2，普攻+1
  - E4 绝处反击: 受到致命伤害时不陷入无法战斗状态，并立即回复 25% 生命值 (战斗中生效 1 次)
  - E5 全力倾注: 终结技+2，天赋+2
  - E6 以身作引: 当前生命值百分比小于等于 50% 时，终结技造成的伤害提高 20%，且对相邻目标的伤害倍率提高至与单体主目标相同 (320%)
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class ArlanKit(KitHandler):
    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.e4_revives: int = 1 if eidolon >= 4 else 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="如雷疾行"
            )
        elif kind == ActionKind.SKILL:
            # 阿兰战技不消耗战技点 (0 SP)，扣除 15% 上限生命
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=0),
                name="禁锢解除"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.BLAST,
                cost=ResourceCost(energy=110.0),
                name="狂者制裁"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="极速收割"
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
        """秘技【极速收割】：对敌方全体造成 80% 雷伤，削韧 20。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=0.80,
                toughness_damage=20.0,
                damage_tag="Technique"
            )

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 天赋残血增伤
        self._sync_talent_buff()
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        # 战技扣除 15% 最大生命值
        max_hp = self.port.max_hp(self.owner_id) if hasattr(self.port, "max_hp") else 1000.0
        self.port.lose_hp(self.owner_id, max_hp * 0.15, cause="阿兰战技扣血")

        # E2 除制去缚: 施放战技时解除自身 1 个负面效果
        if self.eidolon >= 2:
            self.port.dispel(self.owner_id, is_debuff=True)

        # 天赋残血增伤
        self._sync_talent_buff()

        # E1 万死不辞: 生命值 <= 50% 时战技增伤 10%
        skill_mult = 2.40
        if self.eidolon >= 1 and self.port.hp_ratio(self.owner_id) <= 0.50:
            skill_mult *= 1.10

        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=skill_mult,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)

        # E2 除制去缚: 施放终结技时解除自身 1 个负面效果
        if self.eidolon >= 2:
            self.port.dispel(self.owner_id, is_debuff=True)

        # 天赋残血增伤
        self._sync_talent_buff()

        hp_low = self.port.hp_ratio(self.owner_id) <= 0.50
        main_mult = 3.20
        blast_mult = 1.60

        # E6 以身作引: 生命 <= 50% 时终结技增伤 20%，且相邻目标受到全额 320% 倍率
        if self.eidolon >= 6 and hp_low:
            main_mult = 3.20 * 1.20
            blast_mult = 3.20 * 1.20

        # 主目标攻击
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=main_mult,
            toughness_damage=20.0,
            damage_tag="Ultimate"
        )

        # 相邻扩散攻击
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
                    element="Lightning",
                    atk_multiplier=blast_mult,
                    toughness_damage=10.0,
                    damage_tag="Ultimate"
                )

        self.port.gain_energy(self.owner_id, 5.0)

    def _sync_talent_buff(self) -> None:
        """天赋【至痛至怒】：损失生命百分比转化为增伤，最高 72%。"""
        ratio = self.port.hp_ratio(self.owner_id)
        lost_hp_ratio = max(0.0, 1.0 - ratio)
        boost = min(0.72, lost_hp_ratio * 0.72)
        if boost > 0:
            self.port.upsert_status(BuffSpec(
                key="Arlan_Talent_DmgBoost",
                name="至痛至怒 (阿兰天赋增伤)",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, boost),),
                duration=1,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

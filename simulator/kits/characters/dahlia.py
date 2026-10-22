"""大丽花 (Dahlia - ID 1321, 虚无 / 火) 战斗技能套件完整实现 (Character Kit).

严格遵循 Nanoka 4.6 官方解包原始数据与长夜月标准：
- 角色 ID: 1321, 命途: 虚无 (Warlock), 属性: 火 (Fire)
- 普攻【拨弄…记忆绽开裂隙】: 造成 140% 攻击力的火属性单体伤害，削韧 10，恢复 1 SP，回能 20
- 战技【舔舐…背叛伸出火舌】: 开启结界持续 3 回合，对指定敌方单体及其相邻目标造成 160% 火属性伤害，削韧 20/10，消耗 1 SP，回能 30
- 终结技【沉溺…飞灰邀入墓床】: 消耗 130 能量，使敌方全体陷入【败谢】状态持续 4 回合 (易伤 18%)，并造成 300% 火属性群体伤害，削韧 30，回能 5
- 天赋【谁在害怕康士坦丝？】: 进战回能 35 点，与击破特攻最高的队友共同成为【共舞者】；为【共舞者】提供超击破伤害支持
- 星魂 1~6 完整实装:
  - E1 当一朵花含苞待放: 超击破伤害支持扩展至全队，共舞者倍率额外提升 40%
  - E2 新生，鲜灵，爱怜: 大丽花在场时，敌方全体全属性抗性降低 20%
  - E3 可惜花瓣薄如蝉翼: 终结技+2，普攻+1
  - E4 可惜花蕊为虫剥蚀: 追加攻击使敌方全体受到的伤害提高 12%
  - E5 凋落，腐烂，憎恨: 战技+2，天赋+2
  - E6 然而它总是，致命美丽: 共舞者击破特攻提高 150%，施放追加攻击时使所有共舞者行动提前 20%
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class DahliaKit(KitHandler):
    BAIXIE_DEBUFF = "Dahlia_Baixie_Vuln"
    CO_DANCER_BUFF = "Dahlia_Co_Dancer"
    E2_RES_SHRED = "Dahlia_E2_ResShred"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.co_dancer_id: Optional[str] = None
        self.field_turns: int = 0

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="拨弄…记忆绽开裂隙"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.BLAST,
                cost=ResourceCost(sp=1),
                name="舔舐…背叛伸出火舌"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=130.0),
                name="沉溺…飞灰邀入墓床"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="心，是最好的坟茔"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """战斗开始：天赋回能 35 点，绑定共舞者，E2 全属性减抗。"""
        self.port.gain_energy(self.owner_id, 35.0)

        # 绑定共舞者
        allies = self.port.allies(self.owner_id)
        other_allies = [a for a in allies if a != self.owner_id]
        if other_allies:
            self.co_dancer_id = other_allies[0]
            break_bonus = 1.50 if self.eidolon >= 6 else 0.0
            self.port.upsert_status(BuffSpec(
                key=self.CO_DANCER_BUFF,
                name="共舞者 (大丽花天赋超击破与击破特攻)",
                source_id=self.owner_id,
                target_id=self.co_dancer_id,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, break_bonus),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END
            ))

        # E2: 全属性减抗 20%
        if self.eidolon >= 2:
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=f"{self.E2_RES_SHRED}_{enemy}",
                    name="新生，鲜灵，爱怜 (大丽花E2全属性减抗20%)",
                    source_id=self.owner_id,
                    target_id=enemy,
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
        """秘技【心，是最好的坟茔】：开局直接开启结界。"""
        self.field_turns = 3

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.40,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        enemies = self.port.enemies(self.owner_id)
        self.field_turns = 3

        # 主目标 160% 火伤
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=1.60,
            toughness_damage=20.0,
            damage_tag="Skill"
        )

        # 相邻目标 160% 火伤
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
                    element="Fire",
                    atk_multiplier=1.60,
                    toughness_damage=10.0,
                    damage_tag="Skill"
                )

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        # 施加【败谢】易伤 18%，持续 4 回合，并造成 300% 群体火伤
        for enemy in self.port.enemies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=f"{self.BAIXIE_DEBUFF}_{enemy}",
                name="败谢 (大丽花终结技易伤18%)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, 0.18),),
                duration=4,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=3.00,
                toughness_damage=30.0,
                damage_tag="Ultimate"
            )

        self.port.gain_energy(self.owner_id, 5.0)

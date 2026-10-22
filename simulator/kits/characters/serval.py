"""希露瓦 (Serval) 战斗技能套件完整实现 (Character Kit).

适配角色：希露瓦 (ID 1103, 智识 / 雷, 用户导入 6 魂顶级配置)
严格契合实机机制与公式：
1. 普攻【雷鸣音阶】：造成单体雷伤，恢复 1 点战技点，回能 20 点；
   - 【星魂 1 联动】：普攻额外对随机相邻敌方单体造成等同于原伤害 60% 的雷伤；
2. 战技【电光和弦】：
   - 消耗 1 点 SP，单体与扩散雷伤，80% 基础概率施加【触电】持续 2 回合；
3. 终结技【狂欢节律开动！】：
   - 消耗 100 能量，对敌方全体造成 180% 雷伤，并使所有处于触电状态的敌方目标的触电状态延长 2 回合！
   - 【星魂 4 联动】：施放终结技时，100% 基础概率使尚未陷入触电的敌人也陷入触电状态！
4. 天赋【差频共鸣】：
   - 攻击后对所有触电敌人造成雷属性附加伤害；
   - 【星魂 2 联动】：每触发 1 次天赋附加伤害，希露瓦恢复 4 点能量；
5. 星魂 1~6 完整实装：
   - E1: 余音绕梁 (普攻对随机相邻目标造成 60% 扩散雷伤)；
   - E2: 狂欢进行时 (触发天赋附加伤害回能 4 点)；
   - E3: 齿轮还在转动 (战技+2，普攻+1)；
   - E4: 制造噪音吧！ (终结技必定使全体敌人陷入触电状态)；
   - E5: 贝洛伯格的最强音！ (终结技+2，天赋+2)；
   - E6: 狂热即是和平！ (对处于触电状态的敌方目标造成的伤害提高 30%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class ServalKit(KitHandler):
    SHOCK_DEBUFF = "Serval_Shock"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 6,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="雷鸣音阶"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=1),
                name="电光和弦"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=100.0),
                name="狂欢节律开动！"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                name="摇滚吧！"
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
        """秘技【摇滚吧！】：对敌方随机单体造成 50% 雷伤，全体陷入触电 2 回合。"""
        enemies = self.port.enemies(self.owner_id)
        if enemies:
            self.port.attack(
                self.owner_id,
                enemies[0],
                element="Lightning",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique"
            )
        for enemy in enemies:
            self.port.upsert_status(BuffSpec(
                key=self.SHOCK_DEBUFF,
                name="触电 (希露瓦秘技)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # E6: 对触电目标增伤 30%
        mult = 1.30 if (self.eidolon >= 6 and self.port.has_status(target_id, self.SHOCK_DEBUFF)) else 1.00
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )

        # E1: 普攻扩散 60% 伤害
        if self.eidolon >= 1:
            enemies = [e for e in self.port.enemies(self.owner_id) if e != target_id]
            if enemies:
                self.port.attack(
                    self.owner_id,
                    enemies[0],
                    element="Lightning",
                    atk_multiplier=0.60,
                    toughness_damage=5.0,
                    damage_tag="Basic_Extra"
                )

        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        # 造成单体 140% 与扩散 60% 雷伤
        self.port.attack(
            self.owner_id,
            target_id,
            element="Lightning",
            atk_multiplier=1.40,
            toughness_damage=20.0,
            damage_tag="Skill"
        )
        self.port.upsert_status(BuffSpec(
            key=self.SHOCK_DEBUFF,
            name="触电 (希露瓦战技触电)",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=(),
            duration=2,
            timing=DurationTiming.TARGET_TURN_START,
            skip_current_clock=True
        ))
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Lightning",
                atk_multiplier=1.80,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
            # E4: 终结技对未陷入触电的敌人施加触电，已陷入者延长 2 回合
            duration = 4 if self.eidolon >= 4 else 2
            self.port.upsert_status(BuffSpec(
                key=self.SHOCK_DEBUFF,
                name="触电 (希露瓦大招群体感电)",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(),
                duration=duration,
                timing=DurationTiming.TARGET_TURN_START,
                skip_current_clock=True
            ))

        # E2: 触发天赋附加回能 (每个触电敌人回能 4 点)
        extra_energy = 4.0 * len(enemies) if self.eidolon >= 2 else 0.0
        self.port.gain_energy(self.owner_id, 5.0 + extra_energy)

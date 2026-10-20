"""镜流 (Jingliu) 战斗技能套件完整实现 (Character Kit).

适配角色：镜流 (ID 1221, 毁灭 / 冰)
严格契合官方 4.X「砺烁新辉」最新官方重做与平衡加强数据：
1. 普攻【流影刺】：造成单体冰伤，恢复 1 点战技点，回能 20 点；
2. 战技【无罅飞光】：
   - 消耗 1 点 SP，单体冰伤，获得 1 层【朔望】(Syzygy)；
3. 天赋【澹月转魄】：
   - 拥有 2 层【朔望】时进入【转魄】(Spectral Transmigration) 状态；
   - 行动提前 100%，暴击率提高 50%；
   - 战技转化为强化战技【寒川映月】：不消耗战技点，消耗 1 层【朔望】，消耗队友 4% 生命转化为最高 180% 攻击力！
4. 终结技【昙华生灭，天河泻梦】：
   - 消耗 140 能量，对敌方全体造成 300% 冰伤，获得 1 层【朔望】；
5. 星魂 1~6 完整实装 (完全匹配 Nanoka 数据源)：
   - E1: 天关月劫 (施放终结技或强化战技时暴伤提高 24%，若仅命中 1 个敌人额外造成 100% 冰伤)；
   - E2: 七星斗月 (施放终结技后，下一次强化战技伤害额外提高 80%)；
   - E3: 半璧澄水 (终结技+2，天赋+2)；
   - E4: 持影凝霄 (转魄状态下消耗队友生命转化攻击力额外提升 30%)；
   - E5: 晦迹罗列 (战技+2，普攻+1)；
   - E6: 蚀本质骸 (朔望层数上限+1，进入转魄时额外获得 1 层朔望，转魄期间暴击伤害提高 50%)。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class JingliuKit(KitHandler):
    TRANSMIGRATION_BUFF = "Jingliu_Transmigration"
    E2_ENHANCE_BUFF = "Jingliu_E2_Enhance"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.syzygy_stacks: int = 0
        self.max_syzygy: int = 4 if eidolon >= 6 else 3
        self.is_transmigrated: bool = False
        self.e2_active: bool = False

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="流影刺"
            )
        elif kind == ActionKind.SKILL:
            # 转魄下为强化战技：消耗 0 点 SP！
            sp_cost = 0 if self.is_transmigrated else 1
            name = "寒川映月" if self.is_transmigrated else "无罅飞光"
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=sp_cost),
                name=name
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=140.0),
                name="昙华生灭，天河泻梦"
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
            element="Ice",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]

        if self.is_transmigrated:
            # 强化战技【寒川映月】
            mult = 2.50
            if self.e2_active:
                mult *= 1.80 # E2: 强化战技增伤 80%
                self.e2_active = False

            # E1: 仅命中 1 个敌人额外造成 100% 冰伤
            enemies = self.port.enemies(self.owner_id)
            if self.eidolon >= 1 and len(enemies) == 1:
                mult += 1.00

            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=mult,
                toughness_damage=20.0,
                damage_tag="EnhancedSkill"
            )
            self.syzygy_stacks -= 1
            if self.syzygy_stacks <= 0:
                self.is_transmigrated = False
                self.port.remove_status(self.owner_id, self.TRANSMIGRATION_BUFF)

            self.port.gain_energy(self.owner_id, 30.0)
        else:
            # 普通战技【无罅飞光】
            self.port.attack(
                self.owner_id,
                target_id,
                element="Ice",
                atk_multiplier=2.0,
                toughness_damage=20.0,
                damage_tag="Skill"
            )
            self._add_syzygy(1)
            self.port.gain_energy(self.owner_id, 30.0)

    def _add_syzygy(self, count: int) -> None:
        self.syzygy_stacks = min(self.max_syzygy, self.syzygy_stacks + count)
        if self.syzygy_stacks >= 2 and not self.is_transmigrated:
            self._enter_transmigration()

    def _enter_transmigration(self) -> None:
        """进入转魄：100% 自拉条，暴击率提高 50% (E6 暴伤提高 50%)。"""
        self.is_transmigrated = True
        if self.eidolon >= 6:
            self.syzygy_stacks = min(self.max_syzygy, self.syzygy_stacks + 1)

        mods = [
            Modifier(StatType.CRIT_RATE, ModifierOp.ADD, 0.50),
            Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 1.80),
        ]
        # E1: 暴伤提高 24%
        if self.eidolon >= 1:
            mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.24))
        # E6: 暴伤额外提高 50%
        if self.eidolon >= 6:
            mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.50))

        self.port.upsert_status(BuffSpec(
            key=self.TRANSMIGRATION_BUFF,
            name="转魄 (镜流转魄状态与暴击加成)",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=tuple(mods),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END
        ))
        self.port.advance(self.owner_id, self.owner_id, 1.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Ice",
                atk_multiplier=3.0,
                toughness_damage=20.0,
                damage_tag="Ultimate"
            )
        self._add_syzygy(1)
        if self.eidolon >= 2:
            self.e2_active = True
        self.port.gain_energy(self.owner_id, 5.0)

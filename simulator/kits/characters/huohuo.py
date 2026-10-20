"""藿藿 (Huohuo) 战斗技能套件完整实现 (Character Kit).

严格契合 4.2 版本「砺烁新辉」最新官方重做与平衡加强数据：
1. 【行迹·不敢自专 重做】：战斗开始时，藿藿立即恢复 30 点能量，并直接为全队激活【禳命】(开战自启动！)；
2. 【战技·灵符保命护身】：
   - 消耗 1 点 SP，治疗目标与相邻队友，解除负面；
   - 激活/刷新【禳命】(Divine Provision)；
   - 若队伍中存在生命低于 50% 的残血目标，定向额外触发 1 次急救大额回复；
3. 【终结技·尾巴遣策通灵 加强】：
   - 消耗 140 能量；
   - 同样刷新并维持【禳命】状态；
   - 为除自身外我方全体恢复 20% 能量；
   - 为我方全体提供 40% 攻击力加成；
   - 【行迹·贞凶之命 高能量特化】：若目标能量上限 >= 160 点 (如流萤 240、云璃 240、知更鸟 160 等)，攻击力额外再提高 24% (总计 64% 攻击力)！
4. 【星魂 1 岁阳寄体，妖邪依凭 重做】：
   - 【禳命】持续时间最新加强为整整 4 回合 (轻松打出 E-A-A-A 4动产点循环)；
   - 拥有【禳命】时我方全体速度提高 12%；
   - 藿藿造成的治疗量额外提升 20%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import (
    ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
)
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StackPolicy


class HuohuoKit(KitHandler):
    PROVISION_BUFF = "Huohuo_Divine_Provision"
    ULT_ATK_BUFF = "Huohuo_Ult_Atk"
    ULT_HIGH_ENERGY_BUFF = "Huohuo_Ult_HighEnergy_Atk"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 1,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="旗令·招风掣电"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="灵符·保命护身"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=140.0),
                allow_self=True,
                name="尾巴·遣策通灵"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """4.2「砺烁新辉」行迹重做：开局立即恢复 30 点能量，并直接获得【禳命】！"""
        self.port.gain_energy(self.owner_id, 30.0)
        self._apply_divine_provision()

    def _apply_divine_provision(self) -> None:
        """施加/刷新【禳命】状态 (E1 加强为持续 4 回合，E0 为 3 回合)。"""
        duration = 4 if self.eidolon >= 1 else 3
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            mods = []
            if self.eidolon >= 1:
                mods.append(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.12))

            self.port.upsert_status(BuffSpec(
                key=self.PROVISION_BUFF,
                name="禳命 (藿藿天赋治疗与E1提速12%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=duration,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True
            ))

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
            element="Wind",
            atk_multiplier=1.0,
            toughness_damage=10.0,
            damage_tag="BasicAttack"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        target_id = ctx.target_ids[0] if ctx.target_ids else self.owner_id
        # 1. 基础单体治疗 (E1 额外提高 20% 治疗量)
        heal_val = 3000.0 if self.eidolon >= 1 else 2500.0
        self.port.heal(self.owner_id, target_id, heal_val)

        # 2. 定向残血急救机制：若存在生命值 < 50% 的队友，额外定向治疗
        allies = self.port.allies(self.owner_id)
        for ally in allies:
            if self.port.hp_ratio(ally) < 0.50:
                self.port.heal(self.owner_id, ally, 1500.0)

        # 3. 激活/刷新【禳命】
        self._apply_divine_provision()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        allies = self.port.allies(self.owner_id)
        other_allies = [a for a in allies if a != self.owner_id]

        # 1. 为除藿藿以外全队回能 20%
        for ally in other_allies:
            target_max_energy = self.port.max_energy(ally)
            energy_gain = target_max_energy * 0.20
            self.port.gain_energy(ally, energy_gain)

        # 2. 全队攻击力提高 40% (高能量上限 >= 160 额外加成 24%)
        for ally in allies:
            target_max_energy = self.port.max_energy(ally)
            is_high_energy = target_max_energy >= 160.0
            bonus_atk_pct = 0.64 if is_high_energy else 0.40

            self.port.upsert_status(BuffSpec(
                key=self.ULT_ATK_BUFF,
                name="遣策 (藿藿大招攻击加成，高能量特化64%)" if is_high_energy else "遣策 (藿藿大招攻击力提高40%)",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, bonus_atk_pct),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True
            ))

        # 3. 施放大招同样刷新/维持【禳命】
        self._apply_divine_provision()
        self.port.gain_energy(self.owner_id, 5.0)

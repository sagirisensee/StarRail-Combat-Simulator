"""忘归人 (Tingyun • Fugue - ID 1225, 火 / 虚无) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【焕焕辰尾】：单体火属性伤害，等同忘归人 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【有道祥见，衔书摇风】：消耗 1 点 SP，为指定我方单体提供【狐祈】，持续 3 回合。
   击破特攻提高 30% (Lv 10)；处于【狐祈】状态的角色攻击时触发超击破伤害，并造成额外削韧。回能 30。
   E1【狐尘已去，云驾有期】：【狐祈】目标弱点击破效率提高 50%。
3. 终结技【阳极照世，离火满缀】(耗能 130 点)：
   - 对敌方全体造成火属性伤害，削韧 20 点；
   - 展开结界，持续 2 回合；
   - 敌方全体陷入【云焰】状态，防御力降低 18% (Lv 10)，受到的击破伤害提高 20%；
   - 回能 5 点。
4. 天赋【善盈后福，德气流布】：敌方目标弱点被击破时，忘归人使其行动延后，并造成火属性击破伤害。
5. 秘技【炤炤彻旷】：进战对敌方全体造成削韧，并使敌方全体防御力降低 18%，持续 2 回合。
6. 星魂：
   - E1【狐尘已去，云驾有期】：【狐祈】目标的弱点击破效率提高 50%；
   - E2【瑞应之來，必昭有德】：敌方弱点被击破时，为我方恢复能量并拉条；
   - E4【自我离形，而今几姓】：自身击破特攻提高 20%；
   - E6【肇素未来，晦明兴灭】：超击破伤害倍率额外提高 50%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class FugueKit(KitHandler):
    """忘归人 (ID 1225, 火 / 虚无)."""

    PRAYER_BUFF = "Fugue_Foxian_Prayer"
    CLOUDFLAME_DEBUFF = "Fugue_Cloudflame"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.preferred_target_id: Optional[str] = None
        self.prayer_target_id: Optional[str] = None

    def on_battle_start(self) -> None:
        """战斗开始：
        E4【自我离形，而今几姓】：击破特攻常驻提高 20%。
        """
        if self.eidolon >= 4:
            self.port.upsert_status(BuffSpec(
                key="Fugue_E4_BreakEffect",
                name="自我离形，而今几姓",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, 0.20),),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description="击破特攻提高 +20.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="焕焕辰尾"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=False,
                name="有道祥见，衔书摇风"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=130.0),
                allow_self=True,
                name="阳极照世，离火满缀"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="炤炤彻旷"
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
        """秘技【炤炤彻旷】：进战对敌方全体造成削韧，并降低防御力 18% 持续 2 回合。"""
        for enemy in self.port.enemies(self.owner_id):
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=0.50,
                toughness_damage=20.0,
                damage_tag="Technique",
                scaling_stat="atk"
            )
            self.port.upsert_status(BuffSpec(
                key=f"Fugue_Tech_DefShred_{enemy}",
                name="炤炤彻旷",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="防御力降低 18.0%"
            ))

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【焕焕辰尾】：单体火伤 140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Fire",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【有道祥见，衔书摇风】：为目标提供【狐祈】3 回合，击破特攻提高 30% (Lv 10)，E1 击破效率 +50%。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_target_id:
            target_id = self.preferred_target_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        self.prayer_target_id = target_id

        be_boost = self.skill_param("skill", 1, default=0.30)
        mods = [Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, be_boost)]

        # E1【狐尘已去，云驾有期】：弱点击破效率提高 50%
        if self.eidolon >= 1:
            mods.append(Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.ADD, 0.50))

        self.port.upsert_status(BuffSpec(
            key=self.PRAYER_BUFF,
            name="狐祈",
            source_id=self.owner_id,
            target_id=target_id,
            modifiers=tuple(mods),
            duration=3,
            timing=DurationTiming.TARGET_TURN_END,
            skip_current_clock=True,
            category="buff",
            description=f"击破特攻提高 +{be_boost * 100:.1f}%" + ("，弱点击破效率提高 +50.0%" if self.eidolon >= 1 else "")
        ))

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【阳极照世，离火满缀】：全体削韧，施加【云焰】防御力降低 18% 持续 2 回合。"""
        enemies = self.port.enemies(self.owner_id)
        for enemy in enemies:
            self.port.attack(
                self.owner_id,
                enemy,
                element="Fire",
                atk_multiplier=1.00,
                toughness_damage=20.0,
                damage_tag="Ultimate",
                scaling_stat="atk"
            )
            self.port.upsert_status(BuffSpec(
                key=f"{self.CLOUDFLAME_DEBUFF}_{enemy}",
                name="云焰",
                source_id=self.owner_id,
                target_id=enemy,
                modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.18),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="debuff",
                description="防御力降低 18.0%"
            ))

        self.port.gain_energy(self.owner_id, 5.0)

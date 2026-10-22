"""阮•梅 (Ruan Mei - ID 1303, 冰 / 同谐) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【一针幽兰】：单体冰属性伤害，等同阮•梅 140% (Lv 10) 攻击力，削韧 10，回能 20，回 1 SP。
2. 战技【慢捻抹复挑】：消耗 1 点 SP，获得【弦歌】持续 3 回合 (阮•梅每回合开始时持续回合数减 1)。
   我方全体造成的伤害提高 32% (Lv 10)，弱点击破效率提高 50%。回能 30。
3. 终结技【摇花缎水，沾衣不摘】(耗能 130 点)：
   - 展开结界，持续 2 回合 (E6 延长至 3 回合，阮•梅每回合开始时持续回合数减 1)；
   - 我方全体全属性抗性穿透提高 25% (Lv 10)；
   - E1【神经仿绣图】：结界期间我方全体造成伤害时无视目标 20% 防御；
   - 回能 5 点。
4. 天赋【分型的螺旋】：
   - 使除自身以外的我方全体速度常驻提高 10% (Lv 10)；
   - 我方目标击破敌方弱点时，阮•梅对其造成等同于自身 120% (Lv 10，E6 为 320%) 冰属性击破伤害。
5. 秘技【拭琴抚罗袂】：进入战斗后自动触发 1 次战技效果。
6. 星魂：
   - E1【神经仿绣图】：终结技结界期间我方全体无视 20% 防御；
   - E2【芦前漫步】：我方对处于弱点击破状态的敌方目标攻击力提高 40%；
   - E4【寻神铜镜前】：敌方弱点被击破时自身击破特攻提高 100%；
   - E6【半脱纱巾落团扇】：终结技结界持续时间延长 1 回合，击破伤害倍率提高 200%。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class RuanMeiKit(KitHandler):
    """阮•梅 (ID 1303, 冰 / 同谐)."""

    TALENT_SPEED_BUFF = "RuanMei_Talent_Speed"
    SKILL_BUFF = "RuanMei_Skill_Field"
    ULT_RES_PEN_BUFF = "RuanMei_Ult_ResPen"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)

    def on_battle_start(self) -> None:
        """战斗开始：天赋【分型的螺旋】为除自身外的队友提供常驻 10% 速度。"""
        spd_val = self.skill_param("talent", 0, default=0.10)
        for ally in self.port.allies(self.owner_id):
            if ally != self.owner_id:
                self.port.upsert_status(BuffSpec(
                    key=f"{self.TALENT_SPEED_BUFF}_{ally}",
                    name="分型的螺旋",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, spd_val),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description=f"速度提高 +{spd_val * 100:.1f}%"
                ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="一针幽兰"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="慢捻抹复挑"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=130.0),
                allow_self=True,
                name="摇花缎水，沾衣不摘"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="拭琴抚罗袂"
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
        """秘技【拭琴抚罗袂】：进战自动触发 1 次战技效果。"""
        self._apply_skill_buff()

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【一针幽兰】：单体冰伤，140% 攻击力 (Lv 10)。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Ice",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 20.0)

    def _apply_skill_buff(self) -> None:
        """应用战技【慢捻抹复挑】状态：全队增伤 32% (Lv 10)，击破效率提高 50%，持续 3 回合。"""
        dmg_boost = self.skill_param("skill", 0, default=0.32)
        break_eff = self.skill_param("skill", 1, default=0.50)
        turns = int(self.skill_param("skill", 2, default=3))

        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.SKILL_BUFF,
                name="慢捻抹复挑",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(
                    Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_boost),
                    Modifier(StatType.BREAK_EFFICIENCY, ModifierOp.ADD, break_eff),
                ),
                duration=turns,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"伤害提高 +{dmg_boost * 100:.1f}%，弱点击破效率提高 +{break_eff * 100:.1f}%"
            ))

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【慢捻抹复挑】：消耗 1 点 SP，展开结界 3 回合，回能 30 点。"""
        self._apply_skill_buff()
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【摇花缎水，沾衣不摘】：展开结界 2 回合 (E6 为 3 回合)，全队抗穿 25% (Lv 10)，E1 无视 20% 防御。"""
        res_pen = self.skill_param("ultra", 0, default=0.25)
        duration = 3 if self.eidolon >= 6 else int(self.skill_param("ultra", 1, default=2))

        for ally in self.port.allies(self.owner_id):
            self.port.upsert_status(BuffSpec(
                key=self.ULT_RES_PEN_BUFF,
                name="摇花缎水，沾衣不摘",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=(Modifier(StatType.RES_PEN, ModifierOp.ADD, res_pen),),
                duration=duration,
                timing=DurationTiming.CASTER_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"全属性抗性穿透提高 +{res_pen * 100:.1f}%"
            ))

            # E1【神经仿绣图】：结界期间造成伤害无视 20% 防御
            if self.eidolon >= 1:
                self.port.upsert_status(BuffSpec(
                    key="RuanMei_E1_DefShred",
                    name="神经仿绣图",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.20),),
                    duration=duration,
                    timing=DurationTiming.CASTER_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    description="造成伤害时无视目标 20.0% 防御力"
                ))

        self.port.gain_energy(self.owner_id, 5.0)

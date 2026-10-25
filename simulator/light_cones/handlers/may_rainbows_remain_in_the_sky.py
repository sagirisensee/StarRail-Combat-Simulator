"""光锥：愿虹光永驻天空 (May Rainbows Remain in the Sky - ID 23042).

命途：记忆 (风堇专属)
核心效果【包容】：
1. 装备者速度提高 18% / 21% / 24% / 27% / 30% (基础面板已计入)；
2. 装备者施放普攻、战技和终结技时，消耗全队当前生命值 1.0% 并积累忆灵附加伤害；
3. 忆灵施放技能时，使敌方全体受到的伤害提高 18.0% / 22.5% / 27.0% / 31.5% / 36.0%，持续 2 回合。
"""
from typing import Any
from ..base import LightConeHandler
from ...actions import ActionContext, ActionKind
from ...combat_port import BuffSpec
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class MayRainbowsRemainInTheSkyHandler(LightConeHandler):
    """《愿虹光永驻天空》专属战斗逻辑处理器。"""

    VULNERABILITY_VALUES = (0.18, 0.225, 0.27, 0.315, 0.36)

    def on_action_after(self, ctx: ActionContext) -> None:
        """施放普攻/战技/终结技时，消耗全队当前生命值 1.0%，并使敌方全体受到伤害提高 (群体易伤)。"""
        if not self.port or ctx.actor_id != self.owner_id:
            return
        if ctx.kind in (ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.BASIC):
            # 1. 消耗全队当前生命值 1.0% (经由 lose_hp 派发 HPLostEvent 驱动全队生命降低被动)
            for ally in self.port.allies(self.owner_id):
                cur_hp = self.port.current_hp(ally)
                drain_amt = max(1.0, cur_hp * 0.01)
                self.port.lose_hp(ally, drain_amt, cause="LC_MayRainbows_HP_Drain")

            # 2. 敌方全体陷入虹光易伤
            vuln_val = self.scale(self.VULNERABILITY_VALUES)
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="LC_RainbowSky_Vuln",
                    name=f"虹光易伤 (愿虹光永驻天空S{self.superimposition}易伤{vuln_val*100:.1f}%)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.DMG_VULNERABILITY, ModifierOp.ADD, vuln_val),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True
                ))

# 向因果追踪器自注册本光锥的扣血来源描述 (供 tracer 因果报表引用, 核心层不写死本光锥信息)
from ...tracer import ActionCausalTracer as _Tracer

_Tracer.register_cause_plugin(
"LC_MayRainbows_HP_Drain",
"光锥",
"《愿虹光永驻天空》 (风堇 S1)",
"战技施放消耗全队 1.0% 当前生命值，并施加敌方 18.0% 虹光群体易伤",
)

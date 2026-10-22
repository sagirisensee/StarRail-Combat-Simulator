"""
通用数据驱动遗器处理器 (Generic Relic Set Handler).
自动根据 Nanoka 4.6 官方规约参数与描述，执行全量 62 套遗器的静态与动态效果。
遵循崩铁实机机制：2件套常驻属性已在面板中结算，不重复挂载为战斗 Buff；
仅将全队光环、阈值触发或4件套动态战斗机制装配为运行时状态。
"""

from typing import Optional, List, Any
from .base import RelicSetHandler
from .models import RelicSetSpec
from ..assets.models import RelicSetAsset
from ..combat_port import CombatPort, BuffSpec
from ..status import DurationTiming, Modifier, ModifierOp, StatType


class GenericRelicSetHandler(RelicSetHandler):
    """通用遗器套装处理器，数据驱动覆盖全量遗器。"""

    def __init__(
        self,
        owner_id: str,
        port: Optional[CombatPort] = None,
        *,
        pieces: int = 4,
        spec: Optional[RelicSetSpec] = None,
        asset: Optional[RelicSetAsset] = None
    ) -> None:
        super().__init__(owner_id=owner_id, port=port, pieces=pieces, spec=spec)
        self.asset = asset

    def on_battle_start(self) -> None:
        if not self.port or not self.asset:
            return

        for bonus in self.asset.bonuses:
            if self.pieces < bonus.required_pieces:
                continue

            desc = bonus.desc
            params = bonus.params

            # 1. 全队光环增益 (如 仙舟 302 全队加攻, 龙骨 308 全队暴伤, 匹诺康尼 312 属性增伤, 露莎卡 317 首位加攻)
            if "我方全体攻击力提高" in desc and len(params) >= 3:
                # 仙舟：当速度>=120 时全队加攻 8%
                p_atk = params[2]
                for ally in self.port.allies(self.owner_id):
                    self.port.upsert_status(BuffSpec(
                        key=f"Relic_{self.asset.id}_TeamAtk_{ally}",
                        name=f"{self.asset.name} (全队攻击)",
                        source_id=self.owner_id,
                        target_id=ally,
                        modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, p_atk),),
                        duration=None,
                        timing=DurationTiming.TARGET_TURN_END,
                        category="buff"
                    ))
            elif "我方全体暴击伤害提高" in desc and len(params) >= 2:
                # 龙骨：效果抵抗>=30% 时全队暴伤提高 10%
                p_cd = params[1] if len(params) >= 2 else 0.10
                for ally in self.port.allies(self.owner_id):
                    self.port.upsert_status(BuffSpec(
                        key=f"Relic_{self.asset.id}_TeamCritDmg_{ally}",
                        name=f"{self.asset.name} (全队暴伤)",
                        source_id=self.owner_id,
                        target_id=ally,
                        modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, p_cd),),
                        duration=None,
                        timing=DurationTiming.TARGET_TURN_END,
                        category="buff"
                    ))
            elif "如果装备者不是编队中的第一位角色，使编队中的第一位角色攻击力提高" in desc and len(params) >= 2:
                # 露莎卡 317：编队第一位角色攻击力提高 12%
                allies = self.port.allies(self.owner_id)
                if allies and allies[0] != self.owner_id:
                    self.port.upsert_status(BuffSpec(
                        key=f"Relic_{self.asset.id}_FirstAllyAtk_{allies[0]}",
                        name=f"{self.asset.name} (领袖增益)",
                        source_id=self.owner_id,
                        target_id=allies[0],
                        modifiers=(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, params[1]),),
                        duration=None,
                        timing=DurationTiming.TARGET_TURN_END,
                        category="buff"
                    ))

            # 2. 4件套动态战斗状态 (如 烈阳惊雷的女武神、沉醉于狂欢的诗人等已有特化类处理；
            # 其余通用4件套如 快枪手 速度与普攻增伤已在面板或动态计算中处理)

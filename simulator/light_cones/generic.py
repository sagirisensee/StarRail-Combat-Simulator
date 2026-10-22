"""
通用数据驱动光锥处理器 (Generic Light Cone Handler).
根据 Nanoka 4.6 官方规约参数与描述，执行全量 170 顶光锥的常驻与进战效果。
"""

import re
from typing import Optional, List, Any
from .base import LightConeHandler
from .models import LightConeSpec
from ..assets.models import LightConeAsset
from ..combat_port import CombatPort, BuffSpec
from ..status import DurationTiming, Modifier, ModifierOp, StatType


def parse_lc_modifiers(desc: str, params: tuple[float, ...]) -> List[Modifier]:
    """从光锥描述与当前叠影的 ParamList 中提取被动属性加成。"""
    mods: List[Modifier] = []
    if not params:
        return mods

    p0 = params[0]
    # 暴击伤害
    if "暴击伤害提高" in desc or "暴伤提高" in desc:
        mods.append(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, p0))
    # 暴击率
    elif "暴击率提高" in desc:
        mods.append(Modifier(StatType.CRIT_RATE, ModifierOp.ADD, p0))
    # 攻击力
    elif "攻击力提高" in desc:
        mods.append(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, p0))
    # 防御力
    elif "防御力提高" in desc:
        mods.append(Modifier(StatType.DEF_PERCENT, ModifierOp.ADD, p0))
    # 生命上限
    elif "生命上限提高" in desc:
        mods.append(Modifier(StatType.MAX_HP_PERCENT, ModifierOp.ADD, p0))
    # 击破特攻
    elif "击破特攻提高" in desc:
        mods.append(Modifier(StatType.BREAK_EFFECT, ModifierOp.ADD, p0))
    # 效果命中
    elif "效果命中提高" in desc:
        mods.append(Modifier(StatType.EHR, ModifierOp.ADD, p0))
    # 效果抵抗
    elif "效果抵抗提高" in desc:
        mods.append(Modifier(StatType.EFFECT_RES, ModifierOp.ADD, p0))
    # 速度
    elif "速度提高" in desc:
        mods.append(Modifier(StatType.SPEED, ModifierOp.PERCENT, p0))
    # 伤害提升
    elif any(kw in desc for kw in ("造成的伤害提高", "伤害提高", "全属性伤害提高")):
        mods.append(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, p0))

    return mods


class GenericLightConeHandler(LightConeHandler):
    """通用光锥处理器，数据驱动全量覆盖 170 顶光锥。"""

    def __init__(
        self,
        owner_id: str,
        port: Optional[CombatPort] = None,
        *,
        superimposition: int = 1,
        spec: Optional[LightConeSpec] = None,
        asset: Optional[LightConeAsset] = None
    ) -> None:
        super().__init__(owner_id=owner_id, port=port, superimposition=superimposition, spec=spec)
        self.asset = asset

    def on_battle_start(self) -> None:
        if not self.port or not self.asset:
            return

        params = self.asset.refinements.get(self.superimposition, ())
        desc = self.asset.skill_desc

        # 1. 常驻被动属性加成
        mods = parse_lc_modifiers(desc, params)
        if mods:
            self.port.upsert_status(BuffSpec(
                key=f"LC_{self.asset.id}_Passive_{self.owner_id}",
                name=f"{self.asset.name} (叠影S{self.superimposition})",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=tuple(mods),
                duration=None,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=desc
            ))

        # 2. 进战触发特化效果 (如 如果时间是一朵花 23038: 进战回能 21 点 + 全体暴伤 96%)
        if "如果时间是一朵花" in self.asset.name and len(params) >= 6:
            # param_list: [0.6, 12, 2, 0.96, 21, 2]
            # p[4] = 21 (进战回能), p[3] = 0.96 (全体暴伤)
            energy_gain = params[4]
            crit_dmg_team = params[3]
            self.port.gain_energy(self.owner_id, energy_gain)

            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=f"LC_IfTimeWereAFlower_Oracle_{ally}",
                    name="谕示 (如果时间是一朵花)",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, crit_dmg_team),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="buff",
                    description=f"我方全体暴击伤害提高 +{crit_dmg_team*100:.1f}%"
                ))

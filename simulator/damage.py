"""星穹铁道 8 大乘区伤害计算管线 (Damage Pipeline)。

遵循架构师规范：
1. 纯函数计算器：绝无任何副作用，只负责接收请求并输出可解释的伤害账单；
2. 完整 8 大乘区建模：
   - 基础乘区 (Base DMG): 属性基数 x 技能倍率 + 附加伤害
   - 双暴乘区 (Crit): 未暴击=1.0, 暴击=1+暴伤, 期望模式=1+暴击率x暴伤
   - 增伤乘区 (DMG Boost): 1 + 属性增伤 + 全增伤 + 技能类型增伤
   - 防御乘区 (DEF Mult): (攻击者等级*10 + 200) / ((攻击者等级*10 + 200) + 防御值*(1 - 敌方减防 - 攻击者无视防御))
   - 抗性乘区 (RES Mult): 1 - (基础抗性 - 抗性穿透)
   - 易伤乘区 (Vulnerability): 1 + 易伤总和
   - 减伤/韧性乘区 (Broken/Damage Reduction): 韧性未击破固定 0.9 (自带10%减伤)，击破后为 1.0
3. 返回不可变 `DamageBreakdown` 结构体，供审计与日志输出。
"""
from dataclasses import dataclass
from typing import Optional, Any
from .status import StatType


@dataclass(frozen=True)
class DamageBreakdown:
    attacker_name: str
    target_name: str
    # 乘区明细
    base_dmg: float
    crit_mult: float
    is_crit: bool
    dmg_boost_mult: float
    def_mult: float
    res_mult: float
    vuln_mult: float
    reduction_mult: float
    # 最终结算伤害
    final_damage: float

    def format_details(self) -> str:
        """生成清晰可读的乘区算式账单。"""
        crit_tag = "【暴击!】" if self.is_crit else "【未暴击】"
        return (
            f"{self.attacker_name} -> {self.target_name} 伤害拆解:\n"
            f"  [基础区] {self.base_dmg:,.1f} × "
            f"[双暴区] {self.crit_mult:.2f}{crit_tag} × "
            f"[增伤区] {self.dmg_boost_mult:.2f} × "
            f"[防御区] {self.def_mult:.3f} × "
            f"[抗性区] {self.res_mult:.2f} × "
            f"[易伤区] {self.vuln_mult:.2f} × "
            f"[韧性减伤] {self.reduction_mult:.2f}\n"
            f"  => 💥 最终实际伤害: {int(round(self.final_damage)):,} 点"
        )


@dataclass
class DamageRequest:
    attacker: Any
    target: Any
    skill_multiplier: float             # 技能倍率 (如 1.6 代表 160%)
    flat_damage: float = 0.0            # 附加基础伤害
    attacker_level: int = 80
    target_level: int = 90
    target_base_res: float = 0.20       # 敌方初始抗性 (通常非弱点 20%)
    target_is_broken: bool = False      # 敌方是否处于弱点击破状态 (未击破自带 10% 减伤)
    force_crit: Optional[bool] = None   # None: 随机/期望; True: 必暴; False: 不暴
    fixed_crit_dmg: Optional[float] = None # 若指定固定暴击伤害 (如知更鸟协奏附加伤害 150%)，覆盖面板暴伤
    scaling_stat: str = "atk"           # "atk" | "hp" | "def" 


class DamageCalculator:
    """无副作用的纯函数伤害计算器。"""

    @staticmethod
    def calculate(req: DamageRequest) -> DamageBreakdown:
        atk_stat = req.attacker.base_atk
        if hasattr(req.attacker, "simulator") and req.attacker.simulator:
            mgr = req.attacker.simulator.status_mgr
            atk_stat = mgr.calculate_stat(req.attacker.name, req.attacker.base_atk, StatType.ATK_BASE)
            dmg_boost = mgr.calculate_stat(req.attacker.name, 0.0, StatType.DMG_BOOST)
            res_pen = mgr.calculate_stat(req.attacker.name, 0.0, StatType.RES_PEN)
            # 防御乘区同时汇总：目标身上的减防 Debuff + 攻击者身上的无视防御 Buff (如专武冥花、缇宝E4、花火E2)
            target_def_shred = mgr.calculate_stat(req.target.name, 0.0, StatType.DEF_SHRED)
            attacker_def_ignore = mgr.calculate_stat(req.attacker.name, 0.0, StatType.DEF_SHRED)
            def_shred = target_def_shred + attacker_def_ignore
            vuln = mgr.calculate_stat(req.target.name, 0.0, StatType.VULNERABILITY)
        else:
            dmg_boost = 0.0
            res_pen = 0.0
            def_shred = 0.0
            vuln = 0.0

        # 1. 基础伤害区 (支持攻/生命/防多维度属性缩放)
        scaling = getattr(req, "scaling_stat", "atk")
        if scaling == "hp":
            hp_val = getattr(req.attacker, "max_hp", 0.0)
            if hasattr(req.attacker, "simulator") and req.attacker.simulator:
                hp_val = req.attacker.simulator.status_mgr.calculate_stat(req.attacker.name, hp_val, StatType.MAX_HP_PERCENT)
            base_stat = hp_val
        elif scaling == "def":
            def_val = getattr(req.attacker, "base_def", 0.0)
            if hasattr(req.attacker, "simulator") and req.attacker.simulator:
                def_val = req.attacker.simulator.status_mgr.calculate_stat(req.attacker.name, def_val, StatType.DEF_PERCENT)
            base_stat = def_val
        else:
            base_stat = atk_stat

        base_dmg = base_stat * req.skill_multiplier + req.flat_damage

        # 2. 双暴区
        crit_rate = getattr(req.attacker, "crit_rate", 0.05)
        crit_dmg = req.fixed_crit_dmg if req.fixed_crit_dmg is not None else getattr(req.attacker, "crit_dmg", 0.50)

        if req.force_crit is not None:
            is_crit = req.force_crit
        else:
            # 默认按暴击率判定 (大于等于 100% 必暴，或概率模拟)
            import random
            is_crit = (random.random() < crit_rate) or (crit_rate >= 1.0)

        crit_mult = (1.0 + crit_dmg) if is_crit else 1.0

        # 3. 增伤区
        dmg_boost_mult = 1.0 + dmg_boost

        # 4. 防御区
        # 敌方基准防御: Lv * 10 + 200
        enemy_def_base = req.target_level * 10 + 200
        effective_def = enemy_def_base * max(0.0, (1.0 - min(1.0, def_shred)))
        attacker_factor = req.attacker_level * 10 + 200
        def_mult = attacker_factor / (attacker_factor + effective_def)

        # 5. 抗性区
        eff_res = req.target_base_res - res_pen
        res_mult = max(0.0, min(2.0, 1.0 - eff_res))

        # 6. 易伤区
        vuln_mult = 1.0 + vuln

        # 7. 韧性减伤区 (未破韧固定 0.9，破韧 1.0)
        reduction_mult = 1.0 if req.target_is_broken else 0.9

        # 最终汇总
        final_dmg = (
            base_dmg
            * crit_mult
            * dmg_boost_mult
            * def_mult
            * res_mult
            * vuln_mult
            * reduction_mult
        )

        return DamageBreakdown(
            attacker_name=req.attacker.name,
            target_name=req.target.name,
            base_dmg=base_dmg,
            crit_mult=crit_mult,
            is_crit=is_crit,
            dmg_boost_mult=dmg_boost_mult,
            def_mult=def_mult,
            res_mult=res_mult,
            vuln_mult=vuln_mult,
            reduction_mult=reduction_mult,
            final_damage=final_dmg
        )

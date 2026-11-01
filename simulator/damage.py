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
from .actions import DamageType
from .status import StatType, StatusTag


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
    # 诊断与微观明细 (可选扩展字段，保持 100% 向后兼容)
    barrier_mult: float = 1.0
    scaling_stat: str = "atk"
    base_stat: float = 0.0
    skill_multiplier: float = 1.0
    flat_damage: float = 0.0
    dmg_boost: float = 0.0
    def_shred: float = 0.0
    target_def_shred: float = 0.0
    attacker_def_ignore: float = 0.0
    eff_res: float = 0.0
    res_pen: float = 0.0
    vuln: float = 0.0

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
    extra_dmg_boost: float = 0.0        # 技能或星魂专有额外增伤 (如缇宝 E6 追加攻击 +729%)
    scaling_stat: str = "atk"           # "atk" | "hp" | "def"
    is_true_damage: bool = False        # 真实伤害: 仅取基础区数值, 跳过双暴/增伤/防御/抗性/易伤/减伤全部乘区
    damage_type: Any = None             # DamageType 枚举 (供屏障转化等按类别结算的规则读取)


class DamageCalculator:
    """无副作用的纯函数伤害计算器。"""

    @staticmethod
    def calculate(req: DamageRequest) -> DamageBreakdown:
        atk_stat = req.attacker.base_atk
        base_dmg_boost = float(getattr(req.attacker, "base_dmg_boost", 0.0) or 0.0)
        if hasattr(req.attacker, "simulator") and req.attacker.simulator:
            mgr = req.attacker.simulator.status_mgr
            white_atk = getattr(req.attacker, "base_white_atk", 0.0) or req.attacker.base_atk
            atk_stat = mgr.calculate_stat(req.attacker.name, req.attacker.base_atk, StatType.ATK_BASE, white_base=white_atk)
            dmg_boost = mgr.calculate_stat(req.attacker.name, base_dmg_boost, StatType.DMG_BOOST) + getattr(req, "extra_dmg_boost", 0.0)
            res_pen = mgr.calculate_stat(req.attacker.name, 0.0, StatType.RES_PEN)
            # 防御乘区同时汇总：目标身上的减防 Debuff + 攻击者身上的无视防御 Buff (如专武冥花、缇宝E4、花火E2)
            if getattr(req.target, "is_enemy", False):
                target_def_shred = mgr.calculate_stat(req.target.name, 0.0, StatType.DEF_SHRED)
            else:
                target_def_shred = mgr.calculate_stat(req.target.name, 0.0, StatType.DEF_SHRED, category="debuff")
            attacker_def_ignore = mgr.calculate_stat(req.attacker.name, 0.0, StatType.DEF_SHRED, category="buff")
            def_shred = target_def_shred + attacker_def_ignore
            vuln = mgr.calculate_stat(req.target.name, 0.0, StatType.VULNERABILITY)
        else:
            dmg_boost = base_dmg_boost
            res_pen = 0.0
            def_shred = 0.0
            target_def_shred = 0.0
            attacker_def_ignore = 0.0
            vuln = 0.0

        # 1. 基础伤害区 (支持攻/生命/防多维度属性缩放)
        scaling = getattr(req, "scaling_stat", "atk")
        if scaling == "hp":
            hp_val = getattr(req.attacker, "max_hp", 0.0)
            if hasattr(req.attacker, "simulator") and req.attacker.simulator:
                white_hp = getattr(req.attacker, "base_white_hp", 0.0) or hp_val
                hp_val = req.attacker.simulator.status_mgr.calculate_stat(req.attacker.name, hp_val, StatType.MAX_HP_PERCENT, white_base=white_hp)
            base_stat = hp_val
        elif scaling == "def":
            def_val = getattr(req.attacker, "base_def", 0.0)
            if hasattr(req.attacker, "simulator") and req.attacker.simulator:
                white_def = getattr(req.attacker, "base_white_def", 0.0) or def_val
                def_val = req.attacker.simulator.status_mgr.calculate_stat(req.attacker.name, def_val, StatType.DEF_PERCENT, white_base=white_def)
            base_stat = def_val
        else:
            base_stat = atk_stat

        base_dmg = base_stat * req.skill_multiplier + req.flat_damage

        # 真实伤害: 无视防御与抗性, 不可暴击, 不吃增伤/易伤/韧性减伤, 基础区数值即最终伤害
        if getattr(req, "is_true_damage", False):
            return DamageBreakdown(
                attacker_name=req.attacker.name,
                target_name=req.target.name,
                base_dmg=base_dmg,
                crit_mult=1.0,
                is_crit=False,
                dmg_boost_mult=1.0,
                def_mult=1.0,
                res_mult=1.0,
                vuln_mult=1.0,
                reduction_mult=1.0,
                final_damage=base_dmg,
                barrier_mult=1.0,
                scaling_stat=scaling,
                base_stat=base_stat,
                skill_multiplier=req.skill_multiplier,
                flat_damage=req.flat_damage,
            )

        # 2. 双暴区
        crit_rate = getattr(req.attacker, "crit_rate", 0.05)
        crit_dmg = req.fixed_crit_dmg if req.fixed_crit_dmg is not None else getattr(req.attacker, "crit_dmg", 0.50)

        if req.force_crit is not None:
            is_crit = req.force_crit
        elif getattr(req.attacker, "is_enemy", False):
            # 敌方怪物攻击默认不可暴击 (星铁全系列普通怪物/首领均无暴击能力)
            is_crit = False
        else:
            sim = getattr(req.attacker, "simulator", None)
            oracle = getattr(sim, "crit_oracle", None)
            if callable(oracle) and not req.is_true_damage:
                is_crit = bool(oracle(req))
            else:
                # 默认按暴击率判定 (大于等于 100% 必暴，或概率模拟)
                import random
                is_crit = (random.random() < crit_rate) or (crit_rate >= 1.0)

        crit_mult = (1.0 + crit_dmg) if is_crit else 1.0

        # 3. 增伤区
        dmg_boost_mult = 1.0 + dmg_boost

        # 4. 防御区
        # 目标防御力:
        # - 若目标为我方角色 (is_enemy=False 且具备 defense/base_def 属性), 承伤严格基于角色实际防御力属性;
        # - 若目标为敌方怪物, 按星铁底层公式基准防御: Lv * 10 + 200
        is_target_enemy = getattr(req.target, "is_enemy", False)
        attacker_lvl = getattr(req.attacker, "level", None) or req.attacker_level
        target_lvl = getattr(req.target, "level", None) or req.target_level

        if not is_target_enemy and hasattr(req.target, "defense"):
            target_def_base = req.target.defense
        elif not is_target_enemy and hasattr(req.target, "base_def"):
            target_def_base = req.target.base_def
        else:
            target_def_base = target_lvl * 10 + 200

        effective_def = target_def_base * max(0.0, (1.0 - min(1.0, def_shred)))
        attacker_factor = attacker_lvl * 10 + 200
        def_mult = attacker_factor / (attacker_factor + effective_def)

        # 5. 抗性区
        # 我方角色基础全属性抗性默认为 0.0 (除非指定 damage_res); 敌方非弱点抗性默认为 req.target_base_res (通常 0.20)
        if not is_target_enemy and req.target_base_res == 0.20:
            target_base_res = 0.0
            if hasattr(req.target, "damage_res") and isinstance(req.target.damage_res, dict):
                target_base_res = req.target.damage_res.get(getattr(req, "element", ""), 0.0)
        else:
            target_base_res = req.target_base_res
        eff_res = target_base_res - res_pen
        res_mult = max(0.0, min(2.0, 1.0 - eff_res))

        # 6. 易伤区
        vuln_mult = 1.0 + vuln

        # 7. 韧性减伤区 (敌方未破韧固定 0.9，破韧 1.0; 我方角色无韧性减伤条固定 1.0)
        if not is_target_enemy:
            reduction_mult = 1.0
        else:
            reduction_mult = 1.0 if req.target_is_broken else 0.9

        # 屏障转化与关卡独立减伤乘区: 目标屏障护体时, 附加伤害按 25% 结算;
        # 目标携带关卡独立减伤/易损属性 (damage_reduction) 时统一在此乘区结算,
        # 彻底消除角色 Kit 插件对特定 Boss 屏障状态的耦合感知。
        barrier_mult = 1.0
        if getattr(req.target, "barrier_guarded", False):
            if getattr(req, "damage_type", None) == DamageType.ADDITIONAL:
                barrier_mult = 0.25
        if barrier_mult == 1.0:
            target_dmg_red = float(getattr(req.target, "damage_reduction", 0.0) or 0.0)
            barrier_mult = max(0.0, 1.0 - target_dmg_red)

        # 最终汇总
        final_dmg = (
            base_dmg
            * crit_mult
            * dmg_boost_mult
            * def_mult
            * res_mult
            * vuln_mult
            * reduction_mult
            * barrier_mult
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
            final_damage=final_dmg,
            barrier_mult=barrier_mult,
            scaling_stat=scaling,
            base_stat=base_stat,
            skill_multiplier=req.skill_multiplier,
            flat_damage=req.flat_damage,
            dmg_boost=dmg_boost,
            def_shred=def_shred,
            target_def_shred=target_def_shred,
            attacker_def_ignore=attacker_def_ignore,
            eff_res=eff_res,
            res_pen=res_pen,
            vuln=vuln,
        )

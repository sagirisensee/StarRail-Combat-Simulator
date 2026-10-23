"""星穹铁道状态 (Buff/Debuff) 与动态属性计算系统。

核心机制（遵从架构师规范）：
1. 状态生命周期时钟 (DurationTiming)：
   - TARGET_TURN_START: 承伤者/目标自身回合开始扣减（如持续伤害 DoT、裂伤等）；
   - TARGET_TURN_END:   目标自身行动结束扣减（常规 Buff，如花火战技暴伤）；
   - CASTER_TURN_END:   施法者自身行动结束扣减（结界类技能，如符玄穷观阵、阮·梅结界）；
2. 属性动态计算流水线 (Modifier Pipeline)：
   - 杜绝直接原地加减数值导致的状态漂移；
   - 每次按 基础属性 + sum(固定值加成) + 白字基准 * sum(百分比加成) 动态采样。
3. 语义化状态标签 (StatusTag)：
   - 通过标签声明状态的适用范围与转化约束，彻底消除硬编码状态 ID 或名称黑名单。
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Dict, Optional, Any, Tuple


class DurationTiming(Enum):
    """状态衰减时钟锚点。"""
    TARGET_TURN_START = auto()   # 目标自身回合开始扣减
    TARGET_TURN_END = auto()     # 目标自身回合结束扣减
    CASTER_TURN_END = auto()     # 施法者自身回合结束扣减 (结界时钟)


class StackPolicy(Enum):
    """状态刷新与叠层策略。"""
    REPLACE = auto()             # 覆盖数值、刷新时长
    REFRESH = auto()             # 仅刷新持续时间
    STACK = auto()               # 叠加层数并刷新
    INDEPENDENT = auto()         # 独立多实例


class StatType(Enum):
    """战斗属性枚举。"""
    SPEED = "speed"              # 速度
    ATK_BASE = "atk_base"        # 基础攻击
    ATK_PERCENT = "atk_pct"      # 攻击百分比
    CRIT_RATE = "crit_rate"      # 暴击率
    CRIT_DMG = "crit_dmg"        # 暴击伤害
    DMG_BOOST = "dmg_boost"      # 增伤区
    DEF_SHRED = "def_shred"      # 减防/无视防御区
    RES_PEN = "res_pen"          # 抗性穿透
    BREAK_EFFECT = "break_effect"# 击破特攻
    BREAK_EFFICIENCY = "break_eff"# 击破效率
    ELATION = "elation"          # 欢愉伤害/度
    DEF_BASE = "def_base"
    DEF = "def"
    DEF_PERCENT = "def_pct"      # 防御力百分比
    MAX_HP_PERCENT = "max_hp_pct"# 生命上限百分比
    EFFECT_RES = "effect_res"    # 效果抵抗
    AGGRO = "aggro"              # 嘲讽/仇恨值
    BREAK_VULN = "break_vuln"    # 击破易伤
    ATK = "atk"                  # 攻击力加成 (同 ATK_PERCENT)
    VULNERABILITY = "vulnerability" # 受到伤害提高 (易伤区)
    DMG_VULNERABILITY = "vulnerability" # 易伤区 (兼容别名)
    ERR = "err"                  # 能量恢复效率
    EHR = "ehr"                  # 效果命中
    OUTGOING_HEALING = "outgoing_healing" # 治疗量加成
    HEAL_BOOST = "outgoing_healing"       # 治疗量加成 (兼容别名)


class ModifierOp(Enum):
    ADD = auto()                 # 加算 (如 +12% 暴击率, +10 速度)
    PERCENT = auto()             # 百分比算 (基于白字属性)


@dataclass
class Modifier:
    stat: StatType
    op: ModifierOp
    value: float


class StatusTag:
    """状态元数据语义标签（用于通用过滤与属性转化隔离，杜绝硬编码状态ID）。"""
    EXCLUDE_FROM_STAT_TRANSFERS = "exclude_from_stat_transfers"  # 排除属性二次转化/分享 (防自循环)
    MEMOSPRITE_ONLY = "memosprite_only"                          # 伴生忆灵专享
    CHARACTER_ONLY = "character_only"                            # 仅角色本体专享 (不继承/不投影至伴生忆灵)
    AURA_SHARED = "aura_shared"                                  # 全队共享光环
    CANNOT_ADVANCE_OTHER_ALLIES = "cannot_advance_other_allies"  # 无法使其他友方目标获得行动提前效果 (如【特邀嘉宾】)


@dataclass
class StatusInstance:
    id: str                                  # 唯一标识符，如 "MatrixOfPrescience"
    name: str                                # 展示名称，如 "穷观阵"
    source: Any                              # 施法者 Entity
    target: Any                              # 承载者 Entity
    duration: Optional[int] = 1              # 剩余持续回合数 (None 表示常驻，不自动衰减)
    timing: DurationTiming = DurationTiming.TARGET_TURN_END # 扣减时序
    modifiers: List[Modifier] = field(default_factory=list)
    stacks: int = 1                          # 当前层数
    max_stacks: int = 1                      # 最大层数
    stack_policy: StackPolicy = StackPolicy.REPLACE # 合并策略
    skip_current_clock: bool = False         # 施加当回合是否豁免扣减
    category: str = "buff"                   # 状态类别: "buff" (增益), "debuff" (负面), "other" (其他效果/结界)
    description: Optional[str] = None        # 业务层定义的自解释说明文案 (非空时优先展示)
    tags: List[str] = field(default_factory=list) # 语义标签列表，用于插件化无耦合过滤

    @property
    def is_expired(self) -> bool:
        if self.duration is None:
            return False
        return self.duration <= 0


class StatusManager:
    """全局状态与 Buff 管理器。"""
    def __init__(self, simulator: Any):
        self.simulator = simulator
        # entity_name -> list of StatusInstance
        self.statuses: Dict[str, List[StatusInstance]] = {}

    def get_statuses(
        self,
        entity_name: str,
        *,
        category: Optional[str] = None,
        include_tags: Tuple[str, ...] = (),
        exclude_tags: Tuple[str, ...] = ()
    ) -> List[StatusInstance]:
        raw = self.statuses.get(entity_name, [])
        if not category and not include_tags and not exclude_tags:
            return raw
        result = []
        for s in raw:
            if category is not None and getattr(s, "category", "buff") != category:
                continue
            s_tags = getattr(s, "tags", ())
            if include_tags and not any(t in s_tags for t in include_tags):
                continue
            if exclude_tags and any(t in s_tags for t in exclude_tags):
                continue
            result.append(s)
        return result

    def get_status(self, entity_name: str, status_id: str) -> Optional[StatusInstance]:
        """获取目标指定 ID 的状态实例。"""
        return next((s for s in self.get_statuses(entity_name) if s.id == status_id), None)

    def add_status(self, status: StatusInstance):
        """向目标添加状态（严格执行 REPLACE/STACK 策略与数值更新）。"""
        target_name = status.target.name
        if target_name not in self.statuses:
            self.statuses[target_name] = []

        existing = next((s for s in self.statuses[target_name] if s.id == status.id), None)
        if existing:
            if status.stack_policy == StackPolicy.REPLACE:
                existing.modifiers = list(status.modifiers)
                existing.duration = status.duration if status.duration is not None else existing.duration
                existing.stacks = min(existing.max_stacks, max(existing.stacks, status.stacks))
                existing.skip_current_clock = status.skip_current_clock
                if status.description is not None:
                    existing.description = status.description
                if status.tags:
                    existing.tags = list(status.tags)
            elif status.stack_policy == StackPolicy.STACK:
                existing.stacks = min(existing.max_stacks, existing.stacks + status.stacks)
                if status.duration is not None:
                    existing.duration = max(existing.duration or 0, status.duration)
            elif status.stack_policy == StackPolicy.REFRESH:
                if status.duration is not None:
                    existing.duration = max(existing.duration or 0, status.duration)
        else:
            self.statuses[target_name].append(status)

    def remove_status(self, target_name: str, status_id: str):
        """显式移除指定状态。"""
        if target_name in self.statuses:
            self.statuses[target_name] = [s for s in self.statuses[target_name] if s.id != status_id]

    def has_status(self, target_name: str, status_id: str) -> bool:
        """检查目标是否持有指定状态。"""
        return any(s.id == status_id for s in self.get_statuses(target_name))

    def tick_on_turn_begin(self, actor: Any):
        """在回合开始时结算 TARGET_TURN_START 类型的状态。"""
        self._tick_and_clean(
            condition=lambda s: s.target.name == actor.name and s.timing == DurationTiming.TARGET_TURN_START,
            actor_name=actor.name,
            phase="回合开始"
        )

    def tick_on_turn_end(self, actor: Any):
        """在回合结束时结算 TARGET_TURN_END 与 CASTER_TURN_END 类型的状态。"""
        # 1. 作为目标自身行动结束
        self._tick_and_clean(
            condition=lambda s: s.target.name == actor.name and s.timing == DurationTiming.TARGET_TURN_END,
            actor_name=actor.name,
            phase="自身行动结束"
        )
        # 2. 作为施法者行动结束（如符玄自身行动结算穷观阵）
        self._tick_and_clean(
            condition=lambda s: s.source.name == actor.name and s.timing == DurationTiming.CASTER_TURN_END,
            actor_name=actor.name,
            phase="施法者行动结束"
        )

    def _tick_and_clean(self, condition, actor_name: str, phase: str):
        from .events import StatusExpireEvent
        bus = self.simulator.event_bus
        av = self.simulator.current_av
        cycle = self.simulator.current_cycle

        for target_name, status_list in list(self.statuses.items()):
            active = []
            for s in status_list:
                if condition(s):
                    if s.skip_current_clock:
                        s.skip_current_clock = False
                        active.append(s)
                        continue

                    if s.duration is not None:
                        s.duration -= 1
                        if s.duration <= 0:
                            bus.publish(StatusExpireEvent(
                                av=round(av, 2),
                                cycle=cycle,
                                target_name=s.target.name,
                                status_id=s.id,
                                status_name=s.name
                            ))
                            continue
                active.append(s)
            self.statuses[target_name] = active

    def calculate_stat(
        self,
        entity_name: str,
        base_val: float,
        stat_type: StatType,
        white_base: float = 0.0,
        *,
        exclude_tags: Tuple[str, ...] = (),
        exclude_ids: Tuple[str, ...] = ()
    ) -> float:
        """动态计算指定属性的加成总值（支持按语义标签或状态 ID 排除以防自循环转化）。
        
        符合星铁官方属性计算公式：
        - 攻击力 ATK = 战前攻击力 + 基础白字攻击 * 攻击力%总和 + 固定攻击力总和
        - 速度 SPD   = 战前速度 + 基础白字速度 * 速度%总和 + 固定速度总和
        - 防御力 DEF = 战前防御力 + 基础白字防御 * 防御力%总和 + 固定防御力总和
        - 生命上限 HP = 战前生命上限 + 基础白字生命 * 生命%总和 + 固定生命总和
        - 暴击/暴伤/增伤/抗穿/易伤/治疗量 = 基础值 + 加成数值总和
        """
        if white_base <= 0.0 and self.simulator:
            ent = self.simulator.get_entity(entity_name)
            if ent:
                if stat_type == StatType.SPEED:
                    white_base = getattr(ent, "base_white_speed", 0.0)
                elif stat_type in (StatType.ATK_BASE, StatType.ATK_PERCENT, StatType.ATK):
                    white_base = getattr(ent, "base_white_atk", 0.0)
                elif stat_type in (StatType.DEF_PERCENT, StatType.DEF, StatType.DEF_BASE):
                    white_base = getattr(ent, "base_white_def", 0.0)
                elif stat_type == StatType.MAX_HP_PERCENT:
                    white_base = getattr(ent, "base_white_hp", 0.0)

        flat_sum = 0.0
        pct_sum = 0.0

        for status in self.get_statuses(entity_name, exclude_tags=exclude_tags):
            if exclude_ids and status.id in exclude_ids:
                continue
            for mod in status.modifiers:
                # 攻击力属性统一聚合 (包含 ATK_BASE, ATK_PERCENT, ATK)
                if stat_type in (StatType.ATK_BASE, StatType.ATK_PERCENT, StatType.ATK):
                    if mod.stat in (StatType.ATK_BASE, StatType.ATK_PERCENT, StatType.ATK):
                        total_mod_val = mod.value * status.stacks
                        if mod.op == ModifierOp.ADD:
                            if mod.stat in (StatType.ATK_PERCENT, StatType.ATK):
                                pct_sum += total_mod_val
                            else:
                                flat_sum += total_mod_val
                        elif mod.op == ModifierOp.PERCENT:
                            pct_sum += total_mod_val

                # 速度属性统一聚合
                elif stat_type == StatType.SPEED and mod.stat == StatType.SPEED:
                    total_mod_val = mod.value * status.stacks
                    if mod.op == ModifierOp.ADD:
                        flat_sum += total_mod_val
                    elif mod.op == ModifierOp.PERCENT:
                        pct_sum += total_mod_val

                # 防御属性统一聚合
                elif stat_type in (StatType.DEF_PERCENT, StatType.DEF, StatType.DEF_BASE) and mod.stat in (StatType.DEF_PERCENT, StatType.DEF, StatType.DEF_BASE):
                    total_mod_val = mod.value * status.stacks
                    if mod.op == ModifierOp.ADD:
                        pct_sum += total_mod_val
                    elif mod.op == ModifierOp.PERCENT:
                        pct_sum += total_mod_val

                # 生命上限统一聚合 (支持百分比与固定数值)
                elif stat_type == StatType.MAX_HP_PERCENT and mod.stat == StatType.MAX_HP_PERCENT:
                    total_mod_val = mod.value * status.stacks
                    if mod.op == ModifierOp.PERCENT:
                        pct_sum += total_mod_val
                    elif mod.op == ModifierOp.ADD:
                        if total_mod_val > 1.0:
                            flat_sum += total_mod_val
                        else:
                            pct_sum += total_mod_val

                # 其他属性 (CRIT_RATE, CRIT_DMG, DMG_BOOST, RES_PEN, VULNERABILITY 等)
                elif mod.stat == stat_type:
                    total_mod_val = mod.value * status.stacks
                    if mod.op == ModifierOp.ADD:
                        flat_sum += total_mod_val
                    elif mod.op == ModifierOp.PERCENT:
                        pct_sum += total_mod_val

        if stat_type in (StatType.ATK_BASE, StatType.ATK_PERCENT, StatType.ATK):
            eff_base = white_base if white_base > 0 else base_val
            return base_val + (eff_base * pct_sum) + flat_sum
        elif stat_type == StatType.SPEED:
            eff_base = white_base if white_base > 0 else base_val
            return base_val + (eff_base * pct_sum) + flat_sum
        elif stat_type == StatType.MAX_HP_PERCENT:
            eff_base = white_base if white_base > 0 else base_val
            return base_val + (eff_base * pct_sum) + flat_sum
        elif stat_type in (
            StatType.CRIT_RATE, StatType.CRIT_DMG, StatType.DMG_BOOST,
            StatType.RES_PEN, StatType.VULNERABILITY, StatType.BREAK_EFFECT,
            StatType.DEF_SHRED, StatType.OUTGOING_HEALING, StatType.EFFECT_RES,
            StatType.EHR, StatType.ERR
        ):
            return base_val + flat_sum + pct_sum

        return (base_val + flat_sum) * (1.0 + pct_sum)

    def get_detailed_snapshot(self, entity: Any) -> Dict[str, Any]:
        """获取指定实体的全部实时动态属性与生效 Buff 详情快照。"""
        name = entity.name
        base_atk = getattr(entity, "base_atk", 0.0)
        base_spd = getattr(entity, "base_speed", 0.0)
        base_def = getattr(entity, "base_def", 0.0)
        base_cr = getattr(entity, "base_crit_rate", 0.05)
        base_cd = getattr(entity, "base_crit_dmg", 0.50)
        base_be = getattr(entity, "base_break_effect", 0.0)
        base_res = getattr(entity, "base_effect_res", 0.10)
        base_ehr = getattr(entity, "base_effect_hit_rate", 0.0)
        base_err = getattr(entity, "base_err", 1.0)
        base_heal = getattr(entity, "base_outgoing_healing", 0.0)

        # 采样各属性
        cur_atk = self.calculate_stat(name, base_atk, StatType.ATK_BASE)
        cur_spd = self.calculate_stat(name, base_spd, StatType.SPEED, white_base=getattr(entity, "base_white_speed", 0.0))
        cur_def = self.calculate_stat(name, base_def, StatType.DEF_PERCENT)
        cur_cr = self.calculate_stat(name, base_cr, StatType.CRIT_RATE)
        cur_cd = self.calculate_stat(name, base_cd, StatType.CRIT_DMG)
        dmg_boost = self.calculate_stat(name, getattr(entity, "base_dmg_boost", 0.0), StatType.DMG_BOOST)
        res_pen = self.calculate_stat(name, 0.0, StatType.RES_PEN)
        vuln = self.calculate_stat(name, 0.0, StatType.VULNERABILITY)
        def_shred = self.calculate_stat(name, 0.0, StatType.DEF_SHRED)
        break_eff = self.calculate_stat(name, base_be, StatType.BREAK_EFFECT)
        effect_res = self.calculate_stat(name, base_res, StatType.EFFECT_RES)
        cur_heal = self.calculate_stat(name, base_heal, StatType.OUTGOING_HEALING)

        # 统计百分比增量构成
        atk_pct = (cur_atk - base_atk) / base_atk if base_atk > 0 else 0.0
        spd_pct = (cur_spd - base_spd) / base_spd if base_spd > 0 else 0.0
        def_pct = (cur_def - base_def) / base_def if base_def > 0 else 0.0

        base_max_hp = getattr(entity, "max_hp", 0.0)
        cur_max_hp = base_max_hp
        if base_max_hp != float("inf") and base_max_hp > 0:
            white_hp = getattr(entity, "base_white_hp", 0.0) or base_max_hp
            cur_max_hp = self.calculate_stat(name, base_max_hp, StatType.MAX_HP_PERCENT, white_base=white_hp)
        cur_hp = entity.current_hp + (cur_max_hp - base_max_hp) if (entity.current_hp > 0 and base_max_hp != float("inf")) else entity.current_hp

        # Buff 详情列表
        active_buffs = []
        for s in self.get_statuses(name):
            mod_strs = []
            for m in s.modifiers:
                if m.stat == StatType.MAX_HP_PERCENT:
                    if m.op == ModifierOp.PERCENT:
                        mod_strs.append(f"生命上限 +{m.value * 100:.1f}%")
                    else:
                        mod_strs.append(f"生命上限 +{m.value:.0f}")
                else:
                    op_str = "%" if (m.op == ModifierOp.PERCENT or m.stat in (StatType.ATK_PERCENT, StatType.SPEED, StatType.CRIT_RATE, StatType.CRIT_DMG, StatType.RES_PEN, StatType.DMG_BOOST, StatType.VULNERABILITY, StatType.DEF_SHRED, StatType.BREAK_EFFECT, StatType.EFFECT_RES)) else ""
                    val_disp = m.value * 100 if op_str == "%" else m.value
                    mod_strs.append(f"{m.stat.name} +{val_disp:.1f}{op_str}")

            desc = getattr(s, "description", None) or (", ".join(mod_strs) if mod_strs else "特殊效果 / 机制生效中")
            source_name = getattr(s.source, "name", str(s.source))
            active_buffs.append({
                "id": s.id,
                "name": s.name,
                "source": source_name,
                "duration": s.duration,
                "timing": s.timing.name if hasattr(s.timing, "name") else str(s.timing),
                "stacks": s.stacks,
                "category": getattr(s, "category", "buff"),
                "modifiers_desc": desc
            })

        buffs_list = [b for b in active_buffs if b.get("category", "buff") == "buff"]
        debuffs_list = [b for b in active_buffs if b.get("category", "buff") == "debuff"]
        other_list = [b for b in active_buffs if b.get("category", "buff") == "other"]

        # 套件机制独有状态提取
        kit_state = {}
        kit = getattr(entity, "kit", None)
        if kit:
            if hasattr(kit, "get_kit_state"):
                kit_state = kit.get_kit_state()
            else:
                excluded = {"owner_id", "port", "skill_levels"}
                for k, v in getattr(kit, "__dict__", {}).items():
                    if k not in excluded and not k.startswith("_"):
                        if isinstance(v, (int, float, bool, str, list, dict)):
                            kit_state[k] = v

        hp_pct = (cur_hp / cur_max_hp) if (cur_max_hp > 0 and cur_max_hp != float("inf")) else 1.0

        return {
            # 基础身份元数据
            "name": name,
            "avatar_id": getattr(entity, "avatar_id", 0),
            "eidolon": getattr(entity, "eidolon", 0),
            "level": getattr(entity, "level", 80),
            "element": getattr(entity, "element", ""),
            "path": getattr(entity, "path", ""),
            "is_enemy": getattr(entity, "is_enemy", False),

            # 生存与行动资源
            "current_hp": cur_hp,
            "max_hp": cur_max_hp,
            "hp_pct": hp_pct,
            "is_infinite_hp": getattr(entity, "is_infinite_hp", False) or entity.max_hp == float("inf"),
            "shield": getattr(entity, "shield", 0.0),
            "current_energy": getattr(entity, "energy", 0.0),
            "max_energy": getattr(entity, "max_energy", 0.0),
            "energy_ready": getattr(entity, "energy", 0.0) >= getattr(entity, "max_energy", 120.0) if getattr(entity, "max_energy", 0.0) > 0 else False,
            "remaining_av": getattr(entity, "remaining_av", 0.0),
            "distance_remaining": getattr(entity, "distance_remaining", 0.0),

            # 核心战斗面板
            "base_atk": base_atk,
            "current_atk": cur_atk,
            "atk_gain_pct": atk_pct,
            "base_speed": base_spd,
            "current_speed": cur_spd,
            "speed_gain_pct": spd_pct,
            "base_def": base_def,
            "current_def": cur_def,
            "def_gain_pct": def_pct,
            "base_crit_rate": base_cr,
            "current_crit_rate": cur_cr,
            "base_crit_dmg": base_cd,
            "current_crit_dmg": cur_cd,
            "dmg_boost": dmg_boost,
            "res_pen": res_pen,
            "vulnerability": vuln,
            "def_shred": def_shred,
            "break_effect": break_eff,
            "effect_res": effect_res,
            "effect_hit_rate": base_ehr,
            "err": base_err,
            "outgoing_healing": cur_heal,
            "base_outgoing_healing": base_heal,

            # 韧性系统 (敌方)
            "max_toughness": getattr(entity, "max_toughness", 0.0),
            "current_toughness": getattr(entity, "current_toughness", 0.0),
            "is_broken": getattr(entity, "is_broken", False),
            "weaknesses": list(getattr(entity, "weaknesses", [])),

            # Buff 与特有机制
            "buffs": buffs_list,
            "debuffs": debuffs_list,
            "other_effects": other_list,
            "all_statuses": active_buffs,
            "kit_state": kit_state,

            # 结构化别名分组 (供链式查询与对账)
            "stats": {
                "atk": {"current": cur_atk, "base": base_atk, "gain_pct": atk_pct},
                "speed": {"current": cur_spd, "base": base_spd, "gain_pct": spd_pct},
                "def": {"current": cur_def, "base": base_def, "gain_pct": def_pct},
                "crit_rate": cur_cr,
                "crit_dmg": cur_cd,
                "dmg_boost": dmg_boost,
                "res_pen": res_pen,
                "vulnerability": vuln,
                "def_shred": def_shred,
                "break_effect": break_eff,
                "effect_res": effect_res,
                "effect_hit_rate": base_ehr,
                "err": base_err,
                "outgoing_healing": cur_heal
            }
        }

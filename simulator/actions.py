"""星穹铁道战斗动作抽象与请求模型 (Action Definitions & Context)."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple


class ActionKind(Enum):
    BASIC = auto()          # 普通攻击
    SKILL = auto()          # 战技
    ULTIMATE = auto()       # 终结技 (插队执行)
    TECHNIQUE = auto()      # 秘技 (开战前触发)
    TALENT = auto()         # 天赋/被动触发
    FOLLOW_UP = auto()      # 追加攻击
    MEMOSPRITE_SKILL = auto() # 忆灵技


class DamageType(Enum):
    """伤害分类枚举 (对齐实机事件总线的官方伤害类型, 取代自由字符串 damage_tag)。

    官方骨干分类: Basic / Ultimate / Additional / True / Follow-Up / Servant；
    本系统扩展: Skill / DoT / Technique / Elation (欢愉) / Direct (未分类的直接伤害, 默认值)。
    新代码一律通过 CombatPort.attack(..., damage_type=DamageType.X) 声明伤害类型；
    历史字符串标签经 from_tag() 在 Port 边界统一收编, 禁止再新增自由字符串标签。
    """
    BASIC = "Basic"             # 普攻伤害 (含强化普攻)
    SKILL = "Skill"             # 战技伤害
    ULTIMATE = "Ultimate"       # 终结技伤害
    ADDITIONAL = "Additional"   # 附加伤害
    FOLLOW_UP = "Follow-Up"     # 追加攻击伤害
    SERVANT = "Servant"         # 忆灵伤害 (忆灵技/忆灵爆发)
    TRUE = "True"               # 真实伤害
    DOT = "DoT"                 # 持续伤害 (含 DoT 引爆)
    TECHNIQUE = "Technique"     # 秘技伤害
    ELATION = "Elation"         # 欢愉伤害
    DIRECT = "Direct"           # 未分类直接伤害 (默认)

    @classmethod
    def from_tag(cls, tag: object) -> "DamageType":
        """将历史自由字符串 damage_tag 收编为枚举；已是枚举则原样返回，未知标签归 DIRECT。"""
        if isinstance(tag, cls):
            return tag
        return _LEGACY_DAMAGE_TAG_MAP.get(str(tag or ""), cls.DIRECT)


_LEGACY_DAMAGE_TAG_MAP = {
    "BasicAttack": DamageType.BASIC,
    "Basic": DamageType.BASIC,
    "Basic_Extra": DamageType.BASIC,
    "EnhancedBasic": DamageType.BASIC,
    "EnhancedBasicAttack": DamageType.BASIC,
    "EnhancedBasic_Blast": DamageType.BASIC,
    "Skill": DamageType.SKILL,
    "Skill_Blast": DamageType.SKILL,
    "Memory": DamageType.SKILL,
    "Windburst": DamageType.SKILL,
    "Butterfly": DamageType.SKILL,
    "Hellfire": DamageType.SKILL,
    "Moonlight": DamageType.SKILL,
    "Ultimate": DamageType.ULTIMATE,
    "Ultimate_Blast": DamageType.ULTIMATE,
    "MoonlightUlt": DamageType.ULTIMATE,
    "AdditionalDamage": DamageType.ADDITIONAL,
    "SwordStance": DamageType.ADDITIONAL,
    "FollowUpAttack": DamageType.FOLLOW_UP,
    "FollowUp": DamageType.FOLLOW_UP,
    "YanqingFollowUp": DamageType.FOLLOW_UP,
    "KarmaFollowUp": DamageType.FOLLOW_UP,
    "AutarkyFollowUp": DamageType.FOLLOW_UP,
    "AutoSkill_FollowUp": DamageType.FOLLOW_UP,
    "MemospriteSkill": DamageType.SERVANT,
    "MemospriteUltimate": DamageType.SERVANT,
    "dot": DamageType.DOT,
    "DoT_Detonation": DamageType.DOT,
    "Technique": DamageType.TECHNIQUE,
    "ElationBasic": DamageType.ELATION,
    "ElationSkill": DamageType.ELATION,
    "AhaMoment": DamageType.ELATION,
    "direct": DamageType.DIRECT,
    "": DamageType.DIRECT,
}


class TargetMode(Enum):
    SELF = auto()           # 自身
    SINGLE_ALLY = auto()    # 我方单体
    ALL_ALLIES = auto()     # 我方全体
    SINGLE_ENEMY = auto()   # 敌方单体
    ALL_ENEMIES = auto()    # 敌方全体
    BLAST = auto()          # 扩散 (主目标 + 相邻目标)
    BOUNCE = auto()         # 弹射


@dataclass(frozen=True)
class ResourceCost:
    sp: int = 0                         # 战技点消耗 (正为耗点, 负为回点)
    energy: float = 0.0                 # 终结技能量消耗
    technique_points: int = 0           # 秘技点消耗


@dataclass(frozen=True)
class AbilityDefinition:
    kind: ActionKind
    target_mode: TargetMode
    cost: ResourceCost = ResourceCost()
    allow_self: bool = True
    name: str = ""
    priority: int = 1                   # 秘技/动作准备执行优先级 (值越小越先结算，如全队增益=0, 默认=1, 领域展开=2)
    tag: str = ""                       # 动作UI与机制分类标签 (如 "战技", "普攻", "忆灵技", "终极爆发")
    is_auto: bool = False               # 是否为系统自动施放/不可玩家手动操作动作 (如长夜开局自动喷水)


@dataclass(frozen=True)
class ActionRequest:
    actor_id: str
    kind: ActionKind
    primary_target_id: Optional[str] = None


@dataclass(frozen=True)
class ActionContext:
    action_id: str
    actor_id: str
    kind: ActionKind
    target_ids: Tuple[str, ...]         # 目标 ID 元组 (已校验)
    is_natural_turn_action: bool = True # 是否为常规自然回合动作 (终结技插队为 False)
    damage_tag: str = ""                # 可选伤害/动作细分标签

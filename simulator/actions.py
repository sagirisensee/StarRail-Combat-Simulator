"""星穹铁道战斗动作抽象与请求模型 (Action Definitions & Context)."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, Tuple


class ActionKind(Enum):
    BASIC = auto()            # 普通攻击 (官方 OnUseSkill.skill.type = "Normal")
    SKILL = auto()            # 战技 / 自动战技 (官方 OnUseSkill.skill.type = "BPSkill")
    ULTIMATE = auto()         # 终结技 (插队执行, 官方 OnUseSkill.skill.type = "Ultra")
    TECHNIQUE = auto()        # 秘技 (开战前触发)
    TALENT = auto()           # 天赋/被动触发 (官方 OnUseSkill.skill.type = "Unknown")
    FOLLOW_UP = auto()        # 追加攻击 (实机不发布 OnUseSkill, 仅产生 OnDamage.type = "Follow-Up")
    MEMOSPRITE_SKILL = auto() # 忆灵技 (官方 OnUseSkill.skill.type = "Servant")
    ELATION_SKILL = auto()    # 欢愉技 / 阿哈时刻自动技 (官方 OnUseSkill.skill.type = "ElationDamage")


class FollowUpPhase(Enum):
    """追加攻击同波次内部优先级分组 (对齐实机底层调度四段位).

    同一动作边界内同时满足触发条件的追加攻击，先按分组排序：
    1. FAST (10): 最速组 (如砂金、Archer) —— 优先于常规组结算，同组按编队站位升序；
    2. NORMAL (20): 常规组 (真理医生、托帕、飞霄、缇宝、姬子、黑塔、卡芙卡、知更鸟•晴歌、绯英等绝大多数追击角色)
       —— 组内严格遵循【常规组候选人循环左移规则 (`candidates[1:] + candidates[:1]`)】；
    3. SLOW (30): 慢速组 (如翡翠、大丽花、貊泽、布洛妮娅) —— 晚于常规组结算，同组按编队站位升序；
    4. COUNTER (40): 受击反击组 (如克拉拉、云璃、三月七) —— 受击动作结算末尾按编队站位升序。
    """
    FAST = 10
    NORMAL = 20
    SLOW = 30
    COUNTER = 40


class ActionScheduleCategory(Enum):
    """回合外派生动作与追加回合的全局调度分级 (严格与伤害标签 DamageType 解耦).

    对齐实机底层调度四层队列 + 时间轴模型 (Asagi 实测视频 1~3 与官方 Veritas 日志对账)：
    1. IMMEDIATE_EXTRA_TURN (50): 即时型追加回合 (`_immediate_queue`, 如昔涟大招、乱破大招、风堇小伊卡等) ——
       优先级高于整个预约动作队列 (`_reserved_queue`)；
       当 `preempt_follow_up=True` (如昔涟首次大招全队激活) 时甚至抢占 `_followup_queue`；
       默认 `preempt_follow_up=False` (如乱破/小伊卡) 则在 `_followup_queue` 排空后立即抢占 `_reserved_queue` 执行；
    2. FOLLOW_UP (100): 真正追加攻击队列 (`_followup_queue`) ——
       同波次按 FAST / NORMAL(循环左移) / SLOW / COUNTER 分组排序，跨波次严格 FIFO；
    3. 统一预约动作队列 (`_reserved_queue`, 跨介入时机严格 FIFO)：
       - ULTIMATE (150): 预约终结技 (玩家按键/自动插队大招)；
       - AUTO_SKILL (200): 自动触发战技 (如绯英千刃、希儿残血追加战技、花火互动陷阱 BPSkill)；
       - ELATION_SKILL (300): 自动欢愉技 / 阿哈时刻 (ElationDamage)；
       - RESERVED_EXTRA_TURN (350): 预约型追加回合 (如希儿再现、珍珠、流萤E2、银狼E2)；
       同一介入波次同时产生时按 `ULTIMATE -> AUTO_SKILL -> ELATION_SKILL -> RESERVED_EXTRA_TURN`
       排入 `_reserved_queue` 队尾；不同介入时机 (`before_hit` / `after_hit` / `on_kill`) 严格按先来后到 FIFO 排队！
       在连续行动锁定 (`continuous_action_hold=True`, 如 Archer 连续战技回合) 期间，
       `_reserved_queue` 仅当队首元素为 `ULTIMATE` 时允许弹出，若队首为非 `ULTIMATE` 动作则整条预约队列挂起阻塞；
    4. VOYAGE_EXTRA_TURN (400): 旅姬小型追加回合 (`_voyage_queue`) ——
       优先级低于整个 `_reserved_queue` (会被大招与希儿再现等预约动作抢占)，但高于自然时间轴跑条回合。
    """
    IMMEDIATE_EXTRA_TURN = 50   # 即时型追加回合 (昔涟/乱破/风堇小伊卡)
    FOLLOW_UP = 100             # 真正追加攻击队列 (最高优先, 支持 FAST/NORMAL循环左移/SLOW/COUNTER 分组与严格 FIFO)
    ULTIMATE = 150              # 预约终结技 (进入统一预约动作队列 _reserved_queue)
    AUTO_SKILL = 200            # 自动触发战技 (如绯英千刃、互动陷阱 BPSkill, 进入 _reserved_queue)
    ELATION_SKILL = 300         # 自动欢愉技 / 阿哈时刻 (ElationDamage, 进入 _reserved_queue)
    RESERVED_EXTRA_TURN = 350   # 预约型追加回合 (希儿再现/珍珠/流萤E2/银狼E2, 进入 _reserved_queue)
    VOYAGE_EXTRA_TURN = 400     # 旅姬小型追加回合 (低于 _reserved_queue, 高于时间轴跑条)


class DamageType(Enum):
    """伤害分类枚举 (对齐实机事件总线 Veritas 的官方 OnDamage.type 分类, 取代自由字符串 damage_tag)。

    官方 Veritas 日志实证 9 大分类:
    Basic / Skill / Ultimate / Additional / Follow-Up / Servant / True / Break / Elation；
    本系统保留扩展: DoT / Technique / Direct (未分类的直接伤害, 默认值)。
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
    BREAK = "Break"             # 击破/超击破伤害 (官方 OnDamage.type = "Break")
    DOT = "DoT"                 # 持续伤害 (含 DoT 引爆)
    TECHNIQUE = "Technique"     # 秘技伤害
    ELATION = "Elation"         # 欢愉伤害 (官方 OnDamage.type = "Elation")
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
    "Additional": DamageType.ADDITIONAL,
    "SwordStance": DamageType.ADDITIONAL,
    "FollowUpAttack": DamageType.FOLLOW_UP,
    "FollowUp": DamageType.FOLLOW_UP,
    "Follow-Up": DamageType.FOLLOW_UP,
    "YanqingFollowUp": DamageType.FOLLOW_UP,
    "KarmaFollowUp": DamageType.FOLLOW_UP,
    "AutarkyFollowUp": DamageType.FOLLOW_UP,
    "AutoSkill_FollowUp": DamageType.FOLLOW_UP,
    "MemospriteSkill": DamageType.SERVANT,
    "MemospriteUltimate": DamageType.SERVANT,
    "Servant": DamageType.SERVANT,
    "True": DamageType.TRUE,
    "Break": DamageType.BREAK,
    "BreakDamage": DamageType.BREAK,
    "SuperBreak": DamageType.BREAK,
    "dot": DamageType.DOT,
    "DoT": DamageType.DOT,
    "DoT_Detonation": DamageType.DOT,
    "Technique": DamageType.TECHNIQUE,
    "Elation": DamageType.ELATION,
    "ElationDamage": DamageType.ELATION,
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
    skill_id: int = 0                   # 官方 skill_config_id (如 141302); 0 表示未声明, 由 core 按角色 avatar_id 与动作槽位推导


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
    is_natural_turn_action: bool = True # 是否为常规自然回合主动作 (终结技/追加回合/自动技均为 False)
    damage_tag: str = ""                # 可选伤害/动作细分标签
    schedule_category: Optional[ActionScheduleCategory] = None
    owner_turn_id: Optional[int] = None
    owner_turn_actor_id: Optional[str] = None


@dataclass
class ScheduledActionIntent:
    """挂起在调度器中的派生动作意图 (即时追加回合 / 追加攻击 / 统一预约动作 / 旅姬追加回合)."""
    actor_id: str
    callback: Callable[[], None]
    name: str = ""
    category: ActionScheduleCategory = ActionScheduleCategory.FOLLOW_UP
    phase: FollowUpPhase = FollowUpPhase.NORMAL
    action_kind: ActionKind = ActionKind.FOLLOW_UP
    skill_id: int = 0
    enqueue_seq: int = 0
    publish_execute_event: bool = True
    preempt_follow_up: bool = False
    owner_turn_id: Optional[int] = None
    owner_turn_actor_id: Optional[str] = None

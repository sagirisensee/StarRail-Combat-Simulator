"""【新人开发标准脚手架模板】角色与伴生忆灵技能套件 (_template.py)。

使用方式：
1. 复制本文件为 `simulator/kits/characters/<character_pinyin>.py`（注意去掉开头的下划线 `_`）；
2. 取消 `@register_kit(...)` 装饰器注释并填写角色 ID、中文名、英文名；
3. 系统会自动扫描 `characters/` 目录并完成注册，**无需手动修改 `registry.py`**！

核心架构守则（五大红线）：
- 严禁在技能逻辑中写死倍率：必须通过 `self.skill_param("basic"|"skill"|"ultra"|"talent", idx, default=...)` 动态读取；
- 严禁访问 `self.port.sim` 或 `self.port._get_entity` 内部私有结构：一律调用 `self.port.*` 标准契约方法；
- 严禁跨插件硬编码耦合（如角色代码直接调用某把专属光锥的方法）：通过 `self.port.lose_hp` / `heal` / `attack` 产生标准 `BattleEvent`，由光锥/遗器自行监听；
- 严禁通过技能中文名子串判断动作类型：在 `on_event` 中使用 `isinstance(event, HealAppliedEvent | HPLostEvent | ActionExecuteEvent)`；
- 伴生忆灵专属 Buff 必须打上 `StatusTag.MEMOSPRITE_ONLY` 与 `StatusTag.EXCLUDE_FROM_STAT_TRANSFERS` 标签。
"""
from typing import Optional, Any
from ..base import KitHandler
from ..registry import register_kit
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...events import ActionExecuteEvent, HealAppliedEvent, HPLostEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StatusTag


# 复制后取消下方装饰器注释即可自动注册，无需修改 registry.py：
# @register_kit("9999", "示例角色", "example_character")
class ExampleCharacterKit(KitHandler):
    """示例角色 (ID 9999, 冰 / 记忆) 标准技能套件实现参考。"""

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.spirit_name: str = f"{owner_id}的忆灵"
        self.charge_points: int = 0

    def apply_trace_passives(self, entity: Any) -> None:
        """【可选钩子】战前静态阶段：注入角色行迹常驻属性或实机白字基线。"""
        # 示例：行迹常驻暴击率 +12%
        # entity.base_crit_rate += 0.12
        pass

    def get_initial_sp_cap(self) -> Optional[int]:
        """【可选钩子】若角色天赋提高全队战技点上限（如花火），在此返回新上限。"""
        return None

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        """【必填契约】声明各动作类型的目标模式、资源消耗、秘技优先级与分类标签。"""
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="示例普攻",
                tag="普攻"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(sp=1),
                name="示例战技",
                tag="战技"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ENEMIES,
                cost=ResourceCost(energy=120.0),
                name="示例终结技",
                tag="终结技"
            )
        elif kind == ActionKind.TECHNIQUE:
            # 秘技优先级 priority: 全队属性/治疗增益=0, 常规=1, 领域/拉条展开=2
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                name="示例秘技",
                priority=1,
                tag="秘技"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def on_battle_start(self) -> None:
        """【可选钩子】进战初始化：挂载常驻天赋光环、进战回能或召唤伴生忆灵。"""
        err = self.port.stat(self.owner_id, StatType.ERR) or 1.0
        self.port.gain_energy(self.owner_id, 20.0 * err)

        dmg_val = self.skill_param("talent", 0, default=0.20)
        self.port.upsert_status(BuffSpec(
            key=f"{self.owner_id}_Talent_Aura",
            name="示例天赋光环",
            source_id=self.owner_id,
            target_id=self.owner_id,
            modifiers=(Modifier(StatType.DMG_BOOST, ModifierOp.ADD, dmg_val),),
            duration=None,
            timing=DurationTiming.TARGET_TURN_END,
            category="buff",
            description=f"造成伤害提高 +{dmg_val * 100:.1f}%"
        ))

    def execute(self, ctx: ActionContext) -> None:
        """【必填契约】动作执行主分发。"""
        if ctx.kind == ActionKind.BASIC:
            enemies = self.port.enemies(self.owner_id)
            if not enemies:
                return
            target = ctx.target_ids[0] if ctx.target_ids else enemies[0]
            mult = self.skill_param("basic", 0, default=1.0)
            self.port.attack(
                self.owner_id,
                target,
                element="Ice",
                atk_multiplier=mult,
                toughness_damage=10.0,
                damage_tag="BasicAttack",
                scaling_stat="atk"
            )
            self.port.gain_energy(self.owner_id, 20.0)

        elif ctx.kind == ActionKind.SKILL:
            # 示例：基于自身暴伤（排除转化标签防死循环）为全队提供暴伤增益
            own_cd = self.port.stat(
                self.owner_id,
                StatType.CRIT_DMG,
                exclude_tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS, StatusTag.MEMOSPRITE_ONLY)
            )
            ratio = self.skill_param("skill", 0, default=0.20)
            shared_cd = round(own_cd * ratio, 4)

            for ally in self.port.allies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key=f"{self.owner_id}_Skill_Buff_{ally}",
                    name="示例战技增益",
                    source_id=self.owner_id,
                    target_id=ally,
                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, shared_cd),),
                    duration=2,
                    timing=DurationTiming.TARGET_TURN_END,
                    skip_current_clock=True,
                    category="buff",
                    tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS,),
                    description=f"暴击伤害提高 +{shared_cd * 100:.1f}%"
                ))
            self.port.gain_energy(self.owner_id, 30.0)

        elif ctx.kind == ActionKind.ULTIMATE:
            mult = self.skill_param("ultra", 0, default=2.0)
            for enemy in self.port.enemies(self.owner_id):
                self.port.attack(
                    self.owner_id,
                    enemy,
                    element="Ice",
                    atk_multiplier=mult,
                    toughness_damage=20.0,
                    damage_tag="Ultimate",
                    scaling_stat="atk"
                )
            self.port.gain_energy(self.owner_id, 5.0)

        elif ctx.kind == ActionKind.TECHNIQUE:
            self.charge_points += 1

    def intercept_incoming_damage(self, target_id: str, raw_damage: float) -> float:
        """【可选钩子】伤害分摊/减免拦截（如存护角色为队友分摊伤害）。"""
        return raw_damage

    def on_hp_lost(self, entity_id: str, actual_loss: float, cause: str) -> None:
        """【可选钩子】当自身或自身忆灵损失生命值时响应。"""
        if entity_id == self.owner_id or self.port.is_own_memosprite(self.owner_id, entity_id):
            self.charge_points += 1

    def on_event(self, event: Any) -> None:
        """【可选钩子】响应全局事实事件（严禁字符串模糊匹配，一律使用 isinstance）。"""
        if isinstance(event, HealAppliedEvent):
            if self.port.is_ally(event.source_name) and event.source_name != self.owner_id:
                self.charge_points += 1
        elif isinstance(event, ActionExecuteEvent):
            pass

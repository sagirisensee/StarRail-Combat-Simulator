"""【新人开发标准脚手架模板】角色与伴生忆灵技能套件 (_template.py)。

本文件提供两套完整可复制的标准模板：
- 模板 A (`ExampleCharacterKit`)：常规角色技能套件（普攻/战技/终结技/秘技/天赋光环/事件监听）；
- 模板 B (`ExampleMemospriteKit`)：记忆命途「伴生忆灵」独立技能套件及主从召唤联动。

使用方式：
1. 复制本文件为 `simulator/kits/characters/<character_pinyin>.py`（注意去掉开头的下划线 `_`）；
2. 取消 `@register_kit(...)` 装饰器注释并填写角色 ID、中文名、英文名；
3. 系统会自动扫描 `characters/` 目录并完成注册，**无需手动修改 `registry.py`**！

核心避坑提醒（详见 DEVELOPER_GUIDE.md 第二节）：
- 查倍率：用 `self.skill_param("basic"|"skill"|"ultra"|"talent", idx, default=...)`，其中 `idx=0` 对应官方描述 `#1`；
- 选操作符：百分比提速/加攻/加血用 `ModifierOp.PERCENT`，暴击/暴伤/增伤/抗穿/减防/易伤/固定数值用 `ModifierOp.ADD`；
- 防掉回合：当前回合内给自身或队友施加的 `TARGET_TURN_END` / `CASTER_TURN_END` Buff，务必加 `skip_current_clock=True`；
- 防死循环：基于自身属性比例分享给队友/忆灵的 Buff，务必加 `tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS,)`。
"""
from typing import Optional, Any
from ..base import KitHandler
from ..registry import register_kit
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...events import ActionExecuteEvent, HealAppliedEvent, HPLostEvent
from ...status import DurationTiming, Modifier, ModifierOp, StatType, StatusTag


# ============================================================================
# 模板 A：角色本体技能套件 (包含普通角色与记忆命途召唤者通用范式)
# 复制后取消下方装饰器注释即可自动注册，无需修改 registry.py：
# @register_kit("9999", "示例角色", "example_character")
# ============================================================================
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
        self.spirit_alive: bool = False
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

    def summon_companion_spirit(self) -> Any:
        """【记忆命途专用】召唤伴生忆灵入场并绑定独立 Kit。"""
        self.spirit_alive = True
        spirit_max_hp = round(0.50 * self.port.max_hp(self.owner_id))
        spirit = self.port.summon_spirit(
            owner_id=self.owner_id,
            name=self.spirit_name,
            base_speed=160.0,
            max_hp=spirit_max_hp,
            kit_class=ExampleMemospriteKit,
            kit_args={"master_kit": self}
        )
        return spirit

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


# ============================================================================
# 模板 B：伴生忆灵独立技能套件 (仅「记忆」命途等拥有召唤物的角色需要)
# ============================================================================
class ExampleMemospriteKit(KitHandler):
    """伴生忆灵独立技能套件模板。"""

    def __init__(self, owner_id: str, port: CombatPort, master_kit: Optional[ExampleCharacterKit] = None):
        super().__init__(owner_id, port)
        self.master_kit = master_kit

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        return AbilityDefinition(
            kind=ActionKind.SKILL,
            target_mode=TargetMode.SINGLE_ENEMY,
            cost=ResourceCost(sp=0),
            name="示例忆灵技",
            tag="忆灵技"
        )

    def execute(self, ctx: ActionContext) -> None:
        enemies = self.port.enemies(self.owner_id)
        if not enemies or not self.master_kit:
            return
        target = ctx.target_ids[0] if ctx.target_ids else enemies[0]
        self.port.attack(
            self.master_kit.owner_id,
            target,
            element="Ice",
            atk_multiplier=0.80,
            toughness_damage=10.0,
            damage_tag="MemospriteSkill",
            scaling_stat="hp"
        )

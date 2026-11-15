"""光锥：爱如此刻永恒 (This Love, Forever - ID 23052).

命途：记忆 (5★)
核心效果【约定】：
1. 使装备者的速度提高 18% / 21% / 24% / 27% / 30% (基础面板已计入)；
2. 装备者的忆灵对我方单体施放忆灵技时获得【空白】：敌方全体受到的伤害提高 10% / 12% / 14% / 16% / 18%；
3. 装备者的忆灵对敌方施放忆灵技时获得【诗行】：我方全体的暴击伤害提高 16% / 19% / 22% / 25% / 28%；
4. 装备者的忆灵同时持有【空白】和【诗行】时，【空白】和【诗行】的效果提高 60% / 65% / 70% / 75% / 80%。
"""
from typing import Any
from ..base import LightConeHandler
from ..registry import register_light_cone
from ...actions import ActionContext, TargetMode
from ...combat_port import BuffSpec
from ...events import ActionExecuteEvent, EnemySpawnedEvent, SpiritSummonedEvent, TurnBeginEvent
from ...status import Modifier, ModifierOp, StatType


@register_light_cone(
    cone_id="23052",
    name="爱如此刻永恒",
    path="Memory",
    rarity=5,
    aliases=("This Love, Forever",),
)
class ThisLoveForeverHandler(LightConeHandler):
    """《爱如此刻永恒》专属战斗逻辑处理器。"""

    CRIT_DMG_VALUES = (0.16, 0.19, 0.22, 0.25, 0.28)
    VULN_VALUES = (0.10, 0.12, 0.14, 0.16, 0.18)
    AMP_VALUES = (0.60, 0.65, 0.70, 0.75, 0.80)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._has_blank = False
        self._has_poem = False

    def _is_own_memosprite(self, entity_id: str) -> bool:
        if not self.port:
            return False
        sim = getattr(self.port, "sim", None)
        ent = sim.get_entity(entity_id) if sim is not None else None
        return (
            ent is not None
            and getattr(ent, "is_memosprite", False)
            and getattr(ent, "master_name", None) == self.owner_id
        )

    def _sync_auras(self) -> None:
        if not self.port:
            return
        amp = 1.0 + (self.scale(self.AMP_VALUES) if (self._has_blank and self._has_poem) else 0.0)
        if self._has_poem:
            cd_val = self.scale(self.CRIT_DMG_VALUES) * amp
            for ally in self.port.allies(self.owner_id):
                if hasattr(self.port, "is_countdown") and self.port.is_countdown(ally):
                    continue
                self.port.upsert_status(
                    BuffSpec(
                        key="LC_ThisLoveForever_Poem",
                        name=f"诗行 (爱如此刻永恒S{self.superimposition}全队暴伤+{cd_val * 100:.1f}%)",
                        source_id=self.owner_id,
                        target_id=ally,
                        modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_val),),
                        duration=None,
                    )
                )
        if self._has_blank:
            vuln_val = self.scale(self.VULN_VALUES) * amp
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(
                    BuffSpec(
                        key="LC_ThisLoveForever_Blank",
                        name=f"空白 (爱如此刻永恒S{self.superimposition}敌方易伤+{vuln_val * 100:.1f}%)",
                        source_id=self.owner_id,
                        target_id=enemy,
                        modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, vuln_val),),
                        duration=None,
                        category="debuff",
                    )
                )

    def on_action_before(self, ctx: ActionContext) -> None:
        if not self.port or not self._is_own_memosprite(ctx.actor_id):
            return
        if ctx.ability.target_mode in (TargetMode.SINGLE_ENEMY, TargetMode.BLAST, TargetMode.ALL_ENEMIES, TargetMode.BOUNCE):
            self._has_poem = True
        elif ctx.ability.target_mode == TargetMode.SINGLE_ALLY:
            self._has_blank = True
        self._sync_auras()

    def on_event(self, event: Any) -> None:
        if not self.port:
            return
        if isinstance(event, TurnBeginEvent) and self._is_own_memosprite(event.actor_id):
            sim = getattr(self.port, "sim", None)
            ent = sim.get_entity(event.actor_id) if sim is not None else None
            kit = getattr(ent, "kit", None) if ent is not None else None
            if kit is not None and hasattr(kit, "definition"):
                from ...actions import ActionKind
                try:
                    defn = kit.definition(ActionKind.SKILL)
                    if defn.target_mode in (TargetMode.SINGLE_ENEMY, TargetMode.BLAST, TargetMode.ALL_ENEMIES, TargetMode.BOUNCE):
                        self._has_poem = True
                    elif defn.target_mode == TargetMode.SINGLE_ALLY:
                        self._has_blank = True
                except Exception:
                    pass
            self._sync_auras()
        elif isinstance(event, (SpiritSummonedEvent, EnemySpawnedEvent, ActionExecuteEvent)):
            if self._has_poem or self._has_blank:
                self._sync_auras()

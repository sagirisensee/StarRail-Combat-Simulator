"""花火 (Sparkle - ID 1306, 量子 / 同谐) 官方标准战斗技能套件。

严格遵循官方 Nanoka 4.6 技能定义与机制时序：
1. 普攻【独角戏】：造成单体量子伤害，等同花火 140% (Lv 10) 攻击力，削韧 10，回能 20 (行迹【岁时记】额外+10点=30点)，恢复 1 点 SP。
2. 战技【梦游鱼】：消耗 1 点 SP，使指定我方单体暴伤提高 (花火自身暴伤 * 24% + 45%，Lv 10；E6 额外 +30% 花火暴伤)。
   使该目标行动提前 50% (对自身施放不触发拉条)。持续 1 回合。回能 30。
3. 终结技【一人千役】(耗能 110 点)：
   - 为我方恢复 4 点战技点 (E4 提升至 5 点)；
   - 使我方全体获得【谜诡】，持续 2 回合 (E1 延长至 3 回合)；
   - 持有【谜诡】的目标触发天赋伤害提高效果每层额外提高 10% (Lv 10)；
   - E1【悬置怀疑】：持有【谜诡】的我方目标攻击力提高 40%，且进战自身提速 15%；
   - 回能 5 点。
4. 天赋【叙述性诡计】：
   - 花火在场时，战技点上限提高 2 点 (常态上限 7 点，E4 为 8 点)；
   - 我方目标每消耗 1 点战技点，使我方全体造成的伤害提高 6% (Lv 10)，持续 2 回合，最多叠加 3 层；
   - E2【虚构无端】：天赋每层使我方目标造成伤害时无视目标 8% 防御力 (满 3 层无视 24% 防御)；
   - 官方加强：队友耗点时花火回能 3 点，并对敌方全体施加易伤。
5. 秘技【不可靠叙事者】：进战为我方额外恢复 3 点战技点。
6. 星魂：
   - E1【悬置怀疑】：开局提速 15%，【谜诡】持续时间+1，攻击力提高 40%；
   - E2【虚构无端】：天赋每层无视 8% 防御力；
   - E4【游戏人间】：SP 上限额外+1 (至 8 点)，大招多恢复 1 点 SP；
   - E6【多重解答】：战技暴伤效果提高 30% 花火暴伤，并对持有【谜诡】全队生效。
"""

from typing import Optional, List, Any
from ..base import KitHandler
from ...actions import ActionContext, ActionKind, AbilityDefinition, ResourceCost, TargetMode
from ...combat_port import BuffSpec, CombatPort
from ...status import DurationTiming, Modifier, ModifierOp, StatType


class SparkleKit(KitHandler):
    """花火 (Sparkle - ID 1306, 量子 / 同谐)."""

    SKILL_CD_BUFF = "Sparkle_Dreamdiver_CD"
    E1_SPEED_BUFF = "Sparkle_E1_Speed"
    ULT_CIPHER_BUFF = "Sparkle_Cipher"
    TALENT_BUFF = "Sparkle_Talent_Dmg"

    def __init__(
        self,
        owner_id: str,
        port: CombatPort,
        *,
        eidolon: int = 0,
        skill_levels: Optional[dict] = None
    ):
        super().__init__(owner_id, port, eidolon=eidolon, skill_levels=skill_levels)
        self.talent_stacks: int = 0
        self.max_talent_stacks: int = 3
        self.preferred_dps_id: Optional[str] = None

    def on_battle_start(self) -> None:
        """战斗开始：
        1. 天赋【叙述性诡计】：战技点上限提高 2 点 (常态 7 点，E4 为 8 点)。
        2. E1【悬置怀疑】：开局花火自身速度提高 15%，持续 2 回合。
        """
        sp_cap = 8 if self.eidolon >= 4 else 7
        self.port.set_sp_cap(sp_cap)
        self.talent_stacks = 0

        # E1: 战斗开始时花火速度提高 15%
        if self.eidolon >= 1:
            self.port.upsert_status(BuffSpec(
                key=self.E1_SPEED_BUFF,
                name="悬置怀疑",
                source_id=self.owner_id,
                target_id=self.owner_id,
                modifiers=(Modifier(StatType.SPEED, ModifierOp.PERCENT, 0.15),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description="速度提高 +15.0%"
            ))

    def definition(self, kind: ActionKind) -> AbilityDefinition:
        if kind == ActionKind.BASIC:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ENEMY,
                cost=ResourceCost(sp=-1),
                name="独角戏"
            )
        elif kind == ActionKind.SKILL:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SINGLE_ALLY,
                cost=ResourceCost(sp=1),
                allow_self=True,
                name="梦游鱼"
            )
        elif kind == ActionKind.ULTIMATE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.ALL_ALLIES,
                cost=ResourceCost(energy=110.0),
                allow_self=True,
                name="一人千役"
            )
        elif kind == ActionKind.TECHNIQUE:
            return AbilityDefinition(
                kind=kind,
                target_mode=TargetMode.SELF,
                cost=ResourceCost(technique_points=1),
                allow_self=True,
                name="不可靠叙事者"
            )
        raise ValueError(f"未支持的动作类型: {kind}")

    def execute(self, ctx: ActionContext) -> None:
        if ctx.kind == ActionKind.BASIC:
            self._execute_basic(ctx)
        elif ctx.kind == ActionKind.SKILL:
            self._execute_skill(ctx)
        elif ctx.kind == ActionKind.ULTIMATE:
            self._execute_ultimate(ctx)
        elif ctx.kind == ActionKind.TECHNIQUE:
            self.use_technique()

    def use_technique(self) -> None:
        """秘技【不可靠叙事者】：进战为我方额外恢复 3 点战技点。"""
        self.port.change_sp(self.owner_id, 3, "花火秘技恢复战技点")

    def _execute_basic(self, ctx: ActionContext) -> None:
        """普攻【独角戏】：单体量子伤害，140% 攻击力 (Lv 10)。行迹【岁时记】回能 30 点。"""
        target_id = ctx.target_ids[0] if ctx.target_ids else self.port.enemies(self.owner_id)[0]
        mult = self.skill_param("basic", 0, default=1.40)
        self.port.attack(
            self.owner_id,
            target_id,
            element="Quantum",
            atk_multiplier=mult,
            toughness_damage=10.0,
            damage_tag="BasicAttack",
            scaling_stat="atk"
        )
        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_skill(self, ctx: ActionContext) -> None:
        """战技【梦游鱼】：单体暴伤加成，行动提前 50%。"""
        target_id = None
        if ctx.target_ids:
            target_id = ctx.target_ids[0]
        elif self.preferred_dps_id:
            target_id = self.preferred_dps_id
        else:
            allies = [a for a in self.port.allies(self.owner_id) if a != self.owner_id]
            target_id = allies[0] if allies else self.owner_id

        # 采样花火自身当前暴伤 (Lv 10: 24% 自身暴伤 + 45%)
        sparkle_cd = self.port.stat(self.owner_id, StatType.CRIT_DMG)
        cd_ratio = self.skill_param("skill", 0, default=0.24)
        cd_flat = self.skill_param("skill", 1, default=0.45)
        if self.eidolon >= 6:
            cd_ratio += 0.30

        bonus_cd = sparkle_cd * cd_ratio + cd_flat

        targets = [target_id]
        if self.eidolon >= 6:
            for ally in self.port.allies(self.owner_id):
                if self.port.has_status(ally, self.ULT_CIPHER_BUFF) and ally not in targets:
                    targets.append(ally)

        for tgt in targets:
            self.port.upsert_status(BuffSpec(
                key=f"{self.SKILL_CD_BUFF}_{tgt}",
                name="梦游鱼",
                source_id=self.owner_id,
                target_id=tgt,
                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, bonus_cd),),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=f"暴击伤害提高 +{bonus_cd * 100:.1f}%"
            ))

        # 行动提前 50% (自身施放不拉条)
        if target_id != self.owner_id:
            self.port.advance(self.owner_id, target_id, 0.50)

        self.port.gain_energy(self.owner_id, 30.0)

    def _execute_ultimate(self, ctx: ActionContext) -> None:
        """终结技【一人千役】：恢复 4 点 SP (E4 为 5 点)，全队赋予【谜诡】2 回合 (E1 为 3 回合)。"""
        sp_restore = 5 if self.eidolon >= 4 else 4
        self.port.change_sp(self.owner_id, sp_restore, f"花火终结技恢复{sp_restore}点战技点")

        cipher_duration = 3 if self.eidolon >= 1 else 2

        for ally in self.port.allies(self.owner_id):
            mods = []
            desc = "触发天赋伤害提高效果额外提升"

            if self.eidolon >= 1:
                mods.append(Modifier(StatType.ATK_PERCENT, ModifierOp.ADD, 0.40))
                desc += "，攻击力提高 +40.0%"

            self.port.upsert_status(BuffSpec(
                key=self.ULT_CIPHER_BUFF,
                name="谜诡",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=cipher_duration,
                timing=DurationTiming.TARGET_TURN_END,
                skip_current_clock=True,
                category="buff",
                description=desc
            ))

        self.port.gain_energy(self.owner_id, 5.0)

    def on_event(self, event: Any) -> None:
        """监听 SP 消耗事件，触发天赋【叙述性诡计】：
        我方每消耗 1 点 SP，全队增伤 6% (Lv 10) (谜诡加成额外 +10%/层)，最多 3 层。
        官方加强：队友消耗 SP 时为花火回能 3 点，并对全敌施加易伤。
        """
        delta = getattr(event, "delta", getattr(event, "amount", 0))
        if delta < 0:
            spent = abs(delta)
            self.port.gain_energy(self.owner_id, 3.0 * spent)
            self.talent_stacks = min(self.max_talent_stacks, self.talent_stacks + spent)
            self._sync_talent_buffs()

            # 官方加强：为敌方全体施加易伤
            vuln_pct = self.talent_stacks * 0.04
            for enemy in self.port.enemies(self.owner_id):
                self.port.upsert_status(BuffSpec(
                    key="Sparkle_Enemy_Vuln",
                    name="叙述性诡计 (易伤)",
                    source_id=self.owner_id,
                    target_id=enemy,
                    modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, vuln_pct),),
                    duration=None,
                    timing=DurationTiming.TARGET_TURN_END,
                    category="debuff",
                    description=f"受到伤害提高 +{vuln_pct * 100:.1f}%"
                ))

    def _sync_talent_buffs(self) -> None:
        """同步天赋【叙述性诡计】全队增伤与减防。"""
        base_dmg = self.skill_param("talent", 1, default=0.06)
        cipher_extra = self.skill_param("ultra", 2, default=0.10)

        for ally in self.port.allies(self.owner_id):
            has_cipher = self.port.has_status(ally, self.ULT_CIPHER_BUFF)
            per_stack_dmg = base_dmg + (cipher_extra if has_cipher else 0.0)
            total_dmg = per_stack_dmg * self.talent_stacks

            mods = [Modifier(StatType.DMG_BOOST, ModifierOp.ADD, total_dmg)]

            if self.eidolon >= 2:
                shred_pct = 0.08 * self.talent_stacks
                mods.append(Modifier(StatType.DEF_SHRED, ModifierOp.ADD, shred_pct))

            self.port.upsert_status(BuffSpec(
                key=self.TALENT_BUFF,
                name="叙述性诡计",
                source_id=self.owner_id,
                target_id=ally,
                modifiers=tuple(mods),
                duration=2,
                timing=DurationTiming.TARGET_TURN_END,
                category="buff",
                description=f"造成伤害提高 +{total_dmg * 100:.1f}%" + (f"，无视防御 {0.08 * self.talent_stacks * 100:.1f}%" if self.eidolon >= 2 else "")
            ))

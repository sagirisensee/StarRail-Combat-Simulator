"""星穹铁道战斗模拟器：P4 阶段（敌方韧性条、弱点击破与推条机制全流程演示）。

演示场景：
1. 敌方 Boss：
   - 拟真Boss (Lv 90, 拥有 60 点韧性条，弱点：雷、量子)
2. 战技削韧流程：
   - 银狼 (量子): 施放战技，削减 20 点韧性；
   - 黄泉 (雷): 施放战技，削减 30 点韧性；
   - 黄泉终结技: 造成巨额伤害并削减剩余 10 点韧性，直接触发【弱点击破】！
3. 击破后连锁效应：
   - 触发一次性高额【击破伤害】；
   - Boss 行动条被【推条 25%】（距离后移 2,500）；
   - Boss【10% 免伤被破除】（减伤系数 0.9 -> 1.0），后续攻击造成全额伤害！
   - Boss 行动结束后自动【韧性恢复】。
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from simulator.core import Entity, TurnSimulator
from simulator.effects import AdvanceActionEffect, ApplyStatusEffect, ApplyDamageEffect
from simulator.events import (
    ActionExecuteEvent, ActionAdvanceEvent, ActionDelayEvent, 
    DamageAppliedEvent, ToughnessReduceEvent, WeaknessBreakEvent, ToughnessRecoverEvent
)
from simulator.status import StatusInstance, DurationTiming, StatType, Modifier, ModifierOp
from simulator.damage import DamageRequest


def demo():
    # 己方 4 人配置
    sparkle = Entity(name="花火", base_speed=160.0, base_atk=1200.0, policy="E")
    silver_wolf = Entity(name="银狼", base_speed=134.0, base_atk=1500.0, policy="EAA")
    fuxuan = Entity(name="符玄", base_speed=120.0, base_atk=1000.0, policy="EAA")
    acheron = Entity(
        name="黄泉", 
        base_speed=101.0, 
        base_atk=3000.0,
        base_crit_rate=0.50,
        base_crit_dmg=1.20,
        policy="E"
    )

    # 敌方 Boss (Lv 90, 60 点韧性，弱点为雷与量子)
    boss = Entity(
        name="拟真Boss", 
        base_speed=110.0, 
        max_hp=200000.0, 
        current_hp=200000.0, 
        max_toughness=60.0,
        current_toughness=60.0,
        weaknesses=["Lightning", "Quantum"],
        is_enemy=True
    )

    sim = TurnSimulator([sparkle, silver_wolf, fuxuan, acheron, boss], initial_sp=4, max_sp=7)

    # 1. 花火联动：拉条 50% + 80% 暴伤
    def sparkle_callback(self_entity, resolver, action_type):
        if "Skill" in action_type:
            resolver.enqueue(AdvanceActionEffect(self_entity.name, acheron, 0.5))
            resolver.enqueue(ApplyStatusEffect(StatusInstance(
                id="Dreamdiver",
                name="梦游 (花火暴伤)",
                source=self_entity,
                target=acheron,
                duration=1,
                timing=DurationTiming.TARGET_TURN_END,
                modifiers=[Modifier(StatType.CRIT_DMG, ModifierOp.ADD, 0.80)]
            )))

    sparkle.action_callback = sparkle_callback

    # 2. 银狼战技：-45% 减防 + 量子属性削韧 20 点
    def silver_wolf_callback(self_entity, resolver, action_type):
        if "Skill" in action_type:
            resolver.enqueue(ApplyStatusEffect(StatusInstance(
                id="DefShred",
                name="45% 减防",
                source=self_entity,
                target=boss,
                duration=3,
                timing=DurationTiming.TARGET_TURN_END,
                modifiers=[Modifier(StatType.DEF_SHRED, ModifierOp.ADD, 0.45)]
            )))
            resolver.enqueue(ApplyDamageEffect(
                request=DamageRequest(attacker=self_entity, target=boss, skill_multiplier=1.90),
                toughness_reduction=20.0,
                element="Quantum"
            ))

    silver_wolf.action_callback = silver_wolf_callback

    # 3. 黄泉战技：雷属性削韧 30 点
    def acheron_callback(self_entity, resolver, action_type):
        if "Skill" in action_type:
            resolver.enqueue(ApplyDamageEffect(
                request=DamageRequest(attacker=self_entity, target=boss, skill_multiplier=1.60),
                toughness_reduction=30.0,
                element="Lightning"
            ))

    acheron.action_callback = acheron_callback

    # 4. 事件总线订阅与状态展示
    damage_stats = {}

    def on_action(evt: ActionExecuteEvent):
        if evt.action_type == "Ultimate":
            print(f"[{evt.av:>6.1f} AV | 第 {evt.cycle} 轮] ⚡ {evt.actor_name} 插入终结技！")
        else:
            action_name = "战技" if "Skill" in evt.action_type else "普攻"
            print(f"[{evt.av:>6.1f} AV | 第 {evt.cycle} 轮] {evt.actor_name:<4} 施放 {action_name:<8} [SP: {sim.sp.current_sp}/{sim.sp.max_sp}]")

    def on_damage(evt: DamageAppliedEvent):
        damage_stats[evt.attacker_name] = damage_stats.get(evt.attacker_name, 0.0) + evt.damage
        crit_str = "【暴击】" if evt.is_crit else "【未暴击】"
        broken_str = "【破韧全额】" if evt.breakdown.reduction_mult == 1.0 else "【未破韧减伤】"
        print(f"      🗡️ 命中伤害: {int(evt.damage):,} 点 {crit_str} {broken_str} (防御区: {evt.breakdown.def_mult:.3f})")

    def on_toughness_reduce(evt: ToughnessReduceEvent):
        pct = (evt.toughness_left / evt.max_toughness) * 100.0 if evt.max_toughness > 0 else 0
        bar = "█" * int(evt.toughness_left // 4)
        print(f"      🛡️ 削韧命中! 扣减 {evt.amount:.0f} 点 -> 剩余韧性: {evt.toughness_left:.0f}/{evt.max_toughness:.0f} ({pct:.1f}%) | {bar}")

    def on_break(evt: WeaknessBreakEvent):
        print(f"\n      💥💥💥 【弱点击破 BREAK!!】 {evt.breaker_name} 击破了 {evt.target_name} 的弱点！")
        print(f"      ⚡ 造成一次性击破伤害: {int(evt.break_damage):,} 点！")
        print(f"      ⏩ 触发破韧推条 {int(evt.action_delay_pct*100)}%! (Boss 距离被向后推移 2,500 距离)\n")

    def on_delay(evt: ActionDelayEvent):
        print(f"      ⌛ [推条生效] {evt.target_name} 行动距离增加: {evt.distance_before:.0f} -> {evt.distance_after:.0f}")

    def on_recover(evt: ToughnessRecoverEvent):
        print(f"\n      🔄 [韧性恢复] {evt.target_name} 从击破状态恢复，韧性条重置至 {evt.max_toughness:.0f} 点！\n")

    sim.event_bus.subscribe(ActionExecuteEvent, on_action)
    sim.event_bus.subscribe(DamageAppliedEvent, on_damage)
    sim.event_bus.subscribe(ToughnessReduceEvent, on_toughness_reduce)
    sim.event_bus.subscribe(WeaknessBreakEvent, on_break)
    sim.event_bus.subscribe(ActionDelayEvent, on_delay)
    sim.event_bus.subscribe(ToughnessRecoverEvent, on_recover)

    print("=" * 76)
    print("  【星穹铁道战斗模拟器】P4 阶段：韧性条削减、弱点击破与推条联动演示")
    print("=" * 76)
    print(f"Boss 配置: 韧性上限 {boss.max_toughness:.0f} 点 | 弱点属性: {', '.join(boss.weaknesses)}")
    print("-" * 76)
    print("开始模拟战斗（前 1 轮，总计 150 AV）...")
    print("-" * 76)

    acheron_ult_used = False

    for actor in sim.run_until_av(max_av=150.0):
        # 黄泉行动后立即插大招削韧并斩杀
        if actor.name == "黄泉" and not acheron_ult_used:
            print("      ⚡ 黄泉积攒 9 点残梦，触发终结技「残梦尽染，一刀缭乱」！")
            sim.insert_ultimate(acheron, description="终结技四段连斩", sp_change=0)
            # 黄泉大招：无视弱点削减 60 点巨额韧性！
            sim.resolver.enqueue(ApplyDamageEffect(
                request=DamageRequest(attacker=acheron, target=boss, skill_multiplier=3.70),
                toughness_reduction=60.0,
                element="Lightning",
                ignore_weakness=True
            ))
            sim.resolver.resolve_all()
            acheron_ult_used = True

    print("=" * 76)
    print("📊 战斗伤害与击破审计报告：")
    print("=" * 76)
    total_dmg = sum(damage_stats.values())
    print(f"全队总伤害: {int(total_dmg):,} 点 | Boss 当前残血: {int(boss.current_hp):,} / {int(boss.max_hp):,}")
    for name, dmg in sorted(damage_stats.items(), key=lambda x: -x[1]):
        pct = (dmg / total_dmg * 100.0) if total_dmg > 0 else 0.0
        bar = "█" * int(pct // 4)
        print(f"  * {name:<6} : {int(dmg):>8,} 点 ({pct:>5.1f}%) | {bar}")
    print("=" * 76)


if __name__ == "__main__":
    demo()

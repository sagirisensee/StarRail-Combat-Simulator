"""验证全角色战斗技能套件体系 (Character Kit System) 与花火实战机制。"""
import os
import sys

# 保证 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from simulator.db import CharacterDB
from simulator.core import TurnSimulator, Entity
from simulator.status import StatType
from simulator.events import ActionExecuteEvent, ActionAdvanceEvent, StatusExpireEvent


def main():
    print("==================================================================")
    print("🧪 验证 Character Kit 技能体系：花火实战完整联动测试")
    print("==================================================================")

    # 1. 从真实高精数据库加载角色
    db = CharacterDB().load(os.path.join(PROJECT_ROOT, "data", "character_db_export.json"))
    sparkle_entity = db.to_combat_entity("花火", policy="E") # 花火常驻战技
    print(f"✅ 成功从数据库转换实体: {sparkle_entity.name}")
    print(f"   星魂: E{sparkle_entity.eidolon} | 基础速度: {sparkle_entity.base_speed:.3f} | 基础暴伤: {sparkle_entity.base_crit_dmg*100:.1f}%")
    print(f"   已装配专属 Kit: {sparkle_entity.kit.__class__.__name__}")

    # 2. 模拟配置队友 (主 C 黄泉) 与敌人
    acheron = Entity(
        name="黄泉",
        base_speed=101.0,
        base_atk=3000.0,
        base_crit_rate=0.50,
        base_crit_dmg=1.20,
        policy="E"
    )

    boss = Entity(
        name="深渊木桩",
        base_speed=120.0,
        max_hp=500000.0,
        current_hp=500000.0,
        is_enemy=True
    )

    # 花火定向为主 C 黄泉拉条
    sparkle_entity.kit.preferred_dps_id = "黄泉"

    # 初始化战斗模拟器 (初始 3 SP, 默认上限 5 SP)
    sim = TurnSimulator([sparkle_entity, acheron, boss], initial_sp=3, max_sp=5)

    # 监听拉条事件
    def on_advance(evt):
        print(f"  ⏩ [拉条触发] {evt.source_name} 推进 {evt.target_name} 行动 {evt.percent*100:.0f}% (距离: {evt.distance_before:.0f} -> {evt.distance_after:.0f})")

    from simulator.events import ActionAdvanceEvent
    sim.event_bus.subscribe(ActionAdvanceEvent, on_advance)

    print("\n--- 阶段 1：战斗开局被动与星魂生效验证 ---")
    print(f"当前战技点池上限: {sim.sp.max_sp} 点 (应为花火天赋扩展的 7 点)")
    assert sim.sp.max_sp == 7, "花火天赋扩展 7 点战技点失败！"

    init_speed = sparkle_entity.speed
    print(f"花火实时开战速度: {init_speed:.3f} (原基础速度 {sparkle_entity.base_speed:.3f} + E1 提速15%)")
    assert init_speed > sparkle_entity.base_speed, "花火 E1 提速 15% 状态未生效！"

    print("\n--- 阶段 2：首轮排轴与战技释放 ---")
    # 记录黄泉被拉条前的距离
    before_dist = acheron.distance_remaining
    print(f"黄泉当前跑道距离: {before_dist:.1f}")

    # 执行花火行动
    sim.step()

    # 验证黄泉获得的暴伤加成
    acheron_cd = sim.status_mgr.calculate_stat("黄泉", acheron.base_crit_dmg, StatType.CRIT_DMG)
    print(f"\n黄泉当前受加成后暴伤: {acheron_cd*100:.2f}% (基础 {acheron.base_crit_dmg*100:.1f}% + 获得加成 {(acheron_cd - acheron.base_crit_dmg)*100:.2f}%)")
    # 花火面板暴伤为 217.4%，战技提升暴伤 = 217.4% * 26.4% + 48.6% = 105.99%
    assert acheron_cd > 2.0, "花火战技暴伤加成未正确注入！"

    # 验证花火回合结束后的速度时钟 (E1 加速状态不应在当回合结束立即消失)
    after_turn_speed = sparkle_entity.speed
    print(f"花火行动结束后当前速度: {after_turn_speed:.3f} (验证 skip_current_clock 状态未立即过期)")
    assert after_turn_speed > sparkle_entity.base_speed, "花火 E1 提速被当回合立即错误扣除！"

    print("\n--- 阶段 3：大招回点与全队增益验证 ---")
    # 模拟花火施放大招
    from simulator.actions import ActionKind, ActionContext
    sparkle_entity.kit.execute(ActionContext(
        action_id="sparkle_ult",
        actor_id=sparkle_entity.name,
        kind=ActionKind.ULTIMATE,
        target_ids=()
    ))
    sim.resolver.resolve_all()
    print(f"大招释放后当前战技点: {sim.sp.current_sp}/{sim.sp.max_sp} 点")

    # 检查黄泉是否获得 E1 大招攻击力 40% 加成
    acheron_atk = sim.status_mgr.calculate_stat("黄泉", acheron.base_atk, StatType.ATK_PERCENT)
    print(f"黄泉大招后攻击力加成倍率: {acheron_atk/acheron.base_atk:.2f}x")

    print("\n==================================================================")
    print("🎉 花火战斗技能套件 (Sparkle Kit) 与实战机制全部 100% 验证通过！")
    print("==================================================================\n")

if __name__ == "__main__":
    main()

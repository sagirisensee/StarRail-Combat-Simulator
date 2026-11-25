# 微内核统一执行管线架构蓝图（Kernel Execution Pipeline）

本文档记录 `StarRail-Combat-Simulator` 从“全量通关日志倒逼、外围打补丁”向“统一微内核状态机 + 机制族覆盖 + 极简探针验证”演进的架构设计、Phase 1 落地产物与后续路线图。

---

## 一、历史痛点：双世界观接缝与 6 处核心耦合簇

在 Phase 1 收口前，`TurnSimulator` 微内核与 `VMRuntime` 之间存在“微内核发 `EventBus` 事件 → `VMRuntime` 靠 16 个隐式 `_pending_*` / `_in_*` 标志打补丁延后执行 → 回调 `ActionScheduler`”的双轨接缝，具体体现为以下 **6 处耦合簇**：

1. **攻击帧与 8 阶段收口双轨分叉**
   - [`simulator/vm/runtime.py`](../simulator/vm/runtime.py) 的 `flush_pending_after_attack` 与 [`simulator/vm/ops/combat_ops.py`](../simulator/vm/ops/combat_ops.py) 的 `_finalize_attack_lifecycle`（非嵌套 `scope_depth == 0` 分支）各写了一套不同步的 `OnAfterAttack` / `OnAfterBeingAttackedEnd` / 死亡收口逻辑。
2. **分散的 16 个生命周期私有标志**
   - `_attack_scope_depth`、`_in_turn_phase1_end`、`_in_after_attack`、`_in_dying_batch`、`_flushing_listen_die`、`_pending_after_attack`、`_after_attack_fired`、`_attack_targets_by_key`、`_attack_blocked_targets`、`_open_enemy_attack`、`_pending_dying_enemies`、`_pending_limbo_after_dying`、`_pending_level_kills`、`_pending_dead_enemies`、`_pending_listen_die`、`_active_deathrattle_entities` 分散在 `VMRuntime` / `combat_ops.py` / `stage_ops.py` / `turn_ops.py` 中以 `getattr(..., None)` 懒初始化。
3. **亡语悬停态 (`_in_deathrattle_limbo`) 散落清理**
   - 悬停置位、动作计数递减、即时退场与延迟 `OnListenCharacterDie` 在 `combat_ops.py`、`stage_ops.py`、`turn_ops.py` 与 `runtime.py` 中重复实现。
4. **`_action_frame_depth` 手工归零外泄**
   - [`simulator/vm/runtime.py`](../simulator/vm/runtime.py)、[`simulator/vm/enemy_kit.py`](../simulator/vm/enemy_kit.py) 与 [`simulator/vm/stage_director.py`](../simulator/vm/stage_director.py) 在 6 处直接读写 `sched._action_frame_depth = 0` 来绕过原子帧拦截，缺少统一的受保护边界入口。
5. **敌方多动与连动未纳入 `TurnFrame`（已在 Phase 3 收口）**
   - 我方主动作、`UseSkillOneMore` 连动与终结技抢断已在 Phase 2 收编至 `TurnSimulator._run_kit_action_frame` 与 `_run_char_one_more_chain`，全部 VM Ability 帧（我方、敌方、追击、欢愉技、`BattleEvent`）已统一收编至 `ExecutionLifecycle.run_ability_frame(AbilityFrameSpec)`；
   - Phase 3 已在 `EnemyKit` 引入分步子动作契约（`EnemySubActionOutcome`、`begin_turn_session` / `execute_next_sub_action` / `finish_turn_session`），由 `TurnSimulator._run_enemy_turn_frame` 与 `_on_turn_sub_action_boundary` 统一驱动敌方多动、子动作间隙 `OnListenBeforeTurnPhase1End` 与受控 `drain_window()`，并将 `enemy_kit.py` 最后一处 `event_bus.subscribe` 迁移至 `ExecutionLifecycle.capture_damage_targets()`；同时以显式 `InterventionHook` / `CallbackInterventionHook` 取代 `replay.py` 挂在 `sim` 上的 5 个动态猴子补丁属性。
6. **VM 静态覆盖率审计器失真**
   - [`simulator/vm/audit_vm_coverage.py`](../simulator/vm/audit_vm_coverage.py) 在 `TaskExecutor` 拆分出 `_TASK_DISPATCH` 分发表后漏扫了全部静态注册条目，导致 5 星角色/光锥/遗器覆盖率错误显示为 `2.1%` / `0.0%`。

---

## 二、Phase 1 + Phase 2 落地的三层统一执行状态机

Phase 1 与 Phase 2 已将 **簇 1、簇 2、簇 3、簇 4、簇 6** 以及“双总线来回踢皮球 / 六套平行 Ability 帧”（原第 1、2 刀）彻底收口为单一显式状态机与线性调用栈：

### 1. 状态机总览 (`TurnSimulator.emit_event` + `ExecutionLifecycle` + `ActionScheduler`)

```text
TurnFrame (core.py)
  ├─ TurnPrepare / TurnBegin -> emit_event -> dispatch_combat_fact(VMRuntime -> StageDirector) -> EventBus (只读)
  │    └─ TurnPhase1End Scope (lifecycle.turn_phase1_end_scope)
  ├─ ActionPerform -> _run_kit_action_frame (主动作 / UseSkillOneMore / 终结技)
  │    └─ AbilityFrame (lifecycle.run_ability_frame(AbilityFrameSpec))
  │         ├─ Before Hooks (UltraPrepare / InsertStart / BeforeSkillUse)
  │         ├─ AttackFrame (lifecycle.attack_scope)
  │         │    ├─ BeforeAttack / BeforeHitAll / Damage / HPChange / Toughness
  │         │    └─ On outermost exit -> SettlementBarrier (settle_attack_boundary)
  │         │          1. AfterAttack       (OnAfterAttack -> OnListenAfterAttack -> OnAfterBeingAttacked)
  │         │          2. DyingBatch        (OnBeforeDying -> OnBeingLimbo -> strip -> OnDeathrattle -> inline finalize)
  │         │          3. FlushListenDie    (OnListenCharacterDie, respecting _in_deathrattle_limbo)
  │         │          4. LimboWaitHeal     (deferred boss phase transition heals)
  │         │          5. LevelKills        (__LEVEL__ kills -> OnBeforeDying -> emit_sim_event(EnemyDefeated) -> cleanup)
  │         │          6. AfterAttackEnd    (OnAfterBeingAttackedEnd -> OnListenAfterAttackEnd -> 2nd Dying & ListenDie drain)
  │         │          7. BlockedTargets    (clear attack_blocked_targets)
  │         │          8. FinalizeDead      (finalize_dead_enemy & HPSharedGroup cascade for non-limbo dead)
  │         ├─ Energy Grant (SPBase * ERR, if not ModifySPNew(AddRatio))
  │         └─ Post Hooks (AfterSkillUse / ActionEnd / AfterAction / InsertFinish / SettleCallback)
  ├─ Boundary Drain (scheduler.drain_window / scheduler.drain_at_boundary)
  │    └─ Safely opens _action_frame_depth = 0 inside try/finally and drains:
  │       Tier 0 (preempt) -> Tier 1 (FollowUp) -> Tier 0 -> Tier 2 (Reserved) -> Tier 3 (Voyage)
  └─ TurnEnd -> emit_event -> dispatch_combat_fact -> reset_distance
```

### 2. 核心新增与重构模块

| 模块 | 核心职责 |
| :--- | :--- |
| [`simulator/lifecycle.py`](../simulator/lifecycle.py) | 定义 `ExecutionPhase`、`AfterAttackPayload`、`AbilityFrameSpec`、`DamageHitSnapshot`、`InterventionHook` / `CallbackInterventionHook`、`ExecutionLifecycle`（含 8 阶段 `settle_attack_boundary()`、`run_ability_frame()` 与 `capture_damage_targets()`）、`dispatch_combat_fact()` 与 `emit_sim_event()` |
| [`simulator/core.py`](../simulator/core.py) | 新增 `TurnSimulator.emit_event()` 显式路由内核事实，`_run_kit_action_frame()`、`_run_char_one_more_chain()`、`_run_enemy_turn_frame()` 与 `_on_turn_sub_action_boundary()` 统一敌我动作/多动帧与 `InterventionHook` 干预契约 |
| [`simulator/scheduler.py`](../simulator/scheduler.py) | 新增 `ActionScheduler.drain_window()` 与 `ActionScheduler.drain_at_boundary()` 上下文管理器，所有动作事件走 `emit_sim_event` |
| [`simulator/vm/runtime.py`](../simulator/vm/runtime.py)<br>[`simulator/vm/executor.py`](../simulator/vm/executor.py)<br>[`simulator/vm/stage_director.py`](../simulator/vm/stage_director.py) | **彻底移除全部 `event_bus.subscribe` 战斗逻辑回调**，改为由 `dispatch_combat_fact` 按 `VMRuntime/TaskExecutor -> StageDirector` 固定顺序显式调用；`EventBus` 降格为纯只读观测总线（仅日志录制与因果追踪消费） |
| [`simulator/vm/ops/combat_ops.py`](../simulator/vm/ops/combat_ops.py)<br>[`simulator/vm/ops/stage_ops.py`](../simulator/vm/ops/stage_ops.py)<br>[`simulator/vm/ops/turn_ops.py`](../simulator/vm/ops/turn_ops.py)<br>[`simulator/vm/enemy_kit.py`](../simulator/vm/enemy_kit.py)<br>[`simulator/vm/enemy_port.py`](../simulator/vm/enemy_port.py) | 删除重复 Ability 前后置钩子/回能模板代码与多套收口分支，统一走 `lifecycle.run_ability_frame()`、`capture_damage_targets()`、`EnemyKit` 分步子动作契约与 `emit_sim_event()` |
| [`simulator/golden/replay.py`](../simulator/golden/replay.py) | 通过单一 `sim.intervention_hook = CallbackInterventionHook(...)` 接入，移除 5 处动态属性猴子补丁 |
| [`simulator/vm/audit_vm_coverage.py`](../simulator/vm/audit_vm_coverage.py) | 补充解析 `TaskExecutor._TASK_DISPATCH` 分发表全部键，恢复真实静态覆盖率审计 |
| [`simulator/test_kernel_lifecycle.py`](../simulator/test_kernel_lifecycle.py)<br>[`simulator/test_free_run_invariants.py`](../simulator/test_free_run_invariants.py) | 单元测试覆盖 8 阶段栅栏、亡语悬停、零 VM 订阅、`InterventionHook` 与分步敌方多动契约；Free-Run 套件脱离 `battle_logs/` 独立验证 `30126122` / `30126121` / `30325041` / `420564` 物理不变量 |

---

## 三、真实 VM 静态覆盖率基线

修复 [`simulator/vm/audit_vm_coverage.py`](../simulator/vm/audit_vm_coverage.py) 后扫描全量官方 `TurnBasedGameData`（已注册 Task `153`、Predicate `105`、可裁剪表现节点 `179`）：

| 领域 | 扫描文件 / Ability | Task 实例覆盖率 | Task 唯一类型（已支持 + 可裁剪 / 总数） | Predicate 实例覆盖率 | 缺失 Predicate 类型数 | 未支持 OpCode |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `BattleEvent` | 145 / 2417 | 97.3% | 218 / 367 | 99.5% | 18 | 0 |
| `Monster` | 398 / 7306 | 96.8% | 244 / 473 | 99.3% | 31 | 0 |
| `5StarAvatar` | 1486 / 0 | 95.5% | 96 / 229 | 97.4% | 29 | 0 |
| `5StarLightCone` | 73 / 0 | 99.7% | 38 / 40 | 98.4% | 5 | 0 |
| `RelicSet` | 68 / 0 | 99.8% | 19 / 20 | 96.8% | 4 | 0 |

---

## 四、Phase 3 收口产物与后续机制扩展方向

### 已完成（Phase 3 收口）
1. **敌我多动/连动 `TurnFrame` 统一 & `InterventionHook` 契约化**：`TurnSimulator._run_enemy_turn_frame` + `EnemyKit` 分步子动作契约与 `_run_char_one_more_chain` 彻底收口了敌方 `OneMorePerTurn`/`OneMore` 与我方 `UseSkillOneMore`；`replay.py` 全部 5 处动态回调统一收编为 `sim.intervention_hook = CallbackInterventionHook(...)`，`simulator/vm/` 核心非测试文件达到 `EventBus` 零订阅、零发布。
2. **Free-Run Policy 烟雾与不变量回归**：落地 [`simulator/test_free_run_invariants.py`](../simulator/test_free_run_invariants.py)，彻底脱离 `battle_logs/` 与 `reconcile/`，在真实官方关卡 `30126122` / `30126121` / `30325041` / `420564` 上每步硬校验 `rt.lifecycle.assert_clean()`、调度器排空、SP/HP/能量/韧性/跑道与 AV 单调不变量。

### 已完成（Phase 4 收口：混合兼容壳清理与双账本收敛）
1. **双属性账本收敛为单真值**：废弃 `VMMod::*` 镜像状态与 `_sync_modifier_to_status_mgr`，`StatusManager.calculate_stat()` 与 `get_detailed_snapshot()` 直接读取 `VMRuntime.modifier_engine`（同时完整保留原生 `StatusInstance` 与 `MaxHP` 等比例血量缩放）。
2. **纯 VM 弱点击破状态（`MCommon_Element_*` + `ByBreakDamage`）**：删除 `BreakStatusHelper` 与过渡期 `MCommon_BreakDebuff_*` 假状态，弱点击破统一挂载官方 `MCommon_Element_{Bleed,Burn,Frozen,Electric,Poison,Entangle,Confine}` 并由 `CombatOpsMixin` 执行 `FormulaType == "ByBreakDamage"` 结算（含纠缠受击叠层 `OnBeforeBeingAttacked`）。
3. **纯数据驱动敌方再动与 AI 目标选择**：移除 `DataDrivenEnemyKit` 中的手写再动标记与直接磁盘 JSON 字符串扫描，改为基于内存 AST 检测 `OneMorePerTurn`、官方 `MCommon_FastAction` 状态、`ByCompareSkillUsageLimit` 与 `SelectAISkillTarget`。
4. **废弃兼容空壳移除**：清理 `BloodDevourMechanicPlugin` 与 `GenericKit` 等零业务空壳。

### 后续演进建议（机制族横向扩充）
- **极简探针日志（Probe Log）优先原则**：后续扩展全新角色/敌方/环境机制族（如 DoT 引爆、超击破、反击、特定混淆 `$type` 时序）时，优先录制 **1~2 名角色、1~3 动** 的单机制探针日志钉死内核铁律，同时用 `test_free_run_invariants.py` 与 `audit_vm_coverage.py` 做自动化泛化回归；全量深渊/末日/虚构日志仅作端到端回归防线。

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
5. **敌方多动与连动未纳入 `TurnFrame`（敌方部分仍待 Phase 3 合并）**
   - 我方主动作、`UseSkillOneMore` 连动与终结技抢断已在 Phase 2 收编至 `TurnSimulator._run_kit_action_frame`，全部 VM Ability 帧（我方、敌方、追击、欢愉技、`BattleEvent`）已统一收编至 `ExecutionLifecycle.run_ability_frame(AbilityFrameSpec)`；
   - 敌方 `OneMorePerTurn` / `OneMore` 多动循环仍驻留在 [`simulator/vm/enemy_kit.py`](../simulator/vm/enemy_kit.py) 的 `while action_idx < 8` 中。
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
| [`simulator/lifecycle.py`](../simulator/lifecycle.py) | 定义 `ExecutionPhase`、`AfterAttackPayload`、`AbilityFrameSpec`、`ExecutionLifecycle`（含 8 阶段 `settle_attack_boundary()` 与 `run_ability_frame()`）、`dispatch_combat_fact()` 与 `emit_sim_event()` |
| [`simulator/core.py`](../simulator/core.py) | 新增 `TurnSimulator.emit_event()` 显式路由内核事实，新增 `_run_kit_action_frame()` 统一主行动 / `UseSkillOneMore` / 终结技动作帧 |
| [`simulator/scheduler.py`](../simulator/scheduler.py) | 新增 `ActionScheduler.drain_window()` 与 `ActionScheduler.drain_at_boundary()` 上下文管理器，所有动作事件走 `emit_sim_event` |
| [`simulator/vm/runtime.py`](../simulator/vm/runtime.py)<br>[`simulator/vm/executor.py`](../simulator/vm/executor.py)<br>[`simulator/vm/stage_director.py`](../simulator/vm/stage_director.py) | **彻底移除全部 14 处 `event_bus.subscribe` 战斗逻辑回调**，改为由 `dispatch_combat_fact` 按 `VMRuntime/TaskExecutor -> StageDirector` 固定顺序显式调用；`EventBus` 降格为纯只读观测总线（仅日志录制与因果追踪消费） |
| [`simulator/vm/ops/combat_ops.py`](../simulator/vm/ops/combat_ops.py)<br>[`simulator/vm/ops/stage_ops.py`](../simulator/vm/ops/stage_ops.py)<br>[`simulator/vm/ops/turn_ops.py`](../simulator/vm/ops/turn_ops.py)<br>[`simulator/vm/enemy_kit.py`](../simulator/vm/enemy_kit.py) | 删除重复 Ability 前后置钩子/回能模板代码与多套收口分支，统一走 `lifecycle.run_ability_frame()` 与 `emit_sim_event()` |
| [`simulator/vm/audit_vm_coverage.py`](../simulator/vm/audit_vm_coverage.py) | 补充解析 `TaskExecutor._TASK_DISPATCH` 分发表全部键，恢复真实静态覆盖率审计 |
| [`simulator/test_kernel_lifecycle.py`](../simulator/test_kernel_lifecycle.py) | 对 8 阶段栅栏顺序、非嵌套统一路径、亡语悬停、异常不泄漏、`drain_window`、`EventBus` 零战斗订阅、`run_ability_frame`、`_run_kit_action_frame` 与覆盖审计建立秒级单元测试 |

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

## 四、后续路线图（Phase 2 & Phase 3）

### Phase 2：`TurnFrame` 与连动/多动统一
1. 将敌方 `OneMorePerTurn` / `OneMore` 子动作循环（[`simulator/vm/enemy_kit.py`](../simulator/vm/enemy_kit.py)）与我方 `UseSkillOneMore`（[`simulator/core.py`](../simulator/core.py)）统一收编为内核 `TurnFrame` 子阶段（`SubAction` 帧），让敌我子动作间的终结技插队、追击与 `OnListenBeforeTurnPhase1End` 通过同一套 `TurnFrame` 边界声明完成。
2. 将 `replay.py` 中的 `pre_turn_end_hook` / `turn_action_completed_hook` / `on_enemy_sub_action_end` 等外部回调升级为显式的调度介入点契约（`InterventionHook`）。

### Phase 3：无日志自由运行测试 & 极简探针工作流
1. **Free-Run Policy 烟雾与不变量回归**：构建不依赖 `battle_logs/` 与 `reconcile/` 外挂的 4 人队自由策略跑图测试，每回合断言 `rt.lifecycle.assert_clean()`、SP/能量守恒与无死循环。
2. **极简探针日志（Probe Log）优先原则**：探索未知内核机制（如新 `BattleEvent`、多段亡语嵌套、特定混淆 `$type` 时序）时，优先录制 **1~2 名角色、1~3 动** 的单机制探针日志钉死内核铁律并固化进 `test_kernel_lifecycle.py`，全量深渊/末日/虚构/欢愉日志仅作端到端回归防线。

# 星穹铁道战斗模拟器代码索引与架构速查表 (CODEBASE INDEX)

> 📘 **核心文档导航**：
> - [项目总览与 VM 执行流水线架构 (README.md)](README.md)
> - [研发工程规范、四大铁律与对账 SOP 总纲 (AGENTS.md)](AGENTS.md)
> - [当前活跃攻坚台账 (docs/PROGRESS_ApocalypticShadow_420564-84.md)](docs/PROGRESS_ApocalypticShadow_420564-84.md)

本文档用于在研发、VM 算子扩展与官方日志对账排障时**秒级定位**核心模块、数据源、适配器、关卡引擎与测试套件。

---

## 📌 当前基线状态

- **纯数据驱动架构收敛完成**：所有旧手写角色/敌方/光锥/遗器/关卡代码及 Nanoka 中间层已彻底清除；面板数值由 [tables.py](simulator/db/tables.py) 直读官方 `ExcelOutput`，战斗逻辑由 `simulator/vm/` 解释官方 `ConfigAbility` + `ConfigAI`。
- **关卡 `30126122` 全部 9 份官方日志 `< 0.01%` 门禁全绿**：
  - 双人/三人/四人全覆盖（`155925`, `184651`, `184845`, `204943`, `205144`, `220255`, `221208`, `222204`, `041608`），总伤与每回合逐动误差均 `< 0.01%`（其中 `041608` 四人队 `total_err=0.0000%`, `max_turn_err=0.0000%`）。
- **全仓测试**：`pytest simulator/ -v` 共 **59/59 项测试全绿**。

---

## 一、 核心模块全景索引

### 1. 官方 ConfigAbility VM 引擎 (`simulator/vm/`)

| 文件 | 核心类 / 函数 | 职责说明 |
| :--- | :--- | :--- |
| [`simulator/vm/loader.py`](simulator/vm/loader.py) | `GameDataLoader`, `CompiledCharacterSpec`, `prune_ability` | 索引 `data/TurnBasedGameData` Excel 与 Config JSON，编译 `ReadInfo` 动态参数表并裁剪纯表现层节点 |
| [`simulator/vm/expr.py`](simulator/vm/expr.py) | `dotnet_hash`, `CompiledPostfixExpr`, `eval_dynamic_float` | `.NET` 32-bit 哈希（LRU 缓存）与 `PostfixExpr` 字节码求值器（现代 `17` / 早期 `10` + 预解码缓存） |
| [`simulator/vm/target_alias.py`](simulator/vm/target_alias.py) | `ExecutionContext`, `resolve_target_alias`, `resolve_target_type` | 官方目标别名解析、集合 `+` / `-` 运算与 `.GetServant` / `.GetSummoner` 链式后缀 |
| [`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) | `ModifierEngine`, `VMModifierInstance`, `PROPERTY_TO_STAT` | Modifier 叠层/生命周期、`StatusManager` 同步、`*Convert` 防自循环、Priority 回调与光环 |
| [`simulator/vm/executor.py`](simulator/vm/executor.py) | `TaskExecutor` | 官方 AST `Task` & `Predicate` 严格模式主调度器（组合 `ops/` 三个 Mixin） |
| [`simulator/vm/ops/`](simulator/vm/ops/) | `PredicateOpsMixin`, `CombatOpsMixin`, `TurnOpsMixin` | 拆分为断言 (`predicates.py`)、伤害/治疗/护盾/状态 (`combat_ops.py`)、拉推条/召唤/插队 (`turn_ops.py`) |
| [`simulator/vm/runtime.py`](simulator/vm/runtime.py) | `VMRuntime`, `ConfigAbilityKitAdapter`, `ConfigAbilityLightConeAdapter`, `ConfigAbilityRelicAdapter` | `TurnSimulator` 统一 VM 运行时协调器、`EventBus` 桥接与 `protocols.py` 适配器实现 |
| [`simulator/vm/factory.py`](simulator/vm/factory.py) | `build_vm_entity`, `build_vm_team` | VM 队伍/实体构建工厂（零硬编码属性修正） |
| [`simulator/vm/stage_data_loader.py`](simulator/vm/stage_data_loader.py) | `StageDataLoader`, `CompiledStageSpec` | 官方关卡波次、怪物面板曲线、技能倍率与 `BattleEvent` 编译 |
| [`simulator/vm/stage_factory.py`](simulator/vm/stage_factory.py) | `StageFactory` | 数据驱动怪物与关卡事件实体构建 |
| [`simulator/vm/stage_ai.py`](simulator/vm/stage_ai.py) | `StageAILoader`, `MonsterAIExecutor` | 官方 `ConfigAI` 决策树与阶段状态机 |
| [`simulator/vm/stage_runner.py`](simulator/vm/stage_runner.py) | `StageRunner` | 纯数据驱动波次推进、锁血、阶段切换与召唤状态机 |
| [`simulator/vm/enemy_kit.py`](simulator/vm/enemy_kit.py) | `DataDrivenEnemyKit` | 敌方 `ConfigAI` + `ConfigAbility` 技能执行与护盾/锁血拦截 |
| [`simulator/vm/stage_director.py`](simulator/vm/stage_director.py) | `DataDrivenStageDirector`, `build_data_driven_stage` | 波次换波、轮次边界、阿哈回合与 `TurnSimulator` 组装入口 |
| [`simulator/vm/stage_sim_adapter.py`](simulator/vm/stage_sim_adapter.py) | 门面导出 | 重导出 `DataDrivenEnemyKit`, `DataDrivenStageDirector`, `build_data_driven_stage` |
| [`simulator/vm/reconcile/`](simulator/vm/reconcile/) | `extract_log_metadata`, `attach_auto_rng_plugin`, `reconcile_log`, `emit_plugin`, `emit_alignment_test` | 自动对账子包：`models.py` / `metadata.py` / `auto_rng.py` / `runner.py` / `codegen.py` |
| [`simulator/vm/reconcile_generator.py`](simulator/vm/reconcile_generator.py) | `main()` 门面 | `python -m simulator.vm.reconcile_generator` CLI 入口与符号重导出 |
| [`simulator/vm/ir_compiler.py`](simulator/vm/ir_compiler.py) | `DynamicHashRegistry`, `KNOWN_OBFUSCATED_OPS`, `AbilityIRCompiler` | 全局哈希反查字典、混淆 `$type` 语义注册与指纹缓存扁平 IR 编译器 |
| [`simulator/vm/audit_vm_coverage.py`](simulator/vm/audit_vm_coverage.py) | `VMCoverageAuditor` | 静态扫描 `executor.py` + `ops/*.py` 与全量官方 AST 的算子覆盖率审计 |
| [`simulator/vm/state_bridge.py`](simulator/vm/state_bridge.py) & [`causal_tracer.py`](simulator/vm/causal_tracer.py) | `VMStateBridge`, `VMCausalTracer` | VM 运行态变量只读快照与因果追踪 |

---

### 2. 战斗微内核与统一协议 (`simulator/`)

| 文件 | 核心类 / 符号 | 职责说明 |
| :--- | :--- | :--- |
| [`simulator/core.py`](simulator/core.py) | `TurnSimulator` | AV 跑条调度微内核、回合执行、秘技顺序、`vm_runtime.enter_battle()` 编排 |
| [`simulator/scheduler.py`](simulator/scheduler.py) | `ActionScheduler` | 五级优先级派生队列调度器 |
| [`simulator/entity.py`](simulator/entity.py) | `Entity` | 战斗实体模型、静态白字与动态属性只读 `@property` |
| [`simulator/protocols.py`](simulator/protocols.py) | `KitHandler`, `LightConeHandler`, `RelicSetHandler`, `GenericKit`, `apply_equipped_relics_affixes` | 角色/光锥/遗器行为处理器统一抽象协议层 |
| [`simulator/combat_port.py`](simulator/combat_port.py) | `CombatPort`, `SimulatorCombatPort`, `BuffSpec` | 插件安全窄接口契约、召唤物入场四阶段屏障与事务桥接 |
| [`simulator/status.py`](simulator/status.py) | `StatusManager`, `StatType`, `StatusTag`, `DurationTiming` | 动态属性管线、4 类时钟与语义标签隔离 |
| [`simulator/events.py`](simulator/events.py) | `EventBus`, `BattleEvent` 派生类 | 不可变领域事实事件总线 |
| [`simulator/effects.py`](simulator/effects.py) | `EffectResolver` | 效果事务队列与多态伤害拦截/分摊结算 |
| [`simulator/damage.py`](simulator/damage.py) | `DamageCalculator`, `DamageRequest`, `DamageBreakdown` | 8 大乘区纯函数伤害计算器 |
| [`simulator/actions.py`](simulator/actions.py) & [`sp.py`](simulator/sp.py) | `ActionKind`, `DamageType`, `SkillPointManager` | 动作/伤害分类枚举与战技点池管理 |
| [`simulator/inspector.py`](simulator/inspector.py) & [`tracer.py`](simulator/tracer.py) | `BattleInspector`, `ActionCausalTracer` | 只读战场快照查询与动作级因果链路追踪 |
| [`simulator/vm/enemy_kit.py`](simulator/vm/enemy_kit.py) & [`simulator/vm/enemy_port.py`](simulator/vm/enemy_port.py) | `DataDrivenEnemyKit`, `DataDrivenEnemyCombatPort` | 纯数据驱动敌方行为协议与攻击/扩散/弹射/受击回能执行端口 |
| [`simulator/vm/stage_director.py`](simulator/vm/stage_director.py) & [`simulator/stage_mechanics.py`](simulator/stage_mechanics.py) | `DataDrivenStageDirector`, `BreakStatusHelper`, `StageMechanicPlugin` | 数据驱动波次换波、弱点击破辅助与通用关卡环境插件 |

---

### 3. 官方数值面板与黄金日志对账 (`simulator/db/`, `simulator/golden/`, `simulator/plugins/`)

| 路径 | 核心组件 | 职责说明 |
| :--- | :--- | :--- |
| [`simulator/db/tables.py`](simulator/db/tables.py) | `AVATAR_STATS`, `LIGHT_CONE_STATS`, `RELIC_SETS`, `RELIC_MAIN_AFFIX`, `RELIC_SUB_AFFIX` | 启动时直读官方 7 张 `ExcelOutput/*.json`（95 角色 / 172 光锥 / 64 遗器套装） |
| [`simulator/db/calculator.py`](simulator/db/calculator.py) | `StatCalculator` | 按官方成长公式与精炼/强化等级精确计算局外白字与面板 |
| [`simulator/db/character_db.py`](simulator/db/character_db.py) | `CharacterDB` | 玩家存档解析、多维度查询与 `to_combat_entity()` |
| [`simulator/golden/`](simulator/golden/) | `parse_golden_jsonl`, `SequenceRecorder`, `extract_timeline`, `run_trajectory_replay`, `diff_sequences` | Golden Trace 真值拆分模块：`models.py` / `parser.py` / `replay.py` / `diff.py` |
| [`simulator/plugins/`](simulator/plugins/) | `log_<tag>.py` (`NON_CRITS` + `attach_log_<tag>_plugin`) | 单场日志专属 RNG 真值插件（非暴击账本、受击/弹射/阿哈序列） |

---

## 二、 场景化极速定位矩阵 (Task-to-File Matrix)

| 研发 / 调试目标 | 首选目标文件 | 关键注意事项 |
| :--- | :--- | :--- |
| **一键对账新实机日志** | [`gen_reconcile.py`](gen_reconcile.py)<br>[`simulator/vm/reconcile/`](simulator/vm/reconcile/) | 运行 `python gen_reconcile.py battle_logs/<log>.jsonl --data-driven` |
| **扩展官方 `$type` Task / Predicate** | [`simulator/vm/ops/predicates.py`](simulator/vm/ops/predicates.py)<br>[`simulator/vm/ops/combat_ops.py`](simulator/vm/ops/combat_ops.py)<br>[`simulator/vm/ops/turn_ops.py`](simulator/vm/ops/turn_ops.py)<br>[`simulator/vm/executor.py`](simulator/vm/executor.py) | 纯表现节点加入 `loader.py` 的 `PRUNABLE_PRESENTATION_TYPES`，逻辑节点须严格实现 |
| **扩展 TargetAlias / Property 映射** | [`simulator/vm/target_alias.py`](simulator/vm/target_alias.py)<br>[`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) | `*Convert` 属性务必同步登记 `CONVERT_PROPERTY_PAIR` 防二次转化死循环 |
| **调试 `PostfixExpr` 或数值加载** | [`simulator/vm/expr.py`](simulator/vm/expr.py)<br>[`simulator/vm/loader.py`](simulator/vm/loader.py) | 注意现代（`17`）与早期（`10`）字节码差异，用 `dotnet_hash` 核对 Key |
| **调试敌方 AI / 换波 / 锁血 / 护盾** | [`simulator/vm/enemy_kit.py`](simulator/vm/enemy_kit.py)<br>[`simulator/vm/stage_director.py`](simulator/vm/stage_director.py)<br>[`simulator/vm/stage_runner.py`](simulator/vm/stage_runner.py) | 严禁写死中文怪物名，按 `monster_template_id` 或官方配置字段判定 |
| **调试轨迹回放或时序对齐** | [`simulator/golden/parser.py`](simulator/golden/parser.py)<br>[`simulator/golden/replay.py`](simulator/golden/replay.py) | 严禁在通用回放中硬编码单场日志分支，单场随机真值一律放 `simulator/plugins/` |
| **运行全套回归测试** | `pytest simulator/ -v` | 59 项全绿；关卡 30126122 门禁 `< 0.01%` |

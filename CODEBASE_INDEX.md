# 星穹铁道战斗模拟器代码索引与架构速查表 (CODEBASE INDEX)

> 📘 **相关文档**：
> - [项目总览 (README.md)](README.md)
> - [终极架构蓝图与演进路线 (docs/ARCHITECTURE_BLUEPRINT.md)](docs/ARCHITECTURE_BLUEPRINT.md)
> - [ConfigAbility VM 引擎架构设计 (docs/VM_ARCHITECTURE.md)](docs/VM_ARCHITECTURE.md)
> - [研发工程规范与开发指引 (DEVELOPER_GUIDE.md)](DEVELOPER_GUIDE.md)
> - [关卡 30126122 对账进展清单 (docs/STAGE_30126122_ALIGNMENT_STATUS_20261116.md)](docs/STAGE_30126122_ALIGNMENT_STATUS_20261116.md)

本文档用于在研发、VM 扩展与日志对账排障时**秒级定位**核心模块、数据源、适配器、敌方/关卡代码与测试套件。

---

## 📌 最新对账与 VM 演进里程碑 (Latest Milestones - 2026-11-18)

### 1. 关卡 30126122 实机黄金日志对账（8 份日志）
- **通过率**：**6 / 8 已全量通过**（全场总伤及逐动作偏差 `< 0.2%` 标准）。
  - **两人组（4 份）**：`155925`、`184651`、`184845`、`204943` 全量达成 `< 0.2%` 逐回合对齐。
  - **三人组（4 份）**：
    - `205144`：✅ **通过**（全场与逐回合 `< 0.2%`）。
    - `222204`：✅ **通过**（精确到实体的阿哈与二阶段狂兽胚芽时序对齐，全场与逐回合 `< 0.2%`）。
    - `220255`：🟡 **总伤达标**（总伤误差仅 `0.10%`，仅余 `AV=245.12` 单动微小偏差 `0.65%`）。
    - `221208`：🟡 **逼近收官**（总伤偏差已压降至 `0.22%`，仅差 `0.02%` 即达标）。
- **攻克的关键机制**：
  - **亚婆离（Apoli）Boss 机制解耦**：一二阶段形态切换、狂暴倒计时、屏障转化与韧性减伤区解耦（未破韧 0.90x，屏障附加伤害 0.25x）。
  - **狂兽胚芽（Sprout）**：二阶段生成自带 50% 拉条与自然跑条顺位精准对齐。
  - **缇宝 / 风堇 / 忆灵**：缇宝 E4 施法时机、小伊卡击杀跃迁与阿哈笑点联动闭环。

### 2. 官方 ConfigAbility VM 引擎重大落地 (`simulator/vm/`)
- **官方数据源直连**：挂载 `data/TurnBasedGameData` (commit `dad9155eb`) 子模块作为统一唯一真相源。
- **VM 核心架构就绪**：
  - `.NET` 32-bit 双路 5381 字符串哈希与 `PostfixExpr` 现代/早期字节码求值器；
  - 官方目标别名（TargetAlias）与集合运算；
  - Modifier 属性双向同步、`*Convert` 防自循环与回调优先级管理；
  - `ConfigAbilityKitAdapter`、`ConfigAbilityLightConeAdapter`、`ConfigAbilityRelicAdapter` 标准化适配器；
  - 全链路回归测试台 `FixedReconciliationHarness` 与 `VMReconciliationHarness`。

---

## 一、 核心模块全景索引

### 1. 官方 ConfigAbility VM 引擎 (`simulator/vm/` — 核心主线)

| 文件 | 核心类 / 函数 | 职责说明 |
| :--- | :--- | :--- |
| [`simulator/vm/__init__.py`](simulator/vm/__init__.py) | 公共符号导出 | 导出 `GameDataLoader`, `VMRuntime`, `ConfigAbility*Adapter`, `dotnet_hash` 等 |
| [`simulator/vm/loader.py`](simulator/vm/loader.py) | `GameDataLoader`<br>`CompiledCharacterSpec`<br>`prune_ability` | 索引 `data/TurnBasedGameData` Excel 与 Config JSON，编译 `ReadInfo` 动态参数表并裁剪纯表现层节点 |
| [`simulator/vm/expr.py`](simulator/vm/expr.py) | `dotnet_hash`<br>`CompiledPostfixExpr`<br>`eval_dynamic_float` | `.NET` 32-bit 双路 5381 字符串哈希与 `PostfixExpr` 字节码求值器（兼容现代 `17` 与早期 `10` 格式 + 11 个内置函数） |
| [`simulator/vm/target_alias.py`](simulator/vm/target_alias.py) | `ExecutionContext`<br>`resolve_target_alias`<br>`resolve_target_type` | 官方目标别名解析、集合 `+` / `-` 运算与 `.GetServant` / `.GetSummoner` 等链式后缀 |
| [`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) | `ModifierEngine`<br>`VMModifierInstance`<br>`PROPERTY_TO_STAT` | Modifier 叠层/生命周期管理、`StatusManager` 同步、`*Convert` 防自循环、Priority 回调调度、`IsHaloStatus` 光环与区间监听 |
| [`simulator/vm/executor.py`](simulator/vm/executor.py) | `TaskExecutor` | 官方 AST `Task` & `Predicate` 严格模式解释器，桥接伤害/治疗/扣血/拉推条/插队/召唤 |
| [`simulator/vm/runtime.py`](simulator/vm/runtime.py) | `VMRuntime`<br>`ensure_vm_runtime`<br>`ConfigAbilityKitAdapter`<br>`ConfigAbilityLightConeAdapter`<br>`ConfigAbilityRelicAdapter` | `TurnSimulator` 统一 VM 运行时协调器、`EventBus` 桥接与标准角色/光锥/遗器适配器 |
| [`simulator/vm/factory.py`](simulator/vm/factory.py) | `build_vm_entity`<br>`build_vm_team`<br>`TEAM_VM_LOADOUT` | VM 队伍/实体构建工厂与 `character_db_export.json` 预烘焙被动词条去重 |
| [`simulator/vm/vm_reconciliation.py`](simulator/vm/vm_reconciliation.py) | `VMReconciliationHarness` | 基于 VM 队伍复跑官方 Veritas 黄金日志的逐动对账沙盒 |
| [`simulator/vm/test_vm_phase1.py`](simulator/vm/test_vm_phase1.py) | `TestVMPhase1` | 哈希、字节码、角色/忆灵/光锥/遗器参数加载对齐单测 |
| [`simulator/vm/test_vm_hyacine_team.py`](simulator/vm/test_vm_hyacine_team.py) | `TestVMHyacineTeam` | VM 记忆队 `OnEnterBattle` 优先级、召唤、治疗与遗器光环联动单测 |

---

### 2. 战斗微内核与基础设施 (`simulator/`)

| 文件 | 核心类 / 符号 | 职责说明 |
| :--- | :--- | :--- |
| [`simulator/core.py`](simulator/core.py) | `TurnSimulator` | AV 跑条调度微内核、回合执行、秘技顺序、`vm_runtime.enter_battle()` 编排 |
| [`simulator/scheduler.py`](simulator/scheduler.py) | `ActionScheduler` | 五级优先级派生队列（即时追加回合 / 追加攻击 / 统一预约队列 / 旅姬回合 / 自然跑条） |
| [`simulator/entity.py`](simulator/entity.py) | `Entity` | 战斗实体模型、静态白字与动态属性只读 `@property`、跑道推拉方法 |
| [`simulator/combat_port.py`](simulator/combat_port.py) | `CombatPort`, `SimulatorCombatPort`, `BuffSpec` | 插件安全窄接口契约、召唤物入场四阶段屏障与事务桥接 |
| [`simulator/status.py`](simulator/status.py) | `StatusManager`, `StatType`, `StatusTag`, `DurationTiming` | 动态属性管线、4 类时钟与语义标签隔离 |
| [`simulator/events.py`](simulator/events.py) | `EventBus`, `BattleEvent` 派生类 | 不可变领域事实事件总线（回合、动作、伤害、治疗、护盾、扣血、召唤/退场） |
| [`simulator/effects.py`](simulator/effects.py) | `EffectResolver` | 效果事务队列与多态伤害拦截/分摊结算 |
| [`simulator/damage.py`](simulator/damage.py) | `DamageCalculator`, `DamageRequest`, `DamageBreakdown` | 8 大乘区纯函数伤害计算器（支持真伤、暴击覆盖、无视防御与单次命中临时乘区） |
| [`simulator/actions.py`](simulator/actions.py) | `ActionKind`, `AbilityDefinition`, `TargetMode`, `DamageType` | 动作枚举、技能元数据与伤害分类枚举 |
| [`simulator/sp.py`](simulator/sp.py) | `SkillPointManager` | 战技点池与上限管理 |
| [`simulator/inspector.py`](simulator/inspector.py) | `BattleInspector` | 只读战场全量快照 (`get_battle_status`) 与点号路径查询 (`query_status`) |
| [`simulator/tracer.py`](simulator/tracer.py) | `ActionCausalTracer` | 动作级变量流转与因果链路审计追踪器 |

---

### 3. 数据资产与数值库 (`data/`, `simulator/assets/`, `scaling/`, `db/`)

| 路径 | 核心组件 | 职责说明 |
| :--- | :--- | :--- |
| [`data/TurnBasedGameData/`](data/TurnBasedGameData/) | Git Submodule (`dad9155eb`) | 官方 `ExcelOutput`、`ConfigAbility`、`ConfigCharacter` 等 VM 唯一真相源 |
| [`data/character_db_export.json`](data/character_db_export.json) | 实机导出角色库 | 账号角色实机面板白字、遗器词条与历史配置快照 |
| [`data/nanoka/`](data/nanoka/) | Nanoka 4.6 原始/归一化 JSON | 历史与校验用多等级角色、光锥、遗器参数表 |
| [`simulator/db/character_db.py`](simulator/db/character_db.py) | `CharacterDB` / `to_combat_entity()` | 玩家导出面板解析与实体构建 |
| [`simulator/db/calculator.py`](simulator/db/calculator.py) | `StatCalculator` | 高精度面板计算器 |
| [`simulator/assets/repository.py`](simulator/assets/repository.py) | `AssetRepository` | Nanoka 4.6 归一化资产索引 |
| [`simulator/scaling/resolver.py`](simulator/scaling/resolver.py) | `SkillScalingFactory` | 技能等级与星魂倍率解析（供校验与兼容层使用） |

---

### 4. 关卡建模、敌方套件与黄金日志对账 (`kits/enemies/`, `stage_*.py`, `golden_diff.py`, `plugins/`)

| 路径 | 核心组件 | 职责说明 |
| :--- | :--- | :--- |
| [`simulator/kits/enemies/`](simulator/kits/enemies/) | `EnemyKit`, `ApoliBossKit`, `SunlitGriffinKit`, `MoonlitPegasusKit`, `MeteorEagleKit`, `BeastSproutKit`, `LighthouseBossKit` | 独立解耦的敌方机制套件与 `EnemyCombatPort` 契约 |
| [`simulator/stage_director.py`](simulator/stage_director.py) | `MoCWaveMode`, `AnomalyWaveMode`, `BreakStatusHelper` | 混沌回忆/异象仲裁波次模式与弱点击破异常通用工具 |
| [`simulator/stage_30126122.py`](simulator/stage_30126122.py) | `build_stage_30126122`, `Stage30126122Director` | 关卡 30126122 建模（混沌回忆式换波、欢愉笑点/阿哈规则、Lv.95 数值覆盖） |
| [`simulator/stage_30510021.py`](simulator/stage_30510021.py) | `Stage30510021` 相关构建 | 关卡 30510021 场景还原 |
| [`simulator/golden_diff.py`](simulator/golden_diff.py) | `parse_golden_jsonl`, `attach_exact_crit_oracle`, `run_trajectory_replay`, `diff_sequences` | 官方 Veritas JSONL 解析、结构化 Diff 与全轨迹回放对账框架 |
| [`simulator/plugins/`](simulator/plugins/) | `log_<tag>.py`, `non_crit_ledgers.py` | 单场日志专属 RNG 插件（非暴击账本、随机弹射/点名序列与特殊事件钩子） |
| [`simulator/testing/fixed_reconciliation_bench.py`](simulator/testing/fixed_reconciliation_bench.py) | `FixedReconciliationHarness` | 外部环境固定化的小伊卡/风堇光锥逐动对账测试台（`VMReconciliationHarness` 基类） |
| [`battle_logs/`](battle_logs/) | `battle_*.jsonl` | 实机录制官方 Veritas 战斗日志 |

---

### 5. 兼容插件层 (`kits/characters/`, `light_cones/`, `relics/` — Legacy Compatibility)

| 路径 | 核心组件 | 职责说明 |
| :--- | :--- | :--- |
| [`simulator/kits/base.py`](simulator/kits/base.py) & [`registry.py`](simulator/kits/registry.py) | `KitHandler`, `@register_kit` | 角色技能套件抽象基类与装饰器自动发现注册中心 |
| [`simulator/kits/characters/`](simulator/kits/characters/) | 64 位手写角色套件 + [`_template.py`](simulator/kits/characters/_template.py) | 历史手写角色实现（兼容模式，包含本体+忆灵模板） |
| [`simulator/light_cones/`](simulator/light_cones/) | `LightConeHandler`, `@register_light_cone`, 5 个手写处理器 | 光锥抽象基类、目录、注册中心与兼容层处理器 |
| [`simulator/relics/`](simulator/relics/) | `RelicSetHandler`, `@register_relic_set`, 6 个手写处理器 | 遗器抽象基类、目录、注册中心与兼容层处理器 |
| [`simulator/stage_mechanics.py`](simulator/stage_mechanics.py) | `StageMechanicPlugin`, `@register_stage_mechanic` | 通用关卡环境词条插件（如血噬） |

---

## 二、 场景化极速定位矩阵 (Task-to-File Matrix)

| 研发 / 调试目标 | 首选目标文件 | 关键注意事项 |
| :--- | :--- | :--- |
| **接入 / 调试 VM 角色与队伍** | [`simulator/vm/factory.py`](simulator/vm/factory.py)<br>[`simulator/vm/runtime.py`](simulator/vm/runtime.py) | 核对 `character_db_export.json` 是否已预烘焙行迹/内圈词条，防止重复叠加 |
| **扩展官方 `$type` Task / Predicate** | [`simulator/vm/executor.py`](simulator/vm/executor.py)<br>[`simulator/vm/loader.py`](simulator/vm/loader.py) | 仅将纯镜头/动画/UI 节点加入 `PRUNABLE_PRESENTATION_TYPES`，逻辑节点须实现 |
| **扩展 TargetAlias / Property 映射** | [`simulator/vm/target_alias.py`](simulator/vm/target_alias.py)<br>[`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) | `*Convert` 属性务必同步登记 `CONVERT_PROPERTY_PAIR` 以防二次转化死循环 |
| **调试 `PostfixExpr` 或数值编译** | [`simulator/vm/expr.py`](simulator/vm/expr.py)<br>[`simulator/vm/loader.py`](simulator/vm/loader.py) | 注意区分现代（`17` 结尾）与早期（`10` 结尾）字节码，使用 `dotnet_hash` 核对 Key |
| **运行 VM 黄金日志逐动对账** | [`simulator/vm/vm_reconciliation.py`](simulator/vm/vm_reconciliation.py) | 使用 `VMReconciliationHarness` 对照 `battle_logs/` 5 份风堇记忆队日志 |
| **新增敌方机制 / 关卡 / 单场日志插件** | [`simulator/kits/enemies/`](simulator/kits/enemies/)<br>[`simulator/stage_30126122.py`](simulator/stage_30126122.py)<br>[`simulator/plugins/`](simulator/plugins/) | 严格遵守 Enemy ↔ Stage ↔ Replay ↔ Log RNG Plugin 四层隔离 |
| **运行标准测试套件** | [`simulator/vm/test_vm_phase1.py`](simulator/vm/test_vm_phase1.py)<br>[`simulator/vm/test_vm_hyacine_team.py`](simulator/vm/test_vm_hyacine_team.py)<br>[`simulator/test_30126122_alignment.py`](simulator/test_30126122_alignment.py)<br>[`simulator/test_framework_extensibility.py`](simulator/test_framework_extensibility.py)<br>[`simulator/test_code_integrity.py`](simulator/test_code_integrity.py) | 避免直接运行裸 `pytest`（防止扫入 `scratch/`），显式指定 `simulator/...` 路径 |
| **维护历史手写角色 / 光锥 / 遗器** | [`simulator/kits/characters/_template.py`](simulator/kits/characters/_template.py)<br>[`simulator/light_cones/handlers/_template.py`](simulator/light_cones/handlers/_template.py)<br>[`simulator/relics/handlers/_template.py`](simulator/relics/handlers/_template.py) | 兼容模式：严禁访问 `port.sim` / `port._get_entity`，遵循 `DEVELOPER_GUIDE.md` 第六章 |

---

## 三、 常用重点角色 ID 与文件路径速查

> **VM 模式下**：所有 `TurnBasedGameData` 已覆盖的角色均可直接通过 `ConfigAbilityKitAdapter(name, avatar_id, eidolon=...)` 驱动，无需手写 Kit。下表列出高频验证角色与兼容层对应源码位置：

| 角色名 | Avatar ID | 忆灵 ID | VM 配置入口 | 兼容层手写 Kit 源码 |
| :--- | :---: | :---: | :--- | :--- |
| **长夜月** (Evernight) | **1413** | **11413** (`长夜`) | [`factory.py`](simulator/vm/factory.py) / `ConfigAbilityKitAdapter` | [`simulator/kits/characters/changyeyue.py`](simulator/kits/characters/changyeyue.py) |
| **风堇** (Hyacine) | **1409** | **11409** (`小伊卡`) | [`factory.py`](simulator/vm/factory.py) / `ConfigAbilityKitAdapter` | [`simulator/kits/characters/fengjin.py`](simulator/kits/characters/fengjin.py) |
| **缇宝** (Tribbie) | **1403** | — | [`factory.py`](simulator/vm/factory.py) / `ConfigAbilityKitAdapter` | [`simulator/kits/characters/tibao.py`](simulator/kits/characters/tibao.py) |
| **知更鸟•晴歌** | **1512** | **11512** (`晴空乐手`) | [`factory.py`](simulator/vm/factory.py) / `ConfigAbilityKitAdapter` | [`simulator/kits/characters/robin_sunnysong.py`](simulator/kits/characters/robin_sunnysong.py) |
| **知更鸟 (原版)** | **1309** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/robin.py`](simulator/kits/characters/robin.py) |
| **星期日** (Sunday) | **1313** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/sunday.py`](simulator/kits/characters/sunday.py) |
| **花火** (Sparkle) | **1306** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/sparkle.py`](simulator/kits/characters/sparkle.py) |
| **阮•梅** (Ruan Mei) | **1303** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/ruan_mei.py`](simulator/kits/characters/ruan_mei.py) |
| **黄泉** (Acheron) | **1308** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/acheron.py`](simulator/kits/characters/acheron.py) |
| **流萤** (Firefly) | **1310** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/firefly.py`](simulator/kits/characters/firefly.py) |
| **砂金** (Aventurine) | **1304** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/aventurine.py`](simulator/kits/characters/aventurine.py) |
| **符玄** (Fu Xuan) | **1208** | — | `ConfigAbilityKitAdapter` | [`simulator/kits/characters/fuxuan.py`](simulator/kits/characters/fuxuan.py) |

# 《星穹铁道战斗模拟器·研发工程规范与开发指引》 (DEVELOPER GUIDE)

> **致工程师与 Coding Agent**：  
> 本项目采用**纯数据驱动的官方 `TurnBasedGameData` + `ConfigAbility` 虚拟机（[`simulator/vm/`](simulator/vm/)）** 架构：
> - **零手写角色/光锥/遗器/关卡代码**：所有新角色、伴生忆灵、光锥、遗器、怪物与关卡均直接读取官方配置驱动，未覆盖的官方 AST 算子沉淀至 `simulator/vm/ops/`；
> - **核心微内核（`core.py`, `scheduler.py`, `status.py`, `damage.py`）**：保持零角色/装备/关卡硬编码；
> - **四层强制边界隔离**：Enemy Kit ↔ Data-Driven Stage Director ↔ Generic Replay ↔ Log RNG Plugin。

---

## 一、 核心架构与强制边界规范

### 1.1 微内核 + 统一协议 + VM 适配器

`TurnSimulator` 微内核通过 [`simulator/protocols.py`](simulator/protocols.py) 定义的统一协议（`KitHandler` / `LightConeHandler` / `RelicSetHandler`）及 [`CombatPort`](simulator/combat_port.py) 与业务层解耦：
- [`ConfigAbilityKitAdapter`](simulator/vm/runtime.py)、[`ConfigAbilityLightConeAdapter`](simulator/vm/runtime.py)、[`ConfigAbilityRelicAdapter`](simulator/vm/runtime.py) 共享 [`VMRuntime`](simulator/vm/runtime.py)，直接执行 [`data/TurnBasedGameData/`](data/TurnBasedGameData/) 的官方技能、光锥与遗器 AST；
- 敌方侧由 [`DataDrivenEnemyKit`](simulator/vm/enemy_kit.py) 实现 [`EnemyKit`](simulator/kits/enemies/base.py)，由 [`DataDrivenStageDirector`](simulator/vm/stage_director.py) 驱动波次与关卡事件；
- 局外面板由 [`simulator/db/tables.py`](simulator/db/tables.py) 直读官方 `ExcelOutput` 数值表，经 [`StatCalculator`](simulator/db/calculator.py) 精确编译。

### 1.2 黄金日志对账四层强制边界 (Mandatory Boundaries)

在接入官方实机日志 (`battle_logs/battle_*.jsonl`) 或扩展关卡/敌方时，必须严格遵守以下职责隔离：

1. **数据驱动敌方套件 ([`simulator/vm/enemy_kit.py`](simulator/vm/enemy_kit.py))**：
   - 仅执行官方 `ConfigAI` 与 `ConfigAbility` 确定的机制（多动、召唤、阶段切换、印记/Debuff、护盾/锁血拦截）；
   - **严禁**硬编码我方角色名、中文怪物名、玩家 UID 或单场日志随机点名序列。
2. **数据驱动关卡导演 ([`simulator/vm/stage_director.py`](simulator/vm/stage_director.py))**：
   - 仅处理通用关卡级事实：波次切换（`MoCWaveMode` / `AnomalyWaveMode`）、轮次边界、`BattleEvent` 调度与通用钩子（`target_provider`、`blast_target_provider`、`aha_special_handler` 等）；
   - **严禁**写入单场战斗随机命中序列。
3. **通用回放框架 ([`simulator/golden/`](simulator/golden/) & [`simulator/golden_diff.py`](simulator/golden_diff.py))**：
   - 负责解析 Veritas JSONL、动态加载 `KNOWN_AVATAR_NAMES`、注入暴击先知（`attach_exact_crit_oracle`）与驱动 `run_trajectory_replay()`；
   - **严禁**写入 `if "<log_id>" in str(log_path)` 单场分支。
4. **单场日志 RNG 插件 ([`simulator/plugins/log_<tag>.py`](simulator/plugins/))**：
   - 集中封装单场录制日志的**全部随机真值**：`NON_CRITS` 非暴击 `(act_idx, hit_idx)` 账本、随机弹射/点名序列与风行/阿哈真值事件。

---

## 二、 官方 VM 开发与扩展 SOP

### 2.1 装配与启动 VM 队伍与关卡

```python
from simulator.vm.factory import build_vm_team
from simulator.vm.stage_sim_adapter import build_data_driven_stage

team = build_vm_team(["风堇", "缇宝", "长夜月", "知更鸟•晴歌"])
sim, director = build_data_driven_stage(30126122, team, technique_users=["风堇", "缇宝", "长夜月", "知更鸟•晴歌"])
```

### 2.2 一键排查官方 `TurnBasedGameData` 配置与哈希

```python
from simulator.vm import GameDataLoader, dotnet_hash

loader = GameDataLoader()
spec = loader.load_character(1409, eidolon=1)
print("Skill levels:", spec.skill_levels)
print("Loaded abilities:", list(spec.abilities.keys()))
print("Hash of _CurrentSpeed:", dotnet_hash("_CurrentSpeed"))
```

### 2.3 扩展未实现的官方 VM 节点 (`strict=True` 驱动)

`TaskExecutor` 与 `ModifierEngine` 默认运行在 **`strict=True`** 模式下，遇到未知的 `Task` 或 `Predicate` `$type` 会直接抛出 `NotImplementedError`。扩展新角色/新装备时按以下 4 步处理：

1. **区分「纯表现节点」与「战斗逻辑节点」**：
   - 在 `data/TurnBasedGameData/Config/` 中核对新 `$type` 的全部字段与上下文；
   - 若确认仅为镜头/动画/特效/UI/音效（无任何数值、状态、行动条或事件副作用），加入 [`simulator/vm/loader.py`](simulator/vm/loader.py) 的 `PRUNABLE_PRESENTATION_TYPES`；
   - **严禁**把未知逻辑节点直接加入忽略名单或静默 `return`。
2. **补全 `TargetAlias` / `TargetType` ([`simulator/vm/target_alias.py`](simulator/vm/target_alias.py))**：
   - 新增锚点或后缀修饰符在 `_resolve_single_token` / `resolve_target_type` 中按官方语义实现，注意保序去重与存活/不可选中过滤。
3. **补全 `Property` 映射 ([`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py))**：
   - 新增属性加入 `PROPERTY_TO_STAT` 映射表；
   - 二次属性转化（`*Convert`）务必同步登记 `CONVERT_PROPERTY_PAIR` 并确保 `StatusTag.EXCLUDE_FROM_STAT_TRANSFERS` 生效，防止转化死循环。
4. **补全 `Predicate` / `Task` ([`simulator/vm/ops/`](simulator/vm/ops/))**：
   - 断言加在 [`predicates.py`](simulator/vm/ops/predicates.py)，伤害/治疗/护盾/状态加在 [`combat_ops.py`](simulator/vm/ops/combat_ops.py)，拉推条/召唤/插队加在 [`turn_ops.py`](simulator/vm/ops/turn_ops.py)，控制流加在 [`executor.py`](simulator/vm/executor.py)；
   - 所有数值参数统一经 `self._eval_num(...)` 求值，自动兼容固定值与 `PostfixExpr` 公式。

### 2.4 VM 关键时序约定

- **`OnEnterBattle` 全局升序**：`TurnSimulator.__init__` 在实体 `on_battle_start()` 后统一调用 `sim.vm_runtime.enter_battle()`，按 `_CallbackList.Priority` 升序（如 `-92 → -80 → 0`）执行，随后刷新所有实体的 `OnAbilityPropertyChange` 区间监听。
- **Modifier 衰减时钟 (`LifeStepMoment`)**：`ModifierPhase1End` 在 `TurnBeginEvent` 扣减；`TurnEnd` 在 `TurnEndEvent` 扣减。
- **新实体入场光环补发**：通过 `CreateServant` 或波次切换创建新实体时，触发 `modifier_engine.on_entity_created()` / `attach_halos_to_new_entity()`，确保 `IsHaloStatus` 自动覆盖新入场忆灵或敌方。

---

## 三、 黄金日志对账与测试验证规范

### 3.1 常用测试与对账命令

```bash
# 全仓回归测试 (59 项)
pytest simulator/ -v

# 快速微内核与协议单测 (~0.3s)
pytest simulator/ --ignore=simulator/vm -q

# VM 覆盖率审计与核心单测
pytest simulator/vm/test_vm_phase1.py simulator/vm/test_audit_vm_coverage.py -v

# 对任意官方日志执行自动对账
python gen_reconcile.py battle_logs/<battle_log>.jsonl --data-driven
```

### 3.2 对账核心红线（零循环自证 & `< 0.01%` 双门禁）

1. **禁止循环自证**：严禁使用真值伤害或比值反推本地乘区/治疗池/增伤常数；所有中间量必须由内核或 VM 原生计算后单向对比。
2. **禁止凑数常数**：[`simulator/test_code_integrity.py`](simulator/test_code_integrity.py) 会通过 AST 静态扫描拦截经验凑数浮点；一切参数必须可追溯至官方 `ExcelOutput`。
3. **双门禁验收**：
   - 全场总伤偏差 **`< 0.01%`**（`0.0001`）；
   - **逐动（每回合/每次出手）偏差 `< 0.01%`**，防止正负误差相互抵消掩盖底层时序或乘区缺陷。

---

## 四、 常见问题排查速查

| 现象 | 常见根因 | 排查位置 |
| :--- | :--- | :--- |
| 抛出 `NotImplementedError: 未实现的 Task/Predicate 节点类型` | 官方配置出现尚未接入的 `$type` | [`simulator/vm/ops/`](simulator/vm/ops/) / [`executor.py`](simulator/vm/executor.py) / [`loader.py`](simulator/vm/loader.py) |
| 召唤新忆灵或换波新敌人未吃到我方光环 | 未通过 `on_entity_created` / `attach_halos_to_new_entity` 补发 `IsHaloStatus` | [`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) / [`stage_director.py`](simulator/vm/stage_director.py) |
| 忆灵/队友属性转化发生指数膨胀 | 转化后 Modifier 漏标 `IsConvert` / `EXCLUDE_FROM_STAT_TRANSFERS` | [`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) `CONVERT_PROPERTY_PAIR` |
| 覆盖率测试报错缺少某算子 | 新增算子放在了未被扫描的私有辅助方法 | [`simulator/vm/audit_vm_coverage.py`](simulator/vm/audit_vm_coverage.py) |

---

## 五、 工程五大核心戒律 (Architecture Red Lines)

1. **❌ 戒律 1：严禁在核心引擎 (`core.py`, `scheduler.py`, `entity.py`, `effects.py`, `status.py`) 中硬编码具体角色名、技能名或角色 ID。**
2. **❌ 戒律 2：严禁绕过 `CombatPort` 或 `VMRuntime` 契约直接篡改他方私有内部状态；严禁静默吞掉未知 `$type` 掩盖实现缺失。**
3. **❌ 戒律 3：严禁在属性汇算中使用状态名称/ID 硬编码黑名单；二次转化隔离一律依赖 `*Convert` 与 `StatusTag`。**
4. **❌ 戒律 4：严禁把单场日志 RNG 结果写进通用 `DataDrivenEnemyKit`、`DataDrivenStageDirector` 或 `golden/`；必须放入 `simulator/plugins/log_<tag>.py`。**
5. **❌ 戒律 5：严禁使用任何经验凑数浮点或真值反推逻辑伪造对账通过。**

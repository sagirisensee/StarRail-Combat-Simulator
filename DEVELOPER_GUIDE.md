# 《星穹铁道战斗模拟器·研发工程规范与开发指引》 (DEVELOPER GUIDE)

> **致新加入的工程师与 Coding Agent**：  
> 本项目已确立以 **官方 `TurnBasedGameData` + `ConfigAbility` 数据驱动虚拟机（[`simulator/vm/`](simulator/vm/)）** 作为后续开发与实机对账的唯一核心标准。  
> - **新角色 / 新光锥 / 新遗器**：优先通过 VM 适配器接入官方配置，并将未覆盖的官方 AST 算子沉淀进 `simulator/vm/`；  
> - **核心微内核 (`core.py`, `scheduler.py`, `status.py`, `damage.py`)**：保持零角色/装备/关卡硬编码；  
> - **敌方机制、关卡导演与单场日志 RNG**：遵循严格四层边界隔离（Enemy Kit ↔ Stage ↔ Generic Replay ↔ Log RNG Plugin）；  
> - **历史手写插件 (`simulator/kits/characters/`, `light_cones/handlers/`, `relics/handlers/`)**：保留为兼容层，相关规范归档于本文档[第六章](#六-兼容模式手写插件开发规范-legacy-compatibility)。

---

## 一、 核心架构与强制边界规范

### 1.1 双轨插件 + 微内核总体架构

`TurnSimulator` 微内核通过标准窄协议（`KitHandler` / `LightConeHandler` / `RelicSetHandler` / `CombatPort`）与业务实现解耦：
- **标准主线（VM-Driven）**：[`ConfigAbilityKitAdapter`](simulator/vm/runtime.py)、[`ConfigAbilityLightConeAdapter`](simulator/vm/runtime.py)、[`ConfigAbilityRelicAdapter`](simulator/vm/runtime.py) 共享 [`VMRuntime`](simulator/vm/runtime.py)，直接执行 [`data/TurnBasedGameData/`](data/TurnBasedGameData/) 的官方技能、光锥与遗器 AST。
- **兼容模式（Legacy Hand-Coded）**：历史 64 位手写角色与装备处理器实现同一套接口，用于运行早期测试与 CLI 预设，**不再作为新角色默认开发路径**。

更深入的 VM 内部原理请查阅：[《ConfigAbility VM 引擎架构与运行机制 (docs/VM_ARCHITECTURE.md)》](docs/VM_ARCHITECTURE.md)。

### 1.2 黄金日志对账四层强制边界 (Mandatory Boundaries)

在接入官方实机日志 (`battle_logs/battle_*.jsonl`) 或扩展关卡/敌方时，必须严格遵守以下职责隔离：

1. **敌方套件 (`simulator/kits/enemies/*.py`)**：
   - 仅建模确定性敌方机制：开局拉推条、回合阶段轮转、召唤物、印记/Debuff 与攻击参数（倍率、hit 数、元素、受击回能、扩散模式）；
   - 仅通过 `self.port.get_living_allies()` 检索存活目标；
   - **严禁**出现任何我方角色名、玩家 UID、单场日志 AV 或硬编码随机点名序列。
2. **关卡导演 (`simulator/stage_<stage_id>.py`)**：
   - 仅定义关卡级事实：敌方阵容、Lv.95/100 关卡数值覆盖、`sim.enemy_uid_map`、换波逻辑（`MoCWaveMode` / `AnomalyWaveMode`）、场地通用规则（如欢愉笑点/阿哈回合）与通用钩子（`target_provider`、`blast_target_provider`、`aha_special_handler` 等）；
   - **严禁**写入我方角色名或单场战斗随机命中序列。
3. **通用回放框架 (`simulator/golden_diff.py`)**：
   - 负责解析 Veritas JSONL、动态加载 `data/character_db_export.json` 中的 `KNOWN_AVATAR_NAMES`、注入暴击先知（`attach_exact_crit_oracle`）与驱动 `run_trajectory_replay()`；
   - **严禁**硬编码 `PLAYER_ACTORS`、关卡特定 UID 或 `if "<log_id>" in str(log_path)` 分支。
4. **单场日志 RNG 插件 (`simulator/plugins/log_<tag>.py` + `non_crit_ledgers.py`)**：
   - 集中封装单场录制日志的**全部随机真值**：非暴击 `(act_idx, hit_idx)` 台账、随机弹射/点名序列与特殊跳动/风行事件。

---

## 二、 官方 VM 开发与扩展 SOP (Primary Workflow)

### 2.1 装配与启动 VM 角色 / 队伍

使用 [`simulator/vm/factory.py`](simulator/vm/factory.py) 或直接使用 VM 适配器构造 `Entity`：

```python
from simulator.core import TurnSimulator
from simulator.vm.factory import build_vm_team

# 方式 A：使用工厂函数（自动从 data/character_db_export.json 载入面板并扣除预烘焙重复词条）
team = build_vm_team(["长夜月", "缇宝", "风堇", "知更鸟•晴歌"])
sim = TurnSimulator(entities=team + enemies, use_techniques=True, auto_ult=False)
```

或手动挂载（适用于纯自定义白字面板测试，参考 [`simulator/vm/test_vm_hyacine_team.py`](simulator/vm/test_vm_hyacine_team.py)）：

```python
from simulator.vm import (
    ConfigAbilityKitAdapter,
    ConfigAbilityLightConeAdapter,
    ConfigAbilityRelicAdapter,
    GameDataLoader,
)

loader = GameDataLoader()
entity.kit = ConfigAbilityKitAdapter("风堇", 1409, eidolon=1, loader=loader)
entity.light_cone = ConfigAbilityLightConeAdapter("风堇", 23042, superimposition=1)
entity.relic_handlers = [
    ConfigAbilityRelicAdapter("风堇", 125, pieces=4),
    ConfigAbilityRelicAdapter("风堇", 320, pieces=2),
]
```

> ⚠️ **关键避坑：实机导出面板 `character_db_export.json` 的预烘焙词条去重**  
> `character_db_export.json` 中的面板属性往往已包含部分**行迹大节点**或**内圈遗器**的常驻加成（例如风堇 `PointB1` +100% 暴击率、内圈 320 +20% 治疗加成、拾骨地 319 +28% 暴伤）。而官方 VM 会在进场或局内通过 `ConfigAbility` 重新施加这些 `Modifier`。  
> 接入新角色到 `factory.py` 时，**务必核对导出面板与官方 VM 进场属性的差异**，在 `build_vm_entity()` 中扣除已预烘焙的重复词条，防止属性双算！

### 2.2 一键排查官方 `TurnBasedGameData` 配置与哈希

在调试某个角色的技能或 `DynamicKey` 时，可直接调用 `GameDataLoader` 与 `dotnet_hash` 检查官方配置：

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
   - 先在 `data/TurnBasedGameData/Config/` 中核对新 `$type` 的全部字段与上下文；
   - 若确认仅为镜头/动画/特效/UI/音效（无任何数值、状态、行动条或事件副作用），将其加入 [`simulator/vm/loader.py`](simulator/vm/loader.py) 的 `PRUNABLE_PRESENTATION_TYPES`；
   - **严禁**把未知逻辑节点直接加入忽略名单或静默 `return`。
2. **补全 `TargetAlias` / `TargetType` ([`simulator/vm/target_alias.py`](simulator/vm/target_alias.py))**：
   - 若出现新的锚点或后缀修饰符（如 `.GetXxx`），在 `_resolve_single_token` / `resolve_target_type` 中按官方语义实现，注意保序去重与存活/不可选中过滤。
3. **补全 `Property` 映射 ([`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py))**：
   - 新增属性加入 `PROPERTY_TO_STAT` 映射表；
   - 若为二次属性转化（`*Convert`），同时在 `CONVERT_PROPERTY_PAIR` 中登记并确保 `StatusTag.EXCLUDE_FROM_STAT_TRANSFERS` 生效，防止转化死循环。
4. **补全 `Predicate` / `Task` ([`simulator/vm/executor.py`](simulator/vm/executor.py))**：
   - 在 `_eval_predicate_raw` 或 `execute_task` 中实现对应指令，所有数值参数统一经 `self._eval_num(...)`（底层调用 `eval_dynamic_float`）求值，确保兼容固定值与 `PostfixExpr` 公式。

### 2.4 VM 关键时序与机制约定

* **`OnEnterBattle` 全局升序**：`TurnSimulator.__init__` 在完成实体 `on_battle_start()` 后统一调用 `sim.vm_runtime.enter_battle()`，按 `_CallbackList.Priority` 升序（如 `-92 → -80 → 0`）执行，随后刷新所有实体的 `OnAbilityPropertyChange` 区间监听。
* **Modifier 衰减时钟 (`LifeStepMoment`)**：
  * `ModifierPhase1End`：在 `TurnBeginEvent` 阶段扣减（例如风堇【雨过天晴】）；
  * `TurnEnd`：在 `TurnEndEvent` 阶段扣减。
* **新实体入场光环补发**：通过 `CreateServant` 或波次切换创建新实体时，需触发 `modifier_engine.on_entity_created()` / `attach_halos_to_new_entity()`，确保 `IsHaloStatus` 子 Modifier 自动覆盖新入场忆灵或敌方。

---

## 三、 黄金日志对账与测试验证规范

### 3.1 测试运行命令

```bash
# VM 引擎单元测试
pytest simulator/vm/test_vm_phase1.py simulator/vm/test_vm_hyacine_team.py -v

# 架构扩展性与反硬编码静态审计
pytest simulator/test_framework_extensibility.py simulator/test_code_integrity.py -v

# 关卡 30126122 黄金日志轨迹对齐测试
pytest simulator/test_30126122_alignment.py simulator/test_stage_30126122_enemies.py -v
```

### 3.2 对账核心红线（零循环自证）

1. **禁止循环自证**：严禁使用真值伤害或比值反推本地乘区/治疗池/增伤常数；所有中间量必须由内核或 VM 原生计算后单向对比。
2. **禁止凑数常数**：[`simulator/test_code_integrity.py`](simulator/test_code_integrity.py) 会通过 AST 静态扫描拦截历史经验凑数浮点；一切参数必须可追溯至官方 `ExcelOutput` 或 Nanoka 解包数据。
3. **双门禁验收**：
   - 全场总伤偏差 `< 0.2%`；
   - **逐动（每回合/每次出手）偏差 `< 0.2%`**，防止正负误差相互抵消掩盖底层时序/乘区缺陷。

---

## 四、 常见问题排查速查

| 现象 | 常见根因 | 排查位置 |
| :--- | :--- | :--- |
| 抛出 `NotImplementedError: 未实现的 Task/Predicate 节点类型` | 官方配置出现尚未接入的 `$type` | [`simulator/vm/executor.py`](simulator/vm/executor.py) / [`loader.py`](simulator/vm/loader.py) |
| 进场面板数值高于实机（如暴击/暴伤/治疗翻倍） | `character_db_export.json` 已预烘焙该词条，VM 进场又叠加了一次 | [`simulator/vm/factory.py`](simulator/vm/factory.py) `build_vm_entity()` |
| 召唤新忆灵或换波新敌人未吃到我方光环 | 未通过 `on_entity_created` / `attach_halos_to_new_entity` 补发 `IsHaloStatus` | [`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) / [`vm_reconciliation.py`](simulator/vm/vm_reconciliation.py) |
| 忆灵/队友属性转化发生指数膨胀 | 转化后 Modifier 漏标 `IsConvert` / `EXCLUDE_FROM_STAT_TRANSFERS` | [`simulator/vm/modifier_engine.py`](simulator/vm/modifier_engine.py) `CONVERT_PROPERTY_PAIR` |
| `pytest` 报错读取了奇怪的实验文件 | 直接运行了裸 `pytest` 导致收集到 `scratch/` | 显式传入 `simulator/...` 测试路径 |

---

## 五、 工程五大核心戒律 (Architecture Red Lines)

1. **❌ 戒律 1：严禁在核心引擎 (`core.py`, `scheduler.py`, `entity.py`, `effects.py`, `status.py`) 中硬编码具体角色名、技能名或角色 ID。**
2. **❌ 戒律 2：严禁绕过 `CombatPort` 或 `VMRuntime` 契约直接篡改他方私有内部状态；严禁在 VM 逻辑里通过静默吞掉未知 `$type` 掩盖实现缺失。**
3. **❌ 戒律 3：严禁在属性汇算中使用状态名称/ID 硬编码黑名单；二次转化隔离一律依赖 `*Convert` 与 `StatusTag`。**
4. **❌ 戒律 4：严禁把单场日志 RNG 结果写进通用 `EnemyKit`、`Stage` 或 `golden_diff.py`；必须放入 `simulator/plugins/log_<tag>.py`。**
5. **❌ 戒律 5：严禁使用任何经验凑数浮点或真值反推逻辑伪造对账通过。**

---

## 六、 兼容模式：手写插件开发规范 (Legacy Compatibility)

> **适用范围**：维护或调试 [`simulator/kits/characters/`](simulator/kits/characters/)、[`simulator/light_cones/handlers/`](simulator/light_cones/handlers/)、[`simulator/relics/handlers/`](simulator/relics/handlers/) 中的已有手写 Python 插件（或阅读 [`_template.py`](simulator/kits/characters/_template.py)）。**新增角色与装备请优先使用第二章的 VM 方案。**

### 6.1 手写插件 4 大高频避坑速查

1. **`self.skill_param(key, index)` 索引规则**：
   - `key` 取值：`"basic"` / `"skill"` / `"ultra"` / `"talent"` / `"technique"` 或官方技能 ID 字符串；
   - `index` 为 0-indexed（官方描述 `#1` 对应 `0`，`#2` 对应 `1`）。
2. **`StatType` 与 `ModifierOp` 搭配**：

| 游戏效果 | `StatType` | `ModifierOp` | 示例 `value` | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| 百分比提速 | `SPEED` | **`PERCENT`** | `0.16` | 按基础白字速度乘算 |
| 固定值提速 | `SPEED` | **`ADD`** | `25.0` | 直接加算固定速度 |
| 百分比加攻 / 加血 | `ATK_PERCENT` / `MAX_HP_PERCENT` | **`PERCENT`** | `0.40` / `0.30` | 按白字基础属性乘算 |
| 固定值加攻 | `ATK_BASE` | **`ADD`** | `600.0` | 直接加算局内攻击力 |
| 双暴 / 增伤 / 抗穿 / 易伤 / 减防 / 治疗加成 | `CRIT_RATE` / `CRIT_DMG` / `DMG_BOOST` / `RES_PEN` / `VULNERABILITY` / `DEF_SHRED` / `OUTGOING_HEALING` | **`ADD`** | `0.35` | 百分点直接加算（`DEF_SHRED` 挂敌方为减防，挂我方为无视防御） |

3. **Buff 时钟 `timing` 与 `skip_current_clock`**：
   - 回合内给自身/队友挂载 `TARGET_TURN_END` 或 `CASTER_TURN_END` Buff：务必设置 **`skip_current_clock=True`**，防止当前回合结束瞬间掉 1 回合；
   - 目标回合开始扣减（DoT 等）：`TARGET_TURN_START` + `skip_current_clock=False`；
   - 常驻光环：`duration=None`。
4. **二次属性转化防死循环**：
   - 转化出来的 `BuffSpec` 必须附带 `tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS,)`（忆灵专享额外加 `StatusTag.MEMOSPRITE_ONLY`）；
   - 读取基准属性时调用 `self.port.stat(self.owner_id, StatType.CRIT_DMG, exclude_tags=(StatusTag.EXCLUDE_FROM_STAT_TRANSFERS, StatusTag.MEMOSPRITE_ONLY))`。

### 6.2 `KitHandler` 扩展钩子速查 ([`simulator/kits/base.py`](simulator/kits/base.py))

| 钩子方法 | 职责说明 |
| :--- | :--- |
| `definition(kind)` | 声明技能目标模式、SP/能量消耗、秘技 `priority` 与标签 |
| `execute(ctx)` | 通过 `self.port` 执行攻击、治疗、拉条、上 Buff 等逻辑 |
| `apply_trace_passives(entity)` | 战前静态组装阶段注入行迹常驻属性 |
| `get_initial_sp_cap()` | 修改全队初始战技点上限 |
| `on_battle_start()` | 进战初始化光环、回能、召唤伴生忆灵 |
| `on_event(event)` | 订阅 `EventBus` 领域事件 |
| `on_hp_lost(entity_id, loss, cause)` | 响应实体生命值损失 |
| `intercept_incoming_damage(target_id, raw_dmg)` | 多态伤害拦截/分摊（如符玄穷观阵） |
| `can_cast_ultimate(entity)` / `consume_ultimate_cost(entity)` | 自定义特殊终结技充能条件与消耗 |
| `get_memosprite_snapshot()` | 返回伴生忆灵实时战斗面板快照 |

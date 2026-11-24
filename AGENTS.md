# AGENTS.md — StarRail-Combat-Simulator 开发与实机日志对账规范

## 1. 实机日志快速诊察工作流

对账新关卡、排查伤害/时间轴偏差或反查官方配置时，**禁止编写一次性遍历 JSON/日志的探索脚本或反复全量跑整场日志**，一律优先使用项目内置的两个诊察工具：

### 1.1 日志分歧与逐动时间线诊察（必用 `scripts/diff_log_turn.py`）

1. **首次定位最早分歧点**：
   ```powershell
   python scripts/diff_log_turn.py <battle_log.jsonl> [--extra-maze-buffs <id1,id2>]
   ```
2. **定位到具体 AV 后，强制加 `--av-budget` 截断并聚焦时间线**：
   调试早期或中段分歧点 `av` 时，**必须**携带 `--av-budget <av + 1.0>` 截断模拟；调单动分歧时优先单独传 `--av <av> --av-budget <av+1> --timeline`（仅跑 1 次模拟，同时输出 GT `[SKILL]` 技能行与 SIM 全乘区 `base / dmg% / def / res / vuln / crit`，减伤/护盾非 1 时附带 `red=` / `bar=`）：
   ```powershell
   python scripts/diff_log_turn.py <battle_log.jsonl> [--extra-maze-buffs ...] --av <av> --av-budget <av+1> --timeline
   ```
   仅当当前分歧点已修到 `< 0.0001%` 需要确认前后多回合是否过线或查看汇总表时，才追加 `--summary`（内部共享单轮 `reconcile_log` 与缓存索引，不再重复构建队伍/关卡）或放开 `--av-budget` 跑全量对账。
3. **常用选项**：
   - `--av <float>` / `--av-window <float>`：定位目标 AV 窗口（默认半径 `0.20`）；
   - `--av-budget <float>`：模拟截断 AV（调试期提速核心开关）；
   - `--summary` / `--full`：打印 `reconcile_log` 逐动汇总表 / 传 `--av` 时不自动早停、跑完整场；
   - `--threshold <float>`：告警阈值（默认 `1e-6` 即 `0.0001%`）。

### 1.2 官方配置 / Hash / Excel 秒查（必用 `scripts/inspect_ability.py`）

查官方 Ability AST、Modifier、`.NET Hash`、光锥、MazeBuff、BattleEvent 或怪物配置时，**禁止手写 `os.walk` / `glob` 遍历 `ConfigAbility/`**，一律调用缓存索引查询工具（底层 `GameDataLoader` 自动维护 `.cache/vm_ability_index_v1*.pkl` 磁盘缓存并按目录 `mtime` 失效，已加入 `.gitignore`）：

```powershell
# 1) 按 Ability / InnerModifier / GlobalModifier / GlobalTemplate 精确或子串查询
python scripts/inspect_ability.py <SymbolNameOrSubstr> [--list] [--limit 20] [--max-chars 4000] [--full]

# 2) 反查一个或多个 .NET Hash 对应的字段名与引用符号位置
python scripts/inspect_ability.py --hash <int> [<int> ...]

# 3) 按光锥 EquipmentID / SkillID 查询 ParamList 与绑定 Ability
python scripts/inspect_ability.py --equip <id>

# 4) 按 MazeBuff ID 查询 InBattleBindingKey / ModifierName 与参数
python scripts/inspect_ability.py --buff <id>

# 5) 按 BattleEvent ID 查询配置、技能列表与 ParamList
python scripts/inspect_ability.py --battle-event <id>

# 6) 按 MonsterID 查询 MonsterConfig / MonsterTemplateConfig / JsonConfig
python scripts/inspect_ability.py --monster <id>
```

## 2. 架构与质量红线

- **零手写日志/关卡插件**：所有对账修复必须落在通用 `ConfigAbility` VM、官方表加载器（`StageDataLoader` / `loader.py`）、通用调度器（`ActionScheduler` / `core.py`）或通用日志元信息提取器（`simulator/vm/reconcile/`），严禁针对特定关卡或日志编写定制补丁或硬编码数值。
- **严格验收标准**：
  - 每回合/每动伤害误差 **`< 0.0001%`**（`err < 1e-6`）；
  - `turn_matched == turn_total`、`ult_matched == ult_total`、`sp_granted == 0`、`memoria_granted == 0.0`、`forced_or_failed == 0`、`enemy_hit_mismatches == []`；
  - 现有 VM 对账与核心单测全量 `pytest` 零回归。
- **源文件修改规范**：所有仓库文件修改必须直接通过 `edit_file` / `write_file` 落盘，严禁通过临时脚本间接改写。
- **Windows PowerShell 环境注意**：不使用 `rg`、`head`、`tail`、`&&`，不在双引号内使用转义双引号。

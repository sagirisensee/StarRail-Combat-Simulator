# 官方实机战斗日志接入与 VM 对齐标准操作手册（SOP）

> 本文档沉淀自 Stage `30510021`、`30126122`、`30126121` 共 12 份官方实机日志实现 `< 0.01%`（多数 `0.0000%`）满对齐的完整排障经验。适用于任何新关卡、新怪物、新阵容的 `battle_logs/battle_*.jsonl` 接入与对齐。

---

## 0. 架构铁律（红线）

在动任何一行代码前，先确认以下四条底线：

1. **严禁手写插件与数值补丁**：不再新建 `simulator/plugins/log_*.py`，严禁按 AV、角色名、怪物模板 ID 或关卡 ID 写硬编码分支。
2. **严禁修改官方源数据**：`data/TurnBasedGameData/` 只读，所有差异必须由引擎正确解释官方 JSON/Excel 来解决。
3. **先修结构，再看伤害**：优先清零**崩溃异常** → **开局面板/速度偏差** → **`[HIT MISMATCH]` 三方受击错配** → **按时间轴从最早 AV 逐动归零**。绝不从总伤倒猜。
4. **必须测试钉死**：对齐完成后，必须挂进 `simulator/vm/test_vm_<stage_id>_alignment.py`，并断言 `total_err < 0.01%`、`max_turn_err < 0.01%`、`forced_or_failed == 0`、`enemy_hit_mismatches == []`。

---

## 1. 阶段一：首跑冒烟与开局面板核对（0~5 分钟）

### 1.1 运行首次纯数据驱动对账
```powershell
python -c "
from simulator.vm.reconcile import reconcile_log, format_report
r = reconcile_log(
    'battle_logs/battle_<TAG>.jsonl',
    team_override=['角色1', '角色2', '角色3', '角色4'],  # 按实机 1~4 号站位
    force_data_driven=True,
    use_existing_plugin=False,
)
print(format_report(r))
"
```

### 1.2 先排除 3 类“非引擎”前置偏差
在看任何伤害误差前，先核对日志前 30 行与模拟器的开局状态：

| 检查项 | 核对方法 | 常见坑 |
|---|---|---|
| **1. 队伍站位序** | 看日志首次群奶/群体掉血的 UID 顺序 | 站位颠倒会导致扩散相邻目标全错 |
| **2. 角色/光锥档案** | 核对 `data/character_db_export.json` 中的配装名（如 `知更鸟•晴歌_爱如此刻永恒`） | 档案与录屏配装不一致会导致开局面板整体偏移 |
| **3. 开局静态面板对撞** | 提取日志前 20 行 `OnStatChange` 中的 `ActionDelay`（`10000 / delay = 开局速度`）、`MaxHP`、`CriticalDamage` | 若全队速度/暴伤/生命呈统一常数偏移（如全队 `+12 速度`、`+30% 暴伤`），说明关卡挂了未接入的玩法/深渊全局 Buff（查 `StageConfigData`、`ChallengeMazeTierce.json`、`MazeBuff.json` 等） |

---

## 2. 阶段二：清理运行时阻断异常（Crash / `NotImplementedError`）

新关卡第一次跑通时，最常见的是官方 `ConfigAbility` JSON 中出现引擎尚未覆盖的新节点。按以下决策树分类处理：

### 2.1 纯表现层节点 → 剪枝白名单
- **典型特征**：`WaitAnimEvent`、`LevelAudioSwitch`、`ShowUI`、`GlobalTimeSlow`、`SetComfortZoneWidthOverride`、`SetEntityArtRotation`、`RetargetPerSequence` 等只涉及动画/音效/镜头的节点。
- **处理方式**：加入 [simulator/vm/loader.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/loader.py) 的 `PRUNABLE_PRESENTATION_TYPES`。

### 2.2 机械语义 Opcode → 原生实现
- **典型特征**：修改动态变量、添加关卡 Ability、削韧、销毁实体、随机分支等（如 `SetDynamicEntityParam`、`AddStageAbilityByName`、`DamageStance`、`DestroyBattleCharacter`、`RandomConfig`）。
- **处理方式**：在 [simulator/vm/executor.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/executor.py)（必要时配 [runtime.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/runtime.py)）原生实现。
- **高频深坑**：
  - `DestroyBattleCharacter` 若带 `CharacterUniqueName` 且未提供 `TargetType`，**绝不可默认回退到 `ctx.caster_id`**（否则呼雷的 `RageEnd` 清理节点会把呼雷自己秒杀）。
  - `SummonMonster` 由 `BattleEvent`（如 `BattleEvent_20008`）或 `__LEVEL__` 发起时，`stage_runner.py` 需回退到场上存活 Boss/首个敌人作为召唤池上下文。

### 2.3 怪物配置与被动初始化差异
- **AI 技能序列格式**：`OverrideAISkillSequence` / `AISkillSequence` 中的元素可能是 `dict`（如 `2013020 金人勾魂使` 的 `{'MNAHFIGOHML': 201302001}`），已在 [stage_ai.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_ai.py) 通用解析。
- **Wave 0 怪物被动**：确认 [stage_director.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_director.py) 在 Wave 0 及后续波次都触发了 `*PassiveSkillInitiate` 与 `SkillType == "Passive"` 的 `EntryAbility`（且 [stage_data_loader.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_data_loader.py) 中 `is_passive` 按 `SkillTriggerKey.startswith("Passive")` 判定）。

---

## 3. 阶段三：优先清零 `[HIT MISMATCH]` 三方受击错配

对账报告中的 `Enemy hit mismatches` 会对每次敌方出招做**现场三方对撞**：
`官方期望 (TargetInfo + 站位)` vs `模拟实际 (sim)` vs `日志实录 (log)`。

**只要还有任何 `[HIT MISMATCH]`，不要去猜后面的伤害误差，先全部修到 0！**

### 常见问题与根因速查表

| 报错现象 | 典型根因 | 通用修法与文件位置 |
|---|---|---|
| `sim=[] log=[...]`（敌方回合没打人） | 1. 怪物用 `Monster_Common_Sequence*_AI.json`（`UseSequenceSkill`），依赖 `OverrideAISkillSequence` 循环出招<br>2. 怪物 AI 用自定义 `*_AIFlag`（如 `Monster_XP_Elite02_01_AIFlag`）<br>3. 第 1 动技能通过 `AddModifier("OneMore")` 赋予同回合第 2 动 | 1. [stage_ai.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_ai.py)：`select_next_actions` 回退读取 `override_ai_skill_sequence`；`_AIFlag` 支持后缀匹配<br>2. [enemy_kit.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/enemy_kit.py)：循环内实时检查 `has_modifier(..., "OneMore")` |
| `sim=[1人] log=[3人]`（扩散变单体） | 技能的 `TargetInfo.SubTargetType == "TargetAdjoinEntity"` 或 Ability AST 中的 `TargetAdjoinEntity` 未编译进 `is_blast` | [stage_data_loader.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_data_loader.py) 编译 `is_blast`，[enemy_kit.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/enemy_kit.py) 直接读取，严禁按 `Skill01`/`Skill02` 硬编码 |
| `sim=[4人] log=[1~3人]`（单体/扩散变全体） | 误将非 `AllEnemy` 技能当全体结算 | [stage_data_loader.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_data_loader.py) 编译 `is_aoe = (TargetType == "AllEnemy")`，[enemy_kit.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/enemy_kit.py) 仅对 `is_aoe` 或 `GlobalTargetAlias` 走全体逻辑 |
| 模拟器多打 1 动（触发双倍受击/被动奶） | 1. 怪物无 `OneMorePerTurn` 却按 `rank == "Elite"` 误给了二动（如蚕食者之影）<br>2. `RemoveModifier("OneMorePerTurn")` 写在 ConfigAI 的 `PredicateTaskList` 分支里（如摇滚狂徒 `UseSkill03`）未被执行 | 1. [enemy_kit.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/enemy_kit.py)：按怪物 Ability 是否声明 `OneMorePerTurn` 决定初始二动<br>2. [enemy_kit.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/enemy_kit.py)：AI `PredicateTaskList` 求值时同步执行 `AddModifier`/`RemoveModifier` |
| 同 AV 多次行动受击目标串位 | 1. `auto_rng.py` 在同回合 `OneMorePerTurn` 第 2 动误推进了 `cursor_by_av`<br>2. `first_memo_owner` 占用了第 1 动后第 2 动未减去偏移<br>3. `known_blasts` 未排除 `primary` 自身 | [auto_rng.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/reconcile/auto_rng.py)：按 `TurnBeginEvent` 序号区分同回合多动与新回合；`known_blasts` 过滤 `ent is not primary` |
| 召错随机小怪（如 `玄爪狼卒` vs `蚀月狼卒`） | `RPG.GameCore.RandomConfig` 默认选第 0 项，与实机随机结果不同 | [metadata.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/reconcile/metadata.py) 记录 `OnInitializeEnemy` 序列，`auto_rng.py` 提供 `summon_id_provider`，[stage_runner.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_runner.py) 召唤时优先匹配实机召唤 ID |

---

## 4. 阶段四：按时间轴从最早偏差 AV 逐动归零

**黄金法则：永远只看第 1 个出现 `err >= 0.01%` 的 AV！** 后面的误差 90% 都是前面某一动的状态雪崩（HP、韧性、忆质、治疗池、击杀时机）滚出来的。

### 4.1 高频误差特征字典（看百分比秒定位）

| 误差特征 | 几乎必然的根因 | 排查动作 |
|---|---|---|
| **精准 `-10.000%` 或 `+11.111%`** | **韧性减伤（0.9 vs 1.0）不一致** | 1. 对比该 AV 敌方剩余韧性与是否破韧<br>2. 若发生在 Boss 转阶段后：检查转阶段前是否已破韧（[stage_runner.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/stage_runner.py) `was_broken` 规则）<br>3. 若仅 `缇宝:Additional` 差 `-10%`：检查两只怪谁的当前 HP 更高（是否之前某个主副倍率技能主目标选反导致血量高低互换！） |
| **整动差 `~10% ~ 20%`（单目标/某怪）** | **抗性差异 / 召错小怪 / 主副倍率主目标选反** | 检查 `servant_targets`（如长夜月忆灵 `AoEAttack` 主目标 2 倍倍率，[metadata.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/reconcile/metadata.py) 通过首次扣血量 `max > second * 1.4` 提取主目标）；检查实际出场的敌方模板 ID 是否与日志 `OnInitializeEnemy` 一致 |
| **长夜月忆灵差 `~4%` 或 `~8%`** | **忆质层数差 1~2 层** | 回溯前序敌方回合是否漏打 `长夜月` 或 `长夜`；检查 [metadata.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/reconcile/metadata.py) 受击回能检测是否漏捕了 `SPHitBase >= 15` 乘充能绳后的回能（上限需 `< 35.0`，不能写死 `< 15.0`） |
| **风堇小伊卡差 `+0.4% ~ +4%`，且后续每次行动误差精准减半** | **小伊卡累计治疗池多/少 1 次或 N 次被动奶** | 统计该 AV 之前每个 AV 的 `321.2` 被动奶次数（日志 `OnStatChange(CurrentHP)` vs 模拟器 `HealAppliedEvent`），1 秒锁定多奶或漏奶的精确 AV |
| **仅 `风堇:Additional`（专武附加伤）差 `0.01% ~ 0.3%`** | **风堇行动前全队当前 HP 存在几十~几百点尾差** | 对比该 AV 开动前我方全体（含忆灵）当前 HP；检查敌方扩散技能的副目标倍率 `adj_ratio` 是否按官方 `ParamList[1] / ParamList[0]` 计算（[enemy_kit.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/enemy_kit.py)） |
| **某动出现 `+86%` / `±50%` / `100%` 错位** | **残血怪击杀时机差 1 动，导致场上目标数不同或波次切换错位** | 倒查上一动结束时每只敌方的剩余 HP，通常是因为前面某动主目标选错或少了一段伤害 |
| **整段 AV 时间轴平移（GT 与 SIM 的 AV 对不上）** | **速度 / 行动值提前或延后机制缺失** | 检查开局 `ActionDelay`、敌方/场地拉条减速技能、或波次重置 AV 逻辑 |

### 4.2 常用 1 秒诊断片段
排查单个 AV 时，用以下两段探针即可瞬间看清真相：
1. **日志切片**：按 `OnTurnBegin` 切出目标 AV 区间，打印 `OnUseSkill`、`OnDamage`、敌方 `CurrentHP`、我方 `CurrentHP/CurrentSP`。
2. **模拟器切片**：订阅 `TurnBeginEvent` / `DamageAppliedEvent` / `HealAppliedEvent`，打印同一 AV 区间的敌方 HP/韧性、每次受击与被动奶目标列表，与日志逐行并排比对。

### 4.3 常用诊断脚本 API 速查（防写错签名）

写临时 `python -c` 探针时，直接复用以下标准导入与调用（**切勿凭记忆盲猜函数名**）：

```python
from simulator.db.character_db import CharacterDB
from simulator.golden import extract_timeline, parse_golden_jsonl, run_trajectory_replay
from simulator.vm.factory import build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.reconcile.codegen import format_report
from simulator.vm.reconcile.metadata import extract_log_metadata
from simulator.vm.reconcile.models import DEFAULT_CHAR_DB_PATH
from simulator.vm.reconcile.runner import build_stage_for_id, reconcile_log

# 1. 一键对账与打印报告
rep = reconcile_log(log_path, extra_maze_buff_ids=(3034013, 3034003))
print(format_report(rep))  # 指标字段: rep.total_err / rep.max_turn_err / rep.enemy_hit_mismatches

# 2. 截断到指定 AV 检查实体实时状态
meta = extract_log_metadata(log_path)
tl = extract_timeline(log_path)  # 参数为文件路径 str，非 BattleSequence
db = CharacterDB(); db.load(DEFAULT_CHAR_DB_PATH)  # 实例方法 load()，无 from_json
team = build_vm_team(meta.team_names, db=db, loader=GameDataLoader())
sim, director, _ = build_stage_for_id(
    meta.stage_id, team, technique_users=[e.name for e in team], extra_maze_buff_ids=(3034013, 3034003)
)
run_trajectory_replay(sim, director, tl, av_budget=50.0, log_path=log_path)
```

常见易错点避坑表：

| 容易写错 | 正确写法 |
|---|---|
| `parse_log_metadata` | `extract_log_metadata`（`simulator.vm.reconcile.metadata`） |
| `simulator.golden.loader` / `simulator.golden.timeline` | 统一从 `simulator.golden` 导入 `parse_golden_jsonl` / `extract_timeline` / `run_trajectory_replay` |
| `extract_timeline(g)` | `extract_timeline(log_path)`（传路径字符串） |
| `CharacterDB(path)` / `CharacterDB.from_json(path)` | `db = CharacterDB(); db.load(DEFAULT_CHAR_DB_PATH)` |
| `from simulator.vm.roster import build_vm_team` | `from simulator.vm.factory import build_vm_team` |
| `from simulator.vm.reconcile.runner import format_report` | `from simulator.vm.reconcile.codegen import format_report` |
| `rep.total_err_pct` / `rep.turns` | `rep.total_err`（小数，打印乘 100）/ `format_report(rep)` |
| `battle_*.jsonl` 直接 `ev.get("av")` | 事件结构为 `{"index", "time", "event", "data"}`，且 `data` 常为 Python dict 字符串，需 `ast.literal_eval` 或直接用 `parse_golden_jsonl` |
| `MazeBuff.json` 当 `dict` 调用 `.items()` | `ExcelOutput/MazeBuff.json` 顶层是 `list`（按 `row["ID"]` 检索） |
| PowerShell 里写 `cmd1 \|\| cmd2` | Windows PowerShell 5.1 不支持 `\|\|`，需用 `;` 或 `if ($?)` |

---

## 5. 阶段五：收口验收与回归防线

1. **确认四项硬指标全过**：
   - `total_err < 0.01%`
   - `max_turn_err < 0.01%`（`over_0.01% == 0/N`）
   - `forced_or_failed == 0`, `sp_granted == 0`, `memoria_granted == 0.0`
   - `enemy_hit_mismatches == []`
2. **落地正式对齐测试**：
   - 在 `simulator/vm/test_vm_<stage_id>_alignment.py` 中新增用例（参考 [test_vm_30126121_alignment.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/test_vm_30126121_alignment.py)），务必包含 `self.assertEqual(rep.enemy_hit_mismatches, [])`。
3. **回归验证（防修新坏旧）**：
   - 快速回归：`python -m pytest -v`（约 60s，覆盖全部核心单测与代表性对账用例）。
   - 全量对账回归（涉及 `enemy_kit.py` / `stage_runner.py` / `reconcile/` 改动时必跑）：
     ```powershell
     python -m pytest -m "slow or not slow" simulator/vm/test_vm_30126121_alignment.py simulator/vm/test_vm_30126122_alignment.py simulator/vm/test_vm_30510021_alignment.py -v
     ```
4. **干净提交**：确认 `git status` 无遗留临时文件后提交并推送。

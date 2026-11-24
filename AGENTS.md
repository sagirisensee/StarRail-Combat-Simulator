# AGENTS.md — StarRail-Combat-Simulator 开发与实机日志对账规范

## 1. 对账效率与执行铁律（四大防踩坑红线 ⚡）

复盘表明，对账耗时 80% 均浪费在手写探索脚本、多线并行上下文污染、凭感觉盲猜与无截断全量模拟上。所有开发者与 Agent 必须严格恪守以下四条铁律：

1. **严禁编写 ad-hoc 探索脚本**：**严禁**在终端中编写 `python -c "import json..."` 遍历 JSON、`glob.glob` 搜索代码或手工解析官方配置表。反查官方配置/Hash 必须统一使用 `scripts/inspect_ability.py`，日志诊察必须统一使用 `scripts/diff_log_turn.py`。
2. **单关绝对聚焦（严禁多线开工）**：一次**只能聚焦推进 1 个关卡 / 1 份实机日志**。在前一个关卡实现全量 `< 0.0001%` 归零前，**严禁**在同一次会话中交叉对账其他关卡或切换日志，防止上下文剧烈抖动与自我干扰。
3. **强制 `--av-budget` 截断验证**：调试具体动作时，**必须**携带 `--av-budget <av + 1.0>` 截断模拟（执行仅需 0.5 秒）；仅在当前分歧点完全修复、确认前后多动是否过线或全量交付时，方可放开 budget 跑全场。
4. **5分钟定性与“事不过二”收束（防盲猜内卷与爆 Quota）**：
   - **5分钟快速定性**：遇到分歧点，前 5 分钟内必须通过 `diff_log_turn.py --av <av> --timeline` 输出最早分歧动作的 SIM 全乘区与 GT 伤害，计算精确比值 $R = \text{GT} / \text{SIM}$。
   - **数学证伪（严禁盲改试错）**：提出任何假设（自爆易伤、减伤层数、倍率反了）前，必须先算该假设的理论影响是否与比值 $R$ 吻合。数学上无法解释 $R$ 的假设直接在纸面淘汰，严禁盲改代码验证。
   - **事不过二强制收束**：同一分歧点尝试修复 2 次仍未归零，严禁无休止内卷或跨关卡跳跃，必须主动停下，保存代码并向用户汇报当前定位、比值 $R$、各乘区分解与两次尝试结论。

---

## 2. 官方工具秒查规范

### 2.1 日志分歧与逐动时间线诊察（必用 `scripts/diff_log_turn.py`）

1. **首次定位最早分歧点**：
   ```powershell
   python scripts/diff_log_turn.py <battle_log.jsonl> [--extra-maze-buffs <id1,id2>]
   ```
2. **定位到具体 AV 后，强制加 `--av-budget` 截断并聚焦时间线**：
   单动分歧优先单独传 `--av <av> --av-budget <av+1> --timeline`（输出 GT `[SKILL]` 行与 SIM 全乘区 `base / dmg% / def / res / vuln / crit`，减伤/护盾附带 `red=` / `bar=`）：
   ```powershell
   python scripts/diff_log_turn.py <battle_log.jsonl> [--extra-maze-buffs ...] --av <av> --av-budget <av+1> --timeline
   ```
3. **常用选项**：
   - `--av <float>` / `--av-window <float>`：定位目标 AV 窗口（默认半径 `0.20`）；
   - `--av-budget <float>`：模拟截断 AV（调试期提速核心开关）；
   - `--summary` / `--full`：打印 `reconcile_log` 逐动汇总表 / 传 `--av` 时不自动早停、跑完整场；
   - `--threshold <float>`：告警阈值（默认 `1e-6` 即 `0.0001%`）。

### 2.2 官方配置 / Hash / Excel 秒查（必用 `scripts/inspect_ability.py`）

底层 `GameDataLoader` 维护 `.cache/vm_ability_index_v1*.pkl` 磁盘索引（按目录 mtime 自动失效），严禁手写代码遍历：

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

---

## 3. 实机日志对齐标准排障 SOP（五步法）

### 阶段一：首跑冒烟与开局前置偏差核对（0 ~ 5 分钟）
在深入细节伤害前，先看日志前 30 行与开局状态，排除 3 类前置非引擎偏差：

| 检查项 | 核对方法 | 常见坑与影响 |
|---|---|---|
| **1. 队伍站位顺序** | 看日志首次群体回血/掉血 UID 顺序 | 站位颠倒会导致扩散相邻目标完全错位 |
| **2. 角色/光锥档案** | 核对 `data/character_db_export.json` 配装（如 `知更鸟•晴歌_爱如此刻永恒`） | 档案与录屏配装不一致会导致开局面板整体偏移 |
| **3. 开局静态面板对撞** | 提取前 20 行 `ActionDelay`（速度 = `10000 / delay`）、`MaxHP`、`CriticalDamage` | 若全队呈常数偏移（如全队 `+12 速度`、`+30% 暴伤`），说明漏传关卡全局 MazeBuff（查 `ChallengeMazeTierce.json`、`MazeBuff.json`） |

### 阶段二：清理运行时阻断异常（Crash / `NotImplementedError`）
遇到官方 JSON 中未实现的全新 AST 节点，分类分流：
1. **纯表现层节点 → 剪枝白名单**：
   - 典型特征：`WaitAnimEvent`、`LevelAudioSwitch`、`ShowUI`、`GlobalTimeSlow`、`SetComfortZoneWidthOverride`、`SetEntityArtRotation`、`RetargetPerSequence` 等只涉及动画/音效/镜头的节点。
   - 处理方式：统一加入 `simulator/vm/loader.py` 的 `PRUNABLE_PRESENTATION_TYPES`。
2. **机械语义 Opcode → 原生通用实现**：
   - 典型特征：修改动态变量、添加关卡 Ability、削韧、销毁实体、随机分支等（如 `SetDynamicEntityParam`、`AddStageAbilityByName`、`DamageStance`、`DestroyBattleCharacter`、`RandomConfig`）。
   - 处理方式：在 `simulator/vm/executor.py` 或 `runtime.py` 原生通用实现，严禁硬编码特判。
3. **高频深坑与陷阱规避**：
   - `DestroyBattleCharacter` 若带 `CharacterUniqueName` 且未提供 `TargetType`，**绝不可默认回退到 `ctx.caster_id`**（否则呼雷的 `RageEnd` 清理节点会把呼雷自身秒杀）。
   - `SummonMonster` 由 `BattleEvent`（如 `BattleEvent_20008`）或 `__LEVEL__` 发起时，`stage_runner.py` 需回退到场上存活 Boss/首个敌人作为召唤池上下文。
   - `OverrideAISkillSequence` / `AISkillSequence` 中的元素可能是 `dict`（如 `2013020 金人勾魂使` 的 `{'MNAHFIGOHML': 201302001}`），由 `stage_ai.py` 通用解析。
   - Wave 0 怪物被动：确认 `stage_director.py` 在 Wave 0 及后续波次都触发了 `*PassiveSkillInitiate` 与 `SkillType == "Passive"` 的 `EntryAbility`（`stage_data_loader.py` 中 `is_passive` 按 `SkillTriggerKey.startswith("Passive")` 判定）。

### 阶段三：优先清零 `[HIT MISMATCH]` 三方受击错配
报告中的 `Enemy hit mismatches` 是敌方行为的现场三方对撞（官方期望 vs 模拟实际 vs 日志实录）。
**只要存在任何 `[HIT MISMATCH]`，不要看后续伤害，先全部修到 0！**

| 报错现象 | 典型根因 | 通用修复文件与逻辑 |
|---|---|---|
| `sim=[] log=[...]`（敌方回合未出招） | 1. 怪物依赖 `OverrideAISkillSequence` 循环出招<br>2. 怪物 AI 依赖自定义 `*_AIFlag`<br>3. 技能通过 `AddModifier("OneMore")` 赋予同回合二动 | 1. `stage_ai.py`：`select_next_actions` 回退读取 `override_ai_skill_sequence`；`_AIFlag` 支持后缀匹配<br>2. `enemy_kit.py`：循环内实时检查 `has_modifier(..., "OneMore")` |
| `sim=[1人] log=[3人]`（扩散变单体） | 技能 `TargetInfo.SubTargetType == "TargetAdjoinEntity"` 未编译进 `is_blast` | `stage_data_loader.py` 编译 `is_blast`，`enemy_kit.py` 直接读取，严禁按 `Skill01`/`Skill02` 硬编码 |
| `sim=[4人] log=[1~3人]`（扩散变全体） | 误将非 `AllEnemy` 技能当全体结算 | `stage_data_loader.py` 编译 `is_aoe = (TargetType == "AllEnemy")`，`enemy_kit.py` 仅对 `is_aoe` 或 `GlobalTargetAlias` 走全体 |
| 模拟器多打 1 动（双倍受击/被动奶） | 1. 怪物无 `OneMorePerTurn` 却误给了二动<br>2. `RemoveModifier("OneMorePerTurn")` 位于 ConfigAI 的 `PredicateTaskList` 分支内未执行 | 1. `enemy_kit.py`：按怪物 Ability 是否声明 `OneMorePerTurn` 决定初始二动<br>2. `enemy_kit.py`：AI `PredicateTaskList` 求值时同步执行 `AddModifier`/`RemoveModifier` |
| 同 AV 多动受击目标串位 | 1. `auto_rng.py` 在同回合二动误推了 `cursor_by_av`<br>2. `known_blasts` 未排除 `primary` 自身 | `auto_rng.py`：按 `TurnBeginEvent` 序号区分同回合多动与新回合；`known_blasts` 过滤 `ent is not primary` |
| 召错随机小怪（如玄爪 vs 蚀月） | `RPG.GameCore.RandomConfig` 默认选第 0 项，与实机随机结果不同 | `metadata.py` 记录 `OnInitializeEnemy` 序列，`auto_rng.py` 提供 `summon_id_provider`，`stage_runner.py` 优先匹配实机召唤 ID |

### 阶段四：按时间轴从最早偏差 AV 逐动归零
**永远只看第 1 个出现 `err >= 0.01%` 的动作！** 后续误差 90% 都是前序 HP、韧性、忆质或击杀时机滚出来的雪崩。

#### 1. 乘区比值数学定位法（严禁盲猜盲试）
伤害公式为纯连乘体系：
$$\text{Damage} = \text{Base} \times (1 + \text{DmgBoost}) \times \text{DefMult} \times \text{ResMult} \times \text{VulnMult} \times \text{DamageRedMult} \times \text{BrokenMult}$$
计算误差比值 $R = \frac{\text{GT Damage}}{\text{SIM Damage}}$，任何猜想必须能用该乘区公式严格解释：
- **$R \approx 1.1111$ 或 $0.9000$（$-10.000\%$ 或 $+11.111\%$）**：**韧性减伤（0.9 vs 1.0）不一致**（对比敌方破韧状态）。绝不是易伤或自爆！
  - 若发生在 Boss 转阶段后：检查转阶段前是否已破韧（`stage_runner.py` 的 `was_broken` 规则）。
  - 若仅某协同攻击差 `-10%`：检查两只怪当前 HP 高低（是否之前主副倍率选反导致血量顺序互换）。
- **$R \approx 0.8000$ 或 $1.2500$（$-20\%$ 或 $+25\%$）**：**抗性（20% 基础）或特定大额减伤层数**（如银枝护盾单层 20% 减伤漏算）。
- **$R \approx \frac{1 + V + \Delta V}{1 + V}$（几个百分点）**：**易伤乘区**（检查特定 Debuff 或自爆易伤是否未施加）。
- **$R = 1 \pm 0.005 \sim 0.02$（千分之几到百分之二）**：**固定伤害池/攻击力微小差异**：
  - 如知更鸟 Fever 累计奶量池少了一次触发、波次切换时 per-turn 标记未清理（如 `HyperCharge_TurnFlag`）。
  - 长夜月忆灵差 `~4%` 或 `~8%`：忆质层数差 1~2 层（倒查前序受击回能检测上限需 `< 35.0`，不能写死 `< 15.0`）。
  - 小伊卡累计治疗池差值：对比日志 `OnStatChange(CurrentHP)` vs 模拟器 `HealAppliedEvent`。
- **若 Base 乘区不一致**：说明是技能 Hit 数、倍率、攻击力面板或主副目标判定反了，不需要看防御或抗性（如长夜月忆灵 `AoEAttack` 主目标 2 倍倍率需按官方 `AvatarServantSkillConfig.json` 判定）。
- **若出现 `+86%` / `±50%` / `100%` 错位**：残血怪击杀时机差 1 动，导致场上目标数不同或波次切换错位。
- **整段时间轴平移**：开局速度/推拉条/减速机制未生效，或波次重置 AV 缺失。

#### 2. 事不过二执行门禁
1. **纸面算完再改代码**：计算出的理论比值若与实际 $R$ 不符，直接推翻该假说，**严禁修改代码验证无效假说**。
2. **两试不中即停**：同一动作若尝试修改 2 次仍未清零，立即停止自主尝试，向用户汇报当前比值 $R$ 与时间线排查现场。

### 阶段五：收口验收与回归防线

1. **确认五项硬指标全过**：
   - 全场总伤误差 `total_err < 0.0001%`（`err < 1e-6`）；
   - 逐动最大误差 `max_turn_err < 0.0001%`；
   - `turn_matched == turn_total`、`ult_matched == ult_total`；
   - `forced_or_failed == 0`、`sp_granted == 0`、`memoria_granted == 0.0`；
   - `enemy_hit_mismatches == []`。
2. **落地正式对齐测试**：
   在 `simulator/vm/test_vm_<stage_id>_alignment.py` 中新增用例，必须包含 `self.assertEqual(rep.enemy_hit_mismatches, [])` 与误差断言。
3. **回归验证（防修新坏旧）**：
   - 快速回归核心用例：
     ```powershell
     python -m pytest -v
     ```
   - 涉及 `enemy_kit.py` / `stage_runner.py` / `reconcile/` 等底层改动时跑全量对账回归：
     ```powershell
     python -m pytest -m "slow or not slow" simulator/vm/test_vm_*.py -v
     ```
4. **干净提交**：确认 `git status` 无遗留临时文件后提交。

---

## 4. 架构与质量红线

- **零手写日志/关卡插件**：所有对账修复必须落在通用 `ConfigAbility` VM、官方表加载器（`StageDataLoader` / `loader.py`）、通用调度器（`ActionScheduler` / `core.py`）或通用日志元信息提取器（`simulator/vm/reconcile/`），严禁针对特定关卡或日志编写定制补丁或硬编码数值。
- **官方源数据只读**：`data/TurnBasedGameData/` 只读，所有差异必须由引擎正确解释官方 JSON/Excel 来解决。
- **源文件修改规范**：所有仓库文件修改必须直接通过 `edit_file` / `write_file` 落盘，严禁通过临时脚本间接改写。
- **Windows PowerShell 环境注意**：不使用 `rg`、`head`、`tail`、`&&`，不在双引号内使用转义双引号。

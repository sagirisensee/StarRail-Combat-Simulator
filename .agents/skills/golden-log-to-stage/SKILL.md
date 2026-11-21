---
name: golden-log-to-stage
description: >-
  Generate clean, decoupled Log RNG Plugins, Stage alignments, and Tests (< 0.01%
  total damage error) directly from an official HSR battle_logs/battle_*.jsonl using
  the reconcile generator and the data-driven ConfigAbility VM engine.
---

# Golden Log to Stage: Data-Driven VM & Generator Workflow

Use this skill whenever onboarding a new official battle log (`battle_logs/battle_*.jsonl`) into `simulator/` using the **纯数据驱动官方 ConfigAbility VM 引擎** and the **自动对账与插件生成器 (`gen_reconcile.py`)**。

---

## 核心架构分层与职责边界 (Mandatory)

1. **纯数据驱动官方 ConfigAbility VM 引擎 (`simulator/vm/`)**
   - 关卡完全通过 `build_data_driven_stage(stage_id, team)` 构建，由官方数据和 Ability 运行时原生驱动：
     - `GameDataLoader` 解析官方 JSON 表项（角色、光锥、遗器、怪物、技能、状态 Modifier）；
     - 官方 AI 决策树 AST 与 `OneMorePerTurn` 等状态机联动，原生驱动行动逻辑；
     - 官方 Ability 表达式因果求值，计算伤害、治疗池累积、能量与削韧；
   - **绝对红线**：严禁在老关卡或执行器中写死特判、硬编码敌方技能或模拟器专有魔法数。

2. **自动对账与代码生成器 (`gen_reconcile.py` / `reconcile_generator.py`)**
   - 离线/静态代码生成器：从实机日志纯算法抽取事实，一键生成确定性的静态插件代码：
     - **受击目标提取**：通过敌方回合我方角色生命变动（`CurrentHP`），自动提取单体、弹射与扩散主副目标；
     - **我方锁敌提取**：自动捕获我方普攻/单体技能选定的首个扣血目标（`target_provider`）；
     - **敌方非攻击回合判定**：识别同 AV 连续行动（如【风行】自拉条）或无伤害事件，自动生成 `enemy_attack_skip`，杜绝把增益回合误判为攻击忆灵；
     - **忆灵受击约束推导**：基于怪物 Ability 目标范围（单体/扩散/全体）与可观测角色受击差额，确定性分配相邻忆灵受击位点；
     - **阿哈特殊事件提取**：准确归一化阿哈弹射的敌方扣血与我方伴生微伤（`aha_special_handler`）；
     - **未暴击账本提取**：自动从实机命中比值生成 `non_crit_ledgers.py` 中的 `(act_idx, hit_idx)` 集合。

3. **日志专属随机事件插件 (`simulator/plugins/log_<tag>.py`)**
   - 仅且只承接该场实机日志中**不可观测的离散随机事实**（如敌方弹射目标、阿哈随机命中、暴击随机性）；
   - **绝对红线**：严禁在插件中注入任何虚假治疗量（如手动扣减治疗池）、光锥扣血防抖微调或任何用于掩盖模型缺陷的直接伤害注入。

4. **通用回放与对账框架 (`simulator/golden_diff.py`)**
   - 负责抽取时间线、挂载先知与重放动作。严禁在回放框架内编写针对具体某条日志的硬编码判断。

---

## 标准接入与对账工作流 (4-Step Workflow)

### Step 1: 运行生成器提取事实并生成插件
针对待接入的官方战斗日志执行：
```powershell
python gen_reconcile.py battle_logs/battle_<tag>.jsonl --emit-plugin
```
生成器会自动解析并直接落盘生成标准的 `simulator/plugins/log_<tag>.py`。

### Step 2: 运行 VM 对账与误差诊断
在纯数据驱动官方 VM 下执行初次对账与逐动诊断：
```powershell
python gen_reconcile.py battle_logs/battle_<tag>.jsonl --data-driven --verbose
```
检查输出诊断报告：
- **动作匹配**：`turns == turn_total` 且 `ults == ult_total`（100% 匹配）；
- **资源补发**：`sp_granted == 0`，`memoria_granted == 0.0`，`presence_grants == 0`；
- **分歧诊断**：若存在单动误差 `>= 0.01%`，报告会自动指出产生分歧的首个 AV、攻击者及伤害细分类型（Servant / LC_Additional / Skill 等）。

### Step 3: 底层因果闭环（治本不治标）
> **调试 API 与排障速查**：进行事件探针追踪、实机 JSONL 窗口切片、或按误差指纹定位根因前，**先查阅 [docs/DEBUGGING_AND_API_REFERENCE.md](file:///Users/yunkaichen/Downloads/starrail/docs/DEBUGGING_AND_API_REFERENCE.md)** 获取核心入口精确签名（`build_vm_team` / `build_data_driven_stage` / `extract_timeline` / `run_trajectory_replay`）、对象真实字段与 5 步排障方法论，严禁凭猜测写探测脚本。

若存在机制偏差，**改动只发生在通用 ConfigAbility VM 引擎或生成器提取算法中**，严禁在 `log_<tag>.py` 里打补丁：
- **进战治疗池或光锥数值偏差**：在通用 VM 进战阶段（`OnBattleBegin`）校准秘技满血溢出规则或光锥 Modifier 状态机，让全量日志同时受益；
- **目标选择偏差**：优化生成器中的技能目标范围约束求解逻辑（如扩散到相邻忆灵），重新执行 Step 1 重新生成插件。

### Step 4: 注册单元测试并验证全绿门禁
在 `simulator/vm/test_vm_<stage_id>_alignment.py` 中添加用例：
```python
def test_vm_<tag>(self) -> None:
    self._run_vm_case(
        "<tag>",
        "battle_<tag>.jsonl",
        ["<角色1>", "<角色2>", ...],
        attach_log_<tag>_plugin,
        non_crits=OFFICIAL_<tag>_NON_CRITS,  # 若有
    )
```
执行官方测试门禁验证：
```powershell
pytest simulator/vm/test_vm_<stage_id>_alignment.py -k test_vm_<tag> -v
```
**全绿门禁验收标准**：
- 回合匹配：`100%`；
- 终结技匹配：`100%`；
- 强制干预/补发资源：`0`；
- 全场总伤误差：`< 0.01%`（重点用例要求更高）；
- 逐动伤害误差：全场所有结算动次单动误差全部 `< 0.01%`。

# AGENTS.md — StarRail-Combat-Simulator 开发与实机日志对账规范

## 1. 实机日志快速诊察工作流（必用 `scripts/diff_log_turn.py`）

对账新关卡或排查伤害/时间轴偏差时，**禁止盲写临时探索脚本或反复全量跑整场日志**，一律先用统一诊察脚本做最小步长迭代：

1. **首次定位最早分歧点**：
   ```powershell
   python scripts/diff_log_turn.py <battle_log.jsonl> [--extra-maze-buffs <id1,id2>]
   ```
2. **定位到具体 AV 后，强制加 `--av-budget` 截断提速（单轮 ~2~3s）**：
   调试早期或中段分歧点 `av` 时，**必须**携带 `--av-budget <av + 1.0>` 截断模拟，并用 `--av <av> --timeline` 直接对比 GT 与 SIM 的同窗逐条事件、伤害乘区（`base / dmg% / def / res / vuln / crit`）与召唤时间线：
   ```powershell
   python scripts/diff_log_turn.py <battle_log.jsonl> [--extra-maze-buffs ...] --av <av> --av-budget <av+1> --timeline
   ```
   仅当当前分歧点已修到 `< 0.0001%` 需要验证后续回合时，才放开 `--av-budget` 跑全量对账。
3. 常用选项：
   - `--av <float>` / `--av-window <float>`：定位目标 AV 窗口；
   - `--av-budget <float>`：模拟截断 AV（调试期提速核心开关）；
   - `--summary` / `--full`：精简汇总或展开全回合乘区明细；
   - `--threshold <float>`：告警阈值（默认 `1e-6` 即 `0.0001%`）。

## 2. 架构与质量红线

- **零手写日志/关卡插件**：所有对账修复必须落在通用 `ConfigAbility` VM、官方表加载器（`StageDataLoader` / `loader.py`）、通用调度器（`ActionScheduler` / `core.py`）或通用日志元信息提取器（`simulator/vm/reconcile/`），严禁针对特定关卡或日志编写定制补丁或硬编码数值。
- **严格验收标准**：
  - 每回合/每动伤害误差 **`< 0.0001%`**（`err < 1e-6`）；
  - `turn_matched == turn_total`、`ult_matched == ult_total`、`sp_granted == 0`、`memoria_granted == 0.0`、`forced_or_failed == 0`、`enemy_hit_mismatches == []`；
  - 现有 VM 对账与核心单测全量 `pytest` 零回归。
- **源文件修改规范**：所有仓库文件修改必须直接通过 `edit_file` / `write_file` 落盘，严禁通过临时脚本间接改写。
- **Windows PowerShell 环境注意**：不使用 `rg`、`head`、`tail`、`&&`，不在双引号内使用转义双引号。

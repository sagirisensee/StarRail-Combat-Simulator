# Pure Fiction Stage 30325041–30325043 对账进展与环境迁移交接记录

## 1. 虚构叙事 30325041–30325043 全量对账达成

三个关卡日志均已在官方 `ConfigAbility` VM 与通用解析链路下完成端到端全量对账（无 `--av-budget` 截断）：

- `battle_logs/battle_20261122_232910.jsonl`（关卡 `30325041`，`extra_maze_buff_ids=(3031359,)`）：
  - `turn=6/6  ult=13/13  sp=0  mem=0.0  pres=0  forced=0  total_err=0.000001%  max_turn_err=0.000001%  enemy_hit_mismatches=[]`
- `battle_logs/battle_20261122_233304.jsonl`（关卡 `30325042`，`extra_maze_buff_ids=(3031359, 3034013)`）：
  - `turn=9/9  ult=12/12  sp=0  mem=0.0  pres=0  forced=0  total_err=0.000001%  max_turn_err=0.000001%  enemy_hit_mismatches=[]`
- `battle_logs/battle_20261122_233727.jsonl`（关卡 `30325043`，`extra_maze_buff_ids=(3031359,)`）：
  - `turn=11/11  ult=12/12  sp=0  mem=0.0  pres=0  forced=0  total_err=0.000001%  max_turn_err=0.000001%  enemy_hit_mismatches=[]`

### 新增测试与工具

- 回归测试：`simulator/vm/test_vm_30325041_43_alignment.py`（与 `simulator/vm/test_vm_30126123_alignment.py`、`simulator/vm/test_stage_runner.py` 联合验证 `9 passed`）。
- 官方配置反查工具：`scripts/inspect_ability.py`（查询 Ability/Modifier/Template、`.NET Hash`、光锥、MazeBuff、BattleEvent 与怪物配置，并记录在 `AGENTS.md`）。

## 2. 本次一并提交的新增实机日志（待新环境继续对账）

- `battle_logs/battle_20261124_085116.jsonl`
- `battle_logs/battle_20261124_085908.jsonl`
- `battle_logs/battle_20261124_090259.jsonl`

## 3. 全量 `pytest`（5 failed, 56 passed）既有回归根因定位与待修复清单

迁移开发环境后，优先按以下已定位根因修复 4 组共 5 个回归并重跑全量 `pytest`：

1. **`test_vm_30126122_alignment.py::test_vm_20261115_041608`**（`Monster_W5_Fallen_00_BlackBlood` 侵蚀/黑潮血量 `DirtyHPRatio` 0.1 vs 0.2）：
   - **根因**：`DispelStatus`（`simulator/vm/executor.py:827-839`）在驱散 `StatusType == "Debuff"` 时未校验官方表 `ExcelOutput/*StatusConfig*.json` 中的 `CanDispel` 字段。`MonsterStatusConfig.json` 中 `Monster_W5_Fallen_00_BlackBlood` 与 `Monster_W5_Witch_00_BlackBlood` 均未标注 `CanDispel: True`，导致风堇战技/终结技在 `av=140.06` 与 `av=154.55` 错误驱散了黑潮 Debuff。
   - **修复方案**：在 `GameDataLoader`（`simulator/vm/loader.py:644`）缓存 `CanDispel`，并在 `ModifierEngine.can_dispel_modifier()` 与 `executor.py:836` 中强制校验。

2. **`test_vm_30126121_alignment.py::test_vm_20261122_023506`**（`Wolf_AttackCount` 双重计数导致呼雷在 `av=110.61` 提前触发 `Monster_W2_LycanKing_00_Skill07_Phase01`）：
   - **根因**：每次敌方 VM 攻击会触发两次 `OnListenAfterAttack`——一次在技能中执行 `DamagePerformFinish` -> `rt.flush_pending_after_attack()`（`simulator/vm/executor.py:1057`），一次在回合结束调用 `rt.end_being_attacked()`（`simulator/vm/enemy_kit.py:457` / `simulator/vm/runtime.py:276`）。
   - **修复方案**：在 `runtime.py:flush_pending_after_attack()` 清理 `self._open_enemy_attack`（当其等于 `caster_id` 时），并在 `enemy_kit.py:457-458` 调整为先调用 `rt.end_attack_scope()` 再调用 `rt.end_being_attacked()`。

3. **`test_reconcile_generator.py::test_memosprite_deficit_inference_on_184651` 与 `test_reconcile_benchmark_155925_and_emit`**（`av=96.09` `MEquip_23042` 差 `-498.80`）：
   - **根因**：`simulator/vm/enemy_kit.py:497-524` 将 `PredicateTaskList`/`Retarget` 纳入 `has_dynamic_ai_flag`，导致「流星铁鹰」（`Monster_W4_Harpy_00_AI.json`，无 `AIFlag` 切换且依赖未实现的 `ByCompareSkillUsageLimit`）绕过了 `enemy_attack_skip_provider`，在 `av=92.17` 误释放普攻命中「小伊卡」`537.16`（实机应为非攻击辅助技能 `Skill02`）。
   - **修复方案**：收窄 `has_dynamic_ai_flag` 判定仅针对存在 `AIFlag` 变更（或为 `Monster_W4_Harpy_00` 实现 `ByCompareSkillUsageLimit` 与 `SelectAISkillTarget`），同时保持虚构叙事怪物行为不受影响。

4. **`test_vm_30510021_alignment.py::test_vm_log_20261025_131019_alignment`**（`NotImplementedError: RPG.GameCore.SetCharacterShowSummonUI`）：
   - **根因**：`_init_stage_battle_events()` 现已执行 `BattleEvent 30503`（`BattleEventAbility_ChallengePeakBattle_CountDown` + `BattleEventAbility_SummonMonsterInfinite`），遇到未裁剪的 UI 节点与未实现的计数/限制节点。
   - **修复方案**：将 `SetCharacterShowSummonUI`、`ShowBattleVersusBarCountDownEffect`、`SetCountDownWarning` 加入 `PRUNABLE_PRESENTATION_TYPES`（`simulator/vm/loader.py` 及 `simulator/vm/stage_prunable_types.py`），补充 `SetLevelChallengeTurnLimit` / `LockTargetActionDelay` / `ByBattleHasCertainResult` 的基础处理，并将 `stage_director.py:808` 的无限波次兼容回退开关从硬编码 `31001` 泛化为检查 `BattleEventAbility_SummonMonsterInfinite`，防止 Wave 0 双重补怪。

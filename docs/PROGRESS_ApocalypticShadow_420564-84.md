# Apocalyptic Shadow Stage 420564–420584 对账进展记录

> 本文件更新于 **2026-11-24 19:19**。按用户指示，已完成末日幻影 **420584（银枝）** 与 **420574（玻吕刻斯）** 两关的 100% 实机对齐、对齐测试落地及全仓回归验证；**420564（帕姆）** 当前暂停待后续启动。

## 1. 总体进度总览

| 关卡 / 测试集 | 实机日志 / 测试文件 | `extra_maze_buff_ids` | 当前状态 | 实测对齐与回归指标 |
| :--- | :--- | :--- | :--- | :--- |
| **末日幻影 420584** (银枝 / Argenti) | [`battle_logs/battle_20261124_090259.jsonl`](file:///Users/yunkaichen/Downloads/starrail/battle_logs/battle_20261124_090259.jsonl)<br>[`simulator/vm/test_vm_420564_84_alignment.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/test_vm_420564_84_alignment.py) | `(3111092,)` | **100% 对齐（已入回归）** | `total_err=0.000000%` \| `max_turn_err=0.000002%` \| `31/31 [OK]`<br>`turn=21/21` \| `ult=19/19` \| `sp=0` \| `mem=0.0` \| `pres=0` \| `forced=0` \| `enemy_hit_mismatches: []` |
| **末日幻影 420574** (玻吕刻斯 / Pollux) | [`battle_logs/battle_20261124_085908.jsonl`](file:///Users/yunkaichen/Downloads/starrail/battle_logs/battle_20261124_085908.jsonl)<br>[`simulator/vm/test_vm_420564_84_alignment.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/test_vm_420564_84_alignment.py) | `(3111065,)` | **100% 对齐（已入回归）** | `total_err=0.000000%` \| `max_turn_err=0.000002%` \| `18/18 [OK]`<br>`turn=14/14` \| `ult=13/13` \| `sp=0` \| `mem=0.0` \| `pres=0` \| `forced=0` \| `enemy_hit_mismatches: []` |
| **末日幻影 420564** (帕姆 / Pam) | [`battle_logs/battle_20261124_085116.jsonl`](file:///Users/yunkaichen/Downloads/starrail/battle_logs/battle_20261124_085116.jsonl) | `(3111096,)` | **暂停待启动** | 已完成初步结构排查（`501402404` / BattleEvent `20057`–`20058`），按用户指令先暂停等待后续推进 |
| **默认全仓快速测试** (`pytest -v`) | `simulator/` | — | **全绿通过** | **`62 passed, 13 deselected in 81.86s`**（含 [`test_code_integrity.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/test_code_integrity.py) 与 `420574`/`420584`） |
| **全量 VM 对齐与单元测试** (`pytest -m "slow or not slow"`) | [`simulator/vm/test_vm_*.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/test_vm_420564_84_alignment.py) | — | **全绿通过** | **`27 passed in 103.07s`**（涵盖 `30126121`、`30126122`、`30126123`、`30325041–43`、`30510021` 及 `420574`、`420584`） |

> 附：`420574` 开局 `av=0.00` 核对说明 —— 该动开局即处于对齐状态（`gt=280,574.24` vs `sim=280,574.24`，`err=0.000002%`，`bar=0.0400`）；先前排查的 `bar=0.0400 -> 0.0500` 减伤剥离问题发生在二阶段转阶段窗口 `av=135.16`，已在后续 limbo 修复后完全归零。

---

## 2. 本轮新增与最终定型的通用 VM / 引擎修复

在既有 `301`/`303`/`305` 与银枝后段机制修复基础上，围绕 `420574` 与 `420584` 收尾阶段及全仓回归稳定性新增以下通用修复（全部遵循官方 ConfigAbility 数据驱动语义，零角色/关卡/日志硬编码）：

1. **攻后触发窗口（`_in_after_attack=True`）死亡监听与亡语悬停统一延迟**（[`simulator/vm/runtime.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/runtime.py), [`simulator/vm/ops/combat_ops.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/ops/combat_ops.py)）：
   - 在 `VMRuntime` 抽取 `flush_pending_listen_die()`，并在 `flush_pending_after_attack()` 的 `after_end_payload` 之后及 `combat_ops.py` 的 `rt.drain_pending_dying_enemies()` 之后统一调用。
   - `_on_enemy_defeated()` 将 `_attack_scope_depth > 0 or _in_after_attack` 且非 `_flushing_listen_die` 的击败事件统一推入 `_pending_listen_die`，防止类似 `MAvatar_Tribbie_00_SKL03_Buff_Buff` 多段追击/附加伤害中途直接派发 `OnListenCharacterDie` 提前剥离 `MMonster_W2_Argenti_IF_EX_EnemyCount_Sub` 减伤（解决了 `420584` `av=232.26` 的 `0.609506%` 偏差）。
   - `combat_ops.py` 同步将 `_in_after_attack` 期间触发的敌方击败纳入 `_pending_dying_enemies` 并由 `drain_pending_dying_enemies()` 在攻后钩子结束后结算亡语与级联退场。

2. **`RemoveModifier` 阶段 limbo 作用域隔离（`_include_phase_limbo`）**（[`simulator/vm/executor.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/executor.py), [`simulator/vm/target_alias.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/target_alias.py)）：
   - 在 `TaskExecutor` 的 `RPG.GameCore.RemoveModifier` 中独立设置临时上下文标记 `_include_phase_limbo = True`，在 `_alive_enemies` 中仅允许 `include_phase_limbo` 匹配 `_vm_limbo_pending=True` 的转阶段悬停实体。
   - 保持 `Retarget(IncludeLimbo=true)` 与 `TargetSequence(AddedOrAlive)` 语义不变，避免 Boss 进入转阶段 limbo 时被附加伤害重新选中（解决了 `30126121`、`30126122`、`30126123` 三关回退问题，同时保留 `420574` 二阶段 `av=135.16` 正确清层）。

3. **转阶段 limbo、`LockHP` 共享血条终态与低回能敌方受击审计**（[`simulator/effects.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/effects.py), [`simulator/vm/stage_director.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/stage_director.py), [`simulator/vm/enemy_kit.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/enemy_kit.py), [`simulator/vm/reconcile/metadata.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/reconcile/metadata.py), [`simulator/vm/reconcile/runner.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/reconcile/runner.py)）：
   - `sync_hp_shared_subtargets` 与 `finalize_dead_enemy` 确保 `DefineHPSharedGroup` 子目标在本体倒地前正确保持 `LockHP` 并在本体终态时级联清理。
   - `trigger_monster_phase_transition` 在 `OnEndBreak` / `OnListenEndBreak` 期间保留转阶段前 limbo 状态；`AddModifier(AliveOnly=True)` 跳过 `_vm_limbo_pending` 实体。
   - `metadata.py` 下调 `is_enemy_hit_sp` 检测下限并完善 `enemy_kit.py` / `runner.py` 敌方群体命中与忆灵归属的三方审计。

---

## 3. 新增对齐测试与最终回归记录

1. **新增测试文件**：[`simulator/vm/test_vm_420564_84_alignment.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/test_vm_420564_84_alignment.py)
   - `test_vm_420584_20261124_090259`（`420584`，`extra_maze_buff_ids=(3111092,)`）
   - `test_vm_420574_20261124_085908`（`420574`，`extra_maze_buff_ids=(3111065,)`）
   - 严格校验 `turn_matched == turn_total`、`ult_matched == ult_total`、`sp_granted == 0`、`memoria_granted == 0.0`、`presence_grants == 0`、`forced_or_failed == 0`、`enemy_hit_mismatches == []`、`total_err < 1e-6` 与逐动 `td.err < 1e-6`。
2. **完整验证命令与结果**：
   - `python3 -m pytest -v` → **`62 passed, 13 deselected in 81.86s`**
   - `python3 -m pytest -m "slow or not slow" simulator/vm/test_vm_*.py -v` → **`27 passed in 103.07s`**
   - `python3 scripts/diff_log_turn.py battle_logs/battle_20261124_090259.jsonl --extra-maze-buffs 3111092 --summary` → `31/31 [OK]`, `total_err=0.000000%`, `max_turn_err=0.000002%`
   - `python3 scripts/diff_log_turn.py battle_logs/battle_20261124_085908.jsonl --extra-maze-buffs 3111065 --summary` → `18/18 [OK]`, `total_err=0.000000%`, `max_turn_err=0.000002%`

---

## 4. 下一步恢复待办（`420564` 帕姆）

- 后续恢复时仅需聚焦单关 [`battle_logs/battle_20261124_085116.jsonl`](file:///Users/yunkaichen/Downloads/starrail/battle_logs/battle_20261124_085116.jsonl)（`--extra-maze-buffs 3111096`），按 `AGENTS.md` 五步法排查对齐，对齐后再补充 `test_vm_420564_*` 用例至 [`simulator/vm/test_vm_420564_84_alignment.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/test_vm_420564_84_alignment.py)。
- 当前工作区改动尚未 `git commit`（`git status -s` 共 `45` 项：`32` 项已跟踪修改 `M`、`10` 项删除 `D`、`3` 项新增未跟踪文件 `??`）。

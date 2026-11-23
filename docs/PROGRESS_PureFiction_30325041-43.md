# 虚构叙事 3 场日志对齐进度 (WIP, 2026-11-24)

目标：`30325041/42/43` 三场日志仅靠官方 `ConfigAbility` VM + `StageDataLoader` 对齐，每回合误差 `< 0.0001%`，`forced=0`，`enemy_hit_mismatches=[]`。

| 日志 | Stage | extra_maze_buff_ids | 备注 |
|---|---|---|---|
| `battle_logs/battle_20261122_232910.jsonl` | 30325041 | `(3031359,)` | 上一轮提交 `6d84afd` 后本轮改动未再单独重跑，待收口统一全量复验 |
| `battle_logs/battle_20261122_233304.jsonl` | 30325042 | `(3031359, 3034013)` | `3034003` 由 `StageInvasionConfig` 自动挂载；前 5 动已 `< 0.0001%` |
| `battle_logs/battle_20261122_233727.jsonl` | 30325043 | `(3031359,)` | 待补 `BlockDamage` / `OnAfterBeingHit` 后推进 |

诊断工具：`python scripts/diff_log_turn.py <log> --extra-maze-buffs ... [--av X --av-budget N --timeline]`（详见 `AGENTS.md`）。

## 本阶段已落盘通用修复（对比 `6d84afd`）
- **`AGENTS.md`**：补充实机日志快速诊察工作流（强制 `--av-budget` 截断与 `--timeline` 对比）及零手写插件红线。
- **`simulator/damage.py`**：易伤乘区 `vuln_mult` 裁剪至 `[0.0, 3.5]`（对应官方 `+250%` 易伤上限）。
- **`simulator/vm/runtime.py`**：将 `OnAfterBeingAttackedEnd` 延后至 `_pending_dying_enemies`、`OnListenCharacterDie`、limbo 死亡后事件及 `_pending_level_kills` 完成后派发，防止 `MCommon_Gluttony_LV3` 在小怪死亡 6% 真伤结算前提前解锁/回满 Boss 血量。
- **`simulator/vm/ops/combat_ops.py`**：抽离 `_clamp_enemy_direct_hp_loss` 共享辅助函数，统一让直伤 `__LEVEL__`/自身 `ByBaseDamage` 与 `LoseHPByRatio` 遵守 `lock_hp_ratio`、锁血转阶段与 `OnLockHPThresholdReached`。
- **`simulator/vm/executor.py`**：`DispelStatus` 通过 `me.get_modifier_status_type(m) == "Debuff"` 识别 `StatusConfig.json` 中的全局负面状态（修复风堇战技驱散触电 DOT），并完善 `SetDieImmediately`、`TargetSortByProperty` 与 `AddModifier`（`AliveOnly` 对 `_in_deathrattle_limbo` 的兼容）。
- **`simulator/vm/stage_director.py`**：自动挂载并去重 `StageInvasionConfig` 的 `maze_buff_id`（`30325042` 自动挂载 `3034003`）。
- **`simulator/vm/ops/turn_ops.py`**：`_run_insert` 回退目标纳入 `_in_deathrattle_limbo`，记录 `_pending_deathrattle_actions` 以延后死亡结算。
- **`simulator/effects.py`**：为 `OnBeforeBeingHitAll` / `OnAfterBeingHitAll` 传入 `current_attack_type="DOT"`。
- **`simulator/combat_port.py` & `simulator/vm/modifier_engine.py`**：补齐 `VMModifierInstance.caster_snapshot_entity` 与 `CombatPort.attack(..., source_entity=...)`。
- 另有 `.gitignore`、`simulator/vm/loader.py`、`simulator/vm/stage_data_loader.py`、`simulator/vm/reconcile/{auto_rng,metadata,models,runner}.py` 的通用支持改动随本次一并提交。

## 当前验证状态
- `pytest simulator/vm/test_vm_30126123_alignment.py`：通过（回归门禁）。
- `battle_20261122_233304.jsonl`（Stage `30325042`，`--av-budget 88.5` 前 5 动 `< 0.0001%`）：
  - `av=0.00`：`gt=5,788,195.98`, `sim=5,788,195.96`, `err=0.000000%`
  - `av=40.96`：`gt=12,031,670.26`, `sim=12,031,670.28`, `err=0.000000%`
  - `av=45.26`：`gt=27,638,908.05`, `sim=27,638,908.18`, `err=0.000000%`
  - `av=69.07`：`gt=2,745,094.69`, `sim=2,745,094.70`, `err=0.000001%`
  - `av=87.71`：`gt=7,182,234.63`, `sim=7,182,234.69`, `err=0.000001%`

## 已定位根因（尚未改码，继续时直接推进）
1. **`233304` `av=88.94` 分歧（`gt=4,055,023.59` vs `sim=4,215,222.69`，`err=3.950633%`）**：
   - **BattleEvent `20049`（`扫除` `2004901`，`Avatar_AvatarChange_W5_PamPart_00`）未在 Wave 3 进场 (`av=45.26`) 生成与行动**：
     1. `Monster_W5_Pam_00_PassiveSkill02_Phase01_FantasticStory` 同时配置了 `OnAdd` 与 `OnStart`，`simulator/vm/runtime.py` `trigger_ability` 当前仅执行 `OnStart` 而跳过 `OnAdd`（导致 `Monster_W5_Pam_00_FantasticStory` 未挂载）。
     2. 中途波次（Wave 3）怪物刷新时未在 `simulator/vm/stage_director.py` 派发 `OnEnterBattle`，导致 `BattleEventAbility_W5_Pam_SummonMonster_FantasticStory` 未触发 `CreateBattleEvent(20049)`。
     3. `simulator/vm/ops/predicates.py` 中 `RPG.GameCore.ByCheckCustomValueBool` 未读取 `Key["Hash"]`（如 `1557799697` / `1898157109`，需同时确认其初始化/判定来源及 `BattleEvent_20049` 速度 `168.0` 的公式与 `2004901` 伤害 `13,061.9842` 系数）。
     4. `simulator/vm/ops/turn_ops.py` 的 `_execute_create_battle_event` 目前将事件统一建为 `is_countdown=True` 且仅读 `BattleEventConfig.AbilityList`，尚未支持 `EventSubType == "DummyCharacter"` 从 `BattleEventData.json` 加载 `SkillList` 与通过 `ModifyActionDelay(-1)` 在 `av=45.26` 立即执行 `2004901`（GT 中打 `100144` 5 段 `13,061.9842`，使其在 `av=87.71` 死亡并刷新 `100150`）。
   - **`1409:Additional` (`MEquip_23042`) `77,187.55` (SIM) vs `74,189.41` (GT)**：
     - 主因是 `100144` 在 `av=87.71` 未死，导致 `av=88.94` `小伊卡:Servant` 击杀 2 只小怪后场上仅剩 3 名敌人，触发长夜月 E1 `Attacker_BaseDamageMultiRatio=1.25`（GT 场上剩 4 名敌人为 `1.20`）；修通 `20049` 后需复检剩余约 `+0.12%`（`+89.36`，疑与 `小伊卡` 在 `av=79.98`/`87.71` 被动治疗后血量 `4808.02` vs `MaxHP 4882.53` 相关）的微差并继续推进 `av=91.60+`。
2. **`233727` (`Stage 30325043`)**：
   - `Monster_XP_Minion04_02_Ability.json`（`MMonster_XP_Minion04_02_Cunhu_Buff`）使用 `BlockDamageExcludeDot` + `OnAfterBeingHit` + `ByIsTriggeredBlockDamage`；GT（`L5146-5151`）已证实抵挡时生命不变且仍记录 `OnDamage(damage=0.0)`。需在 `predicates.py`、`effects.py`、`ops/combat_ops.py` 与 `runtime.py` 补齐。

## 后续待办
1. 完成 `233304` 的 `20049` (`DummyCharacter` / `OnAdd` / 波次 `OnEnterBattle` / `ByCheckCustomValueBool`) 修复并对齐全 9 动 `< 0.0001%`。
2. 实现 `BlockDamage` / `BlockDamageExcludeDot` + `OnAfterBeingHit` + `ByIsTriggeredBlockDamage`，并用 `--av-budget` 推进对齐 `233727` (`30325043`)。
3. 全量无 `--av-budget` 复验 `232910`、`233304`、`233727` 三场日志均满足 `< 0.0001%` 与零人工兜底/命中不一致。
4. 参照 `simulator/vm/test_vm_30126123_alignment.py` 新增 `simulator/vm/test_vm_30325041_43_alignment.py` 并全量跑通 `pytest`，提交并 push `dev`。

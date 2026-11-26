# Stage 1052096（周本「万色返空主，归寂」/ 海瑟音 DoT 队）实机日志对齐记录

## 1. 对齐目标与标准验收命令

- **实机日志**：`battle_logs/battle_20261126_060855.jsonl`（4,177 行事件，终局 AV = `294.94`）
- **队伍配置**：`['藿藿', '卡芙卡', '海瑟音', '黑天鹅']`（1217 E1/S5 加强态、1005 E0/S1 非加强态、1410 E2/S1、1307 E1/S1 加强态）
- **开局入参**：`--init-ep 1217:108.68882052414119,1005:120.0,1410:0.0,1307:84.19999999762513 --tech-users 1307`

```powershell
python scripts/diff_log_turn.py battle_logs/battle_20261126_060855.jsonl --init-ep 1217:108.68882052414119,1005:120.0,1410:0.0,1307:84.19999999762513 --tech-users 1307 --summary --dot-summary
```

## 2. 全量验收结果（全部五项硬指标通过）

- **回合与终结技对齐**：`turn=23/23`、`ult=13/13`
- **零真值反推 / 强行兜底**：`sp=0`、`ult_e=0.00`、`mem=0.0`、`pres=0`、`forced=0`
- **敌方三方命中审计**：`enemy_hit_mismatches: []`
- **全量总伤与逐动误差**：
  - `gt_total = 12,256,951.73` vs `sim_total = 12,256,951.77`（`total_err = 0.000000%`）
  - `max_turn_err = 0.000002%`（全部 23 动均 `<= 0.000002% < 0.0001%`）
- **逐 AV DoT 对账**（共 14 个 DoT 结算窗口：`59.52, 60.44, 113.63, 118.90, 119.05, 171.78, 174.31, 178.57, 179.68, 222.66, 224.52, 234.31, 287.05, 294.94`）：
  - `gt_dot_total = 11,200,059.24` vs `sim_dot_total = 11,200,059.28`（`dot_diff = +0.04`）
  - 全部 14 个 AV 单窗误差均 `<= 0.000001% < 0.0001%`
  - Layer-4 DoT RNG 统计：`probes=85, rc_overrides=21, ch_overrides=78`
- **回归测试**：已落地 `simulator/vm/test_vm_1052096_alignment.py`（`@pytest.mark.slow`）

## 3. 核心根因排查与通用修复

1. **Layer-4 DoT RNG 收敛与分段目标定位（`simulator/vm/reconcile/dot_rng.py`、`runner.py`）**：
   - 支持同 `(av, target, caster)` 单 AV 内多轮 DoT 引爆按 `dot_epoch` 精确归因 `CHANCE` 槽位（`_ordered_gt_and_sim_hits_for_caster` / `_sim_hit_for_epoch`）。
   - 将 `_solve_chance_pool` 升级为带区间插值的割线逼近，加入 `tested_rc_keys` 跨阶段去重、`max_probes_per_pair = 28` 收敛保护。
   - 修正 `runner.py` 中 `_has_budget_dot_err` 与 `dot_rng.py` 预算过滤边界（收紧至 `+ 1e-6`），并修正未传 `av_budget` 时 `effective_final_av` 误用 `g.final_av` 导致终局 AV 可能被浮点截断的问题（改为 `0.0` 无界）。
2. **终局 `av=294.94` 共享血量击杀与鞭尸 Overkill DoT 对齐（`simulator/vm/ops/modifier_ops.py`、`dot_rng.py`）**：
   - 在 `ModifierOpsMixin._op_trigger_modifier_custom_event` 遍历 `targets` 前过滤已阵亡目标（`current_hp <= 0.0` 且非无限血量/亡语悬停态），防止对主部位引爆黑天鹅奥迹击杀整组共享血量部位后，继续引爆已死亡的「住」「坏」部位；同时保留已累计 `MDF_DotHitCount` 的 `OnAfterBeingAttacked` 海瑟音结界 DoT Overkill 结算。
   - 修正 `extract_gt_dot_hits` 在共享血量多部位场景下的目标 UID 提取：对连续非递增 `OnStatChange(CurrentHP)` 记录取**首个**敌方 UID（`first_enemy_uid`），使实机存活段（`100057 -> 100012 -> 100055`）与击杀后 Overkill 段（仅 `100057`）归属统一，不再被拆成两个虚假目标。
3. **VM 内核与数据加载热路径优化（零行为变化）**：
   - `simulator/vm/modifier_engine.py`：事件按 `_by_event` 分桶索引、`OnDynamicValueChange` 按 `_dvc_mods` 索引、`id(cfg)` 缓存 `_get_cfg_callbacks`、`cache _lookup_modifier_config`（仅缓存命中，不缓存空配置）、`iter_stat_modifiers` 空持有者早退及 `dict` 快速类型判定。
   - `simulator/vm/loader.py`：lookup 直接判定 `_ability_index_built`，并新增 `load_character` 编译产物缓存 `_compiled_char_cache`（返回可变容器浅拷贝）。
   - `simulator/core.py`、`simulator/vm/stage_runner.py`、`simulator/vm/expr.py`、`simulator/vm/executor.py`、`simulator/vm/target_alias.py`、`simulator/vm/ops/predicates.py`：`get_entity` 优先快扫 `e.name`、缓存怪物技能前缀 `_skills_by_prefix_cache`、`resolve_target_alias` 无 `+`/`-` 单 token 快路径及高频 `dict` 类型判断前置。

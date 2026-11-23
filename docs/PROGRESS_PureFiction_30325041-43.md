# 虚构叙事 3 场日志对齐进度 (WIP, 2026-11-23)

目标：`30325041/42/43` 三场日志仅靠官方 ConfigAbility VM + StageDataLoader 对齐，每回合误差 < 0.0001%，forced=0，enemy_hit_mismatches=[]。

| 日志 | Stage | extra_maze_buff_ids |
|---|---|---|
| battle_20261122_232910 | 30325041 | (3031359,) |
| battle_20261122_233304 | 30325042 | (3031359, 3034013) |
| battle_20261122_233727 | 30325043 | (3031359,) |

诊断工具：`python scripts/diff_log_turn.py <log> --extra-maze-buffs ... [--av X --timeline] [--av-budget N]`

## 已完成
- stage_director：战斗开始后不再重复派发全局 OnListenCharacterCreate
- target_alias：`*AdjoinEntity` 保留死亡施法者的站位
- scheduler/turn_ops：`immediate_priority`(MonsterSummon=5)、`allow_limbo`；全灭时补怪先于我方追击
- loader：展开 TriggerAnimStateWithMove；executor：IKAHOOLKHDN 空操作
- replay `_ult_blocked`：满能量大招可打断同 AV 敌方回合
- core：同 AV 动作条平局排序加入批次 `_av_tie_epoch` / `_spawn_seq`（后生成批次先于先前等待者）
- reconcile/metadata：初始敌方 UID 去掉已有 OnInitializeEnemy 的怪（修正 `天谴斗士_3` 命名错位）
- 232910：av=0 / 25 / 43.64 / 47.87 均 0.000000%

## 当前未解决
- 232910 av=72.73 误差 3.01%：`残破容器`(MaxHP 1,932,940) 在 GT 中被缇宝追击第 2 次后，韧性 15→0 触发击破(7,564.64)致死；SIM 同样走到 tough=15、hp=7339.4，但击破伤害 SIM=6641.77 vs GT=7564.64（比值 0.878；SIM 因此只扣到剩约 698 HP，残破容器未死）。已确认 SIM 的 `max_toughness=180`、弱点 Ice/Lightning/Quantum，GT 日志 CurrentStance 序列 120→105→15→0 与 SIM 一致；
  下一步查击破伤害乘区（疑 `Defender_DefenceAddedRatio=-0.545` 对击破的作用 / tough_mult / 抗性），以及击破致死后 `黑潮蚀斧_2/_3` 未出手(enemy_hit_mismatches)。
- 232910 av=93.96、101.83 待在 72.73 修复后继续查
- 233727 (30325043) av=0.00：长夜忆灵爆发后 `银鬃炮手_7` 存活 vs GT 全灭
- 233304 (30325042) 尚未逐回合排查

## 待办
1. 修 72.73 击破伤害/致死后续（见上），跑到 232910 全回合 < 1e-6
2. `simulator/vm/reconcile/runner.py` L628-644：overrides 非空时的二次 `_run_single_pass` 漏传 `extra_maze_buff_ids`
3. 对齐 233727、233304
4. 参照 `simulator/vm/test_vm_30126123_alignment.py` 新增 30325041/42/43 严格(<1e-6)逐回合对齐测试
5. 全量 pytest 无回归，commit 并 push dev

## 注意
- 仅用 edit_file/write_file 改仓库文件；不写手写日志/关卡插件
- Entity 的 `is_unselectable` 用 `getattr(e, "is_unselectable", False)`
- 本次提交为 WIP，全量 pytest 尚未跑，对齐测试尚未添加

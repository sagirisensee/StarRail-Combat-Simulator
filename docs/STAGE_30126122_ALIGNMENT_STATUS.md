# 关卡 30126122 官方数据驱动对账进展与待办 (纯 Data-Driven 架构)

> **目标**：彻底淘汰手写关卡与硬编码怪物 Kit（`stage_30126122.py`），全量切入官方原始数据驱动关卡引擎 `build_data_driven_stage(30126122)`，在 ConfigAbility VM 下将全部 8 个实机日志压进 **总伤误差 < 0.01% (`0.0001`)** 统一门禁。

---

## 一、本次落盘的核心架构与机制突破

### 1. 官方召唤 AST 任务执行与动态延迟比例（DelayRatio）求值
- **问题定位**：
  此前正阳狮鹫在首动（31.57 AV）召唤 3 只【流星铁鹰】时，铁鹰被赋予 `0.0` 距离，导致 31.57 AV 瞬发抢先行动，挤乱时间线。
- **根本原因**：
  官方技能配置 `Monster_W4_Griffin_00_Config.json` 中，召唤距离比例使用了动态哈希（`-1441271971` 等），指向狮鹫 `Skill02` 的技能参数（Index 1 = 0.5，Index 2 = 0.8，Index 3 = 1.1）。此前 StageRunner 缺乏角色模板 `DynamicValues -> SkillParam` 映射。
- **落盘修复**（[simulator/vm/stage_runner.py](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/stage_runner.py)）：
  在 `_register_enemy` 中解析并挂载官方角色模板的动态哈希映射，使召唤距离完全按官方原始配置动态求值：
  - 铁鹰 1 号：5000.0 距离（首动 69.44 AV）
  - 铁鹰 2 号：8000.0 距离（首动 92.18 AV）
  - 铁鹰 3 号：11000.0 距离（首动 114.92 AV）

### 2. 敌方攻击统一接入 `apply_enemy_attack` 与 VM 回调
- **落盘修复**（[simulator/vm/stage_sim_adapter.py](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/stage_sim_adapter.py)）：
  - `DataDrivenEnemyKit.execute_turn` 统一调用 `enemy_port.apply_enemy_attack` 与 `finish_enemy_being_hit`，完整触发 `vm_runtime.begin_being_attacked`、`OnAfterBeingHitAll` 与受击回能。
  - `apply_aha_ally_chip_hit` 完整接入 `OnBeforeBeingHitAll`、`HPLostEvent`、`OnAfterBeingHitAll` 分发，并实现忆灵受击回能重定向给本体。

### 3. 底层战斗机制对齐
- **忆灵站位序对齐**（`target_alias.py`）：首个忆灵固定排列在队伍最右侧，解决天马 Skill04 扩散伤害目标偏差。
- **生命上限缩放**（`status.py`）：修复上限到期回落时的当前生命值等比缩放。
- **阿哈额外回合**（`stage_sim_adapter.py`）：首击广播 `TurnBeginEvent`，并在 `flush_ally_talent_heals` 中补齐 `OnListenBeforeTurnPhase1End` 事件派发，闭环多段受击后的延迟天赋治疗。
- **治疗加成动态重算**（`executor.py`）：解锁 `_execute_heal` 治疗加成快照，支持秘技/群奶过程中动态响应遗器提速转治疗加成。

### 4. 纯通用敌方机制与零硬编码生成器 (`stage_sim_adapter.py` / `reconcile_generator.py`)
- **敌方风行再动与非攻击辅助回合**（`stage_sim_adapter.py`）：`DataDrivenEnemyKit` 接入 `MCommon_FastAction` / `enemy_windwalk_provider`（回合末 `reset_distance=0.0` 立即再动）及 `enemy_attack_skip_provider`。
- **敌方技能 Modifier 原生 VM 执行**（`stage_sim_adapter.py`）：通用注入官方怪物 `CharacterConfig` 的 `SkillParam` 动态表，执行敌方技能 AST 的 `AddModifier`（如天马 `Unicorn_Debuff_Mark` + 狮鹫 `Griffin_Debuff_Mark` 叠加触发 `_MixedMark_LoseHpRatio = 0.25` 原生真伤）。
- **生成器全面去硬编码**（`reconcile_generator.py`）：移除 `build_stage_30126122` 回退及所有关卡/怪物/角色/魔数特判，改为基于 `StageDataLoader` 自动映射敌方 UID，基于受击回能差额 (`sp_gain_counts > hit_counts`) 通用反推忆灵受击/扩散/阿哈微伤，并加入阿哈致死标记防残血。

---

## 二、当前对账达标状态 (按 `data_driven=True` + `0.01%` 严格红灯标准)

> **原则**：单元测试统一以真实终态标准 `data_driven=True` 与 `total_limit=0.0001 / turn_limit=0.0001 (0.01%)` 为准挂红灯，实事求是暴露所有未达标点。

| 用例 ID | 队伍阵容 | 状态 | 当前总伤误差 | 轨迹状态 | 备注 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **155925** | 风堇 + 长夜月 | 🟢 **全绿达标** | **0.0000%** | 8/8 动 + 3/3 大招 (100%) | 11/11 动全部 `<= 0.0002%`，零硬编码通用生成器一键生成通过 |
| **204943** | 风堇 + 知更鸟•晴歌 | 🔴 待微调 | 0.4098% | 100% 吻合 | 纯数据驱动已打通，待微调晴歌受击/治疗层数收进 0.01% |
| **184651** | 风堇 + 长夜月 | 🔴 待跑纯数据驱动 | - | - | 前置机制已就绪 |
| **184845** | 风堇 + 缇宝 | 🔴 待跑纯数据驱动 | - | - | 前置机制已就绪 |
| **205144** | 缇宝 + 风堇 + 知更鸟•晴歌 | 🔴 待测第二波 | - | - | 待对接堕神之血 |
| **220255** | 缇宝 + 风堇 + 知更鸟•晴歌 | 🔴 待测第二波 | - | - | 待对接堕神之血 |
| **221208** | 长夜月 + 风堇 + 知更鸟•晴歌 | 🔴 待测第二波 | - | - | 待对接堕神之血 |
| **222204** | 缇宝 + 长夜月 + 风堇 | 🔴 待测第二波 | - | - | 待对接堕神之血 |

---

## 三、后续待办任务清单

1. [ ] **2 人队纯数据驱动收尾 (< 0.01%)**：
   - [x] 对齐 `155925` 全场 11 动，零硬编码纯通用生成器一键跑进 `< 0.01%`（实测总伤 `0.0000%`、单动最大 `0.0002%`）。
   - [ ] 使用纯通用生成器验证 `184651` 压入 `< 0.01%`。
   - [ ] 使用纯通用生成器验证 `184845` 压入 `< 0.01%`。
   - [ ] 使用纯通用生成器收尾 `204943` 压入 `< 0.01%`。
2. [ ] **3 人队纯数据驱动对齐 (< 0.01%)**：
   - [ ] 在 `DataDrivenStageDirector` 中验证 Wave 2 Boss `堕神之血•亚婆离` 的转阶段韧性锁与 `狂兽的胚芽` 吞噬回血逻辑。
   - [ ] 依次跑通 `205144`、`220255`、`221208`、`222204`，确保全部进入 `< 0.01%`。
3. [ ] **清理老代码与统一门禁**：
   - [x] 统一 [test_vm_30126122_alignment.py](file:///d:/Downloads/StarRail-Combat-Simulator/simulator/vm/test_vm_30126122_alignment.py) 全部 8 用例门禁为 `data_driven=True` 且 `total_limit=0.0001`, `turn_limit=0.0001`, `ika_turn_limit=0.0001`。
   - [ ] 8 用例全绿后，彻底删除手写的 `simulator/stage_30126122.py` 与相关过渡测试。

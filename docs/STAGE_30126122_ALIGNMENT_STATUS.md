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
- **阿哈额外回合**（`stage_sim_adapter.py`）：首击广播 `TurnBeginEvent`，确保监听器时序一致。

---

## 二、当前对账达标状态 (按 `data_driven=True` + `0.01%` 严格红灯标准)

> **原则**：单元测试统一以真实终态标准 `data_driven=True` 与 `limit=0.0001 (0.01%)` 为准挂红灯，实事求是暴露所有未达标点。

| 用例 ID | 队伍阵容 | 状态 | 当前总伤误差 | 轨迹状态 | 备注 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **204943** | 风堇 + 知更鸟•晴歌 | 🔴 待微调 | 0.4098% | 100% 吻合 | 纯数据驱动已打通，待微调晴歌受击/治疗层数收进 0.01% |
| **155925** | 风堇 + 长夜月 | 🔴 待对齐扩散目标 | 14.35% | 12/12 动 Organic (100%) | 31.57 AV 狮鹫与召唤物 0.0000% 对齐，待微调天马 151.52 AV 扩散目标 |
| **184651** | 风堇 + 长夜月 | 🔴 待跑纯数据驱动 | - | - | 前置机制已就绪 |
| **184845** | 风堇 + 缇宝 | 🔴 待跑纯数据驱动 | - | - | 前置机制已就绪 |
| **205144** | 缇宝 + 风堇 + 知更鸟•晴歌 | 🔴 待测第二波 | - | - | 待对接堕神之血 |
| **220255** | 缇宝 + 风堇 + 知更鸟•晴歌 | 🔴 待测第二波 | - | - | 待对接堕神之血 |
| **221208** | 长夜月 + 风堇 + 知更鸟•晴歌 | 🔴 待测第二波 | - | - | 待对接堕神之血 |
| **222204** | 缇宝 + 长夜月 + 风堇 | 🔴 待测第二波 | - | - | 待对接堕神之血 |

---

## 三、后续待办任务清单

1. [ ] **2 人队纯数据驱动收尾 (< 0.01%)**：
   - [ ] 对齐 `155925` 中 151.52 AV 天马扩散目标选择，使总伤误差缩减至 `< 0.01%`。
   - [ ] 验证 `184651` 在纯数据驱动下压入 `< 0.01%`。
   - [ ] 验证 `184845` 在纯数据驱动下压入 `< 0.01%`。
2. [ ] **3 人队纯数据驱动对齐 (< 0.01%)**：
   - [ ] 在 `DataDrivenStageDirector` 中验证 Wave 2 Boss `堕神之血•亚婆离` 的转阶段韧性锁与 `狂兽的胚芽` 吞噬回血逻辑。
   - [ ] 依次跑通 `205144`、`220255`、`221208`、`222204`，确保全部进入 `< 0.01%`。
3. [ ] **清理老代码与统一门禁**：
   - [ ] 统一 [simulator/vm/test_vm_30126122_alignment.py](file:///Users/yunkaichen/Downloads/starrail/simulator/vm/test_vm_30126122_alignment.py) 门禁为 `data_driven=True` 且 `total_limit=0.0001`, `turn_limit=0.0001`。
   - [ ] 彻底删除手写的 `simulator/stage_30126122.py` 与相关过渡测试。

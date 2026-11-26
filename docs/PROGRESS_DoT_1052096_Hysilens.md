# Weekly Boss Stage 1052096（DoT 队 & 海瑟音反推建档）进展记录

> 本文件更新于 **2026-11-26 19:05**。记录实机日志 [`battle_logs/battle_20261126_060855.jsonl`](file:///D:/Downloads/StarRail-Combat-Simulator/battle_logs/battle_20261126_060855.jsonl)（`4,177` 条事件，普通周本 `stage_id: 1052096`）的四人开局能量（EP）反推结论与好友 **海瑟音（`avatar_id: 1410`）** 精确面板反算进度，以及当前已落地进展与后续 6 项根因清单。

---

## 1. 对局概览与配队站位

- **实机日志**：[`battle_logs/battle_20261126_060855.jsonl`](file:///D:/Downloads/StarRail-Combat-Simulator/battle_logs/battle_20261126_060855.jsonl)（共 `4,177` 行）
- **关卡参数**（第 1 行 `OnBattleBegin`）：`stage_id = 1052096`、`max_waves = 1`、`max_cycles = 0`（普通周本，非混沌回忆 50% 能量起手）
- **敌方配置**：主目标 `uid=100012`，初始伴生小怪 `8012040`（`喜剧学家`，Lv.82，`MaxHP = 122969.04390636622`）
- **我方站位顺序**（由第 3–6 行初始 `ActionDelay` 与第 164–167 行全体增益确认）：
  1. `1217` **藿藿**（E1，`等价交换 21021` S5，`ERR = 1.1943940175697207`）
  2. `1005` **卡芙卡**（E0，`只需等待 23006` S1，`ERR = 1.00`）
  3. `1410` **海瑟音**（好友支援，本轮待入库目标，`ERR = 1.00`）
  4. `1307` **黑天鹅**（E1，`重塑时光之忆 23022` S1，`ERR = 1.00`）

> 注：`1217`、`1005`、`1307` 的基础档案均已存在于 [`data/character_db_export.json`](file:///D:/Downloads/StarRail-Combat-Simulator/data/character_db_export.json) 中，实际对局技能 ID（`1121701/02/03`、`100502/03`、`1130703`）亦与日志事件完全一致。

---

## 2. 4 位角色周本开局能量（EP）精确反推结果

Veritas 日志中 `CurrentSP` 在受击/施放技能单段 Hit 时打印单次增幅，而在**击杀 / 天赋被动 / 终结技全队充能**节点打印角色真实累计总量；结合上述机制与 4 人充能效率，开局初始能量结论如下：

| 角色 (UID) | 能量上限 | 充能效率 (`ERR`) | 推算开局 EP | 占比 | 关键日志依据（行号） |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **藿藿 (`1217`)** | `140` | `1.1943940175697207` | **`108.68882052414119`** | **`77.63%`** | `L100` (`5×ERR`), `L127` (`10×ERR`), `L137/146/155` (`10×ERR`), `L158`（`1005` 开大触发天赋首跳 `+1×ERR` 后累计 `139.74306498095393`，减去 `26×ERR = 31.054244456812738` 即得）；且后续 `L379` (`7×ERR`)、`L499` (`12×ERR`)、`L515` (`43×ERR`) 完全严丝合缝 |
| **卡芙卡 (`1005`)** | `120` | `1.00` | **`[105.0, 120.0]`** | **`87.50%–100.00%`** | `L103` (`+5.0`) + `L131/140/149` (`+10.0`) 共 `+15.0` 后于 `L157` 施放终结技 `-120.0` 并于 `L171` 严格归 `0.0`；因能量上限为 `120` 截断溢出且首次「等价交换」判定在 `L497`（归零之后），该区间内任意取值对后续所有动作与数值完全等价 |
| **海瑟音 (`1410`)** | `110` | `1.00` | **`0.0`** | **`0.00%`** | `L109` (`+5.0`) + `L135/144/153` (`+10.0`) = `+15.0`；`L360` 击杀 `+10` 打印累计 **`25.0`**，`L365` 击杀 `+10` 打印 **`35.0`**，`L378` 吃藿藿大招 `+22.0` (`20%×110`) 打印 `57.0000000204891` |
| **黑天鹅 (`1307`)** | `120` | `1.00` | **`84.19999999762513`** | **`70.17%`** | `L106` (`+5.0`) + `L133/142/151` (`+10.0`) = `+15.0`；`L350` 击杀 `+10` 打印累计 **`109.19999999762513`**，`L355` 击杀 `+10` 打印 **`119.19999999762513`**；大招归零后 `L498` 打印 `21.0`（`+5` 施放大招 + `16` 等价交换）交叉验证无额外被动回能 |

---

## 3. 好友海瑟音 (`1410` / `Avatar_Harscyline_00`) 面板锁定进度

### 3.1 已 100% 锁定的装备、星魂与精确小数

| 项目 | 锁定结果 | 验证依据 |
| :--- | :--- | :--- |
| **星魂** | **E2** | 游戏内星魂截图（`1 你问我心为何悲伤`、`2 你说浪花为何喧响` 已解锁，`3` 未解锁） |
| **光锥** | **「海洋为何而歌」(`23047`) S1** | `L529 -> L532 -> L555` 速度变化 `142.50000000419095 -> 154.74000001559034`（`+12.24 = 102×12%` 藿藿E1）`-> 164.94000002508983`（`+10.20 = 102×10%`，精确匹配 `Equip35.json` `Ability23047` Level 1 `ParamList[5] = 0.1`） |
| **遗器套装 & 主词条** | **4件套 `幽锁深牢的系囚` + 2件套 `沉欢醉饮的海隅`**；物理伤害球 | 游戏内遗器截图 + 面板物理伤害提高 `38.8%` |
| **80级满破白字** | `HP = 2155.608`、`ATK = 1236.564`、`DEF = 948.15`、`SPD = 102.0`、`CR = 5.0%`、`CD = 50.0%` | [`AvatarPromotionConfig.json`](file:///D:/Downloads/StarRail-Combat-Simulator/data/TurnBasedGameData/ExcelOutput/AvatarPromotionConfig.json#L22926-L22960) + [`EquipmentPromotionConfig.json`](file:///D:/Downloads/StarRail-Combat-Simulator/data/TurnBasedGameData/ExcelOutput/EquipmentPromotionConfig.json#L35442-L35464) |
| **小行迹总加成 (`PointS1–S10`)** | `SPD +14`、`ATK +18%`、`EHR +10%` | [`AvatarSkillTreeConfig.json`](file:///D:/Downloads/StarRail-Combat-Simulator/data/TurnBasedGameData/ExcelOutput/AvatarSkillTreeConfig.json#L147886-L148318) |
| **精确速度 (SPD)** | **`142.5`** | `L529` 打印 `142.50000000419095`；开局 `L5` `ActionDelay = 64.62453146465123 = 10000 / 154.74` |
| **精确生命上限 (MaxHP)** | **`2979.7531370446086`** | `L549` 满血治疗上限同步值（面板展示 `2155 + 824`） |
| **精确暴击伤害 (CD)** | **`62.96%` (`0.6296`)** | `L166` 吃开局全队 `+25%` 暴伤后打印 `0.8796000040601939`（对应面板截断显示 `62.9%`） |

### 3.2 精确 ATK 浮点值、技能等级与已入库验证结论

1. **技能等级确认（E2 满配）**：普攻 `6` / 战技 `10` / 终结技 `10` / 天赋 `10`（由 `L560` 战技 `1.40`、`L781` 结界 DoT `0.80×1.16`、`L1303` 普攻 `1.00`、`L1363` 终结技 `2.00×1.8796` 交叉验证唯一确定）。
2. **精确 ATK 面板锁定为 `3988.39287724`**（白字 `1236.564` + 固定攻击 `426.890707` [手套 `352.8` + 4 词条 3 档] + 百分比 `188.016%` [行迹 `18%` + 2+2 套装 `24%` + 攻击鞋 `43.2%` + 攻击绳 `43.2%` + 副词条 `59.616%`]）：
   - 解释 UI 差异：局内面板截断显示 `1236 + 2751 = 3987`，而遗器面板汇总显示 `3988`（`floor(3988.39287724) = 3988`）。
   - 多路实机伤害反算（叠加 藿藿大招 `+40% ATK`、卡芙卡 `L436` 验证的黑天鹅 `SkillTree03` `+62.1792%` 增伤与 `SkillTree02` `-20.8%` 减防 + 海瑟音 `-25%` 减防 + 系囚 4 件 `-18%` 无视防御）：
     - `L560` 战技 `18281.026528208982` → 反推 `ATK_panel = 3988.39287949`
     - `L781` 结界 DoT `15830.74547650502` → 反推 `ATK_panel = 3988.39288227`
     - `L755` 触电 DoT `3252.453061439097` → 反推 `ATK_panel = 3988.39288607`
     - `L767` 裂伤 DoT `3710.3309753597714` → 反推 `ATK_panel = 3988.39288747`
     - `L771` 风化/灼烧 DoT `3871.9679314342793` → 反推 `ATK_panel = 3988.39288740`
     - 5 组独立伤害误差 `< 0.0000003%`（`2.5e-9` 量级）。
3. **剩余面板参数（已写入 [`data/character_db_export.json`](file:///Users/yunkaichen/Downloads/starrail/data/character_db_export.json)）**：
   - `DEF = 1129.15`（`948.15 + 181`）、`CR = 7.5%`、`CD = 62.96%`、`BE = 5.8%`、`EHR = 120.4%`、`RES = 0.0%`、`ERR = 100.0%`、`DMG% = 38.8803015%`（`物理属性伤害提高 +38.8%` 主词条精确值）。

---

## 4. 本次提交已落地进展（2026-11-26 19:05）

1. **角色数据库与加强版角色自动识别**：
   - 海瑟音（`avatar_id: 1410`，E2 + `海洋为何而歌 23047` S1 + 4件 `幽锁深牢的系囚 (ID 116)` + 2件 `沉欢醉饮的海隅 (ID 322)`）已正式写入 [`data/character_db_export.json`](file:///Users/yunkaichen/Downloads/starrail/data/character_db_export.json)。
   - 完成 `AvatarConfigEnhanced.json` 增强版角色版本自动识别与加载（`1217` 藿藿、`1307` 黑天鹅走增强版；`1005` 卡芙卡按实机日志技能 ID 自动走非增强版）。
2. **周本 Boss `8015030`（万色返空主，归寂）与相关通用 VM 算子**：
   - 支持 Phase 1/2/3（`8015040 「住」` / `8015050 「坏」`）及 `BattleEvent_60044` / `20046` / `20051` 机制。
   - 补齐/完善通用 VM 算子：`ShowBattleCardBuffSelection`、`AttachEntityUnselectable`（与 `RemoveEntityFromTeamFormation` 解耦）、`ByIsGenderType`、非 Dummy `BattleEvent` 的 `DynamicValues` 加载、`_notify_global_action_delay_changed` 参数 `(delta_av, delta_av / 10.0)`、`OnListenGlobalActionDelayChanged`、`SetAutoUseEntityUltraSkill`、`AddBehaviorFlagForModifier` / `RemoveBehaviorFlagForModifier`、`SetDynamicValueByBehaviorFlagCount`、`ByIsConvertDamage`、`SPRatio` / `ByCompareSPRatio` 以及对应表现层裁剪节点。
3. **诊断工具增强（`scripts/diff_log_turn.py`）**：
   - 新增 `--init-ep`、`--tech-users`、`--dump-mods` 参数，并在运行时输出 `[BE_EP]` 与 `[AUTO_U]` 终结技充能/自动插队诊断行。

---

## 5. 当前已验证基线（Stage 1052096）

- **标准复现命令**：
  ```bash
  python3 scripts/diff_log_turn.py battle_logs/battle_20261126_060855.jsonl \
    --init-ep 1217:108.68882052414119,1005:120.0,1410:0.0,1307:84.19999999762513 \
    --tech-users 1307 \
    --av 234.31 --av-window 15.0 --av-budget 305.0 --summary
  ```
- **核心对账指标**：
  - `turn = 23/23`，`ult = 13/13`，`sp = 0`，`mem = 0.0`，`pres = 0`，`forced = 0`，`enemy_hit_mismatches = []`
  - `total_err = 5.705869%`，`max_turn_err = 44.238249%`
  - `ult_e = 43.03`（共 4 笔终结技补能：`av=174.31 卡芙卡 +4.00 (post)`、`av=224.52 卡芙卡 +21.00 (post)`、`av=289.58 藿藿 +5.03`、`av=294.94 海瑟音 +13.00 (post)`）

---

## 6. 下次会话继续清单（已数学定位的 6 项根因）

1. **Bug 1（`av=234.31` & `287.05` `卡芙卡:Skill` `max_turn_err = 44.238%`）**：
   - 位置：`simulator/vm/reconcile/metadata_post.py` (`resolve_player_and_servant_targets`)
   - 根因：玩家扩散技能（`Blast`，如 `primary_dmg_hits == 5`）未提取主目标。修复方案为复用忆灵扩散主目标推断逻辑（唯一 `p_sp_euids` -> `[100057]`、唯一 `p_dmg_confirmed`、或最大伤害比值 `> 1.4x`）。
2. **Bug 2（`1005`/`1217`/`1307` `0.0066% .. 0.0260%` 全队系统性面板微偏）**：
   - 位置：`simulator/db/tables.py` (`_init_official_tables`)
   - 根因：遍历 `AvatarSkillTreeConfig.json` `PointType == 1` 小行迹时未过滤 `int(row.get("EnhancedID") or 0) != 0`，导致加强版角色行迹加成翻倍并使 `character_db.py` 的 `_reconstruct_exact_stats()` 校验失败回退截断值。修复方案为跳过 `EnhancedID != 0` 行。
3. **Bug 3（`海瑟音 err = 0.006597%` 精确六位数学偏差）**：
   - 位置：`simulator/db/character_db.py` (`_compile_from_export`)
   - 根因：导出的 `"key": "unknown"` 副词条（效果命中/效果抵抗）记录了虚假滚档位 `low=0, mid=0, high=count`，容差校验失败后回退到截断值 `raw_val`。黑天鹅精确 5 星命中档位总和为 `0.43632`（vs `0.433`，`ΔEHR = +0.00032` -> 全队增伤 `+0.000192` -> `0.000192 / 2.910595 = 0.006597%`）。修复方案为在导出档位不匹配时，按总次数 `cnt` 反搜 `stp in range(0, 2*cnt+1)` 匹配截断后等于 `raw_val` 的精确档位。
4. **Bug 4（`av=118.90` & `174.31` `卡芙卡` 漏 `-20.0` 能量）**：
   - 位置：`simulator/lifecycle.py` (`defer_or_dispatch_listen_die`、`flush_listen_die`、`_finalize_limbo_entity`) 及 `runtime.py`、`stage_ops.py`
   - 根因：`OnListenCharacterDie` 派发时缺失 `param_entity2_id=killer_id`（导致 `MAvatar_Kafka_Tree02` 的 `ByIsTargetValid(ParamEntity2)` 恒为假），且 `_finalize_limbo_entity` 先调用 `destroy_all_for_entity` 才派发 `OnListenCharacterDie`（清掉了 `STAT_DOT_Electric`）。修复方案为全链路透传 `killer_id` 并调整至清理前派发 `OnListenCharacterDie`。
5. **Bug 5（`等价交换 21021` `av=119.05` 选错队友 & `av=229.57` 海瑟音漏 `+16.0`）**：
   - 位置：`simulator/vm/executor.py`、`simulator/vm/reconcile/metadata_trackers.py`、`metadata_post.py`、`auto_rng.py`
   - 根因：玩家角色施放 `Retarget(ByRandom=True)` 指向 `AllTeammate` 时未接入 `ally_retarget_provider`。需从日志回合初队友回能序列（`60.47:1307, 118.90:1307, 119.05:1410, 174.31:1410, 229.57:1410, 234.31:1307, 289.58:1307`）自动提取 `meta.ally_retarget_picks` 并接入执行器。
6. **Bug 6（`av=208.33` 阿哈 `BattleEvent_70001` `Skill41_Phase2` 未执行 & `BattleEvent_20046` 误普攻 `311.58`）**：
   - **6a**：`simulator/vm/ops/predicates.py` `ByHasSkillTag` 对 `SkillType == "Elation"` 误放行 `(8, 1)`，导致 `Elation_AllBattleEvent` 误命中 `BattleEvent_70001`，`Skill03_Entry` 走入 `Skill04 -> Skill42` 而跳过 `FailedTaskList`（0 欢愉角色时应执行 `SkillIndex=2` `Skill41_Phase1 -> Phase2`：10 次 50% 我方 `+2 SP` / 50% 敌方弹射；需先核查贪饕 `Avatar_BattleEvent20043_Config.json` 后收紧 `ByHasSkillTag`）。（Bug 4 + 5 + 6a 合计精确消去全部 4 笔 `ult_e=43.03`。）
   - **6b**：`simulator/vm/ops/turn_ops.py` 创建非 Dummy `BattleEvent`（如 `20046` `BossUltra`）时硬编码 `is_enemy=False` 忽略 `Team="TeamDark"`，致使其 `OnPhase1`（`Skill08_Phase01`）向 Boss `「坏」_1` 打出 `311.58` 误伤；同时需完善 `MCommon_LockActionDelayChange` 拦截 `SetActionDelay`（防止 `700004` 在解锁前推进 `BossUltra`）。
   - **6c**：提取 `av=208.33` `Skill41_Phase2` 10 次弹射阵营与目标序列（`1410, 1217, Dark, 1005, Dark, Dark, Dark, 1217, Dark, 1217`）到 `RandomConfig` + `Bounce_SelectTarget` 先知，并核实实机 `Skill41_Phase2` 期间双方血量未下降的原因。
7. **诊断工具与验收收口（`AGENTS.md` 五步法）**：
   - 为 `scripts/diff_log_turn.py` 增加 `--energy`（`[EN   ]`）能量事件输出；
   - 通过全量 `< 0.0001%` 归零后新增 `simulator/vm/test_vm_1052096_alignment.py`；
   - 收口统一跑 `python3 -m pytest -m "slow or not slow" -v` 与 `python3 -m simulator.vm.audit_vm_coverage`。
8. **当前 WIP 已知 2 项回归待下次优先修复**（`python3 -m pytest -v`：`84 passed, 2 failed, 12 deselected`）：
   - `simulator/vm/test_vm_420564_84_alignment.py::TestVMStage420564To84Alignment::test_vm_420584_20261124_090259`（`turn=11/21`）：`simulator/core.py` `_notify_global_action_delay_changed` 触发了 `MMonster_W2_Cocolia_00_IF_SoftFrenzyController`（`OnListenGlobalActionDelayChanged`），在 `av=43.64/93.96/100.38` 提前叠加 `MMonster_W2_Cocolia_00_IF_Frenzy`（每层 `+10%` 易伤）；需对照 `SoftFrenzyController` 与 `BattleEvent_60044` 核实 `ChangeValue`/`ChangeValue2` 的单位与阈值。
   - `simulator/vm/test_vm_30510021_alignment.py::TestVMStage30510021Alignment::test_vm_log_20261025_131019_alignment`（`turn=24/25`）：`simulator/golden/replay.py` `_on_sub_action_end` 移除了 `turn_owner` 匹配兜底分支，导致 `风堇` 终结技未能在 `av=278.50` 处插入 `堕神之血•亚婆离` 多动子行动间隙。

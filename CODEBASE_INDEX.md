# 星穹铁道伤害计算与战斗模拟器代码索引与架构速查表 (CODEBASE INDEX)

> 📘 **新手开发指南与 SOP 规范**：全套公式化开发流程与红线禁令，请查阅 [DEVELOPER_GUIDE.md](file:///Users/yunkaichen/Downloads/starrail/DEVELOPER_GUIDE.md)。  
> 本文档用于在研发、重构与排障时**秒级精确定位**目标代码、数据与测试用例，杜绝盲目搜索。

---

## 一、 核心架构调用链路与分层图谱

```mermaid
flowchart TD
    subgraph 数据与配置层 ["1. 数据与配置层 (Data & Config)"]
        D1["data/character_db_export.json (账号角色实机面板与遗器词条)"]
        D2["data/nanoka/raw/4.6/zh/character/{id}.json (官方原始技能倍率param_list)"]
        D3["simulate_battle.py -> STAGE_CONFIG (关卡波次/首领/环境机制配置)"]
    end

    subgraph 实体与底层驱动 ["2. 实体构建与战斗引擎 (Core & Port)"]
        C1["simulator/db/character_db.py -> to_combat_entity()"]
        C2["simulator/core.py -> TurnSimulator (微内核: 时间轴/行动轮次/战技点)"]
        C3["simulator/combat_port.py -> CombatPort / BuffSpec (安全契约与关系判定)"]
        C4["simulator/status.py -> StatusManager / StatusTag (属性管线与语义标签)"]
        C5["simulator/events.py -> EventBus / BattleEvent (事实事件总线)"]
    end

    subgraph 业务插件层 ["3. 业务逻辑插件层 (Kits, LC, Relics, Stage)"]
        K1["simulator/kits/characters/{char}.py -> KitHandler (技能/天赋/秘技)"]
        K2["simulator/light_cones/handlers/{lc}.py -> LightConeHandler (光锥被动)"]
        K3["simulator/relics/handlers/{relic}.py -> RelicSetHandler (遗器套装)"]
        K4["simulator/stage_mechanics.py -> StageMechanicPlugin / Registry (关卡环境插件)"]
    end

    subgraph 结算与透析层 ["4. 伤害结算与状态透析 (Output & Verification)"]
        R1["simulator/damage.py -> DamageCalculator (韧性/抗性/易伤/双暴)"]
        R2["simulate_battle.py -> render_inspect_panel() (实机状态透析面板)"]
        R3["simulator/test_changyeyue_memosprite.py (核心机制单元测试)"]
    end

    D1 & D2 --> C1
    C1 --> C2
    C2 <--> C3
    C2 <--> C5
    C3 <--> C4
    C3 <--> K1 & K2 & K3
    C2 <--> K4
    C2 --> R1 & R2 & R3
```

---

## 二、 场景化极速定位速查表 (Task-to-File Matrix)

| 研发/调试目标 | 精确文件路径 | 核心类 / 函数 / 字段 | 关键注意事项 |
| :--- | :--- | :--- | :--- |
| **修改角色技能 / 天赋 / 秘技** | `simulator/kits/characters/<char_pinyin>.py` | `KitHandler.execute()`<br>`KitHandler.definition()`<br>`KitHandler.on_battle_start()` | **严禁硬编码！** 动态加成必须通过 `self.port.stat()` 采样本体属性，乘以 `self.skill_param()` 动态倍率；秘技必须声明 `priority`。 |
| **修改伴生忆灵机制** | `simulator/kits/characters/changyeyue.py` | `summon_spirit()`<br>`get_memosprite_snapshot()`<br>`calc_skill_shared_crit_dmg()` | 必须使用 `self.spirit_name` 引用；忆灵专属加成必须打上 `StatusTag.MEMOSPRITE_ONLY` 与 `EXCLUDE_FROM_STAT_TRANSFERS` 标签，防自循环。 |
| **修改缇宝结界 / 天赋追击** | `simulator/kits/characters/tibao.py` | `TibaoKit.on_battle_start()`<br>`apply_divine_revelation()` | 【好忙好忙的缇宝】严禁下发给忆灵；E4【心意相契的安宁】在结界生效时提供 18% 无视防御。 |
| **修改专属光锥机制 (如冥花)** | `simulator/light_cones/handlers/make_farewells_more_beautiful.py` | `trigger_flower_buff()`<br>`on_action_after()` | 自身或忆灵扣血时插入 `LC_Farewells_FlowerBuff`，提供 30% 无视防御。 |
| **修改知更鸟晴歌 / 气氛值** | `simulator/kits/characters/robin_sunnysong.py` | `RobinSunnySongKit.gain_vibes()`<br>`RobinSunnySongKit.on_event()` | 监听标准 `HealAppliedEvent` 与 `ActionExecuteEvent`；进战气氛值 = 风堇(1) + 晴歌(6) = 7 点；忆灵行动再 +1 点。 |
| **修改遗器套装效果 (如女武神)** | `simulator/relics/handlers/valkyrie_of_sun_and_thunder.py` | `apply_panel_passives()`<br>`on_battle_start()` | 挂载【烈阳惊雷的女武神 / 甘霖】全队暴伤 +15%。 |
| **修改关卡波次与环境机制** | `simulator/stage_mechanics.py`<br>`simulate_battle.py` | `StageMechanicRegistry`<br>`STAGE_CONFIG["mechanics"]` | 关卡全局环境机制通过 `StageMechanicPlugin` 插件驱动，支持中英文换名即插即用（如 `["血噬"]`, `["流血环境"]`）。 |
| **修改实时状态透析面板输出** | `simulate_battle.py` | `render_inspect_panel()` | 格式化打印角色与伴生忆灵面板，遵循星铁实机面板标准，直接读取 `msnap` 快照。 |
| **查阅官方 4.6 技能参数与倍率** | `data/nanoka/raw/4.6/zh/character/{id}.json` | `skills -> {skill_id} -> level -> param_list` | 官方原始基准源文件（长夜月: 1413, 晴歌: 1512, 缇宝: 1403, 风堇: 1410）。 |
| **查询当前回合归属与可行动Action** | `query_turn_action.py` | `TurnSimulator.print_turn_action_info()`<br>`TurnSimulator.get_turn_action_info()` | 机械化调用战斗模拟引擎底层，直接输出当前是谁的回合与可行动Action。 |
| **运行与核对核心单元测试** | `simulator/test_changyeyue_memosprite.py`<br>`simulator/test_tibao_verification.py` | `TestChangyeyueMemospriteMechanics`<br>`TestTibaoFullStatusVerification` | 必须维持 10/10 100% 通过率。 |

---

## 三、 常用角色技能套件文件映射表 (Character Kit Registry)

角色注册中心位于：[`simulator/kits/registry.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/registry.py)

| 角色名 (中文) | 英文/别名 | Avatar ID | 源码文件路径 | 核心机制类名 |
| :--- | :--- | :--- | :--- | :--- |
| **长夜月** | Evernight | **1413** | [`simulator/kits/characters/changyeyue.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/changyeyue.py) | `ChangyeyueKit` / `ChangyeMemospriteKit` |
| **缇宝** | Tribbie | **1403** | [`simulator/kits/characters/tibao.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/tibao.py) | `TibaoKit` |
| **知更鸟•晴歌** | Robin SunnySong | **1512** | [`simulator/kits/characters/robin_sunnysong.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/robin_sunnysong.py) | `RobinSunnySongKit` |
| **风堇** | Fengjin | **1410** | [`simulator/kits/characters/fengjin.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/fengjin.py) | `FengjinKit` |
| **知更鸟 (原版)** | Robin | **1309** | [`simulator/kits/characters/robin.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/robin.py) | `RobinKit` |
| **星期日** | Sunday | **1313** | [`simulator/kits/characters/sunday.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/sunday.py) | `SundayKit` |
| **花火** | Sparkle | **1306** | [`simulator/kits/characters/sparkle.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/sparkle.py) | `SparkleKit` |
| **阮•梅** | Ruan Mei | **1303** | [`simulator/kits/characters/ruan_mei.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/ruan_mei.py) | `RuanMeiKit` |
| **黄泉** | Acheron | **1308** | [`simulator/kits/characters/acheron.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/acheron.py) | `AcheronKit` |
| **流萤** | Firefly | **1310** | [`simulator/kits/characters/firefly.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/firefly.py) | `FireflyKit` |
| **砂金** | Aventurine | **1304** | [`simulator/kits/characters/aventurine.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/aventurine.py) | `AventurineKit` |
| **符玄** | Fu Xuan | **1208** | [`simulator/kits/characters/fuxuan.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/fuxuan.py) | `FuXuanKit` |

---

## 四、 核心光锥与遗器文件映射表

### 1. 光锥 (Light Cones)
注册中心：[`simulator/light_cones/catalog.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/catalog.py)
* **《让告别，更美一些》** (长夜月专属 ID 23040): [`simulator/light_cones/handlers/make_farewells_more_beautiful.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/handlers/make_farewells_more_beautiful.py)
* **《若时间是一朵花》** (知更鸟专属 ID 23024): [`simulator/light_cones/handlers/if_time_were_a_flower.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/handlers/if_time_were_a_flower.py)
* **《愿彩虹留于苍穹》** (缇宝专属 ID 23035): [`simulator/light_cones/handlers/may_rainbows_remain_in_the_sky.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/handlers/may_rainbows_remain_in_the_sky.py)
* **《记忆永不褪色》**: [`simulator/light_cones/handlers/memory_never_fades.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/handlers/memory_never_fades.py)

### 2. 遗器 (Relic Sets)
注册中心：[`simulator/relics/catalog.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/relics/catalog.py)
* **烈阳与惊雷的女武神** (ID 124): [`simulator/relics/handlers/valkyrie_of_sun_and_thunder.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/relics/handlers/valkyrie_of_sun_and_thunder.py)
* **谧宁拾骨地** (ID 319): [`simulator/relics/handlers/bone_collecting_ground.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/relics/handlers/bone_collecting_ground.py)
* **沉没的母树** (ID 320): [`simulator/relics/handlers/sunken_tree.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/relics/handlers/sunken_tree.py)
* **哀歌覆国的诗人** (ID 128): [`simulator/relics/handlers/poet_of_mourning.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/relics/handlers/poet_of_mourning.py)

---

## 五、 核心设计守则 (Strict Zero-Hardcoding Mandates)

1. **绝对禁止硬编码任何技能/光锥/遗器加成数值**：
   - 必须通过 `self.skill_param()` 动态读取。
2. **状态插件化挂载原则**：
   - 所有的增益（Buff）、负面（Debuff）以及机制标记（Other），必须通过 `self.port.upsert_status(BuffSpec(...))` 插入。
3. **实体从属与标签隔离原则**：
   - 从属判定严禁基于固定名字，必须使用 `self.port.is_own_memosprite(self.owner_id, entity_id)`；
   - 属性防自循环必须通过 `StatusTag.EXCLUDE_FROM_STAT_TRANSFERS` 与 `StatusTag.MEMOSPRITE_ONLY`。

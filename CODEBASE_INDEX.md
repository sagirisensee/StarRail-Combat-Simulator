# 星穹铁道伤害计算与战斗模拟器代码索引与架构速查表 (CODEBASE INDEX)

> 📘 **新手开发指南与 SOP 规范**：全套公式化开发流程、扩展钩子总表与红线禁令，请查阅 [DEVELOPER_GUIDE.md](file:///Users/yunkaichen/Downloads/starrail/DEVELOPER_GUIDE.md)。  
> 本文档用于在研发、重构与排障时**秒级精确定位**目标代码、脚手架模板、数据与测试用例。

---

## 一、 核心架构调用链路与分层图谱

```mermaid
flowchart TD
    subgraph 数据与配置层 ["1. 数据与配置层 (Data & Config)"]
        D1["data/character_db_export.json (账号角色实机面板与遗器词条)"]
        D2["data/nanoka/normalized/4.6/ (官方归一化角色/光锥/遗器参数)"]
        D3["simulate_battle.py -> STAGE_CONFIG (关卡波次/首领/环境机制配置)"]
    end

    subgraph 实体与底层驱动 ["2. 实体构建与战斗微内核 (Core & Port)"]
        C1["simulator/db/character_db.py -> to_combat_entity()"]
        C2["simulator/core.py -> TurnSimulator (微内核: 时间轴/行动轮次/战技点)"]
        C3["simulator/combat_port.py -> CombatPort / BuffSpec (安全窄接口契约)"]
        C4["simulator/status.py -> StatusManager / StatusTag (属性管线与语义标签)"]
        C5["simulator/events.py -> EventBus / BattleEvent (不可变事实事件总线)"]
        C6["simulator/effects.py -> EffectResolver (事务队列与多态伤害分摊结算)"]
    end

    subgraph 业务插件层 ["3. 业务逻辑插件层 (Auto-Discovered Plugins)"]
        K1["simulator/kits/characters/{char}.py -> @register_kit / KitHandler"]
        K2["simulator/light_cones/handlers/{lc}.py -> @register_light_cone / LightConeHandler"]
        K3["simulator/relics/handlers/{relic}.py -> @register_relic_set / RelicSetHandler"]
        K4["simulator/stage_mechanics.py -> @register_stage_mechanic / StageMechanicPlugin"]
    end

    subgraph 结算与透析层 ["4. 伤害结算与状态透析 (Output & Verification)"]
        R1["simulator/damage.py -> DamageCalculator (8大乘区: 含攻击者无视防御+目标减防)"]
        R2["simulate_battle.py -> render_inspect_panel() (实机状态透析面板)"]
        R3["simulator/test_*.py (核心机制与微内核拓展性单元测试)"]
    end

    D1 & D2 --> C1
    C1 --> C2
    C2 <--> C3 & C5 & C6
    C3 <--> C4
    C3 <--> K1 & K2 & K3
    C2 <--> K4
    C6 --> R1
    C2 --> R2 & R3
```

---

## 二、 场景化极速定位速查表 (Task-to-File Matrix)

| 研发/调试目标 | 精确文件路径 | 核心类 / 装饰器 / 钩子 | 关键注意事项 |
| :--- | :--- | :--- | :--- |
| **新建角色 / 伴生忆灵套件** | [`simulator/kits/characters/_template.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/_template.py) | `@register_kit`<br>`KitHandler.definition()`<br>`KitHandler.execute()` | 复制 `_template.py` 并加上 `@register_kit` 即可自动扫描注册，严禁访问 `port.sim` 或 `port._get_entity`。 |
| **新建专属光锥处理器** | [`simulator/light_cones/handlers/_template.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/handlers/_template.py) | `@register_light_cone`<br>`LightConeHandler.scale()`<br>`LightConeHandler.on_event()` | 复制 `_template.py` 并加上 `@register_light_cone`，通过监听 `HPLostEvent` / `SpiritDespawnEvent` 等事件解耦触发。 |
| **新建遗器套装处理器** | [`simulator/relics/handlers/_template.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/relics/handlers/_template.py) | `@register_relic_set`<br>`RelicSetHandler.on_battle_start()` | 复制 `_template.py` 并加上 `@register_relic_set`，自动扫描注册。 |
| **修改伴生忆灵机制 (长夜月)** | [`simulator/kits/characters/changyeyue.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/changyeyue.py) | `summon_spirit()`<br>`get_memosprite_snapshot()`<br>`calc_skill_shared_crit_dmg()` | 忆灵专属加成必须打上 `StatusTag.MEMOSPRITE_ONLY` 与 `EXCLUDE_FROM_STAT_TRANSFERS` 标签，防自循环。 |
| **修改伤害分摊/减免 (符玄)** | [`simulator/kits/characters/fuxuan.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/fuxuan.py) | `FuXuanKit.intercept_incoming_damage()`<br>`FuXuanKit.on_hp_lost()` | 通过 `KitHandler.intercept_incoming_damage` 多态协议拦截分摊伤害，`effects.py` 零角色名硬编码。 |
| **修改缇宝结界 / 天赋追击** | [`simulator/kits/characters/tibao.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/tibao.py) | `TibaoKit.on_battle_start()`<br>`apply_divine_revelation()` | 【好忙好忙的缇宝】打上 `StatusTag.CHARACTER_ONLY` 标签，严禁下发或投影给忆灵。 |
| **修改专属光锥机制 (如冥花)** | [`simulator/light_cones/handlers/make_farewells_more_beautiful.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/handlers/make_farewells_more_beautiful.py) | `trigger_flower_buff()`<br>`on_event(HPLostEvent)` | 监听标准 `HPLostEvent` 与 `SpiritDespawnEvent`，提供 30%~50% 无视防御 (`StatType.DEF_SHRED`)。 |
| **修改知更鸟晴歌 / 气氛值** | [`simulator/kits/characters/robin_sunnysong.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/robin_sunnysong.py) | `RobinSunnySongKit.gain_vibes()`<br>`RobinSunnySongKit.on_event()` | 监听标准 `HealAppliedEvent` 与 `ActionExecuteEvent`。 |
| **修改关卡波次与环境机制** | [`simulator/stage_mechanics.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/stage_mechanics.py)<br>[`simulate_battle.py`](file:///Users/yunkaichen/Downloads/starrail/simulate_battle.py) | `@register_stage_mechanic`<br>`StageMechanicRegistry` | 关卡全局环境机制通过 `StageMechanicPlugin` 插件驱动，支持中英文换名即插即用。 |
| **运行全套单元测试与架构验证** | [`simulator/test_changyeyue_memosprite.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/test_changyeyue_memosprite.py)<br>[`simulator/test_tibao_verification.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/test_tibao_verification.py)<br>[`simulator/test_changyeyue_team_synergy.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/test_changyeyue_team_synergy.py)<br>[`simulator/test_framework_extensibility.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/test_framework_extensibility.py) | `python3 -m unittest discover -s simulator -t . -p "test_*.py" -v` | 必须维持全量测试 100% 通过率。 |

---

## 三、 常用角色技能套件文件映射表 (Character Kit Registry)

角色注册中心位于：[`simulator/kits/registry.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/registry.py)（支持 `@register_kit` 自动扫描发现）

| 角色名 (中文) | 英文/别名 | Avatar ID | 源码文件路径 | 核心机制类名 |
| :--- | :--- | :---: | :--- | :--- |
| **长夜月** | Evernight | **1413** | [`simulator/kits/characters/changyeyue.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/changyeyue.py) | `ChangyeyueKit` / `ChangyeMemospriteKit` |
| **缇宝** | Tribbie | **1403** | [`simulator/kits/characters/tibao.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/tibao.py) | `TibaoKit` |
| **知更鸟•晴歌** | Robin SunnySong | **1512** | [`simulator/kits/characters/robin_sunnysong.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/robin_sunnysong.py) | `RobinSunnySongKit` |
| **风堇** | Fengjin / Hyacine | **1409** | [`simulator/kits/characters/fengjin.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/fengjin.py) | `FengjinKit` |
| **知更鸟 (原版)** | Robin | **1309** | [`simulator/kits/characters/robin.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/robin.py) | `RobinKit` |
| **星期日** | Sunday | **1313** | [`simulator/kits/characters/sunday.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/sunday.py) | `SundayKit` |
| **花火** | Sparkle | **1306** | [`simulator/kits/characters/sparkle.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/sparkle.py) | `SparkleKit` |
| **阮•梅** | Ruan Mei | **1303** | [`simulator/kits/characters/ruan_mei.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/ruan_mei.py) | `RuanMeiKit` |
| **黄泉** | Acheron | **1308** | [`simulator/kits/characters/acheron.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/acheron.py) | `AcheronKit` |
| **流萤** | Firefly | **1310** | [`simulator/kits/characters/firefly.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/firefly.py) | `FireflyKit` |
| **砂金** | Aventurine | **1304** | [`simulator/kits/characters/aventurine.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/aventurine.py) | `AventurineKit` |
| **符玄** | Fu Xuan | **1208** | [`simulator/kits/characters/fuxuan.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/fuxuan.py) | `FuXuanKit` |

# 崩坏：星穹铁道 回合制战斗与排轴模拟器 (Star Rail Combat Simulator)

一个基于**微内核 + 协议隔离 + 装饰器即插即用插件架构**的《崩坏：星穹铁道》回合制战斗模拟器与全角色高精属性数据库引擎。

> 📘 **研发人员与 AI 开发者必读**：
> - **研发规范与新人指引**：[《星穹铁道战斗模拟器·研发工程规范与新人开发指引 (DEVELOPER_GUIDE.md)》](file:///Users/yunkaichen/Downloads/starrail/DEVELOPER_GUIDE.md) —— 包含 5 大红线戒律、扩展钩子总表与公式化 SOP 骨架。
> - **代码索引与架构速查**：[《代码索引与架构速查表 (CODEBASE_INDEX.md)》](file:///Users/yunkaichen/Downloads/starrail/CODEBASE_INDEX.md) —— 秒级定位角色 Kit、光锥、遗器与测试。
> - **新人即插即用开发模板**：
>   - 角色/忆灵模板：[`simulator/kits/characters/_template.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/kits/characters/_template.py)
>   - 光锥被动模板：[`simulator/light_cones/handlers/_template.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/light_cones/handlers/_template.py)
>   - 遗器套装模板：[`simulator/relics/handlers/_template.py`](file:///Users/yunkaichen/Downloads/starrail/simulator/relics/handlers/_template.py)

---

## 🌟 核心架构设计：微内核 + 四层解耦

本项目严格贯彻**「实机面板只用于验算，实战模拟全走高精浮点」**与**「引擎微内核零硬编码，业务逻辑全插件化」**的架构规范：

1. **数据与资产层 (`data/`, `simulator/assets/`, `simulator/scaling/`, `simulator/db/`)**：
   - 收录 99+ 位角色 80 级白值、170+ 光锥、62+ 遗器套装与 Nanoka 4.6 官方多等级 `param_list` 原始倍率；
   - `StatCalculator` 与 `CharacterDB` 完整保留浮点精度，通过 `db.to_combat_entity("角色名")` 一键装配角色套件、光锥与遗器。
2. **微内核调度与事件总线层 (`simulator/core.py`, `simulator/events.py`, `simulator/effects.py`, `simulator/status.py`, `simulator/damage.py`)**：
   - **10,000 行动距离跑道**：按 $AV = 10000 / \text{Speed}$ 推进，支持瞬时拉条、推条、插队终结技与伴生忆灵立即行动；
   - **纯事实事件总线 (`EventBus`)**：所有攻击、治疗 (`HealAppliedEvent`)、护盾 (`ShieldAppliedEvent`)、扣血 (`HPLostEvent`)、召唤物入场/退场 (`SpiritSummonedEvent` / `SpiritDespawnEvent`) 均以不可变事件广播，彻底解耦角色与光锥/遗器联动；
   - **语义化状态管线 (`StatusManager` & `StatusTag`)**：支持 `TARGET_TURN_START` / `TARGET_TURN_END` / `CASTER_TURN_END` 三类时钟，通过 `StatusTag` (`MEMOSPRITE_ONLY`, `CHARACTER_ONLY`, `EXCLUDE_FROM_STAT_TRANSFERS`) 实现零硬编码黑名单的动态属性汇算；
   - **8 大乘区纯函数伤害管线 (`DamageCalculator`)**：完整汇总攻击/生命/防御基数、双暴、增伤、敌方减防 + 攻击者无视防御 (`DEF_SHRED`)、抗穿、易伤与破韧减伤。
3. **窄接口契约层 (`simulator/combat_port.py`, `simulator/actions.py`)**：
   - 所有插件仅通过 `CombatPort` 标准窄接口查询阵营/从属关系、采样实时属性（支持按标签过滤）、挂载 `BuffSpec` 或发起战斗动作，**严禁跨层访问 `sim` 内部私有结构**。
4. **即插即用业务插件层 (`simulator/kits/`, `simulator/light_cones/`, `simulator/relics/`, `simulator/stage_mechanics.py`)**：
   - 支持 `@register_kit`、`@register_light_cone`、`@register_relic_set`、`@register_stage_mechanic` 装饰器自注册与目录自动扫描发现（Auto-Discovery）；
   - 新人开发新角色、新光锥或新遺器只需复制 `_template.py` 并在新文件中添加装饰器，**无需改动任何中心注册表或核心引擎代码**。

---

## 🚀 快速启动与测试

本项目基于 Python 3.9+ 标准库构建，**零第三方运行时依赖**：

```bash
# 1. 运行全套单元测试与架构拓展性验证 (推荐标准命令)
python3 -m unittest discover -s simulator -t . -p "test_*.py" -v

# 2. 启动实战交互打牌 / 自动排轴模拟
python3 simulate_battle.py -i

# 3. 机械化查询指定步数的回合归属、可选 Action 与实时面板透析
python3 query_turn_action.py --step 0 --status 长夜
```

---

## 📁 目录结构

```
starrail/
├── simulator/                        # 核心模拟器源码包
│   ├── __init__.py                   # 顶层公共契约与装饰器导出
│   ├── core.py                       # 微内核调度器与实体定义 (TurnSimulator, SimulatorCombatPort, Entity)
│   ├── combat_port.py                # 插件安全窄接口契约 (CombatPort, BuffSpec)
│   ├── actions.py                    # 动作枚举、目标模式与技能声明 (ActionKind, AbilityDefinition)
│   ├── damage.py                     # 8 大乘区纯函数伤害引擎 (DamageCalculator, DamageBreakdown)
│   ├── effects.py                    # 效果队列与多态事务结算器 (EffectResolver)
│   ├── events.py                     # 不可变领域事实事件总线 (EventBus, BattleEvent 派生类)
│   ├── sp.py                         # 战技点池管理 (SkillPointManager)
│   ├── status.py                     # 状态时钟与语义标签属性管线 (StatusManager, StatusTag)
│   ├── stage_mechanics.py            # 关卡环境机制插件与注册中心 (StageMechanicPlugin)
│   ├── assets/                       # Nanoka 4.6 官方归一化数据仓库 (AssetRepository)
│   ├── scaling/                      # 技能等级与星魂倍率动态解析器 (SkillScaling)
│   ├── db/                           # 玩家存档解析与高精面板计算引擎 (CharacterDB, StatCalculator)
│   ├── kits/                         # 角色与伴生忆灵技能套件插件
│   │   ├── base.py                   # KitHandler 抽象基类与全生命周期扩展钩子
│   │   ├── registry.py               # @register_kit 装饰器与自动扫描发现注册中心
│   │   └── characters/               # 60+ 位角色实现与 _template.py 标准脚手架
│   ├── light_cones/                  # 光锥独立运行时插件
│   │   ├── base.py                   # LightConeHandler 抽象基类
│   │   ├── registry.py               # @register_light_cone 装饰器与注册中心
│   │   └── handlers/                 # 专属光锥实现与 _template.py 标准脚手架
│   ├── relics/                       # 遗器套装独立运行时插件
│   │   ├── base.py                   # RelicSetHandler 抽象基类
│   │   ├── registry.py               # @register_relic_set 装饰器与注册中心
│   │   └── handlers/                 # 遗器套装实现与 _template.py 标准脚手架
│   ├── test_changyeyue_memosprite.py # 长夜月与伴生忆灵核心机制对账测试
│   ├── test_tibao_verification.py    # 缇宝与风堇全量状态实机对账测试
│   ├── test_changyeyue_team_synergy.py # 四人完整配队排轴与协同测试
│   └── test_framework_extensibility.py # 微内核零硬编码与插件拓展性验证测试
├── data/                             # 角色导出面板与 Nanoka 4.6 原始/归一化资产库
├── simulate_battle.py                # 交互式/自动战斗与实时状态透析 CLI 主入口
├── query_turn_action.py              # 回合状态与可行动 Action 机械查询工具
├── DEVELOPER_GUIDE.md                # 研发工程规范与新人开发 SOP 手册
├── CODEBASE_INDEX.md                 # 代码索引与架构速查表
└── README.md                         # 项目总体介绍
```

# 崩坏：星穹铁道 回合制战斗与排轴模拟器 (Star Rail Combat Simulator)

一个高度解耦、完全独立、高精度的《崩坏：星穹铁道》回合制战斗模拟器与全角色属性数据库引擎。

> 📘 **研发人员与 AI 开发者必读**：
> - **规范手册**：[《星穹铁道战斗模拟器·研发工程规范与新人开发指引 (DEVELOPER_GUIDE.md)》](file:///Users/yunkaichen/Downloads/starrail/DEVELOPER_GUIDE.md) —— 包含 5 大红线戒律与公式化 SOP 骨架。
> - **速查索引**：[《代码索引与架构速查表 (CODEBASE_INDEX.md)》](file:///Users/yunkaichen/Downloads/starrail/CODEBASE_INDEX.md) —— 秒级定位角色 Kit、光锥与测试。

---

## 🌟 核心设计哲学：双层架构隔离

本项目严格贯彻**「实机面板只用于验算，实战模拟全走高精浮点」**的架构规范：

```
                    ┌─────────────────────────────────────────┐
                    │      全量数据源 (freesr / official json) │
                    └───────────────────┬─────────────────────┘
                                        │ 纯函数解析
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │    CharacterDB / StatCalculator 引擎    │
                    │   (完整保留浮点精度，不产生任何提前截断)  │
                    └───────────┬─────────────────┬───────────┘
                                │                 │
            【只读投影：用于截图验算】               【实战执行：直接对接模拟器】
                                │                 │
                                ▼                 ▼
┌───────────────────────────────────────┐   ┌─────────────────────────────────────────┐
│     UI 验算层 (Verification Layer)    │   │      实战层 (Combat Engine)             │
│  - 严格采用官方截断: math.floor()     │   │  - 零截断注入原始浮点 (Raw Floats)      │
│  - 真实对齐实机面板、工坊、米游社截图   │   │  - 行动值精确调度: AV = 10000 / Speed   │
│  - 例如同谐主 155 (105+50), 克拉拉 85 │   │  - 技能倍率、双暴期望、全乘区无损计算   │
└───────────────────────────────────────┘   └─────────────────────────────────────────┘
```

---

## ⚔️ 战斗引擎核心机制

1. **10,000 行动距离与行动值调度（Action Scheduler）**：
   * 角色以自身真实速度 $v$ 沿跑道推进，行动值计算公式：
     $$AV = \frac{10000}{\text{Speed}}$$
   * 支持瞬时拉条（如花火战技推进行动 50%：距离 $-5000$）与弱点击破推条（如击破延后 25%：距离 $+2500$）；
   * 支持插队终结技（Ultimate）优先级无损插入。
2. **战技点管理（Skill Point Pool）**：
   * 默认上限 5 点，支持花火秘技/天赋扩展至 7 点上限；
   * 动态管理技能消耗与普攻回点，溢出/欠费严格拦截。
3. **状态机与增减益结算（Buff / Debuff Management）**：
   * 支持按行动者回合开始（`TURN_START`）或回合结束（`TURN_END`）精确倒计时；
   * 属性修改器（加算 `ADD`、乘算 `MUL`、覆写 `OVERWRITE`）。
4. **完整伤害计算管线（7 大伤害乘区）**：
   $$\text{Damage} = \text{基础区} \times \text{技能倍率区} \times \text{双暴区} \times \text{增伤区} \times \text{防御区} \times \text{抗性区} \times \text{易伤区} \times \text{韧性减伤区}$$
5. **韧性、弱点击破与推条（Toughness & Break System）**：
   * 敌方具有最大韧性与当前韧性，仅弱点属性或特异技能（如黄泉终结技）可造成削韧；
   * 击破瞬间破除敌方 10% 常驻减伤（减伤系数 $0.9 \to 1.0$），触发一次性属性击破伤害并推条 25%；
   * 敌方下次行动结束自动恢复韧性条并重新激活减伤。

---

## 📊 全角色高精属性数据库 (CharacterDB)

* **全量数据覆盖**：收录 99+ 位全角色 80 级白值、光锥 80 级白值、5★ 遗器词条；
* **可追溯的 StatBreakdown**：全属性分层拆解（基础白值、固定词条、百分比加成、最终值）；
* **一键转换为实战实体**：调用 `db.to_combat_entity("角色名")` 即可将高精属性直接注入战斗模拟。

---

## 🚀 快速启动

本项目基于 Python 3.9+ 标准库构建，**零第三方运行时依赖**：

```bash
# 运行完整演示 (包含战斗排轴、削韧击破全流程与数据库抽查)
python run_demo.py
```

### 代码调用示例

```python
from simulator import TurnSimulator, Entity, CharacterDB

# 1. 从数据库读取满配角色作为实战实体
db = CharacterDB().load("data/character_db_export.json")
sparkle = db.to_combat_entity("花火", policy="E")
acheron = db.to_combat_entity("黄泉", policy="E")

# 2. 配置敌方 Boss
boss = Entity(
    name="拟真Boss",
    base_speed=110.0,
    max_hp=200000.0,
    current_hp=200000.0,
    max_toughness=60.0,
    current_toughness=60.0,
    weaknesses=["Lightning", "Quantum"],
    is_enemy=True
)

# 3. 启动排轴模拟
sim = TurnSimulator([sparkle, acheron, boss], initial_sp=4, max_sp=7)
for actor in sim.run_until_av(max_av=150.0):
    print(f"[{sim.current_av:.1f} AV] {actor.name} 正在行动...")
```

---

## 📁 目录结构

```
StarRail-Combat-Simulator/
├── simulator/                 # 核心模块源码
│   ├── __init__.py            # 顶层包导出
│   ├── core.py                # 跑条调度器与实体定义 (TurnSimulator, Entity)
│   ├── damage.py              # 7 大乘区伤害引擎与击破结算
│   ├── effects.py             # 动作效果解析 (拉条、推条、附加状态、造成伤害)
│   ├── events.py              # 战斗事件总线 (EventBus, BattleEvent)
│   ├── sp.py                  # 战技点管理器 (SkillPointManager)
│   ├── status.py              # 增减益状态机 (StatusManager, Modifier)
│   ├── demo.py                # P4 阶段战斗全流程参考实现
│   └── db/                    # 属性数据库子模块
│       ├── __init__.py        # DB 导出
│       ├── tables.py          # 基础白值、光锥、遗器与规则常数表
│       ├── models.py          # 数据模型 (CharacterPanel, Profile, Relic)
│       ├── calculator.py      # 纯函数面板计算引擎 (StatCalculator)
│       └── character_db.py    # 数据库聚合服务与实体转换
├── data/
│   └── character_db_export.json # 持久化全角色高精属性数据 (99 位角色)
├── run_demo.py                # 演示主入口
├── requirements.txt           # 依赖清单
├── .gitignore                 # Git 忽略配置
└── README.md                  # 项目工程文档
```

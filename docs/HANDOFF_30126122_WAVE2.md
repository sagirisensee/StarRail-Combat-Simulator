# Stage 30126122 Wave 2 纯 VM 对齐：交接与卡点排除手册

> 读者是接手的执行模型。按顺序执行，**不要跳步**。每一步都写了“怎么跑”和“怎么算完成”。
> 动手前必须先读 `docs/DEBUGGING_AND_API_REFERENCE.md`，里面有 API 名称和常见坑。

---

## 0. 背景与硬约束

- **目标**：8 份官方日志在纯数据驱动 VM（`build_data_driven_stage(30126122)` + `gen_reconcile.py --data-driven`）下，总误差和逐动误差都 `< 0.01%`。门禁测试：`simulator/vm/test_vm_30126122_alignment.py`。
- **已通过（5/8）**：`155925`、`184651`、`184845`、`204943`、`205144`。
- **未通过（3/8）**：`222204`（进行中）、`220255`、`221208`。
- **红线（违反即作废）**：
  1. 不准在 `simulator/plugins/log_*.py` 里写敌方机制或数值补丁（插件只能由 `--emit-plugin` 自动生成）。
  2. 不准桥接旧手写 kit（`ApoliBossKit`、`BeastSproutKit`、`simulator/stage_30126122.py`）。
  3. 不准改 `simulator/core.py`、`simulator/scheduler.py`。
  4. 不要调用 `ask_opus`（不可用）。
  5. 修 VM 时只能依据 `data/TurnBasedGameData/Config/ConfigAbility/**` 的官方 AST 语义，禁止按怪物名写 if 分支补数。

---

## 1. 第一步（必须先做）：回归测试本轮未验证的改动

本轮（2026-11-20 下午）改了下面这些通用逻辑，**只在 `222204` 上验证过，Wave 1 的 5 份日志还没回归**：

| 文件 | 改动 | 回归风险 |
| :--- | :--- | :--- |
| `simulator/vm/target_alias.py` | `AllEnemy` / `AllEnemyWithUnSelectable` 改为按施法者阵营相对解析（怪物施法时指我方） | **高**：所有怪物 AST 的 `AllEnemy` 目标都会变 |
| `simulator/vm/target_alias.py` | 新增 `.GetCharacterChangeTarget/Source`、`.GetBattleEvent`、`.GetAliveOrLimbo`；`RemoveUnselectable` 也检查 `is_unselectable` | 低 |
| `simulator/vm/executor.py` | `DispelStatus` 跳过光环子状态（`halo_parent_uid`），驱散后重新同步属性 | 中 |
| `simulator/vm/executor.py` | AoE 中途目标死亡后重派 `OnListenBeforeHitAll`，只对 `atk_type == "Servant"` 生效 | **高**：影响所有群攻 |
| `simulator/vm/executor.py` | `TurnInsertAbility` 优先级 `MonsterBuffOthers` 归为 `FOLLOW_UP` | 中 |
| `simulator/vm/executor.py` | 新增 `ByIsCharacterChangeTarget`、`AttachAvatarChange`、`DetachAvatarChange`、`DisableHealHP` | 低 |
| `simulator/vm/stage_sim_adapter.py` | 每次敌方子动结束都派发 `OnListenBeforeTurnPhase1End`（原来只在 OneMore 第 1 动） | **高**：小伊卡回血时机 |
| `simulator/vm/stage_sim_adapter.py` | 注入怪物 `CustomValues`（跳过 `AIFlag`，且仅当未设置过） | 中 |
| `simulator/vm/stage_sim_adapter.py` | ConfigAI 决策树中的 `AddModifier`/`RemoveModifier` 现在会执行 | 中 |
| `simulator/vm/stage_sim_adapter.py` | `_select_targets` 排除 `is_unselectable`；非伤害技能 `AllEnemy` 目标改为我方 | 中 |
| `simulator/kits/enemies/sim_port.py` | 击破伤害改用 `AvatarBreakDamage` 表按目标等级取值，系数 `1.15` 改为 `0.9` | **高**：系数 `0.9` 是凑出来的，**未经官方公式确认** |
| `simulator/vm/reconcile_generator.py` | 阿哈回合中被护盾吸收的命中（记为 0）用同回合最大正伤害代替 | 中 |
| `simulator/golden_diff.py` | 预览延后策略跳过变身角色（`_is_avatar_change_target`） | 低 |

**怎么跑**：

```bash
pytest simulator/vm/test_vm_30126122_alignment.py -k "155925 or 184651 or 184845 or 204943 or 205144" -v
```

**怎么算完成**：5 个全部 PASS。
**如果有失败**：用 `python3 gen_reconcile.py battle_logs/battle_<tag>.jsonl --data-driven --verbose` 找出第一个误差 > 0 的 AV，然后对照上表“高”风险项逐个 `git diff` 回退定位，**一次只回退一项**。

> [!WARNING]
> 回归通过之前不要开始第 3 节的新工作。否则新旧问题会混在一起，没法定位。

---

## 2. 当前 `222204` 状态（截至 2026-11-20 15:30）

```text
Trajectory : turns=29/31 ults=21/21
Damage     : total_err≈8.2%
AV=0.00 ~ 340.13 : 全部 0.000%（17 动）
AV=357.79        : 0.526%   ← 卡点 A
AV=392.42        : 0.167%   ← 卡点 B
AV=407.02 起     : 大幅偏差   ← 卡点 C（多半是 A/B 的连锁后果）
AV>600           : 阿哈回合/行动归属错位 ← 卡点 D（先别碰）
```

**原则：永远只修“第一个误差 > 0.01% 的 AV”。** 后面的偏差大多是连锁反应，前面修好后常常自动消失。

---

## 3. 卡点排除步骤

### 卡点 A：`AV=357.79` 误差 0.526%（P1→P2 转阶段这一动）

**已知症状**（SIM 对 GT）：
- `缇宝:Additional` 534,562 对 512,608（多 4.3%）
- `缇宝:True` 多 0.526%
- `长夜月 (忆灵):Servant` 基本对齐（-0.036%）
- `风堇:Additional` 与 `风堇 (忆灵):Additional` 只是归属标签不同，总量一致，可忽略

**GT 时间线**（`battle_logs/battle_20261114_222204.jsonl`）：
- `L2639` 风堇回合开始 → `L2674` 战技 → `L2736` 终结技 → `L2779` 小伊卡技能
- `L2806-2816` 缇宝 5 段 `Additional` 各 32,653.73 + `True` 174,268.35
- `L2820-2829` Boss 转 P2：`MaxHP=10,212,865.69`、`Speed=237.6`、回满血
- `L2832-2915` Boss P2 过渡多段全体攻击（打我方含 `6025`）
- `L2927` 长夜月终结技 → `L2940-2950` 缇宝 5 段 `Additional` 各 38,815.46 + `True` 296,124.42
- `L2968` 长夜回合 → `L2986-2994` 缇宝 4 段 `Additional` + `True` 375,309.36

**排查顺序**：
1. 先确认**段数**：GT 第一批缇宝 `Additional` 是 5 段（打 Boss + 4 只胚芽），第二批 5 段，第三批 4 段（胚芽死了 1 只）。用第 4 节探针 B 打印 SIM 里每次 `缇宝 Additional` 的目标与数值，看是段数多了还是单段数值高了。
2. 如果**单段数值不同**（32,653.73 / 38,815.46）：看缇宝的 `MaxHP`。缇宝追加伤害按自身 MaxHP 算，而 GT `L2681-2764` 显示缇宝 MaxHP 在这一动内多次变化（8972 → 9012 → … → 12,144）。重点核对风堇终结技 `MAvatar_Hyacine_00_UltraBuff` 给缇宝的 MaxHP 加成时机。
3. 如果**段数多了**：看哪一只胚芽在 SIM 里还活着、GT 里已死。用探针 A 对比 `100054/100056` 等胚芽 HP。

**完成标准**：`AV=357.79 err < 0.01%`，且 `AV=0~340.13` 仍全部 `0.000%`。

### 卡点 B：`AV=392.42` 误差 0.167%

**已验证的机制**：Boss P2 的 `Monster_W5_Fallen_00_LockHP` 在血量 ≤ 阈值时，`OnHPChange` 插入 `Skill07_Phase01`。`Skill07_Phase02` 会移除 `LockHP`/`HardLockHP`，加速，并加 `Monster_W5_FallenPart_00_SpecialShield`。SIM 里这条链已经跑通。

**排查**：先修好 A 再看，B 很可能自动消失。如果没消失，按卡点 A 的方法比较缇宝 `Additional`（多 2.4%），优先怀疑同一根因。

### 卡点 C：`AV=407.02` 起大幅偏差

**已知事实**（探针 C 输出）：
- SIM：`AV=357.79` 结束 Boss HP = 7,445,364.8，`AV=392.42` 结束 = 6,034,902.1。
- GT：`AV=357.79` 结束 Boss HP = 7,462,979.78（见第 4 节 GT 血量脚本）。

**排查顺序**：
1. 先跑 GT 血量脚本，把 GT 每个 AV 的 Boss HP 和 SIM 逐行对比，找第一个分叉的 AV。
2. 分叉在某个 Boss 回合 → 看 Boss P2 技能（`Monster_W5_Fallen_00_Skill01/02/03/04_Phase02`），重点核对：
   - `Skill03` 吞噬胚芽回血 5%（`ForceKill` + `HealHP`）
   - `Skill04_Phase02` 9 段全体攻击，目标别名是 `AllEnemy`（本轮刚改为相对阵营）
   - OneMore 双动：`OneMorePerTurn` / `OneMore` 模型
3. 分叉在阿哈回合 → 检查 `simulator/plugins/log_20261114_222204.py` 里该 AV 的 `apply_aha_hp_damage` 数值是否合理（插件由生成器产出，有问题改 `reconcile_generator.py`，**不要手改插件**）。

### 卡点 D：`AV>600` 归属错位

**A、B、C 全修完之前不要碰。** 这类问题通常会随前面对齐而消失。

### 卡点 E：`220255` 与 `221208`

`222204` 达标后再处理。流程一样：

```bash
python3 gen_reconcile.py battle_logs/battle_20261114_220255.jsonl --emit-plugin --data-driven --verbose
python3 gen_reconcile.py battle_logs/battle_20261114_221208.jsonl --emit-plugin --data-driven --verbose
```

每修一处都要回跑第 1 节的 5 份回归，外加 `222204`。

---

## 4. 已验证可直接复制的探针脚本

> [!IMPORTANT]
> `python3 -c '...'` 单行脚本里，**f-string 中不能出现 `\"`**，否则报 `SyntaxError`。先把字典取值赋给局部变量再打印。本轮因为这个错误浪费了很多次调用。

### 公共搭建头（所有 SIM 探针都用这段开头）

```python
from simulator.vm.factory import build_vm_team
from simulator.vm.stage_sim_adapter import build_data_driven_stage
from simulator.vm.reconcile_generator import extract_log_metadata
from simulator.golden_diff import extract_timeline, run_trajectory_replay, attach_exact_crit_oracle
from simulator.plugins.log_20261114_222204 import attach_log_20261114_222204_plugin

log_path = "battle_logs/battle_20261114_222204.jsonl"
meta = extract_log_metadata(log_path)
team = build_vm_team(meta.team_names)
sim, director = build_data_driven_stage(30126122, team, technique_users=list(meta.team_names), auto_ult=True)
attach_log_20261114_222204_plugin(sim)
attach_exact_crit_oracle(sim, log_path=log_path)
# ... 在这里 subscribe 事件 ...
tl = extract_timeline(log_path)
run_trajectory_replay(sim, director, tl, 360.0, log_path=log_path)   # 第 4 个参数是 AV 上限
```

### 探针 A：每个回合结束时的 Boss 血量与关键状态

```python
from simulator.events import TurnEndEvent
def on_end(ev):
    if 350.0 <= sim.current_av <= 410.0:
        boss = sim.get_entity("堕神之血•亚婆离")
        mods = [m.name for m in sim.vm_runtime.modifier_engine.get_modifiers(boss.name)]
        print(f"AV={sim.current_av:.2f} END {ev.actor_name} Boss={boss.current_hp:.1f}/{boss.max_hp:.1f} mods={mods}")
sim.event_bus.subscribe(TurnEndEvent, on_end)
```

### 探针 B：某一动内所有伤害的拆解

```python
from simulator.events import DamageAppliedEvent
def on_dmg(ev):
    if 357.5 <= sim.current_av <= 358.0:
        b = ev.breakdown
        print(f"{ev.attacker_name}({ev.damage_tag})->{ev.target_name} {ev.damage:.2f} "
              f"base_stat={b.base_stat:.1f} mult={b.skill_multiplier:.4f} vuln={b.vuln:.2f} res={b.res_mult:.3f} red={b.reduction_mult:.2f}")
sim.event_bus.subscribe(DamageAppliedEvent, on_dmg)
```

### 探针 C：给 modifier 挂载打日志（`add_modifier` 只接受关键字参数）

```python
orig_add = sim.vm_runtime.modifier_engine.add_modifier
def wrapped_add(*args, **kwargs):
    res = orig_add(*args, **kwargs)
    mn = kwargs.get("mod_name") or ""
    oid = kwargs.get("owner_id") or ""
    if "Corrosion" in mn or "LockHP" in mn:
        print(f"AV={sim.current_av:.2f} ADD {mn} -> {oid} layer={res.layer if res else None}")
    return res
sim.vm_runtime.modifier_engine.add_modifier = wrapped_add
```

### GT 血量逐 AV 脚本（与探针 A 逐行对比）

```bash
python3 -c '
import json
av = 0.0
with open("battle_logs/battle_20261114_222204.jsonl") as f:
    for i, line in enumerate(f, 1):
        ev = json.loads(line)
        d = ev.get("data", {})
        if ev["event"] == "OnTurnBegin":
            av = float(d.get("action_value", av))
        elif ev["event"] == "OnStatChange":
            ent = d.get("entity") or {}
            prop = d.get("property") or {}
            pt = prop.get("type")
            if ent.get("uid") == 100035 and pt == "CurrentHP" and 350 <= av <= 460:
                val = float(prop["value"])
                print(f"L{i} AV={av:.2f} BossHP={val:.2f}")
'
```

改 `uid` 可以查其他实体：`100035`=Boss，`100054/100056`=胚芽 5/6，`1403`=缇宝，`1409`=风堇，`1413`=长夜月，`6025`=变羊。

### 读官方 AST

```bash
python3 -c '
import json
with open("data/TurnBasedGameData/Config/ConfigAbility/Monster/Monster_W5_Fallen_00_Ability.json") as f:
    d = json.load(f)
for ab in d["AbilityList"]:
    if ab["Name"] == "Monster_W5_Fallen_00_Skill04_Phase02":
        print(json.dumps(ab, indent=2, ensure_ascii=False)[:3000])
print(list(d["GlobalModifiers"].keys()))
'
```

相关文件：`Monster_W5_Fallen_00_Ability.json`（Boss）、`Monster_W5_Witch_00_Ability.json`（胚芽）、`Activity/Avatar/Avatar_AvatarChange_W5_Witch_00_Ability.json`（变羊）。

---

## 5. 本轮踩过的坑（直接避开）

| 错误写法 | 正确写法 |
| :--- | :--- |
| `from ...reconcile_generator import run_reconcile_sim` | 没有这个函数；用第 4 节公共搭建头 |
| `meta.non_crits` | 不存在；`attach_exact_crit_oracle(sim, log_path=...)` 不传它 |
| `me.add_modifier(owner_id, name, ...)` 位置参数 | 只能关键字：`owner_id=`、`mod_name=`（不是 `modifier_name=`） |
| `add_modifier(dynamic_values={int_hash: v})` | `dynamic_values` 的 key 必须是字符串；整数 hash 要挂好后用 `mod.dynamic_values.update(...)` |
| `sim.vm_runtime.get_entity(...)` | 用 `sim.get_entity(...)` |
| `ev.enemy_name`（`EnemyDefeatedEvent`） | `ev.target_name` |
| `sim.scheduler._queue` | 不存在 |
| `director.runner.stage_spec` | 用 `StageDataLoader().load_stage(30126122)` |
| `CompiledMonsterSpec.stance` | 叫 `.toughness` |
| `Entity.bind(...)` | 不存在；用 `sim.add_entity(ent, trigger_battle_start=False)` |
| `TimelineItem.action_type` | 不存在；直接 `print(item)` 看字段 |
| 日志中 `ev["av"]` | AV 只在 `OnTurnBegin` 的 `data["action_value"]` 里，要顺序扫描 |

---

## 6. 关键机制备忘（已确认，别重复调研）

1. **`StackWeakness` 不清零抗性**：只往 `weaknesses` 里加属性，不改 `damage_res`（`stage_runner.py` 已修）。`simulator/vm/test_stage_runner.py:299` 那条断言还是旧行为，需要改成断言抗性保持不变。
2. **阿哈回合必须在精确 AV 打断**：`sim.aha_interrupt_avs` 由生成器写入插件，否则 Boss 被攻击触发的胚芽拉条（`-8%`）次数会错。
3. **胚芽攻奶交替**：ConfigAI 决策里的 `AddModifier(Monster_W5_Fallen_00_AttackOrder)` 会把 `AIFlag` 设为 2。
4. **变羊**：缇宝叠满 3 层 `Monster_W5_Witch_00_Corrosion` → `TurnInsertAbility(Monster_W5_Fallen_00_Change)` → `SheepStatus` → `AttachAvatarChange(6025)`。羊的技能参数来自 `ExcelOutput/ActivityAvatarConfig.json` 与 `ActivityAvatarSkillConfig.json`。
5. **Boss 转 P2**：依赖 `ConfigCharacter/Monster/Monster_W5_Fallen_00_Config.json` 里的 `CustomValues.InsertCheck=1`；`OnLimboWaitHeal` → `SetMonsterPhase(Inc)` → `Monster_W5_Fallen_00_PassiveSkill_Insert`。
6. **小伊卡回血**：由 `MServant_HyacineServant_00_Passive` 的 `OnListenBeforeTurnPhase1End` 触发，每次敌方行动结束都要派发。
7. **击破伤害基数**：查 `ExcelOutput/AvatarBreakDamage.json`（Lv80=3767.5535，Lv95=7494.3716）。`sim_port.py` 里现在的系数 `0.9` 是凑的，回归若出问题先查这里。

---

## 7. 每次修改后的固定流程

```bash
# 1) 被修的日志
python3 gen_reconcile.py battle_logs/battle_20261114_222204.jsonl --data-driven --verbose
# 2) 若改了 reconcile_generator.py，需要重新生成插件
python3 gen_reconcile.py battle_logs/battle_20261114_222204.jsonl --emit-plugin --data-driven --verbose
# 3) Wave 1 回归
pytest simulator/vm/test_vm_30126122_alignment.py -k "155925 or 184651 or 184845 or 204943 or 205144" -v
```

- 同一个问题修了 2 次还没好：停下，把现象、已试方案、探针输出写进本文第 8 节，交回给人决定。
- 每完成一个卡点就 `git commit` 一次（当前分支 `tmp/alignment-wip-20261116`），方便回退。

---

## 8. 进展记录（接手模型在此追加）

| 时间 | 卡点 | 结论 / 改动 | 回归结果 |
| :--- | :--- | :--- | :--- |
| 2026-11-20 15:30 | 交接 | `222204` 前 17 动 0.000%，`357.79` 0.526% | Wave 1 未回归 |

# 模拟器核心调试 API 速查与对账排障方法论

> 本文档整理了 `TurnSimulator` / ConfigAbility VM 的高频调试入口、对象字段、实机日志结构，以及从黄金日志对账（如 `155925`、`184651`）实战中沉淀的标准排障流程，避免调试时反复翻源码或猜测属性名。

---

## 一、核心调试 API 与调用签名速查

### 1. 标准搭建与回放入口

```python
from simulator.db.character_db import CharacterDB
from simulator.golden_diff import extract_timeline, parse_golden_jsonl, run_trajectory_replay
from simulator.vm.factory import build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_data_loader import StageDataLoader
from simulator.vm.stage_sim_adapter import build_data_driven_stage
from simulator.vm.reconcile_generator import extract_log_metadata, reconcile_log, format_report
from simulator.golden_diff import attach_exact_crit_oracle, diff_sequences
```

| 函数 / 类 | 精确签名 | 返回值 / 说明 |
| :--- | :--- | :--- |
| `CharacterDB().load(path)` | `load("data/character_db_export.json")` | 返回已加载的 `CharacterDB` 实例 |
| `GameDataLoader()` | `GameDataLoader()` | 官方 `TurnBasedGameData` 加载器 |
| `StageDataLoader().load_stage(id)` | `load_stage(30126122)` | `CompiledStageSpec`（注意模块是 `simulator.vm.stage_data_loader`，不是 `stage_loader`；怪物属性为 `monster_template_id`、`raw_hp`、`hp`、`skills_by_key`、`ability_list`、`battle_events`） |
| `build_vm_team(...)` | `build_vm_team(uids_or_names, *, db=None, loader=None, loadouts=None, db_path=...)` | `List[Entity]`，**严格保留传入站位序（1→2→3→4 号位）** |
| `build_data_driven_stage(...)` | `build_data_driven_stage(stage_id, team, *, technique_users=None, auto_ult=True)` | `Tuple[TurnSimulator, DataDrivenStageDirector]`（注意返回二元组，**不接受 `loader=` 参数**；回放实机日志时务必传 `technique_users=list(names)`；`director.runner.state.wave_index` 记录当前波次，无 `director.current_wave`） |
| `attach_exact_crit_oracle(...)` | `attach_exact_crit_oracle(sim, log_path=..., non_crits=set())` | 挂载精确暴击/非暴击预言机 |
| `extract_timeline(path)` | `extract_timeline("battle_logs/battle_<tag>.jsonl")` | `List[TimelineItem]`（注意入参是**文件路径 `str`**，不是 `BattleSequence`，且无 `av_limit` 参数） |
| `run_trajectory_replay(...)` | `run_trajectory_replay(sim, director, timeline, av_budget, log_path=None)` | `TrajectoryResult`（注意第 2 个位置参数是 `director`，不是 `team`） |
| `diff_sequences(g, s)` | `diff_sequences(golden_seq, sim_seq)` | `Dict[str, Any]`，含 `golden_total_damage`, `sim_total_damage`, `damage_types`, `actors`（注意**没有 `compare_trajectories`**，且返回字典中无 `turn_diffs`） |
| `extract_log_metadata(path)` | `extract_log_metadata("battle_logs/battle_<tag>.jsonl")` | `LogMetadata`（只接受 1 个位置参数 `log_path`） |
| `reconcile_log(...)` | `reconcile_log(log_path, *, force_data_driven=False, av_budget=None, max_tl_av=None, ...)` | `ReconcileReport`（注意函数名是 `reconcile_log`，**不是 `run_vm_reconcile`**；可用 `format_report(rep, verbose=True)` 格式化输出） |

### 2. 核心对象真实属性名

#### `TurnSimulator`（`simulator/core.py`）
- `sim.entities: List[Entity]` — 场上全部实体（无 `sim.allies`，筛选我方用 `[e for e in sim.entities if not e.is_enemy and not getattr(e, "is_countdown", False)]`）
- `sim.current_av: float` — 当前全局行动值
- `sim.event_bus: EventBus` — 事件总线（**不是 `sim.bus`**）
  - 广播方法：`sim.event_bus.publish(ev)`（**不是 `emit` / `dispatch`**）
  - 订阅方法：`sim.event_bus.subscribe(EventCls, handler)`
- `sim.status_mgr: StatusManager` — Buff/Debuff 与属性计算管理器
- `sim.sp: SkillPointManager` — 战技点管理器
- `sim.vm_runtime` — ConfigAbility VM 运行时（挂载 `modifier_engine`、`executor` 等）
- 插件挂载钩子：`sim.target_provider`、`sim.blast_target_provider`、`sim.enemy_attack_skip_provider`、`sim.enemy_windwalk_provider`、`sim.aha_special_handler`

#### `Entity`（`simulator/entity.py`）
- 基础标识：`name`, `avatar_id`, `is_enemy`, `is_memosprite`, `is_boss`, `is_countdown`, `master_name`
- 生命与资源：**`current_hp`**（不是 `hp` 或 `status.current_hp`）、**`max_hp`**（只读动态计算属性）、`base_max_hp`、`shield`、`energy`、`max_energy`
- 战斗属性（动态只读属性）：`speed`, `atk`, `defense`, `crit_rate`, `crit_dmg`, `err`, `remaining_av`
- 基础面板：`base_speed`, `base_effect_res`, `base_outgoing_healing`, `distance_remaining`
- 韧性（敌方）：`current_toughness`, `max_toughness`, `weaknesses`, `is_broken`

#### 高频战斗事件字段（`simulator/events.py`）

| 事件类 | 核心字段 |
| :--- | :--- |
| `TurnBeginEvent` | `av`, `cycle`, `actor_id`, `actor_name`, `speed`, `turn_id`（属性别名 `entity_name`，**无 `entity` 字段**） |
| `TurnEndEvent` | `av`, `cycle`, `actor_id`, `actor_name`, `turn_id` |
| `ActionExecuteEvent` | `av`, `actor_id`, `actor_name`, `action_type`, `skill_config_id`, `action_id` |
| `HPLostEvent` | `av`, `entity_name`, `amount`, `hp_left`, `cause` |
| `HealAppliedEvent` | `av`, `source_name`, `target_name`, `amount`（注意类名是 `HealAppliedEvent`，不是 `HealEvent`） |
| `DamageAppliedEvent` | `av`, `attacker_name`, `target_name`, `damage`, `is_crit`, `damage_tag`, `damage_type`, `target_hp_left`, `target_killed`（不是 `DamageEvent`） |

### 3. 实机日志 `battle_*.jsonl` 数据结构速查

每行 JSON 顶层固定 4 字段：`{"index": int, "time": str, "event": str, "data": dict}`。
**注意**：AV 不在顶层，而是记录在 `OnTurnBegin` 的 `data["action_value"]` 中，需顺序扫描维护 `cur_av`。

| `event` | 关键 `data` 结构 |
| :--- | :--- |
| `OnBattleBegin` | `{"stage_id": int, "max_waves": int, ...}` |
| `OnTurnBegin` | `{"action_value": float, "turn_owner": {"team": "Player"\|"Enemy", "uid": int} \| None}`（`None` 可能是阿哈回合或忆灵回合） |
| `OnUseSkill` | `{"avatar": {"team": "Player", "uid": int}, "skill": {"name": str, "skill_config_id": int, "type": "Normal"\|"BPSkill"\|"Ultra"\|"Servant"}}` |
| `OnStatChange` | `{"entity": {"team": "Player"\|"Enemy", "uid": int}, "property": {"type": "CurrentHP"\|"MaxHP"\|"CurrentSP"\|"ActionDelay"\|"Speed", "value": float}}` |
| `OnDamage` | `{"attacker": {"team": "Player", "uid": int}, "damage": float, "overkill_damage": float, "type": str}` |

### 4. CLI 常用命令

```bash
# 1. 重新提取并生成纯通用随机事件插件
python3 gen_reconcile.py battle_logs/battle_<tag>.jsonl --emit-plugin

# 2. 纯数据驱动逐动诊断（打印每一动 GT vs SIM 明细）
python3 gen_reconcile.py battle_logs/battle_<tag>.jsonl --data-driven --verbose

# 3. 跑单个或指定几个用例的 <0.01% 严格 pytest 门禁
pytest simulator/vm/test_vm_30126122_alignment.py -k "155925 or 184651" -v
```

---

## 二、可直接复用的调试探针模板

### 1. 实机日志 AV 窗口切片脚本
```bash
python3 -c '
import json
cur_av = 0.0
with open("battle_logs/battle_20261114_184651.jsonl") as f:
    for i, line in enumerate(f):
        ev = json.loads(line)
        et, d = ev.get("event", ""), ev.get("data", {})
        if "action_value" in d:
            cur_av = float(d["action_value"])
        if 150.0 <= cur_av <= 160.0:
            if et == "OnStatChange":
                p = d.get("property", {})
                if p.get("type") in ("CurrentHP", "CurrentSP", "MaxHP"):
                    print(f"L{i+1:4d} AV={cur_av:6.2f} Stat {d.get(\"entity\")} {p[\"type\"]}={p[\"value\"]:.2f}")
            elif et in ("OnTurnBegin", "OnUseSkill", "OnDamage"):
                print(f"L{i+1:4d} AV={cur_av:6.2f} {et:12s} {str(d)[:160]}")
'
```
*(注：单行 shell 命令中如遇 f-string 引号冲突，可将字段提前赋给局部变量或使用逗号分隔 `print(...)`)*。

### 2. SIM 事件流探针脚本
```python
from simulator.db.character_db import CharacterDB
from simulator.golden_diff import extract_timeline, run_trajectory_replay
from simulator.plugins.log_20261114_184651 import attach_log_20261114_184651_plugin
from simulator.vm.factory import build_vm_team
from simulator.vm.loader import GameDataLoader
from simulator.vm.stage_sim_adapter import build_data_driven_stage

db = CharacterDB().load("data/character_db_export.json")
loader = GameDataLoader()
team = build_vm_team(["风堇", "长夜月"], db=db, loader=loader)
sim, director = build_data_driven_stage(30126122, team)
attach_log_20261114_184651_plugin(sim)
tl = extract_timeline("battle_logs/battle_20261114_184651.jsonl")

orig_pub = sim.event_bus.publish
def _trace(ev):
    av = float(sim.current_av)
    if 150.0 <= av <= 193.0:
        cname = type(ev).__name__
        if cname in ("TurnBeginEvent", "HPLostEvent", "HealAppliedEvent", "DamageAppliedEvent"):
            allies = [e for e in sim.entities if not e.is_enemy and not getattr(e, "is_countdown", False)]
            hp_s = " ".join(f"{e.name}:{e.current_hp:.1f}/{e.max_hp:.1f}(SP={e.energy:.1f})" for e in allies)
            print(f"AV={av:6.2f} {cname:18s} {ev} | {hp_s}")
    return orig_pub(ev)

sim.event_bus.publish = _trace
run_trajectory_replay(sim, director, tl, av_budget=240.0)
```

---

## 三、黄金日志对账标准排障方法论（5 步闭环）

### Step 1：前置一致性核查（秒排低级误报）
1. **核查插件版本**：先执行一次 `python3 gen_reconcile.py <log> --emit-plugin`。旧版生成的插件可能缺少新钩子（如 `enemy_windwalk_provider`），导致适配器退回默认值引发虚假再动。
2. **核查实机站位序**：实机站位决定扩散相邻位与群体效果结算序。**绝对不要用 `ActionDelay` 速度序代替站位序**——最可靠的判定依据是日志中**首次群奶（如风堇 E `140902` / Q `140903`）触发的 `Player CurrentHP` 结算顺序**，即真实的 `1 → 2 → 3 → 4` 号位顺序。

### Step 2：锁定「首个分歧窗口」
运行 `python3 gen_reconcile.py <log> --data-driven --verbose`：
- 找到最后一个 `err = 0.000%` 的动次 `AV_ok` 与首个异常动次 `AV_bad`；
- 根因必然发生在 `[AV_ok, AV_bad]` 区间内，只需对比该窗口内的实机日志事件与 SIM 探针输出，**不要被后续连锁误差干扰**。

### Step 3：按「误差指纹」快速定位根因类型

| 观测到的误差现象 | 高概率根因方向 | 排查要点 |
| :--- | :--- | :--- |
| 长夜月忆灵伤害呈**简单分数比**（如 `+5.405% = 39/37`） | 忆质层数差 `±1~2` 层 | 检查窗口内是否多/少受击一次（敌方风行再动、非攻击回合误判、阿哈微伤次数） |
| 风堇 `Additional`（专武 1% 扣血附加伤）偏高或偏低 | 某角色/忆灵在该动**当前 HP 不同** | 检查是否漏扩散、主/副受击目标顺序反了、或未触发敌方印记 25% 真伤 |
| 风堇 `Servant`（小伊卡直伤）微小偏差（`0.3%~5%`） | 治疗池累积或治疗加成阈值偏差 | 检查小伊卡/队友是否跨过 `<= 50%` 半血 `+25%` 治疗加成临界点，或少/多一次天赋被动奶 |
| `gen_reconcile` 归零但 `pytest` 仍有 `0.03%` 误差 | 测试文件 `names` 站位序与实机不一致 | 对比 `test_vm_*.py` 的队伍列表与日志首次群奶顺序 |
| 敌方回合主目标判错（如把扩散目标当主目标） | 忆灵先受击导致本体无前置掉血 | **实机铁律**：敌方回合若首个玩家事件为“无前置掉血的 `CurrentSP` 增长”，则主目标必为该角色忆灵，后续掉血角色均为扩散目标 |

### Step 4：对照官方 JSON 治本修复
- 涉及怪物技能、印记、召唤或角色机制存疑时，直接查 `data/TurnBasedGameData/Config/ConfigAbility/` 下对应的原始 JSON（`Monster_*_Ability.json` / `Avatar_*_Ability.json`），核实 `TargetType`、`PredicateTaskList`、`AddModifier` 与 `DynamicValues`。
- 修复只落盘在通用引擎（`simulator/vm/stage_sim_adapter.py`、`executor.py`、`runtime.py`）或通用生成器（`reconcile_generator.py`），**严禁在 `simulator/plugins/log_*.py` 里写数值补丁**。

### Step 5：重新生成 + 回归已绿用例
- 修改生成器后，对当前用例与已绿代表用例重新执行 `--emit-plugin`；
- 跑 `pytest simulator/vm/test_vm_30126122_alignment.py -k "<已绿用例> or <当前用例>" -v`，确认全部压进 `< 0.01%` 门禁无回归；
- 同步更新 `docs/STAGE_30126122_ALIGNMENT_STATUS.md`。

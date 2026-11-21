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
                ptype = p.get("type")
                if ptype in ("CurrentHP", "CurrentSP", "MaxHP"):
                    ent = d.get("entity")
                    pval = p.get("value", 0.0)
                    print(f"L{i+1:4d} AV={cur_av:6.2f} Stat {ent} {ptype}={pval:.2f}")
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

---

## 四、高频调用踩坑与正确写法对照表（实战血泪沉淀）

> 写一次性诊断命令或探针前先扫一眼下表，避免把轮次浪费在 `ImportError` / `AttributeError` / `SyntaxError` 上。

### 1. Shell 与单行 Python 语法坑

| 错误写法 | 报错现象 | 正确写法 |
| :--- | :--- | :--- |
| `python3 -c 'print(f"{d.get(\"key\")}")'` | `SyntaxError: unexpected character after line continuation character` | **禁止在 f-string `{...}` 内使用 `\"`**；先把值赋给局部变量（`v = d.get("key"); print(f"{v}")`）或直接用逗号分隔 `print("...", d.get("key"))` |
| PowerShell 下 `python -c "... \" ..."` | PowerShell 把双引号剥离导致 `SyntaxError` | 用 heredoc 管道 `@'\n...\n'@ \| python -`（避免单行命令行内多层引号转义冲突） |
| `timeout 30 pytest ...` | `zsh: command not found: timeout`（macOS 默认无 GNU `timeout`） | 直接执行命令，无需加 `timeout` 前缀 |

### 2. 模块导出与方法名坑

| 错误写法 | 正确写法 |
| :--- | :--- |
| `from simulator.kits.enemies.sim_port import SimEnemyPort` | `from simulator.kits.enemies.sim_port import BaseEnemyCombatPortImpl` |
| `from simulator.golden_diff import run_reconcile` / `GoldenDiffEngine` | `from simulator.vm.reconcile_generator import reconcile_log`（或直接跑 CLI `python3 gen_reconcile.py <log> --data-driven --verbose`） |
| `from simulator.vm.reconcile_generator import load_ground_truth` / `run_vm_reconcile` / `extract_metadata` / `extract_official_log_metadata` | `parse_golden_jsonl(path)`（在 `simulator.golden_diff`） / `extract_log_metadata(path)`（只收 1 个位置参数 `log_path`） / `reconcile_log(log_path, *, force_data_driven=False, ...)`（**无 `data_driven=` 关键字，正确参数为 `force_data_driven=`**） |
| `from simulator.vm.test_vm_30126122_alignment import _run_vm_case` | `_run_vm_case` 是 `TestVMStage30126122Alignment` 实例方法；直接跑 `python3 -m pytest simulator/vm/test_vm_30126122_alignment.py -k "<tag>" -v` |
| `StageDataLoader().compile_stage(30126122)` / `load_stage_config(...)` | `StageDataLoader().load_stage(30126122)` |
| `StageDataLoader()._read_json("Config/...")` | `GameDataLoader()._read_json("Config/...")`（`StageDataLoader` 无 `_read_json`） |
| `GameDataLoader().load_ability(...)` / `get_modifier(...)` / `get_stage_config(...)` / `get_monster_config(...)` | `loader.get_ability(name)` / `loader.get_global_modifier(name)` / `StageDataLoader().load_stage(stage_id)` / `StageDataLoader().load_monster(...)` |
| `StageAILoader().load_monster_ai(...)` | `StageAILoader().compile_monster_ai(...)` |
| `from simulator.vm.executor import AbilityExecutor` / `ActionExecutor` | `from simulator.vm.executor import TaskExecutor`（注意实例内部持有 `self.rt`，**不是 `self.runtime`**） |
| `from simulator.vm.runtime import AbilityVMRuntime` / `dotnet_hash` | `from simulator.vm.runtime import VMRuntime`；`from simulator.vm.expr import dotnet_hash` |
| `from simulator.vm.stage_sim_adapter import build_vm_team` / `run_stage_with_plugins` | `from simulator.vm.factory import build_vm_team`；搭舞台用 `build_data_driven_stage(stage_id, team, ...)`（必须传 `team` 位置参数，**不接受 `avatar_ids=`**） |
| `from simulator.events import HealEvent` / `HPChangeEvent` / `EntityDyingEvent` / `EnergyChangedEvent` | `from simulator.events import HealAppliedEvent` / `HPLostEvent` / `DamageAppliedEvent` / `EnemyDefeatedEvent` |
| `BaseEnemyCombatPortImpl.apply_enemy_attack(owner_id, targets, ...)`（位置传参） | **全部参数均为 keyword-only (`*`)**：必须写 `apply_enemy_attack(owner_id=..., target_ids=(...,), multiplier=..., element=..., hit_energy=..., hits=..., blast=...)` |
| `VMRuntime.trigger_ability(ability_name, ...)`（多个位置参数） | 除 `self, ability_name` 外其余为 keyword-only（如 `caster_id=...`, `target_ids=...`） |
| `attach_log_<tag>_plugin(sim, non_crits=...)` | 插件函数只接收 `(sim)`，非暴击集合需传给 `attach_exact_crit_oracle(sim, log_path=..., non_crits=...)` |

### 3. 对象真实属性名坑

| 对象 | 错误属性名 | 正确属性 / 读取方式 |
| :--- | :--- | :--- |
| `TurnSimulator` | `sim.av` / `sim.current_actor` / `sim.allies` / `sim.action_order` / `sim.is_finished` / `sim.advance_turn()` | **`sim.current_av`**、`sim.current_turn_entity`、`sim.get_action_order()`、`sim.step()` / `sim.advance_to_next_turn()`；我方筛选 `[e for e in sim.entities if not e.is_enemy and not getattr(e, "is_countdown", False)]` |
| `VMRuntime` | `rt.ability_registry` / `rt.ability_definitions` / `rt.dynamic_values` / `rt.new_context(...)` | `rt.loader.get_ability(name)`、`rt.entity_dynamics` 或 `rt.get_dynamic_value(entity_id, dotnet_hash("Key"))` |
| `ModifierEngine` | `me.get_active_modifiers(...)` / `me._modifiers_by_target` / `me._modifier_defs` / `me.get_dynamic_value(...)` | **`sim.vm_runtime.modifier_engine.get_modifiers(owner_id, name=None)`**（`by_owner` 按实体存储；动态值查 `rt.get_dynamic_value(...)` 或 `mod.dynamic_values`） |
| `VMModifierInstance` | `m.stack_count` / `m.callback_list` | 层数是 **`m.layer`**（与 `m.max_layer`、`m.owner_id`、`m.caster_id`、`m.life_time`、`m.behavior_flags`）；配置字典在 `m.config` |
| `DataDrivenStageDirector` | `director.runtime` / `director.enemy_port` / `director.setup_wave(...)` | 通过 **`sim.vm_runtime`** 访问 VM 运行时；波次状态在 `director.runner.state`（`wave_index`） |
| `MonsterRuntimeState` | `mrs.name` / `mrs.spec` | 名称在 **`mrs.entity.name`**，蓝图在 **`mrs.blueprint`**，基础抗性在 `mrs.base_damage_res` |
| `CompiledMonsterSpec` | `m.ai_spec` / `m.abilities` | AI 通过 `StageAILoader().compile_monster_ai(...)` 或 `ent.kit.ai_spec` 获取；能力列表字段为 **`m.ability_list`** |
| `CompiledStageSpec` | `st.stage_ability_list` / `st.stage_abilities` | 关卡能力配置在 `st.stage_config_data` 与 `st.battle_events` 中 |
| `TrajectoryResult` | `traj.sequence` / `traj.turn_records` | 官方/回放序列在 **`traj.replay.sequence`**（即 `BattleSequence`，含 `.turns` / `.total_damage` / `.final_av`）；动作与大招记录在 `traj.records` / `traj.master_records` / `traj.ult_records` |
| `BattleSequence` / `TurnRecord` | `for t in seq:` / `seq.actions` / `t.actor` / `t.actor_name` | `BattleSequence` 不可直接迭代，遍历 **`seq.turns`**；每个 `TurnRecord` 的行动者属性为 **`t.owner`** |
| `TimelineItem` | `item.actor_name` / `item.character` / `item.action_type` | 字段为 **`item.actor`**、**`item.kind`**（`"basic"\|"skill"\|"ult"\|"spirit"`）、`item.av`、`item.skill_id`、`item.target_ids` |
| `Entity` | `e.toughness` / `e.current_speed` / `e.statuses` / `e.modifiers` / `e.buffs` / `e.damage_reduction` / `e.add_energy()` | 韧性为 `e.current_toughness` / `e.max_toughness`；速度为只读 `e.speed`；能量直接加减 `e.energy`（受 `e.max_energy` 上限约束）；Status 通过 `sim.status_mgr` 或 `sim.vm_runtime.modifier_engine.get_modifiers(e.name)` 查；`getattr(e, "damage_reduction", 0.0)`；克隆/变身实体务必同步拷贝 `base_white_hp/atk/def/speed` |
| `HealAppliedEvent` | `e.healer_name` / `e.heal_amount` | `e.source_name`、`e.target_name`、`e.amount` |
| `EnemyDefeatedEvent` | `e.enemy_name` / `e.killer_name` | **`e.target_name`**、**`e.attacker_name`** |
| `DamageAppliedEvent` | `e.amount` | **`e.damage`**、`e.attacker_name`、`e.target_name`、`e.damage_type` |
| `DamageHit`（`golden_diff.py`） | `d.target` | 仅含 `d.attacker`, `d.damage_type`, `d.damage`（无 `target` 字段） |
| `DamageBreakdown` | `bd.base_damage` / `bd.toughness_mult` | 属性为 `bd.base_dmg` 等（查看 `simulator/damage.py` 定义） |
| `battle_*.jsonl` `OnDamage` | `data["damage_type"]`、`data["attacker"]["name"]` | 伤害类型字段是 **`data["type"]`**；`attacker` / `turn_owner` 仅含 `{"team", "uid"}`（无 `name`，敌方 `name` 需从 `OnInitializeEnemy` 建映射） |

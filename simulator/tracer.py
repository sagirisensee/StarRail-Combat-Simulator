# coding: utf-8
"""星穹铁道战斗模拟系统 - 核心机制变量流转与插件审计追踪器 (Action Causal Tracer)

职责边界 (通用设计, 核心层不感知任何具体角色/光锥/关卡名)：
1. 监听与捕获每次行动中机制变量的流转：变量由各插件通过 KitHandler.trace_variables()
   自行申报 (名称/单位/实时值/达标注记), 追踪器只按申报通用渲染；
2. 自动记录触发变量变动的底层插件源：扣血来源 (cause) 的插件描述由来源插件自行通过
   ActionCausalTracer.register_cause_plugin() 注册, 追踪器仅保留通用兜底 (如敌方攻击)；
3. 角色专属的报表段落由插件通过 KitHandler.get_trace_panel_section() 自行生成,
   追踪器只负责编号与拼接；
4. 输出高可视度、函数级别的因果流转拓扑树，用于深度对账与机制调试。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable


@dataclass
class VariableDelta:
    entity: str
    var_name: str
    old_val: float
    new_val: float
    delta: float
    source_plugin: str
    cause_desc: str
    extra_note: str = ""


@dataclass
class EnergyDelta:
    entity: str
    old_val: float
    new_val: float
    delta: float
    max_energy: float
    cause_desc: str
    source_plugin: str = ""
    is_ult_ready: bool = False


@dataclass
class PluginRecord:
    plugin_type: str
    plugin_name: str
    summary: str


@dataclass
class TraceVariableSpec:
    """插件自申报的可追踪机制变量 (如某角色的专属资源/层数)。

    - var_name: 变量名 (与 record_var_change 的 var_name 一致)；
    - unit: 数值单位 (如 "点" / "层")；
    - current_value: 实时值读取回调 (本行动无变动时用于展示维持值)；
    - final_note: 最终值注记回调 (如达标提示), 返回空字符串表示无注记。
    """
    var_name: str
    unit: str = "点"
    current_value: Optional[Callable[[], float]] = None
    final_note: Optional[Callable[[float], str]] = None


@dataclass
class ActionTrace:
    actor: str
    action_name: str
    av: float
    cycle: int
    deltas: List[VariableDelta] = field(default_factory=list)
    energy_deltas: List[EnergyDelta] = field(default_factory=list)
    plugins: List[PluginRecord] = field(default_factory=list)


class ActionCausalTracer:
    """全自动行动因果链路与变量审计追踪器。"""

    # 通用兜底的扣血来源描述 (与具体角色/光锥/关卡无关的基础设施条目)。
    # 其余 cause 的插件描述由来源插件在模块加载时通过 register_cause_plugin 自行注册。
    _cause_plugin_registry: Dict[str, Tuple[str, str, str]] = {
        "enemy_attack": ("敌方", "敌方攻击", "受到敌方目标攻击扣除生命值并获得受击能量"),
    }

    @classmethod
    def register_cause_plugin(cls, cause: str, plugin_type: str, plugin_name: str, summary: str) -> None:
        """供来源插件注册其扣血 cause 对应的插件描述 (类型/名称/摘要), 供因果报表引用。"""
        cls._cause_plugin_registry[cause] = (plugin_type, plugin_name, summary)

    @classmethod
    def describe_cause(cls, cause: str) -> Optional[Tuple[str, str, str]]:
        """查询某扣血 cause 的插件描述 (类型/名称/摘要), 未注册返回 None。"""
        return cls._cause_plugin_registry.get(cause)

    def __init__(self, sim: Any = None):
        self.sim = sim
        self.history: List[ActionTrace] = []
        self.current_trace: Optional[ActionTrace] = None
        self.current_hp_cause: str = ""

    def start_action(self, actor: str, action_name: str, av: float, cycle: int = 0) -> None:
        """开启一次新行动的追踪审计记录。"""
        self.current_trace = ActionTrace(actor=actor, action_name=action_name, av=av, cycle=cycle)
        self.current_hp_cause = ""

    def end_action(self) -> None:
        """封存当前行动审计记录并归档至历史记录。"""
        if self.current_trace:
            self.history.append(self.current_trace)

    def record_var_change(
        self,
        entity: str,
        var_name: str,
        old_val: float,
        new_val: float,
        source_plugin: str,
        cause_desc: str,
        extra_note: str = ""
    ) -> None:
        """捕获变量数值跃迁 (插件自申报变量)。"""
        delta = new_val - old_val
        rec = VariableDelta(
            entity=entity,
            var_name=var_name,
            old_val=old_val,
            new_val=new_val,
            delta=delta,
            source_plugin=source_plugin,
            cause_desc=cause_desc,
            extra_note=extra_note
        )
        if self.current_trace is not None:
            self.current_trace.deltas.append(rec)

    def record_energy_change(
        self,
        entity: str,
        old_val: float,
        new_val: float,
        max_energy: float,
        cause_desc: str,
        source_plugin: str = ""
    ) -> None:
        """捕获角色能量数值变动 (获取/受击/消耗/扣除)。"""
        delta = new_val - old_val
        if abs(delta) < 1e-4:
            return
        is_ready = (new_val >= max_energy and old_val < max_energy)
        rec = EnergyDelta(
            entity=entity,
            old_val=old_val,
            new_val=new_val,
            delta=delta,
            max_energy=max_energy,
            cause_desc=cause_desc,
            source_plugin=source_plugin,
            is_ult_ready=is_ready
        )
        if self.current_trace is not None:
            self.current_trace.energy_deltas.append(rec)

    def record_plugin(self, plugin_type: str, plugin_name: str, summary: str) -> None:
        """记录本次行动中生效或被激活的核心插件 (去重)。"""
        if self.current_trace is not None:
            if not any(p.plugin_name == plugin_name for p in self.current_trace.plugins):
                self.current_trace.plugins.append(PluginRecord(plugin_type=plugin_type, plugin_name=plugin_name, summary=summary))

    def record_hp_lost(self, entity_id: str, amount: float, cause: str) -> None:
        """记录生命值减少事件，并关联到来源插件自行注册的描述。"""
        self.current_hp_cause = cause
        desc = self.describe_cause(cause)
        if desc:
            p_type, p_name, p_sum = desc
            self.record_plugin(p_type, p_name, p_sum)

    def _discover_variable_specs(self) -> Dict[Tuple[str, str], "TraceVariableSpec"]:
        """向场上各角色 Kit 收集自申报的可追踪变量 (插件申报, 追踪器不写死任何变量)。"""
        specs: Dict[Tuple[str, str], TraceVariableSpec] = {}
        if not self.sim:
            return specs
        for ent in getattr(self.sim, "entities", []):
            kit = getattr(ent, "kit", None)
            if kit is None or not hasattr(kit, "trace_variables"):
                continue
            try:
                for spec in kit.trace_variables() or []:
                    specs[(ent.name, spec.var_name)] = spec
            except Exception:
                continue
        return specs

    def render_audit_panel(self, trace: Optional[ActionTrace] = None) -> None:
        """渲染高可视度、函数级别的因果流转拓扑面板。"""
        t = trace or self.current_trace or (self.history[-1] if self.history else None)
        if not t:
            print("\n⚠️ 当前无行动因果追踪记录。")
            return

        print("\n" + "=" * 80)
        print("        📋 【核心机制变量流转与插件审计面板】 (Variable Flow & Plugin Audit)")
        print("=" * 80)
        print(f"🕒 [行动时钟]: {t.av:.1f} AV (第 {t.cycle} 轮) │ [当前行动者]: 【{t.actor}】 │ [触发链条]: {t.action_name}")
        print("─" * 80)

        section_no = 0

        def next_heading(title: str) -> None:
            nonlocal section_no
            section_no += 1
            print(f"\n{section_no}. 【{title}】:")

        # 机制变量流转 (按插件自申报通用渲染: 先本行动有变动的变量, 再已申报未变动的变量)
        specs = self._discover_variable_specs()
        grouped: Dict[Tuple[str, str], List[VariableDelta]] = {}
        order: List[Tuple[str, str]] = []
        for d in t.deltas:
            key = (d.entity, d.var_name)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(d)
        for key in specs:
            if key not in grouped:
                grouped[key] = []
                order.append(key)

        for (entity_name, var_name) in order:
            var_deltas = grouped[(entity_name, var_name)]
            spec = specs.get((entity_name, var_name))
            unit = spec.unit if spec else "点"
            next_heading(f"{entity_name} · {var_name}变化流转")
            if var_deltas:
                print(f"   • 起始状态: {int(var_deltas[0].old_val)} {unit}")
                for d in var_deltas:
                    sign = "+" if d.delta > 0 else ""
                    print(f"   ├─ [{d.source_plugin}] {d.cause_desc}")
                    print(f"   │  └─ 实时小计: {int(d.old_val)} ➔ {int(d.new_val)} {unit} ({sign}{int(d.delta)} {unit})")
                    if d.extra_note:
                        print(f"   │     └─ {d.extra_note}")
                final_val = var_deltas[-1].new_val
                note = ""
                if spec and spec.final_note:
                    try:
                        note = spec.final_note(final_val) or ""
                    except Exception:
                        note = ""
                if note:
                    note = f" [{note}]"
                print(f"   └─ 🎯 当前最终{var_name}: {int(final_val)} {unit}{note}")
            else:
                cur = None
                if spec and spec.current_value:
                    try:
                        cur = spec.current_value()
                    except Exception:
                        cur = None
                if cur is not None:
                    print(f"   • 本次行动{var_name}无变动，维持 {int(cur)} {unit}")
                else:
                    print(f"   • 本次行动{var_name}无变动")
        # 全队各角色能量流转 (Energy Flow)
        next_heading("全队角色 · 能量流转审计 (Energy Flow)")
        energy_deltas = t.energy_deltas
        if energy_deltas:
            from collections import defaultdict
            by_entity = defaultdict(list)
            for ed in energy_deltas:
                by_entity[ed.entity].append(ed)

            for ent_name, ed_list in by_entity.items():
                start_e = ed_list[0].old_val
                end_e = ed_list[-1].new_val
                max_e = ed_list[-1].max_energy
                total_d = sum(x.delta for x in ed_list)
                sign = "+" if total_d > 0 else ""
                ready_tag = " [🔥 终结技就绪!]" if end_e >= max_e else ""
                print(f"   • 【{ent_name}】: {start_e:.1f} ➔ {end_e:.1f} / {max_e:.0f} 点 ({sign}{total_d:.1f} 点){ready_tag}")
                for ed in ed_list:
                    d_sign = "+" if ed.delta > 0 else ""
                    src_str = f"[{ed.source_plugin}] " if ed.source_plugin else ""
                    note_str = " [🔥 能量满格!]" if ed.is_ult_ready else ""
                    print(f"     └─ {src_str}{ed.cause_desc} ➔ {d_sign}{ed.delta:.1f} 点 (当前: {ed.new_val:.1f}/{ed.max_energy:.0f}){note_str}")
        else:
            print("   • 本次行动全队能量无变动")

        # 插件自备报表段落 (如某角色的专属矩阵, 由 Kit 通过 get_trace_panel_section 自行生成)
        if self.sim:
            for ent in getattr(self.sim, "entities", []):
                kit = getattr(ent, "kit", None)
                if kit is None or not hasattr(kit, "get_trace_panel_section"):
                    continue
                try:
                    section = kit.get_trace_panel_section()
                except Exception:
                    section = None
                if not section:
                    continue
                title, lines = section
                next_heading(title)
                for line in lines:
                    print(line)

        # 核心插件清单
        next_heading("本次行动过程中激活的核心插件清单 (Active Plugins)")
        if t.plugins:
            for p in t.plugins:
                print(f"   [{p.plugin_type}] {p.plugin_name} ➔ {p.summary}")
        else:
            print("   • 无新增插件被激活")
        print("=" * 80 + "\n")


# 兼容别名: 扣血来源描述注册表 (由各来源插件通过 register_cause_plugin 自行填充)。
CAUSE_PLUGIN_MAP = ActionCausalTracer._cause_plugin_registry


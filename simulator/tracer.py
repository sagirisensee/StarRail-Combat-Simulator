# coding: utf-8
"""星穹铁道战斗模拟系统 - 核心机制变量流转与插件审计追踪器 (Action Causal Tracer)

职责边界：
1. 监听与捕获每回合/每次行动中核心机制变量的流转 (长夜月【忆质】、知更鸟【气氛值】与【律动】、全队【能量 Energy】)；
2. 自动记录触发该变量变动的底层插件源 (光锥/天赋/行迹/关卡机制/忆灵技能/受击机制)；
3. 输出高可视度、函数级别的因果流转拓扑树，用于深度对账与机制调试。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple


CAUSE_PLUGIN_MAP = {
    "LC_MayRainbows_HP_Drain": ("光锥", "《愿虹光永驻天空》 (风堇 S1)", "战技施放消耗全队 1.0% 当前生命值，并施加敌方 18.0% 虹光群体易伤"),
    "stage_mechanic_bleed_turn_begin": ("关卡", "《血噬》 (Stage Mechanic)", "长夜月回合开始受到 500 点环境流血伤害"),
    "enemy_attack": ("敌方", "敌方攻击", "受到敌方目标攻击扣除生命值并获得受击能量"),
    "yika_talent_consume_hp": ("忆灵", "《牵起晴空的手》 (小伊卡 1140903)", "消耗自身生命值为我方生命降低的目标回复生命值"),
}


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
        """捕获变量数值跃迁 (忆质/气氛/律动)。"""
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
        """记录生命值减少事件，并关联到插件源。"""
        self.current_hp_cause = cause
        if cause in CAUSE_PLUGIN_MAP:
            p_type, p_name, p_sum = CAUSE_PLUGIN_MAP[cause]
            self.record_plugin(p_type, p_name, p_sum)

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

        # 1. 忆质
        yizhi_deltas = [d for d in t.deltas if d.var_name == "忆质"]
        print("\n1️⃣  【长夜月 · 忆质变化流转 (Yizhi Flow)】:")
        if yizhi_deltas:
            init_val = yizhi_deltas[0].old_val
            final_val = yizhi_deltas[-1].new_val
            print(f"   • 起始状态: {int(init_val)} 点 (开局受击对账基准)")
            for idx, d in enumerate(yizhi_deltas, 1):
                sign = "+" if d.delta > 0 else ""
                print(f"   ├─ [{d.source_plugin}] {d.cause_desc}")
                print(f"   │  └─ 实时小计: {int(d.old_val)} ➔ {int(d.new_val)} 点 ({sign}{int(d.delta)} 点)")
                if d.extra_note:
                    print(f"   │     └─ {d.extra_note}")
            threshold_tag = " [🌟 已达成 16 质阈值! 解除并免疫控制 / 忆灵「长夜」行动提前 100%]" if final_val >= 16 else ""
            print(f"   └─ 🎯 当前最终忆质: {int(final_val)} 点{threshold_tag}")
        else:
            cy = self.sim.get_entity("长夜月") if self.sim else None
            y = cy.kit.yizhi if (cy and hasattr(cy, "kit") and hasattr(cy.kit, "yizhi")) else 16
            print(f"   • 本次行动忆质无变动，维持 {y} 点")

        # 2. 气氛值
        vibe_deltas = [d for d in t.deltas if d.var_name == "气氛值"]
        print("\n2️⃣  【知更鸟•晴歌 · 气氛值变化流转 (Vibe Flow)】:")
        if vibe_deltas:
            init_val = vibe_deltas[0].old_val
            final_val = vibe_deltas[-1].new_val
            print(f"   • 起始状态: {int(init_val)} 点")
            for idx, d in enumerate(vibe_deltas, 1):
                sign = "+" if d.delta > 0 else ""
                print(f"   ├─ [{d.source_plugin}] {d.cause_desc}")
                print(f"   │  └─ 实时小计: {int(d.old_val)} ➔ {int(d.new_val)} 点 ({sign}{int(d.delta)} 点)")
                if d.extra_note:
                    print(f"   │     └─ {d.extra_note}")
            print(f"   └─ 🎯 当前最终气氛值: {int(final_val)} 点 [全员登台 Fever 狂热维持中]")
        else:
            robin = self.sim.get_entity("知更鸟•晴歌") if self.sim else None
            v = robin.kit.vibes if (robin and hasattr(robin, "kit") and hasattr(robin.kit, "vibes")) else 13
            print(f"   • 本次行动气氛值无变动，维持 {v} 点")

        # 3. 律动层数
        rhythm_deltas = [d for d in t.deltas if d.var_name == "律动层数"]
        print("\n3️⃣  【知更鸟•晴歌 · 律动层数变化流转 (Rhythm Flow)】:")
        if rhythm_deltas:
            init_val = rhythm_deltas[0].old_val
            final_val = rhythm_deltas[-1].new_val
            print(f"   • 起始状态: {int(init_val)} 层")
            for idx, d in enumerate(rhythm_deltas, 1):
                sign = "+" if d.delta > 0 else ""
                print(f"   ├─ [{d.source_plugin}] {d.cause_desc}")
                print(f"   │  └─ 实时小计: {int(d.old_val)} ➔ {int(d.new_val)} 层 ({sign}{int(d.delta)} 层)")
                if d.extra_note:
                    print(f"   │     └─ {d.extra_note}")
            print(f"   └─ 🎯 当前最终律动: {int(final_val)} 层")
        else:
            robin = self.sim.get_entity("知更鸟•晴歌") if self.sim else None
            r = robin.kit.rhythm_stacks if (robin and hasattr(robin, "kit") and hasattr(robin.kit, "rhythm_stacks")) else 11
            print(f"   • 本次行动律动无变动，维持 {r} 层")

        # 4. 全队各角色能量流转 (Energy Flow)
        energy_deltas = t.energy_deltas
        print("\n4️⃣  【全队角色 · 能量流转审计 (Energy Flow)】:")
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

        # 5. 全队偏离和弦 Buff 快照矩阵 (真实快照读取，非全局粗暴覆盖)
        robin = self.sim.get_entity("知更鸟•晴歌") if self.sim else None
        cur_vibes = robin.kit.vibes if (robin and hasattr(robin, "kit") and hasattr(robin.kit, "vibes")) else 11
        robin_atk = 1948.0
        if robin and hasattr(self.sim, "status_mgr"):
            robin_atk = self.sim.status_mgr.get_detailed_snapshot(robin).get("current_atk", 1948.0)

        print("\n5️⃣  【全队各角色 · 偏离和弦 Buff 状态矩阵 (Tonal Chord Matrix)】:")
        print(f"   • 核心机制: 我方目标使知更鸟获气氛值时，根据【触发瞬间的气氛值】快照生成独立 Buff (持续 2 回合)")
        print(f"   • 判定准则: 目标实时攻击 > 知更鸟 ({robin_atk:,.0f}) ? 攻击力加成 (16% + 气氛×0.4%) : 暴击伤害加成 (40% + 气氛×1.5%)")
        print(f"   • 当前知更鸟持有气氛: {cur_vibes} 点 (后续新触发将以此气氛基准实时快照)")
        print("   " + "─" * 78)
        print(f"   {'角色 / 实体':<18} │ {'实时攻击':<10} │ {'触发时机与快照依据':<24} │ {'偏离和弦生效数值与形态'}")
        print("   " + "─" * 78)

        roster = [
            ("【长夜月】", "长夜月", 1443.0, "待行动使知更鸟获气氛"),
            ("【长夜】(伴生忆灵)", "长夜", 1443.0, "0.0 AV 终极爆发 (11气氛)"),
            ("【缇宝】", "缇宝", 1483.0, "0.0 AV 终结技+追击 (10气氛)"),
            ("【知更鸟•晴歌】", "知更鸟•晴歌", robin_atk, "开局秘技后触发 (7气氛)"),
            ("【风堇】", "风堇", 1336.0, "进战开局被动治疗 (1气氛)"),
        ]
        for label, raw_name, default_atk, trigger_info in roster:
            cur_atk = default_atk
            ent = self.sim.get_entity(raw_name) if self.sim else None
            if ent and hasattr(self.sim, "status_mgr"):
                cur_atk = self.sim.status_mgr.get_detailed_snapshot(ent).get("current_atk", default_atk)

            buff = self.sim.status_mgr.get_status(raw_name, f"Robin_Talent_TonalChord_{raw_name}") if self.sim else None
            if buff:
                dur_str = f" [余 {buff.duration} 回合]" if buff.duration is not None else ""
                val_str = f"{buff.description}{dur_str}"
            else:
                val_str = "未激活 (尚未使知更鸟获气氛值)"
            print(f"   {label:<16} │ {cur_atk:>8.0f}   │ {trigger_info:<24} │ {val_str}")
        print("   " + "─" * 78)

        # 6. 核心插件清单
        print("\n6️⃣  【本次行动过程中激活的核心插件清单 (Active Plugins)】:")
        if t.plugins:
            for p in t.plugins:
                print(f"   [{p.plugin_type}] {p.plugin_name} ➔ {p.summary}")
        else:
            print("   • 无新增插件被激活")
        print("=" * 80 + "\n")

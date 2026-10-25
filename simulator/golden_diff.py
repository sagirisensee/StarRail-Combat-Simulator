# coding: utf-8
"""Golden Trace 真值对账工具 (Golden Trace Diff).

用途: 将实机录制的官方战斗日志 (Veritas JSONL, 事件名 OnTurnBegin/OnUseSkill/OnDamage...)
与本模拟器的一场战斗导出为同构的「标准时序」, 再做结构化 diff:
- 回合数 / AV 跨度对照
- 技能施放序列对照 (按角色与技能名统计次数, 并列出仅单边出现的技能)
- 伤害分类分布对照 (DamageType 官方分类占比)
- 角色伤害总账对照 (含偏差百分比)

注意: 本工具做的是序列与分类层面的对账, 不是逐帧回放。敌方阵容细节、玩家操作
输入与随机暴击都会造成数值偏差, 报告中的偏差用于定位机制缺失/多余, 不要求相等。

用法:
    python3 -m simulator.golden_diff battle_logs/battle_20261025_131019.jsonl
    python3 -m simulator.golden_diff <golden.jsonl> --out battle_logs/diff_report.md
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .actions import ActionKind


# 我方 ActionKind -> 官方 OnUseSkill 的 skill.type 对照
SKILL_TYPE_BY_KIND = {
    ActionKind.BASIC: "Normal",
    ActionKind.SKILL: "BPSkill",
    ActionKind.ULTIMATE: "Ultra",
    ActionKind.MEMOSPRITE_SKILL: "Servant",
}

# 官方阵容 uid -> 显示名 (由 OnInitializeEnemy 与技能施放者归纳, 仅用于报告展示)
KNOWN_AVATAR_NAMES = {
    1403: "缇宝",
    1409: "风堇",
    1413: "长夜月",
    1512: "知更鸟•晴歌",
}


@dataclass
class SkillCast:
    actor: str
    name: str
    skill_type: str = "Unknown"
    config_id: Optional[int] = None


@dataclass
class DamageHit:
    attacker: str
    damage_type: str
    damage: float


@dataclass
class TurnRecord:
    index: int
    av: float
    owner: str
    skills: List[SkillCast] = field(default_factory=list)
    damages: List[DamageHit] = field(default_factory=list)

    @property
    def total_damage(self) -> float:
        return sum(d.damage for d in self.damages)


@dataclass
class BattleSequence:
    source: str
    turns: List[TurnRecord] = field(default_factory=list)
    total_damage: float = 0.0
    final_av: float = 0.0
    enemy_names: Dict[int, str] = field(default_factory=dict)

    def damage_by_attacker(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for t in self.turns:
            for d in t.damages:
                out[d.attacker] = out.get(d.attacker, 0.0) + d.damage
        return out

    def hits_by_attacker(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for t in self.turns:
            for d in t.damages:
                out[d.attacker] = out.get(d.attacker, 0) + 1
        return out

    def damage_by_type(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for t in self.turns:
            for d in t.damages:
                out[d.damage_type] = out.get(d.damage_type, 0.0) + d.damage
        return out

    def skill_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for t in self.turns:
            for s in t.skills:
                if s.name:
                    out[f"{s.actor}: {s.name}"] = out.get(f"{s.actor}: {s.name}", 0) + 1
        return out


def _golden_actor_display(uid: Any, team: str, enemy_names: Dict[int, str], dmg_type: str = "") -> str:
    if team == "Enemy":
        return enemy_names.get(uid, f"敌人#{uid}")
    name = KNOWN_AVATAR_NAMES.get(uid, f"UID_{uid}")
    return name


def parse_golden_jsonl(path: str) -> BattleSequence:
    """解析 Veritas 官方 JSONL, 归纳为标准时序。"""
    seq = BattleSequence(source=path)
    enemy_names: Dict[int, str] = {}
    current: Optional[TurnRecord] = None

    def open_turn(av: float, owner: str) -> TurnRecord:
        nonlocal current
        current = TurnRecord(index=len(seq.turns) + 1, av=av, owner=owner)
        seq.turns.append(current)
        return current

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            ev = entry.get("event")
            data = entry.get("data") or {}

            if ev == "OnInitializeEnemy":
                e = data.get("enemy") or {}
                if e.get("uid") is not None:
                    enemy_names[e["uid"]] = e.get("name", f"敌人#{e['uid']}")
            elif ev == "OnTurnBegin":
                owner_ref = data.get("turn_owner")
                if owner_ref:
                    owner = _golden_actor_display(owner_ref.get("uid"), owner_ref.get("team", ""), enemy_names)
                else:
                    owner = "环境/插队"
                open_turn(float(data.get("action_value", 0.0)), owner)
            elif ev == "OnUseSkill":
                if current is None:
                    open_turn(0.0, "环境/插队")
                avatar = data.get("avatar") or {}
                skill = data.get("skill") or {}
                actor = _golden_actor_display(avatar.get("uid"), avatar.get("team", ""), enemy_names)
                # 忆灵技能在官方日志中记在主人 uid 下, 用技能归属的 Servant 类型还原为忆灵显示
                current.skills.append(SkillCast(
                    actor=actor,
                    name=skill.get("name", ""),
                    skill_type=skill.get("type", "Unknown"),
                    config_id=skill.get("skill_config_id"),
                ))
            elif ev == "OnDamage":
                if current is None:
                    open_turn(0.0, "环境/插队")
                attacker = data.get("attacker") or {}
                actor = _golden_actor_display(attacker.get("uid"), attacker.get("team", ""), enemy_names)
                dmg_type = data.get("type", "")
                # 官方将忆灵伤害记在主人名下 (type=Servant), 展示层拆分为忆灵本体
                if attacker.get("team") == "Player" and dmg_type == "Servant":
                    actor = f"{actor} (忆灵)"
                current.damages.append(DamageHit(
                    attacker=actor,
                    damage_type=dmg_type,
                    damage=float(data.get("damage", 0.0)),
                ))
            elif ev == "OnBattleEnd":
                seq.total_damage = float(data.get("total_damage", 0.0))
                seq.final_av = float(data.get("action_value", 0.0))

    if not seq.total_damage:
        seq.total_damage = sum(t.total_damage for t in seq.turns)
    if not seq.final_av and seq.turns:
        seq.final_av = seq.turns[-1].av
    seq.enemy_names = enemy_names
    return seq


def export_sim_sequence(sim: Any, av_budget: float, max_turns: int = 400) -> BattleSequence:
    """运行一场模拟战斗, 将其事件流导出为与官方日志同构的标准时序。

    sim 须为已构造完毕的 TurnSimulator (阵容/敌人由调用方决定)。
    归因规则与官方日志对齐: 技能与伤害记在行动者名下, 终结技插队等回合外
    事件归入当前已开启的回合 (无回合时记为「环境/插队」)。
    """
    from .events import TurnBeginEvent, ActionExecuteEvent, DamageAppliedEvent

    seq = BattleSequence(source="simulator")
    current: Optional[TurnRecord] = None

    # 归因对齐官方日志: 忆灵的技能记在主人名下, 忆灵造成的伤害记为「主人 (忆灵)」
    # 忆灵在战斗中途才被召唤, 实体查询必须惰性执行 (带缓存, 未命中时刷新)
    ent_cache: Dict[str, Any] = {}

    def lookup_entity(name: str):
        if name not in ent_cache:
            for ent in getattr(sim, "entities", []):
                ent_cache[ent.name] = ent
        return ent_cache.get(name)

    def skill_actor(name: str) -> str:
        ent = lookup_entity(name)
        if ent is not None and getattr(ent, "is_memosprite", False):
            return getattr(ent, "master_name", None) or name
        return name

    def damage_actor(name: str, dtype_value: str) -> str:
        ent = lookup_entity(name)
        if ent is not None and getattr(ent, "is_memosprite", False):
            master = getattr(ent, "master_name", None) or name
            return f"{master} (忆灵)"
        if dtype_value == "Servant":
            return f"{name} (忆灵)"
        return name

    def open_turn(av: float, owner: str) -> TurnRecord:
        nonlocal current
        current = TurnRecord(index=len(seq.turns) + 1, av=av, owner=owner)
        seq.turns.append(current)
        return current

    def on_turn_begin(e: TurnBeginEvent) -> None:
        open_turn(float(getattr(e, "av", 0.0)), e.actor_name)

    def on_action(e: ActionExecuteEvent) -> None:
        if current is None:
            open_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        actor_ent = lookup_entity(e.actor_name)
        if actor_ent is not None and getattr(actor_ent, "is_countdown", False):
            return  # 倒计时实体的结算是内部机制, 官方日志不记为技能施放
        kind = getattr(e, "action_kind", None)
        raw_name = e.action_type or ""
        if raw_name == "FollowUpAttack":
            raw_name = ""  # 追击合成事件只是类型标记, 不是具名技能
        elif raw_name.startswith("Ultimate (") and raw_name.endswith(")"):
            raw_name = raw_name[len("Ultimate ("):-1]
        current.skills.append(SkillCast(
            actor=skill_actor(e.actor_name),
            name=raw_name,
            skill_type=SKILL_TYPE_BY_KIND.get(kind, "Unknown"),
        ))

    def on_damage(e: DamageAppliedEvent) -> None:
        if current is None:
            open_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        dtype = getattr(e, "damage_type", None)
        dtype_value = getattr(dtype, "value", "Direct")
        current.damages.append(DamageHit(
            attacker=damage_actor(e.attacker_name, dtype_value),
            damage_type=dtype_value,
            damage=float(e.damage),
        ))

    sim.event_bus.subscribe(TurnBeginEvent, on_turn_begin)
    sim.event_bus.subscribe(ActionExecuteEvent, on_action)
    sim.event_bus.subscribe(DamageAppliedEvent, on_damage)

    steps = 0
    while steps < max_turns * 4 and len(seq.turns) <= max_turns:
        sim.step()
        steps += 1
        if float(getattr(sim, "current_av", 0.0)) > av_budget:
            break

    seq.total_damage = sum(t.total_damage for t in seq.turns)
    seq.final_av = float(getattr(sim, "current_av", 0.0))
    return seq


def diff_sequences(golden: BattleSequence, sim: BattleSequence) -> Dict[str, Any]:
    """对两条标准时序做结构化 diff, 返回可渲染的报告数据。"""
    g_skills = golden.skill_counts()
    s_skills = sim.skill_counts()
    all_skill_keys = sorted(set(g_skills) | set(s_skills))

    g_types = golden.damage_by_type()
    s_types = sim.damage_by_type()
    all_types = sorted(set(g_types) | set(s_types))

    g_actors = golden.damage_by_attacker()
    s_actors = sim.damage_by_attacker()
    g_hits = golden.hits_by_attacker()
    s_hits = sim.hits_by_attacker()
    all_actors = sorted(set(g_actors) | set(s_actors))

    def pct(part: float, whole: float) -> float:
        return (part / whole * 100.0) if whole > 0 else 0.0

    return {
        "golden_turns": len(golden.turns),
        "sim_turns": len(sim.turns),
        "golden_final_av": golden.final_av,
        "sim_final_av": sim.final_av,
        "golden_total_damage": golden.total_damage,
        "sim_total_damage": sim.total_damage,
        "skills": [
            {"key": k, "golden": g_skills.get(k, 0), "sim": s_skills.get(k, 0)}
            for k in all_skill_keys
        ],
        "damage_types": [
            {
                "type": t,
                "golden": g_types.get(t, 0.0),
                "sim": s_types.get(t, 0.0),
                "golden_pct": pct(g_types.get(t, 0.0), golden.total_damage),
                "sim_pct": pct(s_types.get(t, 0.0), sim.total_damage),
            }
            for t in all_types
        ],
        "actors": [
            {
                "actor": a,
                "golden": g_actors.get(a, 0.0),
                "sim": s_actors.get(a, 0.0),
                "golden_hits": g_hits.get(a, 0),
                "sim_hits": s_hits.get(a, 0),
                "deviation_pct": ((s_actors.get(a, 0.0) - g_actors.get(a, 0.0)) / g_actors[a] * 100.0) if g_actors.get(a) else None,
            }
            for a in all_actors
        ],
    }


def render_markdown(report: Dict[str, Any], golden_label: str, sim_label: str) -> str:
    lines = []
    lines.append("# Golden Trace 对账报告")
    lines.append("")
    lines.append(f"- 官方真值: {golden_label}")
    lines.append(f"- 本模拟器: {sim_label}")
    lines.append("- 说明: 序列/分类层面对账; 敌方阵容与玩家操作差异会造成数值偏差, 偏差用于定位机制缺失或多余, 不要求相等。")
    lines.append("")
    lines.append("## 一、 总览")
    lines.append("")
    lines.append("| 指标 | 官方 | 模拟 |")
    lines.append("| :--- | ---: | ---: |")
    lines.append(f"| 回合数 | {report['golden_turns']} | {report['sim_turns']} |")
    lines.append(f"| 最终 AV | {report['golden_final_av']:.2f} | {report['sim_final_av']:.2f} |")
    lines.append(f"| 总伤害 | {report['golden_total_damage']:,.0f} | {report['sim_total_damage']:,.0f} |")
    lines.append("")
    lines.append("## 二、 角色伤害总账")
    lines.append("")
    lines.append("| 角色 | 官方伤害 | 模拟伤害 | 偏差% | 官方命中 | 模拟命中 |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |")
    for a in report["actors"]:
        dev = f"{a['deviation_pct']:+.1f}" if a["deviation_pct"] is not None else "-"
        lines.append(f"| {a['actor']} | {a['golden']:,.0f} | {a['sim']:,.0f} | {dev} | {a['golden_hits']} | {a['sim_hits']} |")
    lines.append("")
    lines.append("## 三、 伤害分类分布 (DamageType)")
    lines.append("")
    lines.append("| 类型 | 官方伤害 | 官方占比% | 模拟伤害 | 模拟占比% |")
    lines.append("| :--- | ---: | ---: | ---: | ---: |")
    for t in report["damage_types"]:
        lines.append(f"| {t['type']} | {t['golden']:,.0f} | {t['golden_pct']:.1f} | {t['sim']:,.0f} | {t['sim_pct']:.1f} |")
    lines.append("")
    lines.append("## 四、 技能施放次数")
    lines.append("")
    lines.append("| 技能 | 官方 | 模拟 |")
    lines.append("| :--- | ---: | ---: |")
    for s in report["skills"]:
        lines.append(f"| {s['key']} | {s['golden']} | {s['sim']} |")
    lines.append("")
    return "\n".join(lines)


def build_default_sim(av_budget: float):
    """构造与官方日志同阵容的对照模拟 (敌方为单体高耐久桩, 仅作序列/分类对照)。"""
    from .db.character_db import CharacterDB
    from .core import TurnSimulator, Entity

    db = CharacterDB().load("data/character_db_export.json")
    team = [db.to_combat_entity(n) for n in ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]]
    boss = Entity(
        name="堕神之血•亚婆离",
        base_speed=140.0,
        max_hp=6389558.0,
        current_hp=6389558.0,
        weaknesses=["Ice", "Wind", "Fire", "Imaginary", "Quantum", "Physical", "Thunder"],
        is_enemy=True,
    )
    boss.is_infinite_hp = True
    sim = TurnSimulator(entities=team + [boss], use_techniques=True, auto_ult=True)
    return sim


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Golden Trace 真值对账")
    parser.add_argument("golden", help="官方 Veritas JSONL 路径")
    parser.add_argument("--out", default="", help="报告输出路径 (默认打印到终端)")
    args = parser.parse_args(argv)

    golden = parse_golden_jsonl(args.golden)
    sim = build_default_sim(golden.final_av)
    sim_seq = export_sim_sequence(sim, av_budget=golden.final_av)
    report = diff_sequences(golden, sim_seq)
    md = render_markdown(report, args.golden, "默认对照场景 (同阵容 vs 单体耐久桩)")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"报告已写入 {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


class SequenceRecorder:
    """将一场模拟的事件流记录为与官方日志同构的标准时序 (自由运行与回放共用)。

    归因规则与官方日志对齐: 技能与伤害记在行动者名下, 终结技插队等回合外
    事件归入当前已开启的回合 (无回合时记为「环境/插队」); 忆灵的技能记在
    主人名下, 忆灵造成的伤害记为「主人 (忆灵)」。
    """

    def __init__(self, sim: Any):
        from .events import TurnBeginEvent, ActionExecuteEvent, DamageAppliedEvent

        self.sim = sim
        self.seq = BattleSequence(source="simulator")
        self.current: Optional[TurnRecord] = None
        self.raw_actions: List[Any] = []
        self._ent_cache: Dict[str, Any] = {}
        sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        sim.event_bus.subscribe(ActionExecuteEvent, self._on_action)
        sim.event_bus.subscribe(DamageAppliedEvent, self._on_damage)

    def _lookup_entity(self, name: str):
        if name not in self._ent_cache:
            for ent in getattr(self.sim, "entities", []):
                self._ent_cache[ent.name] = ent
        return self._ent_cache.get(name)

    def _skill_actor(self, name: str) -> str:
        ent = self._lookup_entity(name)
        if ent is not None and getattr(ent, "is_memosprite", False):
            return getattr(ent, "master_name", None) or name
        return name

    def _damage_actor(self, name: str, dtype_value: str) -> str:
        ent = self._lookup_entity(name)
        if ent is not None and getattr(ent, "is_memosprite", False):
            master = getattr(ent, "master_name", None) or name
            return f"{master} (忆灵)"
        if dtype_value == "Servant":
            return f"{name} (忆灵)"
        return name

    def _open_turn(self, av: float, owner: str) -> TurnRecord:
        self.current = TurnRecord(index=len(self.seq.turns) + 1, av=av, owner=owner)
        self.seq.turns.append(self.current)
        return self.current

    def _on_turn_begin(self, e: Any) -> None:
        self._open_turn(float(getattr(e, "av", 0.0)), e.actor_name)

    def _on_action(self, e: Any) -> None:
        self.raw_actions.append(e)
        if self.current is None:
            self._open_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        actor_ent = self._lookup_entity(e.actor_name)
        if actor_ent is not None and getattr(actor_ent, "is_countdown", False):
            return  # 倒计时实体的结算是内部机制, 官方日志不记为技能施放
        kind = getattr(e, "action_kind", None)
        raw_name = e.action_type or ""
        if raw_name == "FollowUpAttack":
            raw_name = ""  # 追击合成事件只是类型标记, 不是具名技能
        elif raw_name.startswith("Ultimate (") and raw_name.endswith(")"):
            raw_name = raw_name[len("Ultimate ("):-1]
        self.current.skills.append(SkillCast(
            actor=self._skill_actor(e.actor_name),
            name=raw_name,
            skill_type=SKILL_TYPE_BY_KIND.get(kind, "Unknown"),
            config_id=(getattr(e, "skill_config_id", 0) or None),
        ))

    def _on_damage(self, e: Any) -> None:
        if self.current is None:
            self._open_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        dtype = getattr(e, "damage_type", None)
        dtype_value = getattr(dtype, "value", "Direct")
        self.current.damages.append(DamageHit(
            attacker=self._damage_actor(e.attacker_name, dtype_value),
            damage_type=dtype_value,
            damage=float(e.damage),
        ))

    def finish(self) -> BattleSequence:
        self.seq.total_damage = sum(t.total_damage for t in self.seq.turns)
        self.seq.final_av = float(getattr(self.sim, "current_av", 0.0))
        return self.seq


def export_sim_sequence(sim: Any, av_budget: float, max_turns: int = 400, director: Any = None) -> BattleSequence:
    """自由运行一场模拟战斗并导出标准时序 (sim 须为已构造完毕的 TurnSimulator)。"""
    recorder = SequenceRecorder(sim)
    seq = recorder.seq
    steps = 0
    idle_steps = 0
    while steps < max_turns * 4 and len(seq.turns) <= max_turns:
        actor = sim.step()
        if director is not None:
            director.after_step()
        steps += 1
        if actor is None:
            idle_steps += 1
            if idle_steps > 100:
                break
        else:
            idle_steps = 0
        if float(getattr(sim, "current_av", 0.0)) > av_budget:
            break
    return recorder.finish()


@dataclass
class Decision:
    """官方日志中的一次玩家决策 (角色回合行动或终结技抢断)。"""
    actor: str
    kind: str  # "basic" | "skill" | "ult"
    skill_id: int
    name: str


@dataclass
class Divergence:
    av: float
    kind: str  # "turn_order" | "ult_blocked" | "ult_failed" | "sp_downgrade" | "script_exhausted"
    detail: str


@dataclass
class Grant:
    """强制回放中为钉死决策而补足的资源 (即模拟自身经济产出与脚本需求的差额)。"""
    av: float
    actor: str
    kind: str  # "energy" | "sp"
    amount: float


@dataclass
class ReplayResult:
    decisions_total: int
    turn_matched: int
    turn_total: int
    ult_matched: int
    ult_total: int
    divergences: List[Divergence] = field(default_factory=list)
    sequence: Optional[BattleSequence] = None
    forced: bool = False
    grants: List[Grant] = field(default_factory=list)


# 官方技能类型 -> 决策类型 (仅玩家四名角色的主动决策; 忆灵技与被动触发为自动行为, 不入脚本)
_DECISION_KIND_BY_TYPE = {"Normal": "basic", "BPSkill": "skill", "Ultra": "ult"}
PLAYER_ACTORS = ("长夜月", "缇宝", "知更鸟•晴歌", "风堇")


def extract_decisions(path: str) -> List[Decision]:
    """从官方 JSONL 提取玩家决策脚本 (按日志顺序)。"""
    decisions: List[Decision] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("event") != "OnUseSkill":
                continue
            data = entry.get("data") or {}
            avatar = data.get("avatar") or {}
            skill = data.get("skill") or {}
            if avatar.get("team") != "Player":
                continue
            actor = KNOWN_AVATAR_NAMES.get(avatar.get("uid"))
            kind = _DECISION_KIND_BY_TYPE.get(skill.get("type"))
            if actor and kind:
                decisions.append(Decision(
                    actor=actor,
                    kind=kind,
                    skill_id=int(skill.get("skill_config_id") or 0),
                    name=skill.get("name", ""),
                ))
    return decisions


def run_replay(sim: Any, director: Any, decisions: List[Decision], av_budget: float, force: bool = False) -> ReplayResult:
    """按官方决策脚本驱动模拟 (回放对齐模式)。

    严格模式 (force=False): 角色回合到来时强制执行脚本中该角色的行动;
    终结技在脚本顺序到达且能量已满时抢断施放。无法对齐之处逐项记为偏离
    (回合顺序不一致 / 终结技能量不足被跳过 / 战技点不足被降级为普攻),
    不伪造执行结果。

    强制模式 (force=True): 决策被钉死 —— 终结技到达脚本时点时若能量不足,
    按缺口补足后施放; 战技点不足时同样补足。每次补足都记入 grants 台账,
    台账即模拟自身资源经济与实机需求之间的量化差额。回合顺序由调度器
    决定, 不在钉死范围内, 仍记为偏离供排查。
    """
    from .actions import ActionKind

    recorder = SequenceRecorder(sim)
    result = ReplayResult(
        decisions_total=len(decisions),
        turn_matched=0,
        turn_total=sum(1 for d in decisions if d.kind != "ult"),
        ult_matched=0,
        ult_total=sum(1 for d in decisions if d.kind == "ult"),
        forced=force,
    )
    # 回放期间关闭自动终结技: 终结技只能由脚本决策触发, 否则计数不可比
    prev_auto_ult = getattr(sim, "auto_ult", None)
    if prev_auto_ult is not None:
        sim.auto_ult = False
    ptr = 0
    steps = 0
    idle_steps = 0

    def note(kind: str, detail: str) -> None:
        result.divergences.append(Divergence(av=float(getattr(sim, "current_av", 0.0)), kind=kind, detail=detail))

    def mark_ult_blocked(d: Decision) -> None:
        ent = sim.get_entity(d.actor)
        have = float(getattr(ent, "energy", 0.0)) if ent else 0.0
        need = float(getattr(ent, "max_energy", 0.0)) if ent else 0.0
        note("ult_blocked", f"{d.actor} 终结技【{d.name}】未能按脚本施放 (能量 {have:.0f}/{need:.0f})")

    def force_cast_ult(d: Decision) -> None:
        """钉死一次终结技决策: 能量按缺口补足 (记台账) 后施放。"""
        ent = sim.get_entity(d.actor)
        if ent is None:
            note("ult_failed", f"{d.actor} 终结技【{d.name}】施放失败 (实体不存在)")
            return
        deficit = float(ent.max_energy) - float(ent.energy)
        if deficit > 1e-4:
            ent.energy = float(ent.max_energy)
            result.grants.append(Grant(av=float(getattr(sim, "current_av", 0.0)), actor=d.actor, kind="energy", amount=deficit))
        if sim.cast_ultimate(d.actor):
            result.ult_matched += 1
            if director is not None:
                director.after_step()
        else:
            note("ult_failed", f"{d.actor} 终结技【{d.name}】能量补足后仍施放失败")

    def force_sp_for_skill(d: Decision) -> None:
        """钉死一次战技决策: 战技点不足时按缺口补足 (记台账)。"""
        sp = getattr(sim, "sp", None)
        if sp is not None and not sp.can_consume(1):
            deficit = 1 - int(sp.current_sp)
            if deficit > 0:
                sp.generate(deficit, d.actor, "回放强制补足", float(getattr(sim, "current_av", 0.0)))
                result.grants.append(Grant(av=float(getattr(sim, "current_av", 0.0)), actor=d.actor, kind="sp", amount=float(deficit)))

    while steps < 1600 and float(getattr(sim, "current_av", 0.0)) <= av_budget:
        steps += 1
        # 1. 脚本头部的终结技: 能量已满则立即抢断施放 (强制模式则补足后施放)
        while ptr < len(decisions) and decisions[ptr].kind == "ult":
            d = decisions[ptr]
            if force:
                force_cast_ult(d)
                ptr += 1
                continue
            ent = sim.get_entity(d.actor)
            if ent is not None and float(getattr(ent, "energy", 0.0)) >= float(getattr(ent, "max_energy", 0.0)) - 1e-4:
                if sim.cast_ultimate(d.actor):
                    result.ult_matched += 1
                    ptr += 1
                    if director is not None:
                        director.after_step()
                    continue
            break
        # 2. 预览下一个行动者
        actor_ent = sim.advance_to_next_turn()
        if actor_ent is None:
            if director is not None:
                director.after_step()
            idle_steps += 1
            if idle_steps > 100:
                break
            continue
        idle_steps = 0
        override = None
        scripted: Optional[Decision] = None
        if actor_ent.name in PLAYER_ACTORS:
            j = ptr
            while j < len(decisions) and decisions[j].kind == "ult":
                j += 1
            if j < len(decisions):
                d = decisions[j]
                if d.actor == actor_ent.name:
                    for k in range(ptr, j):
                        if force:
                            force_cast_ult(decisions[k])
                        else:
                            mark_ult_blocked(decisions[k])
                    ptr = j + 1
                    scripted = d
                    if force and d.kind == "skill":
                        force_sp_for_skill(d)
                    override = ActionKind.SKILL if d.kind == "skill" else ActionKind.BASIC
                    result.turn_matched += 1
                else:
                    note("turn_order", f"回合顺序偏离: 脚本期待 {d.actor} 行动, 实际为 {actor_ent.name}")
            else:
                note("script_exhausted", f"脚本决策已耗尽, {actor_ent.name} 改由默认策略行动")
        actions_before = len(recorder.raw_actions)
        sim.step(action_override=override)
        if director is not None:
            director.after_step()
        # 3. 战技点不足降级检测: 本步内该角色的行动中无一命中脚本技能 ID 才算降级
        # (同一步内可能先有追击/被动事件, 不能只看第一条)
        if scripted is not None and scripted.kind == "skill":
            executed = [a for a in recorder.raw_actions[actions_before:] if a.actor_name == scripted.actor]
            if executed and not any((getattr(a, "skill_config_id", 0) or 0) == scripted.skill_id for a in executed):
                note("sp_downgrade", f"{scripted.actor} 战技【{scripted.name}】未按脚本执行 (实际: {executed[0].action_type})")

    # 脚本尾部未消费的终结技决策
    for k in range(ptr, len(decisions)):
        if decisions[k].kind == "ult":
            if force:
                force_cast_ult(decisions[k])
            else:
                mark_ult_blocked(decisions[k])

    if prev_auto_ult is not None:
        sim.auto_ult = prev_auto_ult
    result.sequence = recorder.finish()
    return result


def render_replay_markdown(result: ReplayResult) -> str:
    lines = []
    title = "## 五、 回放对齐 (按官方决策脚本驱动"
    title += ", 强制模式: 决策钉死)" if result.forced else ")"
    lines.append(title)
    lines.append("")
    lines.append(f"- 决策总数: {result.decisions_total} (回合行动 {result.turn_total}, 终结技 {result.ult_total})")
    lines.append(f"- 回合行动对齐: {result.turn_matched}/{result.turn_total}")
    lines.append(f"- 终结技对齐: {result.ult_matched}/{result.ult_total}")
    lines.append(f"- 偏离记录: {len(result.divergences)} 条")
    lines.append("")
    if result.forced and result.grants:
        lines.append("### 强制补足台账 (模拟自身经济与脚本需求的差额)")
        lines.append("")
        lines.append("| 角色 | 能量补足 (次/总量) | 战技点补足 (次) |")
        lines.append("| :--- | ---: | ---: |")
        actors = sorted({g.actor for g in result.grants})
        for actor in actors:
            eg = [g for g in result.grants if g.actor == actor and g.kind == "energy"]
            sg = [g for g in result.grants if g.actor == actor and g.kind == "sp"]
            lines.append(f"| {actor} | {len(eg)} 次 / {sum(g.amount for g in eg):,.0f} | {len(sg)} 次 |")
        lines.append("")
        lines.append("| AV | 角色 | 类型 | 补足量 |")
        lines.append("| ---: | :--- | :--- | ---: |")
        for g in result.grants:
            lines.append(f"| {g.av:.1f} | {g.actor} | {g.kind} | {g.amount:,.0f} |")
        lines.append("")
    if result.divergences:
        lines.append("| AV | 类型 | 说明 |")
        lines.append("| ---: | :--- | :--- |")
        for d in result.divergences[:30]:
            lines.append(f"| {d.av:.1f} | {d.kind} | {d.detail} |")
        if len(result.divergences) > 30:
            lines.append(f"| ... | ... | 其余 {len(result.divergences) - 30} 条略 |")
        lines.append("")
    return "\n".join(lines)




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


def render_markdown(report: Dict[str, Any], golden_label: str, sim_label: str, replay_md: str = "") -> str:
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
    if replay_md:
        lines.append(replay_md)
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


def build_stage_sim():
    """构造关卡 30510021 的还原对照场景 (敌方构成/HP/波次按实机日志), 返回 (sim, director)。"""
    from .db.character_db import CharacterDB
    from .stage_30510021 import build_stage_30510021

    db = CharacterDB().load("data/character_db_export.json")
    team = [db.to_combat_entity(n) for n in ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]]
    return build_stage_30510021(team)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Golden Trace 真值对账")
    parser.add_argument("golden", help="官方 Veritas JSONL 路径")
    parser.add_argument("--out", default="", help="报告输出路径 (默认打印到终端)")
    parser.add_argument("--replay", action="store_true", help="回放对齐模式: 按日志中的玩家决策脚本驱动模拟")
    parser.add_argument("--force", action="store_true", help="强制回放: 决策钉死, 能量/战技点按缺口补足并记台账 (隐含 --replay)")
    args = parser.parse_args(argv)

    golden = parse_golden_jsonl(args.golden)
    sim, director = build_stage_sim()
    replay_md = ""
    if args.replay or args.force:
        decisions = extract_decisions(args.golden)
        replay = run_replay(sim, director, decisions, av_budget=golden.final_av, force=args.force)
        sim_seq = replay.sequence
        replay_md = render_replay_markdown(replay)
        sim_label = "关卡 30510021 还原场景 + 官方决策脚本回放驱动" + (" (强制钉死)" if args.force else "")
    else:
        sim_seq = export_sim_sequence(sim, av_budget=golden.final_av, director=director)
        sim_label = "关卡 30510021 还原场景 (同阵容, 敌方构成/HP/波次按日志实测)"
    report = diff_sequences(golden, sim_seq)
    md = render_markdown(report, args.golden, sim_label, replay_md=replay_md)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"报告已写入 {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

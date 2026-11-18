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
from typing import Any, Dict, List, Optional, Set, Tuple, Sequence

from .actions import ActionKind
from .events import TurnBeginEvent


# 我方 ActionKind -> 官方 OnUseSkill 的 skill.type 对照
SKILL_TYPE_BY_KIND = {
    ActionKind.BASIC: "Normal",
    ActionKind.SKILL: "BPSkill",
    ActionKind.ULTIMATE: "Ultra",
    ActionKind.MEMOSPRITE_SKILL: "Servant",
    ActionKind.ELATION_SKILL: "ElationDamage",
}

def _load_known_avatar_names() -> Dict[int, str]:
    """从角色数据库自动加载全部 avatar_id -> 角色名映射，避免在通用框架中硬编码阵容。"""
    import os
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "character_db_export.json",
    )
    mapping: Dict[int, str] = {}
    if os.path.exists(db_path):
        with open(db_path, encoding="utf-8") as f:
            raw = json.load(f)
        for ch in raw.get("characters") or ():
            aid = ch.get("avatar_id")
            name = ch.get("name")
            if aid is not None and name:
                mapping[int(aid)] = str(name)
    return mapping


KNOWN_AVATAR_NAMES: Dict[int, str] = _load_known_avatar_names()


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
    sprout_cnt = 0
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
                uid = e.get("uid")
                if uid is not None:
                    ename = e.get("name", f"敌人#{uid}")
                    if ename == "狂兽的胚芽" and uid not in enemy_names:
                        sprout_cnt += 1
                        enemy_names[uid] = f"狂兽的胚芽{sprout_cnt}"
                    else:
                        enemy_names[uid] = ename
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
                seq.final_av = float(data.get("action_value", 0.0))

    if not seq.final_av and seq.turns:
        seq.final_av = seq.turns[-1].av
    if seq.final_av:
        seq.turns = [t for t in seq.turns if t.av <= seq.final_av]
    seq.total_damage = sum(t.total_damage for t in seq.turns)
    seq.enemy_names = enemy_names
    return seq


class SequenceRecorder:
    """将一场模拟的事件流记录为与官方日志同构的标准时序 (自由运行与回放共用)。

    归因规则与官方日志对齐: 技能与伤害记在行动者名下, 终结技插队等回合外
    事件归入当前已开启的回合 (无回合时记为「环境/插队」); 忆灵的技能记在
    主人名下, 忆灵造成的伤害记为「主人 (忆灵)」。
    """

    def __init__(self, sim: Any):
        from .events import TurnBeginEvent, ActionExecuteEvent, DamageAppliedEvent, WeaknessBreakEvent

        self.sim = sim
        self.seq = BattleSequence(source="simulator")
        self.current: Optional[TurnRecord] = None
        self.raw_actions: List[Any] = []
        self._ent_cache: Dict[str, Any] = {}
        sim.event_bus.subscribe(TurnBeginEvent, self._on_turn_begin)
        sim.event_bus.subscribe(ActionExecuteEvent, self._on_action)
        sim.event_bus.subscribe(DamageAppliedEvent, self._on_damage)
        if getattr(sim, "record_break_damage", False):
            sim.event_bus.subscribe(WeaknessBreakEvent, self._on_break)

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

    def _ensure_turn(self, av: float, owner: str) -> TurnRecord:
        if self.current is None or abs(av - self.current.av) > 0.02:
            return self._open_turn(av, owner)
        return self.current

    def _on_action(self, e: Any) -> None:
        self.raw_actions.append(e)
        self._ensure_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        actor_ent = self._lookup_entity(e.actor_name)
        if actor_ent is not None and getattr(actor_ent, "is_countdown", False):
            return  # 倒计时实体的结算是内部机制, 官方日志不记为技能施放
        kind = getattr(e, "action_kind", None)
        raw_name = e.action_type or ""
        if raw_name == "FollowUpAttack" or kind == ActionKind.FOLLOW_UP:
            raw_name = ""  # 追击合成事件只是类型标记, 不是具名技能
        elif raw_name.startswith("Ultimate (") and raw_name.endswith(")"):
            raw_name = raw_name[len("Ultimate ("):-1]
        self.current.skills.append(SkillCast(
            actor=self._skill_actor(e.actor_name),
            name=raw_name,
            skill_type=SKILL_TYPE_BY_KIND.get(kind, "Unknown"),
            config_id=(getattr(e, "skill_config_id", 0) or None),
        ))

    def _is_enemy_actor(self, name: str) -> bool:
        ent = self._lookup_entity(name)
        return bool(ent is not None and getattr(ent, "is_enemy", False))

    def _on_damage(self, e: Any) -> None:
        if self._is_enemy_actor(e.attacker_name):
            return
        self._ensure_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        dtype = getattr(e, "damage_type", None)
        dtype_value = getattr(dtype, "value", "Direct")
        self.current.damages.append(DamageHit(
            attacker=self._damage_actor(e.attacker_name, dtype_value),
            damage_type=dtype_value,
            damage=float(e.damage),
        ))

    def _on_break(self, e: Any) -> None:
        if self._is_enemy_actor(e.breaker_name):
            return
        self._ensure_turn(float(getattr(e, "av", 0.0)), "环境/插队")
        self.current.damages.append(DamageHit(
            attacker=self._skill_actor(e.breaker_name),
            damage_type="Break",
            damage=float(e.break_damage),
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


# 官方技能类型 -> 决策类型 (仅玩家角色本体的主动决策; 忆灵技与被动触发为自动行为, 不入脚本)
_DECISION_KIND_BY_TYPE = {"Normal": "basic", "BPSkill": "skill", "Ultra": "ult"}


def _sim_player_actors(sim: Any) -> Set[str]:
    """从当前模拟器实体列表动态提取我方参战角色本体名集合。"""
    return {
        e.name
        for e in getattr(sim, "entities", ())
        if not getattr(e, "is_enemy", False)
        and not getattr(e, "is_memosprite", False)
        and not getattr(e, "is_countdown", False)
    }


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


def run_replay(sim: Any, director: Any, decisions: List[Decision], av_budget: float, force: bool = False, on_step: Any = None, pre_step: Any = None) -> ReplayResult:
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
        # 0. 步前钩子 (轨迹模式的 AV 延后策略): 返回 True 表示已延后某个实体,
        #    本轮重新预览, 不消耗行动
        if pre_step is not None and pre_step(sim):
            continue
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
        if actor_ent.name in _sim_player_actors(sim):
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
        if on_step is not None:
            on_step(sim)
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


def build_stage_sim(
    team_members: Optional[Sequence[str]] = None,
    log_path: Optional[str] = None,
    technique_users: Optional[Sequence[str]] = None,
):
    """构造关卡 30510021 的还原对照场景 (敌方构成/HP/波次按实机日志), 返回 (sim, director)。"""
    from .db.character_db import CharacterDB
    from .stage_30510021 import build_stage_30510021

    standard_team = ["长夜月", "缇宝", "知更鸟•晴歌", "风堇"]
    if team_members is None:
        if log_path is not None:
            detected_uids = set()
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        ev = d.get("event")
                        data = d.get("data", {})
                        if ev == "OnUseSkill":
                            uid = data.get("avatar", {}).get("uid")
                            if uid:
                                detected_uids.add(uid)
                        elif ev == "OnDamage":
                            uid = data.get("attacker", {}).get("uid")
                            if uid:
                                detected_uids.add(uid)
            except Exception:
                pass
            uid_map = {1413: "长夜月", 1409: "风堇", 1403: "缇宝", 1309: "知更鸟•晴歌", 1512: "知更鸟•晴歌"}
            detected_names = {uid_map[u] for u in detected_uids if u in uid_map}
            if detected_names:
                team_members = [n for n in standard_team if n in detected_names]
        if not team_members:
            team_members = standard_team

    if technique_users is None:
        if log_path is not None and "20261025" in str(log_path):
            technique_users = ["长夜月", "知更鸟•晴歌"]
        else:
            technique_users = [n for n in standard_team if n in team_members]

    db = CharacterDB().load("data/character_db_export.json")
    team = [db.to_combat_entity(n) for n in team_members]
    if db.get("缇宝_旧") is not None:
        old_tb = db.to_combat_entity("缇宝_旧")
        for ent in team:
            if ent.name == "缇宝":
                ent.base_max_hp = old_tb.base_max_hp
                ent.base_atk = old_tb.base_atk
                ent.base_def = old_tb.base_def
                ent.base_speed = old_tb.base_speed
                ent.base_crit_rate = old_tb.base_crit_rate
                ent.base_crit_dmg = old_tb.base_crit_dmg
                ent.current_hp = ent.max_hp
                break
    return build_stage_30510021(team, technique_users=technique_users)


from .plugins.non_crit_ledgers import OFFICIAL_20261026_NON_CRITS, resolve_non_crits


def attach_exact_crit_oracle(
    sim: Any,
    log_path: Optional[str] = None,
    non_crits: Optional[Set[Tuple[int, int]]] = None,
) -> None:
    """挂载精准暴击真值映射器：优先使用插件传入的未暴击台账 non_crits，未传入时按兼容解析器回退。"""
    from .actions import ActionKind
    from .events import ActionExecuteEvent, BattleEvent

    if non_crits is None:
        non_crits = resolve_non_crits(log_path)

    state = {"act_idx": -1, "hit_idx": 0}

    def _on_battle_ev(e: BattleEvent):
        if isinstance(e, ActionExecuteEvent):
            ent = sim.get_entity(e.actor_name)
            if ent is not None and (getattr(ent, "is_countdown", False) or getattr(ent, "is_enemy", False)):
                return
            kind = getattr(e, "action_kind", None)
            if kind not in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.MEMOSPRITE_SKILL):
                return
            raw_name = e.action_type or ""
            if raw_name == "FollowUpAttack" or not raw_name:
                return
            state["act_idx"] += 1
            state["hit_idx"] = 0

    sim.event_bus.subscribe(BattleEvent, _on_battle_ev)

    def _crit_oracle(req: Any) -> bool:
        if getattr(req.attacker, "is_enemy", False) or getattr(req.attacker, "is_countdown", False):
            return False
        h_idx = state["hit_idx"]
        state["hit_idx"] += 1
        if (state["act_idx"], h_idx) in non_crits:
            return False
        return True

    sim.crit_oracle = _crit_oracle


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Golden Trace 真值对账")
    parser.add_argument("golden", help="官方 Veritas JSONL 路径")
    parser.add_argument("--out", default="", help="报告输出路径 (默认打印到终端)")
    parser.add_argument("--replay", action="store_true", help="回放对齐模式: 按日志中的玩家决策脚本驱动模拟")
    parser.add_argument("--force", action="store_true", help="强制回放: 决策钉死, 能量/战技点按缺口补足并记台账 (隐含 --replay)")
    parser.add_argument("--trajectory", action="store_true", help="轨迹回放: 在强制回放之上再钉死忆灵技轨迹, 缺口补足记账 (隐含 --force)")
    parser.add_argument("--align-crit", action="store_true", help="暴击真值对齐模式: 100%% 对齐实战暴击与未暴击段数 (变态对齐)")
    args = parser.parse_args(argv)

    golden = parse_golden_jsonl(args.golden)
    sim, director = build_stage_sim(log_path=args.golden)
    if args.align_crit:
        attach_exact_crit_oracle(sim, log_path=args.golden)
    replay_md = ""
    trajectory_md = ""
    if args.trajectory:
        decisions = extract_decisions(args.golden)
        traj = run_trajectory_replay(sim, director, extract_timeline(args.golden), av_budget=golden.final_av)
        replay = traj.replay
        sim_seq = replay.sequence
        replay_md = render_replay_markdown(replay)
        trajectory_md = render_trajectory_markdown(traj)
        sim_label = "关卡 30510021 还原场景 + 官方轨迹回放驱动 (决策+忆灵技钉死)"
    elif args.replay or args.force:
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
    md += "\n" + render_enemy_activity_markdown(extract_enemy_activity(args.golden))
    if trajectory_md:
        md += "\n" + trajectory_md
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"报告已写入 {args.out}")
    else:
        print(md)
    return 0


def extract_enemy_activity(path: str) -> Dict[str, Any]:
    """从 OnStatChange 提取敌方行动与受击回能 (签名法)。

    Veritas 的 OnDamage 是玩家侧 DPS 统计事件, 只含我方输出; 敌方命中不产生
    OnDamage。敌方行为的可观测签名在 OnStatChange 中: 敌方回合窗口内, 我方
    角色的 CurrentSP (能量在内存协议中序列化为 CurrentSP) 出现约 5.0 x ERR
    的小额增量即受击回能 (多段攻击会合并为其整数倍附近的样本增量)。
    本提取为签名估算: CurrentSP 样本稀疏, 相邻样本间的净增量可能被同窗口
    内的其他能量变动部分抵消, 计数应视为下限。
    """
    import bisect
    import collections
    import json as _json

    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(_json.loads(line))

    owner_at = []
    turn_starts = []
    cur = (None, None)
    for i, e in enumerate(events):
        if e.get("event") == "OnTurnBegin":
            o = e.get("data", {}).get("turn_owner") or {}
            cur = (o.get("team"), o.get("uid"))
            turn_starts.append(i)
        owner_at.append(cur)

    enemy_turns = collections.Counter()
    for i, e in enumerate(events):
        if e.get("event") == "OnTurnBegin":
            o = e.get("data", {}).get("turn_owner") or {}
            if o.get("team") == "Enemy":
                enemy_turns[o.get("uid")] += 1

    sp_series = collections.defaultdict(list)
    for i, e in enumerate(events):
        if e.get("event") == "OnStatChange":
            ent = e.get("data", {}).get("entity") or {}
            prop = e.get("data", {}).get("property") or {}
            if ent.get("team") == "Player" and prop.get("type") == "CurrentSP":
                sp_series[ent.get("uid")].append((i, float(prop.get("value") or 0.0)))

    hit_energy = {}
    targets_per_turn = collections.defaultdict(set)
    for uid, series in sp_series.items():
        prev = 0.0
        count = 0
        total = 0.0
        for i, v in series:
            d = v - prev
            prev = v
            if 3.5 <= d <= 17.0 and i < len(owner_at) and owner_at[i][0] == "Enemy":
                count += 1
                total += d
                t = bisect.bisect_right(turn_starts, i) - 1
                targets_per_turn[t].add(uid)
        if count:
            hit_energy[uid] = {"count": count, "total": round(total, 1)}

    wide_actions = sum(1 for s in targets_per_turn.values() if len(s) >= 3)
    return {
        "enemy_turns": dict(enemy_turns),
        "enemy_turn_total": sum(enemy_turns.values()),
        "hit_energy": hit_energy,
        "hit_energy_total_count": sum(v["count"] for v in hit_energy.values()),
        "hit_energy_total": round(sum(v["total"] for v in hit_energy.values()), 1),
        "wide_actions": wide_actions,
    }


def render_enemy_activity_markdown(activity: Dict[str, Any]) -> str:
    lines = []
    lines.append("## 六、 敌方行动与受击回能 (官方, OnStatChange 签名提取)")
    lines.append("")
    lines.append("- 说明: OnDamage 仅含我方输出 (DPS 统计口径); 敌方命中以 OnStatChange 中")
    lines.append("  CurrentSP 的受击回能签名 (约 5.0 x ERR/段) 提取, 计数为样本口径下限。")
    lines.append(f"- 敌方回合总数: {activity['enemy_turn_total']} (按 uid: {activity['enemy_turns']})")
    lines.append(f"- 受击回能事件: {activity['hit_energy_total_count']} 次, 合计约 {activity['hit_energy_total']:.1f} 点")
    for uid in sorted(activity["hit_energy"]):
        v = activity["hit_energy"][uid]
        lines.append(f"  - uid {uid}: {v['count']} 次 / {v['total']:.1f} 点")
    lines.append(f"- 群体攻击签名 (>=3 名我方同时受击回能的敌方回合): {activity['wide_actions']} 次")
    lines.append("")
    return "\n".join(lines)



# ---------------------------------------------------------------------------
# 轨迹回放: 在强制回放 (玩家决策钉死) 之上, 再把忆灵技的施放轨迹也钉死到
# 官方时点。官方时点到达时若忆灵技尚未自然触发, 则补足前置条件 (忆灵在场 /
# 忆质阈值) 后强制施放, 所有补足逐项记账——台账即"为走完官方轨迹, 模拟
# 自身经济还差多少"。敌方施放不在日志中 (OnUseSkill 仅我方), 敌方仍自由行动。
# ---------------------------------------------------------------------------

SPIRIT_TRAJECTORY_SKILLS = {1141301: "长夜", 1141307: "长夜", 1140901: "小伊卡", 1151201: "晴空乐手"}


@dataclass
class TrajectoryCast:
    av: float
    actor: str
    skill_id: int
    name: str
    order: int = -1


@dataclass
class TrajectoryRecord:
    skill_id: int
    name: str
    official_av: float
    fired_av: Optional[float]
    mode: str  # "organic" | "forced" | "failed" | "unforceable"
    patches: Tuple[str, ...] = ()


@dataclass
class TrajectoryResult:
    replay: Any
    records: List[TrajectoryRecord] = field(default_factory=list)
    master_records: List["MasterRecord"] = field(default_factory=list)
    ult_records: List["MasterRecord"] = field(default_factory=list)
    memoria_granted: float = 0.0
    presence_grants: int = 0
    ult_energy_granted: float = 0.0
    sp_granted: int = 0
    sunk_turns: int = 0


def extract_trajectory(path: str) -> List[TrajectoryCast]:
    """从官方日志提取忆灵技施放轨迹 (AV 来自回合记录, 按 AV 排序)。"""
    seq = parse_golden_jsonl(path)
    out: List[TrajectoryCast] = []
    for t in seq.turns:
        for s in t.skills:
            if s.config_id in SPIRIT_TRAJECTORY_SKILLS:
                out.append(TrajectoryCast(av=float(t.av), actor=SPIRIT_TRAJECTORY_SKILLS[s.config_id], skill_id=s.config_id, name=s.name))
    out.sort(key=lambda c: c.av)
    return out


@dataclass
class TimelineItem:
    av: float
    kind: str  # "basic" | "skill" | "ult" | "spirit"
    actor: str
    skill_id: int
    name: str
    target_ids: Optional[Tuple[str, ...]] = None
    turn_owner: str = ""
    turn_seq: int = 0
    target_uids: Optional[Tuple[int, ...]] = None


@dataclass
class MasterRecord:
    actor: str
    skill_id: int
    name: str
    official_av: float
    fired_av: Optional[float]


def extract_player_target_plan(path: str) -> List[Tuple[int, Tuple[str, ...], Tuple[int, ...]]]:
    """从官方日志提取玩家本体技能目标序列 (按 Normal/BPSkill/Ultra 出现顺序)。"""
    with open(path, "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]

    uid_map = {
        100011: "「灯塔」",
        100015: "「灯塔」",
        100009: "月夜天马",
        100013: "月夜天马",
    }
    guard_names = ["千星戍卫A", "千星戍卫B", "千星戍卫C"]
    guard_cnt = 0
    sprout_cnt = 0
    eagle_cnt = 0
    for e in events:
        if e.get("event") == "OnInitializeEnemy":
            en = e.get("data", {}).get("enemy", {})
            uid = en.get("uid")
            name = en.get("name")
            if name == "流星铁鹰":
                gen = eagle_cnt // 3 + 1
                slot = eagle_cnt % 3 + 1
                uid_map[uid] = f"流星铁鹰_g{gen}_{slot}"
                eagle_cnt += 1
            elif uid not in uid_map:
                if name == "千星戍卫":
                    uid_map[uid] = guard_names[guard_cnt % 3]
                    guard_cnt += 1
                elif name == "堕神之血•亚婆离":
                    uid_map[uid] = "堕神之血•亚婆离"
                elif name == "狂兽的胚芽":
                    sprout_cnt += 1
                    uid_map[uid] = f"狂兽的胚芽{sprout_cnt}"

    def uid_to_name(uid):
        return uid_map.get(uid)

    player_skill_targets = []
    for i, e in enumerate(events):
        if e.get("event") == "OnUseSkill":
            d = e.get("data", {})
            av = d.get("avatar", {})
            s = d.get("skill", {})
            stype = s.get("type")
            if av.get("team") == "Player" and stype in ("Normal", "BPSkill", "Ultra"):
                sid = s.get("skill_config_id")
                hit_uids = []
                if stype == "Ultra" and sid == 151203:
                    for j in range(i + 1, min(i + 25, len(events))):
                        ev2 = events[j]
                        if ev2.get("event") in ("OnUseSkill", "OnTurnBegin"):
                            break
                        if ev2.get("event") == "OnStatChange":
                            d2 = ev2.get("data", {})
                            ent = d2.get("entity", {})
                            prop = d2.get("property", {})
                            if ent.get("team") == "Player" and prop.get("type") == "ActionDelay":
                                u = ent.get("uid")
                                if u is not None:
                                    hit_uids.append(u)
                                    break
                    named_targets = tuple(KNOWN_AVATAR_NAMES[u] for u in hit_uids if u in KNOWN_AVATAR_NAMES)
                    player_skill_targets.append((sid, named_targets, tuple(hit_uids)))
                    continue
                for j in range(i + 1, min(i + 100, len(events))):
                    ev2 = events[j]
                    if ev2.get("event") in ("OnUseSkill", "OnTurnBegin"):
                        break
                    if ev2.get("event") == "OnStatChange":
                        d2 = ev2.get("data", {})
                        ent = d2.get("entity", {})
                        prop = d2.get("property", {})
                        if ent.get("team") == "Enemy" and prop.get("type") == "CurrentHP":
                            u = ent.get("uid")
                            if u not in hit_uids:
                                hit_uids.append(u)
                named_targets = tuple(uid_to_name(u) for u in hit_uids if uid_to_name(u) is not None)
                player_skill_targets.append((sid, named_targets, tuple(hit_uids)))
    return player_skill_targets


def extract_timeline(path: str) -> List[TimelineItem]:
    """从官方日志提取完整施放时间线 (本体决策 + 忆灵技, 含 AV, 按 AV 排序)。

    AV 取施放所在回合的 AV (终结技为其抢断回合的 AV, 与实机记账口径一致)。
    本体决策应与 extract_decisions 的计数一致 (回合 25 + 终结技 27)。
    """
    seq = parse_golden_jsonl(path)
    target_plan = extract_player_target_plan(path)
    target_idx = 0
    items: List[TimelineItem] = []
    for turn_seq, t in enumerate(seq.turns):
        for s in t.skills:
            if s.config_id in SPIRIT_TRAJECTORY_SKILLS:
                items.append(TimelineItem(float(t.av), "spirit", SPIRIT_TRAJECTORY_SKILLS[s.config_id], s.config_id, s.name, turn_owner=t.owner, turn_seq=turn_seq))
            elif s.actor in KNOWN_AVATAR_NAMES.values():
                kind = _DECISION_KIND_BY_TYPE.get(s.skill_type)
                if kind:
                    t_ids = None
                    t_uids = None
                    if target_idx < len(target_plan):
                        p_sid, p_targets, p_uids = target_plan[target_idx]
                        if p_sid == s.config_id and (kind == "basic" or (kind == "ult" and s.config_id == 151203)):
                            if p_targets:
                                t_ids = p_targets
                            if p_uids:
                                t_uids = p_uids
                        target_idx += 1
                    items.append(TimelineItem(float(t.av), kind, s.actor, s.config_id, s.name, target_ids=t_ids, turn_owner=t.owner, turn_seq=turn_seq, target_uids=t_uids))
    items.sort(key=lambda x: x.av)
    return items


def extract_enemy_target_plan(path: str) -> List[Dict[str, Any]]:
    """从官方日志提取确定性敌方行动目标序列 (供轨迹对账 TraceTargetProvider 使用)。"""
    with open(path, "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]

    uid_to_name = {1409: "风堇", 1413: "长夜月", 1403: "缇宝", 1512: "知更鸟•晴歌"}
    plan = []
    cur_turn = None
    last_hp: Dict[int, float] = {}
    current_sp: Dict[int, float] = {}
    sp_at_turn_start: Dict[int, float] = {}
    turn_hp_lost: Set[int] = set()
    for e in events:
        ev = e.get("event")
        data = e.get("data", {})
        if ev == "OnTurnBegin":
            owner = data.get("turn_owner")
            if isinstance(owner, dict) and owner.get("team") == "Enemy":
                cur_turn = {
                    "av": float(data.get("action_value", 0.0)),
                    "enemy_uid": owner.get("uid"),
                    "targets": [],
                    "sub_targets": [],
                    "sub_hp_targets": [],
                    "closed": False,
                }
                plan.append(cur_turn)
                sp_at_turn_start = dict(current_sp)
                turn_hp_lost = set()
            else:
                cur_turn = None
        elif cur_turn is not None and not cur_turn["closed"] and ev == "OnUseSkill":
            avatar = data.get("avatar") or {}
            if avatar.get("team") == "Player":
                cur_turn["closed"] = True
        elif ev == "OnStatChange":
            ent = data.get("entity", {})
            prop = data.get("property", {})
            ptype = prop.get("type")
            val = float(prop.get("value", 0.0) or 0.0)
            uid = ent.get("uid")
            if ent.get("team") == "Player" and ptype == "CurrentHP":
                prev_hp = last_hp.get(uid, val)
                if val > 400.0:
                    last_hp[uid] = val
                if (
                    cur_turn is not None
                    and not cur_turn["closed"]
                    and val > 400.0
                    and val < prev_hp - 100.0
                ):
                    pname = uid_to_name.get(uid)
                    if pname:
                        turn_hp_lost.add(uid)
                        if not cur_turn["sub_hp_targets"]:
                            cur_turn["sub_hp_targets"].append([])
                        cur_turn["sub_hp_targets"][-1].append(pname)
            elif (
                cur_turn is not None
                and not cur_turn["closed"]
                and ent.get("team") == "Enemy"
                and uid == cur_turn["enemy_uid"]
                and ptype == "CurrentSP"
                and val == 0.0
            ):
                cur_turn["sub_targets"].append([])
                cur_turn["sub_hp_targets"].append([])
            elif (
                ent.get("team") == "Player"
                and ptype == "CurrentSP"
            ):
                current_sp[uid] = val
                pname = uid_to_name.get(uid)
                sp_start = sp_at_turn_start.get(uid)
                is_static_residual = (sp_start is not None and abs(val - sp_start) < 1e-4)

                if cur_turn is not None and not cur_turn["closed"] and pname and 0 < val <= 30.0:
                    if is_static_residual and uid not in turn_hp_lost:
                        if cur_turn["av"] < 100.0:
                            actual_target = "小伊卡"
                        else:
                            actual_target = pname
                    else:
                        actual_target = pname

                    cur_turn["targets"].append(actual_target)
                    if not cur_turn["sub_targets"]:
                        cur_turn["sub_targets"].append([])
                    if actual_target not in cur_turn["sub_targets"][-1] or cur_turn["enemy_uid"] in (100009, 100013):
                        cur_turn["sub_targets"][-1].append(actual_target)
    for p in plan:
        if not p["targets"] and p["sub_hp_targets"]:
            for sub in p["sub_hp_targets"]:
                for t in sub:
                    if t not in p["targets"]:
                        p["targets"].append(t)
        for i in range(len(p["sub_targets"])):
            if not p["sub_targets"][i] and i < len(p["sub_hp_targets"]):
                p["sub_targets"][i] = list(dict.fromkeys(p["sub_hp_targets"][i]))
    return plan


def run_trajectory_replay(
    sim: Any,
    director: Any,
    timeline: List[TimelineItem],
    av_budget: float,
    log_path: Optional[str] = None,
) -> TrajectoryResult:
    """轨迹回放 v2: 全施放轨迹按官方 AV 钉死, 缺口补足逐项记账。

    - 本体回合行动: 预览下一行动者 (只读复刻调度器选择规则), 若其排期施放
      尚在未来, 以距离延后把该回合精确推到官方 AV; 迟到则于到达时施放。
    - 终结技: 到官方 AV 时抢断施放, 能量按缺口补足 (记台账)。
    - 忆灵技: 到点未自然触发的补前置 (在场/忆质) 后强制施放; 长夜忆质在
      非排期窗口钳制 15 (超出暂存, 排期点归还) 以防自行乱爆。
    - 敌方施放不在日志中, 敌方仍自由行动。
    """
    from collections import deque

    from .actions import ActionKind
    from .events import ActionExecuteEvent

    result = TrajectoryResult(replay=None)
    if log_path is not None:
        target_plan = extract_enemy_target_plan(log_path)

        def _attacker_matches_uid(attacker: Any, uid: Any) -> bool:
            name = getattr(attacker, "name", "") or ""
            if name == "「灯塔」":
                return uid in (100011, 100015)
            if name == "月夜天马":
                return uid in (100009, 100013)
            if name.startswith("千星戍卫"):
                return uid not in (100009, 100011, 100013, 100015)
            return True

        def _find_turn(now_av: float, attacker: Any = None) -> Optional[Dict[str, Any]]:
            fallback = None
            for p in target_plan:
                if abs(p["av"] - now_av) < 1.0:
                    if attacker is not None and not _attacker_matches_uid(attacker, p.get("enemy_uid")):
                        continue
                    if p["targets"] or p["sub_targets"]:
                        return p
                    if fallback is None:
                        fallback = p
            return fallback

        existing_target_provider = getattr(sim, "target_provider", None)

        def _trace_target_provider(attacker: Any, candidates: List[Any], sub_idx: int = 0) -> Any:
            if existing_target_provider is not None:
                chosen = existing_target_provider(attacker, candidates, sub_idx)
                if chosen is not None:
                    return chosen
            if attacker is not None and not getattr(attacker, "is_enemy", False):
                return None
            now_av = float(getattr(sim, "current_av", 0.0))
            best_turn = _find_turn(now_av, attacker)
            if best_turn:
                subs = best_turn.get("sub_targets") or []
                sub_hps = best_turn.get("sub_hp_targets") or []
                if subs:
                    if sub_idx < len(subs):
                        hp_list = sub_hps[sub_idx] if sub_idx < len(sub_hps) else subs[sub_idx]
                        if getattr(attacker, "is_enemy", False) and not hp_list:
                            memo = next((c for c in candidates if getattr(c, "is_memosprite", False)), None)
                            if memo is not None:
                                return memo
                        if subs[sub_idx]:
                            tname = subs[sub_idx][0]
                            matched = next((c for c in candidates if c.name == tname), None)
                            if matched:
                                return matched
                    return None
                elif sub_idx == 0:
                    tlist = best_turn.get("targets", [])
                    if tlist:
                        tname = tlist[0]
                        matched = next((c for c in candidates if c.name == tname), None)
                        if matched:
                            return matched
                    elif getattr(attacker, "is_enemy", False):
                        memo = next((c for c in candidates if getattr(c, "is_memosprite", False)), None)
                        if memo is not None:
                            return memo
            return candidates[0] if candidates and sub_idx == 0 else None

        def _trace_bounce_provider(attacker: Any, candidates: List[Any], count: int = 10, sub_idx: int = 0) -> List[Any]:
            now_av = float(getattr(sim, "current_av", 0.0))
            best_turn = _find_turn(now_av, attacker)
            if best_turn:
                subs = best_turn.get("sub_targets") or []
                if subs:
                    tlist = subs[sub_idx] if sub_idx < len(subs) and subs[sub_idx] else []
                else:
                    tlist = best_turn.get("targets", []) if sub_idx == 0 else []
                if count <= 0:
                    c_map = {c.name: c for c in candidates}
                    return [c_map[t] for t in dict.fromkeys(tlist) if t in c_map]
                if tlist:
                    res = []
                    c_map = {c.name: c for c in candidates}
                    for tname in tlist:
                        if tname in c_map:
                            res.append(c_map[tname])
                        if len(res) >= count:
                            break
                    while len(res) < count and res:
                        res.append(res[-1])
                    return res
            if count <= 0:
                return list(candidates[:1]) if sub_idx == 0 else []
            return [candidates[i % len(candidates)] for i in range(count)] if sub_idx == 0 else []

        sim.target_provider = _trace_target_provider
        sim.bounce_target_provider = _trace_bounce_provider
        import os

        has_break_in_log = False
        if log_path and os.path.exists(str(log_path)):
            with open(str(log_path), "r", encoding="utf-8") as _bf:
                has_break_in_log = '"type": "Break"' in _bf.read()
        sim.record_break_damage = has_break_in_log
    turn_items = [i for i in timeline if i.kind in ("basic", "skill")]
    ult_queue = deque([(idx, i) for idx, i in enumerate(timeline) if i.kind == "ult"])
    spirit_queues = {}
    for idx, i in enumerate(timeline):
        if i.kind == "spirit":
            spirit_queues.setdefault(i.skill_id, deque()).append(
                TrajectoryCast(av=i.av, actor=i.actor, skill_id=i.skill_id, name=i.name, order=idx))
    master_indices = [idx for idx, i in enumerate(timeline) if i.kind in ("basic", "skill", "ult")]
    turn_indices = [idx for idx, i in enumerate(timeline) if i.kind in ("basic", "skill")]
    fired_master = set()
    organic: List[Tuple[int, float]] = []
    organic_used = set()
    stash = {"amount": 0.0}
    master_fired: List[Tuple[str, int, float]] = []

    def _on_action(e: Any) -> None:
        sid = int(getattr(e, "skill_config_id", 0) or 0)
        if sid in SPIRIT_TRAJECTORY_SKILLS:
            organic.append((sid, float(getattr(e, "av", 0.0))))
        actor = getattr(e, "actor_name", "")
        kind = getattr(e, "action_kind", None)
        if actor in _sim_player_actors(sim) and kind in (ActionKind.BASIC, ActionKind.SKILL, ActionKind.ULTIMATE):
            master_fired.append((actor, sid, float(getattr(e, "av", 0.0))))

    sim.event_bus.subscribe(ActionExecuteEvent, _on_action)

    def _kit_of(entity_name: str) -> Any:
        ent = sim.get_entity(entity_name)
        return getattr(ent, "kit", None) if ent is not None else None

    def _changye_kit() -> Any:
        moon = sim.get_entity("长夜月")
        return getattr(moon, "kit", None) if moon is not None else None

    def _get_vm_memoria() -> float:
        rt = getattr(sim, "vm_runtime", None)
        if rt is None:
            return 0.0
        from .vm.expr import dotnet_hash
        if sim.get_entity("长夜") is not None and "长夜" in rt.entity_dynamics:
            return float(rt.get_dynamic_value("长夜", dotnet_hash("_Partner_Count")))
        if "长夜月" in rt.entity_dynamics:
            return float(rt.get_dynamic_value("长夜月", dotnet_hash("_Partner_Count_Show")))
        return 0.0

    def _set_vm_memoria(val: float) -> None:
        rt = getattr(sim, "vm_runtime", None)
        if rt is None:
            return
        from .vm.expr import dotnet_hash
        v = float(val)
        if "长夜月" in rt.entity_dynamics:
            rt.set_dynamic_value("长夜月", dotnet_hash("_Partner_Count_Show"), v)
        if "长夜" in rt.entity_dynamics:
            rt.set_dynamic_value("长夜", dotnet_hash("_Partner_Count"), v)

    # --- 忆灵技强制施放 (与 v1 相同口径) ---
    def _force_spirit(cast: TrajectoryCast, now_av: float) -> TrajectoryRecord:
        patches: List[str] = []
        sid = cast.skill_id
        organic_before = len(organic)
        rt = getattr(sim, "vm_runtime", None)
        try:
            if rt is not None:
                from .actions import ActionContext
                enemies = tuple(
                    e.name for e in sim.entities
                    if getattr(e, "is_enemy", False) and float(getattr(e, "current_hp", 0.0)) > 0.0
                )
                if sid in (1141301, 1141307):
                    if sim.get_entity("长夜月") is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ())
                    changye_ent = sim.get_entity("长夜")
                    if changye_ent is None or float(getattr(changye_ent, "current_hp", 0.0)) <= 0.0:
                        changye_ent = rt.summon_servant("长夜月", 11413)
                        patches.append("presence")
                        result.presence_grants += 1
                    sim.cancel_immediate_action("长夜")
                    if changye_ent is not None:
                        sim._turn_id += 1
                        sim.event_bus.publish(TurnBeginEvent(
                            av=round(sim.current_av, 2),
                            cycle=sim.current_cycle,
                            actor_id=changye_ent.name,
                            actor_name=changye_ent.name,
                            speed=round(changye_ent.speed, 1),
                            turn_id=sim._turn_id
                        ))
                        sim.run_stage_turn_begin(changye_ent)
                    if sid == 1141307:
                        if stash["amount"] > 0:
                            cur_mem = _get_vm_memoria()
                            _set_vm_memoria(cur_mem + stash["amount"])
                            patches.append(f"stash+{stash['amount']:.0f}")
                            stash["amount"] = 0.0
                        cur_mem = _get_vm_memoria()
                        if cur_mem < 16:
                            deficit = 16 - cur_mem
                            _set_vm_memoria(16.0)
                            patches.append(f"memoria+{deficit:.0f}")
                            result.memoria_granted += deficit
                        rt.trigger_ability(
                            caster_id="长夜",
                            ability_name="Servant_EvernightServant_00_Skill11_Phase01",
                            target_ids=enemies,
                            skill_target_ids=enemies,
                            current_skill_type="Servant",
                            current_attack_type="Servant",
                        )
                        rt.modifier_engine.dispatch_event(
                            "OnListenAfterSkillUse",
                            param_entity_id="长夜",
                            current_skill_type="Servant",
                        )
                        if sim.port.entity_exists("长夜"):
                            sim.port.despawn_spirit("长夜", reason="1141307 自毁离场")
                    else:
                        if changye_ent is None or getattr(changye_ent, "kit", None) is None:
                            return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
                        ctx = ActionContext(action_id="trajectory", actor_id="长夜", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=enemies, skill_id=1141301)
                        changye_ent.kit.execute(ctx)
                elif sid == 1140901:
                    if sim.get_entity("风堇") is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ())
                    ika_ent = sim.get_entity("小伊卡")
                    if ika_ent is None or float(getattr(ika_ent, "current_hp", 0.0)) <= 0.0:
                        ika_ent = rt.summon_servant("风堇", 11409)
                        patches.append("presence")
                        result.presence_grants += 1
                    if ika_ent is None or getattr(ika_ent, "kit", None) is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
                    ctx = ActionContext(action_id="trajectory", actor_id="小伊卡", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=enemies)
                    ika_ent.kit.execute(ctx)
                elif sid == 1151201:
                    ent = sim.get_entity("晴空乐手")
                    if ent is None or getattr(ent, "kit", None) is None:
                        return TrajectoryRecord(sid, cast.name, cast.av, None, "unforceable", ())
                    ctx = ActionContext(action_id="trajectory", actor_id="晴空乐手", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(e.name for e in sim.entities if getattr(e, "is_enemy", False)))
                    ent.kit.execute(ctx)
            elif sid in (1141301, 1141307):
                kit = _changye_kit()
                if kit is None:
                    return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ())
                if sim.get_entity("长夜") is None or not getattr(kit, "spirit_alive", False):
                    kit.summon_spirit()
                    patches.append("presence")
                    result.presence_grants += 1
                # 本次施放由驱动直接补发: 撤销召唤/阈值在行动队列中留下的待服务
                # 立即行动, 避免同一行动被调度器再次服务而重复施放。
                sim.cancel_immediate_action("长夜")
                # 强发的忆灵行动同样是长夜的一次正式行动: 先按自然回合时序结算
                # 关卡机制回合开始钩子 (【血噬】扣 500 → 天赋 +4 忆质计入本次施放),
                # 否则强发路径会绕过扣血与联动入账 (官方她每次行动都吃血噬)。
                changye_ent = sim.get_entity("长夜")
                if changye_ent is not None:
                    sim._turn_id += 1
                    sim.event_bus.publish(TurnBeginEvent(
                        av=round(sim.current_av, 2),
                        cycle=sim.current_cycle,
                        actor_id=changye_ent.name,
                        actor_name=changye_ent.name,
                        speed=round(changye_ent.speed, 1),
                        turn_id=sim._turn_id
                    ))
                    sim.run_stage_turn_begin(changye_ent)
                if sid == 1141307:
                    if stash["amount"] > 0:
                        kit.yizhi = float(kit.yizhi) + stash["amount"]
                        patches.append(f"stash+{stash['amount']:.0f}")
                        stash["amount"] = 0.0
                    if float(getattr(kit, "yizhi", 0)) < 16:
                        deficit = 16 - float(kit.yizhi)
                        kit.yizhi = 16
                        patches.append(f"memoria+{deficit:.0f}")
                        result.memoria_granted += deficit
                    kit.trigger_spirit_burst()
                else:
                    kit._execute_memosprite_skill()
            elif sid == 1140901:
                fkit = _kit_of("风堇")
                if sim.get_entity("小伊卡") is None and fkit is not None:
                    fkit.summon_yika()
                    patches.append("presence")
                    result.presence_grants += 1
                ika_kit = _kit_of("小伊卡")
                if ika_kit is None:
                    return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
                ika_kit.cast_scatter()
            elif sid == 1151201:
                ent = sim.get_entity("晴空乐手")
                if ent is None or getattr(ent, "kit", None) is None:
                    return TrajectoryRecord(sid, cast.name, cast.av, None, "unforceable", ())
                from .actions import ActionContext
                ctx = ActionContext(action_id="trajectory", actor_id="晴空乐手", kind=ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(e.name for e in sim.entities if getattr(e, "is_enemy", False)))
                ent.kit.execute(ctx)
        except Exception:
            return TrajectoryRecord(sid, cast.name, cast.av, None, "failed", tuple(patches))
        resolver = getattr(sim, "resolver", None)
        if resolver is not None:
            resolver.resolve_all()
        sim.port.publish_action(cast.actor, cast.name, ActionKind.MEMOSPRITE_SKILL, skill_id=sid)
        for idx in range(organic_before, len(organic)):
            if organic[idx][0] == sid:
                organic_used.add(idx)
        if director is not None:
            director.after_step()
        return TrajectoryRecord(sid, cast.name, cast.av, now_av, "forced", tuple(patches))

    def _clamp_memoria(now_av: float) -> None:
        q = spirit_queues.get(1141307)
        if not q:
            return
        if getattr(sim, "vm_runtime", None) is not None:
            if sim.get_entity("长夜月") is None:
                return
            cur_mem = _get_vm_memoria()
            if q[0].av - now_av > 10.0 and cur_mem > 15:
                excess = cur_mem - 15
                _set_vm_memoria(15.0)
                stash["amount"] += excess
            elif q[0].av - now_av <= 10.0 and stash["amount"] > 0:
                _set_vm_memoria(int(cur_mem + stash["amount"]))
                stash["amount"] = 0.0
            return
        kit = _changye_kit()
        if kit is None:
            return
        if q[0].av - now_av > 10.0 and float(getattr(kit, "yizhi", 0)) > 15:
            excess = float(kit.yizhi) - 15
            kit.yizhi = 15
            stash["amount"] += excess
        elif q[0].av - now_av <= 10.0 and stash["amount"] > 0:
            kit.yizhi = int(float(kit.yizhi) + stash["amount"])
            stash["amount"] = 0.0
            if hasattr(kit, "_check_threshold"):
                kit._check_threshold()

    def _master_blocked(cast: TrajectoryCast, now_av: float) -> bool:
        """同 AV 顺序闸门: 官方序位在本施放之前、且同簇 (AV 相差 <=0.5) 的本体
        或忆灵技施放尚未落地时, 本忆灵技不得抢先强制——官方节奏里前置技能先
        落地 (再召唤与忆质入账), 后续忆灵技随后施放。超过簇时点 15 AV 仍未落地
        则放行, 避免死锁。"""
        if cast.order < 0 or now_av > cast.av + 15.0:
            return False
        for j in master_indices:
            if j >= cast.order:
                break
            if j not in fired_master and timeline[j].av <= cast.av + 0.5:
                return True
        for other_q in spirit_queues.values():
            if other_q and other_q[0].order < cast.order and abs(other_q[0].av - cast.av) <= 0.5:
                return True
        if cast.skill_id in (1141301, 1141307) and getattr(director, "_pending_transition_sprouts", False):
            return True
        return False

    defer_counts: Dict[Tuple[str, int, float, int], int] = {}

    def _has_zero_av_pending() -> bool:
        """当前 AV 是否仍有 0 行动值（distance_remaining <= 1e-6 或就绪队列非空）的待执行回合。"""
        if getattr(sim, "_ready_queue", ()):
            return True
        peek = sim.peek_next_actor() if hasattr(sim, "peek_next_actor") else None
        return peek is not None and float(getattr(peek, "distance_remaining", 1e9)) <= 1e-6

    def _musician_due() -> bool:
        """晴空乐手的自然回合是否已到期待服务 (距离耗尽或队列待服务)。"""
        ent = sim.get_entity("晴空乐手")
        if ent is None:
            return False
        if ent.name in getattr(sim, "_ready_queue", ()):
            return True
        if float(getattr(ent, "distance_remaining", 1e9)) <= 5.0:
            return True
        peek = sim.peek_next_actor() if hasattr(sim, "peek_next_actor") else None
        return peek is ent

    def _changye_due(sid: int = 1141307) -> bool:
        """长夜的立即行动是否已在就绪队列待服务 (距离耗尽或队列待服务)。
        对 1141307 (迷梦，流失，如露)，还需当前忆质加上回合初血噬 (+4) 可达 16 点阈值，
        否则长夜出队会误放 1141301 (追忆，蹁跹，如雨)。
        """
        ent = sim.get_entity("长夜")
        if ent is None:
            return False
        if sid == 1141307:
            if getattr(sim, "vm_runtime", None) is not None:
                if _get_vm_memoria() + 4 < 16:
                    return False
            else:
                kit = _changye_kit()
                if kit is None or float(getattr(kit, "yizhi", 0)) + 4 < 16:
                    return False
        if ent.name in getattr(sim, "_ready_queue", ()):
            return True
        if float(getattr(ent, "distance_remaining", 1e9)) <= 5.0:
            return True
        peek = sim.peek_next_actor() if hasattr(sim, "peek_next_actor") else None
        return peek is ent

    def _match_organic_spirits() -> None:
        for sid, q in spirit_queues.items():
            while q:
                head = q[0]
                match_idx = None
                for idx, (s2, av2) in enumerate(organic):
                    if idx in organic_used or s2 != sid:
                        continue
                    if av2 >= head.av - 2.0:
                        match_idx = idx
                        break
                    organic_used.add(idx)
                if match_idx is None:
                    break
                organic_used.add(match_idx)
                result.records.append(TrajectoryRecord(sid, head.name, head.av, organic[match_idx][1], "organic", ()))
                q.popleft()

    def _enforce_spirits() -> None:
        now_av = float(getattr(sim, "current_av", 0.0))
        _clamp_memoria(now_av)
        _match_organic_spirits()
        for sid, q in spirit_queues.items():
            while q and q[0].av <= now_av and not _master_blocked(q[0], now_av):
                # 若当前仍有 0 行动值回合待调度（如敌方多段子动收尾或刚召唤的 0 距离忆灵），
                # 或晴空乐手/长夜即将自然出队，先让行给调度器，避免同簇误强发。
                zero_key = ("zero_av", sid, q[0].av, q[0].order)
                if _has_zero_av_pending() and defer_counts.get(zero_key, 0) < 16:
                    defer_counts[zero_key] = defer_counts.get(zero_key, 0) + 1
                    break
                due_key = ("due", sid, q[0].av, q[0].order)
                if (
                    (sid == 1151201 and _musician_due())
                    or (sid in (1141301, 1141307) and _changye_due(sid))
                ) and defer_counts.get(due_key, 0) < 1:
                    defer_counts[due_key] = defer_counts.get(due_key, 0) + 1
                    break
                cast = q.popleft()
                result.records.append(_force_spirit(cast, now_av))

    def _ult_blocked(u_idx: int, u_item: Any, now_av: float, *, allow_cur_enemy: bool = False) -> bool:
        if now_av > u_item.av + 15.0:
            return False
        cur_turn = getattr(sim, "current_turn_entity", None)
        u_owner = getattr(u_item, "turn_owner", "")
        if (
            cur_turn is not None
            and getattr(cur_turn, "is_enemy", False)
            and u_owner in _sim_player_actors(sim)
            and abs(now_av - u_item.av) <= 0.5
        ):
            return True
        if (
            not allow_cur_enemy
            and cur_turn is not None
            and getattr(cur_turn, "is_enemy", False)
            and u_owner
            and u_owner not in _sim_player_actors(sim)
            and abs(now_av - u_item.av) <= 0.5
            and now_av <= u_item.av + 1e-4
            and (
                getattr(cur_turn, "name", "") == u_owner
                if u_owner[-1:].isdigit()
                else getattr(cur_turn, "name", "").startswith(u_owner)
            )
        ):
            return True
        if u_owner and u_owner not in _sim_player_actors(sim) and abs(now_av - u_item.av) <= 0.5:
            if any(
                e is not cur_turn
                and getattr(e, "is_enemy", False)
                and float(getattr(e, "current_hp", 0.0)) > 0.0
                and (
                    getattr(e, "name", "") == u_owner
                    if u_owner[-1:].isdigit()
                    else getattr(e, "name", "").startswith(u_owner)
                )
                and float(getattr(e, "speed", 0.0)) > 0.0
                and now_av + float(getattr(e, "distance_remaining", 0.0)) / float(e.speed) <= u_item.av + 1e-4
                for e in getattr(sim, "entities", ())
            ):
                return True
        if u_owner.startswith("UID_") and now_av < u_item.av - 1e-4:
            return True
        u_turn_seq = getattr(u_item, "turn_seq", 0)
        if (
            u_owner in _sim_player_actors(sim)
            and abs(now_av - u_item.av) <= 0.5
            and (cur_turn is None or getattr(cur_turn, "name", "") != u_owner)
            and any(
                t_idx not in fired_master
                and getattr(timeline[t_idx], "turn_seq", -1) == u_turn_seq
                for t_idx in turn_indices
            )
        ):
            return True
        for t_idx in turn_indices:
            if t_idx >= u_idx:
                break
            if t_idx not in fired_master and abs(timeline[t_idx].av - u_item.av) <= 0.5:
                return True
        mq = spirit_queues.get(1151201)
        if mq and mq[0].order < u_idx and abs(mq[0].av - u_item.av) <= 0.5 and _musician_due():
            return True
        for sid in (1141301, 1141307):
            cq = spirit_queues.get(sid)
            if cq and cq[0].order < u_idx and abs(cq[0].av - u_item.av) <= 0.5 and _changye_due(sid):
                return True
        return False

    def _fire_due_ults(*, allow_cur_enemy: bool = False) -> None:
        now_av = float(getattr(sim, "current_av", 0.0))
        while ult_queue and ult_queue[0][1].av <= now_av + 1e-4 and not _ult_blocked(ult_queue[0][0], ult_queue[0][1], now_av, allow_cur_enemy=allow_cur_enemy):
            _idx, item = ult_queue.popleft()
            fired_master.add(_idx)
            ent = sim.get_entity(item.actor)
            if ent is None:
                result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))
                continue
            deficit = float(ent.max_energy) - float(ent.energy)
            if deficit > 1e-4:
                ent.energy = float(ent.max_energy)
                result.ult_energy_granted += deficit
            ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
            for e in list(getattr(sim, "entities", ())):
                kit = getattr(e, "kit", None)
                if kit is not None and getattr(kit, "_pending_volley", False) and hasattr(kit, "_flush_zone_window"):
                    kit._flush_zone_window()
            if director is not None:
                director.after_step()
            result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, now_av if ok else None))

    def _peek_next() -> Any:
        # 调度预览与 core 的行动队列保持一致 (队列队首优先, 否则距离最近者)
        return sim.peek_next_actor()

    recorder = SequenceRecorder(sim)
    replay = ReplayResult(decisions_total=len(turn_items) + len(ult_queue), turn_matched=0, turn_total=len(turn_items), ult_matched=0, ult_total=len(ult_queue), forced=True)
    prev_auto_ult = getattr(sim, "auto_ult", None)
    if prev_auto_ult is not None:
        sim.auto_ult = False

    def _on_turn_action_completed(actor_ent: Any, *, enemy_only: bool = False) -> None:
        now_av = float(getattr(sim, "current_av", 0.0))
        act_name = getattr(actor_ent, "name", "")
        if enemy_only and not getattr(actor_ent, "is_enemy", False):
            return
        while (
            ult_queue
            and ult_queue[0][1].av <= now_av + 1e-4
            and (
                (
                    not enemy_only
                    and ult_queue[0][1].actor == act_name
                    and getattr(ult_queue[0][1], "turn_owner", "") == act_name
                    and act_name == "缇宝"
                )
                or (
                    getattr(actor_ent, "is_enemy", False)
                    and bool(getattr(ult_queue[0][1], "turn_owner", ""))
                    and (
                        act_name == getattr(ult_queue[0][1], "turn_owner", "")
                        if getattr(ult_queue[0][1], "turn_owner", "")[-1:].isdigit()
                        else act_name.startswith(getattr(ult_queue[0][1], "turn_owner", ""))
                    )
                )
            )
            and not _ult_blocked(ult_queue[0][0], ult_queue[0][1], now_av, allow_cur_enemy=enemy_only)
        ):
            _idx, item = ult_queue.popleft()
            fired_master.add(_idx)
            ent = sim.get_entity(item.actor)
            if ent is not None:
                deficit = float(ent.max_energy) - float(ent.energy)
                if deficit > 1e-4:
                    ent.energy = float(ent.max_energy)
                    result.ult_energy_granted += deficit
                ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
                for e in list(getattr(sim, "entities", ())):
                    kit = getattr(e, "kit", None)
                    if kit is not None and getattr(kit, "_pending_volley", False) and hasattr(kit, "_flush_zone_window"):
                        kit._flush_zone_window()
                if director is not None:
                    director.after_step()
                result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, now_av if ok else None))
            else:
                result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))

    sim.pre_turn_end_hook = lambda actor_ent: _on_turn_action_completed(actor_ent, enemy_only=True)
    sim.turn_action_completed_hook = _on_turn_action_completed
    # 本体排期按角色分队列: 每名角色的回合只在其排期时点 (或迟到时) 发生,
    # 无排期的额外回合直接沉底, 与官方轨迹一一对应
    from collections import defaultdict as _dd
    actor_queues = _dd(deque)
    for idx, i in enumerate(timeline):
        if i.kind in ("basic", "skill"):
            actor_queues[i.actor].append((idx, i))
    steps = 0
    delays = 0
    idle_steps = 0
    if ult_queue and ult_queue[0][1].av <= 1e-4 and getattr(ult_queue[0][1], "turn_owner", "") == "环境/插队":
        _fire_due_ults()
    while steps < 1600 and float(getattr(sim, "current_av", 0.0)) <= av_budget:
        steps += 1
        # A. 延后/沉底策略 (只读预览下一行动者)
        if getattr(sim, "_current_turn_entity", None) is None and delays < 800:
            nxt = _peek_next()
            if nxt is not None and nxt.name in _sim_player_actors(sim):
                land_av = float(getattr(sim, "current_av", 0.0)) + float(nxt.remaining_av)
                q = actor_queues.get(nxt.name)
                if q:
                    head = q[0][1]
                    if head.av > land_av + 1e-4:
                        nxt.distance_remaining += float(nxt.speed) * (head.av - land_av)
                        if nxt.name in getattr(sim, "_ready_queue", ()):
                            sim._ready_queue.remove(nxt.name)
                        delays += 1
                        continue
                    elif head.av < land_av and (land_av - head.av) <= 0.5:
                        nxt.distance_remaining = max(0.0, nxt.distance_remaining - float(nxt.speed) * (land_av - head.av))
                else:
                    # 无剩余排期: 沉底到预算之外, 该角色不再产生额外回合
                    nxt.distance_remaining += float(nxt.speed) * (av_budget - land_av + 1000.0)
                    if nxt.name in getattr(sim, "_ready_queue", ()):
                        sim._ready_queue.remove(nxt.name)
                    result.sunk_turns += 1
                    delays += 1
                    continue
        # B0. 终结技与关卡轮次/阿哈精确 AV 中断: 若下一终结技或关卡轮次边界
        # 落在本次步进的旅行区间内, 先把时钟推进到该时点并结算其效果。
        if getattr(sim, "_current_turn_entity", None) is None:
            while True:
                now0 = float(getattr(sim, "current_av", 0.0))
                landing_av = sim.peek_landing_av()
                ult_av: Optional[float] = None
                if ult_queue:
                    cand_ult = ult_queue[0][1].av
                    if now0 < cand_ult <= landing_av:
                        next_actor = getattr(sim, "peek_next_actor", lambda: None)()
                        blocked_enemy = cand_ult >= landing_av - 0.25 and next_actor is not None and getattr(next_actor, "is_enemy", False)
                        if not blocked_enemy and not (cand_ult >= landing_av - 0.25 and _ult_blocked(ult_queue[0][0], ult_queue[0][1], cand_ult)):
                            ult_av = cand_ult
                dir_av: Optional[float] = None
                if director is not None and hasattr(director, "peek_next_interrupt_av"):
                    dir_av = director.peek_next_interrupt_av(now0, landing_av)
                if ult_av is None and dir_av is None:
                    break
                if dir_av is not None and (ult_av is None or dir_av <= ult_av + 1e-6):
                    sim.advance_clock(dir_av - now0)
                    if hasattr(director, "mark_interrupt_av_checked"):
                        director.mark_interrupt_av_checked(dir_av)
                    director.after_step()
                    _fire_due_ults()
                else:
                    assert ult_av is not None
                    sim.advance_clock(ult_av - now0)
                    if director is not None:
                        director.after_step()
                    _fire_due_ults()
        # B. 检查下一行动者: 若为敌方实体且恰好当前到达终点，让其先执行自然回合，大招在其行动后放行
        next_actor = getattr(sim, "peek_next_actor", lambda: None)()
        if not (next_actor is not None and getattr(next_actor, "is_enemy", False) and ult_queue and abs(ult_queue[0][1].av - float(getattr(sim, "current_av", 0.0))) < 0.25):
            _fire_due_ults()
        # C. 预览并执行回合
        actor_ent = sim.advance_to_next_turn()
        if actor_ent is not None and actor_ent.name == "长夜" and getattr(director, "_pending_transition_sprouts", False):
            boss_ent = sim.get_entity("堕神之血•亚婆离")
            if boss_ent is not None:
                if "堕神之血•亚婆离" in getattr(sim, "_ready_queue", ()):
                    sim._ready_queue.remove("堕神之血•亚婆离")
                sim._ready_queue.insert(0, "长夜")
                sim._current_turn_entity = boss_ent
                actor_ent = boss_ent
        if director is not None:
            director.after_step()
        def _ult_ready_before_enemy_step() -> bool:
            if (
                actor_ent is None
                or not getattr(actor_ent, "is_enemy", False)
                or not getattr(actor_ent, "is_boss", False)
                or not ult_queue
            ):
                return False
            u_item = ult_queue[0][1]
            if u_item.av > float(getattr(sim, "current_av", 0.0)) + 1e-4:
                return False
            u_ent = sim.get_entity(u_item.actor)
            return u_ent is not None and float(u_ent.energy) >= float(u_ent.max_energy) - 1e-6

        _pre_boss_ult = _ult_ready_before_enemy_step()
        if (
            float(getattr(sim, "current_av", 0.0)) < 1e-4
            or (
                actor_ent is not None
                and not getattr(actor_ent, "is_enemy", False)
                and ult_queue
                and getattr(ult_queue[0][1], "turn_owner", "") == actor_ent.name
            )
            or _pre_boss_ult
        ):
            _fire_due_ults(allow_cur_enemy=_pre_boss_ult)
        if actor_ent is None or getattr(actor_ent, "current_hp", 0.0) <= 0.0:
            if actor_ent is not None and getattr(sim, "_current_turn_entity", None) is actor_ent:
                sim._current_turn_entity = None
            if director is not None:
                director.after_step()
            idle_steps += 1
            if idle_steps > 100:
                break
            continue
        idle_steps = 0
        override = None
        target_ids = None
        if actor_ent.name in _sim_player_actors(sim):
            q = actor_queues.get(actor_ent.name)
            if q:
                _idx, head = q.popleft()
                fired_master.add(_idx)
                if head.kind == "skill":
                    sp = getattr(sim, "sp", None)
                    if sp is not None and not sp.can_consume(1):
                        deficit = 1 - int(sp.current_sp)
                        if deficit > 0:
                            sp.generate(deficit, head.actor, "轨迹回放强制补足", float(getattr(sim, "current_av", 0.0)))
                            result.sp_granted += deficit
                override = ActionKind.SKILL if head.kind == "skill" else ActionKind.BASIC
                uid_override_map = getattr(sim, "enemy_uid_map", None)
                h_uids = getattr(head, "target_uids", None)
                if uid_override_map and h_uids:
                    mapped = tuple(uid_override_map[u] for u in h_uids if u in uid_override_map)
                    if mapped:
                        target_ids = mapped
                if target_ids is None:
                    raw_tids = getattr(head, "target_ids", None)
                    if raw_tids and all(sim.get_entity(tid) is not None for tid in raw_tids):
                        target_ids = raw_tids
                replay.turn_matched += 1
        if actor_ent.name == "长夜":
            q01 = spirit_queues.get(1141301)
            q07 = spirit_queues.get(1141307)
            cur_av_now = float(getattr(sim, "current_av", 0.0))
            if q01 and q01[0].av <= cur_av_now + 0.05 and (not q07 or (q01[0].av, q01[0].order) < (q07[0].av, q07[0].order)):
                actor_ent._trajectory_skill_id = 1141301
        sim.step(action_override=override, target_ids=target_ids)
        if director is not None:
            director.after_step()
        _match_organic_spirits()
        _fire_due_ults()
        _enforce_spirits()
    # 收尾: 预算内剩余终结技与忆灵技排期
    while ult_queue and ult_queue[0][1].av <= av_budget:
        _idx, item = ult_queue.popleft()
        fired_master.add(_idx)
        ent = sim.get_entity(item.actor)
        if ent is not None:
            ent.energy = float(ent.max_energy)
            ok = sim.cast_ultimate(item.actor, target_ids=getattr(item, "target_ids", None))
            if director is not None:
                director.after_step()
            result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, float(getattr(sim, "current_av", 0.0)) if ok else None))
        else:
            result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))
    while ult_queue:
        _idx, item = ult_queue.popleft()
        result.ult_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, None))
    now_av = float(getattr(sim, "current_av", 0.0))
    for sid, q in spirit_queues.items():
        while q and q[0].av <= av_budget:
            cast = q.popleft()
            result.records.append(_force_spirit(cast, now_av))
        while q:
            cast = q.popleft()
            result.records.append(TrajectoryRecord(sid, cast.name, cast.av, None, "failed", ()))
    if prev_auto_ult is not None:
        sim.auto_ult = prev_auto_ult
    replay.sequence = recorder.finish()
    replay.ult_matched = sum(1 for r in result.ult_records if r.fired_av is not None)
    result.replay = replay
    # 本体回合行动的实际 AV 配对 (按 角色+技能 贪心就近)
    from collections import defaultdict
    fired_by_key = defaultdict(list)
    for actor, sid, av in master_fired:
        fired_by_key[(actor, sid)].append(av)
    for item in turn_items:
        candidates = fired_by_key.get((item.actor, item.skill_id), [])
        fired_av = None
        if candidates:
            best = min(range(len(candidates)), key=lambda i: abs(candidates[i] - item.av))
            fired_av = candidates.pop(best)
        result.master_records.append(MasterRecord(item.actor, item.skill_id, item.name, item.av, fired_av))
    result.records.sort(key=lambda r: r.official_av)
    return result


def render_trajectory_markdown(traj: TrajectoryResult) -> str:
    lines = []
    lines.append("## 七、 轨迹回放 (全轨迹按官方 AV 钉死, 缺口补足记账)")
    lines.append("")
    lines.append("- 说明: 本体回合行动以距离延后精确推到官方 AV, 终结技到点抢断,")
    lines.append("  忆灵技到点未自然触发的补前置后强制施放。敌方施放不在日志中, 敌方仍自由行动。")
    lines.append(f"- 补足台账: 终结技能量 {traj.ult_energy_granted:.0f} 点 / 战技点 {traj.sp_granted} 次 / 忆质 {traj.memoria_granted:.0f} 点 / 忆灵在场补发 {traj.presence_grants} 次")
    lines.append("")
    lines.append("### 本体施放 AV 对齐")
    lines.append("")
    lines.append("| 角色 | 排期 | 已施放 | 平均 |ΔAV| | 最大 |ΔAV| |")
    lines.append("| :--- | ---: | ---: | ---: | ---: |")
    from collections import defaultdict
    by_actor = defaultdict(list)
    for r in traj.master_records:
        by_actor[r.actor].append(r)
    ult_by_actor = defaultdict(list)
    for r in traj.ult_records:
        ult_by_actor[r.actor].append(r)
    for actor in sorted(set(by_actor) | set(ult_by_actor)):
        recs = by_actor.get(actor, []) + ult_by_actor.get(actor, [])
        fired = [r for r in recs if r.fired_av is not None]
        deltas = [abs(r.fired_av - r.official_av) for r in fired]
        mean_d = f"{sum(deltas) / len(deltas):.1f}" if deltas else "-"
        max_d = f"{max(deltas):.1f}" if deltas else "-"
        lines.append(f"| {actor} | {len(recs)} | {len(fired)} | {mean_d} | {max_d} |")
    lines.append("")
    lines.append("### 忆灵技轨迹")
    lines.append("")
    lines.append("| 技能 | 官方 | 自然对齐 | 强制补发 | 失败/不可强制 |")
    lines.append("| :--- | ---: | ---: | ---: | ---: |")
    from collections import Counter
    total = Counter(r.skill_id for r in traj.records)
    modes = Counter((r.skill_id, r.mode) for r in traj.records)
    names = {r.skill_id: r.name for r in traj.records}
    for sid in sorted(total):
        bad = modes.get((sid, "failed"), 0) + modes.get((sid, "unforceable"), 0)
        lines.append(f"| {names[sid]} | {total[sid]} | {modes.get((sid, 'organic'), 0)} | {modes.get((sid, 'forced'), 0)} | {bad} |")
    lines.append("")
    lines.append("### 长夜爆发轨迹 (官方 AV -> 实际 AV)")
    lines.append("")
    for r in [r for r in traj.records if r.skill_id == 1141307]:
        fired = f"{r.fired_av:.1f}" if r.fired_av is not None else "-"
        tag = "" if r.mode == "organic" else f" ({r.mode}{': ' + ', '.join(r.patches) if r.patches else ''})"
        lines.append(f"- {r.official_av:.1f} -> {fired}{tag}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

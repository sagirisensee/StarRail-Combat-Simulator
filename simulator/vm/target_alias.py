"""官方 TargetAlias / TargetType 组合表达式求值器。

支持官方配置中的全部集合组合语法：
- 原子锚点：`Caster`, `ModifierOwnerEntity`, `CasterSummoner`, `CasterServant`, `ParamEntity`, `ParamEntity2`,
  `AbilityTargetEntity`, `AbilityTargetAdjoinEntity`, `AbilityTargetGroup`, `SkillTargetEntityList`,
  `ParamEntitySkillTargetEntityList`, `AttackTargetList`, `CurrentTurnOwnerEntity`, `CurrentAimAtTarget`,
  `AllLightTeam`, `AllTeamMember`, `AllLightTeamWithAllLightTeamUnselectable`, `AllEnemy`, `AllDarkTeam`,
  `AllDarkTeamWithAllDarkTeamUnselectable`, `ServantEntityList`, `LightTeamCenter`, `DarkTeamCenter`, `AllTeamCenter`,
  `LeftToRightLightTeamTarget`, `LevelEntity`, 以及动态注册的 Partner 别名 (如 `RobinS_Partner02`)；
- 集合运算：`A + B`（保序去重并集）、`A - B`（集合差）；
- 链式修饰符：`.GetServant`, `.GetSummoner`, `.RemoveBattleEvent`, `.RemoveServant`,
  `.WithBattleEvent`, `.GetActualOwner`, `.GetDummyCharacter`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass
class ExecutionContext:
    """一次 Ability / Modifier 回调或 Task 执行的运行时上下文。"""
    runtime: Any
    caster_id: str
    ability_name: str = ""
    modifier_owner_id: Optional[str] = None
    modifier_instance: Optional[Any] = None
    ability_target_ids: Tuple[str, ...] = ()
    skill_target_ids: Tuple[str, ...] = ()
    attack_target_ids: Tuple[str, ...] = ()
    param_entity_id: Optional[str] = None
    param_entity2_id: Optional[str] = None
    param_skill_targets: Tuple[str, ...] = ()
    template_param_targets: Tuple[str, ...] = ()
    local_dynamics: Dict[int, float] = field(default_factory=dict)
    damage_data: Optional[Dict[str, Any]] = None
    heal_data: Optional[Dict[str, Any]] = None
    callback_modifier_name: str = ""
    callback_behavior_flags: Tuple[str, ...] = ()
    change_value: float = 0.0
    param_flags: Tuple[str, ...] = ()
    current_skill_type: str = ""
    current_attack_type: str = ""

    def clone(self, **overrides: Any) -> "ExecutionContext":
        data = {
            "runtime": self.runtime,
            "caster_id": self.caster_id,
            "ability_name": self.ability_name,
            "modifier_owner_id": self.modifier_owner_id,
            "modifier_instance": self.modifier_instance,
            "ability_target_ids": self.ability_target_ids,
            "skill_target_ids": self.skill_target_ids,
            "attack_target_ids": self.attack_target_ids,
            "param_entity_id": self.param_entity_id,
            "param_entity2_id": self.param_entity2_id,
            "param_skill_targets": self.param_skill_targets,
            "template_param_targets": self.template_param_targets,
            "local_dynamics": dict(self.local_dynamics),
            "damage_data": self.damage_data,
            "heal_data": self.heal_data,
            "callback_modifier_name": self.callback_modifier_name,
            "callback_behavior_flags": self.callback_behavior_flags,
            "change_value": self.change_value,
            "param_flags": self.param_flags,
            "current_skill_type": self.current_skill_type,
            "current_attack_type": self.current_attack_type,
        }
        data.update(overrides)
        return ExecutionContext(**data)


def _dedup_preserve(items: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _is_alive_entity(sim: Any, ent: Any) -> bool:
    return bool(ent is not None and (getattr(ent, "current_hp", 0.0) > 0 or getattr(ent, "is_infinite_hp", False)))


def _is_battle_event(ent: Any) -> bool:
    return bool(getattr(ent, "is_countdown", False) or getattr(ent, "is_battle_event", False))


def _resolve_single_token(token: str, ctx: ExecutionContext) -> List[str]:
    """解析去除空白和 +/- 后的单个原子或带点修饰符表达式。"""
    parts = [p.strip() for p in token.split(".") if p.strip()]
    if not parts:
        return []

    base = parts[0]
    rt = ctx.runtime
    sim = rt.sim

    def _alive_avatars(include_unselectable: bool = False) -> List[str]:
        res = []
        for e in sim.entities:
            if getattr(e, "is_enemy", False) or getattr(e, "is_memosprite", False):
                continue
            if not _is_alive_entity(sim, e):
                continue
            if _is_battle_event(e):
                continue
            if not include_unselectable and (getattr(e, "is_unselectable", False) or getattr(e, "is_proxy", False)):
                continue
            res.append(e.name)
        return res

    def _alive_allies(include_unselectable: bool = False, include_countdown: bool = True) -> List[str]:
        res = []
        for e in sim.entities:
            if getattr(e, "is_enemy", False):
                continue
            if not _is_alive_entity(sim, e):
                continue
            if not include_countdown and _is_battle_event(e):
                continue
            if not include_unselectable and (getattr(e, "is_unselectable", False) or getattr(e, "is_proxy", False)):
                continue
            res.append(e.name)
        return res

    def _alive_enemies(
        include_unselectable: bool = False,
        include_countdown: bool = True,
        spatial_order: bool = False,
    ) -> List[str]:
        include_limbo = bool(getattr(rt, "_include_limbo", False))
        has_living_wave_enemy = include_limbo and any(
            getattr(x, "is_enemy", False) and not _is_battle_event(x) and _is_alive_entity(sim, x)
            for x in sim.entities
        )
        matched = []
        for idx, e in enumerate(sim.entities):
            if not getattr(e, "is_enemy", False):
                continue
            if not _is_alive_entity(sim, e):
                if not (
                    has_living_wave_enemy
                    and any(m.owner_id == e.name for m in rt.modifier_engine.all_modifiers())
                ):
                    continue
            if not include_countdown and _is_battle_event(e):
                continue
            if not include_unselectable and getattr(e, "is_unselectable", False):
                continue
            matched.append((idx, e))
        if not spatial_order:
            matched.sort(key=lambda pair: (getattr(pair[1], "_spawn_seq", pair[0]), pair[0]))
        return [e.name for _, e in matched]

    def _servants_of(eid: str) -> List[str]:
        return [
            e.name
            for e in sim.entities
            if getattr(e, "is_memosprite", False)
            and getattr(e, "master_name", None) == eid
            and _is_alive_entity(sim, e)
        ]

    def _summoner_of(eid: str) -> List[str]:
        ent = sim.get_entity(eid)
        if ent is not None and getattr(ent, "master_name", None):
            m = sim.get_entity(ent.master_name)
            if m is not None:
                return [m.name]
        return []

    # 1. 基础锚点求值
    if base == "Caster":
        cur = [ctx.caster_id] if ctx.caster_id else []
    elif base == "ModifierOwnerEntity":
        eid = ctx.modifier_owner_id or ctx.caster_id
        cur = [eid] if eid else []
    elif base == "ModifierOwnerSummoner":
        eid = ctx.modifier_owner_id or ctx.caster_id
        cur = _summoner_of(eid) if eid else []
    elif base == "CasterSummoner":
        cur = _summoner_of(ctx.caster_id) if ctx.caster_id else []
    elif base == "CasterServant":
        cur = _servants_of(ctx.caster_id) if ctx.caster_id else []
    elif base in ("CasterSummonedMinions", "CasterSummonMonster"):
        cur = [
            e.name
            for e in sim.entities
            if getattr(e, "is_enemy", False)
            and getattr(e, "summoner_name", None) == ctx.caster_id
            and _is_alive_entity(sim, e)
        ]
    elif base == "ParamEntity":
        cur = [ctx.param_entity_id] if ctx.param_entity_id else []
    elif base == "ParamEntity2":
        cur = [ctx.param_entity2_id] if ctx.param_entity2_id else []
    elif base == "AbilityTargetEntity":
        cur = list(ctx.ability_target_ids) if ctx.ability_target_ids else ([ctx.caster_id] if ctx.caster_id else [])
    elif base == "AbilityTargetGroup":
        cur = list(ctx.ability_target_ids)
    elif base == "AbilityTargetAdjoinEntity":
        # 相邻目标（在敌/友阵营列表里取主目标左右相邻存活单位）
        if not ctx.ability_target_ids:
            cur = []
        else:
            primary = sim.get_entity(ctx.ability_target_ids[0])
            if primary is None:
                cur = []
            else:
                blast_fn = getattr(sim, "blast_target_provider", None)
                caster_ent = sim.get_entity(ctx.caster_id) if ctx.caster_id else None
                if (
                    not primary.is_enemy
                    and caster_ent is not None
                    and getattr(caster_ent, "is_enemy", False)
                    and callable(blast_fn)
                ):
                    living_allies = [
                        e for e in sim.entities
                        if not e.is_enemy and not getattr(e, "is_countdown", False) and getattr(e, "current_hp", 0.0) > 0.0
                    ]
                    provided = blast_fn(caster_ent, primary, living_allies)
                    if provided is not None:
                        cur = [e.name for e in provided if e is not None and getattr(e, "current_hp", 0.0) > 0.0]
                    else:
                        pool = _alive_allies(include_countdown=False)
                        if primary.name in pool:
                            idx = pool.index(primary.name)
                            adj = []
                            if idx - 1 >= 0:
                                adj.append(pool[idx - 1])
                            if idx + 1 < len(pool):
                                adj.append(pool[idx + 1])
                            cur = adj
                        else:
                            cur = []
                else:
                    pool = _alive_enemies(spatial_order=True) if primary.is_enemy else _alive_allies(include_countdown=False)
                    if primary.name in pool:
                        idx = pool.index(primary.name)
                        adj = []
                        if idx - 1 >= 0:
                            adj.append(pool[idx - 1])
                        if idx + 1 < len(pool):
                            adj.append(pool[idx + 1])
                        cur = adj
                    else:
                        cur = []
    elif base in ("SkillTargetEntityList",):
        cur = list(ctx.skill_target_ids or ctx.ability_target_ids)
    elif base == "ParamEntitySkillTargetEntityList":
        cur = list(ctx.param_skill_targets or ctx.skill_target_ids)
    elif base == "TemplateParamEntityList":
        if ctx.template_param_targets:
            cur = list(ctx.template_param_targets)
        else:
            cur = [ctx.param_entity_id] if ctx.param_entity_id else []
    elif base == "AttackTargetList":
        cur = list(ctx.attack_target_ids or ctx.ability_target_ids)
    elif base == "CurrentTurnOwnerEntity":
        t = getattr(sim, "current_turn_entity", None)
        cur = [t.name] if t is not None else []
    elif base == "CurrentAimAtTarget":
        cur = list(ctx.ability_target_ids[:1])
    elif base == "AllLightTeam":
        cur = _alive_allies(include_unselectable=False, include_countdown=False)
    elif base == "AllTeamMember":
        caster_ent = sim.get_entity(ctx.caster_id) if ctx.caster_id else None
        if caster_ent is not None and getattr(caster_ent, "is_enemy", False):
            cur = _alive_enemies(include_unselectable=False, include_countdown=False)
        else:
            cur = _alive_allies(include_unselectable=False, include_countdown=False)
    elif base == "AllTeammate":
        caster_ent = sim.get_entity(ctx.caster_id) if ctx.caster_id else None
        if caster_ent is not None and getattr(caster_ent, "is_enemy", False):
            team_list = _alive_enemies(include_unselectable=False, include_countdown=False)
        else:
            team_list = _alive_allies(include_unselectable=False, include_countdown=False)
        cur = [eid for eid in team_list if eid != ctx.caster_id]
    elif base == "LeftToRightLightTeamTarget":
        allies = _alive_allies(include_unselectable=False, include_countdown=False)
        avatars = [n for n in allies if not getattr(sim.get_entity(n), "is_memosprite", False)]
        memos = [n for n in allies if getattr(sim.get_entity(n), "is_memosprite", False)]
        # 崩铁阵型：第1个忆灵站最右，第2个忆灵站最左（后续交替左右）
        ordered = list(avatars)
        for idx, m in enumerate(memos):
            if idx % 2 == 0:
                ordered.append(m)
            else:
                ordered.insert(0, m)
        cur = ordered
    elif base == "RightToLeftLightTeamTarget":
        allies = _alive_allies(include_unselectable=False, include_countdown=False)
        avatars = [n for n in allies if not getattr(sim.get_entity(n), "is_memosprite", False)]
        memos = [n for n in allies if getattr(sim.get_entity(n), "is_memosprite", False)]
        ordered = list(avatars)
        for idx, m in enumerate(memos):
            if idx % 2 == 0:
                ordered.append(m)
            else:
                ordered.insert(0, m)
        cur = list(reversed(ordered))
    elif base == "LeftToRightDarkTeamTarget":
        cur = _alive_enemies(include_unselectable=False, include_countdown=False, spatial_order=True)
    elif base == "RightToLeftDarkTeamTarget":
        cur = list(reversed(_alive_enemies(include_unselectable=False, include_countdown=False, spatial_order=True)))
    elif base in (
        "AllLightTeamWithAllLightTeamUnselectable",
        "AllLightTeamWithAllUnselectableLightTeam",
        "AllTeamMemberWithUnselectable",
        "AllTeammateWithUnselectable",
        "TeamFormation",
    ):
        cur = _alive_allies(include_unselectable=True, include_countdown=False)
    elif base == "AllDarkTeam":
        cur = _alive_enemies(include_unselectable=False, include_countdown=False)
    elif base == "AllEnemy":
        caster_ent = sim.get_entity(ctx.caster_id) if ctx.caster_id else None
        if caster_ent is not None and getattr(caster_ent, "is_enemy", False):
            cur = _alive_allies(include_unselectable=False, include_countdown=False)
        else:
            cur = _alive_enemies(include_unselectable=False, include_countdown=False)
    elif base == "AllDarkTeamWithAllDarkTeamUnselectable":
        cur = _alive_enemies(include_unselectable=True, include_countdown=False)
    elif base == "AllEnemyWithUnSelectable":
        caster_ent = sim.get_entity(ctx.caster_id) if ctx.caster_id else None
        if caster_ent is not None and getattr(caster_ent, "is_enemy", False):
            cur = _alive_allies(include_unselectable=True, include_countdown=False)
        else:
            cur = _alive_enemies(include_unselectable=True, include_countdown=False)
    elif base == "ServantEntityList":
        cur = [
            e.name
            for e in sim.entities
            if getattr(e, "is_memosprite", False) and not getattr(e, "is_enemy", False) and _is_alive_entity(sim, e)
        ]
    elif base in ("LightTeamCenter", "DarkTeamCenter", "AllTeamCenter", "LevelEntity"):
        cur = ["__LEVEL__"]
    elif base == "RobinS_Rank01_HighestHPEnemy":
        enemies = [sim.get_entity(n) for n in _alive_enemies()]
        enemies = [e for e in enemies if e is not None]
        cur = [max(enemies, key=lambda e: e.current_hp).name] if enemies else []
    else:
        # 检查动态注册的 Named Target / Partner (如 RobinS_Partner02, RobinS_Partner03)
        named = rt.named_targets.get(base)
        if named:
            cur = [n for n in named if sim.get_entity(n) is not None]
        else:
            ent = sim.get_entity(base)
            cur = [ent.name] if ent is not None else []

    # 2. 链式后缀变换
    for mod in parts[1:]:
        if mod == "GetServant":
            nxt: List[str] = []
            for eid in cur:
                nxt.extend(_servants_of(eid))
            cur = _dedup_preserve(nxt)
        elif mod == "GetSummoner":
            nxt = []
            for eid in cur:
                nxt.extend(_summoner_of(eid))
            cur = _dedup_preserve(nxt)
        elif mod == "RemoveBattleEvent":
            cur = [eid for eid in cur if eid != "__LEVEL__" and not _is_battle_event(sim.get_entity(eid))]
        elif mod == "RemoveUnselectable":
            cur = [
                eid for eid in cur
                if not getattr(sim.get_entity(eid), "unselectable", False)
                and not getattr(sim.get_entity(eid), "is_unselectable", False)
            ]
        elif mod == "GetCharacterChangeTarget":
            nxt = []
            for eid in cur:
                ent = sim.get_entity(eid)
                tid = getattr(ent, "_avatar_change_target_id", None) if ent is not None else None
                if tid and sim.get_entity(tid) is not None:
                    nxt.append(tid)
            cur = _dedup_preserve(nxt)
        elif mod == "GetCharacterChangeSource":
            nxt = []
            for eid in cur:
                ent = sim.get_entity(eid)
                sid = getattr(ent, "_avatar_change_source_id", None) if ent is not None else None
                if sid and sim.get_entity(sid) is not None:
                    nxt.append(sid)
            cur = _dedup_preserve(nxt)
        elif mod == "GetBattleEvent":
            nxt = []
            for eid in cur:
                for e in sim.entities:
                    if getattr(e, "is_countdown", False) and getattr(e, "master_name", None) == eid and _is_alive_entity(sim, e):
                        nxt.append(e.name)
            cur = _dedup_preserve(nxt)
        elif mod in ("GetAliveOnly", "GetAliveOrLimbo"):
            cur = [eid for eid in cur if (e := sim.get_entity(eid)) is not None and e.current_hp > 0.0]
        elif mod == "RemoveServant":
            cur = [eid for eid in cur if not getattr(sim.get_entity(eid), "is_memosprite", False)]
        elif mod == "WithBattleEvent":
            # 保留既有并允许倒计时/场地事件实体
            cur = list(cur)
        elif mod == "GetActualOwner":
            nxt = []
            for eid in cur:
                ent = sim.get_entity(eid)
                if ent is not None and getattr(ent, "master_name", None):
                    nxt.append(ent.master_name)
                else:
                    nxt.append(eid)
            cur = _dedup_preserve(nxt)
        elif mod == "GetDummyCharacter":
            # 若存在配套 dummy/partner 实体则补充，否则空集
            cur = [eid for eid in cur if getattr(sim.get_entity(eid), "is_dummy", False)]
        else:
            raise ValueError(f"未支持的 TargetAlias 后缀修饰符: .{mod} (完整表达式: {token})")

    return cur


def resolve_target_alias(alias: str, ctx: ExecutionContext) -> List[str]:
    """求值完整 TargetAlias 组合表达式（支持 `+` 与 `-`）。"""
    if not alias:
        return []
    # 将 + / - 拆分为运算符和表达式项
    tokens = re.split(r"(\s*[+-]\s*)", alias.strip())
    result: List[str] = []
    op = "+"
    for tok in tokens:
        s = tok.strip()
        if not s:
            continue
        if s in ("+", "-"):
            op = s
            continue
        items = _resolve_single_token(s, ctx)
        if op == "+":
            result = _dedup_preserve(result + items)
        else:
            drop = set(items)
            result = [x for x in result if x not in drop]
    return result


def resolve_target_type(target_spec: Any, ctx: ExecutionContext) -> List[str]:
    """统一求值官方 TargetType 字段（支持字符串、TargetAlias、TargetFetchPartner、TargetConcat、TargetSequence）。"""
    if target_spec is None:
        return [ctx.caster_id] if ctx.caster_id else []
    if isinstance(target_spec, str):
        return resolve_target_alias(target_spec, ctx)
    if not isinstance(target_spec, Mapping):
        return []

    t = target_spec.get("$type", "")
    if t == "RPG.GameCore.TargetAlias" or ("Alias" in target_spec and not t):
        return resolve_target_alias(str(target_spec.get("Alias", "")), ctx)
    if t == "RPG.GameCore.TargetConcat":
        acc: List[str] = []
        for sub in target_spec.get("Targets", []):
            acc = _dedup_preserve(acc + resolve_target_type(sub, ctx))
        return acc
    if t == "RPG.GameCore.TargetFetchPartner":
        # 查找指定 AvatarID / Partner 实体
        bases = resolve_target_type(target_spec.get("BaseTarget") or {"Alias": "Caster"}, ctx)
        partner_id = target_spec.get("PartnerID") or target_spec.get("AvatarID")
        out: List[str] = []
        for b in bases:
            for e in ctx.runtime.sim.entities:
                if not getattr(e, "is_enemy", False):
                    if partner_id and str(getattr(e, "avatar_id", "")) == str(partner_id):
                        out.append(e.name)
        return _dedup_preserve(out)
    if t == "RPG.GameCore.TargetSequence":
        for sub in target_spec.get("Targets", []):
            r = resolve_target_type(sub, ctx)
            if r:
                return r
        return []
    # 默认回退：若含 Alias 字段
    if "Alias" in target_spec:
        return resolve_target_alias(str(target_spec["Alias"]), ctx)
    return []

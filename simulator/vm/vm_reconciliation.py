# coding: utf-8
"""基于官方 ConfigAbility VM 的风堇队全量逐动对账驱动器 (Phase 4)。

用官方 VM (`ConfigAbilityKitAdapter` / `ConfigAbilityLightConeAdapter` / `ConfigAbilityRelicAdapter`)
直接取代手写角色/光锥/遗器处理器，复跑 `FixedReconciliationHarness` 的 5 份官方黄金日志：
- `battle_20261114_184845.jsonl` (缇宝 + 风堇)
- `battle_20261114_204943.jsonl` (风堇 + 晴歌)
- `battle_20261114_220255.jsonl` (缇宝 + 风堇 + 晴歌)
- `battle_20261114_221208.jsonl` (长夜月 + 风堇 + 晴歌)
- `battle_20261115_041608.jsonl` (长夜月 + 缇宝 + 风堇 + 晴歌)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from simulator.actions import ActionContext, ActionKind, DamageType
from simulator.core import TurnSimulator
from simulator.db.character_db import CharacterDB
from simulator.entity import Entity
from simulator.events import (
    ActionEndEvent,
    ActionExecuteEvent,
    DamageAppliedEvent,
    PrimaryDamageCompleteEvent,
    TurnBeginEvent,
    TurnEndEvent,
)
from simulator.golden_diff import attach_exact_crit_oracle
from simulator.plugins.non_crit_ledgers import (
    OFFICIAL_20261114_204943_NON_CRITS,
    OFFICIAL_20261114_220255_NON_CRITS,
    OFFICIAL_20261114_221208_NON_CRITS,
)
from simulator.plugins.log_20261114_184845 import attach_log_20261114_184845_plugin
from simulator.plugins.log_20261114_204943 import attach_log_20261114_204943_plugin
from simulator.plugins.log_20261114_220255 import attach_log_20261114_220255_plugin
from simulator.plugins.log_20261114_221208 import attach_log_20261114_221208_plugin
from simulator.status import DurationTiming, Modifier, ModifierOp, StatType
from simulator.testing.fixed_reconciliation_bench import (
    CHAR_DB_PATH,
    CastReconciliationRecord,
    FixedReconciliationHarness,
    UID_TO_NAME,
)
from simulator.vm import (
    ConfigAbilityKitAdapter,
    ConfigAbilityLightConeAdapter,
    ConfigAbilityRelicAdapter,
    GameDataLoader,
    dotnet_hash,
)
from simulator.vm.factory import TEAM_VM_LOADOUT, build_vm_team


class VMReconciliationHarness(FixedReconciliationHarness):
    """使用官方 ConfigAbility VM 跑通风堇队对账的沙盒驱动器。"""

    def __init__(self, log_path: str, loader: Optional[GameDataLoader] = None):
        super().__init__(log_path)
        self.loader = loader or GameDataLoader()
        self._apoli_p2_idx: Optional[int] = None

    def _detect_formation_uids(self, team_uids: Sequence[int]) -> List[int]:
        """从日志首次风堇战技/终结技治疗的 OnStatChange 顺序提取实机编队站位（如风堇 1409 处于 1 号位）。"""
        in_heal = False
        order: List[int] = []
        allowed = set(team_uids)
        for ev in self.extractor.events:
            et = ev.get("event")
            d = ev.get("data") or {}
            if et == "OnUseSkill" and ((d.get("skill") or {}).get("skill_config_id") in (140902, 140903)):
                in_heal = True
                order = []
                continue
            if in_heal:
                if et == "OnStatChange":
                    ent = d.get("entity") or {}
                    prop = d.get("property") or {}
                    if ent.get("team") == "Player" and prop.get("type") == "CurrentHP":
                        u = ent.get("uid")
                        if u in allowed and u not in order:
                            order.append(u)
                elif et in ("OnUseSkill", "OnTurnBegin"):
                    break
        for u in team_uids:
            if u not in order:
                order.append(u)
        return order

    def _detect_apoli_phase2_idx(self) -> Optional[int]:
        """定位堕神之血•亚婆离 (5034010) 首次进入二阶段 (HP 归零后 CurrentStance 重置为 1080) 的事件索引。"""
        apoli_uids: set[int] = set()
        seen_p1_zero = False
        for idx, ev in enumerate(self.extractor.events):
            et = ev.get("event")
            d = ev.get("data") or {}
            if et == "OnInitializeEnemy" and (d.get("enemy") or {}).get("id") == 5034010:
                u = d["enemy"].get("uid")
                if u is not None:
                    apoli_uids.add(int(u))
            elif et == "OnStatChange" and apoli_uids:
                ent = d.get("entity") or {}
                prop = d.get("property") or {}
                uid = ent.get("uid")
                if uid in apoli_uids:
                    if prop.get("type") == "CurrentHP" and float(prop.get("value", 1.0)) <= 0.0:
                        seen_p1_zero = True
                    elif seen_p1_zero and prop.get("type") == "CurrentStance" and float(prop.get("value", 0.0)) >= 1000.0:
                        return idx
        return None

    def _skill_has_damage_in_log(self, event_idx: int) -> bool:
        for j in range(event_idx + 1, len(self.extractor.events)):
            et = self.extractor.events[j].get("event")
            if et == "OnDamage":
                return True
            if et in ("OnUseSkill", "OnTurnBegin", "OnBattleEnd"):
                break
        return False

    def _build_sandbox(self, team_uids: Sequence[int]) -> Tuple[TurnSimulator, Any]:
        ordered_uids = self._detect_formation_uids(team_uids)
        team = build_vm_team(ordered_uids, loader=self.loader, db_path=CHAR_DB_PATH)
        tech_users = [ent.name for ent in team]

        sim = TurnSimulator(
            entities=team,
            use_techniques=True,
            technique_users=tech_users,
            auto_ult=False,
        )

        non_crits = set()
        if "204943" in self.log_path:
            non_crits = OFFICIAL_20261114_204943_NON_CRITS
        elif "220255" in self.log_path:
            non_crits = OFFICIAL_20261114_220255_NON_CRITS
        elif "221208" in self.log_path:
            non_crits = OFFICIAL_20261114_221208_NON_CRITS
        attach_exact_crit_oracle(sim, log_path=self.log_path, non_crits=non_crits)

        if "184845" in self.log_path:
            attach_log_20261114_184845_plugin(sim)
        elif "204943" in self.log_path:
            attach_log_20261114_204943_plugin(sim)
        elif "220255" in self.log_path:
            attach_log_20261114_220255_plugin(sim)
        elif "221208" in self.log_path:
            attach_log_20261114_221208_plugin(sim)

        # 对齐实机 MaxHP 增益到期（如【雨过天晴】到期 4282.10 -> 2782.10）时按变动前血量百分比等比缩放忆灵 CurrentHP；
        # VM 中 ModifierPhase1End 在 TurnBeginEvent 内通过 tick_life_step 扣减，故在此处包装 tick_life_step。
        rt_init = getattr(sim, "vm_runtime", None)
        if rt_init is not None:
            me_init = rt_init.modifier_engine
            orig_tick = me_init.tick_life_step

            def _wrapped_tick_life_step(moment: str, actor_name: str, *args: Any, **kwargs: Any) -> Any:
                pre_memo = {
                    e.name: (float(e.current_hp), float(sim.port.max_hp(e.name)))
                    for e in sim.entities
                    if not e.is_enemy and sim.port.is_memosprite(e.name) and e.current_hp > 0
                }
                res = orig_tick(moment, actor_name, *args, **kwargs)
                for mname, (old_hp, old_max) in pre_memo.items():
                    m_ent = sim.get_entity(mname)
                    if m_ent is not None and old_max > 0:
                        new_max = float(sim.port.max_hp(mname))
                        if new_max < old_max - 1e-2:
                            m_ent.current_hp = max(1.0, min(new_max, old_hp * (new_max / old_max)))
                return res

            me_init.tick_life_step = _wrapped_tick_life_step  # type: ignore[method-assign]
        return sim, None

    def _run_sim_action(
        self,
        sim: TurnSimulator,
        actor_name: str,
        kind: ActionKind,
        target_ids: Tuple[str, ...] = (),
        pre_hp_sync: Optional[Dict[str, float]] = None,
        skill_id: int = 0,
    ) -> None:
        super()._run_sim_action(sim, actor_name, kind, target_ids=target_ids, pre_hp_sync=pre_hp_sync, skill_id=skill_id)
        is_turn = kind in (ActionKind.BASIC, ActionKind.SKILL) or (kind == ActionKind.MEMOSPRITE_SKILL and actor_name != "小伊卡")
        ent = sim.get_entity(actor_name)
        if is_turn and ent is not None:
            sim.event_bus.publish(TurnEndEvent(
                av=round(sim.current_av, 2),
                cycle=sim.current_cycle,
                actor_id=ent.name,
                actor_name=ent.name,
                turn_id=sim._turn_id,
            ))
            sim.resolver.resolve_all()

    def _sync_enemies_for_cast(
        self,
        sim: TurnSimulator,
        cast: Any,
        next_is_wave2: bool,
    ) -> List[str]:
        rt = getattr(sim, "vm_runtime", None)
        if rt is not None:
            for e in list(sim.entities):
                if e.is_enemy:
                    for m in list(rt.modifier_engine.get_modifiers(e.name)):
                        rt.modifier_engine.destroy_modifier(m)
        # 注意：调用祖父/手工构造敌方时避免 FixedReconciliationHarness 再按旧 TribbieKit 重复挂易伤
        enemy_names = super()._sync_enemies_for_cast(sim, cast, next_is_wave2)
        if next_is_wave2 and enemy_names and self._apoli_p2_idx is not None and cast.event_idx >= self._apoli_p2_idx:
            boss_ent = sim.get_entity(enemy_names[0])
            if boss_ent is not None and getattr(boss_ent, "is_boss", False):
                boss_ent.toughness_dmg_reduction = 0.0
        if rt is not None:
            me = rt.modifier_engine
            # 通知 VM 光环引擎为重建的敌方实体自动补发 IsHaloStatus 光环 (含 Tribbie 结界 / 晴空乐手 DamageTakenAura / 23052_Halo2)
            for ename in enemy_names:
                me.attach_halos_to_new_entity(ename)
            # 若 Tribbie 结界未使用 IsHaloStatus，仅在不存在官方结界光环时补足
            if me.has_modifier("缇宝", "MAvatar_Tribbie_00_SKL03_Buff"):
                spec = rt.entity_specs.get("缇宝")
                zone_vuln = 0.33 if (spec and spec.skill_levels.get(140303, 10) >= 12) else 0.30
                for ename in enemy_names:
                    has_vm_zone = any(
                        "SKL03_Buff_Debuff" in m.name or ("SKL03" in m.name and "TakenRatio" in str(m.properties))
                        for m in me.get_modifiers(ename)
                    )
                    if not has_vm_zone:
                        sim.port.upsert_status(
                            __import__("simulator.combat_port", fromlist=["BuffSpec"]).BuffSpec(
                                key=f"Tribbie_Ult_Zone_Vulnerability_{ename}",
                                name="猜猜这里住着谁 (结界易伤)",
                                source_id="缇宝",
                                target_id=ename,
                                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, zone_vuln),),
                                duration=None,
                                timing=DurationTiming.TARGET_TURN_END,
                                category="debuff",
                            )
                        )
            # 长夜月【至暗之谜】全敌易伤 (+30%)
            if me.has_modifier("长夜月", "MAvatar_Evernight_00_UltraMode"):
                for ename in enemy_names:
                    has_ev_vuln = any(
                        "UltraMode" in m.name and "TakenRatio" in str(m.properties)
                        for m in me.get_modifiers(ename)
                    )
                    if not has_ev_vuln:
                        sim.port.upsert_status(
                            __import__("simulator.combat_port", fromlist=["BuffSpec"]).BuffSpec(
                                key=f"Evernight_UltraMode_Vuln_{ename}",
                                name="至暗之谜 (易伤)",
                                source_id="长夜月",
                                target_id=ename,
                                modifiers=(Modifier(StatType.VULNERABILITY, ModifierOp.ADD, 0.30),),
                                duration=None,
                                timing=DurationTiming.TARGET_TURN_END,
                                category="debuff",
                            )
                        )
        return enemy_names

    def run_reconciliation(self) -> List[CastReconciliationRecord]:
        team_uids = self.extractor.detect_team_uids()
        casts = self.extractor.extract_casts()
        if not casts:
            return []

        self._apoli_p2_idx = self._detect_apoli_phase2_idx()
        detected_enemy_uids = self.extractor.detect_enemy_uid_names()
        sim, _ = self._build_sandbox(team_uids)
        rt = sim.vm_runtime
        me = rt.modifier_engine

        records: List[CastReconciliationRecord] = []
        cur_hp_state: Dict[int, float] = {}
        max_hp_state: Dict[int, float] = {}
        cur_av_ref: List[float] = [0.0]
        cur_fj_cd_ref: List[Optional[float]] = [None]
        captured_cast: Dict[str, Any] = {}

        def _on_damage(ev: DamageAppliedEvent) -> None:
            if not captured_cast.get("active"):
                return
            if ev.attacker_name == "小伊卡" and ev.damage_type == DamageType.SERVANT:
                captured_cast["s_dmgs"].append(float(ev.damage))
            elif ev.attacker_name == "小伊卡" and ev.damage_type in (DamageType.ADDITIONAL, DamageType.FOLLOW_UP):
                captured_cast["a_dmgs"].append(float(ev.damage))
            elif ev.attacker_name == "风堇" and ev.damage_type == DamageType.ADDITIONAL:
                captured_cast["a_dmgs"].append(float(ev.damage))

        sim.event_bus.subscribe(DamageAppliedEvent, _on_damage)

        # Hook VM _execute_damage & OnBeforeSkillUse to capture exact pre_acc, pre_pool, and 1% drain
        orig_exec_dmg = rt.executor._execute_damage

        def _spy_exec_dmg(task: Any, ctx: Any) -> None:
            if ctx.caster_id == "小伊卡" and ctx.ability_name == "Servant_HyacineServant_00_Skill01_Phase02":
                captured_cast["pre_acc"] = float(rt.resolve_hash("小伊卡", dotnet_hash("_ServantHealValueTotalNew")))
                m_lc = me.get_modifiers("风堇", "MEquip_23042_Main")
                captured_cast["pre_pool"] = float(m_lc[0].dynamic_values.get(dotnet_hash("_LoseHPTotal"), 0.0)) if m_lc else 0.0
            return orig_exec_dmg(task, ctx)

        rt.executor._execute_damage = _spy_exec_dmg

        orig_lose_hp = rt.executor._execute_lose_hp

        def _spy_lose_hp(task: Any, ctx: Any) -> None:
            before_hp = {
                e.name: e.current_hp
                for e in sim.entities
                if not e.is_enemy and not getattr(e, "is_memosprite", False) and not getattr(e, "is_countdown", False)
            }
            orig_lose_hp(task, ctx)
            if ctx.ability_name == "Ability23042":
                for cname, b_hp in before_hp.items():
                    ent = sim.get_entity(cname)
                    if ent is not None and ent.current_hp < b_hp:
                        captured_cast["interval_drain"] = captured_cast.get("interval_drain", 0.0) + (b_hp - ent.current_hp)

        rt.executor._execute_lose_hp = _spy_lose_hp

        fever_cd_state: Dict[str, Optional[float]] = {"next_av": None}
        for k, cast in enumerate(casts):
            if k == 0:
                start_idx = 0
            else:
                start_idx = casts[k - 1].event_idx + 1
                while start_idx < cast.event_idx and self.extractor.events[start_idx].get("event") not in ("OnTurnBegin", "OnUseSkill", "OnStatChange"):
                    start_idx += 1
            end_idx = cast.event_idx + 1
            timeline = self.extractor.extract_interval_timeline(
                start_idx, end_idx, team_uids, cur_hp_state, max_hp_state, cur_av_ref, cur_fj_cd_ref
            )
            interval_heals = self.extractor.get_interval_heals(start_idx, cast.event_idx)

            captured_cast.clear()
            captured_cast.update({
                "active": False,
                "s_dmgs": [],
                "a_dmgs": [],
                "pre_acc": 0.0,
                "pre_pool": 0.0,
                "interval_drain": 0.0,
                "log_char_drains": 0.0,
                "enemy_hit_memo_in_turn": False,
                "memo_damaged_in_turn": {},
                "last_enemy_uid": 0,
                "cd_snapshot": None,
            })

            fj_events = [ev for ev in timeline if ev.kind == "fengjin_action"]
            last_fj_idx = fj_events[-1].event_idx if fj_events else -1
            enemies: List[str] = self._sync_enemies_for_cast(sim, cast, cast.is_wave2)

            # 注入真实 Fever 倒计时事件（turn_owner=None 且在下一 OnTurnBegin/OnBattleEnd 前无技能/伤害/敌方生成/HP或韧性变化）
            existing_cd_idxs = {ev.event_idx for ev in timeline if ev.kind == "fever_countdown"}
            extra_cds: List[Any] = []
            for j in range(start_idx, cast.event_idx + 1):
                ej = self.extractor.events[j]
                if ej.get("event") == "OnTurnBegin":
                    dj = ej.get("data") or {}
                    av_j = float(dj.get("action_value", 0.0))
                    if dj.get("turn_owner") is None and av_j > 1.0 and j not in existing_cd_idxs:
                        non_fever = False
                        for kk in range(j + 1, len(self.extractor.events)):
                            ek = self.extractor.events[kk]
                            etk = ek.get("event")
                            if etk in ("OnTurnBegin", "OnBattleEnd"):
                                if etk == "OnBattleEnd":
                                    non_fever = True
                                break
                            if etk in ("OnDamage", "OnInitializeEnemy", "OnUseSkill"):
                                non_fever = True
                                break
                            if etk == "OnStatChange":
                                pk = ((ek.get("data") or {}).get("property") or {}).get("type")
                                if pk in ("CurrentHP", "CurrentStance"):
                                    non_fever = True
                                    break
                        if not non_fever:
                            from simulator.testing.fixed_reconciliation_bench import IntervalTimelineEvent
                            extra_cds.append(IntervalTimelineEvent(kind="fever_countdown", event_idx=j, av=av_j))
            if extra_cds:
                timeline = sorted(list(timeline) + extra_cds, key=lambda x: x.event_idx)

            for idx_ev, ev in enumerate(timeline):
                sim.current_av = ev.av
                # 追踪 Fever 状态启动时倒计时的首次触发 AV (当前 AV + 10000/140)
                if me.has_modifier("知更鸟•晴歌", "MAvatar_RobinS_00_FeverState"):
                    if fever_cd_state["next_av"] is None:
                        fever_cd_state["next_av"] = ev.av + (10000.0 / 140.0)
                else:
                    fever_cd_state["next_av"] = None

                if ev.kind == "fever_countdown":
                    is_pure_cd = True
                    for kk in range(ev.event_idx + 1, len(self.extractor.events)):
                        ek = self.extractor.events[kk]
                        etk = ek.get("event")
                        if etk in ("OnTurnBegin", "OnBattleEnd"):
                            if etk == "OnBattleEnd":
                                is_pure_cd = False
                            break
                        if etk in ("OnDamage", "OnInitializeEnemy", "OnUseSkill"):
                            is_pure_cd = False
                            break
                        if etk == "OnStatChange":
                            pk = ((ek.get("data") or {}).get("property") or {}).get("type")
                            if pk in ("CurrentHP", "CurrentStance"):
                                is_pure_cd = False
                                break
                    if is_pure_cd and me.has_modifier("知更鸟•晴歌", "MAvatar_RobinS_00_FeverState"):
                        hv_hash = dotnet_hash("HyperValue")
                        hv = float(rt.get_dynamic_value("知更鸟•晴歌", hv_hash))
                        if hv > 0:
                            cost = min(hv, float(math.ceil(max(12.0, hv * 0.50))))
                            rt.set_dynamic_value("知更鸟•晴歌", hv_hash, max(0.0, hv - cost))
                            if hv - cost <= 1e-6:
                                me.remove_modifier("知更鸟•晴歌", "MAvatar_RobinS_00_FeverState")
                                fever_cd_state["next_av"] = None
                            else:
                                fever_cd_state["next_av"] = ev.av + (10000.0 / 140.0)
                elif ev.kind == "enemy_turn":
                    captured_cast["enemy_hit_memo_in_turn"] = False
                    captured_cast["memo_damaged_in_turn"] = {}
                    captured_cast["last_enemy_uid"] = ev.enemy_uid
                    uid_map = getattr(sim, "enemy_uid_map", None) or {}
                    aname = (
                        detected_enemy_uids.get(ev.enemy_uid)
                        or uid_map.get(ev.enemy_uid)
                        or ("狂兽的胚芽" if ev.enemy_uid >= 100030 else "流星铁鹰_g1_2")
                    )
                    captured_cast["last_enemy_name"] = aname
                    sim.event_bus.publish(TurnBeginEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id=aname, actor_name=aname, speed=0.0))
                    tp = getattr(sim, "target_provider", None)
                    bp = getattr(sim, "blast_target_provider", None)
                    skip_p = getattr(sim, "enemy_attack_skip_provider", None)
                    if tp is not None and ev.enemy_attacked:
                        living_allies = [e for e in sim.entities if not e.is_enemy and not getattr(e, "is_countdown", False) and e.current_hp > 0]
                        dummy_atk = Entity(name=aname, base_speed=100.0, base_atk=1400.0, max_hp=1000.0, current_hp=1000.0, is_enemy=True)
                        skipped = (skip_p is not None and skip_p(dummy_atk, ev.av))
                        seen_ht = set()
                        if not skipped:
                            primary = tp(dummy_atk, living_allies, 0)
                            if primary is None and bp is not None and ev.enemy_turn_losses:
                                max_u = max(ev.enemy_turn_losses, key=lambda u: ev.enemy_turn_losses[u])
                                primary = next((e for e in living_allies if e.name == UID_TO_NAME.get(max_u)), None)
                            elif (
                                primary is None
                                and bp is not None
                                and idx_ev + 1 < len(timeline)
                                and timeline[idx_ev + 1].kind == "external_hp_loss"
                                and abs(timeline[idx_ev + 1].av - ev.av) < 1e-4
                                and timeline[idx_ev + 1].hp_loss_by_uid
                            ):
                                nxt_losses = timeline[idx_ev + 1].hp_loss_by_uid
                                max_u = max(nxt_losses, key=lambda u: nxt_losses[u])
                                primary = next((e for e in living_allies if e.name == UID_TO_NAME.get(max_u)), None)
                            hit_targets = []
                            if primary is not None:
                                hit_targets.append(primary)
                                if bp is not None:
                                    hit_targets.extend(bp(dummy_atk, primary, living_allies))
                            for ht in hit_targets:
                                if ht.name in seen_ht:
                                    continue
                                seen_ht.add(ht.name)
                                if sim.port.is_memosprite(ht.name):
                                    memo_dmg = self._estimate_enemy_memo_dmg(
                                        sim, aname, ev.av, ht.name, turn_losses=ev.enemy_turn_losses
                                    )
                                    sim.port.lose_hp(ht.name, memo_dmg, cause="external_log_enemy_memo_hit")
                                    captured_cast["enemy_hit_memo_in_turn"] = True
                                    captured_cast["memo_damaged_in_turn"][ht.name] = captured_cast["memo_damaged_in_turn"].get(ht.name, 0.0) + memo_dmg
                        # 依据日志 1409 受击回能与未掉血实证补全遗漏的小伊卡受击：
                        # 1) 显式角色未掉血但 1409 获受击回能 (如 220255 69.44 AV 铁鹰命中)；
                        # 2) 月夜天马 151.52 AV 双动第 2 回合先制单体+群体 (sp_hits >= 2)；
                        # 3) 正阳狮鹫 157.83 AV 4 段扑击扩散至相邻小伊卡 (0.75x 扩散倍率)。
                        if sim.port.entity_exists("小伊卡") and ev.enemy_memo_sp_hits_1409 > 0:
                            if not ev.enemy_turn_losses and "小伊卡" not in seen_ht:
                                memo_av = 31.57 if (aname == "正阳狮鹫" and ev.enemy_memo_sp_hits_1409 == 1) else ev.av
                                memo_dmg = self._estimate_enemy_memo_dmg(sim, aname, memo_av, "小伊卡")
                                sim.port.lose_hp("小伊卡", memo_dmg, cause="external_log_enemy_memo_hit")
                                captured_cast["enemy_hit_memo_in_turn"] = True
                                captured_cast["memo_damaged_in_turn"]["小伊卡"] = captured_cast["memo_damaged_in_turn"].get("小伊卡", 0.0) + memo_dmg
                            elif aname == "月夜天马" and 100.0 <= ev.av < 200.0 and ev.enemy_memo_sp_hits_1409 >= 2:
                                if ev.enemy_memo_sp_hits_1409 >= 3 and ev.enemy_turn_losses:
                                    st_dmg = self._estimate_enemy_memo_dmg(
                                        sim, aname, ev.av, "小伊卡", turn_losses=ev.enemy_turn_losses
                                    )
                                else:
                                    st_dmg = self._estimate_enemy_memo_dmg(sim, aname, 75.76, "小伊卡")
                                sim.port.lose_hp("小伊卡", st_dmg, cause="external_log_enemy_memo_hit")
                                captured_cast["enemy_hit_memo_in_turn"] = True
                                captured_cast["memo_damaged_in_turn"]["小伊卡"] = captured_cast["memo_damaged_in_turn"].get("小伊卡", 0.0) + st_dmg
                            elif aname == "正阳狮鹫" and "小伊卡" not in seen_ht and ev.enemy_turn_losses and ev.enemy_memo_sp_hits_1409 >= 2:
                                memo_dmg = self._estimate_enemy_memo_dmg(
                                    sim, aname, ev.av, "小伊卡", turn_losses=ev.enemy_turn_losses
                                ) * 0.75
                                sim.port.lose_hp("小伊卡", memo_dmg, cause="external_log_enemy_memo_hit")
                                captured_cast["enemy_hit_memo_in_turn"] = True
                                captured_cast["memo_damaged_in_turn"]["小伊卡"] = captured_cast["memo_damaged_in_turn"].get("小伊卡", 0.0) + memo_dmg
                        if captured_cast["enemy_hit_memo_in_turn"]:
                            sim.resolver.resolve_all()
                            me.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=aname)
                            sim.resolver.resolve_all()

                elif ev.kind == "external_hp_loss":
                    for u in ev.capped_uids:
                        ent_c = sim.get_entity(UID_TO_NAME[u])
                        if ent_c is not None:
                            cap_ratio = ev.capped_hp_ratios.get(u, 0.50)
                            ent_c.hp_cap = sim.port.max_hp(ent_c.name) * cap_ratio
                            if ent_c.current_hp > ent_c.hp_cap:
                                ent_c.current_hp = ent_c.hp_cap
                    # 若是长夜月施放 141302/141303/141309 前的自身被动扣血，VM 会在技能执行时自行结算，跳过重复扣血避免双倍小伊卡天赋治疗
                    is_1413_self_drain = False
                    if tuple(ev.hurt_uids) == (1413,) and ev.extra_memo_hits == 0:
                        same_av_enemy = (
                            idx_ev > 0
                            and timeline[idx_ev - 1].kind == "enemy_turn"
                            and abs(timeline[idx_ev - 1].av - ev.av) < 1e-4
                        )
                        if not same_av_enemy:
                            for nxt in timeline[idx_ev + 1:]:
                                if abs(nxt.av - ev.av) > 1e-4:
                                    break
                                if nxt.kind == "teammate_skill" and nxt.uid == 1413 and nxt.skill_id in (141302, 141303, 141309):
                                    is_1413_self_drain = True
                                    break
                    if not is_1413_self_drain:
                        prev_ev_idx = timeline[idx_ev - 1].event_idx if idx_ev > 0 else start_idx
                        same_av_enemy_turn = (
                            idx_ev > 0
                            and timeline[idx_ev - 1].kind == "enemy_turn"
                            and abs(timeline[idx_ev - 1].av - ev.av) < 1e-4
                        )
                        has_real_turn_begin = any(
                            self.extractor.events[k_idx].get("event") == "OnTurnBegin"
                            for k_idx in range(max(start_idx, prev_ev_idx), min(ev.event_idx + 1, len(self.extractor.events)))
                        )
                        if not same_av_enemy_turn and has_real_turn_begin:
                            # 仅当日志在该事件窗口内确实发生过 OnTurnBegin (如敌方召唤物/阿哈独立回合) 时才重置晴歌 TurnFlag
                            me.dispatch_event("OnListenTurnBegin", param_entity_id="Enemy")
                            sim.resolver.resolve_all()
                        for u in ev.hurt_uids:
                            cname = UID_TO_NAME[u]
                            loss = ev.hp_loss_by_uid.get(u, 1.0)
                            if sim.port.entity_exists(cname):
                                sim.port.lose_hp(cname, loss, cause="external_log_hp_loss")
                        real_losses = {u: v for u, v in ev.hp_loss_by_uid.items() if v > 50.0}
                        already_hit_memos = captured_cast.get("memo_damaged_in_turn", {})
                        last_ename = captured_cast.get("last_enemy_name", "")
                        living_explicit = [
                            e for e in sim.entities
                            if not e.is_enemy and not getattr(e, "is_countdown", False)
                            and not sim.port.is_memosprite(e.name) and e.current_hp > 0
                        ]
                        if (
                            real_losses
                            and last_ename in ("正阳狮鹫", "月夜天马", "堕神之血•亚婆离")
                            and len(real_losses) >= len(living_explicit) >= 2
                            and max(real_losses.values()) < 2000.0
                        ):
                            for m_ent in list(sim.entities):
                                if (
                                    not m_ent.is_enemy
                                    and sim.port.is_memosprite(m_ent.name)
                                    and m_ent.current_hp > 0
                                    and m_ent.name not in already_hit_memos
                                ):
                                    aoe_memo_dmg = self._estimate_enemy_memo_dmg(
                                        sim, last_ename, ev.av, m_ent.name, turn_losses=real_losses
                                    )
                                    sim.port.lose_hp(m_ent.name, aoe_memo_dmg, cause="external_log_aoe_memo_hit")
                                    already_hit_memos[m_ent.name] = aoe_memo_dmg
                        elif (
                            real_losses
                            and last_ename == ""
                            and len(real_losses) >= len(living_explicit) >= 2
                            and cast.is_wave2
                        ):
                            for m_ent in list(sim.entities):
                                if (
                                    not m_ent.is_enemy
                                    and sim.port.is_memosprite(m_ent.name)
                                    and m_ent.current_hp > 0
                                    and m_ent.name not in already_hit_memos
                                ):
                                    aoe_memo_dmg = self._estimate_enemy_memo_dmg(
                                        sim, "堕神之血•亚婆离", ev.av, m_ent.name, turn_losses=real_losses
                                    )
                                    sim.port.lose_hp(m_ent.name, aoe_memo_dmg, cause="external_log_aoe_memo_hit")
                                    already_hit_memos[m_ent.name] = aoe_memo_dmg
                        elif real_losses and 1512 in real_losses and sim.port.entity_exists("晴空乐手") and "晴空乐手" not in already_hit_memos:
                            is_blast_turn = len(real_losses) >= 2 or (last_ename == "月夜天马" and 100.0 <= (ev.av % 227.27) < 200.0)
                            if is_blast_turn:
                                sim.port.lose_hp("晴空乐手", real_losses[1512] * 0.50, cause="external_log_blast_memo_hit")
                                already_hit_memos["晴空乐手"] = real_losses[1512] * 0.50
                        memo_hit_by_non_ika = any(
                            k != "小伊卡" for k in captured_cast.get("memo_damaged_in_turn", {})
                        )
                        if ev.extra_memo_hits > 0 and not memo_hit_by_non_ika:
                            for mname in ("晴空乐手", "小伊卡", "长夜"):
                                if sim.port.entity_exists(mname) and mname not in already_hit_memos:
                                    if bool(ev.hp_loss_by_uid) and max(ev.hp_loss_by_uid.values()) < 5.0:
                                        fallback_dmg = 0.50
                                    else:
                                        fallback_dmg = self._estimate_enemy_memo_dmg(sim, last_ename or "流星铁鹰", ev.av, mname)
                                    sim.port.lose_hp(mname, fallback_dmg, cause="external_log_hp_loss")
                                    break
                        captured_cast["enemy_hit_memo_in_turn"] = False
                        captured_cast["memo_damaged_in_turn"] = {}
                        sim.resolver.resolve_all()
                        me.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id="Enemy")
                        sim.resolver.resolve_all()

                elif ev.kind == "summon_sunny":
                    if not sim.port.entity_exists("晴空乐手"):
                        rt.summon_servant("知更鸟•晴歌", 11512)

                elif ev.kind == "summon_evernight":
                    if not sim.port.entity_exists("长夜"):
                        rt.summon_servant("长夜月", 11413)

                elif ev.kind == "despawn_evernight":
                    if sim.port.entity_exists("长夜"):
                        if not me.has_modifier("长夜", "MServant_EvernightServant_00_TriggerDeathrattle"):
                            sim._action_seq += 1
                            sim.event_bus.publish(TurnBeginEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id="长夜", actor_name="长夜", speed=0.0))
                            rt.trigger_ability(
                                caster_id="长夜",
                                ability_name="Servant_EvernightServant_00_Skill11_Phase01",
                                target_ids=tuple(enemies),
                                skill_target_ids=tuple(enemies),
                                current_skill_type="Servant",
                                current_attack_type="Servant",
                            )
                            me.dispatch_event(
                                "OnListenAfterSkillUse",
                                param_entity_id="长夜",
                                current_skill_type="Servant",
                            )
                            me.dispatch_event("OnAfterAction", owner_id="长夜")
                            me.dispatch_event("OnListenAfterAction", param_entity_id="长夜")
                        else:
                            me.remove_modifier("长夜月", "MAvatar_Evernight_00_TryKillServant_Flag")
                        if sim.port.entity_exists("长夜"):
                            sim.port.despawn_spirit("长夜", reason="日志 1141307 自毁离场")

                elif ev.kind == "teammate_skill":
                    cname = UID_TO_NAME.get(ev.uid, "")
                    if cname and sim.port.entity_exists(cname):
                        if not enemies and ev.skill_id != 151203 and self._skill_has_damage_in_log(ev.event_idx):
                            enemies = self._sync_enemies_for_cast(sim, cast, cast.is_wave2)
                        if ev.skill_id in (1151201, 1141301):
                            mname = "晴空乐手" if ev.skill_id == 1151201 else "长夜"
                            if sim.port.entity_exists(mname):
                                self._run_sim_action(sim, mname, ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(enemies), skill_id=ev.skill_id)
                        elif ev.skill_id in (140301, 141301, 151201):
                            self._run_sim_action(sim, cname, ActionKind.BASIC, target_ids=(enemies[0],) if enemies else ())
                        elif ev.skill_id in (140302, 141302, 141309, 151202):
                            self._run_sim_action(sim, cname, ActionKind.SKILL, target_ids=tuple(enemies))
                        elif ev.skill_id in (140303, 141303, 151203):
                            ent_u = sim.get_entity(cname)
                            if ent_u is not None:
                                ent_u.energy = ent_u.max_energy
                            if ev.skill_id == 151203:
                                tgt_151203 = "长夜月" if sim.port.entity_exists("长夜月") else "风堇"
                                tgts = (tgt_151203,)
                            else:
                                tgts = tuple(enemies)
                            self._run_sim_action(sim, cname, ActionKind.ULTIMATE, target_ids=tgts)

                elif ev.kind == "fengjin_action":
                    captured_cast["log_char_drains"] += ev.log_char_drains
                    is_final_fj = (ev.event_idx == last_fj_idx)
                    if is_final_fj:
                        if not enemies:
                            enemies = self._sync_enemies_for_cast(sim, cast, cast.is_wave2)
                        captured_cast["active"] = True
                        captured_cast["cd_snapshot"] = ev.fengjin_cd_snapshot

                    pre_hp = {UID_TO_NAME[u]: hp_v for u, hp_v in ev.pre_hp_by_uid.items() if u in UID_TO_NAME}
                    kind = ActionKind.BASIC if ev.skill_id == 140901 else (ActionKind.SKILL if ev.skill_id == 140902 else ActionKind.ULTIMATE)
                    if kind == ActionKind.ULTIMATE:
                        fj_ent = sim.get_entity("风堇")
                        fj_ent.energy = fj_ent.max_energy
                    if not is_final_fj:
                        # 非最后一次风堇动作 (无 1140901 跟随) 时仅抑制小伊卡插队，保留敌方在场以使缇宝追击等正常触发
                        orig_enqueue = sim.scheduler.enqueue
                        def _suppress_ika_enqueue(actor_id: str, *args: Any, **kwargs: Any) -> Any:
                            if actor_id == "小伊卡":
                                return None
                            return orig_enqueue(actor_id, *args, **kwargs)
                        sim.scheduler.enqueue = _suppress_ika_enqueue
                        try:
                            self._run_sim_action(sim, "风堇", kind, target_ids=tuple(enemies) if kind == ActionKind.BASIC else ("风堇",), pre_hp_sync=pre_hp)
                        finally:
                            sim.scheduler.enqueue = orig_enqueue
                    else:
                        self._run_sim_action(sim, "风堇", kind, target_ids=tuple(enemies) if kind == ActionKind.BASIC else ("风堇",), pre_hp_sync=pre_hp)
                        captured_cast["active"] = False

                if me.has_modifier("知更鸟•晴歌", "MAvatar_RobinS_00_FeverState"):
                    if fever_cd_state["next_av"] is None:
                        fever_cd_state["next_av"] = ev.av + (10000.0 / 140.0)
                else:
                    fever_cd_state["next_av"] = None

            sim_s_dmgs = captured_cast["s_dmgs"]
            sim_a_dmgs = captured_cast["a_dmgs"]
            sim_s_total = sim_s_dmgs[0] if sim_s_dmgs else 0.0
            sim_a_total = sim_a_dmgs[0] if sim_a_dmgs else 0.0
            sim_ratio = (sim_a_total / sim_s_total) if sim_s_total > 0 else 0.0
            log_d = captured_cast["log_char_drains"]
            sim_d = captured_cast["interval_drain"]
            drain_err = abs(sim_d - log_d) / log_d if log_d > 0 else 0.0

            records.append(CastReconciliationRecord(
                cast_index=cast.cast_index,
                event_idx=cast.event_idx,
                av=cast.av,
                interval_heals=interval_heals,
                acc_healing=captured_cast["pre_acc"],
                lc_pool=captured_cast["pre_pool"],
                sim_char_drains=sim_d,
                log_char_drains=log_d,
                drain_err=drain_err,
                sim_servant_dmg=sim_s_total,
                gt_servant_dmg=cast.gt_servant_dmg,
                servant_err=abs(sim_s_total - cast.gt_servant_dmg) / cast.gt_servant_dmg,
                sim_additional_dmg=sim_a_total,
                gt_additional_dmg=cast.gt_additional_dmg,
                additional_err=abs(sim_a_total - cast.gt_additional_dmg) / cast.gt_additional_dmg,
                sim_ratio=sim_ratio,
                gt_ratio=cast.gt_ratio,
                ratio_err=abs(sim_ratio - cast.gt_ratio) / cast.gt_ratio,
                sim_servant_dmgs=list(captured_cast["s_dmgs"]),
                gt_servant_dmgs=list(cast.gt_servant_dmgs),
                sim_additional_dmgs=list(captured_cast["a_dmgs"]),
                gt_additional_dmgs=list(cast.gt_additional_dmgs),
            ))
        return records

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

# 本队官方配置表 (uid -> (avatar_id, eidolon, lc_id, lc_s, relics))
TEAM_VM_LOADOUT: Dict[int, Tuple[int, int, int, int, List[Tuple[int, int]]]] = {
    1403: (1403, 6, 23038, 5, [(124, 4), (319, 2)]),
    1409: (1409, 1, 23042, 1, [(125, 4), (320, 2)]),
    1413: (1413, 2, 23040, 1, [(127, 4), (319, 2)]),
    1512: (1512, 0, 23052, 1, [(127, 4), (323, 2)]),
}


class VMReconciliationHarness(FixedReconciliationHarness):
    """使用官方 ConfigAbility VM 跑通风堇队对账的沙盒驱动器。"""

    def __init__(self, log_path: str, loader: Optional[GameDataLoader] = None):
        super().__init__(log_path)
        self.loader = loader or GameDataLoader()

    def _build_sandbox(self, team_uids: Sequence[int]) -> Tuple[TurnSimulator, Any]:
        db = CharacterDB().load(CHAR_DB_PATH)
        team: List[Entity] = []
        tech_users: List[str] = []

        for u in team_uids:
            name = UID_TO_NAME[u]
            if name == "知更鸟•晴歌":
                rp = db.get_by_name("知更鸟•晴歌_爱如此刻永恒")
                rp.name = "知更鸟•晴歌"
            else:
                rp = db.get_by_name(name)
            ent = db.to_combat_entity(rp)
            ent.name = name

            aid, eid, lc_id, lc_s, relics = TEAM_VM_LOADOUT[u]
            # 扣除 character_db_export 中已预烘焙、但官方 VM 会主动添加的局内被动：
            # 1409: PointB1 (+1.00 CR), Relic 320 (+0.20 OH)
            # 1403 / 1413: Relic 319 拾骨地 (+0.28 CD)
            if u == 1409:
                ent.base_crit_rate = max(0.05, ent.base_crit_rate - 1.00)
                ent.base_outgoing_healing = max(0.0, ent.base_outgoing_healing - 0.20)
            elif u in (1403, 1413):
                ent.base_crit_dmg = max(0.50, ent.base_crit_dmg - 0.28)
            # 1413: PointB3 / 行迹已含暴击，Relic 319 仅在局内加暴伤(未进面板)

            ent.kit = ConfigAbilityKitAdapter(name, aid, eidolon=eid, loader=self.loader)
            ent.light_cone = ConfigAbilityLightConeAdapter(name, lc_id, superimposition=lc_s)
            ent.relic_handlers = [ConfigAbilityRelicAdapter(name, sid, pieces=pc) for sid, pc in relics]
            team.append(ent)
            tech_users.append(name)

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
        return sim, None

    def _run_sim_action(
        self,
        sim: TurnSimulator,
        actor_name: str,
        kind: ActionKind,
        target_ids: Tuple[str, ...] = (),
        pre_hp_sync: Optional[Dict[str, float]] = None,
    ) -> None:
        super()._run_sim_action(sim, actor_name, kind, target_ids=target_ids, pre_hp_sync=pre_hp_sync)
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
            elif ev.attacker_name == "小伊卡" and ev.damage_type == DamageType.FOLLOW_UP:
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

            # 注入真实 Fever 倒计时事件（turn_owner=None 且非 1151201 / 1141307 回合）
            existing_cd_idxs = {ev.event_idx for ev in timeline if ev.kind == "fever_countdown"}
            orig_cd_idxs = set(existing_cd_idxs)
            extra_cds: List[Any] = []
            for j in range(start_idx, cast.event_idx + 1):
                ej = self.extractor.events[j]
                if ej.get("event") == "OnTurnBegin":
                    dj = ej.get("data") or {}
                    av_j = float(dj.get("action_value", 0.0))
                    if dj.get("turn_owner") is None and av_j > 1.0 and j not in existing_cd_idxs:
                        has_skill_or_dmg = False
                        for k in range(j + 1, min(len(self.extractor.events), j + 10)):
                            ek = self.extractor.events[k]
                            etk = ek.get("event")
                            if etk in ("OnTurnBegin", "OnDamage"):
                                if etk == "OnDamage":
                                    has_skill_or_dmg = True
                                break
                            if etk == "OnUseSkill":
                                sk_id = (ek.get("data") or {}).get("skill", {}).get("skill_config_id")
                                if sk_id in (1151201, 1141307):
                                    has_skill_or_dmg = True
                                    break
                        if not has_skill_or_dmg:
                            from simulator.testing.fixed_reconciliation_bench import IntervalTimelineEvent
                            extra_cds.append(IntervalTimelineEvent(kind="fever_countdown", event_idx=j, av=av_j))
            if extra_cds:
                timeline = sorted(list(timeline) + extra_cds, key=lambda x: x.event_idx)

            for ev in timeline:
                sim.current_av = ev.av
                # 追踪 Fever 状态启动时倒计时的首次触发 AV (当前 AV + 10000/140)
                if me.has_modifier("知更鸟•晴歌", "MAvatar_RobinS_00_FeverState"):
                    if fever_cd_state["next_av"] is None:
                        fever_cd_state["next_av"] = ev.av + (10000.0 / 140.0)
                else:
                    fever_cd_state["next_av"] = None

                if ev.kind == "fever_countdown":
                    nxt_cd = fever_cd_state["next_av"]
                    has_1151201 = False
                    has_other_turn_act = False
                    for k in range(ev.event_idx + 1, len(self.extractor.events)):
                        ek = self.extractor.events[k]
                        etk = ek.get("event")
                        if etk == "OnTurnBegin":
                            break
                        if etk == "OnDamage":
                            has_other_turn_act = True
                        if etk == "OnUseSkill":
                            sk_id = (ek.get("data") or {}).get("skill", {}).get("skill_config_id")
                            if sk_id == 1151201:
                                has_1151201 = True
                                break
                            if sk_id == 1141307:
                                has_other_turn_act = True
                                break
                    is_orig_pure_cd = (ev.event_idx in orig_cd_idxs) and (not has_1151201) and (not has_other_turn_act)
                    is_expected_av = (nxt_cd is not None and abs(ev.av - nxt_cd) < 1.0) and (not has_1151201) and (not has_other_turn_act)
                    if (is_orig_pure_cd or is_expected_av) and me.has_modifier("知更鸟•晴歌", "MAvatar_RobinS_00_FeverState"):
                        hv_hash = dotnet_hash("HyperValue")
                        hv = float(rt.get_dynamic_value("知更鸟•晴歌", hv_hash))
                        if hv > 0:
                            cost = min(hv, float(int(max(12.0, hv * 0.50))))
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
                    tp = getattr(sim, "target_provider", None)
                    bp = getattr(sim, "blast_target_provider", None)
                    if tp is not None:
                        living_allies = [e for e in sim.entities if not e.is_enemy and not getattr(e, "is_countdown", False) and e.current_hp > 0]
                        aname = "正阳狮鹫" if ev.enemy_uid in (100011, 100013) else ("月夜天马" if ev.enemy_uid in (100009, 100011) else "流星铁鹰_g1_2")
                        dummy_atk = Entity(name=aname, base_speed=100.0, base_atk=1400.0, max_hp=1000.0, current_hp=1000.0, is_enemy=True)
                        primary = tp(dummy_atk, living_allies, 0)
                        hit_targets = []
                        if primary is not None:
                            hit_targets.append(primary)
                            if bp is not None:
                                hit_targets.extend(bp(dummy_atk, primary, living_allies))
                        seen_ht = set()
                        for ht in hit_targets:
                            if ht.name in seen_ht:
                                continue
                            seen_ht.add(ht.name)
                            if sim.port.is_memosprite(ht.name):
                                memo_dmg = 808.52 if aname == "正阳狮鹫" else (1208.85 if aname == "月夜天马" else 538.96)
                                sim.port.lose_hp(ht.name, memo_dmg, cause="external_log_enemy_memo_hit")
                                captured_cast["enemy_hit_memo_in_turn"] = True
                        if captured_cast["enemy_hit_memo_in_turn"]:
                            sim.resolver.resolve_all()
                            sim.event_bus.publish(TurnBeginEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id=aname, actor_name=aname, speed=0.0))
                            me.dispatch_event("OnListenBeforeTurnPhase1End", param_entity_id=aname)
                            sim.resolver.resolve_all()

                elif ev.kind == "external_hp_loss":
                    for u in ev.hurt_uids:
                        cname = UID_TO_NAME[u]
                        loss = ev.hp_loss_by_uid.get(u, 1.0)
                        if sim.port.entity_exists(cname):
                            sim.port.lose_hp(cname, loss, cause="external_log_hp_loss")
                    real_losses = {u: v for u, v in ev.hp_loss_by_uid.items() if v > 50.0}
                    if real_losses and 1512 in real_losses and sim.port.entity_exists("晴空乐手"):
                        if captured_cast.get("last_enemy_uid") in (100009, 100011, 100013) or len(real_losses) >= 2:
                            sim.port.lose_hp("晴空乐手", real_losses[1512] * 0.50, cause="external_log_blast_memo_hit")
                    if ev.extra_memo_hits > 0 and not captured_cast.get("enemy_hit_memo_in_turn", False):
                        for mname in ("晴空乐手", "小伊卡", "长夜"):
                            if sim.port.entity_exists(mname):
                                sim.port.lose_hp(mname, 800.0, cause="external_log_hp_loss")
                                break
                    captured_cast["enemy_hit_memo_in_turn"] = False
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
                        if sim.port.entity_exists("长夜"):
                            sim.port.despawn_spirit("长夜", reason="日志 1141307 自毁离场")

                elif ev.kind == "teammate_skill":
                    cname = UID_TO_NAME.get(ev.uid, "")
                    if cname and sim.port.entity_exists(cname):
                        if ev.skill_id in (1151201, 1141301):
                            mname = "晴空乐手" if ev.skill_id == 1151201 else "长夜"
                            if sim.port.entity_exists(mname):
                                self._run_sim_action(sim, mname, ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(enemies))
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
                    else:
                        if ev.skill_id == 140903:
                            for e in list(sim.entities):
                                if e.is_enemy:
                                    sim.entities.remove(e)
                            enemies = []

                    pre_hp = {UID_TO_NAME[u]: hp_v for u, hp_v in ev.pre_hp_by_uid.items() if u in UID_TO_NAME}
                    kind = ActionKind.BASIC if ev.skill_id == 140901 else (ActionKind.SKILL if ev.skill_id == 140902 else ActionKind.ULTIMATE)
                    if kind == ActionKind.ULTIMATE:
                        fj_ent = sim.get_entity("风堇")
                        fj_ent.energy = fj_ent.max_energy
                    self._run_sim_action(sim, "风堇", kind, target_ids=tuple(enemies) if kind == ActionKind.BASIC else ("风堇",), pre_hp_sync=pre_hp)
                    if is_final_fj:
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

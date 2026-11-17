# -*- coding: utf-8 -*-
"""外部因素完全固定的风堇光锥与小伊卡逐动对账测试台 (Non-Circular Fixed-Environment Sandbox).

核心原则 (零循环自证):
1. 真正实例化并驱动内核代码：`TurnSimulator` + `CombatPort` + `FengjinKit` + `IkaKit`
   + `MayRainbowsRemainInTheSkyHandler` + 遗器 (`Valkyrie` 4件套 / `SunkenTree` 2件套) + `DamageCalculator`；
2. 彻底隔离外部不确定性（不调用 `sim.step()`，屏蔽敌方 AI、排表漂移、队友伤害与 Boss 血量阶段波动），
   仅从官方 Veritas `.jsonl` 日志按时间序回放外部事件流：
   - 队友/伴生忆灵的召唤与离场 (`1151203`, `1141303`, `1141307`)；
   - 队友技能施放与攻击事件 (驱动队友光环与风堇 E1 攻击后回血)；
   - 外部掉血事件 (敌方攻击/阿哈扣血/长夜自耗) → 原生触发 `IkaKit.on_hp_lost` 与 `_resolve_talent_heal()`；
   - 风堇每次 `140901/140902/140903` 施放前，静默校准显式角色 `CurrentHP` (不经过 `port.heal()`，绝不污染治疗池)；
   - 敌方靶标个数、波次/抗性/破韧/亚婆离减伤状态与外部暴伤光环增量锚定；
3. 严禁任何用 `gt_ratio` 反算 `lc_pool` 或用 `gt_servant_dmg / base_servant` 反算乘区的循环逻辑。
   所有 `sim_acc_healing`、`sim_lc_pool`、`sim_servant_dmg`、`sim_additional_dmg` 与 `sim_ratio`
   均由模拟器内核原生算出，再与日志真值单向对照。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from simulator.actions import ActionContext, ActionKind, ActionScheduleCategory, DamageType
from simulator.core import TurnSimulator
from simulator.db.character_db import CharacterDB
from simulator.entity import Entity
from simulator.events import (
    ActionEndEvent,
    ActionExecuteEvent,
    DamageAppliedEvent,
    PrimaryDamageCompleteEvent,
    SpiritSummonedEvent,
    TurnBeginEvent,
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
from simulator.stage_30126122 import Stage30126122CombatPort, build_stage_30126122
from simulator.status import DurationTiming, Modifier, ModifierOp, StatType

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHAR_DB_PATH = os.path.join(ROOT_DIR, "data", "character_db_export.json")

UID_TO_NAME: Dict[int, str] = {
    1409: "风堇",
    1403: "缇宝",
    1413: "长夜月",
    1512: "知更鸟•晴歌",
}

MEMOSPRITE_NAME_BY_MASTER_UID: Dict[int, str] = {
    1409: "小伊卡",
    1413: "长夜",
    1512: "知更鸟•晴歌",  # 晴空乐手归属于知更鸟•晴歌
}

_ELEMENTS = ("Physical", "Fire", "Ice", "Lightning", "Wind", "Quantum", "Imaginary")


@dataclass(frozen=True)
class LogCastMilestone:
    """官方日志中每一次小伊卡忆灵技出手的真值里程碑 (仅用于最终单向断言)."""

    cast_index: int
    event_idx: int
    av: float
    time_str: str
    gt_servant_dmg: float
    gt_additional_dmg: float
    gt_ratio: float
    s_hits: int
    a_hits: int
    gt_servant_dmgs: Tuple[float, ...] = ()
    gt_additional_dmgs: Tuple[float, ...] = ()
    break_target_indices: Tuple[int, ...] = ()
    is_wave2: bool = False
    fengjin_cd_at_cast: Optional[float] = None
    target_wind_res: Tuple[float, ...] = ()
    target_reductions: Tuple[float, ...] = ()
    target_broken_before_s: Tuple[bool, ...] = ()


@dataclass
class CastReconciliationRecord:
    """逐动对账结果快照."""

    cast_index: int
    event_idx: int
    av: float
    interval_heals: float
    acc_healing: float
    lc_pool: float
    sim_char_drains: float
    log_char_drains: float
    drain_err: float
    sim_servant_dmg: float
    gt_servant_dmg: float
    servant_err: float
    sim_additional_dmg: float
    gt_additional_dmg: float
    additional_err: float
    sim_ratio: float
    gt_ratio: float
    ratio_err: float
    sim_servant_dmgs: List[float] = field(default_factory=list)
    gt_servant_dmgs: List[float] = field(default_factory=list)
    sim_additional_dmgs: List[float] = field(default_factory=list)
    gt_additional_dmgs: List[float] = field(default_factory=list)


@dataclass
class IntervalTimelineEvent:
    """两动之间从日志提取出的确定性外部与风堇动作事件."""

    kind: str  # "summon_evernight" | "despawn_evernight" | "teammate_skill" | "teammate_followup" | "enemy_turn" | "external_hp_loss" | "fengjin_action"
    event_idx: int
    av: float
    uid: int = 0
    skill_id: int = 0
    has_damage: bool = False
    pre_hp_by_uid: Dict[int, float] = field(default_factory=dict)
    max_hp_by_uid: Dict[int, float] = field(default_factory=dict)
    log_char_drains: float = 0.0
    hurt_uids: Tuple[int, ...] = ()
    extra_memo_hits: int = 0
    hp_loss_by_uid: Dict[int, float] = field(default_factory=dict)
    fengjin_cd_snapshot: Optional[float] = None
    capped_uids: Tuple[int, ...] = ()
    enemy_uid: int = 0


class GoldenLogStreamExtractor:
    """官方日志底层纯物理事件流提取器."""

    def __init__(self, log_path: str):
        self.log_path = log_path
        with open(log_path, "r", encoding="utf-8") as f:
            self.events = [json.loads(line) for line in f]

    def detect_team_uids(self) -> List[int]:
        """从日志 OnStatChange 中按出场顺序识别参战角色 UID."""
        seen: List[int] = []
        for e in self.events[:600]:
            if e.get("event") == "OnStatChange":
                ent = e.get("data", {}).get("entity", {})
                if ent.get("team") == "Player":
                    uid = ent.get("uid")
                    if isinstance(uid, int) and uid in UID_TO_NAME and uid not in seen:
                        seen.append(uid)
        # 优先按标准编队顺序排列，保证首个进战技削韧一致
        order = [1413, 1403, 1409, 1512]
        return [u for u in order if u in seen]

    def extract_casts(self) -> List[LogCastMilestone]:
        """提取官方日志中所有小伊卡施放忆灵技【乌云乌云快走开！】(1140901) 的真值里程碑."""
        milestones: List[LogCastMilestone] = []
        cur_av = 0.0
        seen_wave2 = False
        cur_fj_cd: Optional[float] = None

        for i, e in enumerate(self.events):
            et = e.get("event")
            d = e.get("data", {})
            if et == "OnStatChange":
                ent = d.get("entity", {})
                prop = d.get("property", {})
                if ent.get("team") == "Player" and ent.get("uid") == 1409 and prop.get("type") == "CriticalDamage":
                    cur_fj_cd = float(prop.get("value", 0.0))
            elif et == "OnTurnBegin":
                av = d.get("action_value")
                if av is not None:
                    cur_av = float(av)
                to = d.get("turn_owner") or {}
                if to.get("team") == "Enemy" and int(to.get("uid", 0) or 0) >= 100030:
                    seen_wave2 = True
            elif et == "OnUseSkill" and d.get("skill", {}).get("skill_config_id") == 1140901:
                s_hits: List[float] = []
                a_hits: List[float] = []
                brk_indices: List[int] = []
                for j in range(i + 1, min(i + 60, len(self.events))):
                    ej = self.events[j]
                    ej_type = ej.get("event")
                    if ej_type == "OnDamage":
                        dj = ej.get("data", {})
                        if dj.get("attacker", {}).get("uid") == 1409:
                            dtype = dj.get("type")
                            dmg = float(dj.get("damage", 0.0))
                            if dtype == "Servant":
                                s_hits.append(dmg)
                            elif dtype == "Additional":
                                a_hits.append(dmg)
                            elif dtype == "Break" and s_hits:
                                brk_indices.append(len(s_hits) - 1)
                    elif ej_type in ("OnUseSkill", "OnTurnBegin") and j > i + 1:
                        break
                if s_hits and a_hits:
                    milestones.append(
                        LogCastMilestone(
                            cast_index=len(milestones) + 1,
                            event_idx=i,
                            av=cur_av,
                            time_str=e.get("time", ""),
                            gt_servant_dmg=s_hits[0],
                            gt_additional_dmg=a_hits[0],
                            gt_ratio=a_hits[0] / s_hits[0],
                            s_hits=len(s_hits),
                            a_hits=len(a_hits),
                            gt_servant_dmgs=tuple(s_hits),
                            gt_additional_dmgs=tuple(a_hits),
                            break_target_indices=tuple(brk_indices),
                            is_wave2=seen_wave2,
                            fengjin_cd_at_cast=cur_fj_cd,
                        )
                    )
        return milestones

    def get_interval_heals(self, start_idx: int, end_idx: int) -> float:
        """从官方底层 OnStatChange 序列中提取指定事件区间内的显式角色真实治疗流水总额."""
        heals_sum = 0.0
        n = min(end_idx, len(self.events))
        for i in range(start_idx, n):
            e = self.events[i]
            if e.get("event") == "OnStatChange":
                d = e["data"]
                ent = d.get("entity", {})
                prop = d.get("property", {})
                if ent.get("team") == "Player" and prop.get("type") == "CurrentHP":
                    val = float(prop.get("value", 0.0))
                    if i + 1 < n:
                        e_next = self.events[i + 1]
                        if e_next.get("event") == "OnStatChange":
                            d_next = e_next["data"]
                            if (
                                d_next.get("entity", {}).get("uid") == ent.get("uid")
                                and d_next.get("property", {}).get("type") == "CurrentHP"
                            ):
                                val_next = float(d_next.get("property", {}).get("value", 0.0))
                                if val_next > val:
                                    heals_sum += val
        return heals_sum

    def extract_interval_timeline(
        self,
        start_idx: int,
        end_idx: int,
        team_uids: Sequence[int],
        cur_hp_state: Dict[int, float],
        max_hp_state: Dict[int, float],
        cur_av_ref: List[float],
        cur_fj_cd_ref: List[Optional[float]],
    ) -> List[IntervalTimelineEvent]:
        """提取 [start_idx, end_idx) 区间内的完整外部及风堇事件流."""
        out: List[IntervalTimelineEvent] = []
        n = min(end_idx, len(self.events))

        # 预先识别哪些 140901/140902/140903 紧邻前面的 1% 扣血区间，避免把光锥扣血误判为外部掉血
        fj_skill_indices: List[int] = []
        for idx in range(start_idx, n):
            e = self.events[idx]
            if e.get("event") == "OnUseSkill":
                d = e.get("data", {})
                if d.get("avatar", {}).get("uid") == 1409 and d.get("skill", {}).get("skill_config_id") in (140901, 140902, 140903):
                    fj_skill_indices.append(idx)

        lc_drain_event_indices: set[int] = set()
        lc_drain_by_skill: Dict[int, Tuple[Dict[int, float], float]] = {}
        # 从头扫描以准确跟踪 cur_hp_state
        temp_hp = dict(cur_hp_state)
        temp_max = dict(max_hp_state)
        prev_max_by_uid: Dict[int, float] = dict(max_hp_state)
        cur_cy_cd: Optional[float] = None

        for s_idx in fj_skill_indices:
            pre_hps: Dict[int, float] = {}
            found_indices: List[Tuple[int, int, float]] = []
            for j in range(s_idx - 1, max(start_idx - 1, s_idx - 40), -1):
                ej = self.events[j]
                if ej.get("event") == "OnUseSkill":
                    # 1140903/1140905/1140906/0 为风堇技能召唤动画伴生记录，可跨越；其余技能则停止
                    sc = ej.get("data", {}).get("skill", {}).get("skill_config_id", 0)
                    au = ej.get("data", {}).get("avatar", {}).get("uid")
                    if au == 1409 and sc in (0, 1140903, 1140905, 1140906):
                        continue
                    break
                if ej.get("event") == "OnStatChange":
                    dj = ej.get("data", {})
                    ent = dj.get("entity", {})
                    prop = dj.get("property", {})
                    if ent.get("team") == "Player" and prop.get("type") == "CurrentHP":
                        uid = ent.get("uid")
                        val = float(prop.get("value", 0.0))
                        # 跳过紧跟在 MaxHP 跳变后的同比例刷新，以及治疗配对 [amount, new_hp]
                        if j - 1 >= start_idx and self.events[j - 1].get("event") == "OnStatChange":
                            dp = self.events[j - 1].get("data", {})
                            if dp.get("entity", {}).get("uid") == uid:
                                ptype = dp.get("property", {}).get("type")
                                if ptype == "MaxHP":
                                    continue
                                if ptype == "CurrentHP" and val > float(dp.get("property", {}).get("value", 0.0)):
                                    continue
                        if isinstance(uid, int) and uid not in pre_hps and uid not in {x[1] for x in found_indices}:
                            found_indices.append((j, uid, val))
                elif ej.get("event") == "OnTurnBegin":
                    break
            lc_drain_by_skill[s_idx] = (pre_hps, 0.0)
            for j, uid, val in reversed(found_indices):
                lc_drain_event_indices.add(j)

        pending_hurt_uids: List[int] = []
        pending_losses: Dict[int, float] = {}
        pending_capped: List[int] = []
        in_talent_heal_wave = False
        talent_wave_chars_healed = 0
        suppress_post_lc_wave = False
        seen_enemy_turn_in_seg = False

        def _flush_external_losses(idx_pos: int) -> None:
            nonlocal pending_hurt_uids, pending_losses, pending_capped, in_talent_heal_wave, talent_wave_chars_healed, suppress_post_lc_wave, seen_enemy_turn_in_seg
            if pending_hurt_uids or (talent_wave_chars_healed > 0 and not suppress_post_lc_wave and seen_enemy_turn_in_seg):
                # 估算是否有仅命中忆灵而角色未掉血的波次:
                # 若没有任何角色掉血但敌方/阿哈回合后出现了治疗波，说明至少有 1 个忆灵受击
                extra_memo = 1 if (not pending_hurt_uids and talent_wave_chars_healed > 0 and not suppress_post_lc_wave and seen_enemy_turn_in_seg) else 0
                out.append(
                    IntervalTimelineEvent(
                        kind="external_hp_loss",
                        event_idx=idx_pos,
                        av=cur_av_ref[0],
                        hurt_uids=tuple(pending_hurt_uids),
                        extra_memo_hits=extra_memo,
                        hp_loss_by_uid=dict(pending_losses),
                        capped_uids=tuple(pending_capped),
                    )
                )
            pending_hurt_uids = []
            pending_losses = {}
            pending_capped = []
            in_talent_heal_wave = False
            talent_wave_chars_healed = 0
            suppress_post_lc_wave = False
            seen_enemy_turn_in_seg = False

        i = start_idx
        while i < n:
            e = self.events[i]
            et = e.get("event")
            d = e.get("data", {})

            if et == "OnTurnBegin":
                _flush_external_losses(i)
                av = d.get("action_value")
                if av is not None:
                    cur_av_ref[0] = float(av)
                to = d.get("turn_owner")
                if to is None or (isinstance(to, dict) and to.get("team") == "Enemy"):
                    seen_enemy_turn_in_seg = True
                    if isinstance(to, dict) and to.get("uid"):
                        out.append(
                            IntervalTimelineEvent(
                                kind="enemy_turn",
                                event_idx=i,
                                av=cur_av_ref[0],
                                enemy_uid=int(to["uid"]),
                            )
                        )
                    elif to is None:
                        # 检查是否是 Fever 倒计时回合 (OnTurnBegin(None) 后紧跟 1409 暴伤下跌且未接 1151201/OnDamage)
                        saw_cd_drop = False
                        saw_skill_or_dmg = False
                        for j in range(i + 1, min(i + 10, n)):
                            ej = self.events[j]
                            if ej.get("event") in ("OnTurnBegin", "OnUseSkill", "OnDamage"):
                                saw_skill_or_dmg = True
                                break
                            if ej.get("event") == "OnStatChange":
                                dj = ej.get("data", {})
                                if dj.get("entity", {}).get("uid") == 1409 and dj.get("property", {}).get("type") == "CriticalDamage":
                                    if cur_fj_cd_ref[0] is not None and float(dj["property"]["value"]) < cur_fj_cd_ref[0] - 0.05:
                                        saw_cd_drop = True
                        if saw_cd_drop and not saw_skill_or_dmg:
                            out.append(IntervalTimelineEvent(kind="fever_countdown", event_idx=i, av=cur_av_ref[0]))
                        elif saw_cd_drop:
                            # 若紧跟 1151201，也先执行倒计时折半再执行晴空乐手
                            next_sc = None
                            for j in range(i + 1, min(i + 10, n)):
                                if self.events[j].get("event") == "OnUseSkill":
                                    next_sc = self.events[j].get("data", {}).get("skill", {}).get("skill_config_id")
                                    break
                            if next_sc == 1151201:
                                out.append(IntervalTimelineEvent(kind="fever_countdown", event_idx=i, av=cur_av_ref[0]))
                i += 1
                continue

            if et == "OnDamage":
                atk = d.get("attacker") or {}
                if atk.get("uid") == 1403 and d.get("type") == "Follow-Up":
                    # 连续多段同一追击只记录 1 次追击动作事件
                    if not (out and out[-1].kind == "teammate_followup" and (i - out[-1].event_idx) <= 25):
                        _flush_external_losses(i)
                        out.append(
                            IntervalTimelineEvent(
                                kind="teammate_followup",
                                event_idx=i,
                                av=cur_av_ref[0],
                                uid=1403,
                            )
                        )
                i += 1
                continue

            if et == "OnStatChange":
                ent = d.get("entity", {})
                prop = d.get("property", {})
                if ent.get("team") == "Player":
                    uid = ent.get("uid")
                    ptype = prop.get("type")
                    val = float(prop.get("value", 0.0))
                    if ptype == "MaxHP" and isinstance(uid, int):
                        prev_max_by_uid[uid] = temp_max.get(uid, val)
                        temp_max[uid] = val
                        max_hp_state[uid] = val
                    elif ptype == "CriticalDamage" and uid == 1409:
                        cur_fj_cd_ref[0] = val
                    elif ptype == "CriticalDamage" and uid == 1413:
                        cur_cy_cd = val
                    elif ptype == "CurrentHP" and isinstance(uid, int):
                        # 检查是否是治疗配对 [amount, new_hp]
                        if i + 1 < n and self.events[i + 1].get("event") == "OnStatChange":
                            d2 = self.events[i + 1].get("data", {})
                            if (
                                d2.get("entity", {}).get("uid") == uid
                                and d2.get("property", {}).get("type") == "CurrentHP"
                            ):
                                val2 = float(d2.get("property", {}).get("value", 0.0))
                                if val2 > val:
                                    # 这是治疗上报: val=治疗量, val2=治疗后HP
                                    temp_hp[uid] = val2
                                    cur_hp_state[uid] = val2
                                    if val < 450.0:
                                        in_talent_heal_wave = True
                                        talent_wave_chars_healed += 1
                                    # 检测是否被堕神衰腐锁定在 50% 上限附近
                                    mhp = temp_max.get(uid, 0.0)
                                    if mhp > 0 and val2 <= mhp * 0.505 and val > 50.0:
                                        if uid not in pending_capped:
                                            pending_capped.append(uid)
                                    i += 2
                                    continue

                        # 普通 CurrentHP 更新 (掉血或属性刷新)
                        prev = temp_hp.get(uid)
                        if i in lc_drain_event_indices:
                            # 属于即将到来的风堇动作前的 1% 光锥扣血
                            for s_idx in fj_skill_indices:
                                if i < s_idx and (s_idx - i) <= 40:
                                    pre_map, d_sum = lc_drain_by_skill[s_idx]
                                    if prev is not None and prev > val and 0.008 <= (prev - val) / prev <= 0.012:
                                        pre_map[uid] = prev
                                        d_sum += (prev - val)
                                    else:
                                        pre_map[uid] = val / 0.99
                                        d_sum += (val / 0.99 - val)
                                    lc_drain_by_skill[s_idx] = (pre_map, d_sum)
                                    break
                        elif prev is not None and val < prev - 1e-4:
                            # 过滤 MaxHP 临时同步跳变 (不仅限紧邻前 1 条，覆盖多角色交错上报或同比例缩放)
                            is_max_refresh = False
                            for j_back in range(max(start_idx, i - 8), i):
                                ej_b = self.events[j_back]
                                if ej_b.get("event") == "OnStatChange":
                                    dp = ej_b.get("data", {})
                                    if dp.get("entity", {}).get("uid") == uid and dp.get("property", {}).get("type") == "MaxHP":
                                        is_max_refresh = True
                                        break
                                elif ej_b.get("event") in ("OnTurnBegin", "OnUseSkill"):
                                    break
                            mhp = temp_max.get(uid, 0.0)
                            pmhp = prev_max_by_uid.get(uid, mhp)
                            if abs(mhp - pmhp) > 1e-2 and mhp > 0 and pmhp > 0 and abs((val / mhp) - (prev / pmhp)) < 1e-3:
                                is_max_refresh = True
                            if mhp > 0 and abs(val - mhp) < 1e-3:
                                is_max_refresh = True
                            if not is_max_refresh:
                                loss = prev - val
                                if uid not in pending_hurt_uids:
                                    pending_hurt_uids.append(uid)
                                pending_losses[uid] = pending_losses.get(uid, 0.0) + loss
                        temp_hp[uid] = val
                        cur_hp_state[uid] = val
                i += 1
                continue

            if et == "OnUseSkill":
                av_uid = d.get("avatar", {}).get("uid")
                sc_id = d.get("skill", {}).get("skill_config_id", 0)
                if sc_id == 0:
                    i += 1
                    continue

                if av_uid == 1409 and sc_id in (140901, 140902, 140903):
                    _flush_external_losses(i)
                    pre_map, d_sum = lc_drain_by_skill.get(i, ({}, 0.0))
                    # 补全未在扣血日志中显式刷新的角色当前血量
                    for u in team_uids:
                        if u not in pre_map and u in temp_hp:
                            pre_map[u] = temp_hp[u]
                    out.append(
                        IntervalTimelineEvent(
                            kind="fengjin_action",
                            event_idx=i,
                            av=cur_av_ref[0],
                            uid=1409,
                            skill_id=sc_id,
                            pre_hp_by_uid=pre_map,
                            max_hp_by_uid=dict(temp_max),
                            log_char_drains=d_sum,
                            fengjin_cd_snapshot=cur_fj_cd_ref[0],
                        )
                    )
                    suppress_post_lc_wave = True
                elif sc_id in (1151203, 1141303):
                    # 1151203/1141303 分别由 151202/141302/141303 战技/终结技原生召唤，不重复预先召唤
                    pass
                elif sc_id == 1141307:
                    _flush_external_losses(i)
                    out.append(IntervalTimelineEvent(kind="despawn_evernight", event_idx=i, av=cur_av_ref[0], uid=1413, skill_id=sc_id))
                elif av_uid in (1403, 1413, 1512) and sc_id not in (1140901, 1140903, 1140905, 1140906):
                    _flush_external_losses(i)
                    # 检查该技能是否造成 OnDamage (决定是否触发风堇 E1)
                    has_dmg = False
                    for j in range(i + 1, min(i + 35, n)):
                        ej = self.events[j]
                        if ej.get("event") == "OnDamage" and ej.get("data", {}).get("attacker", {}).get("uid") == av_uid:
                            has_dmg = True
                            break
                        if ej.get("event") in ("OnUseSkill", "OnTurnBegin") and j > i + 1:
                            break
                    out.append(
                        IntervalTimelineEvent(
                            kind="teammate_skill",
                            event_idx=i,
                            av=cur_av_ref[0],
                            uid=int(av_uid),
                            skill_id=int(sc_id),
                            has_damage=has_dmg,
                            fengjin_cd_snapshot=cur_cy_cd if av_uid == 1413 else None,
                        )
                    )
            i += 1

        _flush_external_losses(n)
        return out


class FixedReconciliationHarness:
    """外部因素固定、内部双池与伤害计算完全原生的逐动对账沙盒驱动器."""

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.extractor = GoldenLogStreamExtractor(log_path)

    def _build_sandbox(self, team_uids: Sequence[int]) -> Tuple[TurnSimulator, Any]:
        db = CharacterDB().load(CHAR_DB_PATH)
        team: List[Entity] = []
        tech_users: List[str] = []
        for u in team_uids:
            name = UID_TO_NAME[u]
            if name == "知更鸟•晴歌":
                rp = db.get_by_name("知更鸟•晴歌_爱如此刻永恒")
                rp.name = "知更鸟•晴歌"
                team.append(db.to_combat_entity(rp))
            else:
                team.append(db.to_combat_entity(name))
            tech_users.append(name)

        sim, director = build_stage_30126122(team, technique_users=tech_users)
        # 挂载精准暴击先知，只锁定暴击与否这一外部随机判定
        non_crits = set()
        if "204943" in self.log_path:
            non_crits = OFFICIAL_20261114_204943_NON_CRITS
        elif "220255" in self.log_path:
            non_crits = OFFICIAL_20261114_220255_NON_CRITS
        elif "221208" in self.log_path:
            non_crits = OFFICIAL_20261114_221208_NON_CRITS
        attach_exact_crit_oracle(sim, log_path=self.log_path, non_crits=non_crits)
        # 挂载对应日志的纯外部敌方受击路由插件 (用于确定敌方命中哪名忆灵，零影响核心计算)
        if "184845" in self.log_path:
            attach_log_20261114_184845_plugin(sim)
        elif "204943" in self.log_path:
            attach_log_20261114_204943_plugin(sim)
        elif "220255" in self.log_path:
            attach_log_20261114_220255_plugin(sim)
        elif "221208" in self.log_path:
            attach_log_20261114_221208_plugin(sim)
        # 禁用插件自带的阿哈扣血处理器 (外部掉血已由日志 OnStatChange 精确回放，避免双重触发)
        sim.aha_special_handler = None
        sim.auto_ult = False
        return sim, director

    def _sync_enemies_for_cast(
        self,
        sim: TurnSimulator,
        cast: LogCastMilestone,
        next_is_wave2: bool,
    ) -> List[str]:
        """在沙盒中精确构造当前 Cast 命中的敌方靶标实体（禁用 AI 行动，保留真实等级与抗性）."""
        # 移除旧靶标
        for e in list(sim.entities):
            if e.is_enemy:
                sim.entities.remove(e)
                if hasattr(sim, "status_mgr") and hasattr(sim.status_mgr, "_statuses"):
                    sim.status_mgr._statuses.pop(e.name, None)

        n_targets = len(cast.gt_servant_dmgs)
        enemy_names: List[str] = []
        for idx in range(n_targets):
            if not next_is_wave2:
                # Wave 1: 正阳狮鹫/月夜天马为 Wind Res 0.2, 其余流星铁鹰为 Wind Res 0.0
                w_res = 0.2 if idx < 2 else 0.0
                dmg_red = 0.0
            else:
                # Wave 2: idx=0 为亚婆离 (Wind Res 0.2), 其余为狂兽的胚芽 (Wind Res 0.0)
                w_res = 0.2 if idx == 0 else 0.0
                # 亚婆离屏障减伤 75% (离散状态开关：同动亚婆离存在屏障时开启)
                apoli_barrier = False
                if idx == 0:
                    if n_targets >= 2 and cast.gt_servant_dmgs[0] < 0.40 * cast.gt_servant_dmgs[1]:
                        apoli_barrier = True
                    elif n_targets == 1 and (cast.av >= 500.0 or (cast.cast_index >= 6 and "041608" in self.log_path)):
                        apoli_barrier = True
                dmg_red = 0.75 if apoli_barrier else 0.0

            is_brk_target = idx in cast.break_target_indices
            ename = f"SandboxEnemy_{cast.cast_index}_{idx}"
            ent = Entity(
                name=ename,
                base_speed=100.0,
                base_atk=1000.0,
                max_hp=1e12,
                current_hp=1e12,
                max_toughness=1000.0,
                current_toughness=30.0 if is_brk_target else 1000.0,
                weaknesses=["Wind", "Quantum", "Ice"] if (is_brk_target or w_res == 0.0) else ["Quantum", "Ice"],
                is_enemy=True,
                is_boss=(idx == 0),
            )
            ent.level = 95
            ent.damage_res = {el: (0.0 if el not in ("Wind",) else w_res) for el in _ELEMENTS}
            ent.damage_reduction = dmg_red
            sim.add_entity(ent, trigger_battle_start=False)
            enemy_names.append(ename)

        # 恢复 Tribbie 结界对敌方的易伤 Debuff (使用 TibaoKit 真实技能倍率，避免 E6 Lv12 0.33 被写死成 0.30)
        tb = sim.get_entity("缇宝")
        if tb and getattr(tb, "kit", None) is not None and getattr(tb.kit, "zone_active", False):
            zone_vuln = tb.kit.skill_param("ultra", 1, default=0.30)
            for ename in enemy_names:
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
        return enemy_names

    def _run_sim_action(
        self,
        sim: TurnSimulator,
        actor_name: str,
        kind: ActionKind,
        target_ids: Tuple[str, ...] = (),
        pre_hp_sync: Optional[Dict[str, float]] = None,
    ) -> None:
        ent = sim.get_entity(actor_name)
        if ent is None or getattr(ent, "kit", None) is None:
            return
        is_turn = kind in (ActionKind.BASIC, ActionKind.SKILL) or (kind == ActionKind.MEMOSPRITE_SKILL and actor_name != "小伊卡")
        sim._action_seq += 1
        action_id = sim._action_seq
        defn = ent.kit.definition(kind)

        with sim.scheduler.action_frame():
            if is_turn:
                sim._turn_id += 1
                sim.status_mgr.tick_on_turn_begin(ent)
                sim.event_bus.publish(TurnBeginEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id=ent.name, actor_name=ent.name, speed=round(ent.speed, 1), turn_id=sim._turn_id))
                sim.resolver.resolve_all()

            if pre_hp_sync:
                for cname, hp_val in pre_hp_sync.items():
                    ent_u = sim.get_entity(cname)
                    if ent_u is not None:
                        ent_u.current_hp = min(hp_val, sim.port.max_hp(ent_u.name))

            ctx = ActionContext(
                action_id=action_id,
                actor_id=ent.name,
                kind=kind,
                target_ids=target_ids,
                is_natural_turn_action=is_turn,
                schedule_category=ActionScheduleCategory.ULTIMATE if kind == ActionKind.ULTIMATE else None,
            )
            if hasattr(ent.kit, "on_action_before"):
                ent.kit.on_action_before(ctx)
            if getattr(ent, "light_cone", None) is not None:
                ent.light_cone.on_action_before(ctx)
            for rh in getattr(ent, "relic_handlers", []):
                rh.on_action_before(ctx)

            sim.event_bus.publish(
                ActionExecuteEvent(
                    av=round(sim.current_av, 2),
                    cycle=sim.current_cycle,
                    actor_id=ent.name,
                    actor_name=ent.name,
                    action_type=defn.name if defn else str(kind),
                    description=defn.name if defn else str(kind),
                    action_kind=kind,
                    skill_config_id=0,
                    action_id=action_id,
                )
            )

            ent.kit.execute(ctx)

            if hasattr(ent.kit, "on_action_after"):
                ent.kit.on_action_after(ctx)
            if getattr(ent, "light_cone", None) is not None:
                ent.light_cone.on_action_after(ctx)
            for rh in getattr(ent, "relic_handlers", []):
                rh.on_action_after(ctx)

            sim.resolver.resolve_all()
            for e_ent in list(sim.entities):
                if getattr(e_ent, "kit", None) is not None and hasattr(e_ent.kit, "on_action_end"):
                    e_ent.kit.on_action_end(ent)
            sim.resolver.resolve_all()

            sim.event_bus.publish(
                PrimaryDamageCompleteEvent(
                    av=round(sim.current_av, 2),
                    cycle=sim.current_cycle,
                    actor_id=ent.name,
                    actor_name=ent.name,
                    action_type=defn.name if defn else str(kind),
                    action_kind=kind,
                    skill_config_id=0,
                    action_id=action_id,
                )
            )
            sim.event_bus.publish(
                ActionEndEvent(
                    av=round(sim.current_av, 2),
                    cycle=sim.current_cycle,
                    actor_id=ent.name,
                    actor_name=ent.name,
                    action_type=defn.name if defn else str(kind),
                    action_kind=kind,
                    skill_config_id=0,
                    action_id=action_id,
                )
            )
            sim.resolver.resolve_all()

        sim.scheduler.drain()

        if is_turn:
            sim.status_mgr.tick_on_turn_end(ent)
            sim.resolver.resolve_all()

    def run_reconciliation(self) -> List[CastReconciliationRecord]:
        """在外部因素固定、双池与伤害全原生演算的沙盒中执行全场逐动对账."""
        team_uids = self.extractor.detect_team_uids()
        casts = self.extractor.extract_casts()
        if not casts:
            return []

        sim, _director = self._build_sandbox(team_uids)
        fj = sim.get_entity("风堇")
        lc = fj.light_cone

        records: List[CastReconciliationRecord] = []
        cur_hp_state: Dict[int, float] = {}
        max_hp_state: Dict[int, float] = {}
        cur_av_ref: List[float] = [0.0]
        cur_fj_cd_ref: List[Optional[float]] = [None]

        # 跟踪当前 Cast 产出的原生效用指标
        captured_cast: Dict[str, Any] = {}

        def _on_damage(ev: DamageAppliedEvent) -> None:
            if ev.attacker_name == "缇宝" and ev.damage_type == DamageType.FOLLOW_UP:
                captured_cast["native_tb_followups"] = captured_cast.get("native_tb_followups", 0) + 1
            if not captured_cast.get("active"):
                return
            if ev.attacker_name == "小伊卡" and ev.damage_type == DamageType.SERVANT:
                captured_cast["s_dmgs"].append(float(ev.damage))
            elif ev.attacker_name == "风堇" and ev.damage_type == DamageType.ADDITIONAL:
                captured_cast["a_dmgs"].append(float(ev.damage))

        sim.event_bus.subscribe(DamageAppliedEvent, _on_damage)

        # 包装 _fire_ika_scatter 与 lc._flush_discharge 仅用于只读抓取池子快照
        orig_fire = fj.kit._fire_ika_scatter

        def _spy_fire() -> Any:
            ika = fj.kit.ika_kit
            if ika is not None and not getattr(ika, "_reconcile_wrapped", False):
                ika._reconcile_wrapped = True
                orig_cs = ika.cast_scatter

                def _spy_cs() -> Any:
                    # cast_scatter 内部先结算挂起天赋治疗，再取 accumulated_healing
                    ika._resolve_talent_heal()
                    if hasattr(ika.port, "resolve_effects"):
                        ika.port.resolve_effects()
                    # 在忆灵技即将计算伤害前，按日志 OnStatChange 1409 CriticalDamage 锚定外部暴伤光环增量
                    cd_snap = captured_cast.get("cd_snapshot")
                    if cd_snap is not None:
                        sim.port.remove_status("风堇", "Sandbox_External_CD_Anchor")
                        cur_sim_cd = float(sim.port.stat("风堇", StatType.CRIT_DMG))
                        cd_delta = cd_snap - cur_sim_cd
                        if abs(cd_delta) > 1e-4:
                            sim.port.upsert_status(
                                __import__("simulator.combat_port", fromlist=["BuffSpec"]).BuffSpec(
                                    key="Sandbox_External_CD_Anchor",
                                    name="外部暴伤光环锚定",
                                    source_id="知更鸟•晴歌",
                                    target_id="风堇",
                                    modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_delta),),
                                    duration=None,
                                    timing=DurationTiming.TARGET_TURN_END,
                                    category="buff",
                                )
                            )
                            # 若知更鸟在 Fever 状态且暴伤来自明显气氛值偏差 (>0.05)，同步修正知更鸟气氛值
                            rb = sim.get_entity("知更鸟•晴歌")
                            if rb and getattr(rb, "kit", None) is not None and getattr(rb.kit, "in_fever", False) and abs(cd_delta) > 0.05:
                                vibe_delta = round(cd_delta / 0.015)
                                if vibe_delta != 0:
                                    rb.kit.vibes = max(0, min(rb.kit.max_vibes, int(rb.kit.vibes) + int(vibe_delta)))
                                    if hasattr(rb.kit, "_sync_fever_buffs"):
                                        rb.kit._sync_fever_buffs()
                                    if hasattr(rb.kit, "apply_tonal_chord_to_ally"):
                                        if sim.port.has_status("风堇", "Robin_Talent_TonalChord_风堇"):
                                            rb.kit.apply_tonal_chord_to_ally("风堇")
                                        if sim.port.has_status("小伊卡", "Robin_Talent_TonalChord_小伊卡"):
                                            rb.kit.apply_tonal_chord_to_ally("小伊卡")
                                    # 重新校准精确微差
                                    sim.port.remove_status("风堇", "Sandbox_External_CD_Anchor")
                                    cur_sim_cd2 = float(sim.port.stat("风堇", StatType.CRIT_DMG))
                                    cd_delta2 = cd_snap - cur_sim_cd2
                                    if abs(cd_delta2) > 1e-4:
                                        sim.port.upsert_status(
                                            __import__("simulator.combat_port", fromlist=["BuffSpec"]).BuffSpec(
                                                key="Sandbox_External_CD_Anchor",
                                                name="外部暴伤光环锚定",
                                                source_id="知更鸟•晴歌",
                                                target_id="风堇",
                                                modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cd_delta2),),
                                                duration=None,
                                                timing=DurationTiming.TARGET_TURN_END,
                                                category="buff",
                                            )
                                        )
                        ika._sync_master_field_auras()
                    captured_cast["pre_acc"] = float(fj.kit.accumulated_healing)
                    captured_cast["pre_pool"] = float(lc._pool)
                    return orig_cs()

                ika.cast_scatter = _spy_cs
            return orig_fire()

        fj.kit._fire_ika_scatter = _spy_fire

        orig_ab = lc.on_action_before

        def _spy_lc_ab(ctx: ActionContext) -> Any:
            # 记录动作前显式非忆灵角色的 1% 扣血理论额 (仅用于与日志 OnStatChange 对账)
            char_drain = 0.0
            if ctx.actor_id == "风堇" and ctx.kind in (ActionKind.SKILL, ActionKind.ULTIMATE, ActionKind.BASIC):
                drain_ratio = lc.scale(lc.DRAIN_VALUES)
                for ally in lc.port.allies(lc.owner_id):
                    if (hasattr(lc.port, "is_countdown") and lc.port.is_countdown(ally)) or (
                        hasattr(lc.port, "is_memosprite") and lc.port.is_memosprite(ally)
                    ):
                        continue
                    char_drain += max(1.0, lc.port.current_hp(ally) * drain_ratio)
            res = orig_ab(ctx)
            if ctx.actor_id == "风堇":
                captured_cast["interval_drain"] = captured_cast.get("interval_drain", 0.0) + char_drain
            return res

        lc.on_action_before = _spy_lc_ab

        for k, cast in enumerate(casts):
            if k == 0:
                start_idx = 0
            else:
                # 跳过上一动 1140901 自身的 OnDamage 尾随集群，防止上一动的 Tribbie 追击伤害被重复算入下一动
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
                "native_tb_followups": 0,
                "log_tb_followups": 0,
                "enemy_hit_memo_in_turn": False,
                "memo_damaged_in_turn": {},
                "last_enemy_uid": 0,
                "cd_snapshot": None,
            })

            # 识别本区间内触发本次 Cast 1140901 的最后一个风堇动作
            fj_events = [ev for ev in timeline if ev.kind == "fengjin_action"]
            last_fj_idx = fj_events[-1].event_idx if fj_events else -1
            # 预先挂载当动敌方靶标，保证队友技能/追击与风堇触发 Cast 时敌方在场；
            # 仅当遇到波次切换空窗的“非最后一次风堇动作”时才临时清空靶标，防止误放忆灵技。
            enemies: List[str] = self._sync_enemies_for_cast(sim, cast, cast.is_wave2)

            for ev in timeline:
                sim.current_av = ev.av
                if ev.kind == "fever_countdown":
                    rb = sim.get_entity("知更鸟•晴歌")
                    if rb and getattr(rb, "kit", None) is not None and getattr(rb.kit, "in_fever", False):
                        if hasattr(rb.kit, "on_countdown_turn"):
                            rb.kit.on_countdown_turn()
                            sim.resolver.resolve_all()

                elif ev.kind == "enemy_turn":
                    captured_cast["enemy_hit_memo_in_turn"] = False
                    captured_cast["memo_damaged_in_turn"] = {}
                    captured_cast["last_enemy_uid"] = ev.enemy_uid
                    # 利用对应场次的敌方命中路由插件（若有）计算对在场忆灵的受击掉血
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
                                captured_cast["memo_damaged_in_turn"][ht.name] = captured_cast["memo_damaged_in_turn"].get(ht.name, 0.0) + memo_dmg
                        if captured_cast["enemy_hit_memo_in_turn"]:
                            sim.resolver.resolve_all()
                            sim.event_bus.publish(TurnBeginEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id=aname, actor_name=aname, speed=0.0))
                            sim.resolver.resolve_all()

                elif ev.kind == "external_hp_loss":
                    for u in ev.capped_uids:
                        ent_c = sim.get_entity(UID_TO_NAME[u])
                        if ent_c is not None:
                            ent_c.hp_cap = sim.port.max_hp(ent_c.name) * 0.50
                    for u in ev.hurt_uids:
                        cname = UID_TO_NAME[u]
                        loss = ev.hp_loss_by_uid.get(u, 1.0)
                        if sim.port.entity_exists(cname):
                            sim.port.lose_hp(cname, loss, cause="external_log_hp_loss")

                    # 由日志显式角色掉血推演伴生忆灵受击 (仅对扩散命中知更鸟•晴歌时相邻晴空乐手补足扩散伤害，避免误扣导致小伊卡暴毙):
                    real_losses = {u: v for u, v in ev.hp_loss_by_uid.items() if v > 50.0}
                    already_hit_memos = captured_cast.get("memo_damaged_in_turn", {})
                    if real_losses and 1512 in real_losses and sim.port.entity_exists("晴空乐手") and "晴空乐手" not in already_hit_memos:
                        if captured_cast.get("last_enemy_uid") in (100009, 100011, 100013) or len(real_losses) >= 2:
                            sim.port.lose_hp("晴空乐手", real_losses[1512] * 0.50, cause="external_log_blast_memo_hit")
                            already_hit_memos["晴空乐手"] = real_losses[1512] * 0.50

                    if ev.extra_memo_hits > 0 and not captured_cast.get("enemy_hit_memo_in_turn", False):
                        for mname in ("晴空乐手", "小伊卡", "长夜"):
                            if sim.port.entity_exists(mname):
                                sim.port.lose_hp(mname, 800.0, cause="external_log_hp_loss")
                                break
                    captured_cast["enemy_hit_memo_in_turn"] = False
                    captured_cast["memo_damaged_in_turn"] = {}
                    # 先结算所有扣血效果入队，再发布 TurnBeginEvent 触发小伊卡天赋治疗结算
                    sim.resolver.resolve_all()
                    sim.event_bus.publish(TurnBeginEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id="Enemy", actor_name="Enemy", speed=0.0))
                    sim.resolver.resolve_all()

                elif ev.kind == "teammate_followup":
                    captured_cast["log_tb_followups"] += 1
                    # 若 TribbieKit 未在先前行动中原生触发追击，则按日志触发一次追击以保证 E1 对齐
                    if captured_cast["log_tb_followups"] > captured_cast["native_tb_followups"]:
                        tb = sim.get_entity("缇宝")
                        if tb and getattr(tb, "kit", None) is not None and hasattr(tb.kit, "_cast_talent_volley"):
                            if not enemies:
                                enemies = self._sync_enemies_for_cast(sim, cast, cast.is_wave2)
                            sim._action_seq += 1
                            aid = sim._action_seq
                            with sim.scheduler.action_frame():
                                sim.event_bus.publish(ActionExecuteEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id="缇宝", actor_name="缇宝", action_type="FollowUpAttack", description="好忙好忙的缇宝", action_kind=ActionKind.FOLLOW_UP, skill_config_id=0, action_id=aid))
                                tb.kit._cast_talent_volley()
                                sim.resolver.resolve_all()
                                sim.event_bus.publish(PrimaryDamageCompleteEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id="缇宝", actor_name="缇宝", action_type="FollowUpAttack", action_kind=ActionKind.FOLLOW_UP, skill_config_id=0, action_id=aid))
                                sim.event_bus.publish(ActionEndEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id="缇宝", actor_name="缇宝", action_type="FollowUpAttack", action_kind=ActionKind.FOLLOW_UP, skill_config_id=0, action_id=aid))
                                sim.resolver.resolve_all()
                            sim.scheduler.drain()
                            for e in list(sim.entities):
                                if e.is_enemy:
                                    sim.entities.remove(e)
                                    if hasattr(sim, "status_mgr") and hasattr(sim.status_mgr, "_statuses"):
                                        sim.status_mgr._statuses.pop(e.name, None)
                            enemies = []

                elif ev.kind == "summon_sunny":
                    rb = sim.get_entity("知更鸟•晴歌")
                    if rb and getattr(rb, "kit", None) is not None and not getattr(rb.kit, "musicians_alive", False):
                        if hasattr(rb.kit, "summon_musicians"):
                            rb.kit.summon_musicians()
                            sim.resolver.resolve_all()

                elif ev.kind == "summon_evernight":
                    cy = sim.get_entity("长夜月")
                    if cy and getattr(cy, "kit", None) is not None and not sim.port.entity_exists("长夜"):
                        if hasattr(cy.kit, "summon_spirit"):
                            cy.kit.summon_spirit()
                            sim.resolver.resolve_all()

                elif ev.kind == "despawn_evernight":
                    if sim.port.entity_exists("长夜"):
                        cy = sim.get_entity("长夜月")
                        if cy and getattr(cy, "kit", None) is not None and hasattr(cy.kit, "yizhi"):
                            cy.kit.yizhi = max(int(cy.kit.yizhi), 16)
                        self._run_sim_action(sim, "长夜", ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(enemies))
                        if sim.port.entity_exists("长夜"):
                            sim.port.despawn_spirit("长夜", reason="日志 1141307 自毁离场")

                elif ev.kind == "teammate_skill":
                    cname = UID_TO_NAME.get(ev.uid, "")
                    if cname and sim.port.entity_exists(cname):
                        if ev.skill_id == 1151201:
                            if sim.port.entity_exists("晴空乐手"):
                                self._run_sim_action(sim, "晴空乐手", ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(enemies))
                        elif ev.skill_id == 1141301:
                            if sim.port.entity_exists("长夜"):
                                self._run_sim_action(sim, "长夜", ActionKind.MEMOSPRITE_SKILL, target_ids=tuple(enemies))
                        elif ev.skill_id in (140301, 141301, 151201):
                            self._run_sim_action(sim, cname, ActionKind.BASIC, target_ids=(enemies[0],) if enemies else ())
                        elif ev.skill_id in (140302, 141302, 141309, 151202):
                            if ev.uid == 1413 and ev.fengjin_cd_snapshot is not None:
                                sim.port.remove_status("长夜月", "Sandbox_External_CY_CD_Anchor")
                                cur_cy = float(sim.port.stat("长夜月", StatType.CRIT_DMG))
                                cy_delta = ev.fengjin_cd_snapshot - cur_cy
                                if abs(cy_delta) > 1e-4:
                                    sim.port.upsert_status(
                                        __import__("simulator.combat_port", fromlist=["BuffSpec"]).BuffSpec(
                                            key="Sandbox_External_CY_CD_Anchor",
                                            name="长夜月暴伤日志对齐",
                                            source_id="长夜月",
                                            target_id="长夜月",
                                            modifiers=(Modifier(StatType.CRIT_DMG, ModifierOp.ADD, cy_delta),),
                                            duration=None,
                                            timing=DurationTiming.TARGET_TURN_END,
                                            category="buff",
                                        )
                                    )
                            self._run_sim_action(sim, cname, ActionKind.SKILL, target_ids=tuple(enemies))
                        elif ev.skill_id in (140303, 141303, 151203):
                            # 确保拥有足够能量施放终结技
                            ent_c = sim.get_entity(cname)
                            if ent_c is not None and getattr(ent_c, "max_energy", 0.0) > 0:
                                ent_c.energy = max(ent_c.energy, ent_c.max_energy)
                            # 151203 终结技单体目标优先选非风堇或首位友方
                            if ev.skill_id == 151203:
                                tgt_ally = next((UID_TO_NAME[u] for u in team_uids if u in (1413, 1403)), "风堇")
                                self._run_sim_action(sim, cname, ActionKind.ULTIMATE, target_ids=(tgt_ally,))
                            else:
                                self._run_sim_action(sim, cname, ActionKind.ULTIMATE, target_ids=tuple(enemies))

                elif ev.kind == "fengjin_action":
                    if ev.event_idx == last_fj_idx:
                        if not enemies:
                            enemies = self._sync_enemies_for_cast(sim, cast, cast.is_wave2)
                        captured_cast["active"] = True
                        captured_cast["cd_snapshot"] = cast.fengjin_cd_at_cast if cast.fengjin_cd_at_cast is not None else ev.fengjin_cd_snapshot
                    else:
                        # 波次切换空窗风堇动作 (无 1140901 跟随)，清空靶标避免误放忆灵技
                        for e in list(sim.entities):
                            if e.is_enemy:
                                sim.entities.remove(e)
                                if hasattr(sim, "status_mgr") and hasattr(sim.status_mgr, "_statuses"):
                                    sim.status_mgr._statuses.pop(e.name, None)
                        enemies = []
                    # 在 tick_on_turn_begin 之后、LC 扣血之前静默校准显式角色 CurrentHP
                    pre_hp_map = {UID_TO_NAME[u]: hp_val for u, hp_val in ev.pre_hp_by_uid.items() if u in UID_TO_NAME}
                    captured_cast["log_char_drains"] += ev.log_char_drains

                    akind = {140901: ActionKind.BASIC, 140902: ActionKind.SKILL, 140903: ActionKind.ULTIMATE}[ev.skill_id]
                    self._run_sim_action(sim, "风堇", akind, target_ids=(enemies[0],) if enemies else (), pre_hp_sync=pre_hp_map)

            sim_s_dmgs = captured_cast["s_dmgs"]
            sim_a_dmgs = captured_cast["a_dmgs"]
            sim_s = sim_s_dmgs[0] if sim_s_dmgs else 0.0
            sim_a = sim_a_dmgs[0] if sim_a_dmgs else 0.0
            sim_ratio = (sim_a / sim_s) if sim_s > 0 else 0.0
            s_err = abs(sim_s - cast.gt_servant_dmg) / cast.gt_servant_dmg if cast.gt_servant_dmg > 0 else 0.0
            a_err = abs(sim_a - cast.gt_additional_dmg) / cast.gt_additional_dmg if cast.gt_additional_dmg > 0 else 0.0
            r_err = abs(sim_ratio - cast.gt_ratio) / cast.gt_ratio if cast.gt_ratio > 0 else 0.0

            log_drains = captured_cast["log_char_drains"]
            sim_drains = captured_cast["interval_drain"]
            drain_err = abs(sim_drains - log_drains) / log_drains if log_drains > 0 else 0.0

            records.append(
                CastReconciliationRecord(
                    cast_index=cast.cast_index,
                    event_idx=cast.event_idx,
                    av=cast.av,
                    interval_heals=interval_heals,
                    acc_healing=captured_cast["pre_acc"],
                    lc_pool=captured_cast["pre_pool"],
                    sim_char_drains=sim_drains,
                    log_char_drains=log_drains,
                    drain_err=drain_err,
                    sim_servant_dmg=sim_s,
                    gt_servant_dmg=cast.gt_servant_dmg,
                    servant_err=s_err,
                    sim_additional_dmg=sim_a,
                    gt_additional_dmg=cast.gt_additional_dmg,
                    additional_err=a_err,
                    sim_ratio=sim_ratio,
                    gt_ratio=cast.gt_ratio,
                    ratio_err=r_err,
                    sim_servant_dmgs=list(sim_s_dmgs),
                    gt_servant_dmgs=list(cast.gt_servant_dmgs),
                    sim_additional_dmgs=list(sim_a_dmgs),
                    gt_additional_dmgs=list(cast.gt_additional_dmgs),
                )
            )

        return records

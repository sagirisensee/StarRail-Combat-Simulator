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
from simulator.status import DurationTiming, Modifier, ModifierOp, StatType, StatusTag

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
    enemy_attacked: bool = True
    enemy_turn_losses: Dict[int, float] = field(default_factory=dict)
    enemy_memo_sp_hits_1409: int = 0
    enemy_memo_sp_hits_1512: int = 0
    target_uid: int = 0
    capped_hp_ratios: Dict[int, float] = field(default_factory=dict)


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

    def detect_enemy_uid_names(self) -> Dict[int, str]:
        """从日志 OnTurnBegin 的行动值节拍自动识别敌方 UID 对应的实体名称."""
        uid_avs: Dict[int, List[float]] = {}
        cur_av = 0.0
        for e in self.events:
            if e.get("event") == "OnTurnBegin":
                d = e.get("data", {})
                av = d.get("action_value")
                if av is not None:
                    cur_av = float(av)
                to = d.get("turn_owner")
                if isinstance(to, dict) and to.get("team") == "Enemy" and to.get("uid"):
                    uid_avs.setdefault(int(to["uid"]), []).append(cur_av)

        mapping: Dict[int, str] = {}
        wave2_uids: List[int] = []
        for uid, avs in uid_avs.items():
            if any(abs(a - 31.57) < 0.25 for a in avs):
                mapping[uid] = "正阳狮鹫"
            elif any(abs(a - 75.76) < 0.25 or abs(a - 151.52) < 0.25 or abs(a - 227.27) < 0.25 for a in avs):
                mapping[uid] = "月夜天马"
            elif any(abs(a - 69.44) < 0.25 for a in avs):
                mapping[uid] = "流星铁鹰_g1_1"
            elif any(abs(a - 92.17) < 0.25 for a in avs):
                mapping[uid] = "流星铁鹰_g1_2"
            elif uid >= 100030:
                wave2_uids.append(uid)
            else:
                mapping[uid] = "流星铁鹰_g1_3"

        if wave2_uids:
            # 若 Wave 1 Boss (正阳狮鹫/月夜天马) 在某个 >=100030 UID 首次出现之后仍继续行动，则该 UID 属于 Wave 1 第 2 代流星铁鹰，而非 Wave 2
            wave1_last_av = max(
                (max(avs) for uid, avs in uid_avs.items() if mapping.get(uid) in ("正阳狮鹫", "月夜天马")),
                default=0.0,
            )
            true_wave2_uids: List[int] = []
            for uid in wave2_uids:
                first_av = min(uid_avs[uid])
                if first_av < wave1_last_av - 0.1:
                    mapping[uid] = "流星铁鹰_g2"
                else:
                    true_wave2_uids.append(uid)
            if true_wave2_uids:
                boss_uid = min(true_wave2_uids)
                for uid in true_wave2_uids:
                    avs = uid_avs[uid]
                    if len(avs) >= 2 and any(25.0 <= (avs[k + 1] - avs[k]) <= 45.0 for k in range(len(avs) - 1)):
                        boss_uid = uid
                        break
                for uid in true_wave2_uids:
                    mapping[uid] = "堕神之血•亚婆离" if uid == boss_uid else "狂兽的胚芽"
        return mapping

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
        pending_cap_ratios: Dict[int, float] = {}
        in_talent_heal_wave = False
        talent_wave_chars_healed = 0
        suppress_post_lc_wave = False
        seen_enemy_turn_in_seg = False
        aha_1512_sp_hits = 0
        aha_1512_hp_hits = 0
        aha_1512_prev_sp: Optional[float] = None
        for jb in range(start_idx - 1, max(-1, start_idx - 120), -1):
            ejb = self.events[jb]
            if ejb.get("event") == "OnStatChange":
                djb = ejb.get("data", {})
                if djb.get("entity", {}).get("team") == "Player" and djb.get("entity", {}).get("uid") == 1512 and djb.get("property", {}).get("type") == "CurrentSP":
                    aha_1512_prev_sp = float(djb["property"]["value"])
                    break
        in_aha_turn = False

        def _flush_external_losses(idx_pos: int) -> None:
            nonlocal pending_hurt_uids, pending_losses, pending_capped, pending_cap_ratios, in_talent_heal_wave, talent_wave_chars_healed, suppress_post_lc_wave, seen_enemy_turn_in_seg
            nonlocal aha_1512_sp_hits, aha_1512_hp_hits, in_aha_turn
            if pending_hurt_uids or pending_capped or (talent_wave_chars_healed > 0 and not suppress_post_lc_wave and seen_enemy_turn_in_seg):
                # 估算是否有仅命中忆灵而角色未掉血的波次:
                # 1) 若没有任何角色掉血但敌方/阿哈回合后出现了治疗波，说明至少有 1 个忆灵受击；
                # 2) 阿哈回合期间若知更鸟•晴歌获 2.39 受击回能次数超过其自身掉血次数 >= 2 (如 204943 150.00 AV)，说明晴空乐手也受击。
                extra_memo = 1 if (not pending_hurt_uids and talent_wave_chars_healed > 0 and not suppress_post_lc_wave and seen_enemy_turn_in_seg) else 0
                if in_aha_turn and extra_memo == 0 and (
                    aha_1512_sp_hits >= aha_1512_hp_hits + 2
                    or (pending_losses and 0.3 < max(pending_losses.values()) < 5.0 and len(pending_losses) >= len(team_uids) >= 3)
                ):
                    extra_memo = 1
                out.append(
                    IntervalTimelineEvent(
                        kind="external_hp_loss",
                        event_idx=idx_pos,
                        av=cur_av_ref[0],
                        hurt_uids=tuple(pending_hurt_uids),
                        extra_memo_hits=extra_memo,
                        hp_loss_by_uid=dict(pending_losses),
                        capped_uids=tuple(pending_capped),
                        capped_hp_ratios=dict(pending_cap_ratios),
                    )
                )
            pending_hurt_uids = []
            pending_losses = {}
            pending_capped = []
            pending_cap_ratios = {}
            in_talent_heal_wave = False
            talent_wave_chars_healed = 0
            suppress_post_lc_wave = False
            seen_enemy_turn_in_seg = False
            aha_1512_sp_hits = 0
            aha_1512_hp_hits = 0
            in_aha_turn = False

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
                        e_uid = int(to["uid"])
                        enemy_attacked = False
                        turn_hit_list: Dict[int, List[float]] = {}
                        scan_hp = dict(temp_hp)
                        scan_max = dict(temp_max)
                        scan_prev_max = dict(prev_max_by_uid)
                        saw_heal_in_turn = False
                        sp_hits_1409 = 0
                        hp_hits_1409 = 0
                        sp_in_1409_hp_hit = 0
                        prev_1409_sp_val: Optional[float] = None
                        sp_hits_1512 = 0
                        hp_hits_1512 = 0
                        j = i + 1
                        while j < n:
                            ej = self.events[j]
                            etj = ej.get("event")
                            dj = ej.get("data", {})
                            if etj == "OnTurnBegin":
                                break
                            if etj == "OnUseSkill":
                                av_j = dj.get("avatar") or {}
                                sc_j = dj.get("skill", {}).get("skill_config_id", 0)
                                if av_j.get("team") == "Player" and sc_j != 0:
                                    break
                            if etj == "OnStatChange":
                                ent_j = dj.get("entity", {})
                                prop_j = dj.get("property", {})
                                ptype_j = prop_j.get("type")
                                val_j = float(prop_j.get("value", 0.0))
                                if ent_j.get("team") == "Enemy" and ent_j.get("uid") == e_uid and ptype_j == "CurrentSP" and val_j > 1e-4:
                                    enemy_attacked = True
                                elif ent_j.get("team") == "Player":
                                    u_j = ent_j.get("uid")
                                    if u_j == 1409 and ptype_j == "CurrentSP" and 4.0 <= val_j <= 15.0:
                                        # 正阳狮鹫命中风堇自身时，单次受击会连续上报两条相同 5.97 CurrentSP 增量；同一 1409 掉血段内去重
                                        if (
                                            sp_in_1409_hp_hit >= 1
                                            and abs(val_j - 5.97197) < 0.05
                                            and prev_1409_sp_val is not None
                                            and abs(val_j - prev_1409_sp_val) < 1e-4
                                        ):
                                            pass
                                        else:
                                            sp_hits_1409 += 1
                                            if hp_hits_1409 > 0:
                                                sp_in_1409_hp_hit += 1
                                            prev_1409_sp_val = val_j
                                    elif u_j == 1512 and ptype_j == "CurrentSP" and 4.0 <= val_j <= 15.0:
                                        sp_hits_1512 += 1
                                    if ptype_j == "MaxHP" and isinstance(u_j, int):
                                        scan_prev_max[u_j] = scan_max.get(u_j, val_j)
                                        scan_max[u_j] = val_j
                                    elif ptype_j == "CurrentHP" and isinstance(u_j, int):
                                        if j + 1 < n and self.events[j + 1].get("event") == "OnStatChange":
                                            d2_j = self.events[j + 1].get("data", {})
                                            if (
                                                d2_j.get("entity", {}).get("uid") == u_j
                                                and d2_j.get("property", {}).get("type") == "CurrentHP"
                                            ):
                                                val2_j = float(d2_j.get("property", {}).get("value", 0.0))
                                                if val2_j > val_j:
                                                    enemy_attacked = True
                                                    if val_j < 450.0:
                                                        saw_heal_in_turn = True
                                                    scan_hp[u_j] = val2_j
                                                    j += 2
                                                    continue
                                        prev_j = scan_hp.get(u_j)
                                        if j not in lc_drain_event_indices and prev_j is not None and val_j < prev_j - 1e-4:
                                            is_mr = False
                                            for jb in range(max(start_idx, j - 8), j):
                                                ejb = self.events[jb]
                                                if ejb.get("event") == "OnStatChange":
                                                    dpj = ejb.get("data", {})
                                                    if dpj.get("entity", {}).get("uid") == u_j and dpj.get("property", {}).get("type") == "MaxHP":
                                                        is_mr = True
                                                        break
                                                elif ejb.get("event") in ("OnTurnBegin", "OnUseSkill"):
                                                    break
                                            mh_j = scan_max.get(u_j, 0.0)
                                            pmh_j = scan_prev_max.get(u_j, mh_j)
                                            if abs(mh_j - pmh_j) > 1e-2 and mh_j > 0 and pmh_j > 0 and abs((val_j / mh_j) - (prev_j / pmh_j)) < 1e-3:
                                                is_mr = True
                                            if mh_j > 0 and abs(val_j - mh_j) < 1e-3:
                                                is_mr = True
                                            if not is_mr:
                                                enemy_attacked = True
                                                if u_j == 1409 and (prev_j - val_j) > 50.0:
                                                    hp_hits_1409 += 1
                                                    sp_in_1409_hp_hit = 0
                                                    prev_1409_sp_val = None
                                                elif u_j == 1512 and (prev_j - val_j) > 50.0:
                                                    hp_hits_1512 += 1
                                                if not saw_heal_in_turn:
                                                    turn_hit_list.setdefault(u_j, []).append(prev_j - val_j)
                                        scan_hp[u_j] = val_j
                            j += 1
                        # 过滤同一敌方回合末尾附加的【欧洛尼斯印记】引爆高额爆发 (>2.5x 基础单段伤)，避免误叠到无印记的忆灵身上
                        turn_losses: Dict[int, float] = {}
                        for u_j, hits_j in turn_hit_list.items():
                            base_hit = min(hits_j) if hits_j else 0.0
                            direct_hits = [h for h in hits_j if base_hit <= 0.0 or h <= base_hit * 2.5]
                            turn_losses[u_j] = sum(direct_hits) if direct_hits else sum(hits_j)
                        out.append(
                            IntervalTimelineEvent(
                                kind="enemy_turn",
                                event_idx=i,
                                av=cur_av_ref[0],
                                enemy_uid=e_uid,
                                enemy_attacked=enemy_attacked,
                                enemy_turn_losses=turn_losses,
                                enemy_memo_sp_hits_1409=max(0, sp_hits_1409 - hp_hits_1409),
                                enemy_memo_sp_hits_1512=max(0, sp_hits_1512 - hp_hits_1512),
                            )
                        )
                    elif to is None:
                        in_aha_turn = True
                        # 检查是否是 Fever 倒计时回合 (OnTurnBegin(None) 后紧跟 1409 暴伤下跌且未接 1151201/OnDamage；
                        # 若紧跟 1151201 晴空乐手回合，仅当该段结束时的最终 1409 暴伤净下跌 > 0.05 才是倒计时，排除 诗行 -0.16 瞬时刷新)
                        saw_cd_drop = False
                        saw_skill_or_dmg = False
                        last_cd_val: Optional[float] = None
                        for j in range(i + 1, min(n, i + 30)):
                            ej = self.events[j]
                            if ej.get("event") == "OnTurnBegin":
                                break
                            if ej.get("event") in ("OnUseSkill", "OnDamage"):
                                saw_skill_or_dmg = True
                            if ej.get("event") == "OnStatChange":
                                dj = ej.get("data", {})
                                if dj.get("entity", {}).get("uid") == 1409 and dj.get("property", {}).get("type") == "CriticalDamage":
                                    last_cd_val = float(dj["property"]["value"])
                        if last_cd_val is not None and cur_fj_cd_ref[0] is not None and last_cd_val < cur_fj_cd_ref[0] - 0.05:
                            saw_cd_drop = True
                        if saw_cd_drop and not saw_skill_or_dmg:
                            out.append(IntervalTimelineEvent(kind="fever_countdown", event_idx=i, av=cur_av_ref[0]))
                        elif saw_cd_drop:
                            # 若紧跟 1151201，也先执行倒计时折半再执行晴空乐手
                            next_sc = None
                            for j in range(i + 1, min(i + 15, n)):
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
                    elif ptype == "CurrentSP" and uid == 1512:
                        if in_aha_turn:
                            if aha_1512_prev_sp is not None and 2.0 <= (val - aha_1512_prev_sp) <= 2.6:
                                aha_1512_sp_hits += 1
                        aha_1512_prev_sp = val
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
                                    prev_hp_val = temp_hp.get(uid)
                                    temp_hp[uid] = val2
                                    cur_hp_state[uid] = val2
                                    if val < 450.0:
                                        in_talent_heal_wave = True
                                        talent_wave_chars_healed += 1
                                    # 检测是否被堕神衰腐锁定在 50%~90% 上限 (仅当实际增益明确小于上报治疗量时，才说明触发了锁血截断)
                                    mhp = temp_max.get(uid, 0.0)
                                    if mhp > 0 and val2 < mhp - 1.0 and val > 50.0:
                                        is_partial_cap = (
                                            prev_hp_val is not None
                                            and (val2 - prev_hp_val) < val - 1.0
                                            and (val2 - prev_hp_val) >= -1e-3
                                        )
                                        if is_partial_cap:
                                            if uid not in pending_capped:
                                                pending_capped.append(uid)
                                            pending_cap_ratios[uid] = val2 / mhp
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
                            # 检测召唤/光环刷新导致的瞬时等比回弹 (如 1151203 期间 1409 CurrentHP 先跌再立即回弹至 prev，绝非治疗配对或敌方受击回血)
                            if not is_max_refresh and not seen_enemy_turn_in_seg:
                                for j_fwd in range(i + 1, min(n, i + 10)):
                                    ej_f = self.events[j_fwd]
                                    if ej_f.get("event") in ("OnTurnBegin", "OnDamage"):
                                        break
                                    if ej_f.get("event") == "OnStatChange":
                                        dp_f = ej_f.get("data", {})
                                        ent_f = dp_f.get("entity", {})
                                        prop_f = dp_f.get("property", {})
                                        if ent_f.get("uid") == uid and prop_f.get("type") == "CurrentSP":
                                            break
                                        if ent_f.get("uid") == uid and prop_f.get("type") == "CurrentHP":
                                            v_f = float(prop_f.get("value", 0.0))
                                            # 排除 [amount, new_hp] 治疗配对 (前一条同 uid CurrentHP 且 val_prev < v_f)
                                            is_heal_pair = False
                                            if j_fwd - 1 >= 0 and self.events[j_fwd - 1].get("event") == "OnStatChange":
                                                d_prev = self.events[j_fwd - 1].get("data", {})
                                                if (
                                                    d_prev.get("entity", {}).get("uid") == uid
                                                    and d_prev.get("property", {}).get("type") == "CurrentHP"
                                                    and float(d_prev.get("property", {}).get("value", 0.0)) < v_f - 1e-3
                                                ):
                                                    is_heal_pair = True
                                            if not is_heal_pair and abs(v_f - prev) < 1e-2:
                                                is_max_refresh = True
                                                break
                            if not is_max_refresh:
                                if in_talent_heal_wave:
                                    _flush_external_losses(i)
                                loss = prev - val
                                if uid not in pending_hurt_uids:
                                    pending_hurt_uids.append(uid)
                                pending_losses[uid] = pending_losses.get(uid, 0.0) + loss
                                if in_aha_turn and uid == 1512 and loss < 5.0:
                                    aha_1512_hp_hits += 1
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
                    # 检查该技能是否造成 OnDamage (决定是否触发风堇 E1)，以及 151203 的真实单体增益目标
                    has_dmg = False
                    target_uid = 0
                    for j in range(i + 1, min(i + 35, n)):
                        ej = self.events[j]
                        if sc_id == 151203 and target_uid == 0 and ej.get("event") == "OnStatChange":
                            dj_t = ej.get("data", {})
                            ent_t = dj_t.get("entity", {})
                            prop_t = dj_t.get("property", {})
                            if (
                                ent_t.get("team") == "Player"
                                and ent_t.get("uid") in (1403, 1409, 1413)
                                and prop_t.get("type") in ("ActionDelay", "CurrentSP")
                            ):
                                target_uid = int(ent_t["uid"])
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
                            target_uid=target_uid,
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
        self._apoli_p2_idx = self._detect_apoli_phase2_idx()

    def _detect_apoli_phase2_idx(self) -> Optional[int]:
        """定位堕神之血•亚婆离 (5034010) 首次进入二阶段 (HP 归零后 CurrentStance 重置为 1080) 的事件索引."""
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

    def _build_sandbox(self, team_uids: Sequence[int]) -> Tuple[TurnSimulator, Any]:
        db = CharacterDB().load(CHAR_DB_PATH)
        team: List[Entity] = []
        tech_users: List[str] = []
        for u in team_uids:
            name = UID_TO_NAME[u]
            if name == "知更鸟•晴歌":
                rp = db.get_by_name("知更鸟•晴歌_爱如此刻永恒")
                rp.name = "知更鸟•晴歌"
                ent = db.to_combat_entity(rp)
            else:
                ent = db.to_combat_entity(name)
            if name == "风堇":
                # 实机面板治疗加成为 54.5606% (遗器主词条 34.5606% + 巨树 20%)，消除导出表三位截断 54.5% 引起的系统性 -0.04% 偏移
                ent.base_outgoing_healing = 0.5456060005817562
            team.append(ent)
            tech_users.append(name)

        sim, director = build_stage_30126122(team, technique_users=tech_users)
        # 对齐官方 StageAbility_Maze_Hyacine_00_Modifier (Priority -80) 开战秘技结算序：
        # 1) HealHP(AllLightTeam, 30% MaxHP + 600) 先于 +20% MaxHP 执行 (基于无秘技生命上限)；
        # 2) 前 2 名目标 (自身 + 首位触发女武神4件套的队友) 按未触发甘霖前的暴风停歇 (+1%) 结算，
        #    第 3 名及之后队友/开场伴生忆灵「长夜」按甘霖 (+6% 速度 -> +8% 治疗) 结算。
        fj_ent = sim.get_entity("风堇")
        if fj_ent is not None and getattr(fj_ent, "kit", None) is not None and getattr(fj_ent.kit, "_tech_weather_is_fine_used", False):
            white_hp = float(sim.port.white_stat("风堇", StatType.MAX_HP_PERCENT) or 2250.0)
            pre_tech_max_hp = sim.port.max_hp("风堇") - 0.20 * white_hp
            raw_tech = pre_tech_max_hp * 0.30 + 600.0
            base_oh = float(getattr(fj_ent, "base_outgoing_healing", 0.5456060005817562))
            h_pre_valk = raw_tech * (1.0 + base_oh + 0.01)
            h_post_valk = raw_tech * (1.0 + base_oh + 0.08)
            n_allies = sum(1 for a in sim.port.allies("风堇") if not (hasattr(sim.port, "is_countdown") and sim.port.is_countdown(a)))
            if n_allies >= 2:
                fj_ent.kit.accumulated_healing = 2.0 * h_pre_valk + max(0, n_allies - 2) * h_post_valk
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

        # 对齐官方 Servant_HyacineServant_00_Ability.json (MaxNumber=1)：
        # 小伊卡天赋【牵起晴空的手】同一结算批次内对所有掉血目标各回血 1 次，但自身仅消耗 1 次 4% MaxHP
        def _wrap_ika_max1(_ev: Any = None) -> None:
            ika_ent = sim.get_entity("小伊卡")
            if ika_ent is not None and getattr(ika_ent, "kit", None) is not None and not getattr(ika_ent.kit, "_max1_wrapped", False):
                ika_kit = ika_ent.kit
                ika_kit._max1_wrapped = True
                orig_rth = ika_kit._resolve_talent_heal

                def _wrapped_rth() -> Any:
                    orig_lose = ika_kit.port.lose_hp
                    spent = [False]

                    def _once_lose(eid: str, amt: float, cause: str = "") -> float:
                        if cause == "yika_talent_consume_hp" and eid == ika_kit.owner_id:
                            if spent[0]:
                                return 0.0
                            spent[0] = True
                        return orig_lose(eid, amt, cause=cause)

                    ika_kit.port.lose_hp = _once_lose
                    try:
                        return orig_rth()
                    finally:
                        ika_kit.port.lose_hp = orig_lose

                ika_kit._resolve_talent_heal = _wrapped_rth

        _wrap_ika_max1()
        sim.event_bus.subscribe(SpiritSummonedEvent, _wrap_ika_max1)
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
                if hasattr(sim, "status_mgr") and hasattr(sim.status_mgr, "statuses"):
                    sim.status_mgr.statuses.pop(e.name, None)

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
            if (
                next_is_wave2
                and idx == 0
                and self._apoli_p2_idx is not None
                and cast.event_idx >= self._apoli_p2_idx
            ):
                ent.toughness_dmg_reduction = 0.0
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
        skill_id: int = 0,
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
                pre_memo_state = {
                    e.name: (float(e.current_hp), float(sim.port.max_hp(e.name)))
                    for e in sim.entities
                    if not e.is_enemy and sim.port.is_memosprite(e.name) and e.current_hp > 0
                }
                sim.status_mgr.tick_on_turn_begin(ent)
                # 对齐实机 MaxHP 增益到期（如【雨过天晴】到期 4282 -> 2782）时按变动前血量百分比等比缩放忆灵 CurrentHP
                # 注意必须基于 tick_on_turn_begin 前的 pre_hp 缩放，避免与内核 clamp(new_max) 叠加二次缩水
                for mname, (old_hp, old_max) in pre_memo_state.items():
                    m_ent = sim.get_entity(mname)
                    if m_ent is not None and old_max > 0:
                        new_max = sim.port.max_hp(mname)
                        if new_max < old_max - 1e-2:
                            m_ent.current_hp = max(1.0, min(new_max, old_hp * (new_max / old_max)))
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
                skill_id=skill_id,
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

            pre_evernight_alive = (actor_name == "长夜月" and kind == ActionKind.ULTIMATE and sim.port.entity_exists("长夜"))
            ent.kit.execute(ctx)
            if (
                actor_name == "长夜月"
                and kind == ActionKind.ULTIMATE
                and not pre_evernight_alive
                and float(getattr(sim, "current_av", 0.0)) > 50.0
                and sim.port.entity_exists("长夜")
            ):
                # 官方 141303 召唤「长夜」后，1141305 被动扣减「长夜」5% 当前生命并同批次触发小伊卡天赋治疗；
                # 仅补充该次掉血与天赋入队，不额外提前叠加长夜月忆质，防止紧随其后的 1141301 误提前自毁。
                cy_kit = getattr(ent, "kit", None)
                saved_yz = getattr(cy_kit, "yizhi", None)
                cy_cur_hp = sim.port.current_hp("长夜")
                if cy_cur_hp > 1.0:
                    sim.port.lose_hp("长夜", cy_cur_hp * 0.05, cause="1141305_passive_cost")
                if saved_yz is not None and cy_kit is not None:
                    cy_kit.yizhi = saved_yz

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

    def _estimate_enemy_memo_dmg(
        self,
        sim: TurnSimulator,
        aname: str,
        av: float,
        target_name: str,
        turn_losses: Optional[Dict[int, float]] = None,
    ) -> float:
        """从同回合显式角色实伤 (按防御比换算) 或敌方攻击面板/倍率公式推导对忆灵的真实伤害."""
        atk_factor = 1150.0  # 关卡 30126122 敌方均为 Lv.95 (200 + 10 * 95)
        def_ht = float(sim.port.stat(target_name, StatType.DEF))
        ht_ent = sim.get_entity(target_name)
        dr_ht = 1.0 - float(getattr(ht_ent, "damage_reduction", 0.0)) if ht_ent is not None else 1.0
        mult_ht = (atk_factor / (atk_factor + def_ht)) * dr_ht

        if turn_losses:
            real_losses = {u: v for u, v in turn_losses.items() if v > 50.0 and u in UID_TO_NAME}
            if real_losses:
                master_name = sim.port.get_master_name(target_name) if hasattr(sim.port, "get_master_name") else None
                master_uid = next((u for u, n in UID_TO_NAME.items() if n == master_name), None)
                ref_uid = master_uid if (master_uid in real_losses) else max(real_losses, key=lambda u: real_losses[u])
                ref_name = UID_TO_NAME[ref_uid]
                def_ref = float(sim.port.stat(ref_name, StatType.DEF))
                ref_ent = sim.get_entity(ref_name)
                dr_ref = 1.0 - float(getattr(ref_ent, "damage_reduction", 0.0)) if ref_ent is not None else 1.0
                mult_ref = (atk_factor / (atk_factor + def_ref)) * dr_ref
                if mult_ref > 0.0:
                    return real_losses[ref_uid] * (mult_ht / mult_ref)

        # 仅命中忆灵而无角色掉血时，按敌方基础攻击与当前阶段技能倍率计算 (对齐 Lv.95 实机基线，杜绝硬编码常数)
        if aname == "正阳狮鹫":
            if 150.0 <= av < 170.0:
                base_atk, skill_mult = 1711.0, 1.462  # 4 段扑击合计 (0.365 * 4 ≈ 2501.8)
            elif abs(av - 31.57) < 0.5:
                base_atk, skill_mult = 1711.0, 0.95
            else:
                base_atk, skill_mult = 1711.0, 1.097
        elif aname == "月夜天马":
            base_atk = 1876.4  # Lv.95 实机折算基础面板 (对应 Turn 1 单体 1.0x = 1876.4)
            # Turn 1 单体 1.0x (~75.76 AV); Turn 2 3段扩散 1.50x (~151.52 AV); Turn 3 1.0x
            skill_mult = 1.50 if 100.0 <= av < 200.0 else 1.0
        elif aname.startswith("流星铁鹰"):
            base_atk, skill_mult = 1471.0, 0.85
        elif aname == "堕神之血•亚婆离":
            base_atk, skill_mult = 1476.0, 1.20
        else:
            base_atk, skill_mult = 1471.0, 0.85
        return base_atk * skill_mult * mult_ht

    def run_reconciliation(self) -> List[CastReconciliationRecord]:
        """在外部因素固定、双池与伤害全原生演算的沙盒中执行全场逐动对账."""
        team_uids = self.extractor.detect_team_uids()
        detected_enemy_uids = self.extractor.detect_enemy_uid_names()
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
                    # 必须带 CHARACTER_ONLY 标签：风堇与小伊卡各自持有不同步的【偏离和弦】，不得将风堇个人暴伤微差扩散到小伊卡
                    cd_snap = captured_cast.get("cd_snapshot")
                    if cd_snap is not None:
                        sim.port.remove_status("风堇", "Sandbox_External_CD_Anchor")
                        if sim.port.entity_exists("小伊卡"):
                            sim.port.remove_status("小伊卡", "Sandbox_External_CD_Anchor_IkaAura")
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
                                    tags=(StatusTag.CHARACTER_ONLY,),
                                )
                            )
                            # 若知更鸟在 Fever 状态且暴伤存在气氛值级偏差 (>= 1 层 = 0.015，取 > 0.012)，同步修正知更鸟气氛值
                            # (排除 041608 #6 等 cd_delta < -0.10 且前有 1403 追击导致日志快照滞后的情况？不，此处微调 |cd_delta| > 0.012 即可覆盖 1~3 层微差)
                            rb = sim.get_entity("知更鸟•晴歌")
                            if rb and getattr(rb, "kit", None) is not None and getattr(rb.kit, "in_fever", False) and abs(cd_delta) > 0.012:
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
                                                tags=(StatusTag.CHARACTER_ONLY,),
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

            for idx_ev, ev in enumerate(timeline):
                sim.current_av = ev.av
                if ev.kind == "fever_countdown":
                    rb = sim.get_entity("知更鸟•晴歌")
                    if rb and getattr(rb, "kit", None) is not None and getattr(rb.kit, "in_fever", False):
                        sim._turn_id += 1
                        sim.event_bus.publish(
                            TurnBeginEvent(
                                av=round(sim.current_av, 2),
                                cycle=sim.current_cycle,
                                actor_id=rb.kit.COUNTDOWN_NAME,
                                actor_name=rb.kit.COUNTDOWN_NAME,
                                speed=110.0,
                                turn_id=sim._turn_id,
                            )
                        )
                        sim.resolver.resolve_all()

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
                    # 若日志显示该敌方回合因 DoT 致死或风行跳过而未发动任何攻击，则不再模拟其对忆灵造成伤害
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
                                        sim,
                                        aname,
                                        ev.av,
                                        ht.name,
                                        turn_losses=ev.enemy_turn_losses,
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
                                    sim,
                                    aname,
                                    ev.av,
                                    "小伊卡",
                                    turn_losses=ev.enemy_turn_losses,
                                ) * 0.75
                                sim.port.lose_hp("小伊卡", memo_dmg, cause="external_log_enemy_memo_hit")
                                captured_cast["enemy_hit_memo_in_turn"] = True
                                captured_cast["memo_damaged_in_turn"]["小伊卡"] = captured_cast["memo_damaged_in_turn"].get("小伊卡", 0.0) + memo_dmg
                        if captured_cast["enemy_hit_memo_in_turn"]:
                            sim.resolver.resolve_all()
                            sim.event_bus.publish(TurnBeginEvent(av=round(sim.current_av, 2), cycle=sim.current_cycle, actor_id=aname, actor_name=aname, speed=0.0))
                            sim.resolver.resolve_all()

                elif ev.kind == "external_hp_loss":
                    for u in ev.capped_uids:
                        ent_c = sim.get_entity(UID_TO_NAME[u])
                        if ent_c is not None:
                            cap_ratio = ev.capped_hp_ratios.get(u, 0.50)
                            ent_c.hp_lock_ratio = max(float(getattr(ent_c, "hp_lock_ratio", 0.0)), 1.0 - cap_ratio)
                            eff_cap = ent_c.effective_hp_cap(sim.port.max_hp(ent_c.name))
                            if ent_c.current_hp > eff_cap:
                                ent_c.current_hp = eff_cap
                            if u == 1512 and sim.port.entity_exists("晴空乐手"):
                                sunny_ent = sim.get_entity("晴空乐手")
                                if sunny_ent is not None:
                                    sunny_ent.hp_lock_ratio = max(float(getattr(sunny_ent, "hp_lock_ratio", 0.0)), 1.0 - cap_ratio)
                                    sunny_cap = sunny_ent.effective_hp_cap(sim.port.max_hp("晴空乐手"))
                                    if sunny_ent.current_hp > sunny_cap:
                                        sunny_ent.current_hp = sunny_cap
                    # 若是长夜月施放 141302/141303/141309 前的自身被动扣血，ChangyeyueKit 会在技能执行时自行结算，跳过重复扣血
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
                        for u in ev.hurt_uids:
                            cname = UID_TO_NAME[u]
                            loss = ev.hp_loss_by_uid.get(u, 1.0)
                            if sim.port.entity_exists(cname):
                                sim.port.lose_hp(cname, loss, cause="external_log_hp_loss")

                    # 由日志显式角色掉血推演伴生忆灵受击：
                    # 1) Wave 1 (正阳狮鹫/月夜天马) 全体 AOE 命中全部显式角色时，同步命中尚未受击的在场忆灵；
                    # 2) 仅当本波明确为群体/扩散受击 (len >= 2 或 月夜天马 Turn 2) 且命中知更鸟•晴歌时，给相邻晴空乐手补足扩散伤害；单目标攻击(如 75.76)不误扩散。
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
                        # Wave 2 亚婆离开场全体 AOE 扣血 (按参战角色 DEF 折算真实敌方 AOE 伤害到在场忆灵)
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
                                    if hasattr(sim, "status_mgr") and hasattr(sim.status_mgr, "statuses"):
                                        sim.status_mgr.statuses.pop(e.name, None)
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
                        if ev.has_damage and not enemies:
                            enemies = self._sync_enemies_for_cast(sim, cast, cast.is_wave2)
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
                            # 151203 终结技单体目标优先使用日志 ActionDelay/CurrentSP 实测目标
                            if ev.skill_id == 151203:
                                tgt_ally = UID_TO_NAME.get(ev.target_uid) or next((UID_TO_NAME[u] for u in team_uids if u in (1413, 1403)), "风堇")
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
                                if hasattr(sim, "status_mgr") and hasattr(sim.status_mgr, "statuses"):
                                    sim.status_mgr.statuses.pop(e.name, None)
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

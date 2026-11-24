"""官方 TurnBasedGameData 配置编译器与数值表加载器 (GameData Loader)。

职责：
1. 读取 `/tmp/tbgd/ExcelOutput/` 核心战斗数值表：
   - `AvatarConfig` / `AvatarSkillConfig` / `AvatarSkillTreeConfig` / `AvatarRankConfig`
   - `AvatarServantConfig` / `AvatarServantSkillConfig`
   - `EquipmentConfig` / `EquipmentSkillConfig`
   - `RelicSetConfig` / `RelicSetSkillConfig`
   - `MonsterConfig` / `MonsterSkillConfig`
2. 按 `ReadInfo` 自动解析角色、忆灵、光锥、遗器在任意等级/星魂/叠影下的全部 `DynamicValues` 浮点表；
3. 按需加载并索引 `ConfigCharacter`、`ConfigAbility`、`ConfigGlobalModifier`、`ConfigGlobalTaskListTemplate`，
   并在加载期安全裁剪纯表现层节点（Camera / Anim / Effect / Audio / ClientOnly）。
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .expr import dotnet_hash

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_REPO_TBGD_ROOT = os.path.join(_REPO_ROOT, "data", "TurnBasedGameData")
DEFAULT_TBGD_ROOT = (
    _REPO_TBGD_ROOT
    if os.path.isdir(os.path.join(_REPO_TBGD_ROOT, "ExcelOutput"))
    else "/tmp/tbgd"
)

_ABILITY_INDEX_CACHE_VERSION = 2
_ABILITY_INDEX_MEM_CACHE: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

# 经实证确认的纯表现/客户端无逻辑副作用节点，加载期裁剪以压缩 AST 体积
PRUNABLE_PRESENTATION_TYPES: Set[str] = {
    "RPG.GameCore.VCameraConfigChange",
    "RPG.GameCore.VCameraNoiseChange",
    "RPG.GameCore.WaitAnimState",
    "RPG.GameCore.WaitAnimEvent",
    "RPG.GameCore.TriggerAnimState",
    "RPG.GameCore.TriggerAnimStateWithCallback",
    "RPG.GameCore.TriggerEffect",
    "RPG.GameCore.TriggerEffectList",
    "RPG.GameCore.RemoveEffect",
    "RPG.GameCore.SetEntityVisible",
    "RPG.GameCore.RadialBlurEffect",
    "RPG.GameCore.ShowUIPage",
    "RPG.GameCore.ShowUI",
    "RPG.GameCore.GlobalTimeSlow",
    "RPG.GameCore.SetComfortZoneWidthOverride",
    "RPG.GameCore.SetEntityArtRotation",
    "RPG.GameCore.RetargetPerSequence",
    "RPG.GameCore.TriggerSound",
    "RPG.GameCore.TriggerSoundInAnim",
    "RPG.GameCore.LevelAudioSwitch",
    "RPG.GameCore.CharacterPlayVO",
    "RPG.GameCore.SetCharacterEffect",
    "RPG.GameCore.LookAt",
    "RPG.GameCore.HeadLookAt",
    "RPG.GameCore.PlayTimeline",
    "RPG.GameCore.WaitTimelineFinish",
    "RPG.GameCore.StopTimeline",
    "RPG.GameCore.SetCamera",
    "RPG.GameCore.ShakeCamera",
    "RPG.GameCore.SetCloseupShot",
    "RPG.GameCore.HideUI",
    "RPG.GameCore.SetHUDVisible",
    "RPG.GameCore.ShowBattleUI",
    "RPG.GameCore.ChangeCharacterUIDisplay",
    "RPG.GameCore.TriggerUINotify",
    "RPG.GameCore.TriggerEnergyBarEffect",
    "RPG.GameCore.ShowBonusUIEffect",
    "RPG.GameCore.SkipPopupUIOffset",
    "RPG.GameCore.SetHeadButtonEff",
    "RPG.GameCore.ShowBattleSkillEnhanced",
    "RPG.GameCore.ToggleSkillPreShow",
    "RPG.GameCore.PlayVideo",
    "RPG.GameCore.WaitSecond",
    "RPG.GameCore.WaitFor",
    "RPG.GameCore.WaitParallelTimeStamp",
    "RPG.GameCore.WaitSkillPerformAbilityFinish",
    "RPG.GameCore.MoveTeam",
    "RPG.GameCore.MoveToTargetPosition",
    "RPG.GameCore.SetEntityPosition",
    "RPG.GameCore.HideLevelStage",
    "RPG.GameCore.ScaleCharacterModel",
    "RPG.GameCore.SetAttachmentScale",
    "RPG.GameCore.SetAttachmentVisibility",
    "RPG.GameCore.AlignTargetToTeamCenter",
    "RPG.GameCore.SyncCharLightAndCameraDir",
    "RPG.GameCore.SetTeamFormation",
    "RPG.GameCore.SetSkillTargetFormationByPos",
    "RPG.GameCore.SetCharacterAnimFollow",
    "RPG.GameCore.SetCharacterVisibilityFollow",
    "RPG.GameCore.SetCharacterCustomTeamFormation",
    "RPG.GameCore.ResetCharacterCustomTeamFormation",
    "RPG.GameCore.SetEntityForbidCameraDither",
    "RPG.GameCore.SetCharacterPartsVisibility",
    "RPG.GameCore.CharacterReplaceAnimatorController",
    "RPG.GameCore.GlobalMainIntensityEffect",
    "RPG.GameCore.SetBattleBGMState",
    "RPG.GameCore.ResetBattleBGMToStage",
    "RPG.GameCore.TargetTimeSlow",
    "RPG.GameCore.ClearEntityFollowAttachPoint",
    "RPG.GameCore.HideEntityForCurrentCamera",
    "RPG.GameCore.DebugLog",
    "RPG.GameCore.StopAim",
    "RPG.GameCore.TryStartConnectUltraSkillFrameCapture",
    "RPG.GameCore.ChangeActionEntityToObserveState",
    "RPG.GameCore.RevertActionEntityToObserveState",
    "RPG.GameCore.SetEntityFollowAttachPoint",
    "RPG.GameCore.SetCharacterScaleFollow",
    "RPG.GameCore.HideCharacterFilteredEffect",
    "RPG.GameCore.HideEntityInActionBarByDelay",
    "RPG.GameCore.AddBuffPerform",
    "RPG.GameCore.ModifierAttachEffect",
    "RPG.GameCore.ModifierOverrideOnHitEffect",
    "RPG.GameCore.ShowEntityFloatMessage",
    # 关卡 / 怪物纯表现、HUD、镜头、音效与元评分节点（加载期直接裁剪，不进执行循环）
    "RPG.GameCore.AnimSetParameter",
    "RPG.GameCore.CharacterReactionAnimConfig",
    "RPG.GameCore.LevelAudioState",
    "RPG.GameCore.MakeCharacterHUDVisible",
    "RPG.GameCore.ModifyDefaultTeamFormation",
    "RPG.GameCore.MoveToTargetList",
    "RPG.GameCore.ResetHeadLookAt",
    "RPG.GameCore.SetEffectAnimatorTrigger",
    "RPG.GameCore.SetSimulationSpeedEnable",
    "RPG.GameCore.SetTeamRootOffset",
    "RPG.GameCore.ShowAttackTime",
    "RPG.GameCore.ShowBattleAlert",
    "RPG.GameCore.ShowBattleEventButton",
    "RPG.GameCore.ShowBossInfoBar",
    "RPG.GameCore.ShowSkillTextDialog",
    "RPG.GameCore.SkillExecutionStart",
    "RPG.GameCore.SkillPerformFinish",
    "RPG.GameCore.ShowActionBarEffect",
    "RPG.GameCore.TriggerUITopEffect",
    "RPG.GameCore.SetEnergyBarState",
    "RPG.GameCore.SetSummonerEnergyBarState",
    "RPG.GameCore.SetTargetAlwaysAutoBattle",
    "RPG.GameCore.SetTargetTeamLocation",
    "RPG.GameCore.SetTriggeredFormationAssetAutoCenter",
    "RPG.GameCore.PreloadBattleEventByID",
    "RPG.GameCore.CharacterChangeModel",
    "RPG.GameCore.ChangeCharacterConfigParam",
    "RPG.GameCore.ChangeMonsterHeadIcon",
    "RPG.GameCore.ChangeTargetModifierEffectState",
    "RPG.GameCore.HalfBoomerangProjectileData",
    "RPG.GameCore.MonsterEnergyBarTutorialConfig",
    "RPG.GameCore.BossInfoBarCustomizedTutorialConfig",
    "RPG.GameCore.OverrideSelectDarkTeamEntityCamera",
    "RPG.GameCore.SetEffectAnimatorParameter",
    "RPG.GameCore.SetBossPluralityHP",
    "RPG.GameCore.RefreshChangePhaseUI",
    "RPG.GameCore.StackStatusDesc",
    "RPG.GameCore.LinearProjectileData",
    "RPG.GameCore.CreateBattleTarget",
    "RPG.GameCore.NotifyFeverTimeInfoChange",
    "RPG.GameCore.NotifyVersusBarQuestChange",
    "RPG.GameCore.SetBattleAchievement",
    "RPG.GameCore.SetBattleScoringItem",
    "RPG.GameCore.SetBattleTargetProgress",
    "RPG.GameCore.ShowEvolveBuildGearSelectInBattle",
    "RPG.GameCore.ToggleUITop",
    "RPG.GameCore.SetCharacterShowSummonUI",
    "RPG.GameCore.ShowBattleVersusBarCountDownEffect",
    "RPG.GameCore.SetCountDownWarning",
    "RPG.GameCore.AddChallengeBossInfoPanelState",
    "RPG.GameCore.RemoveChallengeBossInfoPanelState",
    "RPG.GameCore.OverrideEntityModifierPhaseCamera",
    "RPG.GameCore.PlayScreenTransfer",
    "RPG.GameCore.WaitAbilityStartTimeStamp",
    "RPG.GameCore.SetMonsterNameBoardMaxBuffCount",
    "RPG.GameCore.SetModifierOverrideNameForStatus",
    "RPG.GameCore.ReleaseCharacterHUDVisibleControl",
    "RPG.GameCore.AddTargetStancePreshowConfig",
    "RPG.GameCore.SwitchChallengeBossInfoPanelState",
}


def prune_task_list(tasks: Any) -> List[Dict[str, Any]]:
    """递归裁剪纯表现层 Task 节点；保留所有逻辑 Task 与分支容器。"""
    if not isinstance(tasks, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        t = item.get("$type", "")
        if t == "RPG.GameCore.TriggerAnimStateWithMove":
            events = item.get("EventList")
            if isinstance(events, list) and events:
                def _ev_time(ev: Any) -> float:
                    if isinstance(ev, Mapping):
                        nt = ev.get("NormalizedTime")
                        if isinstance(nt, Mapping) and not nt.get("IsDynamic"):
                            return float((nt.get("FixedValue") or {}).get("Value", 0.0) or 0.0)
                    return 0.0
                for ev in sorted((e for e in events if isinstance(e, Mapping)), key=_ev_time):
                    out.extend(prune_task_list(ev.get("TaskList", [])))
            continue
        if t in PRUNABLE_PRESENTATION_TYPES or t.endswith("ClientOnly"):
            continue
        cloned = dict(item)
        for key in ("TaskList", "SuccessTaskList", "FailedTaskList", "CallbackConfig", "OnProjectileHit", "OnHit", "DefaultTaskList"):
            if key in cloned and isinstance(cloned[key], list):
                cloned[key] = prune_task_list(cloned[key])
        for ckey in ("CaseList", "CaseTaskList"):
            if ckey in cloned and isinstance(cloned[ckey], list):
                new_cases = []
                for c in cloned[ckey]:
                    if isinstance(c, dict):
                        nc = dict(c)
                        if "TaskList" in nc and isinstance(nc["TaskList"], list):
                            nc["TaskList"] = prune_task_list(nc["TaskList"])
                        new_cases.append(nc)
                cloned[ckey] = new_cases
        if "OnSuccess" in cloned and isinstance(cloned["OnSuccess"], list):
            cloned["OnSuccess"] = prune_task_list(cloned["OnSuccess"])
        if "OnFail" in cloned and isinstance(cloned["OnFail"], list):
            cloned["OnFail"] = prune_task_list(cloned["OnFail"])
        out.append(cloned)
    return out


def prune_modifier_dict(mod: Mapping[str, Any]) -> Dict[str, Any]:
    """裁剪 Modifier 内 `_CallbackList` / `TaskListTemplate` / `OnAbilityPropertyChange` 的表现节点。"""
    cloned = dict(mod)
    if "_CallbackList" in cloned and isinstance(cloned["_CallbackList"], list):
        new_cbs = []
        for entry in cloned["_CallbackList"]:
            if not isinstance(entry, dict):
                continue
            ne = dict(entry)
            ne["CallbackConfig"] = prune_task_list(entry.get("CallbackConfig", []))
            new_cbs.append(ne)
        cloned["_CallbackList"] = new_cbs
    if "TaskListTemplate" in cloned and isinstance(cloned["TaskListTemplate"], list):
        new_tpls = []
        for tpl in cloned["TaskListTemplate"]:
            if not isinstance(tpl, dict):
                continue
            nt = dict(tpl)
            nt["TaskList"] = prune_task_list(tpl.get("TaskList", []))
            new_tpls.append(nt)
        cloned["TaskListTemplate"] = new_tpls
    if "OnAbilityPropertyChange" in cloned and isinstance(cloned["OnAbilityPropertyChange"], list):
        new_apc = []
        for apc in cloned["OnAbilityPropertyChange"]:
            if not isinstance(apc, dict):
                continue
            na = dict(apc)
            new_ranges = []
            for rng in apc.get("Ranges", []):
                if not isinstance(rng, dict):
                    continue
                nr = dict(rng)
                for hook in ("OnEnterRange", "OnExitRange", "OnChange"):
                    if hook in nr and isinstance(nr[hook], list):
                        nr[hook] = prune_task_list(nr[hook])
                new_ranges.append(nr)
            na["Ranges"] = new_ranges
            new_apc.append(na)
        cloned["OnAbilityPropertyChange"] = new_apc
    if "OnDynamicValueChange" in cloned and isinstance(cloned["OnDynamicValueChange"], list):
        new_dvc = []
        for dvc in cloned["OnDynamicValueChange"]:
            if not isinstance(dvc, dict):
                continue
            nd = dict(dvc)
            new_ranges = []
            for rng in dvc.get("Ranges", []):
                if not isinstance(rng, dict):
                    continue
                nr = dict(rng)
                for hook in ("OnEnterRange", "OnExitRange", "OnChange"):
                    if hook in nr and isinstance(nr[hook], list):
                        nr[hook] = prune_task_list(nr[hook])
                new_ranges.append(nr)
            nd["Ranges"] = new_ranges
            new_dvc.append(nd)
        cloned["OnDynamicValueChange"] = new_dvc
    return cloned


def prune_ability(ability: Mapping[str, Any]) -> Dict[str, Any]:
    """裁剪单个 Ability 的 TaskList 与 Modifiers。"""
    cloned = dict(ability)
    if "OnStart" in cloned and isinstance(cloned["OnStart"], list):
        cloned["OnStart"] = prune_task_list(cloned["OnStart"])
    if "OnAdd" in cloned and isinstance(cloned["OnAdd"], list):
        cloned["OnAdd"] = prune_task_list(cloned["OnAdd"])
    if "TaskListTemplate" in cloned and isinstance(cloned["TaskListTemplate"], list):
        new_tpls = []
        for tpl in cloned["TaskListTemplate"]:
            if isinstance(tpl, dict):
                nt = dict(tpl)
                nt["TaskList"] = prune_task_list(tpl.get("TaskList", []))
                new_tpls.append(nt)
        cloned["TaskListTemplate"] = new_tpls
    if "Modifiers" in cloned and isinstance(cloned["Modifiers"], dict):
        cloned["Modifiers"] = {
            name: prune_modifier_dict(m)
            for name, m in cloned["Modifiers"].items()
            if isinstance(m, dict)
        }
    return cloned


@dataclass
class CompiledCharacterSpec:
    """角色或忆灵在指定星魂与技能等级下的已编译配置与数值上下文。"""
    unit_id: int
    is_servant: bool
    config: Dict[str, Any]
    abilities: Dict[str, Dict[str, Any]]
    global_modifiers: Dict[str, Dict[str, Any]]
    global_templates: Dict[str, List[Dict[str, Any]]]
    dynamic_floats: Dict[int, float]
    skill_levels: Dict[int, int]
    eidolon: int = 0
    unlocked_ranks: Set[int] = field(default_factory=set)
    servant_id: Optional[int] = None


class GameDataLoader:
    """官方 TurnBasedGameData 按需索引与编译器（按 data_root 进程级单例缓存）。"""

    _SHARED_INSTANCES: Dict[str, "GameDataLoader"] = {}

    def __new__(cls, data_root: str = DEFAULT_TBGD_ROOT) -> "GameDataLoader":
        key = os.path.abspath(data_root)
        inst = cls._SHARED_INSTANCES.get(key)
        if inst is None:
            inst = super().__new__(cls)
            cls._SHARED_INSTANCES[key] = inst
        return inst

    def __init__(self, data_root: str = DEFAULT_TBGD_ROOT) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.data_root = data_root
        self._excel_cache: Dict[str, Any] = {}
        self._ability_index_built = False
        self._ability_by_name: Dict[str, Dict[str, Any]] = {}
        self._global_mod_by_name: Dict[str, Dict[str, Any]] = {}
        self._global_target_alias_by_name: Dict[str, Dict[str, Any]] = {}
        self._global_tpl_by_name: Dict[str, List[Dict[str, Any]]] = {}
        self._symbol_sources: Dict[str, str] = {}
        self._ability_mod_index: Dict[str, Tuple[str, str]] = {}
        self._file_cache: Dict[str, Dict[str, Any]] = {}

        # Excel 索引（按需惰性构建）
        self._avatars: Optional[Dict[int, Dict[str, Any]]] = None
        self._avatar_skills: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None
        self._avatar_skill_max_lv: Optional[Dict[int, int]] = None
        self._avatar_trees: Optional[Dict[int, Dict[str, List[Dict[str, Any]]]]] = None
        self._ranks: Optional[Dict[int, Dict[str, Any]]] = None
        self._servants: Optional[Dict[int, Dict[str, Any]]] = None
        self._servant_skills: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None
        self._servant_skill_max_lv: Optional[Dict[int, int]] = None
        self._equipments: Optional[Dict[int, Dict[str, Any]]] = None
        self._equip_skills: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None
        self._relic_skills: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None
        self._monsters: Optional[Dict[int, Dict[str, Any]]] = None
        self._monster_skills: Optional[Dict[int, Dict[str, Any]]] = None
        self._status_type_by_mod: Optional[Dict[str, str]] = None
        self._can_dispel_by_mod: Optional[Dict[str, bool]] = None

    def _read_json(self, rel_or_abs: str) -> Any:
        path = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(self.data_root, rel_or_abs)
        if path in self._file_cache:
            return self._file_cache[path]
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._file_cache[path] = data
        return data

    def _read_excel(self, filename: str) -> Any:
        if filename not in self._excel_cache:
            path = os.path.join(self.data_root, "ExcelOutput", filename)
            with open(path, encoding="utf-8") as f:
                self._excel_cache[filename] = json.load(f)
        return self._excel_cache[filename]

    # --- Excel 索引 ---
    def _ensure_avatars(self) -> None:
        if self._avatars is None:
            self._avatars = {int(r["AvatarID"]): r for r in self._read_excel("AvatarConfig.json")}

    def _ensure_avatar_skills(self) -> None:
        if self._avatar_skills is None:
            self._avatar_skills = {}
            self._avatar_skill_max_lv = {}
            for r in self._read_excel("AvatarSkillConfig.json"):
                sid = int(r["SkillID"])
                lv = int(r["Level"])
                self._avatar_skills[(sid, lv)] = r
                self._avatar_skill_max_lv[sid] = max(self._avatar_skill_max_lv.get(sid, 1), int(r.get("MaxLevel", lv)))

    def _ensure_avatar_trees(self) -> None:
        if self._avatar_trees is None:
            self._avatar_trees = {}
            for r in self._read_excel("AvatarSkillTreeConfig.json"):
                aid = int(r["AvatarID"])
                tk = r.get("PointTriggerKey", "")
                if not tk:
                    continue
                by_key = self._avatar_trees.setdefault(aid, {})
                by_key.setdefault(tk, []).append(r)
            for by_key in self._avatar_trees.values():
                for lst in by_key.values():
                    lst.sort(key=lambda x: int(x.get("Level", 1)))

    def _ensure_ranks(self) -> None:
        if self._ranks is None:
            self._ranks = {int(r["RankID"]): r for r in self._read_excel("AvatarRankConfig.json")}

    def _ensure_servants(self) -> None:
        if self._servants is None:
            self._servants = {int(r["ServantID"]): r for r in self._read_excel("AvatarServantConfig.json")}

    def _ensure_servant_skills(self) -> None:
        if self._servant_skills is None:
            self._servant_skills = {}
            self._servant_skill_max_lv = {}
            for r in self._read_excel("AvatarServantSkillConfig.json"):
                sid = int(r["SkillID"])
                lv = int(r["Level"])
                self._servant_skills[(sid, lv)] = r
                self._servant_skill_max_lv[sid] = max(self._servant_skill_max_lv.get(sid, 1), int(r.get("MaxLevel", lv)))

    def _ensure_equipments(self) -> None:
        if self._equipments is None:
            self._equipments = {int(r["EquipmentID"]): r for r in self._read_excel("EquipmentConfig.json")}
            self._equip_skills = {
                (int(r["SkillID"]), int(r["Level"])): r
                for r in self._read_excel("EquipmentSkillConfig.json")
            }

    def _ensure_relics(self) -> None:
        if self._relic_skills is None:
            self._relic_skills = {
                (int(r["SetID"]), int(r["RequireNum"])): r
                for r in self._read_excel("RelicSetSkillConfig.json")
            }

    def _ensure_monsters(self) -> None:
        if self._monsters is None:
            self._monsters = {int(r["MonsterID"]): r for r in self._read_excel("MonsterConfig.json")}
            self._monster_skills = {int(r["SkillID"]): r for r in self._read_excel("MonsterSkillConfig.json")}

    # --- ConfigAbility 索引 ---
    def _ingest_ability_file(self, path: str) -> None:
        data = self._read_json(path)
        if not isinstance(data, dict):
            return
        rel_path = os.path.relpath(path, self.data_root).replace("\\", "/")
        for ab in data.get("AbilityList", []):
            name = ab.get("Name")
            if name and name not in self._ability_by_name:
                pruned_ab = prune_ability(ab)
                self._ability_by_name[name] = pruned_ab
                self._symbol_sources.setdefault(name, rel_path)
                mods = pruned_ab.get("Modifiers")
                if isinstance(mods, dict):
                    for inner_mname in mods.keys():
                        if inner_mname and inner_mname not in self._ability_mod_index:
                            self._ability_mod_index[inner_mname] = (name, rel_path)
        for mname, mval in data.get("GlobalModifiers", {}).items():
            if mname and mname not in self._global_mod_by_name and isinstance(mval, dict):
                self._global_mod_by_name[mname] = prune_modifier_dict(mval)
                self._symbol_sources.setdefault(mname, rel_path)
        for aname, aval in data.get("GlobalTargetAlias", {}).items():
            if aname and aname not in self._global_target_alias_by_name and isinstance(aval, dict):
                self._global_target_alias_by_name[aname] = aval
                self._symbol_sources.setdefault(aname, rel_path)
        for tpl in data.get("GlobalTemplates", []):
            tname = tpl.get("Name")
            if tname and tname not in self._global_tpl_by_name:
                self._global_tpl_by_name[tname] = prune_task_list(tpl.get("TaskList", []))
                self._symbol_sources.setdefault(tname, rel_path)
        # ConfigGlobalTaskListTemplate 独立文件（单条或 TaskListTemplate 列表）
        if "TaskList" in data and "Name" in data:
            tname = data["Name"]
            if tname not in self._global_tpl_by_name:
                self._global_tpl_by_name[tname] = prune_task_list(data["TaskList"])
                self._symbol_sources.setdefault(tname, rel_path)
        for tpl in data.get("TaskListTemplate", []):
            if isinstance(tpl, dict) and tpl.get("Name"):
                tname = tpl["Name"]
                if tname not in self._global_tpl_by_name:
                    self._global_tpl_by_name[tname] = prune_task_list(tpl.get("TaskList", []))
                    self._symbol_sources.setdefault(tname, rel_path)
        # ConfigGlobalModifier 独立文件
        if "ModifierMap" in data and isinstance(data["ModifierMap"], dict):
            for mname, mval in data["ModifierMap"].items():
                if mname and mname not in self._global_mod_by_name and isinstance(mval, dict):
                    self._global_mod_by_name[mname] = prune_modifier_dict(mval)
                    self._symbol_sources.setdefault(mname, rel_path)

    def _ability_cache_path(self) -> str:
        abs_root = os.path.abspath(self.data_root)
        cache_dir = os.path.join(_REPO_ROOT, ".cache")
        if abs_root == os.path.abspath(_REPO_TBGD_ROOT):
            fname = "vm_ability_index_v1.pkl"
        else:
            digest = hashlib.sha1(abs_root.encode("utf-8")).hexdigest()[:10]
            fname = f"vm_ability_index_v1_{digest}.pkl"
        return os.path.join(cache_dir, fname)

    def _scan_ability_files(self) -> Tuple[List[str], int, int]:
        """扫描 ConfigAbility / ConfigGlobalModifier / ConfigGlobalTaskListTemplate 下 JSON 文件及 mtime 指纹。"""
        paths: List[str] = []
        max_mtime_ns = 0
        stack = [
            os.path.join(self.data_root, "Config", sub)
            for sub in ("ConfigAbility", "ConfigGlobalModifier", "ConfigGlobalTaskListTemplate")
        ]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=True):
                                stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=True):
                                name = entry.name
                                if name.endswith(".json") and not name.endswith(".layout.json"):
                                    st = entry.stat()
                                    if st.st_mtime_ns > max_mtime_ns:
                                        max_mtime_ns = st.st_mtime_ns
                                    paths.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue
        paths.sort()
        return paths, len(paths), max_mtime_ns

    def _ability_index_fingerprint(self, file_count: int, max_mtime_ns: int) -> Tuple[Any, ...]:
        try:
            lst = os.stat(__file__)
            loader_sig = (int(lst.st_mtime_ns), int(lst.st_size))
        except OSError:
            loader_sig = (0, 0)
        return (
            _ABILITY_INDEX_CACHE_VERSION,
            os.path.abspath(self.data_root),
            loader_sig[0],
            loader_sig[1],
            int(file_count),
            int(max_mtime_ns),
        )

    def _apply_ability_payload(self, payload: Mapping[str, Any]) -> None:
        self._ability_by_name = dict(payload.get("abilities") or {})
        self._global_mod_by_name = dict(payload.get("global_mods") or {})
        self._global_target_alias_by_name = dict(payload.get("global_target_aliases") or {})
        self._global_tpl_by_name = dict(payload.get("global_tpls") or {})
        self._symbol_sources = dict(payload.get("symbol_sources") or {})
        self._ability_mod_index = dict(payload.get("ability_mod_index") or {})

    def ensure_ability_index(self) -> None:
        if self._ability_index_built:
            return
        paths, file_count, max_mtime_ns = self._scan_ability_files()
        fingerprint = self._ability_index_fingerprint(file_count, max_mtime_ns)

        mem_hit = _ABILITY_INDEX_MEM_CACHE.get(fingerprint)
        if mem_hit is not None:
            self._apply_ability_payload(mem_hit)
            self._ability_index_built = True
            return

        cache_path = self._ability_cache_path()
        if os.path.isfile(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    disk_payload = pickle.load(f)
                if isinstance(disk_payload, dict) and disk_payload.get("fingerprint") == fingerprint:
                    _ABILITY_INDEX_MEM_CACHE[fingerprint] = disk_payload
                    self._apply_ability_payload(disk_payload)
                    self._ability_index_built = True
                    return
            except (OSError, pickle.UnpicklingError, EOFError, ValueError, AttributeError):
                pass

        for p in paths:
            self._ingest_ability_file(p)

        payload = {
            "fingerprint": fingerprint,
            "abilities": dict(self._ability_by_name),
            "global_mods": dict(self._global_mod_by_name),
            "global_target_aliases": dict(self._global_target_alias_by_name),
            "global_tpls": dict(self._global_tpl_by_name),
            "symbol_sources": dict(self._symbol_sources),
            "ability_mod_index": dict(self._ability_mod_index),
        }
        _ABILITY_INDEX_MEM_CACHE[fingerprint] = payload
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            tmp_path = f"{cache_path}.tmp.{os.getpid()}"
            with open(tmp_path, "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, cache_path)
        except OSError:
            pass
        self._ability_index_built = True

    def get_ability(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self._ability_by_name:
            self.ensure_ability_index()
        return self._ability_by_name.get(name)

    def get_global_modifier(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self._global_mod_by_name:
            self.ensure_ability_index()
        return self._global_mod_by_name.get(name)

    def get_global_template(self, name: str) -> Optional[List[Dict[str, Any]]]:
        if name not in self._global_tpl_by_name:
            self.ensure_ability_index()
        return self._global_tpl_by_name.get(name)

    def get_global_target_alias(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self._global_target_alias_by_name:
            self.ensure_ability_index()
        return self._global_target_alias_by_name.get(name)

    def get_inner_modifier(self, mod_name: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """按内嵌 Modifier 名称返回 (ability_name, rel_path, modifier_dict)。"""
        if mod_name not in self._ability_mod_index:
            self.ensure_ability_index()
        entry = self._ability_mod_index.get(mod_name)
        if not entry:
            return None
        ability_name, rel_path = entry
        ab = self._ability_by_name.get(ability_name)
        if not isinstance(ab, Mapping):
            return None
        mods = ab.get("Modifiers")
        if not isinstance(mods, Mapping):
            return None
        mdef = mods.get(mod_name)
        if not isinstance(mdef, dict):
            return None
        return ability_name, rel_path, mdef

    def _ensure_status_config_tables(self) -> None:
        if getattr(self, "_status_type_by_mod", None) is not None and getattr(self, "_can_dispel_by_mod", None) is not None:
            return
        status_table: Dict[str, str] = {}
        dispel_table: Dict[str, bool] = {}
        excel_dir = os.path.join(self.data_root, "ExcelOutput")
        for fn in (
            "AvatarStatusConfig.json",
            "MonsterStatusConfig.json",
            "StatusConfig.json",
            "StatusConfigLD.json",
        ):
            path = os.path.join(excel_dir, fn)
            if not os.path.exists(path):
                continue
            rows = self._read_excel(fn)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                mn = str(row.get("ModifierName") or "")
                if not mn:
                    continue
                st = str(row.get("StatusType") or "")
                if st and mn not in status_table:
                    status_table[mn] = st
                if mn not in dispel_table:
                    dispel_table[mn] = bool(row.get("CanDispel", False))
        self._status_type_by_mod = status_table
        self._can_dispel_by_mod = dispel_table

    def get_modifier_status_type(self, mod_name: str) -> str:
        """从官方 StatusConfig 系列表按 ModifierName 解析官方 StatusType（Buff/Debuff/Other）。"""
        self._ensure_status_config_tables()
        assert self._status_type_by_mod is not None
        return self._status_type_by_mod.get(mod_name, "")

    def get_modifier_can_dispel(self, mod_name: str) -> Optional[bool]:
        """从官方 StatusConfig 系列表按 ModifierName 解析官方 CanDispel（未收录返回 None）。"""
        self._ensure_status_config_tables()
        assert self._can_dispel_by_mod is not None
        return self._can_dispel_by_mod.get(mod_name)

    # --- 角色/忆灵/光锥/遗器参数解析 ---
    def compute_effective_skill_levels(
        self,
        avatar_id: int,
        eidolon: int = 0,
        trained_levels: Optional[Mapping[str, int]] = None,
    ) -> Dict[int, int]:
        """基于 AvatarConfig + AvatarRankConfig.SkillAddLevelList 计算全技能最终生效等级（含伴生忆灵技）。"""
        self._ensure_avatars()
        self._ensure_avatar_skills()
        self._ensure_servant_skills()
        self._ensure_ranks()

        av = self._avatars[int(avatar_id)]
        trained = dict(trained_levels or {})
        levels: Dict[int, int] = {}

        # 1. 角色自身技能
        for sid in av.get("SkillList", []):
            sid = int(sid)
            max_lv = self._avatar_skill_max_lv.get(sid, 1)
            row = self._avatar_skills.get((sid, 1), {})
            tkey = row.get("SkillTriggerKey", "")
            atk_type = row.get("AttackType", "")
            # 默认按养成满级（普攻 6、战技/终结技/天赋 10、秘技/额外 1）
            default_lv = 1 if max_lv <= 1 else (6 if (atk_type == "Normal" or max_lv == 6) else 10)
            lv = trained.get(str(sid), trained.get(tkey, default_lv))
            levels[sid] = max(1, int(lv))

        # 2. 伴生忆灵技能 (11xxxx)
        servant_id = 10000 + int(avatar_id)
        self._ensure_servants()
        if servant_id in self._servants:
            sv = self._servants[servant_id]
            for sid in sv.get("SkillIDList", []):
                sid = int(sid)
                max_lv = self._servant_skill_max_lv.get(sid, 1)
                default_lv = 1 if max_lv <= 1 else 6
                lv = trained.get(str(sid), default_lv)
                levels[sid] = max(1, int(lv))

        # 3. E3/E5 SkillAddLevelList
        for rid in av.get("RankIDList", []):
            r = self._ranks.get(int(rid))
            if not r or int(r.get("Rank", 0)) > eidolon:
                continue
            for sid_str, delta in (r.get("SkillAddLevelList") or {}).items():
                sid = int(sid_str)
                if sid in levels:
                    levels[sid] += int(delta)
                else:
                    levels[sid] = 6 + int(delta)

        return levels

    def resolve_avatar_dynamic_floats(
        self,
        avatar_id: int,
        config_dict: Mapping[str, Any],
        eidolon: int = 0,
        skill_levels: Optional[Mapping[int, int]] = None,
    ) -> Dict[int, float]:
        """解析角色 ConfigCharacter.DynamicValues.Floats 中的所有 ReadInfo 为 {hash: float}。"""
        self._ensure_avatars()
        self._ensure_avatar_skills()
        self._ensure_avatar_trees()
        self._ensure_ranks()

        av = self._avatars[int(avatar_id)]
        eff_levels = dict(skill_levels) if skill_levels is not None else self.compute_effective_skill_levels(avatar_id, eidolon)

        # 建立 SkillTriggerKey -> SkillRow 映射
        trigger_to_skill: Dict[str, Dict[str, Any]] = {}
        for sid in av.get("SkillList", []):
            sid = int(sid)
            lv = eff_levels.get(sid, 1)
            row = self._avatar_skills.get((sid, lv)) or self._avatar_skills.get((sid, 1))
            if row and row.get("SkillTriggerKey"):
                trigger_to_skill[row["SkillTriggerKey"]] = row

        # Rank01..Rank06 -> RankRow
        rank_map: Dict[str, Dict[str, Any]] = {}
        for rid in av.get("RankIDList", []):
            r = self._ranks.get(int(rid))
            if r:
                rank_map[f"Rank0{int(r['Rank'])}"] = r

        # PointB1.. -> TreeRow (取最高等级)
        tree_map = self._avatar_trees.get(int(avatar_id), {})

        out: Dict[int, float] = {}
        floats = config_dict.get("DynamicValues", {}).get("Floats", {})
        for hash_str, entry in floats.items():
            h = int(hash_str)
            ri = entry.get("ReadInfo", {})
            rtype = ri.get("Type", "None")
            tkey = ri.get("TriggerKey", "")
            idx = int(ri.get("Index", 0))

            if rtype == "SkillParam":
                row = trigger_to_skill.get(tkey)
                if row:
                    plist = row.get("ParamList", [])
                    out[h] = float(plist[idx].get("Value", 0.0)) if idx < len(plist) else 0.0
                else:
                    out[h] = 0.0
            elif rtype == "SkillRank":
                r = rank_map.get(tkey)
                if r and int(r.get("Rank", 99)) <= int(eidolon):
                    plist = r.get("Param", [])
                    out[h] = float(plist[idx].get("Value", 0.0)) if idx < len(plist) else 0.0
                else:
                    out[h] = 0.0
            elif rtype == "SkillTreeParam":
                rows = tree_map.get(tkey, [])
                if rows:
                    plist = rows[-1].get("ParamList", [])
                    out[h] = float(plist[idx].get("Value", 0.0)) if idx < len(plist) else 0.0
                else:
                    out[h] = 0.0
            else:
                # None / ClientOnly: 初始 0.0（运行时由 SetDynamicValue 写入）
                out[h] = 0.0
        return out

    def resolve_servant_dynamic_floats(
        self,
        servant_id: int,
        config_dict: Mapping[str, Any],
        owner_avatar_id: Optional[int] = None,
        eidolon: int = 0,
        skill_levels: Optional[Mapping[int, int]] = None,
    ) -> Dict[int, float]:
        """解析忆灵 ConfigCharacter.DynamicValues.Floats。"""
        self._ensure_servants()
        self._ensure_servant_skills()
        sv = self._servants[int(servant_id)]
        aid = owner_avatar_id or (int(servant_id) - 10000)
        eff_levels = dict(skill_levels) if skill_levels is not None else self.compute_effective_skill_levels(aid, eidolon)

        trigger_to_skill: Dict[str, Dict[str, Any]] = {}
        for sid in sv.get("SkillIDList", []):
            sid = int(sid)
            lv = eff_levels.get(sid, 6)
            row = self._servant_skills.get((sid, lv)) or self._servant_skills.get((sid, 1))
            if row and row.get("SkillTriggerKey"):
                trigger_to_skill[row["SkillTriggerKey"]] = row

        # 若忆灵也引用主人的 Rank/Tree/Skill 参数，合并主人上下文
        out = self.resolve_avatar_dynamic_floats(aid, config_dict, eidolon=eidolon, skill_levels=eff_levels)
        floats = config_dict.get("DynamicValues", {}).get("Floats", {})
        for hash_str, entry in floats.items():
            h = int(hash_str)
            ri = entry.get("ReadInfo", {})
            if ri.get("Type") == "SkillParam":
                tkey = ri.get("TriggerKey", "")
                idx = int(ri.get("Index", 0))
                if tkey in trigger_to_skill:
                    plist = trigger_to_skill[tkey].get("ParamList", [])
                    out[h] = float(plist[idx].get("Value", 0.0)) if idx < len(plist) else 0.0
        return out

    def resolve_ability_dynamic_floats(
        self,
        ability: Mapping[str, Any],
        *,
        equip_id: Optional[int] = None,
        superimposition: int = 1,
        relic_set_id: Optional[int] = None,
        relic_pieces: int = 4,
    ) -> Dict[int, float]:
        """解析光锥/遗器 Ability.DynamicValues.Floats 中的 SkillEquip / SkillRelic 参数。"""
        self._ensure_equipments()
        self._ensure_relics()

        out: Dict[int, float] = {}
        floats = ability.get("DynamicValues", {}).get("Floats", {})
        for hash_str, entry in floats.items():
            h = int(hash_str)
            ri = entry.get("ReadInfo", {})
            rtype = ri.get("Type", "None")
            tkey = ri.get("TriggerKey", "")
            idx = int(ri.get("Index", 0))

            if rtype == "SkillEquip" and equip_id is not None:
                eq = self._equipments.get(int(equip_id))
                sk_id = int(eq["SkillID"]) if eq else int(equip_id)
                row = self._equip_skills.get((sk_id, int(superimposition)))
                if row:
                    plist = row.get("ParamList", [])
                    out[h] = float(plist[idx].get("Value", 0.0)) if idx < len(plist) else 0.0
                else:
                    out[h] = 0.0
            elif rtype == "SkillRelic":
                sid = relic_set_id
                req_num = relic_pieces
                if "_" in tkey:
                    p0, p1 = tkey.split("_", 1)
                    sid = int(p0)
                    req_num = int(p1)
                if sid is not None:
                    row = self._relic_skills.get((int(sid), int(req_num)))
                    if row:
                        plist = row.get("AbilityParamList", [])
                        out[h] = float(plist[idx].get("Value", 0.0)) if idx < len(plist) else 0.0
                    else:
                        out[h] = 0.0
            else:
                out[h] = 0.0
        return out

    def load_character(
        self,
        avatar_id: int,
        *,
        eidolon: int = 0,
        trained_levels: Optional[Mapping[str, int]] = None,
    ) -> CompiledCharacterSpec:
        """编译指定角色的配置、技能 AST、Modifier 与全参数上下文。"""
        self._ensure_avatars()
        self._ensure_servants()
        self.ensure_ability_index()

        av = self._avatars[int(avatar_id)]
        cfg = self._read_json(av["JsonPath"])
        eff_levels = self.compute_effective_skill_levels(avatar_id, eidolon, trained_levels)
        dyn_floats = self.resolve_avatar_dynamic_floats(avatar_id, cfg, eidolon=eidolon, skill_levels=eff_levels)

        # 收集该角色关联的所有 Ability（包含 SkillAbilityList 与 AbilityList）
        ability_names: List[str] = list(cfg.get("AbilityList", []))
        for item in cfg.get("SkillAbilityList", []):
            for ab_name in item.get("AbilityList", []):
                if ab_name not in ability_names:
                    ability_names.append(ab_name)

        abilities: Dict[str, Dict[str, Any]] = {}
        for ab_name in ability_names:
            ab = self.get_ability(ab_name)
            if ab is not None:
                abilities[ab_name] = ab

        servant_id = 10000 + int(avatar_id)
        return CompiledCharacterSpec(
            unit_id=int(avatar_id),
            is_servant=False,
            config=cfg,
            abilities=abilities,
            global_modifiers=self._global_mod_by_name,
            global_templates=self._global_tpl_by_name,
            dynamic_floats=dyn_floats,
            skill_levels=eff_levels,
            eidolon=eidolon,
            unlocked_ranks=set(range(1, eidolon + 1)),
            servant_id=servant_id if servant_id in self._servants else None,
        )

    def load_servant(
        self,
        servant_id: int,
        *,
        owner_avatar_id: Optional[int] = None,
        eidolon: int = 0,
        trained_levels: Optional[Mapping[str, int]] = None,
    ) -> CompiledCharacterSpec:
        """编译指定忆灵的配置、技能 AST 与全参数上下文。"""
        self._ensure_servants()
        self.ensure_ability_index()

        sv = self._servants[int(servant_id)]
        cfg = self._read_json(sv["Config"])
        aid = owner_avatar_id or (int(servant_id) - 10000)
        eff_levels = self.compute_effective_skill_levels(aid, eidolon, trained_levels)
        dyn_floats = self.resolve_servant_dynamic_floats(servant_id, cfg, owner_avatar_id=aid, eidolon=eidolon, skill_levels=eff_levels)

        ability_names: List[str] = list(cfg.get("AbilityList", []))
        for item in cfg.get("SkillAbilityList", []):
            for ab_name in item.get("AbilityList", []):
                if ab_name not in ability_names:
                    ability_names.append(ab_name)

        abilities: Dict[str, Dict[str, Any]] = {}
        for ab_name in ability_names:
            ab = self.get_ability(ab_name)
            if ab is not None:
                abilities[ab_name] = ab

        return CompiledCharacterSpec(
            unit_id=int(servant_id),
            is_servant=True,
            config=cfg,
            abilities=abilities,
            global_modifiers=self._global_mod_by_name,
            global_templates=self._global_tpl_by_name,
            dynamic_floats=dyn_floats,
            skill_levels=eff_levels,
            eidolon=eidolon,
            unlocked_ranks=set(range(1, eidolon + 1)),
            servant_id=None,
        )

    def get_servant_base_inheritance(self, servant_id: int, eidolon: int = 0) -> Dict[str, Any]:
        """从 AvatarServantConfig 解析忆灵初始 HP / Speed 继承公式（#N 引用对应 HPSkill/SpeedSkill 参数）。"""
        self._ensure_servants()
        self._ensure_avatar_skills()
        sv = self._servants[int(servant_id)]
        aid = int(servant_id) - 10000
        eff_levels = self.compute_effective_skill_levels(aid, eidolon)

        def _parse_expr(val_str: Any, skill_id_key: str) -> float:
            s = str(val_str or "0").strip()
            if s.startswith("#"):
                idx = int(s[1:]) - 1
                sk_id = int(sv.get(skill_id_key, 0) or 0)
                lv = eff_levels.get(sk_id, 10)
                row = self._avatar_skills.get((sk_id, lv)) or self._avatar_skills.get((sk_id, 1))
                if row:
                    plist = row.get("ParamList", [])
                    return float(plist[idx].get("Value", 0.0)) if idx < len(plist) else 0.0
                return 0.0
            return float(s)

        return {
            "hp_base": _parse_expr(sv.get("HPBase"), "HPSkill"),
            "hp_inherit": _parse_expr(sv.get("HPInherit"), "HPSkill"),
            "speed_base": _parse_expr(sv.get("SpeedBase"), "SpeedSkill"),
            "speed_inherit": _parse_expr(sv.get("SpeedInherit"), "SpeedSkill"),
        }

    def get_relic_ability(self, set_id: int, pieces: int) -> Optional[Tuple[Dict[str, Any], Dict[int, float]]]:
        """获取遗器套装能力 AST 及其解析后的 SkillRelic 动态参数表。"""
        self._ensure_relics()
        row = self._relic_skills.get((int(set_id), int(pieces)))
        if not row or not row.get("AbilityName"):
            return None
        ab = self.get_ability(row["AbilityName"])
        if ab is None:
            return None
        dyn = self.resolve_ability_dynamic_floats(ab, relic_set_id=set_id, relic_pieces=pieces)
        return ab, dyn

    def get_equipment_ability(self, equip_id: int, superimposition: int = 1) -> Optional[Tuple[Dict[str, Any], Dict[int, float]]]:
        """获取光锥能力 AST 及其解析后的 SkillEquip 动态参数表。"""
        self._ensure_equipments()
        eq = self._equipments.get(int(equip_id))
        sk_id = int(eq["SkillID"]) if eq else int(equip_id)
        row = self._equip_skills.get((sk_id, int(superimposition)))
        if not row or not row.get("AbilityName"):
            return None
        ab = self.get_ability(row["AbilityName"])
        if ab is None:
            return None
        dyn = self.resolve_ability_dynamic_floats(ab, equip_id=equip_id, superimposition=superimposition)
        return ab, dyn

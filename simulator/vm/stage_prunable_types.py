"""Phase 3 ConfigAbility node classification & safe pruning registry.

Categorizes high-frequency Task & Predicate ``$type`` nodes discovered by
``audit_vm_coverage.py`` into:
1. Pure presentation / animation / camera / audio / HUD nodes (safe to prune)
2. Meta / achievement / scoring / tutorial / progress-bar nodes (safe to prune)
3. Mechanical stage & monster nodes (must be executed or evaluated by StageRunner / VM)

This module is standalone and read-only; it does not modify ``loader.py`` or ``executor.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Set

from simulator.vm.loader import PRUNABLE_PRESENTATION_TYPES, prune_task_list

# Pure presentation / animation / camera / audio / HUD nodes identified from
# BattleEvent & Monster Top-25 coverage audit.
STAGE_PRUNABLE_ANIM_CAMERA_AUDIO_TYPES: Set[str] = {
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
}

# Meta / achievement / out-of-combat scoring / UI notification nodes that have
# zero impact on damage, toughness, energy, or action-value scheduling.
STAGE_PRUNABLE_META_SCORING_TYPES: Set[str] = {
    "RPG.GameCore.CreateBattleTarget",
    "RPG.GameCore.NotifyFeverTimeInfoChange",
    "RPG.GameCore.NotifyVersusBarQuestChange",
    "RPG.GameCore.SetBattleAchievement",
    "RPG.GameCore.SetBattleScoringItem",
    "RPG.GameCore.SetBattleTargetProgress",
    "RPG.GameCore.ShowEvolveBuildGearSelectInBattle",
}

STAGE_PRUNABLE_PRESENTATION_TYPES: Set[str] = (
    STAGE_PRUNABLE_ANIM_CAMERA_AUDIO_TYPES | STAGE_PRUNABLE_META_SCORING_TYPES
)

# Combined safe-pruning set merging loader.PRUNABLE_PRESENTATION_TYPES and Phase 3 extensions.
ALL_SAFE_PRUNABLE_TYPES: Set[str] = (
    set(PRUNABLE_PRESENTATION_TYPES) | STAGE_PRUNABLE_PRESENTATION_TYPES
)

# Mechanical stage/monster Task nodes that MUST NOT be pruned.
STAGE_MECHANICAL_TASK_TYPES: Set[str] = {
    "RPG.GameCore.AddStageAbilityByName",
    "RPG.GameCore.AutoUseUltraSkill",
    "RPG.GameCore.ExitBreakState",
    "RPG.GameCore.IncludeGlobalTaskListTemplate",
    "RPG.GameCore.LevelChallengeTurnAcc",
    "RPG.GameCore.LockHP",
    "RPG.GameCore.LoopExecuteTaskListWithInterval",
    "RPG.GameCore.ModifyEvolveBuildProperty",
    "RPG.GameCore.ModifyVersusBarProperty",
    "RPG.GameCore.OwnerEntityAddAbility",
    "RPG.GameCore.ResetStance",
    "RPG.GameCore.RetargetList",
    "RPG.GameCore.SetDynamicValueByEvolveBuild",
    "RPG.GameCore.SetDynamicValueByVersusBar",
    "RPG.GameCore.SetMonsterEnergyBarState",
    "RPG.GameCore.SetMonsterPhase",
    "RPG.GameCore.StackWeakness",
    "RPG.GameCore.SummonMonster",
    "RPG.GameCore.TargetFetchPartner",
    "RPG.GameCore.TargetFetchUniqueNameEntity",
    "RPG.GameCore.ToggleSpecialSkillMark",
    "RPG.GameCore.TriggerCustomString",
}

# Mechanical stage/monster Predicate nodes that MUST NOT be pruned.
STAGE_MECHANICAL_PREDICATE_TYPES: Set[str] = {
    "RPG.GameCore.ByCheckCustomValueBool",
    "RPG.GameCore.ByCompareBattleEventID",
    "RPG.GameCore.ByCompareChallengeLeft",
    "RPG.GameCore.ByCompareDamageTag",
    "RPG.GameCore.ByCompareEvolveBuildGearLevel",
    "RPG.GameCore.ByCompareEvolveBuildProperty",
    "RPG.GameCore.ByCompareHP",
    "RPG.GameCore.ByCompareMonsterPhase",
    "RPG.GameCore.ByCompareMonsterTemplateID",
    "RPG.GameCore.ByCompareMonsterUniqueID",
    "RPG.GameCore.ByCompareParamString",
    "RPG.GameCore.ByCompareSPRatio",
    "RPG.GameCore.ByCompareStageID",
    "RPG.GameCore.ByCompareStageType",
    "RPG.GameCore.ByCompareTurnActionEntityTeamType",
    "RPG.GameCore.ByContainCustomString",
    "RPG.GameCore.ByCurrentSkillName",
    "RPG.GameCore.ByInfiniteMonsterWaveLeft",
    "RPG.GameCore.ByIsDamageType",
    "RPG.GameCore.ByIsInElationTime",
    "RPG.GameCore.ByIsPropertyValueMinOrMax",
    "RPG.GameCore.ByIsSplitDamage",
    "RPG.GameCore.ByIsTargetAbleToAction",
    "RPG.GameCore.ByIsTopActionDelayTarget",
    "RPG.GameCore.ByLocalWin",
    "RPG.GameCore.ByRandomChance",
}


def is_safe_prunable_type(node_type: str) -> bool:
    """Return True if ``node_type`` is a known presentation/meta node safe to prune."""
    if not node_type:
        return True
    return node_type in ALL_SAFE_PRUNABLE_TYPES or node_type.endswith("ClientOnly")


def classify_node_type(node_type: str) -> str:
    """Classify a ConfigAbility ``$type`` string into its Phase 3 category."""
    if node_type in STAGE_PRUNABLE_ANIM_CAMERA_AUDIO_TYPES or node_type in PRUNABLE_PRESENTATION_TYPES:
        return "prunable_presentation"
    if node_type in STAGE_PRUNABLE_META_SCORING_TYPES or node_type.endswith("ClientOnly"):
        return "prunable_meta_scoring"
    if node_type in STAGE_MECHANICAL_TASK_TYPES:
        return "mechanical_task"
    if node_type in STAGE_MECHANICAL_PREDICATE_TYPES:
        return "mechanical_predicate"
    return "unknown"


def prune_stage_task_list(tasks: Any) -> List[Dict[str, Any]]:
    """Recursively prune both core and Phase 3 stage presentation/meta tasks."""
    base_pruned = prune_task_list(tasks)
    out: List[Dict[str, Any]] = []
    for item in base_pruned:
        t = item.get("$type", "")
        if t in STAGE_PRUNABLE_PRESENTATION_TYPES:
            continue
        cloned = dict(item)
        for key in (
            "TaskList",
            "SuccessTaskList",
            "FailedTaskList",
            "CallbackConfig",
            "OnProjectileHit",
            "OnHit",
            "DefaultTaskList",
            "OnSuccess",
            "OnFail",
        ):
            if key in cloned and isinstance(cloned[key], list):
                cloned[key] = prune_stage_task_list(cloned[key])
        for ckey in ("CaseList", "CaseTaskList"):
            if ckey in cloned and isinstance(cloned[ckey], list):
                new_cases = []
                for c in cloned[ckey]:
                    if isinstance(c, dict):
                        nc = dict(c)
                        if "TaskList" in nc and isinstance(nc["TaskList"], list):
                            nc["TaskList"] = prune_stage_task_list(nc["TaskList"])
                        new_cases.append(nc)
                cloned[ckey] = new_cases
        out.append(cloned)
    return out

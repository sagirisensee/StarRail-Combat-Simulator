# coding: utf-8
"""通用官方日志 → ConfigAbility VM 对账与插件自动生成器子包。"""

from simulator.vm.reconcile.auto_rng import _is_memosprite, attach_auto_rng_plugin
from simulator.vm.reconcile.codegen import emit_alignment_test, emit_plugin, format_report
from simulator.vm.reconcile.metadata import extract_log_metadata
from simulator.vm.reconcile.models import (
    DEFAULT_CHAR_DB_PATH,
    ROOT_DIR,
    SKIP_SENTINEL,
    AhaTurnRecord,
    AmbiguousMemospriteSlot,
    EnemyHitRecord,
    InferredMemospriteHit,
    LogMetadata,
    ReconcileReport,
    TurnDiffEntry,
    _extract_tag,
    _get_avatar_skill_effects,
    _get_servant_skill_effects,
    _resolve_uid_name,
)
from simulator.vm.reconcile.runner import (
    _attach_crit_hit_recorder,
    _detect_non_crits_from_trace,
    _run_single_pass,
    _try_load_existing_plugin,
    build_stage_for_id,
    reconcile_log,
)

__all__ = [
    "ROOT_DIR",
    "SKIP_SENTINEL",
    "AhaTurnRecord",
    "AmbiguousMemospriteSlot",
    "EnemyHitRecord",
    "InferredMemospriteHit",
    "LogMetadata",
    "ReconcileReport",
    "TurnDiffEntry",
    "extract_log_metadata",
    "attach_auto_rng_plugin",
    "build_stage_for_id",
    "reconcile_log",
    "format_report",
    "emit_alignment_test",
    "emit_plugin",
]

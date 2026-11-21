# coding: utf-8
"""通用官方日志 → ConfigAbility VM 对账工具与自动化测试生成器（Facade 入口）。

具体实现已按职责拆分至 ``simulator/vm/reconcile/`` 子包：
- ``models.py``: 数据结构与官方技能表缓存
- ``metadata.py``: 官方日志元数据扫描与敌方/阿哈/拉条提取
- ``auto_rng.py``: 全自动 RNG 先知与多忆灵差额反推
- ``runner.py``: 端到端回放对账、自动未暴击检测与二次试跑收敛
- ``codegen.py``: 诊断报告格式化、插件脚本与单测脚本代码生成

用法示例：
  python -m simulator.vm.reconcile_generator battle_logs/battle_20261114_212554.jsonl --data-driven
  python -m simulator.vm.reconcile_generator battle_logs/battle_20261114_212554.jsonl --emit-test
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from simulator.vm.reconcile import (
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
    _attach_crit_hit_recorder,
    _detect_non_crits_from_trace,
    _extract_tag,
    _get_avatar_skill_effects,
    _get_servant_skill_effects,
    _is_memosprite,
    _resolve_uid_name,
    _run_single_pass,
    _try_load_existing_plugin,
    attach_auto_rng_plugin,
    build_stage_for_id,
    emit_alignment_test,
    emit_plugin,
    extract_log_metadata,
    format_report,
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
    "main",
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="通用官方日志 → ConfigAbility VM 对账工具与测试生成器")
    parser.add_argument("log_path", help="battle_logs/battle_*.jsonl 路径")
    parser.add_argument("--team", nargs="+", default=None, help="手动指定队伍站位顺序（默认自动识别）")
    parser.add_argument("--data-driven", action="store_true", help="强制走通用 build_data_driven_stage(stage_id)")
    parser.add_argument("--no-plugin", action="store_true", help="忽略已有 log_<tag>.py，强制走自动提取受击目标")
    parser.add_argument("--no-resolve-memosprites", action="store_true", help="关闭多忆灵差额二次试跑确认")
    parser.add_argument("--av-budget", type=float, default=None, help="截断复现的最大 AV")
    parser.add_argument("--threshold", type=float, default=0.0001, help="单动误差高亮阈值（默认 0.0001 = 0.01%%）")
    parser.add_argument("--verbose", action="store_true", help="输出所有回合的逐动对比")
    parser.add_argument("--emit-test", nargs="?", const="", default=None, help="生成 unittest 对账脚本（可选指定输出路径）")
    parser.add_argument("--emit-plugin", nargs="?", const="", default=None, help="自动生成对应的 simulator/plugins/log_<tag>.py 插件脚本")
    args = parser.parse_args(argv)

    meta = extract_log_metadata(args.log_path, team_override=args.team)

    rep = reconcile_log(
        args.log_path,
        team_override=args.team,
        force_data_driven=args.data_driven,
        use_existing_plugin=not args.no_plugin,
        resolve_memosprites=not args.no_resolve_memosprites,
        av_budget=args.av_budget,
        threshold=args.threshold,
    )
    if args.emit_plugin is not None:
        p_out = emit_plugin(
            meta,
            output_path=args.emit_plugin or None,
            non_crits=getattr(rep, "non_crits", None),
        )
        print(f"[Generated plugin] {p_out}")
    print(format_report(rep, threshold=args.threshold, verbose=args.verbose))
    if args.emit_test is not None:
        out = emit_alignment_test(
            rep,
            output_path=args.emit_test or None,
            force_data_driven=args.data_driven,
        )
        print(f"\n[Generated test] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

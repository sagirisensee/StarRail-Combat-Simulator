#!/usr/bin/env python3
# coding: utf-8
"""通用官方日志 → ConfigAbility VM 对账与测试生成 CLI 入口。

用法示例:
    python3 gen_reconcile.py battle_logs/battle_20261115_041608.jsonl
    python3 gen_reconcile.py battle_logs/battle_20261114_155925.jsonl --emit-test
"""
import sys

from simulator.vm.reconcile_generator import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

# coding: utf-8
"""伴生忆灵独立实体日志转换器单元测试 (Unit Tests for Split Memosprite Log Converter)."""

import json
import os
import tempfile
import unittest

from simulator.split_memosprite_log import convert_battle_log, verify_conversion


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGINAL_LOG = os.path.join(ROOT_DIR, "battle_logs", "battle_20261026_062503.jsonl")


class TestSplitMemospriteLog(unittest.TestCase):
    """验证官方战斗日志伴生忆灵独立拆分与零损耗双向对账。"""

    def test_convert_and_verify_20261026(self):
        """测试对 battle_20261026_062503.jsonl 进行一键转换与严格对账。"""
        self.assertTrue(os.path.exists(ORIGINAL_LOG), f"原始日志不存在: {ORIGINAL_LOG}")

        with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            stats, converted_events = convert_battle_log(ORIGINAL_LOG, tmp_path)
            audit = verify_conversion(ORIGINAL_LOG, tmp_path)

            # 1. 严格行数与总伤害一致断言
            self.assertTrue(audit["is_valid"], f"数据完整性校验失败: {audit.get('mismatches')}")
            self.assertEqual(audit["orig_lines"], 6133)
            self.assertEqual(audit["conv_lines"], 6133)
            self.assertAlmostEqual(audit["dmg_diff"], 0.0, places=4)

            # 2. 忆灵技能与伤害重归属数量断言 (含 96 段 Servant 与 16 段长夜月大招忆灵动作)
            self.assertEqual(stats.skills_converted, 119)
            self.assertEqual(stats.damages_converted, 112)
            self.assertEqual(stats.turns_converted, 32)

            # 3. 伴生忆灵独立 UID 存在性校验
            servant_uids = {e.get("data", {}).get("attacker", {}).get("uid") for e in converted_events if e.get("event") == "OnDamage" and e.get("data", {}).get("type") in ("Servant", "Ultimate") and e.get("data", {}).get("attacker", {}).get("uid") > 10000}
            self.assertEqual(servant_uids, {11413, 11409, 11512}, "所有 Servant 与长夜月大招伤害必须 100% 归属于忆灵独立 UID (11413/11409/11512)")

            # 4. 忆灵回合开始 turn_owner 校验
            turn_owners = [e.get("data", {}).get("turn_owner", {}).get("uid") for e in converted_events if e.get("event") == "OnTurnBegin" and e.get("data", {}).get("turn_owner")]
            self.assertIn(11413, turn_owners, "长夜独立回合必须成功注入")
            self.assertIn(11512, turn_owners, "晴空乐手独立回合必须成功注入")

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()

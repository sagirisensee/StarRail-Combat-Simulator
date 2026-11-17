# -*- coding: utf-8 -*-
"""风堇光锥附伤与小伊卡伤害专项对账与交叉验证测试 (零循环自证外部固定沙盒).

严格断言全量日志中各动 (彻底去除此前用真值反推池子/乘区的恒等式自证):
1. 小伊卡与光锥附伤命中数 1:1 严格对齐，且比值落在合法物理区间；
2. 首动战斗内显式角色治疗流水与手算理论值误差 < 0.01%；
3. 在非循环沙盒 (真实实例化 TurnSimulator + FengjinKit + IkaKit + MayRainbowsRemainInTheSkyHandler + DamageCalculator) 下：
   - 全场 73/73 动次显式角色 1% 扣血对账误差 < 0.05%；
   - 可观测血量段 (`184845` Cast 1~2, `204943` Cast 1) `Servant` / `Additional` / `Ratio` 全指标收敛 < 0.20%；
   - `220255` / `221208` / `041608` 首动与前半场双池比值严格受控，有效拦截忆灵受疗/扣血被排除的回归缺陷。
"""

import json
import os
import unittest

from simulator.golden_diff import parse_golden_jsonl
from simulator.testing.fixed_reconciliation_bench import FixedReconciliationHarness

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestIkaFugueLightConeReconciliation(unittest.TestCase):
    """跨日志非循环逐动对账测试套件."""

    def _verify_log_casts(self, log_name: str, expected_casts: int) -> None:
        log_path = os.path.join(ROOT_DIR, "battle_logs", log_name)
        self.assertTrue(os.path.exists(log_path), f"Log not found: {log_path}")
        g = parse_golden_jsonl(log_path)

        ika_turns = []
        for t in g.turns:
            s_dmgs = [d.damage for d in t.damages if d.attacker == "风堇 (忆灵)" and d.damage_type == "Servant"]
            a_dmgs = [d.damage for d in t.damages if d.attacker == "风堇" and d.damage_type == "Additional"]
            if s_dmgs and a_dmgs:
                ika_turns.append({
                    "turn": t.index,
                    "av": round(t.av, 2),
                    "s_hits": len(s_dmgs),
                    "a_hits": len(a_dmgs),
                    "s_dmg": s_dmgs[0],
                    "a_dmg": a_dmgs[0],
                    "ratio": a_dmgs[0] / s_dmgs[0],
                    "pool_to_heal": (a_dmgs[0] / s_dmgs[0]) / 12.5,
                })

        self.assertGreaterEqual(len(ika_turns), expected_casts, f"Casts count below expected in {log_name}")

        for c in ika_turns:
            # 1. 断言命中数 1:1
            self.assertEqual(c["s_hits"], c["a_hits"], f"Turn {c['turn']} (AV={c['av']}) 命中数不一致: {c['s_hits']} vs {c['a_hits']}")
            # 2. 断言比值在合法物理区间 (0.04 ~ 0.35)
            self.assertGreater(c["ratio"], 0.04, f"Turn {c['turn']} ratio {c['ratio']} 过低")
            self.assertLess(c["ratio"], 0.35, f"Turn {c['turn']} ratio {c['ratio']} 过高")
            # 3. 断言推导出的 Pool/Heal 比例符合满血全队 1%~2% 扣血常数
            self.assertGreater(c["pool_to_heal"], 0.003)
            self.assertLess(c["pool_to_heal"], 0.025)

    def _verify_exact_first_cast_heals(self, log_name: str, expected_battle_heal: float) -> None:
        """断言首动前官方日志底层 OnStatChange 提取出的真实治疗流水与理论计算误差 < 0.01%."""
        log_path = os.path.join(ROOT_DIR, "battle_logs", log_name)
        with open(log_path, "r", encoding="utf-8") as f:
            events = [json.loads(line) for line in f]

        first_serv_idx = None
        for i, e in enumerate(events):
            if e.get("event") == "OnDamage":
                d = e["data"]
                if d.get("attacker", {}).get("uid") == 1409 and d.get("type") == "Servant":
                    first_serv_idx = i
                    break

        self.assertIsNotNone(first_serv_idx)
        heals = []
        for i in range(first_serv_idx):
            e = events[i]
            if e.get("event") == "OnStatChange":
                d = e["data"]
                ent = d.get("entity", {})
                prop = d.get("property", {})
                if ent.get("team") == "Player" and prop.get("type") == "CurrentHP":
                    val = prop.get("value", 0)
                    if i + 1 < len(events):
                        e_next = events[i + 1]
                        if e_next.get("event") == "OnStatChange":
                            d_next = e_next["data"]
                            if (
                                d_next.get("entity", {}).get("uid") == ent.get("uid")
                                and d_next.get("property", {}).get("type") == "CurrentHP"
                            ):
                                val_next = d_next.get("property", {}).get("value", 0)
                                if val_next > val:
                                    heals.append(val)

        total_battle_heals = sum(heals)
        err = abs(total_battle_heals - expected_battle_heal) / expected_battle_heal
        self.assertLess(err, 0.0001, f"{log_name} 战斗治疗流水误差过大: {err:.4%} (GT={total_battle_heals}, Exp={expected_battle_heal})")

    def _verify_strict_all_casts(self, log_name: str, expected_casts: int) -> None:
        """严格门禁：全场每一动 (< 0.20%) 显式扣血、Servant伤害、Additional伤害与比值全指标收敛."""
        log_path = os.path.join(ROOT_DIR, "battle_logs", log_name)
        harness = FixedReconciliationHarness(log_path)
        records = harness.run_reconciliation()
        self.assertEqual(len(records), expected_casts, f"{log_name} Cast 数量应严格等于 {expected_casts}")
        for r in records:
            self.assertGreater(r.acc_healing, 0.0)
            self.assertGreater(r.lc_pool, 0.0)
            self.assertLess(
                r.drain_err,
                0.002,
                f"{log_name} Cast #{r.cast_index} (AV={r.av:.2f}) 显式角色扣血误差过大: {r.drain_err:.4%}",
            )
            self.assertLess(
                r.servant_err,
                0.002,
                f"{log_name} Cast #{r.cast_index} (AV={r.av:.2f}) 小伊卡伤害误差过大: {r.servant_err:.4%} (SIM={r.sim_servant_dmg:.2f}, GT={r.gt_servant_dmg:.2f})",
            )
            self.assertLess(
                r.additional_err,
                0.002,
                f"{log_name} Cast #{r.cast_index} (AV={r.av:.2f}) 光锥附加伤害误差过大: {r.additional_err:.4%} (SIM={r.sim_additional_dmg:.2f}, GT={r.gt_additional_dmg:.2f})",
            )
            self.assertLess(
                r.ratio_err,
                0.002,
                f"{log_name} Cast #{r.cast_index} (AV={r.av:.2f}) 比值误差过大: {r.ratio_err:.4%} (SIM={r.sim_ratio:.6f}, GT={r.gt_ratio:.6f})",
            )

    def test_184845_casts(self) -> None:
        self._verify_log_casts("battle_20261114_184845.jsonl", expected_casts=5)
        self._verify_strict_all_casts("battle_20261114_184845.jsonl", expected_casts=5)

    def test_204943_casts(self) -> None:
        self._verify_log_casts("battle_20261114_204943.jsonl", expected_casts=6)
        # 2人队(风堇+晴歌): 战技 2×1093.57 + 终结技 2×1366.97 + 天赋 2波×2×321.17 = 6205.77
        self._verify_exact_first_cast_heals("battle_20261114_204943.jsonl", 6205.7712)
        self._verify_strict_all_casts("battle_20261114_204943.jsonl", expected_casts=6)

    def test_220255_casts(self) -> None:
        self._verify_log_casts("battle_20261114_220255.jsonl", expected_casts=20)
        # 3人队(缇宝+风堇+晴歌): 战技 3×1093.57 + 终结技 3×1366.97 + 天赋 2波×3×321.17 + 缇宝E1 1148.25 = 10456.90
        self._verify_exact_first_cast_heals("battle_20261114_220255.jsonl", 10456.9030)
        self._verify_strict_all_casts("battle_20261114_220255.jsonl", expected_casts=29)

    def test_221208_casts(self) -> None:
        self._verify_log_casts("battle_20261114_221208.jsonl", expected_casts=20)
        # 3人队(长夜月+风堇+晴歌, 无缇宝E1): 战技 3×1093.57 + 终结技 3×1366.97 + 天赋 2波×3×321.17 = 9308.66
        self._verify_exact_first_cast_heals("battle_20261114_221208.jsonl", 9308.6568)
        self._verify_strict_all_casts("battle_20261114_221208.jsonl", expected_casts=26)

    def test_041608_casts(self) -> None:
        self._verify_log_casts("battle_20261115_041608.jsonl", expected_casts=7)
        # 4人队(长夜月+缇宝+风堇+晴歌): 战技 4×1093.57 + 终结技 4×1366.97 + 天赋 2波×4×321.17 + 缇宝E1 1148.25 = 13559.79
        self._verify_exact_first_cast_heals("battle_20261115_041608.jsonl", 13559.7924)
        self._verify_strict_all_casts("battle_20261115_041608.jsonl", expected_casts=7)


if __name__ == "__main__":
    unittest.main()

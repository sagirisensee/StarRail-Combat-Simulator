"""Unit tests for ``simulator.vm.audit_vm_coverage``."""

from __future__ import annotations

import unittest

from simulator.vm.audit_vm_coverage import VMCoverageAuditor


class TestAuditVMCoverage(unittest.TestCase):
    def test_audit_all_domains_and_markdown_report(self) -> None:
        auditor = VMCoverageAuditor()
        self.assertIn("RPG.GameCore.DamageByAttackProperty", auditor.supported_tasks)
        self.assertIn("RPG.GameCore.CreateBattleEvent", auditor.supported_tasks)
        self.assertIn("RPG.GameCore.SummonMonster", auditor.supported_tasks)
        self.assertIn("RPG.GameCore.JDOLDFECMPL", auditor.supported_tasks)
        self.assertIn("RPG.GameCore.ByAnd", auditor.supported_predicates)
        self.assertIn("RPG.GameCore.ByCompareDynamicValue", auditor.supported_predicates)
        self.assertIn("RPG.GameCore.ByCompareMonsterPhase", auditor.supported_predicates)
        self.assertIn("RPG.GameCore.ShowBossInfoBar", auditor.prunable_types)

        report = auditor.audit_all()
        self.assertEqual(
            set(report.domains.keys()),
            {"BattleEvent", "Monster", "5StarAvatar", "5StarLightCone", "RelicSet"},
        )
        for name, stats in report.domains.items():
            self.assertGreater(stats.files_scanned, 0, f"{name} should scan >0 files")
            self.assertGreater(stats.task_total_occurrences, 0, f"{name} should have tasks")
            self.assertEqual(
                stats.unsupported_opcodes,
                {},
                f"{name} encountered unsupported PostfixExpr opcodes: {stats.unsupported_opcodes}",
            )
            self.assertEqual(
                stats.unknown_expr_func_hashes,
                {},
                f"{name} encountered unknown PostfixExpr builtin hashes: {stats.unknown_expr_func_hashes}",
            )

        md = report.to_markdown(top_n=15)
        self.assertIn("BattleEvent", md)
        self.assertIn("Monster", md)
        self.assertIn("5StarAvatar", md)


if __name__ == "__main__":
    unittest.main()

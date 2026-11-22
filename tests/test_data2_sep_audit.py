"""Regression tests for the DataB SEP-disabled patch inventory and read-only probe."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "data2_sep_audit.py"
spec = importlib.util.spec_from_file_location("data2_sep_audit", SCRIPT)
sep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sep)


class Data2SepAuditTests(unittest.TestCase):
    def test_exact_profile_has_26_stubbed_acm_methods(self):
        report = sep.audit(ROOT)
        self.assertEqual(report["target"], "d431ap-24A446")
        self.assertEqual(report["acm_forced_success_methods"], 26)
        self.assertEqual(report["acm_patch_words"], 52)
        self.assertEqual(report["osb_records"], 7)
        self.assertTrue(report["aks_sep_booted_forced_false"])
        self.assertTrue(report["aks_start_sep_call_skipped"])
        self.assertEqual(report["sep_runtime_state"], "NOT MEASURED")
        self.assertFalse(report["all_sep_features_restored"])

    def test_unknown_profile_fails_without_fallback(self):
        with self.assertRaises(sep.AuditError):
            sep.audit(ROOT, "d421ap-24A446")

    def test_missing_exact_profile_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(sep.AuditError):
                sep.audit(Path(tmp))

    def test_malformed_json_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "profiles" / sep.TARGET
            base.mkdir(parents=True)
            (base / "kernel-boot-jit.json").write_text("{broken")
            (base / "kernel-osb.json").write_text("[]")
            with self.assertRaises(sep.AuditError):
                sep.audit(Path(tmp))

    def test_unapproved_ssh_commands_are_refused(self):
        with mock.patch.object(sep.subprocess, "run") as runner:
            with self.assertRaises(sep.AuditError):
                sep._read_only_ssh(ROOT, "rm -rf /private/var")
            runner.assert_not_called()

    def test_default_audit_never_uses_ssh(self):
        with mock.patch.object(sep.subprocess, "run", side_effect=AssertionError("SSH called")):
            sep.audit(ROOT)

    def test_probe_is_opt_in_private_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "working"
            checkout.mkdir()
            (checkout / "dualboot.py").write_text("# fixture")
            output = Path(tmp) / "private-report"
            with mock.patch.object(sep, "_read_only_ssh", return_value=(0, b"SEP probe text\n")) as fake:
                sep.probe(checkout, output)
                self.assertEqual(fake.call_count, len(sep.READ_ONLY_PROBES))
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for name in (*sep.READ_ONLY_PROBES, "README.txt"):
                self.assertTrue((output / name).is_file())
                self.assertEqual((output / name).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(sep.AuditError):
                sep.probe(checkout, output)


if __name__ == "__main__":
    unittest.main()

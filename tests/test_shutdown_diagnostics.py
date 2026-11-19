import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "standalone/pico2/collect_shutdown_diagnostics.py"
spec = importlib.util.spec_from_file_location("shutdown_diagnostics", SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class ShutdownCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        (self.checkout / "dualboot.py").write_text("# mocked")
        self.output = self.root / "private"
        self.log = ("/private/var/mobile/Library/Logs/CrashReporter/"
                    "panic-full-2026-11-19.ips")

    def test_rejects_untrusted_remote_paths(self):
        for bad in ("/etc/passwd", "/private/var/mobile/Library/Logs/CrashReporter/../panic-full.ips",
                    "/private/var/mobile/Library/Logs/CrashReporter/a;rm panic-full.ips",
                    "panic-full.ips"):
            self.assertFalse(collector.valid_log_path(bad))
        self.assertTrue(collector.valid_log_path(self.log))

    def test_readonly_collection_saves_private_logs(self):
        commands = []
        def ssh(checkout, command, timeout=120):
            commands.append(command)
            if command.startswith("find "):
                return (self.log + "\n/etc/panic-full.ips\n").encode()
            if command.startswith("head "):
                return b'{"panicString":"watchdog timeout"}\n'
            return b"uptime: 00:12:43\n"
        with mock.patch.object(collector, "execute_ssh", side_effect=ssh):
            collector.run(self.checkout, self.output)
        self.assertTrue((self.output / "system-snapshot.txt").is_file())
        self.assertEqual(len(list(self.output.glob("*panic-full*"))), 1)
        self.assertNotIn("/etc/panic-full.ips", (self.output / "inventory.txt").read_text())
        self.assertTrue((self.output.stat().st_mode & 0o777) <= 0o700)
        for command in commands:
            self.assertNotIn("rm ", command)
            self.assertNotIn("mount -", command)
            self.assertNotIn("nvram ", command)
            self.assertNotIn("install ", command)

    def test_fails_if_output_exists(self):
        self.output.mkdir()
        with self.assertRaisesRegex(collector.DiagnoseError, "overwrite"):
            collector.run(self.checkout, self.output)

    def test_no_phone_when_missing_checkout(self):
        with self.assertRaises(FileNotFoundError):
            collector.run(self.root / "missing", self.output)

    def test_missing_logs_is_reported_not_treated_as_panic(self):
        def ssh(checkout, command, timeout=120):
            return b"" if command.startswith("find ") else b"uptime: 12m\n"
        with mock.patch.object(collector, "execute_ssh", side_effect=ssh):
            collector.run(self.checkout, self.output)
        self.assertIn("Remote files inventoried: 0", (self.output / "README.txt").read_text())


if __name__ == "__main__":
    unittest.main()

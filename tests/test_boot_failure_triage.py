import contextlib
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import boot_failure_triage as triage


class PanicTriageTests(unittest.TestCase):
    def test_empty_reports_do_not_prove_kernel_started(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(StringIO()) as out:
            self.assertEqual(triage.analyze(Path(directory), 8), 0)
            self.assertIn('does not prove', out.getvalue())

    def test_reports_are_summarized_without_sensitive_contents(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(StringIO()) as out:
            path = Path(directory) / 'panic-full-test.ips'
            path.write_text('panicString: TXM SPTM trustcache UUID=secret-device-id')
            self.assertEqual(triage.analyze(Path(directory), 8), 0)
            self.assertIn('SPTM/TXM', out.getvalue())
            self.assertIn('Trust cache / signing', out.getvalue())
            self.assertNotIn('secret-device-id', out.getvalue())

    @mock.patch.object(triage.shutil, 'which', return_value='/opt/homebrew/bin/idevicecrashreport')
    @mock.patch.object(triage, 'connected_device', return_value='test-udid')
    @mock.patch.object(triage.subprocess, 'run')
    def test_collect_always_keeps_reports_on_device(self, run, device, which):
        run.return_value = subprocess.CompletedProcess([], 0, '', '')
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(StringIO()):
            triage.collect(Path(directory), None)
            args = run.call_args.args[0]
            self.assertEqual(args[:4], ['idevicecrashreport', '--keep', '-u', 'test-udid'])
            self.assertNotIn('--remove-all', args)

    def test_rejects_ambiguous_connected_devices(self):
        with (mock.patch.object(triage.shutil, 'which', return_value='idevice_id'),
              mock.patch.object(triage.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'A\nB\n', ''))):
            with self.assertRaisesRegex(RuntimeError, 'found 2'):
                triage.connected_device(None)


if __name__ == '__main__':
    unittest.main()

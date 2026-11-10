import contextlib
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

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

    def test_resetcounter_uses_embedded_date_not_copy_time(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(StringIO()) as out:
            path = Path(directory) / 'ResetCounter-2026-11-10-021214.ips'
            path.write_text('Date: 2026-11-10 02:12:14.24 -0500\nBoot failure count: 2\n'
                            'Boot stage: 0x10\nBoot faults: rst dbg_rst,reset_in_2\n')
            self.assertEqual(triage.analyze(Path(directory), 8), 0)
            self.assertIn('2026-11-10 02:12:14 -0500', out.getvalue())
            self.assertIn('boot stage=0x10', out.getvalue())
            self.assertIn('Boot failure count=2', out.getvalue())
            self.assertIn('ResetCounter is not a kernel backtrace', out.getvalue())

    def test_analyzes_zip_without_extracting_files(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(StringIO()) as out:
            archive = Path(directory) / 'reports.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('ResetCounter-2026-11-10-023104.ips',
                           'Date: 2026-11-10 02:31:04.24 -0500\nBoot failure count: 1\n'
                           'Boot stage: 0x30\nBoot faults: rst btn_rst\n')
            self.assertEqual(triage.analyze(archive, 8), 0)
            self.assertIn('boot stage=0x30', out.getvalue())

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

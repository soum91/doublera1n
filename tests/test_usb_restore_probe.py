"""Offline checks for the isolated no-UART USB transport experiment."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('usb_probe_client', ROOT / 'scripts/usb_probe_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class RestoreUsbProbeTests(unittest.TestCase):
    def test_banner_protocol(self):
        good = b'DOUBLERA1N_USB_PROBE_V1\nread_only=yes\napfs_writes=no\n'
        self.assertTrue(client.valid_banner(good))
        self.assertFalse(client.valid_banner(b'DOUBLERA1N_USB_PROBE_V1\nread_only=no\n'))
        self.assertFalse(client.valid_banner(b'unknown service'))

    def test_probe_is_separate_from_disk_changing_installer(self):
        source = (ROOT / 'src/rdprobe.c').read_text()
        for action in ('newfs_apfs(', 'APFSVolumeDelete(', 'mount_apfs(', 'do_install(', 'do_remove('):
            self.assertNotIn(action, source)
        builder = (ROOT / 'lib/mk_setuprd.py').read_text()
        self.assertIn("binary = RDPROBE if mode == 'probe' else RDSETUP", builder)

    def test_usb_probe_requires_explicit_boot_flag(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'dualboot.py'), 'probe-usb', '--help'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('--boot', proc.stdout)
        self.assertIn('read-only', proc.stdout.lower())

    def test_timeout_diagnostics_distinguish_apple_usb_from_irecovery(self):
        usb = types.ModuleType('usb')
        core = types.ModuleType('usb.core')
        core.find = mock.Mock(return_value=[types.SimpleNamespace(idProduct=0x12a8)])
        usb.core = core
        output = io.StringIO()
        reply = subprocess.CompletedProcess([], 1, stdout='', stderr='Unable to connect to device')
        with (mock.patch.dict(sys.modules, {'usb': usb, 'usb.core': core}),
              mock.patch.object(client.subprocess, 'run', return_value=reply),
              redirect_stdout(output)):
            client.final_usb_diagnostics()
        self.assertIn('Apple USB products: 0x12a8', output.getvalue())
        self.assertIn('irecovery read-only status: exit=1', output.getvalue())


if __name__ == '__main__':
    unittest.main()

"""Offline checks for the isolated no-UART USB transport experiment."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


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


if __name__ == '__main__':
    unittest.main()

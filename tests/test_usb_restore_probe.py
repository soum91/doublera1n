"""Offline checks for the isolated no-UART USB transport experiment."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
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
        self.assertIn('--variant', proc.stdout)
        self.assertIn('read-only', proc.stdout.lower())

    def test_stock_usb_observer_does_not_count_recovery_as_ramdisk(self):
        output = io.StringIO()
        with (mock.patch.object(client, 'apple_usb_pids', side_effect=[(0x1281,), (0x12a8,)]),
              mock.patch.object(client, 'usbmux_ids', return_value=[]),
              mock.patch.object(client, 'final_usb_diagnostics') as diagnostics,
              mock.patch.object(client.time, 'sleep'),
              redirect_stdout(output)):
            self.assertEqual(client.observe_stock_usb(10), 0)
        self.assertIn('Apple USB IDs: 0x1281', output.getvalue())
        self.assertIn('Apple USB IDs: 0x12a8', output.getvalue())
        self.assertIn('NOT establish ramdisk startup', output.getvalue())
        diagnostics.assert_called_once()

    def test_stock_builder_never_mounts_or_injects(self):
        class FakeIM4P:
            def __init__(self, payload):
                self.payload = payload
                self.fourcc = 'original'

        class FakeIMG4:
            def __init__(self, im4p, im4m):
                self.im4p = im4p

            def output(self):
                return self.im4p.fourcc.encode() + b':' + self.im4p.payload

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ticket').write_bytes(b'ticket')
            (root / 'RestoreRamDisk').write_bytes(b'unchanged-ramdisk')
            (root / 'RestoreTrustCache').write_bytes(b'unchanged-trustcache')
            osbcfg = types.ModuleType('osbcfg')
            osbcfg.WORK = tmp
            osbcfg.out = lambda name: str(root / 'ticket')
            osbcfg.ipsw = lambda name: str(root / name)
            osbcfg.work = lambda name: str(root / name)
            pyimg4 = types.ModuleType('pyimg4')
            pyimg4.IM4M = lambda payload: payload
            pyimg4.IM4P = FakeIM4P
            pyimg4.IMG4 = FakeIMG4
            with mock.patch.dict(sys.modules, {'osbcfg': osbcfg, 'pyimg4': pyimg4}):
                spec = importlib.util.spec_from_file_location('mk_setuprd_test', ROOT / 'lib/mk_setuprd.py')
                builder = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(builder)
            with (mock.patch.object(sys, 'argv', ['mk_setuprd.py', 'stock']),
                  mock.patch.object(builder, 'sh', side_effect=AssertionError('must not mount')),
                  mock.patch.object(builder.shutil, 'copyfile',
                                    side_effect=AssertionError('must not inject'))):
                builder.main()
            self.assertEqual((root / 'setuprd-stock.img4').read_bytes(), b'rdsk:unchanged-ramdisk')
            self.assertEqual((root / 'setuptc-stock.img4').read_bytes(), b'rtsc:unchanged-trustcache')

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

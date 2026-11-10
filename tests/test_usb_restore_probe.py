"""Offline checks for the isolated no-UART USB transport experiment."""
import importlib.util
import io
import json
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

plan_spec = importlib.util.spec_from_file_location('probe_patch_plan', ROOT / 'lib/probe_patch_plan.py')
plan = importlib.util.module_from_spec(plan_spec)
plan_spec.loader.exec_module(plan)

driver_spec = importlib.util.spec_from_file_location('dualboot_test', ROOT / 'dualboot.py')
driver = importlib.util.module_from_spec(driver_spec)
driver_spec.loader.exec_module(driver)


class RestoreUsbProbeTests(unittest.TestCase):
    def test_kernel_probe_variants_limit_changes_to_known_amfi_records(self):
        records = [
            {'id': 'kernel.panic.seal-broken'},
            {'id': 'kernel.amfi.trust-cache.0'},
            {'id': 'kernel.amfi.launch-constraints.return'},
            {'id': 'kernel.amfi.dyld-policy.1'},
        ]
        self.assertEqual(plan.select_kernel_records(records, 'full'), records)
        self.assertEqual(plan.select_kernel_records(records, 'stock-kernel'), [])
        self.assertEqual(
            [r['id'] for r in plan.select_kernel_records(records, 'lean-kernel')],
            ['kernel.amfi.trust-cache.0', 'kernel.amfi.launch-constraints.return'])
        with self.assertRaises(ValueError):
            plan.select_kernel_records(records, 'unknown')
        with self.assertRaises(ValueError):
            plan.select_kernel_records([{'id': 'kernel.panic.seal-broken'}], 'lean-kernel')

        real_records = json.loads((ROOT / 'profiles/d431ap-24A446/kernel-restore-nodebugger.json').read_text())
        real_records = [r for r in real_records if not r['id'].startswith('kernel.identity')]
        self.assertEqual(len(plan.select_kernel_records(real_records, 'lean-kernel')), 7)

    def test_experimental_kernel_builder_is_isolated_from_installer(self):
        ws = mock.Mock()
        ws.env.return_value = {'DOUBLERA1N_READ_ONLY_PROBE': '1'}
        with mock.patch.object(driver, 'run') as subprocess_call:
            driver.build_setup_chain(ws, 'probe', kernel_variant='lean-kernel')
        self.assertEqual(ws.py.call_count, 2)
        self.assertEqual(ws.py.call_args_list[0].args[:2], ('mk_setuprd.py', 'probe'))
        self.assertEqual(ws.py.call_args_list[1].args[:2], ('mk_chain.py', 'probe'))
        self.assertEqual(subprocess_call.call_args.args[-1], '--probe-lean-kernel')
        self.assertEqual(subprocess_call.call_args.kwargs['env']['DOUBLERA1N_READ_ONLY_PROBE'], '1')
        ws.reset_mock()
        with mock.patch.object(driver, 'run') as subprocess_call:
            driver.build_setup_chain(ws, 'install')
        subprocess_call.assert_not_called()
        self.assertEqual(ws.py.call_args_list[-1].args[0], 'mk_kernel.py')
        with self.assertRaises(SystemExit):
            driver.build_setup_chain(ws, 'install', kernel_variant='lean-kernel')

    def test_kernel_experiments_are_opt_in_and_install_path_is_unchanged(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'dualboot.py'), 'probe-usb', '--help'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('stock-kernel', proc.stdout)
        self.assertIn('lean-kernel', proc.stdout)
        self.assertIn('reference-order', proc.stdout)
        source = (ROOT / 'dualboot.py').read_text()
        builder = (ROOT / 'lib/mk_kernel.py').read_text()
        self.assertIn("mode != 'probe'", source)
        self.assertIn("env=ws.env(DOUBLERA1N_READ_ONLY_PROBE='1')", source)
        self.assertIn('DOUBLERA1N_READ_ONLY_PROBE', builder)
        self.assertIn("variant == 'stock-kernel'", builder)
        self.assertIn('patched TXM retained', builder)

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

    def test_native_ibec_diagnostic_is_opt_in_and_refuses_redundant_boot(self):
        cli = subprocess.run([sys.executable, str(ROOT / 'dualboot.py'), 'probe-usb', '--help'],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertIn('native-ibec', cli.stdout)
        builder = (ROOT / 'dualboot.py').read_text()
        chain = (ROOT / 'lib/mk_chain.py').read_text()
        self.assertIn("native_setup_ibec=a.variant == 'native-ibec'", builder)
        self.assertIn("images.append(('iBEC', 'iBoot.setup.ibec.raw'", builder)
        self.assertIn("NATIVE_IBEC = '--native-ibec' in sys.argv", chain)
        self.assertIn("if NATIVE_IBEC and ibec_bytes == open(MIN_IBOOT, 'rb').read():", chain)
        self.assertIn('no distinct boot experiment; STOP before boot', chain)

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

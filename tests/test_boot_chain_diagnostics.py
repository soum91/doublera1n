"""Offline regressions for the first physical iBSS handoff."""
import importlib.util
import io
from pathlib import Path
from contextlib import redirect_stdout
import subprocess
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_boot_chain():
    # The host running offline tests need not have PyUSB or a connected iPhone.
    core = types.ModuleType('usb.core')
    core.USBError = type('USBError', (Exception,), {})
    core.find = mock.Mock(return_value=None)
    util = types.ModuleType('usb.util')
    util.dispose_resources = mock.Mock()
    usb = types.ModuleType('usb')
    usb.core = core
    usb.util = util
    config = types.ModuleType('osbcfg')
    config.work = lambda kind: str(ROOT / 'work' / kind)
    modules = {'usb': usb, 'usb.core': core, 'usb.util': util, 'osbcfg': config}
    with mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location('boot_chain_diagnostics', ROOT / 'lib/boot_chain.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class BootChainDiagnosticsTests(unittest.TestCase):
    def test_reference_order_stages_dt_before_trust_caches_and_ramdisk(self):
        chain = load_boot_chain()
        chain.send = mock.Mock()
        chain.upload = mock.Mock()
        chain.recovery = mock.Mock(return_value=object())
        chain.recovery_devices = mock.Mock(return_value=iter(()))
        chain.observe_boot_usb = mock.Mock()
        chain.set_probe_bootargs = mock.Mock()
        reply = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        with (mock.patch.object(sys, 'argv', ['boot_chain.py', '--probe-reference-order',
                                             '--probe-explicit-bootargs']),
              mock.patch.object(chain.os.path, 'exists', return_value=True),
              mock.patch.object(chain.time, 'sleep'),
              mock.patch.object(chain.subprocess, 'run', return_value=reply)):
            chain.stages_from_firmware()
        names = [c.args[0] for c in chain.send.call_args_list]
        self.assertEqual(names[:2], ['SPTM.img4', 'TXM.img4'])
        self.assertLess(names.index('SEP.img4'), names.index('PMP.img4'))
        self.assertLess(names.index('DeviceTree.img4'), names.index('StaticTrustCache.img4'))
        self.assertLess(names.index('RestoreTrustCache.img4'), names.index('RestoreRamdisk.img4'))
        self.assertEqual(names.count('SEP.img4'), 1)
        self.assertEqual(names.count('RestoreTrustCache.img4'), 1)
        chain.set_probe_bootargs.assert_called_once()

    def test_reference_order_cannot_be_called_from_installer(self):
        chain = load_boot_chain()
        with mock.patch.object(sys, 'argv', ['boot_chain.py', '--probe-reference-order']):
            with self.assertRaisesRegex(SystemExit, 'restricted to the read-only probe'):
                chain.main()

    def test_first_stage_uses_active_venv_and_reveals_sender_error(self):
        chain = load_boot_chain()
        with mock.patch.object(chain.subprocess, 'run', side_effect=[
                subprocess.CompletedProcess([], 0, stdout='PWND: usbliter8'),
                subprocess.CompletedProcess([], 1, stdout='', stderr='No module named usb'),
        ]) as run, mock.patch.object(chain, 'device_diagnostics') as diagnostics:
            with self.assertRaisesRegex(SystemExit, 'iBSS send failed'):
                chain.main()
            call = run.call_args_list[1].args[0]
            self.assertEqual(call[0], sys.executable)
            self.assertEqual(call[1], chain.CTL)
            diagnostics.assert_called_once()

    def test_recovery_detects_other_documented_pid(self):
        chain = load_boot_chain()
        healthy = types.SimpleNamespace(serial_number='CPID:8030')
        chain.usb.core.find.side_effect = lambda **kw: healthy if kw.get('idProduct') == 0x1282 else None
        self.assertIs(chain.recovery(timeout=1), healthy)
        self.assertEqual(chain.RECOVERY_PIDS, (0x1280, 0x1281, 0x1282, 0x1283))

    def test_raw_apple_usb_snapshot_includes_non_recovery_pid(self):
        chain = load_boot_chain()
        devices = [types.SimpleNamespace(idProduct=0x12a8),
                   types.SimpleNamespace(idProduct=0x1281)]
        chain.usb.core.find.return_value = devices
        self.assertEqual(chain.apple_usb_pids(), (0x1281, 0x12a8))

    def test_bootx_exit_and_usb_handoff_are_observed_not_claimed(self):
        chain = load_boot_chain()
        chain.FIRMWARE = []
        chain.send = mock.Mock()
        chain.upload = mock.Mock()
        chain.recovery = mock.Mock(return_value=object())
        chain.recovery_devices = mock.Mock(return_value=iter(()))
        chain.observe_boot_usb = mock.Mock()
        output = io.StringIO()
        reply = subprocess.CompletedProcess([], 1, stdout='', stderr='USB disconnected')
        with (mock.patch.object(chain.subprocess, 'run', return_value=reply) as run,
              redirect_stdout(output)):
            chain.stages_from_firmware()
        self.assertEqual(run.call_args.args[0], ['irecovery', '-c', 'bootx'])
        chain.observe_boot_usb.assert_called_once()
        self.assertIn('bootx command exit=1', output.getvalue())
        self.assertIn('kernel and ramdisk startup NOT verified', output.getvalue())

    def test_minimal_probe_keeps_core_security_firmware_and_trust_caches(self):
        chain = load_boot_chain()
        self.assertEqual(chain.PROBE_CORE_FIRMWARE,
                         {'SPTM.img4', 'TXM.img4', 'StaticTrustCache.img4', 'RestoreTrustCache.img4'})
        with (mock.patch.object(sys, 'argv', ['boot_chain.py', '--probe-minimal-fw']),
              mock.patch.object(chain, 'device_diagnostics'),
              mock.patch.object(chain.subprocess, 'run', side_effect=[
                  subprocess.CompletedProcess([], 0, stdout='PWND: usbliter8'),
                  subprocess.CompletedProcess([], 1, stdout='', stderr='test stop before upload'),
              ])):
            with self.assertRaisesRegex(SystemExit, 'iBSS send failed'):
                chain.main()
        self.assertEqual({name for name, _ in chain.FIRMWARE}, chain.PROBE_CORE_FIRMWARE)

    def test_minimal_firmware_refuses_jailbreak_boot(self):
        chain = load_boot_chain()
        chain.OSBJB = True
        with mock.patch.object(sys, 'argv', ['boot_chain.py', '--probe-minimal-fw']):
            with self.assertRaisesRegex(SystemExit, 'forbidden for 2nd Data'):
                chain.main()

    def test_explicit_probe_bootargs_are_volatile_and_checked(self):
        chain = load_boot_chain()
        with mock.patch.object(chain, 'cmd') as cmd:
            chain.set_probe_bootargs()
        cmd.assert_called_once_with('setenv boot-args rd=md0 -v debug=0x2014e')

    def test_explicit_probe_bootargs_refuse_jailbreak(self):
        chain = load_boot_chain()
        chain.OSBJB = True
        with self.assertRaisesRegex(SystemExit, 'forbidden for 2nd Data'):
            chain.set_probe_bootargs()

    def test_explicit_probe_bootargs_precede_bootx(self):
        chain = load_boot_chain()
        chain.FIRMWARE = []
        chain.send = mock.Mock()
        chain.upload = mock.Mock()
        chain.recovery = mock.Mock(return_value=object())
        chain.recovery_devices = mock.Mock(return_value=iter(()))
        chain.observe_boot_usb = mock.Mock()
        events = []
        chain.set_probe_bootargs = mock.Mock(side_effect=lambda: events.append('bootargs'))
        with (mock.patch.object(sys, 'argv', ['boot_chain.py', '--probe-explicit-bootargs']),
              mock.patch.object(chain.subprocess, 'run',
                                side_effect=lambda *a, **kw: (
                                    events.append('bootx') or subprocess.CompletedProcess([], 0, stdout='', stderr='')
                                ))):
            chain.stages_from_firmware()
        self.assertEqual(events, ['bootargs', 'bootx'])


if __name__ == '__main__':
    unittest.main()

"""Offline regressions for the first physical iBSS handoff."""
import importlib.util
from pathlib import Path
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


if __name__ == '__main__':
    unittest.main()

"""Host-only regression tests; no device, DFU or Apple firmware involved."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / 'standalone' / 'pico2' / 'boot_bundle.py'
spec = importlib.util.spec_from_file_location('boot_bundle', MOD)
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.ws = self.dir / 'abcdef0123456789-24A446'
        (self.ws / 'build' / 'osbjb').mkdir(parents=True)
        (self.ws / 'out').mkdir(parents=True)
        (self.ws / 'out' / 'apticket.installed.der').write_bytes(b'fake ticket (not an actual APTicket)')
        (self.ws / 'state.json').write_text('{"board":"d431ap","build":"24A446","installed":true}')
        for i, (name, action, _) in enumerate(boot.FULL):
            if name and name != 'WCH.img4':
                (self.ws / 'build' / 'osbjb' / name).write_bytes(bytes([i + 1]) * (111 + i * 227))
        self.out = self.dir / 'BOOT.BIN'

    def make_bundle(self):
        class Opt:
            board = 'd431ap'
            build = '24A446'
            work_root = ''
            workspace = ''
            dry_run = False
            overwrite = False
            output = ''
        opt = Opt()
        opt.workspace = str(self.ws)
        opt.output = str(self.out)
        with contextlib.redirect_stdout(io.StringIO()):
            boot.export_bundle(opt)
        return opt

    def test_roundtrip_and_verified_native_core(self):
        self.make_bundle()
        with contextlib.redirect_stdout(io.StringIO()):
            es = boot.inspect(self.out)
        self.assertEqual(es[0][0:2], ('iBSS.raw', 'dfu_boot'))
        self.assertEqual(es[-1][0:2], ('', 'bootx'))
        self.assertNotIn('StaticTrustCache.img4', [e[0] for e in es])
        self.assertNotIn('WCH.img4', [e[0] for e in es])
        if shutil.which('cc'):
            exe = self.dir / 'check'
            cp = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-o', str(exe),
                                 str(ROOT/'standalone/pico2/inspect_bundle.c'),
                                 str(ROOT/'standalone/pico2/boot_plan.c')], capture_output=True, text=True)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            result = subprocess.run([str(exe), str(self.out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_tampered_data(self):
        self.make_bundle()
        with self.out.open('r+b') as f:
            f.seek(4096)
            v = f.read(1)
            f.seek(4096)
            f.write(bytes([v[0] ^ 1]))
        with self.assertRaisesRegex(boot.BundleError, 'corrupt or modified'):
            boot.inspect(self.out)

    def test_rejects_missing_stage(self):
        (self.ws / 'build' / 'osbjb' / 'SEP.img4').unlink()
        with self.assertRaisesRegex(boot.BundleError, 'missing regular stage'):
            self.make_bundle()

    def test_rejects_wrong_build_and_install_state(self):
        (self.ws / 'state.json').write_text('{"board":"d421ap","build":"24A446","installed":true}')
        with self.assertRaisesRegex(boot.BundleError, 'mismatch'):
            self.make_bundle()
        (self.ws / 'state.json').write_text('{"board":"d431ap","build":"24A446","installed":false}')
        with self.assertRaisesRegex(boot.BundleError, 'installed'):
            self.make_bundle()

    def test_optional_wch(self):
        (self.ws / 'build' / 'osbjb' / 'WCH.img4').write_bytes(b'fake firmware')
        self.make_bundle()
        es = boot.inspect(self.out, quiet=True)
        self.assertIn('WCH.img4', [e[0] for e in es])

    def test_does_not_overwrite_existing(self):
        self.out.write_bytes(b'do not replace')
        with self.assertRaisesRegex(boot.BundleError, 'already exists'):
            self.make_bundle()
        self.assertEqual(self.out.read_bytes(), b'do not replace')

    def test_invalid_header_detected(self):
        self.make_bundle()
        with self.out.open('r+b') as f:
            f.write(b'INVALID!')
        with self.assertRaisesRegex(boot.BundleError, 'magic'):
            boot.inspect(self.out)

    def test_source_data_not_edited(self):
        original = (self.ws/'build/osbjb/Kernelcache.img4').read_bytes()
        self.make_bundle()
        self.assertEqual((self.ws/'build/osbjb/Kernelcache.img4').read_bytes(), original)

    def test_auto_workspace_selection(self):
        self.assertEqual(boot._auto_workspace(self.dir, 'd431ap', '24A446'), self.ws)
        (self.dir/'fake-24A446').mkdir()
        with self.assertRaisesRegex(boot.BundleError, 'exactly one'):
            (self.dir/'fake-24A446'/'state.json').write_text('{"board":"d431ap","build":"24A446","installed":true}')
            boot._auto_workspace(self.dir, 'd431ap', '24A446')


if __name__ == '__main__':
    unittest.main()

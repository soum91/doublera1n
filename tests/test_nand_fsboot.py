"""Tests run entirely on a host; no iPhone, USB or firmware writes."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('nand_fsboot', HERE / 'standalone/pico2/nand_fsboot.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class NANDProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repo'
        for directory in ('lib', 'src'):
            (self.root / directory).mkdir(parents=True)
        (self.root / 'lib/patch_iboot.py').write_text('def patch_fsboot_cmd(d, log): pass\n')
        (self.root / 'lib/mk_osbjb.py').write_text("'patch_iboot.py'), '--no-fsboot',\ndef build_ramdisk(): pass\nsign(IM4P(fourcc='rdsk', payload=rd)\n")
        (self.root / 'lib/boot_chain.py').write_text("send('RestoreRamdisk.img4', 'ramdisk'\nupload('Kernelcache.img4')\n")
        (self.root / 'src/rdsetup.c').write_text('mount_apfs", "-o", "ro", predev\n"/mnt2/jb"\n')
        self.raw = Path(self.tmp.name) / 'orig.raw'
        data = bytearray(b'\0' * 2048)
        data[0x300:0x306] = b'iBoot-'
        self.raw.write_bytes(data)
        self.hash_patch = mock.patch.object(mod, 'STOCK_SHA256', hashlib.sha256(data).hexdigest())
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)
        self.out = Path(self.tmp.name) / 'patched.raw'

    def tearDown(self):
        self.tmp.cleanup()

    def fake_runner(self, stdout=None, returncode=0):
        if stdout is None:
            stdout = 'memboot->fsboot\nremote-boot -> local\nauto-boot -> false\nboot-args\n'
        def run(cmd, **_kwargs):
            self.assertIn('--local', cmd)
            self.assertIn('--no-autoboot', cmd)
            self.assertIn('--keep-cmds', cmd)
            self.assertNotIn('--no-fsboot', cmd)
            self.assertFalse(any(x in str(cmd) for x in ['setenvnp', 'install', 'usb']))
            raw = bytearray(self.raw.read_bytes())
            raw[-1] = 0x7F
            Path(cmd[-1]).write_bytes(raw)
            return subprocess.CompletedProcess(cmd, returncode, stdout, 'failure' if returncode else '')
        return run

    def test_source_checks(self):
        a = mod.check_source(self.root)
        self.assertTrue(all(a['source_checks'].values()))
        self.assertFalse(a['safe_to_conclude_nand_boots_jailbreak'])

    def test_source_change_fails_closed(self):
        (self.root / 'lib/mk_osbjb.py').write_text('empty')
        with self.assertRaisesRegex(mod.ProbeError, 'source layout changed'):
            mod.check_source(self.root)

    def test_probe_preparation_is_host_only(self):
        r = mod.prepare(self.raw, self.out, patcher=self.root/'lib/patch_iboot.py', runner=self.fake_runner(), root=self.root)
        self.assertTrue(self.out.is_file())
        self.assertEqual(r['console_command_to_exercise_fsboot'], 'memboot')
        self.assertFalse(r['device_tested'])
        self.assertFalse(r['uf2_generated'])
        self.assertEqual(r['expected_if_it_works'], 'attempt stock NAND filesystem boot, NOT doublera1n/DataB')
        self.assertNotEqual(self.raw.read_bytes(), self.out.read_bytes())

    def test_refuses_to_overwrite_source(self):
        with self.assertRaisesRegex(mod.ProbeError, 'overwrite source'):
            mod.prepare(self.raw, self.raw, patcher=self.root/'lib/patch_iboot.py', runner=self.fake_runner(), root=self.root)

    def test_refuses_output_in_repository(self):
        with self.assertRaisesRegex(mod.ProbeError, 'Git repository'):
            mod.prepare(self.raw, self.root/'stage.raw', patcher=self.root/'lib/patch_iboot.py', runner=self.fake_runner(), root=self.root)

    def test_refuses_invalid_raw_iboot(self):
        self.raw.write_bytes(b'\0' * 2048)
        with self.assertRaisesRegex(mod.ProbeError, 'not raw iBoot'):
            mod.prepare(self.raw, self.out, patcher=self.root/'lib/patch_iboot.py', runner=self.fake_runner(), root=self.root)

    def test_refuses_missing_required_patch(self):
        with self.assertRaisesRegex(mod.ProbeError, 'required iBoot transformations'):
            mod.prepare(self.raw, self.out, patcher=self.root/'lib/patch_iboot.py',
                        runner=self.fake_runner(stdout='memboot->fsboot\n'), root=self.root)
        self.assertFalse(self.out.exists())

    def test_refuses_patcher_failure(self):
        with self.assertRaisesRegex(mod.ProbeError, 'patch_iboot failed'):
            mod.prepare(self.raw, self.out, patcher=self.root/'lib/patch_iboot.py',
                        runner=self.fake_runner(returncode=1), root=self.root)
        self.assertFalse(self.out.exists())

    def test_refuses_other_build_or_prepatched_input(self):
        data = bytearray(self.raw.read_bytes())
        data[-1] = 1
        self.raw.write_bytes(data)
        runner = mock.Mock()
        with self.assertRaisesRegex(mod.ProbeError, 'SHA256 mismatch'):
            mod.prepare(self.raw, self.out, runner=runner, root=self.root)
        runner.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_refuses_existing_output(self):
        self.out.write_bytes(b'untouched')
        with self.assertRaisesRegex(mod.ProbeError, 'already exists'):
            mod.prepare(self.raw, self.out, patcher=self.root/'lib/patch_iboot.py', runner=self.fake_runner(), root=self.root)
        self.assertEqual(self.out.read_bytes(), b'untouched')


if __name__ == '__main__':
    unittest.main()

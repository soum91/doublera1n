import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / 'standalone/pico2/stage_preboot.py'
if not SRC.is_file():
    SRC = Path(__file__).with_name('stage_preboot.py')
spec = importlib.util.spec_from_file_location('stage_preboot', SRC)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)

class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.export = self.base / 'PicoNAND'
        (self.export / 'preboot-files').mkdir(parents=True)
        self.checkout = self.base / 'checkout';self.checkout.mkdir()
        (self.checkout / 'dualboot.py').write_text('# mock')
        self.h = 'F' * 96
        self.ident = 'a' * 20
        self.dest = f'/private/preboot/{self.h}/doublera1n-pico2/{self.ident}'
        files = {}
        for name in stage.FILES:
            data = ('fake-data-' + name).encode()
            (self.export / 'preboot-files' / name).write_bytes(data)
            files[name] = {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        self.manifest = {'board':'d431ap','build':'24A446','selected_manifest_hash':self.h,
                         'staging_namespace':'/doublera1n-pico2/'+self.ident,
                         'ios_staging_directory':self.dest,
                         'target_preboot_directory':'/'+self.h+'/doublera1n-pico2/'+self.ident,
                         'files':files}
        self.write()

    def write(self):
        (self.export / 'stage-map.json').write_text(json.dumps(self.manifest))

    def test_valid_export(self):
        _, _, dest, h = stage.checked_export(self.export)
        self.assertEqual(dest,self.dest);self.assertEqual(h,self.h)

    def test_wrong_build(self):
        self.manifest['build']='INVALID';self.write()
        with self.assertRaises(stage.StageError):stage.checked_export(self.export)

    def test_manifest_mismatch(self):
        self.manifest['selected_manifest_hash']='D'*96;self.write()
        with self.assertRaises(stage.StageError):stage.checked_export(self.export)

    def test_directory_traversal(self):
        self.manifest['ios_staging_directory']='/private/preboot/../bad';self.write()
        with self.assertRaises(stage.StageError):stage.checked_export(self.export)

    def test_invalid_namespace(self):
        self.manifest['staging_namespace']='/boot';self.write()
        with self.assertRaises(stage.StageError):stage.checked_export(self.export)

    def test_changed_file(self):
        (self.export / 'preboot-files/kernel.img4').write_bytes(b'tampered')
        with self.assertRaises(stage.StageError):stage.checked_export(self.export)

    def test_readonly_by_default(self):
        response='Filesystem 1K-blocks Used Available Capacity Mounted on\n/dev/disk1s6 6000000 1000 6000000 1% /private/preboot\n'
        with mock.patch.object(stage, 'ssh', return_value=response) as ssh:
            stage.run(self.export, self.checkout, False)
        self.assertEqual(ssh.call_count,1)
        self.assertNotIn('mkdir',ssh.call_args.args[1])

    def test_staging_performs_readback_and_atomic_rename(self):
        response='Filesystem 1K-blocks Used Available Capacity Mounted on\n/dev/disk1s6 6000000 1000 6000000 1% /private/preboot\n'
        calls=[]
        def fake_ssh(checkout, command, *, input_file=None, stream_hash=False):
            calls.append((command,input_file,stream_hash))
            if stream_hash:
                name=command.rsplit('/',1)[-1].strip("'\"")
                info=self.manifest['files'][name]
                return info['bytes'],info['sha256']
            return response
        with mock.patch.object(stage, 'ssh', side_effect=fake_ssh):
            stage.run(self.export,self.checkout, True)
        self.assertEqual(len([x for x in calls if x[1] is not None]),5)
        self.assertEqual(len([x for x in calls if x[2]]),5)
        self.assertIn('mv ',calls[-1][0]);self.assertNotIn('rm -rf',str(calls))

    def test_low_space_never_stages(self):
        response='Filesystem 1K-blocks Used Available Capacity Mounted on\n/dev/disk1s6 3000 1000 2000 1% /private/preboot\n'
        with mock.patch.object(stage,'ssh',return_value=response) as ssh:
            with self.assertRaises(stage.StageError):stage.run(self.export,self.checkout, True)
        self.assertEqual(ssh.call_count,1)

if __name__ == '__main__':unittest.main()

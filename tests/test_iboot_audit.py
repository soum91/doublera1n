"""Malformed-input and branch-decoder tests; no Apple binaries or network."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('iboot_audit', ROOT / 'standalone/pico2/iboot_audit.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def manifest():
    return {'ProductBuildVersion': '24A446', 'BuildIdentities': [{
        'ApChipID': '0x8030', 'ApBoardID': '0x02',
        'Info': {'DeviceClass': 'd431ap', 'RestoreBehavior': 'Erase'},
        'Manifest': {'iBEC': {'Info': {'Path': 'Firmware/dfu/iBEC.d431.RELEASE.im4p'}}}}]}


class BinaryAuditTests(unittest.TestCase):
    def test_rejects_other_or_patched_raw_before_inspection(self):
        with mock.patch.object(audit, 'patcher_module') as patcher:
            with self.assertRaisesRegex(audit.AuditError, 'not the verified stock'):
                audit.analyze(bytes(2048))
            patcher.assert_not_called()

    def test_raw_length_and_hash_must_both_match(self):
        raw = b'fixture'
        with mock.patch.object(audit, 'STOCK_SIZE', len(raw)), mock.patch.object(
                audit, 'STOCK_SHA256', hashlib.sha256(raw).hexdigest()):
            audit.validate_raw(raw)
            with self.assertRaises(audit.AuditError):
                audit.validate_raw(b'fixturf')
            with self.assertRaises(audit.AuditError):
                audit.validate_raw(raw + b'x')

    def test_exact_identity(self):
        self.assertEqual(audit.manifest_component(manifest())['Info']['Path'],
                         'Firmware/dfu/iBEC.d431.RELEASE.im4p')

    def test_rejects_wrong_board_build_chip_and_ambiguous_identity(self):
        mutations = [lambda m: m.update(ProductBuildVersion='24B119'),
                     lambda m: m['BuildIdentities'][0]['Info'].update(DeviceClass='d421ap'),
                     lambda m: m['BuildIdentities'][0].update(ApChipID='0x8020'),
                     lambda m: m['BuildIdentities'][0].update(ApBoardID='0x04'),
                     lambda m: m['BuildIdentities'].append(copy.deepcopy(m['BuildIdentities'][0]))]
        for mutate in mutations:
            value = manifest(); mutate(value)
            with self.assertRaises(audit.AuditError):
                audit.manifest_component(value)

    def test_rejects_path_escape(self):
        for path in ('/tmp/iBEC', '../../iBEC'):
            value = manifest()
            value['BuildIdentities'][0]['Manifest']['iBEC']['Info']['Path'] = path
            with self.assertRaisesRegex(audit.AuditError, 'escapes'):
                audit.manifest_component(value)

    def test_manifest_digest_checked_before_parsing(self):
        for digest in (None, bytes(48), bytes(20)):
            with self.assertRaisesRegex(audit.AuditError, 'SHA384'):
                audit.decode_component({'Digest': digest}, b'corrupt')

    def test_signed_branch_decode(self):
        self.assertEqual(audit.direct_branch(0x94000002, 0x100),
                         {'kind': 'bl', 'target_offset': 0x108})
        self.assertEqual(audit.direct_branch(0x97fffffe, 0x100),
                         {'kind': 'bl', 'target_offset': 0xf8})
        self.assertEqual(audit.direct_branch(0x14000001, 0x100),
                         {'kind': 'b', 'target_offset': 0x104})
        for word in (0xd503201f, 0x54000000, 0xd63f0000):
            self.assertIsNone(audit.direct_branch(word, 0x100))

    def test_reference_registers_and_code_bounds(self):
        # ADRP x0, 0x1000; ADD x0, x0, #0x20; BL +4
        raw = struct.pack('<III', 0xb0000000, 0x91008000, 0x94000001)
        fake = mock.Mock()
        fake.adrp_target.return_value = 0x1000
        fake.add_imm.return_value = 0x20
        refs = audit.references(raw, len(raw), {0x1020}, fake)[0x1020]
        self.assertEqual(refs[0]['nearby_direct_branches'][0]['target_offset'], 12)
        mismatched = struct.pack('<II', 0xb0000000, 0x91008001)
        self.assertEqual(audit.references(mismatched, len(mismatched), {0x1020}, fake)[0x1020], [])
        self.assertEqual(audit.references(raw, 4, {0x1020}, fake)[0x1020], [])

if __name__ == '__main__':
    unittest.main()

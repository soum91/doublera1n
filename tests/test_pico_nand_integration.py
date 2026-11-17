import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'standalone/pico2'))
import integrate_pico as integration

class PicoIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.private = root / 'source', root / 'private'
        self.source.mkdir(); self.private.mkdir()
        self.original = b'/* fixture */\nint autoboot_boot(void) { return 0; }\n'
        (self.source / 'autoboot.c').write_bytes(self.original)
        (self.source / 'main.c').write_text('if (autoboot_boot() != 0) {}\n    led_set_state(LED_STATE_SUCCESS);\n\n    printf("\\nsuccess, spinning forever\\n");\n    spin_forever();')
        (self.source / 'CMakeLists.txt').write_text('add_executable(usbliter8 main.c autoboot.c)\n')
        image = bytes(2842448)
        report = {'board': 'd431ap', 'build': '24A446', 'candidate_sha256': hashlib.sha256(image).hexdigest(),
                  'candidate_crc32': zlib.crc32(image), 'ticket_ecid_hex': '000000000000007b'}
        (self.private / 'stage-map.json').write_text(json.dumps(report))
        (self.private / 'nand-first-stage.raw').write_bytes(image)
        (self.private / 'nand_device_config.h').write_text('#pragma once\n#include <stdint.h>\n#define DBNAND_EXPECTED_ECID UINT64_C(0x000000000000007b)\n')
        patch = mock.patch.object(integration, 'AUTOBOOT_SHA256', hashlib.sha256(self.original).hexdigest())
        patch.start(); self.addCleanup(patch.stop)

    def test_wires_real_entry_and_keeps_device_material_outside_source(self):
        result = integration.integrate(self.source, self.private)
        self.assertTrue(result['integrated']); self.assertFalse(result['firmware_built'])
        source = (self.source / 'autoboot.c').read_text()
        self.assertIn('int dbnand_legacy_single_image_boot(void)', source)
        self.assertIn('dbnand_pico_boot(IMAGE, HEADER->size, HEADER->crc32, DBNAND_EXPECTED_ECID)', source)
        self.assertFalse((self.source / 'nand_device_config.h').exists())
        self.assertIn('jailbreak startup remains unverified', (self.source / 'main.c').read_text())
        self.assertIn('extern int device_identify(uint16_t *cpid, bool *pwnd);', (self.source / 'main.c').read_text())
        self.assertNotIn('000000000000007b', '\n'.join(p.read_text() for p in self.source.iterdir()))
        self.assertIn('DBNAND_PRIVATE_EXPORT', (self.source / 'CMakeLists.txt').read_text())

    def test_rejects_mismatched_header_before_any_source_write(self):
        (self.private / 'nand_device_config.h').write_text('wrong')
        with self.assertRaises(integration.IntegrationError): integration.integrate(self.source, self.private)
        self.assertEqual((self.source / 'autoboot.c').read_bytes(), self.original)
        self.assertFalse((self.source / 'nand_transport.c').exists())

    def test_rejects_unreviewed_upstream_revision(self):
        (self.source / 'autoboot.c').write_bytes(self.original + b'changed')
        with self.assertRaisesRegex(integration.IntegrationError, 'unsupported'):
            integration.integrate(self.source, self.private)

    def test_rejects_private_inside_source_tree(self):
        private_inside = self.source / 'private_export'
        private_inside.mkdir()
        for name in ('stage-map.json', 'nand-first-stage.raw', 'nand_device_config.h'):
            (private_inside / name).write_bytes((self.private / name).read_bytes())
        with self.assertRaisesRegex(integration.IntegrationError, 'outside the firmware source'):
            integration.integrate(self.source, private_inside)
        # Source files must not be modified
        self.assertEqual((self.source / 'autoboot.c').read_bytes(), self.original)

    def test_rejects_existing_transport_files(self):
        (self.source / 'nand_transport.c').write_text('// existing')
        with self.assertRaisesRegex(integration.IntegrationError, 'refusing to overwrite'):
            integration.integrate(self.source, self.private)

    def test_rejects_mismatched_candidate_digest(self):
        report = json.loads((self.private / 'stage-map.json').read_text())
        report['candidate_sha256'] = 'deadbeef' * 8
        (self.private / 'stage-map.json').write_text(json.dumps(report))
        with self.assertRaisesRegex(integration.IntegrationError, 'digest mismatch'):
            integration.integrate(self.source, self.private)

    def test_rejects_zero_ecid(self):
        report = json.loads((self.private / 'stage-map.json').read_text())
        report['ticket_ecid_hex'] = '0000000000000000'
        (self.private / 'stage-map.json').write_text(json.dumps(report))
        with self.assertRaisesRegex(integration.IntegrationError, 'ECID'):
            integration.integrate(self.source, self.private)

    def test_cli_success(self):
        result = integration.main(['--source-root', str(self.source),
                                    '--private-export', str(self.private)])
        self.assertEqual(result, 0)

    def test_cli_error_returns_nonzero(self):
        result = integration.main(['--source-root', str(self.source / 'nonexistent'),
                                    '--private-export', str(self.private)])
        self.assertEqual(result, 1)


if __name__ == '__main__': unittest.main()

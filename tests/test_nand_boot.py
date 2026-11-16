"""Execute the generated ARM64 wrappers with mocked iBoot services.

Emulation covers emitted instructions and control flow, not actual APFS, image
verification, PAC hardware, cache coherency or a phone boot.
"""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'standalone/pico2'))
import nand_boot as boot
import iboot_audit as audit

try:
    import unicorn
    from unicorn import arm64_const as arm
except ImportError:
    unicorn = None


class ConfigResolutionTests(unittest.TestCase):
    def fixture(self, concrete=True, value=True):
        raw = bytearray(256)
        struct.pack_into('<Q', raw, 0, 0x1000 + 128)
        struct.pack_into('<II', raw, 128, 0x02008b00, 0x50000 if concrete else 0x10050000)
        raw[136] = value
        return raw

    def test_concrete_true_wins_over_fallback_false(self):
        raw = self.fixture()
        struct.pack_into('<Q', raw, 32, 0x1000 + 160)
        struct.pack_into('<II', raw, 160, 0x02008b00, 0x10050000)
        result = audit.resolve_boolean_config(raw, 0x1000, 0, 64, 0x02008b00)
        self.assertTrue(result['value'])
        self.assertEqual(result['winner_offset'], 128)

    def test_fallback_is_used_only_without_concrete(self):
        self.assertFalse(audit.resolve_boolean_config(self.fixture(False, False), 0x1000, 0, 32, 0x02008b00)['value'])

    def test_duplicate_concrete_or_dynamic_getter_rejected(self):
        raw = self.fixture()
        struct.pack_into('<Q', raw, 32, 0x1080)
        with self.assertRaises(audit.AuditError):
            audit.resolve_boolean_config(raw, 0x1000, 0, 64, 0x02008b00)
        struct.pack_into('<I', raw, 132, 0x02050000)
        with self.assertRaises(audit.AuditError):
            audit.resolve_boolean_config(raw, 0x1000, 0, 32, 0x02008b00)

    def test_out_of_bounds_or_missing_selector_rejected(self):
        raw = self.fixture()
        with self.assertRaises(audit.AuditError):
            audit.resolve_boolean_config(raw, 0x1000, 0, 32, 42)
        struct.pack_into('<Q', raw, 0, 0x9000)
        with self.assertRaises(audit.AuditError):
            audit.resolve_boolean_config(raw, 0x1000, 0, 32, 0x02008b00)


@unittest.skipIf(unicorn is None, 'install unicorn to run ARM64 execution tests')
class ARM64WrapperTests(unittest.TestCase):
    BASE = 0x19c050000
    STACK = 0x200000000
    RETURN = 0x900000

    def setUp(self):
        self.overrides = [(a[4], '/doublera1n-pico2/0123456789abcdef0123/' + a[3]) for a in boot.ASSETS]
        self.patcher = audit.patcher_module()
        self.code, self.layout = boot.build_wrapper(self.BASE, boot.MEMBOOT, boot.MEMBOOT_BYTES,
                                                    self.overrides, self.patcher)
        self.assertLessEqual(len(self.code), boot.MEMBOOT_BYTES)

    def execute(self, env_failure=None, guard=False, loaded_address=0x123000, loaded_size=96*1024*1024, loader_result=0):
        machine = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        machine.mem_map(self.BASE, 4*1024*1024)
        machine.mem_map(self.STACK, 0x4000)
        machine.mem_map(self.RETURN, 0x1000)
        machine.mem_write(self.BASE + boot.MEMBOOT, self.code)
        machine.reg_write(arm.UC_ARM64_REG_SP, self.STACK + 0x3000)
        machine.reg_write(arm.UC_ARM64_REG_X29, 0x778899)
        machine.reg_write(arm.UC_ARM64_REG_LR, self.RETURN)
        machine.mem_write(self.BASE + 0x1ea058, struct.pack('<Q', self.BASE + 0x300000))
        machine.mem_write(self.BASE + 0x1ea060, struct.pack('<Q', self.BASE + 0x300008))
        calls = []
        reached_fsboot = []
        def cstring(ptr):
            return bytes(machine.mem_read(ptr, 128)).split(b'\0', 1)[0].decode()
        def hook(m, address, size, _data):
            if address == self.RETURN:
                m.emu_stop(); return
            if address == self.BASE + boot.SETENV:
                key, value = cstring(m.reg_read(arm.UC_ARM64_REG_X0)), cstring(m.reg_read(arm.UC_ARM64_REG_X4))
                regs = [m.reg_read(getattr(arm, 'UC_ARM64_REG_X' + str(i))) for i in range(8)]
                self.assertEqual(regs[0], regs[1]); self.assertEqual(regs[2], regs[0] + len(key) + 1)
                self.assertEqual(regs[4], regs[5]); self.assertEqual(regs[6], regs[4] + len(value) + 1)
                self.assertEqual(regs[3], self.BASE + boot.CHAR_DESCRIPTOR); self.assertEqual(regs[3], regs[7])
                self.assertEqual(bytes(m.mem_read(m.reg_read(arm.UC_ARM64_REG_SP), 4)), bytes(4))
                calls.append((key, value))
                m.reg_write(arm.UC_ARM64_REG_X0, 1 if len(calls) - 1 == env_failure else 0)
                m.reg_write(arm.UC_ARM64_REG_PC, m.reg_read(arm.UC_ARM64_REG_LR)); return
            if address == self.BASE + 0xc1a2c:
                m.mem_write(self.BASE + 0x300000, struct.pack('<QQ', loaded_address, loaded_size))
                m.reg_write(arm.UC_ARM64_REG_X0, loader_result)
                m.reg_write(arm.UC_ARM64_REG_PC, m.reg_read(arm.UC_ARM64_REG_LR)); return
            if address == self.BASE + boot.FSBOOT:
                reached_fsboot.append(True); m.emu_stop(); return
            word = struct.unpack('<I', bytes(m.mem_read(address, 4)))[0]
            # PAC is a hardware verification gate, explicitly outside this test.
            if word in (0xd503237f, 0xd50323ff):
                m.reg_write(arm.UC_ARM64_REG_PC, address + 4)
            elif word == 0xd65f0fff:
                m.reg_write(arm.UC_ARM64_REG_PC, m.reg_read(arm.UC_ARM64_REG_LR))
        machine.hook_add(unicorn.UC_HOOK_CODE, hook)
        entry = self.layout['ramdisk_guard_offset'] if guard else boot.MEMBOOT
        machine.emu_start(self.BASE + entry, self.RETURN + 4, count=2000)
        self.assertEqual(machine.reg_read(arm.UC_ARM64_REG_SP), self.STACK + 0x3000)
        self.assertEqual(machine.reg_read(arm.UC_ARM64_REG_X29), 0x778899)
        return calls, bool(reached_fsboot), machine.reg_read(arm.UC_ARM64_REG_X0) & 0xffffffff

    def test_all_overrides_precede_fsboot(self):
        calls, fsboot, _ = self.execute()
        self.assertEqual(calls, self.overrides); self.assertTrue(fsboot)

    def test_every_failed_setter_stops_before_fsboot(self):
        for failure in range(5):
            with self.subTest(failure=failure):
                calls, fsboot, result = self.execute(env_failure=failure)
                self.assertEqual(len(calls), failure + 1); self.assertFalse(fsboot)
                self.assertEqual(result, 0xffffffff)

    def test_ramdisk_guard_checks_address_and_size_even_after_false_success(self):
        for address, size, result in ((0, 100, 0), (100, 0, 0), (0, 0, 0), (100, 100, 1)):
            with self.subTest(address=address, size=size, result=result):
                _, _, returned = self.execute(guard=True, loaded_address=address, loaded_size=size, loader_result=result)
                self.assertEqual(returned, 0xffffffff)

    def test_ramdisk_guard_accepts_a_loaded_ramdisk(self):
        _, _, result = self.execute(guard=True)
        self.assertEqual(result, 0)

    def test_rejects_overlong_path_or_changed_key_order(self):
        for overrides in (self.overrides[::-1], [(k, '/doublera1n-pico2/' + 'x'*110) for k, _ in self.overrides]):
            with self.assertRaises(boot.BootError):
                boot.build_wrapper(self.BASE, boot.MEMBOOT, boot.MEMBOOT_BYTES, overrides, self.patcher)


class ExportValidationTests(unittest.TestCase):
    def fixture(self, root):
        from pyimg4 import IM4M, IMG4, IM4P, ManifestProperty, ManifestImageProperties
        ws = root / 'workspace'; (ws / 'out').mkdir(parents=True); (ws / 'build/osbjb').mkdir(parents=True)
        import json
        (ws / 'state.json').write_text(json.dumps({'board': boot.BOARD, 'build': boot.BUILD, 'installed': True}))
        ticket = IM4M()
        for key, value in [('ECID', 123), ('CHIP', 0x8030), ('BORD', 2)]:
            ticket.add_property(ManifestProperty(fourcc=key, value=value))
        properties = ManifestImageProperties(fourcc='krnl')
        properties.add_property(ManifestProperty(fourcc='DGST', value=b'synthetic-test-digest'))
        ticket.add_image_properties(properties); ticket._signature = b'test'; ticket._certificates = b''
        (ws / 'out/apticket.installed.der').write_bytes(ticket.output())
        for filename, fcc, _, _, _ in boot.ASSETS:
            (ws / 'build/osbjb' / filename).write_bytes(IMG4(im4p=IM4P(fourcc=fcc, payload=b'test-payload'), im4m=ticket).output())
        return ws

    def test_private_export_preserves_payload_and_ticket_and_never_modifies_source(self):
        from pyimg4 import IMG4
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.fixture(root); raw = root / 'stock'; raw.write_bytes(b'fixture')
            snapshots = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file()}
            with mock.patch.object(boot, 'verify_patched_assets') as verify, mock.patch.object(
                    boot, 'prepare_candidate', return_value=(b'candidate', {'status': 'DEVICE_UNTESTED_NAND_BOOT_CANDIDATE'})):
                report = boot.export_workspace(ws, raw, root / 'output')
            verify.assert_called_once(); self.assertFalse(report['phone_modified'])
            plan = json.loads((root / 'output/stage-map.json').read_text())
            self.assertEqual(len(plan['files']), 5); self.assertTrue(plan['requires_separate_staging_review'])
            self.assertEqual(len(plan['selected_manifest_hash']), 96)
            self.assertEqual(plan['selected_manifest_hash'], plan['selected_manifest_hash'].upper())
            self.assertIn('/' + plan['selected_manifest_hash'] + '/', plan['ios_staging_directory'])
            for filename, _source, target, name, _key in boot.ASSETS:
                old = IMG4(snapshots[ws / 'build/osbjb' / filename]); new = IMG4((root / 'output/preboot-files' / name).read_bytes())
                self.assertEqual(new.im4p.fourcc, target)
                self.assertEqual(old.im4p.payload.output().data, new.im4p.payload.output().data)
                self.assertEqual(old.im4m.output(), new.im4m.output())
            for path, before in snapshots.items(): self.assertEqual(path.read_bytes(), before)

    def test_wrong_source_tag_stops_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ws = self.fixture(root); raw = root / 'stock'; raw.write_bytes(b'fixture')
            path = ws / 'build/osbjb/Kernelcache.img4'
            path.write_bytes(path.read_bytes().replace(b'rkrn', b'krnl', 1))
            with self.assertRaisesRegex(boot.BootError, 'type or installed ticket mismatch'):
                boot.export_workspace(ws, raw, root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_existing_output_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'output').mkdir()
            with self.assertRaisesRegex(boot.BootError, 'new private directory'):
                boot.export_workspace(root / 'ws', root / 'raw', root / 'output')

if __name__ == '__main__':
    unittest.main()

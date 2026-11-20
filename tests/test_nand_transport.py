import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
class Identity(C.Structure):
    _fields_ = [('vendor', C.c_uint16), ('product', C.c_uint16), ('cpid', C.c_uint16),
                ('bdid', C.c_uint16), ('ecid', C.c_uint64), ('pwned', C.c_int)]
ID = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(Identity))
ENUM = C.CFUNCTYPE(C.c_int, C.c_void_p)
CTL = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint8, C.c_uint8, C.POINTER(C.c_uint8), C.c_uint16, C.c_uint32)
WAIT = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32)
class IO(C.Structure):
    _fields_ = [('ctx', C.c_void_p), ('identity', ID), ('enumerate', ENUM), ('control', CTL), ('wait', WAIT)]
READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_size_t, C.POINTER(C.c_uint8), C.c_size_t)
class Source(C.Structure):
    _fields_ = [('ctx', C.c_void_p), ('read', READ)]

class NANDTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        so = Path(cls.tmp.name) / 'transport.so'
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        str(ROOT / 'standalone/pico2/nand_transport.c'), '-o', str(so)], check=True)
        cls.lib = C.CDLL(str(so))
        cls.lib.dbnand_run.argtypes = [C.POINTER(IO), C.POINTER(C.c_uint8), C.c_size_t, C.c_uint32, C.c_uint64]
        cls.lib.dbnand_run.restype = C.c_int
        cls.lib.dbnand_run_source.argtypes = [C.POINTER(IO), C.POINTER(Source), C.c_size_t, C.c_uint32, C.c_uint64]
        cls.lib.dbnand_run_source.restype = C.c_int
        cls.lib.dbnand_crc32.argtypes = [C.POINTER(C.c_uint8), C.c_size_t]
        cls.lib.dbnand_crc32.restype = C.c_uint32
        cls.lib.dbnand_parse_serial.argtypes = [C.c_char_p, C.c_size_t, C.POINTER(Identity)]
        cls.image = (C.c_uint8 * 2842448)()
        cls.crc = cls.lib.dbnand_crc32(cls.image, len(cls.image))

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def run_transport(self, fail=None, initial=None, swapped=False, corrupt=False, source_mode=None):
        events = []; phase = [False]; chunks = [0]
        @ID
        def identity(_ctx, out):
            events.append('identity')
            obj = Identity(0x5ac, 0x1281 if phase[0] else 0x1227, 0x8030, 2,
                           456 if swapped and phase[0] else 123, 0 if phase[0] else 1)
            if initial and not phase[0]: setattr(obj, initial[0], initial[1])
            out[0] = obj
            return 0
        @ENUM
        def enumerate_(_ctx):
            events.append('enumerate')
            return -1 if fail == 'enumerate' else 0
        @CTL
        def control(_ctx, kind, request, data, size, timeout):
            if kind == 0x21 and request == 1 and size:
                chunks[0] += 1
                if chunks[0] == 1: events.append('chunks')
                if size > 192: events.append('oversized')
                return -1 if fail == 'chunk' and chunks[0] == 2 else 0
            events.append((kind, request, size, C.string_at(data, size) if size else b''))
            if request == 8 and fail == 'customboot': return -1
            if request == 4: return -1  # permitted disconnect after CUSTOM_BOOT
            if kind == 0x40 and fail == 'command': return -1
            return 0
        @WAIT
        def wait(_ctx, timeout):
            events.append(('wait', timeout)); phase[0] = True
            return -1 if fail == 'wait' else 0
        io = IO(None, identity, enumerate_, control, wait)
        if source_mode:
            passes = [0]
            @READ
            def read(_ctx, offset, dest, size):
                if offset == 0: passes[0] += 1
                if size > 192 or offset + size > len(self.image): return -1
                if source_mode == 'fail-preflight' and offset >= 192: return -1
                if source_mode == 'fail-upload' and passes[0] == 2 and offset >= 192: return -1
                C.memmove(dest, C.byref(self.image, offset), size)
                if source_mode == 'mutate-upload' and passes[0] == 2 and offset == 0:
                    dest[0] ^= 1
                return 0
            source = Source(None, read)
            result = self.lib.dbnand_run_source(C.byref(io), C.byref(source), len(self.image), self.crc ^ int(corrupt), 123)
        else:
            result = self.lib.dbnand_run(C.byref(io), self.image, len(self.image), self.crc ^ int(corrupt), 123)
        return result, events, chunks[0]

    def test_stream_source_matches_memory_transport(self):
        self.assertEqual(self.run_transport(source_mode='valid'), self.run_transport())

    def test_stream_preflight_failures_do_not_touch_usb(self):
        for mode, corrupt in [('fail-preflight', False), ('valid', True)]:
            result, events, chunks = self.run_transport(source_mode=mode, corrupt=corrupt)
            self.assertEqual((result, events, chunks), (-1, [], 0))

    def test_stream_upload_failure_or_change_never_triggers_boot(self):
        for mode in ['fail-upload', 'mutate-upload']:
            result, events, chunks = self.run_transport(source_mode=mode)
            self.assertEqual(result, -1)
            self.assertGreater(chunks, 0)
            self.assertNotIn((0x21, 8, 0, b''), events)
            self.assertFalse(any(isinstance(e, tuple) and e[0] == 0x40 for e in events))

    def test_ep0_only_sequence_and_identity_on_both_sides(self):
        result, events, chunks = self.run_transport()
        self.assertEqual(result, 1)
        self.assertEqual(chunks, (len(self.image) + 191)//192)
        self.assertEqual(events, ['identity', 'enumerate', 'chunks', (0x21, 1, 0, b''),
                                 (0x21, 8, 0, b''), (0x21, 4, 0, b''), ('wait', 90000),
                                 'identity', 'enumerate', (0x40, 0, 8, b'memboot\0')])

    def test_corrupt_image_stops_before_any_usb_action(self):
        result, events, _ = self.run_transport(corrupt=True)
        self.assertEqual(result, -1); self.assertEqual(events, [])

    def test_wrong_phone_or_unpwned_dfu_stops_before_transfer(self):
        for field, value in [('vendor', 1), ('product', 0x1281), ('cpid', 0x8020), ('bdid', 6), ('ecid', 999), ('pwned', 0)]:
            with self.subTest(field=field):
                result, events, chunks = self.run_transport(initial=(field, value))
                self.assertEqual(result, -2); self.assertEqual(events, ['identity']); self.assertEqual(chunks, 0)

    def test_failure_phases_do_not_emit_memboot(self):
        for failure, expected in [('enumerate', -3), ('chunk', -4), ('customboot', -4), ('wait', -5)]:
            with self.subTest(failure=failure):
                result, events, _ = self.run_transport(fail=failure)
                self.assertEqual(result, expected)
                self.assertFalse(any(isinstance(x, tuple) and x[0] == 0x40 for x in events))

    def test_device_swap_in_recovery_stops_before_command(self):
        result, events, _ = self.run_transport(swapped=True)
        self.assertEqual(result, -2)
        self.assertFalse(any(isinstance(x, tuple) and x[0] == 0x40 for x in events))

    def test_command_rejection_is_not_handoff_success(self):
        result, _, _ = self.run_transport(fail='command')
        self.assertEqual(result, -6)

    def test_serial_parser_rejects_truncation_missing_and_overflow(self):
        good = b'CPID:8030 BDID:02 ECID:000000000000007B PWND:[usbliter8]\0'
        ident = Identity()
        self.assertEqual(self.lib.dbnand_parse_serial(good, len(good), C.byref(ident)), 0)
        self.assertEqual((ident.cpid, ident.bdid, ident.ecid, ident.pwned), (0x8030, 2, 123, 1))
        for bad in [good[:-1], b'CPID:8030 ECID:1\0', good.replace(b'BDID:02', b'BDID:10002'),
                    good.replace(b'007B', b'00ZZ'), good.replace(b'ECID:000000000000007B', b'ECID:10000000000000000')]:
            self.assertEqual(self.lib.dbnand_parse_serial(bad, len(bad), C.byref(ident)), -1)


class PicoAdapterCompileTests(unittest.TestCase):
    def test_adapter_matches_upstream_bus_api_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); (path / 'pico').mkdir()
            (path / 'pico/stdlib.h').write_text('#include <stdint.h>\nvoid sleep_ms(uint32_t);\n')
            (path / 'bus.h').write_text('''#pragma once
#include <stdint.h>
#include <stdbool.h>
typedef struct { uint8_t address; } usb_device_t;
typedef struct { void *pp; void *root; usb_device_t *dev; uint8_t maxpacket0; } bus_t;
int bus_control_xfer(bus_t *, const uint8_t[8], uint8_t *, uint16_t, bool, uint32_t);
void bus_close_all(bus_t *);
void bus_reset_ep0_reopen(bus_t *);
bool bus_open_ep0(bus_t *, uint8_t);
''')
            (path / 'usb.h').write_text('''#pragma once
#include "bus.h"
typedef int (*usb_executee_t)(bus_t *, void *);
int usb_bus_execute(usb_executee_t, void *, uint64_t);
int usb_bus_reset_open_ep0(void);
''')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-I', str(path), '-c', str(ROOT / 'standalone/pico2/nand_usbliter8_adapter.c'),
                            '-o', str(path / 'adapter.o')], check=True)

if __name__ == '__main__': unittest.main()

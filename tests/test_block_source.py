import ctypes as C
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from standalone.pico2.compression_audit import pack_blocks, BLOCK
from test_nand_transport import IO, Source, READ, ID, ENUM, CTL, WAIT, Identity

ROOT = Path(__file__).resolve().parents[1]


class BlockSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        path = Path(cls.temp.name)
        (path / 'size.c').write_text('#include "block_source.h"\nsize_t state_size(void) { return sizeof(struct dbnand_block_source); }\n')
        src = ROOT / 'standalone/pico2'
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(src), str(path/'size.c'), str(src/'block_source.c'),
                        str(src/'block_inflate.c'), str(src/'nand_transport.c'), '-o', str(path/'blocks.so')], check=True)
        cls.lib = C.CDLL(str(path/'blocks.so'))
        cls.lib.state_size.restype = C.c_size_t
        cls.lib.dbnand_block_init.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
        cls.lib.dbnand_block_read.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t]
        cls.lib.dbnand_run_source.argtypes = [C.POINTER(IO), C.POINTER(Source), C.c_size_t, C.c_uint32, C.c_uint64]

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    @classmethod
    def decode(cls, raw):
        packed = pack_blocks(raw)
        data = C.create_string_buffer(packed)
        state = C.create_string_buffer(cls.lib.state_size())
        assert cls.lib.dbnand_block_init(state, data, len(packed)) == 0
        for _ in range(2):
            output = bytearray()
            for offset in range(0, len(raw), 192):
                n = min(192, len(raw)-offset); dest = C.create_string_buffer(n)
                assert cls.lib.dbnand_block_read(state, offset, dest, n) == 0
                output.extend(dest.raw)
            assert output == raw
        return len(state)

    def test_two_pass_exact_output_at_usb_and_compression_boundaries(self):
        for raw in [b'A', b'ABC123'*(BLOCK//2), os.urandom(BLOCK*2+99)]:
            self.assertLess(self.decode(raw), 64*1024)

    @classmethod
    def upload(cls, raw, corrupt=False):
        import zlib
        packed = bytearray(pack_blocks(raw))
        if corrupt: packed[-1] ^= 1
        data = C.create_string_buffer(bytes(packed))
        state = C.create_string_buffer(cls.lib.state_size())
        assert cls.lib.dbnand_block_init(state, data, len(packed)) == 0
        phase = [False]; events = []; digest = hashlib.sha256()
        @ID
        def identity(ctx, out):
            events.append('identity')
            out[0] = Identity(0x5ac, 0x1281 if phase[0] else 0x1227, 0x8030, 2, 123, not phase[0])
            return 0
        @ENUM
        def enumerate_(ctx): return 0
        @CTL
        def control(ctx, kind, request, ptr, size, timeout):
            if kind == 0x21 and request == 1 and size:
                digest.update(C.string_at(ptr, size))
            else: events.append((kind, request))
            return 0
        @WAIT
        def wait(ctx, timeout): phase[0] = True; return 0
        source = Source(C.cast(state, C.c_void_p), READ(('dbnand_block_read', cls.lib)))
        io = IO(None, identity, enumerate_, control, wait)
        result = cls.lib.dbnand_run_source(C.byref(io), C.byref(source), len(raw), zlib.crc32(raw), 123)
        if corrupt:
            assert result == -1 and events == []
        else:
            assert result == 1 and digest.digest() == hashlib.sha256(raw).digest()
            assert events[-1] == (0x40, 0)

    def test_decoder_through_complete_mock_usb_transfer(self):
        raw = (b'0123456789ABCDEF' * 177653)[:2842448]
        self.upload(raw)
        self.upload(raw, corrupt=True)

    def test_bad_block_rejected_before_any_decoded_bytes_return(self):
        packed = bytearray(pack_blocks(b'A' * (BLOCK+17)))
        packed[32+8] ^= 1  # corrupt first block's CRC
        data = C.create_string_buffer(bytes(packed)); state = C.create_string_buffer(self.lib.state_size())
        self.assertEqual(self.lib.dbnand_block_init(state, data, len(packed)), 0)
        dest = C.create_string_buffer(192)
        self.assertEqual(self.lib.dbnand_block_read(state, 0, dest, 192), -1)

    def test_invalid_framing_and_out_of_order_reads_rejected(self):
        packed = pack_blocks(b'A'*1000)
        for bad in [packed[:-1], packed+b'x', b'bad']:
            data = C.create_string_buffer(bad); state = C.create_string_buffer(self.lib.state_size())
            self.assertEqual(self.lib.dbnand_block_init(state, data, len(bad)), -1)
        data = C.create_string_buffer(packed); state = C.create_string_buffer(self.lib.state_size())
        self.assertEqual(self.lib.dbnand_block_init(state, data, len(packed)), 0)
        dest = C.create_string_buffer(192)
        self.assertEqual(self.lib.dbnand_block_read(state, 192, dest, 192), -1)
        self.assertEqual(self.lib.dbnand_block_read(state, 0, dest, 192), 0)
        self.assertEqual(self.lib.dbnand_block_read(state, 1001, dest, 1), -1)


if __name__ == '__main__': unittest.main()

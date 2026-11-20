import os
from pathlib import Path
import struct
import tempfile
import unittest

from standalone.pico2 import compression_audit as audit
from test_pico_board_preflight import uf2_block


class CompressionAuditTests(unittest.TestCase):
    def test_round_trip_across_block_boundaries_and_raw_fallback(self):
        for raw in [b'x', b'A' * (audit.BLOCK + 17), os.urandom(audit.BLOCK + 17)]:
            packed = audit.pack_blocks(raw)
            chunks = list(audit.unpack_blocks(packed))
            self.assertEqual(b''.join(chunks), raw)
            self.assertLessEqual(max(map(len, chunks)), audit.BLOCK)

    def test_corrupt_truncated_trailing_and_invalid_header_rejected(self):
        packed = audit.pack_blocks(b'A' * (audit.BLOCK + 17))
        corrupt = bytearray(packed); corrupt[-1] ^= 1
        bad_crc = bytearray(packed); bad_crc[24] ^= 1
        bad_version = bytearray(packed); bad_version[8] = 9
        oversized = bytearray(packed)
        struct.pack_into('<I', oversized, audit.HEADER.size + 4, audit.BLOCK + 1)
        for bad in [b'', packed[:31], packed[:-1], packed + b'x', corrupt, bad_crc, bad_version, oversized]:
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                list(audit.unpack_blocks(bad))

    def test_embedded_inflate_bomb_is_bounded(self):
        import zlib
        payload = zlib.compress(b'A' * (audit.BLOCK * 100))
        packed = audit.HEADER.pack(audit.MAGIC, 1, 1, audit.BLOCK, 1, 0, 0)
        packed += audit.RECORD.pack(len(payload), 1, 0) + payload
        with self.assertRaises(ValueError): list(audit.unpack_blocks(packed))

    def test_extract_checks_original_crc_and_missing_blocks(self):
        import zlib
        raw = b'A' * audit.STAGE_BYTES
        header = b'L8BOOT01' + struct.pack('<II', len(raw), zlib.crc32(raw))
        chunks = [header.ljust(256, b'\0')] + [raw[i:i+256].ljust(256, b'\0') for i in range(0, len(raw), 256)]
        data = bytearray()
        for i, chunk in enumerate(chunks):
            block = uf2_block(0x10100000 + i * 256, i, len(chunks))
            block[32:288] = chunk; data.extend(block)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.uf2'; path.write_bytes(data)
            self.assertEqual(audit.extract_stage(path), raw)
            data[-512+32] ^= 1; path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'CRC'): audit.extract_stage(path)


if __name__ == '__main__': unittest.main()

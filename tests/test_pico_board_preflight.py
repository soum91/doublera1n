import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "standalone/pico2/verify_uf2_for_board.py"
spec = importlib.util.spec_from_file_location("verify_uf2_for_board", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def uf2_block(addr, index, total, family=0xe48bff59):
    b = bytearray(512)
    struct.pack_into("<8I", b, 0, module.UF2_MAGIC0, module.UF2_MAGIC1,
                     module.FAMILY_ID_PRESENT, addr, 256, index, total, family)
    struct.pack_into("<I", b, 508, module.UF2_END)
    return b


class BoardPreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "candidate.uf2"

    def test_oversized_for_rp2354a_but_fits_genuine_pico2(self):
        self.file.write_bytes(uf2_block(0x10000000, 0, 2) +
                              uf2_block(0x103b5f00, 1, 2))
        self.assertEqual(module.main(["--board", "rp2354a", "--uf2", str(self.file)]), 2)
        self.assertEqual(module.main(["--board", "pico2", "--uf2", str(self.file)]), 0)

    def test_duplicate_block_rejected(self):
        self.file.write_bytes(uf2_block(0x10000000, 0, 2) +
                              uf2_block(0x10000000, 1, 2))
        with self.assertRaisesRegex(module.PreflightError, "duplicate"):
            module.inspect_uf2(self.file)

    def test_missing_block_number_rejected(self):
        self.file.write_bytes(uf2_block(0x10000000, 0, 2) +
                              uf2_block(0x10000100, 0, 2))
        with self.assertRaisesRegex(module.PreflightError, "missing or duplicate"):
            module.inspect_uf2(self.file)

    def test_wrong_size_or_magic_rejected(self):
        self.file.write_bytes(b"wrong")
        self.assertEqual(module.main(["--board", "pico2", "--uf2", str(self.file)]), 1)

    def test_single_workaround_block_supported(self):
        self.file.write_bytes(uf2_block(0x10000000, 0, 3) +
                              uf2_block(0x10000100, 1, 3) +
                              uf2_block(0x10000000, 2, 3, family=0x12345678))
        result = module.inspect_uf2(self.file)
        self.assertEqual(result["auxiliary_blocks"], 1)
        self.assertEqual(result["flash_extent_bytes"], 512)

    def test_unknown_target_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            module.main(["--board", "rp2350", "--uf2", str(self.file)])


if __name__ == "__main__":
    unittest.main()

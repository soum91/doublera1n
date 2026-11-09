"""Device-identity checks, no DFU/device access."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from common import A13_BOARDS, BOARD_PRODUCTS, board_of, find_profile  # noqa: E402

spec = importlib.util.spec_from_file_location("check_11pm", ROOT / "scripts" / "check_11pm.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class IPhone11ProMaxTests(unittest.TestCase):
    def test_pro_max_has_its_own_board_and_product(self):
        self.assertEqual(A13_BOARDS[0x02], "d431ap")
        self.assertEqual(BOARD_PRODUCTS["d431ap"], "iPhone12,5")
        self.assertEqual(board_of({"CPID": "0x8030", "BDID": "0x02"}), "d431ap")
        self.assertEqual(board_of({"CPID": "0x8030", "BDID": "0x06"}), "d421ap")
        self.assertIsNone(board_of({"CPID": "0x8015", "BDID": "0x02"}))

    def test_no_fallback_to_11_pro_firmware(self):
        profile = find_profile("d431ap", "24A446")
        if profile is not None:
            self.assertEqual(profile["board"], "d431ap")
            self.assertEqual(profile["product_types"], ["iPhone12,5"])
        self.assertNotEqual(profile, find_profile("d421ap", "24A446"))

    def test_missing_manifest_rejects_11_pro_firmware_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env.update(OSB_BOARD="d431ap", OSB_IPSW=directory)
            proc = subprocess.run(
                [sys.executable, "-c", "from osbcfg import comp; print(comp('iBSS'))"],
                env={**env, "PYTHONPATH": str(ROOT / "lib")}, capture_output=True, text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("cannot use 11 Pro firmware path defaults", proc.stderr)

    def test_manifest_selects_pro_max_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {
                "BuildIdentities": [
                    {"Info": {"DeviceClass": "d421ap", "RestoreBehavior": "Erase"},
                     "Manifest": {"iBSS": {"Info": {"Path": "Firmware/dfu/iBSS.d421.RELEASE.im4p"}}}},
                    {"Info": {"DeviceClass": "d431ap", "RestoreBehavior": "Erase"},
                     "Manifest": {"iBSS": {"Info": {"Path": "Firmware/dfu/iBSS.d431.RELEASE.im4p"}}}},
                ]
            }
            (Path(directory) / "BuildManifest.plist").write_bytes(plistlib.dumps(manifest))
            env = os.environ.copy()
            env.update(OSB_BOARD="d431ap", OSB_IPSW=directory)
            proc = subprocess.run(
                [sys.executable, "-c", "from osbcfg import comp; print(comp('iBSS'))"],
                env={**env, "PYTHONPATH": str(ROOT / "lib")}, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "Firmware/dfu/iBSS.d431.RELEASE.im4p")

    def test_existing_272_profile_is_consistent(self):
        errors, notices = checker.inspect_profile("24B119")
        self.assertEqual(errors, [], "\n".join(errors))
        self.assertTrue(any("not device-tested" in note.lower() for note in notices))

    def test_wrong_board_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "profiles" / "d431ap-24A446"
            folder.mkdir(parents=True)
            (folder / "profile.json").write_text(json.dumps({
                "board": "d421ap", "build": "24A446", "cpid": "0x8030",
                "bdid": "0x06", "product_types": ["iPhone12,3"],
                "precheck": {"ok": True},
            }))
            errors, _ = checker.inspect_profile("24A446", directory)
            self.assertTrue(any("board:" in error for error in errors))
            self.assertTrue(any("bdid:" in error for error in errors))
            self.assertTrue(any("product_types" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

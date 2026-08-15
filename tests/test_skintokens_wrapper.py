import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "scripts"))

from run_skintokens_offline import build_cli_args, validate_transfer_input_glb


class SkinTokensWrapperTests(unittest.TestCase):
    def write_glb(self, directory, skin_name="Armature", joint_count=22):
        payload = json.dumps(
            {
                "asset": {"version": "2.0"},
                "skins": [{"name": skin_name, "joints": list(range(joint_count))}],
            }
        )
        encoded = payload.encode("utf-8")
        encoded += b" " * ((4 - len(encoded) % 4) % 4)
        length = 12 + 8 + len(encoded)
        data = struct.pack("<III", 0x46546C67, 2, length)
        data += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
        path = Path(directory) / "input.glb"
        path.write_bytes(data)
        return path

    def test_fixed_skeleton_flags_are_forwarded(self):
        args = SimpleNamespace(
            input="input.glb", output="output.glb", use_skeleton=True,
            use_transfer=True, use_postprocess=False,
        )
        result = build_cli_args(args, SimpleNamespace(MODEL_CKPTS=["checkpoint.ckpt"]))
        self.assertTrue(result.use_skeleton)
        self.assertTrue(result.use_transfer)

    def test_transfer_preflight_enforces_name_and_joint_count(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual("Armature", validate_transfer_input_glb(self.write_glb(directory)))
            with self.assertRaisesRegex(RuntimeError, "22 joints"):
                validate_transfer_input_glb(self.write_glb(directory, joint_count=21))
            with self.assertRaisesRegex(RuntimeError, "requires 'Armature'"):
                validate_transfer_input_glb(self.write_glb(directory, skin_name="CharacterRig"))


if __name__ == "__main__":
    unittest.main()

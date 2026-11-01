"""Offline candidate identity gate tests; never accesses a device."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("touch_gate", HERE / "check_touch_candidate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class IdentityTest(unittest.TestCase):
    def test_pinned_image_manifest_and_negative_controls(self):
        with tempfile.TemporaryDirectory(prefix="touch-gate-", dir=HERE) as tmp:
            root = Path(tmp)
            image = b"test image"
            manifest = json.dumps({"schema": "lgg8-boot-image-v1", "device_acceptance": "NOT_TESTED",
                                   "partition_size": 100, "components": {"image": {
                                       "sha256": digest(image), "size": len(image)}}}).encode()
            (root / "boot.img").write_bytes(image)
            (root / "manifest.json").write_bytes(manifest)
            with patch.object(gate, "IMAGE_SHA", digest(image)), patch.object(gate, "MANIFEST_SHA", digest(manifest)):
                self.assertFalse(gate.check(root)["boot_authorized"])
                (root / "boot.img").write_bytes(b"test imagf")
                with self.assertRaisesRegex(ValueError, "image identity"):
                    gate.check(root)
                (root / "boot.img").write_bytes(image)
                (root / "manifest.json").write_bytes(manifest + b" ")
                with self.assertRaisesRegex(ValueError, "manifest hash"):
                    gate.check(root)
                (root / "boot.img").unlink()
                (root / "manifest.json").write_bytes(manifest)
                with self.assertRaises(FileNotFoundError):
                    gate.check(root)


if __name__ == "__main__":
    unittest.main()

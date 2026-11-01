#!/usr/bin/env python3
"""Read-only identity gate for one diagnostic image; NOT authorization to boot."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "out/lgg8-touch-candidate-20261101/boot"
IMAGE_SHA = "d9ef349136a2440287757f1121e351bead48d545898f7a45fb9a655b78bf3431"
MANIFEST_SHA = "da7678d150300258a20ae85ddee276eb69d4dc1aca7be87f46b58c3109fe5744"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(candidate=CANDIDATE):
    image = candidate / "boot.img"
    manifest = candidate / "manifest.json"
    if sha256(manifest) != MANIFEST_SHA:
        raise ValueError("candidate manifest hash mismatch")
    data = json.loads(manifest.read_bytes())
    if (data.get("schema") != "lgg8-boot-image-v1" or
            data.get("device_acceptance") != "NOT_TESTED" or
            data["components"]["image"] != {"sha256": IMAGE_SHA, "size": image.stat().st_size} or
            image.stat().st_size > data["partition_size"] or sha256(image) != IMAGE_SHA):
        raise ValueError("candidate image identity mismatch")
    return {"status": "IDENTITY_MATCH", "image_sha256": IMAGE_SHA,
            "device_acceptance": "NOT_TESTED", "boot_authorized": False}


if __name__ == "__main__":
    print(json.dumps(check(), sort_keys=True))

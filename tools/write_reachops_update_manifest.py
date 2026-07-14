# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.security_signing import sign_payload
from ReachOps.version import BUILD_CHANNEL, PRODUCT_ID, PRODUCT_NAME, VERSION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    installer: Path,
    version: str,
    build: str,
    channel: str,
    download_url: str = "",
    signing_key_id: str = "",
    signing_key: str = "",
) -> dict:
    installer = installer.resolve()
    if not installer.exists():
        raise FileNotFoundError(str(installer))
    manifest = {
        "product_id": PRODUCT_ID,
        "product_name": PRODUCT_NAME,
        "version": version,
        "build": str(build),
        "channel": channel,
        "platform": "windows",
        "arch": "x64compatible",
        "installer": {
            "file_name": installer.name,
            "path": str(installer),
            "download_url": download_url,
            "size_bytes": installer.stat().st_size,
            "sha256": sha256_file(installer),
        },
        "runtime_policy": {
            "preserve_config": True,
            "preserve_data": True,
            "preserve_activation_status": True,
        },
        "rollback_policy": {
            "allow_downgrade": False,
            "minimum_version": "0.0.0",
        },
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    if signing_key_id and signing_key:
        manifest = sign_payload(manifest, signing_key_id, signing_key, signature_field="manifest_signature")
    return manifest


def parse_args():
    parser = argparse.ArgumentParser(description="Write ReachOps Windows update manifest.")
    parser.add_argument("--installer", required=True, help="Path to ReachOps installer exe.")
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--build", default="0")
    parser.add_argument("--channel", default=BUILD_CHANNEL)
    parser.add_argument("--download-url", default="")
    parser.add_argument("--signing-key-id", default="")
    parser.add_argument("--signing-key", default="")
    parser.add_argument("--output", default="", help="Defaults to dist/installer/reachops-update-manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installer = Path(args.installer)
    output = Path(args.output) if args.output else ROOT_DIR / "dist" / "installer" / "reachops-update-manifest.json"
    manifest = build_manifest(
        installer,
        args.version,
        args.build,
        args.channel,
        args.download_url,
        signing_key_id=args.signing_key_id,
        signing_key=args.signing_key,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

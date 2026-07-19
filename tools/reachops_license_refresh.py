# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.license_client import ReachOpsLicenseClient
from ReachOps.runtime_paths import RuntimePaths


def _redact_license_key(payload: dict) -> dict:
    result = dict(payload)
    if result.get("license_key"):
        result["license_key"] = "***redacted***"
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh ReachOps local activation status from a configured license endpoint.")
    raw_args = list(argv if argv is not None else sys.argv[1:])
    if "--license-key" in raw_args or any(arg.startswith("--license-key=") for arg in raw_args):
        parser.exit(
            2,
            "error: command-line license key is not supported; use Windows Credential Manager or REACHOPS_LICENSE_KEY session env.\n",
        )
    parser.add_argument("--endpoint", default="", help="License service endpoint. Defaults to REACHOPS_LICENSE_ENDPOINT.")
    parser.add_argument("--runtime-dir", default="", help="Override ReachOps runtime directory for activation status output.")
    parser.add_argument("--device-id", default="", help="Override current device id for tests or operator-issued binding.")
    parser.add_argument("--app-version", default="", help="ReachOps app version reported to the license service.")
    parser.add_argument("--preview", action="store_true", help="Build and print the redacted request payload without network or file writes.")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(raw_args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    runtime_paths = RuntimePaths.build(base_dir=args.runtime_dir) if args.runtime_dir else RuntimePaths.build()
    client = ReachOpsLicenseClient(
        endpoint=args.endpoint,
        runtime_paths=runtime_paths,
        device_id=args.device_id,
        app_version=args.app_version,
    )
    if args.preview:
        result = {
            "status": "preview",
            "refreshed": False,
            "activation_status_path": runtime_paths.activation_status_path,
            "endpoint_configured": bool(client.endpoint),
            "request_payload": _redact_license_key(client.build_request_payload()),
            "license_key_source": client.license_key_source,
            "license_key_persistent": client.license_key_persistent,
            "license_key_error": client.license_key_error,
            "secret_value_redacted": True,
            "no_browser_started": True,
            "no_submit": True,
            "customer_data_uploaded": False,
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
        return 0
    try:
        result = client.refresh(timeout_seconds=args.timeout_seconds).as_dict()
        result["request_payload"] = _redact_license_key(result.get("request_payload") or {})
    except Exception as exc:
        result = {
            "status": "failed",
            "refreshed": False,
            "activation_status_path": runtime_paths.activation_status_path,
            "endpoint_configured": bool(client.endpoint),
            "error": exc.__class__.__name__,
            "license_key_source": client.license_key_source,
            "license_key_persistent": client.license_key_persistent,
            "license_key_error": client.license_key_error,
            "secret_value_redacted": True,
            "no_browser_started": True,
            "no_submit": True,
            "customer_data_uploaded": False,
        }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 0 if result.get("refreshed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

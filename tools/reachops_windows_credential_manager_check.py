# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid
from typing import Any

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.security.credential_store import (  # noqa: E402
    BACKEND_WINDOWS_CREDENTIAL_MANAGER,
    CREDENTIAL_STORAGE_SCHEMA_VERSION,
    CredentialStoreUnavailable,
    ReachOpsCredentialStore,
    credential_storage_status,
)


VALIDATION_SCHEMA_VERSION = "reachops.windows_credential_manager_validation.v1"


def _validation_name(prefix: str = "credential_manager_validation") -> str:
    clean_prefix = str(prefix or "credential_manager_validation").strip() or "credential_manager_validation"
    return f"{clean_prefix}_{uuid.uuid4().hex}"


def _public_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": status.get("schema_version"),
        "platform": status.get("platform"),
        "backend": status.get("backend"),
        "available": bool(status.get("available")),
        "secret_persistence_allowed": bool(status.get("secret_persistence_allowed")),
        "windows_credential_manager_required": bool(status.get("windows_credential_manager_required")),
        "status_includes_secret_values": bool(status.get("status_includes_secret_values")),
    }


def run_validation(namespace: str = "ReachOpsValidation", credential_name: str = "") -> dict[str, Any]:
    storage_status = credential_storage_status()
    public_status = _public_status(storage_status)
    result: dict[str, Any] = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "credential_storage_schema_version": CREDENTIAL_STORAGE_SCHEMA_VERSION,
        "status": "blocked_external_validation",
        "passed": False,
        "backend": public_status.get("backend"),
        "storage_status": public_status,
        "windows_required": True,
        "no_browser_started": True,
        "no_submit": True,
        "customer_data_uploaded": False,
        "secret_value_included": False,
        "checks": {
            "windows_credential_manager_available": False,
            "secret_write_succeeded": False,
            "secret_readback_matched": False,
            "secret_delete_succeeded": False,
            "output_excludes_secret_value": True,
        },
        "credential_name": "",
        "target_name": "",
        "next_actions": [],
    }
    if not public_status.get("available") or public_status.get("backend") != BACKEND_WINDOWS_CREDENTIAL_MANAGER:
        result["next_actions"] = [
            "Run this check on Windows 10/11 with pywin32 installed.",
            "Install pywin32 in the ReachOps runtime if backend=win32cred_unavailable.",
            "Re-run: python tools\\reachops_windows_credential_manager_check.py --json",
        ]
        return result

    name = str(credential_name or _validation_name()).strip()
    store = ReachOpsCredentialStore(namespace=namespace)
    secret = f"reachops-validation-{secrets.token_urlsafe(24)}"
    result["credential_name"] = name
    result["checks"]["windows_credential_manager_available"] = True
    delete_result: dict[str, Any] = {}
    try:
        write_result = store.set_secret(name, secret)
        result["checks"]["secret_write_succeeded"] = bool(write_result.get("stored"))
        result["target_name"] = str(write_result.get("target_name") or "")
        result["checks"]["secret_readback_matched"] = store.get_secret(name) == secret
    except (CredentialStoreUnavailable, ValueError) as exc:
        result["status"] = "failed"
        result["error_code"] = exc.__class__.__name__
        result["error"] = str(exc)
    finally:
        try:
            delete_result = store.delete_secret(name)
        except Exception as exc:
            delete_result = {"deleted": False, "error_code": exc.__class__.__name__}
        result["checks"]["secret_delete_succeeded"] = bool(delete_result.get("deleted"))

    passed = all(
        bool(result["checks"].get(key))
        for key in (
            "windows_credential_manager_available",
            "secret_write_succeeded",
            "secret_readback_matched",
            "secret_delete_succeeded",
            "output_excludes_secret_value",
        )
    )
    result["passed"] = passed
    result["status"] = "passed" if passed else result.get("status") if result.get("status") != "blocked_external_validation" else "failed"
    result["next_actions"] = [] if passed else ["Inspect the Windows Credential Manager backend and pywin32 installation, then re-run the check."]
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate ReachOps Windows Credential Manager secret persistence.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--namespace", default="ReachOpsValidation")
    parser.add_argument("--credential-name", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_validation(namespace=args.namespace, credential_name=args.credential_name)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps Windows Credential Manager check: {result['status']}")
        print(f"backend={result.get('backend')} passed={result.get('passed')}")
        for item in result.get("next_actions") or []:
            print(f"next: {item}")
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

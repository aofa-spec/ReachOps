# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.device_seats import evaluate_device_seat_state
from ReachOps.license_state import evaluate_license_state
from ReachOps.license_verification import evaluate_license_verification_state
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from ReachOps.workbench.device_identity import DeviceIdentity


def load_status(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, str(exc)
    if not isinstance(payload, dict):
        return {}, "activation status must be a JSON object"
    return payload, ""


def action_probe(action_type: str) -> dict[str, Any]:
    return {
        "id": f"activation_check_{action_type}",
        "action_type": action_type,
        "target_url": "https://www.tiktok.com/@reachops_activation_check",
        "source_path": "https://www.tiktok.com/@reachops_activation_check/video/0" if action_type == "comment_reply" else "",
        "target_username": "reachops_activation_check",
    }


def check_activation_status(path: str | Path = "") -> dict[str, Any]:
    status_path = Path(path).expanduser() if str(path or "").strip() else Path(RuntimePaths.build().activation_status_path)
    current_device_id = DeviceIdentity.current_device_id()
    result: dict[str, Any] = {
        "status": "blocked",
        "ready": False,
        "no_browser_started": True,
        "no_submit": True,
        "activation_status_path": str(status_path),
        "activation_status_exists": status_path.exists() and status_path.is_file(),
        "current_device_id": current_device_id,
        "runtime_mode": LiveSubmitAuthorizationGate.runtime_mode(),
        "activation_required": LiveSubmitAuthorizationGate.activation_required(),
        "development_bypass": not LiveSubmitAuthorizationGate.activation_required(),
        "checks": [],
    }

    def add(name: str, passed: bool, **evidence):
        result["checks"].append({"name": name, "passed": bool(passed), "evidence": evidence})

    if not LiveSubmitAuthorizationGate.activation_required() and not result["activation_status_exists"]:
        profile = {"profile_id": "activation-check", "group_name": "ACTIVATION_CHECK"}
        decisions = []
        for action_type in ["comment_reply", "follow_review", "dm_review"]:
            decision = LiveSubmitAuthorizationGate(str(status_path)).authorize_live_submit(
                action_probe(action_type),
                profile,
                feature="live_submit",
            )
            decisions.append(
                {
                    "action_type": action_type,
                    "allowed": bool(decision.allowed),
                    "error_code": decision.error_code,
                    "error_message": decision.error_message,
                    "evidence": decision.evidence,
                }
            )
        add(
            "development_runtime_activation_not_required",
            all(item["allowed"] for item in decisions),
            decisions=decisions,
        )
        result["ready"] = all(item["passed"] for item in result["checks"])
        result["status"] = "ready" if result["ready"] else "blocked"
        result["license_tier"] = "development"
        result["expires_at"] = ""
        result["capabilities"] = {
            "live_submit": True,
            "comment_reply": True,
            "follow_review": True,
            "dm_review": True,
        }
        return result

    if not result["activation_status_exists"]:
        add("activation_status_file_exists", False, activation_status_path=str(status_path))
        return result

    payload, error = load_status(status_path)
    add("activation_status_json_valid", not error, error=error)
    if error:
        return result

    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    license_state = evaluate_license_state(payload)
    verification_state = evaluate_license_verification_state(payload)
    device_seat_state = evaluate_device_seat_state(payload, current_device_id)
    result["license_state"] = license_state.as_dict()
    result["license_verification_state"] = verification_state.as_dict()
    result["device_seat_state"] = device_seat_state.as_dict()
    add("activation_not_template", not bool(payload.get("template_only")), template_only=bool(payload.get("template_only")))
    add("activation_active", bool(payload.get("active")), active=bool(payload.get("active")))
    add("license_app_access_allowed", license_state.app_access_allowed, license_state=license_state.as_dict())
    add("license_live_submit_allowed", license_state.live_submit_allowed, license_state=license_state.as_dict())
    verification_declared = any(
        str(payload.get(key) or "").strip()
        for key in ["last_verified_at", "verified_at", "last_license_check_at", "next_verify_at", "next_license_check_at"]
    )
    if verification_declared:
        add("license_verification_current", not verification_state.verification_required, license_verification_state=verification_state.as_dict())
    add("device_seat_allows_current_device", device_seat_state.device_allowed, device_seat_state=device_seat_state.as_dict())
    add("device_binding_matches", device_seat_state.device_allowed, device_seat_state=device_seat_state.as_dict())
    add("live_submit_capability_enabled", bool(capabilities.get("live_submit")), capabilities=capabilities)
    for capability in ["comment_reply", "follow_review", "dm_review"]:
        add(f"{capability}_capability_enabled", bool(capabilities.get(capability)), capabilities=capabilities)

    gate = LiveSubmitAuthorizationGate(str(status_path))
    profile = {"profile_id": "activation-check", "group_name": "ACTIVATION_CHECK"}
    decisions = []
    for action_type in ["comment_reply", "follow_review", "dm_review"]:
        decision = gate.authorize_live_submit(action_probe(action_type), profile, feature="live_submit")
        decisions.append(
            {
                "action_type": action_type,
                "allowed": bool(decision.allowed),
                "error_code": decision.error_code,
                "error_message": decision.error_message,
                "evidence": decision.evidence,
            }
        )
    add("authorization_allows_live_actions", all(item["allowed"] for item in decisions), decisions=decisions)

    ready = all(item["passed"] for item in result["checks"])
    result["ready"] = ready
    result["status"] = "ready" if ready else "blocked"
    result["license_tier"] = str(payload.get("license_tier") or "")
    result["expires_at"] = str(payload.get("expires_at") or "")
    result["capabilities"] = capabilities
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ReachOps live-submit activation status without browser or submit.")
    parser.add_argument("--activation-status-path", default="", help="Path to reachops_activation_status.json. Defaults to ReachOps runtime config path.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = check_activation_status(args.activation_status_path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())

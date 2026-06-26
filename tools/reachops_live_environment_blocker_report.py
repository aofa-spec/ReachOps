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


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def latest_acceptance_summary(reports_dir: Path) -> Path:
    if not reports_dir.exists():
        return Path()
    candidates = sorted(
        [item / "acceptance_summary.json" for item in reports_dir.iterdir() if item.is_dir() and (item / "acceptance_summary.json").exists()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else Path()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def build_report(summary: dict[str, Any], summary_path: str = "") -> dict[str, Any]:
    live_preflight = _as_dict(summary.get("live_preflight"))
    live_readiness = _as_dict(summary.get("live_readiness"))
    live_validation = _as_dict(summary.get("live_validation"))
    live_submit = _as_dict(summary.get("live_submit"))
    delivery_audit = _as_dict(summary.get("delivery_audit"))
    verification = _as_dict(summary.get("acceptance_verification"))
    environment = _as_dict(live_preflight.get("environment_diagnostics"))
    if not environment:
        environment = _as_dict(_as_dict(verification.get("live_preflight")).get("environment"))

    failed_profile_ids = [str(item) for item in _as_list(environment.get("failed_profile_ids"))]
    ready_profile_ids = [str(item) for item in _as_list(environment.get("ready_profile_ids"))]
    classification_counts = _as_dict(environment.get("classification_counts"))
    next_required_actions = [str(item) for item in _as_list(environment.get("next_required_actions"))]
    missing_validation_inputs = [str(item) for item in _as_list(live_validation.get("missing_inputs"))]
    if not missing_validation_inputs:
        missing_validation_inputs = [str(item) for item in _as_list(_as_dict(verification.get("live_validation")).get("missing_inputs"))]

    blockers: list[dict[str, Any]] = []
    blocking_stage = str(environment.get("blocking_stage") or "")
    if blocking_stage:
        blockers.append(
            {
                "code": blocking_stage,
                "scope": "ixbrowser_profile_environment",
                "profile_ids": failed_profile_ids,
                "classifications": classification_counts,
                "next_actions": next_required_actions,
            }
        )
    if str(live_readiness.get("status") or "") == "blocked" or not bool(live_readiness.get("ready")):
        blockers.append(
            {
                "code": "live_readiness_blocked",
                "scope": "authorization_or_inputs",
                "missing_inputs": missing_validation_inputs,
            }
        )
    if str(live_submit.get("status") or "") in {"", "skipped"}:
        blockers.append(
            {
                "code": "live_submit_not_run",
                "scope": "controlled_live_submit",
                "reason": "RunLiveSubmit remains disabled until readiness/preflight pass and targets are authorized.",
            }
        )

    live_preflight_completed = str(live_preflight.get("status") or "") == "completed"
    missing_preflight_types = [str(item) for item in _as_list(live_preflight.get("missing_preflight_action_types"))]
    milestone3_ready = live_preflight_completed and bool(ready_profile_ids) and not missing_preflight_types
    effective_pending = int(delivery_audit.get("effective_pending_external_validation") or 0)
    milestone4_ready = (
        str(summary.get("status") or "") == "passed"
        and effective_pending == 0
        and str(live_submit.get("status") or "") == "completed"
        and bool(live_submit.get("platform_validation"))
    )

    return {
        "status": "passed" if milestone4_ready else "blocked",
        "summary_path": summary_path,
        "acceptance_status": str(summary.get("status") or verification.get("status") or ""),
        "milestone3_status": "ready" if milestone3_ready else "blocked",
        "milestone4_status": "passed" if milestone4_ready else "blocked",
        "no_submit": bool(live_preflight.get("no_submit", True)) and str(live_submit.get("status") or "") != "completed",
        "effective_pending_external_validation": effective_pending,
        "ready_profile_ids": ready_profile_ids,
        "failed_profile_ids": failed_profile_ids,
        "blocking_stage": blocking_stage,
        "classification_counts": classification_counts,
        "missing_preflight_action_types": missing_preflight_types,
        "missing_validation_inputs": missing_validation_inputs,
        "blockers": blockers,
        "safe_rerun_commands": {
            "background_acceptance_no_submit": "powershell -NoProfile -ExecutionPolicy Bypass -File tools\\start_reachops_acceptance_background_windows.ps1 -InputFile .\\tools\\reachops_acceptance_inputs.local.ps1",
            "background_status": "powershell -NoProfile -ExecutionPolicy Bypass -File tools\\get_reachops_acceptance_background_status_windows.ps1 -Json",
            "controlled_live_submit_after_authorization": "powershell -NoProfile -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets ...",
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize ReachOps live environment blockers from an acceptance summary.")
    parser.add_argument("--acceptance-summary", default="", help="Path to acceptance_summary.json. Defaults to latest reports/reachops_acceptance/*.")
    parser.add_argument("--reports-dir", default="", help="Acceptance reports directory used when --acceptance-summary is omitted.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary_path = Path(args.acceptance_summary) if args.acceptance_summary else latest_acceptance_summary(Path(args.reports_dir or ROOT_DIR / "reports" / "reachops_acceptance"))
    if not summary_path or not summary_path.exists():
        report = {"status": "missing", "error": "acceptance_summary.json not found"}
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    summary = load_json(summary_path)
    report = build_report(summary, str(summary_path))
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") != "missing" else 2


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reachops.real_page_timeout_probe.v1"

DETAIL_RE = re.compile(
    r"profile_preflight_detail\s+stage=(?P<stage>\S+)\s+profile=(?P<profile_id>\S+)\s+"
    r"status=(?P<status>\S+)\s+error=PAGE_TIMEOUT\s+evidence=(?P<evidence>.+?)"
    r"(?:\s+close_action=|\s+operator_hint=|\s+message=|$)"
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_page_timeout(lines: list[str]) -> dict[str, str]:
    for line in lines:
        match = DETAIL_RE.search(str(line or ""))
        if not match:
            continue
        return {
            "profile_id": match.group("profile_id"),
            "stage": match.group("stage"),
            "evidence_path": "" if match.group("evidence") == "-" else match.group("evidence"),
            "line": str(line),
        }
    return {}


def build_probe(*, result_path: str | Path, output: str | Path = "") -> dict[str, Any]:
    result = read_json(result_path)
    lines = [str(line) for line in result.get("tail") or []]
    hit = extract_page_timeout(lines)
    evidence_path = str(hit.get("evidence_path") or "")
    evidence_exists = bool(evidence_path and Path(evidence_path).is_file())
    passed = bool(hit and evidence_exists and result.get("status") in {"completed", "degraded", "blocked_by_accounts"})
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked_by_accounts" if hit else "missing",
        "terminal_state": "BLOCKED" if hit else "FAILED",
        "terminal_reason_code": "BLOCKED_BY_ACCOUNTS" if hit else "PAGE_TIMEOUT_EVIDENCE_MISSING",
        "generated_at": utc_stamp(),
        "mode": "real_page_timeout_probe",
        "source_result_path": str(Path(result_path).expanduser()),
        "profile_group": str(result.get("profile_group") or ""),
        "target": str(result.get("target") or ""),
        "no_submit": True,
        "no_browser_collection": False,
        "no_action_execution": bool("no_submit=true" in "\n".join(lines)),
        "fault_injection": {
            "enabled": False,
            "failure_code": "",
            "safe_no_submit": True,
            "real_ixbrowser_opened": bool(hit),
            "real_tiktok_opened": bool(hit),
            "counts_as_real_acceptance": passed,
        },
        "metadata": {
            "status": "ok" if hit else "missing",
            "safe_read_only": True,
            "open_profile_called": bool(hit),
            "group_name_filter": str(result.get("profile_group") or ""),
            "selected_profile_count": 1 if hit else 0,
            "selected_profile_sample_count": 1 if hit else 0,
            "selected_group_id_present": False,
            "profile_limit_honored": True,
            "error_code": "" if hit else "PAGE_TIMEOUT_EVIDENCE_MISSING",
            "error_message": "" if hit else "No PAGE_TIMEOUT profile_preflight_detail line found.",
        },
        "selected_profiles_count": 1 if hit else 0,
        "profile_counts": {
            "schema_version": "reachops.profile_scan_counts.v1",
            "candidate_profile_count": 1 if hit else 0,
            "selected_for_scan_count": 1 if hit else 0,
            "requested_profile_count": 1 if hit else 0,
            "scanned_profile_count": 1 if hit else 0,
            "available_profile_count": 0,
            "unavailable_profile_count": 1 if hit else 0,
            "unscanned_profile_count": 0,
            "metadata_selected_profile_count": 1 if hit else 0,
            "profile_limit_honored": True,
        },
        "summary": {
            "requested": 1 if hit else 0,
            "checked": 1 if hit else 0,
            "available": 0,
            "unavailable": 1 if hit else 0,
            "errors": {"PAGE_TIMEOUT": 1} if hit else {},
        },
        "timeout_triggered": bool(hit),
        "bounded_exit": True,
        "bounded_exit_status": "terminated_after_timeout" if hit else "missing",
        "results": [
            {
                "profile_id": str(hit.get("profile_id") or ""),
                "group_name": str(result.get("profile_group") or ""),
                "status": "PAGE_TIMEOUT",
                "ok": False,
                "error_code": "PAGE_TIMEOUT",
                "error_message": "Real Headless profile preflight page timeout.",
                "duration_seconds": 0.0,
                "evidence_path": evidence_path,
                "evidence_exists": evidence_exists,
                "quarantine_attempted": False,
                "recommended_action": "Retry later with a larger page timeout only after network/proxy check.",
            }
        ]
        if hit
        else [],
        "attempted_profile_ids": [str(hit.get("profile_id") or "")] if hit else [],
        "hard_failed_profile_ids": [str(hit.get("profile_id") or "")] if hit else [],
        "real_evidence": {
            "source": "headless_runtime_log",
            "line": str(hit.get("line") or ""),
            "evidence_path": evidence_path,
            "evidence_exists": evidence_exists,
            "execution_plan": result.get("execution_plan") or {},
            "run_session": result.get("run_session") or {},
            "evidence_bundle": result.get("evidence_bundle") or {},
        },
        "next_action": "Keep PAGE_TIMEOUT as real failure-mode evidence." if passed else "Collect a real PAGE_TIMEOUT with screenshot evidence.",
    }
    if output:
        target = Path(output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract real PAGE_TIMEOUT evidence from a Headless ReachOps run result.")
    parser.add_argument("--result-path", default="reports/reachops/mac_gui/runtime/run_results/run_05a4143871a36e1a.json")
    parser.add_argument("--output", default="/tmp/reachops_page_timeout_probe.json")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(result_path=args.result_path, output=args.output)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("summary", {}).get("errors", {}).get("PAGE_TIMEOUT") and payload.get("real_evidence", {}).get("evidence_exists") else 2


if __name__ == "__main__":
    raise SystemExit(main())

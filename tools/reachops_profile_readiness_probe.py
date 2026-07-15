# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.workbench.profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig

SCHEMA_VERSION = "reachops.profile_readiness_probe.v1"
TERMINAL_COMPLETED = "COMPLETED"
TERMINAL_BLOCKED = "BLOCKED"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]


def safe_int(value: Any, default: int, minimum: int = 1, maximum: int = 1000000) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return max(minimum, min(maximum, parsed))


def ordered_unique(values: list[Any]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        profile_id = str(value or "").strip()
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        rows.append(profile_id)
    return rows


def load_recent_failed_profile_ids(base_dir: str | Path, max_reports: int = 10) -> list[str]:
    root = Path(base_dir)
    candidates = sorted(
        root.glob("*/reports/profile_repair_checklist.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )[: max(1, int(max_reports or 1))]
    failed: list[str] = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        failed.extend(payload.get("failed_profile_ids") or [])
        for group in payload.get("error_groups") or []:
            if isinstance(group, dict):
                failed.extend(group.get("profile_ids") or [])
    return ordered_unique(failed)


def select_profiles(
    *,
    profile_ids: list[str] | None = None,
    profile_group: str = "United States",
    profile_limit: int = 3,
    max_pages: int = 2,
    exclude_profile_ids: list[str] | None = None,
    metadata_builder: Callable[..., dict[str, Any]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    limit = safe_int(profile_limit, 3, minimum=1, maximum=100)
    explicit_ids = [profile_id for profile_id in (profile_ids or []) if str(profile_id).strip()]
    if explicit_ids:
        profiles = [
            {"profile_id": str(profile_id).strip(), "group_name": str(profile_group or "")}
            for profile_id in explicit_ids[:limit]
        ]
        return profiles, {
            "status": "explicit",
            "safe_read_only": True,
            "open_profile_called": False,
            "group_name_filter": str(profile_group or ""),
            "selected_profile_count": len(explicit_ids),
            "selected_profile_sample_count": len(profiles),
            "selected_group_id_present": False,
        }

    if metadata_builder is None:
        return select_profiles_from_ixbrowser(
            profile_group=profile_group,
            profile_limit=limit,
            max_pages=max_pages,
            exclude_profile_ids=exclude_profile_ids,
        )

    builder = metadata_builder
    exclude_set = {str(profile_id).strip() for profile_id in (exclude_profile_ids or []) if str(profile_id).strip()}
    metadata = builder(
        group_name=str(profile_group or ""),
        max_pages=max(1, int(max_pages or 1)),
        profile_limit=min(100, limit + len(exclude_set)),
    )
    selected = metadata.get("selected_profiles") if isinstance(metadata, dict) else []
    profiles: list[dict[str, str]] = []
    excluded: list[str] = []
    for row in selected or []:
        profile = row.get("profile") if isinstance(row, dict) else {}
        profile_id = str((profile or {}).get("profile_id") or "").strip()
        if not profile_id:
            continue
        if profile_id in exclude_set:
            excluded.append(profile_id)
            continue
        profiles.append(
            {
                "profile_id": profile_id,
                "group_id": str((profile or {}).get("group_id") or ""),
                "group_name": str((profile or {}).get("group_name") or profile_group or ""),
            }
        )
        if len(profiles) >= limit:
            break
    metadata_summary = {
        "status": str(metadata.get("status") or "error") if isinstance(metadata, dict) else "error",
        "safe_read_only": bool((metadata or {}).get("safe_read_only")) if isinstance(metadata, dict) else False,
        "open_profile_called": bool((metadata or {}).get("open_profile_called")) if isinstance(metadata, dict) else False,
        "group_name_filter": str((metadata or {}).get("group_name_filter") or profile_group) if isinstance(metadata, dict) else str(profile_group or ""),
        "group_count": int((metadata or {}).get("group_count") or 0) if isinstance(metadata, dict) else 0,
        "known_group_count": int((metadata or {}).get("known_group_count") or 0) if isinstance(metadata, dict) else 0,
        "selected_group_id_present": bool((metadata or {}).get("selected_group_id")) if isinstance(metadata, dict) else False,
        "selected_profile_count": int((metadata or {}).get("selected_profile_count") or 0) if isinstance(metadata, dict) else 0,
        "selected_profile_sample_count": len(profiles),
        "profile_limit_honored": len(profiles) <= limit,
        "excluded_recent_failed_profile_count": len(excluded),
        "excluded_recent_failed_profile_ids_sample": excluded[:12],
        "error_code": str((metadata or {}).get("error_code") or "") if isinstance(metadata, dict) else "METADATA_UNAVAILABLE",
        "error_message": str((metadata or {}).get("error_message") or "") if isinstance(metadata, dict) else "",
    }
    return profiles, metadata_summary


def normalize_ix_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("data", "list", "rows"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def select_profiles_from_ixbrowser(
    *,
    profile_group: str,
    profile_limit: int,
    max_pages: int,
    exclude_profile_ids: list[str] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        from ixbrowser_local_api import IXBrowserClient
    except Exception as exc:
        return [], {
            "status": "error",
            "safe_read_only": True,
            "open_profile_called": False,
            "group_name_filter": str(profile_group or ""),
            "selected_profile_count": 0,
            "selected_profile_sample_count": 0,
            "selected_group_id_present": False,
            "profile_limit_honored": True,
            "error_code": "IXBROWSER_CLIENT_IMPORT_FAILED",
            "error_message": f"{type(exc).__name__}: {exc}",
        }

    limit = safe_int(profile_limit, 3, minimum=1, maximum=100)
    pages = safe_int(max_pages, 2, minimum=1, maximum=10)
    exclude_set = {str(profile_id).strip() for profile_id in (exclude_profile_ids or []) if str(profile_id).strip()}
    wanted = str(profile_group or "").strip().lower()
    groups_seen = 0
    selected_group_id = ""
    selected_group_count = 0
    api_code = None
    api_message = ""
    try:
        client = IXBrowserClient()
        for page in range(1, pages + 1):
            groups = normalize_ix_rows(client.get_group_list(page=page, limit=100) or [])
            groups_seen += len(groups)
            api_code = getattr(client, "code", None)
            api_message = str(getattr(client, "message", "") or "")
            for group in groups:
                label = str(group.get("title") or group.get("group_name") or group.get("name") or "").strip().lower()
                if label == wanted:
                    selected_group_id = str(group.get("id") or group.get("group_id") or "").strip()
                    try:
                        selected_group_count = int(group.get("count") or group.get("profile_count") or 0)
                    except Exception:
                        selected_group_count = 0
                    break
            if selected_group_id or len(groups) < 100:
                break
        if not selected_group_id:
            return [], {
                "status": "group_not_found",
                "safe_read_only": True,
                "open_profile_called": False,
                "group_name_filter": str(profile_group or ""),
                "group_count": groups_seen,
                "known_group_count": 0,
                "selected_profile_count": 0,
                "selected_profile_sample_count": 0,
                "selected_group_id_present": False,
                "profile_limit_honored": True,
                "api_code": api_code,
                "api_message": api_message,
                "error_code": "BLOCKED_US_GROUP_NOT_FOUND",
                "error_message": f"profile group not found: {profile_group}",
            }
        rows = []
        excluded: list[str] = []
        page_limit = min(100, max(limit, limit + len(exclude_set)))
        for page in range(1, pages + 1):
            page_rows = normalize_ix_rows(client.get_profile_list(group_id=int(selected_group_id), page=page, limit=page_limit) or [])
            api_code = getattr(client, "code", None)
            api_message = str(getattr(client, "message", "") or "")
            for row in page_rows:
                profile_id = str(row.get("profile_id") or row.get("id") or "").strip()
                if profile_id and profile_id in exclude_set:
                    excluded.append(profile_id)
                    continue
                rows.append(row)
                if len(rows) >= limit:
                    break
            if len(rows) >= limit or len(page_rows) < page_limit:
                break
        try:
            response_total = int(getattr(client, "total", 0) or selected_group_count or len(rows))
        except Exception:
            response_total = selected_group_count or len(rows)
    except Exception as exc:
        return [], {
            "status": "error",
            "safe_read_only": True,
            "open_profile_called": False,
            "group_name_filter": str(profile_group or ""),
            "selected_profile_count": 0,
            "selected_profile_sample_count": 0,
            "selected_group_id_present": bool(selected_group_id),
            "profile_limit_honored": True,
            "api_code": api_code,
            "api_message": api_message,
            "error_code": "IXBROWSER_PROFILE_LIST_FAILED",
            "error_message": f"{type(exc).__name__}: {exc}",
        }
    profiles: list[dict[str, str]] = []
    for row in rows:
        profile_id = str(row.get("profile_id") or row.get("id") or "").strip()
        if not profile_id:
            continue
        profiles.append(
            {
                "profile_id": profile_id,
                "group_id": selected_group_id,
                "group_name": str(row.get("group_name") or profile_group or ""),
            }
        )
        if len(profiles) >= limit:
            break
    return profiles, {
        "status": "ok",
        "safe_read_only": True,
        "open_profile_called": False,
        "group_name_filter": str(profile_group or ""),
        "group_count": groups_seen,
        "known_group_count": 1 if response_total else 0,
        "selected_group_id_present": bool(selected_group_id),
        "selected_profile_count": int(response_total or len(profiles)),
        "selected_profile_sample_count": len(profiles),
        "profile_limit_honored": len(profiles) <= limit,
        "excluded_recent_failed_profile_count": len(excluded),
        "excluded_recent_failed_profile_ids_sample": ordered_unique(excluded)[:12],
        "api_code": api_code,
        "api_message": api_message,
        "error_code": "",
        "error_message": "",
    }


def public_result(row: dict[str, Any]) -> dict[str, Any]:
    quarantine = row.get("quarantine_move") if isinstance(row.get("quarantine_move"), dict) else {}
    return {
        "profile_id": str(row.get("profile_id") or ""),
        "group_name": str(row.get("group_name") or ""),
        "status": "READY" if row.get("ok") else str(row.get("error_code") or "UNKNOWN_PAGE_STATE"),
        "ok": bool(row.get("ok")),
        "error_code": str(row.get("error_code") or ""),
        "error_message": str(row.get("error_message") or "")[:500],
        "duration_seconds": float(row.get("duration_seconds") or 0),
        "evidence_path": str(row.get("evidence_path") or ""),
        "quarantine_attempted": bool(quarantine.get("attempted")),
        "recommended_action": recommended_action(str(row.get("error_code") or ""), bool(row.get("ok"))),
    }


def recommended_action(error_code: str, ok: bool) -> str:
    if ok:
        return "Keep in candidate pool for real no-submit validation."
    return {
        "LOGIN_REQUIRED": "Log in to TikTok for this profile, then rerun readiness probe.",
        "CAPTCHA_DETECTED": "Resolve captcha manually or remove from automated run pool.",
        "PROXY_FAILED": "Repair proxy/network settings before retry.",
        "PROFILE_START_FAILED": "Check ixBrowser profile existence and startup configuration.",
        "IXBROWSER_KERNEL_MISMATCH": "Repair ixBrowser kernel version or remove from this run pool.",
        "PAGE_TIMEOUT": "Retry later with a larger page timeout only after network/proxy check.",
        "PROFILE_PREFLIGHT_TIMEOUT": "Treat as hard failure for this run; do not retry in the same probe.",
        "PAGE_OPEN_FAILED": "Check TikTok accessibility and proxy before retry.",
    }.get(error_code or "", "Review page-state evidence and classify before retry.")


def readiness_status(summary: dict[str, Any], selected_profiles: list[dict[str, str]]) -> tuple[str, str]:
    checked = int(summary.get("checked") or 0)
    available = int(summary.get("available") or 0)
    if not selected_profiles:
        return "blocked_by_accounts", TERMINAL_BLOCKED
    if checked <= 0:
        return "blocked_by_environment", TERMINAL_BLOCKED
    if available <= 0:
        return "blocked_by_accounts", TERMINAL_BLOCKED
    if available < len(selected_profiles):
        return "partial", TERMINAL_COMPLETED
    return "passed", TERMINAL_COMPLETED


def build_repair_checklist(payload: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in payload.get("results") or []:
        if not isinstance(row, dict) or row.get("ok"):
            continue
        error_code = str(row.get("error_code") or row.get("status") or "UNKNOWN_PAGE_STATE")
        group = grouped.setdefault(
            error_code,
            {
                "error_code": error_code,
                "count": 0,
                "profile_ids": [],
                "recommended_action": recommended_action(error_code, False),
                "evidence_paths": [],
            },
        )
        group["count"] = int(group.get("count") or 0) + 1
        profile_id = str(row.get("profile_id") or "")
        if profile_id:
            group["profile_ids"].append(profile_id)
        evidence_path = str(row.get("evidence_path") or "")
        if evidence_path:
            group["evidence_paths"].append(evidence_path)
    groups = sorted(grouped.values(), key=lambda item: (-int(item.get("count") or 0), str(item.get("error_code") or "")))
    profile_group = str(payload.get("profile_group") or "United States")
    failed_ids = [
        str(row.get("profile_id") or "")
        for row in payload.get("results") or []
        if isinstance(row, dict) and not row.get("ok") and str(row.get("profile_id") or "")
    ]
    ready_ids = [
        str(row.get("profile_id") or "")
        for row in payload.get("results") or []
        if isinstance(row, dict) and row.get("ok") and str(row.get("profile_id") or "")
    ]
    profile_limit = max(1, len(failed_ids) or int((payload.get("budgets") or {}).get("max_profile_scan_count") or 1))
    retest_command = (
        "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_profile_readiness_probe.py "
        f"--profile-group {json.dumps(profile_group)} "
        f"--profile-limit {profile_limit} --max-workers 1 --allow-fail --json"
    )
    if failed_ids:
        retest_command = (
            "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_profile_readiness_probe.py "
            f"--profile-group {json.dumps(profile_group)} "
            f"--profile-ids {json.dumps(','.join(failed_ids))} "
            f"--profile-limit {len(failed_ids)} --max-workers 1 --allow-fail --json"
        )
    return {
        "schema_version": "reachops.profile_repair_checklist.v1",
        "status": "ready_profiles_available" if ready_ids else "manual_repair_required",
        "profile_group": profile_group,
        "ready_profile_ids": ready_ids,
        "failed_profile_ids": failed_ids,
        "error_groups": groups,
        "manual_only": True,
        "no_submit": bool(payload.get("no_submit", True)),
        "does_not_modify_ixbrowser_groups": not bool(payload.get("quarantine_failed_profiles")),
        "retest_command": retest_command,
        "next_action": (
            "Use READY profile IDs for the next single-account real no-submit run."
            if ready_ids
            else "Repair listed profiles or provide a different candidate list, then rerun the retest command."
        ),
    }


def write_outputs(base_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    reports_dir = base_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "profile_readiness_probe.json"
    csv_path = reports_dir / "profile_readiness_probe.csv"
    md_path = reports_dir / "profile_readiness_probe.md"
    repair_json_path = reports_dir / "profile_repair_checklist.json"
    repair_csv_path = reports_dir / "profile_repair_checklist.csv"
    repair_md_path = reports_dir / "profile_repair_checklist.md"
    outputs = {
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
        "repair_json": str(repair_json_path),
        "repair_csv": str(repair_csv_path),
        "repair_markdown": str(repair_md_path),
    }
    payload["outputs"] = outputs
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "profile_id",
            "group_name",
            "status",
            "ok",
            "error_code",
            "duration_seconds",
            "evidence_path",
            "quarantine_attempted",
            "recommended_action",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in payload.get("results") or []:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    repair_checklist = payload.get("repair_checklist") if isinstance(payload.get("repair_checklist"), dict) else build_repair_checklist(payload)
    payload["repair_checklist"] = repair_checklist
    repair_json_path.write_text(json.dumps(repair_checklist, ensure_ascii=False, indent=2), encoding="utf-8")
    with repair_csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["error_code", "count", "profile_ids", "recommended_action", "evidence_paths"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in repair_checklist.get("error_groups") or []:
            writer.writerow(
                {
                    "error_code": row.get("error_code", ""),
                    "count": row.get("count", 0),
                    "profile_ids": ",".join(str(item) for item in row.get("profile_ids") or []),
                    "recommended_action": row.get("recommended_action", ""),
                    "evidence_paths": ",".join(str(item) for item in row.get("evidence_paths") or []),
                }
            )
    repair_lines = [
        "# ReachOps Profile Repair Checklist",
        "",
        f"- status: {repair_checklist.get('status')}",
        f"- profile_group: {repair_checklist.get('profile_group')}",
        f"- no_submit: {str(bool(repair_checklist.get('no_submit'))).lower()}",
        f"- does_not_modify_ixbrowser_groups: {str(bool(repair_checklist.get('does_not_modify_ixbrowser_groups'))).lower()}",
        "",
        "## Error Groups",
    ]
    for row in repair_checklist.get("error_groups") or []:
        repair_lines.append(
            f"- {row.get('error_code')}: {row.get('count')} profiles; action={row.get('recommended_action')}"
        )
    if not repair_checklist.get("error_groups"):
        repair_lines.append("- none")
    repair_lines.extend(["", "## Retest Command", f"`{repair_checklist.get('retest_command')}`"])
    repair_md_path.write_text("\n".join(repair_lines) + "\n", encoding="utf-8")
    lines = [
        "# ReachOps Profile Readiness Probe",
        "",
        f"- status: {payload.get('status')}",
        f"- terminal_state: {payload.get('terminal_state')}",
        f"- profile_group: {payload.get('profile_group')}",
        f"- checked: {(payload.get('summary') or {}).get('checked', 0)}",
        f"- available: {(payload.get('summary') or {}).get('available', 0)}",
        f"- unavailable: {(payload.get('summary') or {}).get('unavailable', 0)}",
        f"- no_submit: {str(bool(payload.get('no_submit'))).lower()}",
        f"- quarantine_failed_profiles: {str(bool(payload.get('quarantine_failed_profiles'))).lower()}",
        f"- exclude_recent_failed: {str(bool(payload.get('exclude_recent_failed'))).lower()}",
        f"- recent_failed_profile_ids_count: {int(payload.get('recent_failed_profile_ids_count') or 0)}",
        "",
        "## Error Counts",
    ]
    errors = (payload.get("summary") or {}).get("errors") or {}
    if errors:
        lines.extend([f"- {key}: {value}" for key, value in sorted(errors.items())])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Repair Checklist",
            f"- JSON: {repair_json_path}",
            f"- CSV: {repair_csv_path}",
            f"- Markdown: {repair_md_path}",
            "",
            "## Retest Command",
            f"`{repair_checklist.get('retest_command')}`",
            "",
            "## Next Action",
            str(payload.get("next_action") or repair_checklist.get("next_action") or ""),
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return outputs


def enrich_existing_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_dir = report_path.parent.parent
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("mode", "profile_readiness_probe")
    payload["repair_checklist"] = build_repair_checklist(payload)
    payload["report_dir"] = str(report_dir)
    write_outputs(report_dir, payload)
    return payload


def run_probe(
    *,
    base_dir: str | Path,
    profile_group: str = "United States",
    profile_ids: list[str] | None = None,
    profile_limit: int = 3,
    max_pages: int = 2,
    max_workers: int = 1,
    page_timeout_seconds: int = 20,
    wait_after_open_seconds: float = 2.0,
    total_timeout_seconds: int = 60,
    check_url: str = "https://www.tiktok.com/messages",
    quarantine_failed_profiles: bool = False,
    exclude_recent_failed: bool = True,
    driver_factory: Callable[[dict], tuple[Any, Any, str]] | None = None,
    metadata_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(base_dir).resolve()
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    explicit_ids = [profile_id for profile_id in (profile_ids or []) if str(profile_id).strip()]
    recent_failed_profile_ids = (
        load_recent_failed_profile_ids(base)
        if bool(exclude_recent_failed) and not explicit_ids
        else []
    )
    profiles, metadata = select_profiles(
        profile_ids=explicit_ids,
        profile_group=profile_group,
        profile_limit=profile_limit,
        max_pages=max_pages,
        exclude_profile_ids=recent_failed_profile_ids,
        metadata_builder=metadata_builder,
    )
    storage = GrowthStorage(str(run_dir / "data" / "growth_intelligence.db"))
    checker = ProfilePreflightChecker(
        storage,
        ProfilePreflightConfig(
            max_workers=max(1, min(int(max_workers or 1), max(1, len(profiles)))),
            page_load_timeout_seconds=max(1, int(page_timeout_seconds or 20)),
            wait_after_open_seconds=max(0.0, float(wait_after_open_seconds or 0)),
            check_url=str(check_url or "https://www.tiktok.com/messages"),
            evidence_dir=str(run_dir / "evidence" / "profile_preflight"),
            close_browser_after_check=True,
            retain_successful_browser_after_check=False,
            total_timeout_seconds=max(5, int(total_timeout_seconds or 60)),
            quarantine_on_failure=bool(quarantine_failed_profiles),
            launch_stagger_seconds=0.0,
        ),
        driver_factory=driver_factory,
    )
    summary = checker.run(profiles) if profiles else {"requested": 0, "checked": 0, "available": 0, "unavailable": 0, "errors": {}, "results": []}
    status, terminal_state = readiness_status(summary, profiles)
    public_results = [public_result(row) for row in summary.get("results") or []]
    attempted_profile_ids = [str(row.get("profile_id") or "") for row in public_results if str(row.get("profile_id") or "")]
    hard_failed_profile_ids = [str(row.get("profile_id") or "") for row in public_results if row.get("error_code")]
    next_action = "Proceed to a one-account real no-submit run only after at least one READY profile is confirmed."
    if status == "blocked_by_accounts":
        next_action = "Repair or replace unavailable profiles, then rerun this readiness probe before any collection run."
    elif status == "blocked_by_environment":
        next_action = "Repair ixBrowser Local API/Profile startup environment, then rerun this readiness probe."
    wall_clock_seconds = round(max(0.0, time.monotonic() - started_monotonic), 3)
    configured_total_timeout = max(5, int(total_timeout_seconds or 60))
    timeout_overrun_seconds = round(max(0.0, wall_clock_seconds - configured_total_timeout), 3)
    timeout_triggered = bool((summary.get("errors") or {}).get("PROFILE_PREFLIGHT_TIMEOUT"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "terminal_state": terminal_state,
        "generated_at": utc_stamp(),
        "run_id": run_id,
        "mode": "profile_readiness_probe",
        "profile_group": str(profile_group or ""),
        "no_submit": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "quarantine_failed_profiles": bool(quarantine_failed_profiles),
        "exclude_recent_failed": bool(exclude_recent_failed),
        "recent_failed_profile_ids_count": len(recent_failed_profile_ids),
        "recent_failed_profile_ids_sample": recent_failed_profile_ids[:12],
        "metadata": metadata,
        "selected_profiles_count": len(profiles),
        "summary": {
            "requested": int(summary.get("requested") or 0),
            "checked": int(summary.get("checked") or 0),
            "available": int(summary.get("available") or 0),
            "unavailable": int(summary.get("unavailable") or 0),
            "errors": summary.get("errors") or {},
        },
        "wall_clock_seconds": wall_clock_seconds,
        "timeout_triggered": timeout_triggered,
        "timeout_overrun_seconds": timeout_overrun_seconds,
        "bounded_exit": True,
        "bounded_exit_status": "terminated_after_timeout" if timeout_triggered else "within_budget",
        "results": public_results,
        "attempted_profile_ids": attempted_profile_ids,
        "hard_failed_profile_ids": hard_failed_profile_ids,
        "budgets": {
            "max_profile_scan_count": safe_int(profile_limit, 3, minimum=1, maximum=100),
            "max_retries_per_profile": 0,
            "max_page_retries": 0,
            "max_account_switches": 0,
            "profile_open_timeout_seconds": max(1, int(page_timeout_seconds or 20)),
            "page_load_timeout_seconds": max(1, int(page_timeout_seconds or 20)),
            "total_timeout_seconds": configured_total_timeout,
            "max_workers": max(1, int(max_workers or 1)),
        },
        "next_action": next_action,
    }
    payload["report_dir"] = str(run_dir)
    payload["repair_checklist"] = build_repair_checklist(payload)
    write_outputs(run_dir, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded no-submit ReachOps profile readiness probe.")
    parser.add_argument("--base-dir", default="reports/reachops/profile_readiness_probe")
    parser.add_argument("--profile-group", default="United States")
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--page-timeout-seconds", type=int, default=20)
    parser.add_argument("--wait-after-open-seconds", type=float, default=2.0)
    parser.add_argument("--total-timeout-seconds", type=int, default=60)
    parser.add_argument("--check-url", default="https://www.tiktok.com/messages")
    parser.add_argument("--quarantine-failed-profiles", action="store_true")
    parser.add_argument("--no-exclude-recent-failed", action="store_true")
    parser.add_argument("--from-report", default="", help="Enrich an existing probe JSON with repair checklist outputs without opening profiles.")
    parser.add_argument("--allow-fail", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if str(args.from_report or "").strip():
        payload = enrich_existing_report(args.from_report)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    payload = run_probe(
        base_dir=args.base_dir,
        profile_group=args.profile_group,
        profile_ids=split_csv(args.profile_ids),
        profile_limit=args.profile_limit,
        max_pages=args.max_pages,
        max_workers=args.max_workers,
        page_timeout_seconds=args.page_timeout_seconds,
        wait_after_open_seconds=args.wait_after_open_seconds,
        total_timeout_seconds=args.total_timeout_seconds,
        check_url=args.check_url,
        quarantine_failed_profiles=bool(args.quarantine_failed_profiles),
        exclude_recent_failed=not bool(args.no_exclude_recent_failed),
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("status") in {"passed", "partial"}:
        return 0
    return 0 if args.allow_fail else 2


if __name__ == "__main__":
    raise SystemExit(main())

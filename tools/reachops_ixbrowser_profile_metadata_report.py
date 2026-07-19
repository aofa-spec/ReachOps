# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SECRET_KEYS = {"proxy_user", "proxy_password", "username", "password", "tfa_secret", "name"}
PROFILE_FIELDS = (
    "profile_id",
    "name",
    "site_url",
    "group_id",
    "group_name",
    "tag_id",
    "tag_name",
    "proxy_mode",
    "proxy_id",
    "proxy_type",
    "proxy_ip",
    "proxy_port",
    "real_ip",
    "last_open_time",
)
PROXY_FIELDS = (
    "id",
    "proxy_type",
    "proxy_ip",
    "proxy_port",
    "proxy_user",
    "proxy_password",
    "country",
    "timezone",
    "city",
    "tag_id",
    "tag_name",
    "activeWindow",
)


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]


def redact_value(key: str, value: Any, reveal_secrets: bool = False) -> Any:
    if key not in SECRET_KEYS:
        return value
    text = str(value or "")
    if not text:
        return ""
    return "***redacted***"


def copy_fields(row: dict[str, Any], fields: tuple[str, ...], reveal_secrets: bool = False) -> dict[str, Any]:
    return {field: redact_value(field, row.get(field, ""), reveal_secrets) for field in fields if field in row}


def normalize_group(row: dict[str, Any]) -> dict[str, Any]:
    count = int(row.get("count") or row.get("profile_count") or 0)
    return {
        "group_id": str(row.get("id") or row.get("group_id") or ""),
        "group_name": str(row.get("title") or row.get("group_name") or row.get("name") or ""),
        "profile_count": count,
        "count_known": count > 0,
        "count_source": "ixbrowser_group_list" if count > 0 else "",
    }


def list_pages(client: Any, method_name: str, limit: int = 100, max_pages: int = 50, **kwargs: Any) -> list[dict[str, Any]]:
    from ReachOps.workbench.standalone_app import extract_ixbrowser_rows, require_ixbrowser_response

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for page in range(1, max(1, int(max_pages or 50)) + 1):
        response = None
        for attempt in range(1, 4):
            try:
                response = require_ixbrowser_response(
                    client,
                    getattr(client, method_name)(page=page, limit=max(1, int(limit or 100)), **kwargs),
                    f"ixbrowser_{method_name}",
                )
                break
            except Exception:
                if attempt >= 3:
                    raise
                time.sleep(0.6 * attempt)
        batch_rows, response_total = extract_ixbrowser_rows(response)
        try:
            total = int(response_total or getattr(client, "total", 0) or total)
        except Exception:
            total = total
        deduped = []
        for item in batch_rows:
            key = str(
                item.get("profile_id")
                or item.get("profileId")
                or item.get("browser_id")
                or item.get("id")
                or f"{method_name}:{page}:{len(deduped)}"
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        batch_rows = deduped
        rows.extend(batch_rows)
        if total and len(seen) >= total:
            break
        if len(batch_rows) < max(1, int(limit or 100)):
            break
    return rows


def list_profile_rows(
    client: Any,
    profile_ids: set[str],
    profile_limit: int,
    max_pages: int,
    group_id: str = "",
) -> list[dict[str, Any]]:
    if not profile_ids:
        kwargs: dict[str, Any] = {}
        if str(group_id or "").strip():
            kwargs["group_id"] = int(str(group_id).strip())
        return list_pages(
            client,
            "get_profile_list",
            limit=min(max(1, int(profile_limit or 200)), 100),
            max_pages=max_pages,
            **kwargs,
        )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for profile_id in sorted(profile_ids):
        try:
            batch = client.get_profile_list(profile_id=int(profile_id), page=1, limit=1) or []
        except ValueError:
            batch = []
        if isinstance(batch, dict):
            data = batch.get("data") or batch.get("list") or []
            batch = data if isinstance(data, list) else []
        for row in batch:
            if not isinstance(row, dict):
                continue
            found_id = str(row.get("profile_id") or row.get("id") or "")
            if found_id and found_id not in seen:
                rows.append(row)
                seen.add(found_id)
    return rows


def list_proxy_rows(client: Any, proxy_ids: set[str], max_pages: int) -> list[dict[str, Any]]:
    if not proxy_ids:
        return list_pages(client, "get_proxy_list", limit=100, max_pages=min(max_pages, 2))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for proxy_id in sorted(proxy_ids):
        try:
            batch = client.get_proxy_list(id=int(proxy_id), page=1, limit=1) or []
        except ValueError:
            batch = []
        if isinstance(batch, dict):
            data = batch.get("data") or batch.get("list") or []
            batch = data if isinstance(data, list) else []
        for row in batch:
            if not isinstance(row, dict):
                continue
            found_id = str(row.get("id") or row.get("proxy_id") or "")
            if found_id and found_id not in seen:
                rows.append(row)
                seen.add(found_id)
    return rows


def build_report(
    *,
    client: Any | None = None,
    profile_ids: list[str] | None = None,
    group_name: str = "",
    max_pages: int = 50,
    profile_limit: int = 200,
    reveal_secrets: bool = False,
) -> dict[str, Any]:
    try:
        if client is None:
            from ReachOps.workbench.standalone_app import create_ixbrowser_client

            client = create_ixbrowser_client()
        wanted_ids = {str(item) for item in (profile_ids or []) if str(item).strip()}
        groups_raw = list_pages(client, "get_group_list", limit=100, max_pages=max_pages)
        wanted_group = str(group_name or "").strip().lower()
        matched_group_id = ""
        for group in groups_raw:
            group_label = str(group.get("title") or group.get("group_name") or group.get("name") or "").strip().lower()
            if wanted_group and group_label == wanted_group:
                matched_group_id = str(group.get("id") or group.get("group_id") or "").strip()
                break
        profiles_raw = list_profile_rows(client, wanted_ids, profile_limit, max_pages, group_id=matched_group_id)
        proxy_ids = {str(row.get("proxy_id") or "") for row in profiles_raw if str(row.get("proxy_id") or "").strip()}
        proxies_raw = list_proxy_rows(client, proxy_ids, max_pages)
    except Exception as exc:
        return {
            "status": "error",
            "safe_read_only": True,
            "open_profile_called": False,
            "error_code": "IXBROWSER_METADATA_READ_FAILED",
            "error_message": f"{exc.__class__.__name__}: {exc}",
        }

    profiles_by_id = {str(row.get("profile_id") or row.get("id") or ""): row for row in profiles_raw}
    proxies_by_id = {str(row.get("id") or row.get("proxy_id") or ""): row for row in proxies_raw}
    selected_profile_total: int | None = None
    if wanted_group and matched_group_id:
        try:
            from ReachOps.workbench.standalone_app import load_ixbrowser_group_profile_count

            selected_profile_total = load_ixbrowser_group_profile_count(matched_group_id, max_pages=1, limit=1)
        except Exception:
            selected_profile_total = None

    selected_profiles = []
    for profile_id, row in profiles_by_id.items():
        if wanted_ids and profile_id not in wanted_ids:
            continue
        if wanted_group and str(row.get("group_name") or "").strip().lower() != wanted_group:
            continue
        selected_profiles.append(row)

    missing_profile_ids = sorted(wanted_ids.difference(profiles_by_id)) if wanted_ids else []
    proxy_mode_counts = Counter(str(row.get("proxy_mode") or "") for row in selected_profiles)
    proxy_type_counts = Counter(str(row.get("proxy_type") or "") for row in selected_profiles)
    selected_rows = []
    for row in selected_profiles:
        proxy_id = str(row.get("proxy_id") or "")
        selected_rows.append(
            {
                "profile": copy_fields(row, PROFILE_FIELDS, reveal_secrets=reveal_secrets),
                "proxy": copy_fields(proxies_by_id.get(proxy_id, {}), PROXY_FIELDS, reveal_secrets=reveal_secrets),
                "proxy_metadata_found": bool(proxy_id and proxy_id in proxies_by_id),
            }
        )

    original_group_counts = {
        str(row.get("id") or row.get("group_id") or ""): int(row.get("count") or row.get("profile_count") or 0)
        for row in groups_raw
        if str(row.get("id") or row.get("group_id") or "")
    }
    groups = [normalize_group(row) for row in groups_raw]
    try:
        from ReachOps.workbench.standalone_app import resolve_ixbrowser_group_counts

        groups = [
            {
                **group,
                "count": int(group.get("profile_count") or 0),
            }
            for group in groups
        ]
        resolved_groups = resolve_ixbrowser_group_counts(groups, max_workers=1, timeout_seconds=75.0)
        groups = [
            {
                **group,
                "profile_count": int(group.get("count") or group.get("profile_count") or 0),
                "count_known": bool(group.get("count_known")),
                "count_source": str(group.get("count_source") or ("ixbrowser_profile_list" if group.get("count_known") else "")),
            }
            for group in (resolved_groups or groups)
        ]
    except Exception:
        pass
    selected_profile_count = int(selected_profile_total) if selected_profile_total is not None else len(selected_rows)
    if matched_group_id and selected_profile_count > 0:
        for group in groups:
            if str(group.get("group_id") or "") == matched_group_id:
                group["profile_count"] = selected_profile_count
                group["count_known"] = True
                group["count_source"] = "selected_group_profile_list"
            elif (
                wanted_group
                and selected_profile_total is not None
                and int(group.get("profile_count") or 0) == selected_profile_count
                and int(original_group_counts.get(str(group.get("group_id") or ""), 0) or 0) == 0
            ):
                group["profile_count"] = 0
                group["count_known"] = False
                group["count_source"] = ""
    elif not wanted_ids:
        counts_by_id: Counter[str] = Counter(str(row.get("group_id") or "") for row in profiles_raw if str(row.get("group_id") or ""))
        counts_by_name: Counter[str] = Counter(str(row.get("group_name") or "") for row in profiles_raw if str(row.get("group_name") or ""))
        for group in groups:
            group_id = str(group.get("group_id") or "")
            group_name = str(group.get("group_name") or "")
            count = int(counts_by_id.get(group_id) or counts_by_name.get(group_name) or group.get("profile_count") or 0)
            if count > 0:
                group["profile_count"] = count
                group["count_known"] = True
                group["count_source"] = group.get("count_source") or "profile_list_sample"
    known_profile_total = sum(int(group.get("profile_count") or 0) for group in groups if group.get("count_known"))
    return {
        "status": "ok",
        "safe_read_only": True,
        "secret_disclosure_disabled": True,
        "open_profile_called": False,
        "profile_count": max(len(profiles_raw), known_profile_total),
        "group_count": len(groups_raw),
        "known_group_count": len([group for group in groups if group.get("count_known")]),
        "all_group_counts_known": bool(groups) and all(bool(group.get("count_known")) for group in groups),
        "proxy_count": len(proxies_raw),
        "selected_profile_count": selected_profile_count,
        "selected_profile_sample_count": len(selected_rows),
        "selected_group_id": matched_group_id,
        "missing_profile_ids": missing_profile_ids,
        "profile_ids_filter": sorted(wanted_ids),
        "group_name_filter": group_name,
        "proxy_mode_counts": dict(proxy_mode_counts),
        "proxy_type_counts": dict(proxy_type_counts),
        "groups": groups[:100],
        "selected_profiles": selected_rows,
        "available_profile_ids_sample": sorted(profiles_by_id)[:100],
        "notes": [
            "This report only calls ixBrowser list APIs and never opens a profile.",
            "Proxy usernames, passwords, account usernames, and account passwords are always redacted.",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only ixBrowser profile/group/proxy metadata report for ReachOps live validation.")
    parser.add_argument("--profile-ids", default="", help="Comma-separated ixBrowser numeric profile ids to inspect.")
    parser.add_argument("--group-name", default="", help="Optional ixBrowser group name filter.")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--profile-limit", type=int, default=200)
    parser.add_argument(
        "--reveal-secrets",
        action="store_true",
        help="Deprecated compatibility flag; ReachOps always redacts proxy/account secret fields.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        profile_ids=split_csv(args.profile_ids),
        group_name=args.group_name,
        max_pages=args.max_pages,
        profile_limit=args.profile_limit,
        reveal_secrets=bool(args.reveal_secrets),
    )
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())

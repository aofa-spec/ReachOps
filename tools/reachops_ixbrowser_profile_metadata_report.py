# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SECRET_KEYS = {"proxy_user", "proxy_password", "username", "password", "tfa_secret"}
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
    if reveal_secrets or key not in SECRET_KEYS:
        return value
    text = str(value or "")
    if not text:
        return ""
    return "***redacted***"


def copy_fields(row: dict[str, Any], fields: tuple[str, ...], reveal_secrets: bool = False) -> dict[str, Any]:
    return {field: redact_value(field, row.get(field, ""), reveal_secrets) for field in fields if field in row}


def normalize_group(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "group_id": str(row.get("id") or row.get("group_id") or ""),
        "group_name": str(row.get("title") or row.get("group_name") or row.get("name") or ""),
        "profile_count": int(row.get("count") or row.get("profile_count") or 0),
    }


def list_pages(client: Any, method_name: str, limit: int = 100, max_pages: int = 50, **kwargs: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max(1, int(max_pages or 50)) + 1):
        batch = getattr(client, method_name)(page=page, limit=max(1, int(limit or 100)), **kwargs) or []
        if isinstance(batch, dict):
            data = batch.get("data") or batch.get("list") or []
            batch = data if isinstance(data, list) else []
        batch_rows = [item for item in batch if isinstance(item, dict)]
        rows.extend(batch_rows)
        if len(batch_rows) < max(1, int(limit or 100)):
            break
    return rows


def list_profile_rows(client: Any, profile_ids: set[str], profile_limit: int, max_pages: int) -> list[dict[str, Any]]:
    if not profile_ids:
        return list_pages(client, "get_profile_list", limit=min(max(1, int(profile_limit or 200)), 100), max_pages=max_pages)
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
            from ixbrowser_local_api import IXBrowserClient

            client = IXBrowserClient()
        wanted_ids = {str(item) for item in (profile_ids or []) if str(item).strip()}
        groups_raw = list_pages(client, "get_group_list", limit=100, max_pages=max_pages)
        profiles_raw = list_profile_rows(client, wanted_ids, profile_limit, max_pages)
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

    wanted_group = str(group_name or "").strip().lower()
    profiles_by_id = {str(row.get("profile_id") or row.get("id") or ""): row for row in profiles_raw}
    proxies_by_id = {str(row.get("id") or row.get("proxy_id") or ""): row for row in proxies_raw}

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

    groups = [normalize_group(row) for row in groups_raw]
    return {
        "status": "ok",
        "safe_read_only": True,
        "open_profile_called": False,
        "profile_count": len(profiles_raw),
        "group_count": len(groups_raw),
        "proxy_count": len(proxies_raw),
        "selected_profile_count": len(selected_rows),
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
            "Proxy usernames, passwords, account usernames, and account passwords are redacted by default.",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only ixBrowser profile/group/proxy metadata report for ReachOps live validation.")
    parser.add_argument("--profile-ids", default="", help="Comma-separated ixBrowser numeric profile ids to inspect.")
    parser.add_argument("--group-name", default="", help="Optional ixBrowser group name filter.")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--profile-limit", type=int, default=200)
    parser.add_argument("--reveal-secrets", action="store_true", help="Print proxy/account secret fields. Off by default.")
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

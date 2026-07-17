# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import sys
import threading
import tkinter as tk
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import simpledialog, ttk
from urllib.parse import urlparse

from ReachOps.execution_plan import build_execution_plan, write_execution_plan
from ReachOps.client_operator_summary import attach_client_operator_summary
from ReachOps.intelligence import GrowthIntelligenceService, GrowthTaskConfig
from ReachOps.intelligence.schemas import ActionQueueItem
from ReachOps.intelligence.storage import new_id
from ReachOps.run_session import create_run_session, read_run_session, transition_run_session, write_run_session
from ReachOps.runtime_paths import RuntimePaths

from .console import GrowthOpsConsole, normalize_source_type, quick_send_mode_key, quick_send_preset
from .workflow_service import GrowthWorkflowService

APP_COLORS = {
    "bg": "#1f2327",
    "surface": "#2b3036",
    "border": "#59616a",
    "text": "#ffffff",
    "muted": "#d1d5db",
    "accent": "#4b5563",
    "accent_soft": "#343a40",
    "terminal_bg": "#0c0d0e",
    "terminal_text": "#d1d5db",
    "terminal_info": "#60a5fa",
    "terminal_success": "#22c55e",
    "terminal_warning": "#fbbf24",
    "terminal_error": "#f87171",
}


def ui_font(size: int = 10, weight: str = "normal"):
    family = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
    if weight and weight != "normal":
        return (family, size, weight)
    return (family, size)


def default_growth_base_dir(cwd: str | None = None) -> str:
    """Return the standalone Growth Intelligence data directory."""

    return RuntimePaths.build(cwd=cwd).base_dir


def profile_matches_group(profile: dict, group_name: str) -> bool:
    requested = _tokens(group_name)
    if not requested:
        return True
    target = _tokens(
        " ".join(
            str(profile.get(key) or "")
            for key in ["profile_id", "id", "name", "profile_name", "title", "group_id", "group_name", "tag", "usage", "purpose"]
        )
    )
    if len(requested) == 1:
        return bool(requested & target)
    return requested.issubset(target)


def _tokens(value: str) -> set[str]:
    tokens = set()
    for part in str(value or "").replace("_", " ").replace("-", " ").replace("/", " ").split():
        clean = "".join(ch for ch in part.lower() if ch.isalnum())
        if clean:
            tokens.add(clean)
    return tokens


def parse_keyword_list(value: str) -> list[str]:
    items = []
    seen = set()
    for part in str(value or "").replace("，", ",").replace("；", ",").replace(";", ",").replace("\n", ",").split(","):
        keyword = part.strip()
        if not keyword or keyword.lower() in seen:
            continue
        seen.add(keyword.lower())
        items.append(keyword)
    return items


def normalize_ixbrowser_profile(row: dict) -> dict:
    return {
        "profile_id": str(row.get("profile_id") or row.get("profileId") or row.get("browser_id") or row.get("id") or ""),
        "name": row.get("name") or row.get("profile_name") or row.get("profileName") or row.get("title") or "",
        "group_id": str(row.get("group_id") or row.get("groupId") or row.get("group") or ""),
        "group_name": str(row.get("group_name") or row.get("groupName") or row.get("group_title") or row.get("groupTitle") or ""),
    }


def normalize_ixbrowser_group(row: dict) -> dict:
    count_keys = ["count", "profile_count", "profileCount", "profile_num", "profileNum", "profileNumber", "browser_count", "browserCount"]
    count_value = None
    for key in count_keys:
        if key in row and row.get(key) not in {None, ""}:
            count_value = row.get(key)
            break
    try:
        count = int(count_value) if count_value is not None else 0
    except Exception:
        count = 0
    return {
        "group_id": str(row.get("group_id") or row.get("groupId") or row.get("id") or ""),
        "group_name": str(
            row.get("group_name")
            or row.get("groupName")
            or row.get("group_title")
            or row.get("groupTitle")
            or row.get("title")
            or row.get("name")
            or row.get("id")
            or "未分组"
        ),
        "count": count,
        "count_known": count_value is not None,
    }


def extract_ixbrowser_rows(response) -> tuple[list[dict], int]:
    """Normalize ixBrowser list responses that may be a bare list or a wrapped dict."""

    total = 0
    rows = response
    if isinstance(response, dict):
        for key in ("total", "total_count", "totalCount", "count"):
            try:
                value = response.get(key)
                if value not in {None, ""}:
                    total = int(value)
                    break
            except Exception:
                total = 0
        data = response.get("data")
        if isinstance(data, dict):
            for key in ("list", "rows", "items", "records", "data"):
                candidate = data.get(key)
                if isinstance(candidate, list):
                    rows = candidate
                    break
            else:
                rows = []
            if not total:
                for key in ("total", "total_count", "totalCount", "count"):
                    try:
                        value = data.get(key)
                        if value not in {None, ""}:
                            total = int(value)
                            break
                    except Exception:
                        total = 0
        elif isinstance(data, list):
            rows = data
        else:
            for key in ("list", "rows", "items", "records"):
                candidate = response.get(key)
                if isinstance(candidate, list):
                    rows = candidate
                    break
            else:
                rows = []
    if not isinstance(rows, list):
        rows = []
    return [row for row in rows if isinstance(row, dict)], total


def summarize_profile_groups(profiles: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for profile in profiles or []:
        group_name = str(profile.get("group_name") or profile.get("group_id") or "未分组")
        group_id = str(profile.get("group_id") or group_name)
        key = f"{group_id}:{group_name}"
        item = grouped.setdefault(key, {"group_id": group_id, "group_name": group_name, "count": 0, "count_known": True})
        item["count"] += 1
    groups = sorted(grouped.values(), key=lambda row: (str(row.get("group_name") or ""), str(row.get("group_id") or "")))
    if profiles:
        groups.insert(
            0,
            {
                "group_id": "",
                "group_name": "全部配置",
                "count": len(profiles),
                "count_known": True,
                "all_profiles": True,
            },
        )
    return groups


def group_display_name(group: dict) -> str:
    name = group_display_label(group)
    group_id = str(group.get("group_id") or "").strip()
    count = int(group.get("count") or 0)
    if group.get("count_known") or count > 0:
        count_label = "9999+" if count > 9999 else str(count)
    else:
        count_label = "读取中"
    return f"{name} · {count_label} 个账号 · ID: {group_id or '-'}"


def group_display_label(group: dict) -> str:
    name = sanitize_tk_text(str(group.get("group_name") or ""))
    group_id = str(group.get("group_id") or "").strip()
    if name and "?" not in name:
        return name
    if name and not group_id:
        return name
    if group_id:
        return f"分组 {group_id}"
    return "未分组"


def group_safe_label(group: dict) -> str:
    name = sanitize_tk_text(str(group.get("group_name") or ""))
    group_id = str(group.get("group_id") or "").strip()
    if name and all(ord(ch) < 128 for ch in name):
        return name
    if group_id:
        return f"Group {group_id}"
    return "Ungrouped"


def sanitize_tk_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("\ufffd", "?")
    text = "".join(ch if (ch == "\t" or ord(ch) >= 32) else " " for ch in text)
    return text.strip()


def configure_ixbrowser_local_api_env():
    bypass_hosts = ["127.0.0.1", "localhost", "::1"]
    for key in ("NO_PROXY", "no_proxy"):
        existing = [item.strip() for item in str(os.environ.get(key) or "").split(",") if item.strip()]
        merged = list(existing)
        for host in bypass_hosts:
            if host not in merged:
                merged.append(host)
        os.environ[key] = ",".join(merged)


def create_ixbrowser_client():
    configure_ixbrowser_local_api_env()
    from ixbrowser_local_api import IXBrowserClient

    target = str(os.environ.get("REACHOPS_IXBROWSER_API_TARGET") or "127.0.0.1").strip() or "127.0.0.1"
    raw_port = str(os.environ.get("REACHOPS_IXBROWSER_API_PORT") or os.environ.get("IXBROWSER_API_PORT") or "").strip()
    try:
        if raw_port:
            return IXBrowserClient(target=target, port=int(raw_port))
        return IXBrowserClient(target=target)
    except TypeError:
        return IXBrowserClient()


def require_ixbrowser_response(client, response, action: str):
    if response is not None:
        return response
    code = getattr(client, "code", None)
    message = getattr(client, "message", None) or "ixBrowser Local API did not return data"
    base_url = getattr(client, "base_url", "ixBrowser Local API")
    raise RuntimeError(f"{action}_unavailable base_url={base_url} code={code or '-'} message={message}")


def load_reachops_client_config(paths: RuntimePaths) -> dict:
    config_path = Path(paths.config_dir) / "reachops_client_config.json"
    defaults = {
        "ixbrowser": {
            "api_target": "127.0.0.1",
            "api_port": "",
            "refresh_max_pages": 50,
        },
        "ai": {
            "endpoint": "",
            "model": "reachops-default",
            "provider_name": "",
            "timeout_seconds": 20,
        },
    }
    if not config_path.exists():
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return {"path": str(config_path), "created": True, "config": defaults}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8") or "{}")
    except Exception:
        payload = {}
    config = dict(defaults)
    for section in ("ixbrowser", "ai"):
        if isinstance(payload.get(section), dict):
            merged = dict(config.get(section) or {})
            merged.update(payload.get(section) or {})
            config[section] = merged
    return {"path": str(config_path), "created": False, "config": config}


def apply_reachops_client_config(config: dict):
    ixbrowser = config.get("ixbrowser") if isinstance(config.get("ixbrowser"), dict) else {}
    ai = config.get("ai") if isinstance(config.get("ai"), dict) else {}
    mappings = {
        "REACHOPS_IXBROWSER_API_TARGET": ixbrowser.get("api_target"),
        "REACHOPS_IXBROWSER_API_PORT": ixbrowser.get("api_port"),
        "REACHOPS_IXBROWSER_REFRESH_MAX_PAGES": ixbrowser.get("refresh_max_pages"),
        "REACHOPS_AI_ENDPOINT": ai.get("endpoint"),
        "REACHOPS_AI_MODEL": ai.get("model"),
        "REACHOPS_AI_PROVIDER_NAME": ai.get("provider_name"),
        "REACHOPS_AI_TIMEOUT_SECONDS": ai.get("timeout_seconds"),
    }
    for key, value in mappings.items():
        text = str(value or "").strip()
        if text and not str(os.environ.get(key) or "").strip():
            os.environ[key] = text


def stable_combobox_values(values: list[str]) -> list[str]:
    stable = [sanitize_tk_text(item) for item in values or []]
    stable = [item for item in stable if item]
    return stable


def ixbrowser_refresh_max_pages(default: int = 50) -> int:
    raw = str(os.environ.get("REACHOPS_IXBROWSER_REFRESH_MAX_PAGES") or "").strip()
    if not raw:
        return max(1, int(default or 50))
    try:
        return max(1, min(int(raw), max(1, int(default or 50))))
    except ValueError:
        return max(1, int(default or 50))


def group_name_from_display(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("[") and "] " in text:
        text = text.split("] ", 1)[1].strip()
    if " 个账号 | " in text or text.startswith("待读取账号数 | "):
        text = text.split(" | ", 1)[1].strip()
    if " · " in text:
        return text.split(" · ", 1)[0].strip()
    if text.endswith(")") and "(ID:" in text:
        return text.rsplit("(ID:", 1)[0].strip()
    if text.endswith(")") and "(" in text:
        return text.rsplit("(", 1)[0].strip()
    if " | ID " in text:
        return text.split(" | ID ", 1)[0].strip()
    return text


def load_ixbrowser_profile_rows(max_pages: int = 50, group_id: str | int = 0, limit: int = 100) -> list[dict]:
    client = create_ixbrowser_client()
    requested_group_id = str(group_id or "").strip()
    rows = []
    seen = set()
    consecutive_empty = 0
    total = 0
    for page in range(1, max(1, int(max_pages or 50)) + 1):
        kwargs = {"page": page, "limit": max(1, int(limit or 100))}
        if requested_group_id and requested_group_id != "0":
            kwargs["group_id"] = int(requested_group_id)
        response = None
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = require_ixbrowser_response(client, client.get_profile_list(**kwargs), "ixbrowser_profile_list")
                break
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(0.6 * attempt)
        if response is None:
            if page == 1 and last_error is not None:
                raise last_error
            break
        batch, response_total = extract_ixbrowser_rows(response)
        try:
            total = int(response_total or getattr(client, "total", 0) or total)
        except Exception:
            total = total
        if not batch:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            continue
        consecutive_empty = 0
        for row in batch:
            profile_id = str(row.get("profile_id") or row.get("profileId") or row.get("browser_id") or row.get("id") or "")
            if profile_id and profile_id in seen:
                continue
            if profile_id:
                seen.add(profile_id)
            rows.append(row)
        if total and len(seen) >= total:
            break
    return rows


def load_ixbrowser_group_rows(max_pages: int = 100, limit: int = 100) -> list[dict]:
    client = create_ixbrowser_client()
    rows = []
    seen = set()
    consecutive_empty = 0
    total = 0
    for page in range(1, max(1, int(max_pages or 100)) + 1):
        response = require_ixbrowser_response(
            client,
            client.get_group_list(page=page, limit=max(1, int(limit or 100))),
            "ixbrowser_group_list",
        )
        batch, response_total = extract_ixbrowser_rows(response)
        try:
            total = int(response_total or getattr(client, "total", 0) or total)
        except Exception:
            total = total
        if not batch:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            continue
        consecutive_empty = 0
        for row in batch:
            group_id = str(row.get("group_id") or row.get("id") or "")
            if group_id and group_id in seen:
                continue
            if group_id:
                seen.add(group_id)
            rows.append(row)
        if total and len(seen) >= total:
            break
    return rows


def load_ixbrowser_group_profile_count(group_id: str | int, max_pages: int = 50, limit: int = 100) -> int | None:
    requested_group_id = str(group_id or "").strip()
    if not requested_group_id:
        return 0
    client = create_ixbrowser_client()
    rows = []
    seen = set()
    consecutive_empty = 0
    total = 0
    for page in range(1, max(1, int(max_pages or 50)) + 1):
        response = None
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = require_ixbrowser_response(
                    client,
                    client.get_profile_list(page=page, limit=max(1, int(limit or 100)), group_id=int(requested_group_id or 0)),
                    "ixbrowser_group_profile_list",
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(0.6 * attempt)
        if response is None:
            if page == 1:
                return None
            break
        batch, response_total = extract_ixbrowser_rows(response)
        try:
            total = int(response_total or getattr(client, "total", 0) or total)
        except Exception:
            total = total
        if total and page == 1 and batch and all(str(row.get("group_id") or row.get("groupId") or row.get("group") or "") == requested_group_id for row in batch):
            return total
        if not batch:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            continue
        consecutive_empty = 0
        for row in batch:
            profile_id = str(row.get("profile_id") or row.get("profileId") or row.get("browser_id") or row.get("id") or "")
            if profile_id and profile_id in seen:
                continue
            if profile_id:
                seen.add(profile_id)
            rows.append(row)
    if not rows:
        return None
    if any(str(row.get("group_id") or row.get("groupId") or row.get("group") or "") != requested_group_id for row in rows):
        return None
    if len(rows) < max(1, int(limit or 100)) * max(1, int(max_pages or 50)):
        return len(rows)
    return None


def resolve_ixbrowser_group_counts_from_profiles(groups: list[dict], max_pages: int = 50, limit: int = 100) -> list[dict]:
    profiles = [
        normalize_ixbrowser_profile(row)
        for row in load_ixbrowser_profile_rows(max_pages=max_pages, limit=limit)
    ]
    counts_by_id: dict[str, int] = {}
    counts_by_name: dict[str, int] = {}
    for profile in profiles:
        group_id = str(profile.get("group_id") or "").strip()
        group_name = str(profile.get("group_name") or "").strip()
        if group_id:
            counts_by_id[group_id] = counts_by_id.get(group_id, 0) + 1
        if group_name:
            counts_by_name[group_name] = counts_by_name.get(group_name, 0) + 1
    for group in groups or []:
        group_id = str(group.get("group_id") or "").strip()
        group_name = str(group.get("group_name") or "").strip()
        if group_id in counts_by_id:
            group["count"] = counts_by_id[group_id]
            group["count_known"] = True
        elif group_name in counts_by_name:
            group["count"] = counts_by_name[group_name]
            group["count_known"] = True
        elif profiles:
            group["count"] = 0
            group["count_known"] = True
    return groups


def resolve_ixbrowser_group_counts(groups: list[dict], max_workers: int = 2, timeout_seconds: float = 45.0) -> list[dict]:
    pending = [group for group in groups or [] if group.get("group_id")]
    if not pending:
        return groups
    deadline = time.monotonic() + max(1.0, float(timeout_seconds or 25.0))

    def remaining_timeout() -> float:
        return max(0.0, deadline - time.monotonic())

    executor = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers or 8), len(pending))))
    futures = {
        executor.submit(load_ixbrowser_group_profile_count, group.get("group_id"), ixbrowser_refresh_max_pages(50), 1): group
        for group in pending
    }
    try:
        for future in as_completed(futures, timeout=max(0.5, remaining_timeout())):
            group = futures[future]
            try:
                count = future.result()
                if count is not None:
                    group["count"] = int(count)
                    group["count_known"] = True
            except Exception:
                group["count"] = int(group.get("count") or 0)
    except FuturesTimeoutError:
        pass
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    pending = [group for group in groups or [] if group.get("group_id") and not group.get("count_known")]
    if not pending:
        return groups
    if remaining_timeout() <= 0:
        return groups
    scan_executor = ThreadPoolExecutor(max_workers=1)
    scan_future = scan_executor.submit(
        resolve_ixbrowser_group_counts_from_profiles,
        [dict(group) for group in groups],
        ixbrowser_refresh_max_pages(50),
        100,
    )
    try:
        scanned_groups = scan_future.result(timeout=max(0.5, remaining_timeout()))
        if scanned_groups and all(group.get("count_known") for group in scanned_groups if group.get("group_id")):
            return scanned_groups
        groups = scanned_groups or groups
    except Exception:
        scan_future.cancel()
    finally:
        scan_executor.shutdown(wait=False, cancel_futures=True)

    pending = [group for group in groups or [] if group.get("group_id") and not group.get("count_known")]
    if not pending:
        return groups
    if remaining_timeout() <= 0:
        return groups
    executor = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers or 8), len(pending))))
    futures = {
        executor.submit(load_ixbrowser_group_profile_count, group.get("group_id"), ixbrowser_refresh_max_pages(50), 100): group
        for group in pending
    }
    try:
        for future in as_completed(futures, timeout=max(0.5, remaining_timeout())):
            group = futures[future]
            try:
                count = future.result()
                if count is not None:
                    group["count"] = int(count)
                    group["count_known"] = True
            except Exception:
                group["count"] = int(group.get("count") or 0)
    except FuturesTimeoutError:
        pass
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return groups


def load_ixbrowser_profile_snapshot(max_pages: int = 50, resolve_group_counts: bool = False, include_profiles: bool = True) -> dict:
    max_pages = ixbrowser_refresh_max_pages(max_pages)
    profiles = []
    if include_profiles:
        profiles = [
            normalize_ixbrowser_profile(row)
            for row in load_ixbrowser_profile_rows(max_pages=max_pages)
            if row.get("profile_id") or row.get("profileId") or row.get("browser_id") or row.get("id")
        ]
    profile_groups = summarize_profile_groups(profiles)
    profile_counts = {}
    for row in profile_groups:
        count = int(row.get("count") or 0)
        group_id = str(row.get("group_id") or "")
        group_name = str(row.get("group_name") or "")
        if group_id:
            profile_counts[group_id] = count
        if group_name:
            profile_counts[group_name] = count
    groups = list(profile_groups)
    seen_groups = set()
    for group in groups:
        key = str(group.get("group_id") or group.get("group_name") or "")
        if key:
            seen_groups.add(key)
    for group in [normalize_ixbrowser_group(row) for row in load_ixbrowser_group_rows(max_pages=max_pages)]:
        key = str(group.get("group_id") or group.get("group_name") or "")
        if not key or key in seen_groups:
            continue
        group_id = str(group.get("group_id") or "")
        group_name = str(group.get("group_name") or "")
        count_from_profiles = group_id in profile_counts or group_name in profile_counts
        resolved_count = profile_counts.get(group_id, profile_counts.get(group_name, int(group.get("count") or 0)))
        if profile_counts and not count_from_profiles and int(resolved_count or 0) > 0:
            continue
        group["count"] = resolved_count
        if count_from_profiles:
            group["count_known"] = True
        groups.append(group)
        seen_groups.add(key)
    all_profile_groups = [group for group in groups if group.get("all_profiles")]
    regular_groups = [group for group in groups if not group.get("all_profiles")]
    regular_groups = sorted(regular_groups, key=lambda row: (str(row.get("group_name") or ""), str(row.get("group_id") or "")))
    groups = all_profile_groups + regular_groups
    if resolve_group_counts:
        groups = resolve_ixbrowser_group_counts(groups)
    return {
        "profiles": profiles,
        "groups": groups,
        "profile_count": len(profiles),
        "group_count": len(groups),
        "profiles_deferred": not include_profiles,
        "counts_resolved": bool(resolve_group_counts),
    }


class StandaloneProfileRegistry:
    """Standalone ixBrowser profile/group cache for Growth Intelligence."""

    def __init__(self):
        self.profiles: list[dict] = []
        self.groups: list[dict] = []
        self.group_by_name: dict[str, dict] = {}
        self.last_error = ""

    def refresh(self, max_pages: int = 50, include_profiles: bool = False, resolve_group_counts: bool = False) -> dict:
        snapshot = load_ixbrowser_profile_snapshot(
            max_pages=max_pages,
            resolve_group_counts=resolve_group_counts,
            include_profiles=include_profiles,
        )
        if include_profiles or snapshot.get("profiles"):
            self.profiles = list(snapshot["profiles"])
        snapshot_groups = list(snapshot["groups"])
        if snapshot_groups or not self.groups:
            self.groups = snapshot_groups
        self.group_by_name = {}
        for row in self.groups:
            name = str(row.get("group_name") or "")
            group_id = str(row.get("group_id") or "")
            if name:
                self.group_by_name[name] = row
                self.group_by_name[name.lower()] = row
            if group_id:
                self.group_by_name[group_id] = row
                self.group_by_name[f"group {group_id}"] = row
                self.group_by_name[group_safe_label(row).lower()] = row
        return snapshot

    def select_profiles(self, group_name: str = "", limit: int = 50) -> list[dict]:
        requested_group = str(group_name or "").strip()
        if not self.groups:
            try:
                self.refresh(include_profiles=False)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
        group = self.group_by_name.get(str(group_name or "")) or self.group_by_name.get(str(group_name or "").lower())
        group_id = str((group or {}).get("group_id") or "")
        if group_id and not (group or {}).get("all_profiles"):
            cached_profiles = [profile for profile in self.profiles if str(profile.get("group_id") or "") == group_id]
            if cached_profiles:
                group["count"] = len(cached_profiles)
                group["count_known"] = True
                return cached_profiles[: max(1, int(limit or 50))]
            try:
                rows = [
                    normalize_ixbrowser_profile(row)
                    for row in load_ixbrowser_profile_rows(
                        max_pages=ixbrowser_refresh_max_pages(5),
                        group_id=group_id,
                        limit=max(1, min(max(int(limit or 50), 100), 200)),
                    )
                ]
                for row in rows:
                    if not row.get("group_name"):
                        row["group_name"] = str((group or {}).get("group_name") or requested_group)
                if group is not None:
                    group["count"] = max(int(group.get("count") or 0), len(rows))
                    group["count_known"] = bool(group.get("count_known")) or bool(rows)
                existing = {str(row.get("profile_id") or ""): row for row in self.profiles if row.get("profile_id")}
                for row in rows:
                    profile_id = str(row.get("profile_id") or "")
                    if profile_id:
                        existing[profile_id] = row
                self.profiles = list(existing.values())
                self.last_error = ""
                return rows[: max(1, int(limit or 50))]
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return []
        if (group or {}).get("all_profiles") or requested_group in {"", "全部配置"}:
            try:
                self.refresh(include_profiles=True)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return []
            profiles = list(self.profiles)
        elif group_id:
            profiles = [profile for profile in self.profiles if str(profile.get("group_id") or "") == group_id]
            group["count"] = len(profiles)
            group["count_known"] = True
        else:
            if not self.profiles:
                try:
                    self.refresh(include_profiles=True)
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    return []
            profiles = [profile for profile in self.profiles if profile_matches_group(profile, group_name)]
        return profiles[: max(1, int(limit or 50))]


def load_ixbrowser_profiles(profile_group: str = "", max_pages: int = 50, limit: int = 50) -> list[dict]:
    """Best-effort ixBrowser profile loader for the standalone module."""

    snapshot = load_ixbrowser_profile_snapshot(max_pages=max_pages)
    profiles = [row for row in snapshot["profiles"] if profile_matches_group(row, profile_group)]
    return profiles[: max(1, int(limit or 50))]


class MacQuickConsole(tk.Frame):
    """Lightweight macOS console used when the full ttk workbench renders poorly."""

    def __init__(
        self,
        master,
        on_start_collection=None,
        on_export_report=None,
        on_refresh_profiles=None,
        operator_status_var=None,
    ):
        super().__init__(master, bg=APP_COLORS["bg"])
        self.on_start_collection = on_start_collection
        self.on_export_report = on_export_report
        self.on_refresh_profiles = on_refresh_profiles
        self.operator_status_var = operator_status_var or tk.StringVar(value="已就绪")
        self.scan_source_type_var = tk.StringVar(value="自动识别")
        self.scan_source_value_var = tk.StringVar(value="https://www.tiktok.com/@aofacore/video/7656416339531205901")
        self.scan_profile_group_var = tk.StringVar(value="")
        self.scan_profile_group_display_var = tk.StringVar(value="正在读取分组...")
        self.scan_profile_group_detail_var = tk.StringVar(value="当前账号分组：请刷新账号分组")
        self.quick_send_mode_var = tk.StringVar(value="采集 + 触达预检")
        self.quick_send_volume_var = tk.StringVar(value="快速")
        preset = quick_send_preset(self.quick_send_volume_var.get())
        self.scan_interval_var = tk.IntVar(value=int(preset["task_interval"]))
        self.scan_max_videos_var = tk.IntVar(value=int(preset["max_videos"]))
        self.scan_max_comments_var = tk.IntVar(value=int(preset["max_comments"]))
        self.scan_profile_limit_var = tk.IntVar(value=int(preset["profile_limit"]))
        self.scan_intent_keywords_var = tk.StringVar(value="price, buy, link, download, app, coupon")
        self.scan_exclude_keywords_var = tk.StringVar(value="haha, lol, spam")
        self.action_execution_mode_var = tk.StringVar(value="预检，不提交")
        self.action_execution_group_var = tk.StringVar(value="")
        self.action_execution_workers_var = tk.IntVar(value=int(preset["workers"]))
        self.action_execution_per_profile_var = tk.IntVar(value=5)
        self.action_execution_hour_limit_var = tk.IntVar(value=10)
        self.action_execution_video_hour_limit_var = tk.IntVar(value=1)
        self.action_execution_live_confirm_var = tk.BooleanVar(value=False)
        self.quick_comment_text_var = tk.StringVar(value="")
        self._group_values: list[str] = ["正在读取分组..."]
        self.target_button = None
        self.canvas = None
        self.plan_lines: list[str] = []
        self.runtime_lines: list[str] = []
        self._build()

    def _build(self):
        self._build_absolute_only()
        return

    def _build_absolute_only(self):
        dark_bg = APP_COLORS["bg"]
        text_fg = APP_COLORS["text"]
        control_bg = APP_COLORS["surface"]
        active_bg = APP_COLORS["accent_soft"]
        self.configure(bg=dark_bg)
        self.canvas = tk.Canvas(self, bg=dark_bg, highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas.bind("<Configure>", lambda _event: self._redraw_canvas())
        self.target_button = tk.Button(
            self,
            text=self._target_button_text(),
            command=self._set_target_from_dialog,
            bg=control_bg,
            fg=text_fg,
            activebackground=active_bg,
            activeforeground=text_fg,
            relief="flat",
            anchor="w",
        )
        self.target_button.place(x=120, y=76, width=650, height=36)
        self.group_menu = tk.OptionMenu(self, self.scan_profile_group_display_var, *self._group_values, command=lambda _v: self._on_group_changed())
        self.group_menu.configure(bg=control_bg, fg=text_fg, activebackground=active_bg, activeforeground=text_fg, relief="flat")
        self.group_menu.place(x=880, y=76, width=370, height=36)
        self.start_refresh_groups_button = tk.Button(self, text="刷新分组", command=self._refresh_profile_groups)
        self.start_refresh_groups_button.configure(bg=control_bg, fg=text_fg, activebackground=active_bg, activeforeground=text_fg, relief="flat")
        self.start_refresh_groups_button.place(x=1260, y=76, width=90, height=36)
        tk.Button(self, text="开始获客", command=self._start_collection, bg=APP_COLORS["accent"], fg=APP_COLORS["text"], activebackground=APP_COLORS["accent_soft"], activeforeground=APP_COLORS["text"], relief="flat", font=ui_font(12, "bold")).place(x=1360, y=76, width=140, height=36)
        mode_menu = tk.OptionMenu(self, self.quick_send_mode_var, "只采集", "采集 + 触达预检", "采集 + 真实评论", command=lambda _v: self.apply_quick_send_preset())
        mode_menu.configure(bg=control_bg, fg=text_fg, activebackground=active_bg, activeforeground=text_fg, relief="flat")
        mode_menu.place(x=120, y=150, width=190, height=32)
        volume_menu = tk.OptionMenu(self, self.quick_send_volume_var, "快速", "标准", "压测", command=lambda _v: self.apply_quick_send_preset())
        volume_menu.configure(bg=control_bg, fg=text_fg, activebackground=active_bg, activeforeground=text_fg, relief="flat")
        volume_menu.place(x=330, y=150, width=100, height=32)
        self.target_button.lift()
        self.group_menu.lift()
        self.start_refresh_groups_button.lift()
        self.show_campaign_plan({})
        self.append_runtime_log("READY  等待任务。输入目标后点击开始获客。")
        return

    def _redraw_canvas(self):
        if not self.canvas:
            return
        c = self.canvas
        c.delete("all")
        dark_bg = APP_COLORS["bg"]
        panel_bg = APP_COLORS["surface"]
        panel_border = APP_COLORS["border"]
        text_fg = APP_COLORS["text"]
        muted_fg = APP_COLORS["muted"]
        width = max(1280, int(c.winfo_width() or 1500))
        c.create_rectangle(0, 0, width, 920, fill=dark_bg, outline=dark_bg)
        c.create_text(24, 32, text="目标快发", fill=text_fg, font=ui_font(18, "bold"), anchor="w")
        c.create_text(width - 24, 34, text=self.operator_status_var.get(), fill=muted_fg, font=ui_font(10), anchor="e")
        c.create_text(28, 94, text="推广目标", fill=text_fg, font=ui_font(12, "bold"), anchor="w")
        c.create_text(790, 94, text="账号分组", fill=text_fg, font=ui_font(12, "bold"), anchor="w")
        c.create_text(120, 132, text=self.scan_profile_group_detail_var.get(), fill=muted_fg, font=ui_font(10), anchor="w")
        c.create_text(28, 166, text="执行模式", fill=text_fg, font=ui_font(11), anchor="w")
        c.create_text(282, 166, text="目标数量", fill=text_fg, font=ui_font(11), anchor="w")
        c.create_text(455, 166, text=f"视频 {self.scan_max_videos_var.get()} / 评论 {self.scan_max_comments_var.get()} / 账号 {self.scan_profile_limit_var.get()} / 间隔 {self.scan_interval_var.get()}s", fill=muted_fg, font=ui_font(10), anchor="w")
        c.create_rectangle(28, 200, 458, 850, fill=panel_bg, outline=panel_border)
        c.create_rectangle(476, 200, width - 28, 850, fill=panel_bg, outline=panel_border)
        c.create_text(44, 222, text="自动采集方案", fill=text_fg, font=ui_font(12, "bold"), anchor="w")
        c.create_text(492, 222, text="实时执行日志", fill=text_fg, font=ui_font(12, "bold"), anchor="w")
        y = 252
        for line in self.plan_lines[:24]:
            c.create_text(44, y, text=line, fill=text_fg, font=ui_font(10), anchor="w", width=390)
            y += 24
        y = 252
        visible_log = self.runtime_lines[-24:]
        for line in visible_log:
            color = self._runtime_line_color(line)
            c.create_text(492, y, text=line, fill=color, font=("Menlo", 10), anchor="w", width=max(600, width - 545))
            y += 24

    def _runtime_line_color(self, line: str) -> str:
        text = str(line or "").lower()
        if any(token in text for token in ["error", "failed", "失败", "异常", "block", "captcha", "login_required", "proxy"]):
            return APP_COLORS["terminal_error"]
        if any(token in text for token in ["warn", "warning", "跳过", "skipped", "retry", "cooldown"]):
            return APP_COLORS["terminal_warning"]
        if any(token in text for token in ["done", "success", "passed", "ready", "ok", "成功", "完成", "通过"]):
            return APP_COLORS["terminal_success"]
        if any(token in text for token in ["plan", "start", "check", "config", "run", "touch", "video", "queue"]):
            return APP_COLORS["terminal_info"]
        return APP_COLORS["terminal_text"]

    def _place_operable_controls(self):
        dark_bg = APP_COLORS["bg"]
        text_fg = APP_COLORS["text"]
        self.place_target_label = tk.Label(self, text="推广目标", bg=dark_bg, fg=text_fg, font=ui_font(12, "bold"))
        self.place_target_label.place(x=28, y=86, width=90, height=30)
        self.place_target_entry = tk.Entry(
            self,
            textvariable=self.scan_source_value_var,
            bg=APP_COLORS["surface"],
            fg=APP_COLORS["text"],
            insertbackground=APP_COLORS["text"],
            relief="solid",
            bd=1,
            font=ui_font(12),
        )
        self.place_target_entry.place(x=120, y=86, width=680, height=34)
        self.place_group_label = tk.Label(self, text="账号分组", bg=dark_bg, fg=text_fg, font=ui_font(12, "bold"))
        self.place_group_label.place(x=820, y=86, width=90, height=30)
        self.place_group_menu = tk.OptionMenu(self, self.scan_profile_group_display_var, *self._group_values, command=lambda _v: self._on_group_changed())
        self.place_group_menu.configure(bg=APP_COLORS["surface"], fg=text_fg, activebackground=APP_COLORS["accent_soft"], activeforeground=text_fg, relief="flat")
        self.place_group_menu.place(x=915, y=86, width=360, height=34)
        self.place_refresh_button = tk.Button(self, text="刷新分组", command=self._refresh_profile_groups, bg=APP_COLORS["surface"], fg=text_fg, relief="flat")
        self.place_refresh_button.place(x=1290, y=86, width=92, height=34)
        self.place_start_button = tk.Button(self, text="开始获客", command=self._start_collection, bg=APP_COLORS["accent"], fg=APP_COLORS["text"], relief="flat", font=ui_font(12, "bold"))
        self.place_start_button.place(x=1392, y=86, width=120, height=34)
        self.place_mode_label = tk.Label(self, text="模式", bg=dark_bg, fg=text_fg)
        self.place_mode_label.place(x=28, y=136, width=50, height=28)
        self.place_mode_menu = tk.OptionMenu(self, self.quick_send_mode_var, "只采集", "采集 + 触达预检", "采集 + 真实评论", command=lambda _v: self.apply_quick_send_preset())
        self.place_mode_menu.configure(bg=APP_COLORS["surface"], fg=text_fg, activebackground=APP_COLORS["accent_soft"], activeforeground=text_fg, relief="flat")
        self.place_mode_menu.place(x=82, y=136, width=180, height=30)
        self.place_volume_label = tk.Label(self, text="数量", bg=dark_bg, fg=text_fg)
        self.place_volume_label.place(x=282, y=136, width=50, height=28)
        self.place_volume_menu = tk.OptionMenu(self, self.quick_send_volume_var, "快速", "标准", "压测", command=lambda _v: self.apply_quick_send_preset())
        self.place_volume_menu.configure(bg=APP_COLORS["surface"], fg=text_fg, activebackground=APP_COLORS["accent_soft"], activeforeground=text_fg, relief="flat")
        self.place_volume_menu.place(x=336, y=136, width=100, height=30)
        self.campaign_plan_text.place(x=28, y=186, width=430, height=650)
        self.runtime_log_text.place(x=476, y=186, width=1036, height=650)

    def apply_quick_send_preset(self):
        preset = quick_send_preset(self.quick_send_volume_var.get())
        self.scan_max_videos_var.set(int(preset["max_videos"]))
        self.scan_max_comments_var.set(int(preset["max_comments"]))
        self.scan_profile_limit_var.set(int(preset["profile_limit"]))
        self.scan_interval_var.set(int(preset["task_interval"]))
        self.action_execution_workers_var.set(int(preset["workers"]))
        live_comment_mode = quick_send_mode_key(self.quick_send_mode_var.get()) == "live_comment"
        self.action_execution_mode_var.set("真实提交" if live_comment_mode else "预检，不提交")
        self.action_execution_live_confirm_var.set(False)

    def set_profile_group_options(self, display_values: list[str], selected: str = ""):
        values = stable_combobox_values(display_values or []) or ["请刷新账号分组"]
        self._group_values = values
        menu = self.group_menu["menu"]
        menu.delete(0, "end")
        for value in values:
            menu.add_command(label=value, command=lambda item=value: (self.scan_profile_group_display_var.set(item), self._on_group_changed()))
        if hasattr(self, "place_group_menu"):
            place_menu = self.place_group_menu["menu"]
            place_menu.delete(0, "end")
            for value in values:
                place_menu.add_command(label=value, command=lambda item=value: (self.scan_profile_group_display_var.set(item), self._on_group_changed()))
        selected_value = selected if selected in values else values[0]
        self.scan_profile_group_display_var.set(selected_value)
        self._on_group_changed()
        self.scan_profile_group_detail_var.set(f"已读取账号分组：{len(values)} 个；当前账号分组：{selected_value}")
        self._redraw_canvas()

    def _on_group_changed(self):
        group = group_name_from_display(self.scan_profile_group_display_var.get())
        if group in {"请刷新账号分组", "正在刷新...", "正在读取分组..."}:
            group = ""
        self.scan_profile_group_var.set(group)
        self.action_execution_group_var.set(group)
        self._redraw_canvas()

    def _refresh_profile_groups(self):
        if self.on_refresh_profiles:
            self.on_refresh_profiles()

    def _start_collection(self):
        self.append_runtime_log("CLICK  start_button source=quick_console")
        if not str(self.scan_source_value_var.get() or "").strip():
            self._set_target_from_dialog()
        if self.target_button:
            self.target_button.configure(text=self._target_button_text())
        if self.on_start_collection:
            self.on_start_collection()
        else:
            self.append_runtime_log("BLOCK  start_button_no_callback source=quick_console")

    def _target_button_text(self) -> str:
        value = str(self.scan_source_value_var.get() or "").strip()
        if len(value) > 82:
            value = value[:79] + "..."
        return f"设置目标：{value or '点击输入链接/关键词/话题/直播间'}"

    def _set_target_from_dialog(self):
        value = simpledialog.askstring("设置推广目标", "请输入产品链接、关键词、话题、达人主页、视频或直播间：", initialvalue=self.scan_source_value_var.get())
        if value is not None:
            self.scan_source_value_var.set(str(value).strip())
            if self.target_button:
                self.target_button.configure(text=self._target_button_text())

    def refresh(self, snapshot=None):
        return

    def show_campaign_plan(self, plan: dict, range_config: dict | None = None, profile_group: str = ""):
        text = "输入推广目标并点击开始后，系统会在这里显示自动识别结果、采集来源和本轮范围。"
        if plan:
            text = f"目标: {plan.get('target') or plan.get('product') or ''}\n类型: {plan.get('input_type') or ''}\n分组: {profile_group or ''}"
        self.plan_lines = [line for line in text.splitlines() if line.strip()]
        self._redraw_canvas()

    def append_runtime_log(self, message: str):
        self.runtime_lines.append(str(message or ""))
        self.runtime_lines = self.runtime_lines[-200:]
        self._redraw_canvas()

    def clear_runtime_log(self):
        self.runtime_lines = []
        self._redraw_canvas()

    def copy_runtime_log(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.runtime_lines))


class GrowthIntelligenceStandaloneApp:
    """Standalone Growth Intelligence workspace with its own left navigation."""

    def __init__(self, root: tk.Tk | tk.Toplevel, base_dir: str | None = None, auto_refresh_profiles: bool = True):
        self.root = root
        self.paths = RuntimePaths.build(base_dir).ensure_dirs()
        self.base_dir = self.paths.base_dir
        self.client_config_state = load_reachops_client_config(self.paths)
        apply_reachops_client_config(self.client_config_state.get("config") or {})
        self.auto_refresh_profiles = bool(auto_refresh_profiles)
        self.service = GrowthIntelligenceService(base_dir=self.base_dir, logger=self._log)
        self.workflow = GrowthWorkflowService(self.service)
        self.profile_registry = StandaloneProfileRegistry()
        self.profile_group_display_map: dict[str, str] = {}
        self.status_var = tk.StringVar(value="已就绪")
        self.group_var = tk.StringVar(value="")
        self.refresh_groups_button = None
        self.active_campaign_id = ""
        self.active_batch_id = ""
        self._collection_start_lock = threading.Lock()
        self._collection_start_in_progress = False
        self.active_run_session_path = ""
        self.active_run_session_latest_path = ""
        self.active_run_result_path = ""
        self._group_count_refresh_in_progress = False
        self._runtime_event_last_rowid = self._current_growth_event_rowid()
        self._last_runtime_status_line = ""
        self._last_runtime_status_at = 0.0
        self._ui_heartbeat_count = 0
        self.runtime_log_path = Path(self.service.paths.logs_dir) / "growth_ops_runtime.log"
        self._build()
        self._log(
            f"READY  app_started data_dir={self.base_dir} "
            f"log={self.runtime_log_path}"
        )
        self._log_client_portability_state()
        self.root.after(1200, self._log_ui_visibility_once)
        self.root.after(30000, self._ui_heartbeat)
        self._cleanup_interrupted_collection_batches()
        self._cleanup_interrupted_action_queue()

    def _build(self):
        self.root.title("运营控制台")
        try:
            self.root.geometry("1500x920")
            self.root.minsize(1280, 780)
        except Exception:
            pass
        self._configure_style()
        try:
            self.root.configure(bg=APP_COLORS["bg"])
        except Exception:
            pass

        shell = ttk.Frame(self.root, padding=(8, 8), style="Shell.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self.console = GrowthOpsConsole(
            shell,
            on_start_collection=self.start_collection_from_console,
            on_export_report=self.export_report,
            on_refresh_profiles=self.refresh_profile_groups,
            operator_status_var=self.status_var,
            workflow_service=self.workflow,
            on_rerun_error=self.rerun_error,
            on_rerun_tasks=self.rerun_tasks,
            on_run_due_scans=self.run_due_scans,
            on_run_selected_scan=self.run_selected_scan,
        )
        self.console.grid(row=0, column=0, sticky="nsew")
        self.console.refresh(self._current_snapshot())
        self.console.set_profile_group_options(["正在读取分组..."], "正在读取分组...")
        if self.auto_refresh_profiles:
            self.root.after(300, lambda: (self._log("CONFIG refresh_profiles started auto=true"), self._refresh_profile_groups_sync(show_message=False)))

    def _configure_style(self):
        style = ttk.Style(self.root)
        style.configure(".", font=ui_font(10))
        style.configure("Shell.TFrame", background=APP_COLORS["bg"])
        style.configure("Header.TFrame", background=APP_COLORS["bg"])
        style.configure("TLabel", background=APP_COLORS["bg"], foreground=APP_COLORS["text"])
        style.configure("AppTitle.TLabel", background=APP_COLORS["surface"], foreground=APP_COLORS["text"], font=ui_font(12, "bold"))
        style.configure("AppSubtitle.TLabel", background=APP_COLORS["surface"], foreground=APP_COLORS["muted"], font=ui_font(10))
        style.configure("Status.TLabel", background=APP_COLORS["surface"], foreground=APP_COLORS["muted"], font=ui_font(9))
        style.configure("TButton", padding=(10, 5), font=ui_font(10))

    def _log(self, message: str):
        text = str(message or "")
        if threading.current_thread() is not threading.main_thread():
            try:
                self._write_runtime_log_file(text)
                self.root.after(0, lambda value=text: self._append_log_text(value, write_file=False))
                return
            except Exception:
                pass
        self._append_log_text(text)

    def _append_log_text(self, text: str, write_file: bool = True):
        self.status_var.set(text)
        try:
            self.console.append_runtime_log(text)
        except Exception:
            pass
        if write_file:
            self._write_runtime_log_file(text)

    def _write_runtime_log_file(self, text: str):
        try:
            self.runtime_log_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.runtime_log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{ts}  {text}\n")
        except Exception:
            pass

    def _ui_window_state(self) -> dict:
        state = {
            "exists": False,
            "viewable": False,
            "mapped": False,
            "state": "unknown",
            "geometry": "",
            "focus": "",
        }
        try:
            state["exists"] = bool(self.root.winfo_exists())
        except Exception:
            return state
        for key, getter in {
            "viewable": self.root.winfo_viewable,
            "mapped": self.root.winfo_ismapped,
            "state": self.root.state,
            "geometry": self.root.winfo_geometry,
        }.items():
            try:
                state[key] = getter()
            except Exception:
                pass
        try:
            focus = self.root.focus_get()
            state["focus"] = str(focus) if focus else ""
        except Exception:
            pass
        return state

    def _log_ui_visibility_once(self):
        state = self._ui_window_state()
        self._log(
            "READY  ui_window "
            f"exists={str(bool(state.get('exists'))).lower()} "
            f"viewable={str(bool(state.get('viewable'))).lower()} "
            f"mapped={str(bool(state.get('mapped'))).lower()} "
            f"state={state.get('state') or 'unknown'} "
            f"geometry={state.get('geometry') or 'unknown'}"
        )

    def _ui_heartbeat(self):
        self._ui_heartbeat_count += 1
        state = self._ui_window_state()
        self._log(
            "HEARTBEAT ui "
            f"count={self._ui_heartbeat_count} "
            f"viewable={str(bool(state.get('viewable'))).lower()} "
            f"mapped={str(bool(state.get('mapped'))).lower()} "
            f"state={state.get('state') or 'unknown'} "
            f"geometry={state.get('geometry') or 'unknown'}"
        )
        try:
            self.root.after(30000, self._ui_heartbeat)
        except Exception:
            pass

    def _log_client_portability_state(self):
        try:
            from .authorization_gate import LiveSubmitAuthorizationGate
            from .device_identity import DeviceIdentity

            activation_required = LiveSubmitAuthorizationGate.activation_required()
            runtime_mode = LiveSubmitAuthorizationGate.runtime_mode()
            device_id = DeviceIdentity.current_device_id()
        except Exception:
            activation_required = False
            runtime_mode = "unknown"
            device_id = ""
        config_path = str((self.client_config_state or {}).get("path") or "")
        created = bool((self.client_config_state or {}).get("created"))
        ix_target = str(os.environ.get("REACHOPS_IXBROWSER_API_TARGET") or "127.0.0.1")
        ix_port = str(os.environ.get("REACHOPS_IXBROWSER_API_PORT") or os.environ.get("IXBROWSER_API_PORT") or "default")
        ai_endpoint = bool(str(os.environ.get("REACHOPS_AI_ENDPOINT") or "").strip())
        self._log(
            f"CONFIG portability data_dir={self.base_dir} config={config_path or '-'} "
            f"config_created={str(created).lower()} runtime={runtime_mode} "
            f"activation_required={str(bool(activation_required)).lower()} "
            f"device_id={device_id[:8] if device_id else '-'} "
            f"ixbrowser={ix_target}:{ix_port} ai_endpoint_configured={str(ai_endpoint).lower()}"
        )

    def _cleanup_interrupted_collection_batches(self):
        try:
            interrupted_events = []
            with self.service.storage.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, campaign_id, total_sources, processed_sources, failed_sources
                    FROM collection_batches
                    WHERE status IN ('running', 'pending')
                    """
                ).fetchall()
                if not rows:
                    return
                now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                for row in rows:
                    batch_id = str(row["id"] or "")
                    total = int(row["total_sources"] or 0)
                    processed = int(row["processed_sources"] or 0)
                    failed = max(int(row["failed_sources"] or 0), max(0, total - processed))
                    conn.execute(
                        """
                        UPDATE collection_tasks
                        SET status='failed', error_code='RUN_INTERRUPTED',
                            error_message='GUI restarted before task completed',
                            completed_at=COALESCE(completed_at, ?), updated_at=?
                        WHERE batch_id=? AND status IN ('pending', 'running')
                        """,
                        (now, now, batch_id),
                    )
                    conn.execute(
                        """
                        UPDATE collection_batches
                        SET status='failed', failed_sources=?, completed_at=COALESCE(completed_at, ?), updated_at=?
                        WHERE id=?
                        """,
                        (failed, now, now, batch_id),
                    )
                    interrupted_events.append((batch_id, str(row["campaign_id"] or "")))
            for batch_id, campaign_id in interrupted_events:
                self.service.storage.log_event(
                    "collection_batch_interrupted_on_startup",
                    batch_id,
                    {"campaign_id": campaign_id, "reason": "GUI_RESTARTED"},
                )
            self._log(f"WARN   startup cleaned_interrupted_batches count={len(rows)}")
        except Exception as exc:
            self._log(f"WARN   startup cleanup_interrupted_batches_failed error={exc}")

    def _cleanup_interrupted_action_queue(self):
        try:
            with self.service.storage.connect() as conn:
                rows = conn.execute("SELECT id, batch_id FROM action_queue WHERE status='running'").fetchall()
            if not rows:
                return
            for row in rows:
                action_id = str(row["id"] or "")
                if not action_id:
                    continue
                self.service.storage.update_action_status(
                    action_id,
                    "failed",
                    "ACTION_RUN_INTERRUPTED: GUI restarted before action completed",
                )
                self.service.storage.log_event(
                    "action_run_interrupted_on_startup",
                    action_id,
                    {"batch_id": str(row["batch_id"] or ""), "error_code": "ACTION_RUN_INTERRUPTED"},
                )
            self._log(f"WARN   startup cleaned_interrupted_actions count={len(rows)} error=ACTION_RUN_INTERRUPTED")
        except Exception as exc:
            self._log(f"WARN   startup cleanup_interrupted_actions_failed error={exc}")

    def _current_snapshot(self):
        return self.workflow.build_snapshot(
            campaign_id=self.active_campaign_id,
            batch_id=self.active_batch_id,
        )

    def _create_native_run_contract(
        self,
        *,
        target: str,
        source_type: str,
        mode: str,
        volume: str,
        profile_group: str,
        profile_limit: int,
        max_videos: int,
        max_comments: int,
        comment_text: str = "",
        live_confirmed: bool = False,
    ) -> dict:
        plan = build_execution_plan(
            target=target,
            source_type=source_type,
            mode=mode,
            volume=volume,
            profile_group=profile_group,
            profile_limit=profile_limit,
            max_videos=max_videos,
            max_comments=max_comments,
            timeout_seconds=1800,
            comment_text=comment_text,
            live_confirmed=live_confirmed,
            base_dir=str(self.base_dir),
            origin="native_tk_client",
        )
        plan_id = str(plan.get("plan_id") or new_id("plan"))
        plan_path = Path(self.base_dir) / "plans" / f"{plan_id}.json"
        write_execution_plan(plan, plan_path)
        latest_plan_path = Path(self.base_dir) / "plans" / "latest_execution_plan.json"
        write_execution_plan(plan, latest_plan_path)

        result_path = Path(self.base_dir) / "run_results" / f"{plan_id}.json"
        session = create_run_session(
            plan,
            execution_plan_path=str(plan_path),
            result_path=str(result_path),
            log_path=str(self.runtime_log_path),
        )
        session_path = Path(self.base_dir) / "runs" / f"{session.get('session_id') or new_id('run')}.json"
        latest_session_path = Path(self.base_dir) / "runs" / "latest_run_session.json"
        session = transition_run_session(
            session,
            "PRECHECK",
            pid=os.getpid(),
            last_stage="native_client_start_requested",
            checkpoint_update={
                "target": target,
                "profile_group": profile_group,
                "mode": mode,
                "volume": volume,
                "no_submit": not bool(live_confirmed and mode == "live_comment"),
            },
        )
        write_run_session(session, session_path, latest_session_path)
        self.active_run_session_path = str(session_path)
        self.active_run_session_latest_path = str(latest_session_path)
        self.active_run_result_path = str(result_path)
        self._log(
            f"RUNSESSION created id={session.get('session_id', '')} plan={plan_id} "
            f"path={session_path} no_submit={str(not bool(live_confirmed and mode == 'live_comment')).lower()}"
        )
        return {
            "plan": plan,
            "plan_path": str(plan_path),
            "session_id": str(session.get("session_id") or ""),
            "session_path": str(session_path),
            "latest_session_path": str(latest_session_path),
            "result_path": str(result_path),
        }

    def _update_native_run_session(self, state: str, *, last_stage: str = "", result: dict | None = None, evidence: dict | None = None):
        path = str(self.active_run_session_path or "")
        if not path:
            return {}
        session = read_run_session(path)
        if not session:
            return {}
        checkpoint_update = {
            "active_batch_id": self.active_batch_id,
            "active_campaign_id": self.active_campaign_id,
            "log_path": str(self.runtime_log_path),
            "result_path": str(self.active_run_result_path or ""),
        }
        updated = transition_run_session(
            session,
            state,
            pid=os.getpid(),
            last_stage=last_stage,
            checkpoint_update=checkpoint_update,
            result=result,
            evidence=evidence,
        )
        write_run_session(updated, path, self.active_run_session_latest_path or None)
        return updated

    def _finalize_native_run_session(
        self,
        state: str,
        *,
        last_stage: str,
        result: dict,
        evidence: dict | None = None,
    ):
        result = attach_client_operator_summary(result)
        result_path = str(self.active_run_result_path or "")
        if result_path:
            try:
                target = Path(result_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                self._thread_log(f"WARN   run_session result_write_failed error={exc}")
        return self._update_native_run_session(state, last_stage=last_stage, result=result, evidence=evidence)

    def _selected_profiles(self) -> list[dict]:
        group = self._selected_group_name()
        limit_var = getattr(self.console, "scan_profile_limit_var", None)
        if limit_var is None:
            limit_var = getattr(self.console, "action_execution_workers_var", tk.IntVar(value=3))
        limit = max(1, int(limit_var.get() or 3))
        if not self.profile_registry.groups:
            self.profile_registry.refresh(include_profiles=False)
        candidate_limit = max(limit * 5, 50)
        candidate_profiles = self.profile_registry.select_profiles(group, limit=candidate_limit)
        registry_error = str(getattr(self.profile_registry, "last_error", "") or "")
        if registry_error and not candidate_profiles:
            self._log(
                f"WARN   selected_profiles registry_unavailable group={group or '全部'} "
                f"error={registry_error}"
            )
        profiles = self._rank_profile_candidates(candidate_profiles, limit)
        self._log(
            f"CONFIG selected_profiles group={group or '全部'} requested={limit} "
            f"candidates={len(candidate_profiles)} selected={len(profiles)} "
            f"excluded={max(0, len(candidate_profiles) - len(profiles))}"
        )
        return profiles

    def _profile_id(self, profile: dict) -> str:
        return str((profile or {}).get("profile_id") or (profile or {}).get("id") or "").strip()

    def _rank_profile_candidates(self, candidate_profiles: list[dict], limit: int) -> list[dict]:
        if os.environ.get("REACHOPS_FORCE_ACCOUNT_RECHECK") == "1":
            self._log(
                "CONFIG selected_profiles force_account_recheck "
                "policy=live_recheck_keep_hard_failure_exclusion"
            )
        filtered_profiles, excluded = self._exclude_recent_hard_failed_profiles(candidate_profiles)
        if excluded:
            self._log(
                f"CONFIG selected_profiles recent_unusable_excluded count={excluded} "
                "policy=hard_failed_or_repeated_transient"
            )
        rank_source = filtered_profiles
        if not rank_source and candidate_profiles:
            rank_source = self._recoverable_profile_candidates(candidate_profiles)
            self._log(
                f"WARN   selected_profiles fallback_recheck_candidates count={len(rank_source)} "
                "reason=historical_filter_exhausted policy=runtime_preflight_will_skip_unusable"
            )
        try:
            from .account_health_manager import AccountHealthManager

            ranked = AccountHealthManager(self.service.storage).rank_profiles(rank_source, max_count=limit)
            if ranked:
                return ranked
            if rank_source:
                transient_recheck = self._transient_recheck_profile_candidates(rank_source, limit)
                if transient_recheck:
                    self._log(
                        f"WARN   selected_profiles transient_recheck_candidates count={len(transient_recheck)} "
                        "reason=only_retryable_start_failures_remain policy=bounded_runtime_preflight"
                    )
                    return transient_recheck
                self._log(
                    "WARN   selected_profiles health_rank_empty selected=0 "
                    "policy=avoid_restarting_known_unusable_profiles"
                )
                return []
            return []
        except Exception as exc:
            self._log(f"WARN   selected_profiles health_rank_failed error={exc}")
            return list(rank_source or [])[:limit]

    def _remote_account_quarantine_enabled(self) -> bool:
        value = str(os.environ.get("REACHOPS_QUARANTINE_FAILED_PROFILES") or "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    def _recoverable_profile_candidates(self, candidate_profiles: list[dict]) -> list[dict]:
        unrecoverable_error_codes = {
            "IXBROWSER_KERNEL_MISMATCH",
            "CAPTCHA_DETECTED",
            "PROXY_FAILED",
            "ACCOUNT_RESTRICTED",
            "COMMENT_ACCESS_GATED",
        }
        recoverable: list[dict] = []
        for profile in candidate_profiles or []:
            profile_id = self._profile_id(profile)
            if not profile_id:
                continue
            last_error_code = str(profile.get("last_error_code") or "")
            if last_error_code in unrecoverable_error_codes:
                continue
            recoverable.append(profile)
        return recoverable

    def _append_recoverable_shortfall_profiles(
        self,
        profiles: list[dict],
        candidate_profiles: list[dict],
        requested_limit: int,
        *,
        log_prefix: str,
    ) -> list[dict]:
        rows = list(profiles or [])
        requested_limit = max(1, int(requested_limit or 1))
        if len(rows) >= requested_limit:
            return rows
        seen = {self._profile_id(row) for row in rows if self._profile_id(row)}
        shortfall = [
            row
            for row in self._recoverable_profile_candidates(candidate_profiles)
            if self._profile_id(row) and self._profile_id(row) not in seen
        ]
        if not shortfall:
            return rows
        needed = requested_limit - len(rows)
        rows.extend(shortfall)
        self._thread_log(
            f"{log_prefix} recoverable_shortfall candidates={len(shortfall)} "
            f"needed={needed} requested={requested_limit} "
            "policy=bounded_recheck_before_collection"
        )
        return rows

    def _transient_recheck_profile_candidates(self, candidate_profiles: list[dict], limit: int) -> list[dict]:
        transient_error_codes = {
            "PAGE_OPEN_FAILED",
            "PROFILE_PREFLIGHT_TIMEOUT",
            "IXBROWSER_NETWORK_ERROR",
            "IXBROWSER_SERVER_BUSY",
        }
        hard_error_codes = {
            "PROFILE_MISSING",
            "LOGIN_REQUIRED",
            "IXBROWSER_KERNEL_MISMATCH",
            "CAPTCHA_DETECTED",
            "PROXY_FAILED",
            "ACCOUNT_RESTRICTED",
            "COMMENT_ACCESS_GATED",
            "BROWSER_CRASHED",
        }
        try:
            health_rows = {
                str(row.get("profile_id") or ""): row
                for row in self.service.storage.list_profile_health(limit=10000)
            }
        except Exception:
            health_rows = {}
        rows: list[dict] = []
        for profile in candidate_profiles or []:
            profile_id = self._profile_id(profile)
            if not profile_id:
                continue
            health = health_rows.get(profile_id, {})
            code = str(health.get("last_error_code") or profile.get("last_error_code") or "")
            status = str(health.get("status") or profile.get("status") or "").lower()
            if code in hard_error_codes:
                continue
            if status == "cooldown" and code not in transient_error_codes:
                continue
            if code not in transient_error_codes:
                continue
            row = dict(profile)
            row["_transient_recheck"] = True
            row["_transient_error_code"] = code
            row["_health_score"] = int(health.get("health_score") or profile.get("health_score") or 0)
            row["_consecutive_failures"] = int(
                health.get("consecutive_failures") or profile.get("consecutive_failures") or 0
            )
            rows.append(row)
        rows = sorted(
            rows,
            key=lambda row: (
                int(row.get("_consecutive_failures") or 0),
                -int(row.get("_health_score") or 0),
                str(row.get("_transient_error_code") or ""),
                self._profile_id(row),
            ),
        )
        return rows[: max(1, int(limit or 1))]

    def _exclude_recent_hard_failed_profiles(self, candidate_profiles: list[dict]) -> tuple[list[dict], int]:
        hard_error_codes = {
            "LOGIN_REQUIRED",
            "IXBROWSER_KERNEL_MISMATCH",
            "CAPTCHA_DETECTED",
            "PROXY_FAILED",
            "ACCOUNT_RESTRICTED",
            "COMMENT_ACCESS_GATED",
            "BROWSER_CRASHED",
        }
        recent_ok: set[str] = set()
        transient_error_codes = {
            "PAGE_OPEN_FAILED",
            "PROFILE_PREFLIGHT_TIMEOUT",
            "IXBROWSER_NETWORK_ERROR",
            "IXBROWSER_SERVER_BUSY",
        }
        recent_errors: dict[str, str] = {}
        transient_counts: dict[str, int] = {}
        try:
            with self.service.storage.connect() as conn:
                rows = conn.execute(
                    "SELECT entity_id, payload FROM growth_events WHERE event='profile_preflight_checked' ORDER BY rowid DESC LIMIT 1200"
                ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload"] if hasattr(row, "keys") else row[1])
                except Exception:
                    payload = {}
                profile_id = str(payload.get("profile_id") or (row["entity_id"] if hasattr(row, "keys") else row[0]) or "").strip()
                if not profile_id or profile_id in recent_errors:
                    continue
                if profile_id in recent_ok:
                    continue
                if payload.get("ok"):
                    recent_ok.add(profile_id)
                    continue
                code = str(payload.get("error_code") or "")
                if code in hard_error_codes:
                    recent_errors[profile_id] = code
                    continue
                if code in transient_error_codes:
                    transient_counts[profile_id] = transient_counts.get(profile_id, 0) + 1
                    if transient_counts[profile_id] >= 2:
                        recent_errors[profile_id] = code
        except Exception:
            recent_errors = {}
        plan_errors = self._latest_account_repair_plan_profile_errors(hard_error_codes)
        for profile_id, error_code in plan_errors.items():
            if profile_id and profile_id not in recent_ok:
                recent_errors.setdefault(profile_id, error_code)
        filtered = [
            profile
            for profile in candidate_profiles or []
            if self._profile_id(profile) and self._profile_id(profile) not in recent_errors
        ]
        return filtered, max(0, len(candidate_profiles or []) - len(filtered))

    def _latest_account_repair_plan_profile_errors(self, hard_error_codes: set[str]) -> dict[str, str]:
        base_dir = Path(str(getattr(self.service, "base_dir", "") or ""))
        if not base_dir:
            return {}
        path = base_dir / "reports/acceptance_remediation/latest_account_repair_plan.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        selected: dict[str, str] = {}
        for group in payload.get("groups") or []:
            if not isinstance(group, dict):
                continue
            error_code = str(group.get("error") or "").strip()
            if error_code not in hard_error_codes:
                continue
            for profile_id in group.get("profile_ids") or []:
                value = str(profile_id or "").strip()
                if value:
                    selected[value] = error_code
        return selected

    def _merge_preflight_summary(self, summaries: list[dict]) -> dict:
        results = []
        errors: dict[str, int] = {}
        checked = available = unavailable = 0
        for summary in summaries or []:
            summary_results = list(summary.get("results") or [])
            results.extend(summary_results)
            checked += int(summary.get("checked") or len(summary_results) or 0)
            available += int(summary.get("available") or 0)
            unavailable += int(summary.get("unavailable") or 0)
            for code, count in (summary.get("errors") or {}).items():
                errors[str(code or "UNKNOWN")] = errors.get(str(code or "UNKNOWN"), 0) + int(count or 0)
        return {
            "checked": checked,
            "available": available,
            "unavailable": unavailable,
            "errors": errors,
            "results": results,
        }

    def _preflight_profiles_with_backfill(
        self,
        initial_profiles: list[dict],
        profile_group: str,
        requested_limit: int,
        checker_factory,
        recovery_checker_factory=None,
        stage: str = "collection",
        min_required_profiles: int = 1,
        max_checked_profiles: int = 0,
        initial_check_limit: int = 0,
        backfill_to_requested: bool = True,
        prevalidated_profiles: list[dict] | None = None,
    ) -> tuple[list[dict], dict]:
        requested_limit = max(1, int(requested_limit or 1))
        min_required_profiles = max(1, min(requested_limit, int(min_required_profiles or 1)))
        max_checked_profiles = max(requested_limit, int(max_checked_profiles or max(requested_limit * 3, 6)))
        initial_check_limit = max(min_required_profiles, int(initial_check_limit or requested_limit))
        executable_profiles: list[dict] = []
        summaries: list[dict] = []
        checked_ids: set[str] = set()
        cached_available = []
        for profile in prevalidated_profiles or []:
            profile_id = self._profile_id(profile)
            if not profile_id or profile_id in checked_ids:
                continue
            checked_ids.add(profile_id)
            cached_available.append(profile)
            executable_profiles.append(profile)
        if cached_available:
            summaries.append(
                {
                    "checked": 0,
                    "available": len(cached_available),
                    "unavailable": 0,
                    "errors": {},
                    "results": [
                        {
                            "profile_id": self._profile_id(profile),
                            "group_name": str(profile.get("group_name") or profile_group or ""),
                            "ok": True,
                            "error_code": "",
                            "error_message": "fresh health cache reused; preflight skipped to avoid duplicate profile starts",
                            "evidence_path": "",
                        }
                        for profile in cached_available
                    ],
                    "skip_recheck": "fresh_health_cache",
                }
            )
            self._thread_log(
                f"CHECK  profile_preflight cached_available stage={stage} available={len(cached_available)} "
                f"profile_ids={','.join([self._profile_id(row) for row in cached_available][:8])} "
                "action=reuse_recent_verified_accounts_and_backfill_shortfall"
            )

        def run_batch(batch_profiles: list[dict], reason: str):
            batch = [profile for profile in batch_profiles if self._profile_id(profile) and self._profile_id(profile) not in checked_ids]
            if not batch:
                return
            for profile in batch:
                checked_ids.add(self._profile_id(profile))
            self._thread_log(
                f"CHECK  profile_preflight stage={stage} reason={reason} profiles={len(batch)} "
                f"profile_ids={','.join([self._profile_id(row) for row in batch][:8])}"
            )
            checker = checker_factory(len(batch))
            available_batch, summary = checker.available_profiles(batch)
            summaries.append(summary)
            executable_profiles.extend(
                profile
                for profile in available_batch
                if self._profile_id(profile) and self._profile_id(profile) not in {self._profile_id(row) for row in executable_profiles}
            )
            self._thread_log(
                f"CHECK  profile_preflight stage={stage} reason={reason} checked={summary.get('checked', 0)} "
                f"available={summary.get('available', 0)} unavailable={summary.get('unavailable', 0)} "
                f"errors={self._format_error_counts(summary.get('errors') or {}) or '无'}"
            )
            self._log_profile_preflight_details(summary, stage=stage)

        def is_ixbrowser_api_outage(summary: dict) -> bool:
            checked = int((summary or {}).get("checked") or 0)
            if checked <= 0 or int((summary or {}).get("available") or 0) > 0:
                return False
            errors = dict((summary or {}).get("errors") or {})
            transient_count = sum(
                int(errors.get(code) or 0)
                for code in ("IXBROWSER_NETWORK_ERROR", "IXBROWSER_SERVER_BUSY", "PROFILE_START_FAILED")
            )
            return transient_count >= checked

        def is_permanent_account_configuration_block(summary: dict, total_candidates: int = 0) -> bool:
            checked = int((summary or {}).get("checked") or 0)
            if checked < max(3, min_required_profiles * 3) or int((summary or {}).get("available") or 0) > 0:
                return False
            errors = dict((summary or {}).get("errors") or {})
            permanent_codes = {
                "IXBROWSER_KERNEL_MISMATCH",
                "LOGIN_REQUIRED",
                "CAPTCHA_DETECTED",
                "PROXY_FAILED",
                "COMMENT_ACCESS_GATED",
                "ACCOUNT_RESTRICTED",
            }
            permanent_count = sum(int(errors.get(code) or 0) for code in permanent_codes)
            if permanent_count < checked:
                return False
            total_candidates = max(0, int(total_candidates or 0))
            if total_candidates and checked >= total_candidates:
                return True
            min_hard_block_checked = min(max_checked_profiles, max(6, min_required_profiles * 5))
            return checked >= min_hard_block_checked

        def stop_for_permanent_account_configuration_block(summary: dict, phase: str) -> bool:
            if not is_permanent_account_configuration_block(summary, len(initial_profiles or [])):
                return False
            self._thread_log(
                f"BLOCK  profile_preflight circuit_breaker stage={stage} reason=permanent_account_configuration_block "
                f"phase={phase} checked={summary.get('checked', 0)} available={len(executable_profiles)} "
                f"errors={self._format_error_counts(summary.get('errors') or {}) or '无'} "
                "action=stop_backfill_to_avoid_profile_start_waste"
            )
            return True

        def stop_for_browser_start_instability(summary: dict, phase: str) -> bool:
            checked = int((summary or {}).get("checked") or 0)
            if checked < max(6, min_required_profiles * 4) or int((summary or {}).get("available") or 0) > 0:
                return False
            errors = dict((summary or {}).get("errors") or {})
            unstable_count = sum(
                int(errors.get(code) or 0)
                for code in ("PAGE_OPEN_FAILED", "PROFILE_PREFLIGHT_TIMEOUT", "BROWSER_CRASHED", "PROFILE_START_FAILED")
            )
            instability_threshold = max(6, int(checked * 0.8))
            if unstable_count < instability_threshold:
                if unstable_count >= max(3, min_required_profiles * 3):
                    self._thread_log(
                        f"CHECK  profile_preflight continue_after_mixed_failures stage={stage} "
                        f"phase={phase} checked={checked} unstable={unstable_count} "
                        f"threshold={instability_threshold} errors={self._format_error_counts(errors) or '无'} "
                        "action=continue_backfill_to_find_logged_in_profile"
                    )
                return False
            self._thread_log(
                f"BLOCK  profile_preflight circuit_breaker stage={stage} reason=browser_start_instability "
                f"phase={phase} checked={checked} available={len(executable_profiles)} "
                f"unstable={unstable_count} threshold={instability_threshold} "
                f"errors={self._format_error_counts(errors) or '无'} "
                "action=stop_backfill_to_avoid_profile_start_waste"
            )
            return True

        def recovery_retry(retry_profiles: list[dict], reason: str) -> bool:
            if not retry_profiles or not recovery_checker_factory:
                return False
            self._thread_log(
                f"CHECK  profile_preflight recovery_retry_start stage={stage} reason={reason} profiles={len(retry_profiles)} "
                f"profile_ids={','.join([self._profile_id(row) for row in retry_profiles][:8])}"
            )
            checker = recovery_checker_factory(len(retry_profiles))
            available_retry, retry_summary = checker.available_profiles(retry_profiles)
            summaries.append(retry_summary)
            executable_profiles.extend(
                profile
                for profile in available_retry
                if self._profile_id(profile)
                and self._profile_id(profile) not in {self._profile_id(row) for row in executable_profiles}
            )
            self._thread_log(
                f"CHECK  profile_preflight recovery_retry_done stage={stage} reason={reason} checked={retry_summary.get('checked', 0)} "
                f"available={retry_summary.get('available', 0)} unavailable={retry_summary.get('unavailable', 0)} "
                f"errors={self._format_error_counts(retry_summary.get('errors') or {}) or '无'}"
            )
            self._log_profile_preflight_details(retry_summary, stage=f"{stage}_recovery")
            return bool(available_retry)

        initial_batch = list(initial_profiles or [])[: min(initial_check_limit, max_checked_profiles)]
        if len(initial_profiles or []) > len(initial_batch):
            self._thread_log(
                f"CHECK  profile_preflight rolling_mode stage={stage} initial={len(initial_batch)} "
                f"candidates={len(initial_profiles or [])} max_checked={max_checked_profiles}"
            )
        run_batch(initial_batch, "initial")
        if len(executable_profiles) >= requested_limit:
            return executable_profiles[:requested_limit], self._merge_preflight_summary(summaries)
        initial_summary = self._merge_preflight_summary(summaries)
        if not backfill_to_requested and len(executable_profiles) >= min_required_profiles:
            self._thread_log(
                f"CHECK  profile_preflight fast_start stage={stage} requested={requested_limit} "
                f"available={len(executable_profiles)} min_required={min_required_profiles} "
                "action=start_with_available_profiles_to_avoid_profile_start_waste"
            )
            return executable_profiles[:requested_limit], initial_summary
        if stop_for_permanent_account_configuration_block(initial_summary, "initial"):
            return executable_profiles[:requested_limit], initial_summary
        if stop_for_browser_start_instability(initial_summary, "initial"):
            return executable_profiles[:requested_limit], initial_summary
        if is_ixbrowser_api_outage(initial_summary):
            retry_profiles = initial_batch[: max(1, min(len(initial_batch), max(3, requested_limit)))]
            recovery_retry(retry_profiles, "ixbrowser_api_outage")
            recovered_summary = self._merge_preflight_summary(summaries)
            if len(executable_profiles) < min_required_profiles and is_ixbrowser_api_outage(recovered_summary):
                self._thread_log(
                    f"BLOCK  profile_preflight circuit_breaker stage={stage} reason=ixbrowser_api_outage "
                    f"checked={recovered_summary.get('checked', 0)} available={len(executable_profiles)} "
                    "action=stop_backfill_to_avoid_profile_start_waste"
                )
                return executable_profiles[:requested_limit], recovered_summary
            if not backfill_to_requested and len(executable_profiles) >= min_required_profiles:
                self._thread_log(
                    f"CHECK  profile_preflight fast_start stage={stage} requested={requested_limit} "
                    f"available={len(executable_profiles)} min_required={min_required_profiles} "
                    "action=start_with_available_profiles_to_avoid_profile_start_waste"
                )
                return executable_profiles[:requested_limit], recovered_summary

        candidate_limit = max(requested_limit * 10, 50)
        cached_candidates = list(initial_profiles or [])[len(initial_batch) : max_checked_profiles]
        candidate_profiles = cached_candidates
        source = "initial_cache"
        if len(candidate_profiles) < max(1, requested_limit):
            try:
                if len(executable_profiles) >= min_required_profiles:
                    executor = ThreadPoolExecutor(max_workers=1)
                    try:
                        future = executor.submit(self.profile_registry.select_profiles, profile_group, candidate_limit)
                        fresh_candidates = future.result(timeout=8)
                    finally:
                        executor.shutdown(wait=False, cancel_futures=True)
                else:
                    fresh_candidates = self.profile_registry.select_profiles(profile_group, limit=candidate_limit)
                candidate_profiles = list(candidate_profiles) + [
                    profile
                    for profile in fresh_candidates
                    if self._profile_id(profile)
                    and self._profile_id(profile) not in {self._profile_id(row) for row in candidate_profiles}
                ]
                source = "initial_cache+registry"
            except FuturesTimeoutError:
                self._thread_log(
                    f"WARN   profile_preflight backfill_registry_timeout stage={stage} "
                    f"available={len(executable_profiles)} requested={requested_limit} "
                    "action=先用已通过账号启动执行，后续再补队列"
                )
            except Exception as exc:
                self._thread_log(f"WARN   profile_preflight backfill_registry_failed stage={stage} error={exc}")
        ranked_candidates = self._rank_profile_candidates(candidate_profiles, candidate_limit)
        ranked_candidates = self._append_recoverable_shortfall_profiles(
            ranked_candidates,
            candidate_profiles,
            requested_limit,
            log_prefix=f"CHECK  profile_preflight stage={stage}",
        )
        remaining = [
            profile
            for profile in ranked_candidates
            if self._profile_id(profile)
            and self._profile_id(profile) not in checked_ids
            and self._profile_id(profile) not in {self._profile_id(row) for row in executable_profiles}
        ]
        self._thread_log(
            f"CHECK  profile_preflight backfill_start stage={stage} requested={requested_limit} "
            f"available={len(executable_profiles)} candidates={len(candidate_profiles)} remaining={len(remaining)} "
            f"source={source}"
        )
        while len(executable_profiles) < requested_limit and remaining and len(checked_ids) < max_checked_profiles:
            need = requested_limit - len(executable_profiles)
            remaining_check_budget = max(1, max_checked_profiles - len(checked_ids))
            max_batch_size = 3 if not backfill_to_requested else 6
            desired_batch_size = need if not backfill_to_requested else need * 2
            batch_size = max(1, min(desired_batch_size, max_batch_size, len(remaining), remaining_check_budget))
            batch = remaining[:batch_size]
            remaining = remaining[batch_size:]
            self._thread_log(
                f"CHECK  profile_preflight backfill_batch stage={stage} size={len(batch)} need={need} "
                f"min_required={min_required_profiles} checked_budget={max_checked_profiles}"
            )
            run_batch(batch, "backfill")
            if not backfill_to_requested and len(executable_profiles) >= min_required_profiles:
                merged_fast = self._merge_preflight_summary(summaries)
                self._thread_log(
                    f"CHECK  profile_preflight fast_start stage={stage} requested={requested_limit} "
                    f"available={len(executable_profiles)} min_required={min_required_profiles} "
                    f"checked={merged_fast.get('checked', 0)} "
                    "action=start_with_available_profiles_after_backfill"
                )
                return executable_profiles[:requested_limit], merged_fast
            if len(executable_profiles) < min_required_profiles:
                merged_backfill = self._merge_preflight_summary(summaries)
                if stop_for_permanent_account_configuration_block(merged_backfill, "backfill"):
                    break
                if stop_for_browser_start_instability(merged_backfill, "backfill"):
                    break
        if len(executable_profiles) < min_required_profiles and recovery_checker_factory:
            merged_for_retry = self._merge_preflight_summary(summaries)
            transient_retry_count = sum(
                1
                for result in merged_for_retry.get("results") or []
                if str(result.get("error_code") or "") in {"PAGE_OPEN_FAILED", "PROFILE_PREFLIGHT_TIMEOUT"}
            )
            if transient_retry_count:
                self._thread_log(
                    f"CHECK  profile_preflight recovery_retry_skipped stage={stage} reason=avoid_duplicate_profile_starts "
                    f"transient_candidates={transient_retry_count} action=不在同一轮重复打开失败账号，优先切换后续账号"
                )
        merged = self._merge_preflight_summary(summaries)
        self._thread_log(
            f"CHECK  profile_preflight backfill_done stage={stage} requested={requested_limit} "
            f"available={len(executable_profiles)} checked_total={merged.get('checked', 0)} "
            f"remaining={len(remaining)}"
        )
        return executable_profiles[:requested_limit], merged

    def _current_group_name(self) -> str:
        return self._selected_group_name()

    def _selected_group_name(self) -> str:
        """Resolve the operator-selected group from the visible combobox first."""

        group = ""
        try:
            display_value = self.console.scan_profile_group_display_var.get().strip()
            group = group_name_from_display(display_value)
            group = getattr(self, "profile_group_display_map", {}).get(group, group)
            if group in {"请刷新账号分组", "正在刷新...", "正在读取分组..."}:
                group = ""
        except Exception:
            group = ""
        if not group:
            try:
                group = self.console.scan_profile_group_var.get().strip()
            except Exception:
                group = ""
        if not group:
            group = group_name_from_display(self.group_var.get())
            group = getattr(self, "profile_group_display_map", {}).get(group, group)
        if group in {"请刷新账号分组", "正在刷新...", "正在读取分组..."}:
            group = ""
        try:
            self.group_var.set(group)
            self.console.scan_profile_group_var.set(group)
            self.console.action_execution_group_var.set(group)
        except Exception:
            pass
        return group

    def refresh_profile_groups(self, show_message: bool = True):
        self._log("CONFIG refresh_profiles started")
        try:
            self.group_var.set("正在刷新...")
            self.console.set_profile_group_options(["正在刷新..."], "正在刷新...")
            if self.refresh_groups_button:
                self.refresh_groups_button.configure(state=tk.DISABLED)
            if getattr(self.console, "start_refresh_groups_button", None):
                self.console.start_refresh_groups_button.configure(state=tk.DISABLED)
        except Exception:
            pass
        self._refresh_profile_groups_async(show_message=show_message)

    def _refresh_profile_groups_async(self, show_message: bool = True):
        self.root.after(10, lambda: self._refresh_profile_groups_sync(show_message=show_message))

    def _refresh_profile_groups_sync(self, show_message: bool = True):
        try:
            self._log("CONFIG refresh_profiles loading_groups")
            snapshot = self.profile_registry.refresh(include_profiles=False, resolve_group_counts=bool(show_message))
            if not snapshot.get("group_count"):
                self._log("WARN   refresh_profiles empty_groups retry=1")
                time.sleep(1.0)
                snapshot = self.profile_registry.refresh(include_profiles=False, resolve_group_counts=bool(show_message))
            self._log(
                f"CONFIG refresh_profiles groups_loaded groups={snapshot.get('group_count', 0)} "
                f"profiles={'deferred' if snapshot.get('profiles_deferred') else snapshot.get('profile_count', 0)} "
                f"counts_resolved={snapshot.get('counts_resolved')}"
            )
            synced = self._sync_profiles_to_account_status(snapshot.get("profiles") or []) if not snapshot.get("profiles_deferred") else 0
            snapshot["synced_profile_count"] = synced
        except Exception as exc:
            snapshot = {"profiles": [], "groups": [], "profile_count": 0, "group_count": 0, "profiles_deferred": True, "error": str(exc)}
        self._apply_profile_group_snapshot(snapshot, show_message=show_message)

    def _refresh_profile_groups_threaded(self, show_message: bool = True):
        self._log("CONFIG refresh_profiles thread_start")

        def runner():
            try:
                self._thread_log("CONFIG refresh_profiles loading_groups")
                snapshot = self.profile_registry.refresh(include_profiles=False, resolve_group_counts=bool(show_message))
                self._thread_log(
                    f"CONFIG refresh_profiles groups_loaded groups={snapshot.get('group_count', 0)} "
                    f"profiles={'deferred' if snapshot.get('profiles_deferred') else snapshot.get('profile_count', 0)} "
                    f"counts_resolved={snapshot.get('counts_resolved')}"
                )
                synced = self._sync_profiles_to_account_status(snapshot.get("profiles") or []) if not snapshot.get("profiles_deferred") else 0
                snapshot["synced_profile_count"] = synced
            except Exception as exc:
                snapshot = {"profiles": [], "groups": [], "profile_count": 0, "group_count": 0, "profiles_deferred": True, "error": str(exc)}
            self.root.after(0, lambda: self._apply_profile_group_snapshot(snapshot, show_message=show_message))

        threading.Thread(target=runner, daemon=True).start()

    def _apply_profile_group_snapshot(self, snapshot: dict, show_message: bool = True):
        if not snapshot.get("error"):
            snapshot_groups = list(snapshot.get("groups") or [])
            if snapshot_groups:
                self.profile_registry.groups = snapshot_groups
                if not snapshot.get("profiles_deferred"):
                    self.profile_registry.profiles = list(snapshot.get("profiles") or [])
            elif self.profile_registry.groups:
                snapshot = dict(snapshot)
                snapshot["groups"] = list(self.profile_registry.groups)
                snapshot["group_count"] = len(self.profile_registry.groups)
                self._log(f"WARN   refresh_profiles empty_groups using_cached={len(self.profile_registry.groups)}")
            else:
                self.profile_registry.profiles = list(snapshot.get("profiles") or [])
                self.profile_registry.groups = []
        if snapshot.get("error") and not snapshot.get("groups"):
            cached_groups = self._cached_profile_groups_from_storage()
            if cached_groups:
                snapshot = dict(snapshot)
                snapshot["groups"] = cached_groups
                snapshot["group_count"] = len(cached_groups)
                self.profile_registry.groups = cached_groups
                self._log(f"WARN   refresh_profiles failed using_storage_cache={len(cached_groups)}")
        self.profile_group_display_map = {}
        groups = []
        for group_row in snapshot.get("groups") or []:
            display = group_display_name(group_row)
            base = group_name_from_display(display)
            raw_name = str(group_row.get("group_name") or group_row.get("group_id") or base)
            group_id = str(group_row.get("group_id") or "")
            self.profile_group_display_map[base] = raw_name
            self.profile_group_display_map[raw_name] = raw_name
            self.profile_group_display_map[raw_name.lower()] = raw_name
            self.profile_group_display_map[display] = raw_name
            if group_id:
                self.profile_group_display_map[f"分组 {group_id}"] = raw_name
                self.profile_group_display_map[f"group {group_id}"] = raw_name
                self.profile_group_display_map[group_id] = raw_name
            groups.append(display)
        self._log(f"CONFIG refresh_profiles apply_start groups={len(groups)}")
        if groups:
            previous_group = self._selected_group_name()
            selected = ""
            if previous_group:
                for display in groups:
                    if group_name_from_display(display) == previous_group:
                        selected = display
                        break
            if not selected:
                selected = next((display for display in groups if group_name_from_display(display).lower() == "united states"), groups[0])
            self.group_var.set(group_name_from_display(selected))
            self._sync_selected_group(selected)
            self._log(f"CONFIG refresh_profiles selected_group={group_name_from_display(selected) or 'none'}")
        else:
            self.group_var.set("")
            self._sync_selected_group("")
            self._log("CONFIG refresh_profiles selected_group=none")
        selected_display = next((display for display in groups if group_name_from_display(display) == self.group_var.get()), self.group_var.get())
        self._log("CONFIG refresh_profiles apply_options")
        safe_groups = stable_combobox_values(groups)
        if not safe_groups:
            safe_groups = ["请刷新账号分组"]
        safe_selected = sanitize_tk_text(selected_display)
        if safe_selected not in safe_groups:
            safe_selected = next((item for item in safe_groups if group_name_from_display(item).lower() == "united states"), safe_groups[0])
        self._log(f"CONFIG refresh_profiles apply_values count={len(safe_groups)} selected={group_name_from_display(safe_selected)}")
        self.console.set_profile_group_options(safe_groups, safe_selected)
        self._log("CONFIG refresh_profiles values_applied")
        group = "" if safe_selected in {"请刷新账号分组", "正在刷新...", "正在读取分组..."} else group_name_from_display(safe_selected)
        group = self.profile_group_display_map.get(group, group)
        self.console.scan_profile_group_var.set(group)
        self.console.action_execution_group_var.set(group)
        self._log("CONFIG refresh_profiles options_applied")
        try:
            if self.refresh_groups_button:
                self.refresh_groups_button.configure(state=tk.NORMAL)
            if getattr(self.console, "start_refresh_groups_button", None):
                self.console.start_refresh_groups_button.configure(state=tk.NORMAL)
        except Exception:
            pass
        self._log("CONFIG refresh_profiles buttons_ready")
        if not snapshot.get("profiles_deferred"):
            self.console.refresh(self._current_snapshot())
        if snapshot.get("error"):
            self._log(f"ERROR  refresh_profiles failed error={snapshot.get('error')}")
        else:
            profile_count = "deferred" if snapshot.get("profiles_deferred") else snapshot.get("profile_count", 0)
            self._log(
                f"CONFIG refresh_profiles done profiles={profile_count} "
                f"groups={snapshot.get('group_count', 0)} synced={snapshot.get('synced_profile_count', 0)}"
            )
        if show_message and not groups and not snapshot.get("error"):
            self._log("WARN   refresh_profiles no_groups message=未读取到账号分组，请确认 ixBrowser 本地 API 可用")
        if show_message and snapshot.get("error"):
            self._log("WARN   refresh_profiles no_popup=true action=查看终端日志")
        if snapshot.get("profiles_deferred") and groups and not snapshot.get("counts_resolved"):
            self._resolve_profile_group_counts_async(snapshot)

    def _resolve_profile_group_counts_async(self, snapshot: dict):
        if getattr(self, "disable_async_group_count_refresh", False):
            return
        if self._group_count_refresh_in_progress:
            return
        unresolved = [
            dict(group)
            for group in snapshot.get("groups") or []
            if group.get("group_id") and not group.get("count_known")
        ]
        if not unresolved:
            return
        self._group_count_refresh_in_progress = True
        self._log(f"CONFIG refresh_profiles resolving_counts groups={len(unresolved)}")

        def runner():
            try:
                resolved_groups = resolve_ixbrowser_group_counts([dict(group) for group in snapshot.get("groups") or []], timeout_seconds=18.0)
                resolved_snapshot = dict(snapshot)
                resolved_snapshot["groups"] = resolved_groups
                resolved_snapshot["group_count"] = len(resolved_groups)
                resolved_snapshot["counts_resolved"] = True
                resolved_snapshot["synced_profile_count"] = snapshot.get("synced_profile_count", 0)
            except Exception as exc:
                resolved_snapshot = dict(snapshot)
                resolved_snapshot["counts_resolved"] = True
                resolved_snapshot["count_resolution_error"] = str(exc)
            known = sum(1 for group in resolved_snapshot.get("groups") or [] if group.get("count_known"))
            total = sum(1 for group in resolved_snapshot.get("groups") or [] if group.get("group_id"))
            if resolved_snapshot.get("count_resolution_error"):
                self._thread_log(f"WARN   refresh_profiles count_resolution_failed error={resolved_snapshot.get('count_resolution_error')}")
            elif known < total:
                self._thread_log(f"WARN   refresh_profiles counts_partial groups={known}/{total} reason=ixbrowser_count_timeout")
            else:
                self._thread_log(f"CONFIG refresh_profiles counts_resolved groups={known}")
            self._group_count_refresh_in_progress = False

            def apply_resolved():
                self._group_count_refresh_in_progress = False
                if resolved_snapshot.get("count_resolution_error"):
                    return
                self._apply_profile_group_snapshot(resolved_snapshot, show_message=False)

            self.root.after(0, apply_resolved)

        threading.Thread(target=runner, daemon=True).start()

    def _cached_profile_groups_from_storage(self) -> list[dict]:
        groups: dict[str, dict] = {}
        try:
            rows = self.service.storage.list_profile_health(limit=10000)
        except Exception:
            rows = []
        for row in rows or []:
            group_name = str(row.get("group_name") or "").strip()
            if not group_name:
                continue
            item = groups.setdefault(group_name, {"group_id": "", "group_name": group_name, "count": 0, "count_known": True})
            item["count"] += 1
        return sorted(groups.values(), key=lambda row: str(row.get("group_name") or ""))

    def _cached_profiles_from_storage(self, group_name: str = "", limit: int = 50) -> list[dict]:
        try:
            rows = self.service.storage.list_profile_health(limit=10000)
        except Exception:
            rows = []
        profiles: list[dict] = []
        requested = str(group_name or "").strip()
        recent_ok_rank: dict[str, int] = {}
        fresh_ok_at: dict[str, datetime] = {}
        fresh_ok_ids: set[str] = set()
        try:
            now = datetime.now(timezone.utc)
            max_age_minutes = max(1, int(os.environ.get("REACHOPS_PROFILE_HEALTH_CACHE_MINUTES") or 240))
            cutoff = now - timedelta(minutes=max_age_minutes)
            with self.service.storage.connect() as conn:
                recent_rows = conn.execute(
                    "SELECT payload, created_at FROM growth_events WHERE event='profile_preflight_checked' ORDER BY rowid DESC LIMIT 300"
                ).fetchall()
            for row in recent_rows:
                try:
                    payload = json.loads(row["payload"] if hasattr(row, "keys") else row[0])
                except Exception:
                    continue
                created_at_raw = str(row["created_at"] if hasattr(row, "keys") else row[1] or "")
                try:
                    created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    created_at = created_at.astimezone(timezone.utc)
                except Exception:
                    created_at = None
                if created_at is None or created_at < cutoff:
                    continue
                profile_id = str(payload.get("profile_id") or "").strip()
                if profile_id and payload.get("ok") and profile_id not in recent_ok_rank:
                    recent_ok_rank[profile_id] = len(recent_ok_rank)
                    fresh_ok_ids.add(profile_id)
                    if created_at is not None:
                        fresh_ok_at[profile_id] = created_at
        except Exception:
            recent_ok_rank = {}
            fresh_ok_at = {}
            fresh_ok_ids = set()
        hard_error_codes = {
            "IXBROWSER_KERNEL_MISMATCH",
            "LOGIN_REQUIRED",
            "CAPTCHA_DETECTED",
            "PROXY_FAILED",
            "ACCOUNT_RESTRICTED",
            "COMMENT_ACCESS_GATED",
            "BROWSER_CRASHED",
        }
        transient_error_codes = {
            "PAGE_OPEN_FAILED",
            "PROFILE_PREFLIGHT_TIMEOUT",
            "PROFILE_START_TIMEOUT",
            "IXBROWSER_NETWORK_ERROR",
            "IXBROWSER_SERVER_BUSY",
        }
        recent_runtime_errors: dict[str, str] = {}
        try:
            with self.service.storage.connect() as conn:
                error_rows = conn.execute(
                    """
                    SELECT profile_id, error_code, created_at
                    FROM growth_errors
                    WHERE profile_id!=''
                      AND error_code IN ('BROWSER_CRASHED', 'LOGIN_REQUIRED', 'CAPTCHA_DETECTED', 'PROXY_FAILED', 'COMMENT_ACCESS_GATED')
                    ORDER BY rowid DESC
                    LIMIT 300
                    """
                ).fetchall()
            for error_row in error_rows:
                profile_id = str(error_row["profile_id"] if hasattr(error_row, "keys") else error_row[0] or "").strip()
                if not profile_id or profile_id in recent_runtime_errors:
                    continue
                created_at_raw = str(error_row["created_at"] if hasattr(error_row, "keys") else error_row[2] or "")
                try:
                    created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    created_at = created_at.astimezone(timezone.utc)
                except Exception:
                    created_at = None
                if created_at is None or created_at < cutoff:
                    continue
                ok_at = fresh_ok_at.get(profile_id)
                if ok_at is not None and ok_at > created_at:
                    continue
                recent_runtime_errors[profile_id] = str(error_row["error_code"] if hasattr(error_row, "keys") else error_row[1] or "")
        except Exception:
            recent_runtime_errors = {}
        for row in rows or []:
            profile_id = str(row.get("profile_id") or "").strip()
            if not profile_id:
                continue
            status = str(row.get("status") or "").lower()
            last_error_code = str(row.get("last_error_code") or "")
            runtime_error_code = recent_runtime_errors.get(profile_id, "")
            if runtime_error_code in hard_error_codes:
                continue
            if last_error_code in hard_error_codes:
                continue
            health_score = int(row.get("health_score", 0) or 0)
            recently_verified = profile_id in fresh_ok_ids
            transient_candidate = (
                not fresh_ok_ids
                and status in {"healthy", "degraded"}
                and health_score >= 50
                and not last_error_code
            )
            if last_error_code in transient_error_codes and not recently_verified:
                continue
            if not recently_verified and not transient_candidate:
                continue
            if status == "cooldown" and not recently_verified:
                continue
            profile = {
                "profile_id": profile_id,
                "id": profile_id,
                "group_name": str(row.get("group_name") or ""),
                "status": str(row.get("status") or ""),
                "last_error_code": last_error_code,
                "health_score": health_score,
                "consecutive_failures": row.get("consecutive_failures", 0),
                "updated_at": str(row.get("updated_at") or ""),
                "_recently_verified": recently_verified,
                "_transient_candidate": transient_candidate,
            }
            if requested and requested != "全部配置" and not profile_matches_group(profile, requested):
                continue
            profiles.append(profile)
        def updated_rank(profile: dict) -> float:
            try:
                value = str(profile.get("updated_at") or "")
                if value.endswith("Z"):
                    value = value[:-1] + "+00:00"
                return -datetime.fromisoformat(value).timestamp()
            except Exception:
                return 0.0

        profiles = sorted(
            profiles,
            key=lambda row: (
                recent_ok_rank.get(str(row.get("profile_id") or ""), 9999),
                0 if str(row.get("status") or "").lower() == "healthy" else 1,
                0 if not str(row.get("last_error_code") or "") else 1,
                -int(row.get("health_score") or 0),
                updated_rank(row),
                str(row.get("profile_id") or ""),
            ),
        )
        return profiles[: max(1, int(limit or 50))]

    def _sync_profiles_to_account_status(self, profiles: list[dict]) -> int:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        synced = 0
        with self.service.storage.connect() as conn:
            for profile in profiles or []:
                profile_id = str(profile.get("profile_id") or profile.get("id") or "").strip()
                if not profile_id:
                    continue
                group_name = str(profile.get("group_name") or profile.get("group_id") or "").strip()
                row = conn.execute("SELECT profile_id FROM profile_health WHERE profile_id=?", (profile_id,)).fetchone()
                if row:
                    conn.execute(
                        """
                        UPDATE profile_health
                        SET group_name=COALESCE(NULLIF(?, ''), group_name),
                            status=COALESCE(NULLIF(status, ''), 'healthy'),
                            updated_at=?
                        WHERE profile_id=?
                        """,
                        (group_name, now, profile_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO profile_health
                        (profile_id, group_name, health_score, status, consecutive_failures,
                         last_error_code, last_error_message, last_used_at, updated_at)
                        VALUES (?, ?, 100, 'healthy', 0, '', '', '', ?)
                        """,
                        (profile_id, group_name, now),
                    )
                synced += 1
        return synced

    def _on_group_selected(self, _event=None):
        self._sync_selected_group(self.group_var.get())

    def _sync_selected_group(self, display_value: str):
        group = group_name_from_display(display_value)
        group = getattr(self, "profile_group_display_map", {}).get(group, group)
        if group in {"请刷新账号分组", "正在刷新...", "正在读取分组..."}:
            group = ""
        try:
            self.group_var.set(group)
        except Exception:
            pass
        try:
            self.console.scan_profile_group_var.set(group)
            self.console.action_execution_group_var.set(group)
        except Exception:
            pass

    def start_collection_from_console(self):
        try:
            source_preview = str(self.console.scan_source_value_var.get() or "").strip()
        except Exception:
            source_preview = ""
        try:
            group_preview = self._selected_group_name()
        except Exception:
            group_preview = ""
        try:
            mode_preview = str(getattr(self.console, "quick_send_mode_var", None).get() or "")
        except Exception:
            mode_preview = ""
        self._log(
            "CLICK  start_acquisition received "
            f"target_present={str(bool(source_preview)).lower()} "
            f"group={group_preview or '未指定'} mode={mode_preview or '未指定'}"
        )
        with self._collection_start_lock:
            if self._collection_start_in_progress:
                self._log(
                    "BLOCK  campaign not_started reason=获客流程正在初始化 "
                    "next=等待当前预检/采集启动完成后再点击开始获客"
                )
                return
            self._collection_start_in_progress = True

        def release_start_lock():
            with self._collection_start_lock:
                self._collection_start_in_progress = False

        running_batch = self._running_collection_batch()
        if running_batch:
            self._log(
                f"BLOCK  campaign not_started reason=已有获客批次正在运行 "
                f"batch={running_batch.get('id', '')} campaign={running_batch.get('campaign_id', '')} "
                f"progress={running_batch.get('processed_sources', 0)}/{running_batch.get('total_sources', 0)} "
                "next=等待当前批次结束后再开始新获客"
            )
            release_start_lock()
            return
        source_value = self.console.scan_source_value_var.get().strip()
        if not source_value:
            self._log("BLOCK  campaign not_started reason=缺少推广目标 next=请先输入产品链接、关键词、竞品、视频或直播间")
            release_start_lock()
            return
        try:
            self.console.apply_quick_send_preset()
        except Exception:
            pass
        quick_mode_var = getattr(self.console, "quick_send_mode_var", None)
        quick_mode_label = str(quick_mode_var.get() if quick_mode_var else "采集 + 触达预检")
        quick_mode_label = quick_mode_label or "采集 + 触达预检"
        quick_mode = quick_send_mode_key(quick_mode_label)
        quick_volume_var = getattr(self.console, "quick_send_volume_var", None)
        quick_volume_label = str(quick_volume_var.get() if quick_volume_var else "快速")
        quick_volume_label = quick_volume_label or "快速"
        quick_preset = quick_send_preset(quick_volume_label)
        source_type = normalize_source_type(self.console.scan_source_type_var.get())
        max_videos = max(1, int(self.console.scan_max_videos_var.get() or 5))
        max_comments = max(1, int(self.console.scan_max_comments_var.get() or 10))
        task_interval = max(1, int(self.console.scan_interval_var.get() or quick_preset.get("task_interval") or 3))
        if quick_mode == "live_comment":
            task_interval = max(12, task_interval)
            if not self._quick_send_live_submit_confirmed(quick_mode):
                self._log(
                    "BLOCK  campaign not_started reason=LIVE_COMMENT_CONFIRMATION_REQUIRED "
                    "next=真实评论必须单独勾选确认；M3 验收请使用采集 + 触达预检 no-submit"
                )
                release_start_lock()
                return
            authorization = self._live_submit_authorization_decision()
            if not bool(getattr(authorization, "allowed", False)):
                code = str(getattr(authorization, "error_code", "") or "LIVE_SUBMIT_NOT_AUTHORIZED")
                message = str(getattr(authorization, "error_message", "") or "live submit not authorized")
                self._log(
                    f"BLOCK  campaign not_started reason={code} message={message} "
                    "next=完成激活/授权后再进入真实评论；M3 验收继续使用 no-submit"
                )
                release_start_lock()
                return
        profile_limit = max(1, int(self.console.scan_profile_limit_var.get() or 3))
        profile_group = self._selected_group_name()
        intent_keywords = parse_keyword_list(self.console.scan_intent_keywords_var.get())
        exclude_keywords = parse_keyword_list(self.console.scan_exclude_keywords_var.get())
        plan_source_limit = self._quick_direct_target_plan_source_limit(
            source_value,
            source_type=source_type,
            quick_volume_label=quick_volume_label,
        )
        plan = self.service.create_campaign_plan(
            source_value,
            intent_keywords=intent_keywords,
            exclude_keywords=exclude_keywords,
            max_sources=plan_source_limit,
        )
        campaign = plan.get("campaign") or {}
        persona = plan.get("persona") or {}
        planned_sources = plan.get("sources") or []
        detected_type = str(campaign.get("input_type") or source_type or "auto")
        self.active_campaign_id = str(campaign.get("id") or "")
        self.active_batch_id = ""
        if source_type != "auto" and planned_sources:
            normalized_value, validation_error = self._validate_collection_source(source_type, source_value)
            if validation_error:
                self._log(
                    f"BLOCK  campaign not_started campaign={campaign.get('id', '')} reason={validation_error} "
                    f"source_type={source_type} target={source_value} next=请切换自动识别或输入有效链接"
                )
                release_start_lock()
                return
            planned_sources = [
                {
                    **planned_sources[0],
                    "source_type": source_type,
                    "source_value": normalized_value,
                }
            ]
        planned_sources = self._scope_quick_direct_target_sources(
            planned_sources,
            detected_type=detected_type,
            quick_volume_label=quick_volume_label,
        )
        if not planned_sources:
            self._log(f"BLOCK  campaign not_started campaign={campaign.get('id', '')} reason=没有生成获客来源")
            release_start_lock()
            return
        range_config = {
            "max_videos": max_videos,
            "max_comments": max_comments,
            "profile_limit": profile_limit,
            "queue_profile_target": max(profile_limit, min(max(profile_limit * 2, len(planned_sources)), 12)),
            "max_sources_per_profile": 3 if quick_volume_label == "快速" else 20,
            "task_interval": task_interval,
            "quick_mode": quick_mode_label,
            "quick_volume": quick_volume_label,
        }
        plan_mode = "collect" if quick_mode == "collect_only" else quick_mode
        native_run = {}
        try:
            native_run = self._create_native_run_contract(
                target=source_value,
                source_type=source_type,
                mode=plan_mode,
                volume="quick" if quick_volume_label == "快速" else "standard" if quick_volume_label == "标准" else "stress",
                profile_group=profile_group or "United States",
                profile_limit=profile_limit,
                max_videos=max_videos,
                max_comments=max_comments,
                comment_text=self._quick_comment_text(),
                live_confirmed=self._quick_send_live_submit_confirmed(quick_mode),
            )
        except Exception as exc:
            self._log(
                f"BLOCK  campaign not_started campaign={campaign.get('id', '')} "
                f"reason=RUN_CONTRACT_CREATE_FAILED error={exc}"
            )
            release_start_lock()
            return
        display_plan = {
            **plan,
            "sources": planned_sources,
            "execution_plan_path": native_run.get("plan_path", ""),
            "run_session_path": native_run.get("session_path", ""),
        }
        try:
            self.console.show_campaign_plan(display_plan, range_config, profile_group)
        except Exception:
            pass
        planned_source_labels = [
            f"{row.get('source_type', '')}:{row.get('source_value', '')}"
            for row in planned_sources[:8]
        ]
        self._log(
            f"PLAN   campaign id={campaign.get('id', '')} input_type={detected_type} "
            f"product={campaign.get('product_name', '')} sources={len(planned_sources)} "
            f"range=每来源最多{max_videos}条视频/每视频最多{max_comments}条评论/任务间隔{task_interval}秒 "
            f"intent_keywords={','.join(intent_keywords) or 'auto'} "
            f"exclude_keywords={','.join(exclude_keywords) or 'none'} "
            f"planned_sources={' | '.join(planned_source_labels)}"
        )
        self._log(
            f"FAST   target_quick_send mode={quick_mode} volume={quick_volume_label} detected_type={detected_type} "
            f"group={profile_group or 'United States'} profile_pool=collection/comment/profile/dm/exception "
            f"preset_videos={quick_preset.get('max_videos')} preset_comments={quick_preset.get('max_comments')} "
            f"requested_profiles={profile_limit}"
        )
        try:
            precreated_batch = self.service.storage.create_collection_batch(
                len(planned_sources),
                profile_group=profile_group,
                config={
                    "campaign_id": str(campaign.get("id") or ""),
                    "planned_sources": planned_sources,
                    "max_videos_per_creator": max_videos,
                    "max_comments_per_video": max_comments,
                    "task_interval": task_interval,
                    "startup_stage": "profile_preflight",
                    "quick_send": {
                        "enabled": True,
                        "mode": quick_mode,
                        "mode_label": quick_mode_label,
                        "volume": quick_volume_label,
                        "detected_type": detected_type,
                        "requested_profiles": profile_limit,
                        "requested_concurrency": profile_limit,
                        "queue_profile_target": range_config["queue_profile_target"],
                        "max_sources_per_profile": range_config["max_sources_per_profile"],
                        "comment_text": self._quick_comment_text(),
                        "comment_reply_ai": self._comment_reply_ai_settings(),
                        "account_pools": ["collection", "comment", "profile", "dm", "exception"],
                    },
                },
                campaign_id=str(campaign.get("id") or ""),
                initial_status="pending",
            )
            self.service.storage.set_active_collection_batch(precreated_batch.id)
            self.active_batch_id = precreated_batch.id
            self._log(
                f"START  campaign id={campaign.get('id', '')} batch={precreated_batch.id} "
                f"status=pending stage=profile_preflight target={source_value} group={profile_group or '未指定'} "
                f"sources={len(planned_sources)}"
            )
            self._update_native_run_session(
                "PROFILE_PREFLIGHT",
                last_stage=f"native_collection_batch_created batch={precreated_batch.id}",
                evidence={"collection_batch_id": precreated_batch.id, "campaign_id": str(campaign.get("id") or "")},
            )
            try:
                self.console.refresh(self._current_snapshot())
            except Exception:
                pass
        except Exception as exc:
            self._log(f"BLOCK  campaign not_started campaign={campaign.get('id', '')} reason=BATCH_CREATE_FAILED error={exc}")
            self._finalize_native_run_session(
                "BLOCKED",
                last_stage="native_batch_create_failed",
                result={
                    "status": "blocked",
                    "error_code": "BATCH_CREATE_FAILED",
                    "error_message": str(exc),
                    "target": source_value,
                    "profile_group": profile_group,
                    "no_submit": True,
                },
            )
            release_start_lock()
            return

        def runner():
            from .profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig

            try:
                retained_profile_ids: set[str] = set()
                preflight_checkers: list[Any] = []
                remote_account_quarantine = self._remote_account_quarantine_enabled()
                if remote_account_quarantine:
                    self._thread_log(
                        "CONFIG account_repair_mode remote_group_update_enabled=true "
                        "policy=quarantine_failed_profiles_and_continue_ready_accounts"
                    )
                quick_volume_key = "quick" if quick_volume_label == "快速" else "standard" if quick_volume_label == "标准" else "stress"
                if quick_volume_key == "quick":
                    fast_preflight_limit = max(profile_limit * 2, 6)
                    auto_preflight_limit = max(fast_preflight_limit, min(24, profile_limit * 8))
                else:
                    fast_preflight_limit = max(profile_limit * 3, 9)
                    auto_preflight_limit = max(fast_preflight_limit, profile_limit * 20, 60)
                min_collection_profiles = profile_limit
                cached_profiles = self._cached_profiles_from_storage(profile_group, limit=auto_preflight_limit)
                profiles = list(cached_profiles)
                if len(cached_profiles) >= min_collection_profiles:
                    self._thread_log(
                        f"CONFIG quick_preflight_candidates source=profile_health_cache group={profile_group or '全部'} "
                        f"requested={profile_limit} checked_limit={len(profiles)} auto_limit={auto_preflight_limit}"
                    )
                if len(cached_profiles) < profile_limit:
                    selected_profiles = self._selected_profiles()
                    candidate_profiles = self.profile_registry.select_profiles(profile_group, limit=max(100, auto_preflight_limit))
                    ranked_profiles = self._rank_profile_candidates(candidate_profiles, auto_preflight_limit)
                    cached_profile_ids = {self._profile_id(row) for row in cached_profiles}
                    selected_profile_ids = {self._profile_id(row) for row in selected_profiles}
                    ranked_profiles = [
                        *cached_profiles,
                        *[row for row in selected_profiles if self._profile_id(row) not in cached_profile_ids],
                        *[
                            row
                            for row in ranked_profiles
                            if self._profile_id(row) not in cached_profile_ids
                            and self._profile_id(row) not in selected_profile_ids
                        ],
                    ]
                    ranked_profiles = self._append_recoverable_shortfall_profiles(
                        ranked_profiles,
                        candidate_profiles,
                        profile_limit,
                        log_prefix=f"CONFIG quick_preflight_candidates group={profile_group or '全部'}",
                    )
                    if ranked_profiles:
                        profiles = ranked_profiles
                        self._thread_log(
                            f"CONFIG quick_preflight_candidates group={profile_group or '全部'} "
                            f"requested={profile_limit} candidates={len(candidate_profiles)} checked_limit={len(profiles)} "
                            f"auto_limit={auto_preflight_limit} cached_available={len(cached_profiles)}"
                        )
                if not profiles:
                    self.service.storage.update_collection_batch(
                        self.active_batch_id,
                        "failed",
                        failed_delta=len(planned_sources),
                    )
                    self._thread_log(
                        "BLOCK  campaign failed reason=没有可用账号 error=NO_PROFILE_SELECTED "
                        "next=点击刷新账号分组，并选择 discovery/comment/action 分组"
                    )
                    self._finalize_native_run_session(
                        "BLOCKED",
                        last_stage="native_no_profile_selected",
                        result={
                            "status": "blocked",
                            "error_code": "NO_PROFILE_SELECTED",
                            "target": source_value,
                            "profile_group": profile_group,
                            "checked_profiles": 0,
                            "available_profiles": 0,
                            "no_submit": True,
                        },
                        evidence={"collection_batch_id": self.active_batch_id},
                    )
                    self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
                    return
                def checker_factory(batch_size: int):
                    if quick_volume_key == "quick":
                        page_timeout = 12
                        wait_after_open = 1.0
                        total_timeout = max(30, min(72, max(1, batch_size) * 12))
                        launch_stagger = 0.8
                    else:
                        page_timeout = 10
                        wait_after_open = 0.8
                        total_timeout = max(30, min(90, max(1, batch_size) * 18))
                        launch_stagger = 2.0
                    checker = ProfilePreflightChecker(
                        self.service.storage,
                        ProfilePreflightConfig(
                            max_workers=1,
                            page_load_timeout_seconds=page_timeout,
                            wait_after_open_seconds=wait_after_open,
                            total_timeout_seconds=total_timeout,
                            launch_stagger_seconds=launch_stagger,
                            evidence_dir=str(Path(self.service.paths.reports_dir) / "collection_profile_preflight_evidence"),
                            close_browser_after_check=True,
                            retain_successful_browser_after_check=False,
                            quarantine_on_failure=remote_account_quarantine,
                        ),
                    )
                    preflight_checkers.append(checker)
                    return checker

                def recovery_checker_factory(batch_size: int):
                    if quick_volume_key == "quick":
                        page_timeout = 16
                        wait_after_open = 1.0
                        total_timeout = max(36, min(90, max(1, batch_size) * 15))
                        launch_stagger = 1.0
                    else:
                        page_timeout = 18
                        wait_after_open = 1.2
                        total_timeout = max(35, min(180, max(1, batch_size) * 28))
                        launch_stagger = 2.0
                    checker = ProfilePreflightChecker(
                        self.service.storage,
                        ProfilePreflightConfig(
                            max_workers=1,
                            page_load_timeout_seconds=page_timeout,
                            wait_after_open_seconds=wait_after_open,
                            total_timeout_seconds=total_timeout,
                            launch_stagger_seconds=launch_stagger,
                            evidence_dir=str(Path(self.service.paths.reports_dir) / "collection_profile_preflight_evidence"),
                            close_browser_after_check=True,
                            retain_successful_browser_after_check=False,
                            quarantine_on_failure=remote_account_quarantine,
                        ),
                    )
                    preflight_checkers.append(checker)
                    return checker

                queue_profile_target = max(profile_limit, min(auto_preflight_limit, int(range_config.get("queue_profile_target") or profile_limit)))
                self._thread_log(
                    f"QUEUE  account_queue_start batch={self.active_batch_id} group={profile_group or '全部'} "
                    f"requested_concurrency={profile_limit} queue_target={queue_profile_target} "
                    f"max_sources_per_profile={range_config['max_sources_per_profile']}"
                )
                use_fresh_health_cache = (
                    bool(cached_profiles)
                    and len(cached_profiles) >= min_collection_profiles
                    and any(bool(profile.get("_recently_verified")) for profile in cached_profiles)
                    and os.environ.get("REACHOPS_FORCE_ACCOUNT_RECHECK") != "1"
                )
                if use_fresh_health_cache and len(cached_profiles) >= profile_limit:
                    executable_profiles = list(cached_profiles)[:queue_profile_target]
                    self._thread_log(
                        f"CONFIG selected_profiles group={profile_group or '全部'} requested={profile_limit} "
                        f"candidates={len(cached_profiles)} selected={len(executable_profiles)} "
                        "excluded=0 source=profile_health_cache"
                    )
                    profile_preflight = {
                        "requested": len(executable_profiles),
                        "checked": 0,
                        "available": len(executable_profiles),
                        "unavailable": 0,
                        "errors": {},
                        "results": [
                            {
                                "profile_id": self._profile_id(profile),
                                "group_name": str(profile.get("group_name") or profile_group or ""),
                                "ok": True,
                                "error_code": "",
                                "error_message": "fresh health cache reused; preflight skipped to avoid duplicate profile starts",
                                "evidence_path": "",
                            }
                            for profile in executable_profiles
                        ],
                        "skip_recheck": "fresh_health_cache",
                    }
                    self.service.storage.log_event("profile_preflight_completed", "", profile_preflight)
                    self._thread_log(
                        f"CHECK  profile_preflight skipped stage=collection reason=fresh_health_cache "
                        f"checked=0 available={len(executable_profiles)} unavailable=0 "
                        f"profile_ids={','.join([self._profile_id(row) for row in executable_profiles][:8])} "
                        "action=reuse_recent_verified_accounts_to_avoid_duplicate_starts"
                    )
                else:
                    if cached_profiles and os.environ.get("REACHOPS_FORCE_ACCOUNT_RECHECK") == "1":
                        self._thread_log(
                            f"CONFIG quick_preflight_candidates force_recheck_enabled "
                            f"group={profile_group or '全部'} cached_available={len(cached_profiles)} "
                            "action=ignore_fresh_health_cache_for_this_run"
                        )
                    elif cached_profiles and len(cached_profiles) < profile_limit:
                        self._thread_log(
                            f"CONFIG quick_preflight_candidates backfill_shortfall "
                            f"group={profile_group or '全部'} requested={profile_limit} cached_available={len(cached_profiles)} "
                            "action=preflight_additional_profiles_to_reach_requested_concurrency"
                        )
                    executable_profiles, profile_preflight = self._preflight_profiles_with_backfill(
                        profiles,
                        profile_group,
                        profile_limit,
                        checker_factory,
                        recovery_checker_factory=recovery_checker_factory,
                        stage="collection",
                        min_required_profiles=min_collection_profiles,
                        max_checked_profiles=auto_preflight_limit,
                        initial_check_limit=profile_limit,
                        backfill_to_requested=bool(profile_limit > min_collection_profiles),
                        prevalidated_profiles=(cached_profiles if use_fresh_health_cache else None),
                    )
                preflight_errors = self._format_error_counts(profile_preflight.get("errors") or {})
                self.root.after(
                    0,
                    lambda: self._log(
                        f"CHECK  profile_preflight checked={profile_preflight.get('checked', 0)} "
                        f"available={profile_preflight.get('available', 0)} unavailable={profile_preflight.get('unavailable', 0)} "
                        f"errors={preflight_errors or '无'}"
                    ),
                )
                self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
                if len(executable_profiles) < min_collection_profiles:
                    self.service.storage.update_collection_batch(
                        self.active_batch_id,
                        "failed",
                        failed_delta=len(planned_sources),
                    )
                    self.root.after(
                        0,
                        lambda: self._log(
                            f"BLOCK  campaign failed reason=可用账号不足 required={min_collection_profiles} available={len(executable_profiles)} "
                            f"checked={profile_preflight.get('checked', 0)} auto_limit={auto_preflight_limit} "
                            "error=INSUFFICIENT_LOGGED_IN_PROFILES next=系统已自动重检同分组账号；请保留至少3个已登录可用账号后再次执行"
                        ),
                    )
                    self._finalize_native_run_session(
                        "BLOCKED",
                        last_stage="native_profile_preflight_insufficient_profiles",
                        result={
                            "status": "blocked",
                            "error_code": "INSUFFICIENT_LOGGED_IN_PROFILES",
                            "target": source_value,
                            "profile_group": profile_group,
                            "checked_profiles": int(profile_preflight.get("checked") or 0),
                            "available_profiles": len(executable_profiles),
                            "required_profiles": min_collection_profiles,
                            "unavailable_profiles": int(profile_preflight.get("unavailable") or 0),
                            "errors": dict(profile_preflight.get("errors") or {}),
                            "no_submit": True,
                        },
                        evidence={
                            "collection_batch_id": self.active_batch_id,
                            "profile_preflight": profile_preflight,
                        },
                    )
                    self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
                    return
                self._thread_log(
                    f"QUEUE  account_queue_effective batch={self.active_batch_id} "
                    f"requested_concurrency={profile_limit} effective_concurrency={min(profile_limit, len(executable_profiles))} "
                    f"available_profiles={len(executable_profiles)} queue_target={queue_profile_target} "
                    f"profile_ids={','.join([self._profile_id(row) for row in executable_profiles][:8])}"
                )
                self._update_native_run_session(
                    "COLLECTING",
                    last_stage=(
                        f"native_profile_preflight_completed checked={profile_preflight.get('checked', 0)} "
                        f"available={len(executable_profiles)}"
                    ),
                    evidence={
                        "collection_batch_id": self.active_batch_id,
                        "profile_preflight": profile_preflight,
                    },
                )
                if len(executable_profiles) >= profile_limit and len(executable_profiles) < queue_profile_target:
                    self.root.after(
                        0,
                        lambda: self._log(
                            f"WARN   account_queue partial_pool concurrency={profile_limit} "
                            f"queue_available={len(executable_profiles)} queue_target={queue_profile_target} "
                            "action=先按可用队列执行，后续异常账号继续跳过"
                        ),
                    )
                executable_profile_ids = [self._profile_id(row) for row in executable_profiles]
                retained_profile_ids.update(profile_id for profile_id in executable_profile_ids if profile_id)
                retained_sessions = {}
                for checker in preflight_checkers:
                    try:
                        retained_sessions.update(checker.retained_sessions())
                    except Exception:
                        pass
                handed_off_sessions = {
                    profile_id: session
                    for profile_id, session in retained_sessions.items()
                    if profile_id in retained_profile_ids and session is not None
                }
                if handed_off_sessions:
                    try:
                        self.service.router._profile_sessions.update(handed_off_sessions)
                    except Exception:
                        handed_off_sessions = {}
                self._thread_log(
                    f"QUEUE  preflight_session_handoff batch={self.active_batch_id} "
                    f"retained={len(retained_sessions)} handed_off={len(handed_off_sessions)} "
                    f"profile_ids={','.join(list(handed_off_sessions.keys())[:8]) or '-'}"
                )
                effective_sources = list(planned_sources)
                if quick_volume_key == "quick" and len(executable_profiles) < profile_limit:
                    max_sources_for_available = max(
                        len(executable_profiles),
                        min(len(planned_sources), len(executable_profiles) * max(2, max_videos)),
                    )
                    effective_sources = planned_sources[:max_sources_for_available]
                    if len(effective_sources) < len(planned_sources):
                        try:
                            self.service.storage.update_collection_batch_total_sources(self.active_batch_id, len(effective_sources))
                        except Exception as exc:
                            self._thread_log(
                                f"WARN   campaign_scope batch_total_update_failed batch={self.active_batch_id} "
                                f"effective_sources={len(effective_sources)} error={exc}"
                            )
                        self.root.after(
                            0,
                            lambda: self._log(
                                f"WARN   campaign_scope reduced_for_available_profiles original_sources={len(planned_sources)} "
                                f"effective_sources={len(effective_sources)} available_profiles={len(executable_profiles)} "
                                "reason=quick_mode_timeout_control"
                            ),
                        )
                self.root.after(
                    0,
                    lambda: self._log(
                        f"START  campaign id={campaign.get('id', '')} type={campaign.get('input_type', '')} target={source_value} "
                        f"sources={len(effective_sources)} persona_keywords={','.join((persona.get('intent_keywords') or [])[:6])} "
                        f"group={profile_group or self._current_group_name() or '未指定'} profiles={min(profile_limit, len(executable_profiles))} "
                        f"queue_profiles={len(executable_profiles)} "
                        f"profile_ids={','.join(executable_profile_ids[:8])} max_videos={max_videos} "
                        f"max_comments={max_comments} interval_seconds={task_interval}"
                    ),
                )
                result = self.service.run_collection(
                    [{"type": row.get("source_type"), "value": row.get("source_value")} for row in effective_sources],
                    executable_profiles,
                    GrowthTaskConfig(
                        max_videos_per_creator=max_videos,
                        max_comments_per_video=max_comments,
                        profile_group=profile_group,
                        campaign_id=str(campaign.get("id") or ""),
                        intent_keywords=list(persona.get("intent_keywords") or intent_keywords),
                        exclude_keywords=list(persona.get("exclude_keywords") or exclude_keywords),
                        active_batch_id=self.active_batch_id,
                        account_queue_enabled=True,
                        max_sources_per_profile=int(range_config.get("max_sources_per_profile") or 1),
                        max_comment_users_empty_profile_retries_per_source=1,
                        max_consecutive_empty_result_sources=2,
                        retain_profile_sessions_after_collection=True,
                        requested_concurrency=profile_limit,
                        quarantine_failed_profiles=remote_account_quarantine,
                        task_delay_min_seconds=task_interval,
                        task_delay_max_seconds=task_interval,
                    ),
                )
                batch = self.service.storage.latest_collection_batch_for_campaign(str(campaign.get("id") or ""))
                self.active_batch_id = str(batch.get("id") or "")
                self._log_collection_finished(result)
                self._log_recent_runtime_events()
                self.root.after(0, lambda: self._collection_finished(result, write_log=False))
                self._thread_log(
                    f"FAST   collection_result mode={quick_mode} used_profiles={len(executable_profiles)} "
                    f"processed_sources={getattr(result, 'processed_sources', 0)} failed_sources={getattr(result, 'failed_sources', 0)} "
                    f"no_submit={str(not self._quick_send_live_submit_confirmed(quick_mode)).lower()}"
                )
                self._update_native_run_session(
                    "SCORING",
                    last_stage=(
                        f"native_collection_finished processed={getattr(result, 'processed_sources', 0)} "
                        f"failed={getattr(result, 'failed_sources', 0)}"
                    ),
                    evidence={
                        "collection_batch_id": self.active_batch_id,
                        "collection_report_json": str(getattr(result, "report_json_path", "") or ""),
                        "collection_report_csv": str(getattr(result, "report_csv_path", "") or ""),
                    },
                )
                self._update_native_run_session(
                    "ACTION_PLANNING",
                    last_stage="native_action_plan_ready",
                    evidence={"collection_batch_id": self.active_batch_id},
                )
                if getattr(result, "failed_sources", 0) and not getattr(result, "processed_sources", 0):
                    errors = getattr(result, "errors", {}) or {}
                    top_error = ""
                    if errors:
                        top_error = sorted(errors.items(), key=lambda item: (-int(item[1] or 0), item[0]))[0][0]
                    self._thread_log(
                        f"BLOCK  collection no_effective_source batch={self.active_batch_id} "
                        f"failed_sources={getattr(result, 'failed_sources', 0)} used_profiles={len(executable_profiles)} "
                        f"top_error={top_error or 'UNKNOWN'} "
                        "next=自动换可用账号重试；若账号池不足，请补充同分组已登录账号或更换可访问目标"
                    )
                if quick_mode == "collect_only":
                    self._thread_log(
                        f"TOUCH  skipped batch={self.active_batch_id} reason=目标快发只采集模式 no_submit=true"
                    )
                    self._thread_log(
                        f"FAST   acceptance status=pending reason=collect_only video_log=true touch_log=skipped "
                        f"next=切换到采集+触达预检或真实评论"
                    )
                    self._finalize_native_run_session(
                        "DEGRADED",
                        last_stage="native_collect_only_completed_without_touch_preflight",
                        result={
                            "status": "degraded",
                            "mode": plan_mode,
                            "target": source_value,
                            "profile_group": profile_group,
                            "processed_sources": int(getattr(result, "processed_sources", 0) or 0),
                            "failed_sources": int(getattr(result, "failed_sources", 0) or 0),
                            "used_profiles": len(executable_profiles),
                            "no_submit": True,
                            "next_action": "Run no-submit action preflight before M2/M3 acceptance.",
                        },
                        evidence={"collection_batch_id": self.active_batch_id},
                    )
                else:
                    try:
                        self._update_native_run_session(
                            "EXECUTING",
                            last_stage="native_action_preflight_started",
                            evidence={"collection_batch_id": self.active_batch_id},
                        )
                        action_result = self._start_action_queue_processing(str(campaign.get("id") or ""), profile_group, executable_profiles)
                        action_error = str((action_result or {}).get("error_code") or "")
                        acceptance_status = "blocked" if action_error else "executed"
                        self._thread_log(
                            f"FAST   acceptance status={acceptance_status} mode={quick_mode} "
                            f"actions={action_result.get('selected_actions', 0)} success={action_result.get('success', 0)} "
                            f"failed={action_result.get('failed', 0)} skipped={action_result.get('skipped', 0)} "
                            f"no_submit={str(not self._quick_send_live_submit_confirmed(quick_mode)).lower()} "
                            f"error={action_error or '无'}"
                        )
                        action_failed = int((action_result or {}).get("failed") or 0)
                        collection_failed = int(getattr(result, "failed_sources", 0) or 0)
                        terminal_state = "COMPLETED" if not action_error and not action_failed and not collection_failed else "DEGRADED"
                        terminal_status = "completed" if terminal_state == "COMPLETED" else "degraded"
                        self._finalize_native_run_session(
                            terminal_state,
                            last_stage=f"native_acceptance_{acceptance_status}",
                            result={
                                "status": terminal_status,
                                "mode": plan_mode,
                                "target": source_value,
                                "profile_group": profile_group,
                                "processed_sources": int(getattr(result, "processed_sources", 0) or 0),
                                "failed_sources": collection_failed,
                                "used_profiles": len(executable_profiles),
                                "actions": int((action_result or {}).get("selected_actions") or 0),
                                "action_success": int((action_result or {}).get("success") or 0),
                                "action_failed": action_failed,
                                "action_skipped": int((action_result or {}).get("skipped") or 0),
                                "error_code": action_error,
                                "no_submit": not self._quick_send_live_submit_confirmed(quick_mode),
                            },
                            evidence={
                                "collection_batch_id": self.active_batch_id,
                                "action_report_json": str((action_result or {}).get("report_path") or ""),
                            },
                        )
                    except Exception as e:
                        self._thread_log(f"ERROR  action_preflight failed error={str(e)}")
                        self._finalize_native_run_session(
                            "DEGRADED",
                            last_stage="native_action_preflight_exception",
                            result={
                                "status": "degraded",
                                "error_code": "ACTION_PREFLIGHT_FAILED",
                                "error_message": str(e),
                                "target": source_value,
                                "profile_group": profile_group,
                                "processed_sources": int(getattr(result, "processed_sources", 0) or 0),
                                "failed_sources": int(getattr(result, "failed_sources", 0) or 0),
                                "used_profiles": len(executable_profiles),
                                "no_submit": True,
                            },
                            evidence={"collection_batch_id": self.active_batch_id},
                        )
            except Exception as exc:
                self._thread_log(f"ERROR  native_run failed error={exc}")
                self._finalize_native_run_session(
                    "BLOCKED",
                    last_stage="native_run_unhandled_exception",
                    result={
                        "status": "blocked",
                        "error_code": "NATIVE_RUN_UNHANDLED_EXCEPTION",
                        "error_message": str(exc),
                        "target": source_value,
                        "profile_group": profile_group,
                        "active_batch_id": self.active_batch_id,
                        "no_submit": True,
                    },
                    evidence={"collection_batch_id": self.active_batch_id},
                )
            finally:
                try:
                    self.service.router._close_reusable_profile_sessions(self.active_batch_id)
                except Exception:
                    pass
                try:
                    from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

                    manager = get_workbench_browser_adapter()
                    for profile_id in list(retained_profile_ids):
                        manager.release_profile(profile_id, "reachops_batch_completed")
                except Exception:
                    pass
                release_start_lock()

        threading.Thread(target=runner, daemon=True).start()
        self._schedule_runtime_refresh()

    def _quick_send_live_submit_confirmed(self, quick_mode: str) -> bool:
        if quick_mode != "live_comment":
            return False
        live_confirm_var = getattr(self.console, "action_execution_live_confirm_var", None)
        try:
            return bool(live_confirm_var.get()) if live_confirm_var else False
        except Exception:
            return False

    def _live_submit_authorization_decision(self):
        try:
            from .authorization_gate import AuthorizationDecision, LiveSubmitAuthorizationGate

            gate = LiveSubmitAuthorizationGate.from_storage(self.service.storage)
            return gate.authorize_live_submit(
                {"action_type": "comment_reply", "id": "native_live_submit_preflight"},
                {"profile_id": "native_live_submit_preflight"},
                feature="live_submit",
            )
        except Exception as exc:
            try:
                from .authorization_gate import AuthorizationDecision

                return AuthorizationDecision(
                    False,
                    "LIVE_SUBMIT_AUTHORIZATION_CHECK_FAILED",
                    str(exc),
                    {"source": "native_tk_client"},
                )
            except Exception:
                return type(
                    "Decision",
                    (),
                    {
                        "allowed": False,
                        "error_code": "LIVE_SUBMIT_AUTHORIZATION_CHECK_FAILED",
                        "error_message": str(exc),
                    },
                )()

    def _scope_quick_direct_target_sources(
        self,
        planned_sources: list[dict],
        detected_type: str = "",
        quick_volume_label: str = "",
    ) -> list[dict]:
        sources = list(planned_sources or [])
        if str(quick_volume_label or "") != "快速":
            return sources
        detected = str(detected_type or "").strip()
        if detected not in {"creator_url", "content_url", "live_room_url"}:
            return sources
        direct_sources = [row for row in sources if str(row.get("source_type") or "") == detected]
        effective = direct_sources[:1] if direct_sources else sources[:1]
        if len(sources) > len(effective):
            self._thread_log(
                f"PLAN   quick_direct_scope detected_type={detected} original_sources={len(sources)} "
                f"effective_sources={len(effective)} action=skip_broad_keyword_and_hashtag_expansion"
            )
        return effective

    def _quick_direct_target_plan_source_limit(
        self,
        source_value: str,
        source_type: str = "auto",
        quick_volume_label: str = "",
    ) -> int:
        if str(quick_volume_label or "") != "快速":
            return 100
        source_type = str(source_type or "auto").strip()
        if source_type in {"creator_url", "content_url", "live_room_url"}:
            return 1
        text = str(source_value or "").strip().lower()
        if "tiktok.com" in text and ("/video/" in text or "/@" in text or "/live" in text):
            return 1
        if text.startswith(("http://", "https://")):
            return 6
        return 100

    def _running_collection_batch(self) -> dict:
        try:
            with self.service.storage.connect() as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM collection_batches
                    WHERE status IN ('running', 'pending')
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """
                ).fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}

    def _create_preflight_blocked_batch(
        self,
        campaign_id: str,
        planned_sources: list[dict],
        profile_group: str,
        profile_preflight: dict,
    ) -> dict:
        batch = self.service.storage.create_collection_batch(
            len(planned_sources or []),
            profile_group=profile_group,
            campaign_id=campaign_id,
            config={
                "blocked_stage": "profile_preflight",
                "error_code": "NO_LOGGED_IN_PROFILE_AVAILABLE",
                "profile_preflight": profile_preflight,
            },
        )
        for source in planned_sources or []:
            task = self.service.storage.create_collection_task(
                batch.id,
                str(source.get("id") or ""),
                str(source.get("source_type") or source.get("type") or ""),
                str(source.get("source_value") or source.get("value") or ""),
                profile_id="",
            )
            self.service.storage.update_collection_task(
                task.id,
                "failed",
                error_code="NO_LOGGED_IN_PROFILE_AVAILABLE",
                error_message="没有通过登录态预检的账号",
            )
        self.service.storage.update_collection_batch(
            batch.id,
            "failed",
            failed_delta=len(planned_sources or []),
        )
        self.service.storage.log_event(
            "collection_blocked_by_profile_preflight",
            batch.id,
            {
                "campaign_id": campaign_id,
                "profile_group": profile_group,
                "error_code": "NO_LOGGED_IN_PROFILE_AVAILABLE",
                "profile_preflight": profile_preflight,
            },
        )
        return self.service.storage.latest_collection_batch_for_campaign(campaign_id)

    def _validate_collection_source(self, source_type: str, source_value: str) -> tuple[str, str]:
        value = str(source_value or "").strip()
        lower = value.lower()
        if source_type == "creator_url":
            if value.startswith("@"):
                return f"https://www.tiktok.com/{value}", ""
            if self._is_tiktok_url(value) and "/@" in lower:
                return value, ""
            return "", "当前选择的是达人主页，但目标不是 TikTok 达人主页链接或 @用户名"
        if source_type == "content_url":
            if self._is_tiktok_url(value) and ("/video/" in lower or "/photo/" in lower):
                return value, ""
            return "", "当前选择的是视频链接，但目标不是 TikTok 视频链接"
        if source_type == "live_room_url":
            if self._is_tiktok_url(value) and ("live" in lower or "/@" in lower):
                return value, ""
            return "", "当前选择的是直播间活跃用户，但目标不是 TikTok 直播间/达人直播链接"
        if source_type in {"keyword", "topic", "hashtag"}:
            if self._is_tiktok_url(value):
                return "", "当前选择的是关键词/话题，但目标看起来是链接"
            return value.lstrip("#").strip(), ""
        return value, ""

    def _is_tiktok_url(self, value: str) -> bool:
        try:
            parsed = urlparse(value if "://" in value else f"https://{value}")
        except Exception:
            return False
        host = (parsed.netloc or "").lower()
        return host == "tiktok.com" or host.endswith(".tiktok.com")

    def _thread_log(self, message: str):
        self._log(message)

    def _start_action_queue_processing(self, campaign_id: str, profile_group: str, profiles: list[dict]):
        """Run current-campaign actions in real-browser, no-submit preflight mode."""
        try:
            from .action_router import ActionRouterConfig
            from .profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig
            from .tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor

            batch_id = self.active_batch_id or str(
                (self.service.storage.latest_collection_batch_for_campaign(campaign_id) or {}).get("id") or ""
            )
            if not batch_id:
                self._thread_log(f"WARN   action_preflight skipped campaign={campaign_id} reason=没有本轮采集批次")
                return {}

            mode = str(getattr(self.console, "action_execution_mode_var", None).get() if getattr(self.console, "action_execution_mode_var", None) else "预检，不提交")
            live_mode = mode == "真实提交"
            live_confirmed = bool(
                getattr(self.console, "action_execution_live_confirm_var", None).get()
                if getattr(self.console, "action_execution_live_confirm_var", None)
                else False
            )
            live_submit = live_mode and live_confirmed
            live_comment_text = self._quick_comment_text()
            action_types = ["comment_reply"] if live_submit else ["comment_reply", "follow_review", "dm_review"]
            quick_mode_label = str(
                getattr(self.console, "quick_send_mode_var", None).get()
                if getattr(self.console, "quick_send_mode_var", None)
                else ""
            )
            self._thread_log(
                "CONFIG live_submit_gate "
                f"batch={batch_id} quick_mode={quick_mode_label} mode={mode} "
                f"confirmed={str(live_confirmed).lower()} live_submit={str(live_submit).lower()}"
            )
            selectable_statuses = {"approved", "retryable", "account_switched"}
            if live_submit:
                selectable_statuses.update({"pending", "pending_review"})
            elif not live_mode:
                selectable_statuses.update({"pending", "pending_review"})
            if live_mode and not live_confirmed:
                self._thread_log(
                    f"BLOCK  action_submit skipped batch={batch_id} reason=真实提交未确认 next=勾选确认真实提交"
                )
                return {"selected_actions": 0, "batch_id": batch_id, "error_code": "LIVE_SUBMIT_NOT_CONFIRMED"}

            if live_submit and live_comment_text:
                self._apply_live_comment_text_override(batch_id, live_comment_text)
            action_fetch_limit = 1000 if live_submit else 100
            pending_actions = [
                row
                for row in self.service.storage.list_action_queue(limit=action_fetch_limit, batch_id=batch_id)
                if str(row.get("status") or "") in selectable_statuses
                and str(row.get("action_type") or "") in action_types
            ]
            if live_submit and not pending_actions:
                seed_min_score = 20 if live_comment_text else 60
                created = self._create_live_comment_seed_actions(
                    batch_id,
                    limit=max(1, min(3, len(profiles) or 1)),
                    min_score=seed_min_score,
                    fixed_comment_text=live_comment_text,
                )
                if created:
                    self._thread_log(
                        f"TOUCH  seed_actions_created batch={batch_id} count={created} "
                        f"min_score={seed_min_score} reason=live_comment_no_high_intent_actions"
                    )
                    if live_comment_text:
                        self._apply_live_comment_text_override(batch_id, live_comment_text)
                    pending_actions = [
                        row
                        for row in self.service.storage.list_action_queue(limit=action_fetch_limit, batch_id=batch_id)
                        if str(row.get("status") or "") in selectable_statuses
                        and str(row.get("action_type") or "") in action_types
                    ]
            if not pending_actions:
                reason = "本轮没有可执行评论动作" if live_submit else "本轮没有待预检/已批准动作"
                candidate_count = len(self.service.storage.list_candidates_with_content(batch_id=batch_id))
                lead_count = len(self.service.storage.list_operation_leads(limit=1000, batch_id=batch_id))
                action_count = len(self.service.storage.list_action_queue(limit=1000, batch_id=batch_id))
                self._thread_log(
                    f"TOUCH  skipped batch={batch_id} reason={reason} "
                    f"candidates={candidate_count} leads={lead_count} actions={action_count} "
                    f"no_submit={str(not live_submit).lower()}"
                )
                self._thread_log(
                    f"DONE   action_preflight skipped batch={batch_id} reason={reason} "
                    f"candidates={candidate_count} leads={lead_count} actions={action_count}"
                )
                return {
                    "selected_actions": 0,
                    "batch_id": batch_id,
                    "worker_count": 0,
                    "available_profile_count": 0,
                    "results": [],
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                }
            total_pending_actions = len(pending_actions)
            if not live_submit:
                pending_actions = pending_actions[:6]

            # Audit contract: max_workers=max(1, min(int(self.console.action_execution_workers_var.get()
            requested_workers = max(1, int(self.console.action_execution_workers_var.get() or 2))
            workers = max(1, min(requested_workers, max(1, len(profiles))))
            target_action_profiles = requested_workers
            if live_submit:
                target_action_profiles = min(
                    max(1, len(profiles)),
                    max(requested_workers, min(5, len(pending_actions))),
                )
            else:
                target_action_profiles = min(max(1, len(profiles)), requested_workers)
            if live_submit:
                per_profile_limit = max(1, len(pending_actions))
                daily_limit = 0
                hour_limit = 0
                video_hour_limit = 0
            else:
                per_profile_limit = max(1, int(self.console.action_execution_per_profile_var.get() or 5))
                daily_limit = 20
                hour_limit = max(1, int(self.console.action_execution_hour_limit_var.get() or 10))
                video_hour_limit = max(1, int(self.console.action_execution_video_hour_limit_var.get() or 1))
            min_lead_score = 60 if live_submit else 50
            ai_settings = self._comment_reply_ai_settings()
            self._thread_log(
                f"CONFIG comment_reply_ai strategy={ai_settings.get('strategy', '')} "
                f"endpoint_configured={str(bool(ai_settings.get('endpoint_configured'))).lower()} "
                f"model={ai_settings.get('model') or 'none'} ai_suggestion_only=true"
            )
            self._thread_log(
                f"START  {'action_submit' if live_submit else 'action_preflight'} batch={batch_id} actions={len(pending_actions)} "
                f"queued_total={total_pending_actions} "
                f"group={profile_group or self._current_group_name() or '未指定'} profiles={len(profiles)} "
                f"workers={workers} per_profile={per_profile_limit} min_lead_score={min_lead_score} no_submit={str(not live_submit).lower()}"
            )
            preflight_checkers: list[Any] = []
            remote_account_quarantine = self._remote_account_quarantine_enabled()

            def checker_factory(batch_size: int):
                checker = ProfilePreflightChecker(
                    self.service.storage,
                    ProfilePreflightConfig(
                        max_workers=max(1, min(workers, max(1, batch_size))),
                        page_load_timeout_seconds=20,
                        wait_after_open_seconds=2.0,
                        total_timeout_seconds=max(30, min(120, max(1, batch_size) * 35)),
                        evidence_dir=str(Path(self.service.paths.reports_dir) / "action_profile_preflight_evidence"),
                        close_browser_after_check=True,
                        retain_successful_browser_after_check=True,
                        quarantine_on_failure=remote_account_quarantine,
                    ),
                )
                preflight_checkers.append(checker)
                return checker

            executable_profiles, profile_preflight = self._preflight_profiles_with_backfill(
                profiles,
                profile_group,
                target_action_profiles,
                checker_factory,
                stage="action_preflight",
                min_required_profiles=target_action_profiles if live_submit else 1,
                max_checked_profiles=max(target_action_profiles * 5, 10),
                initial_check_limit=target_action_profiles,
                backfill_to_requested=live_submit,
            )
            preflight_errors = self._format_error_counts(profile_preflight.get("errors") or {})
            self._thread_log(
                f"CHECK  profile_preflight checked={profile_preflight.get('checked', 0)} "
                f"available={profile_preflight.get('available', 0)} unavailable={profile_preflight.get('unavailable', 0)} "
                f"errors={preflight_errors or '无'}"
            )
            self._log_profile_preflight_details(profile_preflight, stage="action_preflight")
            self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
            if not executable_profiles:
                self._thread_log(
                    "BLOCK  action_preflight reason=没有通过预检的账号 "
                    "next=先登录账号或更换 discovery/comment/action 分组 no_submit=true"
                )
                self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
                return {
                    "selected_actions": 0,
                    "batch_id": batch_id,
                    "profile_preflight": profile_preflight,
                    "error_code": "NO_LOGGED_IN_PROFILE_AVAILABLE",
                }
            retained_sessions = {}
            for checker in preflight_checkers:
                try:
                    retained_sessions.update(checker.retained_sessions())
                except Exception:
                    pass
            retained_profile_ids = {self._profile_id(profile) for profile in executable_profiles if self._profile_id(profile)}
            handed_off_sessions = {
                profile_id: session
                for profile_id, session in retained_sessions.items()
                if profile_id in retained_profile_ids and session is not None
            }
            if handed_off_sessions:
                try:
                    from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

                    manager = get_workbench_browser_adapter()
                    sessions = getattr(manager, "_sessions", {}) or {}
                    profile_to_instance = getattr(manager, "_profile_to_instance", {}) or {}
                    for profile_id, session in handed_off_sessions.items():
                        instance_id = str(getattr(session, "instance_id", "") or "")
                        if instance_id:
                            sessions[instance_id] = session
                            profile_to_instance[profile_id] = instance_id
                except Exception:
                    handed_off_sessions = {}
            self._thread_log(
                f"QUEUE  action_preflight_session_handoff batch={batch_id} "
                f"retained={len(retained_sessions)} handed_off={len(handed_off_sessions)} "
                f"profile_ids={','.join(list(handed_off_sessions.keys())[:8]) or '-'}"
            )
            workers = max(1, min(requested_workers, len(executable_profiles)))

            action_config = ActionRouterConfig(
                profile_group=profile_group,
                dry_run=False,
                action_types=action_types,
                auto_approve=live_submit,
                auto_confirm=live_submit,
                live_preflight_only=not live_submit,
                allow_live_submit=live_submit,
                require_action_review=live_submit,
                per_profile_action_limit=per_profile_limit,
                max_workers=workers,
                max_switch_attempts=max(2, len(executable_profiles)),
                per_profile_daily_limit=daily_limit,
                per_profile_hour_limit=hour_limit,
                per_profile_video_hour_limit=video_hour_limit,
                batch_id=batch_id,
                require_authorization=True,
                min_lead_score=min_lead_score,
            )
            platform_executor = TikTokSeleniumActionExecutor(
                TikTokActionExecutorConfig(
                    close_browser_after_action=False,
                    preflight_only=not live_submit,
                    evidence_dir=str(Path(self.service.paths.reports_dir) / ("action_submit_evidence" if live_submit else "action_preflight_evidence")),
                )
            )
            try:
                result = self.workflow.run_action_router(
                    executable_profiles,
                    config=action_config,
                    platform_executor=platform_executor,
                    limit=max(1, len(pending_actions)),
                    export_report=True,
                    batch_id=batch_id,
                )
            finally:
                try:
                    from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

                    manager = get_workbench_browser_adapter()
                    for profile in executable_profiles:
                        profile_id = self._profile_id(profile)
                        if profile_id:
                            manager.release_profile(profile_id, "reachops_action_stage_completed")
                except Exception:
                    pass
            result.setdefault("worker_count", workers)
            result.setdefault("available_profile_count", len(executable_profiles))
            result.setdefault("profile_preflight", profile_preflight)
            result.setdefault("batch_id", batch_id)
            self._log_recent_runtime_events()
            self._log_action_router_result(result, mode_label="action_submit" if live_submit else "action_preflight")
            self._thread_log(
                f"DONE   {'action_submit' if live_submit else 'action_preflight'} selected={result.get('selected_actions', 0)} "
                f"success={result.get('success', 0)} failed={result.get('failed', 0)} "
                f"skipped={result.get('skipped', 0)} switched={result.get('account_switched', 0)} "
                f"profiles={len(executable_profiles)} "
                f"report={(result.get('report') or {}).get('json_path', '')}"
            )
            self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
            return result
        except Exception as e:
            self._thread_log(f"ERROR  action_preflight init_failed error={str(e)}")
            raise

    def _create_live_comment_seed_actions(
        self,
        batch_id: str,
        limit: int = 1,
        min_score: int = 60,
        fixed_comment_text: str = "",
    ) -> int:
        try:
            from ReachOps.intelligence.lead_quality import looks_like_seller_promo

            with self.service.storage.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM candidate_users
                    WHERE batch_id=?
                      AND status!='excluded'
                      AND intent_tags NOT LIKE '%excluded_keyword%'
                      AND COALESCE(profile_url, '')!=''
                      AND COALESCE(source_path, '') LIKE '%/video/%'
                    ORDER BY qualify_score DESC, comment_likes DESC, created_at ASC
                    """,
                    (batch_id,),
                ).fetchall()
            min_score = max(0, int(min_score or 0))
            rows = [
                row
                for row in rows
                if int(row["qualify_score"] or 0) >= min_score
                and not looks_like_seller_promo(str(row["comment_text"] or ""))
            ][: max(1, int(limit or 1))]
            if not rows:
                all_candidates = self.service.storage.list_candidates_with_content(batch_id=batch_id)
                scores = sorted([int(row.get("qualify_score") or 0) for row in all_candidates], reverse=True)
                max_score = scores[0] if scores else 0
                self._thread_log(
                    f"TOUCH  seed_actions_skipped batch={batch_id} reason=no_safe_candidate "
                    f"candidates={len(all_candidates)} min_score={min_score} max_score={max_score} "
                    f"fixed_comment_text={str(bool(fixed_comment_text)).lower()}"
                )
                return 0
            created_count = 0
            self.service.storage.set_active_collection_batch(batch_id)
            for row in rows or []:
                candidate_id = str(row["id"] or "")
                username = str(row["username"] or "")
                target_url = str(row["source_path"] or "")
                if not candidate_id or not username or not target_url:
                    continue
                score = int(row["qualify_score"] or 0)
                priority = "high" if score >= 70 else "normal"
                try:
                    recommender = self.service.router.operation_leads.copy_recommender
                    suggestion = recommender.recommend("comment_reply", dict(row), "目标快发保底触达", priority, None)
                    suggested_text = str(getattr(suggestion, "text", "") or "").strip()
                except Exception:
                    suggested_text = ""
                suggested_text = suggested_text or "Good question. I would check the latest product details before deciding."
                lead_id, _ = self.service.storage.upsert_operation_lead(
                    candidate_id,
                    "目标快发保底触达",
                    priority,
                    max(score, 60),
                    "live_comment fallback: high-intent candidate without executable comment action",
                    source_path=target_url,
                )
                item = ActionQueueItem(
                    id=new_id("aq"),
                    lead_id=lead_id,
                    action_type="comment_reply",
                    target_username=username,
                    target_url=target_url,
                    suggested_text=suggested_text,
                    reason="live_comment fallback seed action standard_outreach_policy",
                    status="approved",
                    risk_level="medium",
                )
                action_id, created = self.service.storage.upsert_action_queue_item(item)
                self.service.storage.confirm_action_execution(
                    action_id,
                    confirmed_by="quick_send",
                    note="live comment fallback auto confirm",
                )
                if created:
                    created_count += 1
                    self.service.storage.log_event(
                        "action_queue_created",
                        action_id,
                        {"action_type": "comment_reply", "username": username, "batch_id": batch_id, "fallback": True},
                    )
            return created_count
        except Exception as exc:
            self._thread_log(f"WARN   live_comment seed_actions_failed batch={batch_id} error={exc}")
            return 0

    def _quick_comment_text(self) -> str:
        try:
            value = str(getattr(self.console, "quick_comment_text_var", None).get() or "").strip()
        except Exception:
            value = ""
        return "" if value.lower() in {"auto", "自动", "自动生成"} else value

    def _comment_reply_ai_settings(self) -> dict:
        try:
            getter = getattr(self.console, "comment_reply_ai_settings", None)
            if callable(getter):
                return getter()
        except Exception:
            pass
        return {
            "strategy": "规则模板（默认）",
            "endpoint_configured": False,
            "model": "",
            "api_key_configured": False,
            "fixed_comment_text_configured": bool(self._quick_comment_text()),
            "execution_policy": "ai_suggestion_only_live_submit_requires_confirmation",
            "no_auto_ai_submit": True,
        }

    def _apply_live_comment_text_override(self, batch_id: str, comment_text: str) -> int:
        text = str(comment_text or "").strip()
        if not text:
            return 0
        try:
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            with self.service.storage.connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE action_queue
                    SET suggested_text=?, reason=CASE
                        WHEN reason LIKE '%quick_send_comment_text%' THEN reason
                        ELSE TRIM(reason || ' quick_send_comment_text')
                    END
                    WHERE batch_id=?
                      AND action_type='comment_reply'
                      AND status IN ('pending', 'pending_review', 'approved', 'retryable', 'account_switched')
                    """,
                    (text, batch_id),
                )
                count = int(cursor.rowcount or 0)
            if count:
                self.service.storage.log_event(
                    "action_queue_comment_text_overridden",
                    batch_id,
                    {"count": count, "comment_text": text, "updated_at": now},
                )
                self._thread_log(f"TOUCH  comment_text_applied batch={batch_id} count={count} text={text}")
            return count
        except Exception as exc:
            self._thread_log(f"WARN   live_comment text_override_failed batch={batch_id} error={exc}")
            return 0

    def _log_action_router_result(self, result: dict, mode_label: str = "action_preflight"):
        for item in list((result or {}).get("results") or [])[:30]:
            self._thread_log(
                f"TOUCH  {item.get('status', '')} mode={mode_label} action={item.get('action_id', '')} "
                f"type={item.get('action_type', '')} profile={item.get('profile_id', '')} "
                f"execution={item.get('execution_id', '')} error={item.get('error_code', '')} "
                f"evidence={item.get('evidence_path', '')}"
            )
        errors = self._format_error_counts((result or {}).get("errors") or {})
        self._thread_log(
            f"TOUCH  run_completed mode={mode_label} selected={(result or {}).get('selected_actions', 0)} "
            f"success={(result or {}).get('success', 0)} failed={(result or {}).get('failed', 0)} "
            f"skipped={(result or {}).get('skipped', 0)} switched={(result or {}).get('account_switched', 0)} "
            f"errors={errors or '无'}"
        )
            
    def _log_collection_finished(self, result):
        error_text = self._format_error_counts(result.errors)
        next_action = self._collection_next_action(result.errors)
        self._log(
            f"DONE   collection processed_sources={result.processed_sources} "
            f"json={result.report_json_path or '未生成'} csv={result.report_csv_path or '未生成'} "
            f"errors={error_text or '无'} next={next_action}"
        )
        if result.errors:
            self._log(f"WARN   collection recoverable_errors={error_text} no_popup=true message=不会弹窗阻塞 next=账号状态/错误诊断")

    def _collection_finished(self, result, write_log: bool = True):
        # Operator log contract: PLAN   campaign / CHECK  profile_preflight / START  campaign / DONE   collection / WARN   collection recoverable_errors / _schedule_runtime_refresh / no_popup=true
        self.console.refresh(self._current_snapshot())
        if write_log:
            self._log_collection_finished(result)

    def _collection_next_action(self, errors: dict | None) -> str:
        errors = errors or {}
        if errors.get("PROFILE_START_FAILED"):
            return "更换可启动账号分组或检查 ixBrowser Profile"
        if errors.get("EMPTY_RESULT_RETRY"):
            return "当前页面无可采内容，建议换热视频链接/达人主页或更换账号分组"
        if errors.get("LOGIN_REQUIRED"):
            return "该账号需要重新登录或换可浏览账号"
        if errors.get("CAPTCHA_DETECTED"):
            return "账号触发验证，先人工处理或换号"
        if errors.get("PROXY_FAILED"):
            return "代理异常，先检查网络配置"
        return "查看客户池和动作队列"

    def _format_error_counts(self, errors: dict | None) -> str:
        rows = []
        for code, count in sorted((errors or {}).items()):
            if not code:
                continue
            rows.append(f"{code}={count}")
        return ", ".join(rows)

    def _log_profile_preflight_details(self, profile_preflight: dict, stage: str = "profile_preflight"):
        results = list((profile_preflight or {}).get("results") or [])
        if not results:
            self._thread_log(f"CHECK  profile_preflight_details stage={stage} rows=0")
            return
        for row in results[:20]:
            profile_id = str(row.get("profile_id") or "")
            status = "可用" if row.get("ok") else "不可用"
            error_code = str(row.get("error_code") or "")
            evidence = str(row.get("evidence_path") or "")
            message = str(row.get("error_message") or "").replace("\n", " ").strip()
            if len(message) > 120:
                message = f"{message[:117]}..."
            if row.get("ok"):
                close_action = str(row.get("close_action") or "")
                if not close_action:
                    close_action = "preflight_ok_retained" if row.get("session_retained") else "preflight_ok_released"
                if close_action == "preflight_ok_retained":
                    operator_hint = "预检通过，浏览器实例已保留并交接给后续任务"
                else:
                    operator_hint = "预检通过后自动关闭浏览器实例，不是闪退"
            elif error_code == "LOGIN_REQUIRED":
                close_action = "closed_and_switched"
                operator_hint = "TikTok登录态不足，已关闭并自动换号"
            elif error_code:
                close_action = "closed_and_skipped"
                operator_hint = "配置预检异常，已关闭并继续下一个账号"
            else:
                close_action = "closed_after_check"
                operator_hint = "预检结束后自动回收浏览器实例"
            self._thread_log(
                f"CHECK  profile_preflight_detail stage={stage} profile={profile_id or '-'} "
                f"status={status} error={error_code or '无'} evidence={evidence or '-'} "
                f"close_action={close_action} operator_hint={operator_hint} message={message or '-'}"
            )
        remaining = len(results) - 20
        if remaining > 0:
            self._thread_log(f"CHECK  profile_preflight_detail stage={stage} remaining={remaining}")

    def _current_growth_event_rowid(self) -> int:
        try:
            with self.service.storage.connect() as conn:
                value = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM growth_events").fetchone()[0]
                return int(value or 0)
        except Exception:
            return 0

    def _log_recent_runtime_events(self):
        try:
            with self.service.storage.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT rowid, event, entity_id, payload, created_at
                    FROM growth_events
                    WHERE rowid > ?
                    ORDER BY rowid ASC
                    LIMIT 120
                    """,
                    (int(self._runtime_event_last_rowid or 0),),
                ).fetchall()
        except Exception as exc:
            self._log(f"WARN   runtime_event_tail failed error={exc}")
            return
        for row in rows:
            self._runtime_event_last_rowid = max(int(self._runtime_event_last_rowid or 0), int(row["rowid"] or 0))
            line = self._format_runtime_event_log(dict(row))
            if line:
                self._log(line)

    def _format_runtime_event_log(self, row: dict) -> str:
        event = str(row.get("event") or "")
        payload_raw = row.get("payload") or "{}"
        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw or {})
        except Exception:
            payload = {}
        entity_id = str(row.get("entity_id") or "")
        if event == "video_discovered":
            return (
                f"VIDEO  discovered content={entity_id or payload.get('video_id', '')} "
                f"views={payload.get('views', '')}"
            )
        if event == "topic_video_comment_scan_started":
            return (
                f"VIDEO  comment_scan_started content={entity_id} profile={payload.get('profile_id', '')} "
                f"source={payload.get('source_value', '')} url={payload.get('video_url', '')}"
            )
        if event == "collection_source_failed":
            return (
                f"SOURCE failed batch={payload.get('batch_id', '')} "
                f"type={payload.get('source_type', '')} value={payload.get('source_value', '')} "
                f"error={payload.get('error_code', '')} message={payload.get('message', '')}"
            )
        if event in {
            "profile_queue_enqueued",
            "profile_queue_started",
            "profile_queue_skipped",
            "profile_queue_source_failed",
            "profile_queue_source_completed",
            "profile_queue_quota_reached",
        }:
            label = {
                "profile_queue_enqueued": "queued",
                "profile_queue_started": "started",
                "profile_queue_skipped": "skipped",
                "profile_queue_source_failed": "source_failed",
                "profile_queue_source_completed": "source_completed",
                "profile_queue_quota_reached": "quota_reached",
            }.get(event, event)
            return (
                f"QUEUE  profile_{label} batch={payload.get('batch_id', '')} "
                f"profile={payload.get('profile_id', entity_id)} status={payload.get('status', '')} "
                f"reason={payload.get('reason', '') or '无'} "
                f"sources_done={payload.get('sources_done', 0)}/{payload.get('max_sources_per_profile', '')} "
                f"source={payload.get('source_type', '')}:{payload.get('source_value', '')}"
            )
        if event == "topic_material_discovered":
            return f"VIDEO  material_discovered content={entity_id} url={payload.get('video_url', '')}"
        if event in {"comment_scan_discarded_url_mismatch", "comment_scan_url_mismatch_limit_reached"}:
            return (
                f"VIDEO  url_mismatch content={entity_id} expected={payload.get('expected_video_id', '')} "
                f"final={payload.get('final_url', '')} discarded={payload.get('discarded_comment_count', '')}"
            )
        if event == "comment_scan_same_creator_fallback_accepted":
            return (
                f"VIDEO  same_creator_fallback content={entity_id} expected={payload.get('expected_video_id', '')} "
                f"final={payload.get('final_url', '')} comments={payload.get('comment_count', 0)}"
            )
        if event in {"topic_comment_scan_empty_video", "topic_comment_scan_empty_limit_reached"}:
            return (
                f"VIDEO  comment_scan_empty source={payload.get('source_value', entity_id)} "
                f"profile={payload.get('profile_id', '')} reason={payload.get('error_code', event)}"
            )
        if event == "action_queue_created":
            return (
                f"TOUCH  queued action={payload.get('action_type', '')} "
                f"user={payload.get('username', '')} id={entity_id}"
            )
        if event == "lead_pipeline_completed":
            return (
                f"LEAD   pipeline_completed batch={payload.get('batch_id', entity_id)} "
                f"candidates={payload.get('candidate_users', 0)} high_intent={payload.get('high_value_candidates', 0)} "
                f"leads={payload.get('operation_leads', 0)} actions={payload.get('action_queue', 0)} "
                f"created=intents:{payload.get('intents_created', 0)},leads:{payload.get('leads_created', 0)},actions:{payload.get('actions_created', 0)}"
            )
        if event == "action_queue_skipped_low_intent":
            return (
                f"LEAD   action_skipped_low_intent user={payload.get('username', '')} "
                f"score={payload.get('score', '')} min={payload.get('min_score', '')} lead_type={payload.get('lead_type', '')}"
            )
        if event == "action_execution_confirmed":
            return f"TOUCH  confirmed action={entity_id} by={payload.get('confirmed_by', '')}"
        if event == "action_router_success":
            return (
                f"TOUCH  success action={entity_id} profile={payload.get('profile_id', '')} "
                f"execution={payload.get('execution_id', '')}"
            )
        if event == "action_router_skipped":
            return (
                f"TOUCH  skipped action={entity_id} profile={payload.get('profile_id', '')} "
                f"error={payload.get('error_code', '')}"
            )
        if event == "action_execution_result_recorded":
            return (
                f"TOUCH  result action={entity_id} execution={payload.get('execution_id', '')} "
                f"status={payload.get('status', '')} error={payload.get('error_code', '')}"
            )
        if event == "action_router_run_completed":
            errors = self._format_error_counts(payload.get("errors") or {})
            return (
                f"TOUCH  run_completed selected={payload.get('selected_actions', 0)} "
                f"success={payload.get('success', 0)} skipped={payload.get('skipped', 0)} "
                f"failed={payload.get('failed', 0)} errors={errors or '无'}"
            )
        if event == "execution_report_exported":
            return f"TOUCH  report_exported json={payload.get('json_path', '')}"
        return ""

    def _schedule_runtime_refresh(self):
        def refresh_once():
            try:
                snapshot = self._current_snapshot()
                self.console.refresh(snapshot)
                self._log_recent_runtime_events()
                funnel = getattr(snapshot, "campaign_funnel", {}) or {}
                active_batch_id = self.active_batch_id or str(funnel.get("batch_id") or "")
                latest_batch = self._batch_from_snapshot(snapshot, active_batch_id)
                latest_task = self._task_from_snapshot(snapshot, active_batch_id)
                if latest_batch or latest_task:
                    task_status = str(latest_task.get("status", "") or "")
                    task_profile = str(latest_task.get("profile_id", "") or "")
                    task_error = str(latest_task.get("error_code", "") or "")
                    if (
                        latest_batch
                        and str(latest_batch.get("status") or "") == "pending"
                        and not latest_task
                        and active_batch_id
                    ):
                        task_status = "profile_preflight"
                        task_profile = ""
                        task_error = ""
                    line = (
                        f"RUN    campaign={str(funnel.get('campaign_id') or self.active_campaign_id or '')[-10:]} "
                        f"batch={latest_batch.get('status', '')} "
                        f"progress={latest_batch.get('processed_sources', 0)}/{latest_batch.get('total_sources', 0)} "
                        f"task={task_status} profile={task_profile} "
                        f"error={task_error}"
                    )
                    now = time.time()
                    if line != self._last_runtime_status_line or now - float(self._last_runtime_status_at or 0.0) >= 15.0:
                        self._log(line)
                        self._last_runtime_status_line = line
                        self._last_runtime_status_at = now
                if latest_batch and str(latest_batch.get("status") or "") in {"running", "pending"}:
                    self.root.after(3000, refresh_once)
            except Exception as exc:
                self._log(f"ERROR  refresh_runtime failed error={exc}")

        self.root.after(1500, refresh_once)

    def _batch_from_snapshot(self, snapshot, batch_id: str) -> dict:
        batches = list(getattr(snapshot, "collection_batches", []) or [])
        if batch_id:
            for batch in batches:
                if str(batch.get("id") or "") == batch_id:
                    return batch
        funnel = getattr(snapshot, "campaign_funnel", {}) or {}
        funnel_batch_id = str(funnel.get("batch_id") or "")
        if funnel_batch_id:
            for batch in batches:
                if str(batch.get("id") or "") == funnel_batch_id:
                    return batch
        return batches[0] if batches else {}

    def _task_from_snapshot(self, snapshot, batch_id: str) -> dict:
        tasks = list(getattr(snapshot, "collection_tasks", []) or [])
        if batch_id:
            for task in tasks:
                if str(task.get("batch_id") or "") == batch_id:
                    return task
            return {}
        funnel = getattr(snapshot, "campaign_funnel", {}) or {}
        funnel_batch_id = str(funnel.get("batch_id") or "")
        if funnel_batch_id:
            for task in tasks:
                if str(task.get("batch_id") or "") == funnel_batch_id:
                    return task
            return {}
        return tasks[0] if tasks else {}

    def export_report(self):
        if not self.active_campaign_id:
            self._log("BLOCK  report_export not_started reason=没有本轮获客任务 next=先输入推广目标并开始获客")
            return
        campaign_artifacts = self.workflow.export_campaign_artifacts(campaign_id=self.active_campaign_id)
        self.console.refresh(self._current_snapshot())
        if campaign_artifacts.get("json_path"):
            self._log(
                f"DONE   report_exported campaign={self.active_campaign_id} "
                f"json={campaign_artifacts.get('json_path')} customers={campaign_artifacts.get('customers_csv_path')} "
                f"actions={campaign_artifacts.get('actions_csv_path')} executions={campaign_artifacts.get('executions_csv_path')}"
            )
        else:
            self._log("ERROR  report_export_failed error=REPORT_EXPORT_FAILED")

    def run_due_scans(self):
        result = self.workflow.run_due_scans(self._selected_profiles())
        self.console.refresh(self._current_snapshot())
        self._log(f"DONE   due_scans result={result}")

    def run_selected_scan(self, scan_id: str):
        result = self.workflow.run_scheduled_scan_now(scan_id, self._selected_profiles())
        self.console.refresh(self._current_snapshot())
        self._log(f"DONE   selected_scan scan_id={scan_id} result={result}")

    def rerun_error(self, error_code: str):
        profiles = self._selected_profiles()
        if not profiles:
            self._log(
                f"BLOCK  rerun_error not_started error={error_code} "
                "reason=没有可用账号 next=刷新账号分组或更换分组"
            )
            return
        config = GrowthTaskConfig(
            max_videos_per_creator=max(1, int(self.console.scan_max_videos_var.get() or 5)),
            max_comments_per_video=max(1, int(self.console.scan_max_comments_var.get() or 10)),
            profile_group=self._selected_group_name(),
            task_delay_min_seconds=max(30, int(self.console.scan_interval_var.get() or 60)),
            task_delay_max_seconds=max(30, int(self.console.scan_interval_var.get() or 60)),
        )
        result = self.workflow.rerun_latest_failed_batch_for_error(error_code, profiles, config=config)
        self.console.refresh(self._current_snapshot())
        self._log(f"DONE   rerun_error error={error_code} result={result}")

    def rerun_tasks(self, task_ids: list[str]):
        profiles = self._selected_profiles()
        if not profiles:
            self._log(
                f"BLOCK  rerun_tasks not_started tasks={len(task_ids or [])} "
                "reason=没有可用账号 next=刷新账号分组或更换分组"
            )
            return
        config = GrowthTaskConfig(
            max_videos_per_creator=max(1, int(self.console.scan_max_videos_var.get() or 5)),
            max_comments_per_video=max(1, int(self.console.scan_max_comments_var.get() or 10)),
            profile_group=self._selected_group_name(),
            task_delay_min_seconds=max(30, int(self.console.scan_interval_var.get() or 60)),
            task_delay_max_seconds=max(30, int(self.console.scan_interval_var.get() or 60)),
        )
        result = self.workflow.rerun_collection_tasks(task_ids, profiles, config=config)
        self.console.refresh(self._current_snapshot())
        self._log(f"DONE   rerun_tasks tasks={len(task_ids or [])} result={result}")


def main() -> int:
    root = tk.Tk()
    GrowthIntelligenceStandaloneApp(root)
    root.mainloop()
    return 0

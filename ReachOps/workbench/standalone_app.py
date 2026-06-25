# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import threading
import tkinter as tk
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk
from urllib.parse import urlparse

from ReachOps.intelligence import GrowthIntelligenceService, GrowthTaskConfig
from ReachOps.runtime_paths import RuntimePaths

from .console import GrowthOpsConsole, normalize_source_type
from .workflow_service import GrowthWorkflowService

APP_COLORS = {
    "bg": "#f0f0f0",
    "surface": "#f0f0f0",
    "border": "#d9d9d9",
    "text": "#000000",
    "muted": "#666666",
    "accent": "#000000",
    "accent_soft": "#e6e6e6",
}


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
        count_label = "9999+" if count > 9999 else str(count).rjust(5)
    else:
        count_label = "    ?"
    return f"[{count_label}] {name} (ID: {group_id or '-'})"


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


def stable_combobox_values(values: list[str]) -> list[str]:
    stable = [sanitize_tk_text(item) for item in values or []]
    stable = [item for item in stable if item]
    return stable


def group_name_from_display(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("[") and "] " in text:
        text = text.split("] ", 1)[1].strip()
    if " 个账号 | " in text or text.startswith("待读取账号数 | "):
        text = text.split(" | ", 1)[1].strip()
    if text.endswith(")") and "(ID:" in text:
        return text.rsplit("(ID:", 1)[0].strip()
    if text.endswith(")") and "(" in text:
        return text.rsplit("(", 1)[0].strip()
    if " | ID " in text:
        return text.split(" | ID ", 1)[0].strip()
    return text


def load_ixbrowser_profile_rows(max_pages: int = 50, group_id: str | int = 0, limit: int = 100) -> list[dict]:
    from ixbrowser_local_api import IXBrowserClient

    client = IXBrowserClient()
    requested_group_id = str(group_id or "").strip()
    rows = []
    seen = set()
    consecutive_empty = 0
    total = 0
    for page in range(1, max(1, int(max_pages or 50)) + 1):
        kwargs = {"page": page, "limit": max(1, int(limit or 100))}
        if requested_group_id and requested_group_id != "0":
            kwargs["group_id"] = int(requested_group_id)
        response = client.get_profile_list(**kwargs)
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
    from ixbrowser_local_api import IXBrowserClient

    client = IXBrowserClient()
    rows = []
    seen = set()
    consecutive_empty = 0
    total = 0
    for page in range(1, max(1, int(max_pages or 100)) + 1):
        response = client.get_group_list(page=page, limit=max(1, int(limit or 100)))
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


def load_ixbrowser_group_profile_count(group_id: str | int, max_pages: int = 50, limit: int = 100) -> int:
    if not str(group_id or "").strip():
        return 0
    from ixbrowser_local_api import IXBrowserClient

    client = IXBrowserClient()
    rows = []
    seen = set()
    consecutive_empty = 0
    total = 0
    for page in range(1, max(1, int(max_pages or 50)) + 1):
        response = client.get_profile_list(page=page, limit=max(1, int(limit or 100)), group_id=int(group_id or 0))
        batch, response_total = extract_ixbrowser_rows(response)
        try:
            total = int(response_total or getattr(client, "total", 0) or total)
        except Exception:
            total = total
        if total and page == 1:
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
    return len(rows)


def resolve_ixbrowser_group_counts(groups: list[dict], max_workers: int = 8) -> list[dict]:
    pending = [group for group in groups or [] if group.get("group_id")]
    if not pending:
        return groups
    with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers or 8), len(pending)))) as executor:
        futures = {executor.submit(load_ixbrowser_group_profile_count, group.get("group_id")): group for group in pending}
        for future in as_completed(futures):
            group = futures[future]
            try:
                group["count"] = int(future.result())
                group["count_known"] = True
            except Exception:
                group["count"] = int(group.get("count") or 0)
    return groups


def load_ixbrowser_profile_snapshot(max_pages: int = 50, resolve_group_counts: bool = False, include_profiles: bool = True) -> dict:
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
    if not groups:
        for group in [normalize_ixbrowser_group(row) for row in load_ixbrowser_group_rows()]:
            key = str(group.get("group_id") or group.get("group_name") or "")
            if not key or key in seen_groups:
                continue
            resolved_count = profile_counts.get(
                str(group.get("group_id") or ""),
                profile_counts.get(str(group.get("group_name") or ""), int(group.get("count") or 0)),
            )
            group["count"] = resolved_count
            if profile_counts:
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
    }


class StandaloneProfileRegistry:
    """Standalone ixBrowser profile/group cache for Growth Intelligence."""

    def __init__(self):
        self.profiles: list[dict] = []
        self.groups: list[dict] = []
        self.group_by_name: dict[str, dict] = {}

    def refresh(self, max_pages: int = 50, include_profiles: bool = False) -> dict:
        # Keep ReachOps aligned with Smart Publish: refresh the complete profile
        # catalog first, then build group options locally from group_id/group_name.
        snapshot = load_ixbrowser_profile_snapshot(max_pages=max_pages, resolve_group_counts=False, include_profiles=True)
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
        if not self.profiles:
            self.refresh(include_profiles=True)
        group = self.group_by_name.get(str(group_name or "")) or self.group_by_name.get(str(group_name or "").lower())
        group_id = str((group or {}).get("group_id") or "")
        if (group or {}).get("all_profiles") or str(group_name or "").strip() in {"", "全部配置"}:
            profiles = list(self.profiles)
        elif group_id:
            profiles = [profile for profile in self.profiles if str(profile.get("group_id") or "") == group_id]
            group["count"] = len(profiles)
            group["count_known"] = True
        else:
            profiles = [profile for profile in self.profiles if profile_matches_group(profile, group_name)]
        return profiles[: max(1, int(limit or 50))]


def load_ixbrowser_profiles(profile_group: str = "", max_pages: int = 50, limit: int = 50) -> list[dict]:
    """Best-effort ixBrowser profile loader for the standalone module."""

    snapshot = load_ixbrowser_profile_snapshot(max_pages=max_pages)
    profiles = [row for row in snapshot["profiles"] if profile_matches_group(row, profile_group)]
    return profiles[: max(1, int(limit or 50))]


class GrowthIntelligenceStandaloneApp:
    """Standalone Growth Intelligence workspace with its own left navigation."""

    def __init__(self, root: tk.Tk | tk.Toplevel, base_dir: str | None = None, auto_refresh_profiles: bool = True):
        self.root = root
        self.paths = RuntimePaths.build(base_dir).ensure_dirs()
        self.base_dir = self.paths.base_dir
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
        self.runtime_log_path = Path(self.service.paths.logs_dir) / "growth_ops_runtime.log"
        self._build()
        self._log(
            f"READY  app_started data_dir={self.base_dir} "
            f"log={self.runtime_log_path}"
        )

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
            workflow_service=self.workflow,
            on_start_collection=self.start_collection_from_console,
            on_export_report=self.export_report,
            on_rerun_error=self.rerun_error,
            on_rerun_tasks=self.rerun_tasks,
            on_run_due_scans=self.run_due_scans,
            on_run_selected_scan=self.run_selected_scan,
            on_refresh_profiles=self.refresh_profile_groups,
            operator_status_var=self.status_var,
        )
        self.console.grid(row=0, column=0, sticky="nsew")
        self.console.refresh(self._current_snapshot())
        self.console.set_profile_group_options(["正在读取分组..."], "正在读取分组...")
        if self.auto_refresh_profiles:
            self.root.after(300, lambda: (self._log("CONFIG refresh_profiles started auto=true"), self._refresh_profile_groups_sync(show_message=False)))

    def _configure_style(self):
        style = ttk.Style(self.root)
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("Shell.TFrame", background=APP_COLORS["bg"])
        style.configure("Header.TFrame", background=APP_COLORS["bg"])
        style.configure("TLabel", background=APP_COLORS["bg"], foreground=APP_COLORS["text"])
        style.configure("AppTitle.TLabel", background=APP_COLORS["surface"], foreground=APP_COLORS["text"], font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("AppSubtitle.TLabel", background=APP_COLORS["surface"], foreground=APP_COLORS["muted"], font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", background=APP_COLORS["surface"], foreground=APP_COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("TButton", padding=(10, 5), font=("Microsoft YaHei UI", 10))

    def _log(self, message: str):
        text = str(message or "")
        self.status_var.set(text)
        try:
            self.console.append_runtime_log(text)
        except Exception:
            pass
        try:
            self.runtime_log_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.runtime_log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{ts}  {text}\n")
        except Exception:
            pass

    def _current_snapshot(self):
        return self.workflow.build_snapshot(
            campaign_id=self.active_campaign_id,
            batch_id=self.active_batch_id,
        )

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
        try:
            from .account_health_manager import AccountHealthManager

            profiles = AccountHealthManager(self.service.storage).rank_profiles(candidate_profiles, max_count=limit)
        except Exception as exc:
            profiles = list(candidate_profiles)[:limit]
            self._log(f"WARN   selected_profiles health_rank_failed error={exc}")
        self._log(
            f"CONFIG selected_profiles group={group or '全部'} requested={limit} "
            f"candidates={len(candidate_profiles)} selected={len(profiles)} "
            f"excluded={max(0, len(candidate_profiles) - len(profiles))}"
        )
        return profiles

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
            snapshot = self.profile_registry.refresh(include_profiles=False)
            if not snapshot.get("group_count"):
                self._log("WARN   refresh_profiles empty_groups retry=1")
                time.sleep(1.0)
                snapshot = self.profile_registry.refresh(include_profiles=False)
            self._log(
                f"CONFIG refresh_profiles groups_loaded groups={snapshot.get('group_count', 0)} "
                f"profiles={'deferred' if snapshot.get('profiles_deferred') else snapshot.get('profile_count', 0)}"
            )
            synced = self._sync_profiles_to_account_status(snapshot.get("profiles") or [])
            snapshot["synced_profile_count"] = synced
        except Exception as exc:
            snapshot = {"profiles": [], "groups": [], "profile_count": 0, "group_count": 0, "profiles_deferred": True, "error": str(exc)}
        self._apply_profile_group_snapshot(snapshot, show_message=show_message)

    def _refresh_profile_groups_threaded(self, show_message: bool = True):
        def runner():
            try:
                snapshot = self.profile_registry.refresh(include_profiles=False)
                synced = self._sync_profiles_to_account_status(snapshot.get("profiles") or [])
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
                self.profile_registry.profiles = list(snapshot.get("profiles") or [])
            elif self.profile_registry.groups:
                snapshot = dict(snapshot)
                snapshot["groups"] = list(self.profile_registry.groups)
                snapshot["group_count"] = len(self.profile_registry.groups)
                self._log(f"WARN   refresh_profiles empty_groups using_cached={len(self.profile_registry.groups)}")
            else:
                self.profile_registry.profiles = list(snapshot.get("profiles") or [])
                self.profile_registry.groups = []
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
                selected = next((display for display in groups if group_name_from_display(display).lower() == "canada"), groups[0])
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
            safe_selected = next((item for item in safe_groups if group_name_from_display(item).lower() == "canada"), safe_groups[0])
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
        source_value = self.console.scan_source_value_var.get().strip()
        if not source_value:
            self._log("BLOCK  campaign not_started reason=缺少推广目标 next=请先输入产品链接、关键词、竞品、视频或直播间")
            return
        source_type = normalize_source_type(self.console.scan_source_type_var.get())
        max_videos = max(1, int(self.console.scan_max_videos_var.get() or 5))
        max_comments = max(1, int(self.console.scan_max_comments_var.get() or 10))
        task_interval = max(30, int(self.console.scan_interval_var.get() or 60))
        profile_limit = max(1, int(self.console.scan_profile_limit_var.get() or 3))
        profile_group = self._selected_group_name()
        intent_keywords = parse_keyword_list(self.console.scan_intent_keywords_var.get())
        exclude_keywords = parse_keyword_list(self.console.scan_exclude_keywords_var.get())
        plan = self.service.create_campaign_plan(
            source_value,
            intent_keywords=intent_keywords,
            exclude_keywords=exclude_keywords,
            max_sources=max(1, min(max_videos, 5)),
        )
        campaign = plan.get("campaign") or {}
        persona = plan.get("persona") or {}
        planned_sources = plan.get("sources") or []
        self.active_campaign_id = str(campaign.get("id") or "")
        self.active_batch_id = ""
        if source_type != "auto" and planned_sources:
            normalized_value, validation_error = self._validate_collection_source(source_type, source_value)
            if validation_error:
                self._log(
                    f"BLOCK  campaign not_started campaign={campaign.get('id', '')} reason={validation_error} "
                    f"source_type={source_type} target={source_value} next=请切换自动识别或输入有效链接"
                )
                return
            planned_sources = [
                {
                    **planned_sources[0],
                    "source_type": source_type,
                    "source_value": normalized_value,
                }
            ]
        if not planned_sources:
            self._log(f"BLOCK  campaign not_started campaign={campaign.get('id', '')} reason=没有生成获客来源")
            return
        range_config = {
            "max_videos": max_videos,
            "max_comments": max_comments,
            "profile_limit": profile_limit,
            "task_interval": task_interval,
        }
        display_plan = {
            **plan,
            "sources": planned_sources,
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
            f"PLAN   campaign id={campaign.get('id', '')} input_type={campaign.get('input_type', '')} "
            f"product={campaign.get('product_name', '')} sources={len(planned_sources)} "
            f"range=每来源最多{max_videos}条视频/每视频最多{max_comments}条评论/任务间隔{task_interval}秒 "
            f"intent_keywords={','.join(intent_keywords) or 'auto'} "
            f"exclude_keywords={','.join(exclude_keywords) or 'none'} "
            f"planned_sources={' | '.join(planned_source_labels)}"
        )
        profiles = self._selected_profiles()
        if not profiles:
            self._log("BLOCK  campaign not_started reason=没有可用账号 next=点击刷新账号分组，并选择 discovery/comment/action 分组")
            return

        def runner():
            from .profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig

            profile_ids = [str(row.get("profile_id") or row.get("id") or "") for row in profiles]
            self.root.after(
                0,
                lambda: self._log(
                    f"CHECK  profile_preflight stage=collection group={profile_group or self._current_group_name() or '未指定'} "
                    f"profiles={len(profiles)} profile_ids={','.join(profile_ids[:8])}"
                ),
            )
            preflight_checker = ProfilePreflightChecker(
                self.service.storage,
                ProfilePreflightConfig(
                    max_workers=max(1, min(int(self.console.action_execution_workers_var.get() or 2), len(profiles))),
                    page_load_timeout_seconds=20,
                    wait_after_open_seconds=2.0,
                    total_timeout_seconds=max(30, min(120, len(profiles) * 35)),
                    evidence_dir=str(Path(self.service.paths.reports_dir) / "collection_profile_preflight_evidence"),
                    close_browser_after_check=True,
                ),
            )
            executable_profiles, profile_preflight = preflight_checker.available_profiles(profiles)
            preflight_errors = self._format_error_counts(profile_preflight.get("errors") or {})
            self.root.after(
                0,
                lambda: self._log(
                    f"CHECK  profile_preflight checked={profile_preflight.get('checked', 0)} "
                    f"available={profile_preflight.get('available', 0)} unavailable={profile_preflight.get('unavailable', 0)} "
                    f"errors={preflight_errors or '无'}"
                ),
            )
            self._log_profile_preflight_details(profile_preflight, stage="collection")
            self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
            if not executable_profiles:
                blocked_batch = self._create_preflight_blocked_batch(
                    campaign_id=str(campaign.get("id") or ""),
                    planned_sources=planned_sources,
                    profile_group=profile_group,
                    profile_preflight=profile_preflight,
                )
                self.active_batch_id = str(blocked_batch.get("id") or "")
                self.root.after(
                    0,
                    lambda: self._log(
                        "BLOCK  campaign not_started reason=没有通过登录态预检的账号 "
                        "error=NO_LOGGED_IN_PROFILE_AVAILABLE next=先登录账号或更换 discovery/comment/action 分组"
                    ),
                )
                self.root.after(0, lambda: self.console.refresh(self._current_snapshot()))
                return
            executable_profile_ids = [str(row.get("profile_id") or row.get("id") or "") for row in executable_profiles]
            self.root.after(
                0,
                lambda: self._log(
                    f"START  campaign id={campaign.get('id', '')} type={campaign.get('input_type', '')} target={source_value} "
                    f"sources={len(planned_sources)} persona_keywords={','.join((persona.get('intent_keywords') or [])[:6])} "
                    f"group={profile_group or self._current_group_name() or '未指定'} profiles={len(executable_profiles)} "
                    f"profile_ids={','.join(executable_profile_ids[:8])} max_videos={max_videos} "
                    f"max_comments={max_comments} interval_seconds={task_interval}"
                ),
            )
            result = self.service.run_collection(
                [{"type": row.get("source_type"), "value": row.get("source_value")} for row in planned_sources],
                executable_profiles,
                GrowthTaskConfig(
                    max_videos_per_creator=max_videos,
                    max_comments_per_video=max_comments,
                    profile_group=profile_group,
                    campaign_id=str(campaign.get("id") or ""),
                    intent_keywords=list(persona.get("intent_keywords") or intent_keywords),
                    exclude_keywords=list(persona.get("exclude_keywords") or exclude_keywords),
                    task_delay_min_seconds=task_interval,
                    task_delay_max_seconds=task_interval,
                ),
            )
            batch = self.service.storage.latest_collection_batch_for_campaign(str(campaign.get("id") or ""))
            self.active_batch_id = str(batch.get("id") or "")
            self.root.after(0, lambda: self._collection_finished(result))
            try:
                self._start_action_queue_processing(str(campaign.get("id") or ""), profile_group, executable_profiles)
            except Exception as e:
                self._thread_log(f"ERROR  action_preflight failed error={str(e)}")

        threading.Thread(target=runner, daemon=True).start()
        self._schedule_runtime_refresh()

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
        try:
            self.root.after(0, lambda: self._log(message))
        except Exception:
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

            pending_actions = [
                row
                for row in self.service.storage.list_action_queue(limit=100, batch_id=batch_id)
                if str(row.get("status") or "") in {"pending", "pending_review", "approved", "retryable", "account_switched"}
            ]
            if not pending_actions:
                self._thread_log(f"DONE   action_preflight skipped batch={batch_id} reason=本轮没有待触达动作")
                return {"selected_actions": 0, "batch_id": batch_id}

            workers = max(1, min(int(self.console.action_execution_workers_var.get() or 2), len(profiles)))
            per_profile_limit = max(1, int(self.console.action_execution_per_profile_var.get() or 5))
            hour_limit = max(1, int(self.console.action_execution_hour_limit_var.get() or 10))
            video_hour_limit = max(1, int(self.console.action_execution_video_hour_limit_var.get() or 1))
            self._thread_log(
                f"START  action_preflight batch={batch_id} actions={len(pending_actions)} "
                f"group={profile_group or self._current_group_name() or '未指定'} profiles={len(profiles)} "
                f"workers={workers} per_profile={per_profile_limit} no_submit=true"
            )
            preflight_checker = ProfilePreflightChecker(
                self.service.storage,
                ProfilePreflightConfig(
                    max_workers=max(1, min(workers, len(profiles))),
                    page_load_timeout_seconds=20,
                    wait_after_open_seconds=2.0,
                    evidence_dir=str(Path(self.service.paths.reports_dir) / "profile_preflight_evidence"),
                    close_browser_after_check=True,
                ),
            )
            executable_profiles, profile_preflight = preflight_checker.available_profiles(profiles)
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
            workers = max(1, min(workers, len(executable_profiles)))

            action_config = ActionRouterConfig(
                profile_group=profile_group,
                dry_run=False,
                auto_approve=True,
                auto_confirm=True,
                live_preflight_only=True,
                allow_live_submit=False,
                per_profile_action_limit=per_profile_limit,
                max_workers=workers,
                max_switch_attempts=2,
                per_profile_hour_limit=hour_limit,
                per_profile_video_hour_limit=video_hour_limit,
                batch_id=batch_id,
            )
            platform_executor = TikTokSeleniumActionExecutor(
                TikTokActionExecutorConfig(
                    close_browser_after_action=True,
                    preflight_only=True,
                    evidence_dir=str(Path(self.service.paths.reports_dir) / "action_preflight_evidence"),
                )
            )
            result = self.workflow.run_action_router(
                executable_profiles,
                config=action_config,
                platform_executor=platform_executor,
                limit=min(100, len(pending_actions)),
                export_report=True,
                batch_id=batch_id,
            )
            self._thread_log(
                f"DONE   action_preflight selected={result.get('selected_actions', 0)} "
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
            
    def _collection_finished(self, result):
        self.console.refresh(self._current_snapshot())
        error_text = self._format_error_counts(result.errors)
        next_action = self._collection_next_action(result.errors)
        self._log(
            f"DONE   collection processed_sources={result.processed_sources} "
            f"json={result.report_json_path or '未生成'} csv={result.report_csv_path or '未生成'} "
            f"errors={error_text or '无'} next={next_action}"
        )
        if result.errors:
            self._log(f"WARN   collection recoverable_errors={error_text} no_popup=true message=不会弹窗阻塞 next=账号状态/错误诊断")

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
            self._thread_log(
                f"CHECK  profile_preflight_detail stage={stage} profile={profile_id or '-'} "
                f"status={status} error={error_code or '无'} evidence={evidence or '-'} message={message or '-'}"
            )
        remaining = len(results) - 20
        if remaining > 0:
            self._thread_log(f"CHECK  profile_preflight_detail stage={stage} remaining={remaining}")

    def _schedule_runtime_refresh(self):
        def refresh_once():
            try:
                snapshot = self._current_snapshot()
                self.console.refresh(snapshot)
                funnel = getattr(snapshot, "campaign_funnel", {}) or {}
                active_batch_id = self.active_batch_id or str(funnel.get("batch_id") or "")
                latest_batch = self._batch_from_snapshot(snapshot, active_batch_id)
                latest_task = self._task_from_snapshot(snapshot, active_batch_id)
                if latest_batch or latest_task:
                    self._log(
                        f"RUN    campaign={str(funnel.get('campaign_id') or self.active_campaign_id or '')[-10:]} "
                        f"batch={latest_batch.get('status', '')} "
                        f"progress={latest_batch.get('processed_sources', 0)}/{latest_batch.get('total_sources', 0)} "
                        f"task={latest_task.get('status', '')} profile={latest_task.get('profile_id', '')} "
                        f"error={latest_task.get('error_code', '')}"
                    )
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
        funnel = getattr(snapshot, "campaign_funnel", {}) or {}
        funnel_batch_id = str(funnel.get("batch_id") or "")
        if funnel_batch_id:
            for task in tasks:
                if str(task.get("batch_id") or "") == funnel_batch_id:
                    return task
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

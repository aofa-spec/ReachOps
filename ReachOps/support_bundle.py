# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .runtime_paths import RuntimePaths


SUPPORT_BUNDLE_SCHEMA_VERSION = "reachops.support_bundle.v1"
REDACTION_TEXT = "***redacted***"
MAX_TEXT_FILE_BYTES = 512_000

SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "billing_email",
    "comment",
    "comment_text",
    "cookie",
    "cookies",
    "database_path",
    "dm_text",
    "email",
    "license_key",
    "operator_name",
    "password",
    "proxy",
    "proxy_password",
    "proxy_user",
    "raw_dom",
    "screenshot_path",
    "secret",
    "session",
    "submitted_text",
    "target_url",
    "text",
    "token",
    "username",
}

FORBIDDEN_PATH_TOKENS = (
    "activation_status",
    "cookie",
    "credential",
    "database",
    "growth_intelligence.db",
    "password",
    "proxy",
    "raw_dom",
    "screenshot",
    "secret",
    "session",
)

FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".html",
    ".htm",
    ".har",
}

ALLOWED_SUFFIXES = {".json", ".log", ".txt", ".md", ".csv"}

REDACTION_PATTERNS = (
    re.compile(r"https?://(?:www\.)?tiktok\.com/\S+", re.IGNORECASE),
    re.compile(r"(?<![\w.-])@[\w.-]{2,}", re.IGNORECASE),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?i)(api[_-]?key|license[_-]?key|password|proxy[_-]?password|token|secret)=\S+"),
)


@dataclass(frozen=True)
class SupportBundleFile:
    source_path: Path
    archive_path: str
    redacted_sha256: str
    redacted_size: int


def preview_support_bundle(runtime_paths: RuntimePaths, *, extra_paths: Iterable[str | Path] | None = None) -> dict[str, Any]:
    paths = runtime_paths.ensure_dirs()
    files, skipped = _collect_support_files(paths, extra_paths=extra_paths)
    return {
        "status": "preview",
        "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
        "explicit_customer_share_required": True,
        "telemetry_default_off": True,
        "redaction_applied_before_packaging": True,
        "exclusions": _exclusions(),
        "file_count": len(files),
        "files": [
            {
                "path": item.archive_path,
                "redacted_sha256": item.redacted_sha256,
                "redacted_size": item.redacted_size,
            }
            for item in files
        ],
        "skipped": skipped,
    }


def create_support_bundle(
    runtime_paths: RuntimePaths,
    output_path: str | Path,
    *,
    extra_paths: Iterable[str | Path] | None = None,
    customer_confirmed_share: bool = False,
) -> dict[str, Any]:
    if not customer_confirmed_share:
        preview = preview_support_bundle(runtime_paths, extra_paths=extra_paths)
        return {
            "status": "blocked",
            "reason": "customer_share_confirmation_required",
            "preview": preview,
            "path": "",
        }
    paths = runtime_paths.ensure_dirs()
    files, skipped = _collect_support_files(paths, extra_paths=extra_paths)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "explicit_customer_share_required": True,
        "customer_confirmed_share": True,
        "telemetry_default_off": True,
        "redaction_applied_before_packaging": True,
        "exclusions": _exclusions(),
        "files": [
            {
                "path": item.archive_path,
                "redacted_sha256": item.redacted_sha256,
                "redacted_size": item.redacted_size,
            }
            for item in files
        ],
        "skipped": skipped,
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for item in files:
            archive.writestr(item.archive_path, _redacted_bytes(item.source_path))
    return {
        "status": "created",
        "path": str(output),
        "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
        "file_count": len(files),
        "manifest": manifest,
    }


def _collect_support_files(
    paths: RuntimePaths,
    *,
    extra_paths: Iterable[str | Path] | None = None,
) -> tuple[list[SupportBundleFile], list[dict[str, Any]]]:
    candidates: list[Path] = []
    skipped: list[dict[str, Any]] = []
    for root in [Path(paths.logs_dir), Path(paths.reports_dir)]:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                candidates.append(path)
    for raw_path in extra_paths or []:
        candidates.append(Path(raw_path))

    files: list[SupportBundleFile] = []
    seen: set[str] = set()
    for path in candidates:
        reason = _skip_reason(path)
        archive_path = _archive_path(paths, path)
        if reason:
            skipped.append({"path": archive_path or str(path), "reason": reason})
            continue
        if archive_path in seen:
            continue
        seen.add(archive_path)
        payload = _redacted_bytes(path)
        files.append(
            SupportBundleFile(
                source_path=path,
                archive_path=archive_path,
                redacted_sha256=hashlib.sha256(payload).hexdigest(),
                redacted_size=len(payload),
            )
        )
    return files, skipped


def _redacted_bytes(path: Path) -> bytes:
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            return (json.dumps(_redact_json(payload), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        except Exception:
            pass
    text = path.read_text(encoding="utf-8", errors="replace")
    return (_redact_text(text) + ("\n" if text and not text.endswith("\n") else "")).encode("utf-8")


def _redact_json(value: Any, key: str = "") -> Any:
    if _sensitive_key(key):
        return REDACTION_TEXT
    if isinstance(value, dict):
        return {str(k): _redact_json(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(item, key) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in REDACTION_PATTERNS:
        redacted = pattern.sub(REDACTION_TEXT, redacted)
    return redacted


def _skip_reason(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return "not_a_file"
    lower = path.as_posix().lower()
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return "unsupported_file_type"
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return "forbidden_file_type"
    if any(token in lower for token in FORBIDDEN_PATH_TOKENS):
        return "forbidden_path"
    try:
        if path.stat().st_size > MAX_TEXT_FILE_BYTES:
            return "file_too_large"
    except OSError:
        return "stat_failed"
    return ""


def _archive_path(paths: RuntimePaths, path: Path) -> str:
    path = path.resolve()
    base = Path(paths.base_dir).resolve()
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return f"extra/{path.name}"


def _sensitive_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return normalized in SENSITIVE_KEYS or any(token in normalized for token in SENSITIVE_KEYS)


def _exclusions() -> dict[str, bool]:
    return {
        "sqlite_databases": True,
        "windows_credential_manager_secrets": True,
        "activation_status": True,
        "tiktok_cookies_sessions": True,
        "raw_screenshots_dom": True,
        "proxy_credentials": True,
        "real_targets_and_usernames": True,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

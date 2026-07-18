# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .runtime_paths import RuntimePaths


BACKUP_SCHEMA_VERSION = "reachops.backup.v1"
BACKUP_MAGIC = b"REACHOPS-BACKUP-V1\n"
KDF_ITERATIONS = 200_000
SALT_BYTES = 16
NONCE_BYTES = 16
TAG_BYTES = 32

FORBIDDEN_BACKUP_NAMES = {
    "reachops_activation_status.json",
    "reachops_activation_status.template.json",
    "cookies",
    "cookies.sqlite",
    "login data",
}
FORBIDDEN_BACKUP_TOKENS = (
    "cookie",
    "credential",
    "secret",
    "password",
    "proxy",
    "activation_status",
    "screenshot",
    "raw_dom",
    "session",
)


@dataclass(frozen=True)
class BackupFile:
    source_path: Path
    archive_path: str
    sha256: str
    size: int


def create_reachops_backup(
    runtime_paths: RuntimePaths,
    output_path: str | Path,
    password: str,
    *,
    include_evidence_files: bool = False,
) -> dict:
    _require_password(password)
    paths = runtime_paths.ensure_dirs()
    output = Path(output_path)
    files = _collect_backup_files(paths, include_evidence_files=include_evidence_files)
    manifest = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "backup_variant": "full" if include_evidence_files else "lightweight",
        "runtime_root_name": Path(paths.base_dir).name,
        "encryption": {
            "kdf": "pbkdf2_hmac_sha256",
            "iterations": KDF_ITERATIONS,
            "cipher": "hmac_sha256_stream_xor",
            "mac": "hmac_sha256",
        },
        "exclusions": {
            "windows_credential_manager_secrets": True,
            "activation_status": True,
            "tiktok_cookies_sessions": True,
            "raw_screenshots_dom": True,
            "proxy_credentials": True,
        },
        "files": [
            {"path": item.archive_path, "sha256": item.sha256, "size": item.size}
            for item in files
        ],
    }
    plaintext = _build_plaintext_zip(files, manifest)
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    header = BACKUP_MAGIC + salt + nonce
    ciphertext = _xor_bytes(plaintext, _keystream(_derive_key(password, salt, b"enc"), nonce, len(plaintext)))
    tag = hmac.new(_derive_key(password, salt, b"mac"), header + ciphertext, hashlib.sha256).digest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(header + ciphertext + tag)
    return {
        "status": "created",
        "path": str(output),
        "schema_version": BACKUP_SCHEMA_VERSION,
        "backup_variant": manifest["backup_variant"],
        "encrypted": True,
        "authenticated": True,
        "file_count": len(files),
        "manifest": manifest,
        "forbidden_entries": validate_backup_manifest(manifest)["forbidden_entries"],
    }


def inspect_reachops_backup(backup_path: str | Path, password: str) -> dict:
    plaintext = _decrypt_backup(Path(backup_path), password)
    manifest, _files = _read_plaintext_zip(plaintext)
    validation = validate_backup_manifest(manifest)
    return {
        "status": "valid" if validation["passed"] else "invalid",
        "schema_version": manifest.get("schema_version"),
        "backup_variant": manifest.get("backup_variant"),
        "manifest": manifest,
        "validation": validation,
        "file_count": len(manifest.get("files") or []),
    }


def restore_reachops_backup(
    backup_path: str | Path,
    password: str,
    target_runtime_paths: RuntimePaths,
    *,
    preview: bool = True,
) -> dict:
    plaintext = _decrypt_backup(Path(backup_path), password)
    manifest, file_payloads = _read_plaintext_zip(plaintext)
    validation = validate_backup_manifest(manifest)
    if not validation["passed"]:
        return {"status": "blocked", "preview": preview, "validation": validation, "restored_files": []}
    restored = []
    for entry in manifest.get("files") or []:
        archive_path = str(entry.get("path") or "")
        payload = file_payloads.get(archive_path)
        if payload is None:
            return {"status": "blocked", "preview": preview, "validation": {"passed": False, "errors": [f"missing_payload:{archive_path}"]}, "restored_files": []}
        if hashlib.sha256(payload).hexdigest() != str(entry.get("sha256") or ""):
            return {"status": "blocked", "preview": preview, "validation": {"passed": False, "errors": [f"hash_mismatch:{archive_path}"]}, "restored_files": []}
        restored.append({"path": archive_path, "size": len(payload)})
        if not preview:
            target = _restore_target(target_runtime_paths, archive_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(payload)
                os.replace(tmp_name, target)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
    return {
        "status": "preview" if preview else "restored",
        "preview": preview,
        "validation": validation,
        "restored_files": restored,
        "file_count": len(restored),
    }


def validate_backup_manifest(manifest: dict) -> dict:
    errors = []
    forbidden_entries = []
    if not isinstance(manifest, dict):
        return {"passed": False, "errors": ["manifest_not_object"], "forbidden_entries": []}
    if manifest.get("schema_version") != BACKUP_SCHEMA_VERSION:
        errors.append("unsupported_schema_version")
    exclusions = manifest.get("exclusions") if isinstance(manifest.get("exclusions"), dict) else {}
    for key in ["windows_credential_manager_secrets", "activation_status", "tiktok_cookies_sessions", "raw_screenshots_dom", "proxy_credentials"]:
        if exclusions.get(key) is not True:
            errors.append(f"missing_exclusion:{key}")
    for entry in manifest.get("files") or []:
        path = str((entry or {}).get("path") or "")
        if _is_forbidden_archive_path(path):
            forbidden_entries.append(path)
    if forbidden_entries:
        errors.append("forbidden_backup_entries")
    return {"passed": not errors, "errors": errors, "forbidden_entries": forbidden_entries}


def _collect_backup_files(paths: RuntimePaths, *, include_evidence_files: bool) -> list[BackupFile]:
    candidates: list[tuple[Path, str]] = []
    db_path = Path(paths.db_path)
    if db_path.exists() and db_path.is_file():
        candidates.append((db_path, "data/growth_intelligence/growth_intelligence.db"))
    for root_name, root_path in [("config", Path(paths.config_dir)), ("data", Path(paths.data_dir))]:
        if not root_path.exists():
            continue
        for path in sorted(root_path.rglob("*")):
            if not path.is_file():
                continue
            if path == db_path:
                continue
            rel = path.relative_to(root_path).as_posix()
            archive_path = f"{root_name}/{rel}"
            if _is_forbidden_archive_path(archive_path):
                continue
            if not include_evidence_files and _looks_like_evidence_file(archive_path):
                continue
            candidates.append((path, archive_path))
    files = []
    for source, archive_path in candidates:
        payload = source.read_bytes()
        files.append(BackupFile(source, archive_path, hashlib.sha256(payload).hexdigest(), len(payload)))
    return files


def _build_plaintext_zip(files: Iterable[BackupFile], manifest: dict) -> bytes:
    tmp = io.BytesIO()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for item in files:
            archive.write(item.source_path, item.archive_path)
    return tmp.getvalue()


def _read_plaintext_zip(payload: bytes) -> tuple[dict, dict[str, bytes]]:
    tmp = io.BytesIO(payload)
    with zipfile.ZipFile(tmp, "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        files = {name: archive.read(name) for name in archive.namelist() if name != "manifest.json"}
    return manifest, files


def _decrypt_backup(path: Path, password: str) -> bytes:
    _require_password(password)
    data = path.read_bytes()
    min_size = len(BACKUP_MAGIC) + SALT_BYTES + NONCE_BYTES + TAG_BYTES
    if len(data) < min_size or not data.startswith(BACKUP_MAGIC):
        raise ValueError("not a ReachOps backup archive")
    salt_start = len(BACKUP_MAGIC)
    salt = data[salt_start : salt_start + SALT_BYTES]
    nonce = data[salt_start + SALT_BYTES : salt_start + SALT_BYTES + NONCE_BYTES]
    ciphertext = data[salt_start + SALT_BYTES + NONCE_BYTES : -TAG_BYTES]
    expected = hmac.new(_derive_key(password, salt, b"mac"), data[:-TAG_BYTES], hashlib.sha256).digest()
    actual = data[-TAG_BYTES:]
    if not hmac.compare_digest(expected, actual):
        raise ValueError("backup authentication failed")
    return _xor_bytes(ciphertext, _keystream(_derive_key(password, salt, b"enc"), nonce, len(ciphertext)))


def _derive_key(password: str, salt: bytes, purpose: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8") + purpose, salt, KDF_ITERATIONS, dklen=32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    chunks = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _restore_target(paths: RuntimePaths, archive_path: str) -> Path:
    clean = Path(archive_path)
    if clean.is_absolute() or ".." in clean.parts:
        raise ValueError("unsafe restore path")
    root = Path(paths.base_dir)
    return root / clean


def _is_forbidden_archive_path(path: str) -> bool:
    lower = str(path or "").replace("\\", "/").lower()
    name = lower.rsplit("/", 1)[-1]
    return name in FORBIDDEN_BACKUP_NAMES or any(token in lower for token in FORBIDDEN_BACKUP_TOKENS)


def _looks_like_evidence_file(path: str) -> bool:
    lower = str(path or "").lower()
    return any(token in lower for token in ["evidence", "screenshot", "dom", ".png", ".jpg", ".jpeg", ".webp"])


def _require_password(password: str) -> None:
    if len(str(password or "")) < 8:
        raise ValueError("backup password must be at least 8 characters")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ReachOps.runtime_paths import RuntimePaths


BACKUP_SCHEMA_VERSION = "reachops.backup.v1"
BACKUP_FILE_EXTENSION = ".reachops-backup"
BACKUP_MAGIC = b"REACHOPS_BACKUP_V1\n"
PBKDF2_ITERATIONS = 200_000
SECRET_PATH_TOKENS = (
    "activation_status",
    "api_key",
    "cookie",
    "credential",
    "ixbrowser",
    "password",
    "proxy",
    "secret",
    "session",
    "token",
)


class BackupError(RuntimeError):
    pass


class BackupPasswordError(BackupError):
    pass


class BackupIntegrityError(BackupError):
    pass


@dataclass(frozen=True)
class BackupFile:
    source_path: Path
    archive_path: str
    category: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(str(text or "").encode("ascii"), validate=True)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _derive_keys(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> tuple[bytes, bytes]:
    value = str(password or "")
    if len(value) < 8:
        raise BackupPasswordError("backup password must be at least 8 characters")
    key = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, int(iterations), dklen=64)
    return key[:32], key[32:]


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < size:
        chunks.append(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:size]


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(left ^ right for left, right in zip(data, stream))


def _is_secret_relative_path(relative_path: str) -> bool:
    lowered = relative_path.replace("\\", "/").lower()
    return any(token in lowered for token in SECRET_PATH_TOKENS)


def _safe_relative_path(relative_path: str) -> Path:
    text = str(relative_path or "").replace("\\", "/").strip()
    path = Path(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupIntegrityError(f"unsafe restore path: {relative_path}")
    return path


def _file_entry(path: Path, archive_path: str, category: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": archive_path,
        "category": category,
        "size": len(data),
        "sha256": _sha256(data),
    }


def discover_lightweight_backup_files(paths: RuntimePaths) -> tuple[list[BackupFile], list[dict[str, Any]]]:
    files: list[BackupFile] = []
    exclusions: list[dict[str, Any]] = []
    db_path = Path(paths.db_path)
    if db_path.exists() and db_path.is_file():
        files.append(BackupFile(db_path, "data/growth_intelligence/growth_intelligence.db", "sqlite_runtime"))

    config_dir = Path(paths.config_dir)
    if config_dir.exists():
        for path in sorted(config_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(config_dir).as_posix()
            archive_path = f"config/{rel}"
            if _is_secret_relative_path(archive_path):
                exclusions.append({"path": archive_path, "reason": "secret_or_activation_state_excluded"})
                continue
            files.append(BackupFile(path, archive_path, "non_secret_config"))

    return files, exclusions


def build_backup_manifest(paths: RuntimePaths, files: list[BackupFile], exclusions: list[dict[str, Any]], variant: str = "lightweight") -> dict[str, Any]:
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "variant": variant,
        "created_at": _utc_now(),
        "runtime_layout": "reachops.local_runtime.v1",
        "files": [_file_entry(item.source_path, item.archive_path, item.category) for item in files],
        "excluded": list(exclusions)
        + [
            {"path": "config/reachops_activation_status.json", "reason": "license_secret_reissue_required"},
            {"path": "windows_credential_manager", "reason": "credential_manager_secrets_never_exported"},
            {"path": "ixbrowser", "reason": "ixbrowser_cookies_sessions_and_login_state_never_exported"},
            {"path": "reports/evidence_screenshots", "reason": "lightweight_backup_excludes_raw_evidence_files"},
        ],
        "integrity": {
            "file_hash": "sha256",
            "archive_hash": "sha256",
        },
        "restore": {
            "preview_required": True,
            "atomic_restore": True,
            "rollback_on_failure": True,
        },
        "privacy": {
            "customer_data_uploaded": False,
            "secrets_excluded": True,
            "cookies_excluded": True,
            "raw_screenshots_excluded": True,
        },
    }


def _build_plain_archive(paths: RuntimePaths) -> tuple[bytes, dict[str, Any]]:
    files, exclusions = discover_lightweight_backup_files(paths)
    manifest = build_backup_manifest(paths, files, exclusions)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for item in files:
            archive.write(item.source_path, item.archive_path)
    plain = archive_buffer.getvalue()
    manifest["integrity"]["plain_archive_sha256"] = _sha256(plain)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for item in files:
            archive.write(item.source_path, item.archive_path)
    return archive_buffer.getvalue(), manifest


def write_encrypted_backup(base_dir: str | None, output_path: str | Path, password: str) -> dict[str, Any]:
    paths = RuntimePaths.build(base_dir).ensure_dirs()
    plain, manifest = _build_plain_archive(paths)
    salt = os.urandom(16)
    nonce = os.urandom(16)
    enc_key, mac_key = _derive_keys(password, salt)
    header = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "format": "reachops.encrypted_backup.v1",
        "kdf": "pbkdf2_hmac_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": _b64(salt),
        "nonce": _b64(nonce),
        "cipher": "hmac_sha256_stream",
        "mac": "hmac_sha256",
        "manifest_sha256": _sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")),
        "customer_data_uploaded": False,
    }
    header_bytes = _json_bytes(header)
    ciphertext = _xor(plain, _keystream(enc_key, nonce, len(plain)))
    tag = hmac.new(mac_key, header_bytes + ciphertext, hashlib.sha256).digest()
    envelope = BACKUP_MAGIC + len(header_bytes).to_bytes(4, "big") + header_bytes + ciphertext + tag
    target = Path(output_path)
    if target.suffix != BACKUP_FILE_EXTENSION:
        target = target.with_suffix(BACKUP_FILE_EXTENSION)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(envelope)
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "status": "written",
        "path": str(target),
        "size": target.stat().st_size,
        "sha256": _sha256(envelope),
        "manifest": manifest,
        "no_browser_started": True,
        "no_submit": True,
        "customer_data_uploaded": False,
    }


def _decrypt_backup(path: str | Path, password: str) -> tuple[bytes, dict[str, Any]]:
    data = Path(path).read_bytes()
    if not data.startswith(BACKUP_MAGIC):
        raise BackupIntegrityError("invalid backup magic")
    offset = len(BACKUP_MAGIC)
    header_len = int.from_bytes(data[offset : offset + 4], "big")
    offset += 4
    header_bytes = data[offset : offset + header_len]
    offset += header_len
    if len(data) < offset + 32:
        raise BackupIntegrityError("backup is truncated")
    ciphertext = data[offset:-32]
    expected_tag = data[-32:]
    try:
        header = json.loads(header_bytes.decode("utf-8"))
        salt = _unb64(header["salt"])
        nonce = _unb64(header["nonce"])
        iterations = int(header.get("iterations") or PBKDF2_ITERATIONS)
    except Exception as exc:
        raise BackupIntegrityError("backup header is invalid") from exc
    enc_key, mac_key = _derive_keys(password, salt, iterations)
    actual_tag = hmac.new(mac_key, header_bytes + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(actual_tag, expected_tag):
        raise BackupPasswordError("backup password is wrong or archive is corrupted")
    return _xor(ciphertext, _keystream(enc_key, nonce, len(ciphertext))), header


def preview_backup(path: str | Path, password: str) -> dict[str, Any]:
    plain, header = _decrypt_backup(path, password)
    with zipfile.ZipFile(io.BytesIO(plain), "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "status": "preview",
        "path": str(path),
        "header": {key: header.get(key) for key in ["schema_version", "format", "kdf", "iterations", "cipher", "mac"]},
        "manifest": manifest,
        "file_count": len(manifest.get("files") or []),
        "excluded": manifest.get("excluded") or [],
        "restore_preview": True,
        "no_browser_started": True,
        "no_submit": True,
        "customer_data_uploaded": False,
    }


def restore_backup(path: str | Path, password: str, target_base_dir: str | Path, *, preview_only: bool = False, fail_after_files: int = 0) -> dict[str, Any]:
    plain, _header = _decrypt_backup(path, password)
    target_paths = RuntimePaths.build(str(target_base_dir)).ensure_dirs()
    with zipfile.ZipFile(io.BytesIO(plain), "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        if preview_only:
            return {
                "schema_version": BACKUP_SCHEMA_VERSION,
                "status": "preview",
                "target_base_dir": str(target_paths.base_dir),
                "manifest": manifest,
                "file_count": len(files),
                "restore_preview": True,
                "customer_data_uploaded": False,
            }
        staging_dir = Path(tempfile.mkdtemp(prefix="reachops-restore-staging-"))
        rollback_dir = Path(tempfile.mkdtemp(prefix="reachops-restore-rollback-"))
        restored = 0
        created_targets: list[Path] = []
        try:
            for row in files:
                rel = str((row or {}).get("path") or "")
                if not rel or _is_secret_relative_path(rel):
                    raise BackupIntegrityError(f"refusing unsafe restore path: {rel}")
                safe_rel = _safe_relative_path(rel)
                data = archive.read(rel)
                if _sha256(data) != str((row or {}).get("sha256") or ""):
                    raise BackupIntegrityError(f"file hash mismatch: {rel}")
                staged = staging_dir / safe_rel
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(data)
            for row in files:
                rel = str((row or {}).get("path") or "")
                safe_rel = _safe_relative_path(rel)
                staged = staging_dir / safe_rel
                target = Path(target_paths.base_dir) / safe_rel
                if target.exists():
                    rollback_target = rollback_dir / rel
                    rollback_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, rollback_target)
                else:
                    created_targets.append(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, target)
                restored += 1
                if fail_after_files and restored >= int(fail_after_files):
                    raise BackupError("simulated interrupted restore")
            return {
                "schema_version": BACKUP_SCHEMA_VERSION,
                "status": "restored",
                "target_base_dir": str(target_paths.base_dir),
                "restored_files": restored,
                "rollback_on_failure": True,
                "customer_data_uploaded": False,
            }
        except Exception:
            for target in reversed(created_targets):
                try:
                    if target.exists():
                        target.unlink()
                except Exception:
                    pass
            for rollback_file in sorted(rollback_dir.rglob("*")):
                if rollback_file.is_file():
                    rel = rollback_file.relative_to(rollback_dir)
                    target = Path(target_paths.base_dir) / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(rollback_file, target)
            raise
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
            shutil.rmtree(rollback_dir, ignore_errors=True)

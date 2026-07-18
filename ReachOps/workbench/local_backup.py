# -*- coding: utf-8 -*-
"""Local encrypted ReachOps backup and restore primitives."""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


BACKUP_SCHEMA_VERSION = "reachops.backup.v1"
SUPPORTED_BACKUP_SCHEMA_VERSIONS = {BACKUP_SCHEMA_VERSION, "reachops.backup.v0"}
BACKUP_FILE_EXTENSION = ".reachops-backup"
DEFAULT_KDF_ITERATIONS = 210_000
KEY_LENGTH_BYTES = 32
SALT_LENGTH_BYTES = 16
NONCE_LENGTH_BYTES = 16
CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    """Base class for ReachOps backup failures."""


class BackupIntegrityError(BackupError):
    """Raised when the backup cannot be authenticated."""


class BackupCompatibilityError(BackupError):
    """Raised when a backup schema is unsupported."""


class BackupPathError(BackupError):
    """Raised when a backup contains an unsafe path."""


@dataclass(frozen=True)
class BackupSelection:
    path: str
    size_bytes: int
    sha256: str
    kind: str


@dataclass(frozen=True)
class BackupExclusion:
    path: str
    reason: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relpath(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    pure = PurePosixPath(rel)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise BackupPathError(f"unsafe backup path: {rel}")
    return rel


def _normalize_archive_path(value: str) -> str:
    pure = PurePosixPath(str(value or "").replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise BackupPathError(f"unsafe backup path: {value}")
    return pure.as_posix()


def _classify_path(relpath: str, full: bool) -> tuple[bool, str, str]:
    parts = tuple(part.lower() for part in PurePosixPath(relpath).parts)
    name = parts[-1] if parts else ""
    text = "/".join(parts)

    forbidden_tokens = {
        "cookie",
        "cookies",
        "session",
        "sessions",
        "credential",
        "credentials",
        "password",
        "passwd",
        "secret",
        "secrets",
        "proxy",
        "proxies",
        "ixbrowser",
    }
    if any(token in part for part in parts for token in forbidden_tokens):
        return False, "sensitive_path", "sensitive"
    if name in {
        "reachops_acceptance_inputs.local.ps1",
        "reachops_activation_status.json",
        "activation_status_payload.json",
    }:
        return False, "local_authorization_or_license_state", "sensitive"
    if name.endswith((".key", ".pem", ".p12", ".pfx", ".env")):
        return False, "secret_material", "sensitive"
    if name.endswith((".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm")):
        return False, "sqlite_sidecar_not_atomic_snapshot", "runtime"
    if not full and (
        "/evidence/" in f"/{text}/"
        or "/screenshots/" in f"/{text}/"
        or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".html", ".dom"))
    ):
        return False, "evidence_file_excluded_from_lightweight_backup", "evidence"

    if name.endswith((".db", ".sqlite", ".sqlite3")):
        return True, "", "sqlite"
    if "/config/" in f"/{text}/" or name.endswith((".json", ".md", ".txt", ".csv", ".template")):
        return True, "", "config"
    if full and (
        "/evidence/" in f"/{text}/"
        or "/screenshots/" in f"/{text}/"
        or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".jsonl"))
    ):
        return True, "", "evidence"
    return False, "unsupported_backup_file_type", "unknown"


def build_backup_preview(source_dir: str | Path, *, full: bool = False) -> dict[str, Any]:
    root = Path(source_dir).expanduser().resolve()
    selected: list[BackupSelection] = []
    excluded: list[BackupExclusion] = []
    if not root.exists():
        raise FileNotFoundError(str(root))
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = _safe_relpath(path.resolve(), root)
        include, reason, kind = _classify_path(rel, full=full)
        if include:
            selected.append(
                BackupSelection(
                    path=rel,
                    size_bytes=path.stat().st_size,
                    sha256=_sha256_file(path),
                    kind=kind,
                )
            )
        else:
            excluded.append(BackupExclusion(path=rel, reason=reason or "excluded"))
    total_size = sum(item.size_bytes for item in selected)
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "backup_variant": "full" if full else "lightweight",
        "source_root": str(root),
        "selected_count": len(selected),
        "selected_size_bytes": total_size,
        "selected_files": [item.__dict__ for item in selected],
        "excluded_count": len(excluded),
        "excluded_files": [item.__dict__ for item in excluded],
        "exclusion_policy": {
            "cookies_sessions_excluded": True,
            "credential_material_excluded": True,
            "acceptance_inputs_excluded": True,
            "activation_status_excluded": True,
            "sqlite_wal_sidecars_excluded": True,
        },
        "no_browser_started": True,
        "no_submit": True,
    }


def _derive_keys(passphrase: str, salt: bytes, iterations: int) -> tuple[bytes, bytes]:
    if not str(passphrase or ""):
        raise ValueError("backup passphrase is required")
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, int(iterations), dklen=KEY_LENGTH_BYTES * 2)
    return key[:KEY_LENGTH_BYTES], key[KEY_LENGTH_BYTES:]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(left ^ right for left, right in zip(data, stream))


def _encrypt_payload(payload: dict[str, Any], passphrase: str) -> bytes:
    plaintext = gzip.compress(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    salt = secrets.token_bytes(SALT_LENGTH_BYTES)
    nonce = secrets.token_bytes(NONCE_LENGTH_BYTES)
    encryption_key, mac_key = _derive_keys(passphrase, salt, DEFAULT_KDF_ITERATIONS)
    ciphertext = _xor(plaintext, _keystream(encryption_key, nonce, len(plaintext)))
    header = {
        "magic": "REACHOPS-BACKUP",
        "schema_version": BACKUP_SCHEMA_VERSION,
        "kdf": "pbkdf2_hmac_sha256",
        "kdf_iterations": DEFAULT_KDF_ITERATIONS,
        "cipher": "hmac_sha256_stream_xor",
        "compression": "gzip",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    aad = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(mac_key, aad + ciphertext, hashlib.sha256).digest()
    envelope = {
        **header,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decrypt_payload(archive_bytes: bytes, passphrase: str) -> dict[str, Any]:
    try:
        envelope = json.loads(archive_bytes.decode("utf-8"))
    except Exception as exc:
        raise BackupIntegrityError("backup archive is not valid JSON") from exc
    if not isinstance(envelope, dict) or envelope.get("magic") != "REACHOPS-BACKUP":
        raise BackupIntegrityError("backup archive magic is invalid")
    schema_version = str(envelope.get("schema_version") or "")
    if schema_version not in SUPPORTED_BACKUP_SCHEMA_VERSIONS:
        raise BackupCompatibilityError(f"unsupported backup schema: {schema_version}")
    try:
        salt = base64.b64decode(str(envelope.get("salt") or ""), validate=True)
        nonce = base64.b64decode(str(envelope.get("nonce") or ""), validate=True)
        ciphertext = base64.b64decode(str(envelope.get("ciphertext") or ""), validate=True)
        tag = base64.b64decode(str(envelope.get("tag") or ""), validate=True)
    except Exception as exc:
        raise BackupIntegrityError("backup archive encoding is invalid") from exc
    iterations = int(envelope.get("kdf_iterations") or DEFAULT_KDF_ITERATIONS)
    encryption_key, mac_key = _derive_keys(passphrase, salt, iterations)
    header = {key: envelope[key] for key in envelope if key not in {"ciphertext", "tag"}}
    aad = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected = hmac.new(mac_key, aad + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise BackupIntegrityError("backup archive authentication failed")
    try:
        plaintext = _xor(ciphertext, _keystream(encryption_key, nonce, len(ciphertext)))
        payload = json.loads(gzip.decompress(plaintext).decode("utf-8"))
    except Exception as exc:
        raise BackupIntegrityError("backup archive payload is invalid") from exc
    if not isinstance(payload, dict):
        raise BackupIntegrityError("backup archive payload is not an object")
    payload_schema = str(payload.get("schema_version") or schema_version)
    if payload_schema not in SUPPORTED_BACKUP_SCHEMA_VERSIONS:
        raise BackupCompatibilityError(f"unsupported backup payload schema: {payload_schema}")
    return payload


def create_encrypted_backup(
    source_dir: str | Path,
    output_path: str | Path,
    passphrase: str,
    *,
    full: bool = False,
) -> dict[str, Any]:
    root = Path(source_dir).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    preview = build_backup_preview(root, full=full)
    files: list[dict[str, Any]] = []
    for row in preview["selected_files"]:
        rel = _normalize_archive_path(str(row["path"]))
        data = (root / rel).read_bytes()
        sha256 = _sha256_bytes(data)
        if sha256 != row["sha256"]:
            raise BackupIntegrityError(f"backup input changed during snapshot: {rel}")
        files.append(
            {
                "path": rel,
                "size_bytes": len(data),
                "sha256": sha256,
                "kind": row.get("kind") or "file",
                "data_b64": base64.b64encode(data).decode("ascii"),
            }
        )
    payload = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "backup_variant": preview["backup_variant"],
        "manifest": preview,
        "files": files,
        "archive_policy": {
            "format_extension": BACKUP_FILE_EXTENSION,
            "authenticated_encryption": True,
            "customer_password_required": True,
            "lost_password_recoverable": False,
            "no_browser_started": True,
            "no_submit": True,
        },
    }
    archive_bytes = _encrypt_payload(payload, passphrase)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    tmp.write_bytes(archive_bytes)
    tmp.replace(output)
    return {
        "status": "created",
        "path": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": _sha256_file(output),
        "manifest": preview,
        "no_browser_started": True,
        "no_submit": True,
    }


def inspect_encrypted_backup(backup_path: str | Path, passphrase: str) -> dict[str, Any]:
    payload = _decrypt_payload(Path(backup_path).expanduser().read_bytes(), passphrase)
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    return {
        "schema_version": payload.get("schema_version") or BACKUP_SCHEMA_VERSION,
        "created_at": payload.get("created_at") or "",
        "backup_variant": payload.get("backup_variant") or "",
        "manifest": payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {},
        "file_count": len(files),
        "files": [
            {
                "path": str(row.get("path") or ""),
                "size_bytes": int(row.get("size_bytes") or 0),
                "sha256": str(row.get("sha256") or ""),
                "kind": str(row.get("kind") or "file"),
            }
            for row in files
            if isinstance(row, dict)
        ],
        "no_browser_started": True,
        "no_submit": True,
    }


def restore_encrypted_backup(
    backup_path: str | Path,
    destination_dir: str | Path,
    passphrase: str,
    *,
    preview_only: bool = False,
) -> dict[str, Any]:
    payload = _decrypt_payload(Path(backup_path).expanduser().read_bytes(), passphrase)
    destination = Path(destination_dir).expanduser().resolve()
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    planned: list[dict[str, Any]] = []
    for row in files:
        if not isinstance(row, dict):
            raise BackupIntegrityError("backup file entry is invalid")
        rel = _normalize_archive_path(str(row.get("path") or ""))
        data = base64.b64decode(str(row.get("data_b64") or ""), validate=True)
        sha256 = _sha256_bytes(data)
        expected = str(row.get("sha256") or "")
        if sha256 != expected:
            raise BackupIntegrityError(f"backup file hash mismatch: {rel}")
        planned.append(
            {
                "path": rel,
                "size_bytes": len(data),
                "sha256": sha256,
                "kind": str(row.get("kind") or "file"),
            }
        )
    if preview_only:
        return {
            "status": "preview",
            "destination_dir": str(destination),
            "schema_version": payload.get("schema_version") or BACKUP_SCHEMA_VERSION,
            "backup_variant": payload.get("backup_variant") or "",
            "file_count": len(planned),
            "files": planned,
            "no_browser_started": True,
            "no_submit": True,
        }

    staging = destination.with_name(f".{destination.name}.restore-{os.getpid()}-{secrets.token_hex(4)}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=False)
    try:
        for row in files:
            rel = _normalize_archive_path(str(row.get("path") or ""))
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(str(row.get("data_b64") or ""), validate=True))
        if destination.exists():
            backup_existing = destination.with_name(f".{destination.name}.pre-restore-{secrets.token_hex(4)}")
            destination.replace(backup_existing)
            try:
                staging.replace(destination)
            except Exception:
                backup_existing.replace(destination)
                raise
            shutil.rmtree(backup_existing, ignore_errors=True)
        else:
            staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "restored",
        "destination_dir": str(destination),
        "schema_version": payload.get("schema_version") or BACKUP_SCHEMA_VERSION,
        "backup_variant": payload.get("backup_variant") or "",
        "file_count": len(planned),
        "files": planned,
        "atomic_restore": True,
        "no_browser_started": True,
        "no_submit": True,
    }

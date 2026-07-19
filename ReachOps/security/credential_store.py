# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from typing import Any


CREDENTIAL_STORAGE_SCHEMA_VERSION = "reachops.credential_storage.v1"
SERVICE_PREFIX = "ReachOps"
BACKEND_WINDOWS_CREDENTIAL_MANAGER = "windows_credential_manager"
BACKEND_NON_WINDOWS_UNAVAILABLE = "non_windows_unavailable"
BACKEND_WIN32CRED_UNAVAILABLE = "win32cred_unavailable"


class CredentialStoreUnavailable(RuntimeError):
    """Raised when a secret operation cannot use the required secure backend."""


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _import_win32cred():
    try:
        import win32cred  # type: ignore

        return win32cred
    except Exception as exc:
        raise CredentialStoreUnavailable("Windows Credential Manager backend requires pywin32 win32cred") from exc


def _target_name(namespace: str, name: str) -> str:
    clean_namespace = str(namespace or SERVICE_PREFIX).strip() or SERVICE_PREFIX
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("credential name is required")
    return f"{clean_namespace}:{clean_name}"


def redact_secret(value: Any, visible_tail: int = 4) -> str:
    text = str(value or "")
    if not text:
        return ""
    tail_len = max(0, min(int(visible_tail or 0), len(text)))
    if len(text) <= tail_len:
        return "*" * len(text)
    return f"{'*' * max(8, len(text) - tail_len)}{text[-tail_len:]}"


def credential_storage_status() -> dict[str, Any]:
    if not _is_windows():
        return {
            "schema_version": CREDENTIAL_STORAGE_SCHEMA_VERSION,
            "platform": sys.platform,
            "backend": BACKEND_NON_WINDOWS_UNAVAILABLE,
            "available": False,
            "secret_persistence_allowed": False,
            "windows_credential_manager_required": True,
            "status_includes_secret_values": False,
        }
    try:
        _import_win32cred()
    except CredentialStoreUnavailable:
        return {
            "schema_version": CREDENTIAL_STORAGE_SCHEMA_VERSION,
            "platform": sys.platform,
            "backend": BACKEND_WIN32CRED_UNAVAILABLE,
            "available": False,
            "secret_persistence_allowed": False,
            "windows_credential_manager_required": True,
            "status_includes_secret_values": False,
        }
    return {
        "schema_version": CREDENTIAL_STORAGE_SCHEMA_VERSION,
        "platform": sys.platform,
        "backend": BACKEND_WINDOWS_CREDENTIAL_MANAGER,
        "available": True,
        "secret_persistence_allowed": True,
        "windows_credential_manager_required": True,
        "status_includes_secret_values": False,
    }


class ReachOpsCredentialStore:
    """Windows Credential Manager wrapper for application secrets.

    ReachOps intentionally refuses secret persistence on non-Windows platforms.
    Customer secrets must not be written to SQLite, JSON config, logs, reports,
    support bundles, backups, or Git artifacts.
    """

    def __init__(self, namespace: str = SERVICE_PREFIX):
        self.namespace = str(namespace or SERVICE_PREFIX).strip() or SERVICE_PREFIX

    def _backend(self):
        if not _is_windows():
            raise CredentialStoreUnavailable("ReachOps persists secrets only in Windows Credential Manager")
        return _import_win32cred()

    def set_secret(self, name: str, value: str) -> dict[str, Any]:
        secret = str(value or "")
        if not secret:
            raise ValueError("secret value is required")
        win32cred = self._backend()
        target = _target_name(self.namespace, name)
        credential = {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "UserName": self.namespace,
            "CredentialBlob": secret,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }
        win32cred.CredWrite(credential, 0)
        return {
            "schema_version": CREDENTIAL_STORAGE_SCHEMA_VERSION,
            "stored": True,
            "backend": BACKEND_WINDOWS_CREDENTIAL_MANAGER,
            "target_name": target,
            "secret_value": None,
            "secret_redacted": redact_secret(secret),
        }

    def get_secret(self, name: str) -> str:
        win32cred = self._backend()
        target = _target_name(self.namespace, name)
        try:
            credential = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            raise CredentialStoreUnavailable(f"credential not found: {target}") from exc
        blob = credential.get("CredentialBlob", "")
        if isinstance(blob, bytes):
            return blob.decode("utf-16-le", errors="ignore") or blob.decode("utf-8", errors="ignore")
        return str(blob or "")

    def delete_secret(self, name: str) -> dict[str, Any]:
        win32cred = self._backend()
        target = _target_name(self.namespace, name)
        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
            deleted = True
        except Exception:
            deleted = False
        return {
            "schema_version": CREDENTIAL_STORAGE_SCHEMA_VERSION,
            "deleted": deleted,
            "backend": BACKEND_WINDOWS_CREDENTIAL_MANAGER,
            "target_name": target,
            "secret_value": None,
        }


def get_secret_if_available(name: str, namespace: str = SERVICE_PREFIX) -> str:
    try:
        return ReachOpsCredentialStore(namespace=namespace).get_secret(name)
    except CredentialStoreUnavailable:
        return ""

# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import os
import platform
from dataclasses import dataclass
from typing import Mapping


AI_API_KEY_SECRET = "ai_api_key"
AI_API_KEY_ENV = "REACHOPS_AI_API_KEY"


@dataclass(frozen=True)
class SecretLookup:
    value: str
    source: str
    configured: bool
    persistent: bool
    error: str = ""


@dataclass(frozen=True)
class SecretWriteResult:
    stored: bool
    deleted: bool
    status: str
    source: str
    persistent: bool
    error: str = ""


class ReachOpsCredentialStore:
    """ReachOps secret boundary.

    Windows clients persist application secrets in Windows Credential Manager.
    Non-Windows development runtimes deliberately do not persist secrets here;
    they may still use environment variables as a session-only compatibility
    path for tests and local development.
    """

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    MAX_CREDENTIAL_BLOB_BYTES = 2560

    def __init__(self, service_prefix: str = "ReachOps"):
        self.service_prefix = "".join(ch for ch in str(service_prefix or "ReachOps").strip() if ch.isalnum() or ch in {"_", "-", ":"}) or "ReachOps"

    def target_name(self, secret_name: str) -> str:
        clean = "".join(ch.lower() for ch in str(secret_name or "").strip() if ch.isalnum() or ch in {"_", "-", "."})
        if not clean:
            raise ValueError("secret_name is required")
        return f"{self.service_prefix}:{clean}"

    def supported(self) -> bool:
        return platform.system().lower() == "windows"

    def read_secret(self, secret_name: str) -> SecretLookup:
        if not self.supported():
            return SecretLookup("", "unsupported_platform", False, False)
        try:
            value = self._read_windows_secret(self.target_name(secret_name))
        except Exception as exc:
            return SecretLookup("", "windows_credential_manager", False, True, error=exc.__class__.__name__)
        return SecretLookup(value, "windows_credential_manager", bool(value), True)

    def write_secret(self, secret_name: str, secret_value: str) -> SecretWriteResult:
        value = str(secret_value or "")
        if not self.supported():
            return SecretWriteResult(
                stored=False,
                deleted=False,
                status="unsupported_platform",
                source="unsupported_platform",
                persistent=False,
            )
        target = self.target_name(secret_name)
        if not value:
            try:
                deleted = self._delete_windows_secret(target)
            except Exception as exc:
                return SecretWriteResult(
                    stored=False,
                    deleted=False,
                    status="delete_failed",
                    source="windows_credential_manager",
                    persistent=True,
                    error=exc.__class__.__name__,
                )
            return SecretWriteResult(
                stored=False,
                deleted=deleted,
                status="deleted" if deleted else "not_found_or_delete_failed",
                source="windows_credential_manager",
                persistent=True,
            )
        if len(value.encode("utf-16-le")) > self.MAX_CREDENTIAL_BLOB_BYTES:
            return SecretWriteResult(
                stored=False,
                deleted=False,
                status="secret_too_large",
                source="windows_credential_manager",
                persistent=True,
                error="credential_blob_limit_exceeded",
            )
        try:
            self._write_windows_secret(target, value)
        except Exception as exc:
            return SecretWriteResult(
                stored=False,
                deleted=False,
                status="store_failed",
                source="windows_credential_manager",
                persistent=True,
                error=exc.__class__.__name__,
            )
        return SecretWriteResult(
            stored=True,
            deleted=False,
            status="stored",
            source="windows_credential_manager",
            persistent=True,
        )

    def _advapi32(self):
        return ctypes.windll.advapi32

    def _kernel32(self):
        return ctypes.windll.kernel32

    def _read_windows_secret(self, target_name: str) -> str:
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", ctypes.c_uint32),
                ("Type", ctypes.c_uint32),
                ("TargetName", ctypes.c_wchar_p),
                ("Comment", ctypes.c_wchar_p),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", ctypes.c_uint32),
                ("CredentialBlob", ctypes.c_void_p),
                ("Persist", ctypes.c_uint32),
                ("AttributeCount", ctypes.c_uint32),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", ctypes.c_wchar_p),
                ("UserName", ctypes.c_wchar_p),
            ]

        credential_ptr = ctypes.POINTER(CREDENTIALW)()
        advapi32 = self._advapi32()
        advapi32.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        advapi32.CredReadW.restype = ctypes.c_bool
        advapi32.CredFree.argtypes = [ctypes.c_void_p]
        advapi32.CredFree.restype = None
        if not advapi32.CredReadW(target_name, self.CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr)):
            return ""
        try:
            credential = credential_ptr.contents
            if not credential.CredentialBlob or credential.CredentialBlobSize <= 0:
                return ""
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le", errors="strict")
        finally:
            advapi32.CredFree(credential_ptr)

    def _write_windows_secret(self, target_name: str, secret_value: str) -> None:
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", ctypes.c_uint32),
                ("Type", ctypes.c_uint32),
                ("TargetName", ctypes.c_wchar_p),
                ("Comment", ctypes.c_wchar_p),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", ctypes.c_uint32),
                ("CredentialBlob", ctypes.c_void_p),
                ("Persist", ctypes.c_uint32),
                ("AttributeCount", ctypes.c_uint32),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", ctypes.c_wchar_p),
                ("UserName", ctypes.c_wchar_p),
            ]

        blob = secret_value.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(blob)
        credential = CREDENTIALW(
            0,
            self.CRED_TYPE_GENERIC,
            target_name,
            "ReachOps local client secret",
            FILETIME(0, 0),
            len(blob),
            ctypes.cast(buffer, ctypes.c_void_p),
            self.CRED_PERSIST_LOCAL_MACHINE,
            0,
            None,
            None,
            "ReachOps",
        )
        advapi32 = self._advapi32()
        advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), ctypes.c_uint32]
        advapi32.CredWriteW.restype = ctypes.c_bool
        if not advapi32.CredWriteW(ctypes.byref(credential), 0):
            error_code = int(self._kernel32().GetLastError())
            raise OSError(error_code, f"CredWriteW failed for {target_name}")

    def _delete_windows_secret(self, target_name: str) -> bool:
        advapi32 = self._advapi32()
        advapi32.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        advapi32.CredDeleteW.restype = ctypes.c_bool
        return bool(advapi32.CredDeleteW(target_name, self.CRED_TYPE_GENERIC, 0))


def resolve_ai_api_key(
    env: Mapping[str, str] | None = None,
    credential_store: ReachOpsCredentialStore | None = None,
) -> SecretLookup:
    env = env or os.environ
    store = credential_store or ReachOpsCredentialStore()
    stored = None
    if store.supported():
        stored = store.read_secret(AI_API_KEY_SECRET)
        if stored.configured:
            return stored
    env_value = str(env.get(AI_API_KEY_ENV) or "").strip()
    if env_value:
        return SecretLookup(env_value, "environment_session", True, False)
    if store.supported():
        return SecretLookup("", "windows_credential_manager", False, True, error=stored.error if stored else "")
    return SecretLookup("", "unsupported_platform", False, False)


def ai_api_key_status(
    env: Mapping[str, str] | None = None,
    credential_store: ReachOpsCredentialStore | None = None,
) -> dict[str, object]:
    lookup = resolve_ai_api_key(env=env, credential_store=credential_store)
    return {
        "configured": lookup.configured,
        "source": lookup.source,
        "persistent": lookup.persistent,
        "error": lookup.error,
        "windows_credential_manager_required": True,
        "secret_value_redacted": True,
    }

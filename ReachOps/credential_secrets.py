# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass


REACHOPS_CREDENTIAL_PREFIX = "ReachOps"
AI_API_KEY_CREDENTIAL = "ReachOps/AI/APIKey"


@dataclass(frozen=True)
class SecretStoreResult:
    ok: bool
    available: bool
    backend: str
    error_code: str = ""
    error_message: str = ""


class SecretStoreUnavailable(RuntimeError):
    pass


class WindowsCredentialSecretStore:
    """Windows Credential Manager adapter for customer-local ReachOps secrets."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self, service_prefix: str = REACHOPS_CREDENTIAL_PREFIX, platform: str | None = None):
        self.service_prefix = str(service_prefix or REACHOPS_CREDENTIAL_PREFIX).strip()
        self.platform = platform or sys.platform

    @property
    def backend(self) -> str:
        return "windows_credential_manager"

    def is_available(self) -> bool:
        return self.platform.startswith("win")

    def target_name(self, name: str) -> str:
        value = str(name or "").strip().replace("\\", "/")
        if not value:
            raise ValueError("secret name is required")
        if value.startswith(f"{self.service_prefix}/"):
            return value
        return f"{self.service_prefix}/{value}"

    def get_secret(self, name: str) -> str:
        if not self.is_available():
            raise SecretStoreUnavailable("Windows Credential Manager is only available on Windows")
        return _WindowsCredentialApi().read(self.target_name(name))

    def set_secret(self, name: str, value: str, username: str = "ReachOps") -> SecretStoreResult:
        if not self.is_available():
            return SecretStoreResult(False, False, self.backend, "SECRET_STORE_UNAVAILABLE", "Windows Credential Manager is only available on Windows")
        try:
            _WindowsCredentialApi().write(self.target_name(name), str(value or ""), username=username)
            return SecretStoreResult(True, True, self.backend)
        except Exception as exc:
            return SecretStoreResult(False, True, self.backend, exc.__class__.__name__, str(exc))

    def delete_secret(self, name: str) -> SecretStoreResult:
        if not self.is_available():
            return SecretStoreResult(False, False, self.backend, "SECRET_STORE_UNAVAILABLE", "Windows Credential Manager is only available on Windows")
        try:
            _WindowsCredentialApi().delete(self.target_name(name))
            return SecretStoreResult(True, True, self.backend)
        except Exception as exc:
            return SecretStoreResult(False, True, self.backend, exc.__class__.__name__, str(exc))


class _WindowsCredentialApi:
    def __init__(self):
        self.advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)

    def read(self, target_name: str) -> str:
        credential_ptr = ctypes.c_void_p()
        ok = self.advapi32.CredReadW(wintypes.LPCWSTR(target_name), WindowsCredentialSecretStore.CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr))
        if not ok:
            raise SecretStoreUnavailable(f"credential not found: {target_name}")
        try:
            credential = ctypes.cast(credential_ptr, ctypes.POINTER(CREDENTIALW)).contents
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return blob.decode("utf-16-le")
        finally:
            self.advapi32.CredFree(credential_ptr)

    def write(self, target_name: str, value: str, username: str = "ReachOps") -> None:
        encoded = str(value or "").encode("utf-16-le")
        blob = ctypes.create_string_buffer(encoded)
        credential = CREDENTIALW()
        credential.Type = WindowsCredentialSecretStore.CRED_TYPE_GENERIC
        credential.TargetName = target_name
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.c_void_p)
        credential.Persist = WindowsCredentialSecretStore.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = username
        ok = self.advapi32.CredWriteW(ctypes.byref(credential), 0)
        if not ok:
            raise OSError(ctypes.get_last_error(), "CredWriteW failed")

    def delete(self, target_name: str) -> None:
        ok = self.advapi32.CredDeleteW(wintypes.LPCWSTR(target_name), WindowsCredentialSecretStore.CRED_TYPE_GENERIC, 0)
        if not ok:
            raise OSError(ctypes.get_last_error(), "CredDeleteW failed")


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def build_default_secret_store() -> WindowsCredentialSecretStore:
    return WindowsCredentialSecretStore()

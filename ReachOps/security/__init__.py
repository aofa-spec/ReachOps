# -*- coding: utf-8 -*-
"""ReachOps local security contracts."""

from .credential_store import (
    CredentialStoreUnavailable,
    ReachOpsCredentialStore,
    credential_storage_status,
    get_secret_if_available,
    redact_secret,
)
from .backup import (
    BACKUP_SCHEMA_VERSION,
    BackupError,
    BackupIntegrityError,
    BackupPasswordError,
    preview_backup,
    restore_backup,
    write_encrypted_backup,
)

__all__ = [
    "BACKUP_SCHEMA_VERSION",
    "BackupError",
    "BackupIntegrityError",
    "BackupPasswordError",
    "CredentialStoreUnavailable",
    "ReachOpsCredentialStore",
    "credential_storage_status",
    "get_secret_if_available",
    "preview_backup",
    "redact_secret",
    "restore_backup",
    "write_encrypted_backup",
]

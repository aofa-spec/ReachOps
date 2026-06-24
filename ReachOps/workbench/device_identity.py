# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import os
import platform
import uuid


class DeviceIdentity:
    """Stable local device identity for activation binding.

    The raw machine attributes are never persisted by this helper. External
    activation services can request the hashed device id and bind entitlements
    to that value.
    """

    ENV_DEVICE_ID = "REACHOPS_DEVICE_ID"

    @classmethod
    def current_device_id(cls) -> str:
        override = str(os.environ.get(cls.ENV_DEVICE_ID) or "").strip()
        if override:
            return cls._normalize(override)
        parts = [
            "reachops-device-v1",
            platform.node(),
            platform.system(),
            platform.machine(),
            str(uuid.getnode()),
        ]
        raw = "|".join(str(part or "").strip().lower() for part in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @classmethod
    def _normalize(cls, value: str) -> str:
        clean = "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum() or ch in {"_", "-"})
        return clean[:96]

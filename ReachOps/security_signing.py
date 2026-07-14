# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
from typing import Any

SIGNATURE_ALGORITHM = "hmac-sha256"


def canonical_payload(payload: dict[str, Any], signature_field: str = "signature") -> bytes:
    unsigned = copy.deepcopy(payload)
    unsigned.pop(signature_field, None)
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_key_ring(env_name: str = "REACHOPS_TRUSTED_SIGNING_KEYS") -> dict[str, str]:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items() if str(key).strip() and str(value).strip()}


def sign_payload(payload: dict[str, Any], key_id: str, secret: str, signature_field: str = "signature") -> dict[str, Any]:
    signed = copy.deepcopy(payload)
    signed.pop(signature_field, None)
    digest = hmac.new(str(secret).encode("utf-8"), canonical_payload(signed, signature_field), hashlib.sha256).hexdigest()
    signed[signature_field] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "key_id": str(key_id),
        "digest": digest,
    }
    return signed


def verify_signed_payload(
    payload: dict[str, Any],
    key_ring: dict[str, str] | None = None,
    signature_field: str = "signature",
) -> tuple[bool, str]:
    signature = payload.get(signature_field) if isinstance(payload.get(signature_field), dict) else {}
    if not signature:
        return False, "signature_missing"
    if str(signature.get("algorithm") or "") != SIGNATURE_ALGORITHM:
        return False, "signature_algorithm_unsupported"
    key_id = str(signature.get("key_id") or "")
    digest = str(signature.get("digest") or "").lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return False, "signature_digest_invalid"
    keys = key_ring if key_ring is not None else load_key_ring()
    secret = str((keys or {}).get(key_id) or "")
    if not secret:
        return False, "signature_key_unknown"
    expected = hmac.new(str(secret).encode("utf-8"), canonical_payload(payload, signature_field), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        return False, "signature_mismatch"
    return True, "signature_valid"

# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from ReachOps.collectors.normalizer import normalize_language_text


SELLER_PROMO_PATTERNS = [
    r"\blink\s+in\s+(my|our)\s+bio\b",
    r"\blink\s+on\s+(my|our)\s+bio\b",
    r"\buse\s+(my\s+|our\s+)?(code|coupon)\b",
    r"\b(code|coupon)\s*[:：]\s*[a-z0-9_-]{2,}\b",
    r"\b\d{1,2}%\s+off\s+(code|coupon)\b",
    r"\bshop\s+now\b",
]


def looks_like_seller_promo(text: str) -> bool:
    normalized = normalize_language_text(str(text or "").lower())
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in SELLER_PROMO_PATTERNS)

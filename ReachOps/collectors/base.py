# -*- coding: utf-8 -*-
"""Collector adapter interface for browser-driven social data collection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


CollectorLevel = Literal["selenium_dom", "injected_script", "cdp_network"]


@dataclass
class CollectorEvidence:
    level: CollectorLevel
    final_url: str = ""
    item_count: int = 0
    raw_sample: str = ""
    error_code: str = ""
    screenshot_path: str = ""
    fallback_used: bool = False
    adapter_name: str = ""
    diagnostics: dict | None = None


class CollectorAdapter:
    level: CollectorLevel = "selenium_dom"

    def collect(self, driver: Any, task: dict, context: dict):
        raise NotImplementedError

    def evidence(self, driver: Any, item_count: int = 0, raw_sample: str = "", error_code: str = "") -> CollectorEvidence:
        return CollectorEvidence(
            level=self.level,
            final_url=str(getattr(driver, "current_url", "") or ""),
            item_count=int(item_count or 0),
            raw_sample=raw_sample[:500],
            error_code=error_code,
            adapter_name=self.__class__.__name__,
            diagnostics=getattr(self, "last_diagnostics", None),
        )

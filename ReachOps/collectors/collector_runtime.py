# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Iterable

from .base import CollectorAdapter, CollectorEvidence


class CollectorRuntime:
    """Runs collector adapters with evidence and fallback support."""

    def __init__(self, evidence_dir: str = ""):
        self.evidence_dir = evidence_dir
        if evidence_dir:
            os.makedirs(evidence_dir, exist_ok=True)

    def collect_with_fallback(
        self,
        driver: Any,
        adapters: Iterable[CollectorAdapter],
        task: dict,
        context: dict,
        evidence_name: str = "collector",
        fallback_on_empty: bool = False,
    ) -> tuple[list, CollectorEvidence]:
        errors = []
        adapters = list(adapters)
        first_empty_diagnostics = None
        for index, adapter in enumerate(adapters):
            try:
                rows = adapter.collect(driver, task, context) or []
                raw_sample = json.dumps(rows[:2], ensure_ascii=False, default=str)
                if hasattr(adapter, "evidence"):
                    evidence = adapter.evidence(driver, item_count=len(rows), raw_sample=raw_sample)
                else:
                    evidence = CollectorEvidence(
                        level=getattr(adapter, "level", "selenium_dom"),
                        final_url=str(getattr(driver, "current_url", "") or ""),
                        item_count=len(rows),
                        raw_sample=raw_sample[:500],
                        adapter_name=adapter.__class__.__name__,
                    )
                evidence.fallback_used = index > 0
                diagnostics = getattr(adapter, "last_diagnostics", None)
                if isinstance(diagnostics, dict):
                    evidence.diagnostics = diagnostics
                elif isinstance(first_empty_diagnostics, dict):
                    evidence.diagnostics = first_empty_diagnostics
                evidence.screenshot_path = self._capture_screenshot(driver, evidence_name, evidence.level)
                if fallback_on_empty and not rows and index < len(adapters) - 1:
                    if isinstance(evidence.diagnostics, dict) and first_empty_diagnostics is None:
                        first_empty_diagnostics = evidence.diagnostics
                    errors.append(f"{adapter.__class__.__name__}:EMPTY_RESULT")
                    continue
                return rows, evidence
            except Exception as exc:
                errors.append(f"{adapter.__class__.__name__}:{type(exc).__name__}:{exc}")
        fallback = CollectorEvidence(
            level=getattr(adapters[-1], "level", "selenium_dom") if adapters else "selenium_dom",
            final_url=str(getattr(driver, "current_url", "") or ""),
            item_count=0,
            raw_sample="; ".join(errors)[-500:],
            error_code="COLLECTOR_RUNTIME_FAILED",
            screenshot_path=self._capture_screenshot(driver, evidence_name, "failed"),
            fallback_used=len(adapters) > 1,
            adapter_name="CollectorRuntime",
        )
        return [], fallback

    def evidence_payload(self, evidence: CollectorEvidence) -> dict:
        return asdict(evidence)

    def _capture_screenshot(self, driver: Any, evidence_name: str, level: str) -> str:
        if not self.evidence_dir or not hasattr(driver, "save_screenshot"):
            return ""
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in evidence_name)[:80]
        path = os.path.join(self.evidence_dir, f"{safe_name}_{level}.png")
        try:
            if driver.save_screenshot(path):
                return path
        except Exception:
            return ""
        return ""

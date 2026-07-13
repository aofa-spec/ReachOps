# -*- coding: utf-8 -*-
"""Page state sensing for autonomous ReachOps browser execution."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PAGE_STATE_SCHEMA_VERSION = "reachops.page_state.v1"
PAGE_STATES = {
    "READY",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "RATE_LIMITED",
    "PAGE_TIMEOUT",
    "PLATFORM_TEMPORARY_ERROR",
    "DOM_STALLED",
    "MODAL_BLOCKED",
    "COMMENT_BOX_MISSING",
    "SUBMIT_BUTTON_MISSING",
    "UNKNOWN_PAGE_STATE",
}


@dataclass
class PageStateSnapshot:
    state: str = "READY"
    current_url: str = ""
    title: str = ""
    body_text_sample: str = ""
    body_text_sha256: str = ""
    button_status: dict[str, Any] = field(default_factory=dict)
    modal_status: dict[str, Any] = field(default_factory=dict)
    selector_counts: dict[str, int] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    observed_at: str = ""
    schema_version: str = PAGE_STATE_SCHEMA_VERSION
    no_ai_token_used: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        state = str(payload.get("state") or "UNKNOWN_PAGE_STATE")
        payload["state"] = state if state in PAGE_STATES else "UNKNOWN_PAGE_STATE"
        payload["button_status"] = dict(payload.get("button_status") or {})
        payload["modal_status"] = dict(payload.get("modal_status") or {})
        payload["selector_counts"] = dict(payload.get("selector_counts") or {})
        payload["signals"] = list(payload.get("signals") or [])
        payload["schema_version"] = PAGE_STATE_SCHEMA_VERSION
        payload["no_ai_token_used"] = True
        return payload


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _sample_text(text: str, limit: int = 500) -> str:
    return " ".join(str(text or "").split())[:limit]


class PageStateDetector:
    """Classifies browser page state without calling AI services."""

    def detect(
        self,
        driver: Any,
        *,
        action_type: str = "",
        selector_counts: dict[str, int] | None = None,
        previous_snapshot: dict[str, Any] | None = None,
        include_action_requirements: bool = False,
    ) -> dict[str, Any]:
        current_url = self._current_url(driver)
        title = self._title(driver)
        body_text = self._body_text(driver)
        text_lower = body_text.lower()
        combined = f"{current_url.lower()}\n{title.lower()}\n{text_lower}"
        counts = dict(selector_counts or {})
        button_status = self._button_status(driver)
        modal_status = self._modal_status(driver)
        signals: list[str] = []

        state = "READY"
        if self._has_tokens(combined, ["captcha", "verify to continue", "verification", "security check"]):
            state = "CAPTCHA_DETECTED"
            signals.append("captcha_or_verification_text")
        elif self._has_tokens(combined, ["something went wrong", "sorry about that", "please try again later"]):
            state = "PLATFORM_TEMPORARY_ERROR"
            signals.append("platform_temporary_error_text")
        elif self._has_login_gate(current_url.lower(), text_lower, modal_status):
            state = "LOGIN_REQUIRED"
            signals.append("login_gate_visible")
        elif self._has_tokens(combined, ["couldn't load", "no internet", "proxy", "err_proxy", "tunnel connection failed"]):
            state = "PAGE_TIMEOUT" if "couldn't load" in combined else "UNKNOWN_PAGE_STATE"
            signals.append("page_or_network_load_failure")
        elif self._has_tokens(combined, ["too many attempts", "try again later", "temporarily blocked", "limit reached"]):
            state = "RATE_LIMITED"
            signals.append("rate_limit_text")
        elif modal_status.get("blocking_modal_visible"):
            state = "MODAL_BLOCKED"
            signals.append("blocking_modal_visible")
        elif previous_snapshot and self._looks_stalled(previous_snapshot, current_url, body_text):
            state = "DOM_STALLED"
            signals.append("same_url_and_body_digest")
        elif include_action_requirements and str(action_type or "") == "comment_reply":
            comment_box_count = int(counts.get("comment_box_count") or 0)
            comment_submit_count = int(counts.get("comment_submit_count") or 0)
            if comment_box_count <= 0:
                state = "COMMENT_BOX_MISSING"
                signals.append("comment_box_count_zero")
            elif comment_submit_count <= 0:
                state = "SUBMIT_BUTTON_MISSING"
                signals.append("comment_submit_count_zero")

        return PageStateSnapshot(
            state=state,
            current_url=current_url,
            title=title[:160],
            body_text_sample=_sample_text(body_text),
            body_text_sha256=_sha_text(body_text),
            button_status=button_status,
            modal_status=modal_status,
            selector_counts=counts,
            signals=signals,
            observed_at=_utc_now(),
        ).to_dict()

    def capture_state_bundle(
        self,
        driver: Any,
        evidence_dir: str | Path,
        *,
        prefix: str = "page_state",
        metadata: dict[str, Any] | None = None,
        action_type: str = "",
        selector_counts: dict[str, int] | None = None,
        previous_snapshot: dict[str, Any] | None = None,
        include_action_requirements: bool = False,
    ) -> dict[str, Any]:
        """Capture a reusable page-state evidence bundle without AI calls."""
        target_dir = Path(evidence_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_prefix = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(prefix or "page_state"))[:120]
        if not safe_prefix:
            safe_prefix = "page_state"
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        base_path = target_dir / f"{safe_prefix}_{timestamp}"
        screenshot_path = str(base_path.with_suffix(".png"))
        sidecar_path = str(base_path.with_suffix(".json"))

        screenshot_bytes = b""
        screenshot_ok = False
        if driver is not None and hasattr(driver, "save_screenshot"):
            try:
                screenshot_ok = bool(driver.save_screenshot(screenshot_path))
                if screenshot_ok:
                    screenshot_bytes = Path(screenshot_path).read_bytes()
            except Exception:
                screenshot_ok = False
                screenshot_bytes = b""

        snapshot = self.detect(
            driver,
            action_type=action_type,
            selector_counts=selector_counts,
            previous_snapshot=previous_snapshot,
            include_action_requirements=include_action_requirements,
        )
        dom_summary = self._dom_summary(driver)
        payload = {
            "schema_version": PAGE_STATE_SCHEMA_VERSION,
            "captured_at": _utc_now(),
            "metadata": dict(metadata or {}),
            "page_state": snapshot,
            "dom_summary": dom_summary,
            "screenshot": {
                "path": screenshot_path if screenshot_ok else "",
                "captured": screenshot_ok,
                "size": len(screenshot_bytes),
                "sha256": hashlib.sha256(screenshot_bytes).hexdigest() if screenshot_bytes else "",
            },
            "sidecar_path": sidecar_path,
            "no_ai_token_used": True,
        }
        Path(sidecar_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    def _current_url(self, driver: Any) -> str:
        try:
            return str(getattr(driver, "current_url", "") or "")
        except Exception:
            return ""

    def _title(self, driver: Any) -> str:
        try:
            return str(getattr(driver, "title", "") or "")
        except Exception:
            return ""

    def _body_text(self, driver: Any) -> str:
        try:
            return str(driver.execute_script("return document.body ? document.body.innerText : ''") or "")
        except Exception:
            try:
                body = driver.find_element("tag name", "body")
                return str(getattr(body, "text", "") or body.text or "")
            except Exception:
                return ""

    def _button_status(self, driver: Any) -> dict[str, Any]:
        try:
            payload = driver.execute_script(
                """
                const visible = el => {
                  if (!el || !el.getBoundingClientRect) return false;
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const labelOf = el => String([
                  el.innerText,
                  el.textContent,
                  el.getAttribute('aria-label'),
                  el.getAttribute('title'),
                  el.getAttribute('data-e2e')
                ].filter(Boolean).join(' ')).replace(/\\s+/g, ' ').trim().slice(0, 120);
                const buttons = Array.from(document.querySelectorAll('button, [role="button"], a')).filter(visible);
                return {
                  visible_button_count: buttons.length,
                  labels: buttons.slice(0, 30).map(labelOf).filter(Boolean)
                };
                """
            )
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _modal_status(self, driver: Any) -> dict[str, Any]:
        try:
            payload = driver.execute_script(
                """
                const visible = el => {
                  if (!el || !el.getBoundingClientRect) return false;
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const norm = value => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], div[class*="modal" i], div[class*="popup" i]')).filter(visible);
                const labels = dialogs.slice(0, 8).map(el => norm(el.innerText || el.getAttribute('aria-label') || '').slice(0, 180));
                const hardBlock = labels.some(label => /(log in|login|sign up|sign in|captcha|verify|verification|rate limit|try again later|登录|注册|验证|验证码)/i.test(label));
                const softBlock = labels.some(label => /(not now|maybe later|continue|accept|allow|close|dismiss|skip|稍后|以后|允许|关闭|跳过|继续|我知道了|打开 app|open app)/i.test(label));
                const closeCandidates = Array.from(document.querySelectorAll(
                  'button, [role="button"], [aria-label], [data-e2e], svg'
                )).filter(visible).slice(0, 40).map(el => norm([
                  el.innerText,
                  el.textContent,
                  el.getAttribute('aria-label'),
                  el.getAttribute('title'),
                  el.getAttribute('data-e2e')
                ].filter(Boolean).join(' ')).slice(0, 80)).filter(Boolean);
                return {
                  visible_modal_count: dialogs.length,
                  labels,
                  blocking_modal_visible: hardBlock || softBlock || dialogs.length > 0,
                  blocking_modal_type: hardBlock ? 'hard_gate' : (softBlock ? 'dismissible_modal' : (dialogs.length > 0 ? 'unknown_modal' : 'none')),
                  dismissible_modal_visible: softBlock,
                  close_candidates: closeCandidates
                };
                """
            )
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _dom_summary(self, driver: Any) -> dict[str, Any]:
        html = ""
        try:
            html = str(driver.execute_script("return document.documentElement ? document.documentElement.outerHTML : ''") or "")
        except Exception:
            try:
                html = str(getattr(driver, "page_source", "") or "")
            except Exception:
                html = ""
        sample = html[:2000]
        return {
            "html_sample": sample,
            "html_sha256": _sha_text(html),
            "html_length": len(html),
        }

    def _has_login_gate(self, url: str, text: str, modal_status: dict[str, Any]) -> bool:
        if any(token in url for token in ["/login", "/signup", "login?"]):
            return True
        labels = " ".join(str(item or "") for item in modal_status.get("labels") or [])
        if self._has_tokens(labels, ["log in", "login", "sign up", "sign in", "登录", "注册"]):
            return True
        has_login_prompt = self._has_tokens(text, ["log in", "login", "sign up", "sign in", "entrar", "criar conta"])
        has_authenticated_nav = ("messages" in text and "activity" in text) or "inbox" in text
        return bool(has_login_prompt and not has_authenticated_nav)

    def _looks_stalled(self, previous_snapshot: dict[str, Any], current_url: str, body_text: str) -> bool:
        if not previous_snapshot:
            return False
        return (
            str(previous_snapshot.get("current_url") or "") == str(current_url or "")
            and str(previous_snapshot.get("body_text_sha256") or "") == _sha_text(body_text)
        )

    def _has_tokens(self, value: str, tokens: list[str]) -> bool:
        text = str(value or "").lower()
        return any(str(token).lower() in text for token in tokens)


def summarize_page_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": str((snapshot or {}).get("state") or "UNKNOWN_PAGE_STATE"),
        "current_url": str((snapshot or {}).get("current_url") or ""),
        "title": str((snapshot or {}).get("title") or ""),
        "signals": list((snapshot or {}).get("signals") or []),
        "selector_counts": dict((snapshot or {}).get("selector_counts") or {}),
        "schema_version": str((snapshot or {}).get("schema_version") or ""),
        "no_ai_token_used": bool((snapshot or {}).get("no_ai_token_used", True)),
    }


def page_state_to_json(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot or {}, ensure_ascii=False, sort_keys=True)

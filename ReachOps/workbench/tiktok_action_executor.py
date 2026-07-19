# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ReachOps.workbench.offline_learning_ledger import OfflineLearningLedger
from ReachOps.workbench.page_state_detector import PageStateDetector
from ReachOps.workbench.repair_policy_engine import RepairPolicyEngine


@dataclass
class TikTokActionExecutorConfig:
    page_load_timeout_seconds: int = 25
    element_timeout_seconds: int = 10
    after_action_wait_seconds: float = 1.0
    evidence_dir: str = ""
    close_browser_after_action: bool = True
    preflight_only: bool = False
    popup_dismiss_attempts: int = 2


class TikTokSeleniumActionExecutor:
    """Live TikTok action executor behind the GrowthOps PlatformActionExecutor contract.

    The executor is intentionally conservative: it only performs operator-approved
    actions supplied by the action queue, classifies platform failures, captures
    evidence when possible, and lets ExecutionMVPController decide whether a
    technical failure can switch Profile.
    """

    def __init__(
        self,
        config: TikTokActionExecutorConfig | None = None,
        driver_factory: Callable[[dict], tuple[Any, Any, str]] | None = None,
    ):
        self.config = config or TikTokActionExecutorConfig()
        self.driver_factory = driver_factory or self._browser_manager_driver_factory
        self.page_state_detector = PageStateDetector()
        self.repair_policy_engine = RepairPolicyEngine()
        learning_dir = Path(self.config.evidence_dir or "reports/reachops/offline_learning")
        self.offline_learning = OfflineLearningLedger(learning_dir / "unknown_states.json")
        self._page_state_history: dict[str, dict] = {}

    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        if dry_run:
            return {"status": "success", "error_code": "", "error_message": "", "evidence_path": "", "rendered_text": rendered_text}

        driver = None
        release_handle = None
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        try:
            driver, release_handle, factory_error = self.driver_factory(profile)
            if not driver:
                return self._failed("PROFILE_START_FAILED", factory_error or "profile start failed")

            try:
                driver.set_page_load_timeout(self.config.page_load_timeout_seconds)
            except Exception:
                pass

            result = self._execute_with_driver(driver, action, rendered_text)
            if not result.get("evidence_path"):
                live_comment_confirmed = bool(
                    str(action.get("action_type") or "") == "comment_reply"
                    and str(result.get("status") or "") == "success"
                    and not result.get("error_code")
                    and not self.config.preflight_only
                )
                result["evidence_path"] = self._capture_evidence(
                    driver,
                    action,
                    profile_id,
                    result.get("error_code", ""),
                    expected_text=rendered_text,
                    comment_visible_confirmed=live_comment_confirmed,
                )
            result.setdefault("page_diagnostics", self._page_diagnostics(driver))
            return result
        except Exception as exc:
            code = self._classify_exception(exc)
            evidence = self._capture_evidence(driver, action, profile_id, code, expected_text=rendered_text) if driver else ""
            return self._failed(code, str(exc), evidence_path=evidence)
        finally:
            if self.config.close_browser_after_action and release_handle:
                self._release(release_handle)

    def _execute_with_driver(self, driver: Any, action: dict, rendered_text: str) -> dict:
        action_type = str(action.get("action_type") or "")
        target_url = self._target_url(action)
        if not target_url:
            return self._failed("PAGE_OPEN_FAILED", "target_url is empty")

        try:
            driver.get(target_url)
        except Exception as exc:
            code = self._classify_exception(exc)
            if not self.config.preflight_only or code != "PAGE_OPEN_FAILED":
                return self._failed(code, str(exc))
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

        repair_step_results = [
            self._repair_step_from_dismiss_result(self._dismiss_blocking_overlays(driver))
        ]
        state_key = f"{action_type}:{target_url}"
        page_state = self._detect_page_state(driver, state_key=state_key)
        if page_state:
            code = self._normalize_page_state(action_type, page_state)
            if code in {"PAGE_TIMEOUT", "PLATFORM_TEMPORARY_ERROR", "DOM_STALLED", "MODAL_BLOCKED"}:
                repair_step_results.append(self._repair_step_from_refresh_result(self._refresh_page_for_repair(driver)))
                repair_step_results.append(
                    self._repair_step_from_dismiss_result(self._dismiss_blocking_overlays(driver))
                )
                page_state = self._detect_page_state(driver, state_key=state_key)
                if not page_state:
                    code = ""
                else:
                    code = self._normalize_page_state(action_type, page_state)
                    if code == "PLATFORM_TEMPORARY_ERROR" and self._has_real_login_gate(
                        driver,
                        str(getattr(driver, "current_url", "") or "").lower(),
                        self._visible_body_text(driver).lower(),
                    ):
                        code = "LOGIN_REQUIRED"
            if code:
                return self._failed(code, code, repair_step_results=repair_step_results)

        if self.config.preflight_only:
            return self._preflight(driver, action_type, rendered_text)

        if action_type == "comment_reply":
            return self._comment(driver, rendered_text)
        if action_type == "follow_review":
            return self._follow(driver)
        if action_type == "dm_review":
            return self._dm(driver, rendered_text)
        return self._failed("OUTREACH_EXECUTION_FAILED", f"unsupported action_type: {action_type}")

    def _preflight(self, driver: Any, action_type: str, rendered_text: str) -> dict:
        self._dismiss_blocking_overlays(driver)
        if action_type == "comment_reply":
            self._prepare_comment_composer(driver, timeout=self.config.element_timeout_seconds)
            state = self._detect_page_state(
                driver,
                action_type="comment_reply",
                include_action_requirements=True,
            )
            if state in {"COMMENT_BOX_MISSING", "SUBMIT_BUTTON_MISSING"}:
                return self._failed(state, state)
            box = self._find_comment_box(driver, timeout=self.config.element_timeout_seconds)
            if not box:
                return self._failed("COMMENT_BOX_MISSING", "comment box missing")
            return {
                "status": "success",
                "error_code": "",
                "error_message": "preflight: comment box available",
                "rendered_text": rendered_text,
                "preflight": True,
            }
        if action_type == "follow_review":
            button = self._find_first(driver, self._follow_button_selectors(), timeout=self.config.element_timeout_seconds)
            if not button:
                return self._failed("FOLLOW_BUTTON_MISSING", "follow button missing")
            return {
                "status": "success",
                "error_code": "",
                "error_message": f"preflight: follow button available ({self._text(button)})",
                "preflight": True,
            }
        if action_type == "dm_review":
            entry = self._find_first(driver, self._dm_entry_selectors(), timeout=self.config.element_timeout_seconds)
            if not entry:
                return self._failed("DM_ENTRY_NOT_FOUND", "dm entry not found")
            return {
                "status": "success",
                "error_code": "",
                "error_message": "preflight: dm entry available",
                "rendered_text": rendered_text,
                "preflight": True,
            }
        return self._failed("OUTREACH_EXECUTION_FAILED", f"unsupported action_type: {action_type}")

    def _comment(self, driver: Any, rendered_text: str) -> dict:
        self._dismiss_blocking_overlays(driver)
        self._prepare_comment_composer(driver, timeout=self.config.element_timeout_seconds)
        state = self._detect_page_state(
            driver,
            action_type="comment_reply",
            include_action_requirements=True,
        )
        if state in {"COMMENT_BOX_MISSING", "SUBMIT_BUTTON_MISSING"}:
            return self._failed(state, state)
        box = self._find_comment_box(driver, timeout=self.config.element_timeout_seconds)
        if not box:
            return self._failed("COMMENT_BOX_MISSING", "comment box missing")
        try:
            self._click(box)
            box = self._type_comment_text(driver, box, rendered_text) or box
            self._dispatch_comment_input_events(driver, box)
            if not self._comment_box_contains_text(driver, box, rendered_text):
                return self._failed("COMMENT_INPUT_NOT_FILLED", "comment text was not written into composer")
            if self._comment_post_button_disabled(driver):
                return self._failed("COMMENT_SUBMIT_BUTTON_DISABLED", "comment post button stayed disabled after native typing")
            submitted_click = self._click_comment_post_button(driver, box, rendered_text)
            if not submitted_click:
                submitted_click = self._click_visible_comment_submit(driver, rendered_text)
            if not submitted_click:
                submit = self._find_first(driver, self._comment_submit_selectors(), timeout=3)
                submitted_click = bool(submit and self._click_or_dispatch(driver, submit))
            if not submitted_click:
                self._press_enter(box)
            time.sleep(1.0)
            if self._comment_box_contains_text(driver, box, rendered_text):
                if not self._click_comment_post_button(driver, box, rendered_text) and not self._click_comment_submit_cdp(driver, rendered_text) and not self._click_visible_comment_submit(driver, rendered_text):
                    submit = self._find_first(driver, self._comment_submit_selectors(), timeout=1)
                    if not (submit and self._click_or_dispatch(driver, submit)):
                        self._press_enter(box)
                else:
                    time.sleep(0.5)
                    if self._comment_box_contains_text(driver, box, rendered_text):
                        self._press_enter(box)
            confirmed = self._wait_for_comment_submission_confirmation(driver, rendered_text)
        except Exception as exc:
            return self._failed(self._classify_comment_exception(exc), str(exc))
        blocked = self._detect_page_state(driver)
        if blocked:
            code = self._normalize_page_state("comment_reply", blocked)
            return self._failed(code, code)
        if not confirmed:
            return self._failed("COMMENT_SUBMIT_NOT_CONFIRMED", "submitted comment was not visible after posting")
        return {"status": "success", "error_code": "", "error_message": "", "rendered_text": rendered_text}

    def _follow(self, driver: Any) -> dict:
        self._dismiss_blocking_overlays(driver)
        button = self._find_first(driver, self._follow_button_selectors(), timeout=self.config.element_timeout_seconds)
        if not button:
            return self._failed("FOLLOW_BUTTON_MISSING", "follow button missing")
        label_before = self._text(button).lower()
        if self._looks_followed(label_before):
            return {"status": "success", "error_code": "", "error_message": "already followed"}
        try:
            self._click(button)
            time.sleep(max(0.0, float(self.config.after_action_wait_seconds)))
        except Exception as exc:
            return self._failed(self._classify_follow_exception(exc), str(exc))
        state = self._detect_page_state(driver)
        if state:
            code = self._normalize_page_state("follow_review", state)
            return self._failed(code, code)
        label_after = self._text(button).lower()
        if self._looks_followed(label_after) or not label_after:
            return {"status": "success", "error_code": "", "error_message": ""}
        return self._failed("FOLLOW_RATE_LIMITED", f"follow did not change state: {label_after}")

    def _dm(self, driver: Any, rendered_text: str) -> dict:
        self._dismiss_blocking_overlays(driver)
        entry = self._find_first(driver, self._dm_entry_selectors(), timeout=self.config.element_timeout_seconds)
        if not entry:
            return self._failed("DM_ENTRY_NOT_FOUND", "dm entry not found")
        try:
            self._click(entry)
            time.sleep(0.5)
        except Exception as exc:
            return self._failed(self._classify_dm_exception(exc), str(exc))
        state = self._detect_page_state(driver)
        if state:
            code = self._normalize_page_state("dm_review", state)
            return self._failed(code, code)
        box = self._find_first(driver, self._dm_box_selectors(), timeout=self.config.element_timeout_seconds)
        if not box:
            return self._failed("DM_NOT_ALLOWED", "dm input not available")
        try:
            self._click(box)
            self._type_text(box, rendered_text)
            send = self._find_first(driver, self._dm_send_selectors(), timeout=3)
            if send:
                self._click(send)
            else:
                self._press_enter(box)
            time.sleep(max(0.0, float(self.config.after_action_wait_seconds)))
        except Exception as exc:
            return self._failed(self._classify_dm_exception(exc), str(exc))
        state = self._detect_page_state(driver)
        if state:
            code = self._normalize_page_state("dm_review", state)
            return self._failed(code, code)
        return {"status": "success", "error_code": "", "error_message": "", "rendered_text": rendered_text}

    def _normalize_page_state(self, action_type: str, state: str) -> str:
        if state != "RATE_LIMITED":
            return state
        if action_type == "comment_reply":
            return "COMMENT_BLOCKED"
        if action_type == "follow_review":
            return "FOLLOW_RATE_LIMITED"
        if action_type == "dm_review":
            return "DM_RATE_LIMITED"
        return state

    def _browser_manager_driver_factory(self, profile: dict) -> tuple[Any, Any, str]:
        try:
            from ReachOps.adapters.browser_manager import WorkbenchBrowserAdapter, get_workbench_browser_adapter

            profile_id = str(profile.get("profile_id") or profile.get("id") or "")
            manager: WorkbenchBrowserAdapter = get_workbench_browser_adapter()
            inst = manager.acquire(
                account_id=profile_id,
                profile_id=profile_id,
                proxy_id=str(profile.get("proxy_id") or ""),
                trace_id="growth_ops_live_action",
            )
            if not inst:
                return None, None, manager.last_error() or "BrowserManager acquire failed"
            return inst.driver, (manager, inst.instance_id), ""
        except Exception as exc:
            return None, None, str(exc)

    def _release(self, release_handle: Any):
        try:
            if isinstance(release_handle, tuple) and len(release_handle) == 2:
                manager, instance_id = release_handle
                if hasattr(manager, "release"):
                    manager.release(str(instance_id), "growth_ops_action_completed")
                    return
            from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

            get_workbench_browser_adapter().release(str(release_handle), "growth_ops_action_completed")
        except Exception:
            pass

    def _target_url(self, action: dict) -> str:
        action_type = str(action.get("action_type") or "")
        if action_type == "comment_reply":
            return str(action.get("source_path") or action.get("video_url") or action.get("target_content_url") or action.get("target_url") or "").strip()
        return str(action.get("target_url") or action.get("profile_url") or "").strip()

    def _detect_page_state(
        self,
        driver: Any,
        *,
        state_key: str = "",
        action_type: str = "",
        include_action_requirements: bool = False,
    ) -> str:
        previous_snapshot = self._page_state_history.get(state_key) if state_key else None
        snapshot = self.page_state_detector.detect(
            driver,
            action_type=action_type,
            selector_counts=self._page_selector_counts(driver) if include_action_requirements else None,
            previous_snapshot=previous_snapshot,
            include_action_requirements=include_action_requirements,
        )
        if state_key and snapshot:
            self._page_state_history[state_key] = snapshot
        state = str(snapshot.get("state") or "")
        if state == "READY" or (not include_action_requirements and state in {"COMMENT_BOX_MISSING", "SUBMIT_BUTTON_MISSING"}):
            return ""
        return state

    def _has_real_login_gate(self, driver: Any, url: str, text: str) -> bool:
        if any(token in url for token in ["/login", "/signup", "login?"]):
            return True
        if self._has_authenticated_nav_text(text):
            return False
        try:
            visible_gate = driver.execute_script(
                """
                const textMatch = value => /^(log in|login|sign in|sign up|entrar|inscrever-se|criar conta)$/i.test((value || '').trim());
                const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], [role="dialog"]'));
                const visible = el => {
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                return nodes.some(el => visible(el) && textMatch(el.innerText || el.getAttribute('aria-label') || ''));
                """
            )
            if visible_gate:
                return True
        except Exception:
            pass
        login_tokens = ["log in", "login", "sign up", "sign in", "entrar", "criar conta"]
        return any(token in text for token in login_tokens)

    def _has_authenticated_nav_text(self, text: str) -> bool:
        value = str(text or "").lower()
        return ("messages" in value and "activity" in value) or "inbox" in value or ("mensagens" in value and "atividade" in value)

    def _visible_body_text(self, driver: Any) -> str:
        try:
            return str(driver.execute_script("return document.body ? document.body.innerText : ''") or "")
        except Exception:
            return ""

    def _find_first(self, driver: Any, selectors: list[tuple[str, str]], timeout: float = 0) -> Any:
        deadline = time.time() + max(0.0, float(timeout or 0))
        dismiss_round = 0
        while True:
            if dismiss_round < max(0, int(self.config.popup_dismiss_attempts or 0)):
                self._dismiss_blocking_overlays(driver)
                dismiss_round += 1
            for by, selector in selectors:
                try:
                    elements = driver.find_elements(by, selector)
                except Exception:
                    elements = []
                for element in elements or []:
                    if self._is_usable(element):
                        return element
            if time.time() >= deadline:
                return None
            time.sleep(0.25)

    def _is_usable(self, element: Any) -> bool:
        try:
            if hasattr(element, "is_displayed") and not element.is_displayed():
                return False
        except Exception:
            pass
        try:
            if hasattr(element, "is_enabled") and not element.is_enabled():
                return False
        except Exception:
            pass
        return True

    def _click(self, element: Any):
        reason = self._unsafe_click_target_reason(element)
        if reason:
            raise RuntimeError(f"THIRD_PARTY_LOGIN_GUARD: {reason}")
        element.click()

    def _click_or_dispatch(self, driver: Any, element: Any) -> bool:
        if self._unsafe_click_target_reason(element):
            return False
        try:
            self._click(element)
            return True
        except Exception:
            pass
        try:
            return bool(
                driver.execute_script(
                    """
                    const el = arguments[0];
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                      target.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y}));
                    }
                    return true;
                    """,
                    element,
                )
            )
        except Exception:
            return False

    def _click_comment_submit_cdp(self, driver: Any, expected_text: str = "") -> bool:
        if not driver or not hasattr(driver, "execute_cdp_cmd"):
            return False
        try:
            point = driver.execute_script(
                """
                const expected = String(arguments[0] || '').replace(/\\s+/g, ' ').trim();
                const visible = el => {
                  if (!el || !el.getBoundingClientRect) return false;
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const fixedBottomRight = {x: window.innerWidth - 44, y: window.innerHeight - 56};
                const editables = Array.from(document.querySelectorAll('[contenteditable="true"], [role="textbox"], textarea, input, [data-e2e="comment-input"]'))
                  .filter(visible)
                  .filter(el => !expected || ((el.value || el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim()).includes(expected))
                  .sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                const composer = editables[0];
                if (!composer) return null;
                const rect = composer.getBoundingClientRect();
                const y = Math.min(window.innerHeight - 12, Math.max(12, rect.top + rect.height / 2));
                const xs = [
                  Math.min(window.innerWidth - 18, rect.right + 40),
                  Math.min(window.innerWidth - 18, rect.right + 62),
                  window.innerWidth - 42
                ];
                for (const x of xs) {
                  const el = document.elementFromPoint(x, y);
                  const label = el ? [el.innerText, el.textContent, el.getAttribute && el.getAttribute('aria-label'), el.getAttribute && el.getAttribute('data-e2e'), String(el.className || '')].filter(Boolean).join(' ').toLowerCase() : '';
                  if (el && !/(log in|login|sign in|sign up|facebook|google|apple|twitter|instagram)/.test(label)) {
                    return {x, y};
                  }
                }
                return {x: Math.min(window.innerWidth - 42, rect.right + 52), y};
                """,
                expected_text,
            )
            if not isinstance(point, dict):
                return False
            x = float(point.get("x") or 0)
            y = float(point.get("y") or 0)
            if x <= 0 or y <= 0:
                return False
            for event_type in ["mouseMoved", "mousePressed", "mouseReleased"]:
                payload = {"type": event_type, "x": x, "y": y, "button": "left", "buttons": 1 if event_type == "mousePressed" else 0}
                if event_type == "mousePressed":
                    payload["clickCount"] = 1
                if event_type == "mouseReleased":
                    payload["clickCount"] = 1
                driver.execute_cdp_cmd("Input.dispatchMouseEvent", payload)
            if expected_text:
                fallback = driver.execute_script(
                    "return {x: window.innerWidth - 44, y: window.innerHeight - 56};"
                )
                if isinstance(fallback, dict):
                    fx = float(fallback.get("x") or 0)
                    fy = float(fallback.get("y") or 0)
                    if fx > 0 and fy > 0 and (abs(fx - x) > 12 or abs(fy - y) > 12):
                        for event_type in ["mouseMoved", "mousePressed", "mouseReleased"]:
                            payload = {"type": event_type, "x": fx, "y": fy, "button": "left", "buttons": 1 if event_type == "mousePressed" else 0}
                            if event_type in {"mousePressed", "mouseReleased"}:
                                payload["clickCount"] = 1
                            driver.execute_cdp_cmd("Input.dispatchMouseEvent", payload)
            return True
        except Exception:
            return False

    def _dismiss_blocking_overlays(self, driver: Any) -> dict:
        if not driver:
            return {"dismissed": 0, "labels": []}
        labels: list[str] = []
        for _attempt in range(max(1, int(self.config.popup_dismiss_attempts or 1))):
            try:
                result = driver.execute_script(
                    """
                    const dismissLabels = [
                      'not now', 'maybe later', 'later', 'skip', 'cancel', 'close', 'ok', 'got it',
                      'accept all', 'accept', 'agree', 'continue',
                      'agora não', 'não agora', 'nao agora', 'talvez mais tarde', 'pular',
                      'cancelar', 'fechar', 'entendi', 'aceitar tudo', 'aceitar', 'concordo', 'continuar',
                      '以后再说', '稍后', '取消', '关闭', '我知道了', '同意', '接受'
                    ];
                    const unsafeLabels = [
                      'log in', 'login', 'sign up', 'sign in', 'follow', 'following', 'message',
                      'go to tiktok', 'for you feed', 'tiktok-logo',
                      'entrar', 'inscrever', 'criar conta', 'seguir', 'mensagem',
                      '登录', '注册', '关注', '私信'
                    ];
                    const socialAuthTokens = [
                      'facebook', 'google', 'apple', 'twitter', 'x.com', 'instagram',
                      'line', 'kakao', 'wechat', 'whatsapp',
                      'continue with', 'log in with', 'login with', 'sign in with', 'sign up with',
                      '使用', '通过', '继续使用'
                    ];
                    const visible = el => {
                      if (!el || !el.getBoundingClientRect) return false;
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && rect.bottom > 0 && rect.right > 0;
                    };
                    const norm = value => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const labelOf = el => norm([
                      el.innerText,
                      el.textContent,
                      el.getAttribute('aria-label'),
                      el.getAttribute('title'),
                      el.getAttribute('data-e2e')
                    ].filter(Boolean).join(' '));
                    const click = el => {
                      const rect = el.getBoundingClientRect();
                      const x = rect.left + rect.width / 2;
                      const y = rect.top + rect.height / 2;
                      const target = document.elementFromPoint(x, y) || el;
                      for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y}));
                      }
                    };
                    const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, [aria-label], [data-e2e]'))
                      .filter(visible)
                      .map(el => ({el, label: labelOf(el), rect: el.getBoundingClientRect()}))
                      .filter(item => item.label && !unsafeLabels.some(token => item.label.includes(token)))
                      .filter(item => !socialAuthTokens.some(token => item.label.includes(token)));
                    const exact = nodes.find(item => dismissLabels.includes(item.label));
                    const fuzzyTokens = dismissLabels.filter(token => token.length > 3);
                    const fuzzy = nodes.find(item => fuzzyTokens.some(token => item.label.includes(token)) && item.label.length <= 80);
                    const topRightClose = nodes.find(item => {
                      const symbol = ['×', 'x', '✕'].includes(item.label);
                      return symbol && item.rect.top < window.innerHeight * 0.35 && item.rect.left > window.innerWidth * 0.55;
                    });
                    const target = exact || fuzzy || topRightClose;
                    if (target) {
                      click(target.el);
                      return {dismissed: 1, label: target.label};
                    }
                    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true}));
                    return {dismissed: 0, label: ''};
                    """
                )
                if isinstance(result, dict) and int(result.get("dismissed") or 0) > 0:
                    labels.append(str(result.get("label") or ""))
                    time.sleep(0.25)
                    continue
            except Exception:
                pass
            break
        return {"dismissed": len(labels), "labels": labels}

    def _repair_step_from_dismiss_result(self, result: dict | None) -> dict:
        result = result if isinstance(result, dict) else {}
        dismissed = int(result.get("dismissed") or 0)
        return {
            "step": "dismiss_modal",
            "status": "executed_by_browser_executor" if dismissed > 0 else "no_matching_modal",
            "dismissed": dismissed,
            "labels": list(result.get("labels") or []),
            "no_ai_token_used": True,
        }

    def _refresh_page_for_repair(self, driver: Any) -> dict:
        if not driver:
            return {"refreshed": False, "method": "", "error": "driver_missing"}
        try:
            if hasattr(driver, "refresh"):
                driver.refresh()
                time.sleep(0.5)
                return {"refreshed": True, "method": "driver.refresh", "error": ""}
            driver.execute_script("window.location.reload();")
            time.sleep(0.5)
            return {"refreshed": True, "method": "window.location.reload", "error": ""}
        except Exception as exc:
            return {"refreshed": False, "method": "driver.refresh", "error": str(exc) or exc.__class__.__name__}

    def _repair_step_from_refresh_result(self, result: dict | None) -> dict:
        result = result if isinstance(result, dict) else {}
        refreshed = bool(result.get("refreshed"))
        return {
            "step": "refresh_page",
            "status": "executed_by_browser_executor" if refreshed else "failed_by_browser_executor",
            "method": str(result.get("method") or ""),
            "error": str(result.get("error") or ""),
            "no_ai_token_used": True,
        }

    def _click_visible_comment_submit(self, driver: Any, expected_text: str = "") -> bool:
        try:
            return bool(
                driver.execute_script(
                    """
                    const expected = String(arguments[0] || '').replace(/\\s+/g, ' ').trim();
                    const visible = el => {
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const clickAt = (x, y) => {
                      const targetAtPoint = document.elementFromPoint(x, y);
                      const target = targetAtPoint && (targetAtPoint.closest('button, [role="button"], [data-e2e="comment-post"]') || targetAtPoint);
                      if (!target || unsafeClickTarget(target)) return false;
                      const opts = {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, pointerId:1, pointerType:'mouse', isPrimary:true};
                      for (const type of ['pointerover', 'pointerenter', 'mouseover', 'mousemove', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        try {
                          if (type.startsWith('pointer') && window.PointerEvent) {
                            target.dispatchEvent(new PointerEvent(type, opts));
                          } else {
                            target.dispatchEvent(new MouseEvent(type, opts));
                          }
                        } catch (_) {
                          target.dispatchEvent(new MouseEvent(type, opts));
                        }
                      }
                      if (typeof target.click === 'function') target.click();
                      return true;
                    };
                    const unsafeClickTarget = el => {
                      const label = [
                        el && el.innerText,
                        el && el.textContent,
                        el && el.getAttribute && el.getAttribute('aria-label'),
                        el && el.getAttribute && el.getAttribute('title'),
                        el && el.getAttribute && el.getAttribute('href'),
                        el && el.getAttribute && el.getAttribute('data-e2e')
                      ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
                      if (!label) return false;
                      return /(facebook|google|apple|twitter|x\.com|instagram|line|kakao|wechat|whatsapp)/.test(label) ||
                        /(continue with|log in with|login with|sign in with|sign up with)/.test(label) ||
                        /^(log in|login|sign in|sign up|登录|注册|登入)$/.test(label);
                    };
                    if (expected) {
                      const editables = Array.from(document.querySelectorAll('[contenteditable="true"], [role="textbox"], textarea, input, [data-e2e="comment-input"]'))
                        .filter(visible)
                        .filter(el => ((el.value || el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim()).includes(expected))
                        .sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                      const composer = editables[0];
                      if (composer) {
                        const rect = composer.getBoundingClientRect();
                        const y = Math.min(window.innerHeight - 12, Math.max(12, rect.top + rect.height / 2));
                        const xs = [
                          Math.min(window.innerWidth - 20, rect.right + 38),
                          Math.min(window.innerWidth - 20, rect.right + 58),
                          window.innerWidth - 42,
                          window.innerWidth - 28
                        ];
                        for (const x of xs) {
                          if (clickAt(x, y)) return true;
                        }
                      }
                    }
                    const clickable = el => el && (el.closest('button, [role="button"], [data-e2e="comment-post"]') || el);
                    const nodes = Array.from(document.querySelectorAll('button, [role="button"], [data-e2e="comment-post"], svg, div[aria-label], span[aria-label]'))
                      .map(clickable);
                    const unique = Array.from(new Set(nodes));
                    const candidates = unique.filter(el => {
                      if (!visible(el)) return false;
                      if (unsafeClickTarget(el)) return false;
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '') + ' ' + String(el.className || '') + ' ' + (el.getAttribute('data-e2e') || '')).toLowerCase();
                      const nearComposerButton = rect.left > window.innerWidth * 0.88 && rect.top > window.innerHeight * 0.84 && rect.width >= 24 && rect.height >= 24 && rect.width <= 90 && rect.height <= 90;
                      const redSubmit = /rgb\\(254, 44, 85\\)|rgb\\(255, 59, 92\\)|#fe2c55/i.test(style.backgroundColor || '');
                      const submitLike = /post|send|submit|publicar|enviar|comment-post|arrow|seta|发送|发布/.test(label);
                      return (nearComposerButton && (redSubmit || submitLike || label.length < 80)) || submitLike;
                    }).sort((a, b) => {
                      const ar = a.getBoundingClientRect();
                      const br = b.getBoundingClientRect();
                      const ascore = (ar.left > window.innerWidth * 0.88 ? 1000 : 0) + ar.left + ar.top;
                      const bscore = (br.left > window.innerWidth * 0.88 ? 1000 : 0) + br.left + br.top;
                      return bscore - ascore;
                    });
                    const el = candidates[0];
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    return clickAt(x, y);
                    """,
                    expected_text,
                )
            )
        except Exception:
            return False

    def _click_comment_post_button(self, driver: Any, box: Any = None, expected_text: str = "") -> bool:
        def submitted() -> bool:
            if not box or not expected_text:
                return False
            try:
                time.sleep(0.6)
                return not self._comment_box_contains_text(driver, box, expected_text)
            except Exception:
                return False

        try:
            button = driver.execute_script(
                """
                const visible = el => {
                  if (!el || !el.getBoundingClientRect) return false;
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const buttons = Array.from(document.querySelectorAll('[data-e2e="comment-post"], button[aria-label*="Post" i], button[class*="ArrowPostButton" i]'))
                  .filter(visible)
                  .sort((a, b) => {
                    const ar = a.getBoundingClientRect();
                    const br = b.getBoundingClientRect();
                    return (br.left + br.top) - (ar.left + ar.top);
                  });
                return buttons[0] || null;
                """
            )
            if not button:
                return False
            try:
                from selenium.webdriver.common.action_chains import ActionChains

                ActionChains(driver).move_to_element(button).pause(0.05).click(button).perform()
                if submitted():
                    return True
            except Exception:
                pass
            try:
                button.click()
                if submitted():
                    return True
            except Exception:
                pass
            try:
                rect = driver.execute_script(
                    """
                    const el = arguments[0];
                    const rect = el.getBoundingClientRect();
                    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
                    """,
                    button,
                )
                if isinstance(rect, dict) and hasattr(driver, "execute_cdp_cmd"):
                    x = float(rect.get("x") or 0)
                    y = float(rect.get("y") or 0)
                    if x > 0 and y > 0:
                        for event_type in ["mouseMoved", "mousePressed", "mouseReleased"]:
                            payload = {"type": event_type, "x": x, "y": y, "button": "left", "buttons": 1 if event_type == "mousePressed" else 0}
                            if event_type in {"mousePressed", "mouseReleased"}:
                                payload["clickCount"] = 1
                            driver.execute_cdp_cmd("Input.dispatchMouseEvent", payload)
                        if submitted():
                            return True
            except Exception:
                pass
            return False
        except Exception:
            return False

    def _dispatch_comment_input_events(self, driver: Any, element: Any) -> None:
        try:
            driver.execute_script(
                """
                const el = arguments[0];
                if (!el) return;
                el.focus && el.focus();
                for (const type of ['beforeinput', 'input', 'keyup', 'change']) {
                  try {
                    el.dispatchEvent(new Event(type, {bubbles: true, cancelable: true}));
                  } catch (_) {}
                }
                """,
                element,
            )
        except Exception:
            return

    def _comment_post_button_disabled(self, driver: Any) -> bool:
        try:
            return bool(
                driver.execute_script(
                    """
                    const buttons = Array.from(document.querySelectorAll('[data-e2e="comment-post"]'));
                    const visible = el => {
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const button = buttons.filter(visible).sort((a, b) => {
                      const ar = a.getBoundingClientRect();
                      const br = b.getBoundingClientRect();
                      return (br.left + br.top) - (ar.left + ar.top);
                    })[0];
                    if (!button) return false;
                    return Boolean(button.disabled || button.getAttribute('aria-disabled') === 'true');
                    """
                )
            )
        except Exception:
            return False

    def _type_comment_text(self, driver: Any, element: Any, text: str):
        if not text:
            return element
        try:
            rect = driver.execute_script(
                """
                const r = arguments[0].getBoundingClientRect();
                return {x: r.left + r.width / 2, y: r.top + r.height / 2};
                """,
                element,
            )
            if isinstance(rect, dict) and hasattr(driver, "execute_cdp_cmd"):
                x = float(rect.get("x") or 0)
                y = float(rect.get("y") or 0)
                if x > 0 and y > 0:
                    for event_type in ["mouseMoved", "mousePressed", "mouseReleased"]:
                        payload = {"type": event_type, "x": x, "y": y, "button": "left", "buttons": 1 if event_type == "mousePressed" else 0}
                        if event_type in {"mousePressed", "mouseReleased"}:
                            payload["clickCount"] = 1
                        driver.execute_cdp_cmd("Input.dispatchMouseEvent", payload)
                    time.sleep(0.25)
                    self._select_all_and_delete_active_input(driver)
                    try:
                        driver.execute_cdp_cmd("Input.insertText", {"text": text})
                    except Exception:
                        for ch in text:
                            driver.execute_cdp_cmd("Input.dispatchKeyEvent", {"type": "char", "text": ch, "unmodifiedText": ch})
                            time.sleep(0.03)
                    time.sleep(0.35)
                    active = driver.execute_script(
                        """
                        const el = document.activeElement;
                        if (!el) return arguments[0];
                        const value = [el.value, el.innerText, el.textContent].filter(Boolean).join(' ');
                        return value.includes(arguments[1]) ? el : arguments[0];
                        """,
                        element,
                        text,
                    )
                    return active or element
        except Exception:
            pass
        self._type_text(element, text)
        return element

    def _select_all_and_delete_active_input(self, driver: Any) -> None:
        if not hasattr(driver, "execute_cdp_cmd"):
            return
        for modifier in (2, 8):
            try:
                driver.execute_cdp_cmd(
                    "Input.dispatchKeyEvent",
                    {"type": "keyDown", "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65, "modifiers": modifier},
                )
                driver.execute_cdp_cmd(
                    "Input.dispatchKeyEvent",
                    {"type": "keyUp", "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65, "modifiers": modifier},
                )
                driver.execute_cdp_cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8})
                driver.execute_cdp_cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8})
                time.sleep(0.05)
            except Exception:
                continue

    def _comment_box_contains_text(self, driver: Any, element: Any, expected_text: str) -> bool:
        expected = " ".join(str(expected_text or "").split()).strip()
        if not expected:
            return False
        for _ in range(8):
            try:
                current = str(
                    driver.execute_script(
                        """
                        const el = arguments[0];
                        if (!el) return '';
                        return [el.value, el.innerText, el.textContent, el.getAttribute('aria-label')]
                          .filter(Boolean).join(' ');
                        """,
                        element,
                    )
                    or ""
                )
            except Exception:
                current = self._text(element)
            if expected in " ".join(current.split()):
                return True
            time.sleep(0.25)
        return False

    def _wait_for_comment_submission_confirmation(self, driver: Any, rendered_text: str) -> bool:
        expected = " ".join(str(rendered_text or "").split()).strip()
        if not expected:
            return False
        deadline = time.time() + max(5.0, float(self.config.after_action_wait_seconds or 0) + 7.0)
        while time.time() < deadline:
            self._dismiss_blocking_overlays(driver)
            if self._comment_text_visible_outside_composer(driver, expected):
                return True
            time.sleep(0.5)
        return False

    def _comment_text_visible_outside_composer(self, driver: Any, expected_text: str) -> bool:
        try:
            return bool(
                driver.execute_script(
                    """
                    const expected = String(arguments[0] || '').replace(/\\s+/g, ' ').trim();
                    if (!expected) return false;
                    const visible = el => {
                      if (!el || !el.getBoundingClientRect) return false;
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const isComposer = el => {
                      if (!el) return false;
                      const rect = el.getBoundingClientRect();
                      const bottomComposer = rect.top > window.innerHeight * 0.82 && rect.left > window.innerWidth * 0.50;
                      const editableAncestor = Boolean(el.closest('textarea, input, [contenteditable="true"], [role="textbox"], [data-e2e="comment-input"], [class*="input" i], [class*="composer" i]'));
                      return bottomComposer || editableAncestor;
                    };
                    const norm = value => String(value || '').replace(/\\s+/g, ' ').trim();
                    const nodes = Array.from(document.querySelectorAll(
                      '[data-e2e*="comment" i], [class*="comment" i], [data-e2e*="reply" i], [class*="reply" i], p, span, div'
                    ));
                    return nodes.some(el => {
                      if (!visible(el) || isComposer(el)) return false;
                      const text = norm(el.innerText || el.textContent || '');
                      if (!text.includes(expected)) return false;
                      const rect = el.getBoundingClientRect();
                      if (rect.width > window.innerWidth * 0.55 || rect.height > 180) return false;
                      if (text.length > expected.length + 160) return false;
                      if (/start the conversation/i.test(text)) return false;
                      return rect.left > window.innerWidth * 0.35 || rect.top > window.innerHeight * 0.20;
                    });
                    """,
                    expected_text,
                )
            )
        except Exception:
            return False

    def _activate_comments_tab(self, driver: Any):
        try:
            clicked = driver.execute_script(
                """
                const labels = ['comments', 'comment', 'comentários', 'comentarios', 'comentar', '评论'];
                const isRightPanel = rect => rect.left > window.innerWidth * 0.58 || rect.top > window.innerHeight * 0.55;
                const nodes = Array.from(document.querySelectorAll('button, div, span, [role="button"], [aria-label]'));
                const node = nodes
                  .map(el => ({el, rect: el.getBoundingClientRect()}))
                  .filter(item => {
                    const el = item.el;
                    const rect = item.rect;
                    const style = window.getComputedStyle(el);
                    const visible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    if (!visible || !isRightPanel(rect)) return false;
                    const text = (el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const aria = (el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const label = `${text} ${aria}`.trim();
                    if (/(facebook|google|apple|twitter|instagram|continue with|log in with|login with|sign in with|sign up with|登录|注册|login|sign in|sign up)/.test(label)) return false;
                    if (/(you may like|sponsored|shop now|for you|following)/.test(label)) return false;
                    return labels.includes(text) || labels.includes(aria);
                  })
                  .sort((a, b) => a.rect.top - b.rect.top)[0]?.el;
                if (!node) return '';
                const rect = node.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const target = document.elementFromPoint(x, y) || node;
                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window, clientX: x, clientY: y}));
                }
                return (node.textContent || node.getAttribute('aria-label') || '').trim();
                """
            )
            if clicked:
                time.sleep(1.0)
                return
        except Exception:
            pass
        try:
            clicked = driver.execute_script(
                """
                const needles = ['comments', 'comment', 'comentários', 'comentarios', 'comentário', 'comentario', 'comentar', 'ler ou adicionar comentários', 'read or add comments', '评论'];
                const nodes = Array.from(document.querySelectorAll('button, div, span, [role="button"], [aria-label]'));
                const node = nodes.find(el => {
                    const rect = el.getBoundingClientRect();
                    const visible = rect.width > 0 && rect.height > 0;
                    const label = ((el.textContent || '') + ' ' + (el.getAttribute('aria-label') || '')).trim().toLowerCase();
	                    if (!visible || /(facebook|google|apple|twitter|instagram|continue with|log in with|login with|sign in with|sign up with|登录|注册|login|sign in|sign up)/.test(label)) return false;
	                    return needles.some(token => label.includes(token));
	                });
                if (node) {
                    const rect = node.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const target = document.elementFromPoint(x, y) || node;
                    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window, clientX: x, clientY: y}));
                    }
                    return (node.textContent || '').trim();
                }
                return '';
                """
            )
            if clicked:
                time.sleep(1.0)
                return
        except Exception:
            pass
        tab = self._find_first(driver, self._comment_tab_selectors(), timeout=2)
        if not tab:
            return
        try:
            self._click(tab)
            time.sleep(1.0)
        except Exception:
            pass

    def _prepare_comment_composer(self, driver: Any, timeout: float = 0):
        self._dismiss_blocking_overlays(driver)
        self._activate_comments_tab(driver)
        self._click_comment_action(driver)
        self._focus_comment_panel(driver)
        deadline = time.time() + max(0.0, float(timeout or 0))
        while time.time() < deadline:
            self._dismiss_blocking_overlays(driver)
            self._activate_comments_tab(driver)
            if self._find_comment_box(driver, timeout=0.1):
                return
            self._click_comment_action(driver)
            self._focus_comment_panel(driver)
            time.sleep(0.5)

    def _click_comment_action(self, driver: Any):
        try:
            clicked = driver.execute_script(
                """
	                const needles = ['comment', 'comments', 'comentário', 'comentarios', 'comentários', 'comentar', 'ler ou adicionar comentários', 'read or add comments', '评论'];
                const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, div[aria-label], span[aria-label]'));
                const visible = el => {
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const node = nodes.find(el => {
                  if (!visible(el)) return false;
                  const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).toLowerCase();
	                  if (/(facebook|google|apple|twitter|instagram|continue with|log in with|login with|sign in with|sign up with|登录|注册|login|sign in|sign up)/.test(label)) return false;
	                  if (!needles.some(token => label.includes(token))) return false;
                  const rect = el.getBoundingClientRect();
                  return rect.left > window.innerWidth * 0.35 || label.includes('read or add') || label.includes('ler ou adicionar');
                });
                if (!node) return '';
                const rect = node.getBoundingClientRect();
                const x = rect.left + Math.min(rect.width / 2, Math.max(4, rect.width - 4));
                const y = rect.top + rect.height / 2;
                const target = document.elementFromPoint(x, y) || node;
                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                  target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window, clientX: x, clientY: y}));
                }
                return (node.getAttribute('aria-label') || node.innerText || '').trim();
                """
            )
            if clicked:
                time.sleep(0.7)
        except Exception:
            pass

    def _focus_comment_panel(self, driver: Any):
        try:
            driver.execute_script(
                """
                const panel = Array.from(document.querySelectorAll('[data-e2e*="comment"], [class*="comment" i], [aria-label*="comment" i], [aria-label*="coment" i]'))
                  .map(el => ({el, rect: el.getBoundingClientRect()}))
                  .filter(item => item.rect.width > 0 && item.rect.height > 0)
                  .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height))[0]?.el;
                if (panel) {
                  panel.scrollIntoView({block: 'center', inline: 'nearest'});
                  const rect = panel.getBoundingClientRect();
                  const x = Math.min(window.innerWidth - 20, Math.max(20, rect.left + rect.width / 2));
                  const y = Math.min(window.innerHeight - 30, Math.max(30, rect.bottom - 36));
                  const target = document.elementFromPoint(x, y) || panel;
                  target.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:x, clientY:y}));
                  target.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
                }
                window.scrollBy(0, 160);
                """
            )
        except Exception:
            pass

    def _find_comment_box(self, driver: Any, timeout: float = 0) -> Any:
        deadline = time.time() + max(0.0, float(timeout or 0))
        while True:
            self._dismiss_blocking_overlays(driver)
            element = self._find_first(driver, self._comment_box_selectors(), timeout=0)
            if element:
                return element
            try:
                element = driver.execute_script(
                    """
                    const lower = value => String(value || '').toLowerCase();
                    const visible = el => {
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const score = el => {
                      const hay = lower([
                        el.getAttribute('data-e2e'),
                        el.getAttribute('aria-label'),
                        el.getAttribute('placeholder'),
                        el.getAttribute('role'),
                        el.className,
                        el.parentElement && el.parentElement.className,
                        el.parentElement && el.parentElement.getAttribute('aria-label'),
                        el.parentElement && el.parentElement.getAttribute('data-e2e')
                      ].join(' '));
                      if (/search|pesquisar|buscar|combobox/.test(hay)) return -100;
                      let value = 0;
                      if (el.isContentEditable || lower(el.getAttribute('contenteditable')) === 'true') value += 40;
                      if (lower(el.getAttribute('role')) === 'textbox') value += 35;
                      if (['TEXTAREA', 'INPUT'].includes(el.tagName)) value += 20;
                      if (/comment|coment|comentário|comentario|comentar|reply|responder/.test(hay)) value += 45;
                      const rect = el.getBoundingClientRect();
                      if (rect.left > window.innerWidth * 0.38 || rect.top > window.innerHeight * 0.45) value += 12;
                      return value;
                    };
                    const selectors = [
                      '[contenteditable="true"]',
                      '[role="textbox"]',
                      'textarea',
                      '[aria-label*="comment" i]',
                      '[aria-label*="coment" i]',
                      '[data-e2e*="comment" i] [contenteditable="true"]',
                      '[class*="comment" i] [contenteditable="true"]',
                      '[class*="comment" i] [role="textbox"]',
                      '[class*="composer" i] [contenteditable="true"]'
                    ];
                    const nodes = Array.from(new Set(selectors.flatMap(selector => Array.from(document.querySelectorAll(selector)))));
                    const ranked = nodes
                      .filter(visible)
                      .map(el => ({el, value: score(el)}))
                      .filter(item => item.value > 20)
                      .sort((a, b) => b.value - a.value);
                    return ranked[0]?.el || null;
                    """
                )
                if element and self._is_usable(element):
                    return element
            except Exception:
                pass
            if time.time() >= deadline:
                return None
            time.sleep(0.25)

    def _type_text(self, element: Any, text: str):
        try:
            element.clear()
        except Exception:
            pass
        try:
            element.send_keys(text)
            return
        except Exception:
            pass
        try:
            element.parent.execute_script("arguments[0].innerText = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", element, text)
        except Exception as exc:
            raise exc

    def _press_enter(self, element: Any):
        try:
            from selenium.webdriver.common.keys import Keys

            element.send_keys(Keys.ENTER)
            return
        except Exception:
            pass
        try:
            element.parent.execute_script(
                """
                const el = arguments[0];
                if (!el) return false;
                el.focus && el.focus();
                for (const type of ['keydown', 'keypress', 'keyup']) {
                  el.dispatchEvent(new KeyboardEvent(type, {key:'Enter', code:'Enter', bubbles:true, cancelable:true}));
                }
                return true;
                """,
                element,
            )
        except Exception:
            try:
                element.send_keys("\n")
            except Exception:
                pass

    def _text(self, element: Any) -> str:
        try:
            return str(element.text or "")
        except Exception:
            try:
                return str(element.get_attribute("innerText") or element.get_attribute("aria-label") or "")
            except Exception:
                return ""

    def _unsafe_click_target_reason(self, element: Any) -> str:
        label_parts: list[str] = []
        try:
            label_parts.append(str(getattr(element, "text", "") or ""))
        except Exception:
            pass
        for attr in ["innerText", "textContent", "aria-label", "title", "href", "data-e2e", "class"]:
            try:
                if hasattr(element, "get_attribute"):
                    label_parts.append(str(element.get_attribute(attr) or ""))
            except Exception:
                pass
        label = " ".join(" ".join(label_parts).split()).strip().lower()
        if not label:
            return ""
        social_tokens = [
            "facebook",
            "google",
            "apple",
            "twitter",
            "x.com",
            "instagram",
            "line",
            "kakao",
            "wechat",
            "whatsapp",
        ]
        login_provider_tokens = [
            "continue with",
            "log in with",
            "login with",
            "sign in with",
            "sign up with",
            "使用",
            "通过",
            "继续使用",
        ]
        if any(token in label for token in social_tokens):
            return f"third-party login provider target: {label[:120]}"
        if any(token in label for token in login_provider_tokens):
            return f"third-party login action target: {label[:120]}"
        exact_login_labels = {"log in", "login", "sign in", "sign up", "登录", "注册", "登入"}
        if label in exact_login_labels:
            return f"login target: {label[:120]}"
        return ""

    def _looks_followed(self, label: str) -> bool:
        value = str(label or "").lower()
        return any(token in value for token in ["following", "friends", "已关注", "互相关注", "seguindo", "seguidores"])

    def _capture_evidence(
        self,
        driver: Any,
        action: dict,
        profile_id: str,
        code: str = "",
        expected_text: str = "",
        comment_visible_confirmed: bool = False,
    ) -> str:
        if not driver or not self.config.evidence_dir or not hasattr(driver, "save_screenshot"):
            return ""
        try:
            os.makedirs(self.config.evidence_dir, exist_ok=True)
            action_id = str(action.get("id") or "action")
            safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in f"{profile_id}_{action_id}_{code or 'ok'}")[:120]
            path = os.path.join(self.config.evidence_dir, f"{safe}.png")
            if not driver.save_screenshot(path):
                return ""
            data = b""
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except Exception:
                data = b""
            action_type = str(action.get("action_type") or "")
            page_state = self._page_state_snapshot(
                driver,
                action_type=action_type,
                include_action_requirements=bool(code),
            )
            state_bundle = self.page_state_detector.capture_state_bundle(
                driver,
                self.config.evidence_dir,
                prefix=f"{safe}_page_state",
                metadata={
                    "profile_id": profile_id,
                    "action_id": action_id,
                    "action_type": action_type,
                    "target_url": self._target_url(action),
                    "error_code": code or "",
                },
                action_type=action_type,
                selector_counts=self._page_selector_counts(driver),
                include_action_requirements=bool(code),
            )
            offline_learning = self.offline_learning.record_unknown_state(
                page_state=page_state,
                error_code=code or "",
                action_type=action_type,
                evidence_path=path,
                context={"error_message": code or "", "profile_id": profile_id, "action_id": action_id},
            )
            repair_decision = (
                self.repair_policy_engine.decide(
                    code,
                    action_type=action_type,
                    page_state=page_state,
                )
                if code
                else {}
            )
            meta = {
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "profile_id": profile_id,
                "action_id": action_id,
                "action_type": action_type,
                "target_url": self._target_url(action),
                "current_url": str(getattr(driver, "current_url", "") or ""),
                "title": str(getattr(driver, "title", "") or "")[:160],
                "error_code": code or "",
                "preflight_only": bool(self.config.preflight_only),
                "submitted_text": expected_text if action_type == "comment_reply" and not self.config.preflight_only else "",
                "comment_visible_confirmed": bool(comment_visible_confirmed) and not self.config.preflight_only,
                "screenshot_path": path,
                "screenshot_size": len(data),
                "screenshot_sha256": hashlib.sha256(data).hexdigest() if data else "",
                "page_state": page_state,
                "page_state_bundle": state_bundle,
                "offline_learning": offline_learning,
                "repair_decision": repair_decision,
            }
            with open(f"{path}.json", "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
            return path
        except Exception:
            return ""

    def _failed(
        self,
        code: str,
        message: str,
        evidence_path: str = "",
        *,
        repair_step_results: list[dict] | None = None,
    ) -> dict:
        result = {
            "status": "failed",
            "error_code": code or "OUTREACH_EXECUTION_FAILED",
            "error_message": message or code,
            "evidence_path": evidence_path,
        }
        if repair_step_results:
            result["repair_step_results"] = repair_step_results
        return result

    def _page_diagnostics(self, driver: Any) -> dict:
        if not driver:
            return {}
        counts = self._page_selector_counts(driver)
        page_state = self.page_state_detector.detect(
            driver,
            selector_counts=counts,
            include_action_requirements=False,
        )
        return {
            "current_url": str(getattr(driver, "current_url", "") or ""),
            "title": str(page_state.get("title") or "")[:120],
            "body_text_sample": str(page_state.get("body_text_sample") or "")[:300],
            "page_state": page_state,
            "page_state_status": page_state.get("state", ""),
            "comment_button_count": counts.get("comment_button_count", 0),
            "comment_panel_state": self._comment_panel_state(driver),
            "comment_box_count": counts.get("comment_box_count", 0),
            "comment_submit_count": counts.get("comment_submit_count", 0),
            "follow_button_count": counts.get("follow_button_count", 0),
            "dm_entry_count": counts.get("dm_entry_count", 0),
            "editable_candidates": self._editable_candidates(driver),
            "comment_box_candidates": self._comment_box_candidates(driver),
            "button_text_sample": self._button_text_sample(driver),
        }

    def _page_selector_counts(self, driver: Any) -> dict[str, int]:
        return {
            "comment_button_count": self._comment_button_count(driver),
            "comment_box_count": self._count_selectors(driver, self._comment_box_selectors()),
            "comment_submit_count": self._count_selectors(driver, self._comment_submit_selectors()),
            "follow_button_count": self._count_selectors(driver, self._follow_button_selectors()),
            "dm_entry_count": self._count_selectors(driver, self._dm_entry_selectors()),
        }

    def _page_state_snapshot(
        self,
        driver: Any,
        *,
        action_type: str = "",
        include_action_requirements: bool = False,
    ) -> dict:
        if not driver:
            return {}
        return self.page_state_detector.detect(
            driver,
            action_type=action_type,
            selector_counts=self._page_selector_counts(driver),
            include_action_requirements=include_action_requirements,
        )

    def _count_selectors(self, driver: Any, selectors: list[tuple[str, str]]) -> int:
        total = 0
        for by, selector in selectors:
            try:
                total += len(driver.find_elements(by, selector) or [])
            except Exception:
                continue
        return total

    def _editable_candidates(self, driver: Any) -> list[dict]:
        try:
            rows = driver.execute_script(
                """
                return Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"], [role="textbox"]'))
                  .slice(0, 12)
                  .map(el => ({
                    tag: el.tagName,
                    role: el.getAttribute('role') || '',
                    contenteditable: el.getAttribute('contenteditable') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    aria: el.getAttribute('aria-label') || '',
                    text: (el.innerText || el.value || '').slice(0, 80)
                  }));
                """
            )
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _comment_box_candidates(self, driver: Any) -> list[dict]:
        try:
            rows = driver.execute_script(
                """
                const visible = el => {
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                return Array.from(document.querySelectorAll('[contenteditable="true"], [role="textbox"], textarea, [aria-label*="comment" i], [aria-label*="coment" i], [class*="comment" i] [contenteditable="true"], [data-e2e*="comment" i] [contenteditable="true"]'))
                  .filter(visible)
                  .slice(0, 20)
                  .map(el => {
                    const rect = el.getBoundingClientRect();
                    return {
                      tag: el.tagName,
                      role: el.getAttribute('role') || '',
                      contenteditable: el.getAttribute('contenteditable') || '',
                      placeholder: el.getAttribute('placeholder') || '',
                      aria: el.getAttribute('aria-label') || '',
                      data_e2e: el.getAttribute('data-e2e') || '',
                      class_name: String(el.className || '').slice(0, 120),
                      rect: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)},
                      text: (el.innerText || el.value || '').slice(0, 80)
                    };
                  });
                """
            )
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _comment_button_count(self, driver: Any) -> int:
        try:
            count = driver.execute_script(
                """
                const needles = ['comment', 'comments', 'comentário', 'comentarios', 'comentários', 'comentar', 'ler ou adicionar comentários', 'read or add comments', '评论'];
                const visible = el => {
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                return Array.from(document.querySelectorAll('button, [role="button"], a, div[aria-label], span[aria-label]'))
                  .filter(el => visible(el) && needles.some(token => ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase().includes(token)))
                  .length;
                """
            )
            return int(count or 0)
        except Exception:
            return 0

    def _comment_panel_state(self, driver: Any) -> dict:
        try:
            state = driver.execute_script(
                """
                const visible = el => {
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const nodes = Array.from(document.querySelectorAll('[data-e2e*="comment" i], [class*="comment" i], [aria-label*="comment" i], [aria-label*="coment" i]'))
                  .filter(visible)
                  .map(el => {
                    const rect = el.getBoundingClientRect();
                    return {
                      tag: el.tagName,
                      aria: el.getAttribute('aria-label') || '',
                      data_e2e: el.getAttribute('data-e2e') || '',
                      class_name: String(el.className || '').slice(0, 100),
                      text: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 160),
                      rect: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)}
                    };
                  })
                  .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
                return {
                  visible_count: nodes.length,
                  largest: nodes[0] || null,
                  sample: nodes.slice(0, 6)
                };
                """
            )
            return state if isinstance(state, dict) else {}
        except Exception:
            return {}

    def _button_text_sample(self, driver: Any) -> list[str]:
        try:
            rows = driver.execute_script(
                """
                return Array.from(document.querySelectorAll('button, [role="button"]'))
                  .map(el => (el.innerText || el.getAttribute('aria-label') || '').trim())
                  .filter(Boolean)
                  .slice(0, 20);
                """
            )
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _classify_exception(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "third_party_login_guard" in msg:
            return "LOGIN_REQUIRED"
        if any(token in msg for token in ["proxy", "err_tunnel", "tunnel connection"]):
            return "PROXY_FAILED"
        if any(token in msg for token in ["timeout", "timed out"]):
            return "PAGE_OPEN_FAILED"
        if any(token in msg for token in ["disconnected", "chrome not reachable", "invalid session", "no such window"]):
            return "BROWSER_CRASHED"
        return "OUTREACH_EXECUTION_FAILED"

    def _classify_comment_exception(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "rate" in msg or "limit" in msg or "blocked" in msg:
            return "COMMENT_BLOCKED"
        return self._classify_exception(exc) if self._classify_exception(exc) != "OUTREACH_EXECUTION_FAILED" else "COMMENT_SUBMIT_FAILED"

    def _classify_follow_exception(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "rate" in msg or "limit" in msg or "blocked" in msg:
            return "FOLLOW_RATE_LIMITED"
        return self._classify_exception(exc) if self._classify_exception(exc) != "OUTREACH_EXECUTION_FAILED" else "FOLLOW_BUTTON_MISSING"

    def _classify_dm_exception(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "rate" in msg or "limit" in msg:
            return "DM_RATE_LIMITED"
        if "not allowed" in msg or "disabled" in msg:
            return "DM_NOT_ALLOWED"
        return self._classify_exception(exc) if self._classify_exception(exc) != "OUTREACH_EXECUTION_FAILED" else "DM_NOT_ALLOWED"

    def _comment_box_selectors(self) -> list[tuple[str, str]]:
        return [
            ("css selector", "[data-e2e='comment-input']"),
            ("css selector", "[data-e2e*='comment' i] [contenteditable='true']"),
            ("css selector", "[class*='comment' i] [contenteditable='true']"),
            ("css selector", "[class*='composer' i] [contenteditable='true']"),
            ("css selector", "[aria-label*='comment' i][contenteditable='true']"),
            ("css selector", "[aria-label*='coment' i][contenteditable='true']"),
            ("css selector", "[aria-label*='comment' i][role='textbox']"),
            ("css selector", "[aria-label*='coment' i][role='textbox']"),
            ("css selector", "div[contenteditable='true'][role='textbox']"),
            ("css selector", "[contenteditable='true'][role='textbox']"),
            ("css selector", "div[contenteditable='true']"),
            ("css selector", "textarea[placeholder*='comment' i]"),
            ("css selector", "textarea[placeholder*='coment' i]"),
        ]

    def _comment_tab_selectors(self) -> list[tuple[str, str]]:
        return [
            ("xpath", "//*[self::button or self::div or self::span][normalize-space()='Comments' or normalize-space()='Comment' or normalize-space()='Comentários' or normalize-space()='Comentarios' or normalize-space()='评论']"),
            ("xpath", "//*[self::button or self::div or self::span][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÃÕÇ', 'abcdefghijklmnopqrstuvwxyzáéíóúãõç'), 'coment')]"),
        ]

    def _comment_submit_selectors(self) -> list[tuple[str, str]]:
        return [
            ("css selector", "[data-e2e='comment-post']"),
            ("css selector", "[data-e2e*='comment' i] button[type='submit']"),
            ("css selector", "[class*='comment' i] button[type='submit']"),
            ("css selector", "button[type='submit']"),
            ("xpath", "//button[contains(translate(., 'POST', 'post'), 'post')]"),
            ("xpath", "//button[contains(., 'Publicar') or contains(., 'Enviar') or contains(., 'Responder')]"),
        ]

    def _follow_button_selectors(self) -> list[tuple[str, str]]:
        return [
            ("css selector", "[data-e2e='follow-button']"),
            ("xpath", "//button[contains(translate(., 'FOLLOW', 'follow'), 'follow')]"),
            ("xpath", "//button[contains(., '关注') or contains(., 'Seguir')]"),
        ]

    def _dm_entry_selectors(self) -> list[tuple[str, str]]:
        return [
            ("css selector", "[data-e2e='message-button']"),
            ("xpath", "//button[contains(translate(., 'MESSAGE', 'message'), 'message')]"),
            ("xpath", "//a[contains(@href, '/messages') or contains(@href, '/message')]"),
            ("xpath", "//button[contains(., '私信') or contains(., 'Mensagem')]"),
        ]

    def _dm_box_selectors(self) -> list[tuple[str, str]]:
        return [
            ("css selector", "[contenteditable='true'][role='textbox']"),
            ("css selector", "div[contenteditable='true']"),
            ("css selector", "textarea"),
        ]

    def _dm_send_selectors(self) -> list[tuple[str, str]]:
        return [
            ("css selector", "[data-e2e='message-send']"),
            ("css selector", "button[type='submit']"),
            ("xpath", "//button[contains(translate(., 'SEND', 'send'), 'send')]"),
            ("xpath", "//button[contains(., '发送') or contains(., 'Enviar')]"),
        ]

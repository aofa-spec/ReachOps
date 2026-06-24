# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Callable


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
                result["evidence_path"] = self._capture_evidence(driver, action, profile_id, result.get("error_code", ""))
            result.setdefault("page_diagnostics", self._page_diagnostics(driver))
            return result
        except Exception as exc:
            code = self._classify_exception(exc)
            evidence = self._capture_evidence(driver, action, profile_id, code) if driver else ""
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

        self._dismiss_blocking_overlays(driver)
        page_state = self._detect_page_state(driver)
        if page_state:
            code = self._normalize_page_state(action_type, page_state)
            return self._failed(code, code)

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
            box = self._find_comment_box(driver, timeout=self.config.element_timeout_seconds)
            if not box:
                return self._failed("COMMENT_BOX_NOT_FOUND", "comment box not found")
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
        box = self._find_comment_box(driver, timeout=self.config.element_timeout_seconds)
        if not box:
            return self._failed("COMMENT_BOX_NOT_FOUND", "comment box not found")
        try:
            self._click(box)
            self._type_text(box, rendered_text)
            submit = self._find_first(driver, self._comment_submit_selectors(), timeout=3)
            if submit:
                self._click_or_dispatch(driver, submit)
            else:
                if not self._click_visible_comment_submit(driver):
                    self._press_enter(box)
            time.sleep(max(0.0, float(self.config.after_action_wait_seconds)))
        except Exception as exc:
            return self._failed(self._classify_comment_exception(exc), str(exc))
        blocked = self._detect_page_state(driver)
        if blocked:
            code = self._normalize_page_state("comment_reply", blocked)
            return self._failed(code, code)
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
            from ReachOps.adapters.browser_manager import WorkbenchBrowserAdapter

            profile_id = str(profile.get("profile_id") or profile.get("id") or "")
            manager = WorkbenchBrowserAdapter()
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

    def _detect_page_state(self, driver: Any) -> str:
        text = ""
        url = str(getattr(driver, "current_url", "") or "").lower()
        try:
            text = str(driver.execute_script("return document.body ? document.body.innerText : ''") or "").lower()
        except Exception:
            try:
                body = driver.find_element("tag name", "body")
                text = self._text(body).lower()
            except Exception:
                text = ""
        combined = f"{url}\n{text}"
        if any(token in combined for token in ["captcha", "verify to continue", "verification", "security check"]):
            return "CAPTCHA_DETECTED"
        if self._has_real_login_gate(driver, url, text):
            return "LOGIN_REQUIRED"
        if any(token in combined for token in ["couldn't load", "no internet", "proxy", "err_proxy", "tunnel connection failed"]):
            return "PROXY_FAILED"
        if any(token in combined for token in ["too many attempts", "try again later", "temporarily blocked", "limit reached"]):
            return "RATE_LIMITED"
        if "account restricted" in combined:
            return "ACCOUNT_RESTRICTED"
        return ""

    def _has_real_login_gate(self, driver: Any, url: str, text: str) -> bool:
        if any(token in url for token in ["/login", "/signup", "login?"]):
            return True
        logged_in_markers = [
            "messages",
            "message",
            "profile",
            "upload",
            "inbox",
            "mensagens",
            "mensagem",
            "perfil",
            "carregar",
            "enviar",
            "following",
            "seguindo",
            "para você",
            "for you",
        ]
        if any(marker in text for marker in logged_in_markers):
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
        element.click()

    def _click_or_dispatch(self, driver: Any, element: Any) -> bool:
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
                      'entrar', 'inscrever', 'criar conta', 'seguir', 'mensagem',
                      '登录', '注册', '关注', '私信'
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
                      .filter(item => item.label && !unsafeLabels.some(token => item.label.includes(token)));
                    const exact = nodes.find(item => dismissLabels.includes(item.label));
                    const fuzzy = nodes.find(item => dismissLabels.some(token => item.label.includes(token)) && item.label.length <= 80);
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

    def _click_visible_comment_submit(self, driver: Any) -> bool:
        try:
            return bool(
                driver.execute_script(
                    """
                    const visible = el => {
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const nodes = Array.from(document.querySelectorAll('button, [role="button"], svg, div[aria-label], span[aria-label]'));
                    const candidates = nodes.filter(el => {
                      if (!visible(el)) return false;
                      const rect = el.getBoundingClientRect();
                      const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '') + ' ' + String(el.className || '')).toLowerCase();
                      const nearComposer = rect.left > window.innerWidth * 0.72 && rect.top > window.innerHeight * 0.80;
                      const submitLike = /post|send|submit|publicar|enviar|comment-post|arrow|seta/.test(label);
                      return nearComposer || submitLike;
                    }).sort((a, b) => {
                      const ar = a.getBoundingClientRect();
                      const br = b.getBoundingClientRect();
                      return (br.left + br.top) - (ar.left + ar.top);
                    });
                    const el = candidates[0];
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                      target.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y}));
                    }
                    return true;
                    """
                )
            )
        except Exception:
            return False

    def _activate_comments_tab(self, driver: Any):
        try:
            clicked = driver.execute_script(
                """
                const labels = ['Comments', 'Comment', 'Comentários', 'Comentarios', 'Comentar', '评论'];
                const needles = ['comments', 'comment', 'comentários', 'comentarios', 'comentário', 'comentario', 'comentar', 'ler ou adicionar comentários', 'read or add comments', '评论'];
                const nodes = Array.from(document.querySelectorAll('button, div, span, [role="button"], [aria-label]'));
                const node = nodes.find(el => {
                    const rect = el.getBoundingClientRect();
                    const visible = rect.width > 0 && rect.height > 0;
                    const label = ((el.textContent || '') + ' ' + (el.getAttribute('aria-label') || '')).trim().toLowerCase();
                    return visible && (labels.includes((el.textContent || '').trim()) || needles.some(token => label.includes(token)));
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
        except Exception:
            element.send_keys("\n")

    def _text(self, element: Any) -> str:
        try:
            return str(element.text or "")
        except Exception:
            try:
                return str(element.get_attribute("innerText") or element.get_attribute("aria-label") or "")
            except Exception:
                return ""

    def _looks_followed(self, label: str) -> bool:
        value = str(label or "").lower()
        return any(token in value for token in ["following", "friends", "已关注", "互相关注", "seguindo", "seguidores"])

    def _capture_evidence(self, driver: Any, action: dict, profile_id: str, code: str = "") -> str:
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
            meta = {
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "profile_id": profile_id,
                "action_id": action_id,
                "action_type": str(action.get("action_type") or ""),
                "target_url": self._target_url(action),
                "current_url": str(getattr(driver, "current_url", "") or ""),
                "title": str(getattr(driver, "title", "") or "")[:160],
                "error_code": code or "",
                "screenshot_path": path,
                "screenshot_size": len(data),
                "screenshot_sha256": hashlib.sha256(data).hexdigest() if data else "",
            }
            with open(f"{path}.json", "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
            return path
        except Exception:
            return ""

    def _failed(self, code: str, message: str, evidence_path: str = "") -> dict:
        return {"status": "failed", "error_code": code or "OUTREACH_EXECUTION_FAILED", "error_message": message or code, "evidence_path": evidence_path}

    def _page_diagnostics(self, driver: Any) -> dict:
        if not driver:
            return {}
        text = ""
        title = ""
        try:
            title = str(getattr(driver, "title", "") or "")
        except Exception:
            title = ""
        try:
            text = str(driver.execute_script("return document.body ? document.body.innerText : ''") or "")
        except Exception:
            text = ""
        return {
            "current_url": str(getattr(driver, "current_url", "") or ""),
            "title": title[:120],
            "body_text_sample": " ".join(text.split())[:300],
            "comment_button_count": self._comment_button_count(driver),
            "comment_panel_state": self._comment_panel_state(driver),
            "comment_box_count": self._count_selectors(driver, self._comment_box_selectors()),
            "comment_submit_count": self._count_selectors(driver, self._comment_submit_selectors()),
            "follow_button_count": self._count_selectors(driver, self._follow_button_selectors()),
            "dm_entry_count": self._count_selectors(driver, self._dm_entry_selectors()),
            "editable_candidates": self._editable_candidates(driver),
            "comment_box_candidates": self._comment_box_candidates(driver),
            "button_text_sample": self._button_text_sample(driver),
        }

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

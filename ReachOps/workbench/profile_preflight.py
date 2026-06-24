# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.adapters.ix_profile_group_manager import IxProfileGroupManager

from .account_health_manager import AccountHealthManager
from .tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor


@dataclass
class ProfilePreflightConfig:
    max_workers: int = 3
    page_load_timeout_seconds: int = 20
    wait_after_open_seconds: float = 2.0
    check_url: str = "https://www.tiktok.com/messages"
    evidence_dir: str = ""
    close_browser_after_check: bool = True
    total_timeout_seconds: float = 0


class ProfilePreflightChecker:
    """Starts multiple ixBrowser Profiles and keeps only accounts usable for outreach."""

    def __init__(
        self,
        storage: GrowthStorage,
        config: ProfilePreflightConfig | None = None,
        driver_factory: Callable[[dict], tuple[Any, Any, str]] | None = None,
        health_manager: AccountHealthManager | None = None,
        group_manager: IxProfileGroupManager | None = None,
    ):
        self.storage = storage
        self.config = config or ProfilePreflightConfig()
        self.health_manager = health_manager or AccountHealthManager(storage)
        self.group_manager = group_manager or IxProfileGroupManager(
            logger=lambda message: self.storage.log_event("ix_profile_group_manager", "", {"message": message})
        )
        self._executor = TikTokSeleniumActionExecutor(
            TikTokActionExecutorConfig(
                page_load_timeout_seconds=self.config.page_load_timeout_seconds,
                evidence_dir=self.config.evidence_dir,
                close_browser_after_action=self.config.close_browser_after_check,
            ),
            driver_factory=driver_factory,
        )
        self._lock = threading.Lock()

    def run(self, profiles: list[dict]) -> dict:
        rows = list(profiles or [])
        if not rows:
            return self._summary([], [])
        max_workers = max(1, min(int(self.config.max_workers or 1), len(rows)))
        results: list[dict] = []
        self.storage.log_event("profile_preflight_started", "", {"profile_count": len(rows), "workers": max_workers})
        pool = ThreadPoolExecutor(max_workers=max_workers)
        futures = {pool.submit(self.check_profile, profile): profile for profile in rows}
        completed = set()
        timeout = float(self.config.total_timeout_seconds or 0)
        if timeout <= 0:
            timeout = max(10, (int(self.config.page_load_timeout_seconds or 20) + int(self.config.wait_after_open_seconds or 0) + 10) * ((len(rows) + max_workers - 1) // max_workers))
        try:
            for future in as_completed(futures, timeout=timeout):
                result = future.result()
                completed.add(future)
                with self._lock:
                    results.append(result)
        except FuturesTimeout:
            pass
        finally:
            for future, profile in futures.items():
                if future in completed:
                    continue
                future.cancel()
                result = self._record(
                    profile,
                    False,
                    "PROFILE_PREFLIGHT_TIMEOUT",
                    f"profile preflight exceeded {timeout}s",
                    "",
                    time.time() - timeout,
                )
                with self._lock:
                    results.append(result)
            pool.shutdown(wait=False, cancel_futures=True)
        summary = self._summary(rows, results)
        self.storage.log_event("profile_preflight_completed", "", summary)
        return summary

    def available_profiles(self, profiles: list[dict]) -> tuple[list[dict], dict]:
        summary = self.run(profiles)
        ok_ids = {str(row.get("profile_id") or "") for row in summary.get("results", []) if row.get("ok")}
        available = [profile for profile in profiles or [] if str(profile.get("profile_id") or profile.get("id") or "") in ok_ids]
        return available, summary

    def check_profile(self, profile: dict) -> dict:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        driver = None
        release_handle = None
        started_at = time.time()
        try:
            driver, release_handle, factory_error = self._executor.driver_factory(profile)
            if not driver:
                return self._record(profile, False, "PROFILE_START_FAILED", factory_error or "profile start failed", "", started_at)
            try:
                driver.set_page_load_timeout(self.config.page_load_timeout_seconds)
            except Exception:
                pass
            try:
                driver.get(self.config.check_url)
                time.sleep(max(0.0, float(self.config.wait_after_open_seconds or 0)))
            except Exception as exc:
                code = self._executor._classify_exception(exc)
                evidence = self._capture(driver, profile_id, code)
                return self._record(profile, False, code, str(exc), evidence, started_at)
            try:
                self._executor._dismiss_blocking_overlays(driver)
            except Exception:
                pass
            state = self._executor._detect_page_state(driver)
            if state:
                evidence = self._capture(driver, profile_id, state)
                return self._record(profile, False, state, state, evidence, started_at)
            login_state = self._detect_login_state(driver)
            if login_state.get("login_required"):
                evidence = self._capture(driver, profile_id, "LOGIN_REQUIRED")
                return self._record(profile, False, "LOGIN_REQUIRED", login_state.get("reason") or "login required", evidence, started_at)
            evidence = self._capture(driver, profile_id, "ok")
            return self._record(profile, True, "", login_state.get("reason") or "profile ready", evidence, started_at)
        except Exception as exc:
            evidence = self._capture(driver, profile_id, "PROFILE_PREFLIGHT_FAILED") if driver else ""
            return self._record(profile, False, "PROFILE_PREFLIGHT_FAILED", str(exc), evidence, started_at)
        finally:
            if self.config.close_browser_after_check and release_handle:
                self._executor._release(release_handle)

    def _detect_login_state(self, driver: Any) -> dict:
        try:
            state = driver.execute_script(
                """
                const text = (document.body ? document.body.innerText : '').toLowerCase();
                const title = String(document.title || '').toLowerCase();
                const url = String(location.href || '').toLowerCase();
                const visible = el => {
                  if (!el || !el.getBoundingClientRect) return false;
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' &&
                    rect.bottom > 0 && rect.right > 0 && rect.top < (window.innerHeight || 900);
                };
                const label = el => String([
                  el.innerText,
                  el.textContent,
                  el.getAttribute('aria-label'),
                  el.getAttribute('title'),
                  el.getAttribute('data-e2e')
                ].filter(Boolean).join(' ')).replace(/\\s+/g, ' ').trim().toLowerCase();
                const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], [role="dialog"], input'));
                const labels = nodes.filter(visible).map(label).filter(Boolean).slice(0, 80);
                const dialogTexts = Array.from(document.querySelectorAll('[role="dialog"], [data-e2e*="modal"], div'))
                  .filter(visible)
                  .map(label)
                  .filter(v => v.length >= 4 && v.length <= 600)
                  .slice(0, 30);
                const combined = [text, title, labels.join(' '), dialogTexts.join(' ')].join(' ');
                const exactLoginButton = labels.some(v => /^(log in|login|sign in|sign up|entrar|inscrever-se|criar conta|iniciar sesión|registrarse)$/.test(v));
                const dialogLoginGate = dialogTexts.some(v =>
                  /(log in|login|sign in|sign up|entrar|inscrever|criar conta|iniciar sesión|registrarse|登录|注册)/.test(v)
                );
                const forcedLoginText =
                  /(log in to|login to|sign up for|sign up \\| tiktok|entrar para|faça login|inicia sesión|登录后|登入後|注册后)/.test(combined);
                const loginPage = /\\/login|\\/signup|login\\?/.test(url) || /(^|\\|\\s*)(sign up|log in|login)(\\s*\\||$)/.test(title);
                const loggedIn = /messages|inbox|upload|following|profile|mensagens|caixa de entrada|carregar|seguindo|perfil/.test(text)
                  || labels.some(v => /^(messages|inbox|upload|profile|mensagens|carregar|perfil)$/.test(v));
                const loginGate = loginPage || exactLoginButton || dialogLoginGate || forcedLoginText;
                return {
                  url,
                  title,
                  loginGate,
                  loggedIn,
                  exactLoginButton,
                  dialogLoginGate,
                  forcedLoginText,
                  labels: labels.slice(0, 20),
                  dialogs: dialogTexts.slice(0, 8),
                  sample: text.replace(/\\s+/g, ' ').slice(0, 240)
                };
                """
            )
        except Exception:
            state = {}
        if not isinstance(state, dict):
            state = {}
        if state.get("loginGate") and not state.get("loggedIn"):
            return {"login_required": True, "reason": "TikTok login popup/page visible", "state": state}
        return {"login_required": False, "reason": "TikTok session usable", "state": state}

    def _record(self, profile: dict, ok: bool, error_code: str, message: str, evidence_path: str, started_at: float) -> dict:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        if ok:
            self.health_manager.record_success(profile)
        else:
            self.health_manager.record_failure(profile, error_code or "PROFILE_PREFLIGHT_FAILED", message)
            if (error_code or "") in {
                "LOGIN_REQUIRED",
                "CAPTCHA_DETECTED",
                "PROXY_FAILED",
                "PROFILE_START_FAILED",
                "PROFILE_PREFLIGHT_TIMEOUT",
                "COMMENT_ACCESS_GATED",
            }:
                self._move_profile_to_quarantine(profile_id, error_code or "PROFILE_PREFLIGHT_FAILED", message)
        row = {
            "profile_id": profile_id,
            "group_name": str(profile.get("group_name") or ""),
            "ok": bool(ok),
            "error_code": error_code or "",
            "error_message": message or "",
            "evidence_path": evidence_path or "",
            "duration_seconds": round(time.time() - started_at, 3),
        }
        self.storage.log_event("profile_preflight_checked", profile_id, row)
        return row

    def _move_profile_to_quarantine(self, profile_id: str, error_code: str, message: str = ""):
        try:
            result = self.group_manager.move_profile_to_quarantine(profile_id, reason=error_code)
        except Exception as exc:
            self.storage.log_event(
                "profile_quarantine_move_failed",
                profile_id,
                {"error_code": "IX_PROFILE_GROUP_MOVE_FAILED", "error_message": str(exc), "reason": error_code},
            )
            return
        payload = {
            "ok": result.ok,
            "profile_id": result.profile_id,
            "group_id": result.group_id,
            "group_name": result.group_name,
            "reason": error_code,
            "message": message,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }
        self.storage.log_event("profile_quarantine_move_completed" if result.ok else "profile_quarantine_move_failed", profile_id, payload)

    def _capture(self, driver: Any, profile_id: str, code: str) -> str:
        if not driver or not self.config.evidence_dir or not hasattr(driver, "save_screenshot"):
            return ""
        os.makedirs(self.config.evidence_dir, exist_ok=True)
        return self._executor._capture_evidence(driver, {"id": "profile_preflight", "action_type": "profile_preflight", "target_url": self.config.check_url}, profile_id, code)

    def _summary(self, profiles: list[dict], results: list[dict]) -> dict:
        errors: dict[str, int] = {}
        for row in results:
            code = str(row.get("error_code") or "")
            if code:
                errors[code] = errors.get(code, 0) + 1
        return {
            "requested": len(profiles or []),
            "checked": len(results or []),
            "available": len([row for row in results or [] if row.get("ok")]),
            "unavailable": len([row for row in results or [] if not row.get("ok")]),
            "errors": errors,
            "results": sorted(results or [], key=lambda row: str(row.get("profile_id") or "")),
        }

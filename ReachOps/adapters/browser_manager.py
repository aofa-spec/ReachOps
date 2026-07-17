# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class BrowserSession:
    instance_id: str
    profile_id: str
    account_id: str = ""
    proxy_id: str = ""
    trace_id: str = ""
    driver: Any = None
    client: Any = None
    error_message: str = ""


class BrowserDriverAdapter(Protocol):
    last_error: str

    def create_driver(self, profile_id: str) -> tuple[Any | None, Any | None]:
        ...

    def close_profile(self, client: Any, profile_id: str):
        ...

    def close_profile_by_id(self, profile_id: str):
        ...


class IxBrowserLocalAdapter:
    """Standalone ixBrowser adapter for ReachOps.

    This implementation talks to ixBrowser's local API directly and does not
    depend on publishing modules.
    """

    def __init__(self):
        self.last_error = ""

    def create_driver(self, profile_id: str) -> tuple[Any | None, Any | None]:
        client = None
        profile_key = None
        try:
            self.last_error = ""
            self._configure_localhost_proxy_bypass()
            from ixbrowser_local_api import IXBrowserClient

            client = IXBrowserClient()
            profile_key = self._normalize_profile_id(profile_id)
            result = client.open_profile(
                profile_key,
                cookies_backup=False,
                load_profile_info_page=False,
            )
            if result is None:
                result = self._recover_timed_out_open_profile(profile_id, client)
            if result is None:
                self.last_error = (
                    f"ixBrowser open_profile failed: "
                    f"code={getattr(client, 'code', '')} message={getattr(client, 'message', '')}"
                )
                self.close_profile(client, profile_id)
                return None, client

            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            options = Options()
            for arg in [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-blink-features=AutomationControlled",
            ]:
                options.add_argument(arg)
            debug_port = self._resolve_debug_port(client, result)
            if not debug_port:
                self.last_error = "ixBrowser remote debug port is not reachable"
                self.close_profile(client, profile_id)
                return None, None
            options.debugger_address = f"127.0.0.1:{debug_port}"
            driver = webdriver.Chrome(service=Service(result["webdriver"]), options=options)
            self._close_startup_noise_tabs(driver)
            client.profile_id = profile_id
            return driver, client
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if client is not None and profile_key is not None:
                self.close_profile(client, profile_id)
            return None, None

    def close_profile(self, client: Any, profile_id: str):
        try:
            if client is not None and profile_id:
                client.close_profile(self._normalize_profile_id(profile_id))
        except Exception:
            pass

    def close_profile_by_id(self, profile_id: str):
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return
        try:
            from ixbrowser_local_api import IXBrowserClient

            self.close_profile(IXBrowserClient(), profile_id)
        except Exception:
            pass

    @staticmethod
    def _configure_localhost_proxy_bypass():
        existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        entries = [item.strip() for item in existing.split(",") if item.strip()]
        for item in ["127.0.0.1", "localhost", "::1"]:
            if item not in entries:
                entries.append(item)
        value = ",".join(entries)
        os.environ["NO_PROXY"] = value
        os.environ["no_proxy"] = value

    @staticmethod
    def _normalize_profile_id(profile_id):
        value = str(profile_id or "").strip()
        if value.isdigit():
            return int(value)
        return profile_id

    @classmethod
    def _resolve_debug_port(cls, client: Any, result: dict) -> int | None:
        ports: list[int] = []
        for key in ("debugging_port", "debug_port"):
            try:
                port = result.get(key)
                if port:
                    ports.append(int(port))
            except Exception:
                pass
        match = re.search(r"127\.0\.0\.1:(\d+)", str(result.get("ws", "")))
        if match:
            ports.append(int(match.group(1)))
        if not ports:
            try:
                port = client.get_remote_debug_port()
                if port:
                    ports.append(int(port))
            except Exception:
                pass
        seen = set()
        for port in ports:
            if port in seen:
                continue
            seen.add(port)
            if cls._debug_port_reachable(port):
                return port
        return ports[-1] if ports else None

    def _recover_timed_out_open_profile(self, profile_id: str, client: Any) -> dict | None:
        message = str(getattr(client, "message", "") or "").lower()
        if "read timed out" not in message and "timed out" not in message:
            return None
        deadline = time.time() + max(1, int(os.environ.get("REACHOPS_IX_RECOVER_SECONDS", "20") or "20"))
        while time.time() < deadline:
            result = self._profile_process_result(profile_id)
            if result and self._debug_port_reachable(int(result["debugging_port"])):
                return result
            time.sleep(1)
        return None

    @staticmethod
    def _profile_process_result(profile_id: str) -> dict | None:
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return None
        try:
            output = subprocess.run(
                ["ps", "-axo", "command="],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            ).stdout
        except Exception:
            return None
        for line in output.splitlines():
            if f"--protected-userid={profile_id}" not in line or "--remote-debugging-port=" not in line:
                continue
            port_match = re.search(r"--remote-debugging-port=(\d+)", line)
            chrome_match = re.search(r"(/Users/.+?/ixBrowser-Resources/chrome/[^/]+)/Chromium\.app/", line)
            if not port_match or not chrome_match:
                continue
            webdriver = os.path.join(chrome_match.group(1), "chromedriver.app", "Contents", "MacOS", "chromedriver")
            if not os.path.exists(webdriver):
                continue
            return {
                "debugging_port": int(port_match.group(1)),
                "webdriver": webdriver,
                "recovered_from_process": True,
            }
        return None

    @staticmethod
    def _debug_port_reachable(port: int) -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5).read(32)
            return True
        except Exception:
            return False

    @staticmethod
    def _close_startup_noise_tabs(driver: Any) -> int:
        """Remove restored product/store tabs before ReachOps starts navigation."""
        try:
            handles = list(getattr(driver, "window_handles", []) or [])
        except Exception:
            return 0
        if len(handles) <= 1:
            return 0
        try:
            original = getattr(driver, "current_window_handle", "") or handles[0]
        except Exception:
            original = handles[0]
        tab_rows: list[tuple[str, str]] = []
        for handle in handles:
            try:
                driver.switch_to.window(handle)
                tab_rows.append((handle, str(getattr(driver, "current_url", "") or "")))
            except Exception:
                tab_rows.append((handle, ""))

        def keep_url(url: str) -> bool:
            value = str(url or "").lower()
            return (
                not value
                or value.startswith("about:")
                or value.startswith("chrome:")
                or value.startswith("devtools:")
                or "tiktok.com" in value
            )

        keep_handles = [handle for handle, url in tab_rows if keep_url(url)]
        if not keep_handles:
            keep_handles = [original if original in handles else handles[0]]
        closed = 0
        for handle, url in tab_rows:
            if handle in keep_handles:
                continue
            try:
                driver.switch_to.window(handle)
                driver.close()
                closed += 1
            except Exception:
                pass
        try:
            remaining = list(getattr(driver, "window_handles", []) or [])
            target = original if original in remaining else (keep_handles[0] if keep_handles[0] in remaining else (remaining[0] if remaining else ""))
            if target:
                driver.switch_to.window(target)
        except Exception:
            pass
        return closed


class WorkbenchBrowserAdapter:
    """ReachOps browser session manager.

    The standalone adapter is the default path. Any legacy publishing
    browser manager is kept only as a compatibility fallback and can be disabled
    with REACHOPS_BROWSER_FALLBACK_LEGACY=0.
    """

    def __init__(self, driver_adapter: BrowserDriverAdapter | None = None, allow_legacy_fallback: bool | None = None):
        self.driver_adapter = driver_adapter or IxBrowserLocalAdapter()
        self.allow_legacy_fallback = (
            os.environ.get("REACHOPS_BROWSER_FALLBACK_LEGACY", "1") != "0"
            if allow_legacy_fallback is None
            else bool(allow_legacy_fallback)
        )
        self._sessions: dict[str, BrowserSession] = {}
        self._profile_to_instance: dict[str, str] = {}
        self._lock = threading.Lock()
        self._last_error = ""

    def acquire(self, profile_id: str, trace_id: str, account_id: str = "", proxy_id: str = "", max_instances: int = 3) -> BrowserSession | None:
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            self._last_error = "empty profile_id"
            return None
        with self._lock:
            existing_id = self._profile_to_instance.get(profile_id)
            if existing_id and existing_id in self._sessions:
                return self._sessions[existing_id]
            if len(self._sessions) >= max(1, int(max_instances or 1)):
                self._last_error = "reachops browser max_instances reached"
                return None
        driver, client = self.driver_adapter.create_driver(profile_id)
        if driver is None:
            self._last_error = str(getattr(self.driver_adapter, "last_error", "") or "ixBrowser driver creation failed")
            legacy = self._acquire_legacy(profile_id, trace_id, account_id, proxy_id, max_instances)
            if legacy is not None:
                return legacy
            return None
        session = BrowserSession(
            instance_id=f"ro-{uuid.uuid4().hex[:8]}",
            account_id=account_id or f"growth-{profile_id}",
            profile_id=profile_id,
            proxy_id=proxy_id,
            trace_id=trace_id,
            driver=driver,
            client=client,
        )
        with self._lock:
            self._sessions[session.instance_id] = session
            self._profile_to_instance[profile_id] = session.instance_id
        return session

    def release(self, instance_id: str, reason: str):
        if not instance_id:
            return
        with self._lock:
            session = self._sessions.pop(instance_id, None)
            if session:
                self._profile_to_instance.pop(session.profile_id, None)
        if not session:
            self._release_legacy(instance_id, reason)
            return
        try:
            if getattr(session.driver, "quit", None):
                session.driver.quit()
        except Exception:
            pass
        self.driver_adapter.close_profile(session.client, session.profile_id)

    def release_profile(self, profile_id: str, reason: str):
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return
        with self._lock:
            instance_id = self._profile_to_instance.get(profile_id, "")
        if instance_id:
            self.release(instance_id, reason)

    def force_close_profile(self, profile_id: str, reason: str):
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return
        self.release_profile(profile_id, reason)
        close_by_id = getattr(self.driver_adapter, "close_profile_by_id", None)
        if callable(close_by_id):
            close_by_id(profile_id)

    def last_error(self) -> str:
        return self._last_error

    def _acquire_legacy(self, profile_id: str, trace_id: str, account_id: str, proxy_id: str, max_instances: int) -> Any | None:
        if not self.allow_legacy_fallback:
            return None
        try:
            from modules.publish.infrastructure.browser.browser_manager import get_browser_manager

            manager = get_browser_manager()
            try:
                manager.start(max_instances=max_instances)
            except TypeError:
                manager.start()
            inst = manager.acquire(
                account_id=account_id or f"growth-{profile_id}",
                profile_id=profile_id,
                proxy_id=proxy_id,
                trace_id=trace_id,
            )
            if inst is None:
                try:
                    self._last_error = str(manager.get_last_acquire_error() or self._last_error)
                except Exception:
                    pass
            return inst
        except Exception as exc:
            self._last_error = f"{self._last_error}; legacy fallback failed: {exc}".strip("; ")
            return None

    def _release_legacy(self, instance_id: str, reason: str):
        if not self.allow_legacy_fallback:
            return
        try:
            from modules.publish.infrastructure.browser.browser_manager import get_browser_manager

            get_browser_manager().release(instance_id, reason)
        except Exception:
            pass


_ADAPTER = WorkbenchBrowserAdapter()


def get_workbench_browser_adapter() -> WorkbenchBrowserAdapter:
    return _ADAPTER

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ReachOps.workbench.page_state_detector import PageStateDetector
from ReachOps.workbench.tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor


class FakeDriver:
    def __init__(self, url="https://www.tiktok.com/@creator/video/1", title="TikTok", text="", buttons=None, modals=None):
        self.current_url = url
        self.title = title
        self.text = text
        self.buttons = buttons or []
        self.modals = modals or []
        self.page_source = f"<html><head><title>{title}</title></head><body>{text}</body></html>"

    def execute_script(self, script):
        if "document.body ? document.body.innerText" in script:
            return self.text
        if "visible_button_count" in script:
            return {"visible_button_count": len(self.buttons), "labels": self.buttons}
        if "visible_modal_count" in script:
            labels = [str(item).lower() for item in self.modals]
            joined = " ".join(labels)
            hard = any(token in joined for token in ["log in", "captcha", "verify", "登录", "验证"])
            soft = any(token in joined for token in ["not now", "maybe later", "allow", "close", "稍后", "允许", "关闭"])
            return {
                "visible_modal_count": len(labels),
                "labels": labels,
                "blocking_modal_visible": bool(hard or soft or labels),
                "blocking_modal_type": "hard_gate" if hard else ("dismissible_modal" if soft else ("unknown_modal" if labels else "none")),
                "dismissible_modal_visible": bool(soft),
                "close_candidates": ["not now", "close"] if labels else [],
            }
        if "document.documentElement ? document.documentElement.outerHTML" in script:
            return self.page_source
        return None

    def save_screenshot(self, path):
        Path(path).write_bytes(b"fake screenshot")
        return True


class PageStateDetectorTest(unittest.TestCase):
    def setUp(self):
        self.detector = PageStateDetector()

    def test_detects_ready_without_ai_token(self):
        state = self.detector.detect(FakeDriver(text="For you profile upload messages"))
        self.assertEqual(state["state"], "READY")
        self.assertTrue(state["no_ai_token_used"])
        self.assertEqual(state["schema_version"], "reachops.page_state.v1")

    def test_detects_login_required(self):
        state = self.detector.detect(FakeDriver(url="https://www.tiktok.com/login", text="Log in to continue"))
        self.assertEqual(state["state"], "LOGIN_REQUIRED")

    def test_detects_captcha_before_login(self):
        state = self.detector.detect(FakeDriver(text="Security check verify to continue captcha"))
        self.assertEqual(state["state"], "CAPTCHA_DETECTED")

    def test_detects_rate_limited(self):
        state = self.detector.detect(FakeDriver(text="Too many attempts. Try again later."))
        self.assertEqual(state["state"], "RATE_LIMITED")

    def test_detects_dismissible_modal_blocked(self):
        state = self.detector.detect(
            FakeDriver(
                text="For you profile upload messages",
                modals=["Allow notifications Not now"],
            )
        )
        self.assertEqual(state["state"], "MODAL_BLOCKED")
        self.assertEqual(state["modal_status"]["blocking_modal_type"], "dismissible_modal")
        self.assertTrue(state["modal_status"]["dismissible_modal_visible"])
        self.assertIn("blocking_modal_visible", state["signals"])

    def test_detects_comment_box_missing_when_action_requirements_enabled(self):
        state = self.detector.detect(
            FakeDriver(text="For you profile upload messages"),
            action_type="comment_reply",
            selector_counts={"comment_box_count": 0, "comment_submit_count": 0},
            include_action_requirements=True,
        )
        self.assertEqual(state["state"], "COMMENT_BOX_MISSING")

    def test_detects_submit_button_missing(self):
        state = self.detector.detect(
            FakeDriver(text="For you profile upload messages"),
            action_type="comment_reply",
            selector_counts={"comment_box_count": 1, "comment_submit_count": 0},
            include_action_requirements=True,
        )
        self.assertEqual(state["state"], "SUBMIT_BUTTON_MISSING")

    def test_detects_dom_stalled_from_previous_snapshot(self):
        driver = FakeDriver(text="For you profile upload messages")
        previous = self.detector.detect(driver)
        state = self.detector.detect(driver, previous_snapshot=previous)
        self.assertEqual(state["state"], "DOM_STALLED")

    def test_capture_state_bundle_writes_sidecar_and_screenshot_without_ai(self):
        with TemporaryDirectory() as td:
            bundle = self.detector.capture_state_bundle(
                FakeDriver(text="Security check verify to continue captcha"),
                td,
                prefix="captcha_action",
                metadata={"action_id": "action-1"},
                action_type="comment_reply",
                selector_counts={"comment_box_count": 0, "comment_submit_count": 0},
                include_action_requirements=True,
            )
            self.assertEqual(bundle["page_state"]["state"], "CAPTCHA_DETECTED")
            self.assertTrue(bundle["no_ai_token_used"])
            self.assertTrue(Path(bundle["sidecar_path"]).is_file())
            self.assertTrue(Path(bundle["screenshot"]["path"]).is_file())
            self.assertEqual(bundle["screenshot"]["sha256"], "dac9b8759818a663a62fcc26a9f5ed6a7e490f48f2b1b403d0e9721653fda2b9")
            self.assertIn("Security check", bundle["dom_summary"]["html_sample"])

    def test_executor_evidence_sidecar_contains_page_state(self):
        with TemporaryDirectory() as td:
            executor = TikTokSeleniumActionExecutor(TikTokActionExecutorConfig(evidence_dir=td, preflight_only=True))
            driver = FakeDriver(text="Security check verify to continue captcha")
            path = executor._capture_evidence(
                driver,
                {"id": "action-1", "action_type": "comment_reply", "target_url": "https://www.tiktok.com/@c/video/1"},
                "profile-1",
                code="CAPTCHA_DETECTED",
            )
            self.assertTrue(path)
            sidecar = Path(path + ".json")
            self.assertTrue(sidecar.is_file())
            data = __import__("json").loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(data["page_state"]["schema_version"], "reachops.page_state.v1")
            self.assertEqual(data["page_state"]["state"], "CAPTCHA_DETECTED")
            self.assertEqual(data["page_state_bundle"]["page_state"]["state"], "CAPTCHA_DETECTED")
            self.assertTrue(Path(data["page_state_bundle"]["sidecar_path"]).is_file())
            self.assertTrue(data["page_state_bundle"]["no_ai_token_used"])
            self.assertEqual(data["repair_decision"]["schema_version"], "reachops.repair_policy.v1")
            self.assertEqual(data["repair_decision"]["action"], "cooldown_profile_and_switch")
            self.assertTrue(data["repair_decision"]["evidence_bundle_required"])

    def test_unknown_page_state_evidence_sidecar_records_repair_and_offline_learning(self):
        with TemporaryDirectory() as td:
            executor = TikTokSeleniumActionExecutor(TikTokActionExecutorConfig(evidence_dir=td, preflight_only=True))
            driver = FakeDriver(text="Unexpected blank platform state with no known controls")
            path = executor._capture_evidence(
                driver,
                {"id": "action-unknown", "action_type": "comment_reply", "target_url": "https://www.tiktok.com/@c/video/1"},
                "profile-1",
                code="UNKNOWN_PAGE_STATE",
            )
            self.assertTrue(path)
            data = __import__("json").loads(Path(path + ".json").read_text(encoding="utf-8"))
            self.assertEqual(data["repair_decision"]["action"], "capture_unknown_state_bundle")
            self.assertTrue(data["repair_decision"]["block_execution"])
            self.assertIn("record_offline_learning_candidate", [row["step"] for row in data["repair_decision"]["executable_steps"]])
            self.assertEqual(data["offline_learning"]["schema_version"], "reachops.offline_learning.v1")
            self.assertTrue(data["offline_learning"]["signature"])
            self.assertGreaterEqual(data["offline_learning"]["occurrence_count"], 1)
            self.assertTrue(data["offline_learning"]["no_ai_token_used"])
            self.assertTrue(Path(data["page_state_bundle"]["sidecar_path"]).is_file())

    def test_executor_failed_modal_state_includes_browser_repair_step(self):
        class ModalBlockedDriver(FakeDriver):
            def __init__(self):
                super().__init__(
                    text="For you profile upload messages",
                    modals=["Allow notifications Not now"],
                )

            def get(self, url):
                self.current_url = url

            def execute_script(self, script):
                if "const dismissLabels" in script:
                    return {"dismissed": 1, "label": "not now"}
                return super().execute_script(script)

        executor = TikTokSeleniumActionExecutor(TikTokActionExecutorConfig(preflight_only=True, popup_dismiss_attempts=1))
        result = executor._execute_with_driver(
            ModalBlockedDriver(),
            {"id": "action-1", "action_type": "comment_reply", "target_url": "https://www.tiktok.com/@c/video/1"},
            "hello",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "MODAL_BLOCKED")
        self.assertEqual(result["repair_step_results"][0]["step"], "dismiss_modal")
        self.assertEqual(result["repair_step_results"][0]["status"], "executed_by_browser_executor")
        self.assertEqual(result["repair_step_results"][0]["dismissed"], 1)
        self.assertTrue(result["repair_step_results"][0]["no_ai_token_used"])

    def test_executor_page_timeout_records_refresh_repair_step(self):
        class TimeoutDriver(FakeDriver):
            def __init__(self):
                super().__init__(text="This page couldn't load because of a network issue.")
                self.refresh_count = 0

            def get(self, url):
                self.current_url = url

            def refresh(self):
                self.refresh_count += 1

        driver = TimeoutDriver()
        executor = TikTokSeleniumActionExecutor(TikTokActionExecutorConfig(preflight_only=True, popup_dismiss_attempts=1))
        result = executor._execute_with_driver(
            driver,
            {"id": "action-1", "action_type": "comment_reply", "target_url": "https://www.tiktok.com/@c/video/1"},
            "hello",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "PAGE_TIMEOUT")
        by_step = {row["step"]: row for row in result["repair_step_results"]}
        self.assertEqual(by_step["refresh_page"]["status"], "executed_by_browser_executor")
        self.assertEqual(by_step["refresh_page"]["method"], "driver.refresh")
        self.assertEqual(driver.refresh_count, 1)
        self.assertTrue(all(row["no_ai_token_used"] for row in result["repair_step_results"]))

    def test_executor_detects_dom_stalled_from_target_history(self):
        executor = TikTokSeleniumActionExecutor(TikTokActionExecutorConfig(preflight_only=True, popup_dismiss_attempts=1))
        driver = FakeDriver(text="For you profile upload messages")
        self.assertEqual(executor._detect_page_state(driver, state_key="comment_reply:https://www.tiktok.com/@c/video/1"), "")
        self.assertEqual(
            executor._detect_page_state(driver, state_key="comment_reply:https://www.tiktok.com/@c/video/1"),
            "DOM_STALLED",
        )

    def test_executor_returns_action_requirement_page_states_when_enabled(self):
        executor = TikTokSeleniumActionExecutor(TikTokActionExecutorConfig(preflight_only=True))
        driver = FakeDriver(text="For you profile upload messages")
        executor._page_selector_counts = lambda _driver: {"comment_box_count": 0, "comment_submit_count": 0}
        self.assertEqual(
            executor._detect_page_state(driver, action_type="comment_reply", include_action_requirements=True),
            "COMMENT_BOX_MISSING",
        )
        executor._page_selector_counts = lambda _driver: {"comment_box_count": 1, "comment_submit_count": 0}
        self.assertEqual(
            executor._detect_page_state(driver, action_type="comment_reply", include_action_requirements=True),
            "SUBMIT_BUTTON_MISSING",
        )


if __name__ == "__main__":
    unittest.main()

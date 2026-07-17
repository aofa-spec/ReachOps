from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ReachOps.intelligence.schemas import ActionQueueItem
from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.workbench.action_router import ActionRouter, ActionRouterConfig, FixtureActionExecutor


class FakeTemplateManager:
    def normalize_action_type(self, action_type: str) -> str:
        return str(action_type or "")

    def render(self, action: dict, profile: dict | None = None):
        return SimpleNamespace(rendered_text="truthful test message")


class FakeHealthManager:
    def rank_profiles(self, profiles, group_name: str = "", max_count: int = 100):
        return list(profiles or [])[:max_count]

    def record_failure(self, profile, error_code: str, error_message: str):
        return {
            "profile_id": str(profile.get("profile_id") or profile.get("id") or ""),
            "status": "cooldown" if error_code in {"CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"} else "degraded",
            "last_error_code": error_code,
            "last_error_message": error_message,
        }

    def record_success(self, profile):
        return {
            "profile_id": str(profile.get("profile_id") or profile.get("id") or ""),
            "status": "healthy",
        }


class FakeAuthorizationGate:
    def authorize_live_submit(self, action, profile, feature: str = "live_submit"):
        return {"allowed": True, "feature": feature}


class AlwaysSuccessExecutor:
    def __init__(self, evidence_path: str = ""):
        self.evidence_path = evidence_path
        self.calls = 0

    def execute(self, action, profile, rendered_text: str, dry_run: bool = True):
        self.calls += 1
        return {
            "status": "success",
            "error_code": "",
            "error_message": "",
            "evidence_path": self.evidence_path,
        }


class CaptchaExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, action, profile, rendered_text: str, dry_run: bool = True):
        self.calls += 1
        return {
            "status": "failed",
            "error_code": "CAPTCHA_DETECTED",
            "error_message": "captcha gate",
            "evidence_path": "",
            "page_diagnostics": {"page_state": {"state": "CAPTCHA_DETECTED"}},
        }


class TruthfulExecutionSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.storage = GrowthStorage(str(self.base / "runtime" / "growth.sqlite3"))
        self.profile_a = {"profile_id": "1001", "group_name": "United States"}
        self.profile_b = {"profile_id": "1002", "group_name": "United States"}

    def add_action(self, action_id: str = "action-1") -> dict:
        item = ActionQueueItem(
            id=action_id,
            lead_id=f"lead-{action_id}",
            action_type="comment_reply",
            target_username="buyer",
            target_url="https://www.tiktok.com/@creator/video/123",
            suggested_text="truthful test message",
            status="approved",
            risk_level="medium",
        )
        self.storage.upsert_action_queue_item(item)
        return next(row for row in self.storage.list_action_queue(limit=50) if row["id"] == action_id)

    def router(self, executor) -> ActionRouter:
        return ActionRouter(
            self.storage,
            executor=executor,
            template_manager=FakeTemplateManager(),
            health_manager=FakeHealthManager(),
            authorization_gate=FakeAuthorizationGate(),
        )

    def test_live_mode_rejects_fixture_executor(self):
        self.add_action()
        router = self.router(FixtureActionExecutor([{"status": "success"}]))
        config = ActionRouterConfig(
            max_workers=1,
            dry_run=False,
            allow_live_submit=True,
            require_authorization=False,
            require_action_review=False,
        )
        with self.assertRaisesRegex(RuntimeError, "LIVE_EXECUTOR_REQUIRED"):
            router.run([self.profile_a], config=config, limit=1)

    def test_simulated_success_does_not_count_as_live_or_contacted(self):
        action = self.add_action()
        router = self.router(FixtureActionExecutor([{"status": "success"}]))
        summary = router.run(
            [self.profile_a],
            config=ActionRouterConfig(max_workers=1, dry_run=True, auto_approve=False),
            limit=1,
        )
        self.assertEqual(summary["success"], 1)
        execution = self.storage.list_outreach_executions(limit=1)[0]
        self.assertEqual(execution["execution_mode"], "simulated")
        self.assertEqual(execution["submission_state"], "not_attempted")
        self.assertEqual(execution["verification_state"], "not_required")
        self.assertEqual(int(execution["evidence_verified"]), 0)
        truth = self.storage.outreach_execution_truth_counts()
        self.assertEqual(truth["simulated_success"], 1)
        self.assertEqual(truth["live_verified"], 0)
        saved_action = next(row for row in self.storage.list_action_queue(limit=50) if row["id"] == action["id"])
        self.assertNotIn(saved_action["status"], {"success", "completed"})

    def test_preflight_success_is_not_live_success(self):
        action = self.add_action()
        executor = AlwaysSuccessExecutor()
        router = self.router(executor)
        router.run(
            [self.profile_a],
            config=ActionRouterConfig(
                max_workers=1,
                dry_run=False,
                live_preflight_only=True,
                require_authorization=False,
            ),
            limit=1,
        )
        execution = self.storage.list_outreach_executions(limit=1)[0]
        self.assertEqual(execution["execution_mode"], "preflight")
        self.assertEqual(execution["submission_state"], "prepared")
        truth = self.storage.outreach_execution_truth_counts()
        self.assertEqual(truth["preflight_passed"], 1)
        self.assertEqual(truth["live_verified"], 0)
        saved_action = next(row for row in self.storage.list_action_queue(limit=50) if row["id"] == action["id"])
        self.assertNotIn(saved_action["status"], {"success", "completed"})

    def test_captcha_opens_run_circuit_breaker_without_switching_profile(self):
        self.add_action()
        executor = CaptchaExecutor()
        router = self.router(executor)
        summary = router.run(
            [self.profile_a, self.profile_b],
            config=ActionRouterConfig(
                max_workers=1,
                max_switch_attempts=2,
                dry_run=False,
                allow_live_submit=True,
                require_authorization=False,
                require_execution_evidence=False,
            ),
            limit=1,
        )
        self.assertEqual(executor.calls, 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["account_switched"], 0)
        events = self.storage.list_recent_events(event="action_router_run_circuit_breaker", limit=10)
        self.assertEqual(len(events), 1)

    def test_verified_live_success_requires_action_specific_evidence(self):
        action = self.add_action()
        screenshot = self.base / "live-comment.png"
        screenshot.write_bytes(b"verified-image-bytes")
        sidecar = {
            "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
            "action_type": "comment_reply",
            "submitted_text": "truthful test message",
            "comment_visible_confirmed": True,
        }
        Path(f"{screenshot}.json").write_text(json.dumps(sidecar), encoding="utf-8")
        executor = AlwaysSuccessExecutor(str(screenshot))
        router = self.router(executor)
        result = router.run(
            [self.profile_a],
            config=ActionRouterConfig(
                max_workers=1,
                dry_run=False,
                allow_live_submit=True,
                require_authorization=False,
                require_execution_evidence=True,
                require_local_evidence_file=True,
            ),
            limit=1,
        )
        self.assertEqual(result["success"], 1)
        execution = self.storage.list_outreach_executions(limit=1)[0]
        self.assertEqual(execution["execution_mode"], "live")
        self.assertEqual(execution["submission_state"], "verified_success")
        self.assertEqual(execution["verification_state"], "verified")
        self.assertEqual(int(execution["evidence_verified"]), 1)
        truth = self.storage.outreach_execution_truth_counts()
        self.assertEqual(truth["live_submitted"], 1)
        self.assertEqual(truth["live_verified"], 1)
        saved_action = next(row for row in self.storage.list_action_queue(limit=50) if row["id"] == action["id"])
        self.assertIn(saved_action["status"], {"success", "completed"})


if __name__ == "__main__":
    unittest.main()

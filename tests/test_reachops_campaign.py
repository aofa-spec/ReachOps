import csv
import hashlib
import json
import os
import tempfile
import time
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ReachOps.adapters.browser_manager import WorkbenchBrowserAdapter
from ReachOps.adapters.ix_profile_group_manager import IxProfileGroupManager, ProfileGroupMoveResult
from ReachOps import PRODUCT_ID, PRODUCT_NAME, VERSION, ReachOpsUpdateManager, version_info
from ReachOps.intelligence import GrowthIntelligenceService, GrowthTaskConfig
from ReachOps.intelligence.ai_strategy import HTTPAcquisitionIntelligenceProvider
from ReachOps.intelligence.candidate_user_scorer import CandidateUserScorer
from ReachOps.intelligence.comment_intent import CommentIntentResult, RuleBasedCommentIntentClassifier
from ReachOps.intelligence.outreach_copy import OutreachCopySuggestion
from ReachOps.intelligence.schemas import CampaignFunnel
from ReachOps.intelligence.source_planner import CampaignAnalyzer
from ReachOps.runtime_paths import RuntimePaths
from ReachOps.workbench.action_router import ActionRouterConfig
from ReachOps.workbench.action_router import FixtureActionExecutor
from ReachOps.workbench.profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig
from ReachOps.workbench.console import GrowthOpsConsole, format_campaign_plan_summary
from ReachOps.workbench.standalone_app import GrowthIntelligenceStandaloneApp, group_display_name, stable_combobox_values
from ReachOps.workbench.tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor
from ReachOps.workbench.workflow_service import GrowthWorkflowService
from tools.reachops_action_preflight_existing_batch import run_preflight as run_reachops_action_preflight_existing_batch
from ReachOps.collectors.normalizer import is_comment_noise_text
from ReachOps.collectors.collector_runtime import CollectorRuntime
from ReachOps.collectors.base import CollectorEvidence
from ReachOps.collectors.tiktok_comment_collector import TikTokCommentCollector
from ReachOps.collectors.tiktok_search_collector import TikTokSearchCollector
from ReachOps.collectors.tiktok_topic_content_collector import TikTokTopicContentCollector
from tools.reachops_delivery_audit import run_audit as run_reachops_delivery_audit
from tools.reachops_goal_status_report import build_goal_status_report
from tools.reachops_operator_pressure import run_pressure as run_reachops_operator_pressure
from tools.reachops_visual_collection_preflight import build_operator_diagnosis as visual_preflight_operator_diagnosis
from tools.reachops_visual_collection_preflight import source_from_plan as visual_preflight_source_from_plan
from tools.reachops_live_validation_manifest import build_manifest as build_reachops_live_validation_manifest
from tools.reachops_live_validation_manifest import load_profile_snapshot as load_reachops_profile_snapshot
from tools.reachops_live_preflight import run_preflight as run_reachops_live_preflight
from tools.reachops_live_readiness import run_readiness as run_reachops_live_readiness
from tools.reachops_live_submit_acceptance import run_acceptance as run_reachops_live_submit_acceptance
from tools.verify_reachops_acceptance_summary import verify_summary as verify_reachops_acceptance_summary
from tools.reachops_delivery_package_check import check_delivery_package as check_reachops_delivery_package
from tools.write_reachops_update_manifest import build_manifest


class FakeDriver:
    def __init__(self):
        self.current_url = ""
        self.title = ""
        self.visited = []
        self.quit_called = False
        self.script_results = []

    def get(self, url):
        self.current_url = url
        self.visited.append(url)

    def execute_script(self, _script):
        if self.script_results:
            return self.script_results.pop(0)
        return ""

    def quit(self):
        self.quit_called = True


class FakeBrowserDriverAdapter:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.last_error = ""
        self.driver = FakeDriver()
        self.client = object()
        self.closed = []

    def create_driver(self, profile_id):
        if self.fail:
            self.last_error = f"failed profile {profile_id}"
            return None, None
        return self.driver, self.client

    def close_profile(self, client, profile_id):
        self.closed.append((client, profile_id))


class FakeReleaseManager:
    def __init__(self):
        self.released = []

    def release(self, instance_id, reason):
        self.released.append((instance_id, reason))


class FakeProfilePreflightDriver:
    current_url = ""
    title = "TikTok"

    def __init__(self, body_text: str = "Messages Inbox Profile", fail_open: bool = False):
        self.body_text = body_text
        self.fail_open = fail_open
        self.visited = []
        self.timeout = None
        self.script_results = []

    def set_page_load_timeout(self, seconds):
        self.timeout = seconds

    def get(self, url):
        if self.fail_open:
            raise TimeoutError("proxy timeout")
        self.current_url = url
        self.visited.append(url)

    def execute_script(self, script, *args):
        if self.script_results and (
            "const text = (document.body ? document.body.innerText" in script
            or "const text = String(document.body ? document.body.innerText" in script
        ):
            return self.script_results.pop(0)
        if "return document.body ? document.body.innerText" in script:
            return self.body_text
        if "const text = (document.body ? document.body.innerText" in script:
            text = self.body_text.lower()
            return {
                "url": self.current_url,
                "loginGate": "log in to continue" in text or "sign up" in text,
                "loggedIn": any(token in text for token in ["messages", "inbox", "profile", "upload"]),
                "labels": [],
                "sample": self.body_text,
            }
        return None

    def find_elements(self, _by, _selector):
        return []


class BlockingProfilePreflightDriver(FakeProfilePreflightDriver):
    def __init__(self, block_seconds: float = 0.4):
        super().__init__("For You")
        self.block_seconds = block_seconds

    def get(self, url):
        time.sleep(self.block_seconds)
        super().get(url)


class FakeProfileGroupManager:
    def __init__(self):
        self.moves = []

    def move_profile_to_quarantine(self, profile_id: str, reason: str = ""):
        self.moves.append((str(profile_id), str(reason)))
        return ProfileGroupMoveResult(True, str(profile_id), "999", "封禁账号")


class FakeIxProfileClient:
    def __init__(self, groups=None, create_response=None, move_response=True):
        self.groups = list(groups or [])
        self.create_response = create_response if create_response is not None else {"data": {"id": 999}}
        self.move_response = move_response
        self.created = []
        self.moves = []
        self.total = len(self.groups)

    def get_group_list(self, page=1, limit=100):
        start = (int(page) - 1) * int(limit)
        return self.groups[start : start + int(limit)]

    def create_group(self, title, sort=0):
        self.created.append((title, sort))
        return self.create_response

    def update_profile_groups_in_batches(self, profile_id, group_id):
        self.moves.append((profile_id, group_id))
        return self.move_response


class FakeAcquisitionIntelligenceProvider:
    name = "fake_ai_provider"

    def __init__(self):
        self.calls = []

    def analyze(self, campaign, intent_keywords=None, exclude_keywords=None):
        self.calls.append(
            {
                "input_type": campaign.input_type,
                "input_value": campaign.input_value,
                "intent_keywords": list(intent_keywords or []),
                "exclude_keywords": list(exclude_keywords or []),
            }
        )
        return {
            "provider": self.name,
            "mode": "test_ai",
            "product_analysis": {
                "category": "digital_content",
                "product_name": "Episode Finder",
                "customer_problem": "Users need the episode source.",
                "primary_offer": "Give the app name and viewing path.",
                "keywords": ["episode finder", "watch", "app"],
            },
            "audience_profile": {
                "persona": "viewer asking for episode links",
                "interests": ["short drama"],
                "pain_points": ["missing episode"],
                "buying_triggers": ["where to watch"],
            },
            "intent_taxonomy": [
                {"intent_type": "purchase", "keywords": ["watch", "app", "episode"], "score_hint": 82},
                {"intent_type": "consult", "keywords": ["name", "where"], "score_hint": 65},
                {"intent_type": "exclude", "keywords": ["spoiler"], "score_hint": 0},
            ],
            "source_suggestions": [
                {"source_type": "keyword", "source_value": "episode finder app", "reason": "ai source", "priority": 95},
                {"source_type": "hashtag", "source_value": "shortdrama", "reason": "ai hashtag", "priority": 88},
            ],
            "outreach_recommendations": [
                {"action_type": "comment_reply", "priority": 1, "template_angle": "answer episode source", "risk_level": "medium"}
            ],
        }


class FakeCommentIntentClassifier:
    name = "fake_comment_ai"

    def __init__(self):
        self.calls = []

    def classify(self, row, custom_intent_keywords=None, exclude_keywords=None):
        self.calls.append(str(row.get("username") or ""))
        text = str(row.get("comment_text") or "").lower()
        if "ignore" in text:
            return CommentIntentResult(
                intent_type="exclude",
                confidence=0.99,
                tags=["ai_exclude", "intent_ai:fake_comment_ai"],
                score_delta=-100,
                excluded=True,
                provider=self.name,
            )
        return CommentIntentResult(
            intent_type="purchase",
            confidence=0.91,
            matched_keywords=["buy_signal"],
            tags=["ai_purchase", "intent_ai:fake_comment_ai"],
            score_delta=52,
            provider=self.name,
        )


class FakeOutreachCopyRecommender:
    name = "fake_copy_ai"

    def __init__(self):
        self.calls = []

    def recommend(self, action_type, row, lead_type, priority, config=None):
        self.calls.append((action_type, str(row.get("username") or ""), lead_type, priority))
        return OutreachCopySuggestion(
            action_type=action_type,
            text=f"{action_type} AI copy for {row.get('username')} / {lead_type}",
            angle="fake ai angle",
            provider=self.name,
            risk_note="test",
        )


class StaticProfileCollector:
    def collect(self, driver, task, context):
        username = driver.current_url.rstrip("/").split("/")[-1].lstrip("@") or "creator"
        return {
            "username": username,
            "profile_url": driver.current_url,
            "followers": 12000,
            "likes_total": 560000,
        }


class StaticVideoCollector:
    def collect(self, driver, task, context):
        username = task["creator"]["username"]
        return [
            {
                "video_id": f"{username}-video-1",
                "video_url": f"https://www.tiktok.com/@{username}/video/1",
                "caption": "best lip serum where can I buy",
                "views": 120000,
                "likes": 3000,
                "comments": 1000,
                "shares": 25,
            }
        ]


class EmptyVideoCollector:
    def collect(self, driver, task, context):
        return []


class StaticCommentCollector:
    def collect(self, driver, task, context):
        return [
            {
                "username": "buyer_one",
                "profile_url": "https://www.tiktok.com/@buyer_one",
                "comment_text": "where can I buy this serum link please",
                "comment_likes": 12,
                "reply_count": 2,
            }
        ]


class FirstAttemptCommentAccessGatedCollector:
    level = "selenium_dom"

    def __init__(self):
        self.calls = 0
        self.last_diagnostics = {}

    def collect(self, driver, task, context):
        self.calls += 1
        if self.calls == 1:
            self.last_diagnostics = {
                "page_state": "login_required",
                "error_code": "LOGIN_REQUIRED",
                "login_prompt_detected": True,
                "comment_panel_seen": False,
                "max_visible_nodes": 0,
            }
            return []
        self.last_diagnostics = {"page_state": "normal", "error_code": ""}
        return StaticCommentCollector().collect(driver, task, context)


class EmptyDiagnosticCollector:
    level = "selenium_dom"
    last_diagnostics = {
        "page_state": "empty_comments",
        "error_code": "COMMENT_SCAN_EMPTY",
        "comment_open_attempts": 6,
        "comment_open_clicks": 4,
        "comment_panel_seen": False,
    }

    def collect(self, driver, task, context):
        return []


class EmptyFallbackCollector:
    level = "cdp_network"

    def collect(self, driver, task, context):
        return []


class MismatchedUrlCommentCollector:
    level = "selenium_dom"

    def collect(self, driver, task, context):
        return [
            {
                "username": "wrong_video_user",
                "profile_url": "https://www.tiktok.com/@wrong_video_user",
                "comment_text": "where can I buy this",
                "comment_likes": 1,
                "reply_count": 0,
            }
        ]

    def evidence(self, driver, item_count=0, raw_sample=""):
        return CollectorEvidence(
            level=self.level,
            final_url="https://www.tiktok.com/@other_creator/video/999",
            item_count=item_count,
            raw_sample=raw_sample,
            adapter_name=self.__class__.__name__,
        )


class ScriptedCommentDriver:
    current_url = "https://www.tiktok.com/@creator/video/123"

    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute_script(self, script):
        self.calls += 1
        if "return document.body ? document.body.innerText.length" in script:
            return 1000
        if "const text = (document.body && document.body.innerText" in script:
            return {
                "url": self.current_url,
                "commentNodes": len(self.rows),
                "loginPrompt": False,
                "loginDialog": False,
                "captcha": False,
                "proxy": False,
                "emptyHint": False,
                "containers": 1,
            }
        if "candidateLinks" in script:
            return list(self.rows)
        return len(self.rows)


class EmptyTopicContentCollector:
    def collect(self, driver, task, context):
        return []


class StaticSearchCollector:
    def collect(self, driver, task, context):
        return [
            {
                "commerce": {},
                "content": {
                    "creator_username": "search_creator",
                    "video_id": "123",
                    "video_url": "https://www.tiktok.com/@search_creator/video/123",
                    "caption": "anti aging serum review where to buy",
                    "views": 1200,
                    "comments": 10,
                },
            }
        ]


class MixedTopicContentCollector:
    def collect(self, driver, task, context):
        return [
            {
                "commerce": {},
                "content": {
                    "creator_username": "beauty_creator",
                    "video_id": "serum-1",
                    "video_url": "https://www.tiktok.com/@beauty_creator/video/serum-1",
                    "caption": "anti aging serum routine where to buy",
                    "views": 12000,
                    "comments": 120,
                },
            },
            {
                "commerce": {},
                "content": {
                    "creator_username": "finance_creator",
                    "video_id": "forex-1",
                    "video_url": "https://www.tiktok.com/@finance_creator/video/forex-1",
                    "caption": "forex trading setup and investment signal",
                    "views": 18000,
                    "comments": 200,
                },
            },
        ]


class SecondAttemptSearchCollector:
    def __init__(self):
        self.calls = 0

    def collect(self, driver, task, context):
        self.calls += 1
        if self.calls == 1:
            return []
        return StaticSearchCollector().collect(driver, task, context)


def make_reachops_service(base_dir):
    return GrowthIntelligenceService(
        base_dir=base_dir,
        browser_factory=lambda _profile_id: FakeDriver(),
        collectors={
            "profile": StaticProfileCollector(),
            "video": StaticVideoCollector(),
            "comment": StaticCommentCollector(),
            "search": object(),
        },
    )


class ReachOpsCampaignTests(unittest.TestCase):
    def test_reachops_version_info_is_standalone_product_metadata(self):
        info = version_info()

        self.assertEqual(PRODUCT_ID, "reachops")
        self.assertEqual(PRODUCT_NAME, "ReachOps")
        self.assertEqual(info["version"], VERSION)
        self.assertEqual(info["channel"], "mvp")

    def test_reachops_update_manifest_contains_hash_and_preserve_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "ReachOps-Setup.exe"
            installer.write_bytes(b"reachops-installer")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()

            manifest = build_manifest(installer, version="0.4.0", build="7", channel="mvp", download_url="https://example.test/ReachOps-Setup.exe")

            self.assertEqual(manifest["product_id"], "reachops")
            self.assertEqual(manifest["version"], "0.4.0")
            self.assertEqual(manifest["build"], "7")
            self.assertEqual(manifest["installer"]["sha256"], digest)
            self.assertEqual(manifest["installer"]["size_bytes"], len(b"reachops-installer"))
            self.assertTrue(manifest["runtime_policy"]["preserve_activation_status"])
            self.assertTrue(manifest["runtime_policy"]["preserve_data"])

    def test_reachops_update_manager_validates_manifest_hash_and_install_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            installer = tmp_path / "ReachOps-Setup.exe"
            installer.write_bytes(b"reachops-update")
            manifest = build_manifest(installer, version="0.5.0", build="3", channel="mvp")
            manifest_path = tmp_path / "reachops-update-manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            manager = ReachOpsUpdateManager(current_version="0.4.0", install_dir=str(tmp_path / "ReachOps"))
            loaded = manager.load_manifest(manifest_path)
            update = manager.check_manifest(loaded)

            self.assertTrue(update.available)
            self.assertEqual(update.latest_version, "0.5.0")
            self.assertTrue(manager.verify_installer(installer, loaded))
            args = manager.silent_install_args(installer)
            self.assertEqual(args[0], str(installer))
            self.assertIn("/VERYSILENT", args)
            self.assertIn("/SUPPRESSMSGBOXES", args)
            self.assertIn(f'/DIR="{tmp_path / "ReachOps"}"', args)
            self.assertEqual(manager.compare_versions("0.5.0", "0.5.0"), 0)
            self.assertEqual(manager.compare_versions("0.5.1", "0.5.0"), 1)
            self.assertEqual(manager.compare_versions("0.4.9", "0.5.0"), -1)

    def test_reachops_delivery_audit_reports_local_passes_and_external_pending(self):
        class Args:
            target = "anti aging serum"
            base_dir = ""

        result = run_reachops_delivery_audit(Args())

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["summary"]["passed"], 10)
        self.assertGreaterEqual(result["summary"]["pending_external_validation"], 1)
        self.assertEqual(result["summary"]["failed"], 0)
        checks = {row["name"]: row for row in result["checks"]}
        self.assertEqual(checks["升级清单和安装校验机制可用"]["status"], "passed")
        self.assertTrue(checks["升级清单和安装校验机制可用"]["evidence"]["hash_ok"])
        self.assertEqual(checks["授权门覆盖设备绑定、过期和能力限制"]["status"], "passed")
        self.assertEqual(checks["授权门覆盖设备绑定、过期和能力限制"]["evidence"]["expired"]["error_code"], "LIVE_SUBMIT_LICENSE_EXPIRED")
        self.assertEqual(checks["真实执行成功必须有有效证据"]["status"], "passed")
        self.assertGreaterEqual(
            checks["真实执行成功必须有有效证据"]["evidence"]["result"]["errors"]["LIVE_SUBMIT_EVIDENCE_MISSING"],
            1,
        )

    def test_reachops_operator_pressure_runs_multi_campaign_funnel_and_action_routing(self):
        class Args:
            base_dir = ""
            targets = ["anti aging serum", "https://www.tiktok.com/@beauty_creator", "#makeupfinds"]
            profile_group = "US"
            max_campaigns = 3
            max_sources_per_campaign = 1
            max_videos = 5
            max_comments = 10
            min_views = 0
            min_comments = 0
            collect_profile_count = 3
            execute_profile_count = 3
            workers = 2
            per_profile_limit = 10
            switch_attempts = 2
            action_limit = 18
            per_profile_hour_limit = 20
            per_profile_video_hour_limit = 99
            task_delay_seconds = 30
            intent_keywords = ["where", "link", "buy", "price", "download", "app", "coupon"]
            exclude_keywords = ["spam", "bot", "haha", "lol"]
            allow_fail = False

        result = run_reachops_operator_pressure(Args())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["campaign_count"], 3)
        self.assertGreaterEqual(result["summary"]["content_found"], 3)
        self.assertGreaterEqual(result["summary"]["comment_users"], 3)
        self.assertGreaterEqual(result["summary"]["customer_leads"], 3)
        self.assertGreaterEqual(result["summary"]["outreach_actions"], 3)
        self.assertEqual(result["summary"]["workers"], 2)
        self.assertGreaterEqual(result["summary"]["execution_success"], 1)
        self.assertGreaterEqual(result["summary"]["account_switched"], 1)
        routed_results = result["fallback_action_result"]["results"] + result["action_result"]["results"]
        action_types = [row.get("action_type") for row in routed_results]
        statuses = [row.get("status") for row in routed_results]
        self.assertIn("dm_review", action_types)
        self.assertIn("comment_reply", action_types)
        self.assertIn("account_switched", statuses)
        self.assertTrue(Path(result["report_path"]).exists())

    def test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures(self):
        base_summary = {
            "status": "ready_for_external_validation",
            "delivery_audit": {
                "status": "ok",
                "passed": 24,
                "pending_external_validation": 1,
                "resolved_external_validation": 0,
                "effective_pending_external_validation": 1,
                "failed": 0,
            },
            "operator_pressure": {
                "status": "ok",
                "campaign_count": 3,
                "content_found": 15,
                "comment_users": 27,
                "customer_leads": 27,
                "outreach_actions": 81,
                "execution_success": 9,
                "account_switched": 6,
            },
            "installer_smoke": {
                "status": "ok",
                "exe_exists": True,
                "data_in_install_dir": False,
                "hash_ok": True,
            },
            "ui_startup": {
                "status": "ok",
                "process_running": True,
                "interactive_task": True,
            },
            "live_validation": {
                "status": "blocked",
                "no_browser_started": True,
                "no_submit": True,
                "missing_inputs": ["真实 TikTok 平台提交"],
                "selected_profile_ids": [],
            },
            "live_readiness": {"status": "skipped", "ready": False, "no_browser_started": True, "no_submit": True},
            "live_preflight": {"status": "skipped"},
            "live_submit": {"status": "skipped"},
            "goal_status": {
                "status": "ready_for_external_validation",
                "summary": {"stages_passed": 4, "stages_pending_external_validation": 1, "stages_failed": 0},
                "pending_external_validation": ["授权允许时能真实执行", "真实 TikTok 平台提交"],
            },
        }

        pending = verify_reachops_acceptance_summary(base_summary)
        self.assertFalse(pending["passed"])
        self.assertIn("external_platform_validation", pending["pending"])

        allowed = verify_reachops_acceptance_summary(base_summary, allow_external_pending=True)
        self.assertTrue(allowed["passed"])
        self.assertEqual(allowed["live_readiness"]["status"], "skipped")
        self.assertEqual(allowed["live_validation"]["status"], "blocked")
        self.assertTrue(allowed["live_validation"]["no_browser_started"])
        self.assertTrue(allowed["live_validation"]["no_submit"])
        self.assertTrue(allowed["live_readiness"]["no_browser_started"])
        self.assertEqual(allowed["goal_status"]["status"], "ready_for_external_validation")
        self.assertIn("授权允许时能真实执行", allowed["goal_status"]["pending_external_validation"])
        self.assertIn("真实 TikTok 平台提交", allowed["goal_status"]["pending_external_validation"])
        self.assertEqual(allowed["operator_pressure"]["campaign_count"], 3)

        failed_pressure_summary = json.loads(json.dumps(base_summary))
        failed_pressure_summary["operator_pressure"]["account_switched"] = 0
        failed_pressure = verify_reachops_acceptance_summary(failed_pressure_summary, allow_external_pending=True)
        self.assertFalse(failed_pressure["passed"])
        self.assertIn("operator_pressure_failed", failed_pressure["failures"])

        failed_summary = json.loads(json.dumps(base_summary))
        failed_summary["installer_smoke"]["hash_ok"] = False
        failed = verify_reachops_acceptance_summary(failed_summary, allow_external_pending=True)
        self.assertFalse(failed["passed"])
        self.assertIn("installer_smoke_failed", failed["failures"])

        optional_installer_summary = json.loads(json.dumps(base_summary))
        optional_installer_summary["installer_smoke"] = {
            "status": "skipped_optional",
            "optional": True,
            "exe_exists": False,
            "data_in_install_dir": False,
            "hash_ok": False,
        }
        optional_installer = verify_reachops_acceptance_summary(optional_installer_summary, allow_external_pending=True)
        self.assertTrue(optional_installer["passed"])
        self.assertEqual(optional_installer["installer_smoke"]["status"], "skipped_optional")

        failed_ui_summary = json.loads(json.dumps(base_summary))
        failed_ui_summary["ui_startup"]["process_running"] = False
        failed_ui = verify_reachops_acceptance_summary(failed_ui_summary, allow_external_pending=True)
        self.assertFalse(failed_ui["passed"])
        self.assertIn("ui_startup_failed", failed_ui["failures"])

        passed_summary = json.loads(json.dumps(base_summary))
        passed_summary["status"] = "passed"
        passed_summary["delivery_audit"]["resolved_external_validation"] = 1
        passed_summary["delivery_audit"]["effective_pending_external_validation"] = 0
        passed_summary["goal_status"] = {
            "status": "passed",
            "summary": {"stages_passed": 5, "stages_pending_external_validation": 0, "stages_failed": 0},
            "pending_external_validation": [],
        }
        png_sha = hashlib.sha256(b"png").hexdigest()
        def sidecar(action_type):
            return {
                "screenshot_sha256": png_sha,
                "action_type": action_type,
                "profile_id": "profile-a",
                "action_id": f"{action_type}-1",
                "current_url": "https://www.tiktok.com/@creator/video/123",
            }
        passed_summary["live_submit"] = {
            "status": "completed",
            "executor_mode": "platform_selenium",
            "platform_validation": True,
            "activation_status_loaded": True,
            "activation_status_source": "C:/Users/aofa/AppData/Local/ReachOps/config/reachops_activation_status.json",
            "activation_status_path": "reports/reachops_acceptance/live_submit/config/reachops_activation_status.json",
            "evidence_by_action_type": {
                "comment_reply": ["evidence://submit/comment"],
                "follow_review": ["evidence://submit/follow"],
                "dm_review": ["evidence://submit/dm"],
            },
            "evidence_file_details": {
                "comment_reply": [{"path": "C:/evidence/comment.png", "size": 3, "sha256": png_sha, "sidecar_path": "C:/evidence/comment.png.json", "sidecar": sidecar("comment_reply")}],
                "follow_review": [{"path": "C:/evidence/follow.png", "size": 3, "sha256": png_sha, "sidecar_path": "C:/evidence/follow.png.json", "sidecar": sidecar("follow_review")}],
                "dm_review": [{"path": "C:/evidence/dm.png", "size": 3, "sha256": png_sha, "sidecar_path": "C:/evidence/dm.png.json", "sidecar": sidecar("dm_review")}],
            },
            "missing_evidence_action_types": [],
            "missing_local_evidence_file_action_types": [],
        }
        passed = verify_reachops_acceptance_summary(passed_summary)
        self.assertTrue(passed["passed"])
        self.assertEqual(passed["delivery_audit"]["pending_external_validation"], 1)
        self.assertEqual(passed["delivery_audit"]["effective_pending_external_validation"], 0)
        self.assertEqual(passed["goal_status"]["status"], "passed")

        fixture_completed_summary = json.loads(json.dumps(passed_summary))
        fixture_completed_summary["live_submit"] = {
            "status": "completed",
            "executor_mode": "fixture",
            "platform_validation": False,
        }
        fixture_completed = verify_reachops_acceptance_summary(fixture_completed_summary, allow_external_pending=True)
        self.assertFalse(fixture_completed["passed"])
        self.assertIn("live_submit_not_platform_validation", fixture_completed["failures"])

        missing_activation_summary = json.loads(json.dumps(passed_summary))
        missing_activation_summary["live_submit"]["activation_status_loaded"] = False
        missing_activation = verify_reachops_acceptance_summary(missing_activation_summary, allow_external_pending=True)
        self.assertFalse(missing_activation["passed"])
        self.assertIn("live_submit_activation_status_missing", missing_activation["failures"])

        missing_action_evidence_summary = json.loads(json.dumps(passed_summary))
        missing_action_evidence_summary["live_submit"]["evidence_by_action_type"]["dm_review"] = []
        missing_action_evidence_summary["live_submit"]["missing_evidence_action_types"] = ["dm_review"]
        missing_action_evidence = verify_reachops_acceptance_summary(missing_action_evidence_summary, allow_external_pending=True)
        self.assertFalse(missing_action_evidence["passed"])
        self.assertIn("live_submit_action_evidence_missing", missing_action_evidence["failures"])

        missing_local_file_summary = json.loads(json.dumps(passed_summary))
        missing_local_file_summary["live_submit"]["missing_local_evidence_file_action_types"] = ["follow_review"]
        missing_local_file = verify_reachops_acceptance_summary(missing_local_file_summary, allow_external_pending=True)
        self.assertFalse(missing_local_file["passed"])
        self.assertIn("live_submit_local_evidence_file_missing", missing_local_file["failures"])

        invalid_file_detail_summary = json.loads(json.dumps(passed_summary))
        invalid_file_detail_summary["live_submit"]["evidence_file_details"]["follow_review"][0]["size"] = 0
        invalid_file_detail = verify_reachops_acceptance_summary(invalid_file_detail_summary, allow_external_pending=True)
        self.assertFalse(invalid_file_detail["passed"])
        self.assertIn("live_submit_evidence_file_details_invalid", invalid_file_detail["failures"])

        mismatched_sidecar_summary = json.loads(json.dumps(passed_summary))
        mismatched_sidecar_summary["live_submit"]["evidence_file_details"]["comment_reply"][0]["sidecar"]["action_type"] = "dm_review"
        mismatched_sidecar = verify_reachops_acceptance_summary(mismatched_sidecar_summary, allow_external_pending=True)
        self.assertFalse(mismatched_sidecar["passed"])
        self.assertIn("live_submit_evidence_file_details_invalid", mismatched_sidecar["failures"])

        failed_preflight_summary = json.loads(json.dumps(base_summary))
        failed_preflight_summary["live_preflight"] = {
            "status": "completed",
            "preflight_action_statuses": {
                "comment_reply": [{"status": "success"}],
                "follow_review": [{"status": "success"}],
                "dm_review": [{"status": "failed", "error_code": "DM_ENTRY_NOT_FOUND"}],
            },
            "missing_preflight_action_types": ["dm_review"],
        }
        failed_preflight = verify_reachops_acceptance_summary(failed_preflight_summary, allow_external_pending=True)
        self.assertFalse(failed_preflight["passed"])
        self.assertIn("live_preflight_action_missing", failed_preflight["failures"])

        stale_goal_summary = json.loads(json.dumps(passed_summary))
        stale_goal_summary["goal_status"]["status"] = "ready_for_external_validation"
        stale_goal_summary["goal_status"]["pending_external_validation"] = ["真实 TikTok 平台提交"]
        stale_goal = verify_reachops_acceptance_summary(stale_goal_summary, allow_external_pending=True)
        self.assertFalse(stale_goal["passed"])
        self.assertIn("goal_status_not_passed", stale_goal["failures"])
        self.assertIn("goal_status_has_stale_pending", stale_goal["failures"])

    def test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "dist" / "ReachOps" / "ReachOps.exe"
            installer = root / "dist" / "installer" / "ReachOps-Setup-0.4.0.exe"
            manifest_path = root / "dist" / "installer" / "reachops-update-manifest.json"
            report_dir = root / "reports" / "reachops_acceptance" / "20260624_120000"
            exe.parent.mkdir(parents=True, exist_ok=True)
            installer.parent.mkdir(parents=True, exist_ok=True)
            report_dir.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"reachops exe")
            installer.write_bytes(b"reachops installer")
            manifest = build_manifest(installer, version="0.4.0", build="mvp-001", channel="mvp")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            for name in [
                "delivery_audit_payload.json",
                "operator_pressure_payload.json",
                "installer_smoke_payload.json",
                "ui_startup_payload.json",
                "live_validation_manifest.json",
                "live_readiness_payload.json",
                "live_preflight_payload.json",
                "live_submit_payload.json",
                "goal_status_report.json",
            ]:
                (report_dir / name).write_text("{}", encoding="utf-8")

            png_sha = hashlib.sha256(b"png").hexdigest()

            def sidecar(action_type):
                return {
                    "screenshot_sha256": png_sha,
                    "action_type": action_type,
                    "profile_id": "profile-a",
                    "action_id": f"{action_type}-1",
                    "current_url": "https://www.tiktok.com/@creator/video/123",
                }

            summary = {
                "status": "passed",
                "delivery_audit": {
                    "status": "ok",
                    "passed": 26,
                    "pending_external_validation": 2,
                    "resolved_external_validation": 2,
                    "effective_pending_external_validation": 0,
                    "failed": 0,
                    "json_path": str(report_dir / "delivery_audit_payload.json"),
                },
                "operator_pressure": {
                    "status": "ok",
                    "campaign_count": 3,
                    "content_found": 15,
                    "comment_users": 27,
                    "customer_leads": 27,
                    "outreach_actions": 81,
                    "execution_success": 9,
                    "account_switched": 6,
                    "json_path": str(report_dir / "operator_pressure_payload.json"),
                },
                "installer_smoke": {
                    "status": "ok",
                    "exe_exists": True,
                    "data_in_install_dir": False,
                    "hash_ok": True,
                    "json_path": str(report_dir / "installer_smoke_payload.json"),
                },
                "ui_startup": {
                    "status": "ok",
                    "process_running": True,
                    "interactive_task": True,
                    "json_path": str(report_dir / "ui_startup_payload.json"),
                },
                "live_validation": {
                    "status": "ready",
                    "no_browser_started": True,
                    "no_submit": True,
                    "json_path": str(report_dir / "live_validation_manifest.json"),
                },
                "live_readiness": {
                    "status": "ready",
                    "ready": True,
                    "no_browser_started": True,
                    "no_submit": True,
                    "json_path": str(report_dir / "live_readiness_payload.json"),
                },
                "live_preflight": {
                    "status": "completed",
                    "preflight_action_statuses": {
                        "comment_reply": [{"status": "success"}],
                        "follow_review": [{"status": "success"}],
                        "dm_review": [{"status": "success"}],
                    },
                    "missing_preflight_action_types": [],
                    "json_path": str(report_dir / "live_preflight_payload.json"),
                },
                "live_submit": {
                    "status": "completed",
                    "executor_mode": "platform_selenium",
                    "platform_validation": True,
                    "activation_status_loaded": True,
                    "activation_status_source": "C:/ReachOps/config/reachops_activation_status.json",
                    "evidence_by_action_type": {
                        "comment_reply": ["evidence://comment"],
                        "follow_review": ["evidence://follow"],
                        "dm_review": ["evidence://dm"],
                    },
                    "evidence_file_details": {
                        "comment_reply": [{"path": "C:/evidence/comment.png", "size": 3, "sha256": png_sha, "sidecar_path": "C:/evidence/comment.png.json", "sidecar": sidecar("comment_reply")}],
                        "follow_review": [{"path": "C:/evidence/follow.png", "size": 3, "sha256": png_sha, "sidecar_path": "C:/evidence/follow.png.json", "sidecar": sidecar("follow_review")}],
                        "dm_review": [{"path": "C:/evidence/dm.png", "size": 3, "sha256": png_sha, "sidecar_path": "C:/evidence/dm.png.json", "sidecar": sidecar("dm_review")}],
                    },
                    "missing_evidence_action_types": [],
                    "missing_local_evidence_file_action_types": [],
                    "json_path": str(report_dir / "live_submit_payload.json"),
                },
                "goal_status": {
                    "status": "passed",
                    "summary": {"stages_passed": 5, "stages_pending_external_validation": 0, "stages_failed": 0},
                    "pending_external_validation": [],
                    "json_path": str(report_dir / "goal_status_report.json"),
                },
            }
            acceptance_summary = report_dir / "acceptance_summary.json"
            acceptance_summary.write_text(json.dumps(summary), encoding="utf-8")

            result = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertTrue(result["passed"])
            self.assertEqual(result["status"], "passed")
            self.assertFalse(result["failures"])
            self.assertEqual(result["artifacts"]["manifest"]["actual_sha256"], result["artifacts"]["manifest"]["expected_sha256"])

            broken_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            broken_manifest["installer"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(broken_manifest), encoding="utf-8")
            broken = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(broken["passed"])
            self.assertIn("manifest_sha256_mismatch", broken["failures"])

            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            pending_summary = json.loads(json.dumps(summary))
            pending_summary["status"] = "ready_for_external_validation"
            pending_summary["delivery_audit"]["resolved_external_validation"] = 0
            pending_summary["delivery_audit"]["effective_pending_external_validation"] = 2
            pending_summary["live_submit"] = {"status": "skipped"}
            pending_summary["goal_status"] = {
                "status": "ready_for_external_validation",
                "summary": {"stages_passed": 4, "stages_pending_external_validation": 1, "stages_failed": 0},
                "pending_external_validation": ["授权允许时能真实执行", "真实 TikTok 平台提交"],
                "json_path": str(report_dir / "goal_status_report.json"),
            }
            acceptance_summary.write_text(json.dumps(pending_summary), encoding="utf-8")
            pending = check_reachops_delivery_package(
                root=root,
                acceptance_summary_path=acceptance_summary,
                allow_external_pending=True,
            )
            self.assertTrue(pending["passed"])
            self.assertEqual(pending["status"], "ready_for_external_validation")

    def test_reachops_live_preflight_script_runs_without_submit_using_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Args:
                base_dir = tmp
                profile_ids = "profile-a,profile-b"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                workers = 2
                per_profile_limit = 3
                switch_attempts = 2
                per_profile_hour_limit = 20
                per_profile_video_hour_limit = 5
                page_timeout = 1
                element_timeout = 1

            result = run_reachops_live_preflight(
                Args(),
                platform_executor=FixtureActionExecutor(
                    [
                        {"action_type": "comment_reply", "status": "success", "evidence_path": "evidence://preflight/comment"},
                        {"action_type": "follow_review", "status": "success", "evidence_path": "evidence://preflight/follow"},
                        {"action_type": "dm_review", "status": "success", "evidence_path": "evidence://preflight/dm"},
                    ]
                ),
            )

            self.assertTrue(result["no_submit"])
            self.assertTrue(result["preflight_only"])
            self.assertEqual(len(result["seeded_action_ids"]), 3)
            self.assertEqual(result["summary"]["selected_actions"], 3)
            self.assertEqual(result["summary"]["success"], 3)
            self.assertEqual(result["missing_preflight_action_types"], [])
            self.assertTrue(result["preflight_action_statuses"]["comment_reply"])
            self.assertTrue(result["preflight_action_statuses"]["follow_review"])
            self.assertTrue(result["preflight_action_statuses"]["dm_review"])
            self.assertTrue(result["summary"].get("report", {}).get("json_path"))

    def test_reachops_live_submit_acceptance_blocks_without_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Args:
                base_dir = tmp
                profile_ids = "profile-a"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                comment_text = "authorized comment"
                dm_text = "authorized dm"
                workers = 1
                per_profile_limit = 3
                switch_attempts = 2
                limit = 3
                confirm_authorized_targets = ""
                allow_pressure_submit = ""
                per_profile_hour_limit = 3
                per_profile_video_hour_limit = 1
                page_timeout = 1
                element_timeout = 1

            result = run_reachops_live_submit_acceptance(
                Args(),
                platform_executor=FixtureActionExecutor([{"status": "success", "evidence_path": "evidence://should-not-run"}]),
            )

            self.assertFalse(result["passed"])
            self.assertFalse(result["live_submit"])
            self.assertEqual(result["error_code"], "AUTHORIZATION_INVALID")
            self.assertIn("--confirm-authorized-targets YES is required for live submit", result["errors"])
            self.assertIn("--profile-ids must be ixBrowser numeric profile ids: profile-a", result["errors"])

    def test_reachops_live_readiness_reports_blocked_without_activation_or_confirmation(self):
        class Args:
            profile_ids = "profile-a"
            group_name = "AUDIT"
            video_url = "https://www.tiktok.com/@creator/video/123"
            follow_profile_url = "https://www.tiktok.com/@buyer_one"
            dm_profile_url = "https://www.tiktok.com/@buyer_one"
            target_username = "buyer_one"
            confirm_authorized_targets = ""
            activation_status_path = "/tmp/reachops-missing-activation-status.json"
            allow_pressure_submit = ""
            limit = 3

        result = run_reachops_live_readiness(Args())

        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["no_browser_started"])
        self.assertTrue(result["no_submit"])
        checks = {item["name"]: item for item in result["checks"]}
        self.assertFalse(checks["live_submit_parameters"]["passed"])
        self.assertFalse(checks["profile_ids_are_ixbrowser_numeric_ids"]["passed"])
        self.assertFalse(checks["activation_status_file_exists"]["passed"])
        self.assertFalse(checks["activation_allows_live_submit_actions"]["passed"])
        self.assertTrue(checks["execution_evidence_policy_required"]["passed"])
        self.assertEqual(result["execution_evidence_policy"]["failure_error_code"], "LIVE_SUBMIT_EVIDENCE_MISSING")

    def test_reachops_live_readiness_passes_with_matching_authorized_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            activation_path = Path(tmp) / "reachops_activation_status.json"
            activation_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            class Args:
                profile_ids = "12345"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                confirm_authorized_targets = "YES"
                activation_status_path = str(activation_path)
                allow_pressure_submit = ""
                limit = 3

            result = run_reachops_live_readiness(Args())

            self.assertTrue(result["ready"])
            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["no_browser_started"])
            self.assertTrue(result["no_submit"])
            checks = {item["name"]: item for item in result["checks"]}
            self.assertTrue(checks["profile_ids_are_ixbrowser_numeric_ids"]["passed"])
            self.assertTrue(checks["activation_allows_live_submit_actions"]["passed"])
            self.assertEqual(len(checks["activation_allows_live_submit_actions"]["evidence"]["decisions"]), 3)
            self.assertTrue(checks["execution_evidence_policy_required"]["passed"])
            self.assertIn("sidecar_screenshot_sha256_matches_file", result["execution_evidence_policy"]["local_file_requirements"])

    def test_reachops_live_readiness_blocks_mismatched_target_username(self):
        with tempfile.TemporaryDirectory() as tmp:
            activation_path = Path(tmp) / "reachops_activation_status.json"
            activation_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            class Args:
                profile_ids = "12345"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "another_user"
                confirm_authorized_targets = "YES"
                activation_status_path = str(activation_path)
                allow_pressure_submit = ""
                limit = 3

            result = run_reachops_live_readiness(Args())

            self.assertFalse(result["ready"])
            checks = {item["name"]: item for item in result["checks"]}
            self.assertFalse(checks["live_submit_parameters"]["passed"])
            self.assertTrue(checks["profile_ids_are_ixbrowser_numeric_ids"]["passed"])
            self.assertFalse(checks["target_username_matches_profiles"]["passed"])

    def test_reachops_live_readiness_blocks_pressure_submit_without_extra_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            activation_path = Path(tmp) / "reachops_activation_status.json"
            activation_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            class Args:
                profile_ids = "12345"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                confirm_authorized_targets = "YES"
                activation_status_path = str(activation_path)
                allow_pressure_submit = ""
                limit = 4

            result = run_reachops_live_readiness(Args())

            self.assertFalse(result["ready"])
            checks = {item["name"]: item for item in result["checks"]}
            self.assertFalse(checks["live_submit_parameters"]["passed"])
            self.assertIn("--allow-pressure-submit YES is required when --limit > 3", checks["live_submit_parameters"]["evidence"]["errors"])

    def test_reachops_live_validation_manifest_builds_operator_next_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "activation.json"
            status_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            class Args:
                profile_group = "BR"
                profile_ids = ""
                profile_limit = 2
                max_pages = 1
                profile_scan_timeout = 1
                target = "anti aging serum"
                comment_video_url = "https://www.tiktok.com/@creator/video/123"
                target_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = ""
                target_username = ""
                activation_status_path = str(status_path)
                limit = 5
                allow_pressure_submit = "YES"
                confirm_authorized_targets = "YES"
                include_live_submit_command = True

            snapshot = {
                "available": True,
                "error": "",
                "profile_count": 3,
                "group_count": 2,
                "groups": [{"group_id": "br", "group_name": "BR", "count": 2}],
                "profiles": [
                    {"profile_id": "12345", "name": "BR one", "group_name": "BR"},
                    {"profile_id": "not-numeric", "name": "BR bad", "group_name": "BR"},
                    {"profile_id": "67890", "name": "US one", "group_name": "US"},
                ],
            }

            manifest = build_reachops_live_validation_manifest(Args(), snapshot=snapshot)

            self.assertEqual(manifest["status"], "ready_for_readiness_check")
            self.assertTrue(manifest["no_browser_started"])
            self.assertTrue(manifest["no_submit"])
            self.assertEqual(manifest["selected_profile_ids"], ["12345"])
            self.assertEqual(manifest["selected_profile_count"], 1)
            self.assertTrue(manifest["blocking_summary"]["profile_ready"])
            self.assertTrue(manifest["blocking_summary"]["target_ready"])
            self.assertTrue(manifest["blocking_summary"]["activation_ready"])
            self.assertTrue(manifest["blocking_summary"]["authorization_confirmed"])
            self.assertEqual(manifest["blocking_summary"]["next_blocking_item"], "")
            self.assertEqual(manifest["profile_snapshot"]["groups"][0]["selected_profile_count"], 1)
            self.assertEqual(manifest["missing_inputs"], [])
            self.assertIn("run_reachops_live_readiness_windows.ps1", manifest["commands"]["readiness_no_browser_no_submit"])
            self.assertIn("-ProfileIds '12345'", manifest["commands"]["readiness_no_browser_no_submit"])
            self.assertIn("-Limit '5'", manifest["commands"]["readiness_no_browser_no_submit"])
            self.assertIn("-AllowPressureSubmit 'YES'", manifest["commands"]["readiness_no_browser_no_submit"])
            self.assertIn("-Limit '5'", manifest["commands"]["acceptance_preflight"])
            self.assertIn("-AllowPressureSubmit 'YES'", manifest["commands"]["acceptance_preflight"])
            self.assertIn("-RunLiveSubmit", manifest["commands"]["controlled_live_submit"])

    def test_reachops_live_validation_manifest_blocks_missing_real_inputs(self):
        class Args:
            profile_group = "BR"
            profile_ids = ""
            profile_limit = 3
            max_pages = 1
            profile_scan_timeout = 1
            target = "anti aging serum"
            comment_video_url = ""
            target_profile_url = ""
            dm_profile_url = ""
            target_username = ""
            activation_status_path = "/tmp/missing-reachops-activation.json"
            confirm_authorized_targets = ""
            include_live_submit_command = False

        manifest = build_reachops_live_validation_manifest(
            Args(),
            snapshot={"available": False, "error": "ix api down", "profiles": [], "groups": [], "profile_count": 0, "group_count": 0},
        )

        self.assertEqual(manifest["status"], "blocked")
        self.assertIn("ixBrowser 数字 Profile ID", manifest["missing_inputs"])
        self.assertIn("已授权 TikTok 视频链接", manifest["missing_inputs"])
        self.assertIn("激活状态文件", manifest["missing_inputs"])
        self.assertFalse(manifest["blocking_summary"]["profile_ready"])
        self.assertFalse(manifest["blocking_summary"]["target_ready"])
        self.assertFalse(manifest["blocking_summary"]["activation_ready"])
        self.assertFalse(manifest["blocking_summary"]["authorization_confirmed"])
        self.assertEqual(manifest["blocking_summary"]["next_blocking_item"], "ixBrowser 数字 Profile ID")
        self.assertEqual(manifest["commands"]["controlled_live_submit"], "")

    def test_reachops_live_validation_manifest_skips_profile_scan_with_explicit_profile_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "activation.json"
            status_path.write_text("{}", encoding="utf-8")

            class Args:
                profile_group = "BR"
                profile_ids = "12345,67890"
                profile_limit = 3
                max_pages = 1
                profile_scan_timeout = 1
                target = "anti aging serum"
                comment_video_url = "https://www.tiktok.com/@creator/video/123"
                target_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = ""
                target_username = "buyer_one"
                activation_status_path = str(status_path)
                confirm_authorized_targets = "YES"
                include_live_submit_command = False

            manifest = build_reachops_live_validation_manifest(Args())

            self.assertEqual(manifest["selected_profile_ids"], ["12345", "67890"])
            self.assertEqual(manifest["selected_profile_count"], 2)
            self.assertEqual(manifest["profile_snapshot"]["error"], "profile scan skipped because explicit ProfileIds were provided")
            self.assertNotIn("ixBrowser 数字 Profile ID", manifest["missing_inputs"])
            self.assertIn("-ProfileIds '12345,67890'", manifest["commands"]["readiness_no_browser_no_submit"])

    def test_reachops_profile_snapshot_handles_worker_decode_failure_output(self):
        class Completed:
            returncode = 1
            stdout = None
            stderr = "UnicodeDecodeError: invalid start byte"

        with patch("tools.reachops_live_validation_manifest.subprocess.run", return_value=Completed()):
            snapshot = load_reachops_profile_snapshot(max_pages=1, timeout_seconds=1, group_name="US", profile_limit=1)

        self.assertFalse(snapshot["available"])
        self.assertIn("UnicodeDecodeError", snapshot["error"])
        self.assertEqual(snapshot["profiles"], [])

    def test_reachops_live_submit_acceptance_runs_with_activation_and_evidence_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Args:
                base_dir = tmp
                profile_ids = "12345"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                comment_text = "authorized comment"
                dm_text = "authorized dm"
                workers = 1
                per_profile_limit = 3
                switch_attempts = 2
                limit = 3
                confirm_authorized_targets = "YES"
                allow_pressure_submit = ""
                per_profile_hour_limit = 10
                per_profile_video_hour_limit = 5
                page_timeout = 1
                element_timeout = 1

            status_path = RuntimePaths.build(tmp).ensure_dirs().activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    },
                    fh,
                )

            result = run_reachops_live_submit_acceptance(
                Args(),
                platform_executor=FixtureActionExecutor(
                    [
                        {"action_type": "comment_reply", "status": "success", "evidence_path": "evidence://submit/comment"},
                        {"action_type": "follow_review", "status": "success", "evidence_path": "evidence://submit/follow"},
                        {"action_type": "dm_review", "status": "success", "evidence_path": "evidence://submit/dm"},
                    ]
                ),
            )

            self.assertTrue(result["passed"])
            self.assertTrue(result["live_submit"])
            self.assertEqual(result["executor_mode"], "fixture")
            self.assertFalse(result["platform_validation"])
            self.assertTrue(result["activation_status_loaded"])
            self.assertEqual(result["missing_evidence_count"], 0)
            self.assertEqual(result["missing_evidence_action_types"], [])
            self.assertTrue(result["evidence_by_action_type"]["comment_reply"])
            self.assertTrue(result["evidence_by_action_type"]["follow_review"])
            self.assertTrue(result["evidence_by_action_type"]["dm_review"])
            self.assertEqual(result["summary"]["success"], 3)
            self.assertTrue(result["summary"].get("report", {}).get("json_path"))

    def test_reachops_live_submit_acceptance_can_load_external_activation_status(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as activation_tmp:
            activation_path = Path(activation_tmp) / "reachops_activation_status.json"
            activation_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            class Args:
                base_dir = tmp
                activation_status_path = str(activation_path)
                profile_ids = "12345"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                comment_text = "authorized comment"
                dm_text = "authorized dm"
                workers = 1
                per_profile_limit = 3
                switch_attempts = 2
                limit = 3
                confirm_authorized_targets = "YES"
                allow_pressure_submit = ""
                per_profile_hour_limit = 10
                per_profile_video_hour_limit = 5
                page_timeout = 1
                element_timeout = 1

            result = run_reachops_live_submit_acceptance(
                Args(),
                platform_executor=FixtureActionExecutor(
                    [
                        {"action_type": "comment_reply", "status": "success", "evidence_path": "evidence://submit/comment"},
                        {"action_type": "follow_review", "status": "success", "evidence_path": "evidence://submit/follow"},
                        {"action_type": "dm_review", "status": "success", "evidence_path": "evidence://submit/dm"},
                    ]
                ),
            )

            self.assertTrue(result["passed"])
            self.assertTrue(result["activation_status_loaded"])
            self.assertEqual(Path(result["activation_status_source"]), activation_path.resolve())
            self.assertTrue(Path(result["activation_status_path"]).exists())

    def test_reachops_live_submit_acceptance_marks_default_executor_as_platform_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence-fixture"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            comment_evidence = evidence_dir / "comment.png"
            follow_evidence = evidence_dir / "follow.png"
            dm_evidence = evidence_dir / "dm.png"
            for path, action_type in [
                (comment_evidence, "comment_reply"),
                (follow_evidence, "follow_review"),
                (dm_evidence, "dm_review"),
            ]:
                path.write_bytes(b"png")
                Path(f"{path}.json").write_text(
                    json.dumps(
                        {
                            "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                            "screenshot_size": 3,
                            "action_type": action_type,
                            "profile_id": "profile-a",
                            "action_id": f"{action_type}-1",
                            "current_url": "https://www.tiktok.com/@creator/video/123",
                        }
                    ),
                    encoding="utf-8",
                )

            class Args:
                base_dir = tmp
                activation_status_path = ""
                profile_ids = "12345"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                comment_text = "authorized comment"
                dm_text = "authorized dm"
                workers = 1
                per_profile_limit = 3
                switch_attempts = 2
                limit = 3
                confirm_authorized_targets = "YES"
                allow_pressure_submit = ""
                per_profile_hour_limit = 10
                per_profile_video_hour_limit = 5
                page_timeout = 1
                element_timeout = 1

            status_path = RuntimePaths.build(tmp).ensure_dirs().activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    },
                    fh,
                )

            with patch(
                "tools.reachops_live_submit_acceptance.build_platform_executor",
                return_value=FixtureActionExecutor(
                    [
                        {"action_type": "comment_reply", "status": "success", "evidence_path": str(comment_evidence)},
                        {"action_type": "follow_review", "status": "success", "evidence_path": str(follow_evidence)},
                        {"action_type": "dm_review", "status": "success", "evidence_path": str(dm_evidence)},
                    ]
                ),
            ):
                result = run_reachops_live_submit_acceptance(Args())

            self.assertTrue(result["passed"])
            self.assertEqual(result["executor_mode"], "platform_selenium")
            self.assertTrue(result["platform_validation"])
            self.assertEqual(result["missing_local_evidence_file_action_types"], [])
            self.assertEqual(result["evidence_file_details"]["comment_reply"][0]["size"], 3)
            self.assertEqual(result["evidence_file_details"]["follow_review"][0]["sha256"], hashlib.sha256(b"png").hexdigest())
            self.assertTrue(result["evidence_file_details"]["dm_review"][0]["sidecar_path"].endswith(".png.json"))

    def test_reachops_live_submit_acceptance_rejects_mismatched_evidence_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence-fixture"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            comment_evidence = evidence_dir / "comment.png"
            follow_evidence = evidence_dir / "follow.png"
            dm_evidence = evidence_dir / "dm.png"
            for path, action_type in [
                (comment_evidence, "dm_review"),
                (follow_evidence, "follow_review"),
                (dm_evidence, "dm_review"),
            ]:
                path.write_bytes(b"png")
                Path(f"{path}.json").write_text(
                    json.dumps(
                        {
                            "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                            "screenshot_size": 3,
                            "action_type": action_type,
                            "profile_id": "profile-a",
                            "action_id": f"{action_type}-1",
                            "current_url": "https://www.tiktok.com/@creator/video/123",
                        }
                    ),
                    encoding="utf-8",
                )

            class Args:
                base_dir = tmp
                activation_status_path = ""
                profile_ids = "12345"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                follow_profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one"
                target_username = "buyer_one"
                comment_text = "authorized comment"
                dm_text = "authorized dm"
                workers = 1
                per_profile_limit = 3
                switch_attempts = 2
                limit = 3
                confirm_authorized_targets = "YES"
                allow_pressure_submit = ""
                per_profile_hour_limit = 10
                per_profile_video_hour_limit = 5
                page_timeout = 1
                element_timeout = 1

            status_path = RuntimePaths.build(tmp).ensure_dirs().activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    },
                    fh,
                )

            with patch(
                "tools.reachops_live_submit_acceptance.build_platform_executor",
                return_value=FixtureActionExecutor(
                    [
                        {"action_type": "comment_reply", "status": "success", "evidence_path": str(comment_evidence)},
                        {"action_type": "follow_review", "status": "success", "evidence_path": str(follow_evidence)},
                        {"action_type": "dm_review", "status": "success", "evidence_path": str(dm_evidence)},
                    ]
                ),
            ):
                result = run_reachops_live_submit_acceptance(Args())

            self.assertFalse(result["passed"])
            self.assertEqual(result["executor_mode"], "platform_selenium")
            self.assertIn("comment_reply", result["missing_local_evidence_file_action_types"])
            self.assertEqual(result["evidence_file_details"]["comment_reply"], [])

    def test_reachops_packaging_files_define_standalone_windows_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "ReachOps" / "packaging" / "reachops.spec").read_text(encoding="utf-8")
        iss = (root / "ReachOps" / "packaging" / "ReachOps.iss").read_text(encoding="utf-8")
        build_script = (root / "tools" / "build_reachops_windows.ps1").read_text(encoding="utf-8")
        acceptance_script = (root / "tools" / "run_reachops_acceptance_windows.ps1").read_text(encoding="utf-8")
        live_readiness_windows_script = (root / "tools" / "run_reachops_live_readiness_windows.ps1").read_text(encoding="utf-8")
        live_validation_windows_script = (root / "tools" / "run_reachops_live_validation_manifest_windows.ps1").read_text(encoding="utf-8")
        live_preflight_windows_script = (root / "tools" / "run_reachops_live_preflight_windows.ps1").read_text(encoding="utf-8")
        installer_smoke_script = (root / "tools" / "run_reachops_installer_smoke_windows.ps1").read_text(encoding="utf-8")
        ui_startup_smoke_script = (root / "tools" / "run_reachops_ui_startup_smoke_windows.ps1").read_text(encoding="utf-8")
        ui_start_script = (root / "tools" / "start_reachops_ui_windows.ps1").read_text(encoding="utf-8")
        ui_start_bat = (root / "tools" / "start_growth_ui_windows.bat").read_text(encoding="utf-8")
        sync_script = (root / "tools" / "sync_reachops_to_windows_vm.sh").read_text(encoding="utf-8")
        reachops_requirements = (root / "ReachOps" / "packaging" / "requirements-reachops.txt").read_text(encoding="utf-8")
        acceptance_inputs_template = (root / "tools" / "reachops_acceptance_inputs.example.ps1").read_text(encoding="utf-8")

        self.assertIn('name="ReachOps"', spec)
        self.assertIn("ReachOpsApp.py", spec)
        self.assertNotIn("GrowthIntelligenceApp.py", spec)
        self.assertIn("ReachOps.intelligence.ai_strategy", spec)
        self.assertIn("SPEC_FILE", spec)
        self.assertIn("PROJECT_ROOT = SPEC_FILE.parents[2]", spec)
        self.assertIn('#define MyAppName "ReachOps"', iss)
        self.assertIn("ReachOps-Setup-{#MyAppVersion}", iss)
        self.assertIn("MyVersionInfoBuild", iss)
        self.assertIn("VersionInfoVersion={#MyFullVersion}", iss)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\{#MyAppName}", iss)
        self.assertIn("PrivilegesRequired=lowest", iss)
        self.assertIn("requirements-reachops.txt", build_script)
        self.assertIn("Resolve-VersionInfoBuild", build_script)
        self.assertIn("/DMyVersionInfoBuild=$VersionInfoBuild", build_script)
        self.assertIn("ReachOpsApp.py", build_script)
        self.assertIn("Assert-LastExitCode \"ReachOps PyInstaller build\"", build_script)
        self.assertIn("Find-InnoSetupCompiler", build_script)
        self.assertIn("Inno Setup 6\\ISCC.exe", build_script)
        self.assertIn("tools\\reachops_delivery_smoke.py --json", build_script)
        self.assertIn("tools\\reachops_delivery_audit.py --json", build_script)
        self.assertIn("write_reachops_update_manifest.py", build_script)
        self.assertIn("SkipInstallerSmoke", build_script)
        self.assertIn("tools\\run_reachops_installer_smoke_windows.ps1", build_script)
        self.assertIn("Assert-LastExitCode \"ReachOps installer smoke\"", build_script)
        self.assertIn("Assert-LastExitCode \"ReachOps update manifest\"", build_script)
        self.assertIn("tools\\reachops_delivery_audit.py", acceptance_script)
        self.assertIn("tools\\reachops_operator_pressure.py", acceptance_script)
        self.assertIn("tools\\reachops_goal_status_report.py", acceptance_script)
        self.assertIn("tools\\reachops_delivery_package_check.py", acceptance_script)
        self.assertIn("tools\\reachops_live_preflight.py", acceptance_script)
        self.assertIn("tools\\reachops_live_readiness.py", acceptance_script)
        self.assertIn("tools\\reachops_live_validation_manifest.py", acceptance_script)
        self.assertIn("tools\\reachops_live_submit_acceptance.py", acceptance_script)
        self.assertIn("Assert-LastExitCode", acceptance_script)
        self.assertIn("Invoke-PythonCapture", acceptance_script)
        self.assertIn("Invoke-PowerShellCapture", acceptance_script)
        self.assertIn("Write-AcceptanceSummary", acceptance_script)
        self.assertIn("Add-GoalStatusToAcceptanceSummary", acceptance_script)
        self.assertIn("acceptance_summary.json", acceptance_script)
        self.assertIn("goal_status_report.json", acceptance_script)
        self.assertIn("GOAL_STATUS_JSON", acceptance_script)
        self.assertIn("PACKAGE_CHECK_JSON", acceptance_script)
        self.assertIn("delivery_package_check.json", acceptance_script)
        self.assertIn("ReachOps delivery package check failed for final passed acceptance", acceptance_script)
        self.assertIn("goal_status", acceptance_script)
        self.assertIn("operator_pressure", acceptance_script)
        self.assertIn("OPERATOR_PRESSURE_JSON", acceptance_script)
        self.assertIn("operator_pressure_payload.json", acceptance_script)
        self.assertIn("ready_for_external_validation", acceptance_script)
        self.assertIn("resolved_external_validation", acceptance_script)
        self.assertIn("effective_pending_external_validation", acceptance_script)
        self.assertIn("platform_validation", acceptance_script)
        self.assertIn("executor_mode", acceptance_script)
        self.assertIn("activation_status_loaded", acceptance_script)
        self.assertIn("activation_status_source", acceptance_script)
        self.assertIn("evidence_by_action_type", acceptance_script)
        self.assertIn("evidence_file_details", acceptance_script)
        self.assertIn("missing_evidence_action_types", acceptance_script)
        self.assertIn("missing_local_evidence_file_action_types", acceptance_script)
        self.assertIn("preflight_action_statuses", acceptance_script)
        self.assertIn("missing_preflight_action_types", acceptance_script)
        self.assertIn("LIVE_READINESS_JSON", acceptance_script)
        self.assertIn("LIVE_VALIDATION_MANIFEST_JSON", acceptance_script)
        self.assertIn("live_validation", acceptance_script)
        self.assertIn("live_readiness", acceptance_script)
        self.assertIn("Skipping live preflight: live readiness is blocked", acceptance_script)
        self.assertIn("RunLiveSubmit requires live readiness status ready", acceptance_script)
        self.assertIn("AllowPressureSubmit", acceptance_script)
        self.assertIn("AllowMissingInstaller", acceptance_script)
        self.assertIn("--allow-pressure-submit", acceptance_script)
        self.assertIn("--limit\", ([string]$Limit", acceptance_script)
        self.assertIn("Empty-JsonArray", acceptance_script)
        self.assertIn("ActivationStatusPath", acceptance_script)
        self.assertIn("--activation-status-path", acceptance_script)
        self.assertIn("ACCEPTANCE_SUMMARY_JSON", acceptance_script)
        self.assertIn("tools\\run_reachops_installer_smoke_windows.ps1", acceptance_script)
        self.assertIn("installer_smoke_payload.json", acceptance_script)
        self.assertIn("INSTALLER_SMOKE_JSON", acceptance_script)
        self.assertIn("tools\\run_reachops_ui_startup_smoke_windows.ps1", acceptance_script)
        self.assertIn("ui_startup_payload.json", acceptance_script)
        self.assertIn("UI_STARTUP_JSON", acceptance_script)
        self.assertIn("ui_startup", acceptance_script)
        self.assertIn("UTF8Encoding($false)", acceptance_script)
        self.assertIn("(Get-Location).ProviderPath", acceptance_script)
        self.assertIn("while ($idx -ge 0)", acceptance_script)
        self.assertNotIn("Tee-Object", acceptance_script)
        self.assertIn("tools\\reachops_live_readiness.py", live_readiness_windows_script)
        self.assertIn("No browser will be opened", live_readiness_windows_script)
        self.assertIn("No comment/follow/dm will be submitted", live_readiness_windows_script)
        self.assertIn("LIVE_READINESS_JSON", live_readiness_windows_script)
        self.assertIn("ConfirmAuthorizedTargets", live_readiness_windows_script)
        self.assertIn("AllowPressureSubmit", live_readiness_windows_script)
        self.assertIn("--allow-pressure-submit", live_readiness_windows_script)
        self.assertIn("--limit\", \"$Limit", live_readiness_windows_script)
        self.assertIn("ProfileIds is required", live_readiness_windows_script)
        self.assertNotIn("reachops_live_submit_acceptance.py", live_readiness_windows_script)
        self.assertIn("tools\\reachops_live_validation_manifest.py", live_validation_windows_script)
        self.assertIn("No browser will be opened", live_validation_windows_script)
        self.assertIn("No comment/follow/dm will be submitted", live_validation_windows_script)
        self.assertIn("LIVE_VALIDATION_MANIFEST_JSON", live_validation_windows_script)
        self.assertIn("IncludeLiveSubmitCommand", live_validation_windows_script)
        self.assertIn("AllowPressureSubmit", live_validation_windows_script)
        self.assertIn("--allow-pressure-submit", live_validation_windows_script)
        self.assertIn("--limit\", ([string]$Limit", live_validation_windows_script)
        self.assertIn("tools\\reachops_live_preflight.py", live_preflight_windows_script)
        self.assertIn("No comment/follow/dm will be submitted", live_preflight_windows_script)
        self.assertIn("LIVE_PREFLIGHT_JSON", live_preflight_windows_script)
        self.assertIn("ProfileIds is required", live_preflight_windows_script)
        self.assertIn("CommentVideoUrl is required", live_preflight_windows_script)
        self.assertIn("TargetProfileUrl is required", live_preflight_windows_script)
        self.assertNotIn("reachops_live_submit_acceptance.py", live_preflight_windows_script)
        self.assertIn("Start-Process -FilePath $InstallerPath", installer_smoke_script)
        self.assertIn("-Wait -PassThru", installer_smoke_script)
        self.assertIn("data_in_install_dir", installer_smoke_script)
        self.assertIn("manifest_hash_mismatch", installer_smoke_script)
        self.assertIn("UTF8Encoding]::new($false)", installer_smoke_script)
        self.assertIn("pythonw.exe", ui_start_script)
        self.assertIn("Start-Process -FilePath $Pythonw", ui_start_script)
        self.assertIn("InteractiveTask", ui_start_script)
        self.assertIn("Register-ScheduledTask", ui_start_script)
        self.assertIn("Start-ScheduledTask", ui_start_script)
        self.assertIn("growth_ui_startup_state.json", ui_start_script)
        self.assertIn("ReachOpsApp.py", ui_start_script)
        self.assertIn("entrypoint = $entrypoint", ui_start_script)
        self.assertNotIn("GrowthIntelligenceApp.py", ui_start_script)
        self.assertIn("start_reachops_ui_windows.ps1", ui_start_bat)
        self.assertIn("C:\\Users\\aofa\\ReachOps_client", ui_start_bat)
        self.assertNotIn("IntelliOps_codex_growth_ui", ui_start_bat)
        self.assertIn("start_reachops_ui_windows.ps1", ui_startup_smoke_script)
        self.assertIn("-InteractiveTask", ui_startup_smoke_script)
        self.assertIn("process_running", ui_startup_smoke_script)
        self.assertIn("KeepRunning", ui_startup_smoke_script)
        self.assertIn("reachops_live_submit_acceptance.py", sync_script)
        self.assertIn("reachops_live_readiness.py", sync_script)
        self.assertIn("reachops_goal_status_report.py", sync_script)
        self.assertIn("reachops_operator_pressure.py", sync_script)
        self.assertIn("reachops_action_preflight_existing_batch.py", sync_script)
        self.assertIn("reachops_real_acquisition_report.py", sync_script)
        self.assertIn("reachops_visual_collection_preflight.py", sync_script)
        self.assertIn("capture_windows_desktop_hidden.ps1", sync_script)
        self.assertIn("reachops_live_validation_manifest.py", sync_script)
        self.assertIn("run_reachops_live_validation_manifest_windows.ps1", sync_script)
        self.assertIn("run_reachops_live_readiness_windows.ps1", sync_script)
        self.assertIn("run_reachops_live_preflight_windows.ps1", sync_script)
        self.assertIn("start_reachops_ui_windows.ps1", sync_script)
        self.assertIn("run_reachops_ui_startup_smoke_windows.ps1", sync_script)
        self.assertIn("run_reachops_installer_smoke_windows.ps1", sync_script)
        self.assertIn("run_reachops_acceptance_windows.ps1", sync_script)
        self.assertIn("verify_reachops_acceptance_summary.py", sync_script)
        self.assertIn("reachops_delivery_package_check.py", sync_script)
        self.assertIn("reachops_acceptance_inputs.example.ps1", sync_script)
        self.assertIn("reachops_delivery_audit.py --json", sync_script)
        self.assertIn("reachops_operator_pressure.py --json", sync_script)
        self.assertIn("ai_strategy.py", sync_script)
        self.assertIn("requirements.txt", sync_script)
        self.assertIn("startup_icon.ico", sync_script)
        self.assertIn("ReachOpsApp.py", sync_script)
        self.assertIn("C:/Users/aofa/ReachOps_client", sync_script)
        self.assertNotIn("IntelliOps_codex_growth_ui", sync_script)
        self.assertIn("selenium>=4.40", reachops_requirements)
        self.assertIn("ixbrowser_local_api>=1.2", reachops_requirements)
        self.assertIn("pyinstaller>=6.3", reachops_requirements)
        self.assertNotIn("opencv-python", reachops_requirements)
        self.assertIn("$RunControlledLiveSubmit = $false", acceptance_inputs_template)
        self.assertIn("run_reachops_live_readiness_windows.ps1", acceptance_inputs_template)
        self.assertIn("run_reachops_live_preflight_windows.ps1", acceptance_inputs_template)
        self.assertIn("run_reachops_acceptance_windows.ps1", acceptance_inputs_template)
        self.assertIn("Set `$RunControlledLiveSubmit = `$true", acceptance_inputs_template)
        self.assertIn("placeholder value", acceptance_inputs_template)

    def test_standalone_app_tiktok_url_validation_returns_boolean(self):
        self.assertTrue(GrowthIntelligenceStandaloneApp._is_tiktok_url(object(), "https://www.tiktok.com/@creator"))
        self.assertTrue(GrowthIntelligenceStandaloneApp._is_tiktok_url(object(), "tiktok.com/@creator/video/123"))
        self.assertFalse(GrowthIntelligenceStandaloneApp._is_tiktok_url(object(), "https://example.com/@creator"))

    def test_search_page_login_button_is_not_forced_login_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            driver = FakeDriver()
            driver.current_url = "https://www.tiktok.com/search/video?q=anti%20aging%20serum"
            driver.script_results = [
                {
                    "url": driver.current_url,
                    "text": "Top Users Videos LIVE Photo Log in",
                    "videoLinks": 0,
                    "profileLinks": 0,
                    "loginDialog": False,
                    "forcedLoginText": False,
                    "captcha": False,
                    "proxy": False,
                }
            ]

            self.assertEqual(service.router._detect_page_state(driver), "")

    def test_real_mode_retries_next_profile_when_page_has_empty_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": EmptyVideoCollector(),
                    "comment": StaticCommentCollector(),
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@empty_creator"}],
                [{"profile_id": "p1", "group_name": "US"}, {"profile_id": "p2", "group_name": "US"}],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    retry_empty_result_with_next_profile=True,
                ),
            )
            tasks = service.storage.list_collection_tasks(limit=10)

            self.assertEqual(result.processed_sources, 0)
            self.assertEqual(len(tasks), 2)
            self.assertEqual({row["profile_id"] for row in tasks}, {"p1", "p2"})
            self.assertEqual({row["error_code"] for row in tasks}, {"EMPTY_RESULT_RETRY"})

    def test_real_mode_retries_next_profile_when_comments_are_access_gated_after_content_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            comment_collector = FirstAttemptCommentAccessGatedCollector()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": comment_collector,
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "p1", "group_name": "US"}, {"profile_id": "p2", "group_name": "US"}],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    retry_empty_result_with_next_profile=True,
                ),
            )
            tasks = sorted(service.storage.list_collection_tasks(limit=10), key=lambda row: row["profile_id"])
            candidates = service.storage.list_candidates()
            errors = service.storage.error_counts()

            self.assertEqual(result.processed_sources, 1)
            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0]["profile_id"], "p1")
            self.assertEqual(tasks[0]["status"], "failed")
            self.assertEqual(tasks[0]["error_code"], "COMMENT_ACCESS_GATED")
            self.assertEqual(tasks[1]["profile_id"], "p2")
            self.assertEqual(tasks[1]["status"], "completed")
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].username, "buyer_one")
            self.assertGreaterEqual(errors.get("COMMENT_ACCESS_GATED", 0), 1)

    def test_tiktok_search_collector_extracts_video_links_from_dom_rows(self):
        driver = FakeDriver()
        driver.current_url = "https://www.tiktok.com/search/video?q=anti%20aging%20serum"
        driver.script_results = [
            5,
            [
                {
                    "video_url": "https://www.tiktok.com/@creator/video/123",
                    "caption": "where can I buy this serum",
                    "raw_text": "1.2K where can I buy this serum",
                    "collector_level": "search_dom",
                }
            ],
        ]

        rows = TikTokSearchCollector().collect(driver, {"source": {"value": "anti aging serum"}}, {"limit": 5})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"]["video_id"], "123")
        self.assertEqual(rows[0]["content"]["creator_username"], "creator")

    def test_topic_collector_ignores_plain_shop_navigation_link(self):
        driver = FakeDriver()
        driver.script_results = [
            [
                {
                    "href": "https://www.tiktok.com/shop",
                    "text": "",
                    "caption": "",
                    "isVideo": False,
                    "isCommerce": True,
                }
            ]
        ]

        rows = TikTokTopicContentCollector().collect(driver, {}, {"limit": 5})

        self.assertEqual(rows, [])

    def test_keyword_topic_source_uses_search_fallback_then_scans_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": StaticCommentCollector(),
                    "search": StaticSearchCollector(),
                    "topic_content": EmptyTopicContentCollector(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [{"type": "keyword", "value": "anti aging serum"}],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(test_mode=False, task_delay_min_seconds=0, task_delay_max_seconds=0),
            )
            funnel = GrowthWorkflowService(service).build_campaign_funnel(batch_id=service.storage.list_collection_batches()[0]["id"])

            self.assertEqual(result.processed_sources, 1)
            self.assertGreaterEqual(funnel["content_found"], 1)
            self.assertGreaterEqual(funnel["comment_users"], 1)

    def test_keyword_topic_source_rotates_search_urls_until_material_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            search = SecondAttemptSearchCollector()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": StaticCommentCollector(),
                    "search": search,
                    "topic_content": EmptyTopicContentCollector(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [{"type": "keyword", "value": "anti aging serum"}],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(test_mode=False, task_delay_min_seconds=0, task_delay_max_seconds=0),
            )

            self.assertEqual(result.processed_sources, 1)
            self.assertGreaterEqual(search.calls, 2)
            self.assertGreaterEqual(service.storage.count_table("candidate_users"), 1)

    def test_topic_source_skips_weakly_related_recommendation_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": StaticCommentCollector(),
                    "search": object(),
                    "topic_content": MixedTopicContentCollector(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True
            plan = service.create_campaign_plan("anti aging serum", max_sources=1)

            result = service.run_collection(
                [{"type": "keyword", "value": "anti aging serum"}],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(
                    campaign_id=plan["campaign"]["id"],
                    max_videos_per_creator=5,
                    max_comments_per_video=10,
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                ),
            )
            with service.storage.connect() as conn:
                contents = [dict(row) for row in conn.execute("SELECT video_id, caption FROM discovered_contents ORDER BY collected_at")]
                skipped = [
                    dict(row)
                    for row in conn.execute("SELECT event, payload FROM growth_events WHERE event='topic_video_skipped_by_relevance'")
                ]

            self.assertEqual(result.processed_sources, 1)
            self.assertEqual([row["video_id"] for row in contents], ["serum-1"])
            self.assertEqual(len(skipped), 1)
            self.assertIn("forex", skipped[0]["payload"])
            self.assertEqual(service.storage.count_table("candidate_users"), 1)

    def test_direct_content_sources_bypass_campaign_relevance_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            config = GrowthTaskConfig(campaign_id="acq_direct", test_mode=True)
            datasource = type("DataSourceObj", (), {"type": "content_url", "value": "https://www.tiktok.com/@creator/video/123"})()

            relevant, detail = service.router._is_topic_content_relevant(
                datasource,
                {
                    "video_url": "https://www.tiktok.com/@creator/video/123",
                    "caption": "unrelated forex trading text",
                },
                config,
            )

        self.assertTrue(relevant)
        self.assertEqual(detail["reason"], "direct_source")

    def test_comment_scan_discards_rows_when_final_url_does_not_match_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": MismatchedUrlCommentCollector(),
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True
            driver = FakeDriver()

            comments, evidence = service.router._collect_comments_with_retry(
                driver,
                {
                    "id": "ct_target",
                    "video_id": "123",
                    "video_url": "https://www.tiktok.com/@creator/video/123",
                },
                GrowthTaskConfig(test_mode=True, comment_retry_attempts=1),
                "comment_scan",
            )
            with service.storage.connect() as conn:
                events = [
                    dict(row)
                    for row in conn.execute("SELECT event, payload FROM growth_events WHERE event='comment_scan_discarded_url_mismatch'")
                ]

        self.assertEqual(comments, [])
        self.assertEqual(evidence.final_url, "https://www.tiktok.com/@other_creator/video/999")
        self.assertEqual(len(events), 1)
        self.assertIn("discarded_comment_count", events[0]["payload"])

    def test_visual_preflight_source_from_plan_respects_operator_source_type(self):
        plan = {"sources": [{"source_type": "keyword", "source_value": "anti aging serum"}]}

        self.assertEqual(
            visual_preflight_source_from_plan(plan, "content_url", "https://www.tiktok.com/@creator/video/123"),
            [{"type": "content_url", "value": "https://www.tiktok.com/@creator/video/123"}],
        )
        self.assertEqual(
            visual_preflight_source_from_plan(plan, "auto", "anti aging serum"),
            [{"type": "keyword", "value": "anti aging serum"}],
        )

    def test_visual_preflight_operator_diagnosis_explains_account_matrix(self):
        profile_failed = visual_preflight_operator_diagnosis(
            {
                "funnel": {"content_found": 0, "comment_users": 0, "customer_leads": 0},
                "errors": {"PROFILE_START_FAILED": 3},
                "profile_attempts": [
                    {"profile_id": "p1", "error_code": "PROFILE_START_FAILED"},
                    {"profile_id": "p2", "error_code": "PROFILE_START_FAILED"},
                ],
            }
        )
        empty_results = visual_preflight_operator_diagnosis(
            {
                "funnel": {"content_found": 0, "comment_users": 0, "customer_leads": 0},
                "errors": {"EMPTY_RESULT_RETRY": 3},
                "profile_attempts": [{"profile_id": "p1", "started_browser": True}],
            }
        )

        self.assertEqual(profile_failed["status"], "profiles_not_starting")
        self.assertIn("ixBrowser", profile_failed["next_action"])
        self.assertEqual(empty_results["status"], "opened_but_no_results")
        self.assertIn("视频链接", empty_results["next_action"])

    def test_comment_intent_classifier_marks_purchase_and_exclude(self):
        scorer = CandidateUserScorer.__new__(CandidateUserScorer)
        scorer.intent_classifier = RuleBasedCommentIntentClassifier()

        score, tags, status = scorer.score_candidate(
            {
                "username": "buyer_one",
                "comment_text": "where is the link I want to buy",
                "comment_likes": 5,
                "reply_count": 1,
                "views": 120000,
                "video_comments": 500,
            },
            Counter({"buyer_one": 1}),
        )

        self.assertGreaterEqual(score, 70)
        self.assertEqual(status, "high_value")
        self.assertIn("intent_type:purchase", tags)
        self.assertTrue(any(tag.startswith("intent_confidence:") for tag in tags))

        excluded_score, excluded_tags, excluded_status = scorer.score_candidate(
            {
                "username": "viewer",
                "comment_text": "spoiler meme only",
                "comment_likes": 0,
                "reply_count": 0,
                "views": 0,
                "video_comments": 0,
            },
            Counter({"viewer": 1}),
            exclude_keywords=["spoiler"],
        )

        self.assertEqual(excluded_score, 0)
        self.assertEqual(excluded_status, "low_value")
        self.assertIn("intent_type:exclude", excluded_tags)

    def test_collection_uses_injected_comment_intent_classifier_for_customer_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            classifier = FakeCommentIntentClassifier()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": StaticCommentCollector(),
                    "search": object(),
                },
                comment_intent_classifier=classifier,
            )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            candidates = service.storage.list_candidates_with_content()

            self.assertEqual(classifier.calls, ["buyer_one"])
            self.assertEqual(len(candidates), 1)
            self.assertGreaterEqual(int(candidates[0]["qualify_score"]), 70)
            self.assertIn("ai_purchase", json.loads(candidates[0]["intent_tags"]))
            self.assertEqual(candidates[0]["status"], "high_value")

    def test_action_queue_uses_injected_outreach_copy_recommender(self):
        with tempfile.TemporaryDirectory() as tmp:
            recommender = FakeOutreachCopyRecommender()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": StaticCommentCollector(),
                    "search": object(),
                },
                outreach_copy_recommender=recommender,
            )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            actions = service.storage.list_action_queue(limit=20)

            self.assertEqual([call[0] for call in recommender.calls], ["comment_reply", "follow_review", "dm_review"])
            self.assertEqual(len(actions), 3)
            self.assertTrue(all("AI copy for buyer_one" in row["suggested_text"] for row in actions))
            self.assertTrue(all("copy_provider=fake_copy_ai" in row.get("reason", "") for row in actions))
            self.assertTrue(all("copy_angle=fake ai angle" in row.get("reason", "") for row in actions))

    def test_standalone_browser_adapter_acquires_reuses_and_releases_session(self):
        fake_adapter = FakeBrowserDriverAdapter()
        manager = WorkbenchBrowserAdapter(driver_adapter=fake_adapter, allow_legacy_fallback=False)

        first = manager.acquire("profile-1", "trace-1", account_id="acct-1", proxy_id="proxy-1", max_instances=1)
        second = manager.acquire("profile-1", "trace-2", account_id="acct-1", proxy_id="proxy-1", max_instances=1)

        self.assertIs(first, second)
        self.assertEqual(first.profile_id, "profile-1")
        self.assertTrue(first.instance_id.startswith("ro-"))
        manager.release(first.instance_id, "test_done")

        self.assertTrue(fake_adapter.driver.quit_called)
        self.assertEqual(fake_adapter.closed, [(fake_adapter.client, "profile-1")])

    def test_standalone_browser_adapter_can_disable_legacy_fallback(self):
        fake_adapter = FakeBrowserDriverAdapter(fail=True)
        manager = WorkbenchBrowserAdapter(driver_adapter=fake_adapter, allow_legacy_fallback=False)

        session = manager.acquire("profile-2", "trace-1")

        self.assertIsNone(session)
        self.assertEqual(manager.last_error(), "failed profile profile-2")

    def test_live_action_executor_releases_same_browser_manager(self):
        manager = FakeReleaseManager()
        executor = TikTokSeleniumActionExecutor()

        executor._release((manager, "instance-1"))

        self.assertEqual(manager.released, [("instance-1", "growth_ops_action_completed")])

    def test_profile_preflight_filters_unlogged_accounts_before_action_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            drivers = {
                "logged-in": FakeProfilePreflightDriver("Messages Inbox Profile Upload"),
                "logged-out": FakeProfilePreflightDriver("Log in to continue Sign up"),
                "proxy-bad": FakeProfilePreflightDriver("Proxy error", fail_open=True),
            }
            released = []
            group_manager = FakeProfileGroupManager()

            def factory(profile):
                profile_id = str(profile.get("profile_id") or "")
                driver = drivers.get(profile_id)
                if not driver:
                    return None, None, "missing fixture"
                return driver, (FakeReleaseManager(), profile_id), ""

            checker = ProfilePreflightChecker(
                service.storage,
                ProfilePreflightConfig(max_workers=3, page_load_timeout_seconds=1, wait_after_open_seconds=0),
                driver_factory=factory,
                group_manager=group_manager,
            )
            checker._executor._release = lambda handle: released.append(handle)

            available, summary = checker.available_profiles(
                [
                    {"profile_id": "logged-in", "group_name": "US"},
                    {"profile_id": "logged-out", "group_name": "US"},
                    {"profile_id": "proxy-bad", "group_name": "US"},
                ]
            )

            self.assertEqual([row["profile_id"] for row in available], ["logged-in"])
            self.assertEqual(summary["requested"], 3)
            self.assertEqual(summary["available"], 1)
            self.assertEqual(summary["unavailable"], 2)
            self.assertEqual(summary["errors"]["LOGIN_REQUIRED"], 1)
            self.assertEqual(summary["errors"]["PROXY_FAILED"], 1)
            health = {row["profile_id"]: row for row in service.storage.list_profile_health(limit=10)}
            self.assertEqual(health["logged-in"]["status"], "healthy")
            self.assertEqual(health["logged-out"]["status"], "cooldown")
            self.assertEqual(health["proxy-bad"]["status"], "cooldown")
            self.assertCountEqual(group_manager.moves, [("logged-out", "LOGIN_REQUIRED"), ("proxy-bad", "PROXY_FAILED")])
            self.assertEqual(len(released), 3)

    def test_profile_preflight_detects_visible_login_popup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            group_manager = FakeProfileGroupManager()
            driver = FakeProfilePreflightDriver("For You")
            driver.script_results = [
                {
                    "url": "https://www.tiktok.com/messages",
                    "title": "TikTok - Make Your Day",
                    "loginGate": True,
                    "loggedIn": False,
                    "exactLoginButton": True,
                    "dialogLoginGate": True,
                    "forcedLoginText": False,
                    "labels": ["log in", "sign up"],
                    "dialogs": ["log in to continue sign up"],
                    "sample": "for you",
                }
            ]
            checker = ProfilePreflightChecker(
                service.storage,
                ProfilePreflightConfig(max_workers=1, page_load_timeout_seconds=1, wait_after_open_seconds=0),
                driver_factory=lambda _profile: (driver, (FakeReleaseManager(), "popup-login"), ""),
                group_manager=group_manager,
            )
            checker._executor._release = lambda _handle: None

            available, summary = checker.available_profiles([{"profile_id": "12345", "group_name": "US"}])

            self.assertEqual(available, [])
            self.assertEqual(summary["errors"]["LOGIN_REQUIRED"], 1)
            self.assertEqual(group_manager.moves, [("12345", "LOGIN_REQUIRED")])

    def test_profile_preflight_timeout_marks_profile_unavailable_and_quarantines(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            group_manager = FakeProfileGroupManager()
            driver = BlockingProfilePreflightDriver(block_seconds=0.35)
            checker = ProfilePreflightChecker(
                service.storage,
                ProfilePreflightConfig(
                    max_workers=1,
                    page_load_timeout_seconds=1,
                    wait_after_open_seconds=0,
                    total_timeout_seconds=0.1,
                ),
                driver_factory=lambda _profile: (driver, (FakeReleaseManager(), "slow"), ""),
                group_manager=group_manager,
            )
            checker._executor._release = lambda _handle: None
            started = time.time()

            available, summary = checker.available_profiles([{"profile_id": "12346", "group_name": "US"}])

            self.assertLess(time.time() - started, 0.3)
            self.assertEqual(available, [])
            self.assertEqual(summary["errors"]["PROFILE_PREFLIGHT_TIMEOUT"], 1)
            self.assertEqual(group_manager.moves, [("12346", "PROFILE_PREFLIGHT_TIMEOUT")])
            health = {row["profile_id"]: row for row in service.storage.list_profile_health(limit=10)}
            self.assertEqual(health["12346"]["status"], "cooldown")
            self.assertEqual(health["12346"]["last_error_code"], "PROFILE_PREFLIGHT_TIMEOUT")

    def test_profile_health_recording_is_safe_for_parallel_account_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)

            def record_failure():
                return service.storage.record_profile_health(
                    "parallel-profile",
                    group_name="US",
                    ok=False,
                    error_code="FOLLOW_RATE_LIMITED",
                    error_message="rate limited",
                )

            with ThreadPoolExecutor(max_workers=4) as executor:
                rows = list(executor.map(lambda _idx: record_failure(), range(4)))

            self.assertEqual(len(rows), 4)
            health = {row["profile_id"]: row for row in service.storage.list_profile_health(limit=10)}
            self.assertEqual(list(health), ["parallel-profile"])
            self.assertEqual(health["parallel-profile"]["status"], "cooldown")
            self.assertEqual(health["parallel-profile"]["last_error_code"], "FOLLOW_RATE_LIMITED")

    def test_ix_profile_group_manager_reuses_existing_banned_group_and_moves_profile(self):
        client = FakeIxProfileClient(groups=[{"id": 296456, "title": "封禁账号"}])
        manager = IxProfileGroupManager(client_factory=lambda: client)

        result = manager.move_profile_to_quarantine("22376", reason="LOGIN_REQUIRED")

        self.assertTrue(result.ok)
        self.assertEqual(result.group_id, "296456")
        self.assertEqual(client.created, [])
        self.assertEqual(client.moves, [(22376, 296456)])

    def test_ix_profile_group_manager_creates_banned_group_when_missing(self):
        client = FakeIxProfileClient(groups=[], create_response={"data": {"id": 888}})
        manager = IxProfileGroupManager(client_factory=lambda: client)

        result = manager.move_profile_to_quarantine("22377", reason="COMMENT_ACCESS_GATED")

        self.assertTrue(result.ok)
        self.assertEqual(result.group_id, "888")
        self.assertEqual(client.created, [("封禁账号", 0)])
        self.assertEqual(client.moves, [(22377, 888)])

    def test_action_preflight_blocks_when_profile_preflight_finds_no_logged_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            plan = service.create_campaign_plan("#skincare", max_sources=1)
            batch = service.storage.create_collection_batch(1, profile_group="US", campaign_id=plan["campaign"]["id"])

            class Args:
                base_dir = tmp
                campaign_id = plan["campaign"]["id"]
                batch_id = batch.id
                profile_group = "US"
                profile_ids = "logged-out-1,logged-out-2"
                workers = 2
                per_profile_limit = 3
                switch_attempts = 2
                action_types = "comment_reply,follow_review,dm_review"
                limit = 6
                per_profile_hour_limit = 10
                per_profile_video_hour_limit = 2
                page_timeout = 1
                element_timeout = 1
                skip_profile_preflight = False
                preflight_workers = 2
                profile_page_timeout = 1
                profile_wait = 0

            with patch(
                "tools.reachops_action_preflight_existing_batch.ProfilePreflightChecker.available_profiles",
                return_value=(
                    [],
                    {
                        "requested": 2,
                        "checked": 2,
                        "available": 0,
                        "unavailable": 2,
                        "errors": {"LOGIN_REQUIRED": 2},
                        "results": [
                            {"profile_id": "logged-out-1", "ok": False, "error_code": "LOGIN_REQUIRED"},
                            {"profile_id": "logged-out-2", "ok": False, "error_code": "LOGIN_REQUIRED"},
                        ],
                    },
                ),
            ):
                result = run_reachops_action_preflight_existing_batch(Args())

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["error_code"], "NO_LOGGED_IN_PROFILE_AVAILABLE")
            self.assertTrue(result["no_submit"])
            self.assertEqual(result["profile_preflight"]["available"], 0)
            self.assertEqual(result["profile_preflight"]["errors"]["LOGIN_REQUIRED"], 2)
            self.assertEqual(result["executable_profiles"], [])

    def test_live_action_executor_writes_screenshot_sidecar_metadata(self):
        class ScreenshotDriver:
            current_url = "https://www.tiktok.com/@creator/video/123"
            title = "TikTok test page"

            def save_screenshot(self, path):
                Path(path).write_bytes(b"png")
                return True

        with tempfile.TemporaryDirectory() as tmp:
            executor = TikTokSeleniumActionExecutor(TikTokActionExecutorConfig(evidence_dir=tmp))
            path = executor._capture_evidence(
                ScreenshotDriver(),
                {"id": "action-1", "action_type": "comment_reply", "target_url": "https://www.tiktok.com/@creator/video/123"},
                "profile-1",
                "ok",
            )

            self.assertTrue(Path(path).exists())
            sidecar = Path(f"{path}.json")
            self.assertTrue(sidecar.exists())
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(payload["profile_id"], "profile-1")
            self.assertEqual(payload["action_type"], "comment_reply")
            self.assertEqual(payload["screenshot_size"], 3)
            self.assertEqual(payload["screenshot_sha256"], hashlib.sha256(b"png").hexdigest())

    def test_live_action_executor_normalizes_rate_limit_by_action_type(self):
        class RateLimitedDriver:
            current_url = "https://www.tiktok.com/@creator"
            title = "TikTok"

            def get(self, _url):
                return None

            def set_page_load_timeout(self, _seconds):
                return None

            def execute_script(self, script, *args):
                if "document.body ? document.body.innerText" in script:
                    return "try again later limit reached"
                return None

            def find_elements(self, _by, _selector):
                return []

        executor = TikTokSeleniumActionExecutor(
            driver_factory=lambda _profile: (RateLimitedDriver(), None, "")
        )

        cases = [
            (
                {"id": "a1", "action_type": "comment_reply", "source_path": "https://www.tiktok.com/@creator/video/1"},
                "COMMENT_BLOCKED",
            ),
            (
                {"id": "a2", "action_type": "follow_review", "target_url": "https://www.tiktok.com/@creator"},
                "FOLLOW_RATE_LIMITED",
            ),
            (
                {"id": "a3", "action_type": "dm_review", "target_url": "https://www.tiktok.com/@creator"},
                "DM_RATE_LIMITED",
            ),
        ]

        for action, expected_code in cases:
            with self.subTest(action_type=action["action_type"]):
                result = executor.execute(action, {"profile_id": "profile-1"}, "hello", dry_run=False)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error_code"], expected_code)

    def test_runtime_paths_are_independent_and_exclude_auth_from_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.build(tmp).ensure_dirs()

            self.assertEqual(paths.base_dir, os.path.abspath(tmp))
            self.assertTrue(paths.data_dir.endswith(os.path.join(tmp, "data")))
            self.assertTrue(paths.config_dir.endswith(os.path.join(tmp, "config")))
            self.assertTrue(paths.reports_dir.endswith(os.path.join(tmp, "data", "growth_intelligence", "reports")))
            self.assertTrue(paths.db_path.endswith(os.path.join(tmp, "data", "growth_intelligence", "growth_intelligence.db")))
            self.assertTrue(paths.activation_status_path.endswith(os.path.join(tmp, "config", "reachops_activation_status.json")))

    def test_runtime_paths_default_to_user_data_dir(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\ops\AppData\Local"}, clear=True):
            paths = RuntimePaths.build(cwd=r"C:\Program Files\ReachOps")

        self.assertEqual(paths.base_dir, os.path.abspath(os.path.join(r"C:\Users\ops\AppData\Local", "ReachOps")))
        self.assertTrue(paths.data_dir.endswith(os.path.join("ReachOps", "data")))
        self.assertTrue(paths.config_dir.endswith(os.path.join("ReachOps", "config")))

    def test_campaign_funnel_is_formal_schema(self):
        funnel = CampaignFunnel(campaign_id="cmp_1", target_sources=2, comment_users=3)

        self.assertEqual(funnel.campaign_id, "cmp_1")
        self.assertEqual(funnel.target_sources, 2)
        self.assertEqual(funnel.comment_users, 3)
        self.assertTrue(funnel.generated_at.endswith("Z"))

    def test_goal_status_report_keeps_real_platform_submit_pending(self):
        passed_names = [
            "输入产品/关键词即可创建获客任务",
            "AI/规则能生成产品分析",
            "外部 AI 故障可自动降级规则策略",
            "系统能自动生成受众画像",
            "AI/规则能生成意图分类和话术建议",
            "系统能自动规划来源",
            "AI/规则能扩展获客来源",
            "人工可编辑策略可保存并进入报告",
            "系统能发现内容",
            "系统能采集互动用户",
            "系统能识别购买/咨询意向",
            "系统能生成客户线索",
            "系统能生成触达动作",
            "系统能执行预检",
            "真实提交验收入口默认阻止误提交",
            "真实提交验收入口支持授权证据校验",
            "真实执行成功必须有有效证据",
            "授权门覆盖设备绑定、过期和能力限制",
            "账号失败能自动换号",
            "私信/关注失败能降级评论",
            "全程有实时漏斗",
            "全程有错误码和证据",
            "可导出客户名单和执行报告",
            "独立配置/数据/授权目录存在",
            "Windows 打包入口存在",
            "升级清单和安装校验机制可用",
        ]
        audit = {
            "status": "ok",
            "campaign_id": "acq_1",
            "batch_id": "batch_1",
            "checks": [{"name": name, "status": "passed", "evidence": {}} for name in passed_names]
            + [
                {
                    "name": "授权允许时能真实执行",
                    "status": "pending_external_validation",
                    "evidence": {"reason": "needs platform live submit"},
                },
                {
                    "name": "真实 TikTok 平台提交",
                    "status": "pending_external_validation",
                    "evidence": {"reason": "needs authorized real account"},
                }
            ],
        }

        report = build_goal_status_report(audit)

        self.assertEqual(report["status"], "ready_for_external_validation")
        self.assertIn("授权允许时能真实执行", report["pending_external_validation"])
        self.assertIn("真实 TikTok 平台提交", report["pending_external_validation"])
        stage3 = next(row for row in report["stages"] if row["name"] == "阶段 3：真实执行")
        self.assertEqual(stage3["status"], "pending_external_validation")
        self.assertEqual(report["summary"]["final_failed"], 0)
        self.assertEqual(report["summary"]["final_pending_external_validation"], 2)

    def test_goal_status_report_passes_when_platform_submit_is_verified(self):
        png_sha = hashlib.sha256(b"png").hexdigest()

        def detail(action_type):
            return [
                {
                    "path": f"C:/evidence/{action_type}.png",
                    "size": 3,
                    "sha256": png_sha,
                    "sidecar_path": f"C:/evidence/{action_type}.png.json",
                    "sidecar": {
                        "screenshot_sha256": png_sha,
                        "action_type": action_type,
                        "profile_id": "10001",
                        "action_id": f"{action_type}-1",
                        "current_url": "https://www.tiktok.com/@creator/video/123",
                    },
                }
            ]

        report = build_goal_status_report(
            {
                "status": "ok",
                "campaign_id": "acq_1",
                "batch_id": "batch_1",
                "checks": [
                    {"name": name, "status": "passed", "evidence": {}}
                    for name in [
                        "输入产品/关键词即可创建获客任务",
                        "AI/规则能生成产品分析",
                        "外部 AI 故障可自动降级规则策略",
                        "系统能自动生成受众画像",
                        "AI/规则能生成意图分类和话术建议",
                        "系统能自动规划来源",
                        "AI/规则能扩展获客来源",
                        "人工可编辑策略可保存并进入报告",
                        "系统能发现内容",
                        "系统能采集互动用户",
                        "系统能识别购买/咨询意向",
                        "系统能生成客户线索",
                        "系统能生成触达动作",
                        "系统能执行预检",
                        "授权允许时能真实执行",
                        "真实提交验收入口默认阻止误提交",
                        "真实提交验收入口支持授权证据校验",
                        "真实执行成功必须有有效证据",
                        "授权门覆盖设备绑定、过期和能力限制",
                        "真实 TikTok 平台提交",
                        "账号失败能自动换号",
                        "私信/关注失败能降级评论",
                        "全程有实时漏斗",
                        "全程有错误码和证据",
                        "可导出客户名单和执行报告",
                        "独立配置/数据/授权目录存在",
                        "Windows 打包入口存在",
                        "升级清单和安装校验机制可用",
                    ]
                ],
            },
            acceptance_summary={
                "status": "passed",
                "delivery_audit": {
                    "status": "ok",
                    "passed": 26,
                    "failed": 0,
                    "pending_external_validation": 2,
                    "resolved_external_validation": 2,
                    "effective_pending_external_validation": 0,
                },
                "operator_pressure": {
                    "status": "ok",
                    "campaign_count": 3,
                    "content_found": 15,
                    "comment_users": 27,
                    "customer_leads": 27,
                    "outreach_actions": 81,
                    "execution_success": 8,
                    "account_switched": 3,
                },
                "installer_smoke": {"status": "ok", "exe_exists": True, "data_in_install_dir": False, "hash_ok": True},
                "ui_startup": {"status": "ok", "process_running": True, "interactive_task": True},
                "live_validation": {"status": "ready", "no_browser_started": True, "no_submit": True},
                "live_submit": {
                    "status": "completed",
                    "platform_validation": True,
                    "activation_status_loaded": True,
                    "evidence_by_action_type": {
                        "comment_reply": ["C:/evidence/comment_reply.png"],
                        "follow_review": ["C:/evidence/follow_review.png"],
                        "dm_review": ["C:/evidence/dm_review.png"],
                    },
                    "evidence_file_details": {
                        "comment_reply": detail("comment_reply"),
                        "follow_review": detail("follow_review"),
                        "dm_review": detail("dm_review"),
                    },
                    "missing_evidence_action_types": [],
                    "missing_local_evidence_file_action_types": [],
                },
                "goal_status": {
                    "status": "passed",
                    "summary": {"stages_passed": 5, "stages_pending_external_validation": 0, "stages_failed": 0},
                    "pending_external_validation": [],
                },
            },
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["pending_external_validation"], [])
        self.assertEqual(report["summary"]["stages_passed"], 5)

    def test_campaign_report_exports_current_customers_and_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            campaign_id = plan["campaign"]["id"]
            result = service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(
                    campaign_id=campaign_id,
                    max_videos_per_creator=1,
                    max_comments_per_video=10,
                    task_delay_min_seconds=30,
                    task_delay_max_seconds=30,
                    test_mode=True,
                ),
            )
            self.assertEqual(result.processed_sources, 1)

            workflow = GrowthWorkflowService(service)
            funnel = workflow.build_campaign_funnel(campaign_id=campaign_id)
            self.assertEqual(funnel["campaign_id"], campaign_id)
            self.assertEqual(funnel["target_sources"], 1)
            self.assertGreaterEqual(funnel["comment_users"], 1)
            self.assertGreaterEqual(funnel["customer_leads"], 1)
            self.assertGreaterEqual(funnel["outreach_actions"], 1)

            artifacts = workflow.export_campaign_artifacts(campaign_id=campaign_id)
            for key in ["json_path", "sources_csv_path", "customers_csv_path", "actions_csv_path"]:
                self.assertTrue(os.path.exists(artifacts[key]), key)

            with open(artifacts["json_path"], "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertEqual(payload["campaign"]["id"], campaign_id)
            self.assertEqual(payload["funnel"]["campaign_id"], campaign_id)
            self.assertEqual(len(payload["candidate_users"]), 1)
            self.assertGreaterEqual(len(payload["operation_leads"]), 1)
            self.assertGreaterEqual(len(payload["action_queue"]), 1)
            self.assertEqual(payload["strategy"]["campaign_id"], campaign_id)
            self.assertTrue(payload["strategy"]["intent_taxonomy"])
            self.assertIn("intent_taxonomy", payload["strategy"]["editable_fields"])

            with open(artifacts["customers_csv_path"], "r", encoding="utf-8") as fh:
                customers = list(csv.DictReader(fh))
            self.assertEqual(customers[0]["username"], "buyer_one")
            self.assertIn("where can I buy", customers[0]["comment_text"])

            with open(artifacts["actions_csv_path"], "r", encoding="utf-8") as fh:
                actions = list(csv.DictReader(fh))
            self.assertTrue(actions)
            self.assertEqual(actions[0]["target_username"], "buyer_one")

    def test_campaign_report_export_paths_do_not_overwrite_same_second_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            workflow = GrowthWorkflowService(service)
            campaign_ids = []
            exported = []

            for idx, target in enumerate(["https://www.tiktok.com/@beauty_creator", "https://www.tiktok.com/@hair_creator"]):
                plan = service.create_campaign_plan(target, max_sources=1)
                campaign_id = plan["campaign"]["id"]
                campaign_ids.append(campaign_id)
                result = service.run_collection(
                    [{"type": "creator_url", "value": target}],
                    [{"profile_id": f"discovery-{idx}", "group_name": "US"}],
                    GrowthTaskConfig(
                        campaign_id=campaign_id,
                        max_videos_per_creator=1,
                        max_comments_per_video=10,
                        task_delay_min_seconds=30,
                        task_delay_max_seconds=30,
                        test_mode=True,
                    ),
                )
                self.assertEqual(result.processed_sources, 1)
                exported.append(workflow.export_campaign_artifacts(campaign_id=campaign_id))

            for key in ["json_path", "sources_csv_path", "customers_csv_path", "actions_csv_path"]:
                paths = [row[key] for row in exported]
                self.assertEqual(len(set(paths)), len(paths), key)
                self.assertTrue(all(os.path.exists(path) for path in paths), key)

            payloads = []
            for artifacts in exported:
                with open(artifacts["json_path"], "r", encoding="utf-8") as fh:
                    payloads.append(json.load(fh))
            self.assertEqual([payload["campaign"]["id"] for payload in payloads], campaign_ids)

    def test_campaign_plan_returns_editable_acquisition_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("anti aging serum", max_sources=3)

            strategy = plan["strategy"]
            self.assertEqual(strategy["campaign_id"], plan["campaign"]["id"])
            self.assertEqual(strategy["product_analysis"]["category"], "beauty")
            self.assertTrue(strategy["audience_profile"]["interests"])
            self.assertTrue(strategy["source_expansion"])
            self.assertTrue(any(row["intent_type"] == "purchase" for row in strategy["intent_taxonomy"]))
            self.assertTrue(any(row["action_type"] == "comment_reply" for row in strategy["outreach_recommendations"]))
            self.assertIn("source_expansion", strategy["editable_fields"])

    def test_amazon_product_link_becomes_executable_social_search_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan(
                "https://www.amazon.com/Retinol-Anti-Aging-Face-Serum/dp/B0ABC12345?tag=test",
                max_sources=6,
            )

            self.assertEqual(plan["campaign"]["input_type"], "product_url")
            self.assertEqual(plan["campaign"]["category"], "beauty")
            self.assertIn("Retinol Anti Aging Face Serum", plan["campaign"]["product_name"])
            self.assertTrue(plan["sources"])
            source_pairs = [(row["source_type"], row["source_value"]) for row in plan["sources"]]
            self.assertIn(("keyword", "Retinol Anti Aging Face Serum"), source_pairs)
            self.assertIn(("keyword", "Retinol Anti Aging Face Serum review"), source_pairs)
            self.assertIn(("keyword", "Retinol Anti Aging Face Serum before after"), source_pairs)
            self.assertTrue(any(row["source_type"] == "hashtag" for row in plan["sources"]))
            self.assertTrue(any("核心产品词" in row["reason"] for row in plan["sources"]))
            self.assertTrue(any("评测内容" in row["reason"] for row in plan["sources"]))

            summary = format_campaign_plan_summary(
                plan,
                {"max_videos": 5, "max_comments": 10, "profile_limit": 3, "task_interval": 60},
                "Canada",
            )
            self.assertIn("识别结果：商品页", summary)
            self.assertIn("推广对象：Retinol Anti Aging Face Serum", summary)
            self.assertIn("执行路径：分析目标 -> 规划来源 -> 找相关视频/达人/话题 -> 扫评论区", summary)
            self.assertIn("采集来源：关键词搜索", summary)
            self.assertIn("来源分层：核心产品内容 -> 评测/对比内容 -> 效果验证内容", summary)
            self.assertIn("账号分组 Canada", summary)
            self.assertIn("每来源最多 5 条视频", summary)
            self.assertIn("每视频最多 10 条评论", summary)

    def test_campaign_analyzer_detects_live_room_before_creator_profile(self):
        analyzer = CampaignAnalyzer()

        self.assertEqual(
            analyzer.detect_input_type("https://www.tiktok.com/@beauty_creator/live"),
            "live_room_url",
        )

    def test_operator_strategy_overrides_are_persisted_and_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("anti aging serum", max_sources=2)
            campaign_id = plan["campaign"]["id"]
            service.save_campaign_strategy_overrides(
                campaign_id,
                {
                    "product_analysis": {
                        "primary_offer": "Send buyers to the official serum bundle page.",
                        "customer_problem": "Buyer asks whether the serum works for sensitive skin.",
                    },
                    "intent_taxonomy": [
                        {
                            "intent_type": "purchase",
                            "keywords": ["where to buy", "price", "official link"],
                            "score_hint": 90,
                            "operator_note": "Treat these comments as priority customers.",
                        }
                    ],
                    "outreach_recommendations": [
                        {
                            "action_type": "comment_reply",
                            "priority": 1,
                            "template_angle": "Reply with safe usage detail and official page direction.",
                            "risk_level": "medium",
                        }
                    ],
                },
                updated_by="operator-a",
            )

            strategy = service.build_campaign_strategy(campaign_id)
            self.assertTrue(strategy["overrides_applied"])
            self.assertEqual(strategy["overrides_updated_by"], "operator-a")
            self.assertEqual(strategy["product_analysis"]["primary_offer"], "Send buyers to the official serum bundle page.")
            self.assertEqual(strategy["intent_taxonomy"][0]["keywords"], ["where to buy", "price", "official link"])
            self.assertEqual(strategy["outreach_recommendations"][0]["template_angle"], "Reply with safe usage detail and official page direction.")

            workflow = GrowthWorkflowService(service)
            artifacts = workflow.export_campaign_artifacts(campaign_id=campaign_id)
            with open(artifacts["json_path"], "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertTrue(payload["strategy"]["overrides_applied"])
            self.assertEqual(payload["strategy"]["product_analysis"]["customer_problem"], "Buyer asks whether the serum works for sensitive skin.")

    def test_campaign_plan_accepts_pluggable_ai_intelligence_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeAcquisitionIntelligenceProvider()
            service = GrowthIntelligenceService(base_dir=tmp, browser_factory=lambda _profile_id: FakeDriver(), intelligence_provider=provider)
            plan = service.create_campaign_plan("episode finder", intent_keywords=["download"], exclude_keywords=["spoiler"], max_sources=2)

            self.assertEqual(provider.calls[0]["input_type"], "keyword")
            self.assertEqual(plan["campaign"]["category"], "digital_content")
            self.assertEqual(plan["campaign"]["product_name"], "Episode Finder")
            self.assertEqual(plan["persona"]["demographics"]["intelligence_provider"], "fake_ai_provider")
            self.assertIn("short drama", plan["persona"]["interests"])
            self.assertIn("spoiler", plan["persona"]["exclude_keywords"])
            self.assertEqual([row["source_value"] for row in plan["sources"]], ["episode finder app", "shortdrama"])
            strategy = plan["strategy"]
            self.assertEqual(strategy["generator"], "fake_ai_provider")
            self.assertEqual(strategy["product_analysis"]["customer_problem"], "Users need the episode source.")
            self.assertEqual(strategy["audience_profile"]["persona"], "viewer asking for episode links")
            self.assertEqual(strategy["outreach_recommendations"][0]["template_angle"], "answer episode source")

    def test_http_ai_provider_accepts_chat_style_json_response(self):
        calls = []

        def requester(endpoint, payload, headers, timeout_seconds):
            calls.append({"endpoint": endpoint, "payload": payload, "headers": headers, "timeout_seconds": timeout_seconds})
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "product_analysis": {
                                        "category": "pet_supplies",
                                        "product_name": "Portable Water Bowl",
                                        "customer_problem": "Dog owners need water during walks.",
                                        "primary_offer": "Offer a lightweight bottle bowl.",
                                        "keywords": ["dog water bottle", "walk"],
                                    },
                                    "audience_profile": {
                                        "persona": "dog owner asking where to buy",
                                        "interests": ["dog walking"],
                                        "pain_points": ["portable hydration"],
                                        "buying_triggers": ["where to buy"],
                                    },
                                    "intent_taxonomy": [
                                        {"intent_type": "purchase", "keywords": ["where to buy"], "score_hint": 85}
                                    ],
                                    "source_suggestions": [
                                        {"source_type": "keyword", "source_value": "dog water bottle review", "reason": "ai source", "priority": 90}
                                    ],
                                    "outreach_recommendations": [
                                        {"action_type": "comment_reply", "priority": 1, "template_angle": "answer product source", "risk_level": "medium"}
                                    ],
                                }
                            )
                        }
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as tmp:
            provider = HTTPAcquisitionIntelligenceProvider(
                endpoint="https://ai.local/analyze",
                api_key="test-key",
                model="test-model",
                requester=requester,
            )
            service = GrowthIntelligenceService(base_dir=tmp, browser_factory=lambda _profile_id: FakeDriver(), intelligence_provider=provider)
            plan = service.create_campaign_plan("portable dog water bottle", max_sources=1)

            self.assertEqual(calls[0]["endpoint"], "https://ai.local/analyze")
            self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-key")
            self.assertEqual(calls[0]["payload"]["model"], "test-model")
            self.assertEqual(plan["campaign"]["category"], "pet_supplies")
            self.assertEqual(plan["campaign"]["product_name"], "Portable Water Bowl")
            self.assertEqual(plan["persona"]["demographics"]["intelligence_provider"], "http_ai_provider")
            self.assertEqual(plan["sources"][0]["source_value"], "dog water bottle review")
            self.assertEqual(plan["strategy"]["generator"], "http_ai_provider")

    def test_http_ai_provider_falls_back_to_rules_when_request_fails(self):
        def requester(_endpoint, _payload, _headers, _timeout_seconds):
            raise TimeoutError("simulated timeout")

        with tempfile.TemporaryDirectory() as tmp:
            provider = HTTPAcquisitionIntelligenceProvider(
                endpoint="https://ai.local/analyze",
                requester=requester,
                provider_name="configured_ai",
            )
            service = GrowthIntelligenceService(base_dir=tmp, browser_factory=lambda _profile_id: FakeDriver(), intelligence_provider=provider)
            plan = service.create_campaign_plan("anti aging serum", max_sources=1)

            self.assertEqual(plan["strategy"]["generator"], "configured_ai_fallback_rules")
            self.assertEqual(plan["strategy"]["product_analysis"]["category"], "beauty")
            self.assertEqual(plan["strategy"]["product_analysis"]["intelligence_provider"], "configured_ai_fallback_rules")

    def test_action_router_runs_only_current_campaign_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            p1 = service.create_campaign_plan("https://www.tiktok.com/@old_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@old_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=p1["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            old_batch = service.storage.latest_collection_batch_for_campaign(p1["campaign"]["id"])

            p2 = service.create_campaign_plan("https://www.tiktok.com/@new_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@new_creator"}],
                [{"profile_id": "discovery-2", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=p2["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            new_batch = service.storage.latest_collection_batch_for_campaign(p2["campaign"]["id"])

            workflow = GrowthWorkflowService(service)
            result = workflow.run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(max_workers=1, per_profile_action_limit=10, action_types=["comment_reply"], dry_run=True),
                export_report=False,
            )
            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["success"], 1)

            old_actions = service.storage.list_action_queue(limit=20, batch_id=old_batch["id"])
            new_actions = service.storage.list_action_queue(limit=20, batch_id=new_batch["id"])
            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "pending_review" for row in old_actions))
            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "success" for row in new_actions))

    def test_action_router_can_target_explicit_campaign_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            old_plan = service.create_campaign_plan("https://www.tiktok.com/@old_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@old_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=old_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            old_batch = service.storage.latest_collection_batch_for_campaign(old_plan["campaign"]["id"])

            new_plan = service.create_campaign_plan("https://www.tiktok.com/@new_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@new_creator"}],
                [{"profile_id": "discovery-2", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=new_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            new_batch = service.storage.latest_collection_batch_for_campaign(new_plan["campaign"]["id"])

            workflow = GrowthWorkflowService(service)
            result = workflow.run_action_router(
                [{"profile_id": "exec-old", "group_name": "US"}],
                config=ActionRouterConfig(max_workers=1, per_profile_action_limit=10, action_types=["comment_reply"], dry_run=True),
                campaign_id=old_plan["campaign"]["id"],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            old_actions = service.storage.list_action_queue(limit=20, batch_id=old_batch["id"])
            new_actions = service.storage.list_action_queue(limit=20, batch_id=new_batch["id"])
            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "success" for row in old_actions))
            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "pending_review" for row in new_actions))

    def test_action_router_can_switch_account_when_worker_count_is_one(self):
        class ProfileAwareExecutor:
            def execute(self, action, profile, rendered_text, dry_run=True):
                profile_id = str(profile.get("profile_id") or "")
                if profile_id == "exec-1":
                    return {
                        "status": "failed",
                        "error_code": "PAGE_OPEN_FAILED",
                        "error_message": "fixture page failed",
                        "evidence_path": "evidence://switch/failed",
                    }
                return {
                    "status": "success",
                    "error_code": "",
                    "error_message": "",
                    "evidence_path": "evidence://switch/success",
                }

        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}, {"profile_id": "exec-2", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    max_switch_attempts=2,
                    action_types=["comment_reply"],
                    dry_run=True,
                ),
                platform_executor=ProfileAwareExecutor(),
                limit=20,
                export_report=False,
            )

            self.assertEqual(result["worker_count"], 1)
            self.assertEqual(result["available_profile_count"], 2)
            self.assertGreaterEqual(result["account_switched"], 1)
            self.assertGreaterEqual(result["success"], 1)
            self.assertIn("exec-2", [row.get("profile_id") for row in result["results"] if row.get("status") == "success"])

    def test_campaign_funnel_counts_only_current_batch_execution_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            old_plan = service.create_campaign_plan("https://www.tiktok.com/@old_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@old_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=old_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            old_batch = service.storage.latest_collection_batch_for_campaign(old_plan["campaign"]["id"])
            workflow = GrowthWorkflowService(service)
            workflow.run_action_router(
                [{"profile_id": "exec-old", "group_name": "US"}],
                config=ActionRouterConfig(max_workers=1, per_profile_action_limit=10, action_types=["comment_reply"], dry_run=True),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success"}],
                export_report=False,
            )
            old_funnel = workflow.build_campaign_funnel(campaign_id=old_plan["campaign"]["id"], batch_id=old_batch["id"])
            self.assertEqual(old_funnel["execution_success"], 1)
            self.assertEqual(old_funnel["preflight_ok"], 1)

            new_plan = service.create_campaign_plan("https://www.tiktok.com/@new_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@new_creator"}],
                [{"profile_id": "discovery-2", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=new_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            new_batch = service.storage.latest_collection_batch_for_campaign(new_plan["campaign"]["id"])
            new_funnel = workflow.build_campaign_funnel(campaign_id=new_plan["campaign"]["id"], batch_id=new_batch["id"])

            self.assertEqual(new_funnel["campaign_id"], new_plan["campaign"]["id"])
            self.assertEqual(new_funnel["batch_id"], new_batch["id"])
            self.assertEqual(new_funnel["execution_success"], 0)
            self.assertEqual(new_funnel["preflight_ok"], 0)
            self.assertEqual(new_funnel["account_switches"], 0)

    def test_workbench_snapshot_can_stay_on_active_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            old_plan = service.create_campaign_plan("https://www.tiktok.com/@old_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@old_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=old_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            old_batch = service.storage.latest_collection_batch_for_campaign(old_plan["campaign"]["id"])

            new_plan = service.create_campaign_plan("https://www.tiktok.com/@new_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@new_creator"}],
                [{"profile_id": "discovery-2", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=new_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            workflow = GrowthWorkflowService(service)
            active_snapshot = workflow.build_snapshot(campaign_id=old_plan["campaign"]["id"], batch_id=old_batch["id"])
            latest_snapshot = workflow.build_snapshot()

            self.assertEqual(active_snapshot.campaign_funnel["campaign_id"], old_plan["campaign"]["id"])
            self.assertEqual(active_snapshot.campaign_funnel["batch_id"], old_batch["id"])
            self.assertEqual(latest_snapshot.campaign_funnel["campaign_id"], new_plan["campaign"]["id"])
            self.assertNotEqual(active_snapshot.campaign_funnel["campaign_id"], latest_snapshot.campaign_funnel["campaign_id"])
            self.assertTrue(active_snapshot.candidate_users)
            self.assertTrue(active_snapshot.action_queue)
            self.assertTrue(latest_snapshot.candidate_users)
            self.assertTrue(latest_snapshot.action_queue)
            self.assertTrue(all(row["batch_id"] == old_batch["id"] for row in active_snapshot.candidate_users))
            self.assertTrue(all(row["batch_id"] == old_batch["id"] for row in active_snapshot.action_queue))
            self.assertTrue(all(row["batch_id"] != old_batch["id"] for row in latest_snapshot.candidate_users))
            self.assertTrue(all(row["batch_id"] != old_batch["id"] for row in latest_snapshot.action_queue))
            self.assertEqual(active_snapshot.action_review_summary["total"], len(active_snapshot.action_queue))
            self.assertEqual(active_snapshot.execution_readiness_summary["total"], len(active_snapshot.action_queue))
            self.assertEqual(latest_snapshot.action_review_summary["total"], len(latest_snapshot.action_queue))
            self.assertEqual(latest_snapshot.execution_readiness_summary["total"], len(latest_snapshot.action_queue))

    def test_start_page_kpis_use_current_campaign_funnel_not_cumulative_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            old_plan = service.create_campaign_plan("https://www.tiktok.com/@old_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@old_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=old_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            new_plan = service.create_campaign_plan("https://www.tiktok.com/@new_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@new_creator"}],
                [{"profile_id": "discovery-2", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=new_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            batch = service.storage.latest_collection_batch_for_campaign(new_plan["campaign"]["id"])
            snapshot = GrowthWorkflowService(service).build_snapshot(campaign_id=new_plan["campaign"]["id"], batch_id=batch["id"])
            console = GrowthOpsConsole.__new__(GrowthOpsConsole)

            self.assertGreater(snapshot.summary["candidates"], snapshot.campaign_funnel["comment_users"])
            self.assertEqual(console._summary_value(snapshot, "candidates"), snapshot.campaign_funnel["comment_users"])
            self.assertEqual(console._summary_value(snapshot, "action_queue"), snapshot.campaign_funnel["outreach_actions"])

    def test_action_router_dm_fallback_comment_stays_in_current_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            batch = service.storage.latest_collection_batch_for_campaign(plan["campaign"]["id"])

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(max_workers=1, per_profile_action_limit=10, action_types=["dm_review"], dry_run=True),
                fixture_outcomes=[
                    {"action_type": "dm_review", "status": "failed", "error_code": "DM_NOT_ALLOWED"},
                    {"action_type": "comment_reply", "status": "success"},
                ],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual([row["action_type"] for row in result["results"]], ["dm_review", "comment_reply"])
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["success"], 1)
            actions = service.storage.list_action_queue(limit=20, batch_id=batch["id"])
            fallback = next(row for row in actions if row["action_type"] == "comment_reply")
            self.assertEqual(fallback["batch_id"], batch["id"])
            self.assertEqual(fallback["status"], "success")

    def test_live_submit_requires_authorization_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                ),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success"}],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_NOT_AUTHORIZED"], 1)

    def test_live_submit_requires_execution_evidence_after_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                ),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success"}],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_EVIDENCE_MISSING"], 1)

    def test_live_submit_rejects_expired_activation_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2000-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                ),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success", "evidence_path": "evidence://unused"}],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_LICENSE_EXPIRED"], 1)

    def test_live_submit_rejects_action_when_capability_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": False},
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["follow_review"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                ),
                fixture_outcomes=[{"action_type": "follow_review", "status": "success", "evidence_path": "evidence://unused"}],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_NOT_AUTHORIZED"], 1)

    def test_live_submit_allowed_when_activation_status_enables_feature_and_evidence_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {
                            "live_submit": True,
                            "comment_reply": True,
                            "follow_review": True,
                            "dm_review": True,
                        },
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                ),
                fixture_outcomes=[
                    {
                        "action_type": "comment_reply",
                        "status": "success",
                        "evidence_path": "evidence://live-submit/comment-1",
                    }
                ],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["success"], 1)
            self.assertEqual(result["errors"], {})

    def test_live_submit_rejects_missing_local_evidence_file_even_when_authorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                    require_execution_evidence=True,
                ),
                fixture_outcomes=[
                    {
                        "action_type": "comment_reply",
                        "status": "success",
                        "evidence_path": str(Path(tmp) / "missing-evidence.png"),
                    }
                ],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_EVIDENCE_MISSING"], 1)

    def test_live_submit_accepts_valid_local_evidence_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    },
                    fh,
                )
            evidence_path = Path(tmp) / "comment-evidence.png"
            evidence_path.write_bytes(b"png")
            with open(f"{evidence_path}.json", "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                        "action_type": "comment_reply",
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                    require_execution_evidence=True,
                ),
                fixture_outcomes=[
                    {
                        "action_type": "comment_reply",
                        "status": "success",
                        "evidence_path": str(evidence_path),
                    }
                ],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["success"], 1)
            self.assertEqual(result["errors"], {})

    def test_live_submit_rejects_activation_bound_to_another_device(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"REACHOPS_DEVICE_ID": "device-a"}, clear=False):
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "device_id": "device-b",
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                ),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success", "evidence_path": "evidence://unused"}],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_DEVICE_MISMATCH"], 1)

    def test_live_submit_allows_activation_bound_to_current_device(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"REACHOPS_DEVICE_ID": "device-a"}, clear=False):
            service = make_reachops_service(tmp)
            status_path = service.paths.activation_status_path
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": True,
                        "device_id": "device-a",
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    },
                    fh,
                )
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=10,
                    action_types=["comment_reply"],
                    dry_run=False,
                    live_preflight_only=False,
                    allow_live_submit=True,
                ),
                fixture_outcomes=[
                    {
                        "action_type": "comment_reply",
                        "status": "success",
                        "evidence_path": "evidence://live-submit/device-bound",
                    }
                ],
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["success"], 1)
            self.assertEqual(result["errors"], {})

    def test_action_execution_report_exports_only_current_campaign_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            old_plan = service.create_campaign_plan("https://www.tiktok.com/@old_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@old_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=old_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            old_batch = service.storage.latest_collection_batch_for_campaign(old_plan["campaign"]["id"])
            GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-old", "group_name": "US"}],
                config=ActionRouterConfig(max_workers=1, per_profile_action_limit=10, action_types=["comment_reply"], dry_run=True),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success"}],
                export_report=False,
            )

            new_plan = service.create_campaign_plan("https://www.tiktok.com/@new_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@new_creator"}],
                [{"profile_id": "discovery-2", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=new_plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            new_batch = service.storage.latest_collection_batch_for_campaign(new_plan["campaign"]["id"])
            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-new", "group_name": "US"}],
                config=ActionRouterConfig(max_workers=1, per_profile_action_limit=10, action_types=["comment_reply"], dry_run=True),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success"}],
                export_report=True,
            )

            self.assertEqual(result["selected_actions"], 1)
            self.assertEqual(result["report"]["execution_count"], 1)
            self.assertGreaterEqual(len(service.storage.list_outreach_executions(limit=1000)), 2)
            self.assertEqual(len(service.storage.list_outreach_executions(limit=1000, batch_id=old_batch["id"])), 1)
            self.assertEqual(len(service.storage.list_outreach_executions(limit=1000, batch_id=new_batch["id"])), 1)
            workflow = GrowthWorkflowService(service)
            old_snapshot = workflow.build_snapshot(campaign_id=old_plan["campaign"]["id"], batch_id=old_batch["id"])
            new_snapshot = workflow.build_snapshot(campaign_id=new_plan["campaign"]["id"], batch_id=new_batch["id"])
            self.assertEqual(len(old_snapshot.executions), 1)
            self.assertEqual(len(new_snapshot.executions), 1)
            self.assertEqual(old_snapshot.executions[0]["profile_id"], "exec-old")
            self.assertEqual(new_snapshot.executions[0]["profile_id"], "exec-new")
            with open(result["report"]["json_path"], "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertEqual(payload["summary"]["batch_id"], new_batch["id"])
            self.assertEqual(len(payload["executions"]), 1)
            self.assertEqual(payload["executions"][0]["profile_id"], "exec-new")

    def test_standalone_action_preflight_filters_profiles_before_router(self):
        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        class Root:
            def after(self, _delay, callback=None):
                if callback:
                    callback()

        class Console:
            action_execution_workers_var = Value(2)
            action_execution_per_profile_var = Value(3)
            action_execution_hour_limit_var = Value(10)
            action_execution_video_hour_limit_var = Value(1)

            def refresh(self, _snapshot):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            batch = service.storage.latest_collection_batch_for_campaign(plan["campaign"]["id"])
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service
            app.workflow = GrowthWorkflowService(service)
            app.console = Console()
            app.root = Root()
            app.active_batch_id = batch["id"]
            app._current_snapshot = lambda: app.workflow.build_snapshot(campaign_id=plan["campaign"]["id"], batch_id=batch["id"])
            app._current_group_name = lambda: "US"
            logs = []
            app._log = logs.append

            with patch(
                "ReachOps.workbench.profile_preflight.ProfilePreflightChecker.available_profiles",
                return_value=(
                    [{"profile_id": "exec-good", "group_name": "US"}],
                    {
                        "checked": 2,
                        "available": 1,
                        "unavailable": 1,
                        "errors": {"LOGIN_REQUIRED": 1},
                        "results": [],
                    },
                ),
            ), patch(
                "ReachOps.workbench.tiktok_action_executor.TikTokSeleniumActionExecutor",
                return_value=FixtureActionExecutor([{"status": "success", "evidence_path": "evidence://ui/preflight"}]),
            ):
                result = app._start_action_queue_processing(
                    plan["campaign"]["id"],
                    "US",
                    [{"profile_id": "exec-good", "group_name": "US"}, {"profile_id": "exec-bad", "group_name": "US"}],
                )

            self.assertEqual(result["worker_count"], 1)
            self.assertEqual(result["available_profile_count"], 1)
            self.assertEqual(result["success"], 3)
            self.assertEqual({row["profile_id"] for row in result["results"]}, {"exec-good"})
            self.assertTrue(any("CHECK  profile_preflight checked=2 available=1 unavailable=1 errors=LOGIN_REQUIRED=1" in row for row in logs))
            self.assertTrue(any("DONE   action_preflight" in row and "profiles=1" in row for row in logs))

    def test_standalone_collection_uses_visible_selected_profile_group(self):
        class Value:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Console:
            scan_profile_group_display_var = Value("Canada (12)")
            scan_profile_group_var = Value("2024年注册")
            action_execution_group_var = Value("")

        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app.console = Console()
        app.group_var = Value("2024年注册")

        self.assertEqual(app._selected_group_name(), "Canada")
        self.assertEqual(app.console.scan_profile_group_var.get(), "Canada")
        self.assertEqual(app.console.action_execution_group_var.get(), "Canada")
        self.assertEqual(app.group_var.get(), "Canada")

    def test_profile_group_display_keeps_operator_readable_group_name(self):
        display = group_display_name({"group_id": "281726", "group_name": "加拿大获客组", "count": 12})

        self.assertEqual(display, "加拿大获客组 | ID 281726 | 12 个账号")
        self.assertEqual(stable_combobox_values([display]), [display])

    def test_standalone_logs_profile_preflight_details_for_operator(self):
        logs = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append

        app._log_profile_preflight_details(
            {
                "results": [
                    {
                        "profile_id": "ok-1",
                        "ok": True,
                        "error_code": "",
                        "error_message": "profile ready",
                        "evidence_path": "evidence://ok",
                    },
                    {
                        "profile_id": "bad-login",
                        "ok": False,
                        "error_code": "LOGIN_REQUIRED",
                        "error_message": "TikTok login popup/page visible",
                        "evidence_path": "evidence://login",
                    },
                ]
            },
            stage="collection",
        )

        self.assertTrue(any("profile=ok-1" in row and "status=可用" in row for row in logs))
        self.assertTrue(any("profile=bad-login" in row and "error=LOGIN_REQUIRED" in row for row in logs))
        self.assertTrue(any("evidence=evidence://login" in row for row in logs))

    def test_standalone_export_report_uses_current_campaign_only(self):
        class Console:
            def refresh(self, _snapshot):
                return None

        class Service:
            def export_latest_report(self):
                raise AssertionError("global latest report should not be exported from client button")

        class Workflow:
            def __init__(self):
                self.calls = []

            def export_campaign_artifacts(self, campaign_id=""):
                self.calls.append(campaign_id)
                return {
                    "json_path": "/tmp/current.json",
                    "customers_csv_path": "/tmp/customers.csv",
                    "actions_csv_path": "/tmp/actions.csv",
                }

        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app.active_campaign_id = "campaign-1"
        app.service = Service()
        app.workflow = Workflow()
        app.console = Console()
        app._current_snapshot = lambda: None
        logs = []
        app._log = logs.append

        app.export_report()

        self.assertEqual(app.workflow.calls, ["campaign-1"])
        self.assertTrue(any("campaign=campaign-1" in row and "customers=/tmp/customers.csv" in row for row in logs))

    def test_standalone_export_report_blocks_without_current_campaign(self):
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app.active_campaign_id = ""
        logs = []
        app._log = logs.append

        app.export_report()

        self.assertTrue(any("BLOCK  report_export not_started" in row for row in logs))

    def test_standalone_preflight_block_creates_failed_current_batch(self):
        class Value:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("anti aging serum", max_sources=2)
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service
            app.active_batch_id = ""
            app.group_var = Value("Canada")
            planned_sources = [
                {"id": "source-1", "source_type": "keyword", "source_value": "anti aging serum"},
                {"id": "source-2", "source_type": "keyword", "source_value": "anti aging serum review"},
            ]
            blocked = app._create_preflight_blocked_batch(
                campaign_id=plan["campaign"]["id"],
                planned_sources=planned_sources,
                profile_group="Canada",
                profile_preflight={
                    "checked": 2,
                    "available": 0,
                    "unavailable": 2,
                    "errors": {"PROFILE_START_FAILED": 2},
                },
            )

            self.assertEqual(blocked["status"], "failed")
            self.assertEqual(blocked["profile_group"], "Canada")
            self.assertEqual(blocked["total_sources"], 2)
            self.assertEqual(blocked["failed_sources"], 2)
            tasks = [task for task in service.storage.list_collection_tasks(limit=10) if task["batch_id"] == blocked["id"]]
            self.assertEqual(len(tasks), 2)
            self.assertEqual({task["status"] for task in tasks}, {"failed"})
            self.assertEqual({task["error_code"] for task in tasks}, {"NO_LOGGED_IN_PROFILE_AVAILABLE"})

    def test_ixbrowser_profile_loader_continues_after_sparse_empty_page(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def __init__(self):
                self.total = 300

            def get_profile_list(self, page=1, limit=100, group_id=0, **_kwargs):
                pages = {
                    1: [{"profile_id": "p1", "group_id": "g1", "group_name": "BR"}],
                    2: [],
                    3: [{"profile_id": "p3", "group_id": "g2", "group_name": "Canada"}],
                    4: [],
                    5: [],
                    6: [],
                }
                return pages.get(page, [])

            def get_group_list(self, page=1, limit=100):
                return []

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import load_ixbrowser_profile_rows

            rows = load_ixbrowser_profile_rows(max_pages=6)

        self.assertEqual([str(row["profile_id"]) for row in rows], ["p1", "p3"])

    def test_profile_registry_selects_profiles_by_group_id_not_partial_cache(self):
        from ReachOps.workbench.standalone_app import StandaloneProfileRegistry

        registry = StandaloneProfileRegistry()
        registry.profiles = [{"profile_id": "old", "group_id": "old", "group_name": "Old"}]
        registry.groups = [{"group_id": "281726", "group_name": "Canada", "count": 0}]
        registry.group_by_name = {"Canada": registry.groups[0]}

        with patch(
            "ReachOps.workbench.standalone_app.load_ixbrowser_profile_rows",
            return_value=[
                {"profile_id": "ca-1", "group_id": "281726", "group_name": "Canada"},
                {"profile_id": "ca-2", "group_id": "281726", "group_name": "Canada"},
            ],
        ) as loader:
            rows = registry.select_profiles("Canada", limit=10)

        loader.assert_called_once()
        self.assertEqual(loader.call_args.kwargs["group_id"], "281726")
        self.assertEqual([row["profile_id"] for row in rows], ["ca-1", "ca-2"])

    def test_operator_automation_paths_log_instead_of_blocking_popups(self):
        console_source = Path("ReachOps/workbench/console.py").read_text(encoding="utf-8")
        app_source = Path("ReachOps/workbench/standalone_app.py").read_text(encoding="utf-8")

        action_router_body = console_source.split("    def _run_action_router_from_ui(self):", 1)[1].split("\n    def _format_action_router_result", 1)[0]
        plan_dry_run_body = console_source.split("    def _execute_selected_plan_dry_run(self):", 1)[1].split("\n    def _run_action_router_dry_run", 1)[0]
        export_report_body = app_source.split("    def export_report(self):", 1)[1].split("\n    def run_due_scans", 1)[0]

        self.assertNotIn("messagebox.", action_router_body)
        self.assertNotIn("messagebox.", plan_dry_run_body)
        self.assertNotIn("messagebox.", export_report_body)
        self.assertIn("_log_operator_event", action_router_body)
        self.assertIn("_log(", export_report_body)

    def test_standalone_sources_do_not_expose_host_product_boundary(self):
        checked_paths = [
            "README.md",
            "ReachOpsApp.py",
            "ReachOps/README.md",
            "ReachOps/packaging/ReachOps.iss",
            "ReachOps/workbench/console.py",
            "ReachOps/workbench/task_scheduler.py",
            "ReachOps/adapters/browser_manager.py",
            "ReachOps/updater.py",
            "tools/sync_reachops_to_windows_vm.sh",
            "tools/start_growth_ui_windows.bat",
        ]
        forbidden = ["IntelliOps", "DataCollector", "IntelliOps_codex_growth_ui"]
        for path in checked_paths:
            text = Path(path).read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, path)

    def test_comment_noise_filter_rejects_page_chrome_and_ad_rows(self):
        noise_rows = [
            "The Blueprint Self-Paced course lets you go at your speed and build a campaign",
            "CapCut  Editing made easy",
            "#JungKook",
            "121.3K",
            "00:00 / 00:00",
            "CompanyProgramTerms & Policies© 2026 TikTok",
            "HOLIDAY SALE LIVE! Get the number 1 color blind glasses for less. Limited time offer don't miss out!",
            "Join us in celebrating 250 years of history",
            "Follow Reply View replies Like Share Comment For You Profile Search",
        ]
        for text in noise_rows:
            self.assertTrue(is_comment_noise_text(text), text)

        self.assertFalse(is_comment_noise_text("where can I buy this serum link please"))
        self.assertFalse(is_comment_noise_text("qual o link para comprar esse produto?"))
        self.assertFalse(is_comment_noise_text("precio por favor donde compro"))

    def test_tiktok_comment_collector_keeps_only_real_comment_rows(self):
        rows = [
            {
                "username": "ad_user",
                "profile_url": "https://www.tiktok.com/@ad_user",
                "comment_text": "CapCut  Editing made easy",
                "comment_likes": "0",
                "reply_count": "",
            },
            {
                "username": "counter_user",
                "profile_url": "https://www.tiktok.com/@counter_user",
                "comment_text": "121.3K",
                "comment_likes": "0",
                "reply_count": "",
            },
            {
                "username": "buyer_real",
                "profile_url": "https://www.tiktok.com/@buyer_real",
                "comment_text": "where can I buy this serum link please",
                "comment_likes": "12",
                "reply_count": "2 replies",
            },
            {
                "username": "buyer_br",
                "profile_url": "https://www.tiktok.com/@buyer_br",
                "comment_text": "qual o link para comprar esse produto?",
                "comment_likes": "3",
                "reply_count": "ver respostas",
            },
        ]

        comments = TikTokCommentCollector().collect(
            ScriptedCommentDriver(rows),
            {"content": {"video_url": "https://www.tiktok.com/@creator/video/123"}},
            {"limit": 10},
        )

        self.assertEqual([row["username"] for row in comments], ["buyer_real", "buyer_br"])
        self.assertEqual(comments[0]["comment_likes"], 12)
        self.assertEqual(comments[0]["reply_count"], 1)

    def test_injected_comment_normalizer_rejects_noise_before_candidate_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            router = service.router
            normalized = router._normalize_injected_comments(
                [
                    {
                        "username": "noise",
                        "profile_url": "https://www.tiktok.com/@noise",
                        "comment_text": "#JungKook",
                    },
                    {
                        "username": "buyer",
                        "profile_url": "https://www.tiktok.com/@buyer",
                        "comment_text": "where is the price link",
                    },
                ],
                {"content": {"video_url": "https://www.tiktok.com/@creator/video/123"}},
                {},
            )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["username"], "buyer")

    def test_collector_runtime_preserves_primary_empty_diagnostics_through_fallbacks(self):
        rows, evidence = CollectorRuntime().collect_with_fallback(
            FakeDriver(),
            [EmptyDiagnosticCollector(), EmptyFallbackCollector()],
            {"content": {"video_url": "https://www.tiktok.com/@creator/video/123"}},
            {"limit": 10},
            "comment_scan",
            fallback_on_empty=True,
        )

        self.assertEqual(rows, [])
        self.assertEqual(evidence.level, "cdp_network")
        self.assertEqual(evidence.diagnostics["error_code"], "COMMENT_SCAN_EMPTY")
        self.assertEqual(evidence.diagnostics["comment_open_attempts"], 6)
        self.assertFalse(evidence.diagnostics["comment_panel_seen"])

    def test_comment_collector_detects_signup_title_as_login_required(self):
        driver = FakeDriver()
        driver.current_url = "https://www.tiktok.com/signup"
        driver.title = "Sign up | TikTok"
        driver.script_results = [
            {
                "url": driver.current_url,
                "title": "sign up | tiktok",
                "commentNodes": 0,
                "loginPrompt": False,
                "loginPage": True,
                "loginDialog": False,
                "captcha": False,
                "proxy": False,
                "emptyHint": False,
                "containers": 0,
            }
        ]

        diagnostics = TikTokCommentCollector()._inspect_comment_state(driver, {"max_visible_nodes": 0})

        self.assertEqual(diagnostics["error_code"], "LOGIN_REQUIRED")
        self.assertTrue(diagnostics["login_prompt_detected"])


if __name__ == "__main__":
    unittest.main()
